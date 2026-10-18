---
phase: 04-notes-photos-settle-the-mechanism-then-ship-the-read-plane
plan: 04
subsystem: photos
tags: [osxphotos, photos, read-plane, full-disk-access, seam, doctor]

requires:
  - phase: 04-notes-photos-settle-the-mechanism-then-ship-the-read-plane
    provides: "04-01: osxphotos locked and proven in the signed bundle (photosdb_open_s 0.03)"
provides:
  - "runtime.photos_db(): the one lazy, fail-closed door to osxphotos, run on the native worker"
  - "photos(query) on osxphotos in the {results, truncated?} envelope, ids = Photos uuid"
  - "photo_albums() and photo_info(id) read tools (22-key whitelist, no bytes)"
  - "doctor without a Photos Automation probe (11 surfaces)"
affects: [04-05 photos export, 04-06 photos device sitting]

actuals:
  tokens: 9000
  tasks: 3
  commits: 6
plan_head_before: 9a90d5d
plan_head_after: 8382ebb

tech-stack:
  added: []
  patterns: [lazy third-party import inside a runtime seam, fail-closed seam registered in conftest and test_native_seam]

key-files:
  created: []
  modified: [macos_apps_mcp/runtime.py, macos_apps_mcp/adapters/photos.py, macos_apps_mcp/server.py, macos_apps_mcp/doctor.py, tests/conftest.py, tests/test_native_seam.py, tests/test_photos.py, tests/test_registry.py, tests/test_server.py, tests/test_integration.py, tests/test_doctor.py, tests/test_runtime.py, README.md, DESIGN.md, CHANGELOG.md]

key-decisions:
  - "PhotosDB is built per call (photosdb_open_s 0.03 s from 04-01); the cache keyed on Photos.sqlite and -wal stat waits until an open passes about 1 s (shortcut comment in runtime.py)"
  - "A trashed photo counts as unknown for photo_info, though osxphotos get_photo returns it"
  - "Album pointers say '1 photos' for a single photo: the plan fixed the summary shape '<title> (<n> photos)'"

requirements-completed: [PHO-02, PHO-03]

coverage:
  - id: D1
    description: "photo_info returns the 22-key whitelist by uuid, accepts the lower-case and <UUID>/L0/001 aliases, rejects unknown, malformed and trashed ids, cleans every string"
    requirement: PHO-03
    verification:
      - kind: unit
        ref: "tests/test_photos.py#test_photo_info_end_to_end_returns_the_whitelist"
        status: pass
      - kind: unit
        ref: "tests/test_photos.py#test_photo_info_aliases_resolve_to_one_record"
        status: pass
    human_judgment: false
  - id: D2
    description: "photos() searches eight fields in one folded pass, newest first, capped at 25 with truncated; pointers carry no location or person"
    requirement: PHO-02
    verification:
      - kind: unit
        ref: "tests/test_photos.py#test_photos_search_matches_each_searched_field"
        status: pass
      - kind: unit
        ref: "tests/test_photos.py#test_photos_search_caps_at_max_photos"
        status: pass
    human_judgment: false
  - id: D3
    description: "photo_albums() lists albums as pointers, keeps same-title albums apart, orders them, caps at 100 with truncated"
    requirement: PHO-02
    verification:
      - kind: unit
        ref: "tests/test_photos.py#test_photo_albums_cap"
        status: pass
      - kind: unit
        ref: "tests/test_photos.py#test_photo_albums_order_is_folder_then_title_then_uuid"
        status: pass
    human_judgment: false
  - id: D4
    description: "Every osxphotos access runs on the native worker through a fail-closed seam; the adapter holds no AppleScript; doctor reports 11 surfaces"
    requirement: PHO-02
    verification:
      - kind: unit
        ref: "tests/test_native_seam.py#test_unit_tests_cannot_reach_a_seam_unfaked"
        status: pass
      - kind: unit
        ref: "tests/test_photos.py#test_the_photos_adapter_has_no_applescript"
        status: pass
      - kind: unit
        ref: "tests/test_doctor.py"
        status: pass
    human_judgment: false
  - id: D5
    description: "Real-library behaviour through the installed daemon with Full Disk Access"
    requirement: PHO-03
    human_judgment: true
    rationale: "Unit tests use a fake PhotosDB; the device proof is plan 04-06"

duration: ~50min
completed: 2026-10-18
status: complete
---

