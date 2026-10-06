---
spike: 003
idea: eventkit-depth
name: eventkit-allday-rrule
type: standard
validates: "Given a scratch calendar in a non-UTC zone, when all-day and RRULE events are created, then each reads back on the correct days, or EventKit rejects it"
verdict: VALIDATED
related: [002]
tags: [calendar, eventkit, rrule, all-day, timezone, dst, icloud, google-caldav]
---

# Spike 003: EventKit all-day events and RRULE shapes

## What This Validates

Given a scratch iCloud calendar on a Mac in Europe/Brussels (macOS 27.0), when all-day events
and 27 RRULE shapes are created, then each one reads back on the correct days, or EventKit
rejects it (Phase 3 success criteria 1 and 2).

**Answer:** all-day events are correct in every zone tested, with the adapter's current code.
Of the RRULE shapes, 21 of 22 in the main matrix read back exactly. The exception is
**BYWEEKNO**: EventKit saves it unchanged and never rejects it, but expands only DTSTART.
The adapter must reject BYWEEKNO before any native call.

## Research

- Current adapter: `contracts._RRULE_SUPPORTED = (FREQ, INTERVAL, COUNT, UNTIL)`;
  `eventkit.to_recurrence_rule` uses the 3-argument initializer; verify-after-write compares
  `(frequency, interval, count)` only (`recurrence_signature`).
- EventKit exposes the full initializer
  `initRecurrenceWithFrequency:interval:daysOfTheWeek:daysOfTheMonth:monthsOfTheYear:weeksOfTheYear:daysOfTheYear:setPositions:end:`
  and `EKRecurrenceDayOfWeek dayOfWeek:weekNumber:` for ordinals (`2TU`, `-1FR`).
- Apple's docs limit `monthsOfTheYear`, `weeksOfTheYear` and `daysOfTheYear` to yearly rules.
  The matrix tests that claim against the device instead of trusting it.
- Reference expansion: `python-dateutil` `rrulestr` (run through `uv run --with`, not a
  project dependency). dateutil drops a DTSTART that does not match the rule; RFC 5545 counts
  it as the first instance. The probe checks both.
- No "On My Mac" source exists. The default calendar for new events is **Google**. Google
  refuses calendar creation (`EKErrorDomain 17`), so the scratch calendar is on iCloud.

## How to Run

```sh
P=.planning/spikes/003-eventkit-allday-rrule/probe_eventkit.py
uv run --with python-dateutil python $P rrule   # 22 shapes + 60 s iCloud re-read
uv run --with python-dateutil python $P allday  # 3 creator zones × 4 reader zones
uv run --with python-dateutil python $P weekno  # BYWEEKNO isolation
uv run --with python-dateutil python $P gap     # all-day on a day with no midnight
# Google refuses new calendars: run the matrix in an EXISTING calendar. Only events
# titled "gsd-spike-003 …" are written, then deleted by id and by a sweep (left=0).
SPIKE_SOURCE=Google SPIKE_CALENDAR=Personal uv run --with python-dateutil python $P rrule
```

Each run creates `gsd-spike-003` in iCloud and removes it in a `finally`. Results land in
`results-*.json` beside the script (scratch data only).

## What to Expect

One line per shape (`EXACT`, `EXACT (DTSTART counted, RFC)`, `RULE CHANGED`,
`OCCURRENCES DIFFER`, `REJECTED …`), one line per all-day cell (`OK` / `WRONG days=…`), then
`removed scratch calendar: True`.

## Investigation Trail

1. **All-day × zone.** Created a single all-day event (2026-10-26) and a weekly all-day series
   (from 2026-10-19, COUNT=4, crossing the EU and US DST ends) through the real
   `CalendarAdapter.create_event`, from processes with `TZ` = Brussels, Auckland, Los Angeles.
   Read from those zones and UTC. 24/24 cells: right day, `isAllDay`, `timeZone = nil`
   (floating), start at local midnight. `TZ` does move `NSTimeZone.systemTimeZone`, so the
   cells are real cross-zone reads.
2. **Distrusted the clean pass.** Added days whose local midnight does not exist (DST starts
   at 00:00): Asia/Beirut 2027-03-28, America/Santiago 2027-09-05, each confirmed with
   `zoneinfo`. Right day in all 4 reader zones. In the gap zone, `startDate` reads **01:00**
   local, the first instant of that day. The adapter's verify-after-write accepted it.
