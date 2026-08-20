"""On-device Mail outbound tests (#82/#83) — NEVER run in CI.

Every send here targets SELF_ADDRESS, the operator's own address. No test in this
file may ever address a third party: a failed assertion is recoverable, a
mis-sent mail is not.

Run with:  MACOS_APPS_ALLOW_SEND=mail uv run pytest -m integration -k outbound
"""

from __future__ import annotations

import os
import time

import pytest

from macos_apps_mcp.adapters import mail_outgoing  # #160: the send plane lives here
from macos_apps_mcp.adapters.mail import MailAdapter

pytestmark = pytest.mark.integration

SELF_ADDRESS = "andrei@lav.ren"
MARKER = "macos-apps-mcp integration"


def test_list_drafts_returns_pointers():
    out = MailAdapter().list_drafts()
    assert isinstance(out["results"], list)
    for p in out["results"]:
        assert p["id"] and p["deeplink"].startswith("message://")
        assert p["folder"] == "drafts"  # #155: the round-trip token, on every read


def test_dry_run_send_leaves_no_draft_behind():
    # The regression this guards: constructing an outgoing message can strand an
    # autosaved copy in Drafts. A dry run must construct nothing.
    before = {p["id"] for p in MailAdapter().list_drafts()["results"]}
    out = MailAdapter().send(SELF_ADDRESS, f"{MARKER} dry", "body")
    assert out["dry_run"] is True
    assert {p["id"] for p in MailAdapter().list_drafts()["results"]} == before


@pytest.mark.skipif(
    os.environ.get("MACOS_APPS_ALLOW_SEND") is None,
    reason="set MACOS_APPS_ALLOW_SEND=mail to run the real-send test",
)
def test_send_to_self_and_delete_draft_round_trip():
    adapter = MailAdapter()
    subject = f"{MARKER} send"
    out = adapter.send(SELF_ADDRESS, subject, "integration body", dry_run=False)
    assert out["sent"] is True
    assert out["to"] == [SELF_ADDRESS]
    assert out["cc"] == []
    assert out["bcc"] == []
    assert out["from"] == "(Mail default account)"
    assert out["subject"] == subject
    assert isinstance(out["outbox_pending"], int)  # #134: the outbox truth-check ran

    # The regression this guards (#134, device-verified 2026-07-25): a well-formed
    # send (correct subject/recipient/sender) was ACCEPTED by AppleScript's `send`
    # verb, this adapter returned `sent: True`, and the message then sat in Mail's
    # Outbox undelivered for minutes — asserting only the returned dict shape (as
    # this test used to) cannot catch that; it also cannot catch a `forward` that
    # silently delivered an empty message, which is exactly what happened here. Prove
    # the message genuinely LEFT this machine by polling the real outbox count until
    # it drains to 0 — a bounded poll loop, not a blind sleep for the full duration.
    deadline = time.monotonic() + 30
    pending = out["outbox_pending"]
    while pending > 0 and time.monotonic() < deadline:
        time.sleep(1)
        pending = mail_outgoing._outbox_pending()
    assert pending == 0, (
        f"message still queued in Mail's Outbox after 30s ({pending} pending) — "
        "`send` returning does not mean the message was delivered"
    )

    # What the send leaves in Drafts is NOT an assertion this test may make. Mail
    # autosaves any outgoing message ~10-15s after creation, asynchronously and
    # unsuppressably (#133, facts.md §3), and 0.9.4 measured it as INTERMITTENT — of
    # four real sends in one session only one littered (§3c). So "a real send must not
    # leave a draft behind" was a coin flip dressed as an invariant: it passed whenever
    # the autosave happened not to fire, or whenever this line beat the window, which is
    # the exact timing trap §2 exists to warn about.
    #
    # The real contract, and what the tool docstrings promise, is that whatever lands is
    # SWEEPABLE. Assert that instead — and leave the mailbox clean either way.
    leftovers = [p for p in adapter.list_drafts()["results"] if subject in p["summary"]]
    for p in leftovers:
        assert adapter.delete_draft(p["id"])["deleted"]
    assert not [p for p in adapter.list_drafts()["results"] if subject in p["summary"]]


# --- #135: the rollback tells the truth, and outbox_pending measures the real queue ---


def test_rollback_verifies_a_real_delete():
    """The rollback handler run against live Mail: it deletes a freshly built outgoing
    message and PROVES it, returning true. The old code called a bare `delete` and
    assumed the outcome."""
    from macos_apps_mcp.runtime import run_osascript

    probe = (
        mail_outgoing.ROLLBACK
        + """

on run argv
  tell application "Mail"
    set m to make new outgoing message with properties {visible:false}
  end tell
  set verdict to my rollback(m)
  tell application "Mail"
    return (verdict as text) & " " & ((count of outgoing messages) as text)
  end tell
end run"""
    )
    verdict, _count = run_osascript(probe).strip().split()
    assert verdict == "true"  # the delete was verified, not assumed


def test_outbox_pending_tracks_the_real_queue_not_session_objects():
    """A real send to self must move outbox_pending 0 -> non-zero -> 0. The counter this
    shipped with (`count of outgoing messages`) counts script-session objects including
    already-delivered ones, so it would read non-zero here forever and never drain."""
    assert mail_outgoing._outbox_pending() == 0, "start from a clean outbox"
    out = MailAdapter().send(
        SELF_ADDRESS, f"{MARKER} outbox drain", "drain probe", dry_run=False
    )
    assert out["sent"] is True
    drained = False
    for _ in range(20):  # bounded: never leave a loop pointed at Mail
        if mail_outgoing._outbox_pending() == 0:
            drained = True
            break
        time.sleep(6)
    assert drained, "the outbox never drained — delivery is genuinely stuck"

    # Sweep this test's own #133 autosave litter, for the same reason the round-trip
    # test does: an integration suite that leaves drafts in the operator's real mailbox
    # is one this repo stops running. Best-effort — the sweep is not what is under test.
    adapter = MailAdapter()
    for p in adapter.list_drafts()["results"]:
        if f"{MARKER} outbox drain" in (p.get("subject") or ""):
            adapter.delete_draft(p["id"])
