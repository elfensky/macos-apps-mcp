---
phase: 03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub
plan: 09
subsystem: eventkit
tags: [device-sweep, eventkit, calendar, reminders, icloud, google, junit, cascade-fixture]

requires:
  - phase: 03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub
    provides: "03-01..03-08 code and device tests on origin/develop (03-08 included: calendar.py carries 'still resolves after the delete')"
provides:
  - "Device proof, on iCloud and on one named Google calendar, of alarms, recurrence expansion, container ids, list create, reminder BYDAY, the store plane and both delete gone-checks"
  - "Regression proof: the 19 existing EventKit device tests still pass"
  - "The flat cascade fixture (one list, six reminders) and .worktrees/p3-cascade.json in the 03-07 contract shape, waiting for the owner's indent"
affects: [03-10]

actuals:
  tokens: 0
  tasks: 2
  commits: 0
plan_head_before: dc44c962c2a4570a2c30bcc3eaf94ae07a553710
plan_head_after: dc44c962c2a4570a2c30bcc3eaf94ae07a553710

tech-stack:
  added: []
  patterns:
    - "device run in a detached worktree at origin/develop, junit and log files in the git-ignored .worktrees/"
    - "background pytest plus a bounded poll, so a foreground cap can never kill a run and skip its fixture teardowns"

key-files:
  created: []
  modified: []

key-decisions:
  - "The Google target was resolved by source title 'Google' plus the exact owner-named title, with a zero-or-several stop; exactly one calendar matched"
  - "The Google id was held only in a mode-600 git-ignored file read into the environment of the one run, and deleted before return"

patterns-established:
  - "A tracer sweep with no repo change writes no commit; the SUMMARY lives in the records lane"

requirements-completed: []  # CAL-01..CAL-04, REM-01..REM-04, REM-06 stay open: REM-01, REM-03 and REM-04 need 03-10 (cascade, parent and tag values on device) and the owner's indent

coverage:
  - id: D1
    description: "Timed and all-day alarms round trip, and the all-day alarm fires on the right day, on iCloud and Google"
    requirement: "CAL-01"
    verification:
      - kind: integration
        ref: "tests/integration/test_eventkit_depth.py#test_timed_alarms_round_trip[icloud,google]"
        status: pass
      - kind: integration
        ref: "tests/integration/test_eventkit_depth.py#test_all_day_alarms_fire_on_the_right_day[icloud,google]"
        status: pass
      - kind: integration
        ref: "tests/integration/test_eventkit_depth.py#test_all_day_without_alarms_reads_back_empty[icloud,google]"
        status: pass
    human_judgment: false
  - id: D2
    description: "Every accepted recurrence shape reads back over six months equal to the RFC 5545 reference, on iCloud and Google"
    requirement: "CAL-03"
    verification:
      - kind: integration
        ref: "tests/integration/test_eventkit_depth.py#test_recurrence_expansion_matches_rfc5545[icloud,google]"
        status: pass
    human_judgment: false
  - id: D3
    description: "Event Pointers carry their calendar id in folder; reminder list create on the default source; reminder BYDAY round trip; the store plane on the reminders read"
    requirement: "CAL-04"
    verification:
      - kind: integration
        ref: "tests/integration/test_eventkit_depth.py#test_event_pointer_folder_is_its_calendar_id"
        status: pass
      - kind: integration
        ref: "tests/integration/test_eventkit_depth.py#test_create_reminder_list_on_default_source"
        status: pass
      - kind: integration
        ref: "tests/integration/test_eventkit_depth.py#test_reminder_byday_round_trip"
        status: pass
      - kind: integration
        ref: "tests/integration/test_eventkit_depth.py#test_reminders_read_carries_the_store_plane"
        status: pass
    human_judgment: false
  - id: D4
    description: "delete_reminder and delete_event prove the item is gone on device (plain case, no subtasks)"
    requirement: "REM-01"
    verification:
      - kind: integration
        ref: "tests/integration/test_eventkit_depth.py#test_delete_reminder_is_gone_on_device"
        status: pass
      - kind: integration
        ref: "tests/integration/test_eventkit_depth.py#test_delete_event_is_gone_on_device"
        status: pass
    human_judgment: false
  - id: D5
    description: "The flat cascade fixture exists and the owner has indented it; the cascade, parent and tag values are proven on it in 03-10"
    requirement: "REM-04"
    verification: []
    human_judgment: true
    rationale: "An EventKit write cannot make a subtask or a tag and the private API is forbidden (REM-04), so the owner indents by hand; 03-10 proves the values"

