"""Unit tests for the native runtime — pure helpers only; no EventKit calls."""

from __future__ import annotations

from datetime import datetime

import EventKit as EK
import pytest

from mac_mcp.contracts import Recurrence
from mac_mcp.runtime import (
    AccessDenied,
    AppNotRunning,
    AutomationDenied,
    NativeError,
    NativeTimeout,
    OutputOverflow,
    SchemaDrift,
    _classify_osascript_failure,
    _decide,
    due_components,
    from_nsdate,
    run_native,
    run_native_async,
    run_osascript,
    store,
    to_nsdate,
    to_recurrence_rule,
)


def test_decide_passes_on_full_access():
    _decide(3)  # EKAuthorizationStatusFullAccess — returns without raising


@pytest.mark.parametrize(
    "status", [0, 1, 2, 4]
)  # notDetermined, restricted, denied, writeOnly
def test_decide_raises_on_anything_else(status):
    with pytest.raises(AccessDenied, match="System Settings"):
        _decide(status)


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


def test_run_osascript_raises_on_error():
    # A failing script must raise, never return "" (don't mask failures as "no result").
    # A script error with no OSStatus fingerprint stays the loud generic NativeError.
    with pytest.raises(NativeError, match="osascript failed"):
        run_osascript('error "boom"')


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


def test_run_native_async_returns_result():
    # start() invokes the completion immediately; the result flows back through finish.
    assert run_native_async(lambda finish: finish("ok")) == "ok"


def test_run_native_async_times_out():
    # a callback that never fires must raise, not hang the caller.
    with pytest.raises(TimeoutError):
        run_native_async(lambda finish: None, timeout=0.1)


def test_bootstrap_is_nonfatal_on_denied_surface(monkeypatch):
    # #13 safe-mode: a denied TCC surface must not crash startup.
    import mac_mcp.runtime as rt

    def deny(_s, _entity):
        raise rt.AccessDenied("denied")

    monkeypatch.setattr(rt, "_request_one", deny)
    rt.bootstrap()  # returns without raising despite every surface being denied
