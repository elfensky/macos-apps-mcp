---
phase: 03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub
plan: 04
subsystem: eventkit
tags: [eventkit, recurrence, rrule, dtstart, python-dateutil, rfc5545, device-test]

requires:
  - phase: 03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub
    provides: "03-03 Recurrence BY* fields, validation, canonical-dict verify; 03-02 ek_items / icloud_scratch / PREFIX"
provides:
  - "contracts.dtstart_in_rule(rule, start): stdlib DTSTART membership over the supported BY parts"
  - "create_event / update_event Pointer summary states the extra first occurrence when the start is outside its rule (D-10)"
  - "python-dateutil (+ six) in the dev group only, with an ast test that no package module imports it"
  - "google_calendar and target_calendar (iCloud / Google) fixtures; test_recurrence_expansion_matches_rfc5545 (collected, run in 03-09)"
affects: [03-05, 03-09]

actuals:
  tokens: 7900
  tasks: 3
  commits: 5
plan_head_before: aa153ac114463bf7d0e264b6464724b586947768
plan_head_after: 97716c2c6c33ee205b35f3fa27b827ce4d6608d8

tech-stack:
  added: [python-dateutil 2.9.0.post0 (dev group), six 1.17.0 (dev transitive)]
  patterns: ["note appended after the summary bound so a long title cannot cut it", "device test collects every mismatch then asserts once", "membership check as pure stdlib, oracle-tested against dateutil"]

key-files:
  created: []
  modified:
    - macos_apps_mcp/contracts.py
    - macos_apps_mcp/adapters/calendar.py
    - macos_apps_mcp/server.py
    - pyproject.toml
    - uv.lock
    - tests/test_contracts.py
    - tests/test_calendar.py
    - tests/integration/test_eventkit_depth.py
    - README.md
    - CHANGELOG.md

key-decisions:
  - "The D-10 note is appended to the already-bounded summary instead of running clean_summary over summary + note, because the second truncation would cut the note off a long title"
  - "YEARLY shapes in the device test read three years, as spike 003 did; six months cannot exercise a yearly rule"

requirements-completed: [CAL-03]

duration: about 50 min
completed: 2026-10-06
status: complete
---

# Phase 3 Plan 04: DTSTART membership and six-month expansion test Summary

**dtstart_in_rule (stdlib, oracle-tested against dateutil) drives a D-10 note on create/update event pointers; a six-month RFC 5545 device test for iCloud and Google is collected for 03-09**

DTSTART note and six-month expansion test landed — PR #274

A recurring event whose start does not match its rule is accepted, and the returned Pointer summary now ends with " — starts outside its rule: one extra first occurrence (RFC 5545)". The six-month device test creates 21 accepted spike 003 shapes plus the two shapes where dateutil diverges. It is collected only. Plan 03-09 runs it.

## Performance

- **Duration:** about 50 min
- **Completed:** 2026-10-06
- **Tasks:** 3 (Task 1 answered by the owner, Task 2 the tracer, Task 3 device test, docs, landing)
- **Files modified:** 10
- **PR:** #274, rebase-merged into `develop`, merge commit `97716c2c6c33ee205b35f3fa27b827ce4d6608d8` (the last of 5 rebased commits)

## Task 1: package legitimacy checkpoint (python-dateutil)

Owner answer, verbatim: "approved".

Evidence the orchestrator showed the owner: PyPI metadata for python-dateutil. The source is github.com/dateutil/dateutil (active, not archived, last push 2026-09-26). It has 26 releases, from 1.4 (2008-08-06) to 2.9.0.post0 (2024-03-01). The PyPI maintainer Paul Ganssle is the top GitHub contributor `pganssle` (991 commits). It has one dependency, six >= 1.5. Source: https://pypi.org/pypi/python-dateutil/json · archived https://linkding.lav.ren/bookmarks?details=191

## Accomplishments

