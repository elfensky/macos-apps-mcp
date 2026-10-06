---
phase: 03
review: 03-REVIEW.md
titles: json
findings:
  - id: WR-01
    severity: warning
    disposition: fixed
    title: "`update_reminder`, `update_event` and `delete_event` have no item-type guard (`complete_reminder` and `delete_reminder` do)"
  - id: WR-02
    severity: warning
    disposition: fixed
    title: "The subtask guard fails open when the store cannot see the parent (wrong store file, missing join key, or lag)"
  - id: IN-01
    severity: info
    disposition: fixed
    title: "`Recurrence` claims its invariants hold on direct construction but `interval` and `count` are only validated in `from_rrule`"
  - id: IN-02
    severity: info
    disposition: fixed
    title: "`create_reminder_list` accepts names that the exact-match resolver cannot reliably re-target"
  - id: IN-03
    severity: info
    disposition: skipped
    title: "The D-10 note is appended to `Pointer.summary` past `SUMMARY_MAX`"
  - id: IN-04
    severity: info
    disposition: deferred
    title: "`delete_event` post-delete check may false-fail for an id without an occurrence suffix"
open: 0
total: 6
recorded: 2026-10-06T18:39:35+00:00
---

# Phase 03: Code Review Disposition

| Finding | Severity | Disposition | Source |
|---------|----------|-------------|--------|
| WR-01 | warning | fixed | PR #281 (commit f05eeab): type guards before any mutation in update_reminder, update_event, delete_event |
| WR-02 | warning | fixed | PR #281 (commit 40fdc11): a missing live store row refuses delete/complete; NULL ids filtered; read() coverage names reminders the store lacks; device: a new reminder is in the store within 0.05 s |
| IN-01 | info | fixed | PR #281 (commit 2073819): Recurrence checks interval and count on direct construction |
| IN-02 | info | fixed | PR #281 (commit 90d0e62): edge whitespace refused; the persisted title is verified |
| IN-03 | info | skipped | by design (03-04): the D-10 note is a fixed constant appended after the bounded summary, so a long title never drops it; total stays bounded |
| IN-04 | info | deferred | unconfirmed without a device: test_delete_event_is_gone_on_device passed (single, this-event, future-events) in the 03-09 sweep; revisit only on a device false-fail |

Dispositions: `open` (recorded, not yet triaged), `fixed`, `skipped`, `deferred`.
Set `deferred` by hand and put the reason in the Source cell; both are preserved. A `|` in the reason is kept as prose and escaped on the next run.
Re-running the gate keeps every row it can. A row the current review no longer reports is kept and its Source cell flagged, so a finding does not leave this record silently.
