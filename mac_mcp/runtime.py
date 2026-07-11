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

import atexit
import contextlib
import logging
import os
import re
import signal
import subprocess
import threading
import time
import unicodedata
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import TypeVar

import EventKit as EK
import Foundation as F

from .contracts import CLEAR_RECURRENCE, Recurrence

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


class SpanRequired(NativeError):
    """A recurring event's update/delete needs an explicit span (this-event vs
    future-events) so one occurrence isn't silently rewritten as the series (#51)."""

    kind = "span_required"


class WriteRefused(NativeError):
    """The store refused a save/remove — a read-only or subscribed calendar/list, or
    the account rejected the change."""

    kind = "write_refused"


class RecurrenceRequired(NativeError):
    """Updating a repeating reminder needs an explicit recurrence (re-send the rule
    or 'none') so a rename can't silently destroy the series (mirror of
    SpanRequired's rationale, #51)."""

    kind = "recurrence_required"


class BatchTooLarge(NativeError):
    """A bulk operation exceeded its small default safety cap without an explicit
    override — contains blast radius (griches --confirm-destructive, #54)."""

    kind = "batch_too_large"


class AmbiguousTarget(NativeError):
    """A name/title matched more than one container, so a write cannot safely pick one.
    The disambiguation rule (#55): never auto-pick an ambiguous target for a write —
    fuzzy/first-match auto-pick sent iMessages to the wrong human (supermemoryai #48),
    and duplicate calendar names silently mis-targeted writes (mcp-ical #16). ``str(e)``
    tells the caller how to disambiguate."""

    kind = "ambiguous_target"


def resolve_container(items, target: str, *, noun: str):
    """Resolve a write's container target by ``Pointer.id`` (exact) OR exact name (#55).

    The disambiguation rule made concrete: a container-addressed write
    (``create_event(calendar)``, ``create_reminder(list_name)``) accepts EITHER a
    ``Pointer.id`` — the stable, unambiguous handle from the read side — OR an exact
    name. An id wins (it is unambiguous by construction); a name matching >1 container
    raises ``AmbiguousTarget`` **listing the candidate ids**, so the caller re-issues
    the write targeting one of them rather than mac-mcp guessing (mcp-ical #16 silent
    mis-target). id-first: a calendar/list identifier is a UUID, so it can't collide
    with a human-typed name — the precedence is safe.

    ``items`` is ``list[(id, name, value)]``; the matched ``value`` (the native
    container object) is returned. 0 name matches → ``ValueError``; >1 →
    ``AmbiguousTarget``. Pure (no native imports) so it unit-tests with plain tuples.
    """
    for cid, _name, value in items:
        if cid == target:  # id-first: an unambiguous handle is used directly
            return value
    matches = [(cid, value) for cid, name, value in items if name == target]
    if not matches:
        raise ValueError(f"no {noun} named {target!r}")
    if len(matches) > 1:
        ids = ", ".join(cid for cid, _ in matches)
        raise AmbiguousTarget(
            f"{len(matches)} {noun}s are named {target!r} — mac-mcp never auto-picks "
            "an ambiguous write target. Re-issue the write targeting one of these ids "
            f"instead: {ids} (or rename them so the names are unique)."
        )
    return matches[0][1]


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


def norm_text(v) -> str | None:
    """NFC + LF-normalize a free-text field for verify comparison (#49): Cocoa treats
    NFC/NFD as equal and stores may fold CRLF, so byte-exact != would false-fail a
    correct write. "" and None both mean "unset"."""
    if v is None:
        return None
    s = unicodedata.normalize("NFC", str(v)).replace("\r\n", "\n").replace("\r", "\n")
    return s or None


# --- output hygiene (#52) ------------------------------------------------------------
# Raw native text reaches the model two ways: as a one-line Pointer.summary and as an
# opt-in hydrated body. Both are control-stripped and bounded here — in ONE place, one
# uniform rule (no per-tool truncation knobs) — so a pathological item can neither
# corrupt the client (control chars / U+2028-9 blanked Claude Desktop conversations
# retroactively, carterlasalle #2) nor blow the buffer/context (a 150k-char body failed
# *silently* at maxBuffer, FradSer #66/#69). ponytail: the three MAX constants are
# tuning knobs — change the numbers, not the mechanism.
SUMMARY_MAX = 200  # a one-line citable extract
BODY_MAX = 4000  # per-item hydrated body — soft cap: truncate + marker past this
BODY_HARD_MAX = 50_000  # a body past this is a dump, not a note → OutputOverflow

