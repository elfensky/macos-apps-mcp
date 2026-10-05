# Phase 3: EventKit Depth — Calendar Alarms & Recurrence, Reminders CRUD & Subtasks - Context

**Gathered:** 2026-10-05 (assumptions mode)
**Status:** Ready for planning

<domain>
## Phase Boundary

The one native plane Calendar and Reminders share reaches Mail-level completeness: alarms and
real recurrence on events; deletion, lists, subtasks and tags on reminders; and the owning
container on every event and reminder Pointer.

Open requirements: CAL-01, CAL-02, CAL-03, CAL-04, REM-01, REM-02, REM-03, REM-04, REM-06.
MAIL-05 and MAIL-06 (#229, #230) were settled in 0.13.1 ahead of the phase; success criteria
7 and 8 are already true and need no plan.

Not in this phase: alarms on reminders (REM-05, v2), any tag or subtask **write** (no public
route exists; REM-04 forbids private API), Contacts or Messages depth (v2). Nothing in this
phase touches Mail.

Everything below that cites a spike was proven on device before this context was written
(spikes 002, 003, 007, 008; macOS 27.0, iCloud and Google CalDAV sources, host zone
Europe/Brussels). Those findings are locked; the planner does not re-probe them.
</domain>

<decisions>
## Implementation Decisions

### Alarms (CAL-01, CAL-02)
- **D-01:** `create_event` and `update_event` take `alarms: list[int] | None`: **minutes
  before the start, positive integers** — the Google Calendar API
  (`reminders.overrides[].minutes`), Microsoft Graph (`reminderMinutesBeforeStart`) and
  mcp-ical (`alarms_minutes_offsets`) convention (owner, 2026-10-05: follow the convention
  other agents know). Each value maps to `EKAlarm.alarmWithRelativeOffset_(-minutes * 60.0)`.
  Relative alarms only; the tool never builds an absolute alarm (Google rewrites it 10–30 s
  after the save, and on a floating all-day event it is a fixed instant on the wrong day).
- **D-02:** All-day offsets count from local midnight of the event's day (#51, the existing
  rule). Negative values are allowed for that case: "09:00 on the day" is `-540`; "the day
  before at 09:00" is `900`. The docstring states the rule with both examples, and says a
  DST-change day fires at 08:00 or 10:00 — the same as Calendar's own alerts.
- **D-03:** More than 5 alarms is refused in `CalendarEventData.__post_init__`, before any
  native call, on every source (Google keeps 5 and drops a different one after the save; a
  delayed re-read is not the guard). `None`, never `[]`, is passed to `setAlarms_` for no
  alarms.
- **D-04:** On `update_event`, `alarms=None` leaves the alarms untouched and `alarms=[]`
  clears them — the same tri-state as `recurrence` today. Full-replace is wrong: a rename
  would strip alarms set in Calendar.app. Verify-after-write compares alarms only when they
  were set, as a sorted multiset of `round(relativeOffset / 60)`, and asserts no absolute
  alarm came back.
- **D-05:** All-day events stay floating (`timeZone = nil`, naive local midnight bounds), the
  current adapter path (24/24 zone cells correct). The all-day date derives from `.date()`:
  on a day whose local midnight does not exist, `startDate` reads 01:00.

### Recurrence (CAL-03)
- **D-06:** `contracts._RRULE_SUPPORTED` widens to FREQ, INTERVAL, COUNT, UNTIL, BYDAY
  (with ordinals such as `2TU`, `-1FR`), BYMONTHDAY, BYMONTH, BYYEARDAY, BYSETPOS — all
  expand exactly on device. `Recurrence.from_rrule` rejects BYWEEKNO, BYHOUR, BYMINUTE,
  BYSECOND and WKST **by name** with `ValueError` before any native call. BYWEEKNO is the
  trap: EventKit saves it without error and expands to DTSTART only.
- **D-07:** The BY* fields live on the `Recurrence` dataclass in `contracts.py` (pure data,
  no PyObjC). `eventkit.to_recurrence_rule` builds with the 9-argument
  `initRecurrenceWithFrequency_interval_daysOfTheWeek_daysOfTheMonth_monthsOfTheYear_weeksOfTheYear_daysOfTheYear_setPositions_end_`,
  passing `None` (not `[]`) for an absent part, and
  `EKRecurrenceDayOfWeek.dayOfWeek_weekNumber_(EKWeekday, ordinal)` with ordinal 0 for a
  plain weekday. The 3-argument initializer loses every BY* part.
