"""FIX-16 (#348): the Drafts sweep of a refused native reply (facts section 4e
`Refusal cleanup`) — the read half. The index and the ``.emlx`` files are fixtures in a
tmp dir; nothing here touches Mail or the real Envelope Index."""

from __future__ import annotations

import builtins
import email
import email.message
import email.parser
import email.policy
import html
import io
import itertools
import random
import re
import shutil
import sqlite3
import time
from pathlib import Path
from urllib.parse import quote, unquote

import pytest

from macos_apps_mcp.adapters import mail_index, mail_reply_cleanup
from macos_apps_mcp.errors import NativeError
from macos_apps_mcp.text import long_combining_run, squash_text
from tests import mailhtml

# The conftest lock replaces ``_read``; the self-tests bind the real one here.
_REAL_READ = mail_reply_cleanup._read
_ACCT = "11111111-2222-3333-4444-555555555555"
_OTHER = "99999999-8888-7777-6666-555555555555"
_ORIGINAL = "orig-1@example.com"
_ATTRIBUTION = "On 1 Jul 2026, at 14:39, Jane wrote:"
_QUOTE_HTML = f'<blockquote type="cite">{_ATTRIBUTION}<br>quoted words</blockquote>'
_TAIL = "quoted words"  # the last words of the original, as the flow reads them
# what the flow passes besides the text: the original's tail, and the index top right
# after the discard (above every row these tests store)
_KW = {"tail": _TAIL, "landed_by": 10**6}
_URL = f"imap://{_ACCT}/Drafts"


def _emlx(
    in_reply_to: str,
    mid: str,
    body: str,
    kind: str = "html",
    received: bool = False,
) -> bytes:
    """``received``: the two ``Received`` lines a mail server adds to a delivered
    message (a draft and a Sent copy carry none)."""
    postmark = (
        "Received: from mx2.example.net by mx1.example.net; "
        "Wed, 18 Nov 2026 10:00:00 +0000\r\n"
        "Received: from mx3.example.net by mx2.example.net; "
        "Wed, 18 Nov 2026 09:59:59 +0000\r\n"
        if received
        else ""
    )
    raw = (
        f"{postmark}Message-ID: <{mid}>\r\nIn-Reply-To: <{in_reply_to}>\r\n"
        f"Subject: Re: x\r\nContent-Type: text/{kind}; charset=utf-8\r\n\r\n"
        f"{body}"
    ).encode()
    return str(len(raw)).encode() + b"\n" + raw + b"\n<plist></plist>"


