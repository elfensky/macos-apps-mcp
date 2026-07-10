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
    _calendar_pointer,
    _event_pointer,
    _event_summary,
    _range,
    _refetch_event,
    _resolve_calendar,
    _resolve_event,
    _resolve_span,
    _verify_event,
)
from mac_mcp.contracts import CalendarEventData, Pointer, Recurrence
from mac_mcp.runtime import SpanRequired, VerificationFailed
from tests._fakes import fake_rule


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


def test_event_pointer_summary_is_sanitized():
    # #52 routing: a control char in the event title is stripped from the pointer
    # summary (deleting clean_summary from _event_pointer would fail this).
    start = datetime(2026, 6, 23, 9, 0)
    e = _fake_event("Stand\x07up", "E-1", start, datetime(2026, 6, 23, 9, 15))
    assert _event_pointer(e).summary == "Standup 09:00–09:15"


def test_calendar_pointer_summary_is_the_raw_write_key():
    # #52 review: a calendar summary IS its write-resolution key (_resolve_calendar
    # matches title exactly, no id fallback), so it must stay RAW — a sanitized name
    # would not resolve back to the calendar.
    cal = SimpleNamespace(calendarIdentifier=lambda: "C-1", title=lambda: "Work  Cal")
    p = _calendar_pointer(cal)
    assert p.summary == "Work  Cal"  # internal double space preserved, not collapsed
    store = SimpleNamespace(calendarsForEntityType_=lambda _e: [cal])
    assert _resolve_calendar(store, p.summary) is cal  # round-trips by displayed name


def test_range_today_is_one_day():
    start, end = _range("today")
    assert (end - start).days == 1 and start.hour == 0


def test_range_explicit_date():
    start, end = _range("2026-12-25")
    assert start == datetime(2026, 12, 25) and (end - start).days == 1


def test_range_aware_iso_converts_to_local_day():
    # an aware ISO routes through parse_datetime (aware → naive local), then floors —
    # the day is the LOCAL day of that instant, whatever the machine tz.
    aware = "2026-12-25T06:00:00+00:00"
    local_day = (
        datetime.fromisoformat(aware)
        .astimezone()
        .replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    )
    start, end = _range(aware)
    assert start == local_day and (end - start).days == 1


def test_range_garbage_raises_boundary_message():
    # garbage surfaces contracts' agent-directed parse error, not a bare fromisoformat.
    with pytest.raises(ValueError, match="ISO-8601"):
        _range("next tuesday")


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


def test_verify_event_dropped_title_raises():
    data = CalendarEventData(
        title="Standup",
        start=datetime(2026, 6, 24, 9, 0),
        end=datetime(2026, 6, 24, 9, 15),
    )
    fresh = _fake_persisted_event(title="Untitled")
    with pytest.raises(VerificationFailed, match="title"):
        _verify_event(fresh, "E-1|x", data, "Work")


def test_verify_event_dropped_notes_raises():
    # notes requested but persisted as None is a dropped field #49 must name (also
    # exercises the fake's location/notes knobs).
    data = CalendarEventData(
        title="Standup",
        start=datetime(2026, 6, 24, 9, 0),
        end=datetime(2026, 6, 24, 9, 15),
        location="Room 4",
        notes="bring the numbers",
    )
    fresh = _fake_persisted_event(location="Room 4")  # notes silently dropped
    with pytest.raises(VerificationFailed, match="notes"):
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
        rule=fake_rule(freq=2)
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
    fresh = _fake_persisted_event(rule=fake_rule(freq=1, interval=2))  # weekly/2 match
    _verify_event(fresh, "E-1|x", data, "Work")  # no raise


def test_verify_event_nfd_title_matches_nfc_persisted():
    # Cocoa treats NFC/NFD as equal — an NFD input persisted as NFC is the store
    # normalizing, not a dropped field (norm_text, #49 review).
    data = CalendarEventData(
        title="Cafe\u0301",  # NFD: e + combining acute
        start=datetime(2026, 6, 24, 9, 0),
        end=datetime(2026, 6, 24, 9, 15),
    )
    fresh = _fake_persisted_event(title="Caf\u00e9")  # NFC precomposed
    _verify_event(fresh, "E-1|x", data, "Work")  # no raise


def test_verify_event_crlf_notes_match_lf_persisted():
    # stores may fold CRLF → LF; a byte-exact compare would false-fail a correct write.
    data = CalendarEventData(
        title="Standup",
        start=datetime(2026, 6, 24, 9, 0),
        end=datetime(2026, 6, 24, 9, 15),
        notes="line one\r\nline two",
    )
    fresh = _fake_persisted_event(notes="line one\nline two")
    _verify_event(fresh, "E-1|x", data, "Work")  # no raise


