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
from urllib.parse import quote

from ..audit import state_dir
from ..contracts import Pointer
from ..errors import NativeError
from ..runtime import read_via_sqlite

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
        "conversation_id",
    },
    "subjects": {"ROWID", "subject"},
    "addresses": {"ROWID", "address", "comment"},
    "mailboxes": {"ROWID", "url"},
    "message_global_data": {"ROWID", "message_id_header"},
    "recipients": {"message", "address"},
    # conversation_id: Mail's own threading key (five dedicated indexes on it),
    # read by build_thread_query. attachments: backs has_attachments — an indexed
    # EXISTS, never a per-message AppleScript probe.
    "attachments": {"ROWID", "message", "name"},
}


def envelope_index_path() -> Path | None:
    """Newest ~/Library/Mail/V*/MailData/Envelope Index, or None if Mail data absent.
    V* moves between macOS versions; pick the highest-numbered MailData — NUMERICALLY:
    a lexicographic sort reads 'V10' < 'V9', and a Mac that kept an old V9 dir from
    before an OS upgrade would silently serve the stale index to every read."""

    def _version(p: Path) -> int:
        v = p.parts[-3][1:]  # ".../V10/MailData/Envelope Index" -> "10"
        return int(v) if v.isdigit() else -1

    roots = sorted(
        (Path.home() / "Library" / "Mail").glob("V*/MailData/Envelope Index"),
        key=_version,
    )
    return roots[-1] if roots else None


def mail_root() -> Path | None:
    """~/Library/Mail (the parent of the V* dirs), or None if it doesn't exist."""
    root = Path.home() / "Library" / "Mail"
    return root if root.exists() else None


def _deeplink(message_id: str) -> str:
    # message://%3C<id>%3E opens the message in Mail. The angle brackets are percent-
    # encoded (%3C/%3E) and the id itself is percent-encoded with safe='@' (an RFC822
    # message-id is local@domain, so '@' stays literal; spaces/other chars escaped) —
    # the patrickfreyer recipe (#61). Best-effort; verified on-device (integration).
    # Lives HERE (not mail.py) because row_to_pointer needs it: this was the one
    # mail_index -> mail edge, and it forced every mail.py index read into a lazy
    # import. mail.py re-exports it for its own Pointer builders.
    mid = message_id.strip().lstrip("<").rstrip(">")
    return f"message://%3C{quote(mid, safe='@')}%3E"


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


# Dedup (#75/#76/#77): a real mailbox stores the SAME RFC822 Message-ID in several
# mailboxes — device-verified, 36,112 non-deleted rows resolving to 22,223 distinct ids.
# Three causes, none fixable by cleaning up: Gmail shows one server message under both a
# label and All Mail, a migration leaves copies on two accounts, and every reply makes a
# Sent-plus-folder pair. Apple hit this too (mailboxes.unread_count_adjusted_for_
# duplicates). So one row per Message-ID, ranked: a live INBOX copy beats a filed copy,
# which beats an All Mail / Archive / Trash / Junk copy. Fixed literals, no user input —
# every *filter* value is still a bound param. Patterns are anchored to the FINAL path
# segment (urls are percent-encoded, so the space in a name is a literal '%20', escaped
# with ESCAPE so LIKE reads it as text and not as a wildcard): both-side wrapping
# ('%Junk%', '%All%Mail') also matched real user folders — 'Junkyard',
# 'Wallets/Old Mail' — and demoted them, so the OLDER filed copy won the citation.
# Junk/Spam take a '<name>' or '<name>%20…' segment because Exchange names the folder
# `Junk%20E-mail`, which a bare end-anchored '%/Junk' would rank as a preferred filed
# folder and let beat a real Archive copy.
_MAILBOX_RANK = r"""CASE
           WHEN mb.url LIKE '%/INBOX' THEN 0
           WHEN mb.url LIKE '%/All\%20Mail' ESCAPE '\'
             OR mb.url LIKE '%/Archive'
             OR mb.url LIKE '%/Trash'
             OR mb.url LIKE '%/Deleted\%20Messages' ESCAPE '\'
             OR mb.url LIKE '%/Junk'
             OR mb.url LIKE '%/Junk\%20%' ESCAPE '\'
             OR mb.url LIKE '%/Spam'
             OR mb.url LIKE '%/Spam\%20%' ESCAPE '\' THEN 2
           ELSE 1 END"""

