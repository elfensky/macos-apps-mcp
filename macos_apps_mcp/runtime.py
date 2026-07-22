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

import contextlib
import logging
import os
import sqlite3
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import TypeVar
from urllib.parse import quote

import EventKit as EK
import Foundation as F

from .contracts import CLEAR_RECURRENCE, Recurrence
from .errors import (
    PRIVACY_PANE,
    AccessDenied,
    AppNotRunning,
    AutomationDenied,
    FullDiskAccessDenied,
    NativeError,
    NativeTimeout,
    SchemaDrift,
)

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


# NOTE: the typed error taxonomy (#47) and the pure write policies —
# resolve_container, refused_write, verify_persisted, require_batch_within — live in
# errors.py: no native imports there, so adapters/tests use them without loading this
# module's EventKit/Foundation. runtime raises those classes; it does not define them.


def container_id(item) -> str | None:
    """The item's calendar/list IDENTIFIER, read BEFORE the save — the commit may
    re-home the object, and post-save it would tautologically equal the actual. May be
    None (no writable account); the save then surfaces WriteRefused. Verify keys on the
    identifier, not the title (#55 review). Works for EKEvent and EKReminder alike."""
    cal = item.calendar()
    return cal.calendarIdentifier() if cal is not None else None


# NOTE: text hygiene / fold / verify-normalization live in text.py (#52/#49/#64) —
# pure string work with no coupling to the native worker.


def _require_full_access(status: int) -> None:
    """Gate an EKAuthorizationStatus: return on full access, else raise AccessDenied."""
    if status == _FULL_ACCESS:
        return
    raise AccessDenied(
        "macos-apps-mcp needs Calendar + Reminders access. Grant it in "
        f"{PRIVACY_PANE} → Calendars and Reminders, then "
        "restart macos-apps-mcp."
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
            "macOS blocked macos-apps-mcp from controlling the app (Automation consent "
            f"not granted). Tell the user to enable it in {PRIVACY_PANE} → "
            "Automation, for whichever app launched macos-apps-mcp, then "
            "restart macos-apps-mcp. Do not retry until the next user message. "
            f"[{detail}]"
        )
    if any(code in stderr for code in _APP_NOT_RUNNING):
        return AppNotRunning(
            "The target macOS app isn't running or couldn't be launched. Tell the user "
            f"to open it, then try again once it's open. [{detail}]"
        )
    return NativeError(f"osascript failed: {detail}")


# In-flight osascript children, tracked so exit paths (atexit / SIGTERM / orphan
# watcher, #56) can terminate them — an orphaned synchronous Apple Event pinned Mail's
# main thread indefinitely (patrickfreyer #58). The serialized worker means at most one
# at a time, but a set + lock is robust and cheap. The AppleScript-level `with timeout`
# in each template is the second line of defense: it self-terminates a hung child even
# if the Python side died first and never got to call terminate().
_children: set[subprocess.Popen] = set()
_children_lock = threading.Lock()


def terminate_children() -> None:
    """Terminate any in-flight osascript child. Idempotent; safe from any thread and at
    shutdown (an already-dead child raises OSError on terminate, ignored)."""
    with _children_lock:
        children = list(_children)
    for proc in children:
        with contextlib.suppress(OSError):
            proc.terminate()


