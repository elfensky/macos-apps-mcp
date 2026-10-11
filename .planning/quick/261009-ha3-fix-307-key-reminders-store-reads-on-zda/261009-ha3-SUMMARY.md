---
phase: quick-261009-ha3
plan: 01
subsystem: reminders
tags: [reminders, sqlite, eventkit, local-list, "#307"]
status: complete
requires: []
provides:
  - "Reminders store reads keyed on ZDACALENDARITEMUNIQUEIDENTIFIER (`_EK_ID`)"
affects: [reminders_store, reminders delete guard]
key-files:
  modified:
    - macos_apps_mcp/adapters/reminders_store.py
    - tests/test_reminders_store.py
    - tests/test_reminders.py
    - CHANGELOG.md
decisions:
  - "One key column `_EK_ID`, no COALESCE; a NULL key fails closed"
commits: 2
plan_head_before: 241db7f9ba38576d448c7f5fd3b230517ac4da8d
plan_head_after: 8d279a6ff23b544e17e826e52605f035c47838ce
actuals:
  tasks: 2
  commits: 2
---

# Phase quick-261009-ha3 Plan 01: Key Reminders store reads on the EventKit id column Summary

Every Reminders store query and the fingerprint now key on `ZDACALENDARITEMUNIQUEIDENTIFIER` (module constant `_EK_ID`), so a reminder on a Local list (NULL `ZCKIDENTIFIER`) is live, tagged, parented and covered by the delete guard (#307).

## Commits (code lane, branch fix/307-local-reminders-key, not pushed)

| Task | Commit | Subject |
| ---- | ------ | ------- |
| 1 | d513123 | fix(reminders): key Reminders store reads on the EventKit id column (#307) |
| 2 | 8d279a6 | docs(changelog): Local-list reminders are found in the Reminders store (#307) |

Task 1 first landed as 7caf407. An E501 ruff failure (one docstring line, 89 columns) was fixed with an amend before anything was pushed, so d513123 is the commit.

## RED (new tests against unchanged `reminders_store.py`)

Run: `rtk proxy uv run pytest -q -rf tests/test_reminders_store.py tests/test_reminders.py tests/test_server.py` gave 6 failed, 228 passed (exit 1). Every pre-existing test passed.

| Test | Failure line |
| ---- | ------------ |
| tests/test_reminders_store.py::test_a_local_list_row_is_live | `AssertionError: assert {'R1', 'R2', 'R3'} == {'L1', 'R1', 'R2', 'R3'}` |
| tests/test_reminders_store.py::test_subtasks_of_a_local_list_parent | `NativeError: reminder 'LP' is not in the Reminders store (not synced yet, or a different store file), so its subtasks cannot be seen.` |
| tests/test_reminders_store.py::test_a_local_list_reminder_has_its_tag_and_parent | `KeyError: 'LC'` |
| tests/test_reminders_store.py::test_a_store_missing_the_eventkit_id_column_is_schema_drift | `Failed: DID NOT RAISE SchemaDrift` |
| tests/test_reminders_store.py::test_a_cloudkit_only_row_fails_closed | `AssertionError: assert 'CK-ONLY' not in {'CK-ONLY', 'R1', 'R2', 'R3'}` |
| tests/test_reminders.py::test_a_local_list_parent_with_subtasks_is_refused_unless_confirmed | `WriteRefused: delete_reminder refused: the Reminders store could not be read to find this reminder's subtasks (reminder 'P1' is not in the Reminders store ...)` |

## GREEN and verification (exit codes)

| Check | Exit | Result |
| ----- | ---- | ------ |
| `uv run pytest -q` | 0 | 1944 passed, 97 deselected |
| `MACOS_APPS_ALLOW_SEND=mail uv run pytest -q` | 0 | 1940 passed, 4 skipped, 97 deselected |
| `uv run ruff check .` | 0 | clean |
| `uv run ruff format --check .` | 0 | clean |
| `rtk proxy uv run pytest --collect-only -q` | 0 | 1944/2041 collected (97 deselected); baseline 1938, +6 |
| Task 1 targeted run (store, reminders, server tests) | 0 | 234 passed |
| Task 1 `python -c` assertion (no `ZCKIDENTIFIER`/COALESCE in the five queries or `_FINGERPRINT`) | 0 | pass |

Branch state: exactly 2 commits ahead of origin/develop; both subjects end `(#307)`; both bodies carry the `Co-Authored-By: Claude Opus 5.5` trailer; the diff touches only CHANGELOG.md, reminders_store.py, tests/test_reminders.py and tests/test_reminders_store.py; no file deleted; no `.planning/` file committed; nothing pushed. No EventKit call, Reminders write or real-store open was made.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] E501 in the new `_add_reminders` docstring**
- **Found during:** Task 1 lint run
- **Fix:** shortened the first docstring line to 88 columns and amended the unpushed Task 1 commit (7caf407 -> d513123)
- **Files modified:** tests/test_reminders_store.py

Otherwise the plan ran as written. The `_wire_delete` docstring wording ("ckid" -> "EventKit id") was updated in tests/test_reminders.py as planned.

## Known Stubs

None.

## Out-of-scope flags (follow-up candidates, not implemented)

- `store_path()` picks the largest `Data-*.sqlite` by main-file size. With equal sizes, `scandir` order decides (#307 "also worth a look"). The orchestrator files a separate issue.
- The project skill `spike-findings-macos-apps-mcp` (main checkout, untracked: `SKILL.md` line 72 and `references/reminders-tags-subtasks.md` lines 35-54) still says to join on `ZCKIDENTIFIER`. It needs the new key and the 2026-10-09 measurement.

## Not checked

Device behaviour (iCloud tag/parent parity, Local-list `complete_reminder`/`delete_reminder` dry run) is the orchestrator's check; all tests here use a synthetic store.

## Self-Check: PASSED

Files exist (the four modified paths), commits d513123 and 8d279a6 are ancestors of HEAD.

## Task 3: read every per-account store file (#307)

Code lane commits (not pushed): fafc204 `fix(reminders): read every per-account Reminders store file (#307)` (reminders_store.py, tests/test_reminders_store.py, tests/test_reminders.py, tests/test_server.py) and 834b627 `docs(changelog): every Reminders store file is read (#307)`. Four commits now sit ahead of origin/develop; all subjects end `(#307)`, all carry the Claude Opus 5.5 trailer; no `.planning/` file committed.

Design: `store_paths()` replaces `store_path()` (same scandir and typed errors; every `Data-*.sqlite`, size descending then name). One helper `_read_all(query)` keeps the files that have `ZREMCDREMINDER` (`_HAS_TABLE`), raises `SchemaDrift` naming `ZREMCDREMINDER` when none has it, and runs `query` against each kept file with `_FINGERPRINT` (a mismatch in any file raises). `live_ids` unions, `tags_and_parents` merges, `subtasks_of` returns the first non-`None` answer (the file with a live row for the parent) or raises the existing NativeError. No new module, no option, no COALESCE.

### RED
Run 1, tests changed, module unchanged: 50 failed, 12 errors. All of it is `AttributeError: ... has no attribute 'store_paths'` from the rename (every `monkeypatch.setattr(..., "store_paths", ...)` and every `store_paths()` call).

Run 2, to separate real behaviour from that noise: a temporary shim in `reminders_store.py` (`store_paths = lambda: [store_path()]`, `store_path = lambda: store_paths()[0]`: rename only, single-file behaviour). It was removed with `git checkout -- <file>` before the fix. Result: 8 failed, 233 passed. The 8 NEW-behaviour failures:

| Test | Failure |
| ---- | ------- |
| test_reminders_store.py::test_live_ids_are_the_union_over_every_store_file | `assert {'R1','R2','R3'} == {... 'LP','LC','LC2' ...}` |
| test_reminders_store.py::test_tags_and_parents_merge_every_store_file | `{'R1': ...} == {... 'LC': ('errand',)}`, Local tag missing |
| test_reminders_store.py::test_subtasks_of_asks_the_store_file_that_has_the_parent | `NativeError: reminder 'LP' is not in the Reminders store` |
| test_reminders_store.py::test_a_drifted_store_file_fails_the_whole_read | `DID NOT RAISE SchemaDrift` |
| test_reminders_store.py::test_a_shell_file_beside_a_real_store_is_skipped | Local ids missing from the union |
| test_reminders_store.py::test_a_directory_of_only_shell_files_is_schema_drift | message names `Z_PRIMARYKEY`, not `ZREMCDREMINDER` |
| test_reminders_store.py::test_store_paths_lists_every_data_file_largest_first | one path returned, not three |
| test_reminders.py::test_a_local_parent_in_the_smaller_store_file_is_refused_unless_confirmed | `WriteRefused ... reminder 'P1' is not in the Reminders store` |

The two tightened drift tests (`match=r"missing column.*<COLUMN>"`) pass on the old code too, as expected (the old fingerprint raised that message); they now fail if the column leaves `_FINGERPRINT`. The two-store fixture pads the iCloud file with 400 id-less tombstones so it is the larger file (without padding both files were 16384 B and the order was a scandir tie).

### GREEN and verification (exit codes)

| Check | Exit | Result |
| ----- | ---- | ------ |
| `uv run pytest -q` | 0 | 1951 passed, 97 deselected |
| `MACOS_APPS_ALLOW_SEND=mail uv run pytest -q` | 0 | 1947 passed, 4 skipped, 97 deselected |
| `uv run ruff check .` | 0 | clean |
| `uv run ruff format --check .` | 0 | clean |
| `rtk proxy uv run pytest --collect-only -q` | 0 | 1951/2048 collected (97 deselected); +7 vs 1944 |
| leftover `store_path\b` grep in the 4 files | 1 | no match (good) |
| `_HAS_TABLE` present; only `reminders_store.py` changed under `macos_apps_mcp/` | 0 | pass |

Deviations: none beyond the added test helper `_create_store` (empty store with the three fingerprint tables), which `_make_reminders_store` now also uses. Not checked: device behaviour with a real Local account (orchestrator's check); no EventKit call, Reminders write or real-store open was made.
