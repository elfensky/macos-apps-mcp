# Phase 3: EventKit Depth — Calendar Alarms & Recurrence, Reminders CRUD & Subtasks - Research

**Researched:** 2026-10-05
**Domain:** EventKit (PyObjC) Calendar and Reminders writes; read-only Reminders sqlite plane; FastMCP tool surface; pytest seams
**Confidence:** HIGH (decisions locked and spike-proven; four new in-process facts verified this session; a few edge behaviours tagged `[ASSUMED]`)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Alarms (CAL-01, CAL-02)**
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

**Recurrence (CAL-03)**
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

**Container ids (CAL-04, REM-06)**
- **D-12:** `_event_pointer` and `_reminder_pointer` set `folder = eventkit.container_id(item)`
  — the calendar or list **identifier**, never the title (titles repeat across accounts). It
  is the token `free_busy(calendars=…)`, `create_event` and `update_event` already take.
  `calendars()` and `reminder_lists()` already map id to title; no new tool. The
  `Pointer.folder` comment in `contracts.py` ("None elsewhere") is updated. The value flows
  into snapshots, dry-run previews and create/update returns through the same two functions.

**Reminders store plane (REM-03, REM-04)**
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

**Delete and lists (REM-01, REM-02)**
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

**Probes and tests**
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

