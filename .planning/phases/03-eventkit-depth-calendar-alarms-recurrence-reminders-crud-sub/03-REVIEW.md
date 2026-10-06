---
phase: 03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub
reviewed: 2026-10-06T14:35:55Z
depth: standard
files_reviewed: 19
files_reviewed_list:
  - macos_apps_mcp/adapters/calendar.py
  - macos_apps_mcp/adapters/reminders.py
  - macos_apps_mcp/adapters/reminders_store.py
  - macos_apps_mcp/contracts.py
  - macos_apps_mcp/errors.py
  - macos_apps_mcp/eventkit.py
  - macos_apps_mcp/server.py
  - tests/_fakes.py
  - tests/integration/test_eventkit_depth.py
  - tests/test_audit_middleware.py
  - tests/test_calendar.py
  - tests/test_contracts.py
  - tests/test_eventkit.py
  - tests/test_integration.py
  - tests/test_registry.py
  - tests/test_reminders.py
  - tests/test_reminders_store.py
  - tests/test_server.py
  - tests/test_tool_annotations.py
findings:
  critical: 0
  warning: 2
  info: 4
  total: 6
status: issues_found
---

# Phase 3: Code Review Report

**Reviewed:** 2026-10-06T14:35:55Z
**Depth:** standard
**Files Reviewed:** 19
**Status:** issues_found

## Summary

Reviewed the Phase 3 diff (`56b9fa3..HEAD`) of the EventKit adapters, the new read-only
Reminders store plane, the recurrence and alarm contracts, and the server tool layer.
Baseline: `uv run pytest` passes (1810 passed, 96 integration deselected), `ruff check`
and `ruff format --check` are clean.

Beyond that baseline, `dtstart_in_rule` was fuzzed against `dateutil` over about 320
random rules with BYDAY or BYMONTHDAY. The only divergences were rules that mix plain and
ordinal BYDAY items, which the docstring already names as a deliberate RFC 5545 choice.
The recurrence parser, the canonical signature compare and `rrule_text` held up.

No security problems were found. The sqlite id is bound as a parameter. The store is
opened `mode=ro` through `read_via_sqlite`. The tier gating, the `dry_run=True` default
and the dedicated delete snapshotter match the project rules.

The two warnings are both about the safety net around destructive and mutating reminder
and event tools: a missing type guard on the id-addressed write paths, and a subtask guard
that cannot tell "no subtasks" from "parent not in the store".

## Warnings

### WR-01: `update_reminder`, `update_event` and `delete_event` have no item-type guard (`complete_reminder` and `delete_reminder` do)

**File:** `macos_apps_mcp/adapters/reminders.py:407-435`, `macos_apps_mcp/adapters/calendar.py:305-321, 489-513, 528-560`
**Issue:** Phase 3 added `_is_reminder` to `complete_reminder` and `delete_reminder`
because `calendarItemWithIdentifier_` shares one id space between reminders and events.
The same lookup is still unguarded in three other id-addressed write paths:

- `update_reminder` resolves with `calendarItemWithIdentifier_(ident)`. Given a bare event
  id it runs `_apply_reminder`. That calls `setTitle_`, `setNotes_` and `setPriority_` on
  the `EKEvent` (all exist), then raises a raw `AttributeError` at
  `setDueDateComponents_` (verified: `EKEvent` has no such selector). `AttributeError` is
  not caught by `server._guard` (only `NativeError` and `ValueError`), so the model gets
  an unclassified exception and not an agent-directed message. The event object lives in
  the process-wide `EKEventStore` singleton with its title, notes and priority already
  overwritten and unsaved. A later save of that event in the same daemon would carry the
  dirty fields.
- `_resolve_event` has a "legacy id" branch (no `|` in the id) that returns whatever
  `calendarItemWithIdentifier_` finds. A reminder id passed to `update_event` or
  `delete_event` reaches `_apply_event` or `_event_pointer` with an `EKReminder` and fails
  the same way (`delete_event` with `dry_run=True` fails in `_event_pointer` on
  `isAllDay`).
- The audit snapshotters (`RemindersAdapter.snapshot`, `CalendarAdapter.snapshot`) swallow
  the error in `_safe_snapshot`, so the audit `before` is silently `None`.

The guard exists in two of the five paths and is missing in the paths that mutate most
(`update_*`), so the fix for the earlier review finding was applied only to the sites that
review named.