@pytest.fixture
def mailroot(tmp_path, monkeypatch):
    """``put(rowid, in_reply_to, mid, body)`` stores one message where Mail does:
    ``<V10>/<account>/<one .mbox folder per segment>/<guid>/Data/<shard>/Messages``,
    beside the ``V10/MailData/Envelope Index`` the sweep reads."""
    monkeypatch.setattr(
        mail_index,
        "envelope_index_path",
        lambda: tmp_path / "V10" / "MailData" / "Envelope Index",
    )

    def put(
        rowid,
        in_reply_to,
        mid,
        body,
        *,
        url=_URL,
        kind="html",
        partial=False,
        received=False,
    ):
        account, _, path = url.partition("://")[2].partition("/")
        folder = tmp_path / "V10" / account
        for segment in unquote(path).split("/"):
            folder = folder / f"{segment}.mbox"
        shard = "/".join(reversed(str(rowid // 1000))) if rowid >= 1000 else ""
        box = folder / "GUID" / "Data" / shard / "Messages"
        box.mkdir(parents=True, exist_ok=True)
        name = f"{rowid}.partial.emlx" if partial else f"{rowid}.emlx"
        (box / name).write_bytes(_emlx(in_reply_to, mid, body, kind, received))
        return box / name

    return put


@pytest.fixture
def index(blank_envelope, monkeypatch):
    """The real index reads over a schema-only Envelope Index."""
    monkeypatch.setattr(mail_reply_cleanup, "_read", _REAL_READ)
    return blank_envelope


def _rows(monkeypatch, rows):
    """The new rows the sweep sees, without an index."""
    monkeypatch.setattr(mail_reply_cleanup, "new_rows", lambda top: rows)


# --- the baseline and the new rows -------------------------------------------


def test_index_top_is_the_highest_message_row(index):
    assert mail_reply_cleanup.index_top() == 0  # an empty index is still readable
    box = index.add_mailbox(f"imap://{_ACCT}/INBOX")
    index.add_message(mailbox=box)
    top = index.add_message(mailbox=box, deleted=1)  # a deleted row still sets the top
    assert mail_reply_cleanup.index_top() == top


def test_index_top_is_none_when_the_index_cannot_be_read():
    # the conftest lock stands in for an unreadable index (no Full Disk Access)
    assert mail_reply_cleanup.index_top() is None


def test_new_rows_reads_every_live_row_above_the_top_in_any_mailbox(index):
    # the copy lands in the Drafts of the account the reply is SENT from: no account,
    # no mailbox name is assumed
    mine = index.add_mailbox(f"imap://{_ACCT}/INBOX")
    other = index.add_mailbox(f"imap://{_OTHER}/Concepten")
    old = index.add_message(mailbox=mine)
    a = index.add_message(mailbox=mine)
    b = index.add_message(mailbox=other)
    index.add_message(mailbox=other, deleted=1)  # not live
    assert mail_reply_cleanup.new_rows(old) == [
        (a, f"imap://{_ACCT}/INBOX"),
        (b, f"imap://{_OTHER}/Concepten"),
    ]
    assert mail_reply_cleanup.new_rows(b) == []


def test_new_rows_returns_one_row_over_the_cap_so_the_caller_can_tell(
    index, monkeypatch
):
    monkeypatch.setattr(mail_reply_cleanup, "MAX_NEW_ROWS", 3)
    box = index.add_mailbox(f"imap://{_ACCT}/INBOX")
    for _ in range(6):
        index.add_message(mailbox=box)
    assert len(mail_reply_cleanup.new_rows(0)) == 4


# --- where a stored message lives --------------------------------------------


def test_emlx_path_follows_mails_folder_and_shard_layout(mailroot):
    # 174504 -> the digits of 174 reversed: Data/4/7/1 (measured on a real store)
    put = mailroot(174504, _ORIGINAL, "a@x", "<div>x</div>", url=_URL)
    assert put.parent.as_posix().endswith("Drafts.mbox/GUID/Data/4/7/1/Messages")
    assert mail_reply_cleanup._emlx_path(_URL, 174504) == put
    small = mailroot(20, _ORIGINAL, "b@x", "<div>x</div>")
    assert small.parent.as_posix().endswith("Drafts.mbox/GUID/Data/Messages")
    assert mail_reply_cleanup._emlx_path(_URL, 20) == small


def test_emlx_path_nests_a_folder_per_segment_and_finds_a_partial_file(mailroot):
    url = f"imap://{_ACCT}/%5BGmail%5D/Drafts"
    put = mailroot(31, _ORIGINAL, "g@x", "<div>x</div>", url=url, partial=True)
    assert put.as_posix().count("[Gmail].mbox/Drafts.mbox") == 1
    assert mail_reply_cleanup._emlx_path(url, 31) == put


def test_emlx_path_searches_only_the_one_mailbox_folder(mailroot):
    # the shard rule missed (an unknown layout): the walk stays inside the mailbox
    put = mailroot(31, _ORIGINAL, "g@x", "<div>x</div>")
    odd = put.parent.parent / "7" / "Messages"
    odd.mkdir(parents=True)
    put.rename(odd / put.name)
    inbox = f"imap://{_ACCT}/INBOX"
    elsewhere = mailroot(31, _ORIGINAL, "e@x", "<div>x</div>", url=inbox)
    assert mail_reply_cleanup._emlx_path(_URL, 31) == odd / put.name
    assert mail_reply_cleanup._emlx_path(inbox, 31) == elsewhere
    assert mail_reply_cleanup._emlx_path(f"imap://{_ACCT}/Nope", 31) is None


# --- the selector ------------------------------------------------------------


def _find(monkeypatch, rows=None, own="Hi there", attribution=_ATTRIBUTION, **kw):
    _rows(monkeypatch, [(20, _URL)] if rows is None else rows)
    return mail_reply_cleanup.find_own_draft(
        10, _ORIGINAL, own, attribution, **{**_KW, **kw}
    )


def _kind(mailroot, monkeypatch, body, own="Hi there", *, tail=_TAIL, **kw) -> str:
    mailroot(20, _ORIGINAL, "draft-x@example.com", body, **kw)
    return _find(monkeypatch, own=own, tail=tail).kind


def test_find_own_draft_claims_exactly_one_new_reply_with_the_calls_text(
    mailroot, monkeypatch
):
    mailroot(20, _ORIGINAL, "draft-a@example.com", "<div>Hi there</div>" + _QUOTE_HTML)
    got = _find(monkeypatch)
    assert got == mail_reply_cleanup.Draft("one", _URL, "<draft-a@example.com>")


@pytest.mark.parametrize(
    "body",
    [
        "<div>Hi  there</div>",  # whitespace is folded
        f"<div>Hi there</div><div>{_ATTRIBUTION}</div>",  # then Mail's own line
        f"<div>Hi there {_ATTRIBUTION}</div>",
    ],
)
def test_find_own_draft_claims_the_calls_text_alone_or_with_mails_attribution(
    mailroot, monkeypatch, body
):
    assert _kind(mailroot, monkeypatch, body + _QUOTE_HTML) == "one"


@pytest.mark.parametrize(
    "body",
    [
        "",  # no text at all: could be any hand reply that was opened and saved
        f"<div>{_ATTRIBUTION}</div>",  # only Mail's attribution line
        f"<div>{_ATTRIBUTION} Hi there</div>",  # the attribution BEFORE the text
        f"<div>Hi there {_ATTRIBUTION} and more</div>",  # text typed after it
        "<div>Hi there Jane wrote:</div>",  # not this original's line
        "<div>Hi there On 2 Jul 2026, at 14:39, Jane wrote:</div>",  # another date
        "<div>On my way, see you at five.</div>",  # a hand reply that starts with "On "
        "<div>Sure, thanks</div>",  # a hand reply
        "<div>Hi</div>",  # a PREFIX of the call's text is not the call's text
        "<div>Hi there, Jane</div>",  # the call's text is only a PREFIX of this
        "<div>Hi there Hi there</div>",  # a double paste
    ],
)
def test_find_own_draft_deletes_nothing_it_cannot_prove_is_the_calls_own(
    mailroot, monkeypatch, body
):
    # the owner rule: refuse and leave nothing, never touch what is not ours. A copy
    # whose text before the quote is not exactly the call's text (plus Mail's own line)
    # is reported, never claimed.
    assert _kind(mailroot, monkeypatch, body + _QUOTE_HTML) == "unproven"


@pytest.mark.parametrize(
    "own, hand",
    [
        ("Hi", "Hi Jane, I will call you tonight."),
        ("Thanks!", "Thanks! I'll check it tomorrow and send the figures."),
        ("Thanks", "Thanks. Not now."),
    ],
)
@pytest.mark.parametrize("kind", ["html", "plain"])
def test_find_own_draft_never_claims_a_hand_reply_that_starts_with_the_calls_text(
    mailroot, monkeypatch, own, hand, kind
):
    # the reviewers' cases: a short call text is the start of an owner's own reply
    if kind == "html":
        body = f"<div>{hand}</div>" + _QUOTE_HTML
    else:
        body = f"{hand}\r\n\r\n{_ATTRIBUTION}\r\n> quoted words\r\n"
    assert _kind(mailroot, monkeypatch, body, own=own, kind=kind) == "unproven"


def test_find_own_draft_reads_a_plain_text_draft_up_to_the_first_quote_line(
    mailroot, monkeypatch
):
    body = "Hi there\r\n\r\n> quoted words\r\n"
    assert _kind(mailroot, monkeypatch, body, kind="plain") == "one"
    body = f"Hi there\r\n\r\n{_ATTRIBUTION}\r\n> quoted words\r\n"
    assert _kind(mailroot, monkeypatch, body, kind="plain") == "one"


def test_find_own_draft_gives_a_plain_text_hand_reply_that_starts_with_on_no_claim(
    mailroot, monkeypatch
):
    body = f"On my way, see you at five.\r\n\r\n{_ATTRIBUTION}\r\n> quoted\r\n"
    assert _kind(mailroot, monkeypatch, body, kind="plain") == "unproven"


def test_find_own_draft_without_an_attribution_accepts_only_the_text_itself(
    mailroot, monkeypatch
):
    # a reply without a quote (include_quote=False): the body is the text, nothing else
    mailroot(20, _ORIGINAL, "a@x", f"<div>Hi there {_ATTRIBUTION}</div>")
    assert _find(monkeypatch, attribution=None, tail=None).kind == "unproven"
    mailroot(20, _ORIGINAL, "a@x", "<div>Hi there</div>")
    assert _find(monkeypatch, attribution=None, tail=None).kind == "one"


def test_find_own_draft_never_claims_with_an_empty_own_text(mailroot, monkeypatch):
    # an empty call text proves nothing, even against an empty draft
    assert _kind(mailroot, monkeypatch, "<div>anything</div>", own="  ") == "unproven"
    assert _kind(mailroot, monkeypatch, "", own="  ") == "unproven"


@pytest.mark.parametrize("body", ["", "<div></div>"])
def test_find_own_draft_empty_text_guard_stands_on_its_own(mailroot, monkeypatch, body):
    # rv533: with no quote and no attribution to fail on, an empty call text would
    # EQUAL an empty draft: only the empty-text guard keeps this unproven
    mailroot(20, _ORIGINAL, "draft-x@example.com", body)
    got = _find(monkeypatch, own="  ", attribution=None, tail=None)
    assert got.kind == "unproven"


@pytest.mark.parametrize(
    "url, kind",
    [
        (f"imap://{_ACCT}/Drafts", "one"),
        (f"imap://{_ACCT}/Draft", "one"),  # a Yahoo-style server
        (f"imap://{_ACCT}/%5BGmail%5D/Drafts", "one"),
        (f"imap://{_ACCT}/%5BGoogle%20Mail%5D/Drafts", "one"),  # a German Gmail
        (f"imap://{_ACCT}/%5BArchive%202019%5D/Drafts", "unproven"),  # a user folder
        (f"imap://{_OTHER}/Drafts", "one"),  # the account the reply is sent FROM
        (f"imap://{_ACCT}/Concepten", "unproven"),  # a localized Drafts: loud
        (f"imap://{_ACCT}/%5BGmail%5D/All%20Mail", "unproven"),  # a label-backed Drafts
        (f"imap://{_ACCT}/Projects/Drafts", "unproven"),  # a user folder
        (f"imap://{_ACCT}/INBOX/Drafts", "unproven"),
        (f"imap://{_ACCT}/drafts", "unproven"),
        (f"imap://{_ACCT}/INBOX", "unproven"),
    ],
)
def test_find_own_draft_claims_only_a_mailbox_named_drafts(
    mailroot, monkeypatch, url, kind
):
    mailroot(20, _ORIGINAL, "d@x", "<div>Hi there</div>" + _QUOTE_HTML, url=url)
    assert _find(monkeypatch, [(20, url)]).kind == kind


def test_find_own_draft_with_several_candidates_claims_none(mailroot, monkeypatch):
    mailroot(20, _ORIGINAL, "a@x", "<div>Hi there</div>" + _QUOTE_HTML)
    mailroot(21, _ORIGINAL, "b@x", "<div>Hi there</div>" + _QUOTE_HTML)
    got = _find(monkeypatch, [(20, _URL), (21, _URL)])
    assert got.kind == "unproven" and got.mid == ""


def test_find_own_draft_with_a_copy_in_two_accounts_claims_none(mailroot, monkeypatch):
    other = f"imap://{_OTHER}/Drafts"
    mailroot(20, _ORIGINAL, "a@x", "<div>Hi there</div>" + _QUOTE_HTML)
    mailroot(21, _ORIGINAL, "b@x", "<div>Hi there</div>" + _QUOTE_HTML, url=other)
    assert _find(monkeypatch, [(20, _URL), (21, other)]).kind == "unproven"


def test_find_own_draft_ignores_other_threads(mailroot, monkeypatch):
    mailroot(20, "other@example.com", "new@example.com", "<div>Hi there</div>")
    assert _find(monkeypatch) == mail_reply_cleanup.Draft("none")
    assert _find(monkeypatch, rows=[]) == mail_reply_cleanup.Draft("none")


def test_find_own_draft_with_an_unreadable_new_row_proves_nothing(
    mailroot, monkeypatch
):
    # no .emlx on disk for row 20: it might be the call's own copy, in any mailbox
    assert _find(monkeypatch).kind == "unproven"
    mailroot(21, _ORIGINAL, "a@x", "<div>Hi there</div>" + _QUOTE_HTML)
    assert _find(monkeypatch, [(20, _URL), (21, _URL)]).kind == "unproven"


def test_find_own_draft_with_more_new_rows_than_it_reads_proves_nothing(
    mailroot, monkeypatch
):
    # the rows beyond the cap are never read, so "no copy" cannot be said
    monkeypatch.setattr(mail_reply_cleanup, "MAX_NEW_ROWS", 2)
    rows = [(20 + n, _URL) for n in range(3)]
    for rowid, _ in rows:  # all readable, none a reply to the original
        mailroot(rowid, "other@example.com", f"m{rowid}@x", "<div>hello</div>")
    assert _find(monkeypatch, rows) == mail_reply_cleanup.Draft(
        "unproven", reason="too_many_rows"
    )
    assert _find(monkeypatch, rows[:2]) == mail_reply_cleanup.Draft("none")


def _land(index, mailroot, url, text="Hi there"):
    """The index and the disk after Mail autosaved a reply copy into ``url``."""
    box = index.add_mailbox(url)
    rowid = index.add_message(mailbox=box)
    mailroot(rowid, _ORIGINAL, "own@x", f"<div>{text}</div>" + _QUOTE_HTML, url=url)


def test_find_own_draft_finds_a_copy_beside_a_decoy_drafts_folder(index, mailroot):
    # a localized Drafts next to a user folder NAMED Drafts: no mailbox is guessed, so
    # the copy is found where it landed and reported, never read as "no copy"
    index.add_mailbox(f"imap://{_ACCT}/Drafts")
    top = mail_reply_cleanup.index_top()
    _land(index, mailroot, f"imap://{_ACCT}/Concepten")
    got = mail_reply_cleanup.find_own_draft(
        top, _ORIGINAL, "Hi there", _ATTRIBUTION, **_KW
    )
    assert got.kind == "unproven"


def test_find_own_draft_finds_the_gmail_copy_beside_a_labelled_drafts_folder(
    index, mailroot
):
    index.add_mailbox(f"imap://{_ACCT}/Work/Drafts")  # a label with the same leaf
    top = mail_reply_cleanup.index_top()
    url = f"imap://{_ACCT}/%5BGmail%5D/Drafts"
    _land(index, mailroot, url)
    got = mail_reply_cleanup.find_own_draft(
        top, _ORIGINAL, "Hi there", _ATTRIBUTION, **_KW
    )
    assert got == mail_reply_cleanup.Draft("one", url, "<own@x>")


def test_find_own_draft_finds_a_copy_in_another_accounts_drafts(index, mailroot):
    # the reply is sent from an account other than the one that holds the original
    index.add_mailbox(f"imap://{_ACCT}/INBOX")
    top = mail_reply_cleanup.index_top()
    url = f"imap://{_OTHER}/Drafts"
    _land(index, mailroot, url)
    got = mail_reply_cleanup.find_own_draft(
        top, _ORIGINAL, "Hi there", _ATTRIBUTION, **_KW
    )
    assert got == mail_reply_cleanup.Draft("one", url, "<own@x>")


def test_find_own_draft_raises_when_the_index_cannot_be_read():
    with pytest.raises(NativeError):
        mail_reply_cleanup.find_own_draft(0, _ORIGINAL, "Hi", None, **_KW)


# --- ownership proof beyond equal text (rv532) ---------------------------------


def test_find_own_draft_never_claims_a_row_that_landed_after_the_discard(
    mailroot, monkeypatch
):
    # landed_by is the index top right after the discard answered: a row above it
    # landed once the window was gone, so a family or hand draft with the same text
    # cannot be taken for the call's own
    mailroot(20, _ORIGINAL, "a@x", "<div>Hi there</div>" + _QUOTE_HTML)
    assert _find(monkeypatch, landed_by=20).kind == "one"  # up to the top: its own
    assert _find(monkeypatch, landed_by=19).kind == "unproven"
    assert _find(monkeypatch, landed_by=None).kind == "unproven"  # top unreadable


@pytest.mark.parametrize(
    "body, tail",
    [
        ("<div>Hi there</div>", _TAIL),  # the quote was removed
        ("<div>Hi there</div><blockquote>owner trimmed it</blockquote>", _TAIL),
        ("<div>Hi there</div>" + _QUOTE_HTML, None),  # a no-quote reply with a quote
        ("<div>Hi there</div><div>and a signature</div>", None),
        # rv533: nothing may follow the original's tail. The call pastes only at the
        # top, so text below the quote (a PS, a signature) is a hand copy
        ("<div>Hi there</div>" + _QUOTE_HTML + "<div>PS: bring the forms</div>", _TAIL),
        ("<div>Hi there</div>" + _QUOTE_HTML + "<div>--<br>Jane</div>", _TAIL),
    ],
)
def test_find_own_draft_needs_the_originals_quote_after_the_text(
    mailroot, monkeypatch, body, tail
):
    # a hand copy of the text with a trimmed or removed quote is not the call's
    # (include_quote=True: the original's tail follows; False: nothing follows)
    assert _kind(mailroot, monkeypatch, body, tail=tail) == "unproven"


def test_find_own_draft_compares_the_quote_the_way_the_insert_confirms_it(
    mailroot, monkeypatch
):
    # letters and digits only: link and bullet marks differ between Mail's HTML and
    # what the AX walk read (runtime._alnum)
    body = "<div>Hi there</div><blockquote>quoted <b>words</b></blockquote>"
    assert _kind(mailroot, monkeypatch, body) == "one"
    plain = "Hi there\r\n\r\n> * quoted\r\n> words.\r\n"
    assert _kind(mailroot, monkeypatch, plain, kind="plain") == "one"
    # ... and a plain-text PS below the quote is a hand copy
    ps = plain + "\r\nPS: bring the forms\r\n"
    assert _kind(mailroot, monkeypatch, ps, kind="plain") == "unproven"


def test_find_own_draft_never_claims_a_copy_without_a_message_id(mailroot, monkeypatch):
    # `whose message id is ""` would match nothing or the wrong message
    mailroot(20, _ORIGINAL, "", "<div>Hi there</div>" + _QUOTE_HTML)
    assert _find(monkeypatch).kind == "unproven"


def test_find_own_draft_stops_at_the_first_unreadable_row(mailroot, monkeypatch):
    # the verdict is unproven whatever follows: nothing after it is located or read
    mailroot(21, _ORIGINAL, "a@x", "<div>Hi there</div>" + _QUOTE_HTML)
    seen: list[int] = []
    real = mail_reply_cleanup._read_draft

    def spy(url, rowid):
        seen.append(rowid)
        return real(url, rowid)

    monkeypatch.setattr(mail_reply_cleanup, "_read_draft", spy)
    rows = [(20, _URL), (21, _URL), (22, _URL)]  # row 20 has no file
    assert _find(monkeypatch, rows).kind == "unproven"
    assert seen == [20]


def test_find_own_draft_parses_the_body_of_a_threaded_row_only(mailroot, monkeypatch):
    mailroot(20, "other@example.com", "p@x", "<div>private</div>")
    mailroot(21, _ORIGINAL, "a@x", "<div>Hi there</div>" + _QUOTE_HTML)
    mailroot(22, "other@example.com", "q@x", "<div>private</div>")
    parsed: list[bytes] = []
    real = email.message_from_bytes
    monkeypatch.setattr(
        mail_reply_cleanup.email,
        "message_from_bytes",
        lambda raw, **kw: parsed.append(raw) or real(raw, **kw),
    )
    rows = [(20, _URL), (21, _URL), (22, _URL)]
    assert _find(monkeypatch, rows).kind == "one"
    assert len(parsed) == 1 and b"a@x" in parsed[0]


# --- where the files are (rv532) -----------------------------------------------


def test_shard_is_the_reversed_digits_of_rowid_div_1000():
    assert mail_reply_cleanup._shard(999) == ""
    assert mail_reply_cleanup._shard(1000) == "1"
    assert mail_reply_cleanup._shard(12345) == "2/1"
    assert mail_reply_cleanup._shard(174504) == "4/7/1"


def test_emlx_path_finds_a_file_by_its_shard_without_the_fallback_walk(
    mailroot, monkeypatch
):
    # the rglob fallback finds the file whatever the shard rule says; with it disabled
    # a wrong shard rule (always '') misses the file and fails here
    put = mailroot(174504, _ORIGINAL, "a@x", "<div>x</div>")

    def no_walk(self, pattern):
        raise AssertionError("the fallback walk ran")

    monkeypatch.setattr(Path, "rglob", no_walk)
    assert mail_reply_cleanup._emlx_path(_URL, 174504) == put


def test_emlx_path_reads_only_the_v_folder_of_the_index_being_read(mailroot, tmp_path):
    # a stale V9 tree beside V10 holds an unrelated file under the same name
    url = _URL
    live = mailroot(20, _ORIGINAL, "own@x", "<div>live</div>", url=url)
    decoy = tmp_path / "V9" / _ACCT / "Drafts.mbox" / "GUID" / "Data" / "Messages"
    decoy.mkdir(parents=True)
    (decoy / "20.emlx").write_bytes(_emlx("old@example.com", "old@x", "<div>old</div>"))
    assert mail_reply_cleanup._emlx_path(url, 20) == live
    live.unlink()  # a row with no file in V10 is unreadable, never read from V9
    assert mail_reply_cleanup._emlx_path(url, 20) is None


def test_emlx_path_is_none_without_an_index(monkeypatch):
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: None)
    assert mail_reply_cleanup._emlx_path(_URL, 20) is None


# --- ROWID is AUTOINCREMENT (rv532) --------------------------------------------


def test_index_top_checks_once_that_rowid_is_autoincrement(index, monkeypatch):
    mail_reply_cleanup._AUTOINCREMENT_SEEN.clear()
    assert mail_reply_cleanup.index_top() == 0
    # the table definition is read once per index file: a later read does not look
    monkeypatch.setattr(mail_reply_cleanup, "_TABLE_SQL", "SELECT NULL WHERE 0")
    assert mail_reply_cleanup.index_top() == 0


def test_index_top_is_none_when_rowid_is_not_autoincrement(index):
    # without AUTOINCREMENT SQLite may reuse the number of a deleted top row, so a new
    # row would not sort above the baseline: the sweep is unavailable, not wrong
    mail_reply_cleanup._AUTOINCREMENT_SEEN.clear()
    index.execute("ALTER TABLE messages RENAME TO kept")
    index.execute(
        "CREATE TABLE messages(ROWID INTEGER PRIMARY KEY, mailbox INT, "
        "deleted INT NOT NULL DEFAULT 0)"
    )
    assert mail_reply_cleanup.index_top() is None
    # rv533 (I2): the refusal is not cached as a pass: a second call refuses too
    assert mail_reply_cleanup.index_top() is None


def test_index_top_checks_every_index_file_on_its_own(index, monkeypatch, tmp_path):
    # rv533 (I3): the check is per file (the set holds paths): a later index without
    # AUTOINCREMENT (another version's folder) is refused although the first passed
    mail_reply_cleanup._AUTOINCREMENT_SEEN.clear()
    assert mail_reply_cleanup.index_top() == 0
    other = tmp_path / "V11" / "MailData" / "Envelope Index"
    other.parent.mkdir(parents=True)
    shutil.copy(index.path, other)  # the full schema, so only AUTOINCREMENT differs
    conn = sqlite3.connect(other)
    conn.execute("ALTER TABLE messages RENAME TO kept")
    conn.execute(
        "CREATE TABLE messages(ROWID INTEGER PRIMARY KEY, mailbox INT, "
        "deleted INT NOT NULL DEFAULT 0)"
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: other)
    assert mail_reply_cleanup.index_top() is None


# --- the sent message's own copies (reply_all, owner decision 2026-11-01) --------

_SENT = f"imap://{_ACCT}/Sent%20Messages"
_ALL_MAIL = f"imap://{_ACCT}/%5BGmail%5D/All%20Mail"
_OWN = "<div>Hi there</div>" + _QUOTE_HTML


def test_find_own_draft_treats_the_sent_copies_as_the_send_only_after_a_send(
    mailroot, monkeypatch
):
    # a refusal sent nothing, so a threaded row outside Drafts is never explained away
    mailroot(20, _ORIGINAL, "d@x", _OWN)
    mailroot(21, _ORIGINAL, "d@x", _OWN, url=_SENT)
    mailroot(22, _ORIGINAL, "d@x", _OWN, url=_ALL_MAIL)
    rows = [(20, _URL), (21, _SENT), (22, _ALL_MAIL)]
    assert _find(monkeypatch, rows).kind == "unproven"
    got = _find(monkeypatch, rows, sent_twins=True)
    assert got == mail_reply_cleanup.Draft("one", _URL, "<d@x>")


def test_find_own_draft_after_a_send_with_only_the_sent_copy_finds_no_draft(
    mailroot, monkeypatch
):
    mailroot(21, _ORIGINAL, "s@x", _OWN, url=_SENT)
    got = _find(monkeypatch, [(21, _SENT)], sent_twins=True)
    assert got == mail_reply_cleanup.Draft("none")


@pytest.mark.parametrize(
    "body, url",
    [
        ("<div>Something else</div>" + _QUOTE_HTML, _SENT),  # another text
        ("<div>Hi there, Jane</div>" + _QUOTE_HTML, _SENT),  # only starts with ours
        ("<div>Hi there</div>", _SENT),  # the quote is gone
        (_OWN, f"imap://{_ACCT}/Projects/Drafts"),  # a user folder, still not ours
        (_OWN, f"imap://{_ACCT}/verzonden"),  # case variant stays unproven (D-14)
        (_OWN, f"imap://{_ACCT}/E%CC%81le%CC%81ments%20envoye%CC%81s"),  # NFD
        (_OWN, f"imap://{_ACCT}/Projects/Verzonden"),  # nested user folder
        (_OWN, f"imap://{_ACCT}/Concepten"),  # a localized Drafts leftover is reported
        (_OWN, f"imap://{_ACCT}/Projects/Sent"),  # a user folder named Sent
        (_OWN, f"imap://{_ACCT}/All%20Mail"),  # All Mail only under Google's root
    ],
)
def test_find_own_draft_after_a_send_still_reports_any_other_threaded_row(
    mailroot, monkeypatch, body, url
):
    mailroot(20, _ORIGINAL, "d@x", _OWN)
    mailroot(21, _ORIGINAL, "s@x", body, url=url)
    got = _find(monkeypatch, [(20, _URL), (21, url)], sent_twins=True)
    assert got.kind == "unproven"


def test_find_own_draft_after_a_send_needs_a_message_id_on_the_sent_copy(
    mailroot, monkeypatch
):
    mailroot(20, _ORIGINAL, "d@x", _OWN)
    mailroot(21, _ORIGINAL, "", _OWN, url=_SENT)
    got = _find(monkeypatch, [(20, _URL), (21, _SENT)], sent_twins=True)
    assert got.kind == "unproven"


def test_find_own_draft_after_a_send_never_lets_a_second_drafts_row_pass(
    mailroot, monkeypatch
):
    mailroot(20, _ORIGINAL, "d@x", _OWN)
    mailroot(21, _ORIGINAL, "e@x", _OWN)  # a second copy in Drafts
    mailroot(22, _ORIGINAL, "d@x", _OWN, url=_SENT)
    rows = [(20, _URL), (21, _URL), (22, _SENT)]
    assert _find(monkeypatch, rows, sent_twins=True).kind == "unproven"


def test_find_own_draft_after_a_send_never_calls_a_localized_drafts_leftover_none(
    mailroot, monkeypatch
):
    # the own autosave in a localized Drafts must not be taken for the Sent copy
    url = f"imap://{_ACCT}/Concepten"
    mailroot(20, _ORIGINAL, "d@x", _OWN, url=url)
    assert _find(monkeypatch, [(20, url)], sent_twins=True).kind == "unproven"


def test_sent_mailbox_names(monkeypatch):
    sent = mail_reply_cleanup._is_sent_url
    for name in (
        "Sent",
        "Sent%20Messages",
        "Sent%20Items",
        "%5BGmail%5D/Sent%20Mail",
        "Verzonden",
        "%5BGoogle%20Mail%5D/%C3%89l%C3%A9ments%20envoy%C3%A9s",
    ):
        assert sent(f"imap://{_ACCT}/{name}"), name
    assert sent(f"imap://{_ACCT}/%5BGoogle%20Mail%5D/All%20Mail")
    for name in (
        "verzonden",
        "Projects/Sent",
        "All%20Mail",
        "%5BArchive%5D/Sent",
        "E%CC%81le%CC%81ments%20envoye%CC%81s",
        "Projects/Verzonden",
    ):
        assert not sent(f"imap://{_ACCT}/{name}"), name


@pytest.mark.parametrize("name", ["Verzonden", "Éléments envoyés", "Отправленные"])
def test_localized_sent_twin_uses_exact_shared_vocabulary(mailroot, monkeypatch, name):
    url = f"imap://{_ACCT}/" + quote(name)
    mailroot(20, _ORIGINAL, "d@x", _OWN)
    mailroot(21, _ORIGINAL, "s@x", _OWN, url=url)
    rows = [(20, _URL), (21, url)]
    assert _find(monkeypatch, rows).kind == "unproven"  # nothing was sent
    assert _find(monkeypatch, rows, sent_twins=True) == mail_reply_cleanup.Draft(
        "one", _URL, "<d@x>"
    )


# --- the reply's own signature (FIX-16 gap G4, owner decision 2026-11-01) ---------

_SIG = "Jane Doe\nExample Corp"
_SIG_HTML = '<div id="AppleMailSignature">Jane Doe<br>Example Corp</div>'
# the same words, broken into lines and links differently: white space only
_SIG_WS = '<div>Jane  Doe<br>\n<a href="https://x.example">Example&nbsp;Corp</a></div>'


def _signed(before: str, **kw):
    """The kind of the one Drafts copy whose HTML is ``before`` + the quote."""
    return _find_kind_with_signature(before + _QUOTE_HTML, **kw)


def _find_kind_with_signature(body, *, signature=_SIG, own="Hi there"):
    return mail_reply_cleanup._is_own(
        mail_reply_cleanup._split_quote(
            email.message_from_string(
                "Content-Type: text/html; charset=utf-8\r\n\r\n" + body,
                policy=email.policy.default,
            )
        )[0],
        own,
        _ATTRIBUTION,
        signature,
    )


@pytest.mark.parametrize(
    "before, accepted",
    [
        ("<div>Hi there</div>", True),
        (f"<div>Hi there</div><div>{_ATTRIBUTION}</div>", True),
        (f"<div>Hi there</div>{_SIG_HTML}", True),
        (f"<div>Hi there</div>{_SIG_HTML}<div>{_ATTRIBUTION}</div>", True),
        (f"<div>Hi there</div>{_SIG_WS}", True),  # differs in white space only
        (f"<div>Hi there</div>{_SIG_WS}<div>{_ATTRIBUTION}</div>", True),
        # owner content without a letter or a digit is still owner content
        (f"<div>Hi there</div><div>!!!</div>{_SIG_HTML}", False),
        (f"<div>Hi there</div><div>\U0001f44d \U0001f600</div>{_SIG_HTML}", False),
        (f"<div>Hi there</div>{_SIG_HTML}<div>?? :-)</div>", False),
        (
            f"<div>Hi there</div><div>\u2014 \u2014 \u2014</div>{_SIG_HTML}"
            f"<div>\u2014 \u2713</div><div>{_ATTRIBUTION}</div>",
            False,
        ),
        ("<div>Hi there</div><div>Jane Doe - Example Corp</div>", False),
        (_SIG_HTML, False),  # the signature alone
        (f"<div>Hi there</div><div>and more</div>{_SIG_HTML}", False),
        (f"<div>Hi there</div>{_SIG_HTML}<div>and more</div>", False),
        (f"<div>Hi there</div><div>{_ATTRIBUTION}</div>{_SIG_HTML}", False),
        (f"<div>{_ATTRIBUTION}</div><div>Hi there</div>{_SIG_HTML}", False),
        ("<div>Hi there</div><div>Jane Doe Other Corp</div>", False),
        ("<div>Hi there Jane Doe Example Corp</div>", True),  # same squashed text
        ("<div>Hi thereJane Doe Example Corp</div>", False),  # glued, no space
    ],
)
def test_is_own_accepts_the_replys_own_signature_and_nothing_else(before, accepted):
    assert _signed(before) is accepted


def test_is_own_accepts_no_signature_when_the_signature_read_was_empty():
    assert _signed(f"<div>Hi there</div>{_SIG_HTML}", signature="") is False
    assert _signed("<div>Hi there</div>", signature="") is True


@pytest.mark.parametrize("own", ["", "   ", "\n\t "])
@pytest.mark.parametrize(
    "before",
    [
        _SIG_HTML,
        f"{_SIG_HTML}<div>{_ATTRIBUTION}</div>",
        "",
        f"<div>{_ATTRIBUTION}</div>",
    ],
)
def test_is_own_never_matches_an_empty_or_blank_call_text(own, before):
    # owner decision 2026-11-01: a draft that holds only the signature is not the call's
    assert _signed(before, own=own) is False


def test_find_own_draft_after_a_send_sets_aside_a_sent_copy_with_the_signature(
    mailroot, monkeypatch
):
    signed = "<div>Hi there</div>" + _SIG_HTML + _QUOTE_HTML
    mailroot(20, _ORIGINAL, "d@x", signed)
    mailroot(21, _ORIGINAL, "d@x", signed, url=_SENT)
    mailroot(22, _ORIGINAL, "d@x", signed, url=_ALL_MAIL)
    rows = [(20, _URL), (21, _SENT), (22, _ALL_MAIL)]
    got = _find(monkeypatch, rows, sent_twins=True, signature=_SIG)
    assert got == mail_reply_cleanup.Draft("one", _URL, "<d@x>")
    # without the signature read the same rows stay unproven (today's rule)
    assert _find(monkeypatch, rows, sent_twins=True).kind == "unproven"


# --- the delivered copy and the reason of every unproven verdict (#348, 05.2-17) ------

_INBOX = f"imap://{_ACCT}/INBOX"


def _stored(mailroot, monkeypatch, rows, **kw):
    """Store ``(rowid, url, mid, body[, received])`` rows (a ``None`` body leaves the
    file out; ``received`` writes the postmark of a delivered message, default none) and
    run the selector over them."""
    for rowid, url, mid, body, *received in rows:
        if body is not None:
            mailroot(
                rowid,
                _ORIGINAL,
                mid,
                body,
                url=url,
                received=bool(received and received[0]),
            )
    return _find(monkeypatch, [(row[0], row[1]) for row in rows], **kw)


_DRAFT_ROW = (20, _URL, "d@x", _OWN)
_OTHER_BODY = "<div>not the reply</div>"


@pytest.mark.parametrize(
    "inbox_first, twin_url",
    [(True, _SENT), (False, _SENT), (True, _ALL_MAIL), (False, _ALL_MAIL)],
)
def test_find_own_draft_after_a_send_sets_aside_the_postmarked_delivered_inbox_copy(
    mailroot, monkeypatch, inbox_first, twin_url
):
    # the sent message reached an address whose account is in Mail on this Mac: its
    # delivered copy is an INBOX row with the Sent copy's Message-ID (any case), and
    # the order of the two rows in the index is not ours to know
    first, second = (21, 22) if inbox_first else (22, 21)
    twin = (second, twin_url, "s@x", _OWN)
    # its body is never judged; a mail server's `Received` header is the postmark
    inbox = (first, _INBOX, "S@X", _OTHER_BODY, True)
    rows = [_DRAFT_ROW, inbox, twin] if inbox_first else [_DRAFT_ROW, twin, inbox]
    got = _stored(mailroot, monkeypatch, rows, sent_twins=True)
    assert got == mail_reply_cleanup.Draft("one", _URL, "<d@x>")
    # without the own Drafts copy nothing is left to report
    got = _stored(mailroot, monkeypatch, rows[1:], sent_twins=True)
    assert got == mail_reply_cleanup.Draft("none")


@pytest.mark.parametrize(
    "inbox_first, twin_url",
    [(True, _SENT), (False, _SENT), (True, _ALL_MAIL), (False, _ALL_MAIL)],
)
@pytest.mark.parametrize("with_drafts", [True, False])
def test_find_own_draft_keeps_an_inbox_row_without_a_postmark_unproven(
    mailroot, monkeypatch, inbox_first, twin_url, with_drafts
):
    # the Message-ID matches a set-aside copy, but no mail server stamped the row: an
    # account whose Drafts mailbox is its INBOX could hold a leftover draft like this
    first, second = (21, 22) if inbox_first else (22, 21)
    twin = (second, twin_url, "s@x", _OWN)
    inbox = (first, _INBOX, "s@x", _OTHER_BODY)  # no `Received` header
    rows = [inbox, twin] if inbox_first else [twin, inbox]
    got = _stored(
        mailroot,
        monkeypatch,
        [_DRAFT_ROW, *rows] if with_drafts else rows,
        sent_twins=True,
    )
    assert got.kind == "unproven" and got.reason == "inbox_row"


def test_read_draft_reads_the_postmark_from_the_headers(mailroot):
    mailroot(20, _ORIGINAL, "d@x", _OWN, received=True)
    mailroot(21, _ORIGINAL, "s@x", _OWN)
    stamped = mail_reply_cleanup._read_draft(_URL, 20)[1]()
    plain = mail_reply_cleanup._read_draft(_URL, 21)[1]()
    assert stamped[2] is True and plain[2] is False
    assert callable(stamped[1]) and callable(plain[1])  # the body is not parsed here


@pytest.mark.parametrize(
    "rows, kw, reason",
    [
        # no Message-ID: nothing ties it to the sent message
        ([(21, _SENT, "s@x", _OWN), (22, _INBOX, "", _OTHER_BODY)], {}, "inbox_row"),
        # a Message-ID no set-aside copy carries
        (
            [(21, _SENT, "s@x", _OWN), (22, _INBOX, "other@x", _OTHER_BODY)],
            {},
            "inbox_row",
        ),
        # after a refusal nothing was sent: no copy is set aside, whatever it carries
        ([(22, _INBOX, "s@x", _OWN)], {"sent_twins": False}, "inbox_row"),
        # the Sent row failed the text check, so it set nothing aside: the INBOX row
        # with its Message-ID is not set aside either, and nothing is claimed
        (
            [(21, _SENT, "s@x", _OTHER_BODY), (22, _INBOX, "s@x", _OTHER_BODY)],
            {},
            "sent_not_own",
        ),
        (
            [(22, _INBOX, "s@x", _OTHER_BODY), (23, _SENT, "s@x", _OTHER_BODY)],
            {},
            "sent_not_own",
        ),
    ],
)
def test_find_own_draft_keeps_every_other_inbox_row_unproven(
    mailroot, monkeypatch, rows, kw, reason
):
    got = _stored(mailroot, monkeypatch, rows, **{"sent_twins": True, **kw})
    assert got.kind == "unproven" and got.reason == reason


@pytest.mark.parametrize(
    "url, reason",
    [
        (f"imap://{_ACCT}/Concepten", "other_mailbox"),  # a localized Drafts
        (f"imap://{_ACCT}/Projects/INBOX", "other_mailbox"),  # not directly under it
        (f"imap://{_ACCT}/Projects/Drafts", "other_mailbox"),
        (f"imap://{_ACCT}/inbox", "other_mailbox"),  # another spelling
        (f"imap://{_ACCT}/INBOX/Drafts", "other_mailbox"),  # an INBOX-rooted server
        (f"imap://{_ACCT}/INBOX.Drafts", "other_mailbox"),
        (_URL, "several_rows"),  # a second Drafts row: both look like the call's own
    ],
)
def test_find_own_draft_never_sets_aside_a_row_outside_the_inbox_by_message_id(
    mailroot, monkeypatch, url, reason
):
    # the Drafts autosave may share the sent message's Message-ID: only the top-level
    # INBOX, which never holds a draft, may pass for the delivered copy
    rows = [(21, _SENT, "s@x", _OWN), (22, url, "s@x", _OWN)]
    if url == _URL:
        rows.insert(0, _DRAFT_ROW)
    got = _stored(mailroot, monkeypatch, rows, sent_twins=True)
    assert got.kind == "unproven" and got.reason == reason


@pytest.mark.parametrize(
    "body, kw, reason",
    [
        (_OTHER_BODY, {}, "drafts_not_own"),
        (_OWN, {"landed_by": 21}, "drafts_late"),
    ],
)
def test_find_own_draft_never_sets_aside_a_drafts_row_by_message_id(
    mailroot, monkeypatch, body, kw, reason
):
    # a Drafts row that is not provably own stays in the way, even with the Message-ID
    # of the Sent copy that was set aside
    rows = [(21, _SENT, "s@x", _OWN), (22, _URL, "s@x", body)]
    got = _stored(mailroot, monkeypatch, rows, sent_twins=True, **kw)
    assert got.kind == "unproven" and got.reason == reason


def test_find_own_draft_never_sets_aside_an_inbox_row_by_the_drafts_copys_message_id(
    mailroot, monkeypatch
):
    # only a Sent or All Mail copy that was set aside vouches for an INBOX row
    rows = [_DRAFT_ROW, (22, _INBOX, "d@x", _OTHER_BODY)]
    got = _stored(mailroot, monkeypatch, rows, sent_twins=True)
    assert got.kind == "unproven" and got.reason == "inbox_row"


# Combining marks for the scan before normalization (FIX-36, #626), by code point: an
# editor cannot turn these into glyphs.
_GRAVE, _COMMA = chr(0x0300), chr(0x0315)  # combining classes 230 and 232
_OBJECT = chr(0xFFFC)


def _marks(count: int) -> str:
    """``count`` combining marks in the worst order for NFC: class 232, then 230."""
    return _COMMA * (count // 2) + _GRAVE * (count - count // 2)


def _marked_own(count: int, kind: str = "html") -> str:
    """The call's own copy (``_OWN``, or its plain-text form) with ``count`` marks on
    one letter of the quote. At most 30 marks read as the call's own."""
    words = f"quoted w{_marks(count)}ords"
    if kind == "plain":
        return f"Hi there\n\n{_ATTRIBUTION}\n> {words}"
    return _OWN.replace("quoted words", words)


def _sized(size: int, kind: str = "html") -> str:
    """The call's own copy (``_OWN``, or its plain-text form) padded with spaces to
    exactly ``size`` characters. Under the size cap it reads as the call's own."""
    if kind == "plain":
        head, quoted = "Hi there\n", f"\n{_ATTRIBUTION}\n> quoted words"
    else:
        head, quoted = "<div>Hi there</div>", _QUOTE_HTML
    return head + " " * (size - len(head) - len(quoted)) + quoted


# (stored rows, find kwargs, reason): one per code. A body of None leaves the file out.
_BRANCH_CASES = [
    ("too_many_rows", [(20 + n, _URL, f"m{n}@x", _OTHER_BODY) for n in range(3)], {}),
    ("unreadable_row", [(20, _URL, "d@x", None)], {}),
    ("drafts_late", [_DRAFT_ROW], {"landed_by": 19}),
    ("drafts_late", [_DRAFT_ROW], {"landed_by": None}),
    (
        "drafts_not_own",
        [(20, _URL, "d@x", "<div>Hi there, Jane</div>" + _QUOTE_HTML)],
        {},
    ),
    ("drafts_not_own", [(20, _URL, "", _OWN)], {}),
    (
        "sent_not_own",
        [(21, _SENT, "s@x", "<div>Hi there, Jane</div>" + _QUOTE_HTML)],
        {"sent_twins": True},
    ),
    ("sent_not_own", [(21, _SENT, "", _OWN)], {"sent_twins": True}),
    ("inbox_row", [(22, _INBOX, "s@x", _OWN)], {}),
    ("other_mailbox", [(22, f"imap://{_ACCT}/Archive", "s@x", _OWN)], {}),
    ("other_mailbox", [(21, _SENT, "s@x", _OWN)], {}),  # a refusal sent nothing
    ("several_rows", [_DRAFT_ROW, (21, _URL, "e@x", _OWN)], {}),
    # the first row that cannot be claimed names the branch
    (
        "other_mailbox",
        [_DRAFT_ROW, (21, f"imap://{_ACCT}/Archive", "s@x", _OWN)],
        {},
    ),
    (
        "other_mailbox",
        [(19, f"imap://{_ACCT}/Archive", "s@x", _OWN), (20, _URL, "d@x", _OWN)],
        {},
    ),
    # over the size cap, which the two tests below set to 1,000 characters
    ("body_too_large", [(20, _URL, "d@x", _sized(1_001))], {}),
    # 31 combining marks in a row, one over the limit
    ("combining_run", [(20, _URL, "d@x", _marked_own(31))], {}),
    # a Message-ID field value over 998 characters, in a row of the thread
    ("header_too_large", [(20, _URL, "m" * 1_000 + "@x", _OWN)], {}),
    # 1,001 part-delimiter lines
    ("message_too_large", [(20, _URL, "d@x", _OWN + "\r\n--x" * 1_001)], {}),
    # a decimal character reference of 5,000 digits: `html.unescape` raises. The two
    # tests below lift the size cap for this one case.
    (
        "read_failed",
        [(20, _URL, "d@x", _OWN.replace("there", "there &#" + "9" * 5_000 + ";"))],
        {},
    ),
]


@pytest.mark.parametrize("reason, rows, kw", _BRANCH_CASES)
def test_find_own_draft_names_each_unproven_branch(
    mailroot, monkeypatch, reason, rows, kw
):
    if reason == "too_many_rows":
        monkeypatch.setattr(mail_reply_cleanup, "MAX_NEW_ROWS", 2)
    cap = 10_000 if reason == "read_failed" else 1_000
    monkeypatch.setattr(mail_reply_cleanup, "MAX_BODY_CHARS", cap)
    got = _stored(mailroot, monkeypatch, rows, **kw)
    assert got.kind == "unproven" and got.reason == reason


def test_every_find_own_draft_reason_is_a_fixed_code(mailroot, monkeypatch):
    codes = {
        "too_many_rows",
        "unreadable_row",
        "drafts_late",
        "drafts_not_own",
        "sent_not_own",
        "inbox_row",
        "other_mailbox",
        "several_rows",
        "body_too_large",
        "combining_run",
        "header_too_large",
        "message_too_large",
        "read_failed",
    }
    produced = set()
    for n, (reason, rows, kw) in enumerate(_BRANCH_CASES):
        monkeypatch.setattr(mail_reply_cleanup, "MAX_NEW_ROWS", 2 if n == 0 else 300)
        cap = 10_000 if reason == "read_failed" else 1_000
        monkeypatch.setattr(mail_reply_cleanup, "MAX_BODY_CHARS", cap)
        # a fresh row id range per case, so a stored file never answers for the next
        shifted = [(rowid + 100 * n, *rest) for rowid, *rest in rows]
        got = _stored(
            mailroot,
            monkeypatch,
            shifted,
            **{"landed_by": 10**6, **kw},
        )
        produced.add(got.reason)
    assert produced == codes and len(codes) == 13
    assert all(re.fullmatch(r"[a-z_]+", code) for code in produced)


def test_a_claimed_or_empty_verdict_carries_no_reason(mailroot, monkeypatch):
    assert _stored(mailroot, monkeypatch, [_DRAFT_ROW]).reason == ""
    assert _find(monkeypatch, rows=[]).reason == ""


# --- Mail's inline-image placeholder in the quote (#348, 05.2-19, owner decision 1) --

# Mail's quote writes each inline image of the original as one span whose text is
# `<file name>`: the id-only form in Sent and delivered copies, the compose-time form
# (with Mail's editing class) in drafts and autosaves (facts 4e `Layout`).
_PH = '<span id="cid:ii_t1">&lt;logo.png&gt;</span>'
_PH_EDIT = (
    '<span class="AppleTemporaryEditingElement" id="cid:ii_t1">&lt;logo.png&gt;</span>'
)
_PH_EDIT_2 = (
    '<span class="AppleTemporaryEditingElement" id="cid:ii_t2">'
    "&lt;photo 2.jpg&gt;</span>"
)


def _quoted(inner: str) -> str:
    """The call's text above a quote whose last part is ``inner``."""
    return (
        f'<div>Hi there</div><blockquote type="cite">{_ATTRIBUTION}<br>'
        f"{inner}</blockquote>"
    )


@pytest.mark.parametrize(
    "text, token",
    [
        ("<logo.png>", True),
        ("<a b>", True),
        ("<>", False),
        ("< >", False),
        ("<\u00a0>", False),
        ("<a><b>", False),
        ("<a>b", False),
        ("a<b>", False),
        ("<a<b>", False),
        ("<a", False),
        ("a>", False),
        ("", False),
        ("<", False),
        ("ab>", False),
        ("<ab", False),
    ],
)
def test_image_placeholder_token_is_one_bracketed_name(text, token):
    assert mail_reply_cleanup._is_token(text) is token


def test_drop_placeholders_stays_fast_on_a_long_unclosed_image_placeholder():
    # the text is another party's mail: a pattern here once took quadratic time
    # (3.5 s for 32,000 characters); plain string checks take milliseconds
    import time

    quote_html = '<blockquote><span id="cid:x">&lt;' + "a" * 400_000 + "</span>"
    started = time.perf_counter()
    assert mail_reply_cleanup._drop_placeholders(quote_html) == quote_html
    assert time.perf_counter() - started < 2.0


def test_split_quote_drops_an_image_placeholder_only_from_the_quote():
    msg = email.message_from_string(
        "Content-Type: text/html; charset=utf-8\r\n\r\n"
        f"<div>Hi there {_PH}</div>"
        f"<blockquote>quoted words {_PH}{_PH_EDIT}</blockquote>",
        policy=email.policy.default,
    )
    head, tail = mail_reply_cleanup._split_quote(msg)
    assert "<logo.png>" in head  # the text before the quote never loses an element
    assert "<logo.png>" not in tail and tail.endswith("quoted words")


_PROVEN_SHAPES = [
    f"quoted words{_PH}",
    f"quoted words{_PH_EDIT}",
    f"quoted words{_PH}{_PH_EDIT_2}",
    f"quoted {_PH_EDIT}words",
    '<div>quoted words<span class="AppleTemporaryEditingElement" id="cid:ii_t1">'
    " &lt;logo.png&gt;&nbsp;</span></div>",
]


@pytest.mark.parametrize("inner", _PROVEN_SHAPES)
@pytest.mark.parametrize("mode", ["refusal", "send_with_drafts", "send_twins_only"])
def test_find_own_draft_proves_a_copy_whose_quote_holds_an_image_placeholder(
    mailroot, monkeypatch, inner, mode
):
    body = _quoted(inner)
    drafts = (20, _URL, "d@x", body)
    twins = [(21, _SENT, "s@x", body), (22, _ALL_MAIL, "a@x", body)]
    if mode == "refusal":
        got = _stored(mailroot, monkeypatch, [drafts])
        assert got == mail_reply_cleanup.Draft("one", _URL, "<d@x>")
    elif mode == "send_with_drafts":
        got = _stored(mailroot, monkeypatch, [drafts, *twins], sent_twins=True)
        assert got == mail_reply_cleanup.Draft("one", _URL, "<d@x>")
    else:
        got = _stored(mailroot, monkeypatch, twins, sent_twins=True)
        assert got == mail_reply_cleanup.Draft("none")


_ALMOST = "&lt;logo.png&gt;"
_TEXT_LIKE_A_PLACEHOLDER = [
    f"quoted words{_ALMOST}",  # typed text
    f"quoted words<span>{_ALMOST}</span>",  # a span without an id
    f'quoted words<span id="img1">{_ALMOST}</span>',
    f'quoted words<span id="xcid:ii_t1">{_ALMOST}</span>',
    f'quoted words<span id="CID:ii_t1">{_ALMOST}</span>',
    f'quoted words<SPAN ID="cid:ii_t1">{_ALMOST}</SPAN>',
    f"quoted words<span id='cid:ii_t1'>{_ALMOST}</span>",
    f"quoted words<span id=cid:ii_t1>{_ALMOST}</span>",
    f'quoted words<span class="x" id="cid:ii_t1">{_ALMOST}</span>',
    # the class after the id is not a form Mail writes
    'quoted words<span id="cid:ii_t1" class="AppleTemporaryEditingElement">'
    f"{_ALMOST}</span>",
    'quoted words<span id="cid:ii_t1">logo.png</span>',  # no brackets
    'quoted words<span id="cid:ii_t1">&lt;a.png&gt; &lt;b.png&gt;</span>',  # two tokens
    'quoted words<span id="cid:ii_t1">&lt;logo.png&gt; PS</span>',  # extra text
    f'quoted words<span id="cid:ii_t1"><span>{_ALMOST}</span></span>',  # a tag inside
    f'quoted words<span id="cid:ii_t1">{_ALMOST}',  # unclosed
    f'quoted words<img src="cid:ii_t1" alt="logo.png">{_ALMOST}',  # typed after an img
    'quoted words<span id="cid:ii_t1">PS &lt;logo.png&gt;</span>',  # text before
    'quoted words<span id="cid:ii_t1">logo.png&gt;</span>',  # no opening bracket
    'quoted words<span id="cid:ii_t1">&lt;logo.png</span>',  # no closing bracket
    'quoted words<span id="cid:ii_t1">&amp;lt;logo.png&amp;gt;</span>',  # escaped twice
    'quoted words<span id="cid:a>b">&lt;logo.png&gt;</span>',  # a bracket in the id
]


@pytest.mark.parametrize("fragment", _TEXT_LIKE_A_PLACEHOLDER)
@pytest.mark.parametrize("mode", ["refusal", "send"])
def test_find_own_draft_keeps_text_like_an_image_placeholder_unproven(
    mailroot, monkeypatch, fragment, mode
):
    _assert_unproven(mailroot, monkeypatch, _quoted(fragment), mode)


def test_find_own_draft_keeps_an_image_placeholder_before_the_quote_unproven(
    mailroot, monkeypatch
):
    # the text before the quote never loses an element: the quote itself is clean
    body = f"<div>Hi there</div>{_PH}" + _QUOTE_HTML
    _assert_unproven(mailroot, monkeypatch, body, "refusal")
    _assert_unproven(mailroot, monkeypatch, body, "send")


@pytest.mark.parametrize("placeholder", [_PH, _PH_EDIT])
@pytest.mark.parametrize("mode", ["refusal", "send"])
def test_find_own_draft_keeps_an_image_placeholder_below_the_quote_unproven(
    mailroot, monkeypatch, placeholder, mode
):
    # the rule ends at the last closing tag of the quote: where a PS would be, the
    # same element is text
    body = _quoted("quoted words") + f"<div>{placeholder}</div>"
    _assert_unproven(mailroot, monkeypatch, body, mode)


@pytest.mark.parametrize("mode", ["refusal", "send"])
def test_find_own_draft_keeps_an_image_placeholder_in_an_unclosed_quote_unproven(
    mailroot, monkeypatch, mode
):
    body = _quoted(f"quoted words{_PH}").replace("</blockquote>", "")
    assert "<blockquote" in body and "</blockquote>" not in body
    _assert_unproven(mailroot, monkeypatch, body, mode)


def _html_draft(markup: str):
    return email.message_from_string(
        "Content-Type: text/html; charset=utf-8\r\n\r\n" + markup,
        policy=email.policy.default,
    )


def test_split_quote_drops_an_image_placeholder_up_to_the_last_closing_tag():
    # two quotes side by side: the rule runs to the LAST closing tag
    markup = f"hi<blockquote>a</blockquote><blockquote>b{_PH}</blockquote>"
    assert "logo.png" not in mail_reply_cleanup._split_quote(_html_draft(markup))[1]


def test_split_quote_finds_an_upper_case_closing_tag():
    markup = f"hi<BLOCKQUOTE>a{_PH}</BLOCKQUOTE>"
    assert "logo.png" not in mail_reply_cleanup._split_quote(_html_draft(markup))[1]


def test_split_quote_leaves_a_space_for_a_dropped_image_placeholder():
    markup = f"hi<blockquote>foo{_PH}bar</blockquote>"
    assert mail_reply_cleanup._split_quote(_html_draft(markup))[1] == "foo bar"


def test_split_quote_ends_the_quote_where_it_ends_when_lower_casing_adds_characters():
    # "\u0130".lower() is two characters: an end found in the lower-cased text lies
    # past the real end, and the placeholder below the quote would be dropped
    grown = "\u0130" * 60
    assert len(grown.lower()) > len(grown)
    markup = f"own<blockquote>{grown}</blockquote>{_PH}"
    assert "logo.png" in mail_reply_cleanup._split_quote(_html_draft(markup))[1]


def test_read_draft_takes_no_postmark_from_a_received_field_of_white_space(mailroot):
    path = mailroot(22, _ORIGINAL, "s@x", _OTHER_BODY, url=_INBOX, received=True)
    payload = mail_index.emlx_payload(path.read_bytes())
    blank = payload.replace(b"Received:", b"X-Was:").replace(
        b"\r\n\r\n", "\r\nReceived: \u00a0\r\n\r\n".encode(), 1
    )
    path.write_bytes(str(len(blank)).encode() + b"\n" + blank + b"\n<plist></plist>")
    assert mail_reply_cleanup._read_draft(_INBOX, 22)[1]()[2] is False


def test_split_quote_keeps_placeholder_characters_in_a_plain_text_draft():
    msg = email.message_from_string(
        "Content-Type: text/plain; charset=utf-8\r\n\r\n"
        f"Hi there\r\n> quoted words {_PH}\r\n",
        policy=email.policy.default,
    )
    assert "logo.png" in mail_reply_cleanup._split_quote(msg)[1]


@pytest.mark.parametrize("inbox_first", [True, False])
@pytest.mark.parametrize("with_drafts", [True, False])
def test_find_own_draft_keeps_a_postmarked_inbox_row_of_another_message_unproven(
    mailroot, monkeypatch, inbox_first, with_drafts
):
    # a postmark alone proves nothing: the Message-ID must be a set-aside copy's
    first, second = (21, 22) if inbox_first else (22, 21)
    twin = (second, _SENT, "s@x", _OWN)
    inbox = (first, _INBOX, "other@x", _OTHER_BODY, True)
    rows = [inbox, twin] if inbox_first else [twin, inbox]
    got = _stored(
        mailroot,
        monkeypatch,
        [_DRAFT_ROW, *rows] if with_drafts else rows,
        sent_twins=True,
    )
    assert got.kind == "unproven" and got.reason == "inbox_row"


def test_read_draft_takes_the_postmark_from_a_received_header_only(mailroot):
    in_body = "<div>d</div>\r\nReceived: from mx2.example.net by mx1.example.net\r\n"
    mailroot(21, _ORIGINAL, "s@x", in_body, url=_INBOX)
    assert mail_reply_cleanup._read_draft(_INBOX, 21)[1]()[2] is False
    path = mailroot(22, _ORIGINAL, "s@x", _OTHER_BODY, url=_INBOX, received=True)
    payload = mail_index.emlx_payload(path.read_bytes())
    for other in (b"X-Received:", b"Received-SPF:"):
        changed = payload.replace(b"Received:", other)
        framed = str(len(changed)).encode() + b"\n" + changed + b"\n<plist></plist>"
        path.write_bytes(framed)
        assert mail_reply_cleanup._read_draft(_INBOX, 22)[1]()[2] is False
    empty = payload.replace(b"Received:", b"X-Was:").replace(
        b"\r\n\r\n", b"\r\nReceived: \r\n\r\n", 1
    )
    path.write_bytes(str(len(empty)).encode() + b"\n" + empty + b"\n<plist></plist>")
    assert mail_reply_cleanup._read_draft(_INBOX, 22)[1]()[2] is False  # an empty field


def _assert_unproven(mailroot, monkeypatch, body, mode):
    """One copy with ``body``: a refusal with the Drafts copy alone, or a send with a
    Sent twin alone. It is ``unproven`` with its reason, and nothing is claimed."""
    if mode == "refusal":
        got = _stored(mailroot, monkeypatch, [(20, _URL, "d@x", body)])
        assert got.kind == "unproven" and got.reason == "drafts_not_own"
    else:
        got = _stored(
            mailroot, monkeypatch, [(21, _SENT, "s@x", body)], sent_twins=True
        )
        assert got.kind == "unproven" and got.reason == "sent_not_own"


@pytest.mark.parametrize("token", ["&lt;&gt;", "&lt; &gt;", "&lt;&nbsp;&gt;"])
@pytest.mark.parametrize(
    "opening",
    [
        '<span id="cid:ii_t1">',
        '<span class="AppleTemporaryEditingElement" id="cid:ii_t1">',
    ],
)
def test_split_quote_keeps_a_white_space_image_placeholder_as_text(token, opening):
    # the token needs one character inside that is not white space, so an empty one is
    # text. The verdict is not pinned here: `_has_quote` compares letters and digits
    # only, so a quote that ends in `< >` is proven with or without this rule (05.2-19).
    msg = email.message_from_string(
        "Content-Type: text/html; charset=utf-8\r\n\r\n"
        f"<blockquote>quoted words{opening}{token}</span></blockquote>",
        policy=email.policy.default,
    )
    assert "<" in mail_reply_cleanup._split_quote(msg)[1]


# --- the strip in linear time (FIX-34, #611) -----------------------------------------
# The sweep's text decides a delete, so the linear form must give the output of the two
# calls `_split_quote` made before. They are written out here as the reference.

_OLD_BLOCK = r"(?is)<(script|style).*?</\1>"
_OLD_TAG = r"<[^>]+>"
# The bound of every timed test here. The slowest case takes 0.4 s on a busy Mac; the
# quadratic forms these tests guard against take 15 s or more.
_TIME_BOUND_S = 5.0


def _old_strip(chunk: str) -> str:
    chunk = re.sub(_OLD_BLOCK, "", chunk)
    return re.sub(_OLD_TAG, " ", chunk)


def _old_split_quote(msg) -> tuple[str, str]:
    """``_split_quote`` as it was before #611, with the two old calls."""
    markup = text = ""
    for part in msg.walk():
        kind = part.get_content_type()
        try:
            if kind == "text/html":
                markup += part.get_content()
            elif kind == "text/plain":
                text += part.get_content()
        except (LookupError, ValueError):
            continue
    if markup:
        cut = re.search(r"(?i)<blockquote\b", markup)
        at = cut.start() if cut else len(markup)
        parts = []
        quoted = markup[at:]
        closes = list(re.finditer(r"(?i)</blockquote>", quoted))
        end = closes[-1].end() if closes else 0
        for chunk in (
            markup[:at],
            mail_reply_cleanup._drop_placeholders(quoted[:end]) + quoted[end:],
        ):
            parts.append(html.unescape(_old_strip(chunk)))
        head, tail = parts
    else:
        lines = text.splitlines()
        at = next(
            (n for n, line in enumerate(lines) if line.startswith(">")), len(lines)
        )
        head, tail = "\n".join(lines[:at]), "\n".join(lines[at:])
    return squash_text(head.replace(chr(0xFFFC), "")), squash_text(tail)


def _strip(chunk: str) -> str:
    return mail_reply_cleanup._drop_tags(mail_reply_cleanup._drop_blocks(chunk))


def _html_message(markup: str):
    return email.message_from_string(
        "Content-Type: text/html; charset=utf-8\r\n\r\n" + markup,
        policy=email.policy.default,
    )


def test_linear_strip_token_list_holds_its_code_points():
    # by code point, so a glyph that an editor normalized fails here: the long s and the
    # two i's case-fold to `s` or `i`, and U+FFFC is the object mark
    points = {ord(char) for token in mailhtml._TOKENS for char in token}
    assert {0x17F, 0x130, 0x131, 0xFFFC} <= points


def test_linear_strip_keeps_both_old_pattern_objects():
    block, tag = mail_reply_cleanup._BLOCK, mail_reply_cleanup._TAG
    assert (block.pattern, tag.pattern) == (_OLD_BLOCK, _OLD_TAG)
    assert block.flags == re.IGNORECASE | re.DOTALL | re.UNICODE
    assert tag.flags == re.UNICODE


def test_linear_strip_is_fast_on_256_kb_of_script_openers():
    # the crafted mail of #611: this took 28 s, on the one native worker (0.01 s now)
    markup = "<script " * 32_000
    msg = _html_message(markup)
    started = time.perf_counter()
    got = mail_reply_cleanup._split_quote(msg)
    assert time.perf_counter() - started < _TIME_BOUND_S
    assert got == (markup.strip(), "")  # nothing closes, so no character is dropped


# the spellings an opener can have: a letter that case-folds to `s` or `i` matches too
_LONG_S, _DOTTED_I, _DOTLESS_I = chr(0x17F), chr(0x130), chr(0x131)
_OPENER_NAMES = [
    "script",
    f"{_LONG_S}cript",
    f"scr{_DOTTED_I}pt",
    f"scr{_DOTLESS_I}pt",
    f"{_LONG_S}cr{_DOTTED_I}pt",
    f"{_LONG_S}cr{_DOTLESS_I}pt",
    "style",
    f"{_LONG_S}tyle",
]
_WORST_CASES = {
    "256 KB of <": "<" * 256_000,
    "32,000 unclosed a openers": "<a " * 32_000,
    "8 opener names, 256 KB": "".join(f"<{name} " for name in _OPENER_NAMES) * 3_900,
    "2 MB of unclosed script openers": "<script " * 250_000,
}


@pytest.mark.parametrize("text", _WORST_CASES.values(), ids=_WORST_CASES.keys())
def test_linear_strip_is_fast_on_each_worst_case(text):
    started = time.perf_counter()
    got = _strip(text)
    assert time.perf_counter() - started < _TIME_BOUND_S
    assert got == text  # no closing tag and no `>`: nothing is a block or a tag


def _spellings(name: str) -> list[str]:
    """Every ASCII case spelling of ``name``."""
    return ["".join(s) for s in itertools.product(*((c, c.upper()) for c in name))]


def test_linear_strip_scans_once_for_every_case_spelling_of_a_name():
    # 96 ASCII case spellings of the two names, none closed, then 32 MB of text. The
    # spellings of one name share their closing tags, so two scans reach the end. A
    # memo keyed on the exact spelling scans 96 times (about 17 s against 0.4 s).
    names = _spellings("script") + _spellings("style")
    text = "".join(f"<{name} " for name in names) + "x" * 32_000_000
    started = time.perf_counter()
    got = _strip(text)
    assert time.perf_counter() - started < _TIME_BOUND_S
    assert len(names) == 96 and got == text


def test_linear_strip_keeps_a_failed_name_after_a_removed_block():
    # an unclosed script opener beside a closed style block, 20,000 times (460 KB).
    # The script name fails once and stays skipped. A memo that is cleared after each
    # removed block scans to the end from every script opener (about 29 s against
    # 0.02 s).
    text = "<script <style></style>" * 20_000
    started = time.perf_counter()
    got = _strip(text)
    assert time.perf_counter() - started < _TIME_BOUND_S
    assert got == "<script " * 20_000


def test_linear_strip_equals_the_old_patterns_on_generated_mail():
    rng = random.Random(611)
    differs = 0
    for _ in range(2_000):
        msg = mailhtml.message(mailhtml.reply_html(rng), rng)
        differs += mail_reply_cleanup._split_quote(msg) != _old_split_quote(msg)
    assert differs == 0


def test_linear_strip_equals_the_old_patterns_on_crafted_text():
    rng = random.Random(611)
    differs = 0
    for _ in range(20_000):
        text = mailhtml.crafted(rng)
        differs += (
            mail_reply_cleanup._drop_blocks(text) != re.sub(_OLD_BLOCK, "", text)
            or mail_reply_cleanup._drop_tags(text) != re.sub(_OLD_TAG, " ", text)
            or _strip(text) != _old_strip(text)
        )
    assert differs == 0


# --- the size cap, the second bound (FIX-34, #611, D9) -------------------------------


def test_max_body_chars_is_two_million():
    assert mail_reply_cleanup.MAX_BODY_CHARS == 2_000_000


@pytest.mark.parametrize(
    "url, kind, kw",
    [
        (_URL, "html", {}),  # the own Drafts copy alone, after a refusal
        (_SENT, "html", {"sent_twins": True}),  # the Sent copy alone, after a send
        (_URL, "plain", {}),
    ],
)
def test_find_own_draft_keeps_a_body_too_large_unproven(
    mailroot, monkeypatch, url, kind, kw
):
    # one character over the cap: the body is decoded and measured, and the strip does
    # not run, so nothing is claimed and nothing is set aside. Under the cap the same
    # copy reads as the call's own.
    monkeypatch.setattr(mail_reply_cleanup, "MAX_BODY_CHARS", 1_000)
    mailroot(20, _ORIGINAL, "d@x", _sized(1_001, kind), url=url, kind=kind)
    got = _find(monkeypatch, [(20, url)], **kw)
    assert got == mail_reply_cleanup.Draft("unproven", url, "<d@x>", "body_too_large")


def test_find_own_draft_reads_a_body_at_the_cap_not_too_large(mailroot, monkeypatch):
    monkeypatch.setattr(mail_reply_cleanup, "MAX_BODY_CHARS", 1_000)
    mailroot(20, _ORIGINAL, "d@x", _sized(1_000))
    assert _find(monkeypatch) == mail_reply_cleanup.Draft("one", _URL, "<d@x>")


def test_find_own_draft_does_not_cap_an_unthreaded_row_too_large(mailroot, monkeypatch):
    # the cap is for the body of a threaded candidate. A row of another thread is
    # skipped by its headers, whatever its size.
    monkeypatch.setattr(mail_reply_cleanup, "MAX_BODY_CHARS", 1_000)
    mailroot(20, "another-thread@x", "d@x", _sized(50_000))
    assert _find(monkeypatch) == mail_reply_cleanup.Draft("none")


def test_split_quote_checks_the_cap_before_any_strip_runs_too_large(monkeypatch):
    # "before any pattern runs": a body over the cap reaches none of the three steps
    def ran(chunk):
        pytest.fail("a strip step ran on a body over the cap")

    monkeypatch.setattr(mail_reply_cleanup, "MAX_BODY_CHARS", 1_000)
    for step in ("_drop_placeholders", "_drop_blocks", "_drop_tags"):
        monkeypatch.setattr(mail_reply_cleanup, step, ran)
    with pytest.raises(mail_reply_cleanup._BodyTooLarge):
        mail_reply_cleanup._split_quote(_html_message(_sized(1_001)))


def test_find_own_draft_measures_the_html_parts_together_too_large(monkeypatch):
    # two HTML parts, each under the cap and over it together. The strip runs on the
    # joined text, so the joined text is what the cap measures.
    raw = (
        'Content-Type: multipart/mixed; boundary="b"\r\n\r\n'
        f"--b\r\nContent-Type: text/html; charset=utf-8\r\n\r\n{_sized(600)}\r\n"
        f"--b\r\nContent-Type: text/html; charset=utf-8\r\n\r\n{' ' * 600}\r\n"
        "--b--\r\n"
    )
    msg = email.message_from_string(raw, policy=email.policy.default)
    assert [len(part.get_content()) for part in msg.iter_parts()] == [600, 600]
    monkeypatch.setattr(
        mail_reply_cleanup,
        "_read_draft",
        lambda url, rowid: (f"<{_ORIGINAL}>", lambda: ("<d@x>", lambda: msg, False)),
    )
    monkeypatch.setattr(mail_reply_cleanup, "MAX_BODY_CHARS", 2_000)
    assert _find(monkeypatch) == mail_reply_cleanup.Draft("one", _URL, "<d@x>")
    monkeypatch.setattr(mail_reply_cleanup, "MAX_BODY_CHARS", 1_000)
    assert _find(monkeypatch) == mail_reply_cleanup.Draft(
        "unproven", _URL, "<d@x>", "body_too_large"
    )


def test_split_quote_huge_reference_raises_as_before():
    # `html.unescape` refuses a decimal character reference of more than 4,300 digits.
    # Nothing changed here: the flow reports `read_failed` (tests/test_mail.py).
    msg = _html_message("<div>Hi there &#" + "9" * 5_000 + ";</div>")
    with pytest.raises(ValueError):
        mail_reply_cleanup._split_quote(msg)


# --- the combining-run scan before normalization (FIX-36, #626, D12) ----------------
# NFC sorts each run of combining marks, and a long run in mixed order took quadratic
# time (7 s for 120,001 marks, on the one native worker). The scan refuses such a text
# before NFC runs. `squash_text` and the compare functions did not change.


def _utf8_message(body: str, kind: str = "html"):
    raw = f"Content-Type: text/{kind}; charset=utf-8\r\n\r\n{body}".encode()
    return email.message_from_bytes(raw, policy=email.policy.default)


_CRAFTED_RUNS = {
    # one letter and 240,000 marks: class 232, then class 230 (the worst order)
    "240,001 characters in the quote": (
        f"<div>Hi</div><blockquote>a{_marks(240_000)}</blockquote>"
    ),
    # class 0, so a scan by combining class alone counts no mark in it
    "160,000 of U+0F73 above the quote": (
        f"<div>{chr(0x0F73) * 160_000}</div><blockquote>q</blockquote>"
    ),
}


@pytest.mark.parametrize("markup", _CRAFTED_RUNS.values(), ids=_CRAFTED_RUNS.keys())
def test_split_quote_refuses_a_combining_run_fast(markup):
    # without the scan: about 29 s and about 26 s
    assert (ord(_GRAVE), ord(_COMMA)) == (0x300, 0x315)
    msg = _utf8_message(markup)
    assert msg.get_content() == markup  # the marks reach the scan as written
    started = time.perf_counter()
    with pytest.raises(mail_reply_cleanup._CombiningRun):
        mail_reply_cleanup._split_quote(msg)
    assert time.perf_counter() - started < _TIME_BOUND_S


def test_split_quote_scans_the_text_that_nfc_sees_combining_run():
    # two runs of 20 with the object mark between them. Above the quote the mark is
    # removed before NFC runs, so NFC sees one run of 40. In the quote the mark stays.
    pieces = f"a{_marks(20)}{_OBJECT}{_marks(20)}"
    assert ord(_OBJECT) == 0xFFFC and not long_combining_run(pieces)
    above = _utf8_message(f"<div>{pieces}</div><blockquote>q</blockquote>")
    with pytest.raises(mail_reply_cleanup._CombiningRun):
        mail_reply_cleanup._split_quote(above)
    below = _utf8_message(f"<div>Hi</div><blockquote>{pieces}</blockquote>")
    before, after = mail_reply_cleanup._split_quote(below)
    assert before == "Hi" and _OBJECT in after


@pytest.mark.parametrize(
    "url, kind, kw",
    [
        (_URL, "html", {}),  # the own Drafts copy alone, after a refusal
        (_SENT, "html", {"sent_twins": True}),  # the Sent copy alone, after a send
        (_URL, "plain", {}),
    ],
)
def test_find_own_draft_keeps_a_combining_run_unproven(
    mailroot, monkeypatch, url, kind, kw
):
    # 31 marks on one letter of the quote, one over the limit: the text is not
    # normalized, so nothing is claimed and nothing is set aside
    mailroot(20, _ORIGINAL, "d@x", _marked_own(31, kind), url=url, kind=kind)
    got = _find(monkeypatch, [(20, url)], **kw)
    assert got == mail_reply_cleanup.Draft("unproven", url, "<d@x>", "combining_run")


def test_find_own_draft_judges_thirty_marks_as_before_combining_run(
    mailroot, monkeypatch
):
    # at the limit the same copies are judged as before: the Drafts copy is the call's
    # own, and after a send the Sent copy is the send itself
    tail = f"quoted w{_marks(30)}ords"
    mailroot(20, _ORIGINAL, "d@x", _marked_own(30))
    got = _find(monkeypatch, tail=tail)
    assert got == mail_reply_cleanup.Draft("one", _URL, "<d@x>")
    mailroot(21, _ORIGINAL, "s@x", _marked_own(30), url=_SENT)
    got = _find(monkeypatch, [(21, _SENT)], tail=tail, sent_twins=True)
    assert got == mail_reply_cleanup.Draft("none")


@pytest.mark.parametrize("name", ["own", "attribution", "signature", "tail"])
def test_find_own_draft_scans_its_own_arguments_combining_run(
    mailroot, monkeypatch, name
):
    # the attribution line and the tail come from the original, which another party
    # wrote, and every candidate row normalizes them. With 31 marks in one argument a
    # candidate row is not parsed and not compared.
    monkeypatch.setattr(
        mail_reply_cleanup,
        "_split_quote",
        lambda msg: pytest.fail("the body of a row was parsed"),
    )
    kw = {name: f"w{_marks(31)}ord"}
    mailroot(20, _ORIGINAL, "d@x", _OWN)
    got = _find(monkeypatch, **kw)
    assert got == mail_reply_cleanup.Draft("unproven", _URL, "<d@x>", "combining_run")
    mailroot(21, _ORIGINAL, "s@x", _OWN, url=_SENT)
    got = _find(monkeypatch, [(21, _SENT)], sent_twins=True, **kw)
    assert got == mail_reply_cleanup.Draft("unproven", _SENT, "<s@x>", "combining_run")
    # a threaded row that is no candidate keeps its own code
    archive = f"imap://{_ACCT}/Archive"
    mailroot(22, _ORIGINAL, "a@x", _OWN, url=archive)
    assert _find(monkeypatch, [(22, archive)], **kw).reason == "other_mailbox"
    # and a row of another thread still is not the call's own
    mailroot(30, "another-thread@x", "p@x", _OWN)
    assert _find(monkeypatch, [(30, _URL)], **kw) == mail_reply_cleanup.Draft("none")


def test_find_own_draft_scans_no_argument_that_is_none_combining_run(
    mailroot, monkeypatch
):
    # a reply without a quote has no attribution and no tail: None is skipped, and
    # the own copy is claimed as before
    mailroot(20, _ORIGINAL, "d@x", "<div>Hi there</div>")
    got = _find(monkeypatch, attribution=None, tail=None)
    assert got == mail_reply_cleanup.Draft("one", _URL, "<d@x>")


# The size of the differential: 2,000 bodies take about 1 s on this Mac.
_SCAN_BODIES = 2_000


def test_split_quote_with_the_scan_equals_the_old_output_combining_run():
    # every second body carries text in 13 scripts above and inside the quote
    rng = random.Random(626)
    refused = differs = marked = 0
    for n in range(_SCAN_BODIES):
        markup = mailhtml.reply_html(rng)
        if n % 2:
            above, inside = mailhtml.script_text(rng), mailhtml.script_text(rng)
            markup = markup.replace(
                "<blockquote", f"<div>{above}</div><blockquote", 1
            ).replace("</blockquote>", f"<p>{inside}</p></blockquote>", 1)
        msg = mailhtml.message(markup, rng)
        old = _old_split_quote(msg)
        marked += any(ord(char) in range(0x300, 0x370) for char in "".join(old))
        try:
            differs += mail_reply_cleanup._split_quote(msg) != old
        except mail_reply_cleanup._CombiningRun:
            refused += 1
    assert (refused, differs) == (0, 0)
    assert marked > 100  # the bodies do hold combining marks


# --- the bounded header read and message parse (FIX-36, #626; D13, D14) -------------
# A stored message of another party reached the standard library's parsers without a
# bound: 28 s for one crafted header field, 18 s or more for 120,000 small parts. The
# read is bounded now, and a row over a bound is `unproven` with its own code. Every
# value that decides a delete is the standard library's value, or no value.

_IRT = f"In-Reply-To: <{_ORIGINAL}>".encode()
_HEAD = b"Message-ID: <d@x>\r\n" + _IRT + b"\r\nMIME-Version: 1.0\r\n"
_HTML = b"Content-Type: text/html; charset=utf-8\r\n\r\n"
_MIXED = b'Content-Type: multipart/mixed; boundary="b"\r\n\r\n'
_PAD = b"X-Pad: " + b"p" * 60 + b"\r\n"  # one header field of 69 bytes
_ARCHIVE = f"imap://{_ACCT}/Archive"
_BOUND_NAMES = (
    "HEADER_READ_BYTES",
    "MAX_HEADER_FIELD_CHARS",
    "MAX_HEADER_FETCH_CHARS",
    "MAX_MESSAGE_BYTES",
    "MAX_MESSAGE_LINES",
    "MAX_MESSAGE_PARTS",
    "MAX_PARSED_ROWS",
)


def _framed(payload: bytes) -> bytes:
    """``payload`` in Mail's ``.emlx`` framing."""
    return str(len(payload)).encode() + b"\n" + payload + b"\n<plist></plist>"


def _put_raw(mailroot, rowid: int, payload: bytes, url: str = _URL) -> Path:
    """Store ``payload`` (one whole message, its header block included) as a row."""
    path = mailroot(rowid, _ORIGINAL, "x@x", "", url=url)
    path.write_bytes(_framed(payload))
    return path


def _unproven(url: str, reason: str, mid: str = "<d@x>"):
    return mail_reply_cleanup.Draft("unproven", url, mid, reason)


def _old_read(payload: bytes) -> tuple[str, str, bool]:
    """The header read as it was before #626: the whole message, the default policy."""
    head = email.parser.BytesParser(policy=email.policy.default).parsebytes(
        payload, headersonly=True
    )
    return (
        str(head.get("In-Reply-To", "") or ""),
        str(head.get("Message-ID", "") or ""),
        any(str(value).strip() for value in head.get_all("Received") or ()),
    )


def _new_read(url: str = _URL, rowid: int = 20) -> tuple[str, str, bool]:
    in_reply_to, more = mail_reply_cleanup._read_draft(url, rowid)
    mid, _, received = more()
    return in_reply_to, mid, received


class _Counted:
    """A file object that adds every byte that leaves it to ``counter``."""

    def __init__(self, file, counter):
        self._file, self._counter = file, counter

    def _took(self, data):
        self._counter[0] += len(data)
        return data

    def read(self, *args):
        return self._took(self._file.read(*args))

    def read1(self, *args):
        return self._took(self._file.read1(*args))

    def readline(self, *args):
        return self._took(self._file.readline(*args))

    def readlines(self, *args):
        lines = self._file.readlines(*args)
        self._counter[0] += sum(len(line) for line in lines)
        return lines

    def readinto(self, buffer):
        count = self._file.readinto(buffer)
        self._counter[0] += count or 0
        return count

    def __iter__(self):
        for line in self._file:
            yield self._took(line)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return self._file.__exit__(*exc)

    def __getattr__(self, name):
        return getattr(self._file, name)


def _count_bytes(monkeypatch, path: Path) -> list[int]:
    """``[count]`` of the bytes that leave the file at ``path`` from now on, whatever
    call reads it: ``Path.open`` and the builtin ``open`` (``read``, ``readline``,
    ``readinto``, iteration), ``Path.read_bytes`` and ``Path.read_text`` (the whole
    file)."""
    counter = [0]
    real_open, real_bytes, real_text = Path.open, Path.read_bytes, Path.read_text
    real_builtin = builtins.open

    def is_path(target) -> bool:
        return isinstance(target, (str, Path)) and Path(target) == path

    def counted(file, target):
        if is_path(target) and not isinstance(file, _Counted):
            return _Counted(file, counter)
        return file

    def whole(real):
        def read(self, *args, **kw):
            before = counter[0]
            data = real(self, *args, **kw)
            if is_path(self):  # replaces what an inner `open` counted for this call
                counter[0] = before + len(data)
            return data

        return read

    def path_open(self, *args, **kw):
        return counted(real_open(self, *args, **kw), self)

    def builtin_open(file, *args, **kw):
        return counted(real_builtin(file, *args, **kw), file)

    monkeypatch.setattr(Path, "open", path_open)
    monkeypatch.setattr(Path, "read_bytes", whole(real_bytes))
    monkeypatch.setattr(Path, "read_text", whole(real_text))
    monkeypatch.setattr(builtins, "open", builtin_open)
    monkeypatch.setattr(io, "open", builtin_open)
    return counter


def _big_row(size: int = 5_000_000) -> bytes:
    """The call's own copy with one base64 attachment of about ``size`` bytes."""
    lines = (b"A" * 76 + b"\r\n") * (size // 78)
    return (
        _HEAD
        + _MIXED
        + b"--b\r\n"
        + _HTML
        + _OWN.encode()
        + b"\r\n--b\r\nContent-Type: image/png\r\n"
        + b"Content-Transfer-Encoding: base64\r\n\r\n"
        + lines
        + b"--b--\r\n"
    )


def test_read_bound_constants():
    got = {name: getattr(mail_reply_cleanup, name) for name in _BOUND_NAMES}
    assert got == {
        "HEADER_READ_BYTES": 131_072,
        "MAX_HEADER_FIELD_CHARS": 998,
        "MAX_HEADER_FETCH_CHARS": 200_000,
        "MAX_MESSAGE_BYTES": 50_000_000,
        "MAX_MESSAGE_LINES": 1_000_000,
        "MAX_MESSAGE_PARTS": 1_000,
        "MAX_PARSED_ROWS": 8,
    }


def test_read_bound_policy_equals_the_default_policy_inside_the_bounds():
    refusal = mail_reply_cleanup._HeaderTooLarge
    default, bounded = email.policy.default, mail_reply_cleanup._bounded_policy
    for name in ("max_line_length", "linesep", "cte_type", "raise_on_defect", "utf8"):
        assert getattr(bounded(), name) == getattr(default, name), name
    assert bounded().content_manager is default.content_manager
    assert bounded().message_factory is default.message_factory
    rng = random.Random(626)
    parsed = refused = 0
    for n in range(200):
        kind = ("draft", "sent", "delivered", "heavy")[n % 4]
        head = email.parser.BytesParser(policy=default).parsebytes(
            mailhtml.mail_headers(rng, kind), headersonly=True
        )
        policy = bounded()
        for name, raw in head.raw_items():
            if len(raw) > 998:  # a long list of references, a seal: never fetched
                with pytest.raises(refusal):
                    policy.header_fetch_parse(name, raw)
                refused += 1
                continue
            got = policy.header_fetch_parse(name, raw)
            want = default.header_fetch_parse(name, raw)
            assert (str(got), got.name) == (str(want), want.name)
            assert [type(d) for d in got.defects] == [type(d) for d in want.defects]
            parsed += 1
    assert parsed > 2_000 and refused > 0
    # the field bound: the whole raw value, as the parser stores it
    assert str(bounded().header_fetch_parse("X-A", "a" * 998)) == "a" * 998
    with pytest.raises(refusal):
        bounded().header_fetch_parse("X-A", "a" * 999)
    # ... so a folded value counts with its fold bytes: 500 + CR LF + 1 + 496 = 999
    for tail, fits in ((495, True), (496, False)):
        raw = b"X-A: " + b"a" * 500 + b"\r\n " + b"b" * tail + b"\r\n\r\n"
        head = email.parser.BytesParser(policy=bounded()).parsebytes(raw, True)
        stored = dict(head.raw_items())["X-A"]
        assert len(stored) == 503 + tail and "\r\n" in stored
        if fits:
            assert str(head["X-A"]) == "a" * 500 + " " + "b" * tail
        else:
            with pytest.raises(refusal):
                head["X-A"]
    # the budget of one parse: 200,000 characters of field values, then a refusal
    policy = bounded()
    for _ in range(200):
        policy.header_fetch_parse("X-A", "a" * 998)
    policy.header_fetch_parse("X-A", "a" * 400)  # 199,600 + 400: the budget is used up
    with pytest.raises(refusal):
        policy.header_fetch_parse("X-A", "a")
    # a new policy object starts a new budget
    assert str(bounded().header_fetch_parse("X-A", "a")) == "a"


def test_read_bound_exception_classes_derive_from_exception():
    # `_split_quote` skips a part on LookupError and ValueError. A refusal that it
    # skips drops that part's text, and a row with more text then reads as the call's
    # own. So each class derives from Exception itself, and carries no text.
    for name in ("_CombiningRun", "_HeaderTooLarge", "_MessageTooLarge"):
        cls = getattr(mail_reply_cleanup, name)
        assert cls.__bases__ == (Exception,), name
        assert not issubclass(cls, (LookupError, ValueError)), name
        assert cls().args == ()


def _two_part_row() -> bytes:
    """Two HTML parts: the call's own copy, then more text in a part whose
    ``Content-Transfer-Encoding`` field is ``7bit`` and 600 spaces. The parser reads
    that field for the first time inside ``get_content()`` of the part."""
    return (
        _HEAD
        + _MIXED
        + b"--b\r\n"
        + _HTML
        + _OWN.encode()
        + b"\r\n--b\r\nContent-Type: text/html; charset=utf-8\r\n"
        + b"Content-Transfer-Encoding: 7bit"
        + b" " * 600
        + b"\r\n\r\n<div>and more text</div>\r\n--b--\r\n"
    )


def test_read_bound_a_refusal_inside_get_content_reaches_find_own_draft(
    mailroot, monkeypatch
):
    _put_raw(mailroot, 20, _two_part_row())
    # with the default budget the second part is read, and its text counts
    assert _find(monkeypatch) == _unproven(_URL, "drafts_not_own")
    # a budget that ends at that one fetch: every fetch before it fits 900 characters
    monkeypatch.setattr(mail_reply_cleanup, "MAX_HEADER_FETCH_CHARS", 900)
    left: list[tuple[bool, type]] = []
    real = email.message.MIMEPart.get_content

    def spy(part, *args, **kw):
        try:
            return real(part, *args, **kw)
        except Exception as exc:
            left.append(("and more text" in part._payload, type(exc)))
            raise

    monkeypatch.setattr(email.message.MIMEPart, "get_content", spy)
    # never `one`: a skipped refusal would drop the second part's text
    assert _find(monkeypatch) == _unproven(_URL, "header_too_large")
    assert left == [(True, mail_reply_cleanup._HeaderTooLarge)]


def _named_attachment(chars: int) -> bytes:
    """The call's own copy with one attachment whose file name has ``chars`` characters
    outside ASCII (3 bytes each in UTF-8), also as the RFC 2231 ``name`` parameter of
    ``Content-Type``, with Mail's ``x-unix-mode``."""
    name = chr(0x56FE) * chars + ".png"
    msg = email.message.EmailMessage(policy=email.policy.default)
    msg["Message-ID"], msg["In-Reply-To"] = "<d@x>", f"<{_ORIGINAL}>"
    msg.set_content(_OWN, subtype="html")
    msg.add_attachment(
        b"\x89PNG" * 10,
        maintype="image",
        subtype="png",
        filename=name,
        params={"x-unix-mode": "0644", "name": name},
    )
    return msg.as_bytes()


@pytest.mark.parametrize("chars, fits", [(83, True), (120, False)])
def test_read_bound_a_long_file_name_on_content_type(
    mailroot, monkeypatch, chars, fits
):
    # 83 characters are 253 bytes, the longest file name a Mac allows
    payload = _named_attachment(chars)
    parts = email.message_from_bytes(payload, policy=email.policy.default).walk()
    field = {key.lower(): raw for key, raw in list(parts)[-1].raw_items()}
    assert ord(chr(0x56FE)) == 0x56FE and "name*" in field["content-type"]
    assert (len(field["content-type"]) <= 998) is fits
    _put_raw(mailroot, 20, payload)
    got = _find(monkeypatch)
    if fits:
        assert got == mail_reply_cleanup.Draft("one", _URL, "<d@x>")
    else:
        assert got == _unproven(_URL, "header_too_large")


def test_read_bound_header_read_takes_only_the_first_bytes(mailroot, monkeypatch):
    path = _put_raw(mailroot, 20, _big_row())
    assert path.stat().st_size > 5_000_000
    counter = _count_bytes(monkeypatch, path)
    in_reply_to, more = mail_reply_cleanup._read_draft(_URL, 20)
    mid, body, received = more()
    assert (in_reply_to, mid, received) == (f"<{_ORIGINAL}>", "<d@x>", False)
    assert callable(body)
    assert 0 < counter[0] <= mail_reply_cleanup.HEADER_READ_BYTES
    # the counter does see a full read: the body of this row is the whole file
    body()
    assert counter[0] > 5_000_000


# The sizes of the three differentials: about 5 s together on this Mac (the chains run
# at three read sizes).
_HEADER_BLOCKS = 600
_HEADER_CHAINS = 5_000
_PARSED_MESSAGES = 300


def test_read_bound_header_read_equals_the_old_read_on_generated_headers(
    mailroot, monkeypatch
):
    path = _put_raw(mailroot, 20, b"x")
    monkeypatch.setattr(mail_reply_cleanup, "_emlx_path", lambda url, rowid: path)
    rng = random.Random(626)
    differs = threaded = stamped = cut = 0
    for n in range(_HEADER_BLOCKS):
        block = mailhtml.mail_headers(
            rng, ("draft", "sent", "delivered", "heavy")[n % 4]
        )
        # every 50th body is larger than the header read
        body = b"<div>Hi</div>" * rng.randint(1, 60_000 if n % 50 == 0 else 40)
        path.write_bytes(_framed(block + body))
        old = _old_read(block + body)
        differs += _new_read() != old  # a refusal fails the test: it raises
        threaded += bool(old[0])
        stamped += old[2]
        cut += path.stat().st_size > mail_reply_cleanup.HEADER_READ_BYTES
    assert differs == 0
    assert min(threaded, stamped, cut) >= 10  # the blocks do hold what is compared


@pytest.mark.parametrize("read_bytes", [131_072, 256, 64])
def test_read_bound_header_read_is_equal_or_refuses_on_crafted_chains(
    mailroot, monkeypatch, read_bytes
):
    path = _put_raw(mailroot, 20, b"x")
    monkeypatch.setattr(mail_reply_cleanup, "_emlx_path", lambda url, rowid: path)
    monkeypatch.setattr(mail_reply_cleanup, "HEADER_READ_BYTES", read_bytes)
    rng = random.Random(626)
    equal = refused = differs = 0
    for _ in range(_HEADER_CHAINS):
        payload = mailhtml.header_chain(rng)
        path.write_bytes(_framed(payload))
        if not payload:  # an empty payload is no message: the row is unreadable
            assert mail_reply_cleanup._read_draft(_URL, 20) is None
            continue
        try:
            new = _new_read()
        except mail_reply_cleanup._HeaderTooLarge:
            refused += 1
            continue
        equal += new == _old_read(payload)
        differs += new != _old_read(payload)
    assert differs == 0 and equal > _HEADER_CHAINS // 2
    if read_bytes == 131_072:
        assert refused == 0
    else:
        assert refused > 0  # the small read does cut header blocks


def test_read_bound_a_cut_header_block_keeps_only_fields_before_its_last(
    mailroot, monkeypatch
):
    monkeypatch.setattr(mail_reply_cleanup, "HEADER_READ_BYTES", 256)
    other, body = b"In-Reply-To: <other@x>\r\n", b"\r\n<div>x</div>"
    rows = {
        # another thread, read before the cut and not the last field there: skipped
        20: other + b"Subject: s\r\n" + _PAD * 5 + body,
        # in the thread, but the field lies after the cut: the read cannot say "absent"
        21: b"Subject: s\r\n" + _PAD * 5 + _IRT + b"\r\n" + body,
        # in the thread, and the cut runs through the id: the last field before the cut
        22: b"Subject: sssss\r\n" + _PAD * 3 + _IRT + b"\r\n" + body,
        # in the thread, postmarked, and its Message-ID lies after the cut
        23: _IRT
        + b"\r\nReceived: from a by b\r\n"
        + _PAD * 4
        + b"Message-ID: <d@x>\r\n"
        + body,
    }
    for rowid, payload in rows.items():
        raw = _put_raw(mailroot, rowid, payload).read_bytes()
        assert len(raw) > 256 and b"\r\n\r\n" not in raw[:256]  # the block is cut
    # row 22 read whole is in the thread; its cut field alone names no known thread, so
    # a read that kept the last field would skip the row
    cut = mail_index.emlx_payload(_put_raw(mailroot, 22, rows[22]).read_bytes()[:256])
    assert b">" not in cut.rpartition(b"In-Reply-To: <")[2]
    assert _old_read(rows[22])[0] == f"<{_ORIGINAL}>" != _old_read(cut)[0]
    assert _find(monkeypatch, [(20, _URL)]) == mail_reply_cleanup.Draft("none")
    for rowid in (21, 22, 23):
        got = _find(monkeypatch, [(rowid, _URL)])
        assert got == _unproven(_URL, "header_too_large", ""), rowid


def test_read_bound_a_cut_header_block_never_proves_a_postmark(mailroot, monkeypatch):
    # after a send: the Sent copy is set aside, and an INBOX row with its Message-ID
    # is the delivered copy only with a postmark. A postmark after the cut is not read.
    inbox = (
        b"Message-ID: <s@x>\r\n"
        + _IRT
        + b"\r\n"
        + _PAD * 4
        + b"Received: from a by b\r\n\r\n<div>x</div>"
    )
    mailroot(21, _ORIGINAL, "s@x", _OWN, url=_SENT)
    _put_raw(mailroot, 22, inbox, url=_INBOX)
    rows = [(21, _SENT), (22, _INBOX)]
    # read whole, the row is the delivered copy and nothing is left to report
    got = _find(monkeypatch, rows, sent_twins=True)
    assert got == mail_reply_cleanup.Draft("none")
    monkeypatch.setattr(mail_reply_cleanup, "HEADER_READ_BYTES", 256)
    got = _find(monkeypatch, rows, sent_twins=True)
    assert got == _unproven(_INBOX, "header_too_large", "")


_DOTS = b"<" + b"." * 100_000 + b"@x>"
_CRAFTED_FIELDS = {
    # (the stored message, its mailbox, the verdict)
    "In-Reply-To of 100,000 dots": (
        b"In-Reply-To: " + _DOTS + b"\r\nMessage-ID: <d@x>\r\n\r\nx",
        _INBOX,
        ("unproven", _INBOX, "", "header_too_large"),
    ),
    # a row of another thread: its Message-ID is not needed and not parsed
    "Message-ID of 100,000 dots outside the thread": (
        b"In-Reply-To: <other@x>\r\nMessage-ID: " + _DOTS + b"\r\n\r\nx",
        _URL,
        ("none",),
    ),
    # 20,000 nested comments: the parser would raise RecursionError
    "Message-ID of 20,000 ( in the thread": (
        _IRT + b"\r\nMessage-ID: " + b"(" * 20_000 + b"\r\n\r\nx",
        _URL,
        ("unproven", _URL, "", "header_too_large"),
    ),
    # the parser reads the top-level Content-Type of every row when the header read
    # ends, so that field is bounded for a row of another thread too
    "Content-Type of 80,000 bytes outside the thread": (
        b"In-Reply-To: <other@x>\r\nContent-Type: text/html;"
        + b" ; " * 26_666
        + b"\r\n\r\nx",
        _URL,
        ("unproven", _URL, "", "header_too_large"),
    ),
}


@pytest.mark.parametrize(
    "payload, url, verdict", _CRAFTED_FIELDS.values(), ids=_CRAFTED_FIELDS.keys()
)
def test_read_bound_find_own_draft_is_fast_on_a_crafted_field(
    mailroot, monkeypatch, payload, url, verdict
):
    # without the field bound, and with an eager Message-ID: about 28 s each
    _put_raw(mailroot, 20, payload, url=url)
    started = time.perf_counter()
    got = _find(monkeypatch, [(20, url)])
    assert time.perf_counter() - started < _TIME_BOUND_S
    assert got == mail_reply_cleanup.Draft(*verdict)


def test_read_bound_a_crafted_message_id_outside_the_thread_does_not_hide_the_own_copy(
    mailroot, monkeypatch
):
    # the one verdict that moves away from `unproven`: before #626 the Message-ID of
    # every new row was parsed, and this row made the whole sweep `read_failed`
    crafted = b"In-Reply-To: <other@x>\r\nMessage-ID: " + b"(" * 20_000 + b"\r\n\r\nx"
    with pytest.raises(RecursionError):
        _old_read(crafted)
    mailroot(20, _ORIGINAL, "d@x", _OWN)
    _put_raw(mailroot, 21, crafted, url=_INBOX)
    got = _find(monkeypatch, [(20, _URL), (21, _INBOX)])
    assert got == mail_reply_cleanup.Draft("one", _URL, "<d@x>")


_MARKED = {
    # where the parser raises: (the stored message, the Message-ID in the verdict)
    "the header read": (
        b"Message-ID: <d@x>\r\nIn-Reply-To: <BOOM@x>\r\n" + _HTML + _OWN.encode(),
        "",
    ),
    # the parser reads the top-level Content-Type when the header read ends
    "the header read, at Content-Type": (
        _HEAD + b"Content-Type: text/html; x=BOOM\r\n\r\n" + _OWN.encode(),
        "",
    ),
    "more()": (
        b"Message-ID: <BOOM@x>\r\n" + _IRT + b"\r\n" + _HTML + _OWN.encode(),
        "",
    ),
    "the body parse": (
        _HEAD
        + _MIXED
        + b"--b\r\nContent-Type: text/html; x=BOOM\r\n\r\n"
        + _OWN.encode()
        + b"\r\n--b--\r\n",
        "<d@x>",
    ),
}


@pytest.mark.parametrize("payload, mid", _MARKED.values(), ids=_MARKED.keys())
def test_read_bound_a_parser_error_stays_with_its_row(
    mailroot, monkeypatch, payload, mid
):
    real_parse = email.policy.EmailPolicy.header_fetch_parse

    def parse(policy, name, value):
        if "BOOM" in value:
            raise RecursionError  # what 990 nested comments do in the real parser
        return real_parse(policy, name, value)

    monkeypatch.setattr(email.policy.EmailPolicy, "header_fetch_parse", parse)
    _put_raw(mailroot, 20, payload)
    mailroot(21, _ORIGINAL, "a@x", _OWN, url=_ARCHIVE)
    mailroot(22, "another-thread@x", "p@x", _OWN)
    seen: list[int] = []
    real_read = mail_reply_cleanup._read_draft

    def spy(url, rowid):
        seen.append(rowid)
        return real_read(url, rowid)

    monkeypatch.setattr(mail_reply_cleanup, "_read_draft", spy)
    assert _find(monkeypatch) == _unproven(_URL, "read_failed", mid)
    # the other rows are still judged, and the first row names the branch
    seen.clear()
    got = _find(monkeypatch, [(20, _URL), (21, _ARCHIVE), (22, _URL)])
    assert got == mail_reply_cleanup.Draft("unproven", reason="read_failed")
    assert seen == [20, 21, 22]
    got = _find(monkeypatch, [(21, _ARCHIVE), (20, _URL), (22, _URL)])
    assert got == mail_reply_cleanup.Draft("unproven", reason="other_mailbox")


def test_read_bound_a_native_error_still_raises(mailroot, monkeypatch):
    # an index that cannot be read is `unavailable` in the flow, never `read_failed`
    mailroot(20, _ORIGINAL, "d@x", _OWN)

    def gone(*args):
        raise NativeError("the index cannot be read")

    with monkeypatch.context() as patch:
        patch.setattr(mail_reply_cleanup, "_read_draft", gone)
        with pytest.raises(NativeError):
            _find(patch)
    monkeypatch.setattr(mail_reply_cleanup, "new_rows", gone)
    with pytest.raises(NativeError):
        mail_reply_cleanup.find_own_draft(10, _ORIGINAL, "Hi there", None, **_KW)


def test_read_bound_message_over_the_byte_bound_is_not_read(mailroot, monkeypatch):
    monkeypatch.setattr(mail_reply_cleanup, "HEADER_READ_BYTES", 256)
    empty = len(_framed(_HEAD + _HTML + _sized(1_500).encode())) - 1_500
    path = _put_raw(mailroot, 20, _HEAD + _HTML + _sized(2_000 - empty).encode())
    assert path.stat().st_size == 2_000
    counter = _count_bytes(monkeypatch, path)
    # at the bound the row is read whole and is the call's own
    monkeypatch.setattr(mail_reply_cleanup, "MAX_MESSAGE_BYTES", 2_000)
    assert _find(monkeypatch) == mail_reply_cleanup.Draft("one", _URL, "<d@x>")
    assert counter[0] == 256 + 2_000
    # over the bound the header read is the only read: the size comes from `stat`
    counter[0] = 0
    monkeypatch.setattr(mail_reply_cleanup, "MAX_MESSAGE_BYTES", 1_999)
    assert _find(monkeypatch) == _unproven(_URL, "message_too_large")
    assert 0 < counter[0] <= 256


@pytest.mark.parametrize("eol", [b"\n", b"\r\n", b"\r"], ids=["LF", "CRLF", "CR"])
def test_read_bound_message_over_the_line_bound_is_not_parsed(
    mailroot, monkeypatch, eol
):
    monkeypatch.setattr(mail_reply_cleanup, "MAX_MESSAGE_LINES", 100)
    head = [b"Message-ID: <d@x>", _IRT, _HTML.rstrip(), b""]

    def message(line_ends: int) -> bytes:
        gap = [b""] * (line_ends - len(head) - 1)
        lines = [*head, b"<div>Hi there</div>", *gap, _QUOTE_HTML.encode()]
        assert len(lines) - 1 == line_ends
        return eol.join(lines)

    # 100 line ends are parsed: a CRLF is one line end, not two
    _put_raw(mailroot, 20, message(100))
    assert _find(monkeypatch) == mail_reply_cleanup.Draft("one", _URL, "<d@x>")
    _put_raw(mailroot, 20, message(101))
    monkeypatch.setattr(
        mail_reply_cleanup.email,
        "message_from_bytes",
        lambda *args, **kw: pytest.fail("a message over the line bound was parsed"),
    )
    assert _find(monkeypatch) == _unproven(_URL, "message_too_large")


_PART = b"--b\r\nContent-Type: text/html\r\n\r\nx\r\n"
_MANY_PARTS = {
    # (one part, the line end of the parts, the line end of the header block, verdict)
    "CRLF": (_PART, b"\r\n", b"\r\n", ("<d@x>", "message_too_large")),
    # no field in a part. The parser reads the Content-Type of the container once for
    # each part, so the budget of field values stops these parts too (30,000 of them
    # in 0.24 s); the count refuses them before the parse, with its own code.
    "parts without a field": (
        b"--b\r\n\r\nx\r\n",
        b"\r\n",
        b"\r\n",
        ("<d@x>", "message_too_large"),
    ),
    "bare CR in the parts": (_PART, b"\r", b"\r\n", ("<d@x>", "message_too_large")),
    # no LF at all: the end of the header block is not provable in the header read
    "bare CR everywhere": (_PART, b"\r", b"\r", ("", "header_too_large")),
}


@pytest.mark.parametrize(
    "part, eol, head_eol, verdict", _MANY_PARTS.values(), ids=_MANY_PARTS.keys()
)
def test_read_bound_find_own_draft_is_fast_on_120_000_parts(
    mailroot, monkeypatch, part, eol, head_eol, verdict
):
    # a Sent copy after a send. The count of part-delimiter lines refuses it before
    # the parse. Without the count the budget of field values still stops the parse
    # (with the code `header_too_large`); without both it takes 16 s or more.
    parts = (part * 120_000 + b"--b--\r\n").replace(b"\r\n", eol)
    payload = (_HEAD + _MIXED).replace(b"\r\n", head_eol) + parts
    assert len(payload) > 1_200_000
    _put_raw(mailroot, 21, payload, url=_SENT)
    started = time.perf_counter()
    got = _find(monkeypatch, [(21, _SENT)], sent_twins=True)
    assert time.perf_counter() - started < _TIME_BOUND_S
    mid, reason = verdict
    assert got == _unproven(_SENT, reason, mid)


def test_read_bound_find_own_draft_is_fast_on_a_crafted_content_type(
    mailroot, monkeypatch
):
    # one field of 80,000 bytes on a part, so inside the body parse: 29 to 34 s
    # without the bound
    field = b"Content-Type: text/html;" + b" ; " * 26_666
    payload = _HEAD + _MIXED + b"--b\r\n" + field + b"\r\n\r\nx\r\n--b--\r\n"
    _put_raw(mailroot, 21, payload, url=_SENT)
    started = time.perf_counter()
    got = _find(monkeypatch, [(21, _SENT)], sent_twins=True)
    assert time.perf_counter() - started < _TIME_BOUND_S
    assert got == _unproven(_SENT, "header_too_large")


def test_read_bound_the_budget_stops_many_worst_fields(mailroot, monkeypatch):
    # 1,500 parts, each with a field at the field bound in its worst shape (11 ms for
    # each part): about 16 s without the budget of one parse
    monkeypatch.setattr(mail_reply_cleanup, "MAX_MESSAGE_PARTS", 2_000)
    worst = b"text/html" + b"; =" * 329
    assert len(worst) == 996
    part = b"--b\r\nContent-Type: " + worst + b"\r\n\r\nx\r\n"
    _put_raw(mailroot, 21, _HEAD + _MIXED + part * 1_500 + b"--b--\r\n", url=_SENT)
    started = time.perf_counter()
    got = _find(monkeypatch, [(21, _SENT)], sent_twins=True)
    assert time.perf_counter() - started < _TIME_BOUND_S
    assert got == _unproven(_SENT, "header_too_large")


def test_read_bound_at_most_eight_candidate_rows_are_parsed(mailroot, monkeypatch):
    calls: list[int] = []
    real = mail_reply_cleanup._split_quote
    monkeypatch.setattr(
        mail_reply_cleanup, "_split_quote", lambda msg: calls.append(1) or real(msg)
    )
    # nine Sent copies, each the send's own copy in content
    rows = [(21 + n, _SENT, f"s{n}@x", _OWN) for n in range(9)]
    got = _stored(mailroot, monkeypatch, rows[:8], sent_twins=True)
    assert got == mail_reply_cleanup.Draft("none") and len(calls) == 8
    calls.clear()
    got = _stored(mailroot, monkeypatch, rows, sent_twins=True)
    assert got == _unproven(_SENT, "too_many_rows", "<s8@x>") and len(calls) == 8


def test_read_bound_a_file_that_changed_between_the_reads_is_unproven(
    mailroot, monkeypatch
):
    monkeypatch.setattr(mail_reply_cleanup, "HEADER_READ_BYTES", 256)
    path = _put_raw(mailroot, 20, _HEAD + _HTML + _sized(900).encode())
    assert path.stat().st_size > 256
    assert _find(monkeypatch) == mail_reply_cleanup.Draft("one", _URL, "<d@x>")
    real = Path.read_bytes
    monkeypatch.setattr(
        Path,
        "read_bytes",
        lambda self: real(self).replace(b"Message-ID: <d@x>", b"Message-ID: <e@x>"),
    )
    # the second read starts with other bytes than the header read: nothing is claimed
    assert _find(monkeypatch) == _unproven(_URL, "read_failed")


def _own_multipart(mid: bytes) -> bytes:
    """The call's own copy as a multipart message (two part-delimiter lines)."""
    return (
        b"Message-ID: <"
        + mid
        + b">\r\n"
        + _IRT
        + b'\r\nContent-Type: multipart/alternative; boundary="b"\r\n\r\n--b\r\n'
        + _HTML
        + _OWN.encode()
        + b"\r\n--b--\r\n"
    )


_SMALL_BOUNDS = [
    ("HEADER_READ_BYTES", 64, "header_too_large"),
    ("MAX_HEADER_FIELD_CHARS", 10, "header_too_large"),
    ("MAX_HEADER_FETCH_CHARS", 40, "header_too_large"),
    ("MAX_MESSAGE_BYTES", 100, "message_too_large"),
    ("MAX_MESSAGE_LINES", 3, "message_too_large"),
    ("MAX_MESSAGE_PARTS", 1, "message_too_large"),
    ("MAX_PARSED_ROWS", 0, "too_many_rows"),
]


@pytest.mark.parametrize("name, value, reason", _SMALL_BOUNDS)
def test_read_bound_no_bound_makes_a_row_claimable(
    mailroot, monkeypatch, name, value, reason
):
    # the safe direction: a row over a bound is `unproven`. It is never the call's own
    # copy (which the flow deletes) and never the send's own copy (which is set aside).
    assert {case[0] for case in _SMALL_BOUNDS} == set(_BOUND_NAMES)
    _put_raw(mailroot, 20, _own_multipart(b"d@x"))
    _put_raw(mailroot, 21, _own_multipart(b"s@x"), url=_SENT)
    drafts, sent = [(20, _URL)], [(21, _SENT)]
    # inside the bounds the rows are the call's own and the send's own
    assert _find(monkeypatch, drafts) == mail_reply_cleanup.Draft("one", _URL, "<d@x>")
    got = _find(monkeypatch, sent, sent_twins=True)
    assert got == mail_reply_cleanup.Draft("none")
    monkeypatch.setattr(mail_reply_cleanup, name, value)
    for rows, kw in (
        (drafts, {}),
        (sent, {"sent_twins": True}),
        (drafts + sent, {"sent_twins": True}),
    ):
        got = _find(monkeypatch, rows, **kw)
        assert got.kind == "unproven" and got.reason == reason, (rows, got)


def test_read_bound_message_parse_equals_the_old_parse_on_generated_messages(
    mailroot, monkeypatch
):
    path = _put_raw(mailroot, 20, b"x")
    monkeypatch.setattr(mail_reply_cleanup, "_emlx_path", lambda url, rowid: path)
    refusals = (mail_reply_cleanup._HeaderTooLarge, mail_reply_cleanup._MessageTooLarge)
    rng = random.Random(626)
    refused = differs = attached = 0
    for n in range(_PARSED_MESSAGES):
        if n % 10 == 0:  # with 1 to 100 attachments, each named on Content-Type
            payload = mailhtml.message_with_attachments(
                rng, rng.choice([1, 5, 30, 100])
            )
            attached += payload.count(b"name*")
        else:
            payload = mailhtml.message(mailhtml.reply_html(rng), rng).as_bytes()
        path.write_bytes(_framed(payload))
        old = mail_reply_cleanup._split_quote(
            email.message_from_bytes(payload, policy=email.policy.default)
        )
        try:
            body = mail_reply_cleanup._read_draft(_URL, 20)[1]()[1]
            differs += mail_reply_cleanup._split_quote(body()) != old
        except refusals:
            refused += 1
    assert (refused, differs) == (0, 0)
    assert attached > 500  # the messages do hold named attachments


def test_read_bound_a_normal_5_mb_message_is_judged_as_before(mailroot, monkeypatch):
    path = _put_raw(mailroot, 20, _big_row())
    assert path.stat().st_size > 5_000_000
    assert _find(monkeypatch) == mail_reply_cleanup.Draft("one", _URL, "<d@x>")
