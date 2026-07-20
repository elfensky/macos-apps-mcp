# Notes create/update returning the stable x-coredata id — design

**Issue:** [#66](https://github.com/elfensky/macos-apps-mcp/issues/66) · **Milestone:** 0.7.0 — Differentiators · **Date:** 2026-07-21

## Why

The Apple-notes MCP ecosystem is read-only here (sirmews' top issue was "please add edit") or
returns nothing usable on create (supermemoryai returns no id). A create/update path that hands
back the **stable `x-coredata://…/ICNote/pN` id** would be unique in the ecosystem — and it is
exactly what the vault id-writeback needs. Builds on the 0.5.0 NoteStore.sqlite read plane.

## Contract

Add to `contracts.py`, mirroring `ReminderData` / `CalendarEventData` (writes are per-adapter typed):

```python
@dataclass
class NoteData:
    title: str
    body: str = ""
    folder: str | None = None  # None → default folder; else an existing folder name
```

## HTML compose (pure, stdlib)

Notes stores a note's content as HTML in the AppleScript `body` property and derives the note's
title from the first line. A module-level pure helper in `notes.py`:

```python
def _compose_html(title: str, body: str) -> str:
    """Plaintext title+body → the note's HTML body. Escapes everything (injection-safe) and
    puts the title on the first line so Notes derives ZTITLE1 from it."""
```

- `html.escape` (stdlib) the title and each body line; join body lines with `<br>`.
- Compose `<div>{escaped_title}</div><div>{escaped_body}</div>` (empty body → `<div></div>`).
- User text containing `<`, `&`, `"`, or markup is inert — it renders as literal text, never as
  HTML and never as script. The escaping round-trips: `note_bodies` plaintext returns `title\nbody`,
  and Notes stores `ZTITLE1` == the unescaped title, so verify compares equal under `norm_text`.

## Injection-safe write transport

Identical to `mail.create_draft` (the established pattern): the composed HTML is written to a
`tempfile.mkstemp` (0600) file and read inside AppleScript as
`(read (POSIX file (item N of argv)) as «class utf8»)` — **never interpolated** into the script, so
a long / multiline / unicode / markup body cannot break or inject it. Folder name and (for update)
the note id arrive via `argv`. The tempfile is deleted in a `finally` after the synchronous
`run_osascript` returns.

## Create — `NotesAdapter.create(data: NoteData) -> Pointer`

1. `_compose_html(data.title, data.body)` → tempfile.
2. `_CREATE_NOTE` AppleScript (`with timeout`, argv-driven):
   - Resolve the target folder. `folder is None` → create in the default folder (`make new note`
     with no `at` clause). A folder name → scan every account's folders for an exact name match;
     **resolve-or-raise**: error if zero match ("no folder named …") or more than one ("folder name
     is ambiguous across accounts …"), mirroring `runtime.resolve_container`'s loud disambiguation.
   - `make new note [at folder] with properties {body: bodyText}` where `bodyText` is the tempfile
     read as `«class utf8»`.
   - `return id of the new note` — this is the canonical `x-coredata://…/ICNote/pN` id (the same id
     `_LIST_ALL` returns and the sqlite path builds; the integration cross-check already asserts one
     id across both backends). No sqlite lookup, no title-collision race.
   - Atomic (#44): wrap post-`make` steps in a `try`; on any error `delete` the partial note and
     re-raise, so a retry cannot strand a duplicate.
3. **Verify-after-write** (see below) by the returned id.
4. Return the note `Pointer` (id = x-coredata, summary = title/snippet, folder label, empty deeplink).

## Update — `NotesAdapter.update(ident: str, data: NoteData) -> Pointer`

1. `_compose_html(...)` → tempfile.
2. `_UPDATE_NOTE` AppleScript: `set n to note id (item 1 of argv)` (unknown id → the AppleScript
   error surfaces as a typed failure), `set body of n to bodyText`, `return id of n`. Full-replace of
   title+body, matching `update_event`. `folder` on update is out of scope for v1 (moving a note
   between folders is a separate op); if `data.folder` is set on update it is ignored — documented
   in the tool docstring, not silently surprising.
3. **Verify-after-write**: the returned id must equal `ident` (Z_PK is stable across a body edit, so
   the id survives — assert it), and the persisted title must match.
4. Return the refreshed `Pointer`.

## Verify-after-write

A true re-read by id (not trusting the in-script value — catches an iCloud rollback or a fabricated
id, exactly like the calendar adapter's `_refetch`):

- `_read_title_by_id(ident) -> str | None`: sqlite plane primary — `pk = _pk_from_id(ident)`, guard
  the full `x-coredata://{store_uuid}/ICNote/p` prefix (reject foreign/stale ids, per the existing
  body-read rule), `SELECT ZTITLE1 … WHERE Z_PK = ?`. AppleScript fallback (`name of note id`) on
  missing FDA / schema drift, via `read_via_sqlite` with a dedicated fingerprint
  (`ZICCLOUDSYNCINGOBJECT: {Z_PK, ZTITLE1}`, `Z_METADATA: {Z_UUID}`).
- `verify_persisted("note", expected, actual)` with `title` (via `norm_text`) and, for update,
  `id`. A mismatch raises `VerificationFailed` naming the dropped/reverted field — the caller must
  not reuse the id.

## Server tools

- `create_note(title, body="", folder=None) -> dict` — `@_additive_tool` (adds a new item; not
  destructive). Dispatches to `_notes.create(NoteData(...))`, returns `_emit(pointer)`.
- `update_note(id, title, body="", folder=None) -> dict` — `@_write_tool` (overwrites existing
  content → destructive annotation). Dispatches to `_notes.update(id, NoteData(...))`.
- Both are skipped under `MACOS_APPS_READ_ONLY` (they're writes) and both get an entry in the
  `test_tool_annotations` permission map (the repo self-enforces classification) — Automation for
  Notes; the verify read-back additionally uses FDA/sqlite with an AppleScript fallback.

## Tests

Unit (no TCC):
- `_compose_html`: plain title+body; multiline body → `<br>` join; injection payloads
  (`<script>`, `&`, `"`, `A & B`) escaped and inert; empty body.
- `_pk_from_id` reuse + the prefix guard in `_read_title_by_id`'s sqlite branch (foreign-id rejected).
- `verify_persisted` note diffing on plain dict fakes (title dropped, id changed on update).
- Server dispatch: `create_note` / `update_note` forward args and return the emitted pointer
  (Protocol fake), and are correctly permission-classified.

Integration (`-m integration`, manual only, never CI — real Notes + TCC):
- Create → the returned id is immediately readable via `note_bodies` (**confirms `id of newNote` is
  the stable pN right away — the one platform assumption**).
- Update by id preserves the id (round-trip) and changes the content.
- Verify-after-write catches nothing on a good write (happy path) and the created note's `ZTITLE1`
  equals the requested title.
- Folder targeting: create into a named folder; unknown/ambiguous folder raises.

## Out of scope (YAGNI)

- Rich text, lists, attachments, images — plaintext body only; a richer compose is a non-breaking
  later addition.
- Moving a note between folders on update (folder ignored on update).
- Pinning / locking on write (read side already surfaces the flags).
