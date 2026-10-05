"""Phase 3 device tests — REAL EventKit on this Mac (containers, list create, ...).

Run manually, never in CI (no macOS / TCC there):

    uv run pytest -m integration tests/integration/test_eventkit_depth.py

Every item is titled with ``macos-apps-mcp-test:`` plus a per-run stamp (``PREFIX``)
and removed in teardown. Google variants (added in 03-04) need
``MACOS_APPS_IT_GOOGLE_CALENDAR_ID``. Later Phase 3 plans (03-03..03-07) extend this
module with their own device tests.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from types import SimpleNamespace

import EventKit as EK
import pytest

from macos_apps_mcp.adapters.calendar import CalendarAdapter
from macos_apps_mcp.adapters.reminders import RemindersAdapter
from macos_apps_mcp.contracts import CalendarEventData, ReminderData
from macos_apps_mcp.eventkit import store
from macos_apps_mcp.runtime import run_native

# Every test in this module touches real EventKit/TCC — mark them all at module level
# so a forgotten per-test decorator can never leak a live test into CI.
pytestmark = pytest.mark.integration

PREFIX = f"macos-apps-mcp-test: {time.strftime('%H%M%S')} "


@pytest.fixture
def ek_items():
    """Ids a test creates: reminders, reminder lists (calendar identifiers) and events
    (base ids). Teardown removes them all in one worker block, then proves no list
    carrying ``PREFIX`` survives."""
    items = SimpleNamespace(reminders=[], lists=[], events=[])
    yield items

    def _cleanup():
        s = store()
        for ident in items.reminders:
            r = s.calendarItemWithIdentifier_(ident)
            if r is not None:
                s.removeReminder_commit_error_(r, True, None)
        for ident in items.events:
            e = s.calendarItemWithIdentifier_(ident.rpartition("|")[0] or ident)
            if e is not None:
                s.removeEvent_span_commit_error_(e, EK.EKSpanFutureEvents, True, None)
        by_id = {
            c.calendarIdentifier(): c
            for c in s.calendarsForEntityType_(EK.EKEntityTypeReminder)
        }
        for ident in items.lists:
            if ident in by_id:
                s.removeCalendar_commit_error_(by_id[ident], True, None)
        return [
            c.title()
            for c in s.calendarsForEntityType_(EK.EKEntityTypeReminder)
            if c.title().startswith(PREFIX)
        ]

    assert run_native(_cleanup) == [], "test reminder lists left behind"


@pytest.fixture
def icloud_scratch():
    """An event calendar ``PREFIX + "scratch"`` on the source titled "iCloud" (the spike
    003 ``scratch_calendar`` shape). Yields its identifier; removed in teardown."""

    def _make():
        s = store()
        src = next(
            (
                x
                for x in s.sources()
                if x.title() == "iCloud"
                and x.calendarsForEntityType_(EK.EKEntityTypeEvent)
            ),
            None,
        )
        if src is None:
            return None
        cal = EK.EKCalendar.calendarForEntityType_eventStore_(EK.EKEntityTypeEvent, s)
        cal.setTitle_(PREFIX + "scratch")
        cal.setSource_(src)
        ok, err = s.saveCalendar_commit_error_(cal, True, None)
        assert ok, f"cannot create a scratch calendar on iCloud: {err}"
        return cal.calendarIdentifier()

    ident = run_native(_make)
    if ident is None:
        pytest.fail("no EventKit source titled 'iCloud' on this Mac — cannot run")
    yield ident

    def _remove():
        s = store()
        for c in s.calendarsForEntityType_(EK.EKEntityTypeEvent):
            if c.calendarIdentifier() == ident:
                s.removeCalendar_commit_error_(c, True, None)
        return [
            c.calendarIdentifier()
            for c in s.calendarsForEntityType_(EK.EKEntityTypeEvent)
        ]

    assert ident not in run_native(_remove), "scratch calendar left behind"


def test_create_reminder_list_on_default_source(ek_items):
    rem = RemindersAdapter()
    name = PREFIX + "list"
    pointer = rem.create_reminder_list(name)
    ek_items.lists.append(pointer.id)
    assert pointer.id in [p.id for p in rem.get_lists()]
    with pytest.raises(ValueError):  # an exact duplicate is refused
        rem.create_reminder_list(name)

    made = rem.create_reminder(ReminderData(title=PREFIX + "r", list_name=pointer.id))
    ek_items.reminders.append(made.id)
    found = rem.get_pointers(name)
    assert [p.id for p in found] == [made.id]
    assert found[0].folder == pointer.id


def test_event_pointer_folder_is_its_calendar_id(icloud_scratch, ek_items):
    cal = CalendarAdapter()
    day = (datetime.now() + timedelta(days=2)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    made = cal.create_event(
        CalendarEventData(
            title=PREFIX + "event",
            start=day.replace(hour=10),
            end=day.replace(hour=11),
            calendar=icloud_scratch,
        )
    )
    ek_items.events.append(made.id)

    found = {p.id: p for p in cal.get_pointers(day.date().isoformat())}
    folder = found[made.id].folder
    assert folder == icloud_scratch
    assert folder in [p.id for p in cal.get_calendars()]

    window = cal.get_free_busy(
        day.replace(hour=9).isoformat(),
        day.replace(hour=12).isoformat(),
        calendars=[folder],
    )
    assert len(window["busy"]) == 1
