---
phase: 05
review: 05-REVIEW.md
titles: json
findings:
  - id: CR-01
    severity: critical
    disposition: fixed
    title: "The audit reader splits on `str.splitlines()`, so a write whose text holds U+2028, U+2029 or U+0085 vanishes from the dashboard"
  - id: WR-01
    severity: warning
    disposition: deferred
    title: "38 tests open the developer's real TCC databases"
  - id: WR-02
    severity: warning
    disposition: accepted
    title: "The CLI sends the page key to whatever listens on port 47632, and the restart flow hands the cookie to a port squatter"
  - id: WR-03
    severity: warning
    disposition: deferred
    title: "Dashboard toggles and restarts are shown as \"What the model asked for\", with an invented `dry_run` row and a `changes` chip"
  - id: WR-04
    severity: warning
    disposition: fixed
    title: "PM-37's cap bounds the count of unknown adapter names, not their length: one long name still blows the `doctor` budget"
  - id: WR-05
    severity: warning
    disposition: deferred
    title: "A failure while building the dashboard takes MCP down; only a failed port bind is isolated"
  - id: WR-06
    severity: warning
    disposition: deferred
    title: "A toggle returns 303 even when its audit record was not written"
  - id: IN-01
    severity: info
    disposition: skipped
    title: "The 0.15.0 changelog still says \"This release adds the Usage page\""
  - id: IN-02
    severity: info
    disposition: deferred
    title: "The adapter-name set and the version lookup are written five times"
  - id: IN-03
    severity: info
    disposition: deferred
    title: "Private cross-module reach and a shadowed parameter"
  - id: IN-04
    severity: info
    disposition: deferred
    title: "`doctor` reports the dashboard URL even when every page answers 503"
  - id: IN-05
    severity: info
    disposition: deferred
    title: "The adapter gate re-reads the deny-list for every tool during import"
open: 12
total: 12
recorded: 2026-10-22T20:58:32.964Z
---

# Phase 05: Code Review Disposition

| Finding | Severity | Disposition | Source |
|---------|----------|-------------|--------|
| CR-01 | critical | fixed | #431 |
| WR-01 | warning | deferred | #430 |
| WR-02 | warning | accepted | AR-05-08 in 05-SECURITY.md (a T-05-44 variant) |
| WR-03 | warning | deferred | #430 |
| WR-04 | warning | fixed | #431 |
| WR-05 | warning | deferred | #430 |
| WR-06 | warning | deferred | #430 |
| IN-01 | info | skipped | a line in the released 0.15.0 CHANGELOG section; not rewritten |
| IN-02 | info | deferred | #430 |
| IN-03 | info | deferred | #430 |
| IN-04 | info | deferred | #430 |
| IN-05 | info | deferred | #430 |

Dispositions: `open` (recorded, not yet triaged), `fixed`, `skipped`, `deferred`.
Set `deferred` by hand and put the reason in the Source cell; both are preserved. A `|` in the reason is kept as prose and escaped on the next run.
Re-running the gate keeps every row it can. A row the current review no longer reports is kept and its Source cell flagged, so a finding does not leave this record silently. ONE exception: when a finding id is REUSED by a different finding, the earlier decision cannot keep a row — the id is taken — and it is dropped. A RECORDED decision (anything but `open`) is named on the console when that happens; a row still at `open` is replaced silently, because `open` records no decision to lose.
