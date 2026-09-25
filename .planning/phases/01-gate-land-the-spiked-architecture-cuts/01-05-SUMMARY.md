---
phase: 01-gate-land-the-spiked-architecture-cuts
plan: 05
subsystem: mail
tags: [mail, applescript, dry-run, recoverable, gate-09, gate-10]

requires:
  - phase: 01-gate-land-the-spiked-architecture-cuts
    provides: "v0.11.0 release tag (plan 01-01), used as the dry-run identity baseline"
  - phase: 01-gate-land-the-spiked-architecture-cuts
    provides: "GATE-10 script-timeout tripwire and _DEDUPE 900s fix (plan 01-03), merged before this lane branched"
provides:
  - "recoverable(op, targets, act, *, dry_run, present) — the plane owns its dry-run preflight read, not the caller"
  - "mail.py's move_mail/trash_mail/dedupe_batch dry runs all route through recoverable() with a real presence read; no adapter-owned preview() bypass remains"
  - "v0.11.0 byte-identity baseline (tests/mail_recover_dry_run_baseline.json) for move/trash/undo dry-run envelopes and osascript argv"
  - "check_batch's BatchTooLarge text no longer claims a backup for update_status"
affects: ["01-08 (device verification on scratch mailbox; merges this PR)", "01-09 (GATE-10 requirement tick)"]

tech-stack:
  added: []
  patterns:
    - "Dry-run presence read owned by the plane (recoverable/preview), never re-derived per adapter call site"
    - "Byte-identity regression test against a captured pre-change baseline (json.dumps, key order included), regenerated from a release tag rather than a stale spike branch"

key-files:
  created:
    - tests/test_mail_recover_dry_run_identity.py
    - tests/mail_recover_dry_run_baseline.json
  modified:
    - macos_apps_mcp/adapters/mail_recover.py
    - macos_apps_mcp/adapters/mail.py
    - tests/test_mail_recover.py

key-decisions:
  - "dedupe_batch's dry run reads presence through the same _presence(src) plane as move/trash (GATE-09 success criterion 5), diverging from spike 4's present=None/_NO_READ escape — no caller needs an unverified preview; dedupe.py:316 only calls dry_run=False so no caller's behavior changes"
  - "recoverable(dry_run=True) has no present=None opt-out: Python cannot distinguish an omitted keyword from an explicit None, so a missing present always raises TypeError. Code review caught the first-pass docstring/error text implying an opt-out that could never work; corrected to point a genuinely read-less op at preview() directly instead"

requirements-completed: []  # GATE-09/GATE-10/GATE-13 are NOT ticked here — GATE-09 ticks at 01-08, GATE-10 at 01-09, GATE-13 at 01-14 per phase decisions_made

actuals:
  tokens: 6965
  tasks: 3
  commits: 3

coverage:
  - id: D1
    description: "recoverable() requires present on a dry run, runs it exactly once over the batch, never calls act/backup/audit_write on that path"
    requirement: GATE-09
    verification:
      - kind: unit
        ref: "tests/test_mail_recover_dry_run_identity.py#test_recoverable_dry_run_with_no_present_raises_naming_the_op"
        status: pass
      - kind: unit
        ref: "tests/test_mail_recover_dry_run_identity.py#test_dry_run_reads_present_once_in_order_never_calls_act"
        status: pass
      - kind: unit
        ref: "tests/test_mail_recover_dry_run_identity.py#test_wet_run_never_calls_present"
        status: pass
    human_judgment: false
  - id: D2
    description: "move/trash/undo dry-run envelopes and osascript argv are byte-identical to the v0.11.0 baseline"
    requirement: GATE-09
    verification:
      - kind: unit
        ref: "tests/test_mail_recover_dry_run_identity.py#test_move_dry_run_is_byte_identical"
        status: pass
      - kind: unit
        ref: "tests/test_mail_recover_dry_run_identity.py#test_trash_dry_run_is_byte_identical"
        status: pass
      - kind: unit
        ref: "tests/test_mail_recover_dry_run_identity.py#test_undo_dry_run_is_byte_identical"
        status: pass
    human_judgment: false
  - id: D3
    description: "dedupe_batch's dry run can no longer report \"planned\" for a target no read checked — the one intended delta from the baseline, asserted explicitly"
    requirement: GATE-09
    verification:
      - kind: unit
        ref: "tests/test_mail_recover_dry_run_identity.py#test_dedupe_dry_run_reads_presence"
        status: pass
    human_judgment: false
  - id: D4
    description: "check_batch's refusal text keeps \"not overridable\", drops the backup claim for update_status"
    requirement: GATE-10
    verification:
      - kind: unit
        ref: "tests/test_mail_recover_dry_run_identity.py#test_cap_and_empty_batch_errors"
        status: pass
      - kind: unit
        ref: "tests/test_mail_recover.py#test_batch_cap_text_claims_no_backup"
        status: pass
    human_judgment: false
  - id: D5
    description: "Card-4 PR open against develop, CI check green, review-clean, deliberately NOT merged pending the D-08 device verification (plan 01-08)"
    requirement: GATE-13
    verification: []
    human_judgment: true
    rationale: "Merge decision and the on-device scratch-mailbox verification are plan 01-08's owner-gated step, per CLAUDE.md's Mail-write verification rule and D-08. Not something this plan's automated tests can close."

