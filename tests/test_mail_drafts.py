"""Unit tests for the mail drafts module (#178) — create/list/resolve/delete drafts.

Moved verbatim out of ``test_mail.py`` with the #178 split; the tests still drive the
``MailAdapter`` facade (the methods stay on the class — only their bodies moved), and
pin the script constants where they now live, ``mail_drafts``.
"""

from __future__ import annotations

import os
import re

import pytest

from macos_apps_mcp import runtime
from macos_apps_mcp.adapters import mail, mail_drafts
from macos_apps_mcp.adapters.mail_drafts import _CREATE_DRAFT
from macos_apps_mcp.text import RS, US


def _patch_run(monkeypatch, fake):
    """Fake the AppleScript boundary — ONE seam, whatever the module (#176)."""
    monkeypatch.setattr(runtime, "run_osascript", fake)


# --- create_draft (#62/#43/#44) -------------------------------------------------------


def test_create_draft_never_sends():
    # the SAFETY invariant: the draft script has NO `send` verb anywhere — it can only
    # create-and-open, never send (joshrutkowski's two-tier gate; the #62 acceptance).
    # Anchored on the VERB, not the substring: the shared #135 rollback preamble prose
    # contains the word "sends", and a bare substring check would fail on that while
    # still not proving anything about the verb.
    assert not re.search(r"^\s*send \w+\s*$", _CREATE_DRAFT, re.M)
    assert "make new outgoing message" in _CREATE_DRAFT
    assert "visible:true" in _CREATE_DRAFT  # opens for human review


def test_create_draft_passes_body_via_tempfile(monkeypatch, tmp_path):
    # body must be READ from a tempfile as «class utf8», never interpolated into the
    # script; to/subject/path go via argv. Assert the body reaches a real file and the
    # path is argv[3].
    captured = {}

    def fake(script, *args):
        captured["script"] = script
        captured["args"] = args
        # the tempfile must exist and hold the body at call time (script reads it)
        with open(args[2], encoding="utf-8") as f:
            captured["body_on_disk"] = f.read()
        return ""

    monkeypatch.setattr("macos_apps_mcp.runtime.run_osascript", fake)
    mail.MailAdapter().create_draft("bob@x.com", "Hi", "multi\nline © body")
    assert captured["script"] is _CREATE_DRAFT
    assert captured["args"][0] == "bob@x.com" and captured["args"][1] == "Hi"
    assert captured["body_on_disk"] == "multi\nline © body"  # never interpolated
    assert "«class utf8»" in _CREATE_DRAFT  # read as utf8, not string-built


def test_create_draft_cleans_up_tempfile(monkeypatch):
    # the tempfile is deleted after the (synchronous) script read it.
    paths = []
    monkeypatch.setattr(
        "macos_apps_mcp.runtime.run_osascript",
        lambda script, *a: paths.append(a[2]) or "",
    )
    mail.MailAdapter().create_draft("bob@x.com", "Hi", "body")
    assert paths and not os.path.exists(paths[0])  # cleaned up


def test_create_draft_empty_recipient_raises():
    with pytest.raises(ValueError, match="recipient"):
        mail.MailAdapter().create_draft("  ", "Hi", "body")


def test_create_draft_returns_locator_dict(monkeypatch):
    # #43: a freshly opened compose window has no stable Message-ID YET, so
    # create_draft returns a locator (where to find it) instead of a fabricated id.
    # #82/F4 review: once saved to Drafts it DOES get one (drafts()/delete_draft()
    # resolve by it) — the note must point at that recovery path, not claim drafts
    # are permanently unaddressable.
    monkeypatch.setattr("macos_apps_mcp.runtime.run_osascript", lambda *a: "")
    out = mail.MailAdapter().create_draft("x@example.com", "Hi", "body")
    assert out["created"] is True
    assert out["mailbox"] == "Drafts"
    assert out["subject"] == "Hi"
    assert "drafts()" in out["note"]


def test_create_draft_reads_body_through_shared_handler():
    # Bug 1 (device-verified): a bare `read (POSIX file …) as «class utf8»` raises -39
    # ("End of file error") on a ZERO-BYTE file — an empty create_draft body crashed
    # since 0.8.0. The script must compose the shared readBody handler instead of
    # reading directly.
    assert "on readBody(p)" in _CREATE_DRAFT
    assert "my readBody(item 3 of argv)" in _CREATE_DRAFT
    # "read (POSIX file" legitimately appears ONCE, inside the readBody handler itself
    # — the `on run` body must never call it bare (a second, direct occurrence).
    assert _CREATE_DRAFT.count("read (POSIX file") == 1


def test_create_draft_cleanup_on_failure_is_in_script():
    # #44: atomicity is enforced INSIDE the osascript — the partial outgoing message is
    # deleted in the error path. Assert the STRUCTURE (the rollback between `on error`
    # and the re-raise), not just the words: a substring check would pass even if the
    # block were gutted and a stray "delete"/"on error" comment left behind (#43/#44
    # review). Since #135 the delete goes through the VERIFYING rollback handler, so the
    # structure is `on error` -> rollback -> re-raise either way.
    assert re.search(
        r"on error errMsg\s+if my rollback\(msg\) then\s+error errMsg", _CREATE_DRAFT
    ), "the on-error handler must roll back the partial draft, then re-raise"


