"""The native door: the single serialized worker thread + osascript/sqlite dispatch.

Settled by design (adversarial debate). ``EKEventStore`` has **thread affinity** (it
must be accessed from the thread that created it) and **TCC** authorization must be
handled on a consistent thread. A generic ``asyncio.to_thread`` / default multi-worker
pool scatters calls across threads → affinity bugs and a hung first-permission prompt.
So every native call — EventKit (via ``eventkit.py``) and osascript/sqlite alike —
goes through this module's single ``max_workers=1`` executor.

This is user-latency-bound, not throughput-bound, so serialization costs nothing in
practice. The EventKit-typed cluster (the store, NSDate/RRULE coercion, TCC consent)
lives in ``eventkit.py``, which fences its own store access through ``on_worker()``
below — this module owns the worker, not the store.
"""

from __future__ import annotations

import calendar
import contextlib
import ctypes
import logging
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

# Off macOS the server must still import and list its tools; the native doors
# refuse through require_macos().
if sys.platform == "darwin":
    import Foundation as F
else:
    F = None

from .errors import (
    PRIVACY_PANE,
    AppNotRunning,
    AutomationDenied,
    ComposeRefused,
    FullDiskAccessDenied,
    NativeError,
    NativeTimeout,
    SchemaDrift,
    UnsupportedPlatform,
)
from .text import squash_text

# ponytail: one process-wide native thread. If a future app needs a *second* isolated
# native context, give it its own executor — don't widen this one to max_workers>1
# (breaks EKEventStore).
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mac-native")


def require_macos() -> None:
    """Raise ``UnsupportedPlatform`` unless this process runs on macOS.

    Called first by ``run_native``, ``tracked_run``, ``mac_region``, ``doctor.diagnose``
    and the server's ``_guard``. Reads ``sys.platform`` at call time.
    """
    if sys.platform != "darwin":
        raise UnsupportedPlatform(
            f"macos-apps-mcp runs only on macOS: this server is running on "
            f"{sys.platform}, where Mail, Calendar, Reminders and the other Mac apps "
            "do not exist. Use it on a Mac. Do not retry."
        )


def run_native[T](fn: Callable[[], T]) -> T:
    """Run a blocking native callable on the single dedicated worker thread and return
    its result.

    Adapters wrap every EventKit / osascript call in this so the work always lands on
    one thread, regardless of which thread FastMCP invoked the tool from. Off macOS it
    refuses first; ``run_osascript``, ``read_via_sqlite`` and ``photos_db`` dispatch
    through it off the worker, so they refuse too.
    """
    require_macos()
    return _executor.submit(fn).result()


# NOTE: the typed error taxonomy (#47) and the pure write policies —
# resolve_container, refused_write, verify_persisted, require_batch_within — live in
# errors.py: no native imports there, so adapters/tests use them without loading this
# module's EventKit/Foundation. runtime raises those classes; it does not define them.

# NOTE: text hygiene / fold / verify-normalization live in text.py (#52/#49/#64) —
# pure string work with no coupling to the native worker.


def on_worker() -> bool:
    """True when called from the mac-native worker thread.

    Public so eventkit's ``store()`` can fence itself without owning the worker —
    runtime owns the thread affinity; eventkit only asks it a question.
    """
    return threading.current_thread().name.startswith("mac-native")


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
_APPLE_EVENT_TIMEOUT = "(-1712)"  # the app never answered the Apple Event

# #183 (facts §9b): a timeout/-1712 from an app that is IDLE is a wedged event queue —
# permanent, survives a UI quit-and-reopen, cleared only by a force-quit that actually
# changes the pid. The same signal from an ACTIVE process is a busy app (e.g. a
# post-restart account resync) that recovers on its own. Both signatures were observed
# live. The process read happens only on the failure path — never on a happy path.
_TELL_APP = re.compile(r'tell application "([^"]+)"')
_BUSY_CPU = 5.0  # %CPU at/above which a sleeping process still counts as working


def app_process_info(app: str) -> dict | None:
    """pid/state/%cpu/etime of the running app named ``app``, via one ``pgrep`` + one
    ``ps`` (no TCC needed). ``None`` when it isn't running or ps is unreadable. Used by
    the timeout classification (#183) and doctor's automation report."""
    try:
        pid = int(tracked_run(["pgrep", "-x", app], timeout=5.0).stdout.split()[0])
        state, cpu, etime = tracked_run(
            ["ps", "-o", "state=,%cpu=,etime=", "-p", str(pid)], timeout=5.0
        ).stdout.split()
        return {"pid": pid, "state": state, "cpu": float(cpu), "etime": etime}
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def _classify_stuck_app(state: str, cpu: float) -> str:
    """``'wedged'`` vs ``'busy'`` for an app that just refused/timed out an Apple Event
    (#183). Wedged: idle (sleeping, ~1% CPU) yet unresponsive — permanent, needs a
    force-quit. Busy: running/uninterruptible state or real CPU — working through
    something (an account resync) and self-recovering. Pure, so it unit-tests with
    plain values; facts §9b holds the observed signatures."""
    return "busy" if state[:1] in {"R", "U"} or cpu >= _BUSY_CPU else "wedged"


