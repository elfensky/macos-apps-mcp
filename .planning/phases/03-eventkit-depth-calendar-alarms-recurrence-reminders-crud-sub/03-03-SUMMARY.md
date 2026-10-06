---
phase: 03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub
plan: 03
subsystem: eventkit
tags: [eventkit, recurrence, rrule, reminders, calendar, verify-after-write]

requires:
  - phase: 03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub
    provides: "03-01 probe 2 (reminder BY* exact on device, UNTIL kept by day); 03-02 integration scaffolding (PREFIX, ek_items, create_reminder_list)"
provides:
  - "Recurrence BY* fields (byday, bymonthday, bymonth, byyearday, bysetpos) parsed, range-checked and RFC 5545 combination-checked at the boundary"
  - "to_recurrence_rule builds with the 9-argument EventKit initializer"
  - "recurrence_signature / persisted_recurrence_signature return one canonical dict; UNTIL is day-granular and opt-in (include_until)"
  - "rrule_text renders every BY part, so the RecurrenceRequired re-send text round-trips"
affects: [03-04, 03-09]

actuals:
  tokens: 12500
  tasks: 3
  commits: 7
plan_head_before: c068cfc6054522c8521298b1a217977a16d911e5
plan_head_after: e47da3637fc3f93b3c191ca4d7b62016967d9f74

tech-stack:
  added: []
  patterns: ["canonical dict compared field by field in verify-after-write", "validation in the dataclass __post_init__ so direct construction is covered", "rrule_text built on the persisted signature, one reader for both"]

key-files:
  created: []
  modified:
    - macos_apps_mcp/contracts.py
    - macos_apps_mcp/eventkit.py
    - macos_apps_mcp/adapters/calendar.py
    - macos_apps_mcp/adapters/reminders.py
    - macos_apps_mcp/server.py
    - tests/_fakes.py
    - tests/test_eventkit.py
    - tests/test_calendar.py
    - tests/test_contracts.py
    - tests/test_reminders.py
    - tests/test_server.py
    - tests/integration/test_eventkit_depth.py
    - README.md
    - CHANGELOG.md

key-decisions:
  - "Recurrence.__post_init__ normalizes every BY tuple to sorted unique values, so equal rules compare equal however they were built"
  - "rrule_text reads the persisted rule through persisted_recurrence_signature(include_until=True), so the re-send text and the verify compare share one reader"
  - "The tracer test drives _verify_event with a fake persisted event (the existing test level) instead of a full create_event with a fake store"

patterns-established:
  - "Rejected RRULE parts live in contracts._RRULE_REJECTED (part to reason), checked before the generic unknown-part error"

requirements-completed: [CAL-03]

duration: about 30 min
completed: 2026-10-06
status: complete
---

# Phase 3 Plan 03: BY* recurrence Summary

**BY\* recurrence on events and reminders: parsed, RFC 5545 validated, built with the 9-argument initializer and verified part by part, UNTIL by day**

BY* recurrence landed: parse, validate, build, verify — PR #273

BYDAY with ordinals, BYMONTHDAY, BYMONTH, BYYEARDAY and BYSETPOS now parse, validate against RFC 5545, build with the 9-argument EventKit initializer and verify field by field after the write. BYWEEKNO, BYHOUR, BYMINUTE, BYSECOND and WKST are refused by name before any native call.

## Performance

- **Duration:** about 30 min
- **Completed:** 2026-10-05T23:29Z (UTC)
- **Tasks:** 3 (Task 1 was the tracer)
- **Files modified:** 14
- **PR:** #273, rebase-merged into `develop`, merge commit `aa153ac114463bf7d0e264b6464724b586947768` (the last of 7 rebased commits)

## Accomplishments