duration: 45min
completed: 2026-09-25
status: complete
---

# Phase 1 Plan 05: Card 4 — recoverable() owns its dry-run preflight Summary

**`recoverable()` now requires and runs its own presence read on every dry run — move/trash/undo stay byte-identical to v0.11.0, and dedupe_batch can no longer preview "planned" for targets nobody checked; PR #215 is open, CI-green and review-clean, merge held for plan 01-08's device check.**

## Performance

- **Duration:** ~45 min (this resumed session; Tasks 1–2 were completed and committed in a prior session before a computer restart)
- **Completed:** 2026-09-25
- **Tasks:** 3 (Tasks 1–2 resumed/re-verified, Task 3 executed fully this session)
- **Files modified:** 5

## Accomplishments

- Re-confirmed Tasks 1 and 2 hold after the restart: all `<acceptance_criteria>` greps and the Task 2 `<verify>` command pass unchanged, no drift, no re-work needed.
- Ran the local verify triple (`uv run pytest` — 1394 passed; `uv run ruff check .` — clean; `uv run ruff format --check .` — 135 files already formatted).
- Pushed the lane and opened **PR #215**: https://github.com/elfensky/macos-apps-mcp/pull/215 — `refactor/gate-card-4-recoverable-preflight` → `develop`. Title: "refactor(mail): recoverable() owns its dry-run preflight (gate card 4, GATE-09)". Body names the plane-owned read, the dedupe divergence from spike 4 (GATE-09 success criterion 5), the v0.11.0 baseline, the check_batch text fix, and states plainly: **merge blocked until the D-08 scratch-mailbox verification (plan 01-08)**.
- Ran the code-review pass (Standards + Spec axes, self-run — no sub-agent tool available) over `origin/develop...HEAD`. One real finding, fixed, re-verified, re-pushed (see below). PR re-confirmed OPEN, `check` job **SUCCESS**, NOT merged.
- Confirmed both worktrees this phase still needs remain: `.worktrees/gate-card-4-recoverable-preflight` (locked) and `.worktrees/baseline-v0.11.0` (detached at `v0.11.0`), for plan 01-08.

## Code Review Summary (self-run, both axes)

**Standards axis** (CLAUDE.md, AGENTS.md, `docs/mail-applescript-facts.md`, ruff config):

- **Finding (fixed):** `recoverable()`'s docstring and its `TypeError` message both told a caller to "pass `present=None` explicitly" to opt out of the dry-run read if an op "truly has no read." That advice can never work through `recoverable()` — Python cannot distinguish an omitted `present` keyword from an explicit `present=None`, so both hit the exact same `if present is None: raise TypeError(...)` branch. This matters because GATE-09's whole point is that there is *no* opt-out through `recoverable()` (the spike's `present=None`/`_NO_READ` escape was deliberately not kept — see the plan's `<flagged_assumptions>`), so the docstring/error text was actively misleading about the one behavior this task exists to lock down. Fixed in `9cc4fe5`: the docstring and error message now correctly say there is no opt-out here, and a genuinely read-less op must call `preview()` directly (where `present=None` is a legitimate, visible-at-the-call-site default) instead of going through `recoverable()`. No behavior change — `test_recoverable_dry_run_with_no_present_raises_naming_the_op`'s `match=r"needs \`present\`"` still passes unchanged.
- Everything else checked clean: qualified imports (`from .. import runtime`, `runtime.run_osascript(...)`, per #176 — no adapter reaches into another), `run_osascript` calls stay on the one serialized worker, no new tool registrations (so no `_send_tool`/`_write_tool`/docstring-permission gate applies — these are adapter-internal helpers, not MCP tools), ruff/format clean, function sizes reasonable, naming conventions (`_present_ids`, `_presence`, snake_case) match the established patterns.

**Spec axis** (this plan + GATE-09/GATE-10 in REQUIREMENTS.md):

- GATE-09 text matches implementation exactly: `check_batch → present → preview` order in `recoverable()`; a dry run without a stated `present` raises `TypeError`; `dedupe_batch(dry_run=True)` can no longer report "planned" for unchecked targets (asserted explicitly against the baseline in `test_dedupe_dry_run_reads_presence`, not just observed). Device verification is explicitly deferred to plan 01-08 per D-08 — this plan's job was CI-green + review-clean, not the on-device proof.
- GATE-10's `check_batch` refusal-text fix present and tested (`test_batch_cap_text_claims_no_backup`, plus the identity test's `test_cap_and_empty_batch_errors` pinning "not overridable" while excluding "backed up").
- No open findings after the fix above.

## Task Commits

Each task was committed atomically (Tasks 1–2 committed in the prior, restart-interrupted session; the review fix committed this session):

