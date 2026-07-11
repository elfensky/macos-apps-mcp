"""Integration tests — REAL EventKit on this Mac. Run with: uv run pytest -m integration

Never run in CI (no macOS / TCC there). Grant Calendar + Reminders access when first
prompted. Tests create items in the DEFAULT list/calendar with an 'mac-mcp-test:'
title prefix and remove everything they create in teardown.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

import EventKit as EK
import pytest

from mac_mcp.runtime import request_access, run_native, store

TITLE_PREFIX = "mac-mcp-test:"


@pytest.fixture
def created():
    """Track (kind, id) of items a test creates; remove them all afterward."""
    items: list[tuple[str, str]] = []
    yield items

    def _cleanup():
        s = store()
        for kind, ident in items:
            base = (
                ident.rpartition("|")[0] or ident
            )  # event ids carry an occurrence suffix
            obj = s.calendarItemWithIdentifier_(base)
            if obj is None:
                continue
            if kind == "event":
                # FutureEvents removes a recurring series whole, not one occurrence
                s.removeEvent_span_commit_error_(obj, EK.EKSpanFutureEvents, True, None)
            else:
                s.removeReminder_commit_error_(obj, True, None)

    run_native(_cleanup)


@pytest.mark.integration
def test_request_access_grants_full():
    run_native(
        request_access
    )  # raises AccessDenied if not granted — grant when prompted


@pytest.mark.integration
def test_reminders_read_today():
    from mac_mcp.adapters.reminders import RemindersAdapter

    run_native(request_access)
    ptrs = RemindersAdapter().get_pointers("today")
    assert isinstance(ptrs, list)
    for p in ptrs:
        assert p.id and p.summary and p.deeplink.startswith("x-apple-reminderkit://")


@pytest.mark.integration
def test_calendar_read_week():
    from mac_mcp.adapters.calendar import CalendarAdapter

    run_native(request_access)
    ptrs = CalendarAdapter().get_pointers("week")
    assert isinstance(ptrs, list)
    for p in ptrs:
        assert p.id and p.summary and p.deeplink.startswith("calshow:")


@pytest.mark.integration
def test_reminder_create_update_complete(created):
    from datetime import datetime, timedelta

    from mac_mcp.adapters.reminders import RemindersAdapter
    from mac_mcp.contracts import ReminderData

    run_native(request_access)
    a = RemindersAdapter()

    due = datetime.now().replace(microsecond=0) + timedelta(days=1)
    p = a.create_reminder(ReminderData(title=f"{TITLE_PREFIX} v1 round-trip", due=due))
    created.append(("reminder", p.id))
    assert p.id
    assert "due" in p.summary  # created with a due date

    p2 = a.update_reminder(
        p.id, ReminderData(title=f"{TITLE_PREFIX} v1 round-trip (edited)")
    )  # due=None → cleared
    assert p2.id == p.id
    assert "edited" in p2.summary
    assert "due" not in p2.summary  # full-replace cleared the due date

    p3 = a.complete_reminder(p.id)
    assert p3.id == p.id


@pytest.mark.integration
def test_event_create_update_delete(created):
    from datetime import datetime, timedelta

    from mac_mcp.adapters.calendar import CalendarAdapter
    from mac_mcp.contracts import CalendarEventData

    run_native(request_access)
    a = CalendarAdapter()
    start = datetime.now().replace(microsecond=0) + timedelta(days=1)

    p = a.create_event(
        CalendarEventData(
            title=f"{TITLE_PREFIX} v1 event",
            start=start,
            end=start + timedelta(hours=1),
        )
    )
    created.append(("event", p.id))
    assert p.id

    p2 = a.update_event(
        p.id,
        CalendarEventData(
            title=f"{TITLE_PREFIX} v1 event (moved)",
            start=start + timedelta(hours=2),
            end=start + timedelta(hours=3),
        ),
    )
    # moving the event changes the occurrence-id suffix; the base id is unchanged
    assert p2.id.split("|")[0] == p.id.split("|")[0] and "moved" in p2.summary

    a.delete_event(
        p2.id
    )  # delete by the post-move id; teardown is a no-op for an already-deleted id


@pytest.mark.integration
def test_all_day_event_round_trips_date(created):
    """#50: an all-day event created from a date-only local date reads back on the SAME
    calendar day — never shifted a day by the UTC offset."""
    from datetime import datetime, timedelta

    from mac_mcp.adapters.calendar import CalendarAdapter
    from mac_mcp.contracts import CalendarEventData, parse_datetime

    run_native(request_access)
    a = CalendarAdapter()
    day = (datetime.now() + timedelta(days=2)).date()
    start = parse_datetime(day.isoformat())  # date-only → local midnight, naive

    p = a.create_event(  # verify-after-write (#49) already asserts the start date here
        CalendarEventData(
            title=f"{TITLE_PREFIX} all-day", start=start, end=start, all_day=True
        )
    )
    created.append(("event", p.id))

    # read that calendar day back — the event must appear on it, not day ±1
    same_day = a.get_pointers(day.isoformat())
    assert any(q.id.split("|")[0] == p.id.split("|")[0] for q in same_day)


@pytest.mark.integration
def test_named_list_read_excludes_completed(created):
    """Parity row 4: a named-list read returns only incomplete reminders.

    Mocked-store unit tests can't catch this — it takes a real list with a completed
    item to see the leak. Guards the fix routing the named-list path through the
    incomplete-only selector.
    """
    from mac_mcp.adapters.reminders import RemindersAdapter
    from mac_mcp.contracts import ReminderData

    run_native(request_access)
    a = RemindersAdapter()
    list_name = run_native(lambda: store().defaultCalendarForNewReminders().title())

    open_item = a.create_reminder(
        ReminderData(title=f"{TITLE_PREFIX} open", list_name=list_name)
    )
    created.append(("reminder", open_item.id))
    done_item = a.create_reminder(
        ReminderData(title=f"{TITLE_PREFIX} done", list_name=list_name)
    )
    created.append(("reminder", done_item.id))
    a.complete_reminder(done_item.id)

    ids = [p.id for p in a.get_pointers(list_name)]
    assert open_item.id in ids  # incomplete item is returned
    assert done_item.id not in ids  # completed item is filtered out (the row-4 fix)


@pytest.mark.integration
def test_reminder_lists_enumerate():
    """Parity row 8: enumerate lists; the default list is discoverable by name."""
    from mac_mcp.adapters.reminders import RemindersAdapter

    run_native(request_access)
    ptrs = RemindersAdapter().get_lists()
    assert ptrs and all(p.id and p.summary for p in ptrs)
    default_name = run_native(lambda: store().defaultCalendarForNewReminders().title())
    assert default_name in [p.summary for p in ptrs]


@pytest.mark.integration
def test_calendars_enumerate():
    """Parity row 9: enumerate calendars; the default is discoverable by name."""
    from mac_mcp.adapters.calendar import CalendarAdapter

    run_native(request_access)
    ptrs = CalendarAdapter().get_calendars()
    assert ptrs and all(p.id and p.summary for p in ptrs)
    default_name = run_native(lambda: store().defaultCalendarForNewEvents().title())
    assert default_name in [p.summary for p in ptrs]


@pytest.mark.integration
def test_recurring_event_update_targets_one_occurrence(created):
    """#8: editing by an occurrence's pointer id changes only THAT occurrence.

    The bug a mocked store can't catch: all occurrences share one
    calendarItemIdentifier, so the old calendarItemWithIdentifier_ path edited the
    series master. Create a 3-day daily series, edit the middle occurrence by its
    pointer id, assert days 0 and 2 are untouched.
    """
    from datetime import datetime, timedelta

    from mac_mcp.adapters.calendar import CalendarAdapter
    from mac_mcp.contracts import CalendarEventData
    from mac_mcp.runtime import to_nsdate

    run_native(request_access)
    a = CalendarAdapter()
    days = [
        (datetime.now() + timedelta(days=2)).replace(
            hour=9, minute=0, second=0, microsecond=0
        )
        + timedelta(days=d)
        for d in range(3)
    ]

    def _make_series():
        s = store()
        e = EK.EKEvent.eventWithEventStore_(s)
        e.setTitle_(f"{TITLE_PREFIX} recurring")
        e.setStartDate_(to_nsdate(days[0]))
        e.setEndDate_(to_nsdate(days[0] + timedelta(hours=1)))
        e.setCalendar_(s.defaultCalendarForNewEvents())
        end = EK.EKRecurrenceEnd.recurrenceEndWithEndDate_(
            to_nsdate(days[2] + timedelta(hours=2))
        )
        rule = EK.EKRecurrenceRule.alloc().initRecurrenceWithFrequency_interval_end_(
            EK.EKRecurrenceFrequencyDaily, 1, end
        )
        e.setRecurrenceRules_([rule])
        ok, err = s.saveEvent_span_commit_error_(e, EK.EKSpanFutureEvents, True, None)
        if not ok:
            raise RuntimeError(f"create recurring failed: {err}")
        return e.calendarItemIdentifier()

    created.append(("event", run_native(_make_series)))

    def titles_on(day):
        return [
            p.summary
            for p in a.get_pointers(day.strftime("%Y-%m-%d"))
            if "recurring" in p.summary
        ]

    mid = [
        p
        for p in a.get_pointers(days[1].strftime("%Y-%m-%d"))
        if "recurring" in p.summary
    ]
    assert len(mid) == 1  # one occurrence on the middle day

    p = a.update_event(
        mid[0].id,
        CalendarEventData(
            title=f"{TITLE_PREFIX} recurring EDITED",
            start=days[1],
            end=days[1] + timedelta(hours=1),
        ),
        span="this-event",  # #51: edit only THIS occurrence
    )
    # a this-event edit detaches the occurrence into its own item, which may carry its
    # own base id — track the returned pointer so teardown removes it too (leak fix)
    created.append(("event", p.id.split("|")[0]))

    assert any("EDITED" in t for t in titles_on(days[1]))  # middle occurrence changed
    assert all("EDITED" not in t for t in titles_on(days[0]))  # day 0 untouched
    assert all("EDITED" not in t for t in titles_on(days[2]))  # day 2 untouched


@pytest.mark.integration
def test_recurring_update_omitted_span_raises_and_does_not_write(created):
    """#51: an update to a recurring occurrence with NO span must raise SpanRequired and
    leave the series untouched (no silent whole-series rewrite)."""
    from datetime import datetime, timedelta

    from mac_mcp.adapters.calendar import CalendarAdapter
    from mac_mcp.contracts import CalendarEventData
    from mac_mcp.runtime import SpanRequired, to_nsdate

    run_native(request_access)
    a = CalendarAdapter()
    day0 = (datetime.now() + timedelta(days=2)).replace(
        hour=9, minute=0, second=0, microsecond=0
    )

    def _make_series():
        s = store()
        e = EK.EKEvent.eventWithEventStore_(s)
        e.setTitle_(f"{TITLE_PREFIX} span-guard")
        e.setStartDate_(to_nsdate(day0))
        e.setEndDate_(to_nsdate(day0 + timedelta(hours=1)))
        e.setCalendar_(s.defaultCalendarForNewEvents())
        end = EK.EKRecurrenceEnd.recurrenceEndWithEndDate_(
            to_nsdate(day0 + timedelta(days=2, hours=2))
        )
        rule = EK.EKRecurrenceRule.alloc().initRecurrenceWithFrequency_interval_end_(
            EK.EKRecurrenceFrequencyDaily, 1, end
        )
        e.setRecurrenceRules_([rule])
        ok, err = s.saveEvent_span_commit_error_(e, EK.EKSpanFutureEvents, True, None)
        if not ok:
            raise RuntimeError(f"create recurring failed: {err}")
        return e.calendarItemIdentifier()

    created.append(("event", run_native(_make_series)))

    occ = [
        p
        for p in a.get_pointers(day0.strftime("%Y-%m-%d"))
        if "span-guard" in p.summary
    ]
    assert len(occ) == 1

    with pytest.raises(SpanRequired, match="recurring event"):
        a.update_event(
            occ[0].id,
            CalendarEventData(
                title=f"{TITLE_PREFIX} span-guard SHOULD-NOT-STICK",
                start=day0,
                end=day0 + timedelta(hours=1),
            ),
        )  # no span → must raise, no write
    # the title never changed — the write was refused, not silently applied
    still = [
        p.summary
        for p in a.get_pointers(day0.strftime("%Y-%m-%d"))
        if "span-guard" in p.summary
    ]
    assert still and all("SHOULD-NOT-STICK" not in t for t in still)


@pytest.mark.integration
def test_recurring_update_future_events_propagates(created):
    """#51: span='future-events' edits this occurrence AND all later ones, leaving
    earlier occurrences untouched."""
    from datetime import datetime, timedelta

    from mac_mcp.adapters.calendar import CalendarAdapter
    from mac_mcp.contracts import CalendarEventData
    from mac_mcp.runtime import to_nsdate

    run_native(request_access)
    a = CalendarAdapter()
    days = [
        (datetime.now() + timedelta(days=2)).replace(
            hour=9, minute=0, second=0, microsecond=0
        )
        + timedelta(days=d)
        for d in range(3)
    ]

    def _make_series():
        s = store()
        e = EK.EKEvent.eventWithEventStore_(s)
        e.setTitle_(f"{TITLE_PREFIX} propagate")
        e.setStartDate_(to_nsdate(days[0]))
        e.setEndDate_(to_nsdate(days[0] + timedelta(hours=1)))
        e.setCalendar_(s.defaultCalendarForNewEvents())
        end = EK.EKRecurrenceEnd.recurrenceEndWithEndDate_(
            to_nsdate(days[2] + timedelta(hours=2))
        )
        rule = EK.EKRecurrenceRule.alloc().initRecurrenceWithFrequency_interval_end_(
            EK.EKRecurrenceFrequencyDaily, 1, end
        )
        e.setRecurrenceRules_([rule])
        ok, err = s.saveEvent_span_commit_error_(e, EK.EKSpanFutureEvents, True, None)
        if not ok:
            raise RuntimeError(f"create recurring failed: {err}")
        return e.calendarItemIdentifier()

    created.append(("event", run_native(_make_series)))

    def titles_on(day):
        return [
            p.summary
            for p in a.get_pointers(day.strftime("%Y-%m-%d"))
            if "propagate" in p.summary
        ]

    mid = [
        p
        for p in a.get_pointers(days[1].strftime("%Y-%m-%d"))
        if "propagate" in p.summary
    ]
    assert len(mid) == 1

    p = a.update_event(
        mid[0].id,
        CalendarEventData(
            title=f"{TITLE_PREFIX} propagate EDITED",
            start=days[1],
            end=days[1] + timedelta(hours=1),
        ),
        span="future-events",  # #51: this occurrence + all later
    )
    # future-events SPLITS the series: this-and-later becomes a NEW series object with
    # its own base id — track it so teardown removes both halves (leak fix)
    created.append(("event", p.id.split("|")[0]))

    assert all("EDITED" not in t for t in titles_on(days[0]))  # earlier untouched
    assert any("EDITED" in t for t in titles_on(days[1]))  # this occurrence
    assert any("EDITED" in t for t in titles_on(days[2]))  # later propagated


@pytest.mark.integration
def test_contacts_create_find_delete():
    """#15: osascript Contacts — create, find by name, delete (Automation TCC)."""
    from mac_mcp.adapters.contacts import ContactsAdapter
    from mac_mcp.contracts import ContactData
    from mac_mcp.runtime import run_osascript

    a = ContactsAdapter()
    p = a.create_contact(
        ContactData(
            given_name="mac-mcp-test",
            family_name="ZZContact",
            organization="mac-mcp",
        )
    )
    try:
        assert p.id and "ZZContact" in p.summary
        assert any(x.id == p.id for x in a.get_pointers("ZZContact"))
    finally:
        run_osascript(
            "on run argv\n"
            '  tell application "Contacts"\n'
            "    delete (first person whose id is (item 1 of argv))\n"
            "    save\n"
            "  end tell\n"
            "end run",
            p.id,
        )


