---
phase: 03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub
plan: 06
subsystem: reminders
tags: [reminders, sqlite, core-data, tags, subtasks, full-disk-access, read-only, coverage]

requires:
  - phase: 03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub
    provides: "03-02 container ids in Pointer.folder; 03-05 alarms (develop base a379b1d); spikes 002/007 (store route, 1372/1372 join)"
provides:
  - "macos_apps_mcp/adapters/reminders_store.py: store_path(), _FINGERPRINT, _TAGS, _PARENTS, tags_and_parents() (read-only, no fallback)"
  - "Pointer.tags (tuple[str, ...] | None) and Pointer.parent (str | None), emitted only when set; as_dict -> dict"
  - "RemindersAdapter.read(query) -> {results, coverage?}; reminders() returns the envelope, permission (EventKit, Full Disk Access)"
  - "unreadable store -> EventKit pointers intact + coverage 'tags and parent links unavailable: ...'"
  - "write gap named in the reminders, create_reminder and update_reminder docstrings (D-16)"
affects: [03-07 subtasks_of, 03-08 complete parents, 03-09 device run, 03-10 owner fixture]

actuals:
  tokens: 6200
  tasks: 3
  commits: 6
plan_head_before: a379b1d04eb2a95caf95bc3c9be6d7a25cd270fb
plan_head_after: 401fc893b29f6731b7a1116cbde1c0e779b83640

tech-stack:
  added: []
  patterns:
    - "sqlite sidecar beside its adapter (reminders_store beside reminders), fingerprinted, read_via_sqlite with no fallback"
    - "optional read plane degrades into read_result(coverage=...); the primary plane's errors are raised before the try"
    - "directory listing by os.scandir so a PermissionError stays a Full Disk Access denial"

key-files:
  created:
    - macos_apps_mcp/adapters/reminders_store.py
    - tests/test_reminders_store.py
  modified:
    - macos_apps_mcp/adapters/reminders.py
    - macos_apps_mcp/contracts.py
    - macos_apps_mcp/server.py
    - tests/test_reminders.py
    - tests/test_server.py
    - tests/test_registry.py
    - tests/test_contracts.py
    - tests/integration/test_eventkit_depth.py
    - README.md
    - CHANGELOG.md

key-decisions:
  - "Z_ENT resolved by subquery on Z_PRIMARYKEY.Z_NAME at run time; tombstone filter on tag row, reminder row and parent row"
  - "read() catches NativeError only around the store call; get_pointers runs first, outside any try"
  - "store_path maps every OSError to a typed error (review fix): PermissionError -> FullDiskAccessDenied, missing or empty -> not found, anything else -> NativeError"
  - "Pointer.as_dict widened to -> dict because tags is a list (FastMCP output-schema Pitfall 4); proven over the real client"

patterns-established:
  - "Store fixture builder _make_reminders_store(path, ...) with tombstoned tags, reminders and parents; reused by test_server and test_reminders"

requirements-completed: [REM-03, REM-04]

coverage:
  - id: D1
    description: "reminders() results carry tags and parent from the read-only, fingerprinted Reminders store, joined by EventKit id; tombstones filtered; Z_ENT by name"
    requirement: "REM-03"
    verification:
      - kind: unit
        ref: "tests/test_reminders_store.py#test_tags_and_parents_read_live_rows_only"
        status: pass
      - kind: unit
        ref: "tests/test_server.py#test_reminders_over_the_client_carries_tags_and_parents"
        status: pass
    human_judgment: false
  - id: D2
    description: "An unreadable store (no grant, drifted schema, missing, failing mid-read) keeps the EventKit pointers and names the reason in coverage; EventKit errors are never folded in"
    requirement: "REM-03"
    verification:
      - kind: unit
        ref: "tests/test_reminders.py#test_read_with_an_ungranted_store_keeps_the_eventkit_pointers"
        status: pass
      - kind: unit
        ref: "tests/test_reminders.py#test_read_never_folds_an_eventkit_failure_into_coverage"
        status: pass
    human_judgment: false
  - id: D3
    description: "No tag or subtask write exists; the write gap is named in three docstrings"
    requirement: "REM-04"
    verification:
      - kind: unit
        ref: "tests/test_server.py#test_the_tag_and_subtask_write_gap_is_named_where_the_model_reads_it"
        status: pass
    human_judgment: false
  - id: D4
    description: "Real store on the owner's Mac: Full Disk Access reaches the store, tag and parent values match Reminders.app"
    requirement: "REM-03"
    verification: []
    human_judgment: true
    rationale: "Device run belongs to 03-09 (test_reminders_read_carries_the_store_plane, collected only here) and the owner-built fixture in 03-10"

