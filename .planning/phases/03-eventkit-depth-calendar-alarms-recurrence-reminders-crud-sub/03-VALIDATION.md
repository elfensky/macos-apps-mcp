---
phase: "3"
slug: "eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub"
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: validated
nyquist_compliant: true
wave_0_complete: true
validated: "2026-10-06"
created: "2026-10-05"
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 (`>=8,<10`), marker `integration` deselected by default |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths = ["tests"]`, `addopts = "-m 'not integration'"`) |
| **Quick run command** | `uv run pytest tests/test_contracts.py tests/test_eventkit.py tests/test_calendar.py tests/test_reminders.py tests/test_reminders_store.py tests/test_server.py tests/test_registry.py tests/test_tool_annotations.py -q` (the last three pin the wire shape, registry and permission docstrings) |
| **Full suite command** | `uv run pytest && uv run ruff check . && uv run ruff format --check .` |
| **Estimated runtime** | ~16 seconds (phase end: 1810 passed, 15.27 s; planning baseline 1538) |

---

## Sampling Rate

- **After every task commit:** Run the quick run command for the files the task touches
- **After every plan wave:** Run `uv run pytest && uv run ruff check . && uv run ruff format --check .`
- **Before `/gsd-verify-work`:** Full suite must be green, plus the manual `uv run pytest -m integration` device runs named in RESEARCH.md § Validation Architecture
- **Max feedback latency:** 20 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 3-01-01 | 01 | 1 | CAL-01, CAL-02, CAL-03, REM-02 | T-3-01 | Owner at the Mac names the one Google calendar; no answer = no device run; no family account targeted | manual | — | n/a | ✅ owner-answered |
| 3-01-02 | 01 | 1 | REM-02, CAL-03 | T-3-01, T-3-02 | Probe list only on the default source plus the named Google calendar; teardown to left=0; SUMMARY holds booleans only | integration | `uv run pytest -m integration tests/integration/test_eventkit_depth.py -k "reminder_list or reminder_byday"` | ✅ | ✅ green |
| 3-01-03 | 01 | 1 | CAL-01, CAL-02 | T-3-02, T-3-03 | Spike-008 harness sweeps its prefix to left=0 before and after; verdict holds counts only | integration | `uv run pytest -m integration tests/integration/test_eventkit_depth.py -k alarms` | ✅ | ✅ green |
| 3-02-01 | 02 | 2 | CAL-04, REM-06 | T-3-07 | `folder` = raw calendar/list id, never a title; omitted without a container; accepted back by `free_busy` | unit | `uv run pytest tests/test_calendar.py tests/test_reminders.py -q -k folder` | ✅ | ✅ green |
| 3-02-02 | 02 | 2 | REM-02 | T-3-04, T-3-05, T-3-06 | Duplicate, empty and control-character names refused before any native call; EK 17/24 become WriteRefused; additive tier, absent under READ_ONLY | unit | `uv run pytest tests/test_reminders.py tests/test_registry.py -q -k "reminder_list or reproduces"` | ✅ | ✅ green |
| 3-02-03 | 02 | 2 | CAL-04, REM-06, REM-02 | T-3-04, T-3-07 | Device tests remove every list, event and scratch calendar they create and assert it | integration | `uv run pytest -m integration tests/integration/test_eventkit_depth.py -k "reminder_list or folder_is_its_calendar_id"` | ✅ | ✅ green |
| 3-03-01 | 03 | 3 | CAL-03 | T-3-10 | A dropped or changed BY part fails verify-after-write (`recurs`); rule built with the 9-argument initializer | unit | `uv run pytest tests/test_eventkit.py tests/test_calendar.py tests/test_contracts.py -q -k "byday or signature or until or recurrence"` | ✅ | ✅ green |
| 3-03-02 | 03 | 3 | CAL-03 | T-3-08, T-3-09 | Out-of-range, RFC-illegal and unexpandable parts (BYWEEKNO, BYHOUR, BYMINUTE, BYSECOND, WKST) refused by name before any native call | unit | `uv run pytest tests/test_contracts.py tests/test_eventkit.py -q -k "rrule or recurrence"` | ✅ | ✅ green |
| 3-03-03 | 03 | 3 | CAL-03 | T-3-11 | RecurrenceRequired re-send text carries every BY part; reminder UNTIL compared by day (owner A5) | unit | `uv run pytest tests/test_eventkit.py tests/test_reminders.py -q -k "rrule_text or resend or bymonthday or until"` | ✅ | ✅ green |
| 3-04-01 | 04 | 4 | CAL-03 | T-3-SC | python-dateutil enters the dev group only after the owner's PyPI check (answer "approved") | manual | — | n/a | ✅ owner-answered |
| 3-04-02 | 04 | 4 | CAL-03 | T-3-12, T-3-13 | A DTSTART outside its rule is accepted and stated on the Pointer; dateutil is never imported by the package | unit | `uv run pytest tests/test_contracts.py tests/test_calendar.py -q -k dtstart` | ✅ | ✅ green |
| 3-04-03 | 04 | 4 | CAL-03 | T-3-14 | Test events only in the iCloud scratch calendar and the one Google calendar; Google swept to left=0 | integration | `uv run pytest -m integration tests/integration/test_eventkit_depth.py -k recurrence_expansion` | ✅ | ✅ green |
| 3-05-01 | 05 | 5 | CAL-01, CAL-02 | T-3-15 | Only relative EKAlarms are built; verify compares a sorted multiset and requires 0 absolute alarms | unit | `uv run pytest tests/test_calendar.py tests/test_server.py -q -k alarm` | ✅ | ✅ green |
| 3-05-02 | 05 | 5 | CAL-01, CAL-02 | T-3-16, T-3-17, T-3-18 | More than 5, duplicate, bool/non-int and negative-on-timed refused before native (owner A3/A4); None keeps, [] clears; all-day offsets from local midnight | unit | `uv run pytest tests/test_contracts.py tests/test_calendar.py -q -k alarm` | ✅ | ✅ green |
| 3-05-03 | 05 | 5 | CAL-01, CAL-02 | T-3-15, T-3-16 | Alarm round trip and all-day fire day proven on iCloud and Google; items removed | integration | `uv run pytest -m integration tests/integration/test_eventkit_depth.py -k alarms` | ✅ | ✅ green |
| 3-06-01 | 06 | 6 | REM-03, REM-04 | T-3-19, T-3-20, T-3-23 | Store read-only and fingerprinted (drift → SchemaDrift), Z_ENT by name, tombstones filtered, bound SQL, tags cleaned | unit | `uv run pytest -q -k "reminders_store or native_seam or carries_tags or emits_tags"` | ✅ | ✅ green |
| 3-06-02 | 06 | 6 | REM-03, REM-04 | T-3-21, T-3-22 | Unreadable store keeps the EventKit pointers and names the reason in `coverage`; a Full Disk Access denial is never "not found" | unit | `uv run pytest -q -k "read_with or read_never or store_path or clean_line or unreadable_directory or write_gap"` | ✅ | ✅ green |
| 3-06-03 | 06 | 6 | REM-03, REM-04 | T-3-21 | Store-plane read works on the real store with no `coverage`; write gap documented | integration | `uv run pytest -m integration tests/integration/test_eventkit_depth.py -k store_plane` | ✅ | ✅ green |
| 3-06-V | 06 | 6 | REM-04 | — | The package never references a private subtask selector (`setParentID_`, `parentID`, …); added by this audit (PR #280) | unit | `uv run pytest tests/test_reminders_store.py -q -k private_selector` | ✅ | ✅ green |
| 3-07-01 | 07 | 7 | REM-01 | T-3-25, T-3-27, T-3-28, T-3-29 | `dry_run` defaults True; unreadable store refuses before any remove; event ids refused; gone-check after remove | unit | `uv run pytest tests/test_reminders.py tests/test_reminders_store.py tests/test_registry.py tests/test_server.py -q -k "delete or subtasks_of or removes_content"` | ✅ | ✅ green |
| 3-07-02 | 07 | 7 | REM-01, REM-03 | T-3-24, T-3-26 | Parent with subtasks refused unless `with_subtasks=True` (dry run too); preview, confirmation and audit before-state name all N+1 | unit | `uv run pytest tests/test_reminders.py tests/test_contracts.py -q -k "subtask or deletion or audit_before or confirmed_delete"` | ✅ | ✅ green |
| 3-07-03 | 07 | 7 | REM-01, REM-03 | T-3-24, T-3-27 | Plain and cascade deletes proven gone on device; writes only to fixture ids | integration | `uv run pytest -m integration tests/integration/test_eventkit_depth.py -k "delete_reminder_is_gone or cascade_delete"` | ✅ | ✅ green |
| 3-08-01 | 08 | 8 | REM-03, REM-01 | T-3-31, T-3-32 | `complete_reminder` refuses with no save when the store is unreadable (owner A9); open subtasks listed and never touched; event ids refused | unit | `uv run pytest tests/test_reminders.py tests/test_server.py tests/test_registry.py -q -k "complete or reproduces"` | ✅ | ✅ green |
| 3-08-02 | 08 | 8 | REM-01 | T-3-30 | `delete_event` proves the occurrence is gone (occurrence-aware); dry run makes no remove and no re-check | unit | `uv run pytest tests/test_calendar.py -q -k delete_event` | ✅ | ✅ green |
| 3-09-01 | 09 | 9 | CAL-01..04, REM-01..04, REM-06 | T-3-33 | Owner at the Mac names the Google calendar; id resolved by source plus exact title, stop on 0 or >1 matches | manual | — | n/a | ✅ owner-answered |
| 3-09-02 | 09 | 9 | CAL-01..04, REM-01..04, REM-06 | T-3-33, T-3-34 | Sweep green on iCloud and Google; nothing left except the cascade fixture | integration | `uv run pytest -m integration tests/integration/test_eventkit_depth.py -k "not cascade"` | ✅ | ✅ green |
| 3-09-03 | 09 | 9 | REM-01, REM-03, REM-04 | T-3-34 | Owner indents subtasks and adds the tag by hand (no private API) | manual | — | n/a | ✅ owner-answered |
| 3-10-01 | 10 | 10 | REM-01, REM-03, REM-04 | T-3-36 | Every write targets a fixture id; cascade removes exactly N+1; audit before-state keeps all N+1 | integration | `MACOS_APPS_IT_CASCADE_FIXTURE=<json> uv run pytest -m integration tests/integration/test_eventkit_depth.py -k cascade` | ✅ | ✅ green |
| 3-10-02 | 10 | 10 | MAIL-05, MAIL-06 | T-3-37, T-3-38 | MAIL-05/06 verified read-only from the record; issues closed only on passed device proof | unit | `uv run pytest tests/test_mail.py tests/test_mail_outgoing.py -q -k "rollback or leftover or original or 120s"` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `tests/test_reminders_store.py` — `_make_reminders_store` (`Z_PRIMARYKEY` rows `REMCDHashtag`/`REMCDReminder`, `ZREMCDOBJECT`, `ZREMCDREMINDER`, tombstones) plus the `store_file` fixture that patches `reminders_store.store_path`; reused by test_reminders.py and test_server.py
- [x] `tests/_fakes.py` — `fake_rule` BY* keywords (byday, bymonthday, bymonth, byyearday, bysetpos, until); the fake `calendar()` lives per module (`test_calendar._fake_calendar`, `_fake_reminder(calendar_id=)`), not in `_fakes.py`
- [x] Device tests — a new module `tests/integration/test_eventkit_depth.py` (16 tests; `ek_items`, `icloud_scratch`, `google_calendar` sweep to `left=0`, module-scoped `cascade_fixture`) instead of `tests/test_integration.py`
- [x] `uv add --dev python-dateutil` — dev group only after the owner's "approved"; guarded by `test_dtstart_reference_library_is_never_imported_by_the_package` / `…_is_a_dev_dependency_only`

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions | Recorded Result |
|----------|-------------|------------|-------------------|-----------------|
| All-day and recurring all-day alarm fire day, non-UTC | CAL-02 | Live EventKit, device clock; Google rewrites alarms | `uv run pytest -m integration tests/integration/test_eventkit_depth.py -k all_day_alarms_fire` (needs `MACOS_APPS_IT_GOOGLE_CALENDAR_ID` for `[google]`) | 03-09 passed on iCloud and Google; probe 4: 320 fire times in 4 zones on the right day (8 on DST days). The real notification was not observed. |
| Alarm round trip, Google 5-alarm cap, absolute rewrite | CAL-01 | Google rewrites after the save | `… -k alarms` (6 tests) | 03-09 passed; probe 4: relative exact, absolute rewritten, a 6th alarm dropped. |
| Six-month expansion equals RFC 5545 on iCloud and Google | CAL-03 | Live CalDAV sources | `… -k recurrence_expansion` | 03-09 passed both; 23 shapes, the two never-probed shapes included; Google swept to `left=0`. |
| `saveCalendar` on the default reminders source; Google refusal | REM-02 | No documented per-source "allows add" flag | `… -k reminder_list` | 03-09 passed; probe 1: save ok on the default source, Google refused with `EKErrorDomain` 24. |
| Reminder BY* round trip | CAL-03 (D-11) | Live reminders store | `… -k reminder_byday` | 03-09 passed; probe 2: 3 shapes exact now and after 60 s from a fresh process; UNTIL kept by day. |
| Store plane on the real Reminders store | REM-03, REM-04 | Real Core Data schema and the Full Disk Access grant | `… -k store_plane` | 03-09 passed, no `coverage`. |
| Parent delete cascade, parent completion, tag and parent values | REM-01, REM-03, REM-04 | EventKit cannot make a subtask or a tag; the owner indents by hand; one-shot (the test deletes the fixture) | `MACOS_APPS_IT_CASCADE_FIXTURE=<json> uv run pytest -m integration tests/integration/test_eventkit_depth.py -k cascade` | 03-10: 2 passed; 3 refused, 3 previewed, 3 confirmed, gone in EventKit and the store, 3 in the audit before-state. The owner's first tag was not saved by Reminders.app; re-added and seen at once. |
| Existing EventKit device tests (regression) | — | Live stores | `uv run pytest -m integration tests/test_integration.py -k "reminder or event or calendar or free_busy or all_day or recurring or request_access"` | 03-09: 19 of 19 passed; no non-EventKit test selected. |
| Installed daemon carries Phase 3 | all | Needs the `.app` rebuilt and reinstalled (docs/RELEASING.md) | `doctor().version` after a release | Not done: the daemon is still v0.13.1; a release is the operator's call. |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 20s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** validated 2026-10-06 (validate-phase: 10 requirements COVERED, REM-04 PARTIAL → filled by PR #280; 0 MISSING)

## Validation Audit 2026-10-06

| Metric | Count |
|---|---|
| Gaps found | 1 |
| Resolved | 1 |
| Escalated | 0 |
