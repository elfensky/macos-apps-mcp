"""Phase 3 device tests — REAL EventKit on this Mac (containers, list create, ...).

Run manually, never in CI (no macOS / TCC there):

    uv run pytest -m integration tests/integration/test_eventkit_depth.py

Every item is titled with ``macos-apps-mcp-test:`` plus a per-run stamp (``PREFIX``)
and removed in teardown. Google variants (added in 03-04) need
``MACOS_APPS_IT_GOOGLE_CALENDAR_ID``. Later Phase 3 plans (03-03..03-07) extend this
module with their own device tests.
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime, timedelta
from types import SimpleNamespace

import EventKit as EK
import pytest
from dateutil.rrule import rrulestr

from macos_apps_mcp.adapters import reminders_store
from macos_apps_mcp.adapters.calendar import CalendarAdapter
from macos_apps_mcp.adapters.reminders import RemindersAdapter
from macos_apps_mcp.contracts import (
    CalendarEventData,
    Recurrence,
    ReminderData,
    dtstart_in_rule,
)
from macos_apps_mcp.eventkit import epoch_nsdate, from_nsdate, store, to_nsdate
from macos_apps_mcp.runtime import run_native

# Every test in this module touches real EventKit/TCC — mark them all at module level
# so a forgotten per-test decorator can never leak a live test into CI.
pytestmark = pytest.mark.integration

PREFIX = f"macos-apps-mcp-test: {time.strftime('%H%M%S')} "


@pytest.fixture
def ek_items():
    """Ids a test creates: reminders, reminder lists (calendar identifiers) and events
    (base ids). Teardown removes them all in one worker block, then proves no list
    carrying ``PREFIX`` survives."""
    items = SimpleNamespace(reminders=[], lists=[], events=[])
    yield items

    def _cleanup():
        s = store()
        for ident in items.reminders:
            r = s.calendarItemWithIdentifier_(ident)
            if r is not None:
                s.removeReminder_commit_error_(r, True, None)
        for ident in items.events:
            e = s.calendarItemWithIdentifier_(ident.rpartition("|")[0] or ident)
            if e is not None:
                s.removeEvent_span_commit_error_(e, EK.EKSpanFutureEvents, True, None)
        by_id = {
            c.calendarIdentifier(): c
            for c in s.calendarsForEntityType_(EK.EKEntityTypeReminder)
        }
        for ident in items.lists:
            if ident in by_id:
                s.removeCalendar_commit_error_(by_id[ident], True, None)
        return [
            c.title()
            for c in s.calendarsForEntityType_(EK.EKEntityTypeReminder)
            if c.title().startswith(PREFIX)
        ]

    assert run_native(_cleanup) == [], "test reminder lists left behind"


@pytest.fixture
def icloud_scratch():
    """An event calendar ``PREFIX + "scratch"`` on the source titled "iCloud" (the spike
    003 ``scratch_calendar`` shape). Yields its identifier; removed in teardown."""

    def _make():
        s = store()
        src = next(
            (
                x
                for x in s.sources()
                if x.title() == "iCloud"
                and x.calendarsForEntityType_(EK.EKEntityTypeEvent)
            ),
            None,
        )
        if src is None:
            return None
        cal = EK.EKCalendar.calendarForEntityType_eventStore_(EK.EKEntityTypeEvent, s)
        cal.setTitle_(PREFIX + "scratch")
        cal.setSource_(src)
        ok, err = s.saveCalendar_commit_error_(cal, True, None)
        assert ok, f"cannot create a scratch calendar on iCloud: {err}"
        return cal.calendarIdentifier()

    ident = run_native(_make)
    if ident is None:
        pytest.fail("no EventKit source titled 'iCloud' on this Mac — cannot run")
    yield ident

    def _remove():
        s = store()
        for c in s.calendarsForEntityType_(EK.EKEntityTypeEvent):
            if c.calendarIdentifier() == ident:
                s.removeCalendar_commit_error_(c, True, None)
        return [
            c.calendarIdentifier()
            for c in s.calendarsForEntityType_(EK.EKEntityTypeEvent)
        ]

    assert ident not in run_native(_remove), "scratch calendar left behind"


def test_create_reminder_list_on_default_source(ek_items):
    rem = RemindersAdapter()
    name = PREFIX + "list"
    pointer = rem.create_reminder_list(name)
    ek_items.lists.append(pointer.id)
    assert pointer.id in [p.id for p in rem.get_lists()]
    with pytest.raises(ValueError):  # an exact duplicate is refused
        rem.create_reminder_list(name)

    made = rem.create_reminder(ReminderData(title=PREFIX + "r", list_name=pointer.id))
    ek_items.reminders.append(made.id)
    found = rem.get_pointers(name)
    assert [p.id for p in found] == [made.id]
    assert found[0].folder == pointer.id


def test_reminders_read_carries_the_store_plane(ek_items):
    # The store plane (#91) on the real Mac. Parent and tag VALUES are proven on the
    # owner-built fixture (03-10); here the read must work end to end.
    rem = RemindersAdapter()
    pointer = rem.create_reminder_list(PREFIX + "store")
    ek_items.lists.append(pointer.id)
    made = rem.create_reminder(
        ReminderData(
            title=PREFIX + "store r",
            list_name=pointer.id,
            due=datetime.now() + timedelta(days=1),
        )
    )
    ek_items.reminders.append(made.id)

    out = rem.read(pointer.summary)
    assert "coverage" not in out, out.get("coverage")  # a denial = no Full Disk Access
    assert [(r["id"], r["folder"]) for r in out["results"]] == [(made.id, pointer.id)]

    tags, parents = reminders_store.tags_and_parents()
    assert isinstance(tags, dict) and isinstance(parents, dict)


def test_event_pointer_folder_is_its_calendar_id(icloud_scratch, ek_items):
    cal = CalendarAdapter()
    day = (datetime.now() + timedelta(days=2)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    made = cal.create_event(
        CalendarEventData(
            title=PREFIX + "event",
            start=day.replace(hour=10),
            end=day.replace(hour=11),
            calendar=icloud_scratch,
        )
    )
    ek_items.events.append(made.id)

    found = {p.id: p for p in cal.get_pointers(day.date().isoformat())}
    folder = found[made.id].folder
    assert folder == icloud_scratch
    assert folder in [p.id for p in cal.get_calendars()]

    window = cal.get_free_busy(
        day.replace(hour=9).isoformat(),
        day.replace(hour=12).isoformat(),
        calendars=[folder],
    )
    assert len(window["busy"]) == 1


def _second_tuesday(on_or_after):
    """The first second-Tuesday of a month that is ``on_or_after`` (a date)."""
    first = on_or_after.replace(day=1)
    while True:
        tuesday = first + timedelta(days=(1 - first.weekday()) % 7)
        second = tuesday + timedelta(days=7)
        if second >= on_or_after:
            return second
        first = (first.replace(day=28) + timedelta(days=4)).replace(day=1)


def test_reminder_byday_round_trip(ek_items):
    """D-11: a reminder takes BYDAY through the shared parser; a rename without
    ``recurrence`` is refused with re-send text that carries BYDAY, and that text is
    accepted back."""
    import re

    from macos_apps_mcp.contracts import Recurrence
    from macos_apps_mcp.errors import RecurrenceRequired

    rem = RemindersAdapter()
    made_list = rem.create_reminder_list(PREFIX + "byday")
    ek_items.lists.append(made_list.id)
    due = datetime.combine(
        _second_tuesday((datetime.now() + timedelta(days=7)).date()),
        datetime.min.time(),
    ).replace(hour=9)

    made = rem.create_reminder(  # returns, so verify-after-write passed
        ReminderData(
            title=PREFIX + "byday",
            due=due,
            list_name=made_list.id,
            recurrence=Recurrence.from_rrule("FREQ=MONTHLY;BYDAY=2TU;COUNT=6"),
        )
    )
    ek_items.reminders.append(made.id)

    renamed = ReminderData(
        title=PREFIX + "byday (renamed)", due=due, list_name=made_list.id
    )
    with pytest.raises(RecurrenceRequired) as refused:
        rem.update_reminder(made.id, renamed)
    text = re.search(r"\((FREQ=[^)]+)\)", str(refused.value)).group(1)
    assert "BYDAY=2TU" in text

    again = rem.update_reminder(
        made.id,
        ReminderData(
            title=renamed.title,
            due=due,
            list_name=made_list.id,
            recurrence=Recurrence.from_rrule(text),
        ),
    )
    ek_items.reminders.append(again.id)


# --- six-month RFC 5545 expansion on iCloud and Google (D-24, CAL-03, #90) -----------


def _sweep_prefixed(calendar_id: str) -> int:
    """Remove every series titled ``PREFIX…`` from today to today + 800 days in one
    calendar (``EKSpanFutureEvents`` — one removal ends a whole series); returns how
    many prefixed events remain (the Google ``left=0`` check, spike 003 method)."""

    def work():
        s = store()
        cal = s.calendarWithIdentifier_(calendar_id)
        lo = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        def mine():
            pred = s.predicateForEventsWithStartDate_endDate_calendars_(
                to_nsdate(lo), to_nsdate(lo + timedelta(days=800)), [cal]
            )
            found = s.eventsMatchingPredicate_(pred) or []
            return [e for e in found if e.title().startswith(PREFIX)]

        for _ in range(3):  # a series seen by a later occurrence may need a second pass
            idents = {str(e.eventIdentifier()) for e in mine()}
            if not idents:
                break
            for ident in idents:
                e = s.eventWithIdentifier_(ident)
                if e is not None:
                    s.removeEvent_span_commit_error_(
                        e, EK.EKSpanFutureEvents, True, None
                    )
        return len(mine())

    return run_native(work)


@pytest.fixture
def google_calendar():
    """The one existing Google calendar the owner names in
    ``MACOS_APPS_IT_GOOGLE_CALENDAR_ID`` (Google refuses a new calendar, EKErrorDomain
    17). Events written into it carry ``PREFIX``; teardown sweeps them and asserts
    ``left=0``. The calendar itself is never removed."""
    ident = os.environ.get("MACOS_APPS_IT_GOOGLE_CALENDAR_ID")
    if not ident:
        pytest.skip(
            "set MACOS_APPS_IT_GOOGLE_CALENDAR_ID to an existing Google calendar's "
            "id (from calendars())"
        )

    def _check():
        cal = store().calendarWithIdentifier_(ident)
        assert cal is not None, "MACOS_APPS_IT_GOOGLE_CALENDAR_ID names no calendar"
        assert cal.allowsContentModifications(), "that calendar is read-only"

    run_native(_check)
    yield ident
    assert _sweep_prefixed(ident) == 0, "test events left in the Google calendar"


@pytest.fixture(params=["icloud", "google"])
def target_calendar(request):
    """``(calendar_id, sync_wait_seconds)``: a fresh iCloud scratch calendar (60 s) or
    the owner's Google calendar (90 s), the waits spike 003 measured."""
    if request.param == "icloud":
        return request.getfixturevalue("icloud_scratch"), 60
    return request.getfixturevalue("google_calendar"), 90


