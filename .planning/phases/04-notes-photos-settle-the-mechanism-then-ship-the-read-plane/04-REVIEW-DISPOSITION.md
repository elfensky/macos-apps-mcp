---
phase: 04
review: 04-REVIEW.md
titles: json
findings:
  - id: CR-01
    severity: critical
    disposition: fixed
    title: "Export-failure cleanup deletes a file the tool did not write"
  - id: WR-01
    severity: warning
    disposition: fixed
    title: "Body search falls back to 1-character words and floods results"
  - id: WR-02
    severity: warning
    disposition: fixed
    title: "A `VerificationFailed` export leaves a stray directory and a file of its own"
  - id: IN-01
    severity: info
    disposition: deferred
    title: "`FileExistsError` and other `OSError`s bypass `_guard`"
  - id: IN-02
    severity: info
    disposition: fixed
    title: "`photos_db` maps every osxphotos failure to `SchemaDrift` and echoes raw text"
  - id: IN-03
    severity: info
    disposition: fixed
    title: "Long original filenames lose the id disambiguator"
  - id: IN-04
    severity: info
    disposition: fixed
    title: "Body search silently misses CJK and other unsegmented scripts"
  - id: IN-05
    severity: info
    disposition: fixed
    title: "`_body_hits` builds its SQL by string replacement on `_FROM`"
  - id: IN-06
    severity: info
    disposition: deferred
    title: "Stale references after the Photos move and the 3.12 floor"
  - id: IN-07
    severity: info
    disposition: fixed
    title: "Integration fixture reads osxphotos objects off the native worker"
open: 0
total: 10
recorded: 2026-10-19T12:14:24.475Z
---

# Phase 04: Code Review Disposition

| Finding | Severity | Disposition | Source |
|---------|----------|-------------|--------|
| CR-01 | critical | fixed | #385: FileExistsError raises the never-overwrite refusal and never unlinks |
| WR-01 | warning | fixed | #385: 1-character words dropped before the 4-character rule |
| WR-02 | warning | fixed | #385: the stray file osxphotos reported is removed only when new in dest_dir; the directory resolve_dest made stays |
| IN-01 | info | deferred | #383 (pre-existing for Mail; error typing only) |
| IN-02 | info | fixed | #385: raw osxphotos text logged, not in the agent text |
| IN-03 | info | fixed | #385: stem cut before _<id8> |
| IN-04 | info | fixed | #385: CJK limit documented (docstring, README, decision doc) |
| IN-05 | info | fixed | #385: assert on the _FROM replace |
| IN-06 | info | deferred | #385 fixed the doctor comment; ruff target-version py312 is #384 |
| IN-07 | info | fixed | #385: fixture maps to strings on the native worker and skips hidden photos |

Dispositions: `open` (recorded, not yet triaged), `fixed`, `skipped`, `deferred`.
Set `deferred` by hand and put the reason in the Source cell; both are preserved. A `|` in the reason is kept as prose and escaped on the next run.
Re-running the gate keeps every row it can. A row the current review no longer reports is kept and its Source cell flagged, so a finding does not leave this record silently. ONE exception: when a finding id is REUSED by a different finding, the earlier decision cannot keep a row — the id is taken — and it is dropped. A RECORDED decision (anything but `open`) is named on the console when that happens; a row still at `open` is replaced silently, because `open` records no decision to lose.
