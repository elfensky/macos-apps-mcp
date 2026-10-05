---
phase: 03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub
plan: 02
subsystem: eventkit
tags: [eventkit, pointer, folder, reminders, calendar, create-list]

requires:
  - phase: 03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub
    provides: "03-01 probe 1: a list save works on the default reminders source; Google refuses with EKErrorDomain 24 (int)"
provides:
  - "Event and reminder Pointers carry folder = calendar or list identifier"
  - "create_reminder_list(name) on the default reminders account (additive tier)"
  - "tests/integration/test_eventkit_depth.py: Phase 3 device-test module (ek_items, icloud_scratch)"
affects: [03-03, 03-04, 03-05, 03-06, 03-07, 03-09, 03-10]

actuals:
  tokens: 7000
  tasks: 3
  commits: 5
plan_head_before: 56b9fa35a191df054a9e94d61f0dfc38e4e26f7c
plan_head_after: de48332c7040fed1599a2babbb6a69ba71951ead

tech-stack:
  added: []
  patterns: ["container id read through eventkit.container_id in the one Pointer builder per adapter", "scan + save + verify inside one run_native block"]

key-files:
  created: [tests/integration/test_eventkit_depth.py]
  modified:
    - macos_apps_mcp/contracts.py
    - macos_apps_mcp/adapters/calendar.py
    - macos_apps_mcp/adapters/reminders.py
    - macos_apps_mcp/server.py
    - tests/test_calendar.py
    - tests/test_reminders.py
    - tests/test_registry.py
    - tests/test_tool_annotations.py
    - README.md
    - CHANGELOG.md

key-decisions:
  - "folder = raw calendarIdentifier/list identifier, omitted when the item has no container"
  - "create_reminder_list has no account parameter; the list takes the default list's source"
  - "EK errors 17 and 24 map to WriteRefused naming the source; 24 cited as measured in 03-01"

requirements-completed: [CAL-04, REM-06, REM-02]

coverage:
  - id: D1
    description: "events() and reminders() Pointers carry the owning calendar or list id in folder; the id is accepted back by free_busy"
    requirement: CAL-04
    verification:
      - kind: unit
        ref: "tests/test_calendar.py#test_get_pointers_folder_round_trips_into_free_busy"
        status: pass
      - kind: unit
        ref: "tests/test_reminders.py#test_reminder_pointer_folder_is_the_list_identifier"
        status: pass
    human_judgment: false
  - id: D2
    description: "create_reminder_list creates a list on the default account, refuses duplicates and bad names, maps 17/24, verifies by id"
    requirement: REM-02
    verification:
      - kind: unit
        ref: "tests/test_reminders.py -k reminder_list (15 passed)"
        status: pass
      - kind: unit
        ref: "tests/test_registry.py#test_tier_reproduces_the_develop_era_additive_and_destructive_sets"
        status: pass
    human_judgment: false
  - id: D3
    description: "Real EventKit behaviour of the list create and the folder round trip on this Mac"
    verification: []
    human_judgment: true
    rationale: "Device tests are collected only here; the device run is plan 03-09"

duration: about 30 min
completed: 2026-10-06
status: complete
---

# Phase 3 Plan 02: Container ids and create_reminder_list Summary

**Event and reminder Pointers now carry their calendar or list identifier in `folder`, and `create_reminder_list(name)` creates a list on the default Reminders account with duplicate, bad-name and refusing-source guards.**

Container ids and create_reminder_list landed — PR #272 (rebase-merged, c068cfc); the device run is plan 03-09.

## Performance

- **Duration:** about 30 min
- **Tasks:** 3
- **Files modified:** 11 (1 created)
- **PR:** #272, rebase-merged into `develop`, merge commit `c068cfc`

## Accomplishments

- `_event_pointer` and `_reminder_pointer` set `folder = container_id(item)`. Snapshots, the `delete_event` dry-run preview and every create/update return follow, because they build through these two functions.
- `create_reminder_list(name)`: `@_additive_tool`, audit verb `create`, permission EventKit, absent under `MACOS_APPS_READ_ONLY=1`. Exact-name duplicate raises `ValueError` naming the existing id before any save. Empty, whitespace-only and Cc-category names raise before any native call. A missing default list and errors 17 and 24 raise `WriteRefused`; other failures go through `refused_write`. The new id is verified in the store. Scan, save and verify share one `run_native` block.
- Phase 3 device-test module with `ek_items` and `icloud_scratch` fixtures and two device tests (collected only: 2 tests).
- README tool table, `folder` sentence and CHANGELOG entries.

## Task Commits

Merged commits on `develop` (rebased; the lane hashes are in brackets):

