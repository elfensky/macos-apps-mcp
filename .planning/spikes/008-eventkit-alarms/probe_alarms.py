"""Spike 008 — do EventKit alarms survive the round trip, and fire on the right day?

Creates timed, all-day and recurring all-day events with alarm lists, from creator zones
Europe/Brussels and Pacific/Auckland (one child process per zone, `TZ` set), waits for
sync, then reads every alarm back from 4 reader zones in fresh processes. For all-day
events it computes each occurrence's local fire time (start + relative offset).

    P=.planning/spikes/008-eventkit-alarms/probe_alarms.py
    uv run python $P                                   # iCloud scratch calendar
    SPIKE_SOURCE=Google SPIKE_CALENDAR=Personal uv run python $P

iCloud: a scratch calendar `gsd-spike-008`, removed at the end. Google refuses new
calendars (spike 003), so there the events go into an EXISTING calendar, each titled
`gsd-spike-008 …`, deleted by id and then by a sweep, with left=0 checked before
and after.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta

import EventKit as EK

from macos_apps_mcp.eventkit import from_nsdate, to_nsdate

HERE = os.path.dirname(os.path.abspath(__file__))
CAL_TITLE = "gsd-spike-008"
PREFIX = f"{CAL_TITLE} "
SOURCE = os.environ.get("SPIKE_SOURCE", "iCloud")
EXISTING = os.environ.get("SPIKE_CALENDAR")
CREATORS = ["Europe/Brussels", "Pacific/Auckland"]
READERS = ["Europe/Brussels", "Pacific/Auckland", "America/Los_Angeles", "UTC"]
SYNC_WAIT = 90 if SOURCE == "Google" else 60
DAY = datetime(2026, 10, 30)  # a Friday, after the EU DST end
# kind -> (first day, frequency, count). Weekly crosses the EU (10-25) and US (11-01)
# DST ends; the daily series put an occurrence ON each DST-change day, where "+540 from
# midnight" and "09:00 local" disagree (the clock jumps between 00:00 and 09:00).
SERIES = {
    "series": (datetime(2026, 10, 19), EK.EKRecurrenceFrequencyWeekly, 4),
    "daily-fall": (datetime(2026, 10, 24), EK.EKRecurrenceFrequencyDaily, 10),
    "daily-spring": (datetime(2027, 3, 12), EK.EKRecurrenceFrequencyDaily, 18),
}

# (case, kind, alarms). A number is a relative offset in minutes (negative = before
# start); "abs" is an absolute alarm 2 h before a timed start, or 09:00 local on the
# day before an all-day start. All-day offsets count from local midnight (#51).
CASES = [
    ("timed-none", "timed", []),
    ("timed-15", "timed", [-15]),
    ("timed-0", "timed", [0]),
    ("timed-60-15", "timed", [-60, -15]),
    ("timed-1day", "timed", [-1440]),
    ("timed-six", "timed", [-5, -10, -15, -30, -60, -120]),
    ("timed-abs", "timed", ["abs"]),
    ("allday-none", "allday", []),
    ("allday-0900", "allday", [540]),
    ("allday-0900-before", "allday", [-900]),
    ("allday-midnight", "allday", [0]),
    ("allday-abs", "allday", ["abs"]),
    ("series-0900", "series", [540]),
    ("series-0900-before", "series", [-900]),
    ("daily-fall-0900", "daily-fall", [540]),
    ("daily-spring-0900", "daily-spring", [540]),
]
FIRST_DAYS = {DAY.date().isoformat()} | {
    d.date().isoformat() for d, _, _ in SERIES.values()
}


def store():
    s = EK.EKEventStore.alloc().init()
    s.refreshSourcesIfNecessary()
    return s


def calendar(s):
    for c in s.calendarsForEntityType_(EK.EKEntityTypeEvent):
        if c.source().title() == SOURCE and c.title() == (EXISTING or CAL_TITLE):
            return c
    return None


def mine(s, cal) -> list:
    pred = s.predicateForEventsWithStartDate_endDate_calendars_(
        to_nsdate(datetime(2026, 10, 1)), to_nsdate(datetime(2027, 4, 30)), [cal]
    )
    return [
        e
        for e in s.eventsMatchingPredicate_(pred) or []
        if e.title().startswith(PREFIX)
    ]


def sweep() -> int:
    s = store()
    cal = calendar(s)
    for e in mine(s, cal):
        live = s.eventWithIdentifier_(e.eventIdentifier())
        if live is not None:
            s.removeEvent_span_commit_error_(live, EK.EKSpanFutureEvents, True, None)
    s = store()  # one store: a calendar object from another store is NSNull here
    return len(mine(s, calendar(s)))


def alarm(offset, kind: str, start: datetime):
    if offset != "abs":
        return EK.EKAlarm.alarmWithRelativeOffset_(offset * 60.0)
    when = (
        start - timedelta(hours=2) if kind == "timed" else start - timedelta(hours=15)
    )
    return EK.EKAlarm.alarmWithAbsoluteDate_(to_nsdate(when))


def create() -> list[dict]:
    """Child, in its creator zone: one event per case, verify-on-save readback."""
    tz = os.environ["TZ"]
    s = store()
    cal = calendar(s)
    out = []
    for case, kind, alarms in CASES:
        day = SERIES[kind][0] if kind in SERIES else DAY
        e = EK.EKEvent.eventWithEventStore_(s)
        e.setTitle_(f"{PREFIX}{case} {tz}")
        e.setCalendar_(cal)
        if kind == "timed":
            start = day.replace(hour=10)
            e.setStartDate_(to_nsdate(start))
            e.setEndDate_(to_nsdate(start + timedelta(hours=1)))
        else:
            start = day
            e.setAllDay_(True)
            e.setStartDate_(to_nsdate(day))
            e.setEndDate_(to_nsdate(day))
            e.setTimeZone_(None)
        if kind in SERIES:
            _, freq, count = SERIES[kind]
            rule = (
                EK.EKRecurrenceRule.alloc().initRecurrenceWithFrequency_interval_end_(
                    freq,
                    1,
                    EK.EKRecurrenceEnd.recurrenceEndWithOccurrenceCount_(count),
                )
            )
            e.setRecurrenceRules_([rule])
        e.setAlarms_([alarm(a, kind, start) for a in alarms] or None)
        ok, err = s.saveEvent_span_commit_error_(e, EK.EKSpanThisEvent, True, None)
        out.append(
            {"case": case, "creator": tz, "saved": bool(ok), "err": str(err or "")}
        )
    return out


def describe(a, start) -> dict:
    absd = a.absoluteDate()
    if absd is not None:
        return {"abs": from_nsdate(absd).isoformat(timespec="minutes")}
    return {"rel_min": round(a.relativeOffset() / 60)}


def read() -> list[dict]:
    """Child, in its reader zone: every alarm, plus local fire times per occurrence."""
    s = store()
    cal = calendar(s)
    out = []
    for e in sorted(
        mine(s, cal), key=lambda x: (x.title(), from_nsdate(x.startDate()))
    ):
        start = from_nsdate(e.startDate())
        alarms = [describe(a, start) for a in (e.alarms() or [])]
        fires = []
        for a in e.alarms() or []:
            if a.absoluteDate() is not None:
                fires.append(
                    from_nsdate(a.absoluteDate()).isoformat(timespec="minutes")
                )
                continue
            # Seconds from the start INSTANT (EKAlarm's stated model) versus the same
            # offset on the local wall clock. They differ only across a DST change.
            inst = from_nsdate(
                e.startDate().dateByAddingTimeInterval_(a.relativeOffset())
            )
            wall = start + timedelta(seconds=a.relativeOffset())
            f = inst.isoformat(timespec="minutes")
            fires.append(f if inst == wall else f"{f} (wall {wall:%H:%M})")
        out.append(
            {
                "title": e.title()[len(PREFIX) :],
                "start": start.isoformat(timespec="minutes"),
                "all_day": bool(e.isAllDay()),
                "alarms": alarms,
                "fires": fires,
            }
        )
    return out


def child(mode: str, tz: str) -> list[dict]:
    p = subprocess.run(
        [sys.executable, __file__, mode],
        env={**os.environ, "TZ": tz},
        capture_output=True,
        text=True,
    )
    if p.returncode:
        raise RuntimeError(f"{mode} in {tz} failed:\n{p.stderr[-2000:]}")
    return json.loads(p.stdout.strip().splitlines()[-1])


def expected(case: str) -> list:
    return next(a for c, _, a in CASES if c == case)


def verdict(case: str, got: list[dict]) -> str:
    want = expected(case)
    rel = sorted(a["rel_min"] for a in got if "rel_min" in a)
    n_abs = sum("abs" in a for a in got)
    if rel == sorted(x for x in want if x != "abs") and n_abs == want.count("abs"):
        return "EXACT"
    return f"CHANGED want={want} got={got}"


def main() -> None:
    s = store()
    if EXISTING:
        assert calendar(s), f"no {SOURCE}/{EXISTING}"
        print(f"before: left={sweep()}")
    else:
        assert calendar(s) is None, f"{CAL_TITLE} already exists"
        cal = EK.EKCalendar.calendarForEntityType_eventStore_(EK.EKEntityTypeEvent, s)
        cal.setTitle_(CAL_TITLE)
        cal.setSource_(next(x for x in s.sources() if x.title() == SOURCE))
        ok, err = s.saveCalendar_commit_error_(cal, True, None)
        assert ok, err
    res = {"source": SOURCE, "created": [], "reads": {}}
    try:
        for tz in CREATORS:
            res["created"] += child("create", tz)
        bad = [c for c in res["created"] if not c["saved"]]
        print(f"created {len(res['created'])}, save failures: {bad}")
        print(f"waiting {SYNC_WAIT}s for sync")
        time.sleep(SYNC_WAIT)
        for tz in READERS:
            res["reads"][tz] = child("read", tz)
        for row in res["reads"][READERS[0]]:
            case = row["title"].rsplit(" ", 1)[0]
            if row["start"][:10] in FIRST_DAYS:
                print(f"  {row['title']:42} {verdict(case, row['alarms'])}")
        n = 0
        print("all-day fire times where the two models disagree:")
        for tz in READERS:
            for row in res["reads"][tz]:
                if not (row["all_day"] and row["alarms"]):
                    continue
                n += len(row["fires"])
                if any("wall" in f for f in row["fires"]):
                    print(
                        f"  {tz:20} {row['title']:34} {row['start'][:10]} "
                        f"-> {row['fires']}"
                    )
        print(f"({n} all-day fire times checked)")
    finally:
        if EXISTING:
            print(f"after: left={sweep()}")
        else:
            s = store()
            cal = calendar(s)
            ok, err = s.removeCalendar_commit_error_(cal, True, None)
            print(f"removed scratch calendar: {bool(ok) and calendar(store()) is None}")
    name = f"results-{SOURCE.lower()}.json"
    with open(os.path.join(HERE, name), "w") as f:
        json.dump(res, f, indent=2)
        f.write("\n")


def timing() -> None:
    """When does a source change an alarm list: on save, or later, at sync?"""
    assert EXISTING, "timing runs against an existing calendar (SPIKE_CALENDAR)"
    print(f"before: left={sweep()}")
    s = store()
    cal = calendar(s)
    trail = []
    try:
        ids = {}
        for case in ("timed-six", "timed-abs"):
            _, kind, alarms = next(c for c in CASES if c[0] == case)
            e = EK.EKEvent.eventWithEventStore_(s)
            e.setTitle_(f"{PREFIX}{case} timing")
            e.setCalendar_(cal)
            start = DAY.replace(hour=10)
            e.setStartDate_(to_nsdate(start))
            e.setEndDate_(to_nsdate(start + timedelta(hours=1)))
            e.setAlarms_([alarm(x, kind, start) for x in alarms])
            ok, err = s.saveEvent_span_commit_error_(e, EK.EKSpanThisEvent, True, None)
            assert ok, err
            ids[case] = e.eventIdentifier()
        t0 = time.monotonic()
        for at in (0, 10, 30, 60, 120):
            time.sleep(max(0, at - (time.monotonic() - t0)))
            fresh = store()
            row = {"t": at}
            for case, ident in ids.items():
                ev = fresh.eventWithIdentifier_(ident)
                row[case] = [describe(x, None) for x in (ev.alarms() or [])]
            trail.append(row)
            print(json.dumps(row))
    finally:
        print(f"after: left={sweep()}")
    with open(os.path.join(HERE, f"results-timing-{SOURCE.lower()}.json"), "w") as f:
        json.dump(trail, f, indent=2)
        f.write("\n")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "main"
    if mode == "main":
        main()
    elif mode == "timing":
        timing()
    else:
        print(json.dumps({"create": create, "read": read}[mode]()))