@pytest.mark.integration
def test_mail_search_runs():
    """#18: Mail subject search via osascript runs (Automation TCC)."""
    from mac_mcp.adapters.mail import MailAdapter

    ptrs = MailAdapter().get_pointers("mac-mcp-no-such-subject-zzz")
    assert isinstance(
        ptrs, list
    )  # runs without error (likely empty) — validates the path


@pytest.mark.integration
def test_notes_search_finds_created():
    """#19: Notes title search via osascript finds a created note (Automation TCC)."""
    from mac_mcp.adapters.notes import NotesAdapter
    from mac_mcp.runtime import run_osascript

    marker = "mac-mcp-test-zznote"
    run_osascript(
        "on run argv\n"
        '  tell application "Notes"\n'
        '    make new note with properties {name:(item 1 of argv), body:"x"}\n'
        "  end tell\n"
        "end run",
        marker,
    )
    try:
        assert any(marker in p.summary for p in NotesAdapter().get_pointers(marker))
    finally:
        run_osascript(
            "on run argv\n"
            '  tell application "Notes"\n'
            "    delete (every note whose name is (item 1 of argv))\n"
            "  end tell\n"
            "end run",
            marker,
        )


@pytest.mark.integration
def test_safari_tabs_runs():
    """#22: Safari open-tabs read via osascript runs (Automation TCC)."""
    from mac_mcp.adapters.safari import SafariAdapter

    assert isinstance(SafariAdapter().get_tabs(), list)


