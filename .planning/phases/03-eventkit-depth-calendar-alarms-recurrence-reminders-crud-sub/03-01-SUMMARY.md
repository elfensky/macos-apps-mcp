---
phase: 03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub
plan: 01
subsystem: eventkit
tags: [eventkit, probe, reminders, recurrence, alarms, google-caldav, device]

requires:
  - phase: 02.1-mail-fixes-batch-moves-fit-their-timeout-drafts-pick-their-a
    provides: the device rule (owner at the Mac, probe first) this plan follows
provides:
  - "Reminder-list save works on the default reminders source and the list is readable; Google refuses a list save with EKErrorDomain 24"
  - "Reminders keep BY* recurrence parts built with the 9-argument initializer, now and after 60 s from a fresh process"
  - "Google alarm behaviour re-measured unchanged: 5-alarm cap, absolute alarms rewritten, relative alarms exact, all-day fire day right in 4 zones"
affects: [03-02, 03-03, 03-05]

actuals:
  tokens: 3800
  tasks: 3
  commits: 0
plan_head_before: 56b9fa35a191df054a9e94d61f0dfc38e4e26f7c
plan_head_after: 56b9fa35a191df054a9e94d61f0dfc38e4e26f7c

tech-stack:
  added: []
  patterns: ["probe-first: raw EventKit from a detached device tree, git-ignored result files"]

key-files:
  created: []
  modified: []

key-decisions:
  - "No premise overturned: 03-02, 03-03 and 03-05 proceed as planned"
  - "03-02 maps a refused reminder-list save by err.code(): 24 was measured on Google (17 stays in the mapped set)"

requirements-completed: [CAL-01, CAL-02, CAL-03, REM-02]

duration: about 20 min
completed: 2026-10-06
status: complete
---

# Phase 3 Plan 01: Pre-code EventKit probes Summary

**Probes 1/2/4 confirm every premise: reminder-list save works on the default source and Google refuses it with code 24, reminder BY* shapes round-trip exactly (also after 60 s from a fresh process), and Google alarms behave as in spike 008 with all-day alarms on the right day in 4 zones.**

No premise was overturned. Plans 03-02, 03-03 and 03-05 need no replan.

## Performance

- **Duration:** about 20 min
- **Completed:** 2026-10-05T23:02Z (UTC)
- **Tasks:** 3 (Task 1 was answered by the owner through the orchestrator)
- **Files modified:** 0 in the repo (probe files are git-ignored under `.worktrees/`)

## Task 1: owner answer

The owner said "go" and named one existing Google calendar, recorded here as `<named Google calendar>`. The owner confirmed being at the Mac. The orchestrator showed the policy defaults A3, A4, A5 and A9 and the D-15 `reminders()` shape notice before any probe ran.

**Owner overrides:** none at go time. The orchestrator asks the owner about each of A3, A4, A5 and A9 separately after this plan, with the probe results below.

## Probes 1 and 2 (Task 2)

Device tree: detached at `origin/develop`, commit `56b9fa35a191df054a9e94d61f0dfc38e4e26f7c`.

`p3-probes.json` (final run):

```json
{
  "default_source_type": 2,
  "list_saved": true,
  "list_in_reads": true,
  "list_removed": true,
  "refusal_domain": "EKErrorDomain",
  "refusal_code": 24,
  "s1_exact": true,
  "s2_exact": true,
  "s3_exact": true,
  "s2_until_day_matches": true,
  "after_sync_exact": true,
  "left": 0
}
```

- **List save on the default reminders source (D-22): works.** `default_source_type` 2 is a CalDAV source. The saved list appears in `calendarsForEntityType_(EKEntityTypeReminder)` by identifier, and removal leaves no trace (`list_removed`, `left` 0).
- **List save on the named Google calendar's source (RESEARCH A6): refused with `EKErrorDomain` 24.** The error code is an integer, so a code-based mapping works (A6 confirmed). The plan expected 17 or 24; the measured code is 24. 03-02's `create_reminder_list` mapping to `WriteRefused` should cite 24 and keep 17 in the set, because the refusal code on a source can differ by account type.
- **S1 `FREQ=MONTHLY;BYDAY=2TU;COUNT=6`: exact** at once. **S2 `FREQ=WEEKLY;BYDAY=MO,WE,FR` with UNTIL: exact.** **S3 `FREQ=YEARLY;BYMONTH=3;BYMONTHDAY=-1;COUNT=3`: exact.** All three round-trip through the 9-argument initializer on reminders, as spike 003 showed for events.
- **UNTIL on a reminder (RESEARCH A5): kept at day granularity** (`s2_until_day_matches` true). The first run's fresh-process read also showed the same UNTIL day. D-09 still names timed events only, and the owner decides A5 separately. If the owner changes A5, reminders can compare UNTIL at day granularity like timed events.
- **Fresh-process read after 60 s: exact** for all three shapes (`after_sync_exact` true). Nothing was dropped or rewritten by the store.