def test_verify_event_genuinely_different_notes_raise():
    # normalization must not swallow a REAL content change.
    data = CalendarEventData(
        title="Standup",
        start=datetime(2026, 6, 24, 9, 0),
        end=datetime(2026, 6, 24, 9, 15),
        notes="agenda v2",
    )
    fresh = _fake_persisted_event(notes="agenda v1")
    with pytest.raises(VerificationFailed, match="notes"):
        _verify_event(fresh, "E-1|x", data, "Work")


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


def test_resolve_span_recurring_this_event_plus_recurrence_refused():
    # a recurrence change rewrites the series — span='this-event' cannot apply it, so
    # the contradictory combo is refused before any write.
    with pytest.raises(SpanRequired, match="future-events"):
        _resolve_span(_fake_target(True), "this-event", adds_recurrence=True)
    assert (
        _resolve_span(_fake_target(True), "future-events", adds_recurrence=True)
        == EK.EKSpanFutureEvents
    )


def test_resolve_event_fold_window_is_built_from_the_epoch(monkeypatch):
    # DST fall-back fold: 1793514600 is the SECOND 01:30 in America/New_York
    # (2026-11-01). The ±1s predicate window must come straight from the epoch —
    # datetime±timedelta resets the PEP-495 fold, which would shift the window a full
    # hour (−3601/−3599). Pin the tz for determinism (pattern from test_contracts).
    import time

    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    try:
        captured = []

        def predicate(start, end, cals):
            captured.append((start, end))
            return "pred"

        s = SimpleNamespace(
            predicateForEventsWithStartDate_endDate_calendars_=predicate,
            eventsMatchingPredicate_=lambda _p: [],
        )
        epoch = 1793514600
        with pytest.raises(ValueError, match="no event occurrence"):
            _resolve_event(s, f"X|{epoch}")  # no match — the assertion is the window
        ((start, end),) = captured
        assert int(start.timeIntervalSince1970()) == epoch - 1
        assert int(end.timeIntervalSince1970()) == epoch + 1
    finally:
        monkeypatch.undo()
        time.tzset()


def test_refetch_event_missing_is_rollback():
    # The REAL calendar rollback detector: _refetch_event resolves the id after a save;
    # a miss (fabricated id / iCloud rollback) must surface as VerificationFailed, not a
    # bare lookup miss. A suffix-less id takes _resolve_event's master-lookup branch,
    # which returns None → ValueError → _refetch_event converts it.
    store = SimpleNamespace(calendarItemWithIdentifier_=lambda ident: None)
    with pytest.raises(VerificationFailed, match="could not be re-fetched"):
        _refetch_event(store, "E-404")


# --- dry_run delete (#54) ------------------------------------------------------------


def _fake_event_full(title, ident, start, end, *, recurring=False):
    # everything _resolve_span + _event_pointer touch; recurrenceRules drives the span.
    return SimpleNamespace(
        title=lambda: title,
        calendarItemIdentifier=lambda: ident,
        startDate=lambda: _ns(start),
        endDate=lambda: _ns(end),
        isAllDay=lambda: False,
        recurrenceRules=lambda: [object()] if recurring else None,
    )


def test_delete_event_dry_run_resolves_but_removes_nothing(monkeypatch):
    import mac_mcp.adapters.calendar as cal

    removed = []
    event = _fake_event_full(
        "Standup", "E-1", datetime(2026, 6, 23, 9, 0), datetime(2026, 6, 23, 9, 15)
    )
    store = SimpleNamespace(
        calendarItemWithIdentifier_=lambda i: event,
        removeEvent_span_commit_error_=lambda *a: (removed.append(a), (True, None))[1],
    )
    monkeypatch.setattr(cal, "run_native", lambda fn: fn())
    monkeypatch.setattr(cal, "store", lambda: store)

    p = cal.CalendarAdapter().delete_event("E-1", dry_run=True)
    assert removed == []  # ACCEPTANCE: dry_run mutated nothing
    assert isinstance(p, Pointer) and p.summary == "Standup 09:00–09:15"


def test_delete_event_dry_run_recurring_without_span_still_raises(monkeypatch):
    # the preview must be faithful: a recurring target with no span refuses in dry_run
    # exactly as the real delete would (SpanRequired), so the model can't be misled.
    import mac_mcp.adapters.calendar as cal

    event = _fake_event_full(
        "Weekly",
        "E-2",
        datetime(2026, 6, 23, 9, 0),
        datetime(2026, 6, 23, 9, 30),
        recurring=True,
    )
    store = SimpleNamespace(
        calendarItemWithIdentifier_=lambda i: event,
        removeEvent_span_commit_error_=lambda *a: (True, None),
    )
    monkeypatch.setattr(cal, "run_native", lambda fn: fn())
    monkeypatch.setattr(cal, "store", lambda: store)

    with pytest.raises(SpanRequired):
        cal.CalendarAdapter().delete_event("E-2", dry_run=True)
