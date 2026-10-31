"""Unit tests for the native runtime — pure helpers only; no EventKit calls."""

from __future__ import annotations

import contextlib
import pathlib
import re
import subprocess
import sys
import threading
import types
from datetime import datetime

import pytest

from macos_apps_mcp import runtime
from macos_apps_mcp.errors import (
    AccessDenied,
    AmbiguousTarget,
    AppNotRunning,
    AutomationDenied,
    BatchTooLarge,
    NativeError,
    NativeTimeout,
    OutputOverflow,
    RecurrenceRequired,
    SchemaDrift,
    SpanRequired,
    UnsupportedPlatform,
    VerificationFailed,
    WriteRefused,
    require_batch_within,
    resolve_container,
    verify_persisted,
)
from macos_apps_mcp.runtime import (
    _classify_osascript_failure,
    body_file,
    run_osascript,
)

# The seam's own self-tests bind the real function at import time: the conftest lock
# replaces ``runtime.automation_permission`` in every unit test.
_REAL_AUTOMATION_PERMISSION = runtime.automation_permission
# Same for the two Accessibility seams of the Mail reply flow (#348).
_REAL_ACCESSIBILITY_TRUSTED = runtime.accessibility_trusted
_REAL_COMPOSE_INSERT = runtime.compose_insert
# Same for the attribution formatter: conftest swaps it for a deterministic fake.
_REAL_MAIL_ATTRIBUTION_STAMP = getattr(runtime, "mail_attribution_stamp", None)


def test_run_osascript_returns_output():
    # Pure AppleScript expression — no app/TCC needed, so this is CI-safe.
    assert run_osascript('return "hello"') == "hello"


def test_run_osascript_strips_only_its_own_terminator():
    # osascript appends exactly one \n of its own; a trailing linefeed INSIDE the data
    # must survive. stdout here is "x\n\n" → exactly one strip leaves "x\n".
    assert run_osascript('return "x" & linefeed') == "x\n"


def test_run_osascript_raises_on_error():
    # A failing script must raise, never return "" (don't mask failures as "no result").
    # A script error with no OSStatus fingerprint stays the loud generic NativeError.
    with pytest.raises(NativeError, match="osascript failed"):
        run_osascript('error "boom"')


def test_run_osascript_leading_dash_arg_is_data_not_option():
    # #62 review: a leading-'-' arg (e.g. a mail search "-- Original") must reach
    # `on run argv` as DATA, not be parsed by osascript's getopt as an option. The `--`
    # separator makes it work; without it osascript aborts with "illegal option".
    script = "on run argv\nreturn item 1 of argv\nend run"
    assert run_osascript(script, "-- Original Message") == "-- Original Message"
    assert run_osascript(script, "-n") == "-n"


# --- typed error taxonomy (#47) ------------------------------------------------------


def test_taxonomy_all_subclass_native_error_and_runtime_error():
    # One `except NativeError` at the dispatch seam must catch every native failure, and
    # nothing weaker breaks the existing `except RuntimeError` callers.
    for cls in (
        AccessDenied,
        AutomationDenied,
        AppNotRunning,
        NativeTimeout,
        OutputOverflow,
        SchemaDrift,
        SpanRequired,
        VerificationFailed,
        WriteRefused,
        RecurrenceRequired,
        BatchTooLarge,
        AmbiguousTarget,
        UnsupportedPlatform,
    ):
        assert issubclass(cls, NativeError)
        assert issubclass(cls, RuntimeError)


def test_taxonomy_kinds_are_distinct_machine_codes():
    # `kind` is what doctor (#48) and agents branch on — no two classes may collide.
    kinds = [
        c.kind
        for c in (
            NativeError,
            AccessDenied,
            AutomationDenied,
            AppNotRunning,
            NativeTimeout,
            OutputOverflow,
            SchemaDrift,
            SpanRequired,
            VerificationFailed,
            WriteRefused,
            RecurrenceRequired,
            BatchTooLarge,
            AmbiguousTarget,
            UnsupportedPlatform,
        )
    ]
    assert len(kinds) == len(set(kinds))


def test_classify_automation_denied():
    err = _classify_osascript_failure(
        "execution error: Not authorized to send Apple events to Mail. (-1743)"
    )
    assert isinstance(err, AutomationDenied)
    assert "System Settings" in str(err) and "-1743" in str(err)


def test_classify_automation_denied_needs_no_restart():
    err = _classify_osascript_failure(
        "execution error: Not authorized to send Apple events to Mail. (-1743)"
    )
    assert isinstance(err, AutomationDenied)
    text = str(err)
    assert "System Settings" in text and "-1743" in text
    assert "Do not retry until the next user message" in text
    assert "restart" not in text.lower()


@pytest.mark.parametrize("code", ["(-609)", "(-10810)"])
def test_classify_app_not_running(code):
    err = _classify_osascript_failure(f"execution error: something {code}")
    assert isinstance(err, AppNotRunning)


