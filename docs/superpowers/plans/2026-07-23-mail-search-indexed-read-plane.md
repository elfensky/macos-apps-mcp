# Mail Indexed Search (Envelope Index + body FTS) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `mail_search` (indexed header/subject/sender/date search over all mailboxes) and `mail_index_bodies` (opt-in, resumable, size-capped FTS5 body index over `.emlx`), reusing the existing dual-backend sqlite plumbing.

**Architecture:** A new pure/sqlite helper module `adapters/mail_index.py` holds the Envelope Index row→Pointer mapping, the filter→SQL builder, the `.emlx` parser, and the FTS5 sidecar (build + query). `MailAdapter` gains thin `search(...)` / `index_bodies(...)` delegates. The header plane runs through `runtime.read_via_sqlite` (fingerprint + AppleScript fallback); the body plane is a best-effort layer in `runtime.state_dir()` that never affects header search.

**Tech Stack:** Python 3, stdlib `sqlite3` (FTS5), stdlib `email`/`html.parser`, FastMCP 2.0, `uv`, `pytest`, `ruff`.

## Global Constraints

- Line-length 88; ruff rules `E, F, I, UP, B, SIM`; `ruff format`. No mypy.
- All sqlite reads go via `runtime.read_via_sqlite(path, fingerprint, query, *, fallback=, immutable=False)`. Never open EventKit off the worker; sqlite reads ride the same worker via that helper.
- `immutable=False` (mode=ro, reads `-wal`) for the live Envelope Index. Our own FTS sidecar is opened read-write only inside `index_bodies`.
- Reads return `list[Pointer]`; `Pointer(id, summary, deeplink, folder=None, reason=None)`. `id` = RFC822 Message-ID, `deeplink` = `_deeplink(id)` (`message://…`). No `contracts.py` change.
- SQL values are ALWAYS bound params, never string-formatted. Table/column names are literals in code.
- New tools are read-only: register with `@_read_tool` (or `_READ_ANNOTATIONS`); no entry needed in `test_tool_annotations._WRITE_TOOLS`.
- FTS sidecar path: `runtime.state_dir() / "mail_fts.sqlite"`. Size cap default 200 MB, override `MACOS_APPS_MCP_FTS_MAX_BYTES`. NEVER write inside `~/Library/Mail`.
- Verify before done: `uv run pytest && uv run ruff check . && uv run ruff format --check .`. Integration tests (`-m integration`) run on-device, never CI.

---

### Task 1: Envelope Index location + fingerprint + row→Pointer

**Files:**
- Create: `macos_apps_mcp/adapters/mail_index.py`
- Test: `tests/test_mail_index.py`

**Interfaces:**
- Consumes: `contracts.Pointer`, `adapters.mail._deeplink`.
- Produces:
  - `envelope_index_path() -> pathlib.Path | None` — newest `~/Library/Mail/V*/MailData/Envelope Index`, or None.
  - `HEADER_FINGERPRINT: dict[str, set[str]]`
  - `row_to_pointer(row: sqlite3.Row) -> Pointer | None` — None when `message_id_header` is NULL/blank.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mail_index.py
from macos_apps_mcp.adapters import mail_index


class _Row(dict):
    # sqlite3.Row supports __getitem__ by column name; a dict stands in for tests.
    pass


def test_row_to_pointer_maps_all_fields():
    row = _Row(
        message_id_header="<abc@ex.com>",
        subject="Invoice 42",
        mailbox_url="imap://acct/INBOX",
    )
    p = mail_index.row_to_pointer(row)
    assert p.id == "<abc@ex.com>"
    assert p.summary == "Invoice 42"
    assert p.deeplink == "message://%3Cabc@ex.com%3E"
    assert p.folder == "imap://acct/INBOX"