# Phase 4 Plan 04: Photos read plane on osxphotos Summary

Photos read plane on osxphotos (photos, photo_albums, photo_info) — PR #374, on develop at 8382ebb.

**`photos()` now reads the Photos library at rest through osxphotos and returns `{results, truncated?}`; `photo_albums()` and `photo_info(id)` are new, every Photos tool takes the Photos uuid, and the tools need Full Disk Access, not Automation.**

## Performance

- **Duration:** about 50 min
- **Completed:** 2026-10-18
- **Tasks:** 3 of 3 (Task 1 was the tracer; its end-to-end verify passed before expansion)
- **Files modified:** 15 (4 source, 8 test, 3 docs)

## Accomplishments

- `runtime.photos_db()` imports osxphotos lazily on the worker and maps PermissionError to FullDiskAccessDenied, FileNotFoundError to a plain NativeError, a missing package to a NativeError, and any other failure to SchemaDrift naming the osxphotos version. `import macos_apps_mcp.server` does not load osxphotos.
- `photo_info`: 22 whitelisted keys, strings through `clean_summary`, persons drop `_UNKNOWN_` and empties, no bytes, thumbnails or paths. `<UUID>/L0/001`, the lower-case form and a padded id all return the same record.
- `photos()`: one pass over original filename, filename, title, description, keywords, place, persons and labels; folded; newest first (ties by uuid, descending); 24/25/26 matches give 24/25/25 results with `truncated` absent/present/present. Search pointers hold only id, summary, deeplink.
- `photo_albums()`: pointers with folder path, ordered by folded folder, title, uuid; 99/100/101 albums give 99/100/100 with `truncated` absent/present/present; same-title albums stay separate; `(untitled album)` and `(0 photos)` cases covered.
- `doctor._AUTOMATION_APPS` lost Photos (11 surfaces). A grep over `macos_apps_mcp/` finds no `application "Photos"`.
- README, DESIGN.md and CHANGELOG describe the new tools, the breaking `photos()` changes and the permission move.

## Task Commits

On develop after the rebase-merge of PR #374 (develop before: 9a90d5d, after: 8382ebb; `commits: 6` measured with `git rev-list --count 9a90d5d..8382ebb`):

1. **Task 1 RED:** `6808663` test(photos): photo_info reads one photo by id through the photos_db seam
2. **Task 1 GREEN (tracer):** `41b5795` feat(photos): photo_info reads bounded metadata by id through osxphotos
3. **Task 2 RED:** `b393054` test(photos): search and albums on osxphotos in the read envelope
4. **Task 2 GREEN:** `ee65173` feat(photos): photos() and photo_albums() read through osxphotos
5. **Task 3a:** `a6163c6` feat(doctor): Photos needs Full Disk Access, not Automation
6. **Task 3b:** `8382ebb` docs(photos): the read plane in README, DESIGN and CHANGELOG

## TDD notes

- RED for Task 1: with `runtime.photos_db` absent, the test module fails at collection (the plan binds `_REAL_PHOTOS_DB` at import). A transient, uncommitted stub of `photos_db` gave the assertion-level RED: 24 target tests failed on a missing `photo_info` tool or the stub, 48 others passed. Semantic assessment: the failures are the planned behaviours, not fixture faults. `gsd_run check tdd-red-evidence` was not run (plan type is `execute`, not `tdd`).
- RED for Task 2: 35 failed, 161 passed; the failures come from the AppleScript path still being in place (seam refusal, missing `albums`/`read`, banned strings in the source).
- No REFACTOR commit.

## Verification

- Local, in the lane before the PR: `uv run pytest -q` 2136 passed; `MACOS_APPS_READ_ONLY=1` 2124 passed, 12 skipped; `MACOS_APPS_ALLOW_SEND=mail` 2132 passed, 4 skipped; `ruff check` clean; `ruff format --check` clean.
- Acceptance criteria: `def photos_db` 1; `osxphotos` not in `sys.modules` after importing the server (`False`); `photo_info` tests 19 passed; `photos_db` seam test 1 passed; album tests 9 passed; `has_no_applescript` 1 passed; registry shows `Full Disk Access` for `photos`, `photo_albums`, `photo_info`; `_AUTOMATION_APPS` is `('Mail', 'Notes', 'Contacts', 'Safari', 'Messages', 'Music')`; README holds `photo_albums` and `photo_info`; DESIGN.md holds `osxphotos` 3 times.
- Precondition: `photosdb_open_s` read from `.worktrees/p04-gate.json` = 0.03 (under 1.0, so per-call PhotosDB holds).
- CI: PR #374, required `check` job passed in 1m18s, then rebase-merged. Plan-level grep on `origin/develop:macos_apps_mcp/server.py` printed `3`. Lane unlocked, removed, branch deleted; main checkout fast-forwarded.
- T-04-SC: `git diff --name-only origin/develop` listed neither `pyproject.toml` nor `uv.lock`.

