---
phase: 05
review: 05-REVIEW.md
titles: json
findings:
  - id: CR-01
    severity: critical
    disposition: open
    title: "The audit reader splits on `str.splitlines()`, so a write whose text holds U+2028, U+2029 or U+0085 vanishes from the dashboard"
  - id: WR-01
    severity: warning
    disposition: open
    title: "38 tests open the developer's real TCC databases"
  - id: WR-02
    severity: warning
    disposition: open
    title: "The CLI sends the page key to whatever listens on port 47632, and the restart flow hands the cookie to a port squatter"
  - id: WR-03
    severity: warning
    disposition: open
    title: "Dashboard toggles and restarts are shown as \"What the model asked for\", with an invented `dry_run` row and a `changes` chip"
  - id: WR-04
    severity: warning
    disposition: open
    title: "PM-37's cap bounds the count of unknown adapter names, not their length: one long name still blows the `doctor` budget"
  - id: WR-05
    severity: warning
    disposition: open
    title: "A failure while building the dashboard takes MCP down; only a failed port bind is isolated"
  - id: WR-06
    severity: warning
    disposition: open
    title: "A toggle returns 303 even when its audit record was not written"
  - id: IN-01
    severity: info
    disposition: open
    title: "The 0.15.0 changelog still says \"This release adds the Usage page\""
  - id: IN-02
    severity: info
    disposition: open
    title: "The adapter-name set and the version lookup are written five times"
  - id: IN-03
    severity: info
    disposition: open
    title: "Private cross-module reach and a shadowed parameter"
  - id: IN-04
    severity: info
    disposition: open
    title: "`doctor` reports the dashboard URL even when every page answers 503"
  - id: IN-05
    severity: info
    disposition: open
    title: "The adapter gate re-reads the deny-list for every tool during import"
open: 12
total: 12
recorded: 2026-10-22T20:58:32.964Z
---

# Phase 05: Code Review Disposition

| Finding | Severity | Disposition | Source |
|---------|----------|-------------|--------|
| CR-01 | critical | open | - |
| WR-01 | warning | open | - |
| WR-02 | warning | open | - |
| WR-03 | warning | open | - |
| WR-04 | warning | open | - |
| WR-05 | warning | open | - |
| WR-06 | warning | open | - |
| IN-01 | info | open | - |
| IN-02 | info | open | - |
| IN-03 | info | open | - |
| IN-04 | info | open | - |
| IN-05 | info | open | - |

Dispositions: `open` (recorded, not yet triaged), `fixed`, `skipped`, `deferred`.
Set `deferred` by hand and put the reason in the Source cell; both are preserved. A `|` in the reason is kept as prose and escaped on the next run.
Re-running the gate keeps every row it can. A row the current review no longer reports is kept and its Source cell flagged, so a finding does not leave this record silently. ONE exception: when a finding id is REUSED by a different finding, the earlier decision cannot keep a row — the id is taken — and it is dropped. A RECORDED decision (anything but `open`) is named on the console when that happens; a row still at `open` is replaced silently, because `open` records no decision to lose.