def test_create_draft_propagates_error_and_cleans_tempfile(monkeypatch):
    # #44 Python-side contract: if osascript surfaces the propagated error, create_draft
    # re-raises AND does not leak the body tempfile (the finally unlinks it) — so a
    # failed create leaves nothing behind on either side.
    seen = {}

    def boom(script, *args):
        seen["path"] = args[2]  # argv: to, subject, tempfile-path
        raise RuntimeError("osascript failed")

    monkeypatch.setattr("macos_apps_mcp.runtime.run_osascript", boom)
    with pytest.raises(RuntimeError, match="osascript failed"):
        mail.MailAdapter().create_draft("x@example.com", "Hi", "body")
    assert not os.path.exists(seen["path"])  # tempfile cleaned up despite the error


# --- drafts (#82) ---------------------------------------------------------------


def test_list_drafts_parses_framed_records(monkeypatch):
    raw = (
        f"<a@b.com>{US}Q3 numbers{US}boss@corp.com{RS}"
        f"<c@d.com>{US}Lunch?{US}pal@example.org{RS}"
    )
    _patch_run(monkeypatch, lambda *a: raw)
    out = mail.MailAdapter().list_drafts()["results"]
    assert [p["id"] for p in out] == ["<a@b.com>", "<c@d.com>"]
    assert out[0]["summary"] == "Q3 numbers — to boss@corp.com"
    assert out[0]["deeplink"].startswith("message://")


def test_list_drafts_skips_records_without_message_id(monkeypatch):
    # a draft with no Message-ID has no stable citation — never emit a garbage id.
    raw = f"missing value{US}No id{US}x@y.com{RS}<ok@z>{US}Fine{US}a@b.com{RS}"
    _patch_run(monkeypatch, lambda *a: raw)
    assert [p["id"] for p in mail.MailAdapter().list_drafts()["results"]] == ["<ok@z>"]


def test_list_drafts_empty_mailbox(monkeypatch):
    _patch_run(monkeypatch, lambda *a: "")
    assert mail.MailAdapter().list_drafts() == {"results": []}


def test_list_drafts_summary_without_recipient(monkeypatch):
    raw = f"<a@b>{US}Just a subject{US}{RS}"
    _patch_run(monkeypatch, lambda *a: raw)
    out = mail.MailAdapter().list_drafts()["results"]
    assert out[0]["summary"] == "Just a subject"


def test_snapshot_returns_pointer_for_known_draft(monkeypatch):
    raw = f"<a@b>{US}Q3 numbers{US}boss@corp.com{RS}"
    _patch_run(monkeypatch, lambda *a: raw)
    p = mail.MailAdapter().snapshot("<a@b>")
    assert p.summary == "Q3 numbers — to boss@corp.com"


def test_snapshot_returns_none_for_unknown_id(monkeypatch):
    _patch_run(monkeypatch, lambda *a: "")
    assert mail.MailAdapter().snapshot("<nope@nowhere>") is None


def test_delete_draft_dry_run_makes_no_native_call(monkeypatch):
    raw = f"<a@b>{US}Q3 numbers{US}boss@corp.com{RS}"
    calls = []

    def fake(script, *argv):
        calls.append(script)
        return raw

    _patch_run(monkeypatch, fake)
    out = mail.MailAdapter().delete_draft("<a@b>", dry_run=True)
    assert out["dry_run"] is True
    assert out["would_delete"]["id"] == "<a@b>"
    # exactly one call — the snapshot read. Never the delete script.
    assert calls == [mail_drafts._DRAFTS]


def test_delete_draft_dry_run_unknown_id_raises(monkeypatch):
    _patch_run(monkeypatch, lambda *a: "")
    with pytest.raises(ValueError, match="no draft"):
        mail.MailAdapter().delete_draft("<nope@nowhere>", dry_run=True)


def test_delete_draft_deletes_by_message_id(monkeypatch):
    seen = {}

    def fake(script, *argv):
        seen[script] = argv
        return (
            f"<a@b>{US}Q3{US}x@y.com{RS}"
            if script is mail_drafts._DRAFTS
            else "deleted"
        )

    _patch_run(monkeypatch, fake)
    out = mail.MailAdapter().delete_draft("a@b")
    assert out == {"deleted": "a@b"}  # C5d: the ONE deletion envelope
    assert seen[mail_drafts._DELETE_DRAFT] == ("a@b",)


def test_delete_draft_rejects_empty_id():
    with pytest.raises(ValueError, match="draft id"):
        mail.MailAdapter().delete_draft("   ")


# --- M1 review: delete_draft accepts a bracketed id like every other id-taking method -


def test_delete_draft_accepts_bracketed_id(monkeypatch):
    # a caller passing "<id>" (the RFC822-looking form, matching what get_body/reply/
    # reply_all/forward all accept) must resolve — not fail loudly. Brackets are
    # stripped before the id reaches the AppleScript argv.
    seen = {}

    def fake(script, *argv):
        seen[script] = argv
        return (
            f"<a@b>{US}Q3{US}x@y.com{RS}"
            if script is mail_drafts._DRAFTS
            else "deleted"
        )

    _patch_run(monkeypatch, fake)
    out = mail.MailAdapter().delete_draft("<a@b>")
    assert out == {"deleted": "a@b"}  # C5d envelope; id bare like the wire
    assert seen[mail_drafts._DELETE_DRAFT] == ("a@b",)  # bare on the wire, not "<a@b>"


def test_delete_draft_dry_run_resolves_bracketed_id_against_bare_snapshot(monkeypatch):
    # snapshot() must match regardless of whether the caller's id or the stored
    # Pointer.id is bracketed (M1 review) — the dry-run path depends on this.
    raw = f"a@b{US}Q3 numbers{US}boss@corp.com{RS}"  # stored id is BARE
    _patch_run(monkeypatch, lambda *a: raw)
    out = mail.MailAdapter().delete_draft("<a@b>", dry_run=True)  # caller id bracketed
    assert out["dry_run"] is True
    assert out["would_delete"]["id"] == "a@b"