- **Tracer (Task 1):** BYDAY end to end. A dropped or changed BYDAY on an event now fails verify-after-write with `VerificationFailed` naming `recurs`. Today's 3-field tuple let it pass.
- **Task 2:** the four integer BY parts, the five named rejections, the range checks and the RFC 5545 combination bans, all in `Recurrence.__post_init__`, so direct construction is covered too.
- **Task 3:** reminders share the parser, builder and verify. A reminder's UNTIL is compared by day (owner override of A5, 2026-10-06; 03-01 probe 2 `s2_until_day_matches: true`). `rrule_text` renders every BY part, so the `RecurrenceRequired` re-send text keeps BYDAY (T-3-11).
- Docs: tool docstrings of `create_event`, `update_event`, `create_reminder`, `update_reminder`, README and CHANGELOG (`Added` and `Fixed`) name the supported and refused parts.
- Device test `test_reminder_byday_round_trip` is collected (3 tests in the module); the device run is plan 03-09.

## Task Commits

Commits on the lane (single-repo, measured from the ledger: `commits: 7`). After the rebase merge the same changes sit on `develop` under these hashes:

1. **Task 1 RED** - `22e5c16` test(03-03): BYDAY round trip and the canonical recurrence dict (#90)
2. **Task 1 GREEN** - `2a09e6c` feat(03-03): BYDAY recurrence built with the full initializer and verified part by part (#90)
3. **Task 2 RED** - `5db9c2d` test(03-03): BY part ranges, RFC 5545 bans and named rejections (#90)
4. **Task 2 GREEN** - `7207391` feat(03-03): BYMONTHDAY, BYMONTH, BYYEARDAY, BYSETPOS with RFC 5545 validation (#90)
5. **Task 3 RED** - `30341b1` test(03-03): BY parts survive the RecurrenceRequired re-send (#90)
6. **Task 3 GREEN** - `e609132` feat(03-03): rrule_text renders BY parts so the re-send text round-trips (#90)
7. **Code review fix** - `aa153ac` refactor(03-03): give the EKWeekday inverse its own name (#90)

The records-lane SUMMARY is left uncommitted by design (orchestrator-owned).

## TDD Gate Compliance

RED then GREEN for all three tasks (`test(03-03)` precedes `feat(03-03)` each time). Semantic RED notes:

- **Task 1 RED:** 16 tests failed on the planned assertions or on the missing feature (`unsupported RRULE part BYDAY`, canonical-dict keys, `include_until`). Genuine.
- **Task 2 RED:** 30 failed. The out-of-range tables initially passed for the wrong reason (the parts were still "unsupported", which also raises `ValueError`); I tightened them to match `out of range|not a weekday|not an integer` before committing RED, so they discriminate after GREEN.
- **Task 3 RED:** 25 failed (`rrule_text` omitted BY parts; a reminder UNTIL on another day passed). The reminder "dropped BYMONTHDAY" and "UNTIL any time that day" tests already passed from Task 1's canonical dict; they stay as guards.
- No REFACTOR commit as such; the final `refactor(03-03)` commit is the code-review rename.

## Test counts (`^def test_`, before to after)

| File | Before | After |
|---|---|---|
| tests/test_eventkit.py | 19 | 30 |
| tests/test_calendar.py | 53 | 58 |
| tests/test_contracts.py | 40 | 51 |
| tests/test_reminders.py | 49 | 53 |
| tests/test_server.py | 82 | 82 |
| tests/integration/test_eventkit_depth.py | 2 | 3 |

No count dropped. In test_eventkit.py the old hand-built tuple tests were rewritten in place (`test_recurrence_signature_requested`, `test_persisted_recurrence_signature_readback`, `test_rrule_text_renders_freq_interval_count`, `test_recurrence_signatures_agree_for_equivalent_rule` keep their names; `test_rrule_text_omits_count_when_open_ended_or_date_based` became `test_rrule_text_omits_count_when_open_ended`). Parametrized tests add many more cases (full suite 1658 passed).

## Verification (five local checks, in the lane, before the PR)

- `uv run pytest -q`: 1658 passed, 83 deselected
- `MACOS_APPS_READ_ONLY=1 uv run pytest -q`: 1649 passed, 9 skipped, 83 deselected
- `MACOS_APPS_ALLOW_SEND=mail uv run pytest -q`: 1654 passed, 4 skipped, 83 deselected
- `uv run ruff check .`: All checks passed
- `uv run ruff format --check .`: 105 files already formatted

After the review-fix commit: 1658 passed, ruff clean. CI `check` on PR #273: pass (1m44s). Acceptance checks: `grep -c "include_until=not data.all_day"` on calendar.py = 2; `include_until=True` on develop reminders.py = 2; BYWEEKNO in develop README.md = 2; BYSETPOS in develop contracts.py = 4; the 3-argument initializer no longer appears in eventkit.py; both Task 2 one-liners printed `accepted` and `refused`.

## Code review (inline, both axes; no sub-agent tool available)

**Standards** (CLAUDE.md, .claude/CLAUDE.md, smell baseline): one finding. `eventkit._WEEKDAY_CODES` (a dict) shared a name with `contracts._WEEKDAY_CODES` (a tuple): Mysterious Name, judgement call. Fixed in `aa153ac` as `_CODE_OF_WEEKDAY`. Checked and clean: `from __future__` present, qualified imports, no new native call off the worker, tool docstrings keep their permission sentences, no business logic added to the tool layer, typed `ValueError` messages are agent-directed, no stale "subset" or "UNTIL deferred" text left.
**Spec** (plan, CAL-03, D-06 to D-09, D-11, truths 1 to 10): no open finding. Parts, ranges, bans and the planner's plus or minus 5 ordinal limit are implemented; the validation runs in `__post_init__`; `include_until` follows D-09 and the A5 override; `rrule_text` order and the round trip match truth 6; no `python-dateutil` added; rejection happens at argument parse, before `run_native`.

Result: 1 Standards finding (fixed), 0 Spec findings, 0 open.

## Decisions Made

See `key-decisions` above. None changed a locked decision (D-06 to D-11).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Task 2 range tests passed for the wrong reason in RED**
- **Found during:** Task 2 RED
- **Issue:** Before GREEN every BY part raised the generic "unsupported" `ValueError`, so range tests using a bare `pytest.raises(ValueError)` passed trivially.
- **Fix:** The tests match `out of range|not a weekday|not an integer`; the messages in GREEN carry those phrases.
- **Files modified:** tests/test_contracts.py
- **Committed in:** `5db9c2d`

**2. [Task 1 tracer, level of test]** The plan's behaviour line describes `create_event` with a fake store. The existing suite verifies at `_verify_event` with `_fake_persisted_event`, so the tracer tests do the same. The verify seam they exercise is identical to the one `create_event` calls.

**3. [Edit to tests in Task 1]** The two timed-UNTIL event tests use `BYDAY=2TU` instead of `BYMONTHDAY` so the Task 1 commit stays green (BYMONTHDAY arrives in Task 2).

---

**Total deviations:** 1 auto-fixed (Rule 1), 2 test-level adjustments.
**Impact on plan:** none on behaviour or scope.

## Issues Encountered

None. The pin guard I ran before every commit used the orchestrator's logic with a shortened failure message (same checks, same stages).

## Known Stubs

None.

## Threat Flags

None. T-3-08 to T-3-11 are mitigated as planned: range and combination checks before any native call, BYWEEKNO rejected by name, canonical-dict verify-after-write, `rrule_text` renders every part.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- 03-04 can add the DTSTART note (D-10) and the six-month expansion check (D-24) on top of the parser and builder.
- 03-09 runs `tests/integration/test_eventkit_depth.py::test_reminder_byday_round_trip` on the device.
- The repo is not the daemon: nothing changes for Claude Code until the `.app` is rebuilt and reinstalled.

## Self-Check: PASSED

- Merged: `gh pr view 273` reports MERGED (rebase method), merge commit `aa153ac114463bf7d0e264b6464724b586947768`; the 7 commits are on `origin/develop` (`22e5c16` through `aa153ac`).
- Code lane removed (`test ! -e .worktrees/ek-rrule-byparts` succeeds) and `feat/ek-rrule-byparts` deleted; the main checkout is untouched (still `develop`, only the two pre-existing untracked entries).
- Vault journal bullet logged (journal-add, vault MR 1030).

---
*Phase: 03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub*
*Completed: 2026-10-06*
