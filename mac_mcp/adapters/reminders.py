"""Reminders adapter — EventKit via PyObjC.

Reads return Pointers; writes take ``ReminderData``. All EventKit access goes through
``runtime.run_native`` (single serialized worker), and the store is owned by runtime.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import EventKit as EK

from ..contracts import Pointer, ReminderData
from ..runtime import (
    VerificationFailed,
    due_components,
    persisted_recurrence_signature,
    recurrence_signature,
    run_native,
    run_native_async,
    store,
    to_nsdate,
    to_recurrence_rule,
    verify_persisted,
)

# A fetch has no user interaction, so the GCD callback should arrive quickly. Bound the
# wait so a callback that never fires can't hang the single worker — and every later
# run_native — forever.
_FETCH_TIMEOUT = 30.0  # seconds


def _reminder_summary(item) -> str:
    due = item.dueDateComponents()
    if due is not None:
        return (
            f"{item.title()} — due {due.year():04d}-{due.month():02d}-{due.day():02d}"
        )
    return item.title()


def _reminder_deeplink(ident: str) -> str:
    # Best-effort scheme; verify on-device that it opens the item (DESIGN: deeplinks are
    # a calibration knob).
    return f"x-apple-reminderkit://REMCDReminder/{ident}"


def _reminder_pointer(item) -> Pointer:
    ident = item.calendarItemIdentifier()
    return Pointer(
        id=ident, summary=_reminder_summary(item), deeplink=_reminder_deeplink(ident)
    )


def _list_pointer(cal) -> Pointer:
    # A reminder list (container) has no verified open-in-app URL; id + name (summary)
    # are what the projection resolves a write target against. ponytail: deeplink empty
    # by design — if on-device testing finds a working list URL, set it here (deeplinks
    # are a calibration knob).
    return Pointer(id=cal.calendarIdentifier(), summary=cal.title(), deeplink="")


def _fetch_reminders(s, predicate) -> list:
    """fetchRemindersMatchingPredicate_completion_ is async — block on the callback."""

    def start(finish):
        s.fetchRemindersMatchingPredicate_completion_(
            predicate, lambda reminders: finish(list(reminders or []))
        )

    return run_native_async(start, timeout=_FETCH_TIMEOUT)


def _end_of_day(dt: datetime) -> datetime:
    return dt.replace(hour=23, minute=59, second=59, microsecond=0)


def _incomplete_due_pred(s, end: datetime | None, cals):
    """Incomplete reminders due up to ``end`` (no lower bound, start=None).

    ``end=None`` → all incomplete reminders regardless of due date. The named-list path
    relies on this: the old ``predicateForRemindersInCalendars_`` leaked completed items
    (parity row 4), so every reminder read routes through this one incomplete-only
    selector.
    """
    return s.predicateForIncompleteRemindersWithDueDateStarting_ending_calendars_(
        None, to_nsdate(end) if end is not None else None, cals
    )


def _resolve_list(s, name: str | None):
    if name is None:
        return s.defaultCalendarForNewReminders()
    for c in s.calendarsForEntityType_(EK.EKEntityTypeReminder):
        if c.title() == name:
            return c
    raise ValueError(f"no reminder list named {name!r}")


def _apply_reminder(s, r, data: ReminderData) -> None:
    r.setTitle_(data.title)
    r.setNotes_(data.notes)  # full-replace: None clears
    r.setPriority_(data.priority)  # 0 none, 1–9 (1 highest)
    r.setDueDateComponents_(due_components(data.due) if data.due is not None else None)
    r.setStartDateComponents_(
        due_components(data.start) if data.start is not None else None
    )
    r.setRecurrenceRules_(  # full-replace: None clears any existing rule
        [to_recurrence_rule(data.recurrence)] if data.recurrence else None
    )
    r.setCalendar_(_resolve_list(s, data.list_name))


def _due_tuple(comps) -> tuple | None:
    """The (year, month, day, hour, minute) due_components() sets — the exact fields we
    request, so the diff compares like-for-like (EventKit may add extras on read)."""
    if comps is None:
        return None
    return (comps.year(), comps.month(), comps.day(), comps.hour(), comps.minute())


def _expected_due_tuple(dt: datetime | None) -> tuple | None:
    return None if dt is None else (dt.year, dt.month, dt.day, dt.hour, dt.minute)


def _verify_reminder(fresh, ident: str, data: ReminderData, list_title: str) -> None:
    """Re-fetch-by-id verify (#49): fail loudly if the saved reminder can't be re-read
    or any requested field didn't persist. `fresh` is a fresh fetch by the id we return;
    `list_title` is the requested list (the calendar _apply_reminder set)."""
    if fresh is None:
        raise VerificationFailed(
            f"reminder {ident!r} could not be re-fetched — the write did not persist "
            "(a fabricated id or an iCloud rollback). Do not trust the id; re-read "
            "Reminders before retrying."
        )
    expected = {
        "title": data.title,
        "notes": data.notes or None,  # "" and None are both "no notes"
        "priority": data.priority,
        "due": _expected_due_tuple(data.due),
        "start": _expected_due_tuple(data.start),
        "list": list_title,
        # full-replace: None clears the rule, so verify the exact cadence both ways
        "recurs": recurrence_signature(data.recurrence),
    }
    actual = {
        "title": fresh.title(),
        "notes": fresh.notes() or None,
        "priority": fresh.priority(),
        "due": _due_tuple(fresh.dueDateComponents()),
        "start": _due_tuple(fresh.startDateComponents()),
        "list": fresh.calendar().title(),
        "recurs": persisted_recurrence_signature(fresh.recurrenceRules()),
    }
    verify_persisted("reminder", expected, actual)


def _verify_completed(fresh, ident: str) -> None:
    if fresh is None:
        raise VerificationFailed(
            f"reminder {ident!r} could not be re-fetched after completing it — the "
            "write did not persist. Do not trust the id."
        )
    if not fresh.isCompleted():
        raise VerificationFailed(
            f"reminder {ident!r} did not persist as completed (dropped or reverted). "
            "Re-read it before retrying."
        )


class RemindersAdapter:
    def get_pointers(self, query: str) -> list[Pointer]:
        """query: 'today' | 'overdue' | 'this-week' | a reminder-list name."""

        def work():
            s = store()
            cals = s.calendarsForEntityType_(EK.EKEntityTypeReminder)
            q = query.strip().lower()
            if q in ("today", "overdue", "this-week"):
                now = datetime.now()
                end = {
                    "today": _end_of_day(now),
                    "overdue": now,
                    "this-week": now + timedelta(days=7),
                }[q]
                # No lower bound (start=None) is intentional: each selector wants all
                # incomplete reminders due up to `end`, so overdue ⊂ today ⊂ this-week.
                # The briefing relies on this.
                pred = _incomplete_due_pred(s, end, cals)
            else:
                name = query.strip()
                named = [c for c in cals if c.title() == name]
                if not named:
                    raise ValueError(f"no reminder list named {name!r}")
                # Incomplete-only (both bounds nil), same selector as the date
                # paths — predicateForRemindersInCalendars_ leaked completed items
                # (parity row 4).
                pred = _incomplete_due_pred(s, None, named)
            return [_reminder_pointer(r) for r in _fetch_reminders(s, pred)]

        return run_native(work)

    def get_lists(self) -> list[Pointer]:
        """Reminder lists as Pointers (id + name) for resolving write targets."""

        def work():
            s = store()
            return [
                _list_pointer(c)
                for c in s.calendarsForEntityType_(EK.EKEntityTypeReminder)
            ]

        return run_native(work)

    def create_reminder(self, data: ReminderData) -> Pointer:
        def work():
            s = store()
            r = EK.EKReminder.reminderWithEventStore_(s)
            _apply_reminder(s, r, data)
            ok, err = s.saveReminder_commit_error_(r, True, None)
            if not ok:
                raise RuntimeError(f"save reminder failed: {err}")
            # Re-fetch by the id we'll return — never trust the in-memory object (#49):
            # prove the id resolves and the fields persisted.
            ident = r.calendarItemIdentifier()
            fresh = s.calendarItemWithIdentifier_(ident)
            _verify_reminder(fresh, ident, data, r.calendar().title())
            return _reminder_pointer(fresh)

        return run_native(work)

    def update_reminder(self, ident: str, data: ReminderData) -> Pointer:
        def work():
            s = store()
            r = s.calendarItemWithIdentifier_(ident)
            if r is None:
                raise ValueError(f"no reminder with id {ident!r}")
            _apply_reminder(s, r, data)
            ok, err = s.saveReminder_commit_error_(r, True, None)
            if not ok:
                raise RuntimeError(f"save reminder failed: {err}")
            fresh = s.calendarItemWithIdentifier_(ident)
            _verify_reminder(fresh, ident, data, r.calendar().title())
            return _reminder_pointer(fresh)

        return run_native(work)

    def complete_reminder(self, ident: str) -> Pointer:
        def work():
            s = store()
            r = s.calendarItemWithIdentifier_(ident)
            if r is None:
                raise ValueError(f"no reminder with id {ident!r}")
            r.setCompleted_(True)
            ok, err = s.saveReminder_commit_error_(r, True, None)
            if not ok:
                raise RuntimeError(f"complete reminder failed: {err}")
            fresh = s.calendarItemWithIdentifier_(ident)
            _verify_completed(fresh, ident)
            return _reminder_pointer(fresh)

        return run_native(work)