- **D-08:** Verify-after-write compares a canonical dict field by field: freq, interval,
  sorted `(ordinal, weekday)` tuples, sorted bymonthday / bymonth / byyearday / bysetpos,
  count, until. The dict replaces the bodies of `eventkit.recurrence_signature` and
  `persisted_recurrence_signature`; the names and the adapter call sites stay. Today's
  `(frequency, interval, count)` compare lets a dropped BYDAY pass.
- **D-09:** UNTIL is compared at day granularity (`YYYYMMDD`) on timed events only. All-day
  events keep today's omission (#49); the spike did not test that case.
- **D-10:** A DTSTART that does not satisfy its rule is accepted (RFC 5545 §3.3.10: DTSTART
  counts as the first instance; EventKit agrees). A pure-Python membership check in
  `contracts.py`, over the supported parts only, detects it, and the Pointer summary states
  the extra first occurrence. `python-dateutil` is **not** a runtime dependency: it drops
  such a DTSTART, and it diverges from RFC 5545 on mixed plain/ordinal BYDAY (dateutil
  #1588) and WEEKLY+BYSETPOS (dateutil PR #1575).
- **D-11:** BY* reaches reminders through the shared parser: `recurrenceRules` is on
  `EKCalendarItem` with the same initializer. `eventkit.rrule_text` renders BY* parts. This
  also closes a latent loss: a reminder made in Reminders.app with a BYDAY rule, then
  renamed through `update_reminder`, gets a `RecurrenceRequired` message whose re-send text
  omits BYDAY today. One reminder BY* device test proves the round trip.

### Container ids (CAL-04, REM-06)
- **D-12:** `_event_pointer` and `_reminder_pointer` set `folder = eventkit.container_id(item)`
  — the calendar or list **identifier**, never the title (titles repeat across accounts). It
  is the token `free_busy(calendars=…)`, `create_event` and `update_event` already take.
  `calendars()` and `reminder_lists()` already map id to title; no new tool. The
  `Pointer.folder` comment in `contracts.py` ("None elsewhere") is updated. The value flows
  into snapshots, dry-run previews and create/update returns through the same two functions.

### Reminders store plane (REM-03, REM-04)
- **D-13:** Tags and the parent link are read from the live Reminders sqlite store — the
  largest `Data-*.sqlite` under
  `~/Library/Group Containers/group.com.apple.reminders/Container_v1/Stores` — through
  `runtime.read_via_sqlite` with no fallback. `Z_ENT` is resolved from `Z_PRIMARYKEY` at run
  time, never hardcoded. The tag text is `ZNAME1`; the parent link is `ZPARENTREMINDER`; the
  deletion filter (`ZMARKEDFORDELETION = 0`) applies to the tag row **and** the reminder
  row. The join key is `ZCKIDENTIFIER` = EK `calendarItemIdentifier` (1372/1372 on this
  Mac). The Pointer id stays the EventKit id. A module-level `_FINGERPRINT` (the column set
  in the spike reference, step 6) raises `SchemaDrift` on a mismatch — the
  `mail_index.HEADER_FINGERPRINT` / `notes._FINGERPRINT` pattern.
- **D-14:** The store read lives in a new sidecar, `macos_apps_mcp/adapters/reminders_store.py`;
  only `reminders.py` imports it (the `mail_index.py`-beside-`mail.py` precedent). The store
  path is a function tests can patch. `test_native_seam.py` covers it automatically.
- **D-15:** Tags and the parent link **fold into `reminders()`** (owner, 2026-10-05): each
  Pointer carries `tags` (tuple of str) and `parent` (the parent's EK id) when the store has
  them, emitted only when set. `reminders()` declares "Requires **EventKit** and **Full Disk
  Access**". When the store is unreadable (grant missing, `SchemaDrift`), the read still
  returns the EventKit Pointers and the `read_result` envelope carries a `coverage` flag
  that names the reason — loud, never silent, never an exception that hides the EventKit
  plane. No separate `reminder_subtasks` / `reminder_tags` tools.
- **D-16:** No tag or subtask write exists, in any outcome. The `reminders()`,
  `create_reminder` and `update_reminder` docstrings name the gap. Excluded routes: private
  `setParentID:` / `parentID` (REM-04), Shortcuts App Intents (not id-addressed),
  AppleScript (no tag or parent property), `#tag` text in a title (not a tag).

### Delete and lists (REM-01, REM-02)
- **D-17:** `delete_reminder(id, *, dry_run=True, with_subtasks=False)` mirrors
  `delete_event`: `@_write_tool(snapshot=…)`, the dry-run default comes from the
  registration record's `delete_` class (Phase 1 D-04 — the registry test must catch it),
  audit verb `delete`. After the remove, a gone-check: `_fresh_item(id)` must return `None`,
  else `VerificationFailed`. The same gone-check is **added to `delete_event`**, which has
  none today, so success criterion 3's "same contract" is true.
- **D-18:** Before any delete, the store is read for the reminder's subtasks (the one-parent
  query from the spike reference, step 8). If the store is unreadable, `delete_reminder`
  refuses with the typed error and makes no delete — a blind delete would cascade silently.
- **D-19:** A parent with N subtasks is **refused unless confirmed** (owner, 2026-10-05): a
  typed `NativeError` subclass in the `SpanRequired` shape, raised in the dry run too, that
  names the count and lists the subtasks as Pointers; `with_subtasks=True` clears it. The
  dry-run preview and the confirmation then say "and N subtasks" and list them. Rationale:
  EventKit removes the subtasks at once and cannot see them, so a one-call delete would
  remove N+1 and report 1.
- **D-20:** `Pointer` gains an optional `subtasks: tuple[Pointer, ...]`, emitted only when
  set. `delete_reminder` registers its **own** snapshotter that returns the parent Pointer
  with its subtasks, so the audit before-state records all N+1 and an undo can recreate
  them — as flat reminders, since no public write can re-nest; the receipt says so. The
  snapshotter shared by `update_reminder` / `complete_reminder` does not read the store (a
  missing grant there would silently log `before=None`).
- **D-21:** `complete_reminder` on a parent reports its open subtasks in the result:
  completing a parent leaves them open and linked, and the app's default view hides them.
- **D-22:** `create_reminder_list(name)` is `@_additive_tool` ("Requires **EventKit**"),
  audit verb `create`. The new `EKCalendar` for reminders takes the source of
  `defaultCalendarForNewReminders()`; no `account` parameter. An exact-name duplicate among
  existing lists is refused before the write (it would make every later `list_name=`
  resolution `AmbiguousTarget`). `EKErrorSourceDoesNotAllowCalendarAddDelete` (17) and
  `sourceDoesNotAllowReminders` (24) map to `WriteRefused` naming the source. Verify: the new
  list appears in `reminder_lists()` by id. Apple documents no per-source "allows add" flag,
  so the plan's first device task probes the default source.

### Probes and tests
- **D-23:** Probe-first stays the rule; a probe that overturns a premise is a deliverable.
  Device tasks in the plan: (1) `saveCalendar` on the default reminders source; (2) a
  reminder BY* round trip; (3) the cascade fixture — the owner indents subtasks by hand in
  Reminders.app (EventKit cannot make one), and the executor stops at that owner action; (4)
  the Google 5-alarm drop and the all-day fire day, re-run from the spike harness; (5) the
  six-month expansion. Google tests write into an existing calendar with prefixed titles and
  sweep to `left=0`; no probe targets a family account.
- **D-24:** The six-month occurrence check (CAL-03) uses `python-dateutil` in the `dev`
  dependency group as the RFC 5545 reference, `set(ref) | {dtstart}` (the spike method,
  21/22 shapes exact). The shapes where dateutil diverges (mixed plain/ordinal BYDAY,
  WEEKLY+BYSETPOS) use hand-computed dates.
- **D-25:** Unit tests patch `store` and `run_native` per adapter module — conftest seals
  `run_osascript`, `body_file` and `tracked_run` only, not EventKit or sqlite. The store
  plane gets a `tmp_path` sqlite with the fingerprint columns and `Z_PRIMARYKEY` rows plus
  the patched path function (the `test_notes` pattern). `tests/test_tool_annotations.py`
  `envelope_only` gains `create_reminder_list`; the pointer fakes gain a `calendar()`.
- **D-26:** Records: success criterion 5, REM-03 and PROJECT.md's Reminders line are
  rewritten in this records PR to say subtasks read-only (done with this context). Planning
  records land by PR from the locked `.worktrees/phase-3-records` lane; the main checkout
  never commits.

### Claude's Discretion
- The sidecar module's internal names (`_FINGERPRINT`, the path function, the query helpers).
- The exact class name of the subtasks refusal and the wording of its message.
- Whether the `coverage` text for an unreadable store names the grant or the drifted column.
- Where inside `contracts.py` the DTSTART membership check lives, and its helper names.
- The order of plans, except that the device probes in D-23 open their plan.

### Folded Todos
None matched this phase.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

- `.planning/ROADMAP.md` — Phase 3 block (lines 184–200): goal, success criteria 1–8.
- `.planning/REQUIREMENTS.md` — lines 35–49 (CAL-01..04, REM-01..04, REM-06).
- `.claude/skills/spike-findings-macos-apps-mcp/SKILL.md` — the owner's locked spike
  decisions (2026-09-28); load the skill.
- `.claude/skills/spike-findings-macos-apps-mcp/references/calendar-alarms.md` — spike 008.
- `.claude/skills/spike-findings-macos-apps-mcp/references/calendar-recurrence-allday.md` — spike 003.
- `.claude/skills/spike-findings-macos-apps-mcp/references/reminders-tags-subtasks.md` — spikes 002 and 007.
- `.claude/skills/spike-findings-macos-apps-mcp/sources/003-eventkit-allday-rrule/probe_eventkit.py`
  — the tested `parse` / `to_ek` / `from_ek` (canonical dict, 9-arg initializer).
- `.claude/skills/spike-findings-macos-apps-mcp/sources/002-reminders-tags-route/probe_store.py` — the SQL.
- `.claude/skills/spike-findings-macos-apps-mcp/sources/008-eventkit-alarms/probe_alarms.py` — `verdict()`.
- `.claude/skills/spike-findings-macos-apps-mcp/sources/007-reminder-delete-subtasks/probe_cascade.py`.
  The full spike records (`.planning/spikes/`) are on PRs #223 and #224, not yet on
  `develop`; the skill copy is the one on `develop`.
- `.planning/phases/01-gate-land-the-spiked-architecture-cuts/01-CONTEXT.md` — D-01..D-04
  (dry-run defaults from the registration record) and GATE-06 (audit verbs).
- `.planning/codebase/TESTING.md` — fake and seam conventions.
- GitHub issues #89, #90, #91, #92, #207 (`elfensky/macos-apps-mcp`).
- External, read 2026-10-05: [EKError.Code](https://developer.apple.com/documentation/eventkit/ekerror/code)
  · [🔖](https://linkding.lav.ren/bookmarks?details=154);
  [EKRecurrenceRule init](https://developer.apple.com/documentation/eventkit/ekrecurrencerule/init(recurrencewith:interval:daysoftheweek:daysofthemonth:monthsoftheyear:weeksoftheyear:daysoftheyear:setpositions:end:))
  · [🔖](https://linkding.lav.ren/bookmarks?details=162);
  [Google Calendar events resource](https://developers.google.com/workspace/calendar/api/v3/reference/events)
  · [🔖](https://linkding.lav.ren/bookmarks?details=168);
  [dateutil rrule.py](https://raw.githubusercontent.com/dateutil/dateutil/master/src/dateutil/rrule.py)
  · [🔖](https://linkding.lav.ren/bookmarks?details=156).
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `macos_apps_mcp/runtime.py` `_open_sqlite_ro`, `verify_sqlite_schema`, `read_via_sqlite`
  (lines ~341–492): typed FDA / `SchemaDrift` errors; runs inline when already on the
  worker, so one `run_native` block can read the store and then act through EventKit.
- `macos_apps_mcp/eventkit.py` `container_id` (~45–51): the `Pointer.folder` value.
- `macos_apps_mcp/eventkit.py` `to_recurrence_rule`, `recurrence_signature`,
  `persisted_recurrence_signature`, `rrule_text` (~196–254): widen in place.
- `macos_apps_mcp/errors.py` `SpanRequired` (~77–82), `resolve_container`,
  `verify_persisted` (~124–185): the refusal shape and the verify helpers.
- `macos_apps_mcp/contracts.py` `deletion_result` (~93–100), `Pointer` (~209–247),
  `_RRULE_SUPPORTED` (~305), `Recurrence` (~339–399), `CalendarEventData` (~456–470).
- `macos_apps_mcp/adapters/reminders.py` `_fresh_item` (~119–127): the gone-check primitive.
- `macos_apps_mcp/adapters/calendar.py` `_apply_event` alarm slot (~209–230, #51 comment).

### Established Patterns
- `adapters/calendar.py` ~488–509: a delete whose dry run resolves the span first and raises
  `SpanRequired` — the shape D-19 copies.
- `adapters/calendar.py` ~312–357: field-dict verify-after-write.
- `server.py` ~1207–1214: `delete_event` registration (`snapshot=`, `dry_run=True`).
- `registry.py` ~73–90, ~140–148: audit verb from the name prefix; `delete_*` is the
  removes-content class. `tests/test_registry.py` ~365–377 asserts the dry-run default.
- `adapters/mail_index.py` ~20, ~36 and `adapters/notes.py` ~58: the sidecar-plus-fingerprint
  pattern. `tests/test_notes.py` ~244–260: a `tmp_path` sqlite fixture with fingerprint columns.
- `tests/test_reminders.py` ~141–155 `_patch_read`, `tests/test_calendar.py` ~34–41
  `_fake_event`: the EventKit fakes; none has a `calendar()` yet.
- `tests/conftest.py` ~191–224: what is sealed (osascript, body_file, tracked_run) and the
  patched-path pattern.

### Integration Points
- `server.py` ~277–311 (read tools) and ~1087–1214 (write tools): `alarms` on
  `create_event` / `update_event`; new `delete_reminder`, `create_reminder_list`;
  `reminders()` docstring gains Full Disk Access.
- `contracts.py`: `Recurrence` BY* fields, `CalendarEventData.alarms`, `Pointer.tags`,
  `Pointer.parent`, `Pointer.subtasks`, the DTSTART membership check.
- `adapters/calendar.py` `_event_pointer` (~81–86) and `adapters/reminders.py`
  `_reminder_pointer` (~56–62): `folder`, and `tags` / `parent` on reminders.
- `tests/test_tool_annotations.py` ~111–133 `envelope_only`.
- `tests/test_integration.py` ~30–48: the `created` teardown needs list and parent cleanup
  and the Google prefix sweep.
- `pyproject.toml` `[dependency-groups].dev`: `python-dateutil` (test reference only).
</code_context>

<specifics>
## Specific Ideas

- Alarm docstring: "`alarms` are minutes before the start, as in the Google Calendar API.
  For an all-day event the offset counts from local midnight: `-540` is 09:00 on the day,
  `900` is 09:00 the day before. On a DST-change day the alert shifts an hour, the same as
  Calendar's own alerts. At most 5."
- The subtasks refusal reads like `SpanRequired`: "`<title>` has 3 subtasks (a, b, c).
  Deleting it deletes them too. Call again with `with_subtasks=True`."
- The `RecurrenceRequired` re-send text must round-trip the full rule, BY* included.
- `coverage` on `reminders()` when the store is unreadable: name what is missing ("tags and
  parent links unavailable: …") so a briefing can say so instead of showing flat lists.
</specifics>

<deferred>
## Deferred Ideas

- Alarms on reminders (REM-05) — v2, PROJECT.md.
- A `tag=` filter on `reminders()` — a natural follow-up once `tags` is on the Pointer;
  not in this phase's requirements.
- Nested subtasks, a parent with dozens of subtasks, a delete made in Reminders.app or on
  iPhone, a non-iCloud reminders source — untested by spike 007; this Mac has no "On My
  Mac" source. Note in the tool docstring, do not probe now.
- The real notification on a DST day (08:00 vs 09:00) — next observable 2026-10-25,
  Europe/Brussels; not a phase gate.
- Landing `.planning/spikes/` on `develop` (PRs #223, #224) — records housekeeping outside
  this phase.

### Reviewed Todos (not folded)
None matched this phase.
</deferred>

---

*Phase: 03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub*
*Context gathered: 2026-10-05 (assumptions mode)*