3. **RRULE matrix, 22 shapes.** 20 EXACT, 1 EXACT under RFC DTSTART semantics, 1 wrong
   (`FREQ=YEARLY;BYWEEKNO=20;BYDAY=MO`: 1 occurrence, RFC gives 4).
4. **Doc claim versus device.** `FREQ=DAILY;BYMONTH=12` and
   `FREQ=MONTHLY;BYMONTH=1,4,7,10;BYMONTHDAY=1` are outside what Apple documents, but both
   expanded exactly.
5. **BYWEEKNO isolation, 5 variants** (with or without BYDAY, two weeks, week −1, COUNT=3).
   Every variant: rule saved unchanged, 1 occurrence (DTSTART), no error. EventKit on macOS
   stores `weeksOfTheYear` and ignores it at expansion.
6. **After sync.** A fresh `EKEventStore` 60 s later, after `refreshSourcesIfNecessary`, held
   the same 22 rules. This does not prove the server stored them unchanged: the local cache
   can answer. No second device was checked.
7. **Google.** The default calendar for new events is Google/Personal, and Google refuses a
   scratch calendar (`EKErrorDomain 17`). With the owner's approval, the matrix ran inside
   Personal: every event was titled `gsd-spike-003 …` and deleted by id and by a sweep
   (`left=0` before and after). The sweep path was first tested on an iCloud scratch
   calendar. Result: identical to iCloud, with the same 22 verdicts and occurrence counts,
   the same BYWEEKNO under-expansion, and no rule changed after a 90 s sync.

## Results

**Verdict: VALIDATED.** Phase 3 criteria 1–2 are reachable with a known reject list. The
RRULE results are identical on iCloud and Google CalDAV (`results-rrule-icloud.json`,
`results-rrule-google.json`).

| Shape (RRULE) | Result |
|---------------|--------|
| `WEEKLY;BYDAY=MO,WE,FR` · `WEEKLY;INTERVAL=2;BYDAY=TU,TH` · `WEEKLY;BYDAY=MO,WE;COUNT=5` | EXACT |
| `MONTHLY;BYDAY=2TU` · `-1FR` · `5FR` (only months with 5) · `MO` (every Monday) | EXACT |
| `MONTHLY;BYMONTHDAY=15` · `1,15` · `-1` · `31` (skips short months) · `29` (skips Feb) | EXACT |
| `MONTHLY;BYMONTHDAY=15;UNTIL=…` · `MONTHLY;BYDAY=MO..FR;BYSETPOS=-1` | EXACT |
| `MONTHLY;BYMONTH=1,4,7,10;BYMONTHDAY=1` · `DAILY;BYMONTH=12` | EXACT (against Apple's docs) |
| `YEARLY;BYMONTH=3;BYDAY=-1SU` · `BYMONTH=1,7;BYMONTHDAY=1` · `BYYEARDAY=100` · `BYMONTH=11;BYDAY=TH;BYSETPOS=4` | EXACT |
| `MONTHLY;BYDAY=2TU` with DTSTART on a non-matching day | DTSTART added as an extra 1st instance (RFC-correct) |
| `YEARLY;BYWEEKNO=…` (6 variants) | **Saved unchanged, expands to DTSTART only, no error** |
| All-day, 3 creator zones × 4 reader zones, incl. DST crossings | 24/24 correct |
| All-day on a day with no local midnight (2 zones × 4 readers) | 8/8 correct day; start reads 01:00 in the gap zone |

**Signal for the build**

- Map BY* parts with the full initializer. Reject **BYWEEKNO**, plus the parts EventKit has no
  field for (`BYHOUR`, `BYMINUTE`, `BYSECOND`, `WKST`), with a typed error that names the part.
- Extend verify-after-write to every BY* part. `recurrence_signature` compares only
  `(frequency, interval, count)`, so a dropped BYDAY would pass. The canonical dict in
  `from_ek()` is the comparison form.
- An occurrence check, if added, must count DTSTART as RFC 5545 does, not as dateutil does.
- All-day: keep the current naive-midnight path. Derive the all-day date with `.date()`;
  never assume 00:00, because a DST-at-midnight day starts at 01:00.

**Open**

- Server-side storage: on both iCloud and Google the after-sync re-read may come from this
  Mac's cache. No second device was checked.
- DTSTART that does not match the rule: EventKit adds an extra first instance. Decided
  (owner, 2026-09-28): accept with RFC 5545 semantics and state the extra first occurrence in
  the Pointer summary.
