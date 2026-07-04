"""Unit tests for the calendar adapter — pure mapping + range parsing (no
EventKit writes)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import EventKit as EK
import Foundation as F
import pytest

from mac_mcp.adapters.calendar import (
    _all_day_bounds,
    _event_pointer,
    _event_summary,
    _range,
    _refetch_event,
    _resolve_calendar,
    _resolve_span,
    _verify_event,
)
from mac_mcp.contracts import CalendarEventData, Pointer, Recurrence
from mac_mcp.runtime import SpanRequired, VerificationFailed


def _ns(dt: datetime):
    return F.NSDate.dateWithTimeIntervalSince1970_(dt.timestamp())


def _fake_event(title, ident, start, end, all_day=False):
    return SimpleNamespace(
        title=lambda: title,
        calendarItemIdentifier=lambda: ident,
        startDate=lambda: _ns(start),
        endDate=lambda: _ns(end),
        isAllDay=lambda: all_day,
    )


def test_summary_timed():
    e = _fake_event(
        "Standup", "E-1", datetime(2026, 6, 23, 9, 0), datetime(2026, 6, 23, 9, 15)
    )
    assert _event_summary(e) == "Standup 09:00–09:15"


def test_summary_all_day():
    e = _fake_event(
        "Holiday", "E-2", datetime(2026, 6, 23), datetime(2026, 6, 24), all_day=True
    )
    assert _event_summary(e) == "Holiday (all day 2026-06-23)"


def test_pointer_shape():
    start = datetime(2026, 6, 23, 9, 0)
    e = _fake_event("Standup", "E-1", start, datetime(2026, 6, 23, 9, 15))
    p = _event_pointer(e)
    # id = <calendarItemIdentifier>|<occurrence-start-epoch>: addresses one occurrence
    assert isinstance(p, Pointer)
    assert p.id == f"E-1|{int(start.timestamp())}"
    assert p.deeplink.startswith("calshow:")


def test_range_today_is_one_day():
    start, end = _range("today")
    assert (end - start).days == 1 and start.hour == 0


def test_range_explicit_date():
    start, end = _range("2026-12-25")
    assert start == datetime(2026, 12, 25) and (end - start).days == 1


def test_all_day_bounds_same_day_stays_one_day():
    # a timed same-day range → date-only bounds with end == start. EventKit's all-day
    # end is inclusive (verified on-device), so end == start IS a single day — bumping
    # it a day would make a 2-day event.
    s, e = _all_day_bounds(datetime(2026, 7, 1, 9, 30), datetime(2026, 7, 1, 10, 45))
    assert s == datetime(2026, 7, 1)
    assert e == datetime(2026, 7, 1)


def test_all_day_bounds_preserves_multiday_span():
    # Jul 1 09:00 → Jul 3 10:00 spans 3 calendar days; inclusive end keeps end == Jul 3.
    s, e = _all_day_bounds(datetime(2026, 7, 1, 9, 0), datetime(2026, 7, 3, 10, 0))
    assert s == datetime(2026, 7, 1) and e == datetime(2026, 7, 3)


def test_all_day_bounds_clamps_reversed_span_to_one_day():
    # a genuinely reversed range (end before start) clamps to a single day, not an
    # invalid reversed span handed to EventKit.
    s, e = _all_day_bounds(datetime(2026, 7, 10), datetime(2026, 7, 5))
    assert s == datetime(2026, 7, 10) and e == datetime(2026, 7, 10)


def test_all_day_bounds_drops_tzinfo_so_mixed_naive_aware_cannot_crash():
    # a tz-aware start + naive end (each parsed independently at the tool boundary) must
    # not raise on the e < s compare; all-day bounds are a date, so tz is dropped.
    aware = datetime(2026, 7, 1, 9, 0, tzinfo=UTC)
    s, e = _all_day_bounds(aware, datetime(2026, 7, 1, 10, 0))
    assert s == datetime(2026, 7, 1) and e == datetime(2026, 7, 1)
    assert s.tzinfo is None and e.tzinfo is None


def _fake_store(cal_names, default="Home"):
    cals = [SimpleNamespace(title=lambda n=n: n) for n in cal_names]
    return SimpleNamespace(
        calendarsForEntityType_=lambda _e: cals,
        defaultCalendarForNewEvents=lambda: SimpleNamespace(title=lambda: default),
    )


def test_resolve_named_calendar():
    s = _fake_store(["Work", "Personal"])
    assert _resolve_calendar(s, "Work").title() == "Work"


def test_resolve_default_when_none():
    s = _fake_store(["Work"])
    assert _resolve_calendar(s, None).title() == "Home"


def test_resolve_missing_calendar_raises():
    s = _fake_store(["Work"])
    with pytest.raises(ValueError, match="no calendar named"):
        _resolve_calendar(s, "Nope")


# --- verify-after-write (#49) --------------------------------------------------------


def _fake_rule(freq=0, interval=1, count=None):
    # freq is the EKRecurrenceFrequency int (daily=0, weekly=1, monthly=2, yearly=3).
    end = None if count is None else SimpleNamespace(occurrenceCount=lambda: count)
    return SimpleNamespace(
        frequency=lambda: freq, interval=lambda: interval, recurrenceEnd=lambda: end
    )


def _fake_persisted_event(
    title="Standup",
    start=datetime(2026, 6, 24, 9, 0),
    end=datetime(2026, 6, 24, 9, 15),
    all_day=False,
    location=None,
    notes=None,
    cal_title="Work",
    rule=None,
):
    return SimpleNamespace(
        title=lambda: title,
        startDate=lambda: _ns(start),
        endDate=lambda: _ns(end),
        isAllDay=lambda: all_day,
        location=lambda: location,
        notes=lambda: notes,
        calendar=lambda: SimpleNamespace(title=lambda: cal_title),
        recurrenceRules=lambda: [rule] if rule is not None else None,
    )


def test_verify_event_passes_on_timed_match():
    data = CalendarEventData(
        title="Standup",
        start=datetime(2026, 6, 24, 9, 0),
        end=datetime(2026, 6, 24, 9, 15),
        calendar="Work",
    )
    _verify_event(_fake_persisted_event(), "E-1|x", data, "Work")  # no raise


def test_verify_event_none_fresh_is_rollback():
    data = CalendarEventData(
        title="x", start=datetime(2026, 6, 24, 9, 0), end=datetime(2026, 6, 24, 9, 15)
    )
    with pytest.raises(VerificationFailed, match="could not be re-fetched"):
        _verify_event(None, "E-1|x", data, "Work")


def test_verify_event_dropped_title_raises():
    data = CalendarEventData(
        title="Standup",
        start=datetime(2026, 6, 24, 9, 0),
        end=datetime(2026, 6, 24, 9, 15),
    )
    fresh = _fake_persisted_event(title="Untitled")
    with pytest.raises(VerificationFailed, match="title"):
        _verify_event(fresh, "E-1|x", data, "Work")


def test_verify_event_wrong_calendar_raises():
    data = CalendarEventData(
        title="Standup",
        start=datetime(2026, 6, 24, 9, 0),
        end=datetime(2026, 6, 24, 9, 15),
        calendar="Work",
    )
    fresh = _fake_persisted_event(cal_title="Personal")  # landed on wrong calendar
    with pytest.raises(VerificationFailed, match="calendar"):
        _verify_event(fresh, "E-1|x", data, "Work")


def test_verify_event_timed_end_drift_raises():
    data = CalendarEventData(
        title="Standup",
        start=datetime(2026, 6, 24, 9, 0),
        end=datetime(2026, 6, 24, 9, 15),
    )
    fresh = _fake_persisted_event(end=datetime(2026, 6, 24, 9, 30))  # end changed
    with pytest.raises(VerificationFailed, match="end"):
        _verify_event(fresh, "E-1|x", data, "Work")


def test_verify_event_all_day_ignores_end_representation():
    # EventKit's all-day end may store as next-midnight; verifying start-date + flag
    # only must NOT false-fail when fresh end differs from the requested end.
    data = CalendarEventData(
        title="Holiday",
        start=datetime(2026, 7, 1),
        end=datetime(2026, 7, 1),
        all_day=True,
    )
    fresh = _fake_persisted_event(
        title="Holiday",
        start=datetime(2026, 7, 1),
        end=datetime(2026, 7, 2),  # EventKit's exclusive-end representation
        all_day=True,
    )
    _verify_event(fresh, "E-1|x", data, "Work")  # no raise


def test_verify_event_all_day_wrong_start_date_raises():
    data = CalendarEventData(
        title="Holiday",
        start=datetime(2026, 7, 1),
        end=datetime(2026, 7, 1),
        all_day=True,
    )
    fresh = _fake_persisted_event(
        title="Holiday",
        start=datetime(2026, 7, 2),
        end=datetime(2026, 7, 2),
        all_day=True,
    )
    with pytest.raises(VerificationFailed, match="start_date"):
        _verify_event(fresh, "E-1|x", data, "Work")


def test_verify_event_dropped_recurrence_raises():
    data = CalendarEventData(
        title="Standup",
        start=datetime(2026, 6, 24, 9, 0),
        end=datetime(2026, 6, 24, 9, 15),
        recurrence=Recurrence(frequency="weekly"),
    )
    fresh = _fake_persisted_event()  # rule=None → the series rule was dropped
    with pytest.raises(VerificationFailed, match="recurs"):
        _verify_event(fresh, "E-1|x", data, "Work")


def test_verify_event_wrong_frequency_raises():
    # presence-only was insufficient (#49 review): a non-empty rule with the WRONG
    # cadence must still fail loudly.
    data = CalendarEventData(
        title="Standup",
        start=datetime(2026, 6, 24, 9, 0),
        end=datetime(2026, 6, 24, 9, 15),
        recurrence=Recurrence(frequency="weekly"),
    )
    fresh = _fake_persisted_event(
        rule=_fake_rule(freq=2)
    )  # persisted MONTHLY, not weekly
    with pytest.raises(VerificationFailed, match="recurs"):
        _verify_event(fresh, "E-1|x", data, "Work")


def test_verify_event_matching_recurrence_passes():
    data = CalendarEventData(
        title="Standup",
        start=datetime(2026, 6, 24, 9, 0),
        end=datetime(2026, 6, 24, 9, 15),
        recurrence=Recurrence(frequency="weekly", interval=2),
    )
    fresh = _fake_persisted_event(rule=_fake_rule(freq=1, interval=2))  # weekly/2 match
    _verify_event(fresh, "E-1|x", data, "Work")  # no raise


def test_verify_event_no_recurrence_requested_skips_check():
    # recurrence=None means "leave series untouched" — a fresh event with no rules must
    # not be flagged.
    data = CalendarEventData(
        title="Standup",
        start=datetime(2026, 6, 24, 9, 0),
        end=datetime(2026, 6, 24, 9, 15),
    )
    _verify_event(_fake_persisted_event(), "E-1|x", data, "Work")  # no raise


# --- explicit span on recurring update/delete (#51) ----------------------------------


def _fake_target(recurring: bool):
    return SimpleNamespace(recurrenceRules=lambda: ["rule"] if recurring else None)


def test_resolve_span_single_event_is_this_event():
    # a single (non-recurring) event ignores span — it's moot, EventKit has no other
    # occurrences to span.
    assert _resolve_span(_fake_target(False), None) == EK.EKSpanThisEvent
    assert _resolve_span(_fake_target(False), "future-events") == EK.EKSpanThisEvent


def test_resolve_span_single_event_adding_recurrence_is_future():
    # defining a series on a single event is inherently series-wide.
    assert (
        _resolve_span(_fake_target(False), None, adds_recurrence=True)
        == EK.EKSpanFutureEvents
    )


def test_resolve_span_recurring_requires_explicit_choice():
    with pytest.raises(SpanRequired, match="recurring event"):
        _resolve_span(_fake_target(True), None)


def test_resolve_span_recurring_maps_this_event():
    # EKSpanThisEvent == 0 (falsy) — the mapping must use membership, not truthiness.
    assert _resolve_span(_fake_target(True), "this-event") == EK.EKSpanThisEvent


def test_resolve_span_recurring_maps_future_events():
    assert _resolve_span(_fake_target(True), "future-events") == EK.EKSpanFutureEvents


def test_resolve_span_recurring_rejects_invalid_value():
    with pytest.raises(SpanRequired, match="must be 'this-event' or 'future-events'"):
        _resolve_span(_fake_target(True), "the-whole-thing")


def test_refetch_event_missing_is_rollback():
    # The REAL calendar rollback detector: _refetch_event resolves the id after a save;
    # a miss (fabricated id / iCloud rollback) must surface as VerificationFailed, not a
    # bare lookup miss. A suffix-less id takes _resolve_event's master-lookup branch,
    # which returns None → ValueError → _refetch_event converts it.
    store = SimpleNamespace(calendarItemWithIdentifier_=lambda ident: None)
    with pytest.raises(VerificationFailed, match="could not be re-fetched"):
        _refetch_event(store, "E-404")