def test_classify_unknown_code_stays_generic_native_error():
    # An unrecognized OSStatus must NOT be mis-fingerprinted as denied/not-running —
    # it stays a loud generic error carrying the raw native detail.
    err = _classify_osascript_failure("execution error: weird thing (-2700)")
    assert type(err) is NativeError
    assert "weird thing" in str(err)


def test_classify_bare_digits_do_not_false_match():
    # We match the parenthesized OSStatus, so a 1743 appearing bare in a subject/body
    # must not be read as an Automation denial.
    err = _classify_osascript_failure("execution error: order 1743 shipped (-2700)")
    assert type(err) is NativeError


def test_run_osascript_timeout_raises_native_timeout():
    # Real osascript, no TCC needed: a 2s delay against a 0.1s budget must surface as
    # NativeTimeout (not a bare TimeoutError, not a masked hang).
    with pytest.raises(NativeTimeout):
        run_osascript("delay 2", timeout=0.1)


# --- #183: wedged-vs-busy classification on the timeout path -------------------------


def test_classify_stuck_app_wedged_vs_busy():
    # facts §9b signatures: wedged = idle (state S, ~1% CPU) yet unresponsive,
    # permanent; busy = active process (running state or real CPU), self-recovering.
    assert runtime._classify_stuck_app("S", 0.9) == "wedged"
    assert runtime._classify_stuck_app("I", 0.0) == "wedged"  # idle >20s, still wedged
    assert runtime._classify_stuck_app("R", 1.0) == "busy"
    assert runtime._classify_stuck_app("U", 0.0) == "busy"
    assert runtime._classify_stuck_app("S+", 42.0) == "busy"  # sleeping, chewing CPU


def test_app_process_info_parses_ps(monkeypatch):
    def fake_tracked_run(cmd, *, timeout):
        out = "838\n" if cmd[0] == "pgrep" else "S    0.9 05:28:53\n"
        return subprocess.CompletedProcess(cmd, 0, out, "")

    monkeypatch.setattr(runtime, "tracked_run", fake_tracked_run)
    info = runtime.app_process_info("Mail")
    assert info == {"pid": 838, "state": "S", "cpu": 0.9, "etime": "05:28:53"}


def test_app_process_info_not_running_is_none(monkeypatch):
    # pgrep with no match exits 1 with empty stdout → None, never an exception.
    monkeypatch.setattr(
        runtime,
        "tracked_run",
        lambda cmd, *, timeout: subprocess.CompletedProcess(cmd, 1, "", ""),
    )
    assert runtime.app_process_info("Mail") is None


def test_timeout_hint_wedged_names_force_quit_and_pid(monkeypatch):
    monkeypatch.setattr(
        runtime,
        "app_process_info",
        lambda app: {"pid": 838, "state": "S", "cpu": 0.9, "etime": "37:12"},
    )
    hint = runtime._timeout_hint('tell application "Mail" to count accounts')
    # The wedged remediation must be the honest one (facts §9b): force-quit — a UI
    # quit can leave the wedged process alive — and verify the pid actually changed.
    assert "WEDGED" in hint and "killall Mail" in hint and "pid 838" in hint
    assert "pid changed" in hint


def test_timeout_hint_busy_says_self_recovering(monkeypatch):
    monkeypatch.setattr(
        runtime,
        "app_process_info",
        lambda app: {"pid": 99, "state": "R", "cpu": 87.0, "etime": "02:01"},
    )
    hint = runtime._timeout_hint('tell application "Mail" to count accounts')
    assert "busy" in hint and "recovers on its own" in hint
    assert "killall" not in hint  # never suggest a force-quit for a busy app


def test_timeout_hint_empty_without_app_or_process(monkeypatch):
    # No `tell application` in the script, or no readable process → empty hint, so
    # the generic timeout message reads exactly as before.
    assert runtime._timeout_hint("delay 2") == ""
    monkeypatch.setattr(runtime, "app_process_info", lambda app: None)
    assert runtime._timeout_hint('tell application "Mail" to count accounts') == ""


def test_classify_1712_is_native_timeout_with_hint(monkeypatch):
    # The in-script `with timeout` firing (-1712) must surface as the TYPED timeout
    # carrying the #183 classification, not a generic "osascript failed".
    monkeypatch.setattr(
        runtime,
        "app_process_info",
        lambda app: {"pid": 1, "state": "S", "cpu": 0.5, "etime": "40:00"},
    )
    err = _classify_osascript_failure(
        "execution error: Mail got an error: AppleEvent timed out. (-1712)",
        'tell application "Mail" to count accounts',
    )
    assert isinstance(err, NativeTimeout)
    assert "WEDGED" in str(err) and "-1712" in str(err)


# --- verify-after-write diff (#49) ---------------------------------------------------


def test_verify_persisted_passes_when_all_match():
    verify_persisted(
        "reminder",
        {"title": "x", "due": (2026, 6, 23)},
        {"title": "x", "due": (2026, 6, 23)},
    )


