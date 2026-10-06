"""Unit tests for the calendar adapter — pure mapping + range parsing (no
EventKit writes)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import EventKit as EK
import Foundation as F
import pytest

from macos_apps_mcp.adapters.calendar import (
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
from macos_apps_mcp.contracts import CalendarEventData, Pointer, Recurrence
from macos_apps_mcp.errors import AmbiguousTarget, SpanRequired, VerificationFailed
from tests._fakes import fake_rule


def _ns(dt: datetime):
    return F.NSDate.dateWithTimeIntervalSince1970_(dt.timestamp())


def _fake_calendar(calendar_id):
    """``calendar()`` for a fake item: None means an item with no calendar."""
    if calendar_id is None:
        return lambda: None
    return lambda: SimpleNamespace(calendarIdentifier=lambda: calendar_id)


def _fake_event(title, ident, start, end, all_day=False, calendar_id="C-1"):
    return SimpleNamespace(
        title=lambda: title,
        calendarItemIdentifier=lambda: ident,
        startDate=lambda: _ns(start),
        endDate=lambda: _ns(end),
        isAllDay=lambda: all_day,
        calendar=_fake_calendar(calendar_id),
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
    # each calendar gets a stable, distinct id (C0, C1, …) so id-first resolution (#55)
    # and candidate-listing on ambiguity work even when names collide.
    cals = [
        SimpleNamespace(calendarIdentifier=lambda i=i: f"C{i}", title=lambda n=n: n)
        for i, n in enumerate(cal_names)
    ]
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


def test_resolve_ambiguous_calendar_refuses_instead_of_first_match():
    # #55: duplicate calendar names must NOT silently first-match for a write — refuse
    # loudly (the exact mcp-ical #16 bug this rule exists to prevent).
    s = _fake_store(["Work", "Personal", "Work"])
    with pytest.raises(AmbiguousTarget, match="2 calendars are named 'Work'"):
        _resolve_calendar(s, "Work")


def test_resolve_ambiguous_calendar_lists_candidate_ids():
    # #55 DECISION: the refusal LISTS the candidate ids so the caller can recover by
    # re-issuing the write targeting one (not a dead-end "rename them").
    s = _fake_store(["Work", "Personal", "Work"])  # "Work" at index 0 and 2 → C0, C2
    with pytest.raises(AmbiguousTarget) as ei:
        _resolve_calendar(s, "Work")
    assert "C0" in str(ei.value) and "C2" in str(ei.value)


def test_resolve_calendar_by_pointer_id():
    # #55 DECISION: a write may target a calendar by its Pointer.id directly — used
    # as-is, so a duplicate-named calendar is still unambiguously reachable.
    s = _fake_store(["Work", "Personal", "Work"])
    assert _resolve_calendar(s, "C2") is s.calendarsForEntityType_(None)[2]


def test_resolve_single_calendar_among_many_still_works():
    # the rule fires only on DUPLICATES — a unique name at a non-zero index still
    # resolves (guards against a "return the first calendar" regression).
    s = _fake_store(["Work", "Personal", "Family"])
    assert _resolve_calendar(s, "Family").title() == "Family"


# --- verify-after-write (#49) --------------------------------------------------------


class _FakeEvent(SimpleNamespace):
    def setAlarms_(self, alarms):
        self.set_alarms_calls.append(alarms)

    def __getattr__(self, name):  # only reached for a missing attribute
        if name.startswith("set"):
            return lambda *a: None
        raise AttributeError(name)


def _alarm(offset_s, absolute=False):
    """A persisted EKAlarm: ``relativeOffset`` seconds (EventKit's own unit)."""
    return SimpleNamespace(
        relativeOffset=lambda: offset_s,
        absoluteDate=lambda: object() if absolute else None,
    )


def _fake_persisted_event(
    title="Standup",
    start=datetime(2026, 6, 24, 9, 0),
    end=datetime(2026, 6, 24, 9, 15),
    all_day=False,
    location=None,
    notes=None,
    cal_title="Work",
    cal_id="C-Work",  # verify keys on the identifier now, not the title (#55 review)
    rule=None,
    alarms=None,
):
    """A persisted event. ``alarms`` is a list of ``_alarm`` items (None = no alarms);
    ``setAlarms_`` calls are recorded on ``set_alarms_calls`` and any other setter is a
    no-op, so the real ``_apply_event`` can run against it."""
    return _FakeEvent(
        set_alarms_calls=[],
        title=lambda: title,
        startDate=lambda: _ns(start),
        endDate=lambda: _ns(end),
        isAllDay=lambda: all_day,
        location=lambda: location,
        notes=lambda: notes,
        calendar=lambda: SimpleNamespace(
            title=lambda: cal_title, calendarIdentifier=lambda: cal_id
        ),
        recurrenceRules=lambda: [rule] if rule is not None else None,
        alarms=lambda: alarms,
    )


def test_verify_event_passes_on_timed_match():
    data = CalendarEventData(
        title="Standup",
        start=datetime(2026, 6, 24, 9, 0),
        end=datetime(2026, 6, 24, 9, 15),
        calendar="Work",
    )
    _verify_event(_fake_persisted_event(), "E-1|x", data, "C-Work")  # no raise


def test_verify_event_dropped_title_raises():
    data = CalendarEventData(
        title="Standup",
        start=datetime(2026, 6, 24, 9, 0),
        end=datetime(2026, 6, 24, 9, 15),
    )
    fresh = _fake_persisted_event(title="Untitled")
    with pytest.raises(VerificationFailed, match="title"):
        _verify_event(fresh, "E-1|x", data, "C-Work")


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
        _verify_event(fresh, "E-1|x", data, "C-Work")


def test_verify_event_wrong_calendar_raises():
    data = CalendarEventData(
        title="Standup",
        start=datetime(2026, 6, 24, 9, 0),
        end=datetime(2026, 6, 24, 9, 15),
        calendar="Work",
    )
    # landed on a differently-identified calendar (different name too)
    fresh = _fake_persisted_event(cal_title="Personal", cal_id="C-Personal")
    with pytest.raises(VerificationFailed, match="calendar"):
        _verify_event(fresh, "E-1|x", data, "C-Work")


def test_verify_event_same_name_wrong_id_raises():
    # #55 review: verify keys on the calendar IDENTIFIER, not its name. A re-home to a
    # DIFFERENT calendar that happens to SHARE the name (the duplicate-named case that
    # id-targeting exists to serve) must still fail loudly — a title-only compare would
    # falsely pass here, silently confirming a write to the wrong container.
    data = CalendarEventData(
        title="Standup",
        start=datetime(2026, 6, 24, 9, 0),
        end=datetime(2026, 6, 24, 9, 15),
    )
    # targeted calendar id "C2"; store re-homed it to "C0" — SAME name "Work"
    fresh = _fake_persisted_event(cal_title="Work", cal_id="C0")
    with pytest.raises(VerificationFailed, match="calendar"):
        _verify_event(fresh, "E-1|x", data, "C2")


def test_verify_event_timed_end_drift_raises():
    data = CalendarEventData(
        title="Standup",
        start=datetime(2026, 6, 24, 9, 0),
        end=datetime(2026, 6, 24, 9, 15),
    )
    fresh = _fake_persisted_event(end=datetime(2026, 6, 24, 9, 30))  # end changed
    with pytest.raises(VerificationFailed, match="end"):
        _verify_event(fresh, "E-1|x", data, "C-Work")


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
    _verify_event(fresh, "E-1|x", data, "C-Work")  # no raise


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
        _verify_event(fresh, "E-1|x", data, "C-Work")


def test_verify_event_dropped_recurrence_raises():
    data = CalendarEventData(
        title="Standup",
        start=datetime(2026, 6, 24, 9, 0),
        end=datetime(2026, 6, 24, 9, 15),
        recurrence=Recurrence(frequency="weekly"),
    )
    fresh = _fake_persisted_event()  # rule=None → the series rule was dropped
    with pytest.raises(VerificationFailed, match="recurs"):
        _verify_event(fresh, "E-1|x", data, "C-Work")


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
        _verify_event(fresh, "E-1|x", data, "C-Work")


def test_verify_event_matching_recurrence_passes():
    data = CalendarEventData(
        title="Standup",
        start=datetime(2026, 6, 24, 9, 0),
        end=datetime(2026, 6, 24, 9, 15),
        recurrence=Recurrence(frequency="weekly", interval=2),
    )
    fresh = _fake_persisted_event(rule=fake_rule(freq=1, interval=2))  # weekly/2 match
    _verify_event(fresh, "E-1|x", data, "C-Work")  # no raise


def _monthly_2tu_event(**kw):
    return CalendarEventData(
        title="Standup",
        start=datetime(2026, 6, 24, 9, 0),
        end=datetime(2026, 6, 24, 9, 15),
        recurrence=Recurrence.from_rrule("FREQ=MONTHLY;BYDAY=2TU"),
        **kw,
    )


def test_verify_event_byday_matching_passes():
    fresh = _fake_persisted_event(rule=fake_rule(freq=2, byday=[(2, "TU")]))
    _verify_event(fresh, "E-1|x", _monthly_2tu_event(), "C-Work")  # no raise


def test_verify_event_dropped_byday_raises():
    # the store kept MONTHLY but lost the 2TU — presence+cadence alone would pass it
    fresh = _fake_persisted_event(rule=fake_rule(freq=2))
    with pytest.raises(VerificationFailed, match="recurs"):
        _verify_event(fresh, "E-1|x", _monthly_2tu_event(), "C-Work")


def test_verify_event_changed_byday_ordinal_raises():
    fresh = _fake_persisted_event(rule=fake_rule(freq=2, byday=[(3, "TU")]))
    with pytest.raises(VerificationFailed, match="recurs"):
        _verify_event(fresh, "E-1|x", _monthly_2tu_event(), "C-Work")


def _timed_until_event():
    return CalendarEventData(
        title="Standup",
        start=datetime(2026, 6, 24, 9, 0),
        end=datetime(2026, 6, 24, 9, 15),
        recurrence=Recurrence.from_rrule("FREQ=MONTHLY;BYDAY=2TU;UNTIL=20270115"),
    )


def test_verify_event_timed_until_compared_at_day_granularity():
    ok = fake_rule(freq=2, byday=[(2, "TU")], until=datetime(2027, 1, 15, 9, 0))
    _verify_event(
        _fake_persisted_event(rule=ok), "E-1|x", _timed_until_event(), "C-Work"
    )


def test_verify_event_timed_until_on_another_day_raises():
    bad = fake_rule(freq=2, byday=[(2, "TU")], until=datetime(2027, 1, 16, 9, 0))
    with pytest.raises(VerificationFailed, match="recurs"):
        _verify_event(
            _fake_persisted_event(rule=bad), "E-1|x", _timed_until_event(), "C-Work"
        )


def test_verify_event_nfd_title_matches_nfc_persisted():
    # Cocoa treats NFC/NFD as equal — an NFD input persisted as NFC is the store
    # normalizing, not a dropped field (norm_text, #49 review).
    data = CalendarEventData(
        title="Cafe\u0301",  # NFD: e + combining acute
        start=datetime(2026, 6, 24, 9, 0),
        end=datetime(2026, 6, 24, 9, 15),
    )
    fresh = _fake_persisted_event(title="Caf\u00e9")  # NFC precomposed
    _verify_event(fresh, "E-1|x", data, "C-Work")  # no raise


def test_verify_event_crlf_notes_match_lf_persisted():
    # stores may fold CRLF → LF; a byte-exact compare would false-fail a correct write.
    data = CalendarEventData(
        title="Standup",
        start=datetime(2026, 6, 24, 9, 0),
        end=datetime(2026, 6, 24, 9, 15),
        notes="line one\r\nline two",
    )
    fresh = _fake_persisted_event(notes="line one\nline two")
    _verify_event(fresh, "E-1|x", data, "C-Work")  # no raise


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
        _verify_event(fresh, "E-1|x", data, "C-Work")


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


def _fake_event_full(title, ident, start, end, *, recurring=False, calendar_id="C-1"):
    # everything _resolve_span + _event_pointer touch; recurrenceRules drives the span.
    return SimpleNamespace(
        title=lambda: title,
        calendarItemIdentifier=lambda: ident,
        startDate=lambda: _ns(start),
        endDate=lambda: _ns(end),
        isAllDay=lambda: False,
        calendar=_fake_calendar(calendar_id),
        recurrenceRules=lambda: [object()] if recurring else None,
    )


_EPOCH = 1782205200  # an arbitrary occurrence start; only equality matters


def test_delete_event_dry_run_resolves_but_removes_nothing(monkeypatch):
    import macos_apps_mcp.adapters.calendar as cal

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

    out = cal.CalendarAdapter().delete_event("E-1", dry_run=True)
    assert removed == []  # ACCEPTANCE: dry_run mutated nothing
    # C5d: the adapter owns the deletion envelope — tools pass it through
    assert out["dry_run"] is True
    assert out["would_delete"]["summary"] == "Standup 09:00–09:15"


def test_delete_event_real_returns_deletion_envelope(monkeypatch):
    # C5d: the real delete answers with the same envelope family, {"deleted": id}.
    import macos_apps_mcp.adapters.calendar as cal

    removed = []
    event = _fake_event_full(
        "Standup", "E-1", datetime(2026, 6, 23, 9, 0), datetime(2026, 6, 23, 9, 15)
    )
    live = [event]  # the remove takes the event out; the gone-check re-resolves it
    store = SimpleNamespace(
        calendarItemWithIdentifier_=lambda i: live[0] if live else None,
        removeEvent_span_commit_error_=lambda *a: (
            removed.append(a),
            live.clear(),
            (True, None),
        )[2],
    )
    monkeypatch.setattr(cal, "run_native", lambda fn: fn())
    monkeypatch.setattr(cal, "store", lambda: store)

    assert cal.CalendarAdapter().delete_event("E-1") == {"deleted": "E-1"}
    assert removed  # the event actually got removed


def test_delete_event_that_still_resolves_after_the_remove_is_not_reported_deleted(
    monkeypatch,
):
    # D-17: iCloud / Google may restore the event after the commit
    import macos_apps_mcp.adapters.calendar as cal

    event = _fake_event_full(
        "Standup", "E-1", datetime(2026, 6, 23, 9, 0), datetime(2026, 6, 23, 9, 15)
    )
    store = SimpleNamespace(
        calendarItemWithIdentifier_=lambda i: event,  # still there after the remove
        removeEvent_span_commit_error_=lambda *a: (True, None),
    )
    monkeypatch.setattr(cal, "run_native", lambda fn: fn())
    monkeypatch.setattr(cal, "store", lambda: store)

    with pytest.raises(VerificationFailed, match="still resolves after the delete"):
        cal.CalendarAdapter().delete_event("E-1")


def test_delete_event_this_event_passes_while_the_series_master_lives_on(monkeypatch):
    # Pitfall 6: the gone-check is occurrence-aware. After a this-event delete of one
    # occurrence the base id still fetches the master, but the occurrence is gone.
    import macos_apps_mcp.adapters.calendar as cal

    start = datetime(2026, 6, 23, 9, 0)
    occ = _fake_event_full("Weekly", "E-3", start, datetime(2026, 6, 23, 9, 30))
    occ.recurrenceRules = lambda: [object()]
    occ.startDate = lambda: SimpleNamespace(timeIntervalSince1970=lambda: float(_EPOCH))
    live = [occ]
    removed = []
    store = SimpleNamespace(
        calendarItemWithIdentifier_=lambda i: occ,  # the master survives the delete
        predicateForEventsWithStartDate_endDate_calendars_=lambda *a: None,
        eventsMatchingPredicate_=lambda pred: list(live),
        removeEvent_span_commit_error_=lambda *a: (
            removed.append(a),
            live.clear(),
            (True, None),
        )[2],
    )
    monkeypatch.setattr(cal, "run_native", lambda fn: fn())
    monkeypatch.setattr(cal, "store", lambda: store)

    ident = f"E-3|{_EPOCH}"
    out = cal.CalendarAdapter().delete_event(ident, span="this-event")
    assert out == {"deleted": ident}
    assert len(removed) == 1


def test_delete_event_dry_run_makes_no_remove_and_no_gone_check(monkeypatch):
    import macos_apps_mcp.adapters.calendar as cal

    event = _fake_event_full(
        "Standup", "E-1", datetime(2026, 6, 23, 9, 0), datetime(2026, 6, 23, 9, 15)
    )
    lookups = []
    store = SimpleNamespace(
        calendarItemWithIdentifier_=lambda i: (lookups.append(i), event)[1],
        removeEvent_span_commit_error_=lambda *a: pytest.fail("dry run removed"),
    )
    monkeypatch.setattr(cal, "run_native", lambda fn: fn())
    monkeypatch.setattr(cal, "store", lambda: store)

    cal.CalendarAdapter().delete_event("E-1", dry_run=True)
    assert lookups == ["E-1"]  # the one resolve; no second look after a remove


def test_delete_event_dry_run_recurring_without_span_still_raises(monkeypatch):
    # the preview must be faithful: a recurring target with no span refuses in dry_run
    # exactly as the real delete would (SpanRequired), so the model can't be misled.
    import macos_apps_mcp.adapters.calendar as cal

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


def test_calendar_snapshot_missing_returns_none(monkeypatch):
    import macos_apps_mcp.adapters.calendar as cal

    monkeypatch.setattr(cal, "run_native", lambda fn: fn())
    monkeypatch.setattr(cal, "store", lambda: object())

    def _raise(_s, _i):
        raise ValueError("no such event")

    monkeypatch.setattr(cal, "_resolve_event", _raise)
    assert cal.CalendarAdapter().snapshot("E-1|123") is None


def test_calendar_snapshot_found(monkeypatch):
    import macos_apps_mcp.adapters.calendar as cal

    monkeypatch.setattr(cal, "run_native", lambda fn: fn())
    monkeypatch.setattr(cal, "store", lambda: object())
    ev = _fake_event(
        "Standup", "E-1", datetime(2026, 6, 23, 9, 0), datetime(2026, 6, 23, 9, 15)
    )
    monkeypatch.setattr(cal, "_resolve_event", lambda _s, _i: ev)
    p = cal.CalendarAdapter().snapshot("E-1|123")
    assert p is not None and "Standup" in p.summary


# --- container id on the pointer (CAL-04, D-12, #207) --------------------------------


def test_event_pointer_folder_is_the_calendar_identifier():
    start = datetime(2026, 6, 23, 9, 0)
    e = _fake_event("Standup", "E-1", start, start, calendar_id="C-Work")
    assert _event_pointer(e).as_dict()["folder"] == "C-Work"


def test_event_pointer_folder_omitted_when_no_calendar():
    # a calendar-less event: the key is absent from the wire dict, never null
    start = datetime(2026, 6, 23, 9, 0)
    e = _fake_event("Orphan", "E-9", start, start, calendar_id=None)
    assert "folder" not in _event_pointer(e).as_dict()


def test_event_pointer_folder_is_raw_identifier_never_normalized():
    # compared by exact equality: no trim, case-fold or NFC pass on the way out
    start = datetime(2026, 6, 23, 9, 0)
    raw = " Ab:C\u0301/x "
    e = _fake_event("Standup", "E-1", start, start, calendar_id=raw)
    assert _event_pointer(e).folder == raw


def test_get_pointers_folder_round_trips_into_free_busy(monkeypatch):
    # tracer: EventKit item -> Pointer.folder -> wire -> accepted back by free_busy
    import macos_apps_mcp.adapters.calendar as cal

    start = datetime(2026, 6, 23, 9, 0)
    event = _fake_event("Standup", "E-1", start, start, calendar_id="C-Work")
    event.availability = lambda: EK.EKEventAvailabilityBusy
    seen = {}

    def predicate(_s, _e, cals):
        seen["cals"] = cals
        return "pred"

    s = SimpleNamespace(
        calendarsForEntityType_=lambda _e: [
            SimpleNamespace(calendarIdentifier=lambda: "C-Work", title=lambda: "T")
        ],
        predicateForEventsWithStartDate_endDate_calendars_=predicate,
        eventsMatchingPredicate_=lambda _p: [event],
    )
    monkeypatch.setattr(cal, "store", lambda: s)
    monkeypatch.setattr(cal, "run_native", lambda fn: fn())

    ptrs = cal.CalendarAdapter().get_pointers("2026-06-23")
    folder = ptrs[0].as_dict()["folder"]
    assert folder == "C-Work"
    cal.CalendarAdapter().get_free_busy(
        "2026-06-23T00:00:00", "2026-06-24T00:00:00", calendars=[folder]
    )  # no ValueError: the folder is a valid calendar id
    assert [c.calendarIdentifier() for c in seen["cals"]] == ["C-Work"]


def test_delete_event_dry_run_preview_carries_folder(monkeypatch):
    import macos_apps_mcp.adapters.calendar as cal

    event = _fake_event_full(
        "Standup",
        "E-1",
        datetime(2026, 6, 23, 9, 0),
        datetime(2026, 6, 23, 9, 15),
        calendar_id="C-Work",
    )
    store = SimpleNamespace(calendarItemWithIdentifier_=lambda i: event)
    monkeypatch.setattr(cal, "run_native", lambda fn: fn())
    monkeypatch.setattr(cal, "store", lambda: store)

    out = cal.CalendarAdapter().delete_event("E-1", dry_run=True)
    assert out["would_delete"]["folder"] == "C-Work"


# --- DTSTART outside its rule is stated on the pointer (D-10, CAL-03, #90) -----------


def _write_world(monkeypatch, persisted):
    """Fake store + EventKit seams so create_event / update_event run end to end on the
    real pointer and verify code. Returns the adapter."""
    import macos_apps_mcp.adapters.calendar as cal

    s = SimpleNamespace(saveEvent_span_commit_error_=lambda *a: (True, None))
    monkeypatch.setattr(cal, "run_native", lambda fn: fn())
    monkeypatch.setattr(cal, "store", lambda: s)
    monkeypatch.setattr(
        cal.EK,
        "EKEvent",
        SimpleNamespace(eventWithEventStore_=lambda _s: persisted),
    )
    monkeypatch.setattr(cal, "_resolve_span", lambda *a, **k: "span")
    monkeypatch.setattr(cal, "_apply_event", lambda *a, **k: None)
    monkeypatch.setattr(cal, "_resolve_event", lambda _s, _i: persisted)
    monkeypatch.setattr(cal, "_refetch_event", lambda _s, _i: persisted)
    return cal.CalendarAdapter()


def _monthly_2tu_world(monkeypatch, start, title="Standup"):
    end = start + timedelta(minutes=15)
    persisted = _fake_persisted_event(
        title=title, start=start, end=end, rule=fake_rule(freq=2, byday=[(2, "TU")])
    )
    persisted.calendarItemIdentifier = lambda: "E-1"
    data = CalendarEventData(
        title=title,
        start=start,
        end=end,
        recurrence=Recurrence.from_rrule("FREQ=MONTHLY;BYDAY=2TU"),
    )
    return _write_world(monkeypatch, persisted), data


def test_dtstart_outside_rule_create_event_states_the_extra_occurrence(monkeypatch):
    # tracer: 2027-01-04 is a Monday, not the 2nd Tuesday
    adapter, data = _monthly_2tu_world(monkeypatch, datetime(2027, 1, 4, 10))
    p = adapter.create_event(data)
    assert isinstance(p, Pointer)
    assert p.summary.startswith("Standup 10:00")
    assert "one extra first occurrence" in p.summary
    assert p.summary.endswith("(RFC 5545)")


def test_dtstart_inside_rule_create_event_has_no_note(monkeypatch):
    adapter, data = _monthly_2tu_world(monkeypatch, datetime(2027, 1, 12, 10))
    assert "extra first occurrence" not in adapter.create_event(data).summary


def test_dtstart_outside_rule_update_event_states_the_extra_occurrence(monkeypatch):
    adapter, data = _monthly_2tu_world(monkeypatch, datetime(2027, 1, 4, 10))
    p = adapter.update_event("E-1|1", data, span="future-events")
    assert p.summary.endswith("(RFC 5545)")
    assert "one extra first occurrence" in p.summary


def test_dtstart_inside_rule_update_event_has_no_note(monkeypatch):
    adapter, data = _monthly_2tu_world(monkeypatch, datetime(2027, 1, 12, 10))
    p = adapter.update_event("E-1|1", data, span="future-events")
    assert "extra first occurrence" not in p.summary


def test_dtstart_note_survives_a_title_that_fills_the_summary(monkeypatch):
    # the summary is bounded: a long title must be cut, never the note
    adapter, data = _monthly_2tu_world(
        monkeypatch, datetime(2027, 1, 4, 10), title="T" * 400
    )
    assert adapter.create_event(data).summary.endswith("(RFC 5545)")


def test_dtstart_no_recurrence_has_no_note(monkeypatch):
    start = datetime(2027, 1, 4, 10)
    end = start + timedelta(minutes=15)
    persisted = _fake_persisted_event(start=start, end=end)
    persisted.calendarItemIdentifier = lambda: "E-1"
    adapter = _write_world(monkeypatch, persisted)
    data = CalendarEventData(title="Standup", start=start, end=end)
    assert "extra first occurrence" not in adapter.create_event(data).summary


# --- alarms: relative EKAlarms, verified as a multiset (CAL-01, CAL-02, #89) ---------


def _alarm_world(monkeypatch, persisted):
    """create_event / update_event with the REAL ``_apply_event``: it writes onto
    ``persisted``, which is also what the re-fetch returns."""
    import macos_apps_mcp.adapters.calendar as cal

    persisted.calendarItemIdentifier = lambda: "E-1"
    s = SimpleNamespace(
        saveEvent_span_commit_error_=lambda *a: (True, None),
        defaultCalendarForNewEvents=lambda: persisted.calendar(),
    )
    monkeypatch.setattr(cal, "run_native", lambda fn: fn())
    monkeypatch.setattr(cal, "store", lambda: s)
    monkeypatch.setattr(
        cal.EK, "EKEvent", SimpleNamespace(eventWithEventStore_=lambda _s: persisted)
    )
    monkeypatch.setattr(cal, "_resolve_span", lambda *a, **k: "span")
    monkeypatch.setattr(cal, "_resolve_event", lambda _s, _i: persisted)
    monkeypatch.setattr(cal, "_refetch_event", lambda _s, _i: persisted)
    return cal.CalendarAdapter()


def _timed(**kw):
    return CalendarEventData(
        title="Standup",
        start=datetime(2026, 6, 24, 9, 0),
        end=datetime(2026, 6, 24, 9, 15),
        **kw,
    )


def test_create_event_alarms_builds_one_relative_alarm(monkeypatch):
    persisted = _fake_persisted_event(alarms=[_alarm(-900.0)])
    p = _alarm_world(monkeypatch, persisted).create_event(_timed(alarms=(15,)))
    assert isinstance(p, Pointer)
    (built,) = persisted.set_alarms_calls
    assert [a.relativeOffset() for a in built] == [-900.0]
    assert all(a.absoluteDate() is None for a in built)


def test_create_event_alarms_missing_after_save_raises(monkeypatch):
    persisted = _fake_persisted_event(alarms=None)  # the store dropped them
    with pytest.raises(VerificationFailed, match="alarms"):
        _alarm_world(monkeypatch, persisted).create_event(_timed(alarms=(15,)))


def test_verify_event_alarms_absolute_alarm_raises():
    # offset 0 matches the requested (0,), so only the absolute alarm is the mismatch
    fresh = _fake_persisted_event(alarms=[_alarm(0.0, absolute=True)])
    with pytest.raises(VerificationFailed, match="absolute_alarms"):
        _verify_event(fresh, "E-1|x", _timed(alarms=(0,)), "C-Work")


def test_verify_event_alarms_compare_is_a_multiset():
    # EventKit returns alarms in no stable order: either order passes
    want = _timed(alarms=(60, 15))
    for got in ([-900.0, -3600.0], [-3600.0, -900.0]):
        fresh = _fake_persisted_event(alarms=[_alarm(o) for o in got])
        _verify_event(fresh, "E-1|x", want, "C-Work")  # no raise


def test_verify_event_alarms_wrong_offset_raises():
    fresh = _fake_persisted_event(alarms=[_alarm(-1800.0)])
    with pytest.raises(VerificationFailed, match="alarms"):
        _verify_event(fresh, "E-1|x", _timed(alarms=(15,)), "C-Work")


@pytest.mark.parametrize(
    ("minutes", "offset"),
    [(-540, 32400.0), (900, -54000.0), (0, 0.0), (1440, -86400.0)],
)
def test_all_day_alarm_offsets_count_from_local_midnight(minutes, offset):
    # D-02: -540 is 09:00 on the day, 900 is 09:00 the day before, 1440 is midnight
    # the day before — real EKAlarm value objects, built through the real _apply_event
    from macos_apps_mcp.adapters.calendar import _apply_event

    day = datetime(2027, 2, 15)
    data = CalendarEventData("x", day, day, all_day=True, alarms=(minutes,))
    event = _fake_persisted_event()
    store = SimpleNamespace(defaultCalendarForNewEvents=lambda: None)
    _apply_event(store, event, data)
    (built,) = event.set_alarms_calls
    assert [a.relativeOffset() for a in built] == [offset]


def test_update_event_alarms_omitted_leaves_them_untouched(monkeypatch):
    # D-04: None is "not given" — no setAlarms_ call, and verify does not look at them
    persisted = _fake_persisted_event(alarms=[_alarm(-900.0)])
    _alarm_world(monkeypatch, persisted).update_event(
        "E-1|1", _timed(), span="future-events"
    )
    assert persisted.set_alarms_calls == []


def test_update_event_alarms_empty_clears_them(monkeypatch):
    persisted = _fake_persisted_event(alarms=None)
    _alarm_world(monkeypatch, persisted).update_event(
        "E-1|1", _timed(alarms=()), span="future-events"
    )
    assert persisted.set_alarms_calls == [None]  # None, never [], clears


def test_update_event_alarms_replace_them(monkeypatch):
    persisted = _fake_persisted_event(alarms=[_alarm(-3600.0)])
    _alarm_world(monkeypatch, persisted).update_event(
        "E-1|1", _timed(alarms=(60,)), span="future-events"
    )
    ((built,),) = persisted.set_alarms_calls
    assert built.relativeOffset() == -3600.0


def test_verify_event_all_day_alarms_pass_in_either_order():
    day = datetime(2027, 2, 15)
    want = CalendarEventData("Holiday", day, day, all_day=True, alarms=(-540, 900))
    for got in ([32400.0, -54000.0], [-54000.0, 32400.0]):
        fresh = _fake_persisted_event(
            title="Holiday",
            start=day,
            end=day + timedelta(days=1),
            all_day=True,
            alarms=[_alarm(o) for o in got],
        )
        _verify_event(fresh, "E-1|x", want, "C-Work")  # no raise
