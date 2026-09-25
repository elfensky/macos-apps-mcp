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


def to_recurrence_rule(r: Recurrence) -> EK.EKRecurrenceRule:
    """Map a Recurrence (RFC-5545 subset) to a native EKRecurrenceRule.

    A value object (no store / thread affinity), so adapters build it inside their
    run_native work block alongside the EKEvent/EKReminder it attaches to.
    """
    end = None
    if r.count is not None:
        end = EK.EKRecurrenceEnd.recurrenceEndWithOccurrenceCount_(r.count)
    elif r.until is not None:
        end = EK.EKRecurrenceEnd.recurrenceEndWithEndDate_(to_nsdate(r.until))
    return EK.EKRecurrenceRule.alloc().initRecurrenceWithFrequency_interval_end_(
        _FREQUENCIES[r.frequency], r.interval, end
    )


def recurrence_signature(recurrence: Recurrence | None) -> tuple | None:
    """Comparable ``(frequency, interval, count)`` of a *requested* recurrence (#49).

    Verify-after-write diffs this against what persisted, so a *changed* cadence (not
    just a dropped rule) fails loudly. UNTIL is omitted on purpose: its endDate carries
    the same inclusive/exclusive ambiguity as an all-day end, so diffing it would
    false-fail a correct write. ``count`` and "no count" both normalize to 0 (a
    date-based/open-ended rule reports 0), so an until rule still matches on count.
    """
    if recurrence is None or recurrence is CLEAR_RECURRENCE:
        return None
    return (
        int(_FREQUENCIES[recurrence.frequency]),
        recurrence.interval,
        recurrence.count or 0,
    )


def persisted_recurrence_signature(rules) -> tuple | None:
    """The same ``(frequency, interval, count)`` read back from a persisted
    EKRecurrenceRule list (the first rule); ``None``/empty → ``None``."""
    if not rules:
        return None
    rule = rules[0]
    end = rule.recurrenceEnd()
    count = end.occurrenceCount() if end is not None else 0
    return (int(rule.frequency()), int(rule.interval()), int(count))


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
