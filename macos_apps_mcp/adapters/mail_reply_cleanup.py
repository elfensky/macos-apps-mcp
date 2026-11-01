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
too, so the copy is claimed (``one``, and so deleted) only when exactly one row matches,
nothing new was unreadable, it sits in a mailbox that is named ``Drafts`` / ``Draft``
(directly under the account or under one bracket folder such as ``[Gmail]``) AND the
squashed text before its quote EQUALS the call's own full squashed text, optionally
followed by Mail's own attribution line for this original (anchored, built the way the
reply quote is). A longer text that merely starts with the call's text is a hand reply.
Anything else is ``unproven``: reported with the refusal, never deleted.
"""

from __future__ import annotations

import email
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


def index_top() -> int | None:
    """The highest ``messages.ROWID`` now, or None when the index cannot be read (the
    sweep is then unavailable and the refusal says so)."""
    try:
        return int(_read(lambda conn: conn.execute(_TOP_SQL).fetchone()[0]))
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


def _is_drafts_url(url: str) -> bool:
    """A mailbox named ``Drafts`` / ``Draft`` directly under its account or under ONE
    bracket folder (``[Gmail]/Drafts``). A nested user folder (``Projects/Drafts``) is
    not a Drafts mailbox, and neither is a localized one: both are ``unproven``."""
    parts = mailbox_url.path(url).split("/")
    if parts[-1] not in ("Drafts", "Draft"):
        return False
    return len(parts) == 1 or (
        len(parts) == 2 and parts[0].startswith("[") and parts[0].endswith("]")
    )


def _shard(rowid: int) -> str:
    """Mail's folder shard of a message: the digits of ``rowid // 1000`` reversed, one
    folder each (174504 -> ``4/7/1``); none below 1000."""
    return "/".join(reversed(str(rowid // 1000))) if rowid >= 1000 else ""


def _emlx_path(url: str, rowid: int) -> Path | None:
    """The stored file of one message. The mailbox folder is derived from the url (one
    ``.mbox`` folder per path segment) and the shard from the ROWID, so a lookup costs a
    stat; a miss walks that one mailbox folder, never the whole account (a walk of a
    large account took 0.3 to 0.7 s per message)."""
    root, parsed = mail_index.mail_root(), mailbox_url.parse(url)
    if root is None or parsed is None or not parsed[1]:
        return None
    segments = [seg + ".mbox" for seg in parsed[2].split("/") if seg]
    names = (f"{rowid}.emlx", f"{rowid}.partial.emlx")
    for base in root.glob(f"V*/{parsed[1]}"):
        box = base.joinpath(*segments)
        if not box.is_dir():
            continue
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


def _before_quote(msg) -> str:
    """The squashed text of a draft up to its first quote: the HTML text before the
    first blockquote, else the plain lines before the first ``>`` line."""
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
        head = markup[: cut.start()] if cut else markup
        head = re.sub(r"(?is)<(script|style).*?</\1>", "", head)
        head = html.unescape(re.sub(r"<[^>]+>", " ", head))
    else:
        lines: list[str] = []
        for line in text.splitlines():
            if line.startswith(">"):
                break
            lines.append(line)
        head = "\n".join(lines)
    return squash_text(head.replace("\ufffc", ""))


def _read_draft(url: str, rowid: int):
    """``(In-Reply-To, Message-ID, parsed message)`` of one stored message, or None when
    its file is absent or unreadable. The body is parsed lazily, only for a match."""
    path = _emlx_path(url, rowid)
    if path is None:
        return None
    try:
        payload = mail_index.emlx_payload(path.read_bytes())
    except OSError:
        return None
    if not payload:
        return None
    msg = email.message_from_bytes(payload, policy=email.policy.default)
    return (
        str(msg.get("In-Reply-To", "") or ""),
        str(msg.get("Message-ID", "") or ""),
        msg,
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


def find_own_draft(
    top: int, original_mid: str, own_text: str, attribution: str | None
) -> Draft:
    """The call's own Drafts copy among the rows new since ``top``, if there is one.
    Raises ``NativeError`` when the index cannot be read now (the caller treats that as
    unavailable)."""
    rows = new_rows(top)
    if len(rows) > MAX_NEW_ROWS:
        return Draft("unproven")  # too many new rows to read them all
    found: list[Draft] = []
    unreadable = False
    for rowid, url in rows:
        draft = _read_draft(url, rowid)
        if draft is None:
            unreadable = True  # a new row we cannot read might be the one
            continue
        in_reply_to, mid, msg = draft
        if _norm_mid(in_reply_to) != _norm_mid(original_mid):
            continue
        own = _is_drafts_url(url) and _is_own(_before_quote(msg), own_text, attribution)
        found.append(Draft("one" if own else "unproven", url, mid))
    if not found:
        return Draft("unproven" if unreadable else "none")
    if len(found) > 1 or unreadable or found[0].kind != "one":
        return Draft("unproven")
    return found[0]
