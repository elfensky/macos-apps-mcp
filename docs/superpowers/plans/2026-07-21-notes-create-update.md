# Notes create/update (stable x-coredata id) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `create_note` / `update_note` tools that write a note via AppleScript and return its stable `x-coredata://…/ICNote/pN` id, verified against the store.

**Architecture:** A pure `_compose_html` helper turns plaintext title+body into injection-safe HTML. AppleScript (`_CREATE_NOTE`/`_UPDATE_NOTE`) writes the note — body via a 0600 tempfile read as `«class utf8»`, never interpolated — and returns `id of the note` (already the canonical x-coredata id). A verify read-back by id (sqlite plane primary, AppleScript fallback) + `verify_persisted` catches fabrication/rollback. Thin server tools dispatch to the adapter.

**Tech Stack:** Python 3.12+, FastMCP 2.0, osascript (Automation TCC), NoteStore.sqlite read plane, `html` (stdlib), pytest, uv, ruff.

## Global Constraints

- All native access (osascript + sqlite) goes through `runtime.run_osascript` / `runtime.read_via_sqlite` — never call osascript or open the store directly. osascript runs on the single serialized worker.
- Tools in `server.py` are THIN dispatch to adapters — no business logic in the tool layer.
- Writes are per-adapter typed (`NoteData`), never stringly-typed dicts. Reads/returns are `Pointer`.
- **Injection-safe writes:** user body is written to a `tempfile.mkstemp` (0600) file and read inside AppleScript as `(read (POSIX file (item N of argv)) as «class utf8»)` — NEVER interpolated. Folder name and note id arrive via `argv`. Tempfile deleted in a `finally`.
- **Verify-after-write (#49):** re-read by the returned id and `verify_persisted`; a mismatch raises `VerificationFailed`. Never trust the in-script value.
- The x-coredata id form is `x-coredata://{store_uuid}/ICNote/p{Z_PK}`. A verify read-back MUST guard the full `x-coredata://{uuid}/ICNote/p` prefix before trusting a bare pN (foreign/stale ids collide on pN).
- Writes are skipped under `MACOS_APPS_READ_ONLY` (use `@_additive_tool` / `@_write_tool`). Every registered tool MUST be classified in `tests/test_tool_annotations.py` (`_ADDITIVE_TOOLS`/`_DESTRUCTIVE_TOOLS` + `_PERMISSION`) — the suite self-enforces this. Notes tools use the `"Automation"` permission keyword.
- Style: ruff (line-length 88; E, F, I, UP, B, SIM). No mypy.
- Verify: `uv run pytest && uv run ruff check . && uv run ruff format --check .`. Integration tests (`-m integration`) are MANUAL ONLY, never CI.
- Branch: `feat/66-notes-write` (already created).

---

### Task 1: `NoteData` contract + `_compose_html`

**Files:**
- Modify: `macos_apps_mcp/contracts.py` (add `NoteData` dataclass near `ContactData`)
- Modify: `macos_apps_mcp/adapters/notes.py` (add `import html` + `_compose_html`)
- Test: `tests/test_notes.py` (extend)

**Interfaces:**
- Produces: `contracts.NoteData(title: str, body: str = "", folder: str | None = None)` (frozen, slots).
- Produces: `notes._compose_html(title: str, body: str) -> str` — injection-safe HTML for the note `body` property; title on the first line.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_notes.py`:

```python
from macos_apps_mcp.adapters.notes import _compose_html


def test_compose_html_title_and_body():
    assert _compose_html("Shopping", "Milk") == "<div>Shopping</div><div>Milk</div>"


def test_compose_html_multiline_body_uses_br():
    assert _compose_html("T", "a\nb\nc") == "<div>T</div><div>a<br>b<br>c</div>"


def test_compose_html_escapes_markup_injection():
    # user text with markup must render as literal text, never as HTML/script
    out = _compose_html("A & B", "<script>alert(1)</script>")
    assert "&amp;" in out
    assert "&lt;script&gt;" in out
    assert "<script>" not in out


def test_compose_html_empty_body():
    assert _compose_html("Just a title", "") == "<div>Just a title</div><div></div>"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_notes.py -k compose_html -v`
Expected: FAIL with `cannot import name '_compose_html'`.

- [ ] **Step 3: Implement**

In `macos_apps_mcp/contracts.py`, add after `ContactData` (match the frozen/slots dataclass style of `ReminderData`):

```python
@dataclass(frozen=True, slots=True)
class NoteData:
    """Payload for creating/updating an Apple Note (plaintext title + body)."""

    title: str
    body: str = ""
    folder: str | None = None  # None → default folder; else an existing folder name
```

In `macos_apps_mcp/adapters/notes.py`, add `import html` to the stdlib imports and this module-level helper (near the other pure helpers, e.g. after `_parse_bodies`):

```python
def _compose_html(title: str, body: str) -> str:
    """Plaintext title + body → the note's HTML `body`. Everything is `html.escape`d so
    user markup renders as literal text (never HTML/script); the title is the first line,
    which is how Notes derives ZTITLE1. Body newlines become <br>."""
    title_html = html.escape(title)
    body_html = "<br>".join(html.escape(line) for line in body.split("\n"))
    return f"<div>{title_html}</div><div>{body_html}</div>"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_notes.py -k compose_html -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Full verify + commit**

Run: `uv run pytest && uv run ruff check . && uv run ruff format --check .`
Expected: all pass.

```bash
git add macos_apps_mcp/contracts.py macos_apps_mcp/adapters/notes.py tests/test_notes.py
git commit -m "feat(notes): NoteData contract + _compose_html (#66)"
```

---

### Task 2: verify read-back — `_read_title_by_id` + `_verify_note`

**Files:**
- Modify: `macos_apps_mcp/adapters/notes.py` (add fingerprint, SQL, `_read_title_by_id` method, `_verify_note` helper; import `norm_text`, `verify_persisted`, `VerificationFailed` from `..runtime`)
- Test: `tests/test_notes.py` (extend)

**Interfaces:**
- Consumes: `_pk_from_id`, `_store_uuid`, `read_via_sqlite`, `NOTESTORE` (existing in notes.py).
- Produces:
  - `NotesAdapter._read_title_by_id(self, ident: str) -> str | None` — the note's `ZTITLE1` by x-coredata id; `None` if the id isn't this store's or the note isn't found. sqlite primary, AppleScript `name of note id` fallback on missing FDA / drift.
  - `notes._verify_note(persisted_title: str | None, ident: str, data: NoteData, *, expected_id: str | None = None) -> None` — raises `VerificationFailed` if the note didn't persist (title None), the title didn't persist, or (update) the id changed.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_notes.py` (add `import sqlite3` and the runtime imports at the top if absent):

```python
import sqlite3

import pytest

from macos_apps_mcp.adapters.notes import NotesAdapter, _verify_note
from macos_apps_mcp.contracts import NoteData
from macos_apps_mcp.runtime import VerificationFailed


def test_verify_note_passes_on_match():
    _verify_note("Hello", "x-coredata://S/ICNote/p1", NoteData(title="Hello"))


def test_verify_note_none_means_not_persisted():
    with pytest.raises(VerificationFailed, match="did not persist"):
        _verify_note(None, "x-coredata://S/ICNote/p1", NoteData(title="Hello"))


def test_verify_note_title_mismatch():
    with pytest.raises(VerificationFailed, match="title"):
        _verify_note("Wrong", "x-coredata://S/ICNote/p1", NoteData(title="Hello"))


def test_verify_note_update_id_must_survive():
    # expected_id != the id we re-read → the write re-homed/replaced the note
    with pytest.raises(VerificationFailed, match="id"):
        _verify_note(
            "Hello",
            "x-coredata://S/ICNote/p2",
            NoteData(title="Hello"),
            expected_id="x-coredata://S/ICNote/p1",
        )


def _make_notestore(path, uuid="STORE-UUID", rows=((1, "Hello"),)):
    """Synthetic NoteStore with just the columns _read_title_by_id reads."""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE ZICCLOUDSYNCINGOBJECT (Z_PK INTEGER PRIMARY KEY, ZTITLE1 TEXT)"
    )
    conn.execute("CREATE TABLE Z_METADATA (Z_UUID TEXT)")
    conn.execute("INSERT INTO Z_METADATA (Z_UUID) VALUES (?)", (uuid,))
    conn.executemany(
        "INSERT INTO ZICCLOUDSYNCINGOBJECT (Z_PK, ZTITLE1) VALUES (?, ?)", rows
    )
    conn.commit()
    conn.close()
    return path


