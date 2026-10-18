# Phase 4: Notes & Photos - Pattern Map

**Mapped:** 2026-10-18
**Files analyzed:** 18 (new/modified)
**Analogs found:** 16 / 18
All analog paths below are git-tracked source (verified: `git ls-files` on photos.py, mail_files.py, notes.py, runtime.py, tests/test_photos.py, tests/_fakes.py, tests/test_mail_files.py, scripts/build_app.sh).

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match |
|---|---|---|---|---|
| `macos_apps_mcp/files.py` (git mv of `adapters/mail_files.py`) | utility | file-I/O | `adapters/mail_files.py` itself | exact (move) |
| `macos_apps_mcp/runtime.py` + `photos_db()` | native seam | request-response | `runtime.read_via_sqlite` / `run_native` / `body_file` seams | role-match |
| `macos_apps_mcp/adapters/photos.py` (rewrite) | adapter | CRUD read + file-I/O export | `adapters/reminders.py` (`read()` envelope) + `mail.py` `export()` | role-match |
| `macos_apps_mcp/adapters/notes.py` (+ `read()`, FTS5 pass) | adapter | transform | `notes.get_pointers` (same file) + `mail_index._fts_query` | exact |
| `macos_apps_mcp/adapters/mail.py`, `mail_attachments.py` (importer edits) | adapter | file-I/O | self | exact |
| `macos_apps_mcp/server.py` (`photos`, `photo_albums`, `photo_info`, `export_photo`, `notes`) | tool layer | request-response | `export_mail` (server.py:608), `notes` (:1018) | exact |
| `macos_apps_mcp/registry.py` (new records) | config | n/a | existing `export_mail` record (tests/test_registry.py:44,108,242) | exact |
| `macos_apps_mcp/doctor.py` `_AUTOMATION_APPS` (drop "Photos") | config | n/a | itself (line 37) | exact |
| `tests/test_files.py` (rename of `test_mail_files.py`) | test | file-I/O | `tests/test_mail_files.py` | exact |
| `tests/test_photos.py` (rewrite), `tests/_fakes.py` (+FakePhotosDB) | test | fakes | existing `tests/test_photos.py`, `_fakes.py` | role-match |
| `tests/test_notes.py` (+FTS cases) | test | | `tests/test_notes.py:397-455`, `_make_notestore` | exact |
| `tests/conftest.py:215`, `tests/test_native_seam.py:30` (+`photos_db`) | test infra | | themselves | exact |
| `tests/test_tool_annotations.py:111` (`envelope_only` += `export_photo`), `tests/test_registry.py` | test | | themselves | exact |
| `tests/test_packaging.py` (+`libdisclaim` needle), `scripts/build_app.sh` | build | | `ARCH-SPECIFIC NON-BINARY` needle (test_packaging.py:133) | exact |
| `tests/integration/test_photos_integration.py` | test | | existing `tests/integration/*` | role-match |
| `pyproject.toml`, `CREDITS.md`, `CHANGELOG.md`, `docs/DAEMON.md` | config/docs | | self | exact |
| `tests/test_mail_extras.py` (`mail.mail_files.MAX_BYTES` at :72, :240) | test | | self | exact |

## Pattern Assignments

### `macos_apps_mcp/files.py` (utility, file-I/O) - analog `adapters/mail_files.py`
`git mv`, keep: `root()`, `safe_basename`, `_truncate`, `resolve_dest`, `target_path`, `confirm_written`, env `MACOS_APPS_FILE_ROOT`, `_DEFAULT_ROOT`. Changes (D-11):
- `MAX_BYTES` (line ~46) -> per-caller: `check_size(size, name, *, max_bytes)`; Mail keeps `MAIL_MAX_BYTES = 25*1024*1024` in `mail_attachments.py` (also fed to AppleScript argv at :336).
- Remove "mail" wording: `resolve_dest` error ("mail can only be written under it"), `check_size` ("Save it from Mail directly"), `confirm_written` ("attachment is not available locally ... Open the message in Mail"; add `hint=""` kwarg), `_FALLBACK = "attachment"`. Tests match on substrings `"outside"`, `"already exists"`, `"larger than"`, `"0 bytes"`, `"cap"` - keep them.
Core excerpt to preserve (mail_files.py `target_path`):
```python
directory = resolve_dest(dest_dir)
path = (directory / safe_basename(name, fallback)).resolve()
if not path.is_relative_to(directory):
    raise ValueError(f"refusing to write outside {directory}")
if path.exists():
    raise FileExistsError(f"{path} already exists — this never overwrites. ...")
return path
```
Importers to edit (grep, tracked only): `adapters/mail.py` (import list ~:96; uses `target_path` :2496, `resolve_dest` :2513; docstrings :40, :1442, :2474), `adapters/mail_attachments.py` (`from . import mail_addressing, mail_files` :30; `check_size` :326, `target_path` :328, `MAX_BYTES` :336, `confirm_written` :344), `tests/test_mail_extras.py` (:72 exact argv assertion, :240), `tests/test_mail_files.py`, `docs/mail-applescript-facts.md` (:161-171), `docs/ROADMAP.md:46`. Adapters import it as `from .. import files` (qualified).

