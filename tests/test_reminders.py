"""Unit tests for the reminders adapter — pure mapping only (fakes, no EventKit)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from mac_mcp.adapters.reminders import (
    _due_tuple,
    _expected_due_tuple,
    _reminder_deeplink,
    _reminder_pointer,
    _reminder_summary,
    _resolve_list,
    _verify_completed,
    _verify_reminder,
)
from mac_mcp.contracts import Pointer, Recurrence, ReminderData
from mac_mcp.runtime import VerificationFailed
from tests._fakes import fake_rule


def _fake_reminder(title, ident, due=None):
    due_comps = None
    if due is not None:
        y, m, d = due
        due_comps = SimpleNamespace(year=lambda: y, month=lambda: m, day=lambda: d)
    return SimpleNamespace(
        title=lambda: title,
        calendarItemIdentifier=lambda: ident,
        dueDateComponents=lambda: due_comps,
    )


def test_summary_with_due():
    item = _fake_reminder("Call dentist", "R-1", due=(2026, 6, 23))
    assert _reminder_summary(item) == "Call dentist — due 2026-06-23"


def test_summary_without_due():
    assert _reminder_summary(_fake_reminder("Buy milk", "R-2")) == "Buy milk"


def test_deeplink_format():
    assert _reminder_deeplink("R-1") == "x-apple-reminderkit://REMCDReminder/R-1"


def test_pointer_shape():
    p = _reminder_pointer(_fake_reminder("Call dentist", "R-1", due=(2026, 6, 23)))
    assert isinstance(p, Pointer)
    assert (
        p.id == "R-1"
        and p.summary.startswith("Call dentist")
        and p.deeplink.endswith("/R-1")
    )


def _fake_store(list_names, default="Inbox"):
    cals = [SimpleNamespace(title=lambda n=n: n) for n in list_names]
    return SimpleNamespace(
        calendarsForEntityType_=lambda _e: cals,
        defaultCalendarForNewReminders=lambda: SimpleNamespace(title=lambda: default),
    )


def test_resolve_named_list():
    s = _fake_store(["Work", "Home"])
    assert _resolve_list(s, "Home").title() == "Home"


def test_resolve_default_when_none():
    s = _fake_store(["Work"])
    assert _resolve_list(s, None).title() == "Inbox"


def test_resolve_missing_list_raises():
    s = _fake_store(["Work"])
    with pytest.raises(ValueError, match="no reminder list"):
        _resolve_list(s, "Nope")


# --- verify-after-write (#49) --------------------------------------------------------


def _comps(y, m, d, h, mi):
    return SimpleNamespace(
        year=lambda: y,
        month=lambda: m,
        day=lambda: d,
        hour=lambda: h,
        minute=lambda: mi,
    )


def _fake_persisted(
    title="Pay rent",
    notes=None,
    priority=0,
    due=None,
    list_title="Home",
    rule=None,
    completed=False,
):
    return SimpleNamespace(
        title=lambda: title,
        notes=lambda: notes,
        priority=lambda: priority,
        dueDateComponents=lambda: due,
        startDateComponents=lambda: None,
        calendar=lambda: SimpleNamespace(title=lambda: list_title),
        recurrenceRules=lambda: [rule] if rule is not None else None,
        isCompleted=lambda: completed,
    )


def test_due_tuple_roundtrip():
    assert _due_tuple(_comps(2026, 6, 25, 9, 30)) == (2026, 6, 25, 9, 30)
    assert _due_tuple(None) is None
    assert _expected_due_tuple(datetime(2026, 6, 25, 9, 30)) == (2026, 6, 25, 9, 30)
    assert _expected_due_tuple(None) is None


def test_verify_reminder_passes_on_full_match():
    data = ReminderData(
        title="Pay rent", due=datetime(2026, 6, 25, 9, 0), list_name="Home", priority=1
    )
    fresh = _fake_persisted(
        title="Pay rent", priority=1, due=_comps(2026, 6, 25, 9, 0), list_title="Home"
    )
    _verify_reminder(fresh, "R-1", data, "Home")  # no raise


def test_verify_reminder_none_fresh_is_rollback():
    data = ReminderData(title="x")
    with pytest.raises(VerificationFailed, match="could not be re-fetched"):
        _verify_reminder(None, "R-1", data, "Home")


def test_verify_reminder_dropped_due_raises():
    data = ReminderData(title="Pay rent", due=datetime(2026, 6, 25, 9, 0))
    fresh = _fake_persisted(title="Pay rent", due=None, list_title="Inbox")
    with pytest.raises(VerificationFailed, match="due"):
        _verify_reminder(fresh, "R-1", data, "Inbox")


def test_verify_reminder_wrong_list_raises():
    data = ReminderData(title="Pay rent", list_name="Home")
    fresh = _fake_persisted(
        title="Pay rent", list_title="Inbox"
    )  # landed in wrong list
    with pytest.raises(VerificationFailed, match="list"):
        _verify_reminder(fresh, "R-1", data, "Home")


def test_verify_reminder_dropped_recurrence_raises():
    data = ReminderData(
        title="Water plants",
        due=datetime(2026, 6, 25, 9, 0),
        recurrence=Recurrence(frequency="daily"),
    )
    fresh = _fake_persisted(  # rule=None → the series rule was dropped
        title="Water plants", due=_comps(2026, 6, 25, 9, 0)
    )
    with pytest.raises(VerificationFailed, match="recurs"):
        _verify_reminder(fresh, "R-1", data, "Home")


def test_verify_reminder_wrong_frequency_raises():
    # presence-only was insufficient (#49 review): a non-empty rule with the WRONG
    # cadence must still fail loudly.
    data = ReminderData(
        title="Water plants",
        due=datetime(2026, 6, 25, 9, 0),
        recurrence=Recurrence(frequency="weekly", interval=2),
    )
    fresh = _fake_persisted(
        title="Water plants",
        due=_comps(2026, 6, 25, 9, 0),
        rule=fake_rule(freq=0, interval=2),  # persisted DAILY, not weekly
    )
    with pytest.raises(VerificationFailed, match="recurs"):
        _verify_reminder(fresh, "R-1", data, "Home")


def test_verify_reminder_matching_recurrence_passes():
    data = ReminderData(
        title="Water plants",
        due=datetime(2026, 6, 25, 9, 0),
        recurrence=Recurrence(frequency="weekly", interval=2, count=10),
    )
    fresh = _fake_persisted(
        title="Water plants",
        due=_comps(2026, 6, 25, 9, 0),
        rule=fake_rule(freq=1, interval=2, count=10),  # weekly/2/10 — exact match
    )
    _verify_reminder(fresh, "R-1", data, "Home")  # no raise


def test_verify_reminder_nfd_title_matches_nfc_persisted():
    # Cocoa normalizes to NFC on store — a byte-exact diff would false-fail a
    # correct write (#49).
    data = ReminderData(title="Cafe\u0301 run")  # NFD: e + combining acute
    fresh = _fake_persisted(title="Caf\u00e9 run")  # persisted as NFC
    _verify_reminder(fresh, "R-1", data, "Home")  # no raise


def test_verify_reminder_crlf_notes_match_lf_persisted():
    data = ReminderData(title="Pay rent", notes="first\r\nsecond")
    fresh = _fake_persisted(notes="first\nsecond")  # store folded CRLF → LF
    _verify_reminder(fresh, "R-1", data, "Home")  # no raise


def test_verify_reminder_changed_notes_raises():
    # normalization must not swallow a genuinely different value
    data = ReminderData(title="Pay rent", notes="pay by the 1st")
    fresh = _fake_persisted(notes="pay by the 5th")
    with pytest.raises(VerificationFailed, match="notes"):
        _verify_reminder(fresh, "R-1", data, "Home")


def test_verify_reminder_dropped_notes_raises():
    data = ReminderData(title="Pay rent", notes="pay by the 1st")
    fresh = _fake_persisted(notes=None)
    with pytest.raises(VerificationFailed, match="notes"):
        _verify_reminder(fresh, "R-1", data, "Home")


def test_verify_completed_passes_when_completed():
    _verify_completed(_fake_persisted(completed=True), "R-1")  # no raise


def test_verify_completed_raises_when_not_completed():
    with pytest.raises(VerificationFailed, match="did not persist as completed"):
        _verify_completed(_fake_persisted(completed=False), "R-1")


def test_verify_completed_none_fresh_raises():
    with pytest.raises(VerificationFailed, match="could not be re-fetched"):
        _verify_completed(None, "R-1")