def test_verify_persisted_raises_naming_dropped_fields():
    with pytest.raises(VerificationFailed) as exc:
        verify_persisted(
            "reminder",
            {"title": "Pay rent", "due": (2026, 6, 25), "list": "Home"},
            {
                "title": "Pay rent",
                "due": None,
                "list": "Inbox",
            },  # due dropped, wrong list
        )
    msg = str(exc.value)
    assert "due" in msg and "list" in msg
    assert "title" not in msg  # unchanged fields aren't reported


def test_verify_persisted_ignores_keys_absent_from_expected():
    # only requested fields are diffed; extra persisted state (e.g. EventKit metadata)
    # is not a mismatch.
    verify_persisted(
        "event", {"title": "x"}, {"title": "x", "lastModified": "whenever"}
    )


# --- batch cap primitive (#54) -------------------------------------------------------


def test_require_batch_within_allows_at_or_under_cap():
    require_batch_within(0, 5, override_param="max_items")  # empty
    require_batch_within(5, 5, override_param="max_items")  # exactly at cap — no raise


def test_require_batch_within_raises_batch_too_large_naming_override():
    # Acceptance: the typed error names the override param so the model knows how to
    # deliberately raise the cap instead of blindly retrying the oversized batch.
    with pytest.raises(BatchTooLarge, match="max_items") as exc:
        require_batch_within(6, 5, override_param="max_items")
    msg = str(exc.value)
    assert "6" in msg and "5" in msg  # counts the model needs are surfaced


def test_batch_too_large_kind():
    assert BatchTooLarge.kind == "batch_too_large"


def test_ambiguous_target_kind():
    # the machine code doctor/agents branch on — pin the exact value, not just distinct.
    assert AmbiguousTarget.kind == "ambiguous_target"


# --- resolve_container (#55) — pure, plain-tuple tests -------------------------------


def _items():
    # (id, name, value); "Home" is duplicated (ids C0, C2) to exercise ambiguity.
    return [("C0", "Home", "home-a"), ("C1", "Work", "work"), ("C2", "Home", "home-b")]


def test_resolve_container_by_unique_name():
    assert resolve_container(_items(), "Work", noun="calendar") == "work"


def test_resolve_container_by_id_wins_over_name():
    # id-first: even a duplicate-named container is reachable by its unambiguous id.
    assert resolve_container(_items(), "C2", noun="calendar") == "home-b"


def test_resolve_container_missing_raises_valueerror():
    with pytest.raises(ValueError, match="no calendar named 'Nope'"):
        resolve_container(_items(), "Nope", noun="calendar")


def test_resolve_container_ambiguous_lists_all_candidate_ids():
    with pytest.raises(AmbiguousTarget) as ei:
        resolve_container(_items(), "Home", noun="reminder list")
    msg = str(ei.value)
    assert "2 reminder lists are named 'Home'" in msg
    assert "C0" in msg and "C2" in msg  # both candidates listed for recovery
    assert "C1" not in msg  # the non-matching container is not listed


def test_resolve_container_does_not_fold_write_targets():
    # #64 SAFETY: fold_text is READS-ONLY. A write target stays byte-exact, so an ASCII
    # "cafe" does NOT silently resolve to an accented "Café" list — the caller gets a
    # clear miss, never a wrong-container write (the whole point of not folding writes).
    items = [("L0", "Café", "accented"), ("L1", "Bistro", "bistro")]
    with pytest.raises(ValueError, match="no reminder list named 'cafe'"):
        resolve_container(items, "cafe", noun="reminder list")
    assert resolve_container(items, "Café", noun="reminder list") == "accented"


def test_resolve_container_keeps_accented_variants_distinct():
    # because writes don't fold, "Café" and "Cafe" are DISTINCT targets — each exact
    # name hits its own list (folding would collapse them into an AmbiguousTarget).
    items = [("L0", "Café", "accented"), ("L1", "Cafe", "plain")]
    assert resolve_container(items, "Cafe", noun="list") == "plain"
    assert resolve_container(items, "Café", noun="list") == "accented"


class _FakeProc:  # hashable (real object identity) so it can live in the _children set
    def __init__(self, on_terminate):
        self._on = on_terminate

    def terminate(self):
        self._on()


def test_terminate_children_terminates_tracked_child():
    import macos_apps_mcp.runtime as rt

    killed = []
    fake = _FakeProc(lambda: killed.append(True))
    with rt._children_lock:
        rt._children.add(fake)
    try:
        rt.terminate_children()
    finally:
        with rt._children_lock:
            rt._children.discard(fake)
    assert killed == [True]


def test_terminate_children_ignores_an_already_dead_child():
    import macos_apps_mcp.runtime as rt

    def boom():
        raise OSError("no such process")  # terminate() on a reaped child

    fake = _FakeProc(boom)
    with rt._children_lock:
        rt._children.add(fake)
    try:
        rt.terminate_children()  # must swallow OSError, not propagate
    finally:
        with rt._children_lock:
            rt._children.discard(fake)


