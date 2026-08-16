"""Unit tests for the mail attachments module (#178) — list attachments of messages.

Moved verbatim out of ``test_mail.py`` with the #178 split; the tests still drive the
``MailAdapter`` facade (the methods stay on the class — only their bodies moved). The
``save_attachment`` half is pinned in ``test_mail_extras.py`` (#81), where it always
lived.
"""

from __future__ import annotations

import pytest

from macos_apps_mcp import runtime
from macos_apps_mcp.adapters import mail
from macos_apps_mcp.adapters.mail_attachments import _parse_attachments

_GMAIL_UUID = "5936B2CE-D3DC-4072-A81B-E79E6DA94B15"


def _patch_run(monkeypatch, fake):
    """Fake the AppleScript boundary — ONE seam, whatever the module (#176)."""
    monkeypatch.setattr(runtime, "run_osascript", fake)


def test_parse_attachments_groups_by_message():
    us, rs = "\x1f", "\x1e"
    raw = (
        f"<a@x>{us}Logo files{us}LOGO.zip{us}1200000{us}true{us}1.2"
        f"{us}spec.pdf{us}0{us}false{us}1.4{rs}"
        f"{us}No attach subject{rs}"
    )
    out = _parse_attachments(raw)
    assert out[0]["summary"] == "Logo files"
    # #81: each attachment carries its own id (a MIME part path) — the NAME is not
    # unique on a real message, so the id is what save_mail_attachment addresses.
    assert out[0]["attachments"] == [
        {"name": "LOGO.zip", "size": 1200000, "downloaded": True, "id": "1.2"},
        {"name": "spec.pdf", "size": 0, "downloaded": False, "id": "1.4"},
    ]
    assert out[1]["summary"] == "No attach subject"
    assert out[1]["attachments"] == []
    # #155: the row is addressable — id + deeplink — and an unsaved draft (blank id) is
    # still listed rather than dropped, but gets NO deeplink to a message that has none.
    assert out[0]["id"] == "<a@x>"
    assert out[0]["deeplink"] == "message://%3Ca@x%3E"
    assert out[1]["id"] == ""
    assert "deeplink" not in out[1]


def test_list_attachments_resolves_mailbox_and_caps(monkeypatch):
    captured = {}

    def fake(script, *args):
        captured["script"] = script
        captured["args"] = args
        # more records than MAX_MAILS — the cap must actually bite
        records = "".join(
            f"<m{i}@x>\x1fLogo files {i}\x1fLOGO.zip\x1f100\x1ftrue\x1e"
            for i in range(mail.MAX_MAILS + 5)
        )
        return records

    _patch_run(monkeypatch, fake)
    out = mail.MailAdapter().list_attachments("drafts", "Logo")
    # query, cap, the (account, path) mailbox pair and the (empty) message-id travel via
    # argv — no localized candidates (the unified `drafts mailbox` accessor is
    # locale-independent), and an empty account id is what selects that unified branch
    # in the shared resolver
    assert captured["args"] == ("Logo", str(mail.MAX_MAILS), "", "drafts", "")
    assert len(out["results"]) == mail.MAX_MAILS
    # #156: at the cap and NOT complete — the caller must be able to tell.
    assert out["truncated"] is True


def test_list_attachments_empty_query_lists_all(monkeypatch):
    def fake(script, *args):
        return (
            "<1@x>\x1fFirst\x1fa.pdf\x1f10\x1ftrue\x1e"
            "<2@x>\x1fSecond\x1fb.pdf\x1f20\x1ffalse\x1e"
            "<3@x>\x1fThird\x1e"
        )

    _patch_run(monkeypatch, fake)
    out = mail.MailAdapter().list_attachments("inbox")
    assert [r["summary"] for r in out["results"]] == ["First", "Second", "Third"]
    # #155: the mailbox the caller passed is echoed back, so each row round-trips on its
    # own into mail_body / a future save-attachment tool.
    assert {r["folder"] for r in out["results"]} == {"inbox"}
    # under the cap: no truncation claim either way
    assert "truncated" not in out


def test_list_attachments_unknown_mailbox_raises():
    with pytest.raises(ValueError, match="unknown mailbox"):
        mail.MailAdapter().list_attachments("nope", "x")


def test_list_attachments_reaches_a_user_folder(monkeypatch):
    # #45 gave mail_attachments a mailbox, but only the five special ones — a user
    # folder was unreachable there too.
    seen = {}

    def fake(script, *args):
        seen["args"] = args
        return "<c@x>\x1fContract\x1fdeal.pdf\x1f100\x1ftrue\x1f1.2\x1e"

    _patch_run(monkeypatch, fake)
    out = mail.MailAdapter().list_attachments(f"imap://{_GMAIL_UUID}/Backup")
    assert out["results"][0]["attachments"][0]["name"] == "deal.pdf"
    assert seen["args"] == ("", str(mail.MAX_MAILS), _GMAIL_UUID, "Backup", "")