# (name, RRULE): spike 003 SHAPES without yearly-weekno (BYWEEKNO is refused), plus the
# two shapes where python-dateutil diverges from RFC 5545 and EventKit was not probed.
_EXPANSION_SHAPES = [
    ("weekly-byday", "FREQ=WEEKLY;BYDAY=MO,WE,FR"),
    ("weekly-int2", "FREQ=WEEKLY;INTERVAL=2;BYDAY=TU,TH"),
    ("weekly-count", "FREQ=WEEKLY;BYDAY=MO,WE;COUNT=5"),
    ("monthly-2tu", "FREQ=MONTHLY;BYDAY=2TU"),
    ("monthly-last-fr", "FREQ=MONTHLY;BYDAY=-1FR"),
    ("monthly-5fr", "FREQ=MONTHLY;BYDAY=5FR"),
    ("monthly-every-mo", "FREQ=MONTHLY;BYDAY=MO"),
    ("monthly-15", "FREQ=MONTHLY;BYMONTHDAY=15"),
    ("monthly-1-15", "FREQ=MONTHLY;BYMONTHDAY=1,15"),
    ("monthly-last-day", "FREQ=MONTHLY;BYMONTHDAY=-1"),
    ("monthly-31", "FREQ=MONTHLY;BYMONTHDAY=31"),
    ("monthly-29", "FREQ=MONTHLY;BYMONTHDAY=29"),
    ("monthly-until", "FREQ=MONTHLY;BYMONTHDAY=15;UNTIL=20270115T235959"),
    ("monthly-last-wkday", "FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1"),
    ("monthly-bymonth", "FREQ=MONTHLY;BYMONTH=1,4,7,10;BYMONTHDAY=1"),
    ("daily-bymonth", "FREQ=DAILY;BYMONTH=12"),
    ("dtstart-mismatch", "FREQ=MONTHLY;BYDAY=2TU"),
    ("yearly-last-su-mar", "FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU"),
    ("yearly-jan-jul-1", "FREQ=YEARLY;BYMONTH=1,7;BYMONTHDAY=1"),
    ("yearly-yearday", "FREQ=YEARLY;BYYEARDAY=100"),
    ("yearly-4th-thu-nov", "FREQ=YEARLY;BYMONTH=11;BYDAY=TH;BYSETPOS=4"),
    ("monthly-mixed-byday", "FREQ=MONTHLY;BYDAY=1MO,FR"),
    ("weekly-bysetpos", "FREQ=WEEKLY;BYDAY=MO,WE,FR;BYSETPOS=-1"),
]
_FIRST_DAY = datetime(2027, 1, 4)
_SIX_MONTHS = timedelta(days=183)


