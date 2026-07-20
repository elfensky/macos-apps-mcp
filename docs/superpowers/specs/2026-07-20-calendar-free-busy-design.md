# free_busy availability tool — design

**Issue:** [#65](https://github.com/elfensky/macos-apps-mcp/issues/65) · **Milestone:** 0.7.0 — Differentiators · **Date:** 2026-07-20

## Why

No surveyed Apple-apps MCP server exposes availability. Today the LLM must reason over a full
event dump to answer "when am I free Thursday?". EventKit computes availability natively; the
answer is a compact interval list, not events — token-cheap and privacy-preserving (no titles,
no notes). Greenfield differentiator, not parity.

## Tool surface

```python
@_read_tool
def free_busy(start: str, end: str, calendars: list[str] | None = None) -> dict:
    """Merged busy intervals + free gaps in the window [start, end]."""
```

- `start`, `end` — ISO-8601 datetimes, parsed by `contracts.parse_datetime` (naive-local, DST-safe;
  a date-only string is local midnight). `start >= end` is a loud `ValueError` — an empty/reversed
  window is a caller mistake, not a silent empty result.
- `calendars` — optional list of calendar **ids** (the `Pointer.id` from the `calendars` tool).
  `None` = every calendar. An unknown id raises loudly (resolve-or-raise, matching the adapter's
  existing container resolution).
- **Returns** `{"busy": [{"start", "end"}, …], "free": [{"start", "end"}, …]}` — both lists,
  boundaries as naive-local ISO-8601 strings, every interval clipped to `[start, end]`. Dict return
  matches the existing `now` / `doctor` read tools. No event details by design.

## Adapter method

`CalendarAdapter.get_free_busy(start: datetime, end: datetime, calendars: list[str] | None) -> dict`,
all EventKit access inside `run_native` (single serialized worker — the architecture invariant):

1. Resolve the calendar filter: `None` → pass `None` to the predicate (all calendars); a list →
   map each id to its `EKCalendar` via the store, raising on any unknown id.
2. Build `predicateForEventsWithStartDate_endDate_calendars_(to_nsdate(start), to_nsdate(end), cals)`
   and enumerate matches.
3. Keep an event as **busy unless its availability is explicitly Free**:
   `event.availability() != EK.EKEventAvailabilityFree`. This is the single rule that also handles
   all-day events — EventKit marks all-day events `Free` by default, so they drop out naturally; an
   all-day event a user set to busy still blocks. `NotSupported` (local calendars that don't track
   availability) is `!= Free`, so it counts as busy — the safe default.
4. Convert each kept event to an epoch tuple `(int(start.timeIntervalSince1970()),
   int(end.timeIntervalSince1970()))`.
5. Hand the tuples plus the window bounds to `_merge_busy`, then format the returned epoch tuples
   back to ISO via `from_nsdate(epoch_nsdate(x))` (naive-local, fold-proof).

## Pure merger (the testable core)

Module-level in `calendar.py`, no EventKit dependency — this is where the acceptance-test logic lives
and it is unit-tested directly, no device/TCC:

```python
def _merge_busy(
    intervals: list[tuple[int, int]], lo: int, hi: int
) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """Merge overlapping/adjacent busy intervals within [lo, hi]; return (busy, free)."""
```

- Clip each interval to `[lo, hi]`; drop any that is empty after clipping (`start >= end`), which
  also drops zero-length events.
- Sort by start. Merge the next interval into the current run when `next.start <= cur.end` — `<=`
  covers **adjacency** (back-to-back meetings become one block) as well as overlap.
- `free` = the complement of the merged busy runs within `[lo, hi]`: the gap before the first run,
  between consecutive runs, and after the last run. All-free → `busy == []`, `free == [(lo, hi)]`.
  All-busy → `free == []`.

**Everything is epoch seconds.** Comparing/merging instants as integers is fold-proof — the same
reason the adapter already uses `epoch_nsdate` for occurrence windows. No naive-datetime arithmetic
crosses a DST boundary, so a free gap spanning the fall-back repeated hour emits correct boundaries.

## Tests

Unit (no EventKit, no TCC) — `test_free_busy.py`, exercising `_merge_busy` directly:

- Overlapping blocks merge into one.
- Adjacent blocks (`next.start == cur.end`) merge into one.
- Free complement: leading gap (window start → first busy), middle gaps, trailing gap.
- All-free window → `busy == []`, `free == [(lo, hi)]`.
- All-busy window → `free == []`.
- Interval extending past the window is clipped to the bounds.
- Zero-length / post-clip-empty interval is dropped.
- DST-boundary: a busy block and free gap straddling a fall-back transition emit the expected epoch
  boundaries (built from epochs, never `datetime ± timedelta`).

Server-layer: `free_busy` tool returns the `{"busy", "free"}` dict shape, via the existing
Protocol-fake pattern (mock the adapter boundary — no real store).

Integration (`-m integration`, manual only, never CI): availability/transparency and all-day
handling verified against a real EventKit store on-device — the flags that can't be faked in a unit
test.

## Out of scope (YAGNI)

Each is a pure post-filter, non-breaking to add when a concrete caller needs it:

- **granularity / slot-snapping** — rounding busy blocks out to 15/30/60-min slots. Fights the
  exact-interval value prop; dropped (the issue itself marked it `?`).
- **min-gap filter** — suppressing free slivers below a threshold.
- **working-hours mask** — with a multi-day range, overnight hours report as one large `free` block.
  This is correct for a primitive: the caller passes exactly the window they care about (e.g.
  `Thursday 09:00–17:00`). A working-hours mask is a caller concern, layered on top.
- **interval-count cap** — merging already compresses realistic days well under the ~1k-token target;
  a pathological calendar is a wide-range caller choice.