def test_row_to_pointer_skips_headerless():
    assert mail_index.row_to_pointer(_Row(message_id_header=None, subject="x", mailbox_url="m")) is None
    assert mail_index.row_to_pointer(_Row(message_id_header="  ", subject="x", mailbox_url="m")) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mail_index.py -v`
Expected: FAIL — `ModuleNotFoundError` / `AttributeError: row_to_pointer`.

- [ ] **Step 3: Write minimal implementation**

```python
# macos_apps_mcp/adapters/mail_index.py
"""Mail indexed read plane (#70): a read-only sqlite reader over Mail's Envelope Index
for header/subject/sender search at scale, plus a best-effort FTS5 body sidecar in our
own state dir. Pure/sqlite only — no EventKit, no Mail.app. The MailAdapter delegates
here; this module never launches Mail (read-at-rest)."""

from __future__ import annotations

from pathlib import Path

from ..contracts import Pointer
from .mail import _deeplink

# The Envelope Index tables + the exact columns we read/filter on. A macOS schema move
# that renames/drops any of these trips SchemaDrift → AppleScript fallback (never a
# mis-parsed Pointer). Mirrors notes._FINGERPRINT.
HEADER_FINGERPRINT: dict[str, set[str]] = {
    "messages": {
        "ROWID", "subject", "sender", "global_message_id", "mailbox",
        "date_received", "date_sent", "read", "flagged", "deleted",
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_mail_index.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add macos_apps_mcp/adapters/mail_index.py tests/test_mail_index.py
git commit -m "feat(mail): Envelope Index fingerprint + row→Pointer mapping (#70)"
```

---

### Task 2: Header filter → SQL builder (pure, injection-safe)

**Files:**
- Modify: `macos_apps_mcp/adapters/mail_index.py`
- Test: `tests/test_mail_index.py`

**Interfaces:**
- Produces: `build_header_query(*, subject=None, from_=None, to=None, mailbox=None, since=None, until=None, unread=None, flagged=None, message_ids=None, limit=25) -> tuple[str, list]` — returns `(sql, params)`. `message_ids` (a list of RFC822 ids) restricts to those (used by the body join). Excludes `deleted` messages. Newest-first by `date_received`.

- [ ] **Step 1: Write the failing test**

```python
def test_build_header_query_binds_all_filters():
    sql, params = mail_index.build_header_query(
        subject="inv", from_="jane", mailbox="INBOX",
        since=1000, until=2000, unread=True, flagged=True, limit=10,
    )
    low = sql.lower()
    assert "from messages" in low and "join subjects" in low
    assert "message_global_data" in low
    assert "m.deleted = 0" in low
    assert "order by m.date_received desc" in low
    assert "limit ?" in low
    # every filter value is a bound param, none interpolated
    assert "inv" not in sql and "jane" not in sql
    assert "%inv%" in params and "%jane%" in params
    assert 1000 in params and 2000 in params and 10 in params


def test_build_header_query_message_ids_uses_in_clause():
    sql, params = mail_index.build_header_query(message_ids=["<a@x>", "<b@x>"], limit=25)
    assert "message_id_header in (?" in sql.lower()
    assert "<a@x>" in params and "<b@x>" in params


def test_build_header_query_no_filters_ok():
    sql, params = mail_index.build_header_query(limit=5)
    assert params == [5]  # only the limit
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mail_index.py::test_build_header_query_binds_all_filters -v`
Expected: FAIL — `AttributeError: build_header_query`.

- [ ] **Step 3: Write minimal implementation**

```python
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
    *, subject=None, from_=None, to=None, mailbox=None, since=None, until=None,
    unread=None, flagged=None, message_ids=None, limit=25,
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_mail_index.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add macos_apps_mcp/adapters/mail_index.py tests/test_mail_index.py
git commit -m "feat(mail): injection-safe header filter→SQL builder (#70)"
```

---

### Task 3: `MailAdapter.search()` header path via read_via_sqlite + fallback

**Files:**
- Modify: `macos_apps_mcp/adapters/mail.py` (add `search` method + import mail_index lazily to avoid an import cycle)
- Test: `tests/test_mail_search.py`

**Interfaces:**
- Consumes: `mail_index.envelope_index_path`, `HEADER_FINGERPRINT`, `build_header_query`, `row_to_pointer`; `runtime.read_via_sqlite`; existing `get_pointers` (AppleScript fallback).
- Produces: `MailAdapter.search(self, *, subject=None, from_=None, to=None, mailbox=None, since=None, until=None, unread=None, flagged=None, body=None, limit=MAX_MAILS) -> list[Pointer]`. (Body handling is added in Task 6 — here `body` is accepted but ignored, header-only.)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mail_search.py
import sqlite3

import pytest

from macos_apps_mcp.adapters.mail import MailAdapter
from macos_apps_mcp.adapters import mail_index


def _fake_envelope(path):
    """A minimal Envelope Index with the fingerprinted tables + columns."""
    c = sqlite3.connect(path)
    c.executescript(
        """
        CREATE TABLE subjects(ROWID INTEGER PRIMARY KEY, subject TEXT);
        CREATE TABLE addresses(ROWID INTEGER PRIMARY KEY, address TEXT, comment TEXT);
        CREATE TABLE mailboxes(ROWID INTEGER PRIMARY KEY, url TEXT);
        CREATE TABLE message_global_data(ROWID INTEGER PRIMARY KEY, message_id_header TEXT);
        CREATE TABLE recipients(ROWID INTEGER PRIMARY KEY, message INT, address INT);
        CREATE TABLE messages(
            ROWID INTEGER PRIMARY KEY, subject INT, sender INT, global_message_id INT,
            mailbox INT, date_received INT, date_sent INT, read INT, flagged INT, deleted INT);
        INSERT INTO subjects VALUES (1,'Invoice 42');
        INSERT INTO addresses VALUES (1,'jane@ex.com','Jane Doe');
        INSERT INTO mailboxes VALUES (1,'imap://acct/INBOX');
        INSERT INTO message_global_data VALUES (1,'<abc@ex.com>');
        INSERT INTO messages VALUES (10,1,1,1,1,1700000000,1700000000,0,0,0);
        """
    )
    c.commit()
    c.close()


def test_search_returns_pointers_from_sqlite(tmp_path, monkeypatch):
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    out = MailAdapter().search(subject="Invoice")
    assert len(out) == 1
    assert out[0].id == "<abc@ex.com>"
    assert out[0].summary == "Invoice 42"


def test_search_falls_back_on_drift(tmp_path, monkeypatch):
    db = tmp_path / "Envelope Index"
    sqlite3.connect(db).executescript("CREATE TABLE messages(ROWID INTEGER);")  # missing cols → drift
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    adapter = MailAdapter()
    monkeypatch.setattr(adapter, "get_pointers", lambda q: ["FALLBACK"])
    assert adapter.search(subject="x") == ["FALLBACK"]


def test_search_no_store_raises(monkeypatch):
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: None)
    with pytest.raises(Exception):
        MailAdapter().search(subject="x")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mail_search.py -v`
Expected: FAIL — `AttributeError: 'MailAdapter' object has no attribute 'search'`.

- [ ] **Step 3: Write minimal implementation**

Add to `MailAdapter` in `macos_apps_mcp/adapters/mail.py` (import `mail_index` inside the method to avoid the mail_index→mail import cycle at module load):

```python
    def search(
        self, *, subject=None, from_=None, to=None, mailbox=None, since=None,
        until=None, unread=None, flagged=None, body=None, limit=MAX_MAILS,
    ) -> list[Pointer]:
        """Indexed search over ALL mailboxes via Mail's Envelope Index (read-at-rest).
        All filters optional, ANDed. Falls back to the AppleScript inbox search on
        missing FDA / schema drift. `body` is handled in a later task (best-effort FTS);
        header-only here."""
        from . import mail_index
        from ..runtime import read_via_sqlite

        path = mail_index.envelope_index_path()
        if path is None:
            raise NativeError(
                "no Mail data found (~/Library/Mail/V*/MailData/Envelope Index). "
                "Open Mail once to create it. Do not retry."
            )

        sql, params = mail_index.build_header_query(
            subject=subject, from_=from_, to=to, mailbox=mailbox, since=since,
            until=until, unread=unread, flagged=flagged, limit=limit,
        )

        def read(conn):
            conn.row_factory = __import__("sqlite3").Row
            out = []
            for row in conn.execute(sql, params):
                p = mail_index.row_to_pointer(row)
                if p is not None:
                    out.append(p)
            return out

        # Fallback: the existing AppleScript inbox search needs a substring — use the
        # most specific text filter provided (subject/from/mailbox), else empty (raises).
        needle = subject or from_ or to or mailbox or ""
        return read_via_sqlite(
            path,
            mail_index.HEADER_FINGERPRINT,
            read,
            fallback=(lambda: self.get_pointers(needle)) if needle else None,
            immutable=False,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_mail_search.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add macos_apps_mcp/adapters/mail.py tests/test_mail_search.py
git commit -m "feat(mail): MailAdapter.search header plane via read_via_sqlite (#70)"
```

---

### Task 4: `.emlx` parser (pure)

**Files:**
- Modify: `macos_apps_mcp/adapters/mail_index.py`
- Test: `tests/test_mail_index.py`

**Interfaces:**
- Produces: `parse_emlx(raw: bytes) -> tuple[str, str] | None` — `(message_id, body_text)` or None when the file is malformed, header-less, or has no extractable text. `.emlx` layout = a decimal byte-count first line, then that many bytes of RFC822, then a trailing XML plist.

- [ ] **Step 1: Write the failing test**

```python
import textwrap


def _emlx(rfc822: bytes) -> bytes:
    return f"{len(rfc822)}\n".encode() + rfc822 + b"<?xml version='1.0'?><plist></plist>"


def test_parse_emlx_plaintext():
    raw = _emlx(
        b"From: a@x.com\r\nMessage-ID: <m1@x.com>\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\nHello invoice body"
    )
    mid, body = mail_index.parse_emlx(raw)
    assert mid == "<m1@x.com>"
    assert "invoice body" in body


def test_parse_emlx_html_stripped():
    raw = _emlx(
        b"Message-ID: <m2@x.com>\r\nContent-Type: text/html\r\n\r\n"
        b"<p>Hello <b>world</b></p>"
    )
    mid, body = mail_index.parse_emlx(raw)
    assert mid == "<m2@x.com>"
    assert "Hello" in body and "<b>" not in body


def test_parse_emlx_headerless_returns_none():
    raw = _emlx(b"From: a@x.com\r\n\r\nno message id here")
    assert mail_index.parse_emlx(raw) is None


def test_parse_emlx_malformed_returns_none():
    assert mail_index.parse_emlx(b"not an emlx at all") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mail_index.py -k parse_emlx -v`
Expected: FAIL — `AttributeError: parse_emlx`.

- [ ] **Step 3: Write minimal implementation**

```python
from email import message_from_bytes
from html.parser import HTMLParser


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
    """Prefer text/plain; else the first text/html rendered to text. Empty if neither."""
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
    """(message_id, body_text) from an .emlx byte string, or None if malformed /
    header-less / no extractable text. Strips the length-prefix line and trailing plist."""
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_mail_index.py -k parse_emlx -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add macos_apps_mcp/adapters/mail_index.py tests/test_mail_index.py
git commit -m "feat(mail): .emlx parser — message-id + body text (#70)"
```

---

### Task 5: FTS5 body sidecar — build, resume, size-cap

**Files:**
- Modify: `macos_apps_mcp/adapters/mail_index.py`
- Test: `tests/test_mail_index.py`

**Interfaces:**
- Produces:
  - `fts_path() -> pathlib.Path` — `runtime.state_dir() / "mail_fts.sqlite"`.
  - `fts_max_bytes() -> int` — env `MACOS_APPS_MCP_FTS_MAX_BYTES` or 200 MB.
  - `build_body_index(*, mail_root: Path, fts_db: Path, rebuild: bool = False, max_bytes: int) -> dict` — walk full `.emlx` under `mail_root` (skip `*.partial.emlx`), parse, upsert into FTS keyed by message-id; skip files already recorded unchanged; stop at `max_bytes`. Returns `{"indexed", "skipped", "total_emlx", "capped"}`.

- [ ] **Step 1: Write the failing test**

```python
def _write_emlx(path, mid, body):
    rfc = (f"Message-ID: {mid}\r\nContent-Type: text/plain\r\n\r\n{body}").encode()
    path.write_bytes(f"{len(rfc)}\n".encode() + rfc + b"<plist/>")


def test_build_body_index_indexes_full_skips_partial(tmp_path):
    root = tmp_path / "Mail"
    msgs = root / "V10/acct/INBOX.mbox/Data/Messages"
    msgs.mkdir(parents=True)
    _write_emlx(msgs / "1.emlx", "<a@x>", "quarterly invoice total")
    _write_emlx(msgs / "2.partial.emlx", "<b@x>", "should be skipped")
    fts = tmp_path / "mail_fts.sqlite"
    res = mail_index.build_body_index(mail_root=root, fts_db=fts, max_bytes=10**9)
    assert res["indexed"] == 1 and res["total_emlx"] == 1  # partial not counted
    assert mail_index.fts_search(fts, "invoice") == ["<a@x>"]


def test_build_body_index_resumes(tmp_path):
    root = tmp_path / "Mail"; msgs = root / "V10/M"; msgs.mkdir(parents=True)
    _write_emlx(msgs / "1.emlx", "<a@x>", "first")
    fts = tmp_path / "mail_fts.sqlite"
    mail_index.build_body_index(mail_root=root, fts_db=fts, max_bytes=10**9)
    _write_emlx(msgs / "2.emlx", "<b@x>", "second")
    res = mail_index.build_body_index(mail_root=root, fts_db=fts, max_bytes=10**9)
    assert res["indexed"] == 1 and res["skipped"] == 1  # only the new file indexed


def test_build_body_index_size_capped(tmp_path):
    root = tmp_path / "Mail"; msgs = root / "V10/M"; msgs.mkdir(parents=True)
    for i in range(5):
        _write_emlx(msgs / f"{i}.emlx", f"<{i}@x>", "body " * 50)
    fts = tmp_path / "mail_fts.sqlite"
    res = mail_index.build_body_index(mail_root=root, fts_db=fts, max_bytes=1)  # tiny cap
    assert res["capped"] is True and res["indexed"] >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mail_index.py -k build_body_index -v`
Expected: FAIL — `AttributeError: build_body_index`.

- [ ] **Step 3: Write minimal implementation**

```python
import os
import sqlite3

_FTS_DEFAULT_MAX = 200 * 1024 * 1024  # ~200 MB


def fts_path() -> Path:
    from ..runtime import state_dir
    return state_dir() / "mail_fts.sqlite"


def fts_max_bytes() -> int:
    raw = os.environ.get("MACOS_APPS_MCP_FTS_MAX_BYTES")
    return int(raw) if raw and raw.isdigit() else _FTS_DEFAULT_MAX


def _fts_connect(fts_db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(fts_db)
    conn.executescript(
        "CREATE VIRTUAL TABLE IF NOT EXISTS bodies USING fts5(message_id UNINDEXED, body);"
        "CREATE TABLE IF NOT EXISTS indexed_files"
        "(path TEXT PRIMARY KEY, mtime INTEGER, size INTEGER);"
    )
    return conn


def build_body_index(
    *, mail_root: Path, fts_db: Path, rebuild: bool = False, max_bytes: int | None = None
) -> dict:
    """Best-effort FTS body index over full .emlx (skips *.partial.emlx). Resumable
    (skips unchanged files), size-capped (stops when fts_db exceeds max_bytes). Never
    touches Mail's data — reads .emlx at rest, writes only fts_db."""
    if max_bytes is None:
        max_bytes = fts_max_bytes()
    if rebuild and fts_db.exists():
        fts_db.unlink()
    conn = _fts_connect(fts_db)
    seen = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT path, mtime, size FROM indexed_files")}
    indexed = skipped = total = 0
    capped = False
    try:
        for f in sorted(mail_root.rglob("*.emlx")):
            if f.name.endswith(".partial.emlx"):
                continue
            total += 1
            st = f.stat()
            key = str(f)
            if seen.get(key) == (int(st.st_mtime), st.st_size):
                skipped += 1
                continue
            if fts_db.stat().st_size >= max_bytes:
                capped = True
                break
            parsed = parse_emlx(f.read_bytes())
            if parsed is None:
                # record so a re-run doesn't reparse an unindexable file
                conn.execute(
                    "INSERT OR REPLACE INTO indexed_files VALUES (?,?,?)",
                    (key, int(st.st_mtime), st.st_size),
                )
                skipped += 1
                continue
            mid, body = parsed
            conn.execute("DELETE FROM bodies WHERE message_id = ?", (mid,))
            conn.execute("INSERT INTO bodies (message_id, body) VALUES (?, ?)", (mid, body))
            conn.execute(
                "INSERT OR REPLACE INTO indexed_files VALUES (?,?,?)",
                (key, int(st.st_mtime), st.st_size),
            )
            conn.commit()
            indexed += 1
    finally:
        conn.commit()
        conn.close()
    return {"indexed": indexed, "skipped": skipped, "total_emlx": total, "capped": capped}


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_mail_index.py -k "build_body_index or fts_search" -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add macos_apps_mcp/adapters/mail_index.py tests/test_mail_index.py
git commit -m "feat(mail): FTS5 body sidecar — build, resume, size-cap (#70)"
```

---

### Task 6: Wire `body=` into `search()` + `MailAdapter.index_bodies()`

**Files:**
- Modify: `macos_apps_mcp/adapters/mail.py`
- Modify: `macos_apps_mcp/adapters/mail_index.py` (add `mail_root()`)
- Test: `tests/test_mail_search.py`

**Interfaces:**
- Consumes: `fts_search`, `build_body_index`, `fts_path`, `envelope_index_path`.
- Produces:
  - `mail_index.mail_root() -> Path | None` — `~/Library/Mail` (parent of the V* dirs), or None.
  - `MailAdapter.index_bodies(self, rebuild: bool = False) -> dict` — `{indexed, skipped, total_emlx, capped, coverage}` where `coverage = "indexed/total_messages"` (total from the header store count).
  - `search(..., body=...)` now: when `body` is set, FTS → message-ids → `build_header_query(message_ids=…)` intersect; logs a coverage line; returns `[]` (not error) when the sidecar is empty, but logs "run mail_index_bodies".

- [ ] **Step 1: Write the failing test**

```python
def test_search_body_intersects_fts(tmp_path, monkeypatch):
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    # FTS returns the one indexed message-id; header join keeps it
    monkeypatch.setattr(mail_index, "fts_path", lambda: tmp_path / "fts.sqlite")
    monkeypatch.setattr(mail_index, "fts_search", lambda db_, q, limit=200: ["<abc@ex.com>"])
    out = MailAdapter().search(body="invoice")
    assert [p.id for p in out] == ["<abc@ex.com>"]


def test_search_body_empty_index_returns_empty(tmp_path, monkeypatch):
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    monkeypatch.setattr(mail_index, "fts_search", lambda db_, q, limit=200: [])
    assert MailAdapter().search(body="nothing") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mail_search.py -k body -v`
Expected: FAIL — body filter currently ignored, returns the subject-less full set (not intersected) / or wrong.

- [ ] **Step 3: Write minimal implementation**

Add `mail_root` to `mail_index.py`:

```python
def mail_root() -> Path | None:
    root = Path.home() / "Library" / "Mail"
    return root if root.exists() else None
```

Update `search()` in `mail.py` — before building the header query, resolve the body filter to a message-id restriction:

```python
        from . import mail_index
        from ..runtime import log, read_via_sqlite

        path = mail_index.envelope_index_path()
        if path is None:
            raise NativeError(...)  # unchanged

        message_ids = None
        if body:
            message_ids = mail_index.fts_search(mail_index.fts_path(), body, limit=limit)
            if not message_ids:
                log.info("mail_search body=%r: no FTS matches (run mail_index_bodies to "
                         "build/refresh the body index)", body)
                return []

        sql, params = mail_index.build_header_query(
            subject=subject, from_=from_, to=to, mailbox=mailbox, since=since,
            until=until, unread=unread, flagged=flagged, message_ids=message_ids,
            limit=limit,
        )
        # ... read() + read_via_sqlite unchanged ...
        if body:
            log.info("mail_search body=%r: searched %d indexed messages", body, len(message_ids))
```

Add `index_bodies`:

```python
    def index_bodies(self, rebuild: bool = False) -> dict:
        """Opt-in build/refresh of the best-effort FTS body index over downloaded .emlx
        (read-at-rest; skips not-yet-downloaded *.partial.emlx). Resumable, size-capped.
        Returns counts + coverage. Never launches Mail, never writes in Mail's data."""
        from . import mail_index

        root = mail_index.mail_root()
        if root is None:
            raise NativeError("no Mail data found; open Mail once. Do not retry.")
        res = mail_index.build_body_index(
            mail_root=root, fts_db=mail_index.fts_path(), rebuild=rebuild
        )
        res["coverage"] = f"{res['indexed']}/{res['total_emlx']} downloaded .emlx indexed"
        return res
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_mail_search.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add macos_apps_mcp/adapters/mail.py macos_apps_mcp/adapters/mail_index.py tests/test_mail_search.py
git commit -m "feat(mail): body= FTS intersection + index_bodies (#70)"
```

---

### Task 7: Register `mail_search` + `mail_index_bodies` tools

**Files:**
- Modify: `macos_apps_mcp/server.py`
- Test: `tests/test_mail_search.py` (registration) — reuse the FastMCP `Client` pattern from `tests/test_tool_annotations.py`.

**Interfaces:**
- Consumes: `_mail.search`, `_mail.index_bodies`, `_read_tool`, `_READ_ANNOTATIONS`.
- Produces: MCP tools `mail_search(...)`, `mail_index_bodies(rebuild=False)`. Both read-only annotated.

- [ ] **Step 1: Write the failing test**

```python
import asyncio
from fastmcp import Client
import macos_apps_mcp.server as srv


def test_mail_search_tool_registered_read_only():
    async def go():
        async with Client(srv.mcp) as c:
            tools = {t.name: t for t in await c.list_tools()}
            assert "mail_search" in tools and "mail_index_bodies" in tools
            assert tools["mail_search"].annotations.readOnlyHint is True
            assert tools["mail_index_bodies"].annotations.readOnlyHint is True
    asyncio.run(go())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mail_search.py -k tool_registered -v`
Expected: FAIL — tools not registered.

- [ ] **Step 3: Write minimal implementation**

Add to `macos_apps_mcp/server.py`, alongside the other mail tools (thin dispatch — no logic):

```python
@_read_tool
def mail_search(
    subject: str = "", from_: str = "", to: str = "", mailbox: str = "",
    since: int | None = None, until: int | None = None,
    unread: bool = False, flagged: bool = False, body: str = "", limit: int = 25,
) -> list[dict]:
    """Indexed search across ALL mailboxes via Mail's Envelope Index — fast, read-only,
    no Mail launch. All filters optional and ANDed: subject/from_/to/mailbox substrings,
    since/until (epoch seconds on received date), unread/flagged. `body` searches message
    TEXT via the FTS index and is BEST-EFFORT — it only sees messages already downloaded
    AND indexed by mail_index_bodies (run that first; partial coverage is normal). At
    least one filter required. Returns citable Pointers, newest first. Falls back to the
    AppleScript inbox search on missing Full Disk Access / schema drift."""
    if not any([subject, from_, to, mailbox, since, until, unread, flagged, body]):
        raise ValueError("mail_search needs at least one filter")
    return [
        p.as_dict()
        for p in _mail.search(
            subject=subject or None, from_=from_ or None, to=to or None,
            mailbox=mailbox or None, since=since, until=until,
            unread=unread, flagged=flagged, body=body or None, limit=limit,
        )
    ]


@_read_tool
def mail_index_bodies(rebuild: bool = False) -> dict:
    """Build/refresh the opt-in FTS body index used by mail_search(body=…). Reads
    downloaded .emlx files at rest (never launches Mail, never writes in Mail's data);
    skips not-yet-downloaded messages. Resumable and size-capped — safe to re-run; a
    re-run continues where a stop left off. rebuild=True re-indexes from scratch. Returns
    {indexed, skipped, total_emlx, capped, coverage}."""
    return _mail.index_bodies(rebuild=rebuild)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_mail_search.py -k tool_registered -v && uv run pytest tests/test_tool_annotations.py -v`
Expected: PASS (both — `test_tool_annotations` still green: the new tools are read-only, needing no `_WRITE_TOOLS` entry).

- [ ] **Step 5: Commit**

```bash
git add macos_apps_mcp/server.py tests/test_mail_search.py
git commit -m "feat(mail): register mail_search + mail_index_bodies tools (#70)"
```

---

### Task 8: On-device integration tests

**Files:**
- Create: `tests/test_mail_search_integration.py`
- Test: itself (`-m integration`, run manually on this Mac — NEVER CI)

**Interfaces:**
- Consumes: `MailAdapter().search`, `.index_bodies`; real `~/Library/Mail`.

- [ ] **Step 1: Write the integration tests**

```python
# tests/test_mail_search_integration.py
import time

import pytest

from macos_apps_mcp.adapters.mail import MailAdapter

pytestmark = pytest.mark.integration


def test_subject_search_under_1s():
    adapter = MailAdapter()
    t0 = time.perf_counter()
    out = adapter.search(subject="the", limit=25)  # a common word → real work
    dt = time.perf_counter() - t0
    assert dt < 1.0, f"subject search took {dt:.3f}s (acceptance: <1s)"
    assert all(p.id and p.deeplink.startswith("message://") for p in out)


def test_index_bodies_then_body_search():
    adapter = MailAdapter()
    res = adapter.index_bodies()  # opt-in build (resumable — may be a no-op if built)
    assert res["indexed"] >= 0 and "coverage" in res
    # a re-run indexes nothing new (resume works)
    res2 = adapter.index_bodies()
    assert res2["indexed"] == 0 or res2["skipped"] > 0


def test_search_all_mailboxes_beats_inbox_only():
    # sqlite path reaches non-inbox folders the AppleScript inbox search cannot.
    out = MailAdapter().search(mailbox="Sent", limit=5)
    assert isinstance(out, list)
```

- [ ] **Step 2: Run the integration suite on-device**

Run: `uv run pytest -m integration -k mail_search -v`
Expected: PASS on this Mac (grant Full Disk Access if the sqlite path degrades to fallback). Record the measured subject-search time.

- [ ] **Step 3: Full verification gate**

Run: `uv run pytest && uv run ruff check . && uv run ruff format --check .`
Expected: all unit tests PASS, ruff clean.

- [ ] **Step 4: Commit**

```bash
git add tests/test_mail_search_integration.py
git commit -m "test(mail): on-device integration for indexed search + body index (#70)"
```

---

## Notes for the implementer

- **Import cycle:** `mail_index.py` imports `_deeplink` from `mail.py` at module load; `mail.py` imports `mail_index` **inside methods** (lazy) to avoid a cycle. Keep it that way.
- **`log`:** `runtime.log` is the module logger (`logging.getLogger("macos_apps_mcp")`). Use `log.info(...)` for the coverage line — do not print.
- **Coverage honesty (spec):** body results are limited to the indexed/downloaded subset; the `mail_search` docstring says so and `index_bodies` returns the exact `coverage`. The per-search coverage is logged, not a Pointer field (keeps the `list[Pointer]` contract uniform).
- **`ponytail:`** the size cap is a hard byte ceiling checked before each insert (not a row estimate); upgrade path = incremental/background indexing (issue #119 territory) if the cap bites in practice.