def _first_dtstart(rrule: str) -> datetime:
    """10:00 on the first date on or after 2027-01-04 that the rule itself contains."""
    rule = Recurrence.from_rrule(rrule)
    for offset in range(800):
        d = _FIRST_DAY + timedelta(days=offset)
        if dtstart_in_rule(rule, d.date()):
            return d.replace(hour=10)
    raise AssertionError(f"no date within 800 days satisfies {rrule}")


def _hand_expected(name: str, dtstart: datetime, hi: datetime) -> set[datetime]:
    """RFC 5545 by stdlib date arithmetic for the two shapes dateutil gets wrong."""
    days = (dtstart + timedelta(days=i) for i in range((hi - dtstart).days + 1))
    if name == "monthly-mixed-byday":  # every Friday plus each month's first Monday
        return {
            d for d in days if d.weekday() == 4 or (d.weekday() == 0 and d.day <= 7)
        }
    # weekly-bysetpos: the last of MO/WE/FR in a Monday-based week is its Friday
    return {d for d in days if d.weekday() == 4}


def _read_occurrences(calendar_id, title, lo, hi) -> set[datetime]:
    def work():
        s = store()
        s.refreshSourcesIfNecessary()
        cal = s.calendarWithIdentifier_(calendar_id)
        pred = s.predicateForEventsWithStartDate_endDate_calendars_(
            to_nsdate(lo), to_nsdate(hi), [cal]
        )
        found = s.eventsMatchingPredicate_(pred) or []
        return {from_nsdate(e.startDate()) for e in found if e.title() == title}

    return run_native(work)