def run_osascript(script: str, *args: str, timeout: float = _OSASCRIPT_TIMEOUT) -> str:
    """Run an AppleScript via ``osascript`` on the native worker; return stdout.

    The sanctioned escape hatch for framework-less apps (Mail/Notes/Contacts).
    ``args`` are passed to the script's ``on run argv`` handler — put any user input
    (names, ids) there so values are never interpolated into the script (no injection).
    A ``--`` separates the script from ``args`` so a value starting with ``-`` (e.g. a
    mail search for "-- Original Message") is delivered as script DATA, not parsed by
    osascript's getopt as its own option (#62 review). Raises a typed ``NativeError``
    (``AutomationDenied`` / ``AppNotRunning`` / generic) on a non-zero exit, and
    ``NativeTimeout`` on timeout — it never returns an empty string to mask a failure as
    "no result". Safe on or off the worker (dispatches via run_native off it). The child
    is tracked so an exit path can kill it (#56); the AppleScript template's own
    ``with timeout`` bounds it if we can't.
    """

    def _run() -> str:
        # Popen (not subprocess.run) so the live child is a handle exit paths can
        # terminate; communicate(timeout) + kill-on-timeout mirrors run(timeout=). The
        # `--` stops osascript option scanning so a leading-'-' arg is positional data,
        # not a flag (#62 review). It is consumed by getopt, not delivered into `on run
        # argv`, so every existing template's argv indices are unchanged.
        started = time.monotonic()
        proc = subprocess.Popen(
            ["osascript", "-e", script, "--", *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        with _children_lock:
            _children.add(proc)
        try:
            try:
                out, err = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired as e:
                proc.kill()
                proc.communicate()  # reap so we don't leak a zombie
                raise NativeTimeout(
                    f"The macOS app didn't respond within {timeout}s (it may be "
                    "blocked on a dialog, or the query is too broad). Tell the user to "
                    "dismiss any stuck prompt, then retry with a narrower query. Do "
                    "not retry immediately."
                ) from e
        finally:
            with _children_lock:
                _children.discard(proc)
        if proc.returncode != 0:
            raise _classify_osascript_failure(err)
        # debug telemetry (#56): opt-in via logging level, zero cost otherwise.
        log.debug(
            "osascript %.0fms, %d bytes out",
            (time.monotonic() - started) * 1000,
            len(out),
        )
        # trailing newlines inside the data must survive; remove only osascript's own
        # single terminating newline
        return out[:-1] if out.endswith("\n") else out

    return _run() if _on_worker() else run_native(_run)


@contextlib.contextmanager
def body_file(text: str):
    """A 0600 utf-8 tempfile holding ``text``, for an AppleScript template to read as
    ``«class utf8»`` — the safe transport for a large/multiline/unicode body (never
    interpolated into the script; the supermemoryai pattern, #62). Yields the path
    (pass it as the template's LAST argv item); the file is deleted on exit — the
    script runs synchronously, so it has already consumed the content. The one home
    for the mkstemp → write → unlink dance mail and notes each hand-rolled twice."""
    fd, path = tempfile.mkstemp(prefix="macos-apps-mcp-body-", suffix=".txt")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        yield path
    finally:
        with contextlib.suppress(OSError):
            os.unlink(path)


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


# --- dual-backend read plane: read-only sqlite opener + schema fingerprint (#58) -----
# The escape from AppleScript-as-query-engine (the ecosystem's death spiral: reads get
# slow → get stubbed → project abandoned). Native stores answer QUERIES; AppleScript
# only performs ACTIONS. chat.db / NoteStore.sqlite are read through ONE read-only
# opener, serialized on the native worker for consistency with EventKit/osascript (these
# reads are user-latency-bound, not throughput-bound — same rationale as the
# max_workers=1 fence). A schema fingerprint guards every parser against a silent macOS
# schema change. This is the shared plumbing the sqlite read planes (#59 Messages, #60
# Notes) build on with no new plumbing of their own.


def _open_sqlite_ro(path: Path | str, *, immutable: bool = False) -> sqlite3.Connection:
    """Open a system sqlite store STRICTLY read-only.

    Preflights with a raw read so a Full-Disk-Access denial surfaces as a typed
    ``FullDiskAccessDenied`` — sqlite3 alone gives only an opaque "unable to open
    database file" that can't be told apart from a missing file. ``mode=ro`` never
    creates the file and forbids writes at the SQLite layer.

    ``immutable=1`` is OPT-IN and unsafe for a live store: it tells SQLite the file
    never changes, so it ignores the ``-wal`` and returns pre-WAL data — recent items
    would silently vanish. Pass it only for a store known static. Call inside
    run_native: the connection is thread-bound, so the whole query must run on the
    worker.
    """
    p = Path(path)
    try:
        with open(p, "rb") as f:  # preflight: classify FDA-denied vs genuinely-absent
            f.read(1)
    except PermissionError as e:
        raise FullDiskAccessDenied(
            "macos-apps-mcp could not read a macOS data store — Full Disk Access is "
            f"not granted. Grant it in {PRIVACY_PANE} → Full "
            "Disk Access to the app that launched macos-apps-mcp, then restart "
            "macos-apps-mcp. Do not retry until the next user message."
        ) from e
    except FileNotFoundError as e:
        raise NativeError(
            f"the macOS data store {p.name!r} does not exist (the app may never have "
            "been used). This is not a Full Disk Access problem; do not retry."
        ) from e
    except OSError as e:  # dir-as-path, ELOOP, ENOTDIR, EIO … stay typed, never raw
        raise NativeError(
            f"the macOS data store at {p} could not be opened: {e}. Do not retry."
        ) from e
    uri = f"file:{quote(str(p))}?mode=ro" + ("&immutable=1" if immutable else "")
    try:
        return sqlite3.connect(uri, uri=True)
    except sqlite3.Error as e:  # rare (preflight passed) → treat as store-unavailable
        raise SchemaDrift(
            f"the sqlite store {p.name!r} could not be opened ({e}). Falling back or "
            "surfacing rather than trusting an unreadable store."
        ) from e


def verify_sqlite_schema(
    conn: sqlite3.Connection, fingerprint: dict[str, set[str]]
) -> None:
    """Raise ``SchemaDrift`` unless each expected table has every expected column (#58).

    ``fingerprint`` maps table name → the columns the parser reads. macOS updates move
    these schemas; catching drift here means the dual-backend falls back (or fails
    loudly) instead of mis-parsing renamed/dropped columns into garbage Pointers. Table
    names come from adapter code, but are still BOUND via the ``pragma_table_info``
    table-valued function (never string-formatted) so the helper is injection-safe.
    """
    for table, columns in fingerprint.items():
        try:
            # SQLite identifiers are case-INSENSITIVE (a query on `guid` hits a column
            # DEFINED as `GUID`), but pragma_table_info returns the defined case — so
            # compare case-folded, else a mere capitalization change is a false drift.
            present = {
                row[0].lower()
                for row in conn.execute(
                    "SELECT name FROM pragma_table_info(?)", (table,)
                )
            }
        except sqlite3.DatabaseError as e:  # corrupt / not-a-db → can't parse → drift
            raise SchemaDrift(
                "could not read the sqlite store's schema (corrupt or not a database): "
                f"{e}. Falling back or surfacing rather than mis-parsing. Do not retry."
            ) from e
        if not present:
            raise SchemaDrift(
                f"expected table {table!r} is absent — macOS likely changed the "
                "schema. The parser would mis-read the store; do not trust a sqlite "
                "result until the fingerprint is updated."
            )
        missing = sorted(c for c in columns if c.lower() not in present)
        if missing:
            raise SchemaDrift(
                f"table {table!r} is missing column(s) {missing} — macOS likely "
                "changed the schema. Do not trust a sqlite result until the "
                "fingerprint is updated."
            )


# Missing FDA and schema drift are the two "store unavailable" signals the dual-backend
# degrades on (Andrei's #58 policy). A genuinely-absent store (bare NativeError)
# surfaces loudly instead — not an FDA problem, and a wrong "grant FDA" nudge misleads.
_STORE_UNAVAILABLE = (FullDiskAccessDenied, SchemaDrift)


def read_via_sqlite(
    path: Path | str,
    fingerprint: dict[str, set[str]],
    query: Callable[[sqlite3.Connection], T],
    *,
    fallback: Callable[[], T] | None = None,
    immutable: bool = False,
) -> T:
    """Dual-backend read (#58): query a native sqlite store read-only, degrading to the
    adapter's AppleScript reader when the store is unavailable.

    Policy (Andrei-approved): sqlite-primary. On unavailability — missing Full Disk
    Access OR a schema-fingerprint mismatch — call ``fallback`` if the adapter has one
    (Notes does), else re-raise the typed error so the model gets a remediation, never a
    silent empty (Messages content has no fallback → it raises). ``query(conn) -> T``
    does the reads on the open read-only connection and must return plain data (the
    connection is thread-bound and closed here); ``fallback() -> T`` is the AppleScript
    path.

    Everything runs on the single native worker (serialization consistency). This is the
    ONE helper the sqlite read planes (#59/#60) build on — they add no new plumbing.
    """

    def work() -> T:
        try:
            conn = _open_sqlite_ro(path, immutable=immutable)
            try:
                verify_sqlite_schema(conn, fingerprint)
                return query(conn)
            except sqlite3.Error as e:
                # A sqlite error surfacing during the read (a data page corrupt past
                # the schema pages verify touched, an unreadable store) is "store
                # unavailable" — route it through SchemaDrift so it degrades to fallback
                # / surfaces as a typed directive, never a raw exception past
                # server._guard (#47). A non-sqlite error from query() (a parser bug) is
                # NOT caught here — it must propagate, never be masked as a fallback.
                raise SchemaDrift(
                    f"the sqlite store could not be read ({e}) — corrupt, or an "
                    "unexpected sqlite error. Do not trust a partial result."
                ) from e
            finally:
                conn.close()
        except _STORE_UNAVAILABLE:
            if fallback is not None:
                return fallback()
            raise

    return work() if _on_worker() else run_native(work)


def mac_region() -> str | None:
    """The Mac's locale region code (e.g. ``'BE'``), for the locale-derived phone
    country-code default (#59 — never a hardcoded +1). ``None`` if unavailable.

    A pure read of NSLocale: no EventKit thread affinity, no TCC — so it needs neither
    run_native nor a permission. Kept here so Foundation stays out of the adapters.
    """
    region = F.NSLocale.currentLocale().objectForKey_(F.NSLocaleCountryCode)
    return str(region) if region else None


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


log = logging.getLogger("macos_apps_mcp")


# NOTE: the write-audit trail + usage tally (#67) live in audit.py — they are plain
# file IO with no coupling to the native worker, so they don't belong in this module.


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


# NOTE: lifecycle hygiene (#56 — orphan watcher, SIGTERM/atexit child cleanup)
# lives in lifecycle.py; it consumes terminate_children() above.
