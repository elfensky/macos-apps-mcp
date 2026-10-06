---
status: testing
phase: 03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub
source: [03-VERIFICATION.md]
started: 2026-10-06T18:44:26Z
updated: 2026-10-06T18:44:26Z
---

## Current Test

number: 1
name: Device re-run of the paths PR #281 changed (subtask store-row refusal, type guards, list title verify, read coverage)
expected: |
  All pass. delete_reminder on a reminder just created through EventKit is not refused for a missing
  store row; delete_event, update_event and update_reminder still resolve their ids; create_reminder_list
  reads its title back. Commands, on the Mac with the Reminders store readable, against 6c2cdb3 (or the
  release build):
  uv run pytest -m integration tests/integration/test_eventkit_depth.py -k 'delete_reminder or delete_event or create_reminder_list or reminders_read'
  uv run pytest -m integration tests/test_integration.py -k "reminder or event or calendar or free_busy or all_day or recurring or request_access"
awaiting: user response

## Tests

### 1. Device re-run of the paths PR #281 changed (subtask store-row refusal, type guards, list title verify, read coverage)
expected: All pass; no false refusal right after create; event and reminder ids still resolve; list title reads back.
result: [pending]

## Summary

total: 1
passed: 0
issues: 0
pending: 1
skipped: 0
blocked: 0

## Gaps
