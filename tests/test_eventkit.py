"""Unit tests for the EventKit plane — pure helpers + the store fence; no real device
TCC calls (those are the D-08 device proof owned by plan 01-08)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import EventKit as EK
import pytest

from macos_apps_mcp.contracts import CLEAR_RECURRENCE, Recurrence
from macos_apps_mcp.errors import AccessDenied, NativeTimeout
from macos_apps_mcp.eventkit import (
    _require_full_access,
    due_components,
    epoch_nsdate,
    from_nsdate,
    persisted_recurrence_signature,
    recurrence_signature,
    rrule_text,
    run_native_async,
    store,
    to_nsdate,
    to_recurrence_rule,
)
from macos_apps_mcp.runtime import run_native


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


# --- verify-after-write diff (#49) recurrence signatures -----------------------------


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
    import macos_apps_mcp.eventkit as ek

    def deny(_s, _entity):
        raise ek.AccessDenied("denied")

    monkeypatch.setattr(ek, "_request_one", deny)
    ek.bootstrap()  # returns without raising despite every surface being denied


# --- GATE-02: eventkit owns no executor; runtime's stays max_workers=1 --------------


def test_eventkit_owns_no_executor():
    from concurrent.futures import ThreadPoolExecutor

    import macos_apps_mcp.eventkit as ek
    from macos_apps_mcp import runtime

    assert not any(
        isinstance(getattr(ek, name), ThreadPoolExecutor) for name in vars(ek)
    )
    assert runtime._executor._max_workers == 1
