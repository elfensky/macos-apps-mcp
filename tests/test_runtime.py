"""Unit tests for the native runtime — pure helpers only; no EventKit calls."""

from __future__ import annotations

import subprocess
from datetime import datetime
from types import SimpleNamespace

import EventKit as EK
import pytest

from macos_apps_mcp import runtime
from macos_apps_mcp.contracts import CLEAR_RECURRENCE, Recurrence
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
    VerificationFailed,
    WriteRefused,
    require_batch_within,
    resolve_container,
    verify_persisted,
)
from macos_apps_mcp.runtime import (
    _classify_osascript_failure,
    _require_full_access,
    due_components,
    epoch_nsdate,
    from_nsdate,
    persisted_recurrence_signature,
    recurrence_signature,
    rrule_text,
    run_native,
    run_native_async,
    run_osascript,
    store,
    to_nsdate,
    to_recurrence_rule,
)


def test_require_full_access_passes_on_full_access():
    _require_full_access(3)  # EKAuthorizationStatusFullAccess — returns without raising


@pytest.mark.parametrize(
    "status", [0, 1, 2, 4]
)  # notDetermined, restricted, denied, writeOnly
def test_require_full_access_raises_on_anything_else(status):
    with pytest.raises(AccessDenied, match="System Settings"):
        _require_full_access(status)


def test_store_rejects_off_worker_calls():
    # Called directly (main thread, not the mac-native worker) → must refuse.
    with pytest.raises(RuntimeError, match="run_native"):
        store()


def test_store_returns_same_instance_on_worker():
    s1 = run_native(store)
    s2 = run_native(store)
    assert s1 is s2  # one store, created once, on the worker


def test_nsdate_roundtrip():
    dt = datetime(2026, 6, 23, 9, 30, 0)
    assert abs((from_nsdate(to_nsdate(dt)) - dt).total_seconds()) < 1


def test_epoch_nsdate_preserves_exact_epoch(monkeypatch):
    # 1793514600 is the *second* 01:30 in the US fall-back repeated hour — the instant
    # datetime±timedelta arithmetic shifts by 1h (fold reset). Pin the tz so the
    # fold-proof claim is exercised where it matters.
    import time

    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    try:
        assert epoch_nsdate(1793514600).timeIntervalSince1970() == 1793514600
    finally:
        monkeypatch.undo()
        time.tzset()


def test_due_components_fields():
    c = due_components(datetime(2026, 6, 23, 18, 45))
    assert (c.year(), c.month(), c.day(), c.hour(), c.minute()) == (2026, 6, 23, 18, 45)


def test_to_recurrence_rule_frequency_and_interval():
    # EKRecurrenceRule is a value object — buildable off the worker, no store/TCC.
    rule = to_recurrence_rule(Recurrence(frequency="weekly", interval=2))
    assert rule.frequency() == EK.EKRecurrenceFrequencyWeekly
    assert rule.interval() == 2
    assert rule.recurrenceEnd() is None  # open-ended


def test_to_recurrence_rule_count_end():
    rule = to_recurrence_rule(Recurrence(frequency="daily", count=5))
    assert rule.recurrenceEnd().occurrenceCount() == 5


def test_to_recurrence_rule_until_end():
    r = Recurrence(frequency="monthly", until=datetime(2026, 12, 31))
    end = to_recurrence_rule(r).recurrenceEnd()
    assert end is not None and end.occurrenceCount() == 0  # date-based, not count


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
        )
    ]
    assert len(kinds) == len(set(kinds))


def test_classify_automation_denied():
    err = _classify_osascript_failure(
        "execution error: Not authorized to send Apple events to Mail. (-1743)"
    )
    assert isinstance(err, AutomationDenied)
    assert "System Settings" in str(err) and "-1743" in str(err)


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
    assert runtime.classify_stuck_app("S", 0.9) == "wedged"
    assert runtime.classify_stuck_app("I", 0.0) == "wedged"  # idle >20s, still wedged
    assert runtime.classify_stuck_app("R", 1.0) == "busy"
    assert runtime.classify_stuck_app("U", 0.0) == "busy"
    assert runtime.classify_stuck_app("S+", 42.0) == "busy"  # sleeping, chewing CPU


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


