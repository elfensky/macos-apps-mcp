# Mail Reads Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `has_attachments` + `account` filters to `mail_search` (#75), a `mail_overview` tool (#76), and a `mail_thread` tool (#77) — all on the existing Envelope Index read plane, all sharing one SQL dedup rule.

**Architecture:** Every query is a pure function in `adapters/mail_index.py` returning `(sql, params)`; `MailAdapter` runs them through the existing `read_via_sqlite` helper; `server.py` gets two thin `@_read_tool`s. A shared `_MAILBOX_RANK` / `ROW_NUMBER()` CTE deduplicates by RFC822 Message-ID inside SQL, so `LIMIT` counts distinct messages. No new dependency, no new plumbing.

**Tech Stack:** Python 3.12+, FastMCP, stdlib `sqlite3` (window functions), `urllib.parse.unquote`, `uv`, `pytest`, `ruff`.

**Spec:** [docs/superpowers/specs/2026-07-27-mail-reads-design.md](../specs/2026-07-27-mail-reads-design.md)

## Global Constraints

- **Read tier only.** Every tool here is `@_read_tool`. No `_write_tool`, no `_send_tool`, no `dry_run`. `tests/test_tool_annotations.py` enforces this automatically.
- **All native access via `runtime`.** `read_via_sqlite(path, fingerprint, query, fallback=…, immutable=False)` for sqlite; `run_osascript(script, *argv)` argv-only for AppleScript. **Never interpolate user input into a script.** Never widen the executor past `max_workers=1`.
- **Query builders are pure.** Everything in `mail_index.py` returns `(sql, params)` or plain data and never opens a connection, so it unit-tests without a Mac.
- **Every filter value is a bound parameter.** Literal SQL is allowed only for the fixed rank/extension constants, which contain no user input.
- **Style:** `ruff`, line-length 88, rules `E, F, I, UP, B, SIM`. No mypy.
- **Verify before claiming done** (all four must pass):
  ```sh
  uv run pytest
  MACOS_APPS_ALLOW_SEND=mail uv run pytest
  uv run ruff check .
  uv run ruff format --check .
  ```
- **Test-count guard:** `grep -c "^def test_" tests/test_mail.py` must not drop below **88**. A past fix wave silently deleted five tests while the suite total stayed flat.
- **Integration tests** (`-m integration`) run on-device only, **never in CI**.
- **Do not rebuild the daemon** as part of these tasks. The repo is not the daemon; redeployment is a separate step at the end of the branch (`docs/DAEMON.md`).

---

### Task 1: Extend the schema fingerprint and the shared test fixture

Adds the columns/tables later tasks query. Doing this first means every later task's fixture already has them.

