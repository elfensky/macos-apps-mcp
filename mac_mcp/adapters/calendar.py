"""Calendar adapter — EventKit via PyObjC.

Reads return Pointers; writes take ``CalendarEventData``. All EventKit access goes
through ``runtime.run_native``; the store is owned by runtime (shared, not
reached-into).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import EventKit as EK

from ..contracts import CalendarEventData, Pointer
from ..runtime import (
    SpanRequired,
    VerificationFailed,
    from_nsdate,
    persisted_recurrence_signature,
    recurrence_signature,
    run_native,
    store,
    to_nsdate,
    to_recurrence_rule,
    verify_persisted,
)


def _range(query: str) -> tuple[datetime, datetime]:
    q = query.strip().lower()
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if q == "today":
        return today, today + timedelta(days=1)
    if q == "week":
        return today, today + timedelta(days=7)
    day = datetime.fromisoformat(query.strip()).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return day, day + timedelta(days=1)


def _event_summary(item) -> str:
    start = from_nsdate(item.startDate())
    if item.isAllDay():
        return f"{item.title()} (all day {start:%Y-%m-%d})"
    end = from_nsdate(item.endDate())
    return f"{item.title()} {start:%H:%M}–{end:%H:%M}"


def _event_deeplink(item) -> str:
    # calshow:<seconds-since-2001> opens Calendar to the event's day/time. macOS has no
    # public scheme to open a *specific* event by id (x-apple-calevent:// is rejected;
    # eventIdentifier isn't URL-addressable, and is occurrence-shared). See Apple Dev
    # Forums #759266. Co-starting events thus share a deeplink; the Pointer summary +
    # occurrence-precise id (see _event_id) disambiguate, not the link.
    secs = int(item.startDate().timeIntervalSinceReferenceDate())
    return f"calshow:{secs}"


# Recurring events share ONE calendarItemIdentifier across every occurrence, so the
# bare id can't name a single occurrence. Carry the occurrence start (epoch seconds) in
# the pointer id and re-fetch the concrete EKEvent on write (see _resolve_event), so
# EKSpanThisEvent targets THAT occurrence.
_OCC_SEP = "|"


def _event_id(item) -> str:
    base = item.calendarItemIdentifier()
    epoch = int(item.startDate().timeIntervalSince1970())
    return f"{base}{_OCC_SEP}{epoch}"


def _event_pointer(item) -> Pointer:
    return Pointer(
        id=_event_id(item),
        summary=_event_summary(item),
        deeplink=_event_deeplink(item),
    )


def _calendar_pointer(cal) -> Pointer:
    # A calendar (container) has no public per-calendar URL scheme; id + name (summary)
    # are what the projection resolves a write target against. deeplink empty by design.
    return Pointer(id=cal.calendarIdentifier(), summary=cal.title(), deeplink="")


def _resolve_calendar(s, name: str | None):
    if name is None:
        return s.defaultCalendarForNewEvents()
    for c in s.calendarsForEntityType_(EK.EKEntityTypeEvent):
        if c.title() == name:
            return c
    raise ValueError(f"no calendar named {name!r}")


def _all_day_bounds(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    """Snap an all-day event's bounds to date-only midnight so a stored time can't drift
    on CalDAV roundtrips. EventKit's all-day end date is INCLUSIVE (verified on-device:
    the event covers start's day through end's day), so a same-day event keeps
    ``end == start`` as one day; only a reversed span clamps back to a single day.

    An all-day event is a calendar date, not an instant — so tzinfo is dropped too:
    that keeps date-only math well-defined and stops a mixed naive/aware (start, end)
    pair from the tool boundary raising on the comparison below."""
    floor = {"hour": 0, "minute": 0, "second": 0, "microsecond": 0, "tzinfo": None}
    s, e = start.replace(**floor), end.replace(**floor)
    if e < s:  # reversed input only: clamp to a single day (end inclusive == start)
        e = s
    return s, e


def _apply_event(s, e, data: CalendarEventData) -> None:
    e.setTitle_(data.title)
    e.setAllDay_(data.all_day)
    start, end = data.start, data.end
    if data.all_day:  # date-only bounds — EventKit/CalDAV must not see a stray time
        start, end = _all_day_bounds(start, end)
    e.setStartDate_(to_nsdate(start))
    e.setEndDate_(to_nsdate(end))
    e.setLocation_(data.location)  # full-replace: None clears
    e.setNotes_(data.notes)  # full-replace: None clears
    # Recurrence is the exception to full-replace: only SET it when provided. Clearing a
    # series needs EKSpanFutureEvents (see _resolve_span), but an omitted recurrence
    # means "edit this occurrence" (EKSpanThisEvent) — so clearing-on-None would detach
    # one occurrence and leave the series recurring. Leave the rule untouched.
    if data.recurrence is not None:
        e.setRecurrenceRules_([to_recurrence_rule(data.recurrence)])
    e.setCalendar_(_resolve_calendar(s, data.calendar))
    # ponytail: all-day alarm 1440-gotcha (#51) — EKAlarm relativeOffset for an all-day
    # event is measured from MIDNIGHT, so "9am the day before" is -1440+540 = -900 min,
    # NOT -900 from an implicit 9am. We set no alarms yet (no alarm field on
    # CalendarEventData), so nothing can go wrong; wire the -1440 base in with the alarm
    # field, and test it then.


# EKSpanThisEvent == 0 (falsy!), EKSpanFutureEvents == 1 — so map via membership, never
# a truthy test.
_SPANS = {
    "this-event": EK.EKSpanThisEvent,
    "future-events": EK.EKSpanFutureEvents,
}


def _resolve_span(e, span: str | None, *, adds_recurrence: bool = False) -> int:
    """The EKSpan for an update/delete — requiring an explicit choice for a recurring
    target (#51).

    Editing/deleting one occurrence vs rewriting the whole series is destructive to get
    wrong (mcp-ical silently rewrote users' series with a hardcoded EKSpanFutureEvents),
    so a **recurring** event demands an explicit ``span``; a **single** event ignores it
    (span is moot — EventKit has no other occurrences to span). Adding a rule to a
    single event is inherently series-defining, so it saves future-events.
    """
    if not e.recurrenceRules():  # single event — span is moot
        return EK.EKSpanFutureEvents if adds_recurrence else EK.EKSpanThisEvent
    if span is None:
        raise SpanRequired(
            "This is a recurring event — specify span='this-event' (only this "
            "occurrence) or span='future-events' (this and all later), then retry. "
            "No change was made."
        )
    if span not in _SPANS:
        raise SpanRequired(
            "span must be 'this-event' or 'future-events' for a recurring event; got "
            f"{span!r}. No change was made."
        )
    return _SPANS[span]


def _resolve_event(s, ident: str):
    """Resolve a pointer id to the concrete EKEvent (specific occurrence if recurring).

    Pointer ids are ``<calendarItemIdentifier>|<occurrence-start-epoch>``.
    ``calendarItemWithIdentifier_`` returns the series *master* (shared across
    occurrences), so editing/deleting it with EKSpanThisEvent hits the wrong occurrence.
    Re-fetch via a tight date-range predicate and match on (calendarItemIdentifier,
    start) so the write targets exactly the cited occurrence.
    """
    base, sep, occ = ident.rpartition(_OCC_SEP)
    if (
        not sep
    ):  # legacy/plain id (no occurrence suffix) — fall back to the master lookup
        e = s.calendarItemWithIdentifier_(ident)
        if e is None:
            raise ValueError(f"no event with id {ident!r}")
        return e
    occ_epoch = int(occ)
    occ_start = datetime.fromtimestamp(occ_epoch)
    pred = s.predicateForEventsWithStartDate_endDate_calendars_(
        to_nsdate(occ_start - timedelta(seconds=1)),
        to_nsdate(occ_start + timedelta(seconds=1)),
        None,
    )
    for e in s.eventsMatchingPredicate_(pred) or []:
        if (
            e.calendarItemIdentifier() == base
            and int(e.startDate().timeIntervalSince1970()) == occ_epoch
        ):
            return e
    raise ValueError(f"no event occurrence for id {ident!r}")


def _verify_event(fresh, ident: str, data: CalendarEventData, cal_title: str) -> None:
    """Re-fetch-by-id verify (#49): fail loudly if the saved event didn't persist as
    requested. `fresh` is a fresh re-resolve of the occurrence we're about to return;
    `cal_title` is the requested calendar (what _apply_event set)."""
    if fresh is None:
        raise VerificationFailed(
            f"event {ident!r} could not be re-fetched after save — the write did not "
            "persist (a fabricated id or an iCloud rollback). Do not trust the id."
        )
    expected = {
        "title": data.title,
        "all_day": data.all_day,
        "location": data.location or None,  # "" and None are both "no location"
        "notes": data.notes or None,
        "calendar": cal_title,
    }
    actual = {
        "title": fresh.title(),
        "all_day": bool(fresh.isAllDay()),
        "location": fresh.location() or None,
        "notes": fresh.notes() or None,
        "calendar": fresh.calendar().title(),
    }
    fresh_start = from_nsdate(fresh.startDate())
    if data.all_day:
        # EventKit's internal all-day END representation is ambiguous (inclusive vs
        # stored-as-next-midnight) — an end-epoch check would false-fail every all-day
        # event, so verify the start *date* + the flag only. End stays on-device
        # calibration (integration), like the deeplinks.
        s_exp, _ = _all_day_bounds(data.start, data.end)
        expected["start_date"] = (s_exp.year, s_exp.month, s_exp.day)
        actual["start_date"] = (fresh_start.year, fresh_start.month, fresh_start.day)
    else:
        expected["start"] = int(data.start.timestamp())
        expected["end"] = int(data.end.timestamp())
        actual["start"] = int(fresh_start.timestamp())
        actual["end"] = int(from_nsdate(fresh.endDate()).timestamp())
    if data.recurrence is not None:  # None = "leave series untouched" (_apply_event)
        # verify the exact cadence, not just presence — a wrong-frequency series is a
        # changed field #49 must name (UNTIL deferred; see recurrence_signature).
        expected["recurs"] = recurrence_signature(data.recurrence)
        actual["recurs"] = persisted_recurrence_signature(fresh.recurrenceRules())
    verify_persisted("event", expected, actual)


def _refetch_event(s, ident: str):
    """Re-resolve the occurrence by id after a write; a not-found is a persistence
    failure (fabricated id / rollback), not a plain lookup miss."""
    try:
        return _resolve_event(s, ident)
    except ValueError as e:
        raise VerificationFailed(
            f"event {ident!r} could not be re-fetched after save — the write did not "
            "persist (a fabricated id or an iCloud rollback). Do not trust the id."
        ) from e


class CalendarAdapter:
    def get_pointers(self, query: str) -> list[Pointer]:
        """query: 'today' | 'week' | 'YYYY-MM-DD'."""

        def work():
            s = store()
            start, end = _range(query)
            pred = s.predicateForEventsWithStartDate_endDate_calendars_(
                to_nsdate(start), to_nsdate(end), None
            )
            return [_event_pointer(e) for e in (s.eventsMatchingPredicate_(pred) or [])]

        return run_native(work)

    def get_calendars(self) -> list[Pointer]:
        """Enumerate calendars as Pointers (id + name) for resolving write targets."""

        def work():
            s = store()
            return [
                _calendar_pointer(c)
                for c in s.calendarsForEntityType_(EK.EKEntityTypeEvent)
            ]

        return run_native(work)

    def create_event(self, data: CalendarEventData) -> Pointer:
        def work():
            s = store()
            e = EK.EKEvent.eventWithEventStore_(s)
            # A fresh event has no rules → single-event path; a create defining a series
            # saves future-events. No span param — create is never an ambiguous edit.
            span = _resolve_span(e, None, adds_recurrence=data.recurrence is not None)
            _apply_event(s, e, data)
            ok, err = s.saveEvent_span_commit_error_(e, span, True, None)
            if not ok:
                raise RuntimeError(f"save event failed: {err}")
            # Re-resolve by the occurrence id we'll return — never trust the in-memory
            # event (#49): prove the id resolves and the fields persisted.
            ident = _event_id(e)
            fresh = _refetch_event(s, ident)
            _verify_event(fresh, ident, data, e.calendar().title())
            return _event_pointer(fresh)

        return run_native(work)

    def update_event(
        self, ident: str, data: CalendarEventData, span: str | None = None
    ) -> Pointer:
        def work():
            s = store()
            e = _resolve_event(s, ident)
            # Resolve span BEFORE saving: a recurring target with no span raises here,
            # so no write happens (#51). Checks the ORIGINAL event's rules, so a
            # single→recurring conversion is series-defining, not ambiguous.
            ek_span = _resolve_span(
                e, span, adds_recurrence=data.recurrence is not None
            )
            _apply_event(s, e, data)
            ok, err = s.saveEvent_span_commit_error_(e, ek_span, True, None)
            if not ok:
                raise RuntimeError(f"save event failed: {err}")
            # Re-key from the post-apply event: if start changed, _event_id(e) carries
            # the new occurrence epoch, so we re-resolve (and cite) it as persisted.
            ident_after = _event_id(e)
            fresh = _refetch_event(s, ident_after)
            _verify_event(fresh, ident_after, data, e.calendar().title())
            return _event_pointer(fresh)

        return run_native(work)

    def delete_event(self, ident: str, span: str | None = None) -> None:
        def work():
            s = store()
            e = _resolve_event(s, ident)
            ek_span = _resolve_span(
                e, span
            )  # recurring + no span → SpanRequired, no write
            ok, err = s.removeEvent_span_commit_error_(e, ek_span, True, None)
            if not ok:
                raise RuntimeError(f"delete event failed: {err}")

        run_native(work)
