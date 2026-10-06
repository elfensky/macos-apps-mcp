---
phase: 03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub
verified: 2026-10-06T19:30:00Z
status: human_needed
score: 8/8 must-haves verified
covered_files:
  - ".planning/phases/03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub/03-01-PLAN.md"
  - ".planning/phases/03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub/03-01-SUMMARY.md"
  - ".planning/phases/03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub/03-02-PLAN.md"
  - ".planning/phases/03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub/03-02-SUMMARY.md"
  - ".planning/phases/03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub/03-03-PLAN.md"
  - ".planning/phases/03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub/03-03-SUMMARY.md"
  - ".planning/phases/03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub/03-04-PLAN.md"
  - ".planning/phases/03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub/03-04-SUMMARY.md"
  - ".planning/phases/03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub/03-05-PLAN.md"
  - ".planning/phases/03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub/03-05-SUMMARY.md"
  - ".planning/phases/03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub/03-06-PLAN.md"
  - ".planning/phases/03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub/03-06-SUMMARY.md"
  - ".planning/phases/03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub/03-07-PLAN.md"
  - ".planning/phases/03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub/03-07-SUMMARY.md"
  - ".planning/phases/03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub/03-08-PLAN.md"
  - ".planning/phases/03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub/03-08-SUMMARY.md"
  - ".planning/phases/03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub/03-09-PLAN.md"
  - ".planning/phases/03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub/03-09-SUMMARY.md"
  - ".planning/phases/03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub/03-10-PLAN.md"
  - ".planning/phases/03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub/03-10-SUMMARY.md"
  - "macos_apps_mcp/adapters/calendar.py"
  - "macos_apps_mcp/adapters/reminders.py"
  - "macos_apps_mcp/adapters/reminders_store.py"
  - "macos_apps_mcp/contracts.py"
  - "macos_apps_mcp/errors.py"
  - "macos_apps_mcp/eventkit.py"
  - "macos_apps_mcp/server.py"
  - "tests/integration/test_eventkit_depth.py"
  - "tests/test_registry.py"
  - "tests/test_reminders_store.py"
covered_digest: "v3:sha256:2d99b8777a0ee103890f64bf8c6e937912ea158cadfe46efeea0831da2aec047"
behavior_unverified: 0
overrides_applied: 0
human_verification:
  - test: "On the Mac, with the Reminders store readable, run the device tests against the code at 6c2cdb3 (or the release build): `uv run pytest -m integration tests/integration/test_eventkit_depth.py -k 'delete_reminder or delete_event or create_reminder_list or reminders_read'` and `uv run pytest -m integration tests/test_integration.py` (the 19 EventKit regression tests)."
    expected: "All pass. delete_reminder on a reminder just created through EventKit is not refused for a missing store row; delete_event, update_event and update_reminder still resolve their ids; create_reminder_list reads its title back."
    why_human: "PR #281 changed these paths after the 03-09 and 03-10 device runs (built at dc44c96). The new checks are unit-tested, and a store-lag measurement (3 of 3, row visible within 0.05 s) supports them, but no device run covers the final commit. Device tests are never run by the verifier."
---

# Phase 3: EventKit Depth Verification Report

