"""FIX-16 (#348): the Drafts sweep of a refused native reply (facts section 4e
`Refusal cleanup`) — the read half. The index and the ``.emlx`` files are fixtures in a
tmp dir; nothing here touches Mail or the real Envelope Index."""

from __future__ import annotations

import pytest

from macos_apps_mcp.adapters import mail_index, mail_reply_cleanup
from macos_apps_mcp.errors import NativeError

# The conftest lock replaces ``drafts_rows``; the self-tests bind the real one here.
_REAL_DRAFTS_ROWS = mail_reply_cleanup.drafts_rows
_ACCT = "11111111-2222-3333-4444-555555555555"
_ORIGINAL = "orig-1@example.com"
_QUOTE_HTML = (
    '<blockquote type="cite">On 1 Jul 2026, at 14:39, Jane wrote:<br>quoted words'
    "</blockquote>"
)


def _emlx(in_reply_to: str, mid: str, html: str) -> bytes:
    raw = (
        f"Message-ID: <{mid}>\r\nIn-Reply-To: <{in_reply_to}>\r\n"
        "Subject: Re: x\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
        f"{html}"
    ).encode()
    return str(len(raw)).encode() + b"\n" + raw + b"\n<plist></plist>"


@pytest.fixture
def mailroot(tmp_path, monkeypatch):
    monkeypatch.setattr(mail_index, "mail_root", lambda: tmp_path)
    box = tmp_path / "V10" / _ACCT / "Drafts.mbox" / "S" / "Data" / "0" / "Messages"
    box.mkdir(parents=True)

    def put(rowid, in_reply_to, mid, html, *, partial=False):
        name = f"{rowid}.partial.emlx" if partial else f"{rowid}.emlx"
        (box / name).write_bytes(_emlx(in_reply_to, mid, html))

    return put


def _rows(monkeypatch, rows):
    monkeypatch.setattr(mail_reply_cleanup, "drafts_rows", lambda: rows)


_URL = f"imap://{_ACCT}/Drafts"


def test_drafts_rows_reads_only_live_drafts_of_every_account(
    blank_envelope, monkeypatch
):
    a = blank_envelope.add_mailbox(f"imap://{_ACCT}/Drafts")
    g = blank_envelope.add_mailbox("imap://gmail-uuid/%5BGmail%5D/Drafts")
    inbox = blank_envelope.add_mailbox(f"imap://{_ACCT}/INBOX")
    keep = blank_envelope.add_message(mailbox=a, deleted=0)
    gm = blank_envelope.add_message(mailbox=g, deleted=0)
    blank_envelope.add_message(mailbox=a, deleted=1)
    blank_envelope.add_message(mailbox=inbox, deleted=0)
    rows = _REAL_DRAFTS_ROWS()
    assert sorted(r for r, _ in rows) == sorted([keep, gm])
    assert {u for _, u in rows} == {
        f"imap://{_ACCT}/Drafts",
        "imap://gmail-uuid/%5BGmail%5D/Drafts",
    }


def test_drafts_baseline_is_none_when_the_index_cannot_be_read(monkeypatch):
    def boom():
        raise NativeError("no Full Disk Access")

    monkeypatch.setattr(mail_reply_cleanup, "drafts_rows", boom)
    assert mail_reply_cleanup.drafts_baseline() is None
    _rows(monkeypatch, [(5, _URL), (9, _URL)])
    assert mail_reply_cleanup.drafts_baseline() == frozenset({5, 9})


def test_find_own_draft_claims_exactly_one_new_reply_with_the_calls_text(
    mailroot, monkeypatch
):
    mailroot(20, _ORIGINAL, "draft-a@example.com", "<div>Hi there</div>" + _QUOTE_HTML)
    _rows(monkeypatch, [(10, _URL), (20, _URL)])
    got = mail_reply_cleanup.find_own_draft(frozenset({10}), _ORIGINAL, "Hi there")
    assert got == mail_reply_cleanup.Draft("one", _URL, "<draft-a@example.com>")


