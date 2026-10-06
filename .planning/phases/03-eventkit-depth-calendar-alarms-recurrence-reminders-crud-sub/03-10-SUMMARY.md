---
phase: 03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub
plan: 10
subsystem: eventkit
tags: [device-proof, cascade, reminders, store-plane, issue-closure]

requires:
  - phase: 03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub
    provides: "03-09: cascade fixture, device-3 tree, owner answer 'indented'"
provides:
  - "Cascade, parent-completion and store-plane values proven on device on an owner-built fixture"
  - "MAIL-05/06 confirmed complete from the 0.13.1 record"
  - "Issues #89, #90, #91, #92, #207 closed on device evidence"
affects: []

actuals:
  tokens: 0
  tasks: 2
  commits: 0
plan_head_before: dc44c962c2a4570a2c30bcc3eaf94ae07a553710
plan_head_after: dc44c962c2a4570a2c30bcc3eaf94ae07a553710

tech-stack:
  added: []
  patterns: []

key-files:
  created: []
  modified: []

key-decisions: []

requirements-completed: [REM-01, REM-03, REM-04, MAIL-05, MAIL-06]

duration: resumed run, about 15 min after the owner's re-add
completed: 2026-10-06
status: complete
---

# Phase 3 Plan 10: Cascade device proof and Phase 3 issue closure Summary

Cascade proven on device (2 passed, 0 failed, 0 errors, 0 skipped); MAIL-05/06 confirmed from 0.13.1; #89 #90 #91 #92 #207 closed — the installed daemon is still v0.13.1, so a release is your call (docs/RELEASING.md); the life-cockpit caller must read `reminders()["results"]`.

## Task 1: cascade proof on the owner-built fixture

**Store wait.** First run (halted): parent links were in the store at t=0 and t=510 s; the tag was absent on every read for 540 s. Cause, from the owner and the orchestrator: the first tag attempt was not saved by Reminders.app (the store held no trace of the tag text in any table or column). After the owner re-added the tag, the store plane saw it with no delay: the resumed poll printed `linked` on the first read (0 s).

| Check at the resumed read | Result |
| --- | --- |
| each of the 3 children maps to P1 | True |
| D1 maps to P2 | True |
| the fixture tag is among C1's tags | True |

**Cascade pytest** (`-m integration tests/integration/test_eventkit_depth.py -k cascade`, `device-3` at `dc44c96`, fixture via `MACOS_APPS_IT_CASCADE_FIXTURE`): junit `p3-cascade.xml` = 2 tests, 0 failures, 0 errors, 0 skipped (0.60 s). Verify printed `cascade proven`.

| Step (asserted inside the tests) | Result |
| --- | --- |
| `reminders(<fixture list>)`: children carry `parent == p1`, children[0] carries the tag, no `coverage` | pass |
| `delete_reminder(p1)` unconfirmed, refused naming 3 subtasks, nothing removed | 3 refused |
| dry run with `with_subtasks=True` lists the subtasks | 3 previewed |
| confirmed delete returns the parent and 3 subtasks, `cascade` present | 3 confirmed |
| parent and all 3 children gone in EventKit | pass |
| store reports no subtasks of the parent | pass |
| newest `delete_reminder` audit record: before-state lists all 3 subtasks | 3 in before-state |
| `complete_reminder(p2)` lists d1 as an open subtask; d1 stays open and linked | pass |

No `macos-apps-mcp-test: cascade` list remains (8 lists in the store, 0 with the test prefix). `.worktrees/device-3` is removed. Log and junit: `.worktrees/p3-cascade.log`, `.worktrees/p3-cascade.xml` (git-ignored). Every write went to an id from the fixture file.

## Task 2: MAIL-05/MAIL-06 (0.13.1, verified, not re-probed)

| Check | Output | Gate |
| --- | --- | --- |
| `grep -c -E '^- \[x\] \*\*MAIL-0[56]\*\*' .planning/REQUIREMENTS.md` | `2` | pass (2) |
| origin/develop `tests/integration/test_mail_outbound.py` names the 0.13.1 decision in the #229 xfail reason | `1` | pass (not 0) |
| origin/develop `test_mail_reply_opens_threaded_draft_and_never_sends` carries xfail | `0` | pass (0) |
| `gh issue view 229` / `230` state | `CLOSED` / `CLOSED` | pass |

REQUIREMENTS.md traceability reads `Complete (0.13.1, ahead of the phase)` for both rows. No Mail native call was made and no Mail test was run.

## Issues

All five proofs passed; each closing comment names its PRs and the device result (counts only).

| Issue | PRs cited | State |
| --- | --- | --- |
| #207 | #272 | CLOSED |
| #90 | #273, #274 | CLOSED |
| #89 | #276 (adds: reminder alarms stay REM-05, v2) | CLOSED |
| #92 | #272, #278, #279 | CLOSED |
| #91 | #277, #278, #279 (adds: no public API to write tags or subtasks; write gap documented, not built) | CLOSED |

PRs confirmed from the 03-02..03-08 SUMMARYs: 03-02 #272, 03-03 #273, 03-04 #274, 03-05 #276, 03-06 #277, 03-07 #278, 03-08 #279. 03-09 device results cited: sweep 14/14 on iCloud and the named Google calendar (0 failed, 0 errors, 0 skipped); EventKit regression 19/19.

Owner rulings in force: A9, `complete_reminder` refuses (no save) when the Reminders store is unreadable; A5, reminders compare UNTIL by day.

## Deviations from Plan

None - plan executed exactly as written. The first run stopped under the plan's own stop rule (tag absent after 10 minutes); the owner re-added the tag and the run resumed at step 1.

One self-inflicted slip, no side effect: a leftover-list check nested `runtime.run_native` around an adapter call that already uses it, which deadlocked the single worker. I stopped that process and ran the check by calling the adapter directly.

## Issues Encountered

The first tag attempt was not saved by Reminders.app (see Task 1). Resolved by the owner's re-add.

## Known Stubs

None.

## Threat Flags

None. The only deletes were the fixture's parent and 3 children, by fixture id (T-3-36). Issues were closed only on passed device proof (T-3-37). MAIL rows were verified read-only (T-3-38).

## Next Phase Readiness

Phase 3 is proven on device and on `develop`. The daemon is still v0.13.1: a Claude session sees none of it until a release is cut. No commit was made; the main checkout is unchanged. STATE.md, ROADMAP.md and REQUIREMENTS.md are the orchestrator's to update in the records lane. Journal bullet landed (vault MR 1052).

## Self-Check: PASSED

`p3-cascade.xml` and `p3-cascade.log` exist; junit 2/0/0/0; `device-3` removed; issues 89, 90, 91, 92, 207 read CLOSED; `commits: 0` matches no code change; main checkout shows only its two pre-existing untracked planning files.

---
*Phase: 03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub*
*Completed: 2026-10-06*