**Fix:** Guard once where all callers route through. In `update_reminder`, after the `None`
check:
```python
if not _is_reminder(r):
    raise ValueError(
        f"{ident!r} is a calendar event, not a reminder — use update_event for "
        "events. Nothing was changed."
    )
```
In `calendar._resolve_event`'s legacy branch, refuse a non-event (`hasattr(e,
"isCompleted")`, or `not hasattr(e, "isAllDay")` mirrored from `_is_reminder`) with the
same style of `ValueError`. Add one fake-based test per path next to the existing
`complete_reminder` event-id test.

### WR-02: The subtask guard fails open when the store cannot see the parent (wrong store file, missing join key, or lag)

**File:** `macos_apps_mcp/adapters/reminders_store.py:57-98, 122-135`, `macos_apps_mcp/adapters/reminders.py:520-538, 464-470`
**Issue:** The delete safety rests on `subtasks_of(ident)` returning the full set of
children. Its failure signal is only a typed store error. These cases give an empty list
that reads the same as "no subtasks":

- `store_path()` picks the largest `Data-*.sqlite` by file size (main file only, not the
  WAL). The "others are empty shells" assumption is measured on one Mac (spike 007). A
  Mac with more than one account store, or a large WAL on a small main file, can select
  the wrong store. `tags_and_parents` then returns no tags and no parents and
  `subtasks_of` returns `[]`.
- The join key `ZCKIDENTIFIER` is assumed equal to the EventKit `calendarItemIdentifier`
  for every reminder (1372 of 1372 on the spike Mac). For a reminder whose account does
  not populate that column the same silent empty result follows, and a NULL
  `ZCKIDENTIFIER` on a child row would flow into `_subtask_pointers` as
  `calendarItemWithIdentifier_(None)` and a `Pointer(id=None, ...)`.
- The documented store lag (a subtask indented minutes earlier is not yet in the store)
  is caught by neither check.

In all three cases `delete_reminder(..., with_subtasks=False)` proceeds to delete the
parent and EventKit removes the subtasks without the `SubtasksRequired` confirmation. The
receipt then reports a plain `{"deleted": ident}` with no `cascade` key, and the audit
`before` has no `subtasks`. `read()` has the same blind spot: a readable store that has no
row for a pointer produces a pointer without `tags` and with no `coverage` note.

**Fix:** Make "the parent is not in the store" distinguishable from "the parent has no
children". In `subtasks_of`, first `SELECT 1 FROM ZREMCDREMINDER WHERE ZCKIDENTIFIER = ?
AND ZMARKEDFORDELETION = 0` and return a sentinel or raise a typed error when no row
exists. In `delete_reminder` and `complete_reminder`, refuse (or at minimum add a loud
`coverage`-style note to the result) when the parent has no store row, with a message that
names the lag case. Filter `None` ids out of `_SUBTASKS_OF` and `_PARENTS`
(`AND c.ZCKIDENTIFIER IS NOT NULL`). For the store choice, either union the rows of every
`Data-*.sqlite` or verify the chosen file contains the live reminders (for example by
matching a known id) before trusting it. Whichever route is taken, state the residual lag
risk in the `delete_reminder` receipt rather than only in the tool docstring.

## Info

### IN-01: `Recurrence` claims its invariants hold on direct construction but `interval` and `count` are only validated in `from_rrule`

**File:** `macos_apps_mcp/contracts.py:457-465, 556-563`
**Issue:** The `__post_init__` comment says the invariants hold "however a Recurrence is
built". Phase 3 extended that to every BY part, but `interval < 1` and `count < 1` are
still checked only in `from_rrule`. `Recurrence("daily", interval=0)` builds and reaches
`to_recurrence_rule`. Both new validation paths in this phase (`_validate_by_parts` and
`CalendarEventData.__post_init__`) follow the "validate on the contract" pattern, so this
one is now inconsistent.
**Fix:** Move the two range checks into `__post_init__` and keep `from_rrule` as the parser
only.

### IN-02: `create_reminder_list` accepts names that the exact-match resolver cannot reliably re-target

**File:** `macos_apps_mcp/adapters/reminders.py:353-405`
**Issue:** The name check rejects only control characters (category `Cc`). Names with
leading or trailing whitespace, or with format characters (category `Cf`, for example a
zero-width space), are accepted and saved verbatim. The post-save verification only checks
that the new identifier is in the store, not that the persisted title equals `name`. A
source that trims or normalizes the title would pass verification and make the duplicate
scan (`c.title() == name`) disagree with what was stored.
**Fix:** Reject `name != name.strip()` and categories `Cc`/`Cf`, and compare
`norm_text(cal.title())` with `norm_text(name)` in the post-save check.

### IN-03: The D-10 note is appended to `Pointer.summary` past `SUMMARY_MAX`

**File:** `macos_apps_mcp/adapters/calendar.py:97-110`
**Issue:** `_with_dtstart_note` deliberately skips `clean_summary` so a long title cannot
cut the note. The result is a summary longer than the 256-character cap that every other
pointer honours, and a machine-readable annotation embedded in a field that vault
citations store as the item title.
**Fix:** If the cap matters to downstream consumers, truncate the title part to
`SUMMARY_MAX - len(_DTSTART_NOTE)` before appending. Otherwise record the exception in the
`Pointer` docstring.

### IN-04: `delete_event` post-delete check may false-fail for an id without an occurrence suffix

**File:** `macos_apps_mcp/adapters/calendar.py:547-558`, `macos_apps_mcp/adapters/calendar.py:314-321`
**Issue:** The new "still resolves" check reuses `_resolve_event`. For ids with `|` it
queries the database and is sound. For a plain id (the legacy branch) it calls
`calendarItemWithIdentifier_`, and `reminders.py:_fresh_item` documents that a same-store
fetch can serve the registered in-memory object after a remove (its fix is `refresh()`).
If that applies to events, a successful delete of a plain-id event raises
`VerificationFailed` ("may have been restored"), which invites a retry of a destructive
call that already succeeded. Not reproduced here (needs a device); pointer ids from
`events` always carry the suffix, so only a hand-written id reaches it.
**Fix:** In the legacy branch of the post-check, apply the same `refresh()` test as
`_fresh_item`, or confirm on device and add a note to `docs/`.

---

_Reviewed: 2026-10-06T14:35:55Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