**Files:**
- Modify: `macos_apps_mcp/adapters/mail_index.py:21-39` (`HEADER_FINGERPRINT`)
- Modify: `tests/test_mail_search.py:13-35` (`_fake_envelope`)
- Test: `tests/test_mail_index.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `HEADER_FINGERPRINT` gains `messages.conversation_id` and an `attachments: {"ROWID", "message", "name"}` entry. `_fake_envelope(path)` builds a fixture carrying `conversation_id`, an `attachments` table, and multi-mailbox duplicate rows used by Tasks 2–6.

- [ ] **Step 1: Write the failing test**

In `tests/test_mail_index.py`, append:

```python
def test_fingerprint_covers_conversation_and_attachments():
    # conversation_id backs mail_thread; attachments backs has_attachments. Both must be
    # fingerprinted or a macOS schema move would silently mis-answer instead of drifting.
    assert "conversation_id" in mail_index.HEADER_FINGERPRINT["messages"]
    assert mail_index.HEADER_FINGERPRINT["attachments"] == {"ROWID", "message", "name"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mail_index.py::test_fingerprint_covers_conversation_and_attachments -v`
Expected: FAIL — `KeyError: 'attachments'`

- [ ] **Step 3: Write minimal implementation**

In `macos_apps_mcp/adapters/mail_index.py`, inside `HEADER_FINGERPRINT`, add `"conversation_id",` to the `"messages"` set (after `"deleted",`) and add a new top-level entry after `"recipients": {"message", "address"},`:

```python
    # conversation_id: Mail's own threading key (five dedicated indexes on it), read by
    # build_thread_query. attachments: backs has_attachments — an indexed EXISTS, never a
    # per-message AppleScript probe.
    "attachments": {"ROWID", "message", "name"},
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_mail_index.py -v`
Expected: PASS

- [ ] **Step 5: Extend the shared fixture**

Replace `_fake_envelope` in `tests/test_mail_search.py` entirely with:

```python
def _fake_envelope(path):
    """A minimal Envelope Index with the fingerprinted tables + columns.

    Deliberately includes the duplicate shapes found on a real Mac: <abc@ex.com> exists
    in INBOX *and* Archive (cross-folder), and <dup@ex.com> exists twice in the SAME
    folder (a migration copy that ran twice). Dedup tests depend on both.
    """
    c = sqlite3.connect(path)
    c.executescript(
        """
        CREATE TABLE subjects(ROWID INTEGER PRIMARY KEY, subject TEXT);
        CREATE TABLE addresses(ROWID INTEGER PRIMARY KEY, address TEXT, comment TEXT);
        CREATE TABLE mailboxes(ROWID INTEGER PRIMARY KEY, url TEXT);
        CREATE TABLE message_global_data(
            ROWID INTEGER PRIMARY KEY, message_id_header TEXT);
        CREATE TABLE recipients(ROWID INTEGER PRIMARY KEY, message INT, address INT);
        CREATE TABLE attachments(
            ROWID INTEGER PRIMARY KEY, message INT, name TEXT);
        CREATE TABLE messages(
            ROWID INTEGER PRIMARY KEY, subject INT, sender INT, global_message_id INT,
            mailbox INT, date_received INT, date_sent INT, read INT, flagged INT,
            deleted INT, conversation_id INT);
        INSERT INTO subjects VALUES (1,'Invoice 42'),(2,'Re: Invoice 42');
        INSERT INTO addresses VALUES (1,'jane@ex.com','Jane Doe');
        INSERT INTO mailboxes VALUES
            (1,'imap://AAAA/INBOX'),(2,'imap://AAAA/Archive'),(3,'imap://BBBB/Travel');
        INSERT INTO message_global_data VALUES
            (1,'<abc@ex.com>'),(2,'<reply@ex.com>'),(3,'<dup@ex.com>');
        -- <abc@ex.com>: INBOX + Archive, same conversation 7 as its reply
        INSERT INTO messages VALUES (10,1,1,1,1,1700000000,1700000000,0,0,0,7);
        INSERT INTO messages VALUES (11,1,1,1,2,1700000000,1700000000,0,0,0,7);
        -- the reply, newer, in Travel, conversation 7
        INSERT INTO messages VALUES (12,2,1,2,3,1700000900,1700000900,1,0,0,7);
        -- <dup@ex.com>: twice in the SAME mailbox, unrelated conversation
        INSERT INTO messages VALUES (13,1,1,3,3,1700000500,1700000500,0,0,0,9);
        INSERT INTO messages VALUES (14,1,1,3,3,1700000500,1700000500,0,0,0,9);
        INSERT INTO attachments VALUES (1,10,'contract.pdf'),(2,12,'image001.png');
        """
    )
    c.commit()
    c.close()
```

- [ ] **Step 6: Run the full mail suite to verify nothing regressed**

Run: `uv run pytest tests/test_mail_search.py tests/test_mail_index.py -v`
Expected: PASS. `test_search_returns_pointers_from_sqlite` asserts `len(out) == 1` and still passes — Task 2 introduces dedup; today the query has no `conversation_id`/`attachments` dependency, and `subject="Invoice"` matches only `<abc@ex.com>` rows, which currently return **two** rows (INBOX + Archive). **If this test fails with `len(out) == 2`, that is expected and correct** — change the assertion to `len(out) == 2` with the comment `# deduped to 1 in Task 2` and let Task 2 flip it back.

- [ ] **Step 7: Commit**

```bash
git add macos_apps_mcp/adapters/mail_index.py tests/test_mail_index.py tests/test_mail_search.py
git commit -m "test(mail): fingerprint conversation_id + attachments, fixture grows real duplicate shapes"
```

---

### Task 2: Dedup by Message-ID inside the header query

The load-bearing change. 27% of messages on a real Mac live in 2+ mailboxes, so `mail_search` returns the same mail several times today.

**Files:**
- Modify: `macos_apps_mcp/adapters/mail_index.py:73-135` (`_BASE_SQL`, `build_header_query`)
- Test: `tests/test_mail_index.py`, `tests/test_mail_search.py`

**Interfaces:**
- Consumes: `_fake_envelope` from Task 1.
- Produces: `mail_index._MAILBOX_RANK` (a SQL `CASE` string, no bound params) and `mail_index._DEDUP_SELECT_COLS`, reused verbatim by `build_thread_query` in Task 5. `build_header_query(...)` keeps its signature and returns one row per distinct `message_id_header`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_mail_index.py`, append:

```python
def test_header_query_deduplicates_by_message_id():
    sql, _ = mail_index.build_header_query(subject="x", limit=5)
    low = sql.lower()
    assert "row_number() over" in low
    assert "partition by gd.message_id_header" in low
    assert "where rn = 1" in low


def test_header_query_excludes_headerless_rows():
    # no Message-ID means no citable Pointer; excluding in SQL (not after) keeps LIMIT
    # honest — otherwise LIMIT 25 can return 20 usable rows.
    sql, _ = mail_index.build_header_query(subject="x", limit=5)
    low = sql.lower()
    assert "gd.message_id_header is not null" in low
    assert "gd.message_id_header <> ''" in low
```

In `tests/test_mail_search.py`, append:

```python
def test_search_dedupes_cross_folder_preferring_inbox(tmp_path, monkeypatch):
    # <abc@ex.com> is in INBOX and Archive. One Pointer, and it cites the INBOX copy.
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    out = MailAdapter().search(subject="Invoice 42")
    assert [p.id for p in out].count("<abc@ex.com>") == 1
    inbox = [p for p in out if p.id == "<abc@ex.com>"][0]
    assert inbox.folder == "imap://AAAA/INBOX"


def test_search_dedupes_same_folder_copies(tmp_path, monkeypatch):
    # <dup@ex.com> exists twice in the SAME mailbox (migration ran twice) — collapses.
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    out = MailAdapter().search(subject="Invoice", limit=25)
    assert [p.id for p in out].count("<dup@ex.com>") == 1


def test_search_limit_counts_distinct_messages(tmp_path, monkeypatch):
    # LIMIT must apply AFTER dedup: limit=2 over 5 rows / 3 distinct ids returns 2
    # messages, not 2 rows that collapse to 1.
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    out = MailAdapter().search(subject="Invoice", limit=2)
    assert len(out) == 2
    assert len({p.id for p in out}) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mail_index.py tests/test_mail_search.py -k "dedup or headerless or distinct" -v`
Expected: FAIL — `assert 'row_number() over' in low` fails; the search tests return duplicate ids.

- [ ] **Step 3: Write the implementation**

In `macos_apps_mcp/adapters/mail_index.py`, replace `_BASE_SQL` (lines 73–84) with:

```python
# Dedup (#75/#76/#77): a real mailbox stores the SAME RFC822 Message-ID in several
# mailboxes — device-verified, 36,112 non-deleted rows resolving to 22,223 distinct ids.
# Three causes, none fixable by cleaning up: Gmail shows one server message under both a
# label and All Mail, a migration leaves copies on two accounts, and every reply makes a
# Sent-plus-folder pair. Apple hit this too (mailboxes.unread_count_adjusted_for_
# duplicates). So one row per Message-ID, ranked: a live INBOX copy beats a filed copy,
# which beats an All Mail / Archive / Trash / Junk copy. Fixed literals, no user input —
# every *filter* value is still a bound param.
_MAILBOX_RANK = """CASE
           WHEN mb.url LIKE '%/INBOX' THEN 0
           WHEN mb.url LIKE '%All%Mail' OR mb.url LIKE '%/Archive'
             OR mb.url LIKE '%/Trash'   OR mb.url LIKE '%Deleted%Messages'
             OR mb.url LIKE '%Junk'     OR mb.url LIKE '%Spam' THEN 2
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
```

Then in `build_header_query`, replace the two closing lines:

```python
    sql += " ORDER BY m.date_received DESC LIMIT ?"
    params.append(limit)
    return sql, params
```

with:

```python
    # Dedup and LIMIT wrap the filtered set: rank inside, pick rn = 1, then LIMIT — so
    # LIMIT counts distinct messages, not rows that collapse afterwards.
    sql = (
        f"SELECT message_id_header, subject, mailbox_url, date_received FROM ({sql})"
        " WHERE rn = 1 ORDER BY date_received DESC LIMIT ?"
    )
    params.append(limit)
    return sql, params
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_mail_index.py tests/test_mail_search.py -v`
Expected: PASS. If Step 6 of Task 1 required loosening `test_search_returns_pointers_from_sqlite` to `len(out) == 2`, restore it to `len(out) == 1` now and drop the temporary comment.

- [ ] **Step 5: Run the whole suite — this changes shared behaviour**

Run: `uv run pytest`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add macos_apps_mcp/adapters/mail_index.py tests/test_mail_index.py tests/test_mail_search.py
git commit -m "fix(mail): one Pointer per Message-ID — search returned the same mail up to 8 times"
```

---

### Task 3: `has_attachments` and `account` filters (#75)

**Files:**
- Modify: `macos_apps_mcp/adapters/mail_index.py` (`build_header_query`)
- Test: `tests/test_mail_index.py`, `tests/test_mail_search.py`

**Interfaces:**
- Consumes: `_BASE_SQL` from Task 2.
- Produces: `build_header_query(..., has_attachments: bool | None = None, account: str | None = None)`. `account` is matched as a substring of `mailboxes.url`, so it accepts a raw account UUID; name→UUID resolution is Task 4's job and happens before this is called. `mail_index._IMAGE_EXTS` is the image-extension tuple.

- [ ] **Step 1: Write the failing tests**

In `tests/test_mail_index.py`, append:

```python
def test_has_attachments_excludes_inline_images():
    # Mail records signature/newsletter images as attachment rows — device-verified, the
    # top names on a real Mac are image001.png (426) and embed0.png (285). A naive EXISTS
    # matched 4,474 messages where only 2,223 carried a real document.
    sql, _ = mail_index.build_header_query(has_attachments=True, limit=5)
    low = sql.lower()
    assert "exists" in low and "attachments" in low
    for ext in ("png", "jpg", "jpeg", "gif"):
        assert f"%.{ext}" in low


def test_has_attachments_false_adds_no_clause():
    with_f, _ = mail_index.build_header_query(subject="x", has_attachments=False, limit=5)
    without, _ = mail_index.build_header_query(subject="x", limit=5)
    assert with_f == without


def test_account_is_a_bound_param():
    sql, params = mail_index.build_header_query(account="AAAA", limit=5)
    assert "AAAA" not in sql
    assert "%AAAA%" in params
```

In `tests/test_mail_search.py`, append:

```python
def test_search_has_attachments_matches_document_not_image(tmp_path, monkeypatch):
    # msg 10 (<abc@ex.com>) has contract.pdf; msg 12 (<reply@ex.com>) has only
    # image001.png and must NOT match.
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    ids = [p.id for p in MailAdapter().search(has_attachments=True)]
    assert "<abc@ex.com>" in ids
    assert "<reply@ex.com>" not in ids


def test_search_account_filters_by_uuid(tmp_path, monkeypatch):
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    # mailbox 3 (imap://BBBB/Travel) holds <reply@ex.com> and both <dup@ex.com> copies
    ids = [p.id for p in MailAdapter().search(account="BBBB")]
    assert set(ids) == {"<reply@ex.com>", "<dup@ex.com>"}
    assert "<abc@ex.com>" not in ids  # lives only under account AAAA
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mail_index.py tests/test_mail_search.py -k "attachment or account" -v`
Expected: FAIL — `TypeError: build_header_query() got an unexpected keyword argument 'has_attachments'`

- [ ] **Step 3: Write the implementation**

In `macos_apps_mcp/adapters/mail_index.py`, above `build_header_query`, add:

```python
# has_attachments means "carries a real document". Mail counts inline signature and
# newsletter images as attachment rows, so a naive EXISTS is noise-dominated — on a real
# Mac 4,474 messages "have an attachment" while only 2,223 carry a document. Names with
# no extension count as documents: a false positive beats a silently dropped attachment.
_IMAGE_EXTS = (
    "png", "jpg", "jpeg", "gif", "webp", "heic", "bmp", "tiff", "tif", "svg", "ico",
)

_HAS_DOCUMENT = (
    " AND EXISTS (SELECT 1 FROM attachments at WHERE at.message = m.ROWID"
    " AND (at.name IS NULL OR NOT ("
    + " OR ".join(f"lower(at.name) LIKE '%.{e}'" for e in _IMAGE_EXTS)
    + ")))"
)
```

Add the two parameters to the `build_header_query` signature, after `flagged=None`:

```python
    has_attachments=None,
    account=None,
```

And add the two clauses inside the function body, immediately after the `if flagged:` block:

```python
    if has_attachments:
        sql += _HAS_DOCUMENT
    if account:
        # substring of mailboxes.url, which embeds the account UUID as
        # imap://<UUID>/<path> — so a raw UUID works even when Mail is unreachable.
        sql += " AND mb.url LIKE ?"
        params.append(f"%{account}%")
```

Update the docstring's first line to `"""Build (sql, params) for the header plane. All filters optional, ANDed; every`  — unchanged — and add to it: `` `has_attachments` means a real document (images excluded); `account` matches a UUID substring of the mailbox url.``

- [ ] **Step 4: Add the pass-through in the adapter**

In `macos_apps_mcp/adapters/mail.py`, `MailAdapter.search`, add `has_attachments=None,` and `account=None,` to the keyword-only signature (after `flagged=None,`), and pass them through to `mail_index.build_header_query(...)` alongside the existing filters.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_mail_index.py tests/test_mail_search.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add macos_apps_mcp/adapters/mail_index.py macos_apps_mcp/adapters/mail.py tests/
git commit -m "feat(mail): #75 has_attachments means a document, not a signature logo"
```

---

### Task 4: Account UUID → display-name map

**Files:**
- Modify: `macos_apps_mcp/adapters/mail.py`
- Test: `tests/test_mail.py`

**Interfaces:**
- Consumes: `run_osascript` (already imported in `mail.py`), `US`/`RS` separators from `..text`.
- Produces: `mail._account_map() -> dict[str, str]` mapping account UUID → display name, cached in module-global `_ACCOUNT_MAP_CACHE`. Returns `{}` when Mail is unreachable. `mail._resolve_account(value: str) -> str` returns a UUID for a display name, or `value` unchanged if it is already a UUID / unknown.

- [ ] **Step 1: Write the failing tests**

In `tests/test_mail.py`, append:

```python
def test_account_map_parses_osascript_pairs(monkeypatch):
    import macos_apps_mcp.adapters.mail as m

    m._ACCOUNT_MAP_CACHE = None
    monkeypatch.setattr(m, "run_osascript", lambda *a: "UUID-1\x1fPersonal\x1eUUID-2\x1fGoogle")
    assert m._account_map() == {"UUID-1": "Personal", "UUID-2": "Google"}


def test_account_map_empty_when_mail_unreachable(monkeypatch):
    import macos_apps_mcp.adapters.mail as m
    from macos_apps_mcp.errors import NativeError

    m._ACCOUNT_MAP_CACHE = None

    def boom(*a):
        raise NativeError("Automation denied")

    monkeypatch.setattr(m, "run_osascript", boom)
    # a cosmetic label must never fail the call that wanted counts
    assert m._account_map() == {}


def test_resolve_account_maps_name_and_passes_uuid_through(monkeypatch):
    import macos_apps_mcp.adapters.mail as m

    m._ACCOUNT_MAP_CACHE = None
    monkeypatch.setattr(m, "run_osascript", lambda *a: "UUID-1\x1fPersonal")
    assert m._resolve_account("Personal") == "UUID-1"
    assert m._resolve_account("UUID-1") == "UUID-1"
    assert m._resolve_account("Nonexistent") == "Nonexistent"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mail.py -k account_map -v`
Expected: FAIL — `AttributeError: module … has no attribute '_ACCOUNT_MAP_CACHE'`

- [ ] **Step 3: Write the implementation**

In `macos_apps_mcp/adapters/mail.py`, after the `_SYSTEM_MAILBOXES` block, add:

```python
# Account UUID -> display name. The UUID is what mailboxes.url embeds; the name is what a
# human reads. Device-verified: AppleScript `id of account` returns exactly the UUID in
# mailboxes.url. There is NO at-rest source — MailData has no accounts plist, and
# ~/Library/Accounts/Accounts4.sqlite omits some accounts' description entirely (iCloud
# is blank on this Mac), so it would cost an FDA grant, a fingerprint and a fallback for
# a cosmetic label. Cached per process: accounts change about never.
_ACCOUNT_MAP_CACHE: dict[str, str] | None = None

_ACCOUNTS = (
    STRIP_FRAMING
    + """

on run argv
  set us to character id 31
  set rs to character id 30
  set out to ""
  tell application "Mail"
    repeat with acct in every account
      set out to out & (id of acct) & us & (name of acct) & rs
    end repeat
  end tell
  return out
end run
"""
)


def _account_map() -> dict[str, str]:
    """UUID -> account display name, cached. ``{}`` when Mail is unreachable — this is a
    label lookup, and it must never fail a call whose real payload came from sqlite."""
    global _ACCOUNT_MAP_CACHE
    if _ACCOUNT_MAP_CACHE is None:
        try:
            raw = run_osascript(_ACCOUNTS)
        except Exception:
            # Automation denied, Mail not installed, osascript timeout — all mean "no
            # names available", never "the call failed".
            return {}
        out = {}
        for rec in raw.split(RS):
            if US in rec:
                uuid, name = rec.split(US, 1)
                if uuid.strip():
                    out[uuid.strip()] = name.strip()
        _ACCOUNT_MAP_CACHE = out
    return _ACCOUNT_MAP_CACHE


def _resolve_account(value: str) -> str:
    """A display name -> its UUID; anything else (a UUID, an unknown name) unchanged, so
    account= still works when Mail is unreachable."""
    for uuid, name in _account_map().items():
        if name.casefold() == value.casefold():
            return uuid
    return value
```

Note the bare `except Exception` is deliberate and is the one place it is correct here: every failure mode means the same thing (no names), and the counts the caller wanted never needed Mail.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_mail.py -k account -v`
Expected: PASS

- [ ] **Step 5: Wire `_resolve_account` into `search`**

In `MailAdapter.search`, resolve before building the query:

```python
        account = _resolve_account(account) if account else None
```

Place it immediately after the `limit = min(limit, MAX_MAILS)` line.

- [ ] **Step 6: Run tests and commit**

Run: `uv run pytest tests/test_mail.py tests/test_mail_search.py -v`
Expected: PASS

```bash
git add macos_apps_mcp/adapters/mail.py tests/test_mail.py
git commit -m "feat(mail): resolve account names to UUIDs, degrading to UUID when Mail is unreachable"
```

---

### Task 5: `mail_thread` — conversation fetch (#77)

**Files:**
- Modify: `macos_apps_mcp/adapters/mail_index.py` (add `build_thread_query`)
- Modify: `macos_apps_mcp/adapters/mail.py` (add `MAX_THREAD`, `MailAdapter.thread`)
- Test: `tests/test_mail_index.py`, `tests/test_mail_search.py`

**Interfaces:**
- Consumes: `_MAILBOX_RANK`, `_DEDUP_SELECT_COLS` (Task 2); `HEADER_FINGERPRINT` with `conversation_id` (Task 1).
- Produces: `mail_index.build_thread_query(message_id: str, limit: int) -> tuple[str, list]`; `mail.MAX_THREAD = 100`; `MailAdapter.thread(message_id: str, limit: int = MAX_THREAD) -> list[Pointer]`, oldest-first.

- [ ] **Step 1: Write the failing tests**

In `tests/test_mail_index.py`, append:

```python
def test_thread_query_binds_message_id_and_limit():
    sql, params = mail_index.build_thread_query("<abc@ex.com>", limit=50)
    assert "<abc@ex.com>" not in sql
    assert params == ["<abc@ex.com>", 50]
    low = sql.lower()
    assert "conversation_id" in low
    assert "row_number() over" in low  # same dedup rule as search
```

In `tests/test_mail_search.py`, append:

```python
def test_thread_returns_whole_conversation_oldest_first(tmp_path, monkeypatch):
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    out = MailAdapter().thread("<abc@ex.com>")
    # conversation 7 holds <abc@ex.com> (INBOX + Archive) and its reply
    assert [p.id for p in out] == ["<abc@ex.com>", "<reply@ex.com>"]
    assert out[0].folder == "imap://AAAA/INBOX"  # deduped to the INBOX copy


def test_thread_finds_conversation_from_any_member(tmp_path, monkeypatch):
    # asking with the REPLY's id must return the same thread, not just the reply
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    assert len(MailAdapter().thread("<reply@ex.com>")) == 2


def test_thread_truncation_keeps_the_newest(tmp_path, monkeypatch):
    # when the point of reading a thread is to reply, the OLD end is the end to drop
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    out = MailAdapter().thread("<abc@ex.com>", limit=1)
    assert [p.id for p in out] == ["<reply@ex.com>"]


def test_thread_unknown_id_returns_empty(tmp_path, monkeypatch):
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    assert MailAdapter().thread("<nope@ex.com>") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mail_index.py tests/test_mail_search.py -k thread -v`
Expected: FAIL — `AttributeError: module … has no attribute 'build_thread_query'`

- [ ] **Step 3: Write the query builder**

In `macos_apps_mcp/adapters/mail_index.py`, after `build_header_query`, add:

```python
def build_thread_query(message_id: str, limit: int):
    """Build (sql, params) for one conversation, addressed by any member's Message-ID.

    Threads on messages.conversation_id — Mail's own threading key, which carries five
    dedicated indexes, so matching References/In-Reply-To by hand would be redundant work
    on top of an answer Mail already computed. Deduped by the same rule as search, and
    ordered OLDEST-first: a thread reads as a transcript. Truncation keeps the NEWEST
    ``limit`` messages (the old end is the end to drop when the point is to reply), then
    re-sorts ascending for the caller.
    """
    sql = f"""
SELECT message_id_header, subject, mailbox_url, date_received FROM (
  SELECT message_id_header, subject, mailbox_url, date_received, sort_date FROM (
    SELECT {_DEDUP_SELECT_COLS},
           COALESCE(m.date_sent, m.date_received) AS sort_date,
           ROW_NUMBER() OVER (PARTITION BY gd.message_id_header
                              ORDER BY {_MAILBOX_RANK},
                                       m.date_received DESC, m.ROWID) AS rn
    FROM messages m
    JOIN subjects s ON s.ROWID = m.subject
    JOIN mailboxes mb ON mb.ROWID = m.mailbox
    JOIN message_global_data gd ON gd.ROWID = m.global_message_id
    WHERE m.deleted = 0
      AND gd.message_id_header IS NOT NULL AND gd.message_id_header <> ''
      AND m.conversation_id = (
            SELECT m2.conversation_id FROM messages m2
            JOIN message_global_data gd2 ON gd2.ROWID = m2.global_message_id
            WHERE gd2.message_id_header = ? LIMIT 1)
  ) WHERE rn = 1
  ORDER BY sort_date DESC
  LIMIT ?
) ORDER BY sort_date ASC
"""
    return sql, [message_id, limit]
```

- [ ] **Step 4: Write the adapter method**

In `macos_apps_mcp/adapters/mail.py`, add next to `MAX_MAILS`:

```python
MAX_THREAD = 100  # largest thread seen on a real Mac is 154 rows (~144 distinct)
```

And add to `MailAdapter`, after `search`:

```python
    def thread(self, message_id: str, limit: int = MAX_THREAD) -> list[Pointer]:
        """Every message in the conversation containing ``message_id``, deduped and
        oldest-first — including the ones YOU sent, which is what makes it a transcript.
        Bodies stay behind ``mail_body``: a thread is Pointers, so quoted-text
        duplication never arises. Unknown id -> [] (a no-match read, not an error).

        No AppleScript fallback: AppleScript cannot express "fetch this conversation", so
        on schema drift this raises the typed error rather than inventing a degraded
        answer built from a subject-substring match.
        """
        from ..runtime import read_via_sqlite
        from . import mail_index

        limit = min(limit, MAX_THREAD)
        path = mail_index.envelope_index_path()
        if path is None:
            raise NativeError(
                "no Mail data found (~/Library/Mail/V*/MailData/Envelope Index). "
                "Open Mail once to create it. Do not retry."
            )
        sql, params = mail_index.build_thread_query(message_id, limit)

        def read(conn):
            conn.row_factory = sqlite3.Row
            out = []
            for row in conn.execute(sql, params):
                p = mail_index.row_to_pointer(row)
                if p is not None:
                    out.append(p)
            return out

        return read_via_sqlite(
            path, mail_index.HEADER_FINGERPRINT, read, immutable=False
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_mail_index.py tests/test_mail_search.py -k thread -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add macos_apps_mcp/adapters/mail_index.py macos_apps_mcp/adapters/mail.py tests/
git commit -m "feat(mail): #77 thread view on conversation_id — no References parsing needed"
```

---

### Task 6: `mail_overview` — per-mailbox unread counts (#76)

**Files:**
- Modify: `macos_apps_mcp/adapters/mail_index.py` (add `build_overview_query`)
- Modify: `macos_apps_mcp/adapters/mail.py` (add `MailAdapter.overview`)
- Test: `tests/test_mail_index.py`, `tests/test_mail_search.py`

**Interfaces:**
- Consumes: `_account_map` (Task 4).
- Produces: `mail_index.build_overview_query() -> tuple[str, list]` selecting `account_uuid, mailbox_url, total, unread`; `MailAdapter.overview() -> list[dict]` with keys `account`, `mailbox`, `total`, `unread`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_mail_index.py`, append:

```python
def test_overview_query_counts_live_not_stored():
    # mailboxes.unread_count is trigger-maintained and STALE on a real Mac — the Gmail
    # INBOX row claims 1 unread where a live count returns 0. Never read that column.
    sql, params = mail_index.build_overview_query()
    low = sql.lower()
    assert params == []
    assert "unread_count" not in low
    assert "count(" in low and "m.read = 0" in low
    assert "m.deleted = 0" in low
```

In `tests/test_mail_search.py`, append:

```python
def test_overview_reports_counts_and_decodes_names(tmp_path, monkeypatch):
    import macos_apps_mcp.adapters.mail as m

    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    m._ACCOUNT_MAP_CACHE = {"AAAA": "Personal"}
    rows = MailAdapter().overview()
    by_box = {r["mailbox"]: r for r in rows}
    assert by_box["INBOX"]["account"] == "Personal"
    assert by_box["INBOX"]["total"] == 1 and by_box["INBOX"]["unread"] == 1
    # BBBB has no name in the map -> the UUID stands in, the call still succeeds
    assert by_box["Travel"]["account"] == "BBBB"


def test_overview_survives_mail_being_unreachable(tmp_path, monkeypatch):
    import macos_apps_mcp.adapters.mail as m

    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    m._ACCOUNT_MAP_CACHE = None
    monkeypatch.setattr(m, "run_osascript", lambda *a: (_ for _ in ()).throw(OSError()))
    rows = MailAdapter().overview()
    assert rows  # counts never needed Mail
    assert all(r["account"] for r in rows)  # UUID stands in for the name


def test_overview_sorts_unread_first(tmp_path, monkeypatch):
    import macos_apps_mcp.adapters.mail as m

    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    m._ACCOUNT_MAP_CACHE = {}
    unread = [r["unread"] for r in MailAdapter().overview()]
    assert unread == sorted(unread, reverse=True)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mail_index.py tests/test_mail_search.py -k overview -v`
Expected: FAIL — `AttributeError: module … has no attribute 'build_overview_query'`

- [ ] **Step 3: Write the query builder**

In `macos_apps_mcp/adapters/mail_index.py`, after `build_thread_query`, add:

```python
def build_overview_query():
    """Build (sql, params) for per-mailbox totals and unread counts.

    Counts are computed LIVE rather than read from mailboxes.unread_count: that column is
    trigger-maintained and device-verified stale — on a real Mac the Gmail INBOX row
    reports 1 unread where a live count returns 0, and
    unread_count_adjusted_for_duplicates carries the same wrong value. A live count over
    36k rows measured 16 ms, backed by the partial index on (read = 0 AND deleted = 0).

    Mailboxes with no messages are included via the LEFT JOIN, so a newly-created folder
    shows as 0/0 rather than vanishing.
    """
    sql = """
SELECT mb.url                                               AS mailbox_url,
       COUNT(m.ROWID)                                       AS total,
       COALESCE(SUM(CASE WHEN m.read = 0 THEN 1 ELSE 0 END), 0) AS unread
FROM mailboxes mb
LEFT JOIN messages m ON m.mailbox = mb.ROWID AND m.deleted = 0
GROUP BY mb.ROWID
ORDER BY unread DESC, mailbox_url ASC
"""
    return sql, []
```

The account UUID is **not** split out in SQL. The adapter derives it from `mailbox_url` in
Python, which handles `local://` (the *On My Mac* store) as cleanly as `imap://` without a
second `substr`/`instr` expression to get wrong.

- [ ] **Step 4: Write the adapter method**

In `macos_apps_mcp/adapters/mail.py`, add to `MailAdapter` after `thread`:

```python
    def overview(self) -> list[dict]:
        """Per-mailbox {account, mailbox, total, unread}, unread-first.

        Every mailbox is listed, including Junk/Trash/All Mail — a read tool reports, it
        does not decide what deserves attention, and Spam-with-7-unread is only useful if
        you can see it IS Spam. Not Pointers: a count is not a citable message, so this
        is an enumeration read like safari_tabs / messages_chats.

        Account names come from Mail and are best-effort; when Mail is unreachable the
        UUID stands in and the counts — which never needed Mail — are returned anyway.
        """
        from urllib.parse import unquote

        from ..runtime import read_via_sqlite
        from . import mail_index

        path = mail_index.envelope_index_path()
        if path is None:
            raise NativeError(
                "no Mail data found (~/Library/Mail/V*/MailData/Envelope Index). "
                "Open Mail once to create it. Do not retry."
            )
        sql, params = mail_index.build_overview_query()

        def read(conn):
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute(sql, params)]

        rows = read_via_sqlite(
            path, mail_index.HEADER_FINGERPRINT, read, immutable=False
        )
        names = _account_map()
        out = []
        for r in rows:
            url = r["mailbox_url"]
            # imap://<UUID>/<percent-encoded path> — scheme is imap:// or local://
            uuid, _, box = url.partition("://")[2].partition("/")
            out.append(
                {
                    "account": names.get(uuid, uuid),
                    "mailbox": unquote(box),
                    "total": r["total"],
                    "unread": r["unread"],
                }
            )
        return out
```

Note `account_prefix` from the SQL is unused by this method — the adapter re-derives the UUID from the full url, which handles `local://` too. Drop `account_prefix` from the SELECT if `ruff` or review flags it as dead.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_mail_index.py tests/test_mail_search.py -k overview -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add macos_apps_mcp/adapters/mail_index.py macos_apps_mcp/adapters/mail.py tests/
git commit -m "feat(mail): #76 inbox overview — live counts, because the stored ones are stale"
```

---

### Task 7: Register the tools

**Files:**
- Modify: `macos_apps_mcp/server.py:399-457`
- Test: `tests/test_mail_search.py`, `tests/test_tool_annotations.py` (no edit — it self-enforces)

**Interfaces:**
- Consumes: `MailAdapter.thread`, `.overview`, `.search(has_attachments=…, account=…)`.
- Produces: MCP tools `mail_thread(id, limit)` and `mail_overview()`; `mail_search` gains `has_attachments: bool = False` and `account: str = ""`.

- [ ] **Step 1: Write the failing test**

In `tests/test_mail_search.py`, append:

```python
def test_new_read_tools_are_registered():
    async def go():
        async with Client(srv.mcp) as c:
            return {t.name for t in await c.list_tools()}

    names = asyncio.run(go())
    assert {"mail_thread", "mail_overview"} <= names


def test_mail_search_exposes_new_filters():
    async def go():
        async with Client(srv.mcp) as c:
            return {t.name: t for t in await c.list_tools()}

    props = asyncio.run(go())["mail_search"].inputSchema["properties"]
    assert "has_attachments" in props and "account" in props


def test_mail_search_still_requires_a_filter():
    # has_attachments/account must COUNT as filters, and an all-empty call must still
    # raise rather than dumping the whole mailbox.
    with pytest.raises(ValueError):
        srv.mail_search.fn()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mail_search.py -k "registered or filters or requires" -v`
Expected: FAIL — `mail_thread` not in names.

- [ ] **Step 3: Extend `mail_search`**

In `macos_apps_mcp/server.py`, add to the `mail_search` signature after `body: str = ""`:

```python
    has_attachments: bool = False,
    account: str = "",
```

Extend the guard so the new filters count — replace the `text_filters` line and the `if` block:

```python
    text_filters = [subject, from_, to, mailbox, body, account]
    if (
        not any(text_filters)
        and since is None
        and until is None
        and not unread
        and not flagged
        and not has_attachments
    ):
        raise ValueError("mail_search needs at least one filter")
```

Pass them through in the `_mail.search(...)` call:

```python
            has_attachments=has_attachments,
            account=account or None,
```

Append to the docstring, before the closing `Read-only;` sentence:

```
    `has_attachments` means a real DOCUMENT — inline signature/newsletter images are
    excluded, so it will not match a mail whose only attachment is a logo. `account`
    takes a display name ("Personal") or a raw account UUID.
```

- [ ] **Step 4: Add the two tools**

In `macos_apps_mcp/server.py`, after `mail_search` and before `mail_index_bodies`:

```python
@_read_tool
def mail_thread(id: str, limit: int = 100) -> list[dict[str, str]]:
    """Every message in the conversation containing `id`, oldest-first — the transcript,
    including messages YOU sent. Deduped: a message filed in several mailboxes appears
    once. Returns citable Pointers; use mail_body(id) for any message's text. Over
    `limit` messages the OLDEST are dropped, since a thread is usually read to reply to
    it. Unknown id returns []. Fast, read-only, no Mail launch. Needs Full Disk Access."""
    return [p.as_dict() for p in _mail.thread(id, limit)]


@_read_tool
def mail_overview() -> list[dict]:
    """Every mailbox with its message total and unread count, unread-first — the triage
    entry point ("what's unread where?"). Includes Junk/Trash/All Mail so you can see
    what they are rather than having them silently filtered. Counts are computed live,
    not read from Mail's own stored counters, which go stale. Account names need Mail
    reachable; without it the account UUID stands in and the counts are still correct.
    Fast, read-only, no Mail launch. Needs Full Disk Access."""
    return _mail.overview()
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_mail_search.py tests/test_tool_annotations.py tests/test_doctor.py -v`
Expected: PASS. `test_tool_annotations.py` must pass unchanged — if it fails, the new tools were classified wrong, not the test.

- [ ] **Step 6: Run everything, both gated and ungated**

```sh
uv run pytest
MACOS_APPS_ALLOW_SEND=mail uv run pytest
uv run ruff check .
uv run ruff format --check .
grep -c "^def test_" tests/test_mail.py   # must be >= 88
```
Expected: all pass; the count is at least 88.

- [ ] **Step 7: Commit**

```bash
git add macos_apps_mcp/server.py tests/test_mail_search.py
git commit -m "feat(mail): register mail_thread + mail_overview, widen mail_search filters"
```

---

### Task 8: On-device integration tests

Unit tests run against a fixture. These run against the real Envelope Index, which is where a wrong join or a bad LIKE pattern actually shows up.

**Files:**
- Create: `tests/integration/test_mail_reads_integration.py`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing further.

- [ ] **Step 1: Write the integration tests**

Create `tests/integration/test_mail_reads_integration.py`:

```python
"""On-device reads against the REAL Envelope Index (-m integration, never CI).

These assert shape and invariants, never specific message content — the mailbox they run
against belongs to whoever is at the keyboard.
"""

import pytest

from macos_apps_mcp.adapters.mail import MailAdapter

pytestmark = pytest.mark.integration


def test_overview_lists_mailboxes_with_named_or_uuid_accounts():
    rows = MailAdapter().overview()
    assert rows, "no mailboxes — is Mail set up on this machine?"
    for r in rows:
        assert set(r) == {"account", "mailbox", "total", "unread"}
        assert r["account"] and r["mailbox"]
        assert r["unread"] <= r["total"]
    unread = [r["unread"] for r in rows]
    assert unread == sorted(unread, reverse=True)
    # percent-encoding must be decoded, not passed through
    assert not any("%20" in r["mailbox"] for r in rows)


def test_search_returns_no_duplicate_message_ids():
    # the whole point of the dedup rule
    ids = [p.id for p in MailAdapter().search(subject="a", limit=25)]
    assert len(ids) == len(set(ids))


def test_thread_round_trips_from_a_real_message():
    hits = MailAdapter().search(subject="a", limit=5)
    if not hits:
        pytest.skip("no messages matched to thread from")
    thread = MailAdapter().thread(hits[0].id)
    assert any(p.id == hits[0].id for p in thread), "a thread must contain its own seed"
    assert len({p.id for p in thread}) == len(thread), "thread has duplicates"


def test_has_attachments_excludes_image_only_messages():
    docs = MailAdapter().search(has_attachments=True, limit=25)
    plain = MailAdapter().search(subject="", limit=25)
    assert isinstance(docs, list) and isinstance(plain, list)
    assert len({p.id for p in docs}) == len(docs)


def test_unknown_message_id_threads_to_empty():
    assert MailAdapter().thread("<definitely-not-a-real-id@example.invalid>") == []
```

- [ ] **Step 2: Run them on device**

Run: `uv run pytest -m integration tests/integration/test_mail_reads_integration.py -v`
Expected: PASS. If `test_search_returns_no_duplicate_message_ids` fails, the dedup CTE is wrong — that is the single most important assertion in this file.

- [ ] **Step 3: Confirm they are excluded from the default run**

Run: `uv run pytest tests/integration/test_mail_reads_integration.py`
Expected: 5 deselected/skipped, 0 run.

- [ ] **Step 4: Eyeball the real output**

Run:
```sh
uv run python -c "
from macos_apps_mcp.adapters.mail import MailAdapter
a = MailAdapter()
for r in a.overview()[:8]:
    print(r)
"
```
Expected: readable account names (not UUIDs, since Mail is reachable), decoded mailbox names, plausible counts. **Judge the output, not the exit code** — a green test proves the shape, only reading it proves the answer.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_mail_reads_integration.py
git commit -m "test(mail): on-device integration for the reads slice"
```

---

### Task 9: Docs and close-out

**Files:**
- Modify: `docs/ROADMAP.md`
- Modify: `README.md` (tool table, if one lists tools)

- [ ] **Step 1: Check whether the README lists tools**

Run: `grep -n "mail_search\|mail_body" README.md docs/ROADMAP.md`
If `mail_search` appears in a tool table, add `mail_thread` and `mail_overview` rows in the same format. If it does not appear, skip the README edit — do not invent a table.

- [ ] **Step 2: Run the full verification set one final time**

```sh
uv run pytest
MACOS_APPS_ALLOW_SEND=mail uv run pytest
uv run ruff check .
uv run ruff format --check .
grep -c "^def test_" tests/test_mail.py
```
Expected: all green; test count >= 88. **Report the actual output. Do not suppress or simplify a failure.**

- [ ] **Step 3: Commit**

```bash
git add -A docs README.md
git commit -m "docs(mail): note the reads slice tools"
```

- [ ] **Step 4: Report, do not merge**

Summarise for Andrei: what landed, the integration output you eyeballed, and anything the plan did not anticipate. Merging (PR → develop, rebase-merge, delete branch) and redeploying the daemon are his calls, not steps in this plan.

---

## Notes for the implementer

**Why dedup is in SQL and not Python.** `LIMIT 25` must return 25 *messages*. Dedup after the fact returns 25 rows that collapse to 16, and the caller has no way to know they were shortchanged.

**Why `mail_thread`/`mail_overview` pass no `fallback=`.** `mail_search` degrades to an AppleScript inbox search on schema drift. These two cannot — AppleScript has no way to express "fetch this conversation" or "count unread across all mailboxes" — so they raise the typed error. Passing a fallback that quietly did a subject-substring search would answer a different question while looking like success. This is deliberate; do not "fix" it.

**Do not touch `mail.py`'s send/reply/forward paths.** Nothing in this plan is an outbound change. If a test in `tests/test_mail.py` about sending starts failing, you broke something unrelated — stop and report rather than adjusting the test.

**The thread SQL was executed before this plan was written.** The exact query in Task 5 Step 3
was run against a real 36k-message Envelope Index: 25 rows for a 25-message conversation, 25
distinct Message-IDs (no duplicates), Sent and received interleaved correctly, and `limit=3`
returning the newest three in ascending order. If it fails for you, you changed it.

**`ORDER BY sort_date` in the outer SELECT is legal** even though `sort_date` is not in that
SELECT list — SQLite allows ordering on any column of the subquery in `FROM`. Verified. Do not
"fix" it by adding `sort_date` to the projection; `row_to_pointer` would then see an extra key.

**Percent-encoding.** `mailboxes.url` is percent-encoded (`%5BGmail%5D/All%20Mail`). The rank `LIKE` patterns are written to work *against the encoded form* — `'%All%Mail'` matches `All%20Mail` because `%` is a SQL wildcard. Verified against all 51 mailboxes on a real Mac. Do not "helpfully" decode before matching.
