---
phase: 04-notes-photos-settle-the-mechanism-then-ship-the-read-plane
reviewed: 2026-10-19T12:00:00Z
depth: standard
files_reviewed: 21
files_reviewed_list:
  - macos_apps_mcp/adapters/photos.py
  - macos_apps_mcp/adapters/notes.py
  - macos_apps_mcp/files.py
  - macos_apps_mcp/runtime.py
  - macos_apps_mcp/server.py
  - macos_apps_mcp/doctor.py
  - macos_apps_mcp/adapters/mail.py
  - macos_apps_mcp/adapters/mail_attachments.py
  - pyproject.toml
  - scripts/build_app.sh
  - tests/conftest.py
  - tests/test_photos.py
  - tests/integration/test_photos_integration.py
  - tests/test_files.py
  - tests/test_native_seam.py
  - tests/test_registry.py
  - tests/test_runtime.py
  - tests/test_tool_annotations.py
  - tests/test_notes.py
  - CHANGELOG.md
  - README.md
findings:
  critical: 1
  warning: 2
  info: 7
  total: 10
status: issues_found
---

# Phase 4: Code Review Report

**Reviewed:** 2026-10-19T12:00:00Z
**Depth:** standard
**Files Reviewed:** 21
**Status:** issues_found

## Summary

Scope: the phase source diff `cb36415..6e54c05` (planning artifacts and `uv.lock`
excluded). The review covers the cross-plan seams: `files` module and `export_photo`,
`runtime.photos_db` and doctor, the notes envelope and the `notes` tool. The osxphotos
0.77.2 calls (`PhotoInfo.export`, `PhotoExporter._get_dest_path`, `PhotosDB` logging and
temp-copy behaviour) were traced in the installed package source. The unit suite passes
(2178 passed, 102 deselected) and `ruff check` / `ruff format --check` are clean on a
scratch copy of `6e54c05`.

