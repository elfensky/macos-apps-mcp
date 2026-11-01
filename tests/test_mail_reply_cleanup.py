"""FIX-16 (#348): the Drafts sweep of a refused native reply (facts section 4e
`Refusal cleanup`) — the read half. The index and the ``.emlx`` files are fixtures in a
tmp dir; nothing here touches Mail or the real Envelope Index."""

from __future__ import annotations

import email
import shutil
import sqlite3
from pathlib import Path

import pytest

from macos_apps_mcp.adapters import mail_index, mail_reply_cleanup
from macos_apps_mcp.errors import NativeError

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


def _emlx(in_reply_to: str, mid: str, body: str, kind: str = "html") -> bytes:
    raw = (
        f"Message-ID: <{mid}>\r\nIn-Reply-To: <{in_reply_to}>\r\n"
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

    def put(rowid, in_reply_to, mid, body, *, url=_URL, kind="html", partial=False):
        account, _, path = url.partition("://")[2].partition("/")
        folder = tmp_path / "V10" / account
        for segment in path.replace("%5B", "[").replace("%5D", "]").split("/"):
            folder = folder / f"{segment.replace('%20', ' ')}.mbox"
        shard = "/".join(reversed(str(rowid // 1000))) if rowid >= 1000 else ""
        box = folder / "GUID" / "Data" / shard / "Messages"
        box.mkdir(parents=True, exist_ok=True)
        name = f"{rowid}.partial.emlx" if partial else f"{rowid}.emlx"
        (box / name).write_bytes(_emlx(in_reply_to, mid, body, kind))
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
    assert _find(monkeypatch, rows) == mail_reply_cleanup.Draft("unproven")
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
        (_OWN, f"imap://{_ACCT}/Verzonden"),  # a localized Sent is not matched
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
    for name in ("Sent", "Sent%20Messages", "Sent%20Items", "%5BGmail%5D/Sent%20Mail"):
        assert sent(f"imap://{_ACCT}/{name}"), name
    assert sent(f"imap://{_ACCT}/%5BGoogle%20Mail%5D/All%20Mail")
    for name in ("Verzonden", "Projects/Sent", "All%20Mail", "%5BArchive%5D/Sent"):
        assert not sent(f"imap://{_ACCT}/{name}"), name