# The projected columns every deduped read returns; row_to_pointer consumes exactly
# these names. Shared with build_thread_query.
_DEDUP_SELECT_COLS = """gd.message_id_header AS message_id_header,
       s.subject            AS subject,
       mb.url               AS mailbox_url,
       m.date_received      AS date_received"""

_BASE_SQL = f"""
SELECT {_DEDUP_SELECT_COLS},
       ROW_NUMBER() OVER (PARTITION BY gd.message_id_header
                          ORDER BY {_MAILBOX_RANK}, m.date_received DESC, m.ROWID) AS rn
FROM messages m
JOIN subjects s ON s.ROWID = m.subject
LEFT JOIN addresses a ON a.ROWID = m.sender
JOIN mailboxes mb ON mb.ROWID = m.mailbox
JOIN message_global_data gd ON gd.ROWID = m.global_message_id
WHERE m.deleted = 0
  AND gd.message_id_header IS NOT NULL AND gd.message_id_header <> ''
"""

# has_attachments means "carries a real document". Mail counts inline signature and
# newsletter images as attachment rows, so a naive EXISTS is noise-dominated — on a real
# Mac 4,474 messages "have an attachment" while only 2,223 carry a document. Names with
# no extension count as documents: a false positive beats a silently dropped attachment.
_IMAGE_EXTS = (
    "png",
    "jpg",
    "jpeg",
    "gif",
    "webp",
    "heic",
    "bmp",
    "tiff",
    "tif",
    "svg",
    "ico",
)

_HAS_DOCUMENT = (
    " AND EXISTS (SELECT 1 FROM attachments at WHERE at.message = m.ROWID"
    " AND (at.name IS NULL OR NOT ("
    + " OR ".join(f"lower(at.name) LIKE '%.{e}'" for e in _IMAGE_EXTS)
    + ")))"
)


def like_escape(value: str) -> str:
    r"""Escape LIKE metacharacters so a bound value matches LITERALLY.

    Binding a parameter stops injection; it does NOT stop ``%`` and ``_`` from being
    read as wildcards, so an un-escaped ``account='%'`` quietly matches every mailbox
    and returns a confidently wrong answer. Pair with ``ESCAPE '\'``.
    """
    return value.replace("\\", r"\\").replace("%", r"\%").replace("_", r"\_")


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
    has_attachments=None,
    account=None,
    message_ids=None,
    limit=25,
):
    """Build (sql, params) for the header plane. All filters optional, ANDed; every
    value is a bound param (injection-safe). Newest-first, deleted excluded.
    `has_attachments` means a real document (images excluded); `account` matches the
    account segment of the mailbox url (<scheme>://<UUID>/<path>) — exactly, not as a
    substring of the path."""
    # Every LIKE filter escapes its value: a bound param stops injection, not '%'/'_'
    # being read as wildcards — subject='50% off' matched '50 anything off', and
    # mailbox='_' matched every mailbox (the exact failure like_escape documents).
    sql = _BASE_SQL
    params: list = []
    if subject:
        sql += r" AND s.subject LIKE ? ESCAPE '\'"
        params.append(f"%{like_escape(subject)}%")
    if from_:
        sql += r" AND (a.address LIKE ? ESCAPE '\' OR a.comment LIKE ? ESCAPE '\')"
        params += [f"%{like_escape(from_)}%", f"%{like_escape(from_)}%"]
    if to:
        sql += (
            " AND EXISTS (SELECT 1 FROM recipients r JOIN addresses ra"
            " ON ra.ROWID = r.address WHERE r.message = m.ROWID"
            r" AND ra.address LIKE ? ESCAPE '\')"
        )
        params.append(f"%{like_escape(to)}%")
    if mailbox:
        sql += r" AND mb.url LIKE ? ESCAPE '\'"
        params.append(f"%{like_escape(mailbox)}%")
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
    if has_attachments:
        sql += _HAS_DOCUMENT
    if account:
        # Anchored to the ACCOUNT SEGMENT of mailboxes.url (<scheme>://<UUID>/<path>),
        # not a substring of the whole url: an unanchored '%value%' also matches any
        # mailbox whose PATH contains the text, under any account, and reports it as
        # though the account filter worked. The trailing '/' is appended to mb.url so
        # an account-root mailbox with no path still matches. LIKE metacharacters in
        # the value are escaped for the same honesty reason — account='%' must match
        # one account, not every mailbox (it is a bound param, so never injection).
        sql += r" AND mb.url || '/' LIKE '%://' || ? || '/%' ESCAPE '\'"
        params.append(like_escape(account))
    if message_ids:
        placeholders = ",".join("?" for _ in message_ids)
        sql += f" AND gd.message_id_header IN ({placeholders})"
        params += list(message_ids)
    # Dedup and LIMIT wrap the filtered set: rank inside, pick rn = 1, then LIMIT — so
    # LIMIT counts distinct messages, not rows that collapse afterwards.
    sql = (
        f"SELECT message_id_header, subject, mailbox_url, date_received FROM ({sql})"
        " WHERE rn = 1 ORDER BY date_received DESC LIMIT ?"
    )
    params.append(limit)
    return sql, params