def test_read_title_by_id_sqlite(tmp_path, monkeypatch):
    import macos_apps_mcp.adapters.notes as notes_mod

    db = _make_notestore(tmp_path / "NoteStore.sqlite")
    monkeypatch.setattr(notes_mod, "NOTESTORE", db)
    got = NotesAdapter()._read_title_by_id("x-coredata://STORE-UUID/ICNote/p1")
    assert got == "Hello"


def test_read_title_by_id_foreign_store_returns_none(tmp_path, monkeypatch):
    import macos_apps_mcp.adapters.notes as notes_mod

    db = _make_notestore(tmp_path / "NoteStore.sqlite", uuid="STORE-UUID")
    monkeypatch.setattr(notes_mod, "NOTESTORE", db)
    # a pN from a DIFFERENT store must not resolve to a local note's title
    got = NotesAdapter()._read_title_by_id("x-coredata://OTHER-UUID/ICNote/p1")
    assert got is None


def test_read_title_by_id_unknown_pk_returns_none(tmp_path, monkeypatch):
    import macos_apps_mcp.adapters.notes as notes_mod

    db = _make_notestore(tmp_path / "NoteStore.sqlite")
    monkeypatch.setattr(notes_mod, "NOTESTORE", db)
    got = NotesAdapter()._read_title_by_id("x-coredata://STORE-UUID/ICNote/p999")
    assert got is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_notes.py -k "verify_note or read_title" -v`
Expected: FAIL with `cannot import name '_verify_note'`.

- [ ] **Step 3: Implement**

In `macos_apps_mcp/adapters/notes.py`, extend the runtime import block with `norm_text`, `verify_persisted`, `VerificationFailed`. Add near the sqlite-read-plane section:

```python
# verify read-back: the note's title by id. Its OWN small fingerprint — a drift here
# degrades only the verify read (falls back to AppleScript), like the body read.
_TITLE_FINGERPRINT = {
    "ZICCLOUDSYNCINGOBJECT": {"Z_PK", "ZTITLE1"},
    "Z_METADATA": {"Z_UUID"},
}
_TITLE_SQL = "SELECT ZTITLE1 FROM ZICCLOUDSYNCINGOBJECT WHERE Z_PK = ?"


