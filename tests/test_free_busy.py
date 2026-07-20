"""Unit tests for calendar free_busy — pure interval logic, no EventKit."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import EventKit as EK
import Foundation as F
import pytest

from macos_apps_mcp.adapters.calendar import (
    CalendarAdapter,
    _busy_epochs,
    _iso_interval,
    _merge_busy,
    _resolve_calendars,
)


def test_overlapping_blocks_merge():
    busy, free = _merge_busy([(10, 30), (20, 40)], 0, 100)
    assert busy == [(10, 40)]
    assert free == [(0, 10), (40, 100)]


def test_adjacent_blocks_merge():
    # next.start == cur.end must merge (back-to-back meetings are one busy run)
    busy, free = _merge_busy([(10, 20), (20, 30)], 0, 100)
    assert busy == [(10, 30)]
    assert free == [(0, 10), (30, 100)]


def test_free_complement_leading_middle_trailing():
    busy, free = _merge_busy([(10, 20), (40, 50)], 0, 100)
    assert busy == [(10, 20), (40, 50)]
    assert free == [(0, 10), (20, 40), (50, 100)]


def test_all_free_window():
    busy, free = _merge_busy([], 0, 100)
    assert busy == []
    assert free == [(0, 100)]


def test_all_busy_window():
    busy, free = _merge_busy([(0, 100)], 0, 100)
    assert busy == [(0, 100)]
    assert free == []


def test_interval_clipped_to_window():
    busy, free = _merge_busy([(-50, 20), (80, 200)], 0, 100)
    assert busy == [(0, 20), (80, 100)]
    assert free == [(20, 80)]


def test_zero_length_and_post_clip_empty_dropped():
    # a zero-length event and one entirely outside the window vanish
    busy, free = _merge_busy([(30, 30), (200, 300)], 0, 100)
    assert busy == []
    assert free == [(0, 100)]


def test_dst_boundary_is_instant_based():
    # US fall-back 2026-11-01: 01:00 occurs twice; a meeting across it is 2 real hours.
    # timestamp() on naive-local gives the correct epoch pair; _merge_busy is pure int
    # math, so the run stays a single ordered interval (no fold miscount).
    lo = int(datetime(2026, 11, 1, 0, 30).timestamp())
    start = int(datetime(2026, 11, 1, 0, 45).timestamp())
    end = int(datetime(2026, 11, 1, 3, 0).timestamp())
    hi = int(datetime(2026, 11, 1, 4, 0).timestamp())
    busy, free = _merge_busy([(start, end)], lo, hi)
    assert busy == [(start, end)]
    assert free == [(lo, start), (end, hi)]
    assert all(s < e for s, e in busy + free)  # every interval ordered


def _ns(dt: datetime):
    return F.NSDate.dateWithTimeIntervalSince1970_(dt.timestamp())


def _ev(availability, start, end):
    return SimpleNamespace(
        availability=lambda: availability,
        startDate=lambda: _ns(start),
        endDate=lambda: _ns(end),
    )


def test_busy_event_included():
    ev = _ev(
        EK.EKEventAvailabilityBusy, datetime(2026, 7, 20, 9), datetime(2026, 7, 20, 10)
    )
    out = _busy_epochs([ev])
    assert out == [
        (
            int(datetime(2026, 7, 20, 9).timestamp()),
            int(datetime(2026, 7, 20, 10).timestamp()),
        )
    ]


def test_free_marked_event_excluded():
    ev = _ev(
        EK.EKEventAvailabilityFree, datetime(2026, 7, 20, 9), datetime(2026, 7, 20, 10)
    )
    assert _busy_epochs([ev]) == []


def test_not_supported_counts_as_busy():
    # local calendars report NotSupported; != Free, so they block (safe default)
    ev = _ev(
        EK.EKEventAvailabilityNotSupported,
        datetime(2026, 7, 20, 9),
        datetime(2026, 7, 20, 10),
    )
    assert len(_busy_epochs([ev])) == 1


def _fake_store(events, calendars=()):
    cals = list(calendars)

    def predicate(a, b, c):
        return ("pred", a, b, c)

    return SimpleNamespace(
        calendarsForEntityType_=lambda t: cals,
        predicateForEventsWithStartDate_endDate_calendars_=predicate,
        eventsMatchingPredicate_=lambda p: events,
    )


def _fake_cal(cid):
    return SimpleNamespace(calendarIdentifier=lambda: cid)


def test_iso_interval_naive_local():
    epoch = int(datetime(2026, 7, 20, 9, 30).timestamp())
    assert _iso_interval((epoch, epoch)) == {
        "start": "2026-07-20T09:30:00",
        "end": "2026-07-20T09:30:00",
    }


def test_resolve_calendars_none_means_all():
    assert _resolve_calendars(_fake_store([]), None) is None


def test_resolve_calendars_maps_ids():
    s = _fake_store([], calendars=[_fake_cal("C-1"), _fake_cal("C-2")])
    out = _resolve_calendars(s, ["C-2"])
    assert [c.calendarIdentifier() for c in out] == ["C-2"]


def test_resolve_calendars_unknown_id_raises():
    s = _fake_store([], calendars=[_fake_cal("C-1")])
    with pytest.raises(ValueError, match="C-9"):
        _resolve_calendars(s, ["C-9"])


def test_get_free_busy_end_to_end(monkeypatch):
    import macos_apps_mcp.adapters.calendar as cal

    busy_ev = _ev(
        EK.EKEventAvailabilityBusy, datetime(2026, 7, 20, 9), datetime(2026, 7, 20, 10)
    )
    free_ev = _ev(
        EK.EKEventAvailabilityFree, datetime(2026, 7, 20, 12), datetime(2026, 7, 20, 13)
    )
    monkeypatch.setattr(cal, "store", lambda: _fake_store([busy_ev, free_ev]))
    monkeypatch.setattr(cal, "run_native", lambda fn: fn())

    out = CalendarAdapter().get_free_busy("2026-07-20T08:00:00", "2026-07-20T11:00:00")
    assert out == {
        "busy": [{"start": "2026-07-20T09:00:00", "end": "2026-07-20T10:00:00"}],
        "free": [
            {"start": "2026-07-20T08:00:00", "end": "2026-07-20T09:00:00"},
            {"start": "2026-07-20T10:00:00", "end": "2026-07-20T11:00:00"},
        ],
    }


def test_get_free_busy_rejects_reversed_window():
    with pytest.raises(ValueError, match="start.*before.*end"):
        CalendarAdapter().get_free_busy("2026-07-20T11:00:00", "2026-07-20T08:00:00")