def build_thread_query(message_id: str, limit: int):
    """Build (sql, params) for one conversation, addressed by any member's Message-ID.

    Threads on messages.conversation_id — Mail's own threading key, which carries
    five dedicated indexes, so matching References/In-Reply-To by hand would be
    redundant work on top of an answer Mail already computed. Deduped by the same
    rule as search, and ordered OLDEST-first: a thread reads as a transcript.
    Truncation keeps the NEWEST ``limit`` messages (the old end is the end to drop
    when the point is to reply), then re-sorts ascending for the caller.

    The seed matches EVERY conversation the Message-ID belongs to, not one of them:
    the premise of this module is that one Message-ID has several rows, and a
    cross-account copy can carry a DIFFERENT conversation_id, so a `= (SELECT …
    LIMIT 1)` seed silently drops the other branch — and picks a deleted copy just as
    happily. Which one won was up to SQLite's query plan and could flip on an OS
    upgrade. Deleted copies are excluded from the seed for the same reason.

    ``sort_date`` guards a date_sent of 0 (not just NULL): a zero sorts to the very
    front of an oldest-first transcript and would be the first message dropped under
    truncation.
    """
    sql = f"""
SELECT message_id_header, subject, mailbox_url, date_received FROM (
  SELECT message_id_header, subject, mailbox_url, date_received, sort_date FROM (
    SELECT {_DEDUP_SELECT_COLS},
           COALESCE(NULLIF(m.date_sent, 0), m.date_received) AS sort_date,
           ROW_NUMBER() OVER (PARTITION BY gd.message_id_header
                              ORDER BY {_MAILBOX_RANK},
                                       m.date_received DESC, m.ROWID) AS rn
    FROM messages m
    JOIN subjects s ON s.ROWID = m.subject
    JOIN mailboxes mb ON mb.ROWID = m.mailbox
    JOIN message_global_data gd ON gd.ROWID = m.global_message_id
    WHERE m.deleted = 0
      AND gd.message_id_header IS NOT NULL AND gd.message_id_header <> ''
      AND m.conversation_id IN (
            SELECT m2.conversation_id FROM messages m2
            JOIN message_global_data gd2 ON gd2.ROWID = m2.global_message_id
            WHERE gd2.message_id_header = ? AND m2.deleted = 0)
  ) WHERE rn = 1
  ORDER BY sort_date DESC
  LIMIT ?
) ORDER BY sort_date ASC
"""
    return sql, [message_id, limit]


def build_local_account_query():
    """Build (sql, params) that finds the account segment mailboxes.url embeds for the
    On My Mac store — the value ``build_header_query``'s ``account`` clause anchors on
    for a ``local://`` mailbox (``<scheme>://<UUID>/<path>``, same shape as an
    ``imap://`` account). AppleScript's `every account` never lists this store (see
    ``mail.overview``'s docstring), so it has no name to resolve from Mail — this is
    read straight from the same Envelope Index the account filter itself queries,
    which guarantees the two agree. Every ``local://`` mailbox on a device shares the
    same account segment, so the first row is enough; no rows means no On My Mac
    store in this index."""
    return "SELECT url FROM mailboxes WHERE url LIKE 'local://%' LIMIT 1", []