- `contracts.dtstart_in_rule(rule, start)`: BYMONTH, BYYEARDAY, BYMONTHDAY (with negative forms), BYDAY (plain and ordinal; ordinals counted inside the month for MONTHLY and YEARLY+BYMONTH, inside the year for YEARLY alone) and BYSETPOS over the month, year, Monday-based week or day. An absent part never fails. INTERVAL, COUNT and UNTIL do not affect it.
- `create_event` and `update_event` add `_DTSTART_NOTE` to the Pointer after verify-after-write. `events()` reads never carry it; the `events` docstring says why.
- Test table: 37 hand-computed rows (all 2027), 21 dateutil-oracle shapes over 7 start dates each (147 comparisons), end-to-end create and update through a fake store, a long-title case, the `ast` no-import test and a pyproject check that dateutil is dev-only.
- Device test `test_recurrence_expansion_matches_rfc5545[icloud|google]` with fixtures `google_calendar` (env `MACOS_APPS_IT_GOOGLE_CALENDAR_ID`, sweep to `left=0`) and `target_calendar`. Collected: both parameters appear.
- I checked the device test's expected sets offline: for the two divergent shapes the hand-computed set equals exactly the set of days `dtstart_in_rule` accepts, and every DTSTART is in its own expected set.

## TDD gates

- **RED** (`16172f9`): 60 failed, 5 passed. The target `test_dtstart_outside_rule_create_event_states_the_extra_occurrence` failed on its assertion (`'one extra first occurrence' in 'Standup 10:00–10:15'`). `gsd-tools check tdd-red-evidence` on the pytest JUnit XML returned `RED_EVIDENCE_OK` (`target_test_failed`). The contracts tests failed with `ImportError: cannot import name 'dtstart_in_rule'`, raised inside the test body through a late import, so no test errored at collection. The 5 passing tests are the "no note" regression guards, the `ast` test and the dev-dependency test. Semantic assessment: the target ran and failed on the planned assertion for the planned reason.
- **GREEN** (`94c168e`): the same selection passes (85 passed with the existing recurrence tests); full suite 1723 passed.
- **REFACTOR** (`97716c2`): review fix, `_period` moved above its caller. No behavior change.

## Task Commits

Commit hashes are the rebased ones on `develop`.

1. **Task 2 dependency add** - `85006fe` (chore)
2. **Task 2 RED** - `16172f9` (test)
3. **Task 2 GREEN** - `94c168e` (feat)
4. **Task 3 device test, docstrings, README, CHANGELOG** - `6fec6d4` (test)
5. **Review fix** - `97716c2` (refactor)

## uv.lock

`git diff origin/develop --stat -- uv.lock`: 1 file changed, 24 insertions(+), 1 deletion(-). The diff holds the `python-dateutil` and `six` package entries, the `python-dateutil` line in the dev group (twice: the package's dependency list and the `requires-dist` metadata), and the header `revision = 3` to `revision = 5`. The revision bump comes from the local uv (newer than the one that wrote the lock). No other locked package changed. `uv lock --check` passes, and CI's `uv sync --locked` step ran green on the PR. `pyproject.toml` gained one line in `[dependency-groups].dev`; `[project].dependencies` is unchanged.

## Verification (local, in the lane, before the PR)

- `uv run pytest -q`: 1723 passed, 85 deselected
- `MACOS_APPS_READ_ONLY=1 uv run pytest -q`: 1714 passed, 9 skipped, 85 deselected
- `MACOS_APPS_ALLOW_SEND=mail uv run pytest -q`: 1719 passed, 4 skipped, 85 deselected
- `uv run ruff check .`: All checks passed
- `uv run ruff format --check .`: 105 files already formatted
- `uv run pytest tests/integration/test_eventkit_depth.py --collect-only -q -m integration`: 5 collected, including `test_recurrence_expansion_matches_rfc5545[icloud]` and `[google]`
- Acceptance greps: dateutil imports under `macos_apps_mcp/` = 0; `python-dateutil` lines in pyproject = 1 (dev group); `def dtstart_in_rule` = 1 (also on `origin/develop` after the merge)
- CI on PR #274: `check` passed (1m27s), required checks green. Merged with the rebase method.

## Code review

The `code-review` skill needs two sub-agents, and none could be spawned. I performed both axes inline.

**Standards** (CLAUDE.md, .claude/CLAUDE.md, smell baseline): no open issue. Checked: tool layer stays thin (the note logic lives in the adapter); the adapter imports from `..contracts` only; `contracts.py` stays free of native imports; docstrings keep the permission wording; line length 88 and ruff rules pass; no `print`; no cross-adapter import. One judgement call: `_period` was defined after its caller. Fixed in `97716c2`. No smell found worth acting on (`_passes_by_filters` is 25 lines; the `Recurrence` BY fields are not a data clump because they already live on one type).

**Spec** (03-04-PLAN, CAL-03, D-10, D-24): no open issue. All must-have truths hold:
- D-10 membership rules as listed in the plan; the note on create and update; no note on reads; the docstring says why.
- dateutil is in the dev group only; an `ast` test and a pyproject test enforce it (T-3-13).
- D-24 unit table: oracle for 21 spike shapes, hand-computed dates for mixed BYDAY and WEEKLY+BYSETPOS.
- D-24 device test: 21 spike shapes plus 2 divergent shapes, iCloud scratch (60 s) and Google by id (90 s), one wait per source, `set(dateutil) | {dtstart}`, hand sets for the two divergent shapes, Google sweep to `left=0`, scratch calendar removed by the existing fixture, no write outside those two calendars (T-3-14).
- Scope: the extra hand-computed rows (YEARLY year-scope ordinals, BYYEARDAY=-1, week-boundary row) and the pyproject test go beyond the plan list. They cover branches of the planned logic and the T-3-13 mitigation, so I kept them. The two deviations below are the only departures from the plan text.

## Decisions Made

- The D-10 note is appended after the summary bound (see deviation 1).
- YEARLY device shapes read three years (see deviation 2).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] The note could be cut off a long title**
- **Found during:** Task 2 (GREEN design)
- **Issue:** The plan writes `clean_summary(p.summary + _DTSTART_NOTE)`. `clean_summary` truncates at 200 characters and appends a `[truncated N chars]` marker, so a long title would lose the note, breaking "summary ends with the note" and T-3-12.
- **Fix:** `_with_dtstart_note` appends the constant note to the already-bounded `p.summary` with `dataclasses.replace`. Both parts are already clean, so no second pass is needed. A test with a 400-character title proves the note survives.
- **Files modified:** macos_apps_mcp/adapters/calendar.py, tests/test_calendar.py
- **Committed in:** `94c168e`

