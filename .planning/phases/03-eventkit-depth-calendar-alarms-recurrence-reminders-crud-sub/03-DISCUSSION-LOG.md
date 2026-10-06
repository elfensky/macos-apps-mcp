# Phase 3: EventKit Depth — Calendar Alarms & Recurrence, Reminders CRUD & Subtasks - Discussion Log (Assumptions Mode)

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the analysis.

**Date:** 2026-10-05
**Phase:** 03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub
**Mode:** assumptions
**Areas analyzed:** Code placement and recurrence plumbing; Tool surface; Delete safety and audit; Verification and tests

## Assumptions Presented

### Code placement and recurrence plumbing
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Reminders sqlite read in a new sidecar `adapters/reminders_store.py`, on `runtime.read_via_sqlite`, no fallback | Likely | `adapters/mail_index.py:20,36`; `runtime.py:487`; `tests/test_native_seam.py:31-35` |
| BY* fields on `Recurrence` in `contracts.py`; canonical dict replaces the signature bodies in `eventkit.py`; 9-arg initializer | Confident | `contracts.py:339-384`; `eventkit.py:196-219`; `tests/test_eventkit.py:78-80` |
| UNTIL compared at day granularity on timed events only | Likely | `eventkit.py:216-219`; spike 003 reference step 5 |
| BY* reaches reminders too; `rrule_text` renders BY* | Unclear → Likely after research | `server.py:1109,1138`; `reminders.py:141-145,289-294`; `eventkit.py:244-254`; Apple: `recurrenceRules` on `EKCalendarItem` |

### Tool surface
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| `folder = container_id(item)` in both pointer builders; no new tool | Confident | `calendar.py:81-86,96,180-197`; `reminders.py:56-62,76`; `eventkit.py:45-51`; `contracts.py:221-222` |
| Tags and subtasks as two read tools, `reminders()` EventKit-only | Likely | `registry.py:41`; `tests/test_tool_annotations.py:89-99`; `contracts.py:116-120` |
| `CalendarEventData.alarms`, >5 refused in `__post_init__`, tri-state on update, sorted-multiset verify; minutes-before with negatives allowed | Likely | `contracts.py:443-470`; `calendar.py:217-230`; spike 008 reference |
| `create_reminder_list(name)` additive, default list's source, duplicate name refused | Likely | `reminders.py:110-111`; `errors.py:136-145`; `registry.py:87-89`; no `saveCalendar_` code exists |

### Delete safety and audit
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| `delete_reminder` refuses a parent with subtasks unless confirmed (`SpanRequired` shape) | Likely | `calendar.py:246-263,494-503`; spike 007 |
| FDA denied or `SchemaDrift` on the subtask read → refuse, no delete | Confident | `runtime.py:488-492`; PROJECT.md:108 |
| `Pointer.subtasks` optional tuple; `delete_reminder` registers its own snapshotter | Likely | `contracts.py:263-273`; `audit.py:197-211`; `server.py:1114,1143` |
| Gone-check after remove, added to `delete_event` as well | Likely | `reminders.py:119-127`; `calendar.py:504-507`; `tests/test_integration.py:152-154` |

### Verification and tests
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| DTSTART-mismatch detection: pure-Python membership check, no runtime dateutil | Unclear → Confident after research | `pyproject.toml:51-56`; `uv.lock`; dateutil #1588, PR #1575 |
| Six-month check with `python-dateutil` in the dev group, `set(ref) \| {dtstart}` | Likely | spike 003 `probe_eventkit.py:265-266`; `tests/test_integration.py:680-714` |
| EventKit fakes patch `store` / `run_native`; `tmp_path` sqlite for the store plane; device-only list | Confident | `tests/conftest.py:195-224`; `tests/test_reminders.py:141-155`; `tests/test_notes.py:244-260` |
| Stale "create subtasks via `parentReminder`" wording rewritten before verification | Confident | `ROADMAP.md:195`; `REQUIREMENTS.md:46`; `PROJECT.md:48`; spike 002 |

## Corrections Made

### Tool surface — store reads
- **Original assumption:** two read tools, `reminder_subtasks(id)` and `reminder_tags(...)`,
  with `reminders()` left EventKit-only, so a host without Full Disk Access keeps `reminders()`.