1. **Task 1 RED** - `b411bcd` [dd78521] test(03-02): event and reminder pointers carry their container id (#207)
2. **Task 1 GREEN** - `2a355c5` [b3109c0] feat(03-02): events and reminders carry their calendar or list id in folder (#207)
3. **Task 2 RED** - `580a34e` [a4f2fdf] test(03-02): create_reminder_list contract (#92)
4. **Task 2 GREEN** - `a9dc230` [d63ad90] feat(03-02): create_reminder_list on the default account (#92)
5. **Task 3** - `c068cfc` [de48332] test(03-02): Phase 3 device-test module; docs for folder and create_reminder_list

### TDD record

- **RED (Task 1):** five `folder` tests failed on the planned assertion (`KeyError: 'folder'` / `None != 'L-1'`); the omitted-folder tests passed already because that is today's behaviour. Semantic assessment: the target tests ran and failed for the intended reason.
- **RED (Task 2):** 15 `create_reminder_list` tests and the three registry/annotation pins failed with `AttributeError: 'RemindersAdapter' object has no attribute 'create_reminder_list'` (the method did not exist), not on a collection or fixture fault.
- **GREEN:** both passed after the implementation commits. No REFACTOR commit was needed.

## Test counts (`^def test_`, before -> after)

| File | Before | After |
|---|---|---|
| tests/test_calendar.py | 48 | 53 |
| tests/test_reminders.py | 33 | 49 |
| tests/test_registry.py | 17 | 17 |
| tests/test_tool_annotations.py | 7 | 7 |

No count dropped. Parametrized tests count once in this measure.

## Verification (lane, before the push)

- `uv run pytest -q`: 1563 passed, 82 deselected
- `MACOS_APPS_READ_ONLY=1 uv run pytest -q`: 1554 passed, 9 skipped, 82 deselected
- `MACOS_APPS_ALLOW_SEND=mail uv run pytest -q`: 1559 passed, 4 skipped, 82 deselected
- `uv run ruff check .`: All checks passed!
- `uv run ruff format --check .`: 105 files already formatted
- Acceptance: registry check printed `ok` (additive, verb `create`, permission `('EventKit',)`); read-only check printed `absent`; `-k folder` 10 passed; `-k reminder_list` 15 passed; `grep -c "folder=container_id("` is 1 in each adapter; `grep -c "None elsewhere"` is 0; error-mapping comment cites 03-01 probe 1.
- CI: required `check` passed on PR #272 (1m7s) before the merge.

## Code review

The `code-review` skill needs sub-agents that this run cannot spawn, so both axes ran inline over `origin/develop...HEAD`.

- **Standards** (CLAUDE.md, .claude/CLAUDE.md): tools are one-line dispatch; all EventKit access is inside `run_native`; the write tool uses `@_additive_tool` and names EventKit in its docstring; `from __future__` and ruff rules hold; no cross-adapter import; no real titles, ids or account names in code, tests, commits or the PR. No issue.
- **Spec** (this plan, CAL-04, REM-06, REM-02, D-12, D-22): every must-have truth maps to a test (folder set / omitted / raw / per-list / fetch order; duplicate, case-differing name, bad names, 17 / 24 / other, missing default, verify, idempotency, single `run_native`). The PR body says "Refs #207, #92". No issue.
- **Result:** no open issue; no review-fix commit needed.

## Decisions Made

None beyond the plan. The `Pointer.folder` comment now names the calendar or list identifier for EventKit reads.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `_fake_persisted_event` needed no `calendar_id=` keyword**
- **Found during:** Task 1 (RED)
- **Issue:** The plan asked for a `calendar_id=` keyword on `_fake_persisted_event`. That fake already returns a `calendar()` through its existing `cal_id=` keyword, so a second keyword would duplicate it.
- **Fix:** Left it unchanged. `_fake_event` and `_fake_event_full` (which the `delete_event` tests build through `_event_pointer`) gained `calendar_id=`; `_fake_reminder` gained it too.
- **Files modified:** tests/test_calendar.py, tests/test_reminders.py

**2. [Rule 1 - Bug] Task 1 tracer test fake lacked `availability()`**
- **Found during:** Task 1 (GREEN run)
- **Issue:** `get_free_busy` calls `availability()` on each event; the new round-trip test's fake had none.
- **Fix:** The test sets `availability` to `EKEventAvailabilityBusy`.
- **Committed in:** b3109c0 (Task 1 GREEN)

**3. Commit scope** - commits use `{type}(03-02)` as the executor protocol requires, not the `(eventkit)` / `(reminders)` scopes written in the plan text.

**Total deviations:** 3 (1 blocking-minor, 1 test-fake bug, 1 naming). **Impact:** none on behaviour or scope.

## Issues Encountered

None. The first `ruff check` run flagged two over-long docstring lines in `server.py` and one in the new integration module; fixed before the commits.

## Authentication Gates

None.

## Known Stubs

None.

## Threat Flags

None. `folder` exposes only the opaque identifier that `calendars` and `reminder_lists` already return (T-3-07, accepted). The mitigations for T-3-04, T-3-05 and T-3-06 are in code and tests.

## Next Phase Readiness

- 03-03..03-07 extend `tests/integration/test_eventkit_depth.py` (`PREFIX`, `ek_items`, `icloud_scratch`).
- 03-09 runs the two new device tests after the owner says go. 03-10 closes #207 and #92 after the device proof.
- The installed daemon does not change until the `.app` is rebuilt and reinstalled.
- Lane `.worktrees/ek-containers` removed and branch `feat/ek-containers` deleted; the main checkout was not edited.

## Self-Check: PASSED

- `origin/develop` holds `def create_reminder_list` (1), `def ek_items`, `def icloud_scratch`, and `create_reminder_list` in CHANGELOG.md.
- Commits `b411bcd`, `2a355c5`, `580a34e`, `a9dc230`, `c068cfc` are on `origin/develop`.
- `test ! -e .worktrees/ek-containers` succeeds.

---
*Phase: 03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub*
*Completed: 2026-10-06*
