"""Unit tests for calendar free_busy — pure interval logic, no EventKit."""

from __future__ import annotations

from datetime import datetime

from macos_apps_mcp.adapters.calendar import _merge_busy


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
