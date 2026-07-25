"""On-device Mail outbound tests (#82/#83) — NEVER run in CI.

Every send here targets SELF_ADDRESS, the operator's own address. No test in this
file may ever address a third party: a failed assertion is recoverable, a
mis-sent mail is not.

Run with:  MACOS_APPS_ALLOW_SEND=mail uv run pytest -m integration -k outbound
"""

from __future__ import annotations

import os

import pytest

from macos_apps_mcp.adapters.mail import MailAdapter

pytestmark = pytest.mark.integration

SELF_ADDRESS = "andrei@lav.ren"
MARKER = "macos-apps-mcp integration"


def test_list_drafts_returns_pointers():
    out = MailAdapter().list_drafts()
    assert isinstance(out, list)
    for p in out:
        assert p.id and p.deeplink.startswith("message://")


def test_dry_run_send_leaves_no_draft_behind():
    # The regression this guards: constructing an outgoing message can strand an
    # autosaved copy in Drafts. A dry run must construct nothing.
    before = {p.id for p in MailAdapter().list_drafts()}
    out = MailAdapter().send(SELF_ADDRESS, f"{MARKER} dry", "body")
    assert out["dry_run"] is True
    assert {p.id for p in MailAdapter().list_drafts()} == before


@pytest.mark.skipif(
    os.environ.get("MACOS_APPS_ALLOW_SEND") is None,
    reason="set MACOS_APPS_ALLOW_SEND=mail to run the real-send test",
)
def test_send_to_self_and_delete_draft_round_trip():
    adapter = MailAdapter()
    subject = f"{MARKER} send"
    out = adapter.send(SELF_ADDRESS, subject, "integration body", dry_run=False)
    assert out == {
        "sent": True,
        "to": [SELF_ADDRESS],
        "cc": [],
        "bcc": [],
        "from": "(Mail default account)",
        "subject": subject,
    }
    # a real send must not leave a draft behind either
    assert not [p for p in adapter.list_drafts() if subject in p.summary]