def test_recurrence_expansion_matches_rfc5545(target_calendar, ek_items):
    """D-24: every accepted shape, written through the real adapter, expands over six
    months (three years for YEARLY rules, as in the spike) to the RFC 5545 occurrences
    — ``set(dateutil) | {DTSTART}`` — on iCloud and on Google. Every mismatch is
    collected so one run reports them all."""
    calendar_id, sync_wait = target_calendar
    cal = CalendarAdapter()
    created, problems = {}, []
    for name, rrule in _EXPANSION_SHAPES:
        dtstart = (
            _FIRST_DAY.replace(hour=10)
            if name == "dtstart-mismatch"
            else _first_dtstart(rrule)
        )
        if "UNTIL=" in rrule:
            until = (dtstart + timedelta(days=120)).strftime("%Y%m%dT235959")
            rrule = re.sub(r"UNTIL=[^;]+", f"UNTIL={until}", rrule)
        try:
            made = cal.create_event(
                CalendarEventData(
                    title=PREFIX + name,
                    start=dtstart,
                    end=dtstart + timedelta(hours=1),
                    calendar=calendar_id,
                    recurrence=Recurrence.from_rrule(rrule),
                )
            )
        except Exception as ex:  # a shape EventKit refuses is a finding, not an abort
            problems.append((name, f"create failed: {type(ex).__name__}: {ex}"))
            continue
        ek_items.events.append(made.id)
        noted = "one extra first occurrence" in made.summary
        if noted != (name == "dtstart-mismatch"):
            problems.append((name, f"D-10 note present={noted}: {made.summary!r}"))
        created[name] = (rrule, dtstart)

    time.sleep(sync_wait)

    for name, (rrule, dtstart) in created.items():
        hi = dtstart + _SIX_MONTHS + timedelta(days=365 * 3 if "YEARLY" in rrule else 0)
        if name in ("monthly-mixed-byday", "weekly-bysetpos"):
            expected = _hand_expected(name, dtstart, hi)
        else:
            reference = rrulestr(rrule, dtstart=dtstart)
            expected = set(reference.between(dtstart, hi, inc=True)) | {dtstart}
        got = _read_occurrences(
            calendar_id, PREFIX + name, dtstart, hi + timedelta(hours=1)
        )
        if got != expected:
            problems.append(
                (
                    name,
                    {
                        "missing": sorted(d.isoformat() for d in expected - got)[:4],
                        "extra": sorted(d.isoformat() for d in got - expected)[:4],
                    },
                )
            )
    assert problems == []


