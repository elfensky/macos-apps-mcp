"""Native-call runtime: serialize ALL EventKit access onto ONE dedicated thread.

Settled by design (adversarial debate). ``EKEventStore`` has **thread affinity** (it
must be accessed from the thread that created it) and **TCC** authorization must be
handled on a consistent thread. A generic ``asyncio.to_thread`` / default multi-worker
pool scatters calls across threads → affinity bugs and a hung first-permission prompt.
So every native call goes through a single ``max_workers=1`` executor; the
``EKEventStore``
itself is created *inside* that worker, lazily by ``store()`` (owned by runtime, not the
adapters — they obtain it by calling ``store()`` via run_native).

This is user-latency-bound, not throughput-bound, so serialization costs nothing in
practice.
"""

from __future__ import annotations

import logging
import subprocess
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import TypeVar

import EventKit as EK
import Foundation as F

from .contracts import Recurrence

T = TypeVar("T")

# ponytail: one process-wide native thread. If a future app needs a *second* isolated
# native context, give it its own executor — don't widen this one to max_workers>1
# (breaks EKEventStore).
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mac-native")


def run_native(fn: Callable[[], T]) -> T:
    """Run a blocking native callable on the single dedicated worker thread and return
    its result.

    Adapters wrap every EventKit / osascript call in this so the work always lands on
    one thread, regardless of which thread FastMCP invoked the tool from.
    """
    return _executor.submit(fn).result()


_FULL_ACCESS = EK.EKAuthorizationStatusFullAccess  # == 3 on macOS 14+

# Generous (this wait blocks on the user answering a TCC prompt) but bounded: a callback
# that never fires (headless/sandboxed, EventKit error) must not hang the sole worker —
# and every later run_native — forever. ponytail: bump if a user legitimately needs
# >2min to click Allow.
_ACCESS_TIMEOUT = 120.0  # seconds


# --- typed error taxonomy (#47) ------------------------------------------------------
# The winnable axis is trust: the category leader died of *fake success* — stubbed reads
# returning [] made permission-denied / crashed / genuinely-empty indistinguishable, so
# the agent hammered a denied tool. Every native failure is one of these loud, typed
# classes; str(e) IS the agent-directed remediation. The dispatch layer (server.py)
# turns them into MCP tool *results* carrying that directive — never a silent [], never
# a masked stack trace. `kind` is the machine code doctor (#48) and tests branch on.


class NativeError(RuntimeError):
    """Base for every typed native failure. ``str(e)`` is the agent-facing directive."""

    kind = "native_error"


class AccessDenied(NativeError):
    """Calendar/Reminders (EventKit) TCC access is not fully granted."""

    kind = "access_denied"


class AutomationDenied(NativeError):
    """osascript blocked from controlling an app — Automation consent not granted."""

    kind = "automation_denied"


class AppNotRunning(NativeError):
    """The target app isn't running / its Apple-events connection is invalid."""

    kind = "app_not_running"


class NativeTimeout(NativeError):
    """A native call didn't return in time (stuck dialog, pathological query)."""

    kind = "native_timeout"


class OutputOverflow(NativeError):
    """A native result exceeded the caller's size cap (raised by callers, e.g. #52)."""

    kind = "output_overflow"


class SchemaDrift(NativeError):
    """Native output didn't match the shape the parser expects (an OS/app change)."""

    kind = "schema_drift"


class VerificationFailed(NativeError):
    """A create/update didn't persist as requested — the returned id is fabricated, or
    a field was dropped, or iCloud reverted the write (#49)."""

    kind = "verification_failed"


def verify_persisted(
    entity: str, expected: dict[str, object], actual: dict[str, object]
) -> None:
    """Diff requested field values against what the store actually persisted; raise
    ``VerificationFailed`` naming every dropped/changed field (#49).

    The anti-fabrication + anti-rollback check behind every create/update: the category
    leader shipped a fabricated id and dropped due/list (supermemoryai #64), and iCloud
    can revert a write ~1s later — and our writes feed the vault id-writeback, so a fake
    or reverted id silently corrupts the cockpit. Callers pass primitives already
    normalized for comparison (dates → epoch ints / y-m-d tuples, containers → names) so
    this stays pure and unit-testable with plain fakes.
    """
    dropped = {k: (v, actual.get(k)) for k, v in expected.items() if actual.get(k) != v}
    if dropped:
        fields = "; ".join(
            f"{k}: requested {req!r}, persisted {got!r}"
            for k, (req, got) in dropped.items()
        )
        raise VerificationFailed(
            f"{entity} write did not persist as requested (dropped or reverted; iCloud "
            f"can roll a write back ~1s later). Mismatches: {fields}. Re-read the item "
            "before trusting it; do not reuse the returned id."
        )


def _decide(status: int) -> None:
    """Map an EKAuthorizationStatus to a decision: return on full access, else raise."""
    if status == _FULL_ACCESS:
        return
    raise AccessDenied(
        "mac-mcp needs Calendar + Reminders access. Grant it in "
        "System Settings → Privacy & Security → Calendars and Reminders, then "
        "restart mac-mcp."
    )


_store: EK.EKEventStore | None = None


def _on_worker() -> bool:
    return threading.current_thread().name.startswith("mac-native")


def store() -> EK.EKEventStore:
    """The one process-wide EKEventStore, created lazily on the worker thread.

    Owned by runtime (not an adapter) so both adapters share one store without reaching
    into each other. Must be called from inside run_native (the mac-native worker).
    """
    global _store
    if not _on_worker():
        raise RuntimeError(
            "store() must be called on the mac-native worker — wrap the call in "
            "run_native()"
        )
    if _store is None:
        _store = EK.EKEventStore.alloc().init()
    return _store