def _verify_note(
    persisted_title: str | None,
    ident: str,
    data: NoteData,
    *,
    expected_id: str | None = None,
) -> None:
    """Verify-after-write (#49): the note must be re-readable by the returned id with the
    requested title; on update the id must survive the edit. Raises VerificationFailed
    naming the mismatch — the caller must not reuse the id."""
    if persisted_title is None:
        raise VerificationFailed(
            f"note {ident!r} could not be re-read after the write — it did not persist "
            "(a fabricated id or an iCloud rollback). Do not trust the id."
        )
    expected: dict[str, object] = {"title": norm_text(data.title)}
    actual: dict[str, object] = {"title": norm_text(persisted_title)}
    if expected_id is not None:  # update: Z_PK is stable, so the id must be unchanged
        expected["id"] = expected_id
        actual["id"] = ident
    verify_persisted("note", expected, actual)
```

Add the method to `NotesAdapter` (near `get_bodies`):

```python
    def _read_title_by_id(self, ident: str) -> str | None:
        """The note's ZTITLE1 by x-coredata id (sqlite primary, AppleScript fallback);
        None if the id isn't this store's or the note isn't found."""

        def sqlite(conn) -> str | None:
            prefix = f"x-coredata://{_store_uuid(conn)}/ICNote/p"
            if not ident.startswith(prefix):
                return None  # foreign/stale id — a colliding pN must not resolve
            pk = _pk_from_id(ident)
            if pk is None:
                return None
            row = conn.execute(_TITLE_SQL, (pk,)).fetchone()
            return row[0] if row else None

        return read_via_sqlite(
            NOTESTORE,
            _TITLE_FINGERPRINT,
            sqlite,
            fallback=lambda: self._applescript_title(ident),
            immutable=False,
        )

    def _applescript_title(self, ident: str) -> str | None:
        """Fallback title read (no FDA): `name of note id`. Unknown id → the osascript
        error surfaces as a typed NativeError."""
        return run_osascript(_TITLE_BY_ID, ident) or None
```

Add the AppleScript template near the other templates:

```python
# verify-fallback title read (no FDA path): name of a note by id.
_TITLE_BY_ID = """on run argv
  with timeout of 120 seconds
  tell application "Notes"
    return name of note id (item 1 of argv)
  end tell
  end timeout
end run"""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_notes.py -k "verify_note or read_title" -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Full verify + commit**

Run: `uv run pytest && uv run ruff check . && uv run ruff format --check .`

