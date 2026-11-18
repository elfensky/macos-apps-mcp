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
        return "" if _is_token(text) else found.group(0)

    return _PLACEHOLDER.sub(drop, quote)


def _split_quote(msg) -> tuple[str, str]:
    """The squashed text of a draft before its first quote, and the squashed text from
    the quote on: the HTML text before / from the first blockquote, else the plain lines
    before / from the first ``>`` line. In the quote part of HTML, Mail's inline-image
    placeholders are not text (``_drop_placeholders``); the part before the quote keeps
    every element."""
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
        for chunk in (markup[:at], _drop_placeholders(markup[at:])):
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
    """``(In-Reply-To, Message-ID, body, received)`` of one stored message, or None
    when its file is absent or unreadable. Only the headers are parsed here; ``body()``
    parses the whole message and is called for a threaded row only. ``received``: the
    headers carry a ``Received`` field. A mail server adds one to a delivered message;
    a draft and a Sent copy carry none."""
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
        bool(head.get_all("Received")),
    )


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
    was sent, so nothing is set aside. An ``unproven`` verdict carries the code of its
    branch in ``reason`` (the first row that could not be set aside names it; INBOX
    rows after a send are judged last). Raises ``NativeError`` when the index cannot be
    read now (the caller treats that as unavailable)."""
    rows = new_rows(top)
    if len(rows) > MAX_NEW_ROWS:
        return Draft("unproven", reason="too_many_rows")  # too many rows to read all
    found: list[Draft] = []
    twin_mids: set[str] = set()  # Message-IDs of the Sent / All Mail copies set aside
    # INBOX rows (url, Message-ID, has Received), judged after the loop
    delivered: list[tuple[str, str, bool]] = []
    for rowid, url in rows:
        draft = _read_draft(url, rowid)
        if draft is None:
            # a new row we cannot read might be the one
            return Draft("unproven", reason="unreadable_row")
        in_reply_to, mid, body, received = draft
        if _norm_mid(in_reply_to) != _norm_mid(original_mid):
            continue
        is_drafts = _is_drafts_url(url)
        late = landed_by is None or rowid > landed_by
        own = not late and bool(_norm_mid(mid)) and is_drafts
        twin = sent_twins and _is_sent_url(url) and bool(_norm_mid(mid))
        if own or twin:
            before, after = _split_quote(body())
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