1. **Task 1: recoverable() owns the dry-run read; move_mail through it; v0.11.0 baseline captured (tracer)** — `2649218` (feat)
2. **Task 2: trash and dedupe through the plane; undo/cap errors pinned; check_batch text fixed** — `30f6ded` (feat)
3. **Task 3: PR opened, CI green, code review — one Standards finding fixed** — `9cc4fe5` (fix)

**Plan metadata:** this SUMMARY.md is left uncommitted per the main-checkout rules; the orchestrator commits it with the wave's tracking update.

## Files Created/Modified
- `macos_apps_mcp/adapters/mail_recover.py` — `Present` type alias; `preview(..., present=)`; `recoverable(..., dry_run=, present=)`; `check_batch`'s refusal text (GATE-10); docstring/error-message fix from code review
- `macos_apps_mcp/adapters/mail.py` — `_present_ids`, `_presence` helpers; `move_mail`/`trash_mail`/`dedupe_batch` dry-run branches deleted, routed through `recoverable()`
- `tests/test_mail_recover_dry_run_identity.py` — new; `capture()` entry point, byte-identity tests (move/trash/undo), the explicit dedupe delta test, cap/empty-batch error-text tests, and the plan's `<behavior>` unit tests for `recoverable()` itself
- `tests/mail_recover_dry_run_baseline.json` — new; captured from tag `v0.11.0` via `uv run --project .worktrees/baseline-v0.11.0 python .../capture.py --capture`
- `tests/test_mail_recover.py` — `test_batch_cap_text_claims_no_backup` added

## Decisions Made

- Dedupe's dry run reads presence through `_presence(src)`, same as move/trash — the spike's `present=None` escape and `_NO_READ` sentinel are not kept. No caller needs an unverified preview, and `dedupe.py:316`'s only call site is `dry_run=False`, so no caller's behavior changes. (Per plan's `<flagged_assumptions>` and GATE-09 success criterion 5.)
- `recoverable()` has no `present=None` opt-out mechanism by design — this is deliberate (not an oversight), and the docstring/error text is now honest about it after the review fix.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Misleading docstring/error message in `recoverable()` suggesting an unusable `present=None` opt-out**
- **Found during:** Task 3 (code-review pass, Standards axis)
- **Issue:** The docstring and the raised `TypeError`'s own message told a caller to "pass `present=None` explicitly" to skip the dry-run read for an op with no read — but `recoverable()` has no way to distinguish an omitted keyword from an explicit `None`, so following that advice hits the identical `TypeError` again. This directly contradicts GATE-09's intent (no unverified preview escape through `recoverable()`), so leaving it would mislead the next person debugging this exact error.
- **Fix:** Rewrote both the docstring and the error message to state plainly there is no opt-out through `recoverable()`, and that a genuinely read-less op must call `preview()` directly (where `present=None` is a legitimate default). No behavior change; the existing `match=r"needs \`present\`"` test still passes.
- **Files modified:** `macos_apps_mcp/adapters/mail_recover.py`
- **Verification:** `uv run pytest tests/test_mail_recover_dry_run_identity.py tests/test_mail_recover.py -q` (37 passed), `uv run ruff check .` (clean), `uv run ruff format --check .` (clean). Pushed; CI `check` job re-ran SUCCESS.
- **Committed in:** `9cc4fe5`

---

**Total deviations:** 1 auto-fixed (1 bug — Rule 1, docstring/error-message correction found during self-run code review)
**Impact on plan:** Documentation/error-message correctness only; no functional change, no test behavior change, no re-scoping. Zero risk to the byte-identity guarantee (move/trash/undo tests re-passed unchanged).

## Issues Encountered

None beyond the deviation above. The computer-restart interruption between Task 2 and Task 3 left the lane in a fully committed, clean state exactly as `.continue-here.md` described — no recovery work was needed beyond re-running the acceptance-criteria greps to confirm nothing had drifted.

## Authentication Gates

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- **PR #215 is OPEN, `check` job SUCCESS, NOT merged.** https://github.com/elfensky/macos-apps-mcp/pull/215
- Both worktrees plan 01-08 needs are present and correctly configured: `.worktrees/gate-card-4-recoverable-preflight` (locked, tip `9cc4fe5`, tracks `origin/refactor/gate-card-4-recoverable-preflight`) and `.worktrees/baseline-v0.11.0` (detached at tag `v0.11.0`).
- Plan 01-08 (owner device stop, wave 5) does the scratch-mailbox (`Personal/macos-apps-mcp-test`) verification with the Mail watchdog running, then merges this PR. GATE-09 ticks only at 01-08; GATE-10 ticks only at 01-09 (per phase `decisions_made`) — this plan intentionally left both unticked in REQUIREMENTS.md.
- No blockers for wave 4 (01-06, 01-07) or the rest of wave 3 (01-04) — this plan's `files_modified` (`mail_recover.py`, `mail.py`, mail test files) do not overlap with either.

---
*Phase: 01-gate-land-the-spiked-architecture-cuts*
*Completed: 2026-09-25*
