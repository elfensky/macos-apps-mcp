---
phase: 02-gate-close-fail-closed-suite-and-device-sweep
plan: 03
subsystem: testing
tags: [pytest, mail, fixtures, gate-12]

# Dependency graph
requires:
  - phase: 01-gate-land-the-spiked-architecture-cuts
    provides: the spiked-review adapters (mail.py search/overview) this fixture calls
provides:
  - "MARKER_SUBJECT / SEED_MARKERS constants and _scratch_account(rows) helper in tests/test_integration.py"
  - "fail-loud inbox_messages fixture scoped to 2 marker mails only, agreeing with scratch_mailbox's account"
affects: [02-04 (device sweep — runs the seed command and proves the fixture on device)]

# Actuals (#2632)
actuals:
  tokens: 4300
  tasks: 2
  commits: 1

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "One shared account-selection helper (_scratch_account) feeds two fixtures instead of each picking independently — closes a silent cross-account gap on multi-account Macs"
    - "A test fixture that cannot find its real-world precondition fails loud (pytest.fail, naming the exact remediation command) instead of skipping, per D-04"

key-files:
  created: []
  modified:
    - tests/test_integration.py

key-decisions:
  - "Marker subject text (\"macos-apps-mcp sweep marker\") deliberately avoids the word \"integration\" so a subject-substring search can never match the outbound tests' \"macos-apps-mcp integration …\" mails"
  - "inbox_messages depends on the same _scratch_account(rows) helper as scratch_mailbox, rather than picking an account independently, so the cross-account and same-account move tests always agree on which account they operate on (RESEARCH Pitfall 2)"

patterns-established:
  - "Fail-loud fixture pattern: when a device-side precondition (2 marker mails) is missing, pytest.fail() names the exact seed command to run, rather than pytest.skip()-ing past it silently"

requirements-completed: [GATE-12]

coverage:
  - id: D1
    description: "inbox_messages selects only marker-subject mails in the scratch account's INBOX, never falling back to real mail"
    requirement: GATE-12
    verification:
      - kind: unit
        ref: "uv run pytest -m integration tests/test_integration.py --collect-only -q -k \"move_mail_dry_run or move_then_undo or cross_account_move or update_mail_status\""
        status: pass
      - kind: unit
        ref: "uv run pytest -q && uv run ruff check . && uv run ruff format --check ."
        status: pass
    human_judgment: false
  - id: D2
    description: "The fixture fails loud (not skip) with the seed command named when fewer than 2 markers exist, and this is proven correct against real Mail on device"
    requirement: GATE-12
    verification: []
    human_judgment: true
    rationale: "The fail-loud path and the post-seed pass path can only be observed by running against real Mail on device — that device proof is plan 02-04 Task 3, not this plan"

# Metrics
duration: 12min
completed: 2026-09-29
status: complete
---

# Phase 2 Plan 3: Marker-mail-only fixture for the Mail write integration tests Summary

**D-04 fixture landed: Mail write tests use 2 marker mails only — PR #225**

## Performance

- **Duration:** 12 min
- **Started:** 2026-09-29T13:31:00Z (approx.)
- **Completed:** 2026-09-29T13:43:41Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments
- `MARKER_SUBJECT` (`"macos-apps-mcp sweep marker"`) and `SEED_MARKERS` (the exact one-time seed command) added to `tests/test_integration.py`, next to `_mail_adapter`
- `_scratch_account(rows) -> str` extracted as the one account-selection helper both `scratch_mailbox` and `inbox_messages` now call, closing the cross-account gap RESEARCH Pitfall 2 named
- `inbox_messages` rewritten: selects only `MARKER_SUBJECT` hits in the scratch account's INBOX, `pytest.fail()`s (never skips, never falls back) naming the count found, the folder, and the seed command when fewer than 2 are present
- PR #225 rebase-merged to `develop` (merge commit `8128303`); lane cleaned up (worktree unlocked/removed, branch deleted)

## Task Commits

Each task was committed atomically:

1. **Task 1: Marker constants, one account helper, fail-loud inbox_messages** - `2034a61` (test) — rebased onto `develop` as `8128303` on merge
2. **Task 2: Land the marker-fixture PR on develop** - no separate commit (PR merge only); cleanup steps (`gh pr merge --rebase --delete-branch`, worktree removal) carry no commit hash of their own

**Plan metadata:** this SUMMARY.md (committed by the orchestrator, per dispatch instructions — plans in this wave do not self-commit STATE.md/ROADMAP.md/REQUIREMENTS.md)

## Files Created/Modified
- `tests/test_integration.py` - `MARKER_SUBJECT`/`SEED_MARKERS` constants, `_scratch_account` helper, `scratch_mailbox` and `inbox_messages` fixtures rewritten (same names, same return shapes, 4 dependent tests unchanged)

## Decisions Made
- Marker subject avoids the word "integration" so a substring search can never match the outbound tests' `macos-apps-mcp integration …` mails (verified: neither string is a substring of the other)
- `inbox_messages` derives its account from the exact same helper `scratch_mailbox` uses, rather than picking independently, so same-account and cross-account move tests never silently disagree about which account they touch

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. One tooling note for future plans in this repo: the `rtk` PreToolUse hook filtered `uv run pytest --collect-only` output down to an empty match ("Pytest: No tests collected") on the first pass even though pytest itself collected correctly — `rtk proxy <cmd>` (documented in the user's global CLAUDE.md) bypasses that filtering and shows the real output. Worth remembering if a future collect-only check reports zero tests unexpectedly.

## User Setup Required

None - no external service configuration required. The one-time device seed (`SEED_MARKERS`) is documented here and in the PR body for plan 02-04 to run with the owner present; it is not run by this plan (test-only change, no Mail write executed).

## Seed command (for plan 02-04 Task 3)

Run once from the repo root, with the Mail watchdog loaded (`launchctl list | grep ren.lav.mail-watchdog`):

```
uv run python -c "from macos_apps_mcp.adapters.mail import MailAdapter as M; [M().send('andrei@lav.ren', 'macos-apps-mcp sweep marker', 'Marker mail for the integration sweep (D-04). Leave it in the INBOX.', dry_run=False) for _ in range(2)]"
```

## Next Phase Readiness
- `develop` carries the marker-only fixture; the unit suite (1471 passed, 80 deselected) and `ruff check`/`ruff format --check` are green on `develop`
- Plan 02-04 can run the seed command above once, then prove the fixture on device (fail loud before seeding, pass after)
- No blockers

---
*Phase: 02-gate-close-fail-closed-suite-and-device-sweep*
*Completed: 2026-09-29*

## Self-Check: PASSED

- FOUND: `tests/test_integration.py`
- FOUND: commit `8128303` (rebase-merged onto `origin/develop` via PR #225)
- FOUND: `.planning/phases/02-gate-close-fail-closed-suite-and-device-sweep/02-03-SUMMARY.md`
