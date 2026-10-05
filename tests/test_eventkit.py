"""Unit tests for the EventKit plane — pure helpers + the store fence; no real device
TCC calls (those are the D-08 device proof owned by plan 01-08)."""

from __future__ import annotations

from datetime import datetime

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
from tests._fakes import fake_rule


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


# --- BYDAY: the 9-argument builder (D-07) ---------------------------------------------


def test_to_recurrence_rule_byday_ordinal_is_built_with_the_full_initializer():
    rule = to_recurrence_rule(Recurrence.from_rrule("FREQ=MONTHLY;BYDAY=2TU"))
    day = rule.daysOfTheWeek()[0]
    assert day.weekNumber() == 2
    assert day.dayOfTheWeek() == 3  # EKWeekday: SU=1 … TU=3
    assert rule.daysOfTheMonth() is None  # absent part → None, never []
    assert rule.setPositions() is None


def test_to_recurrence_rule_plain_weekday_has_ordinal_zero():
    rule = to_recurrence_rule(Recurrence.from_rrule("FREQ=WEEKLY;BYDAY=MO,WE"))
    assert [(d.weekNumber(), d.dayOfTheWeek()) for d in rule.daysOfTheWeek()] == [
        (0, 2),
        (0, 4),
    ]


# --- verify-after-write diff (#49, D-08) canonical recurrence dict -------------------

_KEYS = {
    "freq",
    "interval",
    "byday",
    "bymonthday",
    "bymonth",
    "byyearday",
    "bysetpos",
    "count",
    "until",
}


def test_recurrence_signature_requested():
    assert recurrence_signature(None) is None
    assert recurrence_signature(CLEAR_RECURRENCE) is None  # explicit clear == no rule
    daily = recurrence_signature(Recurrence(frequency="daily"))
    assert set(daily) == _KEYS
    assert daily["freq"] == int(EK.EKRecurrenceFrequencyDaily)
    assert (daily["interval"], daily["count"], daily["until"]) == (1, 0, None)
    weekly = recurrence_signature(Recurrence(frequency="weekly", interval=2, count=10))
    assert (weekly["freq"], weekly["interval"], weekly["count"]) == (
        int(EK.EKRecurrenceFrequencyWeekly),
        2,
        10,
    )


def test_recurrence_signature_byday_sorted_regardless_of_input_order():
    a = recurrence_signature(Recurrence.from_rrule("FREQ=WEEKLY;BYDAY=FR,MO"))
    b = recurrence_signature(Recurrence.from_rrule("FREQ=WEEKLY;BYDAY=MO,FR"))
    assert a == b
    assert a["byday"] == [(0, "FR"), (0, "MO")]


def test_persisted_recurrence_signature_readback():
    assert persisted_recurrence_signature(None) is None
    assert persisted_recurrence_signature([]) is None
    sig = persisted_recurrence_signature(
        [fake_rule(freq=1, interval=2, count=10, byday=[(0, "MO")])]
    )
    assert set(sig) == _KEYS
    assert (sig["freq"], sig["interval"], sig["count"]) == (1, 2, 10)
    assert sig["byday"] == [(0, "MO")]


def test_recurrence_signatures_agree_for_equivalent_rule():
    # the requested and persisted signatures must be equal for an unchanged write, so
    # verify-after-write doesn't false-fail a correct recurrence.
    req = recurrence_signature(Recurrence(frequency="monthly", interval=1))
    assert req == persisted_recurrence_signature([fake_rule(freq=2)])


def test_byday_signatures_agree_between_request_and_a_real_rule_object():
    r = Recurrence.from_rrule("FREQ=MONTHLY;BYDAY=2TU")
    sig = recurrence_signature(r)
    assert sig == persisted_recurrence_signature([to_recurrence_rule(r)])
    assert sig["byday"] == [(2, "TU")]


def test_persisted_signature_sees_a_dropped_byday():
    req = recurrence_signature(Recurrence.from_rrule("FREQ=MONTHLY;BYDAY=2TU"))
    assert req != persisted_recurrence_signature([fake_rule(freq=2)])


