# free_busy Availability Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `free_busy(start, end, calendars?)` read tool that returns merged busy intervals and free gaps across selected calendars in a window.

**Architecture:** A pure interval merger (`_merge_busy`) and a pure availability filter (`_busy_epochs`) hold all the logic and are unit-tested without EventKit. The adapter method `get_free_busy` is thin glue inside `run_native`: fetch events, filter, merge, format to ISO. The server tool is a one-line dispatch, matching `events`.

**Tech Stack:** Python 3.12+, FastMCP 2.0, PyObjC/EventKit, pytest, uv, ruff.

## Global Constraints

- All EventKit access goes through `runtime.run_native()` — the single serialized worker. Never call EventKit off it; never widen `max_workers` past 1.
- Tools in `server.py` are **thin dispatch** to adapters — no business logic in the tool layer.
- Reads are uniform pointers where applicable; `free_busy` returns a compact dict (like `now`/`doctor`), **no event details** (privacy + tokens).
- Datetimes are canonical **naive-local** (`contracts.parse_datetime`); instants compared/stored as **epoch seconds** (fold-proof, per `epoch_nsdate`).
- Style: `ruff` (line-length 88, rules `E, F, I, UP, B, SIM`). No mypy.
- Verify before claiming done: `uv run pytest && uv run ruff check . && uv run ruff format --check .`. Integration tests (`-m integration`) are manual only, never CI.
- Branch: `feat/65-free-busy` (already created).

---

### Task 1: `_merge_busy` — the pure interval core

**Files:**
- Modify: `macos_apps_mcp/adapters/calendar.py` (add module-level function near the other helpers, e.g. after `_all_day_bounds`)
- Test: `tests/test_free_busy.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `_merge_busy(intervals: list[tuple[int, int]], lo: int, hi: int) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]` — returns `(busy, free)`, each a list of `(start_epoch, end_epoch)` tuples clipped to `[lo, hi]`, busy runs merged, free = complement.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_free_busy.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_free_busy.py -v`
Expected: FAIL with `ImportError` / `cannot import name '_merge_busy'`.

- [ ] **Step 3: Implement `_merge_busy`**

Add to `macos_apps_mcp/adapters/calendar.py` (module level, after `_all_day_bounds`):

```python
def _merge_busy(
    intervals: list[tuple[int, int]], lo: int, hi: int
) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """Merge overlapping/adjacent busy intervals within [lo, hi]; return (busy, free).

    All epoch seconds — pure int math, so it's fold-proof across DST (no naive-datetime
    arithmetic crosses a boundary). `free` is the complement of the merged runs within
    the window. `<=` on the merge test folds adjacency (back-to-back) into overlap.
    """
    clipped = []
    for start, end in intervals:
        start, end = max(start, lo), min(end, hi)
        if start < end:  # drop zero-length and out-of-window intervals
            clipped.append((start, end))
    clipped.sort()
    busy: list[tuple[int, int]] = []
    for start, end in clipped:
        if busy and start <= busy[-1][1]:
            busy[-1] = (busy[-1][0], max(busy[-1][1], end))
        else:
            busy.append((start, end))
    free: list[tuple[int, int]] = []
    cursor = lo
    for start, end in busy:
        if start > cursor:
            free.append((cursor, start))
        cursor = end
    if cursor < hi:
        free.append((cursor, hi))
    return busy, free
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_free_busy.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add tests/test_free_busy.py macos_apps_mcp/adapters/calendar.py
git commit -m "feat(calendar): _merge_busy interval merger for free_busy (#65)"
```

---

### Task 2: `_busy_epochs` — the availability filter

**Files:**
- Modify: `macos_apps_mcp/adapters/calendar.py` (add module-level function; add `EK.EKEventAvailabilityFree` usage — `EventKit` is already imported as `EK`)
- Test: `tests/test_free_busy.py` (extend)

**Interfaces:**
- Consumes: nothing (operates on EKEvent-like objects with `.availability()`, `.startDate()`, `.endDate()`).
- Produces: `_busy_epochs(events) -> list[tuple[int, int]]` — epoch `(start, end)` for every event that is **not** explicitly Free.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_free_busy.py`:

```python
from types import SimpleNamespace

import EventKit as EK
import Foundation as F

from macos_apps_mcp.adapters.calendar import _busy_epochs


def _ns(dt: datetime):
    return F.NSDate.dateWithTimeIntervalSince1970_(dt.timestamp())


def _ev(availability, start, end):
    return SimpleNamespace(
        availability=lambda: availability,
        startDate=lambda: _ns(start),
        endDate=lambda: _ns(end),
    )


def test_busy_event_included():
    ev = _ev(EK.EKEventAvailabilityBusy, datetime(2026, 7, 20, 9), datetime(2026, 7, 20, 10))
    out = _busy_epochs([ev])
    assert out == [
        (int(datetime(2026, 7, 20, 9).timestamp()), int(datetime(2026, 7, 20, 10).timestamp()))
    ]


def test_free_marked_event_excluded():
    ev = _ev(EK.EKEventAvailabilityFree, datetime(2026, 7, 20, 9), datetime(2026, 7, 20, 10))
    assert _busy_epochs([ev]) == []