### `runtime.photos_db()` (native seam)
**Analog:** `runtime.read_via_sqlite` (runtime.py:433, signature `path, fingerprint, query, *, fallback, immutable, setup`) and the RESEARCH Pattern 1 skeleton (lazy `import osxphotos` inside the function, run on worker via `run_native`, `PermissionError` -> FDA typed error, `sqlite3.Error/KeyError/AttributeError/ValueError` -> `SchemaDrift`). Register the seam in three places:
- `tests/conftest.py:215`: `for seam in ("run_osascript", "body_file", "tracked_run"):` add `"photos_db"` (refusal closure raises `AssertionError("a unit test reached ...")`).
- `tests/test_native_seam.py:30`: `_SEAM = frozenset({"run_osascript", "body_file", "tracked_run"})` add `"photos_db"`, plus its parametrize list `test_unit_tests_cannot_reach_a_seam_unfaked`.
- Adapters call `runtime.photos_db()` qualified, never `from ..runtime import ...` (`test_native_module_does_not_import_the_seam_by_name`). `test_native_seam.py` asserts `len(_NATIVE_MODULES) >= 10` - still true after the move.

### `adapters/photos.py` (adapter) - analogs `reminders.py` + `mail.py:export`
**Imports** (current file, keep style; drop AppleScript/STRIP_FRAMING/parse_framed):
```python
from __future__ import annotations
from .. import files, runtime
from ..contracts import Pointer, read_result
from ..text import clean_summary, fold_text
```
Reminders imports `from ..runtime import run_native` (reminders.py:43) - allowed there because it is not a mail/seam name; for photos use `runtime.run_native(...)` qualified for consistency with seam test.

**Envelope pattern** (reminders.py:295-326): `get_pointers` stays a `list[Pointer]`; add `read()` returning `read_result(pointers, coverage=note)`; a NativeError from the optional enrichment is named in `coverage`, never swallowed:
```python
try:
    tags, parents = reminders_store.tags_and_parents()
except NativeError as e:
    return read_result(pointers, coverage=f"tags and parent links unavailable: {e}")
...
return read_result(pointers, coverage=note)
```
For Photos: `photo_albums()` -> `read_result(pointers, cap=MAX_ALBUMS)`; `photos(q)` -> one `db.photos()` pass with `fold_text` predicate over filename/original_filename/title/description/keywords/place/persons/labels, cap `MAX_PHOTOS = 25` (existing constant, photos.py:19) with `truncated`.

**Query guard** (existing photos.py, keep): `if not q: raise ValueError("photos read needs a search string (got an empty query)")`. Unknown id -> `ValueError` (D-05); normalise `strip().split("/")[0].upper()` then `db.get_photo`.

**Export shape** (mail.py:2457-2514, copy the per-id `absent` + envelope):
```python
if payload is None:
    out.append({"id": t.id, "status": "absent", "fidelity": t.fidelity}); continue
path = mail_files.target_path(dest_dir, f"{t.id}.eml", fallback="message")
...
out.append({"id": t.id, "status": "written", "path": str(path), "bytes": len(payload)})
return {"results": out, "written": sum(...), "dest_dir": str(mail_files.resolve_dest(dest_dir)), "plane": "at-rest"}
```
Photos adaptation (RESEARCH Pattern 6): decide `absent` from `src = p.path_edited if p.hasadjustments else p.path` is None BEFORE exporting; `files.check_size(os.stat(src).st_size, ..., max_bytes=PHOTO_MAX_BYTES)`; `files.target_path` (Python overwrite refusal first); call `p.export(dest, filename=..., edited=p.hasadjustments, overwrite=False, increment=False)` with explicit kwargs only; empty result -> `VerificationFailed`; then `files.confirm_written(path)`. `ismovie` -> typed refusal. Name from actual source suffix.

