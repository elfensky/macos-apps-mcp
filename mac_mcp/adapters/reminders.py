"""Reminders adapter — EventKit via PyObjC.

Reads return Pointers; writes take ``ReminderData``. All EventKit access goes through
``runtime.run_native`` (single serialized worker), and the store is owned by runtime.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import EventKit as EK

from ..contracts import Pointer, Recurrence, ReminderData
from ..runtime import (
    RecurrenceRequired,
    VerificationFailed,
    WriteRefused,
    clean_summary,
    due_components,
    norm_text,
    persisted_recurrence_signature,
    recurrence_signature,
    resolve_container,
    rrule_text,
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
        id=ident,
        summary=clean_summary(_reminder_summary(item)),
        deeplink=_reminder_deeplink(ident),
    )


def _list_pointer(cal) -> Pointer:
    # A reminder list (container) has no verified open-in-app URL; id + name (summary)
    # are what the projection resolves a write target against. The title is kept RAW
    # (NOT routed through clean_summary, unlike item summaries): the resolver still
    # matches `c.title() == name` exactly for the name path (a write may target the id
    # or the name, #55), so the summary IS a write key — sanitizing it (e.g. trimming a
    # trailing space, collapsing a double space) would desync the displayed name from
    # the resolvable one and make the list name-untargetable (#52 review). Container
    # names are short user-typed text, so the hygiene risk a sanitized summary would
    # guard is negligible here. ponytail: deeplink empty by design — set a working list
    # URL here if on-device testing finds one.
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
    # Disambiguation rule (#55): accept a Pointer.id OR an exact name; an id is used
    # directly, an ambiguous name is refused loudly (never auto-picked). The shared
    # logic — including listing candidate ids — lives in runtime.resolve_container.
    if name is None:
        return s.defaultCalendarForNewReminders()
    items = [
        (c.calendarIdentifier(), c.title(), c)
        for c in s.calendarsForEntityType_(EK.EKEntityTypeReminder)
    ]
    return resolve_container(items, name, noun="reminder list")


def _apply_reminder(s, r, data: ReminderData) -> None:
    r.setTitle_(data.title)
    r.setNotes_(data.notes)  # full-replace: None clears
    r.setPriority_(data.priority)  # 0 none, 1–9 (1 highest)
    r.setDueDateComponents_(due_components(data.due) if data.due is not None else None)
    r.setStartDateComponents_(
        due_components(data.start) if data.start is not None else None
    )
    # Tri-state: a Recurrence sets the rule; CLEAR_RECURRENCE and None both clear —
    # None only gets here when the target has no rule to destroy (RecurrenceRequired
    # guard in update_reminder).
    r.setRecurrenceRules_(
        [to_recurrence_rule(data.recurrence)]
        if isinstance(data.recurrence, Recurrence)
        else None
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


def _verify_reminder(fresh, ident: str, data: ReminderData, list_id: str) -> None:
    """Re-fetch-by-id verify (#49): fail loudly if the saved reminder can't be re-read
    or any requested field didn't persist. `fresh` is a fresh fetch by the id we return;
    `list_id` is the requested list's identifier (of the list _apply_reminder set).

    The list is verified by IDENTIFIER, not title (#55 review): with id-targeting a
    write can name a SPECIFIC one of several same-named lists, so a title compare would
    falsely pass if the store re-homed the reminder to a different list sharing the name
    — exactly the re-home this #49 guard exists to catch."""
    if fresh is None:
        raise VerificationFailed(
            f"reminder {ident!r} could not be re-fetched — the write did not persist "
            "(a fabricated id or an iCloud rollback). Do not trust the id; re-read "
            "Reminders before retrying."
        )
    expected = {
        "title": norm_text(data.title),
        "notes": norm_text(data.notes),  # norm_text folds "" and None to "no notes"
        "priority": data.priority,
        "due": _expected_due_tuple(data.due),
        "start": _expected_due_tuple(data.start),
        "list": list_id,  # opaque UUID handle — compared raw, not norm_text
        # full-replace: None clears the rule, so verify the exact cadence both ways
        "recurs": recurrence_signature(data.recurrence),
    }
    actual = {
        "title": norm_text(fresh.title()),
        "notes": norm_text(fresh.notes()),
        "priority": fresh.priority(),
        "due": _due_tuple(fresh.dueDateComponents()),
        "start": _due_tuple(fresh.startDateComponents()),
        "list": fresh.calendar().calendarIdentifier(),
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
            # Read the EXPECTED list before the save — the commit may re-home the
            # object, and post-save it would tautologically equal the actual. Capture
            # the IDENTIFIER (not title) — that's what verify keys on (#55 review).
            cal = r.calendar()
            list_id = cal.calendarIdentifier() if cal is not None else None
            ok, err = s.saveReminder_commit_error_(r, True, None)
            if not ok:
                raise WriteRefused(
                    f"the reminder write was refused by the store: {err}. The target "
                    "list may be read-only (a subscribed list) or the account "
                    "rejected the change — do not retry the same target; tell the "
                    "user."
                )
            # Re-fetch by the id we'll return — never trust the in-memory object (#49):
            # prove the id resolves and the fields persisted.
            ident = r.calendarItemIdentifier()
            fresh = s.calendarItemWithIdentifier_(ident)
            # Same-store fetches can serve the registered in-memory object; refresh()
            # pulls current DB state so the diff is against what actually persisted.
            if fresh is not None and not fresh.refresh():
                fresh = None  # gone from the DB between save and verify
            _verify_reminder(fresh, ident, data, list_id)
            return _reminder_pointer(fresh)

        return run_native(work)

    def update_reminder(self, ident: str, data: ReminderData) -> Pointer:
        def work():
            s = store()
            r = s.calendarItemWithIdentifier_(ident)
            if r is None:
                raise ValueError(f"no reminder with id {ident!r}")
            # Repeating target + omitted recurrence → refuse BEFORE any mutation, so
            # a rename can't silently clear the series (mirror of SpanRequired, #51).
            rules = r.recurrenceRules()
            if rules and data.recurrence is None:
                raise RecurrenceRequired(
                    f"this reminder repeats ({rrule_text(rules[0])}) — re-send "
                    "recurrence='FREQ=...' to keep or change it, or "
                    "recurrence='none' to stop it repeating, then retry. "
                    "No change was made."
                )
            _apply_reminder(s, r, data)
            # Read the EXPECTED list before the save — the commit may re-home the
            # object, and post-save it would tautologically equal the actual. Capture
            # the IDENTIFIER (not title) — that's what verify keys on (#55 review).
            cal = r.calendar()
            list_id = cal.calendarIdentifier() if cal is not None else None
            ok, err = s.saveReminder_commit_error_(r, True, None)
            if not ok:
                raise WriteRefused(
                    f"the reminder write was refused by the store: {err}. The target "
                    "list may be read-only (a subscribed list) or the account "
                    "rejected the change — do not retry the same target; tell the "
                    "user."
                )
            # A list move may re-issue the identifier; the held object's post-save id
            # is authoritative (same pattern as create and calendar.update).
            ident_after = r.calendarItemIdentifier()
            fresh = s.calendarItemWithIdentifier_(ident_after)
            # Same-store fetches can serve the registered in-memory object; refresh()
            # pulls current DB state so the diff is against what actually persisted.
            if fresh is not None and not fresh.refresh():
                fresh = None  # gone from the DB between save and verify
            _verify_reminder(fresh, ident_after, data, list_id)
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
                raise WriteRefused(
                    f"the reminder completion was refused by the store: {err}. The "
                    "target list may be read-only (a subscribed list) or the account "
                    "rejected the change — do not retry the same target; tell the "
                    "user."
                )
            fresh = s.calendarItemWithIdentifier_(ident)
            # Same-store fetches can serve the registered in-memory object; refresh()
            # pulls current DB state so the diff is against what actually persisted.
            if fresh is not None and not fresh.refresh():
                fresh = None  # gone from the DB between save and verify
            _verify_completed(fresh, ident)
            return _reminder_pointer(fresh)

        return run_native(work)