def test_not_supported_counts_as_busy():
    # local calendars report NotSupported; != Free, so they block (safe default)
    ev = _ev(EK.EKEventAvailabilityNotSupported, datetime(2026, 7, 20, 9), datetime(2026, 7, 20, 10))
    assert len(_busy_epochs([ev])) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_free_busy.py -k busy_epochs -v` (and `-k not_supported`, `-k free_marked`)
Expected: FAIL with `cannot import name '_busy_epochs'`.

- [ ] **Step 3: Implement `_busy_epochs`**

Add to `macos_apps_mcp/adapters/calendar.py` (module level, just above `_merge_busy`):

```python
def _busy_epochs(events) -> list[tuple[int, int]]:
    """Epoch (start, end) for each event that blocks — i.e. NOT explicitly Free.

    An event blocks unless its availability is `EKEventAvailabilityFree`. This one rule
    also handles all-day events: EventKit marks them Free by default, so they drop out;
    an all-day event a user set to busy still blocks. `NotSupported` (local calendars)
    is `!= Free`, so it counts busy — the safe default.
    """
    out = []
    for e in events:
        if e.availability() == EK.EKEventAvailabilityFree:
            continue
        out.append(
            (
                int(e.startDate().timeIntervalSince1970()),
                int(e.endDate().timeIntervalSince1970()),
            )
        )
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_free_busy.py -v`
Expected: PASS (all, including the 3 new).

- [ ] **Step 5: Commit**

```bash
git add tests/test_free_busy.py macos_apps_mcp/adapters/calendar.py
git commit -m "feat(calendar): _busy_epochs availability filter for free_busy (#65)"
```

---

### Task 3: `get_free_busy` adapter method + calendar resolution + ISO formatting

**Files:**
- Modify: `macos_apps_mcp/adapters/calendar.py` (add `_resolve_calendars`, `_iso_interval` helpers; add `get_free_busy` method to `CalendarAdapter`). `parse_datetime`, `run_native`, `store`, `to_nsdate`, `from_nsdate`, `epoch_nsdate` are already imported.
- Test: `tests/test_free_busy.py` (extend)

**Interfaces:**
- Consumes: `_busy_epochs` (Task 2), `_merge_busy` (Task 1).
- Produces:
  - `_resolve_calendars(s, ids: list[str] | None)` → `None` (all) or `list[EKCalendar]`; raises `ValueError` on an unknown id.
  - `_iso_interval(pair: tuple[int, int]) -> dict[str, str]` → `{"start": iso, "end": iso}` (naive-local).
  - `CalendarAdapter.get_free_busy(start: str, end: str, calendars: list[str] | None = None) -> dict` → `{"busy": [...], "free": [...]}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_free_busy.py`:

```python
from macos_apps_mcp.adapters.calendar import (
    CalendarAdapter,
    _iso_interval,
    _resolve_calendars,
)


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

    busy_ev = _ev(EK.EKEventAvailabilityBusy, datetime(2026, 7, 20, 9), datetime(2026, 7, 20, 10))
    free_ev = _ev(EK.EKEventAvailabilityFree, datetime(2026, 7, 20, 12), datetime(2026, 7, 20, 13))
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
```

Add `import pytest` to the test file's imports if not already present.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_free_busy.py -k "resolve or iso or get_free_busy" -v`
Expected: FAIL with `cannot import name '_resolve_calendars'`.

- [ ] **Step 3: Implement the helpers and method**

Add module-level helpers to `macos_apps_mcp/adapters/calendar.py` (near the other `_resolve_*` helpers):

```python
def _resolve_calendars(s, ids: list[str] | None):
    """None → all calendars (pass None to the predicate); a list → the matching
    EKCalendars, raising loudly on any unknown id (resolve-or-raise)."""
    if ids is None:
        return None
    by_id = {
        c.calendarIdentifier(): c
        for c in s.calendarsForEntityType_(EK.EKEntityTypeEvent)
    }
    out = []
    for cid in ids:
        c = by_id.get(cid)
        if c is None:
            raise ValueError(
                f"no calendar with id {cid!r} — call the `calendars` tool for valid ids"
            )
        out.append(c)
    return out


def _iso_interval(pair: tuple[int, int]) -> dict[str, str]:
    """An epoch (start, end) as naive-local ISO — fold-proof via epoch_nsdate."""
    lo, hi = pair
    return {
        "start": from_nsdate(epoch_nsdate(lo)).isoformat(),
        "end": from_nsdate(epoch_nsdate(hi)).isoformat(),
    }
```

Add the method to `CalendarAdapter` (alongside `get_pointers` / `get_calendars`):

