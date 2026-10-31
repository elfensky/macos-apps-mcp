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

**Selector** (a design rule, run as one step on device only in 05.2-13): a Drafts row
that is NEW since the call's own baseline, whose ``In-Reply-To`` header is the original.
A hand reply to the same original matches too, so the copy is claimed only when exactly
one row matches AND the text before its quote is empty or starts with the call's own
text. Anything else is ``unproven`` and nothing is deleted.

Limits, all fail-safe (an unproven copy is reported to the caller, never deleted): the
Drafts mailbox is recognised by the English names ``Drafts`` / ``Draft`` (the probe's
rule), and only an English ``On <date> … wrote:`` attribution line counts as empty text.
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

# Only what the query reads: present in every Envelope Index shape (also the Sequoia
# shape, where message_global_data loses its Message-ID column).
_FINGERPRINT: dict[str, set[str]] = {
    "messages": {"ROWID", "mailbox", "deleted"},
    "mailboxes": {"ROWID", "url"},
}

_DRAFTS_SQL = """
SELECT m.ROWID, mb.url
FROM messages m
JOIN mailboxes mb ON mb.ROWID = m.mailbox
WHERE m.deleted = 0 AND (mb.url LIKE '%/Drafts' OR mb.url LIKE '%/Draft')
"""

# The whole text before the quote is Mail's attribution line and nothing else.
_ATTRIBUTION_ONLY = re.compile(r"On .{3,200} wrote:")


class Draft(NamedTuple):
    """The sweep's verdict. ``kind``: ``none`` (no new reply draft), ``one`` (exactly
    one, proven the call's own: ``url`` is its mailbox, ``mid`` its Message-ID) or
    ``unproven`` (something is there that cannot be proven the call's own)."""

    kind: str
    url: str = ""
    mid: str = ""


def drafts_rows() -> list[tuple[int, str]]:
    """``(ROWID, mailbox url)`` of every live Drafts row in every account. Raises a
    ``NativeError`` (Full Disk Access, schema drift, no index) when it cannot read."""
    path = mail_index.envelope_index_path()
    if path is None:
        raise NativeError("Mail's Envelope Index does not exist on this Mac")

    def query(conn) -> list[tuple[int, str]]:
        return [(int(r), str(u)) for r, u in conn.execute(_DRAFTS_SQL)]

    return runtime.read_via_sqlite(path, _FINGERPRINT, query)


def drafts_baseline() -> frozenset[int] | None:
    """The Drafts ROWIDs now, or None when the index cannot be read (the sweep is then
    unavailable and the refusal says so)."""
    try:
        return frozenset(rowid for rowid, _ in drafts_rows())
    except NativeError:
        return None


def _emlx_path(url: str, rowid: int) -> Path | None:
    root, account = mail_index.mail_root(), mailbox_url.account(url)
    if root is None or not account:
        return None
    for base in root.glob(f"V*/{account}"):
        for name in (f"{rowid}.emlx", f"{rowid}.partial.emlx"):
            hit = next(base.rglob(name), None)
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


def _read_draft(url: str, rowid: int) -> tuple[str, str, str] | None:
    """``(In-Reply-To, Message-ID, text before the quote)`` of one stored draft, or None
    when its file is absent or unreadable."""
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
        _before_quote(msg),
    )


def _is_own(before_quote: str, own_text: str) -> bool:
    return (
        before_quote == ""
        or before_quote.startswith(squash_text(own_text))
        or _ATTRIBUTION_ONLY.fullmatch(before_quote) is not None
    )


def find_own_draft(baseline: frozenset[int], original_mid: str, own_text: str) -> Draft:
    """The call's own Drafts copy, if there is one. Raises ``NativeError`` when the
    index cannot be read now (the caller treats that as unavailable)."""
    found: list[Draft] = []
    unreadable = False
    for rowid, url in drafts_rows():
        if rowid in baseline:
            continue
        draft = _read_draft(url, rowid)
        if draft is None:
            unreadable = True  # a new row we cannot read might be the one
            continue
        in_reply_to, mid, before_quote = draft
        if _norm_mid(in_reply_to) != _norm_mid(original_mid):
            continue
        found.append(
            Draft("one" if _is_own(before_quote, own_text) else "unproven", url, mid)
        )
    if not found:
        return Draft("unproven" if unreadable else "none")
    if len(found) > 1 or unreadable or found[0].kind != "one":
        return Draft("unproven")
    return found[0]
