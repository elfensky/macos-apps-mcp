"""The Drafts sweep of a refused native reply (FIX-16, #348; facts section 4e
`Refusal cleanup`).

Mail autosaves a scripted reply into Drafts 5 to 70 s after its window opens, and that
copy survives a later discard (the sitting: 5 s after the open, still there after the
discard and after the send). So a reply that is refused after its window opened is not
clean until the Drafts copy, if one landed, is found and deleted.

This module is the READ half: it finds the call's own autosave copy and proves it is the
call's own. The delete is a Mail script in ``mail_outgoing`` (``_SWEEP_DELETE``).
Reading the Envelope Index and the ``.emlx`` files is not a Mail call, so the wait
before the read adds no load on Mail.

**Scope.** The copy lands in the Drafts of the account the reply is SENT FROM, which is
not always the account that holds the original (spike 005: a message from a family
address in the owner's inbox got a reply from that address's account). The Drafts
mailbox of an account cannot be named reliably either: the Envelope Index has no
mailbox role (``mailboxes`` holds a url and counters), the draft flag in
``messages.flags`` was set on 1 of 287 stored drafts, and a Drafts can be localized
(``Concepten``) or sit beside a user folder named ``Drafts``. So no mailbox is guessed.
The baseline is the highest ``messages.ROWID`` (the column is AUTOINCREMENT, so a new
row always sorts above it) and the read looks at EVERY row above it, in any mailbox of
any account. "No copy" therefore means no new row anywhere threads to the original.

**Selector** (a design rule, run as one step on device only in 05.2-13): a new row
whose ``In-Reply-To`` header is the original. A hand reply to the same original matches
too, so the copy is claimed (``one``) only when ALL of these hold: exactly one row
matches and nothing new was unreadable; the row is not above the index top read right
after the discard answered (``landed_by``: a row that landed after the window was gone
is not proven the window's own); it has a Message-ID; it sits in a mailbox that is named
``Drafts`` / ``Draft`` (directly under the account or under ``[Gmail]`` /
``[Google Mail]``); the squashed text before its quote EQUALS the call's own full
squashed text, optionally followed by the signature Mail put into this reply (equal
except for white space), then by Mail's own attribution line for this original; AND
it carries the original's quote and nothing after it (its tail, by letters and digits,
as the insert's confirmation compares it, is the LAST thing in the draft; Mail's own
inline-image placeholders inside the quote are not text, owner decision 2026-11-18),
or, for a reply without a quote, nothing at all after the text. Anything else is
``unproven``: reported with the refusal, never deleted.

The selector reads the index and the files only. The flow adds what it alone knows
before it deletes the claimed row (``mail_outgoing._ReplyFlow._may_claim``): the span
from the baseline read to the discard is within the open's timeout; the row is in the
account the reply is sent from (the From of the outgoing message, matched to the one
account that holds that address); and no scripted compose window for this original was
open at the start. The baseline read comes right before the ``reply`` verb, after the
slow lookup of the original, so a row that landed during that lookup is never new.

**After a send** (``reply_all``, owner decision 2026-11-01) the same sweep runs once the
window is gone. The sent message creates rows of its own, threaded to the original: its
Sent copy and, on Gmail, an All Mail twin. ``find_own_draft(..., sent_twins=True)`` sets
those aside (in a ``Sent`` mailbox or Gmail's ``All Mail``, with a Message-ID, the
call's exact text and the original's quote), and so is the delivered copy of the same
message when it landed in an INBOX on this Mac (the top-level INBOX of an account, with
the Message-ID of a copy set aside and a mail server's ``Received`` header, owner
decision 2026-11-18); the Drafts copy is then judged by the rules above,
and any other threaded row keeps the result ``unproven``. The sweep never deletes
anything outside the one Drafts row it proved, by that row's own message id.

Every ``unproven`` verdict names its branch in ``Draft.reason``, one of a fixed set of
codes (never message text, a Message-ID, a url or an address).

The ROWID column is AUTOINCREMENT, so a new row always sorts above the baseline. That is
checked once per index file at run time (``index_top``): an index without it is
unreadable for the sweep.
"""

from __future__ import annotations

import codecs
import email
import email.parser
import email.policy
import html
import re
import unicodedata
from pathlib import Path
from typing import NamedTuple

from .. import runtime
from ..errors import NativeError
from ..text import long_combining_run, squash_text
from . import mail_index, mailbox_url
from .mail_addressing import _norm_mid

# Only what the queries read: present in every Envelope Index shape (also the Sequoia
# shape, where message_global_data loses its Message-ID column).
_FINGERPRINT: dict[str, set[str]] = {
    "messages": {"ROWID", "mailbox", "deleted"},
    "mailboxes": {"ROWID", "url"},
}