def _timeout_hint(script: str) -> str:
    """The #183 classification, appended to a timeout error's message. Empty when the
    script names no app or the process can't be read — the generic timeout message
    then reads exactly as before."""
    m = _TELL_APP.search(script)
    if not m:
        return ""
    app = m.group(1)
    info = app_process_info(app)
    if info is None:
        return ""
    desc = (
        f"{app} (pid {info['pid']}, up {info['etime']}, state {info['state']}, "
        f"{info['cpu']:.1f}% CPU)"
    )
    if _classify_stuck_app(info["state"], info["cpu"]) == "busy":
        return (
            f" {desc} is ACTIVE — likely busy (e.g. an account resync) and usually "
            "recovers on its own. Wait a minute, then retry once."
        )
    return (
        f" {desc} is IDLE yet not answering Apple Events — its event queue is likely "
        "WEDGED (facts §9b): it will not recover on its own, and a normal "
        "quit-and-reopen can leave the same wedged process running. Tell the user to "
        f"force-quit (`killall {app} && open -a {app}`), then confirm the pid changed "
        "(doctor reports it). Do not retry until it has. sqlite-backed reads keep "
        "working meanwhile."
    )


def _classify_osascript_failure(stderr: str, script: str = "") -> NativeError:
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
            "Automation, for whichever app launched macos-apps-mcp. "
            "Do not retry until the next user message. "
            f"[{detail}]"
        )
    if any(code in stderr for code in _APP_NOT_RUNNING):
        return AppNotRunning(
            "The target macOS app isn't running or couldn't be launched. Tell the user "
            f"to open it, then try again once it's open. [{detail}]"
        )
    if _APPLE_EVENT_TIMEOUT in stderr:
        # the script's own `with timeout` fired: the app never answered the event.
        return NativeTimeout(
            "The macOS app did not answer the Apple Event in time (-1712)."
            f"{_timeout_hint(script)} [{detail}]"
        )
    return NativeError(f"osascript failed: {detail}")


# In-flight children (osascript, the shortcuts CLI), tracked so exit paths (atexit /
# SIGTERM / orphan watcher, #56) can terminate them — an orphaned synchronous Apple
# Event pinned Mail's main thread indefinitely (patrickfreyer #58). The serialized
# worker means at most one at a time, but a set + lock is robust and cheap. The
# AppleScript-level `with timeout` in each template is the second line of defense: it
# self-terminates a hung child even if the Python side died first and never got to call
# terminate().
_children: set[subprocess.Popen] = set()
_children_lock = threading.Lock()


def terminate_children() -> None:
    """Terminate any in-flight tracked child. Idempotent; safe from any thread and at
    shutdown (an already-dead child raises OSError on terminate, ignored)."""
    with _children_lock:
        children = list(_children)
    for proc in children:
        with contextlib.suppress(OSError):
            proc.terminate()


@contextlib.contextmanager
def _track_child(proc: subprocess.Popen):
    """Register ``proc`` in the #56 child registry for the duration of the block, so
    every exit path (atexit / SIGTERM / orphan watcher — lifecycle.py) can terminate it.
    The ONE seam for subprocess lifetime: every child a module spawns (osascript here,
    the shortcuts CLI via ``tracked_run``) must run inside it."""
    with _children_lock:
        _children.add(proc)
    try:
        yield proc
    finally:
        with _children_lock:
            _children.discard(proc)