# --- alarms on iCloud and Google (CAL-01, CAL-02, #89) -------------------------------


def _read_alarms(calendar_id, title, lo, hi):
    """Every occurrence of ``title`` in [lo, hi) as ``(start, minutes_before, fires,
    absolute)`` read fresh from the store: ``minutes_before`` sorted, ``fires`` the
    fire instants (``startDate`` plus ``relativeOffset``, spike 008) as naive local
    datetimes, ``absolute`` how many alarms carry an absolute date."""

    def work():
        s = store()
        s.refreshSourcesIfNecessary()
        cal = s.calendarWithIdentifier_(calendar_id)
        pred = s.predicateForEventsWithStartDate_endDate_calendars_(
            to_nsdate(lo), to_nsdate(hi), [cal]
        )
        out = []
        for e in s.eventsMatchingPredicate_(pred) or []:
            if e.title() != title:
                continue
            start = e.startDate().timeIntervalSince1970()
            alarms = e.alarms() or []
            out.append(
                (
                    int(start),
                    sorted(-round(a.relativeOffset() / 60) for a in alarms),
                    sorted(int(start + a.relativeOffset()) for a in alarms),
                    sum(a.absoluteDate() is not None for a in alarms),
                )
            )
        return sorted(out)

    return [
        (
            from_nsdate(epoch_nsdate(start)),
            minutes,
            [from_nsdate(epoch_nsdate(f)) for f in fires],
            absolute,
        )
        for start, minutes, fires, absolute in run_native(work)
    ]


def _dst_change_day(day: datetime) -> bool:
    """True when the local UTC offset differs between this midnight and the next."""
    return (
        day.astimezone().utcoffset()
        != (day + timedelta(days=1)).astimezone().utcoffset()
    )