_TOP_SQL = "SELECT COALESCE(MAX(ROWID), 0) FROM messages"
_TABLE_SQL = "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'messages'"

_NEW_ROWS_SQL = """
SELECT m.ROWID, mb.url FROM messages m
JOIN mailboxes mb ON mb.ROWID = m.mailbox
WHERE m.ROWID > ? AND m.deleted = 0
ORDER BY m.ROWID LIMIT ?
"""

# More new rows than this in the sweep window (a mailbox sync) are not all read; the
# sweep then proves nothing. Far above the 0 to 10 a quiet minute brings.
MAX_NEW_ROWS = 300

# The strip does not run on a larger decoded body (#611): the body is decoded and
# measured only. The strip of a crafted 2 MB body took 0.06 to 0.15 s in the prototype
# run of 2026-11-20, and up to 0.35 s on a busy Mac.
MAX_BODY_CHARS = 2_000_000

# The bounds of the read path (#626). Each sits before the step it bounds. The numbers
# are from the prototype run of 2026-11-20, on generated input.
# The header read takes this many bytes of a stored file: 7.5 times the largest
# generated header block (17,407 bytes: 16 hops, 4 seals, 120 references). The field
# split of a crafted block of this size took at most 0.05 s.
HEADER_READ_BYTES = 131_072
# A bound on the VALUE of one header field: the whole raw value as the parser stores
# it, with every line of a folded field and its fold bytes. The basis, and a basis
# only: RFC 5322 section 2.1.1 allows 998 characters for one LINE, and a valid message
# id fits one line. The value parse of the worst field of this size took 2 to 8 ms
# (2 to 3 ms in the prototype run, 7.6 ms in the review of the change).
MAX_HEADER_FIELD_CHARS = 998
# One parse reads at most this many characters of field values together. The parser
# reads the Content-Type of each part about 5 times, so about 42 attachments fit when
# each has the longest file name a Mac allows (253 bytes) outside ASCII (42 fit and 43
# are refused), or about 276 with names of 10 characters; a generated message with 100
# attachments used 90,252.
MAX_HEADER_FETCH_CHARS = 200_000
# A candidate row is parsed only when its stored size is at most this. A message of
# the 25 MB sending limit of the large providers is about 34 MB after base64 (that
# limit is from memory, not read from a source).
MAX_MESSAGE_BYTES = 50_000_000
# ... and when it has at most this many lines (LF, CR and CRLF line ends). A 25 MB
# message with one base64 attachment has 320,526; 4,000,000 one-byte lines took 0.6 s.
MAX_MESSAGE_LINES = 1_000_000
# ... and at most this many part-delimiter lines (lines that start with two hyphens).
# A generated message with 100 attachments has 106; 25,001 small parts took 3.4 s with
# the default policy, and the most parts that pass took 0.13 to 0.27 s. The budget of
# field values stops a parse of many parts too (the parser reads the Content-Type of
# the container for each part); this count refuses such a message before the parse.
MAX_MESSAGE_PARTS = 1_000
# At most this many candidate rows are parsed in one sweep. A send makes two or three
# (the Drafts copy, the Sent copy, on Gmail an All Mail twin); a candidate row built
# just inside every bound took 0.36 to 0.53 s.
MAX_PARSED_ROWS = 8
# A text part that declares one of these as its charset is not decoded. They are text
# encodings of the standard library, but no character sets: they encode domain names.
# The decode of `punycode` takes quadratic time (2.3 s for 100,000 bytes, 9.4 s for
# 200,000); `idna` needs `punycode`. Every other text encoding of Python 3.14.5 decoded
# 1 MB of crafted input in at most 0.12 s (110 encodings, 22 input shapes; a test
# repeats that on the running Python). A codec that is no text encoding (base64, zlib,
# bz2, hex, quopri, rot-13, uu) is refused by `bytes.decode` itself before it runs.
_REFUSED_CHARSETS = frozenset({"punycode", "idna"})


class _BodyTooLarge(Exception):
    """A decoded body is over ``MAX_BODY_CHARS``. It carries no text of the body."""


class _CombiningRun(Exception):
    """A text of the sweep holds a run of combining characters over
    ``text.MAX_COMBINING_RUN``; it was not normalized. It carries no text. It derives
    from ``Exception`` itself, never from ``LookupError`` or ``ValueError``: those are
    what a decode error of a part raises, and a refusal must stay apart from them."""


