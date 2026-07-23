"""Mail indexed read plane (#70): a read-only sqlite reader over Mail's Envelope Index
for header/subject/sender search at scale, plus a best-effort FTS5 body sidecar in our
own state dir. Pure/sqlite only — no EventKit, no Mail.app. The MailAdapter delegates
here; this module never launches Mail (read-at-rest)."""

from __future__ import annotations

import os
import sqlite3
from email import message_from_bytes
from html.parser import HTMLParser
from pathlib import Path

from ..audit import state_dir
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


def mail_root() -> Path | None:
    """~/Library/Mail (the parent of the V* dirs), or None if it doesn't exist."""
    root = Path.home() / "Library" / "Mail"
    return root if root.exists() else None


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
    if length < 0:
        return None
    rfc822 = raw[nl + 1 : nl + 1 + length]
    if not rfc822:
        return None
    try:
        msg = message_from_bytes(rfc822)
        mid = msg.get("Message-ID")
        if not mid or not mid.strip():
            return None
        body = _body_text(msg).strip()
    except Exception:
        # Untrusted-input boundary: .emlx bytes are attacker-influenceable (deeply
        # nested multipart can overflow stdlib email's own recursive descent before
        # we ever see a Message object). Never let a parse failure escape — None.
        return None
    if not body:
        return None
    return mid.strip(), body


# --- FTS5 body sidecar (#70) ---------------------------------------------------------
# Best-effort full-text index over .emlx bodies, keyed by RFC822 Message-ID. Lives in
# our own state dir — NEVER inside Mail's data — so it can be rebuilt or deleted freely
# without touching anything Mail.app owns.

_FTS_DEFAULT_MAX = 200 * 1024 * 1024  # ~200 MB


def fts_path() -> Path:
    """Where the FTS5 body sidecar lives: our state dir, never Mail's."""
    return state_dir() / "mail_fts.sqlite"


def fts_max_bytes() -> int:
    """Size cap for the sidecar: env override or the ~200 MB default."""
    raw = os.environ.get("MACOS_APPS_MCP_FTS_MAX_BYTES")
    return int(raw) if raw and raw.isdigit() else _FTS_DEFAULT_MAX


def _fts_connect(fts_db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(fts_db)
    conn.executescript(
        "CREATE VIRTUAL TABLE IF NOT EXISTS bodies"
        " USING fts5(message_id UNINDEXED, body);"
        "CREATE TABLE IF NOT EXISTS indexed_files"
        "(path TEXT PRIMARY KEY, mtime INTEGER, size INTEGER);"
    )
    return conn


def build_body_index(
    *,
    mail_root: Path,
    fts_db: Path,
    rebuild: bool = False,
    max_bytes: int | None = None,
) -> dict:
    """Best-effort FTS body index over full .emlx (skips *.partial.emlx). Resumable
    (skips unchanged files), size-capped (stops when fts_db exceeds max_bytes). Never
    touches Mail's data — reads .emlx at rest, writes only fts_db."""
    if max_bytes is None:
        max_bytes = fts_max_bytes()
    if rebuild and fts_db.exists():
        fts_db.unlink()
    conn = _fts_connect(fts_db)
    seen = {
        r[0]: (r[1], r[2])
        for r in conn.execute("SELECT path, mtime, size FROM indexed_files")
    }
    indexed = skipped = total = 0
    capped = False
    try:
        for f in sorted(mail_root.rglob("*.emlx")):
            if f.name.endswith(".partial.emlx"):
                continue
            total += 1
            key = str(f)
            try:
                st = f.stat()
                if seen.get(key) == (int(st.st_mtime), st.st_size):
                    skipped += 1
                    continue
                raw = f.read_bytes()
            except OSError:
                # Mail.app can expunge/rename a file between rglob() enumerating it
                # and us reading it — skip just this file, never abort the run.
                skipped += 1
                continue
            parsed = parse_emlx(raw)
            if parsed is None:
                # record so a re-run doesn't reparse an unindexable file
                conn.execute(
                    "INSERT OR REPLACE INTO indexed_files VALUES (?,?,?)",
                    (key, int(st.st_mtime), st.st_size),
                )
                skipped += 1
            else:
                mid, body = parsed
                conn.execute("DELETE FROM bodies WHERE message_id = ?", (mid,))
                conn.execute(
                    "INSERT INTO bodies (message_id, body) VALUES (?, ?)", (mid, body)
                )
                conn.execute(
                    "INSERT OR REPLACE INTO indexed_files VALUES (?,?,?)",
                    (key, int(st.st_mtime), st.st_size),
                )
                conn.commit()
                indexed += 1
            # Check the cap only *after* committing progress on this file: a bare
            # CREATE VIRTUAL TABLE fts5 schema already occupies more than a few bytes,
            # so checking before the first write would cap the run at zero files
            # indexed instead of stopping once real progress has been recorded.
            if fts_db.stat().st_size >= max_bytes:
                capped = True
                break
    finally:
        try:
            conn.commit()
        finally:
            conn.close()
    return {
        "indexed": indexed,
        "skipped": skipped,
        "total_emlx": total,
        "capped": capped,
    }


def fts_search(fts_db: Path, query: str, limit: int = 200) -> list[str]:
    """Message-IDs whose body matches the FTS query, or [] if the sidecar is absent."""
    if not fts_db.exists():
        return []
    conn = sqlite3.connect(f"file:{fts_db}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT message_id FROM bodies WHERE bodies MATCH ? LIMIT ?", (query, limit)
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()