**Phase Goal:** The one native plane Calendar and Reminders share reaches Mail-level completeness: alarms and real recurrence on events, deletion, lists and subtasks on reminders. The two Mail sweep findings carried over from Phase 02.1 (#229, #230) are settled first.
**Verified:** 2026-10-06
**Status:** human_needed
**Re-verification:** No, initial verification
**Code under verification:** `develop` at 6c2cdb3 (the records lane holds identical code).

## Goal Achievement

### Observable Truths

| # | Truth (ROADMAP success criterion) | Status | Evidence |
|---|-----------------------------------|--------|----------|
| 1 | Event alarms (minutes before) land as `EKAlarm`s and verify-after-write reads them back; all-day and recurring all-day alarms fire on the right day in a non-UTC zone, probed before the code | VERIFIED | `contracts.CalendarEventData.alarms` (None / () / tuple) validates max 5, whole minutes, no duplicates, no negative on timed events. `calendar._apply_event` builds `alarmWithRelativeOffset_(-m*60)` only. `_verify_event` compares a sorted multiset and requires 0 absolute alarms. `create_event` and `update_event` expose `alarms` (server.py 1215, 1258). Device: probe 008 `verdict.json` shows `relative_exact`, `six_kept_five`, `abs_rewritten`, `allday_fire_days_ok` (320 fires), run in 03-01 before any code. Sweep `p3-sweep.xml` 14/14, including timed round trip, all-day fire day and all-day-no-alarms on iCloud and Google. |
| 2 | Recurring event with BYDAY (monthly ordinals), BYMONTHDAY or BYMONTH reads back six months matching RFC 5545; an inexpressible shape is rejected loudly naming the shape | VERIFIED | `Recurrence` carries byday, bymonthday, bymonth, byyearday, bysetpos with range and combination checks. `eventkit.to_recurrence_rule` uses the 9-argument initializer. `_verify_event` compares a canonical dict part by part. `_RRULE_REJECTED` refuses BYWEEKNO, BYHOUR, BYMINUTE, BYSECOND, WKST by name with the reason. Device: `test_recurrence_expansion_matches_rfc5545[icloud,google]` passed over 23 shapes (BYDAY ordinals, BYMONTHDAY, BYMONTH, BYSETPOS, YEARLY). The rejection is a `ValueError` converted to a tool error by the guard (project convention for boundary validation); it names the part. |
| 3 | `delete_reminder(id)` defaults `dry_run=True`, logs its own audit verb, and its verify-after-write confirms the reminder is gone on device, like `delete_event` | VERIFIED (device re-run requested, see Human Verification) | `server.delete_reminder(id, dry_run=True, with_subtasks=False)`. `tests/test_registry.py::test_delete_reminder_registration_record` asserts tier destructive, audit verb "delete", `dry_run` default True, own `ReminderDeleteSnapshotter`. Adapter removes, then `_fresh_item` for the parent and each subtask; any survivor raises `VerificationFailed`. The dry run runs every refusal and makes no remove. Device: `test_delete_reminder_is_gone_on_device` and `test_delete_event_is_gone_on_device` passed in `p3-sweep.xml`; `test_cascade_delete_with_subtasks` passed in `p3-cascade.xml` (2/2). Those runs were built at dc44c96, before PR #281 added the missing-store-row refusal. |
| 4 | A reminder list can be created and appears in the adapter's list read | VERIFIED | `RemindersAdapter.create_reminder_list` (additive tier): scan, save and verify in one `run_native` block; refuses a duplicate name, edge whitespace; verifies id in the list read and persisted title. Device: probe 1 (`list_saved`, `list_in_reads`, `list_removed` all true; Google refuses with EKErrorDomain 24) and `test_create_reminder_list_on_default_source` (sweep, passed at dc44c96). |
| 5 | Subtasks and tags read-only from the Reminders sqlite store, joined by id, schema-fingerprinted; `reminders()` Pointers carry `tags` and `parent`; unreadable store degrades loudly with `coverage`; write gap named in docstrings; no private-API write | VERIFIED | `reminders_store.py`: `_FINGERPRINT` over three tables, `read_via_sqlite` read-only, no fallback, tombstone and NULL-id filters. `RemindersAdapter.read` returns `{results, coverage?}` with `tags` and `parent` per Pointer; a `NativeError` is named in `coverage` and EventKit pointers stay intact; ids unknown to a readable store are counted in `coverage`. Docstrings of `reminders`, `create_reminder`, `update_reminder` name the write gap. Guard test `tests/test_reminders_store.py` (lines 238-262) fails on any reference to `parentID`, `setParentID`, `parentReminder`; grep of `macos_apps_mcp/` finds none. Device: `test_reminders_read_carries_the_store_plane` (sweep) and `test_cascade_*` (2/2) on an owner-built fixture: children carry `parent`, the tag appears on the child, no `coverage`. |
| 6 | `events()` and `reminders()` Pointers carry the owning calendar or list id in `folder`, the token `free_busy(calendars=...)` and the write tools take; unit test on both pointer builders; no per-calendar workaround | VERIFIED | `calendar.py:93` and `reminders.py:76` set `folder=container_id(item)` (the identifier, never the title). `calendars()` and `reminder_lists()` map ids to names. `resolve_container` is id-first. Tests: `test_get_pointers_folder_round_trips_into_free_busy`, `test_reminder_pointer_folder_is_the_list_identifier` and four siblings. Device: `test_event_pointer_folder_is_its_calendar_id` passed. |
| 7 | #229: `rollback()`'s unverified delete of a windowless outgoing message has a decided handling; an outbound call that leaves a message behind says so loudly; xfail removed or its reason names the decision; device-verified | VERIFIED | Commit 2f77bc7 (0.13.1): the leftover WARNING is the caller contract and now names the recovery ("Quitting and reopening Mail clears it."), see `mail_outgoing.ROLLBACK` / `outgoingLeftover`. The non-strict xfail on `test_rollback_verifies_a_real_delete` keeps its reason and now names the 2026-10-05 decision. `docs/mail-applescript-facts.md` §3c holds the state. REQUIREMENTS.md and `gh` state: MAIL-05 complete, #229 closed. Delivered in 0.13.1, ahead of the phase (email before features). Not re-probed here; the Mail rule forbids a verifier device run. |
| 8 | #230: five dedicated device runs decide the reply quote's read; 5 of 5 removes the xfail; any failure ships a mitigation and a facts entry separating a transient stall from the permanent wedge | VERIFIED | Commit 13a2b23 (0.13.1): every script acting on the original (`_ORIGINAL`, `_REPLY`, `_REPLY_ALL`, `_REPLY_ALL_RECIPIENTS`, `_FORWARD`) uses `ORIGINAL_TIMEOUT = 120.0` (mail_outgoing.py 663, 677, 777, 783, 813; mail_drafts.py 317); a test pins all five (test_mail_outgoing.py 502-507). `docs/mail-applescript-facts.md` lines 459-478 hold the transient-vs-permanent reading and "#230 settled": 5 of 5 in 52-72 s, xfail removed. The reply test in `test_mail_outbound.py` carries no xfail. MAIL-06 complete, #230 closed. |

**Score:** 8/8 truths verified (0 present-but-behavior-unverified). One re-validation item remains (below).

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `macos_apps_mcp/adapters/reminders_store.py` | Read-only store plane | VERIFIED | 166 lines; fingerprint, `tags_and_parents`, `live_ids`, `subtasks_of` (bound parameter); imported by `reminders.py` only |
| `macos_apps_mcp/adapters/reminders.py` | delete, list create, read envelope, parent-aware complete | VERIFIED | 607 lines; wired through `server.py` |
| `macos_apps_mcp/adapters/calendar.py` | alarms, BY* verify, delete gone-check | VERIFIED | 566 lines |
| `macos_apps_mcp/contracts.py` | `Recurrence` BY* fields, `alarms`, `Pointer.folder/tags/parent/subtasks` | VERIFIED | 766 lines |
| `macos_apps_mcp/eventkit.py` | 9-argument rule builder, canonical signature | VERIFIED | `to_recurrence_rule` at line 201 |
| `tests/integration/test_eventkit_depth.py` | Phase 3 device tests | VERIFIED | all tests named in the sweep and cascade junit exist |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `server.delete_reminder` | `RemindersAdapter.delete_reminder` | one-line dispatch, `ReminderDeleteSnapshotter` | WIRED | registry test asserts the snapshotter |
| `server.create_event` / `update_event` | `CalendarEventData.alarms` | `alarms=None if alarms is None else tuple(alarms)` | WIRED | tri-state kept |
| `RemindersAdapter.read` | `reminders_store.tags_and_parents` / `live_ids` | try/except `NativeError` into `coverage` | WIRED | EventKit read runs first, outside the try |
| `RemindersAdapter.delete_reminder` / `complete_reminder` | `reminders_store.subtasks_of` | same `run_native` block, before any write | WIRED | store error becomes `WriteRefused`; no save |
| `Pointer.folder` | `free_busy(calendars=)`, `resolve_container` | container identifier | WIRED | id-first resolution; round-trip unit test |

### Data-Flow Trace (Level 4)

| Artifact | Data | Source | Real data | Status |
|----------|------|--------|-----------|--------|
| `reminders()` `tags`, `parent` | `tags_and_parents()` | Reminders sqlite (`mode=ro`) | Yes: owner fixture read back on device | FLOWING |
| `Pointer.folder` | `container_id(item)` | `item.calendar().calendarIdentifier()` | Yes: device test | FLOWING |
| `delete_reminder` subtasks | `subtasks_of(id)` | sqlite, bound parameter | Yes: 3 subtasks listed and removed on device | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Unit suite | `uv run pytest -q -p no:cacheprovider` (main checkout, develop 6c2cdb3) | 1830 passed, 96 deselected | PASS |
| Lint and format | `uv run ruff check .`, `uv run ruff format --check .` | clean; 107 files formatted | PASS |
| REM-04 private-selector guard | `pytest tests/test_reminders_store.py tests/test_registry.py -k "private or delete_reminder or selector"` | 4 passed | PASS |
| Device sweep (recorded, not re-run) | `p3-sweep.xml` | 14 tests, 0 failures, 0 errors, 0 skipped | PASS (at dc44c96) |
| EventKit regression (recorded) | `p3-regress.xml` | 19 tests, 0 failures | PASS (at dc44c96) |
| Cascade (recorded) | `p3-cascade.xml` | 2 tests, 0 failures | PASS (at dc44c96) |

### Probe Execution

SKIPPED: the phase declares no `probe-*.sh` scripts. Its probes are device Python harnesses (spike 008 alarm harness, probe 1 and 2), recorded in `p3-probes.json` and `p3-probe-008/verdict.json` (all booleans true, refusal code 24 on Google as predicted).

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| CAL-01 | 03-01, 03-05, 03-09 | alarms on create/update, read back | SATISFIED | Truth 1 |
| CAL-02 | 03-01, 03-05, 03-09 | all-day alarms on the right day, probed first | SATISFIED | Truth 1; probe 008 before code |
| CAL-03 | 03-01, 03-03, 03-04, 03-09 | BY* recurrence, loud rejection, six-month check | SATISFIED | Truth 2 |
| CAL-04 | 03-02, 03-09 | events `folder` = calendar id | SATISFIED | Truth 6 |
| REM-01 | 03-07, 03-08, 03-09, 03-10 | delete reminder, dry-run default | SATISFIED | Truth 3 |
| REM-02 | 03-01, 03-02, 03-09 | create reminder list | SATISFIED | Truth 4 |
| REM-03 | 03-06, 03-07, 03-08, 03-09, 03-10 | subtasks read-only, `parent` | SATISFIED | Truth 5 |
| REM-04 | 03-06, 03-09, 03-10 | tags read-only, no private write | SATISFIED | Truth 5 |
| REM-06 | 03-02, 03-09 | reminders `folder` = list id | SATISFIED | Truth 6 |
| MAIL-05 | 03-10 | #229 decided handling | SATISFIED | Truth 7 (0.13.1) |
| MAIL-06 | 03-10 | #230 five runs decide | SATISFIED | Truth 8 (0.13.1) |

All 11 phase IDs appear in PLAN frontmatter and in REQUIREMENTS.md (all marked Complete). No orphaned requirement: REQUIREMENTS.md maps no other ID to Phase 3. REM-05 (reminder alarms) is v2 and stays out of scope by decision (COVERAGE.md, OPT-OUT).

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| macos_apps_mcp/* (files changed in phase) | | TBD / FIXME / XXX | none found | none |

No stubs, hollow props or debt markers in the changed package files. Known accepted items: IN-03 (D-10 note appended past `SUMMARY_MAX`, by design) and IN-04 (`delete_event` post-delete check for an id without an occurrence suffix, deferred; the device test passed for single, this-event and future-events deletes). Both are recorded in 03-REVIEW-DISPOSITION.md; neither blocks a truth.

### Human Verification Required

#### 1. Device re-run on the final commit

**Test:** On the Mac, run the Phase 3 device tests that touch code changed by PR #281: `delete_reminder`, `delete_event`, `create_reminder_list`, `reminders` read, plus the 19 EventKit regression tests, against 6c2cdb3 or the release build.
**Expected:** All pass. In particular: a reminder created through EventKit is deletable at once (the store lists its row); event writes still resolve ids after the new reminder-id guard in `_resolve_event`; the list create reads its title back.
**Why human:** The 03-09 and 03-10 device runs predate #281. #281 added: a refusal when the store has no live row for the reminder (`subtasks_of`), a reminder-id guard (`hasattr(item, "isCompleted")`) in `_resolve_event` and `update_reminder`, a persisted-title check in `create_reminder_list`, and a `live_ids` coverage note. All are unit-tested (1830 passed) and the store-lag measurement supports the first. The `isCompleted` check returning false for an `EKEvent` on a real device has no device proof yet; it sits on every event write. The verifier does not run device tests. Risk is low; the item is raised so the final commit is not shipped on pre-fix device evidence.

### Gaps Summary

No gaps. Every ROADMAP success criterion is backed by code in `develop` at 6c2cdb3, by unit tests (1830 pass, ruff clean) and, for the device-dependent clauses, by recorded device runs (sweep 14/14, regression 19/19, cascade 2/2, probes) taken one fix round earlier. The status is `human_needed` only for the device re-run of the post-#281 paths. The daemon is still v0.13.1: a Claude session sees none of this until a release is cut (docs/RELEASING.md); that is expected, not a gap. Housekeeping for the orchestrator: ROADMAP.md line 36 still shows Phase 3 unchecked.

---

_Verified: 2026-10-06_
_Verifier: Claude (gsd-verifier)_