```bash
git add macos_apps_mcp/adapters/notes.py tests/test_notes.py
git commit -m "feat(notes): verify read-back (_read_title_by_id + _verify_note) (#66)"
```

---

### Task 3: create — AppleScript + adapter method + server tool

**Files:**
- Modify: `macos_apps_mcp/adapters/notes.py` (add `_CREATE_NOTE`, `NotesAdapter.create`; import `os`, `tempfile`, `contextlib` is already imported; import `NoteData` from `..contracts`; import `clean_summary` is already imported)
- Modify: `macos_apps_mcp/server.py` (add `create_note` tool; `NoteData` import)
- Modify: `tests/test_server.py` (extend `_FakeSource` + dispatch test)
- Modify: `tests/test_tool_annotations.py` (classify `create_note`)
- Modify: `tests/test_integration.py` (manual on-device test)

**Interfaces:**
- Consumes: `_compose_html` (T1), `_verify_note` / `_read_title_by_id` (T2), `NoteData` (T1).
- Produces: `NotesAdapter.create(self, data: NoteData) -> Pointer`; server tool `create_note(title, body="", folder=None) -> dict`.

- [ ] **Step 1: Write the failing dispatch test**

In `tests/test_server.py`, extend the notes fake used for notes tools. Add a `create_note` method to the fake source class the notes tests use (the `_FakeSource` near line 28), and add the test near the other notes dispatch tests:

```python
    def create(self, data):
        self.queries.append(("create", data.title, data.body, data.folder))
        return Pointer(id="x-coredata://S/ICNote/p9", summary=data.title, deeplink="")
```

(Method is named `create` — the `create_note` *tool* dispatches to `_notes.create`, not `_notes.create_note`.)

```python
def test_create_note_tool_dispatches(monkeypatch):
    fake = _FakeSource()
    monkeypatch.setattr(srv, "_notes", fake)
    out = srv.create_note("Title", "Body", "Ideas")
    assert fake.queries == [("create", "Title", "Body", "Ideas")]
    assert out == {"id": "x-coredata://S/ICNote/p9", "summary": "Title", "deeplink": ""}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_server.py::test_create_note_tool_dispatches -v`
Expected: FAIL with `AttributeError: ... has no attribute 'create_note'`.

- [ ] **Step 3: Implement the adapter method + AppleScript**

In `macos_apps_mcp/adapters/notes.py`, add `import os` and `import tempfile` to the stdlib imports, and `NoteData` to the `..contracts` import. Add the template:

```python
# create_note: make a note (body from the tempfile as «class utf8» — never interpolated,
# so markup/newlines/unicode can't inject). folder "" → the default folder; else locate a
# folder by name across accounts, erroring on 0 (not found) or >1 (ambiguous). Returns the
# new note's x-coredata id — the canonical id (same one _LIST_ALL returns). No post-make
# mutation, so nothing to roll back.
_CREATE_NOTE = """on run argv
  set folderName to item 1 of argv
  set bodyText to (read (POSIX file (item 2 of argv)) as «class utf8»)
  with timeout of 120 seconds
  tell application "Notes"
    if folderName is "" then
      set newNote to make new note with properties {body:bodyText}
    else
      set matches to {}
      repeat with acc in accounts
        repeat with f in folders of acc
          if name of f is folderName then set end of matches to f
        end repeat
      end repeat
      if (count of matches) is 0 then error "no folder named " & folderName
      if (count of matches) > 1 then ¬
        error "folder name is ambiguous across accounts: " & folderName
      set newNote to make new note at (item 1 of matches) with properties {body:bodyText}
    end if
    return id of newNote
  end tell
  end timeout
end run"""
```

Add the method to `NotesAdapter`:

```python
    def create(self, data: NoteData) -> Pointer:
        """Create a note from plaintext title+body; return its stable x-coredata id.

        Body is written to a 0600 tempfile and read by AppleScript as «class utf8» (never
        interpolated). folder=None → the default folder; a name is resolved across
        accounts (unknown/ambiguous → a loud error). The returned id is verified by a
        re-read (#49) before it's trusted.
        """
        html_body = _compose_html(data.title, data.body)
        fd, path = tempfile.mkstemp(prefix="macos-apps-mcp-note-", suffix=".html")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(html_body)
            ident = run_osascript(_CREATE_NOTE, data.folder or "", path).strip()
        finally:
            with contextlib.suppress(OSError):
                os.unlink(path)
        _verify_note(self._read_title_by_id(ident), ident, data)
        return Pointer(
            id=ident,
            summary=clean_summary(data.title) or "(untitled note)",
            deeplink="",
            folder=data.folder,
        )
```