def test_recurrence_signature_requested():
    assert recurrence_signature(None) is None
    assert recurrence_signature(CLEAR_RECURRENCE) is None  # explicit clear == no rule
    # frequency maps to the EK constant; interval defaults 1; no count → 0
    assert recurrence_signature(Recurrence(frequency="daily")) == (
        int(EK.EKRecurrenceFrequencyDaily),
        1,
        0,
    )
    assert recurrence_signature(
        Recurrence(frequency="weekly", interval=2, count=10)
    ) == (int(EK.EKRecurrenceFrequencyWeekly), 2, 10)


def test_persisted_recurrence_signature_readback():
    assert persisted_recurrence_signature(None) is None
    assert persisted_recurrence_signature([]) is None
    rule = SimpleNamespace(
        frequency=lambda: EK.EKRecurrenceFrequencyWeekly,
        interval=lambda: 2,
        recurrenceEnd=lambda: SimpleNamespace(occurrenceCount=lambda: 10),
    )
    assert persisted_recurrence_signature([rule]) == (
        int(EK.EKRecurrenceFrequencyWeekly),
        2,
        10,
    )


def test_rrule_text_renders_freq_interval_count():
    rule = SimpleNamespace(
        frequency=lambda: EK.EKRecurrenceFrequencyWeekly,
        interval=lambda: 2,
        recurrenceEnd=lambda: SimpleNamespace(occurrenceCount=lambda: 10),
    )
    assert rrule_text(rule) == "FREQ=WEEKLY;INTERVAL=2;COUNT=10"


def test_rrule_text_omits_count_when_open_ended_or_date_based():
    open_ended = SimpleNamespace(
        frequency=lambda: EK.EKRecurrenceFrequencyDaily,
        interval=lambda: 1,
        recurrenceEnd=lambda: None,
    )
    assert rrule_text(open_ended) == "FREQ=DAILY;INTERVAL=1"
    # date-based end reports occurrenceCount 0 → no COUNT= (matches signature rules)
    until_based = SimpleNamespace(
        frequency=lambda: EK.EKRecurrenceFrequencyMonthly,
        interval=lambda: 3,
        recurrenceEnd=lambda: SimpleNamespace(occurrenceCount=lambda: 0),
    )
    assert rrule_text(until_based) == "FREQ=MONTHLY;INTERVAL=3"


def test_recurrence_signatures_agree_for_equivalent_rule():
    # the requested and persisted signatures must be equal for an unchanged write, so
    # verify-after-write doesn't false-fail a correct recurrence.
    req = recurrence_signature(Recurrence(frequency="monthly", interval=1))
    rule = SimpleNamespace(
        frequency=lambda: EK.EKRecurrenceFrequencyMonthly,
        interval=lambda: 1,
        recurrenceEnd=lambda: None,  # open-ended → count 0
    )
    assert req == persisted_recurrence_signature([rule])


def test_run_native_async_returns_result():
    # start() invokes the completion immediately; the result flows back through finish.
    assert run_native_async(lambda finish: finish("ok")) == "ok"


def test_run_native_async_timeout_raises_native_timeout():
    # a callback that never fires must raise the TYPED timeout (agent-directed, caught
    # by the `except NativeError` dispatch seam), not a bare builtin TimeoutError.
    with pytest.raises(NativeTimeout, match="callback never fired"):
        run_native_async(lambda finish: None, timeout=0.05)


def test_bootstrap_is_nonfatal_on_denied_surface(monkeypatch):
    # #13 safe-mode: a denied TCC surface must not crash startup.
    import macos_apps_mcp.runtime as rt

    def deny(_s, _entity):
        raise rt.AccessDenied("denied")

    monkeypatch.setattr(rt, "_request_one", deny)
    rt.bootstrap()  # returns without raising despite every surface being denied


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

    from macos_apps_mcp.runtime import body_file

    with body_file("héllo\nworld") as path, open(path, encoding="utf-8") as f:
        assert f.read() == "héllo\nworld"
    assert not os.path.exists(path)  # deleted on exit


def test_body_file_deletes_on_exception():
    import os

    from macos_apps_mcp.runtime import body_file

    try:
        with body_file("x") as path:
            raise RuntimeError("script failed")
    except RuntimeError:
        pass
    assert not os.path.exists(path)  # deleted even when the script raises