def build_overview_query():
    """Build (sql, params) for per-mailbox totals and unread counts.

    Counts are computed LIVE rather than read from mailboxes.unread_count: that column
    is trigger-maintained and device-verified stale — on a real Mac the Gmail INBOX row
    reports 1 unread where a live count returns 0, and
    unread_count_adjusted_for_duplicates carries the same wrong value. A live count over
    36k rows measured 16 ms, backed by the partial index on (read = 0 AND deleted = 0).

    Counted per DISTINCT Message-ID, not per row. A raw COUNT(m.ROWID) is inflated by
    the same duplication the search plane dedups — device-verified against a 36k store,
    Travel reported 4,423 against a true 1,241 (3.6x), Expense 3,535 against 1,127,
    Investing 2,611 against 410. This is same-mailbox dedup, so it needs no mailbox
    rank; the rows collapse inside one GROUP BY. A message with no RFC822 Message-ID
    still counts (keyed on its ROWID) — it has no citation, but it is genuinely in the
    mailbox, and a count that silently omits it is the same class of lie.

    Mailboxes with no messages are included via the LEFT JOINs (both of them — the
    message_global_data join must not turn the outer join inner), so a newly-created
    folder shows as 0/0 rather than vanishing.
    """
    # One expression, used twice: the dedup key. COUNT(DISTINCT …) ignores NULLs, so
    # the unread count is the same key wrapped in a CASE with no ELSE.
    key = "COALESCE(NULLIF(gd.message_id_header, ''), 'rowid:' || m.ROWID)"
    sql = f"""
SELECT mb.url                                       AS mailbox_url,
       COUNT(DISTINCT {key})                        AS total,
       COUNT(DISTINCT CASE WHEN m.read = 0 THEN {key} END) AS unread
FROM mailboxes mb
LEFT JOIN messages m ON m.mailbox = mb.ROWID AND m.deleted = 0
LEFT JOIN message_global_data gd ON gd.ROWID = m.global_message_id
GROUP BY mb.ROWID
ORDER BY unread DESC, mailbox_url ASC
"""
    return sql, []


# --- the one sqlite entry per read shape (C1) ----------------------------------------
# Everything below is the ONLY place adapter code reaches the Envelope Index: path
# resolution, the missing-store error, the schema fingerprint and the read_via_sqlite
# wiring each live here exactly once. Policy stays with the caller — mail.py still
# decides WHEN an AppleScript fallback is honest and passes it through as an opaque
# callable; this module never learns AppleScript semantics.

_NO_MAIL_DATA = (
    "no Mail data found (~/Library/Mail/V*/MailData/Envelope Index). "
    "Open Mail once to create it. Do not retry."
)


def _require_index_path() -> Path:
    """``envelope_index_path()`` or the one followable missing-store error.

    Late-binds the path lookup deliberately: tests monkeypatch
    ``envelope_index_path`` as a module attribute, and that seam must keep
    resolving at call time."""
    path = envelope_index_path()
    if path is None:
        raise NativeError(_NO_MAIL_DATA)
    return path


def _pointer_rows(sql, params, *, fallback=None) -> list[Pointer]:
    """Run a Pointer-projecting query against the required index.

    search and thread differ only in SQL — this is their one shared read. The
    missing-store raise happens BEFORE any fallback is consulted (matching the
    adapter's long-standing behavior: no store is a followable error, not a reason
    to silently scan the inbox). ``immutable=False`` always: the Envelope Index is
    a live WAL store, and ``immutable=1`` would freeze pre-WAL data and silently
    drop recent mail (see runtime's warning)."""
    path = _require_index_path()

    def read(conn):
        conn.row_factory = sqlite3.Row
        out = []
        for row in conn.execute(sql, params):
            p = row_to_pointer(row)
            if p is not None:
                out.append(p)
        return out

    return read_via_sqlite(
        path, HEADER_FINGERPRINT, read, fallback=fallback, immutable=False
    )