# --- body_file (#62 transport) --------------------------------------------------------


def test_body_file_roundtrips_and_deletes():
    import os

    with body_file("héllo\nworld") as path, open(path, encoding="utf-8") as f:
        assert f.read() == "héllo\nworld"
    assert not os.path.exists(path)  # deleted on exit


def test_body_file_deletes_on_exception():
    import os

    try:
        with body_file("x") as path:
            raise RuntimeError("script failed")
    except RuntimeError:
        pass
    assert not os.path.exists(path)  # deleted even when the script raises


# --- FIX-14 (#455): the live, non-prompting Automation check ------------------------


def _fake_ae_lib(create_rc=0, determine_rc=-1743, threads=None):
    """A fake CoreServices: three recording callables (no real AE call)."""
    calls = []

    def _record(name, rc):
        def _fn(*args):
            calls.append((name, args))
            if threads is not None:
                threads.append(threading.current_thread().name)
            return rc

        return _fn

    lib = types.SimpleNamespace(
        AECreateDesc=_record("create", create_rc),
        AEDeterminePermissionToAutomateTarget=_record("determine", determine_rc),
        AEDisposeDesc=_record("dispose", 0),
    )
    return lib, calls


@pytest.mark.skipif(sys.platform != "darwin", reason="NSDateFormatter is macOS-only")
def test_mail_attribution_stamp_formats_date_and_time_apart(monkeypatch):
    # #348: Mail's `On <date>, at <time>, <sender> wrote:` has the date and the time
    # formatted apart; the combined style gives a different line.
    calls = []
    real_run_native = runtime.run_native

    def recording(fn):
        calls.append(fn)
        return real_run_native(fn)

    monkeypatch.setattr(runtime, "run_native", recording)
    date, time = _REAL_MAIL_ATTRIBUTION_STAMP(datetime(2026, 10, 13, 14, 39))
    assert "2026" in date and "13" in date
    assert "39" in time
    assert " at " not in date and " at " not in time
    # PM-15: formatted apart, not one combined string split afterwards
    assert ":" not in date and "2026" not in time
    # and the date is exactly Foundation's date-only string (no leftover "at"/comma)
    import Foundation as F

    nsdate = F.NSDate.dateWithTimeIntervalSince1970_(1_791_902_340)  # 2026-10-13 14:39Z
    utc = F.NSDateFormatter.alloc().init()
    utc.setTimeZone_(F.NSTimeZone.timeZoneWithAbbreviation_("UTC"))
    utc.setLocale_(F.NSLocale.currentLocale())
    utc.setDateStyle_(F.NSDateFormatterMediumStyle)
    utc.setTimeStyle_(F.NSDateFormatterNoStyle)
    assert date == str(utc.stringFromDate_(nsdate))
    assert len(calls) == 1  # off the worker, so it went through run_native once


@pytest.mark.skipif(sys.platform != "darwin", reason="NSDateFormatter is macOS-only")
def test_mail_attribution_stamp_keeps_the_wall_clock(monkeypatch):
    # PM-17: the wall clock passes through unchanged, whatever the zone: 02:30 is
    # inside Europe/Brussels' 2026-03-29 DST gap and must not move to 01:30 or 03:30.
    import time as _time

    monkeypatch.setenv("TZ", "Europe/Brussels")
    _time.tzset()
    try:
        _, gap = _REAL_MAIL_ATTRIBUTION_STAMP(datetime(2026, 3, 29, 2, 30))
        date, clock = _REAL_MAIL_ATTRIBUTION_STAMP(datetime(2026, 10, 26, 1, 36))
    finally:
        monkeypatch.delenv("TZ")
        _time.tzset()
    assert re.search(r"(?<!\d)0?2\D30", gap)  # 12-hour locales print 2:30
    assert re.search(r"(?<!\d)0?1\D36", clock)
    if date.startswith("26 Oct"):  # en_GB-style locale
        assert (date, clock) == ("26 Oct 2026", "01:36")


def test_automation_permission_binds_the_ae_calls(monkeypatch):
    lib, calls = _fake_ae_lib(determine_rc=-1743)
    monkeypatch.setattr(runtime, "_ae_lib", lambda: lib)
    assert _REAL_AUTOMATION_PERMISSION("com.apple.Notes") == -1743
    assert [c[0] for c in calls] == ["create", "determine", "dispose"]
    create = calls[0][1]
    assert create[0] == 0x62756E64 and create[1] == b"com.apple.Notes"
    assert create[2] == 15
    determine = calls[1][1]
    # wildcard class and id, and askUserIfNeeded is the constant 0: never prompts.
    assert determine[1:] == (0x2A2A2A2A, 0x2A2A2A2A, 0)


def test_automation_permission_returns_a_create_error_without_a_determine(
    monkeypatch,
):
    lib, calls = _fake_ae_lib(create_rc=-50)
    monkeypatch.setattr(runtime, "_ae_lib", lambda: lib)
    assert _REAL_AUTOMATION_PERMISSION("com.apple.Notes") == -50
    assert [c[0] for c in calls] == ["create"]


