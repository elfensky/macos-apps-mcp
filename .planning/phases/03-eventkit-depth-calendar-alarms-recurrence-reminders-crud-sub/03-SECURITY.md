---
phase: "3"
slug: "eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub"
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on severity (the blocking gate)
threats_open: 0
asvs_level: 1
created: "2026-10-06"
---

# Phase 3 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| probe script → the owner's EventKit store | probes write real lists, reminders and events on iCloud and Google | — |
| SUMMARY → public repo | anything recorded becomes public | — |
| MCP caller → `create_reminder_list(name)` | the name is model-supplied text that becomes a container title | — |
| EventKit store → Pointer.folder | container identifiers reach the model | — |
| MCP caller → RRULE text | model-supplied recurrence becomes a native rule in the owner's calendars | — |
| EventKit → persisted rule | the store may keep a different rule than requested (iCloud/Google) | — |
| PyPI → dev environment | a new third-party package enters the lock | — |
| device test → the owner's Google calendar | ~23 prefixed recurring events are written and swept | — |
| MCP caller → `alarms` | model-supplied integers become notifications on the owner's devices | — |
| EventKit → Google CalDAV | Google rewrites alarm lists 10-30 s after the save | — |
| Reminders sqlite store (user-typed tags, Apple schema) → adapter | untrusted text and an undocumented schema enter the process | — |
| adapter → model context | tag strings reach the model | — |
| MCP caller → `delete_reminder(id)` | a model-chosen id addresses a destructive write | — |
| EventKit ↔ Reminders store | EventKit cannot see subtasks; the store is the only witness of the cascade | — |
| MCP caller → `complete_reminder` / `delete_event` | model-chosen ids address writes on the owner's data | — |
| EventKit → CalDAV sources | a server can restore a deleted item after the commit | — |
| device tests → the owner's iCloud and Google data | real writes on the owner's accounts | — |
| cascade test → the owner's Reminders | a real cascade delete on iCloud | — |
| executor → GitHub tracker | issue closures are public and drive the life-cockpit | — |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-3-SC | Tampering | package installs | low | accept | no dependency change outside 03-04 (`git log -- pyproject.toml uv.lock`) | closed |
| T-3-SC/03-04 | Tampering | `uv add --dev python-dateutil` (and `six`) | high | mitigate | owner legitimacy check answered "approved" (03-04); dev group only; CI `uv sync --locked` | closed |
| T-3-01 | Tampering | probe writes into a family member's calendar or list | high | mitigate | device: Google calendar found by source + exact title, stop on 0 or >1 (03-01 probe script); list only on the default source | closed |
| T-3-02 | Denial of service | probe items left in the owner's calendars | medium | mitigate | device: `finally` teardown; p3-probes `left 0`, `list_removed`; spike 008 harness left=0 before/after | closed |
| T-3-03 | Information disclosure | real titles, ids or account names copied into the SUMMARY | medium | mitigate | result files hold booleans/counts only; SUMMARYs scanned clean | closed |
| T-3-04 | Tampering | a duplicate list name makes every later `list_name=` write ambiguous | medium | mitigate | `adapters/reminders.py` exact-name duplicate refused in the same `run_native` turn before the save | closed |
| T-3-05 | Tampering | control characters or an empty name in a container title | low | mitigate | `test_create_reminder_list_bad_name_raises_before_any_native_call` | closed |
| T-3-06 | Elevation of privilege | a write tool reachable in a read-only deployment | medium | mitigate | `@_additive_tool`; absent under `MACOS_APPS_READ_ONLY` (`tests/test_registry.py`) | closed |
| T-3-07 | Information disclosure | `folder` exposes a container identifier | low | accept | `eventkit.container_id` returns the opaque identifier only (already exposed by `calendars`/`reminder_lists`) | closed |
| T-3-08 | Tampering | an out-of-range or RFC-illegal BY value reaches the store (EventKit does not validate) | high | mitigate | `contracts._validate_by_parts` on every construction path; `test_rrule_rejects_out_of_range_values`, `…_rfc_5545_combination_bans` | closed |
| T-3-09 | Tampering | BYWEEKNO saved silently and expanded to DTSTART only | high | mitigate | BYWEEKNO refused by name; `weeksOfTheYear` always None; `test_rrule_rejects_unsupported_parts_by_name` | closed |
| T-3-10 | Repudiation | a changed or dropped BY part reported as a successful write | high | mitigate | canonical-dict verify-after-write; `test_verify_event_dropped_byday_raises`, `test_persisted_signature_sees_a_dropped_byday` | closed |
| T-3-11 | Tampering | a rename of a BYDAY reminder destroys the rule via an incomplete re-send text | medium | mitigate | `rrule_text` renders every part; `test_rrule_text_reparses_to_the_persisted_rule`; device `test_reminder_byday_round_trip` | closed |
| T-3-12 | Repudiation | an accepted rule silently adds an occurrence the caller did not ask for | medium | mitigate | `contracts.dtstart_in_rule` + Pointer note on create/update; `test_dtstart_outside_rule_*` | closed |
| T-3-13 | Tampering | a test-only library leaks into the runtime and changes recurrence semantics | medium | mitigate | dev group only; `test_dtstart_reference_library_is_never_imported_by_the_package` | closed |
| T-3-14 | Denial of service | prefixed test events left in the owner's Google calendar | medium | mitigate | `google_calendar` fixture sweeps to `left == 0`; sweep 14/14 | closed |
| T-3-15 | Tampering | an absolute alarm fires on the wrong day of a floating all-day event | high | mitigate | only `alarmWithRelativeOffset_`; verify requires 0 absolute alarms | closed |
| T-3-16 | Repudiation | Google silently drops the 6th alarm after an immediate verify passed | high | mitigate | more than 5 alarms refused in `CalendarEventData.__post_init__` | closed |
| T-3-17 | Tampering | a rename through `update_event` strips alarms set in Calendar.app | medium | mitigate | `alarms=None` leaves alarms untouched; `test_update_event_alarms_omitted_leaves_them_untouched` | closed |
| T-3-18 | Tampering | `bool`, float, string, duplicate or negative-on-timed alarm values | low | mitigate | bool/non-int/negative-on-timed/duplicate refused (owner A3/A4); `test_event_alarms_refused_at_the_boundary` | closed |
| T-3-19 | Tampering | prompt injection through tag text | medium | mitigate | `clean_summary` on every tag; untrusted-content notice kept; `test_a_tag_reaches_the_caller_as_one_clean_line` | closed |
| T-3-20 | Tampering | SQL injection | low | mitigate | constant SQL, bound `?`; `test_subtasks_of_binds_the_id_never_formats_it_into_the_sql` | closed |
| T-3-21 | Repudiation | the optional plane fails and the read looks complete | high | mitigate | EventKit read outside the `try`; store error → `coverage`; `test_read_never_folds_an_eventkit_failure_into_coverage` | closed |
| T-3-22 | Information disclosure | a Full Disk Access denial reported as "store not found" | low | mitigate | `os.scandir` PermissionError → `FullDiskAccessDenied` | closed |
| T-3-23 | Tampering | an OS update shifts Core Data column suffixes and the read returns wrong data | medium | mitigate | `_FINGERPRINT` → `SchemaDrift` → `coverage` | closed |
| T-3-24 | Tampering | a silent cascade deletes N subtasks the caller never saw | critical | mitigate | `SubtasksRequired` before the dry-run branch; device cascade refused/previewed/confirmed (2/2) | closed |
| T-3-25 | Tampering | a blind delete when the store cannot be read | high | mitigate | store error → `WriteRefused` before any remove; `test_delete_reminder_with_an_unreadable_store_refuses_and_changes_nothing` | closed |
| T-3-26 | Repudiation | the audit log records 1 reminder where N+1 went | high | mitigate | `ReminderDeleteSnapshotter` records all N+1; device audit before-state 3/3 | closed |
| T-3-27 | Repudiation | `deleted` reported for a reminder iCloud restored | medium | mitigate | gone-check on parent and every subtask → `VerificationFailed` | closed |
| T-3-28 | Tampering | an event's base id passed to `delete_reminder` deletes a calendar event | high | mitigate | `_is_reminder` before any remove/complete | closed |
| T-3-29 | Elevation of privilege | a destructive tool reachable in a read-only deployment or without a dry-run default | high | mitigate | `@_write_tool`, `dry_run=True` default, removes-content class; absent under READ_ONLY | closed |
| T-3-30 | Repudiation | `delete_event` reports `deleted` for an event that is still there | medium | mitigate | occurrence-aware re-resolve → `VerificationFailed`; device `test_delete_event_is_gone_on_device` | closed |
| T-3-31 | Information disclosure | a completed parent hides open subtasks from the user | medium | mitigate | open subtasks listed after the completion; refusal before any save when the store is unreadable (owner A9) | closed |
| T-3-32 | Denial of service | a store failure blocks every completion | low | accept | owner ruling A9: refuse rather than complete blind; `WriteRefused` names the store error | closed |
| T-3-33 | Tampering | a device test writes into a family member's calendar | high | mitigate | Google id resolved by source + exact title, one match; held only in the run environment | closed |
| T-3-34 | Denial of service | test items left in the owner's calendars or lists | medium | mitigate | fixture teardowns assert no prefixed list, scratch calendar removed, Google `left==0` | closed |
| T-3-35 | Information disclosure | identifiers or titles in the SUMMARY | medium | mitigate | Google id in no SUMMARY; helper file mode 600, deleted | closed |
| T-3-36 | Tampering | the cascade delete hits real reminders if the fixture is misidentified | high | mitigate | fixture-only ids; store links proven before any delete | closed |
| T-3-37 | Repudiation | an issue closed without device proof | medium | mitigate | issues closed after the passing sweep and cascade; comments carry PR numbers and counts only | closed |
| T-3-38 | Tampering | MAIL-05/06 "verified" by editing the record | low | mitigate | MAIL-05/06 rows predate the phase; 03-10 Task 2 read-only | closed |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above workflow.security_block_on count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-3-01 | T-3-07 | `folder` carries only the opaque container identifier that `calendars` and `reminder_lists` already return; no title or account name crosses | planning (03-02), confirmed by the security audit | 2026-10-06 |
| AR-3-02 | T-3-32 | Owner ruling A9: an unreadable Reminders store refuses every completion rather than completing a possible parent blind; the refusal names the store error and `doctor()` reports the Full Disk Access grant | owner (A9) | 2026-10-06 |
| AR-3-03 | T-3-SC | Every plan but 03-04 installs nothing; `uv sync --locked` restores the locked set (CI and publish run it) | planning, confirmed by the security audit | 2026-10-06 |

*Accepted risks do not resurface in future audit runs.*

---

## Advisories (non-blocking)

- **A1 (T-3-01):** the spike 008 alarm harness (`.claude/skills/spike-findings-macos-apps-mcp/sources/008-eventkit-alarms/probe_alarms.py`, git-ignored) takes the first (source, title) match and has no several-match stop. The 03-01 run was safe because the probe script had proven the pair unique in the same session. Add the stop before the harness is reused.
- **A2 (T-3-33):** the kept `google_calendar` fixture (`tests/integration/test_eventkit_depth.py`) checks that `MACOS_APPS_IT_GOOGLE_CALENDAR_ID` exists and is writable, not that its source is "Google". A source-title assert would make the 03-09 resolution rule part of the code for future device runs.

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-10-06 | 40 | 40 | 0 | gsd-security-auditor (ASVS L1, block_on high): 37 mitigated, 3 accepted |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-10-06