- **User correction:** fold tags and the parent link into `reminders()` (D-15). The owner
  asked whether the app already holds Full Disk Access; it does (daemon identity
  `ren.lav.macos-apps-mcp`, the same grant the Mail, Messages and Notes planes use), so the
  question narrowed to coupling, answered by a loud `coverage` flag when the store is
  unreadable.
- **Reason:** one call for the briefing; the store read is needed for `delete_reminder`
  anyway; the read envelope already has a non-silent partial-answer shape.

### Tool surface — alarm convention
- **Original assumption:** minutes before, negatives allowed (presented beside the EventKit
  signed-offset form).
- **User direction:** "follow official conventions so other agents are used to it; don't
  reinvent the wheel." Verified on 2026-10-05: Google Calendar API, Microsoft Graph and
  mcp-ical all take positive minutes before; EventKit and RFC 5545 take signed offsets.
  The owner chose **minutes before, positive** (D-01); the RFC 5545 `TRIGGER` string form
  was offered as the standard alternative and declined. Signed minutes was dropped as a
  reinvention (neither Apple's, the RFC's nor Google's form).

### Delete safety — parent delete
- Explained in plain terms on request (cascade proven by spike 007; EventKit reports 1 when
  N+1 are gone; undo re-creates subtasks flat only). The owner confirmed **refuse unless
  confirmed** (D-19).

All other assumptions were confirmed as listed ("Yes, as listed").

## External Research

- **`saveCalendar` per source type.** Apple documents no per-source "allows add/delete"
  flag; `EKErrorSourceDoesNotAllowCalendarAddDelete` (17) is the only signal, and the
  per-source matrix is undocumented → device probe (D-22, D-23).
  [EKError.Code](https://developer.apple.com/documentation/eventkit/ekerror/code) ·
  [🔖 2026-10-05](https://linkding.lav.ren/bookmarks?details=154);
  [EKSource](https://developer.apple.com/documentation/eventkit/eksource) ·
  [🔖](https://linkding.lav.ren/bookmarks?details=148).
- **python-dateutil vs RFC 5545.** DTSTART is not emitted unless it fits the rule
  (`rrule.py` `_iter`); `__contains__` exists; known deviations: mixed plain/ordinal BYDAY
  is an intersection ([#1588](https://github.com/dateutil/dateutil/issues/1588) ·
  [🔖](https://linkding.lav.ren/bookmarks?details=166)), WEEKLY+BYSETPOS with a mid-week
  DTSTART ([PR #1575](https://github.com/dateutil/dateutil/pull/1575) ·
  [🔖](https://linkding.lav.ren/bookmarks?details=161)), BYSETPOS bounded to ±366
  ([#905](https://github.com/dateutil/dateutil/issues/905)). Resolved D-10 (no runtime
  dateutil) and D-24 (dev-only reference, divergent shapes hand-computed).
  [rrule.py](https://raw.githubusercontent.com/dateutil/dateutil/master/src/dateutil/rrule.py) ·
  [🔖 2026-10-05](https://linkding.lav.ren/bookmarks?details=156).
- **`EKRecurrenceRule` on reminders.** `recurrenceRules` is on `EKCalendarItem`; the full
  initializer applies to reminders; the only reminder-specific error is
  `EKErrorRecurringReminderRequiresDueDate` (18). Per-source round-trip is undocumented →
  one device test (D-11).
  [EKRecurrenceRule](https://developer.apple.com/documentation/eventkit/ekrecurrencerule) ·
  [🔖 2026-10-05](https://linkding.lav.ren/bookmarks?details=153).
- **Alarm conventions.** Google `reminders.overrides[].minutes`: "Number of minutes before
  the start of the event … between 0 and 40320"
  ([events resource](https://developers.google.com/workspace/calendar/api/v3/reference/events) ·
  [🔖 2026-10-05](https://linkding.lav.ren/bookmarks?details=168)); Graph
  `reminderMinutesBeforeStart: Int32`
  ([event](https://learn.microsoft.com/en-us/graph/api/resources/event?view=graph-rest-1.0) ·
  [🔖 2026-10-05](https://linkding.lav.ren/bookmarks?details=167)); mcp-ical
  `alarms_minutes_offsets: list[int]`, `minutes = int(-offset_seconds / 60)`
  ([models.py](https://raw.githubusercontent.com/Omar-V2/mcp-ical/main/src/mcp_ical/models.py) ·
  [🔖 2026-10-05](https://linkding.lav.ren/bookmarks?details=170)). Resolved D-01.
