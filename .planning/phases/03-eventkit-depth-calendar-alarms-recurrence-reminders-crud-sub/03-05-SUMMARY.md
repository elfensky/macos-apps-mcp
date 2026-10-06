---
phase: 03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub
plan: 05
subsystem: eventkit
tags: [eventkit, calendar, alarms, ekalarm, all-day, google-caldav, device-test]

requires:
  - phase: 03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub
    provides: "03-01 probe 4 (relative alarms exact, all-day midnight rule, more than 5 refused); 03-04 _with_dtstart_note and the google_calendar / target_calendar fixtures"
provides:
  - "CalendarEventData.alarms: tuple[int, ...] | None (None untouched, () clears) with D-03/A3/A4 validation in __post_init__"
  - "create_event / update_event alarms=list[int] | None, minutes before the start, docstrings state the all-day midnight rule"
  - "calendar._apply_event builds relative EKAlarms only; _verify_event compares a sorted multiset and requires zero absolute alarms"
  - "test_timed_alarms_round_trip, test_all_day_alarms_fire_on_the_right_day, test_all_day_without_alarms_reads_back_empty (iCloud and Google, collected; run in 03-09)"
affects: [03-09]

actuals:
  tokens: 7000
  tasks: 3
  commits: 6
plan_head_before: 97716c2c6c33ee205b35f3fa27b827ce4d6608d8
plan_head_after: a379b1d04eb2a95caf95bc3c9be6d7a25cd270fb

tech-stack:
  added: []
  patterns: ["alarm list compared as a sorted multiset of minutes-before, with an absolute-alarm count that must be 0", "None / () / tuple tri-state: None makes no setAlarms_ call and adds no verify key", "FakeEvent subclass whose unknown set* methods are no-ops lets the real _apply_event run in unit tests"]

key-files:
  created: []
  modified:
    - macos_apps_mcp/contracts.py
    - macos_apps_mcp/adapters/calendar.py
    - macos_apps_mcp/server.py
    - tests/test_contracts.py
    - tests/test_calendar.py
    - tests/test_server.py
    - tests/integration/test_eventkit_depth.py
    - README.md
    - CHANGELOG.md

key-decisions:
  - "update_event takes alarms after span (appended), so no positional caller of span shifts"
  - "A3 (negative refused on a timed event) and A4 (duplicate refused) applied as the owner confirmed after 03-01"
  - "Device test for the timed round trip sleeps twice (after create, after the final clear) and reads the rename step from the local store, to bound the Google wait"

requirements-completed: [CAL-01, CAL-02]

duration: about 40 min
completed: 2026-10-06
status: complete
---

# Phase 3 Plan 05: Event alarms Summary

**Event alarms landed: minutes-before, all-day from midnight, max 5 — PR #276**

**create_event and update_event take `alarms` (minutes before the start) as relative EKAlarms only, refused at the boundary when a source would rewrite them, verified after the write as a sorted multiset with no absolute alarm.**

## Performance

- **Duration:** about 40 min
- **Tasks:** 3 (tracer, boundary refusals, device tests and landing)
- **Files modified:** 9
- **PR:** #276, rebase-merged into `develop`, merge commit `a379b1d`; required check `check` passed (1m5s)

## Accomplishments

- Tracer: `create_event(alarms=(15,))` builds one `alarmWithRelativeOffset_(-900.0)`, and verify reads it back; a dropped alarm raises `VerificationFailed` naming `alarms`, an absolute alarm raises it naming `absolute_alarms`.
- Boundary (D-03, A3, A4): more than 5, duplicates, `bool`, non-int and negative-on-timed raise `ValueError` before any native call. `0` is accepted on both kinds, negatives only on all-day events.
- All-day rule (D-02) asserted with real `EKAlarm` value objects through the real `_apply_event`: `-540` gives +32400.0, `900` gives -54000.0, `0` gives 0.0, `1440` gives -86400.0. Both tool docstrings state it with the DST-day wording.
- Tri-state (D-04): `alarms=None` makes no `setAlarms_` call and adds no verify key (a persisted event with alarms still passes); `()` calls `setAlarms_(None)`.
- The old `ponytail:` #51 alarm comment (the `1440-gotcha` block) is replaced by a three-line comment. No absolute alarm is built anywhere (grep outside comments: 0).
- 03-04's `_with_dtstart_note` still works; its tests pass unchanged.
- README tool table and CHANGELOG `Unreleased / Added` updated.

## Task Commits

Commit hashes on `develop` after the rebase merge (scope `03-05`):