def test_automation_permission_runs_on_the_worker_and_waits_behind_it(monkeypatch):
    threads: list[str] = []
    lib, _ = _fake_ae_lib(determine_rc=0, threads=threads)
    monkeypatch.setattr(runtime, "_ae_lib", lambda: lib)
    release = threading.Event()
    started = threading.Event()

    def _hold():
        started.set()
        release.wait(10)

    held = runtime._executor.submit(_hold)
    assert started.wait(5)
    result: list[int] = []
    t = threading.Thread(
        target=lambda: result.append(_REAL_AUTOMATION_PERMISSION("com.apple.mail"))
    )
    t.start()
    t.join(0.2)
    assert t.is_alive() and not result  # queued behind the held worker
    release.set()
    held.result(5)
    t.join(5)
    assert result == [0]
    assert threads and all(n.startswith("mac-native") for n in threads)


# --- GATE-02: runtime's public surface is exactly the native door -------------------


def test_runtime_public_surface_is_the_native_door(monkeypatch):
    # The public names runtime defines: callables whose __module__ is this module,
    # plus the logger `log` — excludes imported modules/functions and anything
    # starting with "_". A card-7 regression (a moved name left behind, or a new
    # public name added without updating eventkit.py) fails this test immediately.
    #
    # `monkeypatch` here is the SAME function-scoped fixture instance the autouse
    # `_no_real_osascript` seam lock (conftest.py) already used to patch
    # run_osascript/body_file/tracked_run to `_refuse` — undo() restores the real
    # bindings so this introspects the module's actual surface, not the test-time fake.
    monkeypatch.undo()
    import inspect

    public = set()
    for name, val in vars(runtime).items():
        if name.startswith("_"):
            continue
        if name == "log":
            public.add(name)
            continue
        if (
            inspect.isfunction(val)
            and getattr(val, "__module__", None) == "macos_apps_mcp.runtime"
        ):
            public.add(name)
    assert public == {
        "run_native",
        "require_macos",
        "on_worker",
        "app_process_info",
        "terminate_children",
        "tracked_run",
        "run_osascript",
        "body_file",
        "verify_sqlite_schema",
        "read_via_sqlite",
        "photos_db",
        "automation_permission",
        "accessibility_trusted",
        "compose_insert",
        "mac_region",
        "mail_attribution_stamp",
        "log",
    }
    assert not hasattr(runtime, "EK")


# --- FIX-16 (#348): the two Accessibility seams -------------------------------
#
# Facts section 4e is the contract. No test here makes a real AX, CoreGraphics or
# pasteboard call: every private loader and helper is replaced.


def test_accessibility_trusted_reads_the_switch_without_a_prompt(monkeypatch):
    threads: list[str] = []

    def trust():
        threads.append(threading.current_thread().name)
        return True

    monkeypatch.setattr(runtime, "_ax_lib", lambda: {"AXIsProcessTrusted": trust})
    assert _REAL_ACCESSIBILITY_TRUSTED() is True
    assert threads and all(n.startswith("mac-native") for n in threads)
    monkeypatch.setattr(
        runtime, "_ax_lib", lambda: {"AXIsProcessTrusted": lambda: False}
    )
    assert _REAL_ACCESSIBILITY_TRUSTED() is False
    # only the non-prompting trust read exists in the runtime source (T-05.2-38)
    assert "WithOptions" not in pathlib.Path(runtime.__file__).read_text("utf-8")


class _Clip:
    """A fake general pasteboard: records the order of its calls."""

    def __init__(self, events, items=None):
        self.events = events
        self.items = items if items is not None else [{"public.utf8-plain-text": b"x"}]
        self.count = 10
        self.written: list[str] = []

    def change_count(self):
        return self.count

    def snapshot(self):
        self.events.append("snapshot")
        return [dict(i) for i in self.items]

    def write_text(self, text):
        self.events.append("write")
        self.written.append(text)
        self.count += 1

    def restore(self, snap):
        self.events.append("restore")
        self.items = snap
        self.count += 1


def _compose_rig(
    monkeypatch,
    bodies,
    *,
    held=True,
    focused=True,
    trusted=True,
    items=None,
):
    """Replace every private loader of compose_insert. ``bodies`` is the AX read-back
    sequence (the last one repeats). Returns (events, clip, keys)."""
    events: list = []
    keys: list = []
    reads = iter(bodies)
    last = [bodies[0]]
    clip = _Clip(events, items)
    clock = [0.0]

    def read(_el):
        events.append("read")
        with contextlib.suppress(StopIteration):
            last[0] = next(reads)
        return last[0]

    def hold(window_id):
        events.append(("hold", window_id))
        if not held:
            raise runtime.ComposeRefused("window check: not the front window")

    def focus(pid, window_id):
        events.append(("focus", pid, window_id))
        if not focused:
            raise runtime.ComposeRefused("focus check: not the reply body")
        return "EL"

    def sleep(seconds):
        clock[0] += seconds

    monkeypatch.setattr(runtime, "accessibility_trusted", lambda: trusted)
    monkeypatch.setattr(runtime, "_mail_pid", lambda: 4242)
    monkeypatch.setattr(runtime, "_clipboard", lambda: clip)
    monkeypatch.setattr(runtime, "_hold_window", hold)
    monkeypatch.setattr(runtime, "_focused_body", focus)
    monkeypatch.setattr(runtime, "_read_body", read)
    monkeypatch.setattr(
        runtime, "_post_cmd_key", lambda pid, code: keys.append((pid, code))
    )
    monkeypatch.setattr(
        runtime,
        "time",
        types.SimpleNamespace(monotonic=lambda: clock[0], sleep=sleep),
    )
    return events, clip, keys


