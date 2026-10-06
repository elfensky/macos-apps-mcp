"""Reminders adapter — EventKit via PyObjC.

Reads return Pointers; writes take ``ReminderData``. All EventKit access goes through
``runtime.run_native`` (single serialized worker), and the store is owned by runtime.
"""

from __future__ import annotations

import dataclasses
import unicodedata
from datetime import datetime, timedelta

import EventKit as EK

from ..contracts import (
    Pointer,
    Recurrence,
    ReminderData,
    deletion_result,
    read_result,
)
from ..errors import (
    NativeError,
    RecurrenceRequired,
    SubtasksRequired,
    VerificationFailed,
    WriteRefused,
    refused_write,
    resolve_container,
    verify_persisted,
)
from ..eventkit import (
    container_id,
    due_components,
    persisted_recurrence_signature,
    recurrence_signature,
    rrule_text,
    run_native_async,
    store,
    to_nsdate,
    to_recurrence_rule,
)
from ..runtime import run_native
from ..text import clean_summary, fold_text, norm_text
from . import reminders_store

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


def _reminder_pointer(
    item, *, tags: tuple[str, ...] | None = None, parent: str | None = None
) -> Pointer:
    ident = item.calendarItemIdentifier()
    return Pointer(
        id=ident,
        summary=clean_summary(_reminder_summary(item)),
        deeplink=_reminder_deeplink(ident),
        folder=container_id(item),  # the list identifier, never its title (D-12)
        tags=tags,
        parent=parent,
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
    # Disambiguation rule (#55): see contracts.py; shared logic in
    # errors.resolve_container.
    if name is None:
        return s.defaultCalendarForNewReminders()
    items = [
        (c.calendarIdentifier(), c.title(), c)
        for c in s.calendarsForEntityType_(EK.EKEntityTypeReminder)
    ]
    return resolve_container(items, name, noun="reminder list")


def _fresh_item(s, ident):
    """Refetch by id for verify-after-write: same-store fetches can serve the
    registered in-memory object, so refresh() pulls current DB state — the diff must
    run against what actually persisted. None if the item vanished between save and
    verify (iCloud rollback)."""
    fresh = s.calendarItemWithIdentifier_(ident)
    if fresh is not None and not fresh.refresh():
        return None  # gone from the DB between save and verify
    return fresh


def _subtask_pointers(s, sub_ids: list[str]) -> tuple[Pointer, ...]:
    """A Pointer per store subtask id. An id the store lists but EventKit cannot fetch
    (a store-ahead lag) still counts, as a placeholder — dropping it would report fewer
    reminders than the delete removes (RESEARCH Pitfall 7)."""
    out = []
    for sid in sub_ids:
        item = s.calendarItemWithIdentifier_(sid)
        out.append(
            _reminder_pointer(item)
            if item is not None
            else Pointer(
                id=sid,
                summary="(subtask not visible to EventKit)",
                deeplink=_reminder_deeplink(sid),
            )
        )
    return tuple(out)


def _is_reminder(item) -> bool:
    """An EKReminder answers ``isCompleted``; an EKEvent, which shares the id space of
    ``calendarItemWithIdentifier_``, does not."""
    return hasattr(item, "isCompleted")


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
        # full-replace: None clears the rule, so verify the exact cadence both ways.
        # UNTIL is compared by day (D-09): a tool-created reminder always has a timed
        # due, and 03-01 probe 2 measured the day surviving on device (owner, A5).
        "recurs": recurrence_signature(data.recurrence, include_until=True),
    }
    actual = {
        "title": norm_text(fresh.title()),
        "notes": norm_text(fresh.notes()),
        "priority": fresh.priority(),
        "due": _due_tuple(fresh.dueDateComponents()),
        "start": _due_tuple(fresh.startDateComponents()),
        "list": fresh.calendar().calendarIdentifier(),
        "recurs": persisted_recurrence_signature(
            fresh.recurrenceRules(), include_until=True
        ),
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
                # READ-side list match folds diacritics/smart punctuation (#64): "cafe"
                # finds the "Café" list, ASCII "'" finds a U+2019 name. A fold-collision
                # ("Café" + "Cafe" lists) returns reminders from BOTH — fine for a
                # search (a superset beats "found nothing"); unlike a WRITE it can't
                # mis-home anything. resolve_container (writes) stays exact by design.
                folded = fold_text(name)
                named = [c for c in cals if fold_text(c.title()) == folded]
                if not named:
                    raise ValueError(f"no reminder list named {name!r}")
                # Incomplete-only (both bounds nil), same selector as the date
                # paths — predicateForRemindersInCalendars_ leaked completed items
                # (parity row 4).
                pred = _incomplete_due_pred(s, None, named)
            return [_reminder_pointer(r) for r in _fetch_reminders(s, pred)]

        return run_native(work)

    def read(self, query: str) -> dict:
        """``get_pointers`` plus the read-only store plane: each Pointer carries its
        ``tags`` and ``parent`` (joined by EventKit id) when the store has them, in the
        ``{results, coverage?}`` envelope (D-15, #91)."""
        # EventKit first and outside any `try`: its errors are the read's own and must
        # never be folded into `coverage`.
        pointers = self.get_pointers(query)
        # The store is optional enrichment: a missing grant, a drifted schema or a store
        # that fails mid-read leaves the EventKit pointers intact and is named in
        # `coverage` — loud, never an empty list or a swallowed error (D-15, Pitfall 5).
        try:
            tags, parents = reminders_store.tags_and_parents()
            live = reminders_store.live_ids()
        except NativeError as e:
            return read_result(
                pointers, coverage=f"tags and parent links unavailable: {e}"
            )
        unseen = sum(p.id not in live for p in pointers)
        pointers = [
            dataclasses.replace(p, tags=tags.get(p.id), parent=parents.get(p.id))
            for p in pointers
        ]
        # A readable store that lacks a pointer's id is a wrong store file or a lag:
        # its tags and parent are unknown, not absent — say so (never silent).
        note = (
            f"{unseen} of {len(pointers)} reminders are not in the Reminders store "
            "(a different store file, or not synced yet) — their tags and parent "
            "links are unknown"
            if unseen
            else None
        )
        return read_result(pointers, coverage=note)

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
            list_id = container_id(r)  # read EXPECTED list before save (#55)
            ok, err = s.saveReminder_commit_error_(r, True, None)
            if not ok:
                raise refused_write("reminder write", "list", err)
            # Re-fetch by the id we'll return — never trust the in-memory object (#49):
            # prove the id resolves and the fields persisted.
            ident = r.calendarItemIdentifier()
            fresh = _fresh_item(s, ident)
            _verify_reminder(fresh, ident, data, list_id)
            return _reminder_pointer(fresh)

        return run_native(work)

    def create_reminder_list(self, name: str) -> Pointer:
        """Create a reminder list on the default Reminders account (D-22, #92).

        No account parameter: the new list takes the source of the default list. An
        exact-name duplicate is refused before the save, because a second same-named
        list would make every later ``list_name=`` write ambiguous."""
        if not name.strip() or any(unicodedata.category(c) == "Cc" for c in name):
            raise ValueError(
                f"name must be non-empty text without control characters — got {name!r}"
            )

        def work():  # scan, save and verify on one worker turn: nothing interleaves
            s = store()
            lists = s.calendarsForEntityType_(EK.EKEntityTypeReminder)
            same = [c.calendarIdentifier() for c in lists if c.title() == name]
            if same:
                raise ValueError(
                    f"a reminder list named {name!r} already exists (id "
                    f"{', '.join(same)}) — a second one would make every later "
                    "`list_name=` write ambiguous. Use the existing id as `list_name`."
                )
            default = s.defaultCalendarForNewReminders()
            if default is None:
                raise WriteRefused(
                    "no default Reminders account to create the list in — set one in "
                    "Reminders settings, then retry. No list was created."
                )
            cal = EK.EKCalendar.calendarForEntityType_eventStore_(
                EK.EKEntityTypeReminder, s
            )
            cal.setTitle_(name)
            cal.setSource_(default.source())
            ok, err = s.saveCalendar_commit_error_(cal, True, None)
            if not ok:
                # 03-01 probe 1 (device): the default (CalDAV) source saves a list;
                # a Google source refuses with EKErrorDomain code 24, an int. 17 stays
                # in the set because the refusal code can differ by account type.
                code = int(err.code()) if err is not None else None
                if code in (
                    EK.EKErrorSourceDoesNotAllowCalendarAddDelete,  # 17
                    EK.EKErrorSourceDoesNotAllowReminders,  # 24
                ):
                    raise WriteRefused(
                        f"the default Reminders account {default.source().title()!r} "
                        "does not allow creating lists; no list was created."
                    )
                raise refused_write("reminder list create", "account", err)
            ident = cal.calendarIdentifier()
            if ident not in {
                c.calendarIdentifier()
                for c in s.calendarsForEntityType_(EK.EKEntityTypeReminder)
            }:
                raise VerificationFailed(
                    f"reminder list {name!r} (id {ident!r}) is not in the store after "
                    "the save — the write did not persist. Do not trust the id."
                )
            return _list_pointer(cal)

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
            list_id = container_id(r)  # read EXPECTED list before save (#55)
            ok, err = s.saveReminder_commit_error_(r, True, None)
            if not ok:
                raise refused_write("reminder write", "list", err)
            # A list move may re-issue the identifier; the held object's post-save id
            # is authoritative (same pattern as create and calendar.update).
            ident_after = r.calendarItemIdentifier()
            fresh = _fresh_item(s, ident_after)
            _verify_reminder(fresh, ident_after, data, list_id)
            return _reminder_pointer(fresh)

        return run_native(work)

    def snapshot(self, ident: str) -> Pointer | None:
        """The reminder's current pointer by id, or None if absent — audit
        before-state."""

        def work():
            r = store().calendarItemWithIdentifier_(ident)
            return _reminder_pointer(r) if r is not None else None

        return run_native(work)

    def complete_reminder(self, ident: str) -> dict:
        """Complete a reminder → its Pointer dict, plus ``subtasks`` when it is a parent
        that still has open children (D-21: completing a parent leaves them open and
        Reminders.app hides them). The store read comes FIRST (D-18's order): without
        it a parent cannot be told from a plain reminder, so an unreadable store
        refuses the completion and nothing is saved."""

        def work():
            s = store()
            r = s.calendarItemWithIdentifier_(ident)
            if r is None:
                raise ValueError(f"no reminder with id {ident!r}")
            if not _is_reminder(r):
                raise ValueError(
                    f"{ident!r} is a calendar event, not a reminder — nothing to "
                    "complete. Nothing was changed."
                )
            try:
                child_ids = reminders_store.subtasks_of(ident)
            except NativeError as e:
                raise WriteRefused(
                    "complete_reminder refused: the Reminders store could not be read "
                    f"to find this reminder's subtasks ({e}). No change was made."
                ) from e
            r.setCompleted_(True)
            ok, err = s.saveReminder_commit_error_(r, True, None)
            if not ok:
                raise refused_write("reminder completion", "list", err)
            fresh = _fresh_item(s, ident)
            _verify_completed(fresh, ident)
            out = _reminder_pointer(fresh)
            # a child EventKit cannot fetch stays in the report (Pitfall 7): it is not
            # known to be completed
            still_open = [
                c
                for c in child_ids
                if (kid := s.calendarItemWithIdentifier_(c)) is None
                or not kid.isCompleted()
            ]
            if still_open:
                out = dataclasses.replace(
                    out, subtasks=_subtask_pointers(s, still_open)
                )
            return out.as_dict()

        return run_native(work)

    def delete_reminder(
        self, ident: str, *, dry_run: bool = True, with_subtasks: bool = False
    ) -> dict:
        """Delete a reminder by id → the ``deletion_result`` envelope (D-17).

        The subtask read, the refusal check, the remove and the gone-check run in ONE
        ``run_native`` block, so what a confirmation lists is what was present at delete
        time, not at preview time. A subtask indented in Reminders.app minutes earlier
        may not be in the store yet (spike 007); the store is the only witness there is.
        ``dry_run=True`` does everything but the remove — the store is read and the
        refusals fire exactly as they would for the real call.
        """

        def work():
            s = store()
            r = s.calendarItemWithIdentifier_(ident)
            if r is None:
                raise ValueError(f"no reminder with id {ident!r}")
            if not _is_reminder(r):
                raise ValueError(
                    f"{ident!r} is a calendar event, not a reminder — use delete_event "
                    "for events. Nothing was changed."
                )
            # D-18: deleting a parent takes its subtasks and EventKit cannot see them.
            # Read them first; if the store is unreadable the cascade is unknowable, so
            # nothing is removed.
            try:
                sub_ids = reminders_store.subtasks_of(ident)
            except NativeError as e:
                raise WriteRefused(
                    "delete_reminder refused: the Reminders store could not be read to "
                    f"find this reminder's subtasks ({e}). No change was made."
                ) from e
            subs = _subtask_pointers(s, sub_ids)
            # D-19, before the dry-run branch (Pitfall 8): the preview of an unconfirmed
            # parent delete must refuse exactly as the real call would.
            if subs and not with_subtasks:
                listed = ", ".join(f"{p.summary} [{p.id}]" for p in subs)
                title = clean_summary(r.title())
                noun = "subtask" if len(subs) == 1 else "subtasks"
                raise SubtasksRequired(
                    f"{title!r} has {len(subs)} {noun} ({listed}). Deleting it "
                    "deletes them too. Call again with `with_subtasks=True`. "
                    "No change was made."
                )
            if dry_run:
                parent = dataclasses.replace(
                    _reminder_pointer(r), subtasks=subs or None
                )
                return deletion_result(ident, parent, subtasks=subs)
            ok, err = s.removeReminder_commit_error_(r, True, None)
            if not ok:
                raise refused_write("reminder delete", "list", err)
            # the parent and every subtask must be gone — "deleted" is never reported
            # for a reminder that is still there (iCloud may restore one)
            for gone in (ident, *(p.id for p in subs)):
                if _fresh_item(s, gone) is not None:
                    raise VerificationFailed(
                        f"reminder {gone!r} is still present after the delete — it "
                        "may have been restored by iCloud; re-read before retrying."
                    )
            return deletion_result(ident, None, subtasks=subs)

        return run_native(work)


class ReminderDeleteSnapshotter:
    """The audit before-state source for ``delete_reminder`` (D-20) — its own class so
    the shared ``RemindersAdapter.snapshot`` (update, complete) stays EventKit-only: a
    store read there, with the grant missing, would silently log ``before=None``."""

    def snapshot(self, ident: str) -> Pointer | None:
        def work():
            s = store()
            r = s.calendarItemWithIdentifier_(ident)
            if r is None or not _is_reminder(r):
                return None
            # A store error propagates: the audit layer then records before=None, and
            # the delete itself refuses anyway (D-18).
            sub_ids = reminders_store.subtasks_of(ident)
            subs = _subtask_pointers(s, sub_ids)
            return dataclasses.replace(_reminder_pointer(r), subtasks=subs or None)

        return run_native(work)