duration: 15min
completed: 2026-10-06
status: complete
---

# Phase 3 Plan 09: Phase 3 device sweep Summary

Phase 3 device sweep green on iCloud and the named Google calendar (14 of 14 tests, 0 failed, 0 errors, 0 skipped), EventKit regression green (19 of 19), and the cascade fixture is indented by the owner (answer: "indented", 2026-10-06), ready for 03-10.

The plan stopped at Task 3 (the owner action) as designed; the orchestrator recorded the owner's answer and re-summarized it as `complete`.

## Performance

- **Duration:** about 15 min wall clock (the sweep itself took 12 min 34 s)
- **Started:** 2026-10-06T12:03:06Z
- **Completed (to the checkpoint):** 2026-10-06T12:17Z
- **Tasks:** 3 of 3 done (Task 3 by the owner, by hand)
- **Files modified in the repo:** 0 (no commit; every written file is git-ignored under `.worktrees/`)

## Task 1: owner go (answered through the orchestrator)

Type checkpoint:decision, gate blocking-human. Answer: **"go `<named Google calendar>`"** (2026-10-06). The owner confirmed they are at the Mac and named one existing Google calendar. No family account is a target.

## Task 2: the sweep

**`$BUILT`** = `dc44c962c2a4570a2c30bcc3eaf94ae07a553710` (`origin/develop`, which contains 03-08). Precondition `grep -c "still resolves after the delete"` printed 1. The device tree is `.worktrees/device-3` (detached at `$BUILT`, `uv sync` done) and is kept for 03-10.

**Google target:** resolved by source title "Google" plus the exact owner-named title and writable. Exactly 1 match. The identifier lived in the environment of the one run only.

### Junit totals

| Run | Command selection | tests | failures | errors | skipped | wall |
| --- | --- | --- | --- | --- | --- | --- |
| Phase 3 sweep | `-m integration tests/integration/test_eventkit_depth.py -k "not cascade"` (16 collected, 2 cascade deselected) | 14 | 0 | 0 | 0 | 12 min 34 s |
| EventKit regression | `-m integration tests/test_integration.py -k "reminder or event or calendar or free_busy or all_day or recurring or request_access"` (51 collected, 32 deselected) | 19 | 0 | 0 | 0 | 0.9 s |

Regression ids: the case-insensitive count of `mail|note|contact|safari|music|photo|message|shortcut` in `p3-regress-ids.txt` is **0**.

Verify gates: `device sweep green 14 19`, count `0`, `fixture ready`.

### Phase 3 device tests, result per source

| Test | iCloud | Google | Requirement / decision |
| --- | --- | --- | --- |
| `test_recurrence_expansion_matches_rfc5545` (all 23 shapes, six months, `set(ref) \| {dtstart}`) | PASSED | PASSED | CAL-03, D-23 probe 5, D-24 |
| `test_timed_alarms_round_trip` | PASSED | PASSED | CAL-01 |
| `test_all_day_alarms_fire_on_the_right_day` | PASSED | PASSED | CAL-02, D-23 probe 4 |
| `test_all_day_without_alarms_reads_back_empty` | PASSED | PASSED | CAL-02 |
| `test_event_pointer_folder_is_its_calendar_id` | PASSED | n/a (scratch calendar only) | CAL-04 |
| `test_create_reminder_list_on_default_source` | PASSED | n/a (Google refuses a list, EKErrorDomain 24) | REM-02, REM-06 (folder = list id), D-23 probe 1 |
| `test_reminder_byday_round_trip` | PASSED | n/a | D-23 probe 2 (reminder BY* read back) |
| `test_reminders_read_carries_the_store_plane` | PASSED | n/a | REM-03, REM-04 (store plane present, no `coverage`), D-15 |
| `test_delete_reminder_is_gone_on_device` | PASSED | n/a | REM-01, D-17 (plain case) |
| `test_delete_event_is_gone_on_device` | PASSED | n/a | D-17 (occurrence gone-check, 03-08) |