- [ ] **Step 4: Add the server tool**

In `macos_apps_mcp/server.py`, add `NoteData` to the `.contracts` import, and add the tool near the other notes write tools (e.g. after `delete_note`):

```python
@_additive_tool
def create_note(title: str, body: str = "", folder: str | None = None) -> dict:
    """Create a note and return its STABLE x-coredata id (unique in the ecosystem —
    immediately usable with note_bodies). `title`/`body` are plaintext (escaped, so
    markup is inert); `folder` an existing folder name (across accounts) or omit for the
    default folder — an unknown/ambiguous name is refused. Verified after write (#49).
    Side effect (creates); needs Automation access for Notes (verify read-back also uses
    Full Disk Access, falling back to Automation)."""
    return _emit(_notes.create(NoteData(title=title, body=body, folder=folder)))
```

- [ ] **Step 5: Classify the tool (annotation self-enforcement)**

In `tests/test_tool_annotations.py`: add `"create_note"` to `_ADDITIVE_TOOLS`, and `"create_note": "Automation"` to the `_PERMISSION` map.

- [ ] **Step 6: Run the dispatch + annotation tests**

Run: `uv run pytest tests/test_server.py::test_create_note_tool_dispatches tests/test_tool_annotations.py -v`
Expected: PASS.

- [ ] **Step 7: Add the integration test (manual, on-device)**

