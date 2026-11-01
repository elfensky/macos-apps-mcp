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
    monkeypatch.setattr(mail_reply_cleanup, "drafts_rows", lambda account: rows)


_URL = f"imap://{_ACCT}/Drafts"


def test_drafts_rows_reads_only_the_live_rows_of_the_accounts_own_drafts(
    blank_envelope,
):
    # a family account's Drafts, a nested user folder named Drafts and a deleted row
    # all sit in the same index; none of them is the reply account's Drafts
    a = blank_envelope.add_mailbox(f"imap://{_ACCT}/Drafts")
    nested = blank_envelope.add_mailbox(f"imap://{_ACCT}/Projects/Drafts")
    other = blank_envelope.add_mailbox("imap://9999-family/Drafts")
    inbox = blank_envelope.add_mailbox(f"imap://{_ACCT}/INBOX")
    keep = blank_envelope.add_message(mailbox=a, deleted=0)
    blank_envelope.add_message(mailbox=a, deleted=1)
    blank_envelope.add_message(mailbox=nested, deleted=0)
    blank_envelope.add_message(mailbox=other, deleted=0)
    blank_envelope.add_message(mailbox=inbox, deleted=0)
    assert _REAL_DRAFTS_ROWS(_ACCT) == [(keep, f"imap://{_ACCT}/Drafts")]


def test_drafts_rows_takes_gmails_drafts_under_its_bracket_folder(blank_envelope):
    g = blank_envelope.add_mailbox("imap://gmail-uuid/%5BGmail%5D/Drafts")
    gm = blank_envelope.add_message(mailbox=g, deleted=0)
    assert _REAL_DRAFTS_ROWS("gmail-uuid") == [
        (gm, "imap://gmail-uuid/%5BGmail%5D/Drafts")
    ]


@pytest.mark.parametrize("leaf", ["Concepten", "Brouillons", "Entw%C3%BCrfe"])
def test_drafts_rows_refuses_when_the_accounts_drafts_has_another_name(
    blank_envelope, leaf
):
    # a localized Drafts is not recognised: that must be loud (unavailable), never an
    # empty list that reads as "no copy"
    box = blank_envelope.add_mailbox(f"imap://{_ACCT}/{leaf}")
    blank_envelope.add_message(mailbox=box, deleted=0)
    with pytest.raises(NativeError, match="Drafts"):
        _REAL_DRAFTS_ROWS(_ACCT)


@pytest.mark.parametrize("account", ["", "local"])
def test_drafts_rows_refuses_an_unknown_account(blank_envelope, account):
    blank_envelope.add_mailbox(f"imap://{_ACCT}/Drafts")
    with pytest.raises(NativeError):
        _REAL_DRAFTS_ROWS(account)  # an alias such as `inbox` names no account


def test_drafts_baseline_is_none_when_the_index_cannot_be_read(monkeypatch):
    def boom(account):
        raise NativeError("no Full Disk Access")

    monkeypatch.setattr(mail_reply_cleanup, "drafts_rows", boom)
    assert mail_reply_cleanup.drafts_baseline(_ACCT) is None
    _rows(monkeypatch, [(5, _URL), (9, _URL)])
    assert mail_reply_cleanup.drafts_baseline(_ACCT) == frozenset({5, 9})


def test_find_own_draft_claims_exactly_one_new_reply_with_the_calls_text(
    mailroot, monkeypatch
):
    mailroot(20, _ORIGINAL, "draft-a@example.com", "<div>Hi there</div>" + _QUOTE_HTML)
    _rows(monkeypatch, [(10, _URL), (20, _URL)])
    got = mail_reply_cleanup.find_own_draft(
        _ACCT, frozenset({10}), _ORIGINAL, "Hi there"
    )
    assert got == mail_reply_cleanup.Draft("one", _URL, "<draft-a@example.com>")


_ATTRIBUTION = "On 1 Jul 2026, at 14:39, Jane wrote:"


def _kind(mailroot, monkeypatch, html: str, own: str = "Hi there") -> str:
    mailroot(20, _ORIGINAL, "draft-x@example.com", html + _QUOTE_HTML)
    _rows(monkeypatch, [(20, _URL)])
    return mail_reply_cleanup.find_own_draft(_ACCT, frozenset(), _ORIGINAL, own).kind