duration: 40min
completed: 2026-10-06
status: complete
---

# Phase 3 Plan 06: Reminders store plane Summary

**Read-only sqlite sidecar for Reminders tags and parent links, fingerprinted and joined to EventKit by id, degrading loudly into `coverage`**

reminders() now carries tags and parent links (read-only); returns {results, coverage?} — PR #277

## Performance

- **Duration:** about 40 min
- **Completed:** 2026-10-06T08:47Z
- **Tasks:** 3 (Task 1 tracer, Task 2, Task 3)
- **Files modified:** 12 (production: 4, tests: 6, docs: 2)

## Accomplishments

- `reminders_store.tags_and_parents()` reads tags (`ZNAME1`) and parent links (`ZPARENTREMINDER`) from the largest `Data-*.sqlite`, through `read_via_sqlite` with no fallback. `_FINGERPRINT` raises `SchemaDrift` on a mismatch. `Z_ENT` comes from `Z_PRIMARYKEY` by name. `ZMARKEDFORDELETION = 0` filters the tag, reminder and parent rows. Tags pass through `clean_summary`, are de-duplicated and sorted.
- `reminders()` returns `{results, coverage?}`. Each result may carry `tags` and `parent`. The tool declares `("EventKit", "Full Disk Access")`. Verified over the FastMCP client, so the list-valued `tags` passes the output schema.
- An unreadable store still returns every EventKit pointer. `coverage` reads `tags and parent links unavailable: <reason>`. An EventKit failure still raises.
- The docstrings of `reminders`, `create_reminder` and `update_reminder` state that tags and subtasks are read-only ("no public API"). No private selector, App Intent, AppleScript or `#tag` title route exists (`grep` count 0).
- Breaking wire change named in the CHANGELOG and the PR body: the life-cockpit caller must read `results`.

## Task Commits

