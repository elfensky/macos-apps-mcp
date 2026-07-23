"""Mail indexed read plane (#70): a read-only sqlite reader over Mail's Envelope Index
for header/subject/sender search at scale, plus a best-effort FTS5 body sidecar in our
own state dir. Pure/sqlite only — no EventKit, no Mail.app. The MailAdapter delegates
here; this module never launches Mail (read-at-rest)."""

from __future__ import annotations

from email import message_from_bytes
from html.parser import HTMLParser
from pathlib import Path

from ..contracts import Pointer
from .mail import _deeplink

# The Envelope Index tables + the exact columns we read/filter on. A macOS schema move
# that renames/drops any of these trips SchemaDrift → AppleScript fallback (never a
# mis-parsed Pointer). Mirrors notes._FINGERPRINT.
HEADER_FINGERPRINT: dict[str, set[str]] = {
    "messages": {
        "ROWID",
        "subject",
        "sender",
        "global_message_id",
        "mailbox",
        "date_received",
        "date_sent",
        "read",
        "flagged",
        "deleted",
    },
    "subjects": {"ROWID", "subject"},
    "addresses": {"ROWID", "address", "comment"},
    "mailboxes": {"ROWID", "url"},
    "message_global_data": {"ROWID", "message_id_header"},
    "recipients": {"message", "address"},
}


def envelope_index_path() -> Path | None:
    """Newest ~/Library/Mail/V*/MailData/Envelope Index, or None if Mail data absent.
    V* moves between macOS versions; pick the highest-numbered MailData."""
    roots = sorted(
        (Path.home() / "Library" / "Mail").glob("V*/MailData/Envelope Index"),
        key=lambda p: p.parts,
    )
    return roots[-1] if roots else None


def row_to_pointer(row) -> Pointer | None:
    """Map one joined Envelope Index row → Pointer. None when the message has no RFC822
    Message-ID (no stable citation — same rule the adapter documents for header-less
    messages)."""
    mid = row["message_id_header"]
    if not mid or not str(mid).strip():
        return None
    return Pointer(
        id=str(mid),
        summary=row["subject"] or "",
        deeplink=_deeplink(str(mid)),
        folder=row["mailbox_url"],
    )


_BASE_SQL = """
SELECT gd.message_id_header AS message_id_header,
       s.subject            AS subject,
       mb.url               AS mailbox_url,
       m.date_received      AS date_received
FROM messages m
JOIN subjects s ON s.ROWID = m.subject
LEFT JOIN addresses a ON a.ROWID = m.sender
JOIN mailboxes mb ON mb.ROWID = m.mailbox
JOIN message_global_data gd ON gd.ROWID = m.global_message_id
WHERE m.deleted = 0
"""


def build_header_query(
    *,
    subject=None,
    from_=None,
    to=None,
    mailbox=None,
    since=None,
    until=None,
    unread=None,
    flagged=None,
    message_ids=None,
    limit=25,
):
    """Build (sql, params) for the header plane. All filters optional, ANDed; every
    value is a bound param (injection-safe). Newest-first, deleted excluded."""
    sql = _BASE_SQL
    params: list = []
    if subject:
        sql += " AND s.subject LIKE ?"
        params.append(f"%{subject}%")
    if from_:
        sql += " AND (a.address LIKE ? OR a.comment LIKE ?)"
        params += [f"%{from_}%", f"%{from_}%"]
    if to:
        sql += (
            " AND EXISTS (SELECT 1 FROM recipients r JOIN addresses ra"
            " ON ra.ROWID = r.address WHERE r.message = m.ROWID AND ra.address LIKE ?)"
        )
        params.append(f"%{to}%")
    if mailbox:
        sql += " AND mb.url LIKE ?"
        params.append(f"%{mailbox}%")
    if since is not None:
        sql += " AND m.date_received >= ?"
        params.append(since)
    if until is not None:
        sql += " AND m.date_received <= ?"
        params.append(until)
    if unread:
        sql += " AND m.read = 0"
    if flagged:
        sql += " AND m.flagged = 1"
    if message_ids:
        placeholders = ",".join("?" for _ in message_ids)
        sql += f" AND gd.message_id_header IN ({placeholders})"
        params += list(message_ids)
    sql += " ORDER BY m.date_received DESC LIMIT ?"
    params.append(limit)
    return sql, params


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._chunks: list[str] = []

    def handle_data(self, data):
        self._chunks.append(data)

    def text(self) -> str:
        return " ".join(" ".join(self._chunks).split())


def _html_to_text(html: str) -> str:
    p = _TextExtractor()
    p.feed(html)
    return p.text()


def _body_text(msg) -> str:
    """Prefer text/plain; else the first text/html rendered to text.

    Empty if neither.
    """
    plain, html = None, None
    for part in msg.walk() if msg.is_multipart() else [msg]:
        ctype = part.get_content_type()
        if ctype == "text/plain" and plain is None:
            plain = part.get_payload(decode=True)
        elif ctype == "text/html" and html is None:
            html = part.get_payload(decode=True)
    if plain:
        return plain.decode("utf-8", "replace")
    if html:
        return _html_to_text(html.decode("utf-8", "replace"))
    return ""


def parse_emlx(raw: bytes) -> tuple[str, str] | None:
    """(message_id, body_text) from an .emlx byte string.

    Returns None if malformed, header-less, or no extractable text.
    Strips the length-prefix line and trailing plist.
    """
    nl = raw.find(b"\n")
    if nl == -1:
        return None
    try:
        length = int(raw[:nl].strip())
    except ValueError:
        return None
    rfc822 = raw[nl + 1 : nl + 1 + length]
    if not rfc822:
        return None
    msg = message_from_bytes(rfc822)
    mid = msg.get("Message-ID")
    if not mid or not mid.strip():
        return None
    body = _body_text(msg).strip()
    if not body:
        return None
    return mid.strip(), body