## Probe 4 (Task 3)

Spike 008 harness, copied unchanged, run on the named Google calendar: 32 events created, no save failure, 90 s wait, reads in 4 zones, sweep. Log: `before: left=0` ... `after: left=0` (320 all-day fire times checked).

`verdict.json`:

```json
{
  "left_before_0": true,
  "left_after_0": true,
  "six_kept_five": true,
  "relative_exact": true,
  "abs_rewritten": true,
  "allday_fire_days_ok": true,
  "allday_fires_checked": 320,
  "dst_day_fires": 8
}
```

Harness lines that matter: `timed-six` read back as `[-15, -60, -30, -10, -120]` (the `-5` was dropped this run). `timed-abs` read back as `rel_min -120`. `allday-abs` read back as `-900` (made in Brussels) and `-1620` (made in Auckland). Every other case read `EXACT`. Eight all-day fire times fall on DST-change days at 08:00 (fall) or 10:00 (spring) with a `(wall 09:00)` suffix.

Comparison with the spike 008 Constraints table (Google column; the iCloud column was not re-run, the plan targets Google only):

| Row | Result now |
|---|---|
| Timed: none, -15, 0, -60 and -15, -1440 | Same as spike 008: exact. |
| Timed: 6 alarms | Same as spike 008: 5 kept; the dropped one differs per run (-5 this time). |
| Timed: absolute (start - 2 h) | Same as spike 008: rewritten to relative -120. |
| All-day: none, +540, -900, 0 | Same as spike 008: exact, no default alarm injected. |
| All-day: absolute | Same as spike 008: rewritten to relative, anchored to the creator's day (-900 and -1620). |
| Weekly and daily all-day series, +540 and -900 | Same as spike 008: exact. |
| All-day fire day, 4 reader zones, 320 fire times | Same as spike 008: right day everywhere; 8 DST-day times at 08:00 / 10:00. |

`six_kept_five` is true, so Google still keeps 5 alarms. D-03 refuses more than 5 on every source either way. `allday_fire_days_ok` and `relative_exact` are true, so 03-05's alarm refusals (D-03) and all-day rule (D-02) stand.

## Accomplishments

- Probed the list-create, reminder BY* and Google alarm premises on today's macOS (host zone Europe/Brussels) before any Phase 3 code.
- Left nothing behind: probe lists, reminders and harness events are all removed (`left` 0, `list_removed` true, harness `left=0` before and after), and the temporary device tree is removed.

## Task Commits

None. The plan changes no tracked file and makes no commit. The probe files are git-ignored: `.worktrees/.p3_probes.py`, `.worktrees/p3-probes.json`, `.worktrees/p3-probe-ids.json`, `.worktrees/p3-probe-008/`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Probe script compared tuples with JSON lists**
- **Found during:** Task 2 (fresh-process readback)
- **Issue:** The first run reported `after_sync_exact` false. The cause was the probe script itself: the child process returned `byday` as JSON lists, and the parent compared them with tuples. The rule values were identical.
- **Fix:** `nodate()` in the git-ignored `.p3_probes.py` now converts `byday` entries to tuples before the compare. The probe ran again in full.
- **Verification:** The re-run reports `after_sync_exact` true; teardown of both runs left 0.
- **Committed in:** not committed (git-ignored probe file).

---

**Total deviations:** 1 auto-fixed (1 bug in the one-off probe script, not in the product).
**Impact on plan:** None on the findings. The probe sequence ran twice (create, wait 60 s, read, remove), both times with clean teardown.

## Issues Encountered

None beyond the probe-script bug above. The first-day filter in the harness prints `daily-fall-0900` rows twice because 2026-10-30 is also an occurrence of that series; this is the harness' own output and not a defect.

## Authentication Gates

None. This shell's process already held EventKit full access for events and reminders.

## Known Stubs

None.

## Threat Flags

None. The probes wrote only to the default reminders source (probe list) and to the one named Google calendar; no family account was a target (T-3-01). The result files hold booleans and counts only (T-3-03).

## Next Phase Readiness

- 03-02 can write the `create_reminder_list` error mapping from `refusal_code` 24 (plus 17).
- 03-03 may take BY* on reminders through the shared parser (D-11): all three shapes are exact.
- 03-05 keeps D-02 and D-03 as planned.
- Open for the owner after this plan: A3, A4, A5, A9, answered separately by the orchestrator. Probe 2 gives A5 its evidence (reminders keep UNTIL at day granularity).

## Self-Check: PASSED

- `.worktrees/p3-probes.json` and `.worktrees/p3-probe-008/verdict.json` exist and pass the plan's automated verify commands ("probes ran clean", "probe 4 ran clean 320").
- `.worktrees/device-3-probes` is removed ("device tree removed").
- No tracked file changed in the main checkout (still on `develop`, clean apart from two pre-existing untracked entries) and no commit was made.

---
*Phase: 03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub*
*Completed: 2026-10-06*