_TEXT = "Hi there"
_QUOTE = "On 1 Jul 2026, at 14:39, Jane wrote:\n> original words end here"


def test_compose_insert_targets_mails_window_only(monkeypatch):
    events, clip, keys = _compose_rig(monkeypatch, ["", f"{_TEXT}\n{_QUOTE}"])
    _REAL_COMPOSE_INSERT(77, _TEXT, quote_tail="original words end here")
    assert runtime._MAIL_BUNDLE == "com.apple.mail"
    assert keys == [(4242, 9)]  # exactly one Cmd-V, to Mail's pid
    assert ("hold", 77) in events and ("focus", 4242, 77) in events
    assert clip.written == [_TEXT]
    # the order of facts 4e `Insert`: snapshot, window, focus, write, key, restore
    names = [e if isinstance(e, str) else e[0] for e in events]
    assert names.index("snapshot") < names.index("hold") < names.index("focus")
    assert names.index("focus") < names.index("write") < names.index("restore")


def test_post_cmd_key_sends_one_down_and_one_up_to_mails_pid_only(monkeypatch):
    calls: list = []

    class Lib:
        def CGEventCreateKeyboardEvent(self, src, code, down):
            calls.append(("create", src, code, down))
            return f"ev{len(calls)}"

        def CGEventSetFlags(self, ev, flags):
            calls.append(("flags", ev, flags))

        def CGEventPostToPid(self, pid, ev):
            calls.append(("post", pid, ev))

        def CFRelease(self, ev):
            calls.append(("release", ev))

    monkeypatch.setattr(runtime, "_cg_lib", lambda: Lib())
    runtime._post_cmd_key(4242, 9)
    creates = [c for c in calls if c[0] == "create"]
    assert [(c[2], c[3]) for c in creates] == [(9, True), (9, False)]
    assert [c[2] for c in calls if c[0] == "flags"] == [0x100000, 0x100000]
    assert [c[1] for c in calls if c[0] == "post"] == [4242, 4242]
    assert "CGEventPost(" not in pathlib.Path(runtime.__file__).read_text("utf-8")


def test_compose_insert_refuses_unconfirmed_text(monkeypatch):
    # the body never changes: not settled -> the reply is rolled back BEFORE the restore
    events, clip, keys = _compose_rig(monkeypatch, ["old body"])
    with pytest.raises(runtime.ComposeRefused, match="confirmation"):
        _REAL_COMPOSE_INSERT(
            77,
            _TEXT,
            quote_tail="tail words",
            rollback=lambda: events.append("rollback"),
        )
    assert "rollback" in events and "restore" in events
    assert events.index("rollback") < events.index("restore")
    assert (4242, 9) in keys


def test_compose_insert_refuses_another_front_window(monkeypatch):
    events, clip, keys = _compose_rig(monkeypatch, ["x"], held=False)
    with pytest.raises(runtime.ComposeRefused, match="window check"):
        _REAL_COMPOSE_INSERT(77, _TEXT, quote_tail="tail")
    assert keys == [] and "write" not in events  # before any key event or write
    events, clip, keys = _compose_rig(monkeypatch, ["x"], focused=False)
    with pytest.raises(runtime.ComposeRefused, match="focus check"):
        _REAL_COMPOSE_INSERT(77, _TEXT, quote_tail="tail")
    assert keys == [] and "write" not in events


def test_compose_insert_refuses_when_accessibility_is_off(monkeypatch):
    events, clip, keys = _compose_rig(monkeypatch, ["x"], trusted=False)
    with pytest.raises(runtime.ComposeRefused, match="Accessibility"):
        _REAL_COMPOSE_INSERT(77, _TEXT, quote_tail="tail")
    assert events == [] and keys == []  # clipboard untouched, no key event


def test_compose_insert_refuses_a_reply_without_mails_quote(monkeypatch):
    # the text landed, but nothing follows it: Mail's quote is missing
    _compose_rig(monkeypatch, ["", _TEXT])
    with pytest.raises(runtime.ComposeRefused, match="confirmation") as exc:
        _REAL_COMPOSE_INSERT(77, _TEXT, quote_tail="original words end here")
    msg = str(exc.value)
    assert "Quote the text of the original message" in msg
    assert "include_quote=False" in msg