### `adapters/notes.py` (+ `read()` and body FTS pass) - analog same file
**Substring pass to keep** (notes.py:542-554):
```python
needle = fold_text(query).strip()
if not needle:
    raise ValueError("notes read needs a title substring (got an empty query)")
def read(conn):
    uuid = _store_uuid(conn)
    for r in conn.execute(_ALL_SQL):
        if needle in fold_text(r[1]) or needle in fold_text(r[2]):
            out.append(_note_pointer(r, uuid))
```
**Wrapper to reuse** (notes.py:570-576): `read_via_sqlite(NOTESTORE, _FINGERPRINT, read, fallback=fallback, immutable=False)`. Make both closures return `(pointers, plane, coverage)` and build `read_result` after; fallback -> `plane="applescript"`, `coverage="titles only — body search needs Full Disk Access"`. `get_pointers` stays a list (tests :397-455).
**FTS query sanitiser** - copy from `mail_index._fts_query` (mail_index.py:1712-1727): quote each token as a phrase, double embedded `"`:
```python
tokens = raw.split()
return " ".join('"' + t.replace('"', '""') + '"' for t in tokens)
```
Differences for Notes: join with ` OR `, tokens of length >= 4, else all tokens (RESEARCH Pattern 7). Body corpus SQL/`:memory:` FTS5 table recipe is in RESEARCH Pattern 7 (join `ZICNOTEDATA d ON d.Z_PK = o.ZNOTEDATA`, `_decode_note_data`, skip `ZISPASSWORDPROTECTED`); call `runtime.verify_sqlite_schema(conn, _BODY_FINGERPRINT)` in the body pass; on `SchemaDrift`/`OperationalError` keep substring hits and say so in `coverage`. Add a `# shortcut:` comment (O(library) decode per call).

### `server.py` tools
**Additive export** (server.py:607-628) - copy decorator and docstring shape (permission named in docstring, `plane`, per-id `absent`):
```python
@_additive_tool(audit="export", adapter="mail", permission="Full Disk Access")
def export_mail(ids: str, dest_dir: str) -> dict:
    """... (Full Disk Access). ... Additive: writes new files, never overwrites ..."""
    return _mail.export(ids, dest_dir)
```
-> `@_additive_tool(audit="export", adapter="photos", permission="Full Disk Access")`. Reads: current `@_read_tool(adapter="photos", permission="Automation")` (server.py:1065) becomes `permission="Full Disk Access"`; `notes()` (:1018) returns `_notes.read(title)` envelope, keep `permission="Automation"` wording plus Full Disk Access in docstring (it still has the Automation floor). Tools stay one-line dispatch. Add to `envelope_only` (`tests/test_tool_annotations.py:111`, next to `"export_mail"`), and update frozen tables in `tests/test_registry.py` (:44 tool list, :108 permission map `"export_mail": "Full Disk Access"`, :121 `"photos": "Automation"`, :242 audit-verb map `"export_mail": "export"`) - compared with `==`.

### `doctor.py`
Remove `"Photos"` from `_AUTOMATION_APPS` (doctor.py:37-45) after confirming nothing else sends Apple Events to Photos.

### Build/packaging
- `scripts/build_app.sh`: after the per-arch `uv pip install` loop, `rm -f "$WORK/site-$a/osxphotos/lib/"libdisclaim_*.dylib` in BOTH trees (before the lipo/`cmp -s` steps); update comment at ~:98 (cffi/pycparser re-enter via xattr; only cryptography stays pruned, `--prune cryptography` at :105); add `import osxphotos` to both smokes.
- `tests/test_packaging.py:133`: extend `for needle in ("shasum -a 256 -c", "ARCH TREES DIFFER", "ARCH-SPECIFIC NON-BINARY"):` with `"libdisclaim"`.
- `docs/DAEMON.md`: "leaves out cryptography, cffi and pycparser" -> cryptography only. `CREDITS.md` + osxphotos (MIT). `CHANGELOG.md`: `notes()` return-shape change, `photos()` id/mechanism change, `photo_albums`/`photo_info`/`export_photo`. `pyproject.toml`: `osxphotos>=0.77.2,<0.78` in base deps; replace stale "Photos extra deferred" comment.

## Shared Patterns
- **Envelope:** `contracts.read_result(pointers, cap=..., plane=..., coverage=...)` for every bounded read (reminders.py:295-326).
- **Typed errors:** raise `NativeError` subclasses from `errors.py` (FDA, `SchemaDrift`, `VerificationFailed`, `ValueError` for bad ids); never `[]` for a failure.
- **Qualified seam imports:** `from .. import runtime, files`; call `runtime.x()`.
- **Text hygiene:** `clean_summary`, `fold_text`, `clean_body` on all free text (title, description, place, person names).
- **Docstring permission:** each tool docstring names its permission ("Full Disk Access"); `tests/test_tool_annotations.py` checks it.
- **Write-to-disk:** only through `files.*`; overwrite refusal in Python before osxphotos writes.

## No Analog Found
| File | Role | Reason |
|---|---|---|
| `runtime.photos_db()` cache keyed on `(st_mtime_ns, st_size)` of `Photos.sqlite` + `-wal` | native seam | No cached native handle exists; RESEARCH Pattern 2 is the spec (discretion: per-call vs cache, decide from D-03 timing) |
| `tests/integration/test_photos_integration.py` import of throwaway photo | device test | Photos AppleScript cannot delete media (Pitfall 6); see RESEARCH Open Question 1 |

## Metadata
**Analog search scope:** `macos_apps_mcp/`, `macos_apps_mcp/adapters/`, `tests/`, `scripts/`, `docs/`
**Not read:** RESEARCH.md lines 462-671 (Code Examples, Open Questions, validation) - planner should read them.
**Extraction date:** 2026-10-18