### Deferred Ideas (OUT OF SCOPE)
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
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CAL-01 | Alarms (minutes-before list) on create/update event, read back by verify-after-write | D-01/D-03/D-04; Code Examples "Alarms"; Pitfalls 1, 2 |
| CAL-02 | All-day and recurring all-day alarms fire on the right day in a non-UTC zone (device-probed first) | D-02/D-05; spike 008 table; device task (4) |
| CAL-03 | BYDAY (ordinals), BYMONTHDAY, BYMONTH; rejects inexpressible shapes; six-month read-back matches RFC 5545 | D-06..D-10; verified: EventKit does NOT validate BY* ranges, so boundary validation is ours (Pitfall 3) |
| CAL-04 | `events()` Pointers carry calendar id in `folder` | D-12; `container_id` exists; fakes need `calendar()` |
| REM-01 | `delete_reminder` (`dry_run=True`, verify-after-write) | D-17..D-20; Pitfalls 6, 7, 8 |
| REM-02 | Create a reminder list | D-22; EK error codes verified (17, 24) |
| REM-03 | Subtasks read-only (`parent` on Pointers) from sqlite | D-13..D-16; `reminders_store.py` pattern |
| REM-04 | Tags read-only from sqlite; no private-API write | D-13..D-16 |
| REM-06 | `reminders()` Pointers carry list id in `folder` | D-12 |
| MAIL-05 | `rollback()` handling (#229) | **Already complete (0.13.1, REQUIREMENTS.md lines 32 and 161). No plan, not researched.** |
| MAIL-06 | Reply-quote read decision (#230) | **Already complete (0.13.1, REQUIREMENTS.md lines 33 and 162). No plan, not researched.** |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

Sources: `/Users/andrei/Developer/macos-apps-mcp/CLAUDE.md` and `.claude/CLAUDE.md`. These carry the same authority as locked decisions.

- Tools in `server.py` are thin dispatch to adapters; no business logic in the tool layer. No ABC, no plugin registry.
- Reads uniform (`get_pointers -> list[Pointer]`); writes per-adapter typed. `Pointer(id, summary, deeplink)` — pointers, not payload.
- All EventKit/native access goes through `runtime.run_native()` (single worker, `max_workers=1`, never widen).
- One adapter module per app; an adapter must not reach into another adapter. Sidecar modules beside an adapter are allowed (`mail_index.py`).
- Three capability tiers gated at registration: read, write (`@_write_tool` / `@_additive_tool`, skipped by `MACOS_APPS_READ_ONLY`), outbound. A gated-off tool is absent, never registered-and-erroring.
- Every id-addressed write registers a snapshotter (`@_write_tool(snapshot=...)`); `tests/test_tool_annotations.py` enforces it.
- Tool docstrings MUST name the macOS permission (`EventKit`, `Full Disk Access`, `Automation`); `test_every_tool_docstring_states_permission_and_is_nontrivial` checks the registered `permission` tuple against the text.
- Errors: typed `NativeError` subclasses with a unique `kind` and agent-directed message; `@_guard` turns `NativeError` and `ValueError` into `ToolError`. Never mask errors with empty results.
- Mail adapters use qualified `runtime.<seam>` imports (not applicable here; Reminders sidecar imports `read_via_sqlite`, which is not in the sealed set).
- Style: ruff `E, F, I, UP, B, SIM`, line length 88, `from __future__ import annotations`, frozen dataclasses for contracts, logging via `logging.getLogger(__name__)`.
- Verification before reporting success: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`. Baseline this session: 1538 passed, 80 deselected in 15.27 s; ruff clean.
- Never run `-m integration` in CI; device tests are run manually. Dry-run path of any send tool makes no native call (not relevant here; `delete_reminder` dry run DOES read, as `delete_event`'s does).
- GSD workflow: all edits happen through a GSD command inside a `.worktrees/<slug>` lane; main checkout never commits.
- Mail is untouched in this phase.

## Summary

Phase 3 is two widenings of one existing plane plus one new read-only plane. EventKit writes gain alarms, BY* recurrence, a reminder delete and a list create. A new sidecar `adapters/reminders_store.py` reads tags and parent links from the Reminders sqlite store. Every decision is locked and spike-proven, so the open work is mechanical: the exact API call shapes, the existing seams that must move together, and the tests that pin the old shapes and will break.

Four facts were verified in-process this session and change how the plan should be cut. (1) EventKit's 9-argument initializer accepts out-of-range BY* values without complaint (BYMONTHDAY 0 and 32, BYMONTH 13, BYYEARDAY 367, BYSETPOS 0, a weekday ordinal of 54, an ordinal on a WEEKLY rule); only `interval=0` raises. Range validation therefore belongs in `Recurrence`, or a garbage rule reaches the store. (2) FastMCP 3.4.7 enforces the return annotation as an output schema: a tool annotated `dict[str, str]` that returns a list value fails with `Output validation error`. `tags` (a list), `subtasks` and the D-21 open-subtasks report cannot ride on tools annotated `dict[str, str]`. (3) `Path.glob` swallows `PermissionError` and returns `[]`, so the "largest `Data-*.sqlite`" lookup would report an FDA denial as "no store found". (4) The tests that pin the old shapes are enumerated below (registry pins, `envelope_only`, two "unsupported RRULE" tests that use BYDAY, `fake_rule`, the pointer fakes, and the `reminders()` list-shape assertions).

Two design consequences deserve the planner's attention. `reminders()` changes wire shape from a bare list to the `read_result` envelope (D-15 mandates it); that breaks any consumer that indexes the result as a list and is flagged under Open Questions. The "extra first occurrence" note (D-10) can only be stated on the Pointer returned by `create_event` / `update_event`, because a Pointer built from a later occurrence cannot see DTSTART.

**Primary recommendation:** Cut the phase as seven seams in this order: pure contracts, EventKit helpers, calendar adapter, store sidecar, reminders adapter, server tools plus pinned-test updates, then device verification with the D-23 probes first. Keep all BY* range and RFC-combination validation in `contracts.Recurrence`.

## Architectural Responsibility Map

This is a local macOS server, not a web stack. The tiers are the project's own layers.

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Tool surface, docstrings, return annotations, tier gating | `server.py` (tool layer) | `registry.py` | Thin dispatch only; the registration record states verb, permission, snapshotter |
| RRULE parsing, BY* validation, DTSTART membership, alarm count/type validation | `contracts.py` (pure data) | — | No PyObjC; unit-testable with plain values; `ValueError` caught by `@_guard` |
| `EKRecurrenceRule` / `EKAlarm` construction, canonical read-back dict, `rrule_text` | `eventkit.py` | — | The only module that owns value-object coercion |
| Event/reminder/list writes and verify-after-write | `adapters/calendar.py`, `adapters/reminders.py` | `errors.py` (`verify_persisted`, `refused_write`) | One adapter per app; EventKit calls inside `run_native` |
| Tags and parent link read, subtask query, fingerprint | `adapters/reminders_store.py` (sqlite plane) | `runtime.read_via_sqlite` | Read-only, FDA-gated; EventKit keeps every write |
| Before-state for audit | `audit.AuditMiddleware` via `Snapshotter` | adapters | Middleware calls `snapshot(id)` before the write |
| Pointer wire shape (`folder`, `tags`, `parent`, `subtasks`) | `contracts.Pointer.as_dict` | — | The one serialization shared by tool results and audit |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pyobjc-framework-EventKit | 12.2.2 installed [VERIFIED: `uv pip list`] | `EKAlarm`, `EKRecurrenceRule`, `EKCalendar`, `EKEventStore` | Already the project's EventKit bridge (`pyproject.toml` `>=10.0`) |
| fastmcp | 3.4.7 installed [VERIFIED: `uv pip list`] | Tool registration; enforces output schema from return annotation | Already the server framework |
| sqlite3 (stdlib) | Python 3.14.5 in the venv [VERIFIED: `uv run python -c "import sys"`] | Read-only Reminders store via `runtime.read_via_sqlite` | Existing plane (`notes.py`, `mail_index.py`); no ORM |
| pytest | 9.1.1 installed [VERIFIED: `uv pip list`] | Unit and integration runner | Existing; `addopts = "-m 'not integration'"` |

The project declares Python 3.11-3.13 in classifiers; the local venv is 3.14.5. Both are in use; nothing in this phase depends on the difference.

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| python-dateutil | `[ASSUMED]` 2.9.0.post0 (registry reports a 2024-03-01 publish date) | RFC 5545 reference for the six-month expansion test and the DTSTART-membership unit table | `dev` dependency group ONLY (D-24); never a runtime dependency |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Pure-Python DTSTART membership (D-10) | `dateutil.rrule` at runtime | Locked out: it drops a non-matching DTSTART and diverges on mixed BYDAY and WEEKLY+BYSETPOS |
| One envelope-returning `reminders()` (D-15) | Separate `reminder_tags` / `reminder_subtasks` tools | Locked out by D-15 |

**Installation:**
```bash
uv add --dev python-dateutil     # only after the human-verify checkpoint below
```

**Version verification:** `uv pip index` does not exist in this uv; the legitimacy seam returned the registry signals instead.

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| python-dateutil | PyPI | latest release published 2024-03-01 | not exposed by PyPI (seam: `weeklyDownloads: null`) | github.com/dateutil/dateutil | SUS (reason: `unknown-downloads` only) | Flagged — planner inserts `checkpoint:human-verify` before `uv add --dev python-dateutil` |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** python-dateutil `[WARNING: flagged as suspicious — verify before using.]`. The only signal is that PyPI publishes no download count, so the seam cannot rate it. It is a long-established package with a source repo, named in the owner's locked D-24 and in the spike probe. The owner confirms at the checkpoint; it stays dev-only.

[VERIFIED: `gsd-tools query package-legitimacy check --ecosystem pypi python-dateutil`, run this session]

## Architecture Patterns

### System Architecture Diagram

```
 MCP client (Claude Code session)
        │ tool call
        ▼
 server.py  @_write_tool / @_additive_tool / @_read_tool  (thin dispatch, @_guard)
   │  registry.TOOLS record: tier, verb, permission, snapshot, removes_content
   │
   ├─ AuditMiddleware ──► snapshot(id) BEFORE the write ──► audit.jsonl (before/after)
   │
   ▼
 contracts.py (pure)
   parse_recurrence → Recurrence(BY*, validated)   CalendarEventData(alarms ≤5, validated)
   deletion_result / read_result / Pointer.as_dict
   │
   ▼
 adapters/calendar.py            adapters/reminders.py ──────────────┐
   _apply_event: alarms, rule      _apply_reminder: rule             │ import (only reminders.py)
   verify: alarms multiset,        create_reminder_list              ▼
           canonical rule          delete_reminder:             adapters/reminders_store.py
   delete_event + gone-check         store read → refuse/confirm      path fn (patchable)
   _event_pointer(folder)            → removeReminder → gone-check    _FINGERPRINT
   │                                 _reminder_pointer(folder,        tags_and_parents()
   │                                   tags, parent)                  subtasks_of(id)
   ▼                                 │                                │
 eventkit.py (run_native worker)     │                                ▼
   to_recurrence_rule (9-arg)        │                       runtime.read_via_sqlite
   canonical_from_rule / rrule_text  │                       (_open_sqlite_ro mode=ro,
   container_id                      │                        verify_sqlite_schema)
   ▼                                 ▼                                │
 EKEventStore (one store, one worker thread)            Reminders Data-*.sqlite (FDA)
```

### Recommended Project Structure
```
macos_apps_mcp/
├── contracts.py                  # Recurrence BY*, validation, membership; CalendarEventData.alarms;
│                                 #   Pointer tags/parent/subtasks; deletion_result(subtasks=)
├── errors.py                     # + subtasks-refusal NativeError subclass (SpanRequired shape)
├── eventkit.py                   # to_recurrence_rule (9-arg), canonical readback, rrule_text
├── adapters/
│   ├── calendar.py               # alarms in _apply_event/_verify_event, folder, delete gone-check
│   ├── reminders.py              # delete_reminder, create_reminder_list, tags/parent join, snapshotters
│   └── reminders_store.py        # NEW sidecar: path fn, _FINGERPRINT, two queries
└── server.py                     # alarms param; delete_reminder; create_reminder_list; reminders() envelope
tests/
├── test_reminders_store.py       # NEW: tmp_path sqlite fixture (test_notes pattern)
├── _fakes.py                     # fake_rule gains BY* attributes (default None/empty)
└── test_integration.py           # device tests + teardown (list, Google prefix sweep)
```

### Pattern 1: Alarms through `_apply_event` (D-01, D-03, D-04)
**What:** Build relative alarms only; `None` leaves them untouched, `[]` clears, a non-empty tuple replaces.
**When to use:** `create_event` and `update_event`.
**Example:**
```python
# Source: spike 008 (references/calendar-alarms.md step 1), EKAlarm API verified in-process
if data.alarms is not None:
    alarms = [EK.EKAlarm.alarmWithRelativeOffset_(-m * 60.0) for m in data.alarms]
    e.setAlarms_(alarms or None)          # None, never [], clears
```
Verify (only when set):
```python
if data.alarms is not None:
    got = fresh.alarms() or []
    expected["alarms"] = sorted(-m for m in data.alarms)               # seconds/60, signed
    actual["alarms"] = sorted(round(a.relativeOffset() / 60) for a in got)
    expected["absolute_alarms"] = 0
    actual["absolute_alarms"] = sum(1 for a in got if a.absoluteDate() is not None)
```
Sign convention: the tool takes positive minutes-before; `relativeOffset` is negative-before. Compare in one convention (above uses EventKit's) so the mismatch message does not confuse the caller. [VERIFIED: in-process `alarmWithRelativeOffset_(-900.0)` reads `relativeOffset() == -900.0`, `absoluteDate() is None`]

### Pattern 2: Build and read back a rule through one canonical dict (D-07, D-08)
**What:** `Recurrence` (pure) to a canonical dict to the 9-arg initializer; the persisted rule reads back into the same dict shape; `verify_persisted` compares dict to dict.
**Example:**
```python
# Source: .claude/skills/spike-findings-macos-apps-mcp/sources/003-eventkit-allday-rrule/probe_eventkit.py (to_ek / from_ek, tested)
WD = {"SU": 1, "MO": 2, "TU": 3, "WE": 4, "TH": 5, "FR": 6, "SA": 7}   # EKWeekday
dow = [EK.EKRecurrenceDayOfWeek.dayOfWeek_weekNumber_(WD[wd], n) for n, wd in r.byday]
rule = EK.EKRecurrenceRule.alloc().initRecurrenceWithFrequency_interval_daysOfTheWeek_daysOfTheMonth_monthsOfTheYear_weeksOfTheYear_daysOfTheYear_setPositions_end_(
    _FREQUENCIES[r.frequency], r.interval,
    dow or None, list(r.bymonthday) or None, list(r.bymonth) or None,
    None, list(r.byyearday) or None, list(r.bysetpos) or None, end)
```
[VERIFIED: in-process this session — the selector responds; a MONTHLY `2TU` rule round-trips as `daysOfTheWeek() == [(weekNumber 2, day 3)]`, absent parts read back as `None`; `BYSETPOS=-1` reads back `[-1]`; `firstDayOfTheWeek()` reads 2]

### Pattern 3: Store sidecar beside the adapter (D-13, D-14)
**What:** Mirror `notes._FINGERPRINT` plus `read_via_sqlite` with no fallback. One query returns all live tag rows and all live child-to-parent pairs; the adapter joins by EK id in Python. One further query answers "subtasks of this parent".
**Example:**
```python
# Source: references/reminders-tags-subtasks.md steps 2-6, 8; runtime.read_via_sqlite signature read this session
_FINGERPRINT = {
    "Z_PRIMARYKEY": {"Z_ENT", "Z_NAME"},
    "ZREMCDOBJECT": {"Z_ENT", "ZNAME1", "ZREMINDER3", "ZMARKEDFORDELETION"},
    "ZREMCDREMINDER": {"Z_PK", "ZCKIDENTIFIER", "ZPARENTREMINDER", "ZMARKEDFORDELETION"},
}
_TAGS = """SELECT r.ZCKIDENTIFIER, h.ZNAME1 FROM ZREMCDOBJECT h
  JOIN ZREMCDREMINDER r ON r.Z_PK = h.ZREMINDER3
  WHERE h.Z_ENT = (SELECT Z_ENT FROM Z_PRIMARYKEY WHERE Z_NAME = 'REMCDHashtag')
    AND h.ZMARKEDFORDELETION = 0 AND r.ZMARKEDFORDELETION = 0"""
_PARENTS = """SELECT c.ZCKIDENTIFIER, p.ZCKIDENTIFIER FROM ZREMCDREMINDER c
  JOIN ZREMCDREMINDER p ON p.Z_PK = c.ZPARENTREMINDER
  WHERE c.ZMARKEDFORDELETION = 0 AND p.ZMARKEDFORDELETION = 0"""
_SUBTASKS_OF = """SELECT c.ZCKIDENTIFIER FROM ZREMCDREMINDER c
  JOIN ZREMCDREMINDER p ON p.Z_PK = c.ZPARENTREMINDER
  WHERE p.ZCKIDENTIFIER = ? AND c.ZMARKEDFORDELETION = 0 AND p.ZMARKEDFORDELETION = 0"""
```
`read_via_sqlite(path, _FINGERPRINT, query)` runs inline when already on the worker, so one `run_native` block can read the store and then act through EventKit. [VERIFIED: `runtime.py` `read_via_sqlite`, `work() if on_worker() else run_native(work)`]

### Pattern 4: Refusal in the `SpanRequired` shape (D-19)
`calendar.delete_event` resolves the span before the `dry_run` branch, so the refusal fires in the dry run too. Copy that order: resolve the target, read subtasks, raise if `subtasks and not with_subtasks`, then branch on `dry_run`. A new `NativeError` subclass with its own `kind` (suggested `subtasks_required`) keeps `errors.py` the one taxonomy. [VERIFIED: `adapters/calendar.py` `delete_event`, `errors.py` `SpanRequired`]

### Pattern 5: Own snapshotter object for `delete_reminder` (D-20)
`registry.ToolRecord.snapshot` holds a `Snapshotter` object and `AuditMiddleware` calls `source.snapshot(args["id"])`; it swallows any exception into `before=None`. So the delete tool needs a second small object with a `snapshot(ident)` method (for example a tiny class in `reminders.py`, instantiated in `server.py`) that returns the parent Pointer with `subtasks`. The shared `RemindersAdapter.snapshot` stays EventKit-only. [VERIFIED: `audit.py` `_safe_snapshot`, `on_call_tool`]

### Suggested plan seams (planner owns the cut)
1. **Device probes plan (opens first):** D-23 probes 1 (`saveCalendar`), 2 (reminder BY*), 4 (Google 5-alarm and all-day fire day from the spike harness), 5 (six-month expansion). Probe 3 (cascade fixture) needs the owner to indent subtasks by hand, so it goes in a plan of its own at the end, where the executor stops at the owner action.
2. **Pure contracts:** `Recurrence` BY* + validation + membership check; `CalendarEventData.alarms`; `Pointer` fields; `deletion_result` subtasks; new error class.
3. **eventkit.py + calendar adapter:** 9-arg builder, canonical dict, `rrule_text`, alarms, folder, `delete_event` gone-check.
4. **Store sidecar + reminders adapter:** fingerprint, queries, tags/parent join with `coverage`, `delete_reminder`, `create_reminder_list`, snapshotters, `complete_reminder` report.
5. **Server + pinned tests + docs:** tools, annotations, registry pins, README/docstrings.

### Anti-Patterns to Avoid
- **Trusting EventKit to reject bad BY* values:** it does not (Pitfall 3). Validate in `Recurrence`.
- **Annotating a tool `dict[str, str]` and returning a list value:** FastMCP rejects it (Pitfall 4). Use `dict`.
- **Calling `store_path()` outside the degrade handler:** its exceptions escape `read_via_sqlite`'s own `_STORE_UNAVAILABLE` handling (Pitfall 5).
- **Reading the store per reminder:** two queries per `reminders()` call, joined in Python.
- **`from ..runtime import run_osascript` style imports:** not needed here; `from ..runtime import read_via_sqlite` is allowed (it is not in `test_native_seam._SEAM`).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Read-only sqlite open, FDA classification, schema check | A new opener or PRAGMA check | `runtime.read_via_sqlite`, `_open_sqlite_ro`, `verify_sqlite_schema` | Typed `FullDiskAccessDenied` / `SchemaDrift`, bound `pragma_table_info`, runs on the worker |
| Persisted-vs-requested diff | A custom comparer | `errors.verify_persisted(entity, expected, actual)` | Names every mismatched field; already used by both adapters |
| Container resolution by id or name | A new matcher for the list name | `errors.resolve_container` | Id-first, `AmbiguousTarget` with candidate ids (#55) |
| Store-refused-a-write error text | A new message | `errors.refused_write(what, noun, err)` | One wording for every EventKit write |
| Bounded read wire shape with `coverage` | A hand-built dict | `contracts.read_result(results, coverage=...)` | The one envelope, with one test |
| Delete wire shape | A hand-built dict | `contracts.deletion_result` (extend it) | One shape for every delete tool (C5d) |
| Free-text hygiene | A new sanitizer | `text.clean_summary` / `text.sanitize_line` for tag text | Tags are user text that reaches the model context |
| RFC 5545 expansion | A recurrence expander | `python-dateutil` in the test group only | The expansion test is a reference oracle, not shipped code |

**Key insight:** the single hand-written algorithm this phase needs is the one-date DTSTART membership check (D-10). Everything else already has a seam.

## Runtime State Inventory

Not a rename or migration phase. Omitted.

## Common Pitfalls

### Pitfall 1: Alarm sign and the all-day base
**What goes wrong:** the tool takes positive minutes-before; `EKAlarm` takes negative seconds. An all-day `9am the day before` is `900`, not `1440`.
**Why it happens:** relative offsets for an all-day event count from local midnight (#51).
**How to avoid:** one conversion site (`-m * 60.0`), a docstring with both examples, a unit test that feeds `-540` and `900` and reads the built `EKAlarm` offsets back (`+32400.0` and `-54000.0` seconds; see Code Examples).
**Warning signs:** a verify mismatch showing the same magnitudes with opposite signs.

### Pitfall 2: Alarms on a timed event with a negative value, and duplicates
**What goes wrong:** D-02 allows negatives "for that case" (all-day). For a timed event a negative minutes value is an alarm after the start. Duplicate offsets were never probed.
**How to avoid:** in `CalendarEventData.__post_init__` reject a negative value when `all_day` is false, and reject duplicate offsets, both with an agent-directed `ValueError`. Reject non-int values and `bool`. `[ASSUMED]` — these two refusals are policy beyond D-01..D-05; confirm with the owner (Assumptions Log A3, A4).
**Warning signs:** a Google calendar silently re-ordering or deduping alarms after the save.

### Pitfall 3: EventKit accepts out-of-range BY* values
**What goes wrong:** the 9-argument initializer returned an object for BYMONTHDAY `0` and `32`, BYMONTH `13`, BYYEARDAY `367`, BYSETPOS `0`, a weekday ordinal `54`, an ordinal on a WEEKLY and a DAILY rule, and BYMONTHDAY `-31`. Only `interval=0` raised (`ValueError: NSInvalidArgumentException - Interval must be greater than 0`). [VERIFIED: in-process run of 11 cases this session; value objects only, no store]
**Why it happens:** the initializer does not validate; what the store does with such a rule is unknown.
**How to avoid:** validate in `Recurrence.__post_init__` / `from_rrule`: BYMONTHDAY in -31..-1 or 1..31; BYMONTH 1..12; BYYEARDAY -366..-1 or 1..366; BYSETPOS the same; BYDAY ordinal 0 or in -53..-1 / 1..53; weekday code in SU..SA. Also reject, naming the combination: an ordinal BYDAY unless FREQ is MONTHLY or YEARLY; BYSETPOS with no other BY* part (RFC 5545: BYSETPOS must accompany another BYxxx part [CITED: https://datatracker.ietf.org/doc/html/rfc5545#section-3.3.10 · [🔖 2026-10-05](https://linkding.lav.ren/bookmarks?details=182)]). The further RFC combination bans (BYMONTHDAY with WEEKLY, BYYEARDAY with DAILY/WEEKLY/MONTHLY) are `[ASSUMED]` from training: the fetched RFC text was truncated at those lines.
**Warning signs:** a read-back dict that equals the request but expands to nothing.

### Pitfall 4: A list value under a `dict[str, str]` return annotation
**What goes wrong:** FastMCP 3.4.7 builds the output schema from the annotation and validates the result. `-> dict[str, str]` returning `{"tags": ["a", "b"]}` raises `ToolError: Output validation error: ['a', 'b'] is not of type 'string'`; `-> list[dict[str, str]]` fails the same way; `-> dict` passes. [VERIFIED: in-process FastMCP client run this session]
**Why it happens:** `create_reminder`, `update_reminder`, `complete_reminder`, `create_event`, `update_event` and `reminders()` are annotated with `str`-only dicts today.
**How to avoid:** `reminders()` becomes `-> dict` (the envelope). `complete_reminder` (D-21 open-subtasks report) and `delete_reminder` (`-> dict`, already) must return `dict`. `create_reminder` / `update_reminder` / `create_event` / `update_event` keep `dict[str, str]` only while their Pointer carries `str` fields: `folder` is a `str` (safe); do NOT put `tags`, `subtasks` or the extra-first-occurrence structure into those returns. If the adapter attaches `tags` to the create/update Pointer, widen the annotation to `dict`.
**Warning signs:** a unit test that calls `srv.reminders()` directly passes while the in-process `Client.call_tool` fails; add one client-level test per changed tool.

### Pitfall 5: `Path.glob` swallows `PermissionError`; the path function runs outside the degrade handler
**What goes wrong:** on a directory the process cannot read, `Path.glob("Data-*.sqlite")` returns `[]` (no exception); `os.scandir` on the same directory raises `PermissionError`. [VERIFIED: in-process run on a `chmod 000` directory, Python 3.14.5]. A path function written with `glob` and `max(...)` would either raise `ValueError` on an empty sequence or report "no store" for an FDA denial. And because the path is an argument to `read_via_sqlite`, an exception from the path function escapes the function's own `_STORE_UNAVAILABLE` handling.
**How to avoid:** list the directory with `os.scandir` (or `Path.iterdir`); map `PermissionError` to `FullDiskAccessDenied`, `FileNotFoundError` and an empty directory to a bare `NativeError` ("Reminders store not found"). In `reminders()` wrap BOTH the path call and `read_via_sqlite` in one `try`, catching `FullDiskAccessDenied`, `SchemaDrift` and bare `NativeError`, and fold the reason into `coverage`. Whether macOS raises `PermissionError` on this specific Group Container directory under a missing grant `[ASSUMED]`; the integration test in the plan should observe it with FDA withheld, or the unit test should fake it.
**Warning signs:** `coverage` text saying "not found" on a Mac where Reminders is installed.

### Pitfall 6: `delete_event`'s gone-check must be occurrence-aware
**What goes wrong:** D-17 says `_fresh_item(id)` for reminders. For events `calendarItemWithIdentifier_(base)` still finds the series master after a `this-event` delete of one occurrence, so a base-id check would false-fail every recurring delete.
**How to avoid:** for events re-run `_resolve_event(s, ident)` and require `ValueError` (occurrence gone). A single event and a `future-events` delete both end with that occurrence unresolvable. Add the gone-check after `removeEvent_span_commit_error_` and before `deletion_result(ident, None)`. Add a device test for a single event, a `this-event` delete and a `future-events` delete.
**Warning signs:** `VerificationFailed` on a recurring delete that actually worked.

### Pitfall 7: The cascade makes a successful parent delete look like a 1-item delete
**What goes wrong:** EventKit removes the parent and all its subtasks at once and reports one reminder. Subtasks stay linked as tombstones (`ZMARKEDFORDELETION = 1`).
**How to avoid:** read subtasks first (the `_SUBTASKS_OF` query filters tombstones), refuse without `with_subtasks=True`, put all N+1 in the audit snapshot. The spike trail shows EventKit returns `None` for the parent and both children at t=0 after the remove [VERIFIED: `sources/007-reminder-delete-subtasks/results-cascade.json`, trail A], so the immediate gone-check is sound for the parent. Build subtask Pointers from `calendarItemWithIdentifier_(sub_id)`; EventKit does fetch app-made subtasks by id (the probe's `ek_items` listed `A.1` and `A.2`). If a store row has no EK item (store ahead of EventKit), emit a Pointer with the id and a clear summary rather than dropping it.
**Warning signs:** an audit record whose `before.subtasks` is shorter than the cascade.

### Pitfall 8: A dry run still reads the store, and a failed store read must refuse
**What goes wrong:** D-18 refuses when the store is unreadable. If the subtask read is skipped in the dry run, the preview lies about the blast radius.
**How to avoid:** read in both paths, before the `dry_run` branch. The audit middleware also calls the delete snapshotter before the tool body, so the store is read twice per call; this matches the existing two-read pattern for `delete_draft` (accepted in the `audit.py` comment) and is cheap here.

### Pitfall 9: `Pointer` is a frozen, slotted dataclass
**What goes wrong:** the "extra first occurrence" note and the join of `tags` / `parent` cannot mutate a Pointer.
**How to avoid:** give `_reminder_pointer(item, *, tags=None, parent=None)` keyword arguments, and use `dataclasses.replace(pointer, summary=...)` for the DTSTART note.
**Where the note can live:** only on the Pointer returned by `create_event` / `update_event`. A Pointer built from a later occurrence in `events()` cannot see DTSTART (it holds the occurrence's `startDate`), so a read cannot state the extra first occurrence. Say so in the `events()` docstring or leave the read silent. [VERIFIED by reading `_event_pointer` / `_resolve_event`]

### Pitfall 10: UNTIL is compared only for timed events; `recurrence_signature` needs a switch
**What goes wrong:** D-09 compares `until` for timed events only; the all-day omission (#49) stays. Reminders were not tested for UNTIL either.
**How to avoid:** give `recurrence_signature` and the persisted reader an `include_until: bool` argument; the calendar adapter passes `not data.all_day`; the reminders adapter passes `False` (untested; keep today's omission). `[ASSUMED]` for the reminders choice; confirm with the device reminder BY* round trip (probe 2) and widen only if it matches.

### Pitfall 11: Existing tests pin the old shapes (the planner must edit them in the same plan as the code)
Edit list, each verified by reading the file this session:
- `tests/test_registry.py` `_DEVELOP_ADDITIVE` (+`create_reminder_list`), `_DEVELOP_DESTRUCTIVE` (+`delete_reminder`), `_DEVELOP_PERMISSION` (+two tools, `reminders` becomes a 2-tuple), the `removes_content_tools()` literal (+`delete_reminder`), and the "65-entry" / "exactly the seven tools" comments. These are equality pins, so they fail the moment the tools register.
- `tests/test_tool_annotations.py` `envelope_only` (+`create_reminder_list`; `delete_reminder` has its own snapshotter so it is NOT envelope-only).
- `tests/test_contracts.py:112` and `tests/test_server.py:560`: both use `FREQ=WEEKLY;BYDAY=MO` as the "unsupported RRULE" example. BYDAY becomes supported, so switch both to `BYWEEKNO` and add a per-name rejection test for BYHOUR, BYMINUTE, BYSECOND, WKST.
- `tests/_fakes.py` `fake_rule(freq, interval, count)` has three attributes; the canonical read-back calls `daysOfTheWeek()`, `daysOfTheMonth()`, `monthsOfTheYear()`, `daysOfTheYear()`, `setPositions()`, `weeksOfTheYear()`, `recurrenceEnd().endDate()`. Extend it with defaults (`None`), keeping the old call signature. Seven call sites use it.
- `tests/test_eventkit.py` lines 101-164 assert the tuple signature `(int(freq), interval, count)`, `rrule_text` text, and signature agreement; rewrite for the dict.
- `tests/test_calendar.py` `_fake_event` and `_fake_persisted_event`, and `tests/test_reminders.py` `_fake_reminder`: add `calendar=lambda: SimpleNamespace(calendarIdentifier=lambda: "C-1")`. `container_id` returns `None` when `calendar()` is `None`, so one test should cover a `None` calendar (folder omitted).
- `tests/test_server.py:102` and `:994-1035`: `reminders()` returns the envelope; `_FakeSource.get_pointers` returns a list, so the fake needs a `reminders_read`-style method (whatever the adapter exposes) and the assertions change from `== [{...}]` to `["results"]`. The `UNTRUSTED_NOTICE` middleware tests keep working because the notice rides `content[0]`.
- `README.md:77` states that BYDAY is rejected; update. `contracts.py:363` docstring and the `Pointer.folder` comment too.

### Pitfall 12: The `reminders()` wire shape changes
`reminders()` returns `list[dict]` today and must return `{results, coverage?}` (D-15). Any consumer that indexes the result as a list breaks (the life-cockpit vault caller is the project's primary consumer). D-15 is locked, so ship it; see Open Question 1.

## Code Examples

### Alarm unit test shape (no native call)
```python
# EKAlarm is a value object (verified in-process): buildable off the worker, no store/TCC.
def test_all_day_alarm_offsets():
    # "09:00 on the day" = -540 min before midnight start => +540 min after => +32400 s
    assert EK.EKAlarm.alarmWithRelativeOffset_(-(-540) * 60.0).relativeOffset() == 32400.0
    # "09:00 the day before" = 900 min before midnight => -54000 s
    assert EK.EKAlarm.alarmWithRelativeOffset_(-900 * 60.0).relativeOffset() == -54000.0
```

### Canonical read-back (replaces both signature bodies)
```python
# Source: probe_eventkit.py from_ek(), adapted; names stay recurrence_signature / persisted_recurrence_signature
def _canonical_from_rule(r, *, include_until: bool) -> dict:
    names = {v: k for k, v in WD.items()}
    end = r.recurrenceEnd()
    until = None
    if include_until and end is not None and end.endDate() is not None:
        until = from_nsdate(end.endDate()).strftime("%Y%m%d")
    ints = lambda xs: sorted(int(x) for x in (xs or []))
    return {
        "freq": int(r.frequency()), "interval": int(r.interval()),
        "byday": sorted((int(d.weekNumber()), names[int(d.dayOfTheWeek())])
                        for d in (r.daysOfTheWeek() or [])),
        "bymonthday": ints(r.daysOfTheMonth()), "bymonth": ints(r.monthsOfTheYear()),
        "byyearday": ints(r.daysOfTheYear()), "bysetpos": ints(r.setPositions()),
        "count": int(end.occurrenceCount()) if end is not None else 0,
        "until": until,
    }
```
The requested-side builder from `Recurrence` produces the same keys with the same types (`freq` as `int(_FREQUENCIES[...])`, ordinal 0 for a plain weekday). Both sides must produce identical key sets or `verify_persisted` reports a spurious mismatch.

### Reminder-list create (D-22)
```python
# Source: probe_cascade.py setup() (worked on this Mac's default reminders source, spike 007);
#         EKError codes verified in-process this session
def create_reminder_list(self, name: str) -> Pointer:
    def work():
        s = store()
        if any(c.title() == name for c in s.calendarsForEntityType_(EK.EKEntityTypeReminder)):
            raise ValueError(f"a reminder list named {name!r} already exists ...")
        default = s.defaultCalendarForNewReminders()
        if default is None:
            raise WriteRefused("no default reminders account ...")
        cal = EK.EKCalendar.calendarForEntityType_eventStore_(EK.EKEntityTypeReminder, s)
        cal.setTitle_(name)
        cal.setSource_(default.source())
        ok, err = s.saveCalendar_commit_error_(cal, True, None)
        if not ok:
            code = int(err.code()) if err is not None else None
            if code in (EK.EKErrorSourceDoesNotAllowCalendarAddDelete,   # 17
                        EK.EKErrorSourceDoesNotAllowReminders):          # 24
                raise WriteRefused(f"{default.source().title()!r} does not allow ...")
            raise refused_write("reminder list create", "account", err)
        ident = cal.calendarIdentifier()
        if ident not in {c.calendarIdentifier()
                         for c in s.calendarsForEntityType_(EK.EKEntityTypeReminder)}:
            raise VerificationFailed(...)
        return _list_pointer(cal)
    return run_native(work)
```
EK error constants: `EKErrorSourceDoesNotAllowCalendarAddDelete == 17`, `EKErrorSourceDoesNotAllowReminders == 24`, `EKErrorCalendarHasNoSource == 14`, `EKErrorCalendarSourceCannotBeModified == 15`, `EKErrorCalendarIsImmutable == 16`, `EKErrorCalendarDoesNotAllowReminders == 23` [VERIFIED: `import EventKit` in-process this session]. Consider also mapping 14, 15 and 16 to `WriteRefused` (adjacent create-a-calendar failures); that is an extension beyond D-22, harmless and cheap. `err.code()` is the standard `NSError` accessor `[ASSUMED]` — the existing code passes `err` straight into a message and never reads `.code()`; the probe in task (1) should confirm it.

### `reminders()` degrade (D-15)
```python
# in RemindersAdapter: one run_native work(), EventKit first, store second, never raising past EventKit
try:
    tags, parents = reminders_store.tags_and_parents()      # path fn + read_via_sqlite inside
    coverage = None
except (FullDiskAccessDenied, SchemaDrift, NativeError) as e:   # order: subclasses first is irrelevant, all are NativeError
    tags, parents = {}, {}
    coverage = f"tags and parent links unavailable: {e}"
return read_result(pointers, coverage=coverage)
```
Catching the base `NativeError` here is deliberate: the store plane is optional enrichment; EventKit errors raised earlier in `work()` are not inside this `try`.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| 3-argument `initRecurrenceWithFrequency_interval_end_` | 9-argument initializer with BY* slots | This phase (D-07) | The 3-argument form loses every BY* part |
| `(frequency, interval, count)` verify | Canonical dict compare | This phase (D-08) | A dropped BYDAY no longer passes |
| `reminders()` bare list | `read_result` envelope | This phase (D-15) | Wire shape change (Pitfall 12) |
| `delete_event` without a gone-check | Gone-check added (D-17) | This phase | Success criterion 3's "same contract" becomes true |

**Deprecated/outdated:**
- `EKReminder.parentReminder`: does not exist in the public SDK or the runtime; no subtask write (REM-04, spike 002).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | macOS raises `PermissionError` (not `FileNotFoundError`) when listing the Reminders Group Container without FDA | Pitfall 5 | `coverage` names the wrong reason; handled by also catching bare `NativeError` |
| A2 | RFC 5545 bans BYMONTHDAY with WEEKLY and BYYEARDAY with DAILY/WEEKLY/MONTHLY (training memory; fetched text truncated) | Pitfall 3 | A valid shape rejected, or an invalid one saved; confirm against RFC 5545 §3.3.10 |
| A3 | Reject negative alarm minutes on a timed event | Pitfall 2 | A legitimate "alert after start" request refused; owner confirms |
| A4 | Reject duplicate alarm offsets (never probed; EventKit or CalDAV may merge them) | Pitfall 2 | Needless refusal if duplicates are harmless; or an unseen dedupe if allowed |
| A5 | Keep the UNTIL omission for reminders (D-09 names timed events only) | Pitfall 10 | A changed UNTIL on a reminder passes verify; probe 2 can widen it |
| A6 | `err.code()` returns the `EKErrorDomain` integer for `saveCalendar_commit_error_` failures | Code Examples | Code-based mapping to `WriteRefused` misfires; probe 1 confirms |
| A7 | python-dateutil latest release is 2.9.0.post0 | Standard Stack | None (dev-only; `uv add` resolves the version) |
| A8 | The Reminders store path and column names hold on later macOS releases | Pattern 3 | `SchemaDrift` fires; the fingerprint is the guard (spike constraint) |
| A9 | `complete_reminder` on a parent should complete anyway when the store is unreadable, with the open-subtask check marked unavailable | Open Question 2 | Owner may prefer a refusal |

## Open Questions

1. **`reminders()` list-to-envelope wire change**
   - What we know: D-15 mandates the `read_result` envelope; `tests/test_server.py` and the cockpit consumer expect a list today.
   - What's unclear: whether the life-cockpit vault caller indexes the result as a list.
   - Recommendation: ship per D-15, state the new shape at the top of the `reminders()` docstring, and have the plan add an explicit note for the cockpit side. If the owner wants to avoid the break, the alternative is a `coverage`-carrying Pointer-level field, which D-15 excludes.

2. **`complete_reminder` when the store is unreadable**
   - What we know: D-21 says it reports open subtasks; D-18 refuses a delete on an unreadable store.
   - What's unclear: whether a completion (non-destructive, reversible) should also refuse.
   - Recommendation: complete anyway and return `open_subtasks_unchecked` with the reason (loud, not silent); a completion is undone by uncompleting. Confirm with the owner (A9).

3. **Interval / BYSETPOS membership scope for `FREQ=WEEKLY`**
   - What we know: dateutil diverges on WEEKLY+BYSETPOS; the spike hand-computed those dates; EventKit's `firstDayOfTheWeek()` read 2 (Monday) on a default-built rule.
   - What's unclear: whether a CalDAV round trip preserves that week start.
   - Recommendation: the membership function returns `True`/`False` for decidable shapes and the Pointer states the extra occurrence only on `False`; for WEEKLY+BYSETPOS treat the week as Monday-based and cover it with the hand-computed dates the owner already settled in D-24.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| uv | all commands | ✓ | present (used this session) | — |
| Python (venv) | tests | ✓ | 3.14.5 | — |
| pyobjc-framework-EventKit | adapters, value-object tests | ✓ | 12.2.2 | — |
| fastmcp | server tests | ✓ | 3.4.7 | — |
| pytest | unit tests | ✓ | 9.1.1 | — |
| python-dateutil | six-month test, membership table | ✗ (not in `uv.lock`) | — | `uv add --dev` after the legitimacy checkpoint |
| Reminders store readable (FDA on the daemon identity) | store plane device tests | not probed (read-only research; no device access) | — | Unit tests use a `tmp_path` sqlite |
| Owner at the Mac (indent subtasks, Calendar/Reminders, Google calendar) | D-23 probes 1-5 | not probed | — | Executor stops at the owner action |

**Missing dependencies with no fallback:** none for unit work. Device tasks need the owner's Mac and the Mail-free probes only.
**Missing dependencies with fallback:** python-dateutil (dev group, after the checkpoint).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 (`>=8,<10`), markers `integration` |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]`: `testpaths = ["tests"]`, `addopts = "-m 'not integration'"` |
| Quick run command | `uv run pytest tests/test_contracts.py tests/test_eventkit.py tests/test_calendar.py tests/test_reminders.py tests/test_reminders_store.py -q` |
| Full suite command | `uv run pytest && uv run ruff check . && uv run ruff format --check .` |
| Baseline | 1538 passed, 80 deselected, 15.27 s; ruff clean [VERIFIED: run this session] |

Unit tests mock at the adapter boundary: `conftest.py` seals only `run_osascript`, `body_file`, `tracked_run`. EventKit and sqlite are NOT sealed, so each test patches `store` and `run_native` on the adapter module (`rem.store`, `rem.run_native`, as `tests/test_reminders.py::_patch_read` does) and the store path function on `reminders_store`. `EKAlarm`, `EKRecurrenceRule`, `EKRecurrenceDayOfWeek` are value objects and build in unit tests with no TCC (as `test_eventkit.py` already builds rules).

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CAL-01 | `alarms` maps to relative `EKAlarm`; 6th alarm, negative-on-timed, duplicate, bool refused in `__post_init__`; `None` vs `[]` tri-state; verify compares sorted multiset and flags absolute | unit | `uv run pytest tests/test_contracts.py tests/test_calendar.py -k alarm -q` | ✅ files, ❌ new tests |
| CAL-01 | Alarms land and read back on iCloud and Google | integration | `uv run pytest -m integration tests/test_integration.py -k alarm` | ❌ Wave 0 |
| CAL-02 | All-day and recurring all-day alarm fires on the right day (4 reader zones) | integration (spike 008 harness) | `uv run pytest -m integration -k allday_alarm` | ❌ Wave 0 |
| CAL-03 | BY* parse, ranges, RFC combinations, per-name rejection (BYWEEKNO, BYHOUR, BYMINUTE, BYSECOND, WKST) | unit | `uv run pytest tests/test_contracts.py -k rrule -q` | ✅ file, ❌ new tests |
| CAL-03 | 9-arg builder and canonical dict round trip (value objects) | unit | `uv run pytest tests/test_eventkit.py -q` | ✅ file, rewrite |
| CAL-03 | DTSTART membership table incl. hand-computed dateutil divergences; dateutil as oracle where it is right | unit | `uv run pytest tests/test_contracts.py -k dtstart -q` | ❌ Wave 0 (needs dateutil) |
| CAL-03 | Six-month expansion vs RFC 5545 (`set(ref) | {dtstart}`) on iCloud and Google | integration | `uv run pytest -m integration -k recurrence_expansion` | ❌ Wave 0 |
| CAL-04 | `_event_pointer` sets `folder` to the calendar id; `None` calendar omits it | unit | `uv run pytest tests/test_calendar.py -k folder -q` | ✅ file, ❌ new tests |
| REM-06 | `_reminder_pointer` sets `folder` to the list id | unit | `uv run pytest tests/test_reminders.py -k folder -q` | ✅ file, ❌ new tests |
| REM-01 | `delete_reminder`: dry-run default True (registry test), refusal with N subtasks in the dry run, `with_subtasks=True` clears it, unreadable store refuses, gone-check raises `VerificationFailed`, `delete_event` gone-check | unit | `uv run pytest tests/test_reminders.py tests/test_calendar.py tests/test_registry.py -k "delete or dry_run" -q` | ✅ files, ❌ new tests |
| REM-01 | Cascade on device (owner-built fixture) and delete gone on device | integration | `uv run pytest -m integration -k reminder_delete` | ❌ Wave 0 |
| REM-02 | `create_reminder_list`: duplicate refused, codes 17 and 24 map to `WriteRefused`, verify by id, `envelope_only` classification | unit | `uv run pytest tests/test_reminders.py tests/test_tool_annotations.py -k list -q` | ✅ files, ❌ new tests |
| REM-02 | `saveCalendar` on the default source on device | integration | `uv run pytest -m integration -k reminder_list` | ❌ Wave 0 |
| REM-03, REM-04 | Store sidecar: fingerprint match, `SchemaDrift` on a missing column, tombstones excluded on tag and reminder rows, `Z_ENT` resolved from `Z_PRIMARYKEY`, subtask query, unreadable store gives `coverage` | unit | `uv run pytest tests/test_reminders_store.py tests/test_reminders.py -q` | ❌ Wave 0 (new file) |
| REM-03, REM-04 | `Pointer.as_dict` emits `tags` / `parent` / `subtasks` only when set; tool returns pass the FastMCP output schema | unit | `uv run pytest tests/test_contracts.py tests/test_server.py -q` | ✅ files, ❌ new tests |
| D-11 | Reminder BY* round trip on device; `RecurrenceRequired` text re-sends BYDAY | unit + integration | `uv run pytest tests/test_eventkit.py -k rrule_text -q`; `-m integration -k reminder_byday` | ❌ Wave 0 |
| MAIL-05, MAIL-06 | Complete in 0.13.1 | — | no plan | n/a |

### Sampling Rate
- **Per task commit:** the quick run command above for the files the task touches.
- **Per wave merge:** `uv run pytest && uv run ruff check . && uv run ruff format --check .`
- **Phase gate:** full suite green plus the manual `-m integration` device runs listed above, before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `tests/test_reminders_store.py` — `tmp_path` sqlite with `Z_PRIMARYKEY` rows (`REMCDHashtag`, `REMCDReminder`), `ZREMCDOBJECT`, `ZREMCDREMINDER` (the `test_notes._make_notestore` pattern), plus a patched path function
- [ ] `tests/_fakes.py` — `fake_rule` BY* attributes; a shared fake `calendar()` for event and reminder fakes
- [ ] `tests/test_integration.py` — new device tests; teardown extended for list removal (`removeCalendar_commit_error_`), parent cleanup and the Google prefix sweep to `left=0`
- [ ] Framework install: `uv add --dev python-dateutil` after the human-verify checkpoint

## Security Domain

`security_enforcement` is enabled in `.planning/config.json` (`security_asvs_level: 1`, `security_block_on: high`).

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Local stdio or unix-socket server; no user auth in this phase |
| V3 Session Management | no | — |
| V4 Access Control | yes | Tool tiers gated at registration: `delete_reminder` is `@_write_tool` (destructive, absent under `MACOS_APPS_READ_ONLY`), `create_reminder_list` is `@_additive_tool`; `dry_run=True` default enforced by `test_content_removing_tools_default_to_dry_run` |
| V5 Input Validation | yes | `ValueError` at the boundary: alarm count and type, BY* ranges and combinations, list name (non-empty, no control characters), `with_subtasks` bool; SQL values bound with `?`; fingerprint identifiers come from adapter code, never from the caller |
| V6 Cryptography | no | — |
| V8 Data Protection | yes | Store opened `mode=ro` through `_open_sqlite_ro`; no write to Reminders' own store; FDA required and named in the docstring; audit before-state records subtasks for undo |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Prompt injection through tag text or reminder titles reaching the model | Tampering | Route tag strings through `text.sanitize_line` / `clean_summary`; the `UntrustedDataNotice` middleware already prefixes read results (`reminders` is not in `no_notice`) |
| SQL injection via the parent id | Tampering | Bound parameter (`WHERE p.ZCKIDENTIFIER = ?`); table/column names are constants |
| Silent cascade delete (data loss) | Denial of service / Tampering | Subtask refusal unless `with_subtasks=True`, raised in the dry run; unreadable store refuses; all N+1 in the audit snapshot |
| Hidden failure of the optional plane | Repudiation | `coverage` flag names the missing plane; never an empty list or a masked exception |
| Out-of-range rule saved by an unvalidated native API | Tampering | Boundary validation in `Recurrence` (Pitfall 3) plus canonical verify-after-write |
| Path traversal in the store path | Tampering | Path is a constant under `Path.home()`; no caller input reaches it |

## Sources

### Primary (HIGH confidence)
- `/Users/andrei/Developer/macos-apps-mcp/.planning/phases/03-.../03-CONTEXT.md` — decisions D-01..D-26 (copied verbatim above)
- `.claude/skills/spike-findings-macos-apps-mcp/SKILL.md` and `references/calendar-alarms.md`, `calendar-recurrence-allday.md`, `reminders-tags-subtasks.md` — locked spike findings, read in full
- `.claude/skills/spike-findings-macos-apps-mcp/sources/003-.../probe_eventkit.py`, `002-.../probe_store.py`, `007-.../probe_cascade.py`, `007-.../results-cascade.json`, `008-.../probe_alarms.py` — tested call shapes and the t=0 EventKit-gone evidence
- Source files read this session: `macos_apps_mcp/adapters/calendar.py`, `adapters/reminders.py`, `eventkit.py`, `contracts.py`, `errors.py`, `runtime.py` (lines 330-511), `registry.py`, `audit.py` (middleware), `server.py` (decorators, reminder and event tools), `adapters/notes.py` (fingerprint pattern); tests `test_registry.py`, `test_tool_annotations.py`, `test_native_seam.py`, `test_reminders.py`, `test_calendar.py`, `test_eventkit.py`, `test_server.py`, `test_notes.py`, `conftest.py`, `_fakes.py`
- In-process runs this session (value objects and a throwaway FastMCP app; no store, no TCC): EK error constants, `EKAlarm`, the 9-argument initializer and 11 validation cases, FastMCP output-schema behaviour, `Path.glob` versus `os.scandir` on an unreadable directory, `uv run pytest` and `uv run ruff check .` baseline, the legitimacy check

### Secondary (MEDIUM confidence)
- [RFC 5545 §3.3.10](https://datatracker.ietf.org/doc/html/rfc5545#section-3.3.10) · [🔖 2026-10-05](https://linkding.lav.ren/bookmarks?details=182) — BYSETPOS needs another BYxxx part; DTSTART is the first instance; the text returned was truncated at the FREQ-specific bans
- External references listed in CONTEXT.md `<canonical_refs>` (Apple `EKError.Code`, `EKRecurrenceRule` initializer, Google Calendar events resource, dateutil `rrule.py`); read by the discuss session on 2026-10-05, not re-fetched here

### Tertiary (LOW confidence)
- Training-memory items listed in the Assumptions Log (A1-A9)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — everything is already in the repo; only `python-dateutil` is new and dev-only
- Architecture: HIGH — every seam was read in source; decisions are locked and spike-proven
- Pitfalls: HIGH for 3, 4, 5, 6, 7, 11 (verified this session or read in source); MEDIUM for 2, 10 and 12 (policy beyond the locked decisions)

**Research date:** 2026-10-05
**Valid until:** 2026-11-04 for repo seams; the macOS store column names are guarded by the fingerprint, so re-check only after an OS update