The findings the per-PR reviews already fixed are not repeated here (see the task scope
list; #373 is tracked).

Key concerns:

- The export-failure cleanup added in #381 deletes a file that the tool did not write
  when osxphotos refuses because the destination appeared after `target_path` checked
  it (CR-01). The parallel-session workflow of this repo makes the race reachable.
- The notes body-search expression falls back to 1-character words, so a contraction
  query such as `don't` matches every body that holds any contraction (WR-01).
- An `export_photo` rejected as `VerificationFailed` leaves its directory and, when
  osxphotos wrote under another name, a file that the code labels "not ours" (WR-02).

## Critical Issues

### CR-01: Export-failure cleanup deletes a file the tool did not write

**File:** `macos_apps_mcp/adapters/photos.py:240-255`
**Issue:** The `except Exception` handler unlinks `dest` on any osxphotos failure, on the
reasoning "target_path proved dest absent, so whatever is there now is ours". That is not
true across the check-to-write window. With `overwrite=False, increment=False`,
osxphotos 0.77.2 checks `dest.exists()` itself (`PhotoExporter._get_dest_path`,
`raise FileExistsError("destination exists ...")`) and refuses. That refusal is the safe
outcome. The handler then deletes the file another writer put there.

The race is reachable: in stdio mode every client runs its own server process, and this
repo runs parallel sessions by design. Two sessions that export the same photo into the
same `dest_dir` derive the same name (`<stem>_<id8>.<ext>`). Session A passes
`target_path` and writes the file; session B passes `target_path` before A's write, gets
`FileExistsError` from osxphotos, and unlinks A's finished file. A has already returned
`status: "written"` with that path. The result is the "reassuring-direction lie" this
repo refuses, and an accidental delete of a write the model reported as done.

The window is milliseconds, so the probability is low. The consequence is silent data
loss under the "Safe writes" core value. The fix is one clause.

**Fix:** Let osxphotos' own refusal pass through without cleanup:
```python
try:
    written = p.export(
        str(dest.parent),
        filename=dest.name,
        edited=edited,
        overwrite=False,
        increment=False,
    )
except FileExistsError:
    # osxphotos refused: the file there now is someone else's — never delete it.
    raise
except Exception as e:
    dest.unlink(missing_ok=True)
    raise NativeError(...) from e
```
Add a unit test: a fake `export` that creates `dest`, then raises `FileExistsError`;
assert that the file still exists.

## Warnings

### WR-01: Body search falls back to 1-character words and floods results

**File:** `macos_apps_mcp/adapters/notes.py:530-541`
**Issue:** `_fts_expr` keeps words of 4+ characters, or ALL words when none is that long.
The `\w+` split breaks a contraction at the apostrophe, so the fallback emits
1-character phrases that are joined with OR:

- `don't` → `"don" OR "t"`. The unicode61 tokenizer splits every `isn't`, `can't`,
  `it's` in a body into a `t` or `s` token, so nearly every English note body matches.
- `C++` → `"C"`, which matches every body with a standalone `c`.
- `tax 2024` → `"2024"` only. `tax` is dropped, so the body pass returns every note that
  holds the year.

These body-only hits are appended after the title/snippet hits until `MAX_NOTES`. The
envelope then reports `truncated: true`, and the hits are noise, not partial matches.
A caller cannot tell a precise answer from a flooded one. (Measured on `6e54c05` by
calling `_fts_expr` directly.)

**Fix:** Drop 1-character tokens from the fallback, and keep every word when no 4+ word
remains rather than an empty list:
```python
words = [w for w in re.findall(r"\w+", norm_text(query) or "") if len(w) >= 2]
use = [w for w in words if len(w) >= 4] or words
```
Add `don't`, `C++` and `tax 2024` cases to `tests/test_notes.py`. Whether `tax` must stay
in a mixed-length query is a ranking decision against spike 004; record it as a D-NN if
the 4-character rule is meant to drop it.

### WR-02: A `VerificationFailed` export leaves a stray directory and a file of its own

**File:** `macos_apps_mcp/adapters/photos.py:235-262`
**Issue:** `files.target_path` → `resolve_dest` creates `dest_dir` before the export. When
osxphotos returns no path, or a path other than `dest`, the code raises
`VerificationFailed` and leaves both the new directory and any file at `written[0]`.
The test `test_export_photo_a_different_written_path_is_a_verification_failure` pins
`stray.exists()` as "not ours to delete". But osxphotos wrote that file during this
call, for this photo, inside the allowed root. It is a by-product of this tool, not a
foreign file. The message tells the model "nothing was exported", while a full-size copy
of the photo stays on disk under a name the model never sees.
**Fix:** When `written` names a path inside `dest.parent` that did not exist before the
call, unlink it before the raise. Alternatively, keep the file and return its path in the
error text as the only reference to it. In both cases, state the outcome truthfully
("osxphotos wrote X instead; it was removed" or "it is at X"), and keep the existing
test for a path OUTSIDE the destination directory.

## Info

### IN-01: `FileExistsError` and other `OSError`s bypass `_guard`

**File:** `macos_apps_mcp/server.py:75`, `macos_apps_mcp/files.py:134`
**Issue:** `_guard` converts only `NativeError` and `ValueError`. `target_path` raises
`FileExistsError`, and `resolve_dest`'s `mkdir` can raise `PermissionError` or
`NotADirectoryError`. Both reach FastMCP as untyped exceptions. This was already true for
`save_mail_attachment` / `export_mail`; `export_photo` now inherits it (unit and
integration tests assert the raw `FileExistsError`).
**Fix:** Raise `WriteRefused` (or a `ValueError` subclass) from `target_path`, or add
`OSError` to `_guard` with an agent-directed message.

### IN-02: `photos_db` maps every osxphotos failure to `SchemaDrift` and echoes raw text

**File:** `macos_apps_mcp/runtime.py:552-558`
**Issue:** `except Exception` turns any failure, transient ones included (for example a
sqlite `database is locked`, or an `OSError` while osxphotos copies a locked
`Photos.sqlite` to temp), into "macOS may have changed the Photos database. Do not retry;
report it." The message interpolates `{e}`, which for osxphotos errors often names the
library file path. #381 removed exactly that path leak from the export error. This
door still has it.
**Fix:** Keep `type(e).__name__` and drop `{e}` from the agent-facing text (log it with
`log.warning` instead). Optionally map `sqlite3.OperationalError` to a retryable
`NativeError`.

### IN-03: Long original filenames lose the id disambiguator

**File:** `macos_apps_mcp/adapters/photos.py:234-237`, `macos_apps_mcp/files.py:86-97`
**Issue:** `_truncate` cuts the stem from the right to 200 bytes. A long
`original_filename` therefore loses the `_<id8>` suffix that keeps two photos apart.
Two photos whose long names share a 200-byte prefix collide, and the second export is
refused with `FileExistsError` and a "choose another dest_dir" hint. This is safe, but
it is a spurious refusal.
**Fix:** Truncate the stem before appending the suffix, for example
`stem = files.safe_basename(stem)[:100]`, so that `_<id8>` always survives.

### IN-04: Body search silently misses CJK and other unsegmented scripts

**File:** `macos_apps_mcp/adapters/notes.py:568-571`
**Issue:** `unicode61` tokenizes a run of CJK characters as one token, so a word inside a
Japanese or Chinese sentence never matches. The envelope gives no `coverage` hint, so the
miss reads as authoritative. The title/snippet substring pass still catches titles.
**Fix:** Document the limitation in the `notes` docstring and in
`docs/notes-semantic-search.md`. Alternatively, run a substring check over decoded bodies
when the query holds no ASCII letters.

### IN-05: `_body_hits` builds its SQL by string replacement on `_FROM`

**File:** `macos_apps_mcp/adapters/notes.py:552-554`
**Issue:** `_FROM.replace(head, ..., 1)` is a silent no-op if `_FROM`'s first line ever
changes. The query then fails on `d.ZDATA`, and every search degrades to "body search
unavailable" with no test failure.
**Fix:** Add an assert, `assert frm != _FROM`, or put the join in a named fragment that
`_FROM` and `_body_hits` share.

### IN-06: Stale references after the Photos move and the 3.12 floor

**File:** `pyproject.toml:86`, `macos_apps_mcp/doctor.py:58`
**Issue:** `target-version = "py311"` stays after `requires-python = ">=3.12"` (D-16). The
doctor `_PROBE` comment still names Photos as the #317 example, though doctor no longer
probes Photos.
**Fix:** Set `target-version = "py312"` (then run `ruff check` for new UP rewrites).
Reword the comment, or name the #317 app generically.

### IN-07: Integration fixture reads osxphotos objects off the native worker

**File:** `tests/integration/test_photos_integration.py:160-168`
**Issue:** `runtime.run_native(lambda: runtime.photos_db().photos(albums=[ALBUM]))`
returns `PhotoInfo` objects, and the fixture then reads `p.uuid` and
`p.original_filename` on the test thread. That breaks the module's own rule ("Every
osxphotos object is touched on the single native worker"). The fixture can also pick a
reused test photo that is hidden, and then every later `info` call refuses it.
**Fix:** Map to `(uuid, original_filename)` inside the worker lambda and skip
`p.hidden`, as `_existing_test_photo_names` already does for names.

---

_Reviewed: 2026-10-19T12:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