**2. [Rule 2 - Missing critical] YEARLY shapes read three years in the device test**
- **Found during:** Task 3
- **Issue:** The plan reads six months for every shape. For a YEARLY rule that covers one occurrence at most, so it checks DTSTART only and not the expansion.
- **Fix:** YEARLY shapes read `183 + 3 * 365` days, the window spike 003 used. All other shapes read 183 days as planned. The sweep window (today to today + 800 days) still finds every event by its DTSTART.
- **Files modified:** tests/integration/test_eventkit_depth.py
- **Committed in:** `6fec6d4`

---

**Total deviations:** 2 auto-fixed (1 bug, 1 missing critical)
**Impact on plan:** Both keep the plan's intent. No scope creep.

## Issues Encountered

None blocking. `gsd_run` is not a shell function in this harness, so I called the classifier through `node ~/.claude/gsd-core/bin/gsd-tools.cjs`. The classifier refuses a record outside the project directory, so the RED record was written briefly inside the lane and deleted before the commit.

## Known Stubs

None.

## Threat Flags

None. The device test writes only into the iCloud scratch calendar and the one Google calendar the owner names, and sweeps its own prefix.

## Authentication Gates

None.

## User Setup Required

For plan 03-09: set `MACOS_APPS_IT_GOOGLE_CALENDAR_ID` to the id of an existing writable Google calendar (from `calendars()`). Without it the `[google]` parameter skips with a message that says so. The iCloud parameter needs no setup.

## Next Phase Readiness

- 03-05 can reuse the `target_calendar` fixture for the alarm device tests.
- 03-09 runs `test_recurrence_expansion_matches_rfc5545` on device. The two shapes never probed on device (WEEKLY+BYSETPOS, mixed plain/ordinal BYDAY) may expand differently from RFC 5545. If so, that is a finding: the follow-up rejects the shape by name. It is not a reason to weaken the test.

## Self-Check: PASSED

- `dtstart_in_rule` exists on `origin/develop`; `_DTSTART_NOTE` and the device test are in the merged files.
- Commits `85006fe`, `16172f9`, `94c168e`, `6fec6d4`, `97716c2` are ancestors of `origin/develop`.
- Lane `.worktrees/ek-dtstart-expansion` removed; branch `feat/ek-dtstart-expansion` deleted; main checkout untouched.

---
*Phase: 03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub*
*Completed: 2026-10-06*
