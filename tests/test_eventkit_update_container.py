"""#572: an update without ``calendar`` / ``list_name`` keeps the item where it is.

The real ``_apply_event`` / ``_apply_reminder`` and verify run against a stateful
fake item, so the container the save sees is the one the setters left."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import macos_apps_mcp.adapters.calendar as cal
import macos_apps_mcp.adapters.reminders as rem
from macos_apps_mcp.contracts import CalendarEventData, ReminderData
from tests.test_calendar import _fake_store as _fake_calendar_store
from tests.test_reminders import _fake_store as _fake_list_store


class _Item:
    """An EKEvent / EKReminder stand-in: ``setX_(v)`` stores ``x``, ``x()`` reads it,
    and every setter call is recorded in ``calls``."""

    def __init__(self, reminder=False, **state):
        self.calls = []
        self.state = {
            "calendarItemIdentifier": "I-1",
            "recurrenceRules": None,
            "alarms": None,
            **state,
        }
        if reminder:
            self.state["isCompleted"] = False

    def __getattr__(self, name):
        if name.startswith("set") and name.endswith("_"):
            key = name[3].lower() + name[4:-1]

            def setter(v):
                self.calls.append(key)
                self.state[key] = v

            return setter
        if name == "isAllDay":  # setAllDay_ stores "allDay"
            return lambda: self.state.get("allDay", False)
        if name in self.state:
            return lambda: self.state[name]
        raise AttributeError(name)


def _event_world(monkeypatch, item, store):
    store.saveEvent_span_commit_error_ = lambda *a: (True, None)
    monkeypatch.setattr(cal, "run_native", lambda fn: fn())
    monkeypatch.setattr(cal, "store", lambda: store)
    monkeypatch.setattr(
        cal.EK, "EKEvent", SimpleNamespace(eventWithEventStore_=lambda _s: item)
    )
    monkeypatch.setattr(cal, "_resolve_event", lambda _s, _i: item)
    monkeypatch.setattr(cal, "_refetch_event", lambda _s, _i: item)
    return cal.CalendarAdapter()


def _reminder_world(monkeypatch, item, store):
    store.saveReminder_commit_error_ = lambda *a: (True, None)
    store.calendarItemWithIdentifier_ = lambda _i: item
    item.state["refresh"] = True
    monkeypatch.setattr(rem, "run_native", lambda fn: fn())
    monkeypatch.setattr(rem, "store", lambda: store)
    monkeypatch.setattr(
        rem.EK, "EKReminder", SimpleNamespace(reminderWithEventStore_=lambda _s: item)
    )
    return rem.RemindersAdapter()


def _cal_store():
    """Calendars C0 "Home" (the default) and C1 "Work"."""
    s = _fake_calendar_store(["Home", "Work"])
    home = s.calendarsForEntityType_(None)[0]
    s.defaultCalendarForNewEvents = lambda: home
    return s


def _list_store():
    """Lists L0 "Inbox" (the default) and L1 "Work"."""
    s = _fake_list_store(["Inbox", "Work"])
    inbox = s.calendarsForEntityType_(None)[0]
    s.defaultCalendarForNewReminders = lambda: inbox
    return s


_START, _END = datetime(2026, 6, 24, 9, 0), datetime(2026, 6, 24, 9, 30)


def _event_data(**kw):
    return CalendarEventData(title="Standup", start=_START, end=_END, **kw)


# --- events ------------------------------------------------------------------------


def test_update_event_without_calendar_keeps_a_non_default_calendar(monkeypatch):
    s = _cal_store()
    work = s.calendarsForEntityType_(None)[1]
    item = _Item(calendar=work, notes="agenda")
    p = _event_world(monkeypatch, item, s).update_event("I-1|1", _event_data())
    assert item.state["calendar"] is work
    assert "calendar" not in item.calls
    assert p.folder == "C1"


def test_update_event_with_calendar_moves_it(monkeypatch):
    s = _cal_store()
    item = _Item(calendar=s.calendarsForEntityType_(None)[0])
    p = _event_world(monkeypatch, item, s).update_event(
        "I-1|1", _event_data(calendar="Work")
    )
    assert p.folder == "C1"


def test_create_event_without_calendar_uses_the_default(monkeypatch):
    s = _cal_store()
    item = _Item(calendar=None)  # a fresh EKEvent has no calendar yet
    p = _event_world(monkeypatch, item, s).create_event(_event_data())
    assert p.folder == "C0"


def test_update_event_omitted_notes_still_clears(monkeypatch):
    s = _cal_store()
    item = _Item(calendar=s.calendarsForEntityType_(None)[1], notes="agenda")
    _event_world(monkeypatch, item, s).update_event("I-1|1", _event_data())
    assert item.state["notes"] is None  # full replace stays for every other field


# --- reminders ---------------------------------------------------------------------


def test_update_reminder_without_list_keeps_a_non_default_list(monkeypatch):
    s = _list_store()
    work = s.calendarsForEntityType_(None)[1]
    item = _Item(reminder=True, calendar=work)
    p = _reminder_world(monkeypatch, item, s).update_reminder(
        "I-1", ReminderData(title="Pay rent")
    )
    assert item.state["calendar"] is work
    assert "calendar" not in item.calls
    assert p.folder == "L1"


def test_update_reminder_with_list_moves_it(monkeypatch):
    s = _list_store()
    item = _Item(reminder=True, calendar=s.calendarsForEntityType_(None)[0])
    p = _reminder_world(monkeypatch, item, s).update_reminder(
        "I-1", ReminderData(title="Pay rent", list_name="L1")
    )
    assert p.folder == "L1"


def test_create_reminder_without_list_uses_the_default(monkeypatch):
    s = _list_store()
    item = _Item(reminder=True, calendar=None)
    p = _reminder_world(monkeypatch, item, s).create_reminder(
        ReminderData(title="Pay rent")
    )
    assert p.folder == "L0"


def test_update_reminder_omitted_notes_still_clears(monkeypatch):
    s = _list_store()
    item = _Item(reminder=True, calendar=s.calendarsForEntityType_(None)[1])
    item.state["notes"] = "landlord IBAN"
    _reminder_world(monkeypatch, item, s).update_reminder(
        "I-1", ReminderData(title="Pay rent")
    )
    assert item.state["notes"] is None