## Code review

The `code-review` skill needs a sub-agent tool this executor did not have. The diff `origin/develop...HEAD` was reviewed inline against the plan, PHO-02, PHO-03 and D-04..D-07. No open finding. Checked: the seam is called qualified and only inside `run_native`; `_uuid` validates before the seam; trashed photos are unknown; no key carries a path or bytes; search pointers carry no GPS or person name; strings are cleaned. The orchestrator runs an independent review.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocker] The runtime public-surface test lists every public name**
- **Found during:** Task 1 GREEN (full suite)
- **Issue:** `tests/test_runtime.py::test_runtime_public_surface_is_the_native_door` pins the set of public functions in `runtime`; the new `photos_db` broke it. The file is not in the plan's `files_modified`.
- **Fix:** added `"photos_db"` to the expected set.
- **Files modified:** tests/test_runtime.py
- **Commit:** 41b5795

**2. [Rule 1 - Test defect] The tool wraps ValueError as ToolError**
- **Found during:** Task 1 GREEN
- **Issue:** the plan's behaviour text says the tool raises ValueError; `_guard` turns it into a `ToolError`. Five RED tests expected ValueError from `srv.photo_info`.
- **Fix:** the id-rejection tests call `PhotosAdapter().info` for ValueError; one tool-level test expects `ToolError` naming the id.
- **Files modified:** tests/test_photos.py
- **Commit:** 41b5795

**3. [Rule 1 - Test defect] Empty-query probe and album order**
- **Found during:** Task 2 RED/GREEN
- **Issue:** `"U+200B"` does not fold to empty (zero-width space survives `fold_text`); and the nested-folder album test assumed folder albums sort before top-level ones, but the empty folder key sorts first.
- **Fix:** the empty-query case uses a lone combining mark (`"U+0301"`), which folds to empty; the test reads `top, nested`.
- **Files modified:** tests/test_photos.py
- **Commit:** b393054, ee65173

**4. [Style] A docstring line in `tests/conftest.py` was over 88 columns in the RED commit**
- **Issue:** the edit that added `photos_db` to the seam docstring left an E501 in commit 6808663; it is fixed in the next commit, so the PR tip is clean.
- **Commit:** 41b5795

**Total deviations:** 4 (1 blocker fix, 2 test defects, 1 style). **Impact:** none on behaviour or scope.

### Project root pin

The guard was run from a scratchpad copy that keeps the same logic as the supplied block; two diagnostic echo lines were shortened. It passed before every Edit batch and every commit.

## Known Stubs

None.

## Threat Flags

None. The tools add no network endpoint; the new read surface (Photos metadata) is the one the plan's threat model covers (T-04-12 to T-04-17), and its mitigations are tested: exact key-set test, `clean_summary` on every string, GPS only in `photo_info`, worker-thread test, UUID check before the seam.

## Issues Encountered

- `gh pr merge --delete-branch` skipped the local branch delete because the worktree held it; the lane was removed by hand per the plan.
- The `bumped` CI job is not required (#330); no version bump was made.
- The vault journal bullet is logged (MR 1608 in the vault repo).

## Next Phase Readiness

04-05 (export) can call `runtime.photos_db()` and `PhotosAdapter._uuid`/`_live` for the same id handling and the trashed-id rule. It must still handle the edit-render race recorded in 04-01. 04-06 holds the device proof: the unit tests here use a fake PhotosDB, so real-library reads through the daemon are not yet observed.

## Self-Check: PASSED

PR #374 state MERGED; `origin/develop` holds `def photo_info`, `def photo_albums` and `return _photos.read(query)` (grep count 3); lane directory absent; local branch deleted.

---
*Phase: 04-notes-photos-settle-the-mechanism-then-ship-the-read-plane*
*Completed: 2026-10-18*