```python
    def get_free_busy(
        self, start: str, end: str, calendars: list[str] | None = None
    ) -> dict:
        """Merged busy intervals + free gaps in [start, end] (ISO-8601 naive-local).

        calendars: optional Pointer ids to restrict to; None = all. No event details.
        """
        start_dt = parse_datetime(start)
        end_dt = parse_datetime(end)
        if start_dt >= end_dt:
            raise ValueError(
                f"start must be before end — got start={start!r}, end={end!r}"
            )
        lo, hi = int(start_dt.timestamp()), int(end_dt.timestamp())

        def work():
            s = store()
            cals = _resolve_calendars(s, calendars)
            pred = s.predicateForEventsWithStartDate_endDate_calendars_(
                to_nsdate(start_dt), to_nsdate(end_dt), cals
            )
            events = s.eventsMatchingPredicate_(pred) or []
            busy, free = _merge_busy(_busy_epochs(events), lo, hi)
            return {
                "busy": [_iso_interval(b) for b in busy],
                "free": [_iso_interval(f) for f in free],
            }

        return run_native(work)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_free_busy.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add tests/test_free_busy.py macos_apps_mcp/adapters/calendar.py
git commit -m "feat(calendar): get_free_busy adapter method (#65)"
```

---

### Task 4: `free_busy` server tool, dispatch test, README, integration test

**Files:**
- Modify: `macos_apps_mcp/server.py` (add the `free_busy` tool after `events`, ~line 199)
- Modify: `tests/test_server.py` (add a fake adapter method + dispatch test)
- Modify: `tests/test_integration.py` (add a manual on-device test)
- Modify: `README.md` (add a row after the `events` row, ~line 65)

**Interfaces:**
- Consumes: `CalendarAdapter.get_free_busy` (Task 3).
- Produces: the `free_busy` MCP tool.

- [ ] **Step 1: Write the failing dispatch test**

Add to `tests/test_server.py`. First extend `_FakeSource` (the class near line 28) with:

```python
    def get_free_busy(self, start, end, calendars=None):
        self.queries.append((start, end, calendars))
        return {
            "busy": [{"start": start, "end": end}],
            "free": [],
        }
```

Then add the test (near `test_events_tool_dispatches`):

```python
def test_free_busy_tool_dispatches(monkeypatch):
    fake = _FakeSource()
    monkeypatch.setattr(srv, "_calendar", fake)
    out = srv.free_busy("2026-07-20T08:00:00", "2026-07-20T17:00:00", ["C-1"])
    assert fake.queries == [("2026-07-20T08:00:00", "2026-07-20T17:00:00", ["C-1"])]
    assert out == {
        "busy": [{"start": "2026-07-20T08:00:00", "end": "2026-07-20T17:00:00"}],
        "free": [],
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_server.py::test_free_busy_tool_dispatches -v`
Expected: FAIL with `AttributeError: module 'macos_apps_mcp.server' has no attribute 'free_busy'`.

- [ ] **Step 3: Add the server tool**

In `macos_apps_mcp/server.py`, after the `events` tool (~line 199):

```python
@_read_tool
def free_busy(
    start: str, end: str, calendars: list[str] | None = None
) -> dict:
    """Availability in a window: merged busy intervals + free gaps. `start`/`end` are
    ISO-8601 datetimes (naive local, e.g. 2026-07-20T09:00:00); `calendars` optional
    Pointer ids (from `calendars`) to restrict to, else all. Returns {"busy": [...],
    "free": [...]} of {start, end} — no event details. Read-only; needs EventKit."""
    return _calendar.get_free_busy(start, end, calendars)
```

- [ ] **Step 4: Run the dispatch test to verify it passes**

Run: `uv run pytest tests/test_server.py::test_free_busy_tool_dispatches -v`
Expected: PASS.

- [ ] **Step 5: Add the integration test (manual, on-device)**

In `tests/test_integration.py`, add (matching the file's existing `@pytest.mark.integration` style — mirror a nearby calendar test's marker and adapter construction):

```python
@pytest.mark.integration
def test_free_busy_on_device():
    from macos_apps_mcp.adapters.calendar import CalendarAdapter

    # a wide window; asserts structure + invariants, not specific events (device varies)
    out = CalendarAdapter().get_free_busy("2026-07-20T00:00:00", "2026-07-21T00:00:00")
    assert set(out) == {"busy", "free"}
    for block in out["busy"] + out["free"]:
        assert set(block) == {"start", "end"}
        assert block["start"] < block["end"]
    # busy and free never overlap and both stay inside the window
    for b in out["busy"]:
        for f in out["free"]:
            assert b["end"] <= f["start"] or f["end"] <= b["start"]
```

(Do **not** run `-m integration` in CI; note it for the human to run manually.)

- [ ] **Step 6: Update the README tool table**

In `README.md`, add a row directly after the `events` row (~line 65):

```markdown
| `free_busy` | `start`, `end` (ISO), optional `calendars` ids | merged busy intervals + free gaps in the window; no event details |
```

- [ ] **Step 7: Full verification**

Run:
```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```
Expected: all pass, no lint/format diffs. (Integration tests are not collected without `-m integration`.)

- [ ] **Step 8: Commit**

```bash
git add macos_apps_mcp/server.py tests/test_server.py tests/test_integration.py README.md
git commit -m "feat(calendar): free_busy availability tool (#65)"
```

---

## Post-plan

- [ ] Open a PR from `feat/65-free-busy` → `develop`, closing #65. Include the spec link and note the YAGNI deferrals (granularity, min-gap, working-hours mask).
