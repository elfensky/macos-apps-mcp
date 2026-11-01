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
squashed text, optionally followed by Mail's own attribution line for this original; AND
it carries the original's quote and nothing after it (its tail, by letters and digits,
as the insert's confirmation compares it, is the LAST thing in the draft), or, for a
reply without a quote, nothing at all after the text. Anything else is ``unproven``:
reported with the refusal, never deleted.

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
call's exact text and the original's quote); the Drafts copy is then judged by the rules
above, and any other threaded row keeps the result ``unproven``. The sweep never
deletes anything outside the one Drafts row it proved, by that row's own message id.

The ROWID column is AUTOINCREMENT, so a new row always sorts above the baseline. That is
checked once per index file at run time (``index_top``): an index without it is
unreadable for the sweep.
"""

from __future__ import annotations

import email
import email.parser
import email.policy
import html
import re
from pathlib import Path
from typing import NamedTuple

from .. import runtime
from ..errors import NativeError
from ..text import squash_text
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


class Draft(NamedTuple):
    """The sweep's verdict. ``kind``: ``none`` (no new reply draft), ``one`` (exactly
    one, proven the call's own: ``url`` is its mailbox, ``mid`` its Message-ID) or
    ``unproven`` (something is there that cannot be proven the call's own)."""

    kind: str
    url: str = ""
    mid: str = ""


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
    for the same reason (the index has no mailbox role): a localized name or a user
    folder is not matched, so a copy there is ``unproven``, never explained away."""
    parts = mailbox_url.path(url).split("/")
    nested = len(parts) == 2 and parts[0] in _GOOGLE_ROOTS
    if parts[-1] == "All Mail":
        return nested
    return parts[-1] in mailbox_url.SENT_LEAVES and (len(parts) == 1 or nested)


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


def _split_quote(msg) -> tuple[str, str]:
    """The squashed text of a draft before its first quote, and the squashed text from
    the quote on: the HTML text before / from the first blockquote, else the plain lines
    before / from the first ``>`` line."""
    markup = text = ""
    for part in msg.walk():
        kind = part.get_content_type()
        try:
            if kind == "text/html":
                markup += part.get_content()
            elif kind == "text/plain":
                text += part.get_content()
        except (LookupError, ValueError):  # an undecodable part adds nothing
            continue
    if markup:
        cut = re.search(r"(?i)<blockquote\b", markup)
        at = cut.start() if cut else len(markup)
        parts = []
        for chunk in (markup[:at], markup[at:]):
            chunk = re.sub(r"(?is)<(script|style).*?</\1>", "", chunk)
            parts.append(html.unescape(re.sub(r"<[^>]+>", " ", chunk)))
        head, tail = parts
    else:
        lines = text.splitlines()
        at = next(
            (n for n, line in enumerate(lines) if line.startswith(">")), len(lines)
        )
        head, tail = "\n".join(lines[:at]), "\n".join(lines[at:])
    return squash_text(head.replace("\ufffc", "")), squash_text(tail)


def _read_draft(url: str, rowid: int):
    """``(In-Reply-To, Message-ID, body)`` of one stored message, or None when its file
    is absent or unreadable. Only the headers are parsed here; ``body()`` parses the
    whole message and is called for a threaded row only."""
    path = _emlx_path(url, rowid)
    if path is None:
        return None
    try:
        payload = mail_index.emlx_payload(path.read_bytes())
    except OSError:
        return None
    if not payload:
        return None
    head = email.parser.BytesParser(policy=email.policy.default).parsebytes(
        payload, headersonly=True
    )
    return (
        str(head.get("In-Reply-To", "") or ""),
        str(head.get("Message-ID", "") or ""),
        lambda: email.message_from_bytes(payload, policy=email.policy.default),
    )


def _is_own(before_quote: str, own_text: str, attribution: str | None) -> bool:
    """The text before the quote EQUALS the call's full text, optionally followed by
    Mail's attribution line for this original. Empty text and the attribution alone are
    not proof (a hand reply opened and saved looks the same), and neither is text that
    merely starts with the call's (a hand reply that begins "Hi" is not "Hi")."""
    own = squash_text(own_text)
    if not own:
        return False
    if before_quote == own:
        return True
    line = squash_text(attribution)
    return bool(line) and before_quote == f"{own} {line}"


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
) -> Draft:
    """The call's own Drafts copy among the rows new since ``top``, if there is one.
    ``tail``: the original's last words (None: a reply without a quote). ``landed_by``:
    the index top read right after the window went (the discard, or the send) answered
    (None: unreadable); a row above it landed after the window was gone and is never
    claimed. ``sent_twins``: the reply was SENT, so the sent message's own copies (its
    Sent copy, and on Gmail an All Mail twin) are new rows threaded to the original
    too. A threaded row in a ``Sent`` mailbox (or Gmail's ``All Mail``) that carries a
    Message-ID, the call's exact text and the original's quote is such a copy and is set
    aside, never claimed and never a reason for ``unproven``; any other threaded row
    still is one (a localized Sent or Drafts, a user folder). After a refusal
    nothing was sent, so nothing is set aside. Raises ``NativeError`` when the index
    cannot be read now (the caller treats that as unavailable)."""
    rows = new_rows(top)
    if len(rows) > MAX_NEW_ROWS:
        return Draft("unproven")  # too many new rows to read them all
    found: list[Draft] = []
    for rowid, url in rows:
        draft = _read_draft(url, rowid)
        if draft is None:
            return Draft("unproven")  # a new row we cannot read might be the one
        in_reply_to, mid, body = draft
        if _norm_mid(in_reply_to) != _norm_mid(original_mid):
            continue
        is_drafts = _is_drafts_url(url)
        own = (
            landed_by is not None
            and rowid <= landed_by
            and bool(_norm_mid(mid))
            and is_drafts
        )
        twin = sent_twins and _is_sent_url(url) and bool(_norm_mid(mid))
        if own or twin:
            before, after = _split_quote(body())
            says_ours = _is_own(before, own_text, attribution) and _has_quote(
                after, tail
            )
            if twin and says_ours:
                continue  # the send itself, not a leftover; it is never touched
            own = own and says_ours
        found.append(Draft("one" if own else "unproven", url, mid))
    if not found:
        return Draft("none")
    return Draft("unproven") if len(found) > 1 else found[0]
