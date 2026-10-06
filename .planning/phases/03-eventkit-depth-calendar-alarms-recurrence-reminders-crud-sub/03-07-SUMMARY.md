---
phase: 03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub
plan: 07
subsystem: reminders
tags: [reminders, delete, dry-run, subtasks, cascade, audit, sqlite, destructive]

requires:
  - phase: 03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub
    provides: "03-06 reminders_store (store_path, _FINGERPRINT, tags_and_parents) and Pointer.tags/parent; spike 007 cascade facts"
provides:
  - "RemindersAdapter.delete_reminder(ident, *, dry_run=True, with_subtasks=False) -> deletion_result envelope"
  - "reminders.ReminderDeleteSnapshotter (own audit before-state source; attaches the store's subtasks)"
  - "reminders_store._SUBTASKS_OF and subtasks_of(parent_id) -> list[str] (bound ? parameter, live rows only)"
  - "errors.SubtasksRequired (kind subtasks_required)"
  - "contracts.Pointer.subtasks; deletion_result(..., subtasks=) with the cascade note"
  - "MCP tool delete_reminder(id, dry_run=True, with_subtasks=False), permission (EventKit, Full Disk Access)"
  - "device tests test_delete_reminder_is_gone_on_device and test_cascade_delete_with_subtasks (cascade_fixture, env MACOS_APPS_IT_CASCADE_FIXTURE)"
affects: [03-08 complete_reminder open-subtask report and delete_event gone-check, 03-09 device sweep, 03-10 cascade device run]

actuals:
  tokens: 10560
  tasks: 3
  commits: 6
plan_head_before: 8135932d8eb94728cc67a6f165f63bf6f1baefdb
plan_head_after: 3a5eb0429e2121d9b2db09b33f9b4747bdf1698e

tech-stack:
  added: []
  patterns:
    - "destructive id-addressed write with its own snapshotter when the before-state needs a read plane the shared snapshot must not touch"
    - "store read, refusal check, remove and gone-checks in ONE run_native block; the dry run runs every refusal the real call would"
    - "a refusal that confirms with a flag (SubtasksRequired / with_subtasks) in the SpanRequired shape"

key-files:
  created: []
  modified:
    - macos_apps_mcp/adapters/reminders.py
    - macos_apps_mcp/adapters/reminders_store.py
    - macos_apps_mcp/contracts.py
    - macos_apps_mcp/errors.py
    - macos_apps_mcp/server.py
    - tests/test_reminders.py
    - tests/test_reminders_store.py
    - tests/test_contracts.py
    - tests/test_server.py
    - tests/test_registry.py
    - tests/test_audit_middleware.py
    - tests/integration/test_eventkit_depth.py
    - README.md
    - CHANGELOG.md

key-decisions:
  - "The subtask read happens before any remove and before the dry-run branch; an unreadable store raises WriteRefused ('No change was made') and no remove call happens"
  - "A subtask the store lists but EventKit cannot fetch stays in the count as a placeholder Pointer (summary '(subtask not visible to EventKit)')"
  - "ReminderDeleteSnapshotter reads the store; a store error propagates so the audit layer logs before=None, while the delete itself refuses anyway"
  - "An id whose item has no isCompleted (an event) is refused with ValueError before any remove"

patterns-established:
  - "Dry-run parity: a preview raises the same typed refusals as the real call (SubtasksRequired, WriteRefused)"
  - "Gone-check on the parent and on every subtask after the remove; VerificationFailed names the survivor"

requirements-completed: [REM-01, REM-03]