class _HeaderTooLarge(Exception):
    """A header field that the sweep reads is over ``MAX_HEADER_FIELD_CHARS``, the
    fields of one parse are over ``MAX_HEADER_FETCH_CHARS`` together, or the field
    lies in the part of a header block that was not read. It carries no text, and it
    derives from ``Exception`` itself, like ``_CombiningRun`` and for the same reason:
    it can leave ``get_content()`` of a part."""


class _MessageTooLarge(Exception):
    """A stored message is over ``MAX_MESSAGE_BYTES``, ``MAX_MESSAGE_LINES`` or
    ``MAX_MESSAGE_PARTS``; it was not parsed. It carries no text, and it derives from
    ``Exception`` itself."""


class _BoundedPolicy(email.policy.EmailPolicy):
    """``email.policy.default`` with two limits on the VALUE parse of a field. It only
    refuses: a value inside the limits is parsed by the parent method, so it is the
    value of the default policy. ``budget``: a one-item list, the characters of field
    values that this parse may still read.

    ``skip_content_type`` is for the header read only. The parser asks for the
    top-level ``Content-Type`` once when a parse ends (``FeedParser.close``) and drops
    the answer of a headers-only parse; nothing in the header read uses that field. So
    with the flag the field is not parsed at all and the answer is ``""``: a new mail
    of another thread with a long ``Content-Type`` (a long file name) is skipped as
    before, and is not a refusal. This cannot make a row of the thread a skipped row:
    the thread test reads ``In-Reply-To`` alone, through this same method, and the
    flag changes the answer for the one name ``Content-Type``. The body parse of a
    candidate row has no flag, so there the field keeps its bound."""

    budget = None
    skip_content_type = False

    def header_fetch_parse(self, name, value):
        if self.skip_content_type and name.lower() == "content-type":
            return ""
        # the raw value as the parser stored it: fold bytes included
        if len(value) > MAX_HEADER_FIELD_CHARS:
            raise _HeaderTooLarge
        self.budget[0] -= len(value)
        if self.budget[0] < 0:
            raise _HeaderTooLarge
        return super().header_fetch_parse(name, value)


def _bounded_policy() -> _BoundedPolicy:
    """A new policy object with a new budget: one for each parse."""
    return _BoundedPolicy(budget=[MAX_HEADER_FETCH_CHARS])


class Draft(NamedTuple):
    """The sweep's verdict. ``kind``: ``none`` (no new reply draft), ``one`` (exactly
    one, proven the call's own: ``url`` is its mailbox, ``mid`` its Message-ID) or
    ``unproven`` (something is there that cannot be proven the call's own).
    ``reason`` names the branch of an ``unproven`` verdict (a fixed code) and is ""
    otherwise."""

    kind: str
    url: str = ""
    mid: str = ""
    reason: str = ""


def _read(query):
    """Run ``query(conn)`` on the Envelope Index, read-only. Raises a ``NativeError``
    when it cannot read (Full Disk Access, schema drift, no index): the caller must then
    treat the sweep as unavailable, never as "no copy"."""
    path = mail_index.envelope_index_path()
    if path is None:
        raise NativeError("Mail's Envelope Index does not exist on this Mac")
    return runtime.read_via_sqlite(path, _FINGERPRINT, query)


# Index files whose ``messages.ROWID`` was seen to be AUTOINCREMENT (checked once each).
_AUTOINCREMENT_SEEN: set[Path] = set()


def index_top() -> int | None:
    """The highest ``messages.ROWID`` now, or None when the index cannot be read (the
    sweep is then unavailable and the refusal says so) or when ``messages.ROWID`` is not
    AUTOINCREMENT: only then does a new row always sort above the baseline, and the
    whole sweep rests on that. The table definition is read once per index file."""
    path = mail_index.envelope_index_path()

    def top(conn) -> int | None:
        if path not in _AUTOINCREMENT_SEEN:
            row = conn.execute(_TABLE_SQL).fetchone()
            if not row or "AUTOINCREMENT" not in str(row[0]).upper():
                return None
            _AUTOINCREMENT_SEEN.add(path)
        return int(conn.execute(_TOP_SQL).fetchone()[0])

    try:
        return _read(top)
    except NativeError:
        return None


def new_rows(top: int) -> list[tuple[int, str]]:
    """``(ROWID, mailbox url)`` of every live row above ``top``, at most
    ``MAX_NEW_ROWS + 1`` (one over the cap tells the caller it was cut). Raises a
    ``NativeError`` when the index cannot be read."""
    return _read(
        lambda conn: [
            (int(r[0]), str(r[1]))
            for r in conn.execute(_NEW_ROWS_SQL, (top, MAX_NEW_ROWS + 1))
        ]
    )


_GOOGLE_ROOTS = ("[Gmail]", "[Google Mail]")


