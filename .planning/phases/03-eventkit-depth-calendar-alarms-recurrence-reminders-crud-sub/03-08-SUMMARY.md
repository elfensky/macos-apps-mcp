---
phase: 03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub
plan: 08
subsystem: eventkit
tags: [reminders, calendar, eventkit, subtasks, verify-after-write, fastmcp]

requires:
  - phase: 03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub
    provides: "03-07: reminders_store.subtasks_of, Pointer.subtasks, _subtask_pointers, delete_reminder D-18 refusal"
provides:
  - "complete_reminder returns a dict; a parent's open subtasks are listed under `subtasks`"
  - "complete_reminder refuses (WriteRefused, no save) when the Reminders store is unreadable"
  - "delete_event gone-check: occurrence-aware re-resolve after the remove"
  - "device tests test_delete_event_is_gone_on_device and test_cascade_complete_reports_open_subtasks (collected only)"
affects: [03-09, 03-10]

actuals:
  tokens: 14000
  tasks: 2
  commits: 6

tech-stack:
  added: []
  patterns:
    - "store read first, inside the one run_native block, before any write (D-18 order, now shared by delete and complete)"
    - "gone-check by re-resolving the occurrence id, never the base id (Pitfall 6)"

key-files:
  created: []
  modified:
    - macos_apps_mcp/adapters/reminders.py
    - macos_apps_mcp/adapters/calendar.py
    - macos_apps_mcp/server.py
    - tests/test_reminders.py
    - tests/test_calendar.py
    - tests/test_registry.py
    - tests/test_server.py
    - tests/test_integration.py
    - tests/integration/test_eventkit_depth.py
    - README.md
    - CHANGELOG.md

key-decisions:
  - "Per the owner override of A9 (2026-10-06): an unreadable Reminders store refuses complete_reminder; there is no coverage fallback"
  - "complete_reminder refuses a calendar event id (reminder-only guard, as delete_reminder has) before the store read and any write"
  - "A subtask EventKit cannot fetch counts as open in the report (Pitfall 7), rendered as a placeholder Pointer"
  - "The shared RemindersAdapter.snapshot stays store-free; complete_reminder's audit before-state is unchanged"

patterns-established:
  - "A write that needs the store to be safe names Full Disk Access in its permission tuple and docstring"

requirements-completed: [REM-01, REM-03]

coverage:
  - id: D1
    description: "complete_reminder on a parent returns its open subtasks under `subtasks`, over the FastMCP client without output-validation error"
    requirement: REM-03
    verification:
      - kind: unit
        ref: "tests/test_reminders.py#test_complete_reminder_over_the_client_lists_the_open_subtask"
        status: pass
      - kind: unit
        ref: "tests/test_reminders.py#test_complete_reminder_leaves_the_subtasks_open"
        status: pass
    human_judgment: false
  - id: D2
    description: "an unreadable store refuses the completion before any save"
    requirement: REM-03
    verification:
      - kind: unit
        ref: "tests/test_reminders.py#test_complete_reminder_with_an_unreadable_store_refuses_before_any_save"
        status: pass
    human_judgment: false
  - id: D3
    description: "delete_event proves the occurrence is gone, occurrence-aware"
    requirement: REM-01
    verification:
      - kind: unit
        ref: "tests/test_calendar.py#test_delete_event_that_still_resolves_after_the_remove_is_not_reported_deleted"
        status: pass
      - kind: unit
        ref: "tests/test_calendar.py#test_delete_event_this_event_passes_while_the_series_master_lives_on"
        status: pass
    human_judgment: false
  - id: D4
    description: "on device, event deletes (single, this-event, future-events) leave the expected occurrences; the parent completion lists d1 open"
    requirement: REM-01
    verification:
      - kind: integration
        ref: "tests/integration/test_eventkit_depth.py#test_delete_event_is_gone_on_device"
        status: unknown
      - kind: integration
        ref: "tests/integration/test_eventkit_depth.py#test_cascade_complete_reports_open_subtasks"
        status: unknown
    human_judgment: true
    rationale: "Device tests are collected only in this plan; 03-09 and 03-10 run them after the owner says go."

duration: 45min
completed: 2026-10-06
status: complete
plan_head_before: 3a5eb0429e2121d9b2db09b33f9b4747bdf1698e
plan_head_after: 57f98021c67155b0f84423d478142f5788516e44
commits: 6
---

# Phase 3 Plan 08: complete_reminder open-subtask report and delete_event gone-check Summary

**complete_reminder lists a parent's open subtasks and refuses when the Reminders store is unreadable; delete_event now proves the occurrence is gone**

complete_reminder reports open subtasks (refuses, changing nothing, when the store is unreadable); delete_event proves the event is gone — PR #279

## Performance

- **Duration:** about 45 min
- **Tasks:** 2 (tracer + auto, both TDD)
- **Files modified:** 11
- **PR:** #279, rebase-merged into develop, merge head `dc44c962c2a4570a2c30bcc3eaf94ae07a553710`

## Accomplishments