def tracked_run(
    cmd: list[str],
    *,
    timeout: float,
    input: str | None = None,  # shadows the builtin to mirror subprocess.run's keyword
    errors: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """``subprocess.run(capture_output=True, text=True)`` with the child registered in
    the #56 cleanup registry (``_track_child``) while it runs.

    ``subprocess.run`` never exposes its live ``Popen``, so a child spawned through it
    escapes the exit-path cleanup — an orphaned server could leave e.g. a ``shortcuts
    run`` in flight forever. Adapters that shell out to a CLI use this instead. Raises
    ``subprocess.TimeoutExpired`` (the child is killed and reaped first) exactly like
    ``run(timeout=...)`` so callers translate it to their own typed timeout. Refuses
    off macOS.
    """
    require_macos()
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE if input is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors=errors,
    )
    with _track_child(proc):
        try:
            out, err = proc.communicate(input=input, timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()  # reap so we don't leak a zombie
            raise
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


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
        with _track_child(proc):
            try:
                out, err = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired as e:
                proc.kill()
                proc.communicate()  # reap so we don't leak a zombie
                raise NativeTimeout(
                    f"The macOS app didn't respond within {timeout}s (it may be "
                    "blocked on a dialog, or the query is too broad). Tell the user to "
                    "dismiss any stuck prompt, then retry with a narrower query. Do "
                    f"not retry immediately.{_timeout_hint(script)}"
                ) from e
        if proc.returncode != 0:
            raise _classify_osascript_failure(err, script)
        # debug telemetry (#56): opt-in via logging level, zero cost otherwise.
        log.debug(
            "osascript %.0fms, %d bytes out",
            (time.monotonic() - started) * 1000,
            len(out),
        )
        # trailing newlines inside the data must survive; remove only osascript's own
        # single terminating newline
        return out[:-1] if out.endswith("\n") else out

    return _run() if on_worker() else run_native(_run)


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


def read_via_sqlite[T](
    path: Path | str,
    fingerprint: dict[str, set[str]],
    query: Callable[[sqlite3.Connection], T],
    *,
    fallback: Callable[[], T] | None = None,
    immutable: bool = False,
    setup: Callable[[sqlite3.Connection], None] | None = None,
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

    ``setup(conn)`` — optional connection preparation run after open, BEFORE the
    fingerprint check (#201): an ATTACH or TEMP VIEW that must be in place for
    verification and the read to see the store the adapter intends. The hook's
    CONTENT belongs to the adapter — this helper stays store-agnostic — and a sqlite
    error inside it degrades exactly like any other store-unavailable (fallback, or
    the typed raise).

    Everything runs on the single native worker (serialization consistency). This is the
    ONE helper the sqlite read planes (#59/#60) build on — they add no new plumbing.
    """

    def work() -> T:
        try:
            conn = _open_sqlite_ro(path, immutable=immutable)
            try:
                if setup is not None:
                    setup(conn)
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

    return work() if on_worker() else run_native(work)


# The Photos prefs file osxphotos reads to find the library; Full Disk Access guards it.
_PHOTOS_PREFS = (
    Path.home()
    / "Library/Containers/com.apple.Photos/Data/Library/Preferences"
    / "com.apple.Photos.plist"
)


def _photos_prefs_denied() -> bool:
    """True when TCC blocks the Photos prefs file. osxphotos swallows that
    PermissionError and reports a missing library, so this tells the two apart."""
    try:
        with open(_PHOTOS_PREFS, "rb") as f:
            f.read(1)
    except PermissionError:
        return True
    except OSError:  # absent (Photos never opened) or unreadable for another reason
        pass
    return False


def photos_db():
    """The osxphotos ``PhotosDB`` for the library Photos last opened (osxphotos
    ``get_last_library_path``; Full Disk Access).

    The one door to osxphotos (D-01, D-06): every Photos read builds its library
    through here, so unit tests fake one name and a test that forgets raises instead of
    opening the developer's real library. Returns the object, so the caller must use it
    on the worker too — call it inside ``run_native`` (the adapter does).
    """

    def work():
        # Lazy: 0.65 s warm and 5-8 s cold, and it pulls PyObjC Photos/Vision/Metal,
        # so it stays out of server import and out of every unit test.
        try:
            import osxphotos
        except ImportError as e:
            raise NativeError(
                "osxphotos is not installed in this environment, so the Photos tools "
                "cannot run here. Do not retry."
            ) from e
        # shortcut: PhotosDB() per call is O(library) (open about 0.1 s at ~60 assets,
        # measured in 04-01); cache it on the (st_mtime_ns, st_size) of Photos.sqlite
        # and Photos.sqlite-wal when an open passes ~1 s.
        try:
            return osxphotos.PhotosDB()
        except (PermissionError, FileNotFoundError) as e:
            if isinstance(e, PermissionError) or _photos_prefs_denied():
                raise FullDiskAccessDenied(
                    "macos-apps-mcp could not read the Photos library — Full Disk "
                    f"Access is not granted. Grant it in {PRIVACY_PANE} → Full Disk "
                    "Access to the app that launched macos-apps-mcp, then restart "
                    "macos-apps-mcp. Do not retry until the next user message."
                ) from e
            raise NativeError(
                "osxphotos found no Photos library on this Mac. Open Photos once to "
                "create one; if Photos already has a library, Full Disk Access may be "
                "missing — run doctor. Do not retry."
            ) from e
        except Exception as e:
            # The cause's text can name the library path: log it, keep it out of the
            # agent-facing text (IN-02).
            log.warning("osxphotos could not read the Photos library: %r", e)
            raise SchemaDrift(
                f"osxphotos {osxphotos.__version__} could not read the Photos library "
                f"({type(e).__name__}) — macOS may have changed the Photos "
                "database. Do not retry; report it."
            ) from e

    return work() if on_worker() else run_native(work)


_TYPE_BUNDLE_ID = 0x62756E64  # 'bund' = typeApplicationBundleID
_TYPE_WILD = 0x2A2A2A2A  # '****' = typeWildCard


class _AEDesc(ctypes.Structure):
    # struct AEDesc { DescType descriptorType; AEDataStorage dataHandle; }
    _fields_ = [("descriptorType", ctypes.c_uint32), ("dataHandle", ctypes.c_void_p)]


def _ae_lib():
    """CoreServices with the three AppleEvent calls bound. Lazy, so nothing loads at
    import time (the server must import off macOS), and a test replaces it."""
    lib = ctypes.CDLL("/System/Library/Frameworks/CoreServices.framework/CoreServices")
    lib.AECreateDesc.argtypes = [
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_long,
        ctypes.POINTER(_AEDesc),
    ]
    lib.AECreateDesc.restype = ctypes.c_int16  # OSErr
    lib.AEDisposeDesc.argtypes = [ctypes.POINTER(_AEDesc)]
    lib.AEDisposeDesc.restype = ctypes.c_int16  # OSErr
    determine = lib.AEDeterminePermissionToAutomateTarget
    determine.argtypes = [
        ctypes.POINTER(_AEDesc),
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_ubyte,  # Boolean askUserIfNeeded
    ]
    determine.restype = ctypes.c_int32  # OSStatus
    return lib


def automation_permission(bundle_id: str) -> int:
    """The OSStatus of THIS process's Automation grant to ``bundle_id``: ``0`` granted,
    ``-1743`` denied, ``-1744`` not asked yet, ``-600`` target not running or unknown.

    Never prompts (askUserIfNeeded is the constant 0) and sends no Apple Event. Safe on
    or off the worker; it dispatches itself, so it waits behind a job that holds the
    one worker. A stalled call would hold that worker: a child process via
    ``tracked_run`` is the upgrade if a device ever shows one.
    """

    def _probe() -> int:
        lib, raw, desc = _ae_lib(), bundle_id.encode("utf-8"), _AEDesc()
        err = lib.AECreateDesc(_TYPE_BUNDLE_ID, raw, len(raw), ctypes.byref(desc))
        if err != 0:
            return err
        try:
            return lib.AEDeterminePermissionToAutomateTarget(
                ctypes.byref(desc), _TYPE_WILD, _TYPE_WILD, 0
            )
        finally:
            lib.AEDisposeDesc(ctypes.byref(desc))

    return _probe() if on_worker() else run_native(_probe)


# --- FIX-16 (#348): the Accessibility seams of the Mail reply flow -----------------
#
# Facts section 4e is the recipe; the phase 05.2 `reply_gui_probe.py` (in
# `.planning/phases/05.2-*/05.2-proto/`) is the device-proven reference for every
# binding below. `accessibility_trusted` and `compose_insert` are the ONLY two public
# doors: every AX, CoreGraphics and general pasteboard call sits behind them, in
# private helpers a test replaces. The target is a constant (Mail) plus the one reply
# window the caller opened: there is no app, pid or bundle parameter, so the grant
# cannot be steered at another app (T-05.2-36).

_HISERVICES = (
    "/System/Library/Frameworks/ApplicationServices.framework/Frameworks/"
    "HIServices.framework"
)
_COREGRAPHICS = "/System/Library/Frameworks/CoreGraphics.framework"
_COREFOUNDATION = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
_MAIL_BUNDLE = "com.apple.mail"
_KEY_A, _KEY_V = 0, 9  # kVK_ANSI_A, kVK_ANSI_V
_CMD_FLAG = 0x100000  # kCGEventFlagMaskCommand
# Clipboard-history tools skip an item that carries these (nspasteboard.org).
_TRANSIENT_TYPES = (
    "org.nspasteboard.TransientType",
    "org.nspasteboard.ConcealedType",
)
# facts 4e `Pasteboard`: the largest settle was 133 ms over 5 runs; the bound is at
# least twice that. Calculated, not run.
_PASTE_SETTLE_S = 1.0
_FOCUS_WAIT_S = 3.0  # a fresh reply's body takes AX focus late (untested bound)
_ACTIVATE_WAIT_S = 0.4
_SELECT_ALL_WAIT_S = 0.2
# shortcut: the AX walk of the sitting stops after 400 nodes, so on a much longer
# original the read is incomplete and the quote check refuses ("too long to check",
# facts 4e `Confirm`); raise it if a device run shows a refusal of that kind. The walk
# is bounded by this budget alone (no depth cut): a cut walk is reported, never trusted.
_AX_WALK_BUDGET = 400
_COMPOSE_OSA_TIMEOUT = 120.0  # equals each script's own `with timeout` backstop

_WINDOW_INDEX = """on run argv
  set wid to (item 1 of argv) as integer
  with timeout of 120 seconds
    tell application "Mail"
      set idx to index of window id wid
    end tell
  end timeout
  return idx
end run"""

_ACTIVATE_WINDOW = """on run argv
  set wid to (item 1 of argv) as integer
  with timeout of 120 seconds
    tell application "Mail"
      activate
      set index of window id wid to 1
    end tell
  end timeout
  return "activated"
end run"""

_AX: dict = {}


def _ax_lib() -> dict:
    """The HIServices calls, bound once through PyObjC. Lazy, so nothing loads at
    import time (the server must import off macOS), and a test replaces it. The trust
    read is the plain one: the variant that can raise the system prompt is never
    bound."""
    if not _AX:
        import objc

        lib: dict = {}
        hi = objc.loadBundle("HIServices", {}, bundle_path=_HISERVICES)
        objc.loadBundleFunctions(
            hi,
            lib,
            [
                ("AXIsProcessTrusted", b"Z"),
                ("AXUIElementGetTypeID", b"Q"),
                ("AXUIElementCreateApplication", b"^{__AXUIElement=}i"),
                (
                    "AXUIElementCopyAttributeValue",
                    b"i^{__AXUIElement=}^{__CFString=}o^@",
                ),
                ("_AXUIElementGetWindow", b"i^{__AXUIElement=}o^I"),  # SPI
            ],
        )
        objc.registerCFSignature(
            "AXUIElementRef", b"^{__AXUIElement=}", lib["AXUIElementGetTypeID"]()
        )
        _AX.update(lib)
    return _AX


def accessibility_trusted() -> bool:
    """Whether THIS process holds the Accessibility grant (macOS 27: "Device Control and
    Data Access"). Reads the switch only: it never asks macOS to show a prompt. Safe on
    or off the worker; it dispatches itself, so it waits behind a job that holds the one
    worker."""

    def work() -> bool:
        return bool(_ax_lib()["AXIsProcessTrusted"]())

    return work() if on_worker() else run_native(work)


# AX errors that only say "this element has no such attribute / no value": an empty
# read, not a failed one (a leaf has no children). Any other error is a failed read.
_AX_NO_ATTRIBUTE = (-25205, -25212)  # kAXErrorAttributeUnsupported, ...NoValue


def _ax_read(el, attr: str):
    """``(value, readable)``: the AX attribute of ``el`` (None when absent) and whether
    the read itself worked. ``readable`` is False only for a failed read, so a caller
    that must not act on a partial walk can tell it from an empty one."""
    err, val = _ax_lib()["AXUIElementCopyAttributeValue"](el, attr, None)
    return (val if err == 0 else None), err == 0 or err in _AX_NO_ATTRIBUTE


def _ax_get(el, attr: str):
    """One AX attribute of ``el``, or None when it cannot be read."""
    return _ax_read(el, attr)[0]


def _mail_pid() -> int:
    import AppKit

    apps = AppKit.NSRunningApplication.runningApplicationsWithBundleIdentifier_(
        _MAIL_BUNDLE
    )
    if not apps:
        raise ComposeRefused("window check: Mail is not running")
    return int(apps[0].processIdentifier())


# kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements
_ON_SCREEN_WINDOWS = 1 | 16
_WINDOW_LIB: dict = {}


def _frontmost_pid() -> int | None:
    """The pid of the front app: the owner of the topmost on-screen layer-0 window (the
    list is front to back). A live WindowServer read that works on any thread.

    NOT ``NSWorkspace.frontmostApplication``: it caches its answer until the MAIN run
    loop turns, and the daemon never runs one (asyncio holds the main thread), so on the
    worker thread it froze at its first answer (measured stale 43 of 44 reads, review of
    #348). The CGWindowList read matched ``lsappinfo front`` in 25 of 25 samples. Needs
    no Screen Recording grant: only the window title is withheld, not owner or layer."""
    if not _WINDOW_LIB:
        import CoreFoundation  # noqa: F401 - registers CFArrayRef for the bound call
        import objc

        cg = objc.loadBundle("CoreGraphics", {}, bundle_path=_COREGRAPHICS)
        objc.loadBundleFunctions(
            cg, _WINDOW_LIB, [("CGWindowListCopyWindowInfo", b"^{__CFArray=}II")]
        )
    for info in _WINDOW_LIB["CGWindowListCopyWindowInfo"](_ON_SCREEN_WINDOWS, 0) or []:
        if info.get("kCGWindowLayer") == 0:
            return int(info["kCGWindowOwnerPID"])
    return None


def _window_index(window_id: int) -> int | None:
    out = run_osascript(_WINDOW_INDEX, str(window_id), timeout=_COMPOSE_OSA_TIMEOUT)
    return int(out) if out.strip().isdigit() else None


def _window_held(window_id: int) -> bool:
    return _frontmost_pid() == _mail_pid() and _window_index(window_id) == 1


def _hold_window(window_id: int) -> None:
    """Facts 4e `Activation`: Mail is active and the reply window is at index 1, else
    activate Mail, put the window at index 1 and check again. The window is named by its
    id (never by title, never by `window 1`); a reply can open BEHIND another window."""
    if _window_held(window_id):
        return
    run_osascript(_ACTIVATE_WINDOW, str(window_id), timeout=_COMPOSE_OSA_TIMEOUT)
    time.sleep(_ACTIVATE_WAIT_S)
    if not _window_held(window_id):
        raise ComposeRefused(
            "window check: the reply window is not Mail's front window, so the text "
            "was not inserted"
        )


def _window_number(win) -> int | None:
    """The CoreGraphics window number of an AX window element (the id Mail's scripting
    reports), through the SPI the sitting used; None when it is not readable."""
    spi = _ax_lib().get("_AXUIElementGetWindow")
    if spi is None:
        return None
    err, num = spi(win, None)
    return int(num) if err == 0 and num else None


def _focused_body(pid: int, window_id: int):
    """Facts 4e `Insert`, the focus check: Mail's focused element is an AXWebArea whose
    window is the bound one. A fresh reply's body takes focus late, so wait up to
    ``_FOCUS_WAIT_S`` for it (AX reads only). Returns the element."""
    app = _ax_lib()["AXUIElementCreateApplication"](pid)
    t0 = time.monotonic()
    el = _ax_get(app, "AXFocusedUIElement")
    while el is None and time.monotonic() - t0 < _FOCUS_WAIT_S:
        time.sleep(0.05)
        el = _ax_get(app, "AXFocusedUIElement")
    if el is None:
        raise ComposeRefused("focus check: Mail has no focused element in the reply")
    if _ax_get(el, "AXRole") != "AXWebArea":
        raise ComposeRefused("focus check: the focused element is not a compose body")
    win = _ax_get(el, "AXWindow")
    if win is None or _window_number(win) != window_id:
        raise ComposeRefused(
            "focus check: the focused body is not inside the reply window"
        )
    return el


def _read_body(el) -> tuple[str, bool]:
    """``(text, complete)``: the compose body text through AX, the AXStaticText parts in
    document order. The walk drops empty lines, so callers compare squashed text only.
    ``complete`` is False when the walk was cut short (the node budget ran out or an AX
    read failed), so the text may be missing its end: a caller must not treat "nothing
    follows" as proof then."""
    val = _ax_get(el, "AXValue")
    if isinstance(val, str) and val:
        return val, True
    parts: list[str] = []
    state = {"budget": _AX_WALK_BUDGET, "complete": True}

    def walk(node) -> None:
        if state["budget"] <= 0:
            state["complete"] = False
            return
        state["budget"] -= 1
        role, ok = _ax_read(node, "AXRole")
        if role == "AXStaticText":
            text, text_ok = _ax_read(node, "AXValue")
            ok = ok and text_ok
            if isinstance(text, str):
                parts.append(text)
        children, children_ok = _ax_read(node, "AXChildren")
        if not (ok and children_ok):
            state["complete"] = False
        for child in children or []:
            walk(child)

    walk(el)
    return "\n".join(parts), state["complete"]


def _cg_lib():
    """CoreGraphics with the three event calls bound (+ CFRelease). Lazy; a test
    replaces it."""
    lib = ctypes.CDLL(_COREGRAPHICS + "/CoreGraphics")
    lib.CGEventCreateKeyboardEvent.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint16,
        ctypes.c_bool,
    ]
    lib.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
    lib.CGEventSetFlags.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
    lib.CGEventPostToPid.argtypes = [ctypes.c_int, ctypes.c_void_p]
    lib.CFRelease = ctypes.CDLL(_COREFOUNDATION).CFRelease
    lib.CFRelease.argtypes = [ctypes.c_void_p]
    return lib


def _post_cmd_key(pid: int, keycode: int) -> None:
    """Cmd+<key>, one key down and one key up, delivered to ONE process. Never the
    global event post, so a focus change cannot send the key to another app."""
    lib = _cg_lib()
    for down in (True, False):
        ev = lib.CGEventCreateKeyboardEvent(None, keycode, down)
        lib.CGEventSetFlags(ev, _CMD_FLAG)
        lib.CGEventPostToPid(pid, ev)
        lib.CFRelease(ev)


def _require_complete_snapshot(items: list, unreadable: int, type_count: int) -> None:
    """A lossy snapshot would let the restore destroy the user's clipboard. Complete =
    every type of every item returned data. No items but types present refuses; no
    items and no types (an emptied pasteboard) is complete and restores by clearing."""
    if unreadable or (not items and type_count):
        raise ComposeRefused(
            "clipboard: the clipboard could not be saved completely, so it was left "
            "alone and nothing was pasted"
        )


class _Clipboard:
    """The general pasteboard, as far as the paste needs it. AppKit loads lazily, so a
    test that replaces ``_clipboard`` never touches it."""

    def __init__(self) -> None:
        import AppKit

        self._ak = AppKit
        self._pb = AppKit.NSPasteboard.generalPasteboard()

    def change_count(self) -> int:
        return int(self._pb.changeCount())

    def snapshot(self) -> list[dict[str, bytes]]:
        items, unreadable = [], 0
        for item in self._pb.pasteboardItems() or []:
            one: dict[str, bytes] = {}
            for t in item.types():
                data = item.dataForType_(t)
                if data is None:
                    unreadable += 1
                else:
                    one[str(t)] = bytes(data)
            items.append(one)
        _require_complete_snapshot(items, unreadable, len(self._pb.types() or []))
        return items

    def write_text(self, text: str) -> None:
        item = self._ak.NSPasteboardItem.alloc().init()
        item.setString_forType_(text, self._ak.NSPasteboardTypeString)
        for t in _TRANSIENT_TYPES:
            item.setData_forType_(F.NSData.data(), t)
        self._pb.clearContents()
        self._pb.writeObjects_([item])

    def restore(self, snap: list[dict[str, bytes]]) -> None:
        items = []
        for types in snap:
            item = self._ak.NSPasteboardItem.alloc().init()
            for t, raw in types.items():
                item.setData_forType_(F.NSData.dataWithBytes_length_(raw, len(raw)), t)
            items.append(item)
        self._pb.clearContents()
        if items:
            self._pb.writeObjects_(items)


def _clipboard() -> _Clipboard:
    return _Clipboard()


def _body_text(body: str) -> str:
    """The squashed body without the leading blanks and object-replacement marks the AX
    walk can emit before the first real text."""
    return squash_text(body.lstrip(" \n\t\ufffc"))


def _alnum(text: str) -> str:
    """Only the letters and digits of ``text``, for the quote-tail compare. The AX walk
    joins the parts of one line with a separator the original's own text does not have
    (a link or bold run followed by punctuation reads 'example.com .' for
    'example.com.'), and list bullets and '>' marks differ too. Squashed whitespace
    alone misses those; letters and digits carry the words and nothing else."""
    return "".join(c for c in squash_text(text) if c.isalnum())


def _starts_with(body: str, text: str) -> bool:
    return _body_text(body).startswith(squash_text(text))


def _wait_settled(el, text: str, before: str) -> bool:
    """Settled = the body starts with the text AND changed since just before the key
    event (facts 4e: a body that already started with the text once read as settled at
    4 ms, the clipboard was restored, and Mail's late Cmd-V pasted the user's own
    clipboard). Reads AX only, for at most ``_PASTE_SETTLE_S``."""
    t0 = time.monotonic()
    while True:
        body = _read_body(el)[0]
        if _starts_with(body, text) and squash_text(body) != before:
            return True
        if time.monotonic() - t0 >= _PASTE_SETTLE_S:
            return False
        time.sleep(0.05)


def _confirm(el, text: str, replace_all: bool, quote_tail: str | None) -> None:
    """Facts 4e `Confirm`, after a settled paste: the text is first and, in a quoted
    reply, the original's own tail follows it; after a whole-body replace nothing
    follows. Compared squashed (the AX walk drops empty lines); the tail compares by
    letters and digits only (``_alnum``). A body read that was cut short proves nothing
    about what follows, so it never confirms a whole-body replace and gets its own
    refusal reason when the tail was not seen."""
    read, complete = _read_body(el)
    body = _body_text(read)
    want = squash_text(text)
    if not body.startswith(want):
        raise ComposeRefused("confirmation: the reply does not start with your text")
    rest = body[len(want) :]
    if replace_all:
        if rest:
            raise ComposeRefused(
                "confirmation: text is left in the reply after your text, so the "
                "whole body was not replaced"
            )
        if not complete:
            raise ComposeRefused(
                "confirmation: the reply could not be read to its end through "
                "Accessibility, so the whole-body replace cannot be confirmed"
            )
    elif _alnum(quote_tail or "") not in _alnum(rest):
        if not complete:
            raise ComposeRefused(
                "confirmation: the reply is too long to check through Accessibility, "
                "so Mail's quote of the original could not be confirmed. To reply "
                "without the quote, call mail_reply with include_quote=False"
            )
        raise ComposeRefused(
            "confirmation: Mail's quote of the original does not follow your text. "
            "Mail's setting 'Quote the text of the original message' (Mail > "
            "Settings > Composing > Responding; 'Include original message text' "
            "before Mail 16) may be off, or a text selection is left in Mail's "
            "message viewer. Click the original once, or call mail_reply with "
            "include_quote=False"
        )


def compose_insert(
    window_id: int,
    text: str,
    *,
    replace_all: bool = False,
    quote_tail: str | None = None,
    rollback: Callable[[], object] | None = None,
) -> None:
    """Put ``text`` at the top of the reply window ``window_id`` that the caller opened
    in Mail, and confirm it landed (facts 4e, mechanism M2: one Cmd-V from a borrowed
    and restored clipboard). Raises ``ComposeRefused`` naming the failed step.

    ``replace_all`` first selects the whole body (a reply with no quote). Otherwise
    ``quote_tail`` (the last words of the original) must follow the text, else the
    call refuses: an unknown tail refuses before any write. ``rollback`` is called when
    the paste did not settle, BEFORE the clipboard comes back, so a late Cmd-V cannot
    paste the user's own clipboard into a reply that stays.

    Identity rule: the target is Mail (constant), the window is the id the caller
    bound, and right before the write Mail's AX focused element must be a body inside
    that window. The key goes to Mail's pid only; the borrowed item is marked
    transient and concealed; the clipboard is restored unless the user copied
    something newer. No text or clipboard content reaches a message or a log. Safe on
    or off the worker.
    """

    def work() -> None:
        if not accessibility_trusted():
            raise ComposeRefused(
                "Accessibility is off for this process, so nothing was inserted"
            )
        if not replace_all and not _alnum(quote_tail or ""):
            raise ComposeRefused(
                "confirmation: the original's last words are unknown, so Mail's "
                "quote cannot be confirmed and nothing was inserted"
            )
        pid = _mail_pid()
        clip = _clipboard()
        count = clip.change_count()  # BEFORE the snapshot: a copy during it is caught
        snap = clip.snapshot()
        _hold_window(window_id)
        el = _focused_body(pid, window_id)
        if replace_all:
            _post_cmd_key(pid, _KEY_A)
            time.sleep(_SELECT_ALL_WAIT_S)
            el = _focused_body(pid, window_id)  # right before the write
        before = squash_text(_read_body(el)[0])
        if clip.change_count() != count:  # the last step before the write
            raise ComposeRefused(
                "clipboard: the clipboard changed after it was saved, so nothing was "
                "pasted; run the call again"
            )
        mine = None  # the change count right after OUR write
        settled = False
        try:
            clip.write_text(text)
            mine = clip.change_count()
            _post_cmd_key(pid, _KEY_V)
            settled = _wait_settled(el, text, before)
            if not settled and rollback is not None:
                rollback()  # BEFORE the restore (facts 4e `Pasteboard`)
        except Exception:
            if rollback is not None:
                rollback()
            raise
        finally:
            # a newer copy by the user stays; a write that failed midway is undone
            if mine is None or clip.change_count() == mine:
                clip.restore(snap)
        if not settled:
            raise ComposeRefused(
                "confirmation: your text did not appear in the reply within "
                f"{_PASTE_SETTLE_S:g} s"
            )
        _confirm(el, text, replace_all, quote_tail)

    return work() if on_worker() else run_native(work)


def mac_region() -> str | None:
    """The Mac's locale region code (e.g. ``'BE'``), for the locale-derived phone
    country-code default (#59 — never a hardcoded +1). ``None`` if unavailable.

    A pure read of NSLocale: no EventKit thread affinity, no TCC — so it needs neither
    run_native nor a permission. Kept here so Foundation stays out of the adapters.
    Refuses off macOS.
    """
    require_macos()
    region = F.NSLocale.currentLocale().objectForKey_(F.NSLocaleCountryCode)
    return str(region) if region else None


def mail_attribution_stamp(when: datetime) -> tuple[str, str]:
    """``(date, time)`` of a naive local ``when`` in the Mac's own region, the two
    pieces of Mail's reply attribution ``On <date>, at <time>, <sender> wrote:`` (#348).

    The date (medium style) and the time (short style) are formatted apart: the
    combined style is not Mail's line. A Foundation read: no TCC. It runs on the worker
    like every native call and takes microseconds. Kept here so Foundation stays out of
    the adapters. Refuses off macOS (through ``run_native``).
    """

    def work() -> tuple[str, str]:
        # the wall clock passes through unchanged: read it as UTC, format it as UTC
        nsdate = F.NSDate.dateWithTimeIntervalSince1970_(
            calendar.timegm(when.timetuple())
        )

        def fmt(date_style, time_style) -> str:
            f = F.NSDateFormatter.alloc().init()
            f.setLocale_(F.NSLocale.currentLocale())
            f.setTimeZone_(F.NSTimeZone.timeZoneWithAbbreviation_("UTC"))
            f.setDateStyle_(date_style)
            f.setTimeStyle_(time_style)
            return str(f.stringFromDate_(nsdate))

        return (
            fmt(F.NSDateFormatterMediumStyle, F.NSDateFormatterNoStyle),
            fmt(F.NSDateFormatterNoStyle, F.NSDateFormatterShortStyle),
        )

    return work() if on_worker() else run_native(work)


log = logging.getLogger("macos_apps_mcp")


# NOTE: the write-audit trail + usage tally (#67) live in audit.py — they are plain
# file IO with no coupling to the native worker, so they don't belong in this module.

# NOTE: lifecycle hygiene (#56 — orphan watcher, SIGTERM/atexit child cleanup)
# lives in lifecycle.py; it consumes terminate_children() above.