@pytest.mark.integration
def test_photos_search_runs():
    """#20: Photos search via osascript runs (Automation TCC)."""
    from mac_mcp.adapters.photos import PhotosAdapter

    assert isinstance(PhotosAdapter().get_pointers("mac-mcp-no-such-photo-zzz"), list)


@pytest.mark.integration
def test_messages_chats_runs():
    """#21: Messages chat list via osascript runs (Automation TCC)."""
    from mac_mcp.adapters.messages import MessagesAdapter

    assert isinstance(MessagesAdapter().get_chats(), list)


@pytest.mark.integration
def test_shortcuts_list_runs():
    """#22: `shortcuts list` CLI enumerates shortcuts (no TCC)."""
    from mac_mcp.adapters.shortcuts import ShortcutsAdapter

    ptrs = ShortcutsAdapter().get_pointers()
    assert isinstance(ptrs, list) and all(p.id and p.summary for p in ptrs)


@pytest.mark.integration
def test_run_shortcut_missing_raises():
    """run_shortcut on an unknown name surfaces a clear RuntimeError."""
    from mac_mcp.adapters.shortcuts import ShortcutsAdapter

    with pytest.raises(RuntimeError, match="shortcuts run"):
        ShortcutsAdapter().run_shortcut("mac-mcp-no-such-shortcut-zzz")