def test_compose_insert_refuses_an_unknown_quote_tail_before_any_write(monkeypatch):
    events, _, keys = _compose_rig(monkeypatch, [""])
    with pytest.raises(runtime.ComposeRefused, match="confirmation"):
        _REAL_COMPOSE_INSERT(77, _TEXT)  # a quoted reply with no known tail
    assert events == [] and keys == []


def test_compose_insert_confirms_after_nfc_and_line_folding(monkeypatch):
    import unicodedata

    text = "Hi\nSecond line \u2013 caf\u00e9 \u2713"
    readback = unicodedata.normalize("NFD", text).replace("\n", "\r\n")
    _compose_rig(monkeypatch, ["", f"{readback}\r\nquote text tail words"])
    _REAL_COMPOSE_INSERT(77, text, quote_tail="tail words")
    # the AX walk drops empty lines: no blank line between two paragraphs still passes
    para = "First paragraph.\n\nSecond paragraph."
    _compose_rig(
        monkeypatch, ["", "First paragraph.\nSecond paragraph.\nquote tail words"]
    )
    _REAL_COMPOSE_INSERT(77, para, quote_tail="tail words")
    # the text after the quote is not the text on top
    _compose_rig(monkeypatch, ["", f"quote tail words\n{text}"])
    with pytest.raises(runtime.ComposeRefused):
        _REAL_COMPOSE_INSERT(77, text, quote_tail="tail words")


def test_compose_insert_replace_all_selects_all_and_wants_nothing_after(monkeypatch):
    events, _, keys = _compose_rig(monkeypatch, ["old quote", _TEXT])
    _REAL_COMPOSE_INSERT(77, _TEXT, replace_all=True)
    assert keys == [(4242, 0), (4242, 9)]  # Cmd-A, then Cmd-V, both to Mail
    assert [e for e in events if isinstance(e, tuple) and e[0] == "focus"] == [
        ("focus", 4242, 77),
        ("focus", 4242, 77),  # the focus check runs again after Cmd-A
    ]
    _compose_rig(monkeypatch, ["old quote", f"{_TEXT}\nleft over quote"])
    with pytest.raises(runtime.ComposeRefused, match="confirmation"):
        _REAL_COMPOSE_INSERT(77, _TEXT, replace_all=True)


def test_compose_insert_seam_takes_no_target_app():
    import inspect

    params = list(inspect.signature(_REAL_COMPOSE_INSERT).parameters)
    assert params[:2] == ["window_id", "text"]
    assert set(params) == {"window_id", "text", "replace_all", "quote_tail", "rollback"}
    assert not any(w in p for p in params for w in ("app", "pid", "bundle"))
    assert runtime._MAIL_BUNDLE == "com.apple.mail"


def test_compose_insert_restores_every_pasteboard_item(monkeypatch):
    items = [
        {"public.utf8-plain-text": b"a", "public.html": b"<b>a</b>"},
        {"com.example.one": b"\x00\x01", "com.example.two": b"b"},
    ]
    events, clip, _ = _compose_rig(monkeypatch, ["", f"{_TEXT}\ntail"], items=items)
    _REAL_COMPOSE_INSERT(77, _TEXT, quote_tail="tail")
    assert clip.items == items
    # and also when the insert raised
    events, clip, _ = _compose_rig(monkeypatch, ["old"], items=items)
    monkeypatch.setattr(
        runtime, "_post_cmd_key", lambda *a: (_ for _ in ()).throw(OSError("boom"))
    )
    with pytest.raises(OSError):
        _REAL_COMPOSE_INSERT(77, _TEXT, quote_tail="tail")
    assert clip.items == items


def test_compose_insert_undoes_a_clipboard_write_that_failed_midway(monkeypatch):
    events, clip, keys = _compose_rig(monkeypatch, ["old"])

    def broken(_text):
        raise OSError("pasteboard write failed")

    monkeypatch.setattr(clip, "write_text", broken)
    with pytest.raises(OSError):
        _REAL_COMPOSE_INSERT(77, _TEXT, quote_tail="tail")
    assert "restore" in events and keys == []  # no key event for a failed write


def test_compose_insert_keeps_a_newer_user_copy(monkeypatch):
    events, clip, _ = _compose_rig(monkeypatch, ["", f"{_TEXT}\ntail"])
    real_read = runtime._read_body

    def read(el):
        clip.count += 5  # the user copies something while the paste settles
        return real_read(el)

    monkeypatch.setattr(runtime, "_read_body", read)
    _REAL_COMPOSE_INSERT(77, _TEXT, quote_tail="tail")
    assert "restore" not in events


def test_compose_insert_marks_the_borrowed_clipboard_transient():
    assert runtime._TRANSIENT_TYPES == (
        "org.nspasteboard.TransientType",
        "org.nspasteboard.ConcealedType",
    )


