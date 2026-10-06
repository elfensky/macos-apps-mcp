"""Spike 003 — does EventKit store all-day events and RRULE shapes exactly as asked?

Writes: one scratch iCloud calendar `gsd-spike-003`, removed at the end (also on error).
dateutil is the RFC 5545 reference and is NOT a project dependency:

    uv run --with python-dateutil python \
        .planning/spikes/003-eventkit-allday-rrule/probe_eventkit.py [rrule|allday|all]

Prints only scratch-event data. Writes results-*.json beside this file.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import EventKit as EK
from dateutil.rrule import rrulestr

from macos_apps_mcp.eventkit import from_nsdate, to_nsdate

HERE = Path(__file__).parent
CAL_TITLE = "gsd-spike-003"
WD = {"SU": 1, "MO": 2, "TU": 3, "WE": 4, "TH": 5, "FR": 6, "SA": 7}  # EKWeekday
FREQ = {
    "DAILY": EK.EKRecurrenceFrequencyDaily,
    "WEEKLY": EK.EKRecurrenceFrequencyWeekly,
    "MONTHLY": EK.EKRecurrenceFrequencyMonthly,
    "YEARLY": EK.EKRecurrenceFrequencyYearly,
}

# (name, RRULE, DTSTART) — DTSTART is local wall time, Europe/Brussels on this Mac.
SHAPES = [
    ("weekly-byday", "FREQ=WEEKLY;BYDAY=MO,WE,FR", "2026-10-05T10:00"),
    ("weekly-int2", "FREQ=WEEKLY;INTERVAL=2;BYDAY=TU,TH", "2026-10-06T10:00"),
    ("weekly-count", "FREQ=WEEKLY;BYDAY=MO,WE;COUNT=5", "2026-10-05T10:00"),
    ("monthly-2tu", "FREQ=MONTHLY;BYDAY=2TU", "2026-10-13T10:00"),
    ("monthly-last-fr", "FREQ=MONTHLY;BYDAY=-1FR", "2026-10-30T10:00"),
    ("monthly-5fr", "FREQ=MONTHLY;BYDAY=5FR", "2026-10-30T10:00"),
    ("monthly-every-mo", "FREQ=MONTHLY;BYDAY=MO", "2026-10-05T10:00"),
    ("monthly-15", "FREQ=MONTHLY;BYMONTHDAY=15", "2026-10-15T10:00"),
    ("monthly-1-15", "FREQ=MONTHLY;BYMONTHDAY=1,15", "2026-10-01T10:00"),
    ("monthly-last-day", "FREQ=MONTHLY;BYMONTHDAY=-1", "2026-10-31T10:00"),
    ("monthly-31", "FREQ=MONTHLY;BYMONTHDAY=31", "2026-10-31T10:00"),
    ("monthly-29", "FREQ=MONTHLY;BYMONTHDAY=29", "2026-10-29T10:00"),
    (
        "monthly-until",
        "FREQ=MONTHLY;BYMONTHDAY=15;UNTIL=20270115T235959",
        "2026-10-15T10:00",
    ),
    (
        "monthly-last-wkday",
        "FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1",
        "2026-10-30T10:00",
    ),
    (
        "monthly-bymonth",
        "FREQ=MONTHLY;BYMONTH=1,4,7,10;BYMONTHDAY=1",
        "2026-10-01T10:00",
    ),
    ("daily-bymonth", "FREQ=DAILY;BYMONTH=12", "2026-12-01T10:00"),
    ("dtstart-mismatch", "FREQ=MONTHLY;BYDAY=2TU", "2026-10-01T10:00"),
    ("yearly-last-su-mar", "FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU", "2027-03-28T10:00"),
    ("yearly-jan-jul-1", "FREQ=YEARLY;BYMONTH=1,7;BYMONTHDAY=1", "2027-01-01T10:00"),
    ("yearly-weekno", "FREQ=YEARLY;BYWEEKNO=20;BYDAY=MO", "2027-05-17T10:00"),
    ("yearly-yearday", "FREQ=YEARLY;BYYEARDAY=100", "2027-04-10T10:00"),
    (
        "yearly-4th-thu-nov",
        "FREQ=YEARLY;BYMONTH=11;BYDAY=TH;BYSETPOS=4",
        "2026-11-26T10:00",
    ),
]


# Follow-up: isolate the BYWEEKNO under-expansion seen in the first matrix run.
WEEKNO_SHAPES = [
    ("weekno-20-mo", "FREQ=YEARLY;BYWEEKNO=20;BYDAY=MO", "2027-05-17T10:00"),
    ("weekno-20-allweek", "FREQ=YEARLY;BYWEEKNO=20", "2027-05-17T10:00"),
    ("weekno-20-21-mo", "FREQ=YEARLY;BYWEEKNO=20,21;BYDAY=MO", "2027-05-17T10:00"),
    ("weekno-last-mo", "FREQ=YEARLY;BYWEEKNO=-1;BYDAY=MO", "2026-12-28T10:00"),
    ("weekno-count3", "FREQ=YEARLY;BYWEEKNO=20;BYDAY=MO;COUNT=3", "2027-05-17T10:00"),
]


def parse(rrule: str) -> dict:
    """RRULE → canonical dict (the comparison form for request vs readback)."""
    p = dict(kv.split("=", 1) for kv in rrule.split(";"))
    ints = lambda k: sorted(int(x) for x in p[k].split(",")) if k in p else []  # noqa: E731
    byday = []
    for d in p.get("BYDAY", "").split(",") if "BYDAY" in p else []:
        byday.append((int(d[:-2] or 0), d[-2:]))
    until = p.get("UNTIL")
    return {
        "freq": p["FREQ"],
        "interval": int(p.get("INTERVAL", 1)),
        "byday": sorted(byday),
        "bymonthday": ints("BYMONTHDAY"),
        "bymonth": ints("BYMONTH"),
        "byweekno": ints("BYWEEKNO"),
        "byyearday": ints("BYYEARDAY"),
        "bysetpos": ints("BYSETPOS"),
        "count": int(p.get("COUNT", 0)),
        "until": until[:8] if until else None,
    }


def to_ek(c: dict) -> EK.EKRecurrenceRule:
    dow = [
        EK.EKRecurrenceDayOfWeek.dayOfWeek_weekNumber_(WD[wd], n)
        for n, wd in c["byday"]
    ]
    end = None
    if c["count"]:
        end = EK.EKRecurrenceEnd.recurrenceEndWithOccurrenceCount_(c["count"])
    elif c["until"]:
        u = datetime.strptime(c["until"], "%Y%m%d").replace(hour=23, minute=59)
        end = EK.EKRecurrenceEnd.recurrenceEndWithEndDate_(to_nsdate(u))
    return EK.EKRecurrenceRule.alloc().initRecurrenceWithFrequency_interval_daysOfTheWeek_daysOfTheMonth_monthsOfTheYear_weeksOfTheYear_daysOfTheYear_setPositions_end_(  # noqa: E501
        FREQ[c["freq"]],
        c["interval"],
        dow or None,
        c["bymonthday"] or None,
        c["bymonth"] or None,
        c["byweekno"] or None,
        c["byyearday"] or None,
        c["bysetpos"] or None,
        end,
    )


def from_ek(r) -> dict:
    names = {v: k for k, v in WD.items()}
    freq = {int(v): k for k, v in FREQ.items()}[int(r.frequency())]
    end = r.recurrenceEnd()
    until = None
    if end is not None and end.endDate() is not None:
        until = from_nsdate(end.endDate()).strftime("%Y%m%d")
    ints = lambda xs: sorted(int(x) for x in (xs or []))  # noqa: E731
    return {
        "freq": freq,
        "interval": int(r.interval()),
        "byday": sorted(
            (int(d.weekNumber()), names[int(d.dayOfTheWeek())])
            for d in (r.daysOfTheWeek() or [])
        ),
        "bymonthday": ints(r.daysOfTheMonth()),
        "bymonth": ints(r.monthsOfTheYear()),
        "byweekno": ints(r.weeksOfTheYear()),
        "byyearday": ints(r.daysOfTheYear()),
        "bysetpos": ints(r.setPositions()),
        "count": int(end.occurrenceCount()) if end is not None else 0,
        "until": until,
    }


SOURCE = os.environ.get("SPIKE_SOURCE", "iCloud")  # SPIKE_SOURCE=Google to compare
# A source that refuses new calendars (Google, EKErrorDomain 17) needs an EXISTING
# calendar: SPIKE_CALENDAR=<title>. That calendar is never removed — only the events
# titled PREFIX… are, by id and then by a sweep.
EXISTING = os.environ.get("SPIKE_CALENDAR")
PREFIX = f"{CAL_TITLE} "


def scratch_calendar(s) -> object:
    src = next(
        x
        for x in s.sources()
        if x.title() == SOURCE and x.calendarsForEntityType_(EK.EKEntityTypeEvent)
    )
    cal = EK.EKCalendar.calendarForEntityType_eventStore_(EK.EKEntityTypeEvent, s)
    cal.setTitle_(CAL_TITLE)
    cal.setSource_(src)
    ok, err = s.saveCalendar_commit_error_(cal, True, None)
    if not ok:
        raise SystemExit(f"cannot create a scratch calendar in {SOURCE}: {err}")
    return cal


def remove_scratch(s) -> None:
    for c in s.calendarsForEntityType_(EK.EKEntityTypeEvent):
        if c.title() == CAL_TITLE:
            ok, err = s.removeCalendar_commit_error_(c, True, None)
            print(f"removed scratch calendar: {ok} {err or ''}")


def existing_calendar(s) -> object:
    cals = [
        c
        for x in s.sources()
        if x.title() == SOURCE
        for c in x.calendarsForEntityType_(EK.EKEntityTypeEvent)
        if c.title() == EXISTING and c.allowsContentModifications()
    ]
    if len(cals) != 1:
        raise SystemExit(
            f"expected one writable {SOURCE}/{EXISTING}, found {len(cals)}"
        )
    return cals[0]


def sweep_events(cal) -> int:
    """Delete every series titled PREFIX… in cal; return how many are left after."""
    s = EK.EKEventStore.alloc().init()
    cal = s.calendarWithIdentifier_(cal.calendarIdentifier())
    lo, hi = datetime(2026, 9, 28), datetime(2030, 9, 1)

    def mine():
        pred = s.predicateForEventsWithStartDate_endDate_calendars_(
            to_nsdate(lo), to_nsdate(hi), [cal]
        )
        evs = s.eventsMatchingPredicate_(pred) or []
        return {str(e.eventIdentifier()) for e in evs if e.title().startswith(PREFIX)}

    for ident in mine():
        e = s.eventWithIdentifier_(ident)
        if e is not None:
            s.removeEvent_span_commit_error_(e, EK.EKSpanFutureEvents, True, None)
    left = len(mine())
    print(f"swept {CAL_TITLE} events from {SOURCE}/{EXISTING}: left={left}")
    return left


def occurrences(s, cal, title: str, lo: datetime, hi: datetime) -> list[datetime]:
    pred = s.predicateForEventsWithStartDate_endDate_calendars_(
        to_nsdate(lo), to_nsdate(hi), [cal]
    )
    evs = s.eventsMatchingPredicate_(pred) or []
    return sorted(from_nsdate(e.startDate()) for e in evs if e.title() == title)


# ---------------------------------------------------------------- RRULE matrix


def run_rrule(s, cal, shapes=SHAPES, sync_wait: int = 60) -> list[dict]:
    rows, ids = [], {}
    for name, rrule, dts in shapes:
        dtstart = datetime.fromisoformat(dts)
        years = 3 if "YEARLY" in rrule else 0
        hi = dtstart + timedelta(days=183 + 365 * years)
        req = parse(rrule)
        row = {"name": name, "rrule": rrule, "dtstart": dts}
        try:
            rule = to_ek(req)
        except Exception as ex:  # an ObjC exception surfaces as a Python error
            rows.append({**row, "verdict": "REJECTED at rule init", "error": str(ex)})
            continue
        e = EK.EKEvent.eventWithEventStore_(s)
        e.setTitle_(PREFIX + name)
        e.setStartDate_(to_nsdate(dtstart))
        e.setEndDate_(to_nsdate(dtstart + timedelta(hours=1)))
        e.setCalendar_(cal)
        e.setRecurrenceRules_([rule])
        ok, err = s.saveEvent_span_commit_error_(e, EK.EKSpanFutureEvents, True, None)
        if not ok:
            rows.append({**row, "verdict": "REJECTED at save", "error": str(err)})
            continue
        ids[name] = str(e.eventIdentifier())
        back = from_ek(e.recurrenceRules()[0])
        got = occurrences(s, cal, PREFIX + name, dtstart, hi)
        ref = list(rrulestr(rrule, dtstart=dtstart).between(dtstart, hi, inc=True))
        ref_rfc = sorted(set(ref) | {dtstart})  # RFC 5545: DTSTART is always 1st
        saved_start = from_nsdate(e.startDate())
        diff_rule = {k: (req[k], back[k]) for k in req if req[k] != back[k]}
        if got == ref and not diff_rule:
            verdict = "EXACT"
        elif got == ref_rfc and not diff_rule:
            verdict = "EXACT (DTSTART counted, RFC)"
        elif diff_rule:
            verdict = "RULE CHANGED"
        else:
            verdict = "OCCURRENCES DIFFER"
        missing = [d.isoformat() for d in ref if d not in got][:4]
        extra = [d.isoformat() for d in got if d not in ref][:4]
        rows.append(
            {
                **row,
                "verdict": verdict,
                "saved_start": saved_start.isoformat(),
                "saved_rule": back,
                "n_ek": len(got),
                "n_ref": len(ref),
                "rule_diff": diff_rule,
                "missing": missing,
                "extra": extra,
            }
        )
        print(
            f"{name:20} {verdict:30} ek={len(got):3} ref={len(ref):3} "
            f"{'rule ' + str(diff_rule) if diff_rule else ''}"
            f"{' missing ' + str(missing) if missing else ''}"
            f"{' extra ' + str(extra) if extra else ''}"
        )

    # After iCloud sync: does the server hand back a different rule?
    if not sync_wait:
        return rows
    print(f"waiting {sync_wait}s for {SOURCE} sync, then re-reading rules …")
    time.sleep(sync_wait)
    s2 = EK.EKEventStore.alloc().init()
    s2.refreshSourcesIfNecessary()
    time.sleep(5)
    for r in rows:
        ident = ids.get(r["name"])
        if not ident:
            continue
        e2 = s2.eventWithIdentifier_(ident)
        if e2 is None or not e2.recurrenceRules():
            r["after_sync"] = "GONE or rule dropped"
        else:
            b2 = from_ek(e2.recurrenceRules()[0])
            r["after_sync"] = "same" if b2 == r["saved_rule"] else str(b2)
    changed = [r["name"] for r in rows if r.get("after_sync") not in (None, "same")]
    print(f"rules changed after sync: {changed or 'none'}")
    return rows


# ------------------------------------------------------ all-day × time zone

ZONES = ["Europe/Brussels", "Pacific/Auckland", "America/Los_Angeles", "UTC"]
CREATORS = ZONES[:3]


def child(mode: str, tz: str, cal_id: str, *extra: str) -> list[dict]:
    env = {**os.environ, "TZ": tz}
    p = subprocess.run(
        [sys.executable, __file__, mode, cal_id, *extra],
        env=env,
        capture_output=True,
        text=True,
    )
    if p.returncode:
        raise RuntimeError(f"{mode} in {tz} failed:\n{p.stderr[-2000:]}")
    return json.loads(p.stdout.strip().splitlines()[-1])


def allday_create(cal_id: str) -> list[dict]:
    """Create via the REAL adapter path (naive-midnight bounds, verify-after-write)."""
    from macos_apps_mcp.adapters.calendar import CalendarAdapter
    from macos_apps_mcp.contracts import CalendarEventData, Recurrence

    tz = os.environ["TZ"]
    a = CalendarAdapter()
    one = datetime(2026, 10, 26)
    rec = datetime(2026, 10, 19)
    made = []
    for title, d, r in [
        (f"allday-{tz}", one, None),
        (f"allday-rec-{tz}", rec, Recurrence.from_rrule("FREQ=WEEKLY;COUNT=4")),
    ]:
        try:
            p = a.create_event(
                CalendarEventData(
                    title=title,
                    start=d,
                    end=d,
                    calendar=cal_id,
                    all_day=True,
                    recurrence=r,
                )
            )
            made.append({"title": title, "id": p.id})
        except Exception as ex:  # VerificationFailed is itself a finding
            made.append({"title": title, "error": f"{type(ex).__name__}: {ex}"})
    return made


# Dates where local midnight does not exist: DST starts AT 00:00 in these zones.
GAP_CASES = [("Asia/Beirut", date(2027, 3, 28)), ("America/Santiago", date(2027, 9, 5))]


def gap_create(cal_id: str, day: str) -> list[dict]:
    """One all-day event on a day whose local midnight is skipped by DST."""
    from macos_apps_mcp.adapters.calendar import CalendarAdapter
    from macos_apps_mcp.contracts import CalendarEventData

    d = datetime.fromisoformat(day)
    title = f"gap-{os.environ['TZ']}"
    try:
        p = CalendarAdapter().create_event(
            CalendarEventData(
                title=title, start=d, end=d, calendar=cal_id, all_day=True
            )
        )
        return [{"title": title, "id": p.id}]
    except Exception as ex:
        return [{"title": title, "error": f"{type(ex).__name__}: {ex}"}]


def run_gap(cal) -> dict:
    from zoneinfo import ZoneInfo

    cal_id = str(cal.calendarIdentifier())
    out = {}
    for tz, day in GAP_CASES:
        wall = datetime(day.year, day.month, day.day, tzinfo=ZoneInfo(tz))
        exists = wall.astimezone(ZoneInfo("UTC")).astimezone(ZoneInfo(tz)) == wall
        made = child("gap-create", tz, cal_id, day.isoformat())
        print(f"{tz}: local midnight on {day} exists={exists}; create -> {made}")
        out[tz] = {"midnight_exists": exists, "created": made, "read": {}}
    time.sleep(3)
    for reader in [tz for tz, _ in GAP_CASES] + ["Europe/Brussels", "UTC"]:
        evs = child("allday-read", reader, cal_id)
        for tz, day in GAP_CASES:
            got = [e for e in evs if e["title"] == f"gap-{tz}"]
            res = [(e["start"], e["all_day"], e["tz"]) for e in got]
            ok = [datetime.fromisoformat(e["start"]).date() for e in got] == [day]
            out[tz]["read"][reader] = {"ok": ok, "events": res}
            print(f"  gap-{tz:17} read {reader:17}: {'OK ' if ok else 'WRONG'} {res}")
    return out


def allday_read(cal_id: str) -> list[dict]:
    s = EK.EKEventStore.alloc().init()
    cal = s.calendarWithIdentifier_(cal_id)
    lo, hi = datetime(2026, 10, 1), datetime(2027, 10, 1)
    pred = s.predicateForEventsWithStartDate_endDate_calendars_(
        to_nsdate(lo), to_nsdate(hi), [cal]
    )
    return [
        {
            "title": e.title(),
            "all_day": bool(e.isAllDay()),
            "tz": e.timeZone().name() if e.timeZone() else None,
            "start": from_nsdate(e.startDate()).isoformat(),
            "end": from_nsdate(e.endDate()).isoformat(),
        }
        for e in (s.eventsMatchingPredicate_(pred) or [])
    ]


def run_allday(cal) -> dict:
    cal_id = str(cal.calendarIdentifier())
    created = {tz: child("allday-create", tz, cal_id) for tz in CREATORS}
    time.sleep(3)
    seen = {tz: child("allday-read", tz, cal_id) for tz in ZONES}
    want_one = {date(2026, 10, 26)}
    want_rec = {date(2026, 10, 19) + timedelta(weeks=k) for k in range(4)}
    verdicts = {}
    for reader, evs in seen.items():
        for creator in CREATORS:
            for kind, want in (("single", want_one), ("weekly", want_rec)):
                t = f"allday-{creator}" if kind == "single" else f"allday-rec-{creator}"
                got = [e for e in evs if e["title"] == t]
                days = {datetime.fromisoformat(e["start"]).date() for e in got}
                ok = days == want and all(
                    e["all_day"]
                    and e["tz"] is None
                    and datetime.fromisoformat(e["start"]).time().hour == 0
                    for e in got
                )
                key = f"{kind:6} created {creator:19} read {reader}"
                verdicts[key] = "OK" if ok else f"WRONG days={sorted(map(str, days))}"
                print(f"{key}: {verdicts[key]}")
    sample = seen["Pacific/Auckland"][:2]
    return {"created": created, "verdicts": verdicts, "sample_read": sample}


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode in ("allday-create", "allday-read", "gap-create"):
        fn = {
            "allday-create": allday_create,
            "allday-read": allday_read,
            "gap-create": gap_create,
        }[mode]
        print(json.dumps(fn(*sys.argv[2:])))
        return
    s = EK.EKEventStore.alloc().init()
    if EXISTING:
        if mode != "rrule":
            raise SystemExit("SPIKE_CALENDAR is for the rrule matrix only")
        cal = existing_calendar(s)
        sweep_events(cal)  # a previous crashed run
        try:
            res = run_rrule(s, cal, sync_wait=90)
            name = f"results-rrule-{SOURCE.lower()}.json"
            (HERE / name).write_text(json.dumps(res, indent=1))
        finally:
            sweep_events(cal)
        return
    remove_scratch(s)  # a previous crashed run
    cal = scratch_calendar(s)
    try:
        if mode in ("rrule", "all"):
            res = run_rrule(s, cal)
            (HERE / f"results-rrule-{SOURCE.lower()}.json").write_text(
                json.dumps(res, indent=1)
            )
        if mode in ("allday", "all"):
            res = run_allday(cal)
            (HERE / "results-allday.json").write_text(json.dumps(res, indent=1))
        if mode in ("weekno", "all"):
            res = run_rrule(s, cal, WEEKNO_SHAPES, sync_wait=0)
            (HERE / "results-weekno.json").write_text(json.dumps(res, indent=1))
        if mode in ("gap", "all"):
            res = run_gap(cal)
            (HERE / "results-gap.json").write_text(json.dumps(res, indent=1))
    finally:
        remove_scratch(EK.EKEventStore.alloc().init())


if __name__ == "__main__":
    main()