@pytest.mark.integration
def test_safari_open_creates_tab():
    """open_url adds a tab whose URL we can find, then we close it."""
    from mac_mcp.adapters.safari import SafariAdapter
    from mac_mcp.runtime import run_osascript

    url = "https://example.com/mac-mcp-test"
    a = SafariAdapter()
    p = a.open_url(url)
    try:
        assert p.deeplink == url
        assert any(url in t.id for t in a.get_tabs())
    finally:
        run_osascript(
            "on run argv\n"
            '  tell application "Safari"\n'
            "    repeat with w in windows\n"
            "      repeat with t in (tabs of w whose URL contains (item 1 of argv))\n"
            "        close t\n"
            "      end repeat\n"
            "    end repeat\n"
            "  end tell\n"
            "end run",
            url,
        )


@pytest.mark.integration
def test_event_create_all_day(created):
    """all_day=True creates an all-day event (the summary renders it specially)."""
    from datetime import datetime, timedelta

    from mac_mcp.adapters.calendar import CalendarAdapter
    from mac_mcp.contracts import CalendarEventData

    run_native(request_access)
    day = (datetime.now() + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    p = CalendarAdapter().create_event(
        CalendarEventData(
            title=f"{TITLE_PREFIX} all-day",
            start=day,
            end=day + timedelta(days=1),
            all_day=True,
        )
    )
    created.append(("event", p.id))
    assert "all day" in p.summary


@pytest.mark.integration
def test_reminder_create_with_priority(created):
    """priority is written through and reads back off the stored EKReminder."""
    from mac_mcp.adapters.reminders import RemindersAdapter
    from mac_mcp.contracts import ReminderData

    run_native(request_access)
    p = RemindersAdapter().create_reminder(
        ReminderData(title=f"{TITLE_PREFIX} prio", priority=1)
    )
    created.append(("reminder", p.id))
    prio = run_native(lambda: store().calendarItemWithIdentifier_(p.id).priority())
    assert prio == 1


@pytest.mark.integration
def test_event_create_recurring_series(created):
    """create_event with an RRULE makes a real repeating series (span=FutureEvents).

    A daily COUNT=3 series must show exactly one occurrence on each of days 0–2 and
    none on day 3 — proving both the rule mapping and the create-span branch.
    """
    from datetime import datetime, timedelta

    from mac_mcp.adapters.calendar import CalendarAdapter
    from mac_mcp.contracts import CalendarEventData, Recurrence

    run_native(request_access)
    a = CalendarAdapter()
    start = (datetime.now() + timedelta(days=1)).replace(
        hour=9, minute=0, second=0, microsecond=0
    )
    p = a.create_event(
        CalendarEventData(
            title=f"{TITLE_PREFIX} daily series",
            start=start,
            end=start + timedelta(hours=1),
            recurrence=Recurrence.from_rrule("FREQ=DAILY;COUNT=3"),
        )
    )
    created.append(("event", p.id))

    def occ_on(day):
        return [
            x
            for x in a.get_pointers(day.strftime("%Y-%m-%d"))
            if "daily series" in x.summary
        ]

    assert all(len(occ_on(start + timedelta(days=d))) == 1 for d in range(3))
    assert occ_on(start + timedelta(days=3)) == []  # COUNT=3 stops the series


@pytest.mark.integration
def test_reminder_create_recurring(created):
    """A recurring reminder stores a rule (and requires a due date)."""
    from datetime import datetime, timedelta

    from mac_mcp.adapters.reminders import RemindersAdapter
    from mac_mcp.contracts import Recurrence, ReminderData

    run_native(request_access)
    due = (datetime.now() + timedelta(days=1)).replace(microsecond=0)
    p = RemindersAdapter().create_reminder(
        ReminderData(
            title=f"{TITLE_PREFIX} weekly",
            due=due,
            recurrence=Recurrence.from_rrule("FREQ=WEEKLY"),
        )
    )
    created.append(("reminder", p.id))
    rules = run_native(
        lambda: store().calendarItemWithIdentifier_(p.id).recurrenceRules()
    )
    assert rules and len(rules) == 1


@pytest.mark.integration
def test_notes_all_and_bodies_and_delete_roundtrip():
    """Create a note whose body contains newlines, find it via get_all, hydrate its
    body (verifying the embedded newlines survive the control-char framing), then
    delete it with a matching expect_title."""
    from mac_mcp.adapters.notes import NotesAdapter
    from mac_mcp.runtime import run_osascript

    notes = NotesAdapter()
    title = "mac-mcp-itest-note"
    # Notes stores `body` as HTML, so line breaks must be <br> to yield real newlines
    # in plaintext. The newlines are the point: a newline-delimited record format would
    # split on them — the \x1f/\x1e framing must not. (Tabs aren't preserved by Notes
    # plaintext at all, so they're not part of this guard.)
    body_html = "line one<br>line two<br>line three"

    # create a note via osascript (test-only helper; not part of the shipped surface)
    create = (
        "on run argv\n"
        '  tell application "Notes"\n'
        '    make new note at folder "Notes" of account 1 '
        "with properties {name:(item 1 of argv), body:(item 2 of argv)}\n"
        "  end tell\n"
        "end run"
    )
    run_osascript(create, title, body_html)

    try:
        # get_all finds it, with an account-qualified folder
        all_ptrs = notes.get_all()
        mine = [p for p in all_ptrs if p.summary == title]
        assert mine, "created note not returned by get_all"
        ptr = mine[0]
        assert ptr.folder and " / " in ptr.folder  # "Account / Folder"

        # body hydrates with embedded newlines intact (framing didn't split on them)
        bodies = notes.get_bodies([ptr.id])
        assert len(bodies) == 1 and bodies[0]["id"] == ptr.id
        assert "line one\nline two\nline three" in bodies[0]["body"]

        # mismatched expect_title refuses to delete
        with pytest.raises(RuntimeError):
            notes.delete(ptr.id, expect_title="wrong title")
        assert any(p.summary == title for p in notes.get_all())

        # matching expect_title deletes (moves to Recently Deleted)
        notes.delete(ptr.id, expect_title=title)
        assert not any(p.summary == title for p in notes.get_all())
    finally:
        # best-effort cleanup if an assertion left the note behind
        for p in notes.get_all():
            if p.summary == title:
                notes.delete(p.id)


@pytest.mark.integration
def test_event_move_to_other_calendar_reresolves(created):
    """C-IDCHURN (variant c): a cross-calendar move must return the POST-save pointer —
    the store may re-issue the item identifier when an event changes calendars, so the
    returned id (not the pre-move one) is the one that has to resolve. update_event's
    verify-after-write (#49) already asserts the calendar field persisted."""
    from datetime import datetime, timedelta

    from mac_mcp.adapters.calendar import CalendarAdapter
    from mac_mcp.contracts import CalendarEventData

    run_native(request_access)
    a = CalendarAdapter()

    def _writable_titles():
        s = store()
        default = s.defaultCalendarForNewEvents().title()
        others = [
            c.title()
            for c in s.calendarsForEntityType_(EK.EKEntityTypeEvent)
            # writable only: moving INTO a read-only (subscribed) calendar would
            # WriteRefused and fail this test for the wrong reason
            if c.allowsContentModifications() and c.title() != default
        ]
        return others

    others = run_native(_writable_titles)
    if not others:
        pytest.skip("needs a second writable event calendar")
    target = others[0]

    start = datetime.now().replace(microsecond=0) + timedelta(days=1)
    p = a.create_event(  # created in the default calendar
        CalendarEventData(
            title=f"{TITLE_PREFIX} cal-move",
            start=start,
            end=start + timedelta(hours=1),
        )
    )
    created.append(("event", p.id))

    p2 = a.update_event(
        p.id,
        CalendarEventData(
            title=f"{TITLE_PREFIX} cal-move (moved)",
            start=start,
            end=start + timedelta(hours=1),
            calendar=target,
        ),
    )
    created.append(("event", p2.id))  # the move may re-issue the id — track both

    def _resolved_calendar():
        obj = store().calendarItemWithIdentifier_(p2.id.split("|")[0])
        return None if obj is None else str(obj.calendar().title())

    # the returned pointer id resolves, and it lives in the requested calendar
    assert run_native(_resolved_calendar) == target


@pytest.mark.integration
def test_reminder_move_between_lists_reresolves(created):
    """C-REMIDMOVE: moving a reminder to another list must return the POST-save id —
    a list move may re-issue the identifier, so update_reminder re-keys its refetch
    (and the returned pointer) from the held object's post-save id."""
    from mac_mcp.adapters.reminders import RemindersAdapter
    from mac_mcp.contracts import ReminderData

    run_native(request_access)
    a = RemindersAdapter()

    def _writable_titles():
        s = store()
        default = s.defaultCalendarForNewReminders().title()
        others = [
            c.title()
            for c in s.calendarsForEntityType_(EK.EKEntityTypeReminder)
            # writable only: moving INTO a read-only (subscribed) list would
            # WriteRefused and fail this test for the wrong reason
            if c.allowsContentModifications() and c.title() != default
        ]
        return others

    others = run_native(_writable_titles)
    if not others:
        pytest.skip("needs a second writable reminder list")
    target = others[0]

    p = a.create_reminder(  # created in the default list
        ReminderData(title=f"{TITLE_PREFIX} list-move")
    )
    created.append(("reminder", p.id))

    p2 = a.update_reminder(
        p.id,
        ReminderData(title=f"{TITLE_PREFIX} list-move (moved)", list_name=target),
    )
    created.append(("reminder", p2.id))  # the move may re-issue the id — track both

    def _resolved_list():
        obj = store().calendarItemWithIdentifier_(p2.id)
        return None if obj is None else str(obj.calendar().title())

    # the returned pointer id resolves, and it lives in the requested list
    assert run_native(_resolved_list) == target


@pytest.mark.integration
def test_recurring_reminder_update_requires_recurrence(created):
    """User decision 1: updating a repeating reminder with recurrence omitted is
    REFUSED (RecurrenceRequired, rule intact — a rename can't silently kill the
    series); an explicit CLEAR_RECURRENCE ('none' at the tool boundary) clears the
    rule and verifies."""
    from datetime import datetime, timedelta

    from mac_mcp.adapters.reminders import RemindersAdapter
    from mac_mcp.contracts import CLEAR_RECURRENCE, Recurrence, ReminderData
    from mac_mcp.runtime import RecurrenceRequired

    run_native(request_access)
    a = RemindersAdapter()
    due = (datetime.now() + timedelta(days=1)).replace(microsecond=0)
    p = a.create_reminder(
        ReminderData(
            title=f"{TITLE_PREFIX} weekly guard",
            due=due,
            recurrence=Recurrence.from_rrule("FREQ=WEEKLY"),
        )
    )
    created.append(("reminder", p.id))

    def state():
        r = store().calendarItemWithIdentifier_(p.id)
        return bool(r.recurrenceRules()), str(r.title())

    with pytest.raises(RecurrenceRequired, match="repeats"):
        a.update_reminder(
            p.id,
            ReminderData(
                title=f"{TITLE_PREFIX} weekly guard SHOULD-NOT-STICK", due=due
            ),
        )  # omitted recurrence on a repeating target → refuse BEFORE any mutation
    recurs, title = run_native(state)
    assert recurs  # the rule survived the refused update
    assert "SHOULD-NOT-STICK" not in title  # ...and so did the title

    p2 = a.update_reminder(
        p.id,
        ReminderData(
            title=f"{TITLE_PREFIX} weekly guard (stopped)",
            due=due,
            recurrence=CLEAR_RECURRENCE,
        ),
    )  # explicit stop — verify-after-write inside asserts recurs cleared (#49)
    assert p2.id == p.id and "stopped" in p2.summary
    recurs, title = run_native(state)
    assert not recurs  # the rule is gone from the store
    assert "stopped" in title


# --- lifecycle hygiene (#56): orphan watcher --------------------------------------

# child: install the orphan watcher, announce our pid, then idle. When our parent (the
# intermediate below) is killed, the watcher must os._exit us within ~1-2s.
_ORPHAN_CHILD = """
import os, sys, time
from mac_mcp.runtime import install_lifecycle_guards
install_lifecycle_guards()
# print our pid AFTER the guards are installed — this is the test's readiness signal, so
# the parent is only killed once we've captured our launching-parent pid. (If the test
# killed the parent DURING our slow import, we'd already be reparented to 1 and the
# watcher could never detect it — the exact bug on-device testing caught.)
sys.stdout.write(str(os.getpid()) + "\\n"); sys.stdout.flush()
time.sleep(60)
"""

# intermediate: spawn the watched child, then wait. It prints NOTHING — the child
# inherits our stdout (the test's pipe) and reports its own readiness. Killing THIS
# process orphans the child so the watcher's reparent detection fires.
_ORPHAN_INTERMEDIATE = """
import subprocess, sys
child = subprocess.Popen([sys.executable, "-c", {child!r}])
child.wait()
"""


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but not ours to signal — still alive


@pytest.mark.integration
def test_orphaned_server_exits_within_5s():
    inter_src = _ORPHAN_INTERMEDIATE.format(child=_ORPHAN_CHILD)
    inter = subprocess.Popen(
        [sys.executable, "-c", inter_src], stdout=subprocess.PIPE, text=True
    )
    try:
        child_pid = int(inter.stdout.readline().strip())
        assert _alive(child_pid), "child never started"
        inter.kill()  # orphan the child — its ppid changes, watcher should fire
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if not _alive(child_pid):
                break
            time.sleep(0.2)
        else:
            os.kill(child_pid, 9)  # don't leak the child if the watcher failed
            pytest.fail("orphaned child did not exit within 5s")
    finally:
        inter.wait()


# --- Messages content via chat.db (#59) — needs Full Disk Access ---------------------


@pytest.mark.integration
def test_messages_search_reads_real_store():
    """Real chat.db: a broad search returns snippet Pointers obeying the contract. Needs
    Full Disk Access; skips cleanly if the store has no messages. Never mutates."""
    from mac_mcp.adapters.messages import MessagesAdapter

    ptrs = MessagesAdapter().search_messages("a", limit=5)  # 'a' matches most chats
    if not ptrs:
        pytest.skip("no messages in this Mac's chat.db")
    for p in ptrs:
        assert p.id and isinstance(p.summary, str)


@pytest.mark.integration
def test_attributedbody_decoder_matches_foundation():
    """The ONLY real proof the hand-rolled typedstream decoder matches Apple's byte
    layout: decode real attributedBody blobs with our decoder AND with Apple's own
    NSUnarchiver, and assert they agree. A fixture can't prove this (it bakes in the
    same assumptions). Needs Full Disk Access; skips if neither side decodes."""
    import sqlite3

    import Foundation as F

    from mac_mcp.adapters.messages import CHAT_DB, _decode_attributed_body

    conn = sqlite3.connect(f"file:{CHAT_DB}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT attributedBody FROM message WHERE attributedBody IS NOT NULL "
            "AND (text IS NULL OR text = '') LIMIT 50"
        ).fetchall()
    finally:
        conn.close()

    checked = 0
    for (blob,) in rows:
        blob = bytes(blob)
        try:  # NSUnarchiver is Apple's own typedstream reader; skip a blob it rejects
            data = F.NSData.dataWithBytes_length_(blob, len(blob))
            obj = F.NSUnarchiver.unarchiveObjectWithData_(data)
            apple = str(obj.string()) if obj is not None else None
        except Exception:
            apple = None
        if not apple:
            continue
        ours = _decode_attributed_body(blob)
        assert ours is not None, (
            f"our decoder declined a blob Foundation read: {apple!r}"
        )
        assert ours == apple, f"decoder disagrees: ours={ours!r} foundation={apple!r}"
        checked += 1

    if checked == 0:
        pytest.skip("no attributedBody message both decoders could read")


# --- Notes dual-backend (#60) — needs Full Disk Access -------------------------------


@pytest.mark.integration
def test_notes_sqlite_is_subset_of_applescript_real_store():
    """The real schema validation: every note the sqlite plane returns must be one the
    AppleScript reader also knows (same x-coredata id) — proves the NoteStore
    schema/query/id-construction against Apple's real store, and that sqlite does NOT
    leak notes AppleScript hides (e.g. Recently Deleted). Needs Full Disk Access.

    SUBSET, not equality: immutable=1 ignores the -wal, so a just-created note not yet
    checkpointed is legitimately visible to AppleScript (live) but not sqlite — that
    direction is accepted staleness, not a bug. A sqlite id ABSENT from AppleScript is
    the real defect (a wrong id, or a leaked deleted note)."""
    from mac_mcp.adapters import notes as notes_mod

    adapter = notes_mod.NotesAdapter()
    sqlite_ptrs = adapter.get_all()  # sqlite path (FDA granted)
    applescript_ptrs = notes_mod._parse_all(  # the fallback path, called directly
        notes_mod.run_osascript(notes_mod._LIST_ALL)
    )
    if not applescript_ptrs:
        pytest.skip("no notes in this Mac's library")
    sqlite_ids = {p.id for p in sqlite_ptrs}
    applescript_ids = {p.id for p in applescript_ptrs}
    assert sqlite_ids, "sqlite path returned no notes despite a non-empty library"
    phantom = sqlite_ids - applescript_ids
    assert (
        not phantom
    ), (  # a sqlite id AppleScript doesn't know = wrong id or leaked note
        f"sqlite returned ids AppleScript does not: {phantom} — wrong x-coredata id "
        "construction or a leaked (e.g. Recently Deleted) note"
    )