def test_find_own_draft_claims_an_autosave_that_landed_before_the_insert(
    mailroot, monkeypatch
):
    # only Mail's attribution line sits above the quote: no text typed yet
    mailroot(
        20,
        _ORIGINAL,
        "draft-a@example.com",
        "<div>On 1 Jul 2026, at 14:39, Jane wrote:</div>" + _QUOTE_HTML,
    )
    _rows(monkeypatch, [(20, _URL)])
    got = mail_reply_cleanup.find_own_draft(frozenset(), _ORIGINAL, "Hi there")
    assert got.kind == "one"


def test_find_own_draft_never_claims_someone_elses_text(mailroot, monkeypatch):
    # a hand reply to the same original: new, threads to it, but not the call's text
    mailroot(20, _ORIGINAL, "hand@example.com", "<div>Sure, thanks</div>" + _QUOTE_HTML)
    _rows(monkeypatch, [(20, _URL)])
    got = mail_reply_cleanup.find_own_draft(frozenset(), _ORIGINAL, "Hi there")
    assert got.kind == "unproven"
    # hand text then the attribution line is still not the attribution alone
    mailroot(
        21,
        _ORIGINAL,
        "hand2@example.com",
        "<div>Sure On 1 Jul 2026, at 14:39, Jane wrote:</div>" + _QUOTE_HTML,
    )
    _rows(monkeypatch, [(21, _URL)])
    assert (
        mail_reply_cleanup.find_own_draft(frozenset(), _ORIGINAL, "Hi there").kind
        == "unproven"
    )


def test_find_own_draft_with_several_candidates_claims_none(mailroot, monkeypatch):
    mailroot(20, _ORIGINAL, "a@example.com", "<div>Hi there</div>" + _QUOTE_HTML)
    mailroot(21, _ORIGINAL, "b@example.com", "<div>Hi there</div>" + _QUOTE_HTML)
    _rows(monkeypatch, [(20, _URL), (21, _URL)])
    got = mail_reply_cleanup.find_own_draft(frozenset(), _ORIGINAL, "Hi there")
    assert got.kind == "unproven" and got.mid == ""


def test_find_own_draft_ignores_old_rows_and_other_threads(mailroot, monkeypatch):
    mailroot(10, _ORIGINAL, "old@example.com", "<div>Hi there</div>" + _QUOTE_HTML)
    mailroot(20, "other@example.com", "new@example.com", "<div>Hi there</div>")
    _rows(monkeypatch, [(10, _URL), (20, _URL)])
    got = mail_reply_cleanup.find_own_draft(frozenset({10}), _ORIGINAL, "Hi there")
    assert got == mail_reply_cleanup.Draft("none")


def test_find_own_draft_with_an_unreadable_new_row_proves_nothing(
    mailroot, monkeypatch
):
    _rows(monkeypatch, [(20, _URL)])  # no .emlx on disk for row 20
    got = mail_reply_cleanup.find_own_draft(frozenset(), _ORIGINAL, "Hi there")
    assert got.kind == "unproven"


def test_find_own_draft_reads_a_plain_text_draft_up_to_the_first_quote_line(
    tmp_path, mailroot, monkeypatch
):
    box = next(tmp_path.rglob("Messages"))
    raw = (
        f"Message-ID: <p@example.com>\r\nIn-Reply-To: <{_ORIGINAL}>\r\n"
        "Content-Type: text/plain\r\n\r\nHi there\r\n\r\n> quoted words\r\n"
    ).encode()
    (box / "30.partial.emlx").write_bytes(
        str(len(raw)).encode() + b"\n" + raw + b"\n<plist/>"
    )
    _rows(monkeypatch, [(30, _URL)])
    got = mail_reply_cleanup.find_own_draft(frozenset(), _ORIGINAL, "Hi  there")
    assert got.kind == "one" and got.mid == "<p@example.com>"