# Fold every kind of line break to one char first: CRLF/CR, VT, FF, NEL (U+0085), and
# the Unicode LINE/PARAGRAPH SEPARATORS (U+2028/9) that historically blank JS/JSON
# consumers. \r\n is one alternative so a Windows newline folds to a single char.
_LINE_BREAKS = re.compile(r"\r\n|[\r\n\x0b\x0c\x85\u2028\u2029]")
# Disallowed chars remaining after breaks are folded: C0 controls (minus TAB \x09 and
# the fold char \n \x0a, both kept), DEL \x7f, and C1 \x80-\x9f. \x0b-\x0d never survive
# folding, so the class starts at \x0e.
_CTRL = re.compile(r"[\x00-\x08\x0e-\x1f\x7f-\x9f]")


def _truncate(text: str, limit: int) -> str:
    """Cap ``text`` at ``limit`` chars, appending an explicit ``[truncated N chars]``
    marker (N = chars dropped) so the model never mistakes a clip for the whole."""
    if len(text) <= limit:
        return text
    return f"{text[:limit]} [truncated {len(text) - limit} chars]"


def sanitize_line(text: object) -> str:
    """Collapse ``text`` to one control-char-free line (NO truncation): every line break
    → space, C0/C1/DEL controls removed, whitespace runs collapsed. For anything that
    lands in a one-line ``Pointer.summary``. ``None`` → ``""``."""
    folded = _LINE_BREAKS.sub(" ", str(text) if text is not None else "")
    return re.sub(r"\s+", " ", _CTRL.sub("", folded)).strip()


def sanitize_block(text: object) -> str:
    """Strip control chars from multi-line ``text``, preserving line structure (NO
    truncation): every line break → ``\\n``, TAB kept, other C0/C1/DEL removed. For
    opt-in hydrated bodies (a body legitimately spans lines — do not flatten it)."""
    folded = _LINE_BREAKS.sub("\n", str(text) if text is not None else "")
    return _CTRL.sub("", folded)


def clean_summary(text: object) -> str:
    """One-line, control-free, ``SUMMARY_MAX``-bounded ``Pointer.summary`` text."""
    return _truncate(sanitize_line(text), SUMMARY_MAX)


def clean_body(
    text: object, limit: int = BODY_MAX, hard: int | None = BODY_HARD_MAX
) -> str:
    """Control-free, line-preserving body truncated at ``limit`` with a marker.

    Raises ``OutputOverflow`` when the sanitized body exceeds ``hard``: a single item
    that large is a pasted dump, not a note, and truncating it to a few KB would just
    hand back misleading noise — the model should open it in-app instead. Pass
    ``hard=None`` to always truncate (where one huge item must not fail a batch)."""
    s = sanitize_block(text)
    if hard is not None and len(s) > hard:
        raise OutputOverflow(
            f"this item is {len(s)} chars — too large to hydrate (cap {hard}). Open it "
            "in the app instead of fetching its body; do not retry the hydrate."
        )
    return _truncate(s, limit)