def test_timed_alarms_round_trip(target_calendar, ek_items):
    """D-01, D-04: ``alarms=[15, 60]`` lands as two relative alarms and survives the
    sync; an update that omits ``alarms`` keeps them; ``alarms=[]`` removes them."""
    calendar_id, sync_wait = target_calendar
    cal = CalendarAdapter()
    start = datetime(2027, 2, 15, 10)
    end = start + timedelta(hours=1)
    title = PREFIX + "timed alarms"
    day = (start.replace(hour=0), start.replace(hour=0) + timedelta(days=1))

    made = cal.create_event(  # returns, so verify-after-write passed
        CalendarEventData(
            title=title,
            start=start,
            end=end,
            calendar=calendar_id,
            alarms=(15, 60),
        )
    )
    ek_items.events.append(made.id)
    time.sleep(sync_wait)
    ((_, minutes, _, absolute),) = _read_alarms(calendar_id, title, *day)
    assert minutes == [15, 60] and absolute == 0

    renamed = PREFIX + "timed alarms (renamed)"
    cal.update_event(  # alarms omitted: the event's own alarms stay
        made.id,
        CalendarEventData(title=renamed, start=start, end=end, calendar=calendar_id),
    )
    ((_, minutes, _, absolute),) = _read_alarms(calendar_id, renamed, *day)
    assert minutes == [15, 60] and absolute == 0

    cal.update_event(
        made.id,
        CalendarEventData(
            title=renamed, start=start, end=end, calendar=calendar_id, alarms=()
        ),
    )
    time.sleep(sync_wait)
    ((_, minutes, _, _),) = _read_alarms(calendar_id, renamed, *day)
    assert minutes == []


def test_all_day_alarms_fire_on_the_right_day(target_calendar, ek_items):
    """D-02, D-05: all-day offsets count from local midnight of the event's day, on a
    floating event, across a DST change."""
    calendar_id, sync_wait = target_calendar
    cal = CalendarAdapter()

    single = PREFIX + "all-day alarms"
    day = datetime(2027, 2, 15)
    made = cal.create_event(
        CalendarEventData(
            title=single,
            start=day,
            end=day,
            all_day=True,
            calendar=calendar_id,
            alarms=(-540, 900),
        )
    )
    ek_items.events.append(made.id)

    series = PREFIX + "all-day alarm series"
    first = datetime(2027, 3, 15)  # weekly: 15, 22, 29 (after the EU DST start), 5 Apr
    made = cal.create_event(
        CalendarEventData(
            title=series,
            start=first,
            end=first,
            all_day=True,
            calendar=calendar_id,
            recurrence=Recurrence.from_rrule("FREQ=WEEKLY;COUNT=4"),
            alarms=(-540,),
        )
    )
    ek_items.events.append(made.id)
    time.sleep(sync_wait)

    ((_, minutes, fires, absolute),) = _read_alarms(
        calendar_id, single, day - timedelta(days=2), day + timedelta(days=2)
    )
    assert minutes == [-540, 900] and absolute == 0
    assert fires == [datetime(2027, 2, 14, 9), datetime(2027, 2, 15, 9)]

    occurrences = _read_alarms(calendar_id, series, first, first + timedelta(days=30))
    assert len(occurrences) == 4
    for start, minutes, (fire,), absolute in occurrences:
        assert minutes == [-540] and absolute == 0
        assert fire.date() == start.date(), f"{start}: fires on {fire}"
        if not _dst_change_day(start):
            assert fire.hour == 9, f"{start}: fires at {fire}"


def test_all_day_without_alarms_reads_back_empty(target_calendar, ek_items):
    """D-04: ``alarms=[]`` on an all-day event leaves none — Google injects no
    default."""
    calendar_id, sync_wait = target_calendar
    day = datetime(2027, 2, 15)
    title = PREFIX + "all-day no alarms"
    made = CalendarAdapter().create_event(
        CalendarEventData(
            title=title,
            start=day,
            end=day,
            all_day=True,
            calendar=calendar_id,
            alarms=(),
        )
    )
    ek_items.events.append(made.id)
    time.sleep(sync_wait)
    ((_, minutes, _, _),) = _read_alarms(
        calendar_id, title, day - timedelta(days=1), day + timedelta(days=2)
    )
    assert minutes == []