- `RemindersAdapter.complete_reminder` returns a dict. It reads `reminders_store.subtasks_of(id)` first in the same `run_native` block. An unreadable store raises `WriteRefused` ("complete_reminder refused: … No change was made.") and the fakes record no save. After the verified completion, children not completed (or not fetchable by EventKit) are listed under `subtasks`; no key when none are open.
- The MCP tool `complete_reminder` is annotated `-> dict`, permission `("EventKit", "Full Disk Access")`, docstring names both; registry pin and `removes_content` unchanged (not a removal tool).
- `CalendarAdapter.delete_event` re-resolves the occurrence id after the remove; a return means `VerificationFailed` ("still resolves after the delete"), `ValueError` means gone. A this-event delete with the master alive passes. A dry run is untouched.
- Device tests collected (not run): `test_delete_event_is_gone_on_device`, `test_cascade_complete_reports_open_subtasks`. README and CHANGELOG updated.

## Task Commits

Commits on develop after the rebase merge (lane hashes in the frontmatter range):

1. **Task 1 RED:** `0f268f0` test(03-08): completing a parent reports its open subtasks (#91)
2. **Task 1 GREEN:** `cadf587` feat(03-08): complete_reminder reports a parent's open subtasks (#91)
3. **Task 2 RED:** `a0c7876` test(03-08): delete_event proves the occurrence is gone (#92)
4. **Task 2 GREEN:** `e5b4a43` feat(03-08): delete_event verifies the occurrence is gone (#92)
5. **Task 2 docs and device tests:** `6920c4f` test(03-08): event-delete and parent-completion device tests; docs
6. **Review fix:** `dc44c96` fix(03-08): complete_reminder refuses a calendar event id before any write (review)

## TDD Gate Compliance

RED then GREEN present for both TDD tasks. RED evidence (pytest, targets failed on the planned behavior): Task 1 — `KeyError: 'subtasks'`, `TypeError: 'Pointer' object is not subscriptable` (adapter still returned a Pointer instead of the dict contract), `DID NOT RAISE WriteRefused`, registry permission mismatch. Task 2 — `DID NOT RAISE VerificationFailed` for the still-resolving case; the occurrence-aware and dry-run tests passed before the fix by design (they pin behavior the fix must not break). The gsd `check tdd-red-evidence` classifier was not run; semantic inspection only.

## Decisions Made

See key-decisions. The review fix (event-id guard) mirrors `delete_reminder`; before it, an event id reached `setCompleted_` and raised `AttributeError`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] complete_reminder on a calendar event id**
- **Found during:** code review (after Task 2)
- **Issue:** `calendarItemWithIdentifier_` also resolves event ids; `setCompleted_` then raised `AttributeError` (pre-existing, but now sat behind a store read and the refusal order)
- **Fix:** `_is_reminder` guard, `ValueError` "… not a reminder … Nothing was changed.", before the store read
- **Files modified:** macos_apps_mcp/adapters/reminders.py, tests/test_reminders.py
- **Committed in:** `dc44c96`

**2. [Process] Commit-time branch allow-list**
- The executor's worktree allow-list (`agent-*` branches) does not fit this repo's one-lane rule; only the protected-branch assertion and the pinned-root guard were applied. Commits stayed on `feat/rem-complete-event-gone`.

**Total deviations:** 1 auto-fixed (Rule 1), 1 process note. **Impact:** none on scope.

## Verification (final, in the lane before push)

- `uv run pytest -q`: 1807 passed
- `MACOS_APPS_READ_ONLY=1 uv run pytest -q`: 1796 passed, 0 failed, 11 skipped
- `MACOS_APPS_ALLOW_SEND=mail uv run pytest -q`: 1803 passed, 0 failed, 4 skipped
- `uv run ruff check .`: no issues
- `uv run ruff format --check .`: 107 files already formatted
- CI `check` on PR #279: pass (1m5s)

## Code review

`code-review` skill sub-agents not used; both axes done inline.
- **Standards** (CLAUDE.md, .claude/CLAUDE.md): tool layer is one-line dispatch; adapter owns logic; typed errors; permission keywords in docstring; no cross-adapter import; qualified imports unchanged; no new native call off `run_native`. No open issue.
- **Spec** (this revised plan, REM-01, REM-03, D-17, D-18, D-21): store read precedes the save (test asserts `saved == []` and the item still open); wording matches D-18; completion never touches a child; gone-check re-resolves the occurrence, not the base id; dry run makes no remove and no second lookup. One finding (event-id guard), fixed in `dc44c96`. No open issue.
- Explicit passes: refusal-before-save order — confirmed; delete_event gone-check — confirmed occurrence-aware, with the real-device confirmation left to 03-09.

## Known Stubs

None.

## Issues Encountered

None.

## Threat Flags

None. T-3-30 (delete_event repudiation) and T-3-31 (hidden open subtasks) are mitigated as planned; T-3-32 accepted per the A9 override.

## Next Phase Readiness

03-09 runs `test_delete_event_is_gone_on_device`; 03-10 runs `test_cascade_complete_reports_open_subtasks` on the owner-built fixture. Both need the owner's go. Main checkout needs `git pull --ff-only` (orchestrator).

## Self-Check: PASSED

PR #279 merged (rebase); six `(03-08)` commits on origin/develop; lane removed and branch deleted; main checkout untouched.