def test_compose_insert_refuses_a_changed_clipboard_before_writing(monkeypatch):
    events, clip, keys = _compose_rig(monkeypatch, ["x"])
    real_focus = runtime._focused_body

    def focus(pid, wid):
        clip.count += 1  # a copy between the snapshot and the write
        return real_focus(pid, wid)

    monkeypatch.setattr(runtime, "_focused_body", focus)
    with pytest.raises(runtime.ComposeRefused, match="clipboard"):
        _REAL_COMPOSE_INSERT(77, _TEXT, quote_tail="tail")
    assert "write" not in events and keys == []


def test_compose_insert_restores_only_after_the_paste_settles(monkeypatch):
    # the text shows on the third read: the restore comes after that read
    events, _, _ = _compose_rig(
        monkeypatch, ["old", "old", "old", f"{_TEXT}\ntail", f"{_TEXT}\ntail"]
    )
    _REAL_COMPOSE_INSERT(77, _TEXT, quote_tail="tail")
    assert events.count("read") >= 4
    assert events.index("restore") > [i for i, e in enumerate(events) if e == "read"][3]
    # never shown: the restore runs after the bound, and the call refuses
    events, _, _ = _compose_rig(monkeypatch, ["old"])
    with pytest.raises(runtime.ComposeRefused, match="confirmation"):
        _REAL_COMPOSE_INSERT(77, _TEXT, quote_tail="tail")
    assert runtime._PASTE_SETTLE_S == 1.0
    assert "restore" in events


def test_compose_insert_does_not_settle_on_an_unchanged_body(monkeypatch):
    # facts 4e late-paste finding: a body that already starts with the text is not proof
    events, _, _ = _compose_rig(monkeypatch, [f"{_TEXT}\ntail"])
    with pytest.raises(runtime.ComposeRefused, match="confirmation"):
        _REAL_COMPOSE_INSERT(77, _TEXT, quote_tail="tail")


def test_snapshot_incomplete_refuses_and_an_empty_pasteboard_is_complete():
    require = runtime._require_complete_snapshot
    require([{"t": b"x"}], 0, 1)
    require([], 0, 0)  # emptied pasteboard: no items and no types
    with pytest.raises(runtime.ComposeRefused, match="clipboard"):
        require([{"t": b"x"}], 1, 2)  # one unreadable type
    with pytest.raises(runtime.ComposeRefused, match="clipboard"):
        require([], 0, 3)  # types present, no items


class _FakeAx:
    """A fake HIServices binding over a dict of element -> attributes."""

    def __init__(self, attrs, windows):
        self.attrs, self.windows = attrs, windows

    def lib(self):
        return {
            "AXUIElementCreateApplication": lambda pid: ("app", pid),
            "AXUIElementCopyAttributeValue": lambda el, attr, _: (
                (0, self.attrs[el][attr])
                if attr in self.attrs.get(el, {})
                else (-25212, None)
            ),
            "_AXUIElementGetWindow": lambda win, _: (0, self.windows[win]),
        }


def test_focused_body_wants_a_web_area_inside_the_bound_window(monkeypatch):
    ax = _FakeAx(
        {
            ("app", 4242): {"AXFocusedUIElement": "body"},
            "body": {"AXRole": "AXWebArea", "AXWindow": "win"},
        },
        {"win": 5001},
    )
    monkeypatch.setattr(runtime, "_ax_lib", ax.lib)
    assert runtime._focused_body(4242, 5001) == "body"
    with pytest.raises(runtime.ComposeRefused, match="focus check"):
        runtime._focused_body(4242, 9999)  # another window of Mail
    ax.attrs["body"]["AXRole"] = "AXTextField"
    with pytest.raises(runtime.ComposeRefused, match="focus check"):
        runtime._focused_body(4242, 5001)  # not a body


def test_focused_body_waits_up_to_three_seconds_for_a_fresh_reply(monkeypatch):
    ax = _FakeAx({("app", 4242): {}, "body": {}}, {})
    clock = [0.0]
    monkeypatch.setattr(runtime, "_ax_lib", ax.lib)
    monkeypatch.setattr(
        runtime,
        "time",
        types.SimpleNamespace(
            monotonic=lambda: clock[0],
            sleep=lambda s: clock.__setitem__(0, clock[0] + s),
        ),
    )
    with pytest.raises(runtime.ComposeRefused, match="focus check"):
        runtime._focused_body(4242, 5001)
    assert 3.0 <= clock[0] < 3.5


def test_read_body_walks_the_static_text_parts(monkeypatch):
    attrs = {
        "web": {"AXRole": "AXWebArea", "AXChildren": ["a", "b"]},
        "a": {"AXRole": "AXStaticText", "AXValue": "first"},
        "b": {"AXRole": "AXGroup", "AXChildren": ["c"]},
        "c": {"AXRole": "AXStaticText", "AXValue": "second"},
    }
    ax = _FakeAx(attrs, {})
    monkeypatch.setattr(runtime, "_ax_lib", ax.lib)
    assert runtime._read_body("web") == "first\nsecond"