1. **Task 1 RED** - `a4d7a28` (test): alarms round trip and multiset verify (#89)
2. **Task 1 GREEN** - `f977088` (feat): alarms on create_event and update_event, verified as a multiset (#89)
3. **Task 2 RED** - `27f46a7` (test): alarm boundary refusals and the all-day offset rule (#89)
4. **Task 2 GREEN** - `908143a` (feat): alarm refusals at the boundary; the all-day rule in the docstring (#89)
5. **Task 3** - `22bd636` (test): alarm round trip and all-day fire day on iCloud and Google (#89)
6. **Review fix** - `a379b1d` (refactor): reflow the update_event alarms docstring

**Plan metadata:** left uncommitted in the records lane by design.

## TDD Gate Compliance

- **RED, Task 1:** 8 target tests failed (`TypeError: ... unexpected keyword argument 'alarms'` and `AttributeError` on `CalendarEventData.alarms`), the planned reason: the field did not exist. JUnit XML from pytest passed `gsd_run check tdd-red-evidence` with `RED_EVIDENCE_OK`. Semantic assessment: every target ran and failed on the planned feature gap; no collection or fixture fault.
- **RED, Task 2:** 5 refusal tests failed with `DID NOT RAISE ValueError` (duplicate, bool, float, string, negative-on-timed). The other new tests (offset conversion, tri-state, all-day multiset) passed at once because Task 1's code already covered them; they pin D-02 and D-04 behaviour and were not RED. Not run through the classifier (pytest report, parametrized `DID NOT RAISE` failures, read by hand).
- **GREEN / REFACTOR:** present for both tasks (`feat` after each `test`; one `refactor`).

`^def test_` counts before and after:

| File | Before | After |
|---|---|---|
| tests/test_calendar.py | 64 | 74 |
| tests/test_server.py | 82 | 85 |
| tests/test_contracts.py | 55 | 57 |
| tests/integration/test_eventkit_depth.py | 4 | 7 |

(Parametrized tests count once; the suite went from 1731-baseline-plus to 1750 passed.)

## Verification

Run in the lane before the PR:

- `uv run pytest -q`: 1750 passed, 91 deselected
- `MACOS_APPS_READ_ONLY=1 uv run pytest -q`: 1741 passed, 0 failed, 9 skipped
- `MACOS_APPS_ALLOW_SEND=mail uv run pytest -q`: 1746 passed, 0 failed, 4 skipped
- `uv run ruff check .`: No issues found
- `uv run ruff format --check .`: 105 files already formatted

Device tests (collect only, run in 03-09): `test_timed_alarms_round_trip`, `test_all_day_alarms_fire_on_the_right_day`, `test_all_day_without_alarms_reads_back_empty`, each for `[icloud]` and `[google]` (6 collected). `origin/develop` contains `alarmWithRelativeOffset_` (count 1).

## Code review (inline, both axes; sub-agents not spawned)

- **Standards** (CLAUDE.md, .claude/CLAUDE.md): tool layer stays thin dispatch (`None if alarms is None else tuple(alarms)`); validation sits in the contract; typed `ValueError` is converted by `_guard`; qualified imports untouched; tool docstrings keep the permission wording (`tests/test_tool_annotations.py` passes); no cross-adapter reach; no new dependency; no real titles, ids or accounts in code, tests or this PR. One finding: the `update_event` docstring wrapped badly after the inserted paragraph. Fixed in `a379b1d`.
- **Spec** (plan, CAL-01, CAL-02, D-01..D-05, truths 1-13, T-3-15..T-3-18): every truth has a test or an acceptance command; no absolute alarm built; more than 5 refused before the write; the tri-state holds on update; all-day events stay floating (`_apply_event` unchanged for time zones); A3/A4 applied; threats T-3-15, T-3-16, T-3-17, T-3-18 mitigated as written. No open issue.

## Decisions Made

See `key-decisions`. No spec change was needed; the plan notes' rulings on A3 and A4 were applied as written.

## Deviations from Plan

None - plan executed exactly as written. Two small notes: the update path needed no code change (it already reaches `_apply_event` and `_verify_event`, Task 2's "check" step), and Task 2's RED set is partly green on arrival (see TDD Gate Compliance).

## Issues Encountered

None. The `gh pr merge` local-branch delete was skipped while the lane was checked out, as expected; the lane and branch were removed by hand afterwards.

## Known Stubs

None.

## Threat Flags

None. No new endpoint, auth path or file access; alarms are a field on an existing write tool.

## User Setup Required

None. Device tests need `MACOS_APPS_IT_GOOGLE_CALENDAR_ID` for the `[google]` parameter (same convention as 03-04); without it they skip.

## Next Phase Readiness

- 03-09 runs the six alarm device tests (iCloud and Google). On a DST-change day an all-day alert shifts an hour (08:00 or 10:00); the real notification is not observed (next chance 2026-10-25, Europe/Brussels, per the spike).
- Lane `.worktrees/ek-alarms` removed, branch `feat/ek-alarms` deleted local and remote; main checkout untouched (it is 6 commits behind `origin/develop`, for the orchestrator to fast-forward).
- Vault journal bullet logged (MR 1040).

## Self-Check: PASSED

- Merge commit `a379b1d` is on `origin/develop`; `gh pr view 276` reports `MERGED` with the rebase method.
- `test ! -e .worktrees/ek-alarms` succeeds.