def test_until_is_day_granular_and_opt_in():
    r = Recurrence(frequency="monthly", until=datetime(2027, 1, 15, 23, 59, 59))
    assert recurrence_signature(r)["until"] is None  # default: omitted (#49)
    assert recurrence_signature(r, include_until=True)["until"] == "20270115"
    # persisted side: any time that day matches
    late = fake_rule(freq=2, until=datetime(2027, 1, 15, 23, 59))
    early = fake_rule(freq=2, until=datetime(2027, 1, 15, 0, 0))
    want = recurrence_signature(r, include_until=True)
    assert persisted_recurrence_signature([late], include_until=True) == want
    assert persisted_recurrence_signature([early], include_until=True) == want
    assert persisted_recurrence_signature([late])["until"] is None


def test_rrule_text_renders_freq_interval_count():
    rule = fake_rule(freq=1, interval=2, count=10)
    assert rrule_text(rule) == "FREQ=WEEKLY;INTERVAL=2;COUNT=10"


def test_rrule_text_omits_count_when_open_ended():
    assert rrule_text(fake_rule(freq=0)) == "FREQ=DAILY;INTERVAL=1"


# The spike 003 matrix (22 shapes, 21 exact on device); BYWEEKNO is refused, so the
# accepted set is the other 21. Each must survive the value-object round trip.
_SPIKE_RRULES = [
    "FREQ=WEEKLY;BYDAY=MO,WE,FR",
    "FREQ=WEEKLY;INTERVAL=2;BYDAY=TU,TH",
    "FREQ=WEEKLY;BYDAY=MO,WE;COUNT=5",
    "FREQ=MONTHLY;BYDAY=2TU",
    "FREQ=MONTHLY;BYDAY=-1FR",
    "FREQ=MONTHLY;BYDAY=5FR",
    "FREQ=MONTHLY;BYDAY=MO",
    "FREQ=MONTHLY;BYMONTHDAY=15",
    "FREQ=MONTHLY;BYMONTHDAY=1,15",
    "FREQ=MONTHLY;BYMONTHDAY=-1",
    "FREQ=MONTHLY;BYMONTHDAY=31",
    "FREQ=MONTHLY;BYMONTHDAY=29",
    "FREQ=MONTHLY;BYMONTHDAY=15;UNTIL=20270115T235959",
    "FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1",
    "FREQ=MONTHLY;BYMONTH=1,4,7,10;BYMONTHDAY=1",
    "FREQ=DAILY;BYMONTH=12",
    "FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU",
    "FREQ=YEARLY;BYMONTH=1,7;BYMONTHDAY=1",
    "FREQ=YEARLY;BYYEARDAY=100",
    "FREQ=YEARLY;BYMONTH=11;BYDAY=TH;BYSETPOS=4",
]


@pytest.mark.parametrize("rrule", _SPIKE_RRULES)
def test_rrule_spike_shape_round_trips_through_a_real_rule_object(rrule):
    r = Recurrence.from_rrule(rrule)
    persisted = persisted_recurrence_signature(
        [to_recurrence_rule(r)], include_until=True
    )
    assert persisted == recurrence_signature(r, include_until=True)


def test_rrule_text_renders_byday_with_an_ordinal():
    rule = fake_rule(freq=2, byday=[(2, "TU")], count=6)
    assert rrule_text(rule) == "FREQ=MONTHLY;INTERVAL=1;BYDAY=2TU;COUNT=6"


def test_rrule_text_renders_a_plain_weekday_without_zero():
    rule = fake_rule(freq=1, byday=[(0, "MO"), (0, "WE")])
    assert rrule_text(rule) == "FREQ=WEEKLY;INTERVAL=1;BYDAY=MO,WE"


def test_rrule_text_orders_every_part_then_ends_with_until():
    rule = fake_rule(
        freq=3,
        byday=[(-1, "FR")],
        bymonthday=[1, 15],
        bymonth=[3],
        byyearday=[100],
        bysetpos=[-1],
        until=datetime(2027, 1, 15, 23, 59, 59),
    )
    assert rrule_text(rule) == (
        "FREQ=YEARLY;INTERVAL=1;BYDAY=-1FR;BYMONTHDAY=1,15;BYMONTH=3;"
        "BYYEARDAY=100;BYSETPOS=-1;UNTIL=20270115"
    )


@pytest.mark.parametrize("rrule", _SPIKE_RRULES)
def test_rrule_text_reparses_to_the_persisted_rule(rrule):
    # the RecurrenceRequired re-send text must carry the whole rule (D-11)
    rule = to_recurrence_rule(Recurrence.from_rrule(rrule))
    again = Recurrence.from_rrule(rrule_text(rule))
    assert recurrence_signature(again, include_until=True) == (
        persisted_recurrence_signature([rule], include_until=True)
    )


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