coverage:
  - id: D1
    description: "delete_reminder(id) defaults dry_run=True, is destructive with audit verb delete, sits in the removes-content class with permission (EventKit, Full Disk Access), and is absent under MACOS_APPS_READ_ONLY"
    requirement: REM-01
    verification:
      - kind: unit
        ref: "tests/test_registry.py#test_delete_reminder_registration_record"
        status: pass
      - kind: unit
        ref: "tests/test_registry.py#test_content_removing_tools_default_to_dry_run"
        status: pass
      - kind: unit
        ref: "tests/test_server.py#test_delete_reminder_dispatches_with_the_dry_run_default"
        status: pass
    human_judgment: false
  - id: D2
    description: "A real delete re-fetches the parent (and each subtask) and never reports deleted for a reminder that is still there; an event id is refused; a second real delete errors"
    requirement: REM-01
    verification:
      - kind: unit
        ref: "tests/test_reminders.py#test_delete_reminder_still_there_after_the_remove_is_not_reported_deleted"
        status: pass
      - kind: unit
        ref: "tests/test_reminders.py#test_a_subtask_that_is_still_there_after_the_delete_is_named"
        status: pass
      - kind: unit
        ref: "tests/test_reminders.py#test_delete_reminder_never_removes_a_calendar_event"
        status: pass
      - kind: unit
        ref: "tests/test_reminders.py#test_second_real_delete_of_the_same_id_is_an_error_not_a_second_success"
        status: pass
    human_judgment: false
  - id: D3
    description: "An unreadable Reminders store refuses the delete (dry run included) with no remove call; a parent with subtasks is refused unless with_subtasks=True, in the dry run too"
    requirement: REM-03
    verification:
      - kind: unit
        ref: "tests/test_reminders.py#test_delete_reminder_with_an_unreadable_store_refuses_and_changes_nothing"
        status: pass
      - kind: unit
        ref: "tests/test_reminders.py#test_a_parent_with_subtasks_is_refused_unless_confirmed"
        status: pass
      - kind: unit
        ref: "tests/test_reminders_store.py#test_subtasks_of_lists_live_children_of_a_live_parent"
        status: pass
    human_judgment: false
  - id: D4
    description: "The confirmed preview and the confirmation name every subtask and a cascade note; the audit before-state records the parent and all subtasks; the shared snapshot stays store-free"
    requirement: REM-03
    verification:
      - kind: unit
        ref: "tests/test_reminders.py#test_confirmed_delete_names_every_removed_reminder"
        status: pass
      - kind: unit
        ref: "tests/test_reminders.py#test_the_audit_before_state_records_all_the_reminders_a_delete_removes"
        status: pass
      - kind: unit
        ref: "tests/test_reminders.py#test_the_shared_snapshot_makes_no_store_read"
        status: pass
    human_judgment: false
  - id: D5
    description: "The real cascade on an owner-built subtask fixture (the delete takes N+1 reminders, the store agrees, the audit log keeps all of them) and the plain device delete"
    requirement: REM-01
    verification:
      - kind: integration
        ref: "tests/integration/test_eventkit_depth.py#test_delete_reminder_is_gone_on_device"
        status: unknown
      - kind: integration
        ref: "tests/integration/test_eventkit_depth.py#test_cascade_delete_with_subtasks"
        status: unknown
    human_judgment: true
    rationale: "Device proof is owned by 03-09 (plain delete) and 03-10 (cascade on the owner-built fixture); the tests are collected here, not run"

duration: 23min
completed: 2026-10-06
status: complete
---

# Phase 3 Plan 07: delete_reminder Summary

**`delete_reminder(id, dry_run=True, with_subtasks=False)` deletes by id, reads the Reminders store for subtasks before any remove, refuses a parent with subtasks unless confirmed, proves the parent and every subtask gone, and keeps all N+1 in the audit before-state**

delete_reminder landed: dry-run default, gone-check, subtasks refused unless confirmed — PR #278

## Performance

- **Duration:** about 23 min
- **Started:** about 2026-10-06T08:40Z (approximate; no start stamp was captured)
- **Completed:** 2026-10-06T09:03Z
- **Tasks:** 3
- **Files modified:** 14 (731 insertions, 8 deletions on develop)

## Accomplishments

- `delete_reminder` mirrors `delete_event`: `@_write_tool` with its own snapshotter, audit verb `delete`, removes-content class, `dry_run=True` default pinned by the registry test, absent under `MACOS_APPS_READ_ONLY`.
- Order inside one `run_native` block: fetch by id, refuse an event, read subtasks from the store (unreadable store gives `WriteRefused`, "No change was made"), refuse an unconfirmed parent (`SubtasksRequired`, dry run too), then dry-run preview or remove plus gone-checks. No path removes before the subtask read.
- Confirmed preview and confirmation carry the subtasks and a `cascade` note; a store-listed subtask EventKit cannot fetch stays in the count as a placeholder.
- `ReminderDeleteSnapshotter` attaches the store's subtasks to the audit before-state; the shared `RemindersAdapter.snapshot` is unchanged and store-free.
- Device tests collected: plain delete and the cascade test (skips unless `MACOS_APPS_IT_CASCADE_FIXTURE` is set).

## Task Commits