def require_batch_within(count: int, cap: int, *, override_param: str) -> None:
    """Guard a bulk operation's size (#54): raise ``BatchTooLarge`` when ``count``
    exceeds the small default ``cap``, naming the ``override_param`` the caller can pass
    to raise the cap deliberately. Small caps + explicit override contain blast radius
    (griches). The first bulk destructive op wires this in; single-item writes don't
    need it. ponytail: this is the shared primitive — a bulk op calls it, it does not
    invent its own limit check."""
    if count > cap:
        raise BatchTooLarge(
            f"this operation would affect {count} items but the safety cap is {cap}. "
            f"Narrow the batch, or pass {override_param}=<n> to raise the cap on "
            "purpose. Do not retry the same oversized batch unchanged."
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


# In-flight osascript children, tracked so exit paths (atexit / SIGTERM / orphan
# watcher, #56) can terminate them — an orphaned synchronous Apple Event pinned Mail's
# main thread indefinitely (patrickfreyer #58). The serialized worker means at most one
# at a time, but a set + lock is robust and cheap. The AppleScript-level `with timeout`
# in each template is the second line of defense: it self-terminates a hung child even
# if the Python side died first and never got to call terminate().
_children: set[subprocess.Popen] = set()
_children_lock = threading.Lock()


def _terminate_children() -> None:
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
    Raises a typed ``NativeError`` (``AutomationDenied`` / ``AppNotRunning`` / generic)
    on a non-zero exit, and ``NativeTimeout`` on timeout — it never returns an empty
    string to mask a failure as "no result". Safe on or off the worker (dispatches via
    run_native when called off it). The child is tracked so an exit path can kill it
    (#56); the AppleScript template's own ``with timeout`` bounds it if we can't.
    """

    def _run() -> str:
        # Popen (not subprocess.run) so the live child is a handle exit paths can
        # terminate; communicate(timeout) + kill-on-timeout mirrors run(timeout=).
        started = time.monotonic()
        proc = subprocess.Popen(
            ["osascript", "-e", script, *args],
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


_ASYNC_TIMEOUT = 30.0  # seconds


def run_native_async(start, timeout: float = _ASYNC_TIMEOUT):
    """Block on a completion-handler call; bounded so a dropped callback can't hang.

    Generalizes the EventKit fetch pattern. ``start(finish)`` kicks off the async op
    and arranges its completion handler to call ``finish(result)``; this returns that
    result, or raises NativeTimeout if the callback never fires within ``timeout``.
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


# --- lifecycle hygiene (#56) ---------------------------------------------------------
# A stdio MCP server orphaned by its parent (Claude exits/crashes) must not linger,
# re-launching Mail.app forever (patrickfreyer #58, python-sdk #526). We watch our
# parent pid and hard-exit on reparent; on every exit path we also terminate any
# in-flight osascript child (the AppleScript `with timeout` in each template is the
# backstop for when we can't). Installed by the server entry point, NOT bootstrap(), so
# importing the module or running unit tests never starts a watcher or grabs SIGTERM.
_PPID_POLL = 1.0  # seconds — well inside the 5s orphan-exit budget

# The launching parent's pid, captured at IMPORT — deliberately NOT at
# install_lifecycle_guards() time. bootstrap() blocks up to 120s on the TCC permission
# prompt *before* the guards install; if the parent died during that wait, an
# install-time os.getppid() would already read 1 (reparented) and the watcher could
# never fire (1 == 1 forever). Import runs right after the parent spawns us (alive).
_LAUNCH_PPID = os.getppid()


def _parent_died(original_ppid: int) -> bool:
    """True once our launching parent is gone: its pid was reaped and we were reparented
    (``getppid`` changes, typically to 1/launchd). A process's parent never changes
    while that parent is alive, so a changed ppid reliably means the parent died."""
    return os.getppid() != original_ppid


_lifecycle_installed = False


def install_lifecycle_guards() -> None:
    """Start the orphan watcher and register child-cleanup on exit (#56). Idempotent.

    Call once from the server entry point (after bootstrap). The watcher is a daemon
    thread; SIGTERM and normal exit both terminate any in-flight osascript child so a
    graceful stop doesn't leave one hung until its AppleScript timeout.
    """
    global _lifecycle_installed
    if _lifecycle_installed:
        return
    _lifecycle_installed = True

    atexit.register(_terminate_children)
    # signal.signal only works on the main thread — skip (suppress ValueError) if not.
    with contextlib.suppress(ValueError):
        signal.signal(signal.SIGTERM, lambda *_: (_terminate_children(), os._exit(0)))

    def _watch() -> None:
        # compare against the import-time launch ppid (see _LAUNCH_PPID) so a parent
        # that died during bootstrap's permission prompt is still detected as gone.
        while not _parent_died(_LAUNCH_PPID):
            time.sleep(_PPID_POLL)
        # parent gone: kill any in-flight child, then hard-exit (skip Python teardown —
        # its stdio pipes point at a dead parent and could block).
        _terminate_children()
        os._exit(0)

    threading.Thread(target=_watch, name="mac-ppid-watch", daemon=True).start()