def query_search(
    *,
    subject=None,
    from_=None,
    to=None,
    mailbox=None,
    since=None,
    until=None,
    unread=None,
    flagged=None,
    has_attachments=None,
    account=None,
    message_ids=None,
    limit=25,
    fallback=None,
) -> list[Pointer]:
    """Header search over ALL mailboxes, deduped, newest-first → Pointers.

    ``account`` must already be a resolved UUID segment (name resolution talks to
    Mail and is the adapter's job). FTS body search stays with the caller too — it
    is a different store with a different lifecycle; pass its hits as
    ``message_ids``."""
    sql, params = build_header_query(
        subject=subject,
        from_=from_,
        to=to,
        mailbox=mailbox,
        since=since,
        until=until,
        unread=unread,
        flagged=flagged,
        has_attachments=has_attachments,
        account=account,
        message_ids=message_ids,
        limit=limit,
    )
    return _pointer_rows(sql, params, fallback=fallback)


def query_thread(message_id: str, limit: int) -> list[Pointer]:
    """One conversation by any member's EXACT-form (bracketed) Message-ID →
    Pointers, oldest-first. Id-form normalization is the adapter's concern."""
    sql, params = build_thread_query(message_id, limit)
    return _pointer_rows(sql, params)


def query_overview_rows() -> list[dict]:
    """Per-mailbox totals/unread as RAW rows — percent-encoded ``mailbox_url``, no
    account names. Decoding and naming are adapter concerns (naming can launch
    Mail, which this module never does); the ``_rows`` suffix is the warning that
    this is not the Pointer shape."""
    path = _require_index_path()
    sql, params = build_overview_query()

    def read(conn):
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(sql, params)]

    return read_via_sqlite(path, HEADER_FINGERPRINT, read, immutable=False)


def query_local_account_url() -> str | None:
    """First ``local://`` mailbox url, or None when the store (or the local store
    inside it) is absent. Asymmetric with the raising reads BY CONTRACT: the
    account resolver owns the richer "no On My Mac store" error, so this read must
    answer None, never ``_NO_MAIL_DATA``. URL parsing stays with the caller."""
    path = envelope_index_path()
    if path is None:
        return None
    sql, params = build_local_account_query()

    def read(conn):
        conn.row_factory = sqlite3.Row
        row = conn.execute(sql, params).fetchone()
        return row["url"] if row else None

    return read_via_sqlite(path, HEADER_FINGERPRINT, read, immutable=False)


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
    # Concurrency (#71 panel): mail_index_bodies runs OFF run_native (pure file/sqlite
    # I/O), so two overlapping builds — or a mail_search(body=) reader racing a build —
    # would hit the default instant-fail lock and raise a raw sqlite OperationalError.
    # WAL lets readers proceed during a write; busy_timeout makes writer/writer
    # contention wait instead of erroring. Safe: this is OUR sidecar, never Mail's data.
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA journal_mode=WAL")
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


def _fts_query(raw: str) -> str:
    """Sanitize a raw user query into an always-valid FTS5 MATCH expression.

    FTS5 parses the MATCH value as query syntax, not literal text — bound params only
    stop injection, they don't stop e.g. `jane@acme.com` ("syntax error near @") or
    `invoice AND` from raising sqlite3.OperationalError. So every whitespace-split
    token is quoted as a literal phrase (embedded `"` doubled per SQL-string-escaping
    convention) and the quoted tokens are joined with a space — FTS5's implicit AND —
    which is valid for ANY input, including punctuation, bare operators, or an
    unbalanced `"`. Returns "" when there are no tokens (query was all whitespace);
    the caller must not call MATCH with that (#70 review I1)."""
    tokens = raw.split()
    return " ".join('"' + t.replace('"', '""') + '"' for t in tokens)


def fts_search(fts_db: Path, query: str, limit: int = 200) -> list[str]:
    """Message-IDs whose body matches the FTS query, or [] if the sidecar is absent."""
    if not fts_db.exists():
        return []
    fts_query = _fts_query(query)
    if not fts_query:
        return []
    conn = sqlite3.connect(f"file:{fts_db}?mode=ro", uri=True)
    conn.execute("PRAGMA busy_timeout=5000")  # wait out a concurrent build, don't error
    try:
        rows = conn.execute(
            "SELECT message_id FROM bodies WHERE bodies MATCH ? LIMIT ?",
            (fts_query, limit),
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()