@pytest.mark.parametrize(
    "html",
    [
        "",  # no text at all: could be any hand reply that was opened and saved
        f"<div>{_ATTRIBUTION}</div>",  # only Mail's attribution line
        f"<div>On it, thanks! {_ATTRIBUTION}</div>",  # typed text, then the attribution
        "<div>On my way, see you at five.</div>",  # a hand reply that starts with "On "
        "<div>Sure, thanks</div>",  # a hand reply
        "<div>Sure On 1 Jul 2026, at 14:39, Jane wrote:</div>",
        "<div>Hi</div>",  # a PREFIX of the call's text is not the call's text
    ],
)
def test_find_own_draft_deletes_nothing_it_cannot_prove_is_the_calls_own(
    mailroot, monkeypatch, html
):
    # the owner rule: refuse and leave nothing, never touch what is not ours. A copy
    # that does not start with the call's full text is reported, never claimed.
    assert _kind(mailroot, monkeypatch, html) == "unproven"


def test_find_own_draft_claims_a_copy_that_starts_with_the_calls_full_text(
    mailroot, monkeypatch
):
    assert _kind(mailroot, monkeypatch, "<div>Hi there</div>") == "one"
    assert _kind(mailroot, monkeypatch, "<div>Hi  there, Jane</div>") == "one"


def test_find_own_draft_never_claims_with_an_empty_own_text(mailroot, monkeypatch):
    # every text starts with the empty string; an empty call text proves nothing
    assert _kind(mailroot, monkeypatch, "<div>anything</div>", own="  ") == "unproven"


def test_find_own_draft_gives_a_plain_text_hand_reply_that_starts_with_on_no_claim(
    tmp_path, mailroot, monkeypatch
):
    box = next(tmp_path.rglob("Messages"))
    raw = (
        f"Message-ID: <p@example.com>\r\nIn-Reply-To: <{_ORIGINAL}>\r\n"
        "Content-Type: text/plain\r\n\r\nOn my way, see you at five.\r\n\r\n"
        f"{_ATTRIBUTION}\r\n> quoted\r\n"
    ).encode()
    (box / "31.emlx").write_bytes(str(len(raw)).encode() + b"\n" + raw + b"\n<plist/>")
    _rows(monkeypatch, [(31, _URL)])
    got = mail_reply_cleanup.find_own_draft(_ACCT, frozenset(), _ORIGINAL, "Hi there")
    assert got.kind == "unproven"


def test_find_own_draft_with_several_candidates_claims_none(mailroot, monkeypatch):
    mailroot(20, _ORIGINAL, "a@example.com", "<div>Hi there</div>" + _QUOTE_HTML)
    mailroot(21, _ORIGINAL, "b@example.com", "<div>Hi there</div>" + _QUOTE_HTML)
    _rows(monkeypatch, [(20, _URL), (21, _URL)])
    got = mail_reply_cleanup.find_own_draft(_ACCT, frozenset(), _ORIGINAL, "Hi there")
    assert got.kind == "unproven" and got.mid == ""


def test_find_own_draft_ignores_old_rows_and_other_threads(mailroot, monkeypatch):
    mailroot(10, _ORIGINAL, "old@example.com", "<div>Hi there</div>" + _QUOTE_HTML)
    mailroot(20, "other@example.com", "new@example.com", "<div>Hi there</div>")
    _rows(monkeypatch, [(10, _URL), (20, _URL)])
    got = mail_reply_cleanup.find_own_draft(
        _ACCT, frozenset({10}), _ORIGINAL, "Hi there"
    )
    assert got == mail_reply_cleanup.Draft("none")


def test_find_own_draft_with_an_unreadable_new_row_proves_nothing(
    mailroot, monkeypatch
):
    _rows(monkeypatch, [(20, _URL)])  # no .emlx on disk for row 20
    got = mail_reply_cleanup.find_own_draft(_ACCT, frozenset(), _ORIGINAL, "Hi there")
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
    got = mail_reply_cleanup.find_own_draft(_ACCT, frozenset(), _ORIGINAL, "Hi  there")
    assert got.kind == "one" and got.mid == "<p@example.com>"