def _is_drafts_url(url: str) -> bool:
    """A mailbox named ``Drafts`` / ``Draft`` directly under its account or under
    Google's root (``[Gmail]/Drafts``, ``[Google Mail]/Drafts``). A nested user folder
    (``Projects/Drafts``, ``[Archive 2019]/Drafts``) is not a Drafts mailbox, and
    neither is a localized one: both are ``unproven``."""
    parts = mailbox_url.path(url).split("/")
    if parts[-1] not in ("Drafts", "Draft"):
        return False
    return len(parts) == 1 or (len(parts) == 2 and parts[0] in _GOOGLE_ROOTS)


def _is_sent_url(url: str) -> bool:
    """A mailbox that holds the SENT message's own copy: a ``Sent`` folder under its
    account or under Google's root (``Sent Messages``, ``[Gmail]/Sent Mail``,
    ``Sent Items``), or Gmail's ``All Mail``. Matched by name like ``_is_drafts_url``,
    for the same reason (the index has no mailbox role): a name outside
    ``mailbox_url.SENT_LEAVES`` (its English names and the canonical translations) or
    a user folder is not matched, so a copy there is ``unproven``, never explained
    away."""
    parts = mailbox_url.path(url).split("/")
    nested = len(parts) == 2 and parts[0] in _GOOGLE_ROOTS
    if parts[-1] == "All Mail":
        return nested
    return parts[-1] in mailbox_url.SENT_LEAVES and (len(parts) == 1 or nested)


def _is_inbox_url(url: str) -> bool:
    """The INBOX directly under an account. Only this mailbox may hold the delivered
    copy of a sent message: a delivered message lands there, and the Drafts autosave
    may share the sent message's Message-ID, so a Message-ID match in any other mailbox
    (a localized Drafts, ``Projects/INBOX``, a user folder) proves nothing. The row must
    also carry a mail server's ``Received`` header (``find_own_draft``): an account
    whose Drafts mailbox is its INBOX could hold a leftover draft with the sent
    Message-ID, and a draft has no ``Received`` field, so that row stays
    ``unproven``."""
    return mailbox_url.path(url) == "INBOX"


