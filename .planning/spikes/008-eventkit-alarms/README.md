---
spike: 008
idea: eventkit-depth
name: eventkit-alarms
type: standard
validates: "Given iCloud and Google/Personal, when timed, all-day and recurring all-day events get alarm lists from 3 zones, then each alarm reads back exactly after sync and falls on the correct local day"
verdict: VALIDATED
related: [003]
tags: [calendar, alarms, all-day, timezone, dst, icloud, google-caldav]
---

# Spike 008: EventKit alarms — round trip and fire day

## What This Validates

Given an iCloud scratch calendar and the existing Google/Personal calendar (the default for
new events), when events get alarm lists — timed, all-day and recurring all-day, created from
Europe/Brussels and Pacific/Auckland — then after sync every alarm reads back exactly, and
each all-day alarm's fire time falls on the correct local day in 4 reader zones (CAL-01,
CAL-02, research Pitfall 5).

**Answer:**

- **Relative alarms round-trip exactly on iCloud and Google,** timed and all-day, single and
  recurring, from both creator zones. A relative all-day alarm fires on the correct local
  day and hour in every reader zone, across both DST ends. Pitfall 5 (mcp-ical's off-by-one)
  does not occur with relative offsets from midnight.
- **Google changes two things, silently and late.** It keeps at most **5** alarms and drops a
  different one each time. It converts an **absolute** alarm to a relative one. The save
  succeeds, and the local store shows the request for 10–30 s, then Google's version syncs
  back. A verify-after-write right after the save cannot see it.
- **An absolute alarm on an all-day event is wrong in any other zone.** It is a fixed instant
  on a floating event. On Google it is then converted relative to the Brussels day.
- **On a DST-change day, "+540 from midnight" is 08:00 (fall) or 10:00 (spring)** under
  EventKit's model (seconds from the start instant). Calendar.app encodes its own all-day
  alerts the same way, so the adapter matches Calendar there.

## Research

- `calendar.py:226` (#51): an all-day alarm's `relativeOffset` counts from midnight, so
  "09:00 the day before" is −900 min. No alarm code exists yet (CAL-01 is unbuilt).
- Research Pitfall 5: mcp-ical computed all-day alarms from a UTC-anchored start and fired a
  day early in zones ahead of UTC; the probe must use a recurring all-day event in a non-UTC
  zone.
- Web search found only secondary sources: some apps cap at 5 reminders per event, and
  all-day defaults count minutes from midnight. No authoritative statement on Google CalDAV's
  VALARM handling, so the device decides.
- Spike 003's harness: child processes with `TZ` set, Google writes only into an existing
  calendar with prefixed titles, a sweep, `left=0` before and after.

## How to Run

```sh
P=.planning/spikes/008-eventkit-alarms/probe_alarms.py
uv run python $P                                            # iCloud scratch calendar
SPIKE_SOURCE=Google SPIKE_CALENDAR=Personal uv run python $P
SPIKE_SOURCE=Google SPIKE_CALENDAR=Personal uv run python $P timing
```

## What to Expect

One `EXACT` / `CHANGED want=… got=…` line per event and creator, the all-day fire times where
the instant model and the wall-clock model disagree, and `left=0` / `removed scratch
calendar: True`. `timing` prints the alarm list of two Google events at 0, 10, 30, 60, 120 s.

## Investigation Trail

1. **Matrix, iCloud.** 14 cases × 2 creator zones. Timed: none, −15, 0, −60 and −15, −1440, six
   alarms, absolute. All-day: none, +540, −900, 0, absolute. Weekly all-day series ×4 across
   both DST ends: +540, −900. 28/28 EXACT after a 60 s sync.
2. **Fire day, 4 reader zones.** Every relative all-day fire time landed on the right local
   day and hour. The absolute all-day alarm made in Auckland read as 21:00 two days before the
   event in Brussels: a fixed instant on a floating event.
3. **Distrusted the clean pass.** The weekly series had no occurrence ON a DST-change day.
   Added daily series across EU 2026-10-25 / US 2026-11-01 (fall) and US 2027-03-14 / EU
   2027-03-28 (spring). The instant model gives 08:00 (fall) and 10:00 (spring) for "+540";
   8 of 320 fire times, all on those days. Which one Calendar actually fires at cannot be
   observed before 2026-10-25.
4. **How Calendar encodes its own alerts (read-only census).** Existing all-day alarms on this
   Mac: +540 ×164, −900 ×50, −10 ×185, −30 ×4, +1200 ×1 (mostly Google). So +540 / −900 is
   Calendar's and Google's own encoding; the adapter shares their DST-day behaviour.
5. **Matrix, Google/Personal.** Same 32 events. Relative alarms, all-day and series: EXACT.
   Changed: six alarms → 5; timed absolute → −120; all-day absolute → −900 (made in
   Brussels) or −1620 (the same instant made in Auckland, taken relative to the Brussels
   day). No default alarm appeared on the no-alarm events. `left=0` before and after.
6. **When Google changes it.** Two timing runs: the local store showed the request at 0 s
   (and at 10 s in one run), and Google's version by 10–30 s. The dropped alarm was −10, −15
   and −30 in three runs. EventKit returns alarms in no stable order.
7. **Probe bug found and fixed.** The sweep's final count passed a calendar from one
   `EKEventStore` into another store's predicate and crashed (`NSNull backingObject`). The
   deletes had already run; a single-store re-count showed `left=0`.

## Results

**Verdict: VALIDATED.**

| Case | iCloud | Google |
|---|---|---|
| Timed: none, −15, 0, −60 and −15, −1440 | EXACT | EXACT |
| Timed: 6 alarms | EXACT | **5 kept, a different one dropped each run** |
| Timed: absolute (start − 2 h) | EXACT | **→ relative −120** |
| All-day: none, +540, −900, 0 | EXACT | EXACT (no default injected) |
| All-day: absolute | EXACT (wrong day in other zones) | **→ relative, anchored to the Brussels day** |
| Weekly / daily all-day series, +540 and −900 | EXACT | EXACT |
| All-day fire day, 4 reader zones, 320 fire times | correct day; 8 DST-day times at 08:00 / 10:00 | same |

`results-icloud.json`, `results-google.json` and `results-timing-google.json` hold every read.

**Signal for the build (Phase 3, CAL-01 / CAL-02)**

- **Offer relative alarms only**, as minutes before the start. For all-day events convert
  "minutes before" to an offset from midnight (#51: "09:00 the day before" is −900). Do not
  offer absolute alarms: they break on floating all-day events, and Google rewrites them.
- **Refuse more than 5 alarms before the write.** Google keeps 5 and drops an unpredictable
  one after the save, and the default calendar for new events is Google. Refusing on every
  source keeps the rule simple; a per-source rule needs the source type.
- **Verify-after-write cannot see a Google rewrite** (it lands 10–30 s later). Rejecting the
  two known shapes before the write is the fix; a delayed re-read is not.
- **Compare alarm lists as sorted multisets.** EventKit returns them in no stable order.
- **DST days:** "+540 from midnight" is 08:00 or 10:00 on a DST-change day under EventKit's
  model. Calendar.app's own all-day alerts use the same encoding, so the docstring can say
  "the same as Calendar's own alerts" without claiming a wall-clock guarantee.

**Not tested**

- The actual notification: no alarm was waited for, so which of 08:00 / 09:00 Calendar fires
  on a DST day is unobserved (next chance: 2026-10-25, Europe/Brussels).
- Reminders alarms (REM-05, v2), Exchange and subscribed calendars.
- Server-side storage: the after-sync reads come from this Mac's store (as in spike 003).
