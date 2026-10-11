---
phase: 03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub
verified: 2026-10-11T12:00:00Z
status: passed
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
  - "macos_apps_mcp/runtime.py"
  - "macos_apps_mcp/server.py"
  - "tests/integration/test_eventkit_depth.py"
  - "tests/test_registry.py"
  - "tests/test_reminders.py"
  - "tests/test_reminders_store.py"
covered_digest: "v3:sha256:0fdb906569a06e91c7879e734c61d33ac16c7fcf7a7d40e8f6e4ee60cd5cd3f8"
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: passed
  previous_score: 8/8
  gaps_closed: []
  gaps_remaining: []
  regressions: []
---

# Phase 3: EventKit Depth Verification Report

**Phase Goal:** The one native plane Calendar and Reminders share reaches Mail-level completeness: alarms and real recurrence on events, deletion, lists and subtasks on reminders. The two Mail sweep findings carried over from Phase 02.1 (#229, #230) are settled first.
**Verified:** 2026-10-11
**Status:** passed
**Re-verification:** Yes. The report of 2026-10-06 went stale after #307 (PR #313).
**Code under verification:** `develop` at 4b404eb (worktree `records-307`).

## Re-verification

The first report (2026-10-06, status passed, 8/8) verified `develop` at 6c2cdb3. Its human item, a device re-run of the PR #281 paths, passed on 2026-10-07 (03-UAT.md, status complete). Both results stand.

Since 6c2cdb3, the only Phase 3 source file that changed is `macos_apps_mcp/adapters/reminders_store.py` (`git diff 6c2cdb3..HEAD`). `calendar.py`, `reminders.py`, `contracts.py`, `errors.py`, `eventkit.py`, `tests/integration/test_eventkit_depth.py` and `tests/test_registry.py` have no diff. `server.py` changed only in Mail tool docstrings (#287, #291). `tests/test_reminders.py` and `tests/test_reminders_store.py` gained the #307 tests. So Truths 1, 2, 6, 7 and 8 got a regression check only; Truths 3, 4 and 5 got a full re-check.

### What #307 changed, and what it preserved

| Aspect | Before (6c2cdb3) | Now (4b404eb) | Verdict |
|--------|------------------|---------------|---------|
| Join key | `ZCKIDENTIFIER`, the CloudKit id, NULL on a Local list | `_EK_ID = "ZDACALENDARITEMUNIQUEIDENTIFIER"`, one constant in all five queries and in `_FINGERPRINT` | CHANGED, and it is a fix. A Pointer id is still the EventKit `calendarItemIdentifier`. |
| Parent link | `ZPARENTREMINDER` to `Z_PK` | same | PRESERVED |
| Files read | the one largest `Data-*.sqlite` (`store_path()`) | every `Data-*.sqlite` with a `ZREMCDREMINDER` table (`store_paths()`, `_read_all`) | CHANGED, and it is a fix. |
| Fail-closed behaviour | typed error on a missing grant, a drifted schema, a missing parent row | same. A file with the table that fails `_FINGERPRINT` fails the whole read. No file with the table raises `SchemaDrift`. | PRESERVED, and extended to the multi-file case |
| Read-only | `runtime.read_via_sqlite`, `mode=ro` | same (`runtime.py:375`) | PRESERVED |
| Private-API write | none | none. `grep parentID\|setParentID\|parentReminder` over `macos_apps_mcp/` finds nothing; the guard test passes. | PRESERVED |
| `reminders.py` call sites | `tags_and_parents`, `live_ids`, `subtasks_of` | unchanged signatures and unchanged call sites (lines 306, 307, 495, 551, 603) | PRESERVED |

The old defect: on a Local list every reminder had a NULL `ZCKIDENTIFIER`, so `subtasks_of` found no live row and `complete_reminder` and `delete_reminder` refused permanently. That is the exact fail-closed guard working on a wrong key. The new key removes the false refusal without weakening the guard: `test_a_cloudkit_only_row_fails_closed` and the unchanged "no live row means refuse" branch of `subtasks_of` still hold.

## Goal Achievement

### Observable Truths

| # | Truth (ROADMAP success criterion) | Status | Evidence |
|---|-----------------------------------|--------|----------|
| 1 | Event alarms land as `EKAlarm`s and are read back; all-day and recurring all-day alarms fire on the right day in a non-UTC zone, probed first | VERIFIED (regression check) | `calendar.py` and `contracts.py` have no diff since 6c2cdb3. Device evidence of 2026-10-06 stands (probe 008, sweep 14/14). Unit suite green. |
| 2 | Recurring event with BYDAY, BYMONTHDAY or BYMONTH reads back six months matching RFC 5545; an inexpressible shape is rejected loudly | VERIFIED (regression check) | `eventkit.py`, `contracts.py`, `calendar.py` unchanged. `test_recurrence_expansion_matches_rfc5545[icloud,google]`, 23 shapes, stands. |
| 3 | `delete_reminder(id)` defaults `dry_run=True`, logs its own audit verb, and confirms the reminder is gone | VERIFIED | `reminders.py` unchanged: `delete_reminder` calls `reminders_store.subtasks_of(ident)` before any remove (line 551) and turns a store `NativeError` into `WriteRefused` with no change made. `snapshot` calls the same function (line 603). `test_registry.py` is unchanged and passes. #307 behaviour: `test_a_local_list_parent_with_subtasks_is_refused_unless_confirmed` and `test_a_local_parent_in_the_smaller_store_file_is_refused_unless_confirmed` pass, so the guard sees a Local parent and a parent in a smaller file. Device (PR #313): iCloud Mac, a real parent with 97 subtasks, the unconfirmed dry run raised `SubtasksRequired`, the confirmed dry run listed the same 97, nothing removed; a throwaway reminder was created, completed and deleted, and is gone from the store. Intel iMac, Local source: `test_delete_reminder_is_gone_on_device` passed, throwaway Local reminder completed and deleted. |
| 4 | A reminder list can be created and appears in the adapter's list read | VERIFIED | `create_reminder_list` unchanged. Device (PR #313): `test_create_reminder_list_on_default_source` passed on the Intel iMac (default source Local). Earlier iCloud evidence stands. |
| 5 | Subtasks and tags read-only from the Reminders sqlite store, joined by id, schema-fingerprinted; `reminders()` Pointers carry `tags` and `parent`; unreadable store degrades loudly with `coverage`; no private-API write | VERIFIED | `reminders_store.py` re-read in full. Join by EventKit id on every query. `_FINGERPRINT` covers `Z_PRIMARYKEY`, `ZREMCDOBJECT`, `ZREMCDREMINDER` incl. `_EK_ID`. `reminders.py:read` unchanged: a `NativeError` goes into `coverage`, EventKit pointers stay; ids unknown to the store are counted. Tests: Local-row liveness, subtasks, tag and parent; union of live ids; merged tags and parents across files; `subtasks_of` across files; a drifted second file; a shell file skipped; only shells raise `SchemaDrift`; listing order. Guard test against private selectors passes. Device (PR #313): iCloud, store reads identical to pre-fix (1371 live ids, 13 tagged, 312 parent links, equal hashes), no "not in the Reminders store" note; Intel iMac `test_reminders_read_carries_the_store_plane` passed, no note on a Local list. |
| 6 | `events()` and `reminders()` Pointers carry the owning calendar or list id in `folder` | VERIFIED (regression check) | `calendar.py`, `reminders.py` unchanged. Tests green. |
| 7 | #229 decided handling | VERIFIED (regression check) | `tests/integration/test_mail_outbound.py:96` keeps the non-strict xfail with the decision in its reason. Unit suite green after the later Mail commits. |
| 8 | #230 five runs decide; mitigation in place | VERIFIED (regression check) | `ORIGINAL_TIMEOUT = 120.0` still used at `mail_outgoing.py` 677, 777, 783, 813 and `mail_drafts.py:317`. The pinning test is part of the green suite. |

**Score:** 8/8 truths verified (0 present-but-behavior-unverified).

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `macos_apps_mcp/adapters/reminders_store.py` | Read-only, fingerprinted store plane | VERIFIED | `_EK_ID`, `store_paths`, `_read_all`, `tags_and_parents`, `live_ids`, `subtasks_of`. Imported by `reminders.py` only. No `store_path`/`ZCKIDENTIFIER` code reference remains outside a comment and tests. |
| `macos_apps_mcp/adapters/reminders.py` | delete, list create, read envelope, parent-aware complete | VERIFIED | unchanged since 6c2cdb3; wired to the new store API through unchanged names |
| `macos_apps_mcp/adapters/calendar.py`, `contracts.py`, `eventkit.py`, `errors.py` | alarms, BY* recurrence, folder ids | VERIFIED | unchanged since 6c2cdb3 |
| `tests/test_reminders_store.py`, `tests/test_reminders.py` | store and guard tests | VERIFIED | 14 #307 tests; monkeypatches use `store_paths` consistently |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `RemindersAdapter.read` | `tags_and_parents`, `live_ids` | try/except `NativeError` into `coverage` | WIRED | lines 306-310 |
| `delete_reminder`, `complete_reminder`, `snapshot` | `subtasks_of` | same `run_native` block, before any write | WIRED | lines 495, 551, 603; store error becomes `WriteRefused` |
| `tags_and_parents`, `live_ids`, `subtasks_of` | `_read_all` then `read_via_sqlite` | every store file with the table, `mode=ro`, fingerprint checked | WIRED | |
| `server.delete_reminder`, `create_event`, `update_event` | adapters | one-line dispatch | WIRED | unchanged |

### Data-Flow Trace (Level 4)

| Artifact | Data | Source | Real data | Status |
|----------|------|--------|-----------|--------|
| `reminders()` `tags`, `parent` | `tags_and_parents()` | every Reminders sqlite file, joined on the EventKit id | Yes: 13 tagged and 312 parent links on the iCloud Mac; Local list read on the Intel iMac (PR #313 body) | FLOWING |
| `delete_reminder` subtasks | `subtasks_of(id)` | sqlite, bound parameter | Yes: 97 subtasks listed on a real parent (PR #313 body) | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Phase 3 unit tests | `uv run pytest -q -p no:cacheprovider tests/test_reminders_store.py tests/test_reminders.py tests/test_registry.py tests/test_server.py` | 259 passed | PASS |
| Full unit suite | `uv run pytest -q -p no:cacheprovider` | 1960 passed, 97 deselected | PASS |
| Lint | `uv run ruff check .` | All checks passed | PASS |
| Format | `uv run ruff format --check .` | 109 files already formatted | PASS |
| Local-key and multi-file subset | `pytest tests/test_reminders_store.py -k "local or every or store_paths or private or selector or drift or skip"` | 17 passed | PASS |

Device tests were not run by the verifier (no EventKit, no Reminders writes). The device evidence cited is recorded in PR #313 and 03-UAT.md.

### Probe Execution

SKIPPED: the phase declares no `probe-*.sh` scripts. Its probes are device Python harnesses, recorded in `p3-probes.json` and `p3-probe-008/verdict.json` in the first report.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| CAL-01 | 03-01, 03-05, 03-09 | alarms on create/update, read back | SATISFIED | Truth 1 |
| CAL-02 | 03-01, 03-05, 03-09 | all-day alarms on the right day | SATISFIED | Truth 1 |
| CAL-03 | 03-01, 03-03, 03-04, 03-09 | BY* recurrence, loud rejection | SATISFIED | Truth 2 |
| CAL-04 | 03-02, 03-09 | events `folder` = calendar id | SATISFIED | Truth 6 |
| REM-01 | 03-07, 03-08, 03-09, 03-10 | delete reminder, dry-run default | SATISFIED. #307 preserved the guard and fixed its false refusal on Local lists. | Truth 3 |
| REM-02 | 03-01, 03-02, 03-09 | create reminder list | SATISFIED | Truth 4 |
| REM-03 | 03-06, 03-07, 03-08, 03-09, 03-10 | subtasks read-only, `parent` | SATISFIED. #307 preserved the link (`ZPARENTREMINDER` to `Z_PK`) and extended it to every store file. | Truth 5 |
| REM-04 | 03-06, 03-09, 03-10 | tags read-only, no private write | SATISFIED. #307 changed the join key only; still read-only, no private selector. | Truth 5 |
| REM-06 | 03-02, 03-09 | reminders `folder` = list id | SATISFIED | Truth 6 |
| MAIL-05 | 03-10 | #229 decided handling | SATISFIED | Truth 7 |
| MAIL-06 | 03-10 | #230 five runs decide | SATISFIED | Truth 8 |

All 11 phase IDs are in PLAN frontmatter and in REQUIREMENTS.md (all marked Complete). No orphaned requirement. REM-05 (reminder alarms) is v2 and out of scope by decision.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `macos_apps_mcp/adapters/reminders_store.py` | | TBD / FIXME / XXX | none found | none |

Known accepted items from the first report (IN-03, IN-04 in 03-REVIEW-DISPOSITION.md) are unchanged.

### Human Verification Required

None open. The one human item of the first report is closed by 03-UAT.md (pass, 2026-10-07). The #307 device evidence (iCloud Mac, Intel iMac with a Local source) is in PR #313.

### Gaps Summary

No gaps. #307 changed the store join key and the set of files read. It preserved the read-only, fingerprinted, fail-closed contract behind REM-01, REM-03, REM-04 and REM-06, and it removed a false refusal on Local lists.

Limits to know (none block a truth):
- A Local subtask is not device-tested. The Intel iMac rig has none and EventKit cannot make one (PR #313 says so). The Local subtask path is covered by unit tests with a fixture store only.
- `tags_and_parents()` + `live_ids()` now cost 15.6 ms median (was 5.3 ms) because four files are each opened twice. Accepted in PR #313.
- The daemon stays at the last released version until a release cut and a `.app` rebuild; a Claude session sees none of this before then. Expected, not a gap.
- Housekeeping for the orchestrator: ROADMAP.md may still show Phase 3 unchecked.

---

_Verified: 2026-10-11_
_Verifier: Claude (gsd-verifier)_