Commits on develop (rebase-merged, PR #278, merge tip `3a5eb04`):

1. **Task 1: tracer, delete_reminder without subtasks** - RED `f4a9a45` (test), GREEN `5c1c7aa` (feat)
2. **Task 2: subtask guard** - RED `d18faf6` (test), GREEN `d4c0904` (feat)
3. **Task 3: device tests and docs** - `cbb2979` (test)
4. **Code review fix** - `3a5eb04` (refactor: the snapshotter reads the EventKit store once)

**Plan metadata:** not committed here (records lane, orchestrator-owned).

## TDD Gate Compliance

RED and GREEN commits exist in order for both TDD tasks (Task 1: `f4a9a45` then `5c1c7aa`; Task 2: `d18faf6` then `d4c0904`).

- **RED, Task 1:** 18 tests failed before the code: `AttributeError: 'RemindersAdapter' object has no attribute 'delete_reminder'`, `ImportError` for `ReminderDeleteSnapshotter`, registry pin mismatches, `srv.delete_reminder` missing. semanticAssessment: each target test executed and failed on the planned missing behavior, no load or fixture fault. The `gsd_run check tdd-red-evidence` classifier was not run: pytest console output is not one of its supported report formats (TAP, JUnit, swift-testing, unittest), so the assessment is by inspection of the failure reasons.
- **RED, Task 2:** 11 tests failed: `ImportError: cannot import name 'SubtasksRequired'`, `TypeError ... unexpected keyword argument 'subtasks'` (Pointer, deletion_result), `KeyError: 'subtasks'`, `DID NOT RAISE VerificationFailed`. Same semantic assessment. Two tests that assert behavior already true (shared snapshot store-free, no-subtask delete shape) passed from the start by design.
- **GREEN:** full suite green after each GREEN commit. No REFACTOR commit beyond the review fix.

Test-function counts (`^def test_`), before to after:

| File | Before | After |
|---|---|---|
| tests/test_reminders.py | 58 | 76 |
| tests/test_reminders_store.py | 10 | 13 |
| tests/test_contracts.py | 58 | 61 |
| tests/test_server.py | 87 | 88 |
| tests/test_registry.py | 17 | 18 |
| tests/test_audit_middleware.py | 9 | 9 |
| tests/integration/test_eventkit_depth.py | 8 | 10 |

## Files Created/Modified

- `macos_apps_mcp/adapters/reminders.py` - `delete_reminder`, `ReminderDeleteSnapshotter`, `_subtask_pointers`, `_is_reminder`
- `macos_apps_mcp/adapters/reminders_store.py` - `_SUBTASKS_OF`, `subtasks_of`
- `macos_apps_mcp/contracts.py` - `Pointer.subtasks`, `deletion_result(..., subtasks=)` with `cascade`
- `macos_apps_mcp/errors.py` - `SubtasksRequired`
- `macos_apps_mcp/server.py` - `delete_reminder` tool, `_reminder_delete_snapshot`
- `tests/*` - unit tests, registry pins, audit-through-client test; `tests/integration/test_eventkit_depth.py` - device tests
- `README.md`, `CHANGELOG.md` - tool table row and Unreleased entry

## Decisions Made

See `key-decisions` above. The plan's D-17..D-20 were followed as written.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] An existing pin listed the snapshot sources without the new tool**
- **Found during:** Task 1 (full suite after GREEN)
- **Issue:** `tests/test_audit_middleware.py::test_server_snapshot_sources_are_derived_and_satisfy_the_protocol` hard-codes the set of tools with a snapshotter; it failed once `delete_reminder` registered its own.
- **Fix:** added `delete_reminder` to the expected set. The file was not in the plan's `files_modified`.
- **Files modified:** tests/test_audit_middleware.py
- **Verification:** full suite green in all three modes
- **Committed in:** `5c1c7aa`

**2. [Rule 1 - Bug] A unit test could reach the real Reminders store**
- **Found during:** Task 2 (after the snapshotter began reading the store)
- **Issue:** the Task 1 snapshotter test patched the EventKit store but not `store_path`; once the snapshotter read subtasks it would have opened the owner's real store.
- **Fix:** the test now builds a fixture store through `_wire_delete`. No other unit test calls `subtasks_of` unpatched.
- **Files modified:** tests/test_reminders.py
- **Committed in:** `d4c0904`

**3. [Rule 1 - Bug] The audit-through-client test failed under MACOS_APPS_READ_ONLY=1**
- **Found during:** Task 2 (read-only suite run)
- **Issue:** the write tool is absent in that mode, so the client call raised `Unknown tool`.
- **Fix:** `skipif(tiers.read_only())`, the repo's existing pattern.
- **Files modified:** tests/test_reminders.py
- **Committed in:** `d4c0904`

---

**Total deviations:** 3 auto-fixed (3 Rule 1, all test-side). **Impact:** none on the production contract.

## Code Review (inline, both axes plus a destructive-path pass)

The `code-review` skill needs parallel sub-agents, which this run cannot spawn; both axes were done inline over `origin/develop...HEAD`.

- **Standards** (CLAUDE.md, .claude/CLAUDE.md): tool layer is one line to the adapter; adapter reaches the store through a sidecar, with no cross-adapter import; qualified `reminders_store.subtasks_of` call; the docstring names both grants (`test_tool_annotations` passes); `from __future__` present; ruff lint and format clean; no mypy. Smell baseline: one Duplicated Code hit (the snapshotter called `store()` twice), fixed in `3a5eb04`. No other finding.
- **Spec** (03-07-PLAN.md, REM-01, D-17..D-20): every truth implemented and pinned by a test; the message wording matches CONTEXT ("N subtasks (summary [id], ...) ... Call again with `with_subtasks=True`. No change was made."); the one-parent query uses a bound `?`; the shared snapshot is untouched. No missing requirement, no scope creep. The plan said "(subtask check)" `Pointer.subtasks` is reused by 03-08 as written.
- **Destructive-path pass:** (1) dry run: reads the store and raises both refusals, makes no remove call (tests assert `world.removed == []`). (2) Order: lookup, event refusal, store read, refusal, dry-run return, remove: nothing removes before the subtask read. (3) Unreadable store: `WriteRefused`, no remove, dry run included. (4) Confirmation: `with_subtasks` is only consulted when subtasks exist; `deleted` is returned only after the parent and each subtask re-fetch as gone. (5) Audit: the before-state is a separate worker turn from the delete, so a subtask indented in between would be missing from the log but still caught by the delete's own store read and refusal; accepted and stated in the docstring. (6) Event ids are refused by the `isCompleted` check. Residual, by design: a subtask indented in Reminders minutes earlier may not be in the store yet (spike 007).
- **Result:** no open issue.

## Verification

- `uv run pytest -q`: 1798 passed, 94 deselected
- `MACOS_APPS_READ_ONLY=1 uv run pytest -q`: 1788 passed, 10 skipped, 94 deselected
- `MACOS_APPS_ALLOW_SEND=mail uv run pytest -q`: 1794 passed, 4 skipped, 94 deselected
- `uv run ruff check .`: All checks passed
- `uv run ruff format --check .`: 107 files already formatted
- CI `check` on PR #278: pass (1m18s); merged with the rebase method
- Device tests: `--collect-only -m integration` lists both new tests; not run (03-09/03-10 after the owner says go)

## Issues Encountered

None. Landing: PR #278, merge commit `3a5eb0429e2121d9b2db09b33f9b4747bdf1698e`; the code lane `.worktrees/rem-delete` and branch `feat/rem-delete` were removed. Vault journal entry written (MR 1044).

## Known Stubs

None.

## Threat Flags

None beyond the plan's register: T-3-24..T-3-29 are mitigated as listed (SubtasksRequired in both modes, WriteRefused on an unreadable store, own snapshotter, gone-checks, reminder-only check, tier gating).

## User Setup Required

None - no external service configuration required. The cascade device test needs the owner-built fixture (`MACOS_APPS_IT_CASCADE_FIXTURE`, built in 03-09).

## Next Phase Readiness

- 03-08 can import `reminders_store.subtasks_of`, `Pointer.subtasks`, `_subtask_pointers` and reuse the D-18 refusal wording; it adds the gone-check to `delete_event` and the open-subtask report to `complete_reminder`.
- 03-09 runs the plain device delete; 03-10 runs the cascade after the owner builds the fixture (JSON keys `list_id`, `list_title`, `p1`, `children`, `p2`, `d1`, `tag`).

## Self-Check: PASSED

- Files exist on origin/develop (`macos_apps_mcp/adapters/reminders.py`, `reminders_store.py`, `contracts.py`, `errors.py`, `server.py`, the tests): verified through the merge.
- Commits `f4a9a45`, `5c1c7aa`, `d18faf6`, `d4c0904`, `cbb2979`, `3a5eb04` are on origin/develop (`git log origin/develop`).

---
*Phase: 03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub*
*Completed: 2026-10-06*