def _shard(rowid: int) -> str:
    """Mail's folder shard of a message: the digits of ``rowid // 1000`` reversed, one
    folder each (174504 -> ``4/7/1``); none below 1000."""
    return "/".join(reversed(str(rowid // 1000))) if rowid >= 1000 else ""


def _emlx_path(url: str, rowid: int) -> Path | None:
    """The stored file of one message. The mailbox folder is derived from the url (one
    ``.mbox`` folder per path segment) and the shard from the ROWID, so a lookup costs a
    stat; a miss walks that one mailbox folder, never the whole account (a walk of a
    large account took 0.3 to 0.7 s per message). Only the ``V*`` folder of the index
    that is read counts: a ROWID means nothing in another version's tree."""
    index_path, parsed = mail_index.envelope_index_path(), mailbox_url.parse(url)
    if index_path is None or parsed is None or not parsed[1]:
        return None
    box = index_path.parents[1].joinpath(
        parsed[1], *(seg + ".mbox" for seg in parsed[2].split("/") if seg)
    )
    if not box.is_dir():
        return None
    names = (f"{rowid}.emlx", f"{rowid}.partial.emlx")
    shard = _shard(rowid)
    pattern = f"*/Data/{shard}/Messages" if shard else "*/Data/Messages"
    for messages in box.glob(pattern):
        for name in names:
            if (messages / name).is_file():
                return messages / name
    for name in names:
        hit = next(box.rglob(name), None)
        if hit is not None:
            return hit
    return None


# Mail's quote writes each inline image of the original this way: the first form in Sent
# and delivered copies, the second (compose-time marker) in drafts (facts 4e `Layout`).
_PLACEHOLDER = re.compile(
    r'<span (?:class="AppleTemporaryEditingElement" )?id="cid:[^"<>]*">([^<]*)</span>'
)


def _is_token(text: str) -> bool:
    """``<...>`` with something inside that is not white space and no other angle
    bracket. Plain string checks: the text comes from a stored message, and a pattern
    here took quadratic time on a long text with no closing bracket."""
    inner = text[1:-1]
    return (
        len(text) > 2
        and text[0] == "<"
        and text[-1] == ">"
        and "<" not in inner
        and ">" not in inner
        and bool(inner.strip())
    )


def _drop_placeholders(quote: str) -> str:
    """``quote`` (HTML) without Mail's own inline-image placeholders (owner decision
    2026-11-18): an element in exactly one of the two forms of ``_PLACEHOLDER``, with no
    tag inside, whose text (unescaped, white space at both ends removed) is one
    ``<...>`` token. A typed ``<x.png>`` and every other form stay text, so the copy
    keeps reading ``unproven``."""

    def drop(found: re.Match[str]) -> str:
        text = html.unescape(found.group(1)).strip()
        return " " if _is_token(text) else found.group(0)

    return _PLACEHOLDER.sub(drop, quote)


# The two strip patterns of `_split_quote`. They must not change: what they match
# decides which text counts, and that text decides a delete. Each one alone repeats a
# scan that cannot succeed (#611: 28 s for 256 KB of unclosed `<script ` openers), so
# they run only behind `_drop_blocks` and `_drop_tags`.
_BLOCK = re.compile(r"(?is)<(script|style).*?</\1>")
_TAG = re.compile(r"<[^>]+>")
_OPENER = re.compile(r"(?i)<(script|style)")


def _drop_blocks(chunk: str) -> str:
    """``_BLOCK.sub("", chunk)`` in linear time: the output of the old call
    ``re.sub(r"(?is)<(script|style).*?</\\1>", "", chunk)`` for every input. The
    pattern is tried only where an opener starts. A failed try means that no closing
    tag for that captured name exists from there on, so a later opener with the same
    name is skipped without a scan."""
    out: list[str] = []
    done = at = 0
    dead: set[str] = set()  # captured names with no closing tag from here on
    while (opener := _OPENER.search(chunk, at)) is not None:
        # equal keys differ in ASCII case only, so they have the same closing tags
        key = opener.group(1).lower()
        block = None if key in dead else _BLOCK.match(chunk, opener.start())
        if block is None:
            dead.add(key)
            at = opener.end()
            continue
        out.append(chunk[done : opener.start()])
        done = at = block.end()
    out.append(chunk[done:])
    return "".join(out)


def _drop_tags(chunk: str) -> str:
    """``_TAG.sub(" ", chunk)`` in linear time: the output of the old call
    ``re.sub(r"<[^>]+>", " ", chunk)`` for every input. No tag ends after the last
    ``>``, and before it every ``<`` meets a ``>``."""
    last = chunk.rfind(">") + 1
    return _TAG.sub(" ", chunk[:last]) + chunk[last:]


def _part_text(part) -> str:
    """The decoded text of one ``text/html`` or ``text/plain`` part
    (``get_content()``). A part that declares a charset of ``_REFUSED_CHARSETS`` is
    not decoded: ``LookupError``, raised before the decode runs. Every other error is
    the standard library's own (an unknown charset, a codec that is no text encoding,
    a decode that fails), and none is caught here: a part that is not decoded is text
    that the proof did not see, so the row must not be judged."""
    # the charset as `email.contentmanager.get_text_content` reads it
    charset = part.get_param("charset", "ASCII")
    if codecs.lookup(charset).name in _REFUSED_CHARSETS:
        raise LookupError("a text part declares a charset that is no character set")
    return part.get_content()


def _split_quote(msg) -> tuple[str, str]:
    """The squashed text of a draft before its first quote, and the squashed text from
    the quote on: the HTML text before / from the first blockquote, else the plain lines
    before / from the first ``>`` line. Inside the quote of HTML (from the first
    ``<blockquote`` to the last ``</blockquote>``), Mail's inline-image placeholders are
    not text (``_drop_placeholders``); the part before the quote, the part below it and
    plain text keep everything. Raises ``_BodyTooLarge`` before any pattern runs when
    the decoded HTML (for a message without HTML, the plain text) is longer than
    ``MAX_BODY_CHARS``. Raises ``_CombiningRun`` before either text is normalized when
    one of them holds a long run of combining characters (``long_combining_run``); the
    text before the quote is scanned after its object marks are removed, because a
    removal can join two runs. A ``text/html`` or ``text/plain`` part that cannot be
    decoded is never skipped: its error leaves this function (``_part_text``), and so
    does a refusal of the bounded policy (``_HeaderTooLarge``) from inside
    ``get_content()``. A part of another text type (a text attachment) is not read."""
    markup = text = ""
    for part in msg.walk():
        kind = part.get_content_type()
        if kind == "text/html":
            markup += _part_text(part)
        elif kind == "text/plain":
            text += _part_text(part)
    if len(markup or text) > MAX_BODY_CHARS:
        raise _BodyTooLarge
    if markup:
        cut = re.search(r"(?i)<blockquote\b", markup)
        at = cut.start() if cut else len(markup)
        parts = []
        quote = markup[at:]
        # the quote ends at the last closing tag; text below it stays text, and an
        # unclosed quote loses nothing
        # (a search in ``quote.lower()`` would shift: lower-casing can add characters)
        closes = list(re.finditer(r"(?i)</blockquote>", quote))
        end = closes[-1].end() if closes else 0
        for chunk in (markup[:at], _drop_placeholders(quote[:end]) + quote[end:]):
            parts.append(html.unescape(_drop_tags(_drop_blocks(chunk))))
        head, tail = parts
    else:
        lines = text.splitlines()
        at = next(
            (n for n, line in enumerate(lines) if line.startswith(">")), len(lines)
        )
        head, tail = "\n".join(lines[:at]), "\n".join(lines[at:])
    head = head.replace("\ufffc", "")
    if long_combining_run(head) or long_combining_run(tail):
        raise _CombiningRun
    return squash_text(head), squash_text(tail)


def _read_draft(url: str, rowid: int):
    """``(in_reply_to, more)`` of one stored message, or None when its file is absent
    or unreadable. ``in_reply_to`` is parsed here. ``more()`` returns
    ``(message_id, body, received)`` and is for a row in the thread only: a row of
    another thread costs one bounded read, one field split and at most two value
    parses (``In-Reply-To``, and the top-level ``Content-Type``, see below).
    ``received``: the headers carry a ``Received`` field with a value. A mail server
    adds one to a delivered message; a draft and a Sent copy carry none. ``body()``
    parses the whole message and is for a candidate row only.

    Two bounds hold for the header read. Only the first ``HEADER_READ_BYTES`` of the
    file are used: one ``read`` asks for one byte more, and that byte only tells
    whether the file ends there. A field value is parsed only when it is at most
    ``MAX_HEADER_FIELD_CHARS`` long. The standard library splits the fields and parses
    each value, so a value is the value of the whole-message read, or a refusal
    (``_HeaderTooLarge``). The top-level ``Content-Type``, which the parser asks for
    when a parse ends, is not parsed in the header read (``skip_content_type``).

    The message was read whole when the read met the end of the file. The size from
    ``stat`` does not decide that: a file can grow between the two calls. A header
    block is complete when the message was read whole, or when the bytes used hold its
    end (two LF in a row, or LF CR LF). In a block that is not complete the
    last field is not used (the cut may have shortened it), and no answer is given
    that the part not read could change: a field that is not found there is a refusal,
    never "absent", and so is a postmark that is not found.

    ``body()`` raises ``_MessageTooLarge`` before any further read when the stored
    size (from ``stat``) is over ``MAX_MESSAGE_BYTES``, and before the parse when the
    lines or the part-delimiter lines are over their bounds. A message that the header
    read holds whole is not read again; a second read must start with the bytes of the
    first (``OSError`` otherwise: the file changed). The parse uses a bounded policy
    of its own, with its own budget and without the flag, so a field of a part (or the
    top-level ``Content-Type``) over a bound raises ``_HeaderTooLarge``."""
    path = _emlx_path(url, rowid)
    if path is None:
        return None
    try:
        size = path.stat().st_size
        with path.open("rb") as file:
            raw = file.read(HEADER_READ_BYTES + 1)
    except OSError:
        return None
    whole = len(raw) <= HEADER_READ_BYTES  # the read met the end of the file
    payload = mail_index.emlx_payload(raw[:HEADER_READ_BYTES])
    if not payload:
        return None
    complete = whole or b"\n\n" in payload or b"\n\r\n" in payload
    policy = _bounded_policy().clone(skip_content_type=True)
    head = email.parser.BytesParser(policy=policy).parsebytes(payload, headersonly=True)
    fields = list(head.raw_items())
    usable = fields if complete else fields[:-1]

    def first(name: str) -> str:
        for key, value in usable:
            if key.lower() == name:
                return str(head.policy.header_fetch_parse(key, value) or "")
        if not complete:
            raise _HeaderTooLarge  # it may lie in the part that was not read
        return ""

    def body():
        if size > MAX_MESSAGE_BYTES:
            raise _MessageTooLarge
        full = payload
        if not whole:
            full = mail_index.emlx_payload(path.read_bytes())
            if not full.startswith(payload):
                raise OSError("the stored message changed between the two reads")
        lines = full.count(b"\n") + full.count(b"\r") - full.count(b"\r\n")
        delimiters = full.count(b"\n--") + full.count(b"\r--")
        if lines > MAX_MESSAGE_LINES or delimiters > MAX_MESSAGE_PARTS:
            raise _MessageTooLarge
        return email.message_from_bytes(full, policy=_bounded_policy())

    def more():
        # every `Received` field is parsed, as the whole-message read did
        stamps = [
            str(head.policy.header_fetch_parse(key, value))
            for key, value in usable
            if key.lower() == "received"
        ]
        received = any(stamp.strip() for stamp in stamps)
        if not received and not complete:
            raise _HeaderTooLarge  # a postmark may lie in the part that was not read
        return first("message-id"), body, received

    return first("in-reply-to"), more


def _bare(text: str) -> str:
    """``text`` after NFC with every white-space character and U+FFFC removed. The
    signature branch compares with this and nothing looser: punctuation, symbols and
    emoji count."""
    return "".join(
        c
        for c in unicodedata.normalize("NFC", str(text or ""))
        if not c.isspace() and c != "\ufffc"
    )


def _is_own(
    before_quote: str, own_text: str, attribution: str | None, signature: str = ""
) -> bool:
    """The text before the quote is the call's full text (exact), then optionally the
    signature Mail put into THIS reply, then optionally Mail's attribution line for this
    original: four shapes, in that order only. The signature (and the attribution
    after it) must equal the text after the call's text EXCEPT FOR WHITE SPACE (the
    stored HTML and the signature's own text break lines differently); punctuation,
    symbols and emoji are never ignored, so a hand draft with any other content there
    is not proof. Empty or blank text, the attribution or signature alone, and text
    that merely starts with the call's (a hand reply that
    begins "Hi" is not "Hi") are not proof; neither is any other text between the call's
    and the quote, nor a signature that did not read (``""`` adds no shape).
    Residual (owner decision 2026-11-01): a hand draft with the same text, the same
    signature and the full quote cannot be told from the call's own."""
    own = squash_text(own_text)
    if not own:
        return False
    if before_quote == own:
        return True
    line = squash_text(attribution)
    if line and before_quote == f"{own} {line}":
        return True
    sig = _bare(signature)
    if not sig or not before_quote.startswith(f"{own} "):
        return False
    rest = _bare(before_quote[len(own) + 1 :])
    return rest in (sig, sig + _bare(line))


def _has_quote(after_quote: str, tail: str | None) -> bool:
    """A quoted reply carries the original's tail after the text and NOTHING after the
    tail (the call pastes only at the top, so its own copy never has a PS below the
    quote), compared the way the insert's confirmation does (letters and digits only);
    a reply without a quote (``tail`` None) has nothing after the text."""
    if tail is None:
        return not after_quote
    return runtime._alnum(after_quote).endswith(runtime._alnum(tail))


def find_own_draft(
    top: int,
    original_mid: str,
    own_text: str,
    attribution: str | None,
    *,
    tail: str | None,
    landed_by: int | None,
    sent_twins: bool = False,
    signature: str = "",
) -> Draft:
    """The call's own Drafts copy among the rows new since ``top``, if there is one.
    ``tail``: the original's last words (None: a reply without a quote). ``landed_by``:
    the index top read right after the window went (the discard, or the send) answered
    (None: unreadable); a row above it landed after the window was gone and is never
    claimed. ``sent_twins``: the reply was SENT, so the sent message's own copies (its
    Sent copy, and on Gmail an All Mail twin) are new rows threaded to the original
    too. A threaded row in a ``Sent`` mailbox (or Gmail's ``All Mail``) that carries a
    Message-ID, the call's exact text and the original's quote is such a copy and is set
    aside, never claimed and never a reason for ``unproven``; so is a threaded row in
    the INBOX directly under an account whose Message-ID equals that of a copy set aside
    and whose headers carry a mail server's ``Received`` field (the delivered copy, when
    the recipient's account is in Mail on this Mac), whatever the order of the two rows;
    without a ``Received`` field the row stays ``unproven`` (``inbox_row``). Any other
    threaded row still is ``unproven`` (a localized Sent or Drafts, a user folder, an
    INBOX row of another message). ``signature``: the signature Mail put into this
    reply ("" when it did not read), accepted between the text and the attribution
    (``_is_own``), for the Drafts copy and the sent twins alike. After a refusal nothing
    was sent, so nothing is set aside. A candidate row (a Drafts row that is not late
    and has a Message-ID, or, after a send, a Sent or All Mail row with a Message-ID)
    whose decoded body is longer than ``MAX_BODY_CHARS`` is decoded and measured, and
    the strip does not run: it is ``unproven`` (``body_too_large``), never claimed and
    never set aside; no other row is measured. A candidate row is ``unproven``
    (``combining_run``) in the same way when a text of it, or one of the four text
    arguments (``own_text``, ``attribution``, ``signature``, ``tail``; scanned once, a
    ``None`` is skipped), holds a long run of combining characters: that text is never
    normalized, and for an argument over the limit no body is parsed.
    The read of each row is bounded (``_read_draft``). A row whose needed header field
    is over a bound, or cannot be answered from a cut header block, is ``unproven``
    (``header_too_large``); so is a candidate row with such a field in a part. A
    candidate row whose stored message is over a size bound is ``unproven``
    (``message_too_large``) and is not parsed. At most ``MAX_PARSED_ROWS`` candidate
    rows are parsed; a further one is ``unproven`` (``too_many_rows``). An error of
    the parser on one row (a ``RecursionError`` is one) makes that row ``unproven``
    (``read_failed``), and the other rows are still judged; so does a ``text/html`` or
    ``text/plain`` part of a candidate row that cannot be decoded, or that declares a
    charset that is not decoded (``_REFUSED_CHARSETS``): such a part is never skipped,
    because its text would be missing from the proof. None of these rows is
    claimed or set aside. The ``Message-ID`` and the ``Received`` fields are parsed for
    a row in the thread only.
    An ``unproven`` verdict carries the code of its branch in ``reason`` (the first row
    that could not be set aside names it; INBOX rows after a send are judged last).
    Raises ``NativeError`` when the index cannot be read now (the caller treats that as
    unavailable)."""
    rows = new_rows(top)
    if len(rows) > MAX_NEW_ROWS:
        return Draft("unproven", reason="too_many_rows")  # too many rows to read all
    # the arguments are normalized for every candidate row; the attribution and the
    # tail come from the original, which another party wrote
    bad_argument = any(
        long_combining_run(text) for text in (own_text, attribution, signature, tail)
    )
    found: list[Draft] = []
    twin_mids: set[str] = set()  # Message-IDs of the Sent / All Mail copies set aside
    # INBOX rows (url, Message-ID, has Received), judged after the loop
    delivered: list[tuple[str, str, bool]] = []
    parsed = 0  # candidate rows whose message was parsed
    for rowid, url in rows:
        try:
            draft = _read_draft(url, rowid)
            if draft is None:
                # a new row we cannot read might be the one
                return Draft("unproven", reason="unreadable_row")
            in_reply_to, more = draft
            if _norm_mid(in_reply_to) != _norm_mid(original_mid):
                continue
            mid, body, received = more()
        except NativeError:
            raise
        except _HeaderTooLarge:
            found.append(Draft("unproven", url, "", "header_too_large"))
            continue
        except Exception:  # noqa: BLE001 - the parser's error stays with this row
            found.append(Draft("unproven", url, "", "read_failed"))
            continue
        is_drafts = _is_drafts_url(url)
        late = landed_by is None or rowid > landed_by
        own = not late and bool(_norm_mid(mid)) and is_drafts
        twin = sent_twins and _is_sent_url(url) and bool(_norm_mid(mid))
        if own or twin:
            if bad_argument:
                found.append(Draft("unproven", url, mid, "combining_run"))
                continue
            if parsed >= MAX_PARSED_ROWS:
                found.append(Draft("unproven", url, mid, "too_many_rows"))
                continue
            parsed += 1
            try:
                before, after = _split_quote(body())
            except NativeError:
                raise
            except _BodyTooLarge:
                refused = "body_too_large"
            except _MessageTooLarge:
                refused = "message_too_large"
            except _HeaderTooLarge:
                refused = "header_too_large"
            except _CombiningRun:
                refused = "combining_run"
            except Exception:  # noqa: BLE001 - the parser's error stays with this row
                refused = "read_failed"
            else:
                refused = ""
            if refused:
                found.append(Draft("unproven", url, mid, refused))
                continue
            says_ours = _is_own(
                before, own_text, attribution, signature
            ) and _has_quote(after, tail)
            if twin and says_ours:
                twin_mids.add(_norm_mid(mid))  # the send itself, never touched
                continue
            own = own and says_ours
        if own:
            found.append(Draft("one", url, mid))
            continue
        if sent_twins and _is_inbox_url(url):
            # judged once every copy is set aside
            delivered.append((url, mid, received))
            continue
        if is_drafts:
            reason = "drafts_late" if late else "drafts_not_own"
        elif sent_twins and _is_sent_url(url):
            reason = "sent_not_own"
        elif _is_inbox_url(url):
            reason = "inbox_row"
        else:
            reason = "other_mailbox"
        found.append(Draft("unproven", url, mid, reason))
    for url, mid, received in delivered:
        # twin_mids never holds ""; a draft or a Sent copy has no `Received` field
        if not (received and _norm_mid(mid) in twin_mids):
            found.append(Draft("unproven", url, mid, "inbox_row"))
    if not found:
        return Draft("none")
    if len(found) == 1:
        return found[0]
    first = next((d.reason for d in found if d.kind == "unproven"), "several_rows")
    return Draft("unproven", reason=first)