# osascript is the escape hatch for apps with no PyObjC framework (Mail, Notes, etc.).
# It runs on the SAME worker as EventKit — serialized, never concurrent — so the
# max_workers=1 fence covers all native access. A timeout bounds it so a hung script
# (e.g. a modal permission dialog) can't block the worker forever.
_OSASCRIPT_TIMEOUT = 30.0  # seconds

# osascript reports native failures as an OSStatus in parentheses at the end of stderr,
# e.g. "…Not authorized to send Apple events to Mail. (-1743)". Match the parenthesized
# form so a bare digit run never false-fingerprints. Codes per the survey (#47 design).
_AUTOMATION_DENIED = "(-1743)"  # Automation (Apple-events) consent not granted
_APP_NOT_RUNNING = ("(-609)", "(-10810)")  # connection invalid / app not launchable


def _classify_osascript_failure(stderr: str) -> NativeError:
    """Fingerprint a non-zero osascript exit into a typed, agent-directed error.

    Only the failures with a *clear* remediation get a specific class; everything else
    stays a loud generic ``NativeError`` (never swallowed, never an empty result). The
    raw native detail is appended in ``[...]`` so the model has the underlying evidence.
    """
    detail = stderr.strip() or "osascript failed with no stderr"
    if _AUTOMATION_DENIED in stderr:
        return AutomationDenied(
            "macOS blocked mac-mcp from controlling the app (Automation consent not "
            "granted). Tell the user to enable it in System Settings → Privacy & "
            "Security → Automation, for whichever app launched mac-mcp, then restart "
            f"mac-mcp. Do not retry until the next user message. [{detail}]"
        )
    if any(code in stderr for code in _APP_NOT_RUNNING):
        return AppNotRunning(
            "The target macOS app isn't running or couldn't be launched. Tell the user "
            f"to open it, then try again once it's open. [{detail}]"
        )
    return NativeError(f"osascript failed: {detail}")


def run_osascript(script: str, *args: str, timeout: float = _OSASCRIPT_TIMEOUT) -> str:
    """Run an AppleScript via ``osascript`` on the native worker; return stdout.

    The sanctioned escape hatch for framework-less apps (Mail/Notes/Contacts).
    ``args`` are passed to the script's ``on run argv`` handler — put any user input
    (names, ids) there so values are never interpolated into the script (no injection).
    Raises a typed ``NativeError`` (``AutomationDenied`` / ``AppNotRunning`` / generic)
    on a non-zero exit, and ``NativeTimeout`` on timeout — it never returns an empty
    string to mask a failure as "no result". Safe on or off the worker (dispatches via
    run_native when called off it).
    """

    def _run() -> str:
        try:
            proc = subprocess.run(
                ["osascript", "-e", script, *args],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as e:
            raise NativeTimeout(
                f"The macOS app didn't respond within {timeout}s (it may be blocked on "
                "a dialog, or the query is too broad). Tell the user to dismiss any "
                "stuck prompt, then retry with a narrower query. Do not retry "
                "immediately."
            ) from e
        if proc.returncode != 0:
            raise _classify_osascript_failure(proc.stderr)
        return proc.stdout.rstrip("\n")

    return _run() if _on_worker() else run_native(_run)


_ASYNC_TIMEOUT = 30.0  # seconds


def run_native_async(start, timeout: float = _ASYNC_TIMEOUT):
    """Block on a completion-handler call; bounded so a dropped callback can't hang.

    Generalizes the EventKit fetch pattern. ``start(finish)`` kicks off the async op
    and arranges its completion handler to call ``finish(result)``; this returns that
    result, or raises TimeoutError if the callback never fires within ``timeout``.
    Call on the worker (inside run_native), where ``start`` issues the native call.

    Works for GCD-delivered callbacks (EventKit fetch/auth). ponytail: APIs that
    deliver on the main run loop (MapKit, NSMetadataQuery) need an NSRunLoop pump here —
    add it with the first such consumer (Maps #17 / Photos #20) to validate it.
    """
    box: dict = {}
    done = threading.Event()

    def finish(result=None):
        box["result"] = result
        done.set()

    start(finish)
    if not done.wait(timeout=timeout):
        raise TimeoutError(f"native async callback never fired within {timeout}s")
    return box.get("result")


def to_nsdate(dt: datetime) -> F.NSDate:
    return F.NSDate.dateWithTimeIntervalSince1970_(dt.timestamp())


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
    if recurrence is None:
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


log = logging.getLogger("mac_mcp")


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
    _decide(status)


# EventKit TCC surfaces requested at startup. Adapters with their own permission
# (Contacts, Photos) add a separate non-fatal bootstrap step following this pattern.
_ENTITIES = (EK.EKEntityTypeEvent, EK.EKEntityTypeReminder)


def request_access() -> None:
    """Ensure full Calendar + Reminders access; raises AccessDenied on any."""
    s = store()
    for entity in _ENTITIES:
        _request_one(s, entity)


def bootstrap() -> None:
    """Startup hook: create the store + request each TCC surface on the worker.

    Each surface is requested independently and **non-fatally** — a denied permission
    disables only that adapter (which raises on use), never the server.
    """

    def _request_all() -> None:
        s = store()
        for entity in _ENTITIES:
            try:
                _request_one(s, entity)
            except AccessDenied as e:
                log.warning("mac-mcp starting without one EventKit surface: %s", e)

    run_native(_request_all)
