---
phase: 04
review: 04-REVIEW.md
titles: json
findings:
  - id: CR-01
    severity: critical
    disposition: open
    title: "Export-failure cleanup deletes a file the tool did not write"
  - id: WR-01
    severity: warning
    disposition: open
    title: "Body search falls back to 1-character words and floods results"
  - id: WR-02
    severity: warning
    disposition: open
    title: "A `VerificationFailed` export leaves a stray directory and a file of its own"
  - id: IN-01
    severity: info
    disposition: open
    title: "`FileExistsError` and other `OSError`s bypass `_guard`"
  - id: IN-02
    severity: info
    disposition: open
    title: "`photos_db` maps every osxphotos failure to `SchemaDrift` and echoes raw text"
  - id: IN-03
    severity: info
    disposition: open
    title: "Long original filenames lose the id disambiguator"
  - id: IN-04
    severity: info
    disposition: open
    title: "Body search silently misses CJK and other unsegmented scripts"
  - id: IN-05
    severity: info
    disposition: open
    title: "`_body_hits` builds its SQL by string replacement on `_FROM`"
  - id: IN-06
    severity: info
    disposition: open
    title: "Stale references after the Photos move and the 3.12 floor"
  - id: IN-07
    severity: info
    disposition: open
    title: "Integration fixture reads osxphotos objects off the native worker"
open: 10
total: 10
recorded: 2026-10-19T12:14:24.475Z
---

# Phase 04: Code Review Disposition

| Finding | Severity | Disposition | Source |
|---------|----------|-------------|--------|
| CR-01 | critical | open | - |
| WR-01 | warning | open | - |
| WR-02 | warning | open | - |
| IN-01 | info | open | - |
| IN-02 | info | open | - |
| IN-03 | info | open | - |
| IN-04 | info | open | - |
| IN-05 | info | open | - |
| IN-06 | info | open | - |
| IN-07 | info | open | - |

Dispositions: `open` (recorded, not yet triaged), `fixed`, `skipped`, `deferred`.
Set `deferred` by hand and put the reason in the Source cell; both are preserved. A `|` in the reason is kept as prose and escaped on the next run.
Re-running the gate keeps every row it can. A row the current review no longer reports is kept and its Source cell flagged, so a finding does not leave this record silently. ONE exception: when a finding id is REUSED by a different finding, the earlier decision cannot keep a row — the id is taken — and it is dropped. A RECORDED decision (anything but `open`) is named on the console when that happens; a row still at `open` is replaced silently, because `open` records no decision to lose.