Not run here by design: `test_cascade_delete_with_subtasks` and `test_cascade_complete_reports_open_subtasks` (deselected by `-k "not cascade"`; 03-10).

No failure occurred, so no diagnostic re-run was used. No finding on `monthly-mixed-byday` or `weekly-bysetpos`: both matched on iCloud and on Google.

### Leftovers

Fixture teardowns asserted removal (Google `left=0`, scratch calendar removed, no prefixed reminder list). A separate read after the fixture build found: prefixed event calendars 0, prefixed events 0, prefixed reminder lists 1 (the cascade fixture list only, which is the intended leftover, removed in 03-10).

### Cascade fixture (D-23 probe 3)

Built through the adapters by `.worktrees/.p3_cascade_fixture.py`: `create_reminder_list`, then six reminders in it. `.worktrees/p3-cascade.json` carries `list_id`, `list_title`, `p1`, `children` (3), `p2`, `d1`, `tag` = `mamcptest` (the 03-07 contract; verify printed `fixture ready`).

- List title: `macos-apps-mcp-test: cascade 141628`
- Reminders: `macos-apps-mcp-test: P1`, `C1`, `C2`, `C3`, `P2`, `D1`

## Task 3: owner indent (done)

Type checkpoint:human-action, gate blocking. **Owner's answer, recorded by the orchestrator: "indented"** (2026-10-06): C1–C3 indented under P1, D1 under P2, tag `mamcptest` on C1, by hand in Reminders.app. The alternative was "skip". With "skip", REM-01's cascade and REM-03/REM-04's on-device values stay unproven and the phase cannot close. 03-10 Task 1 waits (bounded) for C1..C3 to point at P1, D1 at P2 and C1 to carry `mamcptest` before any cascade test runs.

## Accomplishments

- Every Phase 3 device test passed on iCloud and on the named Google calendar in one run, with no re-run.
- The existing EventKit device tests still pass (19 of 19).
- No test item was left behind except the intended cascade fixture list.

## Task Commits

None. The plan changes no tracked file and makes no commit. **Plan metadata:** the SUMMARY is uncommitted in the records lane (orchestrator-owned).

## Files Created/Modified

Repo: none. Git-ignored under `/Users/andrei/Developer/macos-apps-mcp/.worktrees/`: `device-3` (kept), `p3-sweep.xml`, `p3-sweep.log`, `p3-regress-ids.txt`, `p3-regress.xml`, `p3-regress.log`, `.p3_cascade_fixture.py`, `p3-cascade.json` (kept for 03-10), `.p3-09-start` (timestamp helper). The temporary Google id file was deleted.

## Decisions Made

None beyond the plan. The Google id was resolved by source plus exact title and never written to the SUMMARY or a log.

## Deviations from Plan

None - plan executed exactly as written. Two small process notes, neither a deviation: the Google id resolver printed only a match count and wrote the id to a mode-600 file (the orchestrator's rule, instead of printing it); both device pytest runs went to the background with a bounded poll (the orchestrator's rule).

## Issues Encountered

None.

## Known Stubs

None.

## Threat Flags

None. No new network endpoint, auth path or schema; all writes went to `macos-apps-mcp-test:` titled items.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- 03-10 can start after the owner indents the fixture (Task 3). It needs `.worktrees/device-3` at `$BUILT` and `.worktrees/p3-cascade.json`, both kept.
- Open until 03-10: REM-01 cascade, REM-03 parent values and REM-04 tag values on device. The cascade list `macos-apps-mcp-test: cascade 141628` stays in the owner's Reminders until 03-10 removes it.

## Self-Check: PASSED

Junit files, logs, `p3-cascade.json` and `device-3` exist; no commit was made; the main checkout is clean (only the two pre-existing untracked planning files); the Google id file is gone.

---
*Phase: 03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub*
*Completed to the checkpoint: 2026-10-06*