Merged to `develop` by rebase (PR #277). Hashes on `develop`; the pre-merge lane hashes are in brackets.

1. **Task 1 (tracer): RED** - `341a78e` [13ba49f] test: tags and parent links from the store
2. **Task 1: GREEN** - `4040438` [63959b9] feat: reminders() carries tags and parent links
3. **Task 2: RED** - `6e0672b` [ce15539] test: the store plane degrades loudly
4. **Task 2: GREEN** - `269cd7c` [8d971ad] feat: unreadable store named in coverage; write gap documented
5. **Task 3** - `7bccc15` [883e405] test: device test (collected only); README and CHANGELOG
6. **Review fix** - `8135932` [401fc89] fix: a store directory that cannot be listed stays a typed error

**PR:** https://github.com/elfensky/macos-apps-mcp/pull/277, merged 2026-10-06T08:46:49Z with the rebase method; merge tip `8135932d8eb94728cc67a6f165f63bf6f1baefdb`. Required check `check` passed (1m18s). Lane `.worktrees/rem-store-plane` removed, branch `feat/rem-store-plane` deleted.

## TDD Gate Compliance

- **RED Task 1:** `13ba49f`. New-module tests fail on `ImportError: cannot import name 'reminders_store'` (the module does not exist yet: a load failure, not a planned assertion). The other targets fail on their planned assertion: `test_reminders_tool_dispatches` (list instead of envelope), `test_permission_reproduces_the_develop_era_hand_map` (permission pin), the `as_dict` test (`TypeError` unexpected keyword `tags`) and the client tracer (`ImportError` inside the test body). Semantic assessment: acceptable for a feature whose module is new, but strictly the new-module RED is import-shaped, not assertion-shaped. `gsd_run check tdd-red-evidence` was not run (workflow.tdd_mode not in use for this plan).
- **GREEN Task 1:** `63959b9`, all five targets pass.
- **RED Task 2:** `ce15539`. Four `read()` degrade tests failed because the store error propagated (planned assertion: coverage returned). The docstring test failed on the missing "no public API" text. The `store_path` tests and the tag-sanitising test passed already: that behaviour shipped with Task 1 as the plan placed it, so they are characterisation tests, not RED.
- **GREEN Task 2:** `8d971ad`.
- No REFACTOR commit. The review fix (`401fc89`) was RED first (`NotADirectoryError` escaped) and fixed in the same commit as its test.

## Test counts (`^def test_`), before and after

| File | Before | After |
|------|--------|-------|
| tests/test_reminders_store.py | 0 (new) | 10 |
| tests/test_server.py | 85 | 87 |
| tests/test_reminders.py | 53 | 58 |
| tests/test_registry.py | 17 | 17 |
| tests/test_contracts.py | 57 | 58 |
| tests/integration/test_eventkit_depth.py | 7 | 8 |

No count dropped. Full suite: 1759 passed before the review fix, 1770 after (+11 including the store tests).

## Verification (lane, at tip 401fc89 before merge)

- `uv run pytest -q`: 1770 passed
- `MACOS_APPS_READ_ONLY=1 uv run pytest -q`: 1761 passed, 0 failed, 9 skipped
- `MACOS_APPS_ALLOW_SEND=mail uv run pytest -q`: 1766 passed, 0 failed, 4 skipped
- `uv run ruff check .`: no issues
- `uv run ruff format --check .`: 107 files already formatted
- Integration test collected only: `uv run pytest tests/integration/test_eventkit_depth.py --collect-only -q -m integration` lists `test_reminders_read_carries_the_store_plane` (12 collected). No device run (03-09/03-10).
- `origin/develop` holds `reminders_store.py` (`_FINGERPRINT` count 2) and the CHANGELOG line `Breaking: \`reminders()\` returns` (count 1).

## Code review (both axes inline; no sub-agents available)

**Standards** (CLAUDE.md, .claude/CLAUDE.md, baseline smells): follows the sidecar precedent, qualified native seam rule not touched (`test_native_seam.py` passes), docstrings name permissions, errors typed, logging unchanged, `from __future__ import annotations` present. One judgement call, kept: `_reminder_pointer(item, *, tags, parent)` has no production caller passing them (the plan names the signature; `read()` uses `dataclasses.replace`) — possible Speculative Generality. Open issue found and fixed: `store_path` let a non-permission, non-missing `OSError` (for example `NotADirectoryError`) escape raw, which would hide the EventKit plane (fixed in `8135932`).

**Spec** (plan 03-06, REM-03, REM-04, D-13..D-16): all ten truths met. D-13 route, fingerprint, `Z_ENT` by name, no fallback. D-14 only `reminders.py` imports the sidecar; `store_path()` patched by tests. D-15 envelope, permission pair, no separate tools. Pitfall 5 `os.scandir`. D-16 docstrings, no write route. Truth 9 (store lag after an indent) is a backstop: the read mirrors the store and invents no link. No scope creep found.

Result: no open issue after `8135932`.

## Decisions Made

- Followed the plan. One addition inside it: `store_path` also maps any other `OSError` to `NativeError` (review).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Raw OSError escaped store_path**
- **Found during:** Task 3 code review
- **Issue:** `os.scandir` on a path that is not a directory raised `NotADirectoryError`, which is not a `NativeError`, so `read()` would raise and hide the EventKit pointers.
- **Fix:** `except OSError` maps to `NativeError` ("could not be listed"); test added.
- **Files modified:** macos_apps_mcp/adapters/reminders_store.py, tests/test_reminders_store.py
- **Commit:** `8135932` [401fc89]

**2. [Rule 3 - Blocking] Test placement of two behaviours**
- The plan lists the tag-sanitising and `store_path` cases under Task 2; they test code written in Task 1, so they were written with the Task 1 RED (sanitising) or pass on arrival (`store_path` characterisation). No behaviour is missing.

**Total deviations:** 1 auto-fixed bug, 1 placement note. **Impact:** none on scope.

## Issues Encountered

None.

## Known Stubs

None.

## Threat Flags

None. T-3-19 to T-3-23 are mitigated as planned: `clean_summary` on every tag, constant SQL, `coverage` on failure, `os.scandir` for the denial, `_FINGERPRINT` for drift.

## User Setup Required

None. Full Disk Access for the daemon identity is already granted (spike 007); the device check is 03-09.

## Owner summary

reminders() now carries tags and parent links (read-only); returns {results, coverage?} — PR #277. The life-cockpit caller must read `results`.

## Next Phase Readiness

03-07 adds `subtasks_of` and 03-08 completes parents on this module. The module surface is as the plan names it: `store_path`, `_FINGERPRINT`, `_TAGS`, `_PARENTS`, `tags_and_parents`. Both plans can add their query beside `_PARENTS` and reuse `_make_reminders_store`.

## Self-Check: PASSED

- `reminders_store.py` and `tests/test_reminders_store.py` exist on `origin/develop`.
- All six commits are ancestors of `origin/develop` (rebased as `341a78e`, `4040438`, `6e0672b`, `269cd7c`, `7bccc15`, `8135932`).
- PR #277 state MERGED.

---
*Phase: 03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub*
*Completed: 2026-10-06*
