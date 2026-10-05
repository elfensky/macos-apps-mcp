"""The EventKit plane: store, NSDate/RRULE coercion, TCC consent request.

Thread affinity is enforced here (every ``EKEventStore`` call happens on the mac-native
worker), but the worker itself is OWNED by ``runtime`` — this module creates no
executor and dispatches only through ``runtime.run_native``. Never create a second
``EKEventStore`` or a second executor; one process-wide store, one worker, always.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime
from typing import TypeVar

import EventKit as EK
import Foundation as F

from .contracts import CLEAR_RECURRENCE, Recurrence
from .errors import PRIVACY_PANE, AccessDenied, NativeTimeout
from .runtime import log, on_worker, run_native

T = TypeVar("T")

_FULL_ACCESS = EK.EKAuthorizationStatusFullAccess  # == 3 on macOS 14+

# Generous (this wait blocks on the user answering a TCC prompt) but bounded: a callback
# that never fires (headless/sandboxed, EventKit error) must not hang the sole worker —
# and every later run_native — forever. ponytail: bump if a user legitimately needs
# >2min to click Allow.
_ACCESS_TIMEOUT = 120.0  # seconds


def _require_full_access(status: int) -> None:
    """Gate an EKAuthorizationStatus: return on full access, else raise AccessDenied."""
    if status == _FULL_ACCESS:
        return
    raise AccessDenied(
        "macos-apps-mcp needs Calendar + Reminders access. Grant it in "
        f"{PRIVACY_PANE} → Calendars and Reminders, then "
        "restart macos-apps-mcp."
    )


def container_id(item) -> str | None:
    """The item's calendar/list IDENTIFIER, read BEFORE the save — the commit may
    re-home the object, and post-save it would tautologically equal the actual. May be
    None (no writable account); the save then surfaces WriteRefused. Verify keys on the
    identifier, not the title (#55 review). Works for EKEvent and EKReminder alike."""
    cal = item.calendar()
    return cal.calendarIdentifier() if cal is not None else None


_store: EK.EKEventStore | None = None


def store() -> EK.EKEventStore:
    """The one process-wide EKEventStore, created lazily on the worker thread.

    Owned by runtime (not an adapter) so both adapters share one store without reaching
    into each other. Must be called from inside run_native (the mac-native worker).
    """
    global _store
    if not on_worker():
        raise RuntimeError(
            "store() must be called on the mac-native worker — wrap the call in "
            "run_native()"
        )
    if _store is None:
        _store = EK.EKEventStore.alloc().init()
    return _store


def _request_one(s: EK.EKEventStore, entity: int) -> None:
    """Request access for one entity type if undetermined, blocking on the async
    callback."""
    status = EK.EKEventStore.authorizationStatusForEntityType_(entity)
    if status == EK.EKAuthorizationStatusNotDetermined:
        done = threading.Event()
        requester = (
            s.requestFullAccessToEventsWithCompletion_
            if entity == EK.EKEntityTypeEvent
            else s.requestFullAccessToRemindersWithCompletion_
        )

        def handler(granted, error, _done=done):  # fires on a GCD queue, not our worker
            _done.set()

        requester(handler)
        if not done.wait(timeout=_ACCESS_TIMEOUT):
            raise AccessDenied(
                "Timed out waiting for the Calendar/Reminders permission response."
            )
        status = EK.EKEventStore.authorizationStatusForEntityType_(entity)
    _require_full_access(status)


# EventKit TCC surfaces requested at startup. Adapters with their own permission
# (Contacts, Photos) add a separate non-fatal bootstrap step following this pattern.
_ENTITIES = (EK.EKEntityTypeEvent, EK.EKEntityTypeReminder)


def request_access() -> None:
    """Ensure full Calendar + Reminders access; raises AccessDenied on any."""
    s = store()
    for entity in _ENTITIES:
        _request_one(s, entity)


def request_access_each() -> None:
    """Request each EventKit surface independently — one denied surface must never
    block the other's consent prompt (doctor #48 and bootstrap share this)."""
    s = store()
    for entity in _ENTITIES:
        try:
            _request_one(s, entity)
        except AccessDenied as e:
            log.warning("EventKit surface not granted: %s", e)


def bootstrap() -> None:
    """Startup hook: create the store + request each TCC surface on the worker.

    Each surface is requested independently and **non-fatally** — a denied permission
    disables only that adapter (which raises on use), never the server.
    """
    run_native(request_access_each)


_ASYNC_TIMEOUT = 30.0  # seconds


def run_native_async(
    start: Callable[[Callable[[T | None], None]], None],
    timeout: float = _ASYNC_TIMEOUT,
) -> T | None:
    """Block on a completion-handler call; bounded so a dropped callback can't hang.

    Generalizes the EventKit fetch pattern. ``start(finish)`` kicks off the async op
    and arranges its completion handler to call ``finish(result)``; this returns that
    result, or raises NativeTimeout if the callback never fires within ``timeout``.
    Call on the worker (inside run_native), where ``start`` issues the native call.

    Works for GCD-delivered callbacks (EventKit fetch/auth). ponytail: APIs that
    deliver on the main run loop (MapKit, NSMetadataQuery) need an NSRunLoop pump here —
    add it with the first such consumer (Maps #17 / Photos #20) to validate it.
    """
    box: dict[str, T | None] = {}
    done = threading.Event()

    def finish(result: T | None = None) -> None:
        box["result"] = result
        done.set()

    start(finish)
    if not done.wait(timeout=timeout):
        raise NativeTimeout(
            f"native async callback never fired within {timeout}s — the native "
            "service may be hung. Tell the user; do not retry immediately."
        )
    return box.get("result")


def to_nsdate(dt: datetime) -> F.NSDate:
    return F.NSDate.dateWithTimeIntervalSince1970_(dt.timestamp())


def epoch_nsdate(epoch: int) -> F.NSDate:
    """Fold-proof NSDate from an epoch — datetime±timedelta resets the PEP-495 fold
    and shifts DST-repeated-hour instants by 1h (#review)."""
    return F.NSDate.dateWithTimeIntervalSince1970_(epoch)


def from_nsdate(d: F.NSDate) -> datetime:
    return datetime.fromtimestamp(d.timeIntervalSince1970())


def due_components(dt: datetime) -> F.NSDateComponents:
    c = F.NSDateComponents.alloc().init()
    c.setYear_(dt.year)
    c.setMonth_(dt.month)
    c.setDay_(dt.day)
    c.setHour_(dt.hour)
    c.setMinute_(dt.minute)
    return c


_FREQUENCIES = {
    "daily": EK.EKRecurrenceFrequencyDaily,
    "weekly": EK.EKRecurrenceFrequencyWeekly,
    "monthly": EK.EKRecurrenceFrequencyMonthly,
    "yearly": EK.EKRecurrenceFrequencyYearly,
}


# EKWeekday numbers (SU=1 … SA=7) and back.
_WEEKDAYS = {"SU": 1, "MO": 2, "TU": 3, "WE": 4, "TH": 5, "FR": 6, "SA": 7}
_WEEKDAY_CODES = {v: k for k, v in _WEEKDAYS.items()}


def to_recurrence_rule(r: Recurrence) -> EK.EKRecurrenceRule:
    """Map a Recurrence (RFC-5545 subset) to a native EKRecurrenceRule.

    A value object (no store / thread affinity), so adapters build it inside their
    run_native work block alongside the EKEvent/EKReminder it attaches to.

    Built with the 9-argument initializer (D-07): the 3-argument one drops every BY
    part. An absent part is ``None``, not ``[]``; ``weeksOfTheYear`` is always ``None``
    (BYWEEKNO is refused at parse — EventKit saves it but expands only DTSTART).
    """
    end = None
    if r.count is not None:
        end = EK.EKRecurrenceEnd.recurrenceEndWithOccurrenceCount_(r.count)
    elif r.until is not None:
        end = EK.EKRecurrenceEnd.recurrenceEndWithEndDate_(to_nsdate(r.until))
    days = [
        EK.EKRecurrenceDayOfWeek.dayOfWeek_weekNumber_(_WEEKDAYS[code], ordinal)
        for ordinal, code in r.byday
    ]
    return EK.EKRecurrenceRule.alloc().initRecurrenceWithFrequency_interval_daysOfTheWeek_daysOfTheMonth_monthsOfTheYear_weeksOfTheYear_daysOfTheYear_setPositions_end_(  # noqa: E501
        _FREQUENCIES[r.frequency],
        r.interval,
        days or None,
        list(r.bymonthday) or None,
        list(r.bymonth) or None,
        None,
        list(r.byyearday) or None,
        list(r.bysetpos) or None,
        end,
    )


def _canonical(
    freq, interval, byday, bymonthday, bymonth, byyearday, bysetpos, count, until
) -> dict:
    """The one comparable shape for a requested and a persisted rule (D-08)."""
    return {
        "freq": int(freq),
        "interval": int(interval),
        "byday": sorted((int(n), str(code)) for n, code in byday),
        "bymonthday": sorted(int(x) for x in bymonthday or ()),
        "bymonth": sorted(int(x) for x in bymonth or ()),
        "byyearday": sorted(int(x) for x in byyearday or ()),
        "bysetpos": sorted(int(x) for x in bysetpos or ()),
        "count": int(count or 0),
        "until": until,
    }


def recurrence_signature(
    recurrence: Recurrence | None, *, include_until: bool = False
) -> dict | None:
    """Canonical dict of a *requested* recurrence for verify-after-write (#49, D-08).

    Verify diffs this against ``persisted_recurrence_signature``, so a dropped or
    changed BY part, cadence or count fails loudly instead of passing as "a rule is
    there". ``count`` 0 means none (an open-ended or date-ended rule).

    UNTIL is opt-in and day-granular (``YYYYMMDD``, D-09): EventKit stores its endDate
    with an inclusive/exclusive ambiguity, so a timestamp compare would false-fail a
    correct write, while the day survives on device. Callers pass ``include_until``
    for timed items and leave it off for all-day events (#49).
    """
    if recurrence is None or recurrence is CLEAR_RECURRENCE:
        return None
    until = None
    if include_until and recurrence.until is not None:
        until = recurrence.until.strftime("%Y%m%d")
    return _canonical(
        _FREQUENCIES[recurrence.frequency],
        recurrence.interval,
        recurrence.byday,
        recurrence.bymonthday,
        recurrence.bymonth,
        recurrence.byyearday,
        recurrence.bysetpos,
        recurrence.count,
        until,
    )


def persisted_recurrence_signature(
    rules, *, include_until: bool = False
) -> dict | None:
    """The same canonical dict read back from a persisted EKRecurrenceRule list (the
    first rule); ``None``/empty → ``None``. ``include_until`` as in
    ``recurrence_signature``: the persisted endDate is read in local time, to the
    day."""
    if not rules:
        return None
    rule = rules[0]
    end = rule.recurrenceEnd()
    count = end.occurrenceCount() if end is not None else 0
    until = None
    if include_until and end is not None and end.endDate() is not None:
        until = from_nsdate(end.endDate()).strftime("%Y%m%d")
    return _canonical(
        rule.frequency(),
        rule.interval(),
        [
            (d.weekNumber(), _WEEKDAY_CODES[int(d.dayOfTheWeek())])
            for d in rule.daysOfTheWeek() or ()
        ],
        rule.daysOfTheMonth(),
        rule.monthsOfTheYear(),
        rule.daysOfTheYear(),
        rule.setPositions(),
        count,
        until,
    )


_FREQUENCY_NAMES = {int(v): k.upper() for k, v in _FREQUENCIES.items()}


def rrule_text(rule) -> str:
    """Render a persisted EKRecurrenceRule as RRULE text for agent-facing messages,
    e.g. ``FREQ=WEEKLY;INTERVAL=2;COUNT=10``."""
    parts = [
        f"FREQ={_FREQUENCY_NAMES[int(rule.frequency())]}",
        f"INTERVAL={int(rule.interval())}",
    ]
    end = rule.recurrenceEnd()
    if end is not None and end.occurrenceCount() > 0:
        parts.append(f"COUNT={int(end.occurrenceCount())}")
    return ";".join(parts)