In `tests/test_integration.py`, add (match the file's `@pytest.mark.integration` style and `run_native(request_access)` setup used by neighboring notes tests):

```python
@pytest.mark.integration
def test_create_note_returns_usable_id():
    from macos_apps_mcp.adapters.notes import NotesAdapter
    from macos_apps_mcp.contracts import NoteData

    adapter = NotesAdapter()
    p = adapter.create(NoteData(title="mac-mcp itest note", body="line one\nline two"))
    assert p.id.startswith("x-coredata://") and "/ICNote/p" in p.id
    # the one platform assumption: id of the new note is the stable pN immediately
    bodies = adapter.get_bodies([p.id])
    assert bodies and bodies[0]["id"] == p.id
    assert "line one" in bodies[0]["body"]
    # cleanup
    adapter.delete(p.id)
```

(Do NOT run `-m integration` in CI. Note it for the human to run manually — it is the real correctness gate for the AppleScript + id-immediacy assumption.)

- [ ] **Step 8: Full verify + commit**

Run: `uv run pytest && uv run ruff check . && uv run ruff format --check .`
Expected: all pass; integration test deselected by default.
Also confirm collectible: `uv run pytest -m integration --collect-only tests/test_integration.py 2>&1 | grep create_note_returns_usable_id`

```bash
git add macos_apps_mcp/adapters/notes.py macos_apps_mcp/server.py tests/test_server.py tests/test_tool_annotations.py tests/test_integration.py
git commit -m "feat(notes): create_note returning stable x-coredata id (#66)"
```

---

### Task 4: update — AppleScript + adapter method + server tool

**Files:**
- Modify: `macos_apps_mcp/adapters/notes.py` (add `_UPDATE_NOTE`, `NotesAdapter.update`)
- Modify: `macos_apps_mcp/server.py` (add `update_note` tool)
- Modify: `tests/test_server.py` (extend `_FakeSource` + dispatch test)
- Modify: `tests/test_tool_annotations.py` (classify `update_note`)
- Modify: `tests/test_integration.py` (manual on-device test)

**Interfaces:**
- Consumes: `_compose_html`, `_verify_note`, `_read_title_by_id`, `NoteData`.
- Produces: `NotesAdapter.update(self, ident: str, data: NoteData) -> Pointer`; server tool `update_note(id, title, body="", folder=None) -> dict`.

- [ ] **Step 1: Write the failing dispatch test**

In `tests/test_server.py`, add to the fake source class:

```python
    def update(self, ident, data):
        self.queries.append(("update", ident, data.title, data.body))
        return Pointer(id=ident, summary=data.title, deeplink="")
```

```python
def test_update_note_tool_dispatches(monkeypatch):
    fake = _FakeSource()
    monkeypatch.setattr(srv, "_notes", fake)
    out = srv.update_note("x-coredata://S/ICNote/p1", "New", "Body")
    assert fake.queries == [("update", "x-coredata://S/ICNote/p1", "New", "Body")]
    assert out == {"id": "x-coredata://S/ICNote/p1", "summary": "New", "deeplink": ""}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_server.py::test_update_note_tool_dispatches -v`
Expected: FAIL with `AttributeError: ... has no attribute 'update_note'`.

- [ ] **Step 3: Implement the adapter method + AppleScript**

In `macos_apps_mcp/adapters/notes.py`, add the template:

```python
# update_note: full-replace a note's content by id (body from the tempfile as «class
# utf8»). `note id` errors on an unknown id (surfaces as a typed NativeError). Returns the
# id (Z_PK is stable across a body edit, so it's unchanged — verify asserts it).
_UPDATE_NOTE = """on run argv
  set noteId to item 1 of argv
  set bodyText to (read (POSIX file (item 2 of argv)) as «class utf8»)
  with timeout of 120 seconds
  tell application "Notes"
    set n to note id noteId
    set body of n to bodyText
    return id of n
  end tell
  end timeout
end run"""
```

Add the method to `NotesAdapter`:

```python
    def update(self, ident: str, data: NoteData) -> Pointer:
        """Full-replace a note's title+body by id; the id must survive (verified, #49).

        `data.folder` is IGNORED on update — moving a note between folders is a separate
        op. Body transport and verify match `create`.
        """
        if not ident.strip():
            raise ValueError("update_note needs a note id")
        html_body = _compose_html(data.title, data.body)
        fd, path = tempfile.mkstemp(prefix="macos-apps-mcp-note-", suffix=".html")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(html_body)
            ident_after = run_osascript(_UPDATE_NOTE, ident, path).strip()
        finally:
            with contextlib.suppress(OSError):
                os.unlink(path)
        _verify_note(
            self._read_title_by_id(ident_after),
            ident_after,
            data,
            expected_id=ident,
        )
        return Pointer(
            id=ident_after,
            summary=clean_summary(data.title) or "(untitled note)",
            deeplink="",
        )
```

- [ ] **Step 4: Add the server tool**

In `macos_apps_mcp/server.py`, add near `create_note`:

```python
@_write_tool
def update_note(id: str, title: str, body: str = "", folder: str | None = None) -> dict:
    """Update a note by id (full-replace title+body); the stable id is preserved and
    verified (#49). `title`/`body` plaintext (escaped). `folder` is ignored on update
    (moving between folders is a separate op). Side effect (full-replace update); needs
    Automation access for Notes. `id` from notes / notes_all / create_note."""
    return _emit(_notes.update(id, NoteData(title=title, body=body, folder=folder)))
```

- [ ] **Step 5: Classify the tool**

In `tests/test_tool_annotations.py`: add `"update_note"` to `_DESTRUCTIVE_TOOLS`, and `"update_note": "Automation"` to `_PERMISSION`.

- [ ] **Step 6: Run the dispatch + annotation tests**

Run: `uv run pytest tests/test_server.py::test_update_note_tool_dispatches tests/test_tool_annotations.py -v`
Expected: PASS.

- [ ] **Step 7: Add the integration test**

In `tests/test_integration.py`:

```python
@pytest.mark.integration
def test_update_note_preserves_id():
    from macos_apps_mcp.adapters.notes import NotesAdapter
    from macos_apps_mcp.contracts import NoteData

    adapter = NotesAdapter()
    created = adapter.create(NoteData(title="mac-mcp itest upd", body="before"))
    updated = adapter.update(created.id, NoteData(title="mac-mcp itest upd", body="after"))
    assert updated.id == created.id  # id survives a body edit
    bodies = adapter.get_bodies([created.id])
    assert "after" in bodies[0]["body"] and "before" not in bodies[0]["body"]
    adapter.delete(created.id)
```

- [ ] **Step 8: Full verify + commit**

Run: `uv run pytest && uv run ruff check . && uv run ruff format --check .`
Confirm collectible: `uv run pytest -m integration --collect-only tests/test_integration.py 2>&1 | grep update_note_preserves_id`

```bash
git add macos_apps_mcp/adapters/notes.py macos_apps_mcp/server.py tests/test_server.py tests/test_tool_annotations.py tests/test_integration.py
git commit -m "feat(notes): update_note (full-replace, id-survival verified) (#66)"
```

---

## Post-plan

- [ ] Open a PR from `feat/66-notes-write` → `develop`, closing #66. Note the one platform assumption verified only by the manual integration tests (`id of newNote` is the stable pN immediately; ZTITLE1 == requested title). Flag that the integration tests should be run on-device before relying on the verify comparison basis.
