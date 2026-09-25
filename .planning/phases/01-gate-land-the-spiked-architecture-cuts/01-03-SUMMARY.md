---
phase: 01-gate-land-the-spiked-architecture-cuts
plan: 03
subsystem: testing
tags: [ast, pytest, applescript, timeout, mail, gate-10]

# Dependency graph
requires:
  - phase: 01-gate-land-the-spiked-architecture-cuts
    provides: plan 01-01 (v0.11.0 cut) as the merge base for this lane
provides:
  - "GATE-10 script-timeout tripwire: `tests/test_applescript_timeout.py::test_every_call_site_backstop_covers_host_cap`, an ast-walk over every `run_osascript` call site (52 discovered) asserting the AppleScript template's own `with timeout of N seconds` backstop >= the host-side `timeout=` cap, failing closed (never skipping) on anything unresolvable"
  - "`mail._DEDUPE`'s run-block backstop raised 600s -> 900s to match `_DEDUPE_TIMEOUT = 900.0` (unchanged) — the one real inversion the tripwire caught"
affects: [02.1-mail-fixes, mail-timeout-tuning]

# Actuals (#2632)
actuals:
  tokens: 2350
  tasks: 2
  commits: 2

tech-stack:
  added: []
  patterns:
    - "AST call-site cross-reference tripwire (mirrors tests/test_native_seam.py's ast.walk shape): resolve a call's template and host-timeout arguments back to module attributes, then assert an invariant across all resolved sites — fails closed on anything the resolver can't pin down rather than skipping it"

key-files:
  created: []
  modified:
    - tests/test_applescript_timeout.py
    - macos_apps_mcp/adapters/mail.py

key-decisions:
  - "AST cross-reference over a hand-maintained mapping table (RESEARCH.md Assumption A1) — the AST route resolved all 52 real call sites cleanly (verified in a throwaway probe against unmerged develop before writing the test), so the table fallback was never needed"
  - "Backstop-resolution rule: the first `with timeout of N seconds` at or after the template's `on run` line (or the first in the template when there is no `on run`) — a handler's own with-timeout block before `on run` (e.g. `mail_addressing.MAILBOX_REF`'s 120s `mailboxFor` wrapper) does not count as the call's backstop"
  - "Unresolvable call sites (bad template/timeout expression shape) are hard test failures naming file:line, never `pytest.skip` — matches the plan's 'never skipped' must-have"

requirements-completed: [GATE-10]

coverage:
  - id: D1
    description: "Script-timeout tripwire over every run_osascript call site (52 sites: 51 adapters + doctor._PROBE), fail-closed on unresolvable expressions"
    requirement: "GATE-10"
    verification:
      - kind: unit
        ref: "tests/test_applescript_timeout.py::test_every_call_site_backstop_covers_host_cap"
        status: pass
      - kind: unit
        ref: "tests/test_applescript_timeout.py::test_call_sites_are_discovered"
        status: pass
    human_judgment: false
  - id: D2
    description: "mail._DEDUPE run-block backstop raised 600s -> 900s; _DEDUPE_TIMEOUT stays 900.0"
    requirement: "GATE-10"
    verification:
      - kind: unit
        ref: "tests/test_applescript_timeout.py::test_every_call_site_backstop_covers_host_cap[mail.py:1484:_DEDUPE]"
        status: pass
    human_judgment: false
  - id: D3
    description: "Card 9 landed on origin/develop via rebase-merged PR #213, lane removed, owner summary recorded"
    requirement: "GATE-10"
    verification:
      - kind: other
        ref: "gh pr view 213 --json state -> MERGED; git show origin/develop:macos_apps_mcp/adapters/mail.py | grep -c 'with timeout of 900 seconds' -> 1"
        status: pass
    human_judgment: false

duration: 46min
completed: 2026-09-25
status: complete
---

# Phase 1 Plan 3: Gate Card 9 — Script-Timeout Tripwire Summary

**Every `run_osascript` call site now asserts its AppleScript backstop >= its host-side timeout cap (52 sites, fail-closed), and the one real inversion it caught — `mail._DEDUPE`'s 600s script backstop under a 900s host cap — is fixed.**

## Performance

- **Duration:** ~46 min
- **Started:** 2026-09-25T11:10:00Z (approx)
- **Completed:** 2026-09-25T11:56:29Z
- **Tasks:** 2
- **Files modified:** 2 (`tests/test_applescript_timeout.py`, `macos_apps_mcp/adapters/mail.py`)

## Accomplishments

- Extended `tests/test_applescript_timeout.py` (the existing #56 home for osascript-template tests) with an `ast`-based cross-reference tripwire: it walks every `macos_apps_mcp/adapters/*.py` module and `macos_apps_mcp/doctor.py`, finds every call to `run_osascript` (qualified or unqualified), resolves the template string and the host-side `timeout=` cap back to module attributes, and asserts the template's own `with timeout of N seconds` backstop is `>=` the host cap.
- Discovered and covers 52 real call sites (`test_call_sites_are_discovered` guards the walk itself with a `>= 40` floor plus explicit checks for `mail.py`'s `_DEDUPE` and `doctor.py`'s `_PROBE`).
- Confirmed RED before the fix: exactly one failure, `mail.py:1484:_DEDUPE` (script backstop 600s < host cap 900.0s) — the exact bug RESEARCH.md's Pitfall 5 named, and the only inversion across all 52 sites.
- Fixed it: raised `_DEDUPE`'s run-block `with timeout of 600 seconds` to `900 seconds`; `_DEDUPE_TIMEOUT` stays `900.0` (never lowered a host cap). `_MOVE`/`_TRASH` keep their own 600s backstops — those pair with a 300s host cap and were never inverted.
- Verified GREEN: 55/55 in the target file, 1387/1387 across the full unit suite.
- Landed via PR #213, rebase-merged onto `develop` after CI green, the local verify triple green, and a self-run Standards + Spec code-review pass with no open issue.

## Task Commits

Both from the (now-removed) lane `fix/gate-card-9-timeout-tripwire`, rebase-merged onto `origin/develop` as part of merge commit `36624be`:

1. **Task 1 (RED): add the tripwire** — `0cfc0f0` on develop (`678491e` in the lane) `test(01-03): add GATE-10 script-timeout tripwire over every run_osascript call site`
2. **Task 1 (GREEN): fix `_DEDUPE`** — `36624be` on develop (`4c4cb02` in the lane) `fix(01-03): raise _DEDUPE script backstop to 900s (GATE-10)`

No REFACTOR commit — the GREEN implementation needed no cleanup.

**PR:** #213, merged `2026-09-25T11:54:54Z`, merge sha `36624be543e8df101f875753aa9efdf46c861751`.

## Files Created/Modified

- `tests/test_applescript_timeout.py` — added the GATE-10 call-site resolver (`_call_sites`, `_resolve_expr`, `_resolve_backstop`, `_resolve_host_cap`) and two tests (`test_call_sites_are_discovered`, `test_every_call_site_backstop_covers_host_cap`), parametrized over the 52 discovered sites
- `macos_apps_mcp/adapters/mail.py` — one-line change: `_DEDUPE`'s run-block `with timeout of 600 seconds` → `900 seconds`

## Decisions Made

- **AST cross-reference, not a hand-maintained table** (RESEARCH.md Assumption A1 left this to the implementer). A throwaway probe against unmerged `develop` resolved all 52 real call sites cleanly with zero unresolvable cases before any test code was written, so the simpler-fallback table was never needed.
- **Backstop-resolution rule**: first `with timeout of N seconds` at or after the template's `on run` line, else the first in the template. This correctly skips `mail_addressing.MAILBOX_REF`'s 120s `mailboxFor`-handler backstop (which precedes `on run` in `_MOVE`/`_TRASH`/`_DEDUPE`'s concatenated templates) and picks the real run-block backstop instead.
- **Fail closed, never skip**: an unresolvable template or timeout expression is a hard test failure naming `file:line`, matching the plan's must-have verbatim. No call site in the current tree hits this path (verified: 52/52 resolved), so it is untested-by-omission on the happy path but the RED-phase evidence for the `_DEDUPE` inversion confirms the failure-reporting path works for a real assertion failure; the "cannot resolve" branch is a defensive line for a future template shape (Phase 02.1's cross-note on `_MOVE`/`_TRASH`/`_PRESENT` scaling host timeouts with batch size, per PLAN.md's cross-phase note).

## Deviations from Plan

None — plan executed exactly as written. Card 9's own withdrawn `framed_script` wrapper (spike 9) was correctly not reintroduced, per CONTEXT.md.

## Code Review (D-07, self-run — no Task/Agent tool available for parallel sub-agents)

**Standards axis** (against `CLAUDE.md`, `.claude/CLAUDE.md`, `CONTRIBUTING.md`, plus the Fowler smell baseline):
- `ruff check .` and `ruff format --check .` both clean.
- Naming, module-private-underscore convention, and the frozen-dataclass (`_CallSite`) pattern match existing repo style (`Pointer`, `ReminderData`, etc. are also frozen dataclasses).
- Shape mirrors `tests/test_native_seam.py`'s existing `ast.parse` + `ast.walk` tripwire pattern, as the plan's `<read_first>` directed.
- No hard violations found. One judgement-call note: `module` and `template` parameters on the internal resolver helpers (`_resolve_expr`, `_resolve_backstop`, `_resolve_host_cap`) are not type-hinted — consistent with the existing test file's own untyped test-parameter style (e.g. `test_mail_module_does_not_import_the_seam_by_name(path)` in `test_native_seam.py`), so not flagged as an open issue.
- No Duplicated Code / Feature Envy / Speculative Generality / Shotgun Surgery / Divergent Change found — the recursive `_resolve_expr` handling both `Name` and one-level `Attribute` chains is the natural shape of the resolution problem, not padding for an unused future need.

**Spec axis** (against `01-03-PLAN.md`'s must-haves, artifacts, key-links, and prohibitions):
- Every `must_haves.truths` line verified directly: the ≥900s `_DEDUPE` backstop with `_DEDUPE_TIMEOUT` unchanged; the adjacency edge (`doctor._PROBE` at 120s vs 120.0s host passes — confirmed by running that single parametrized case); the empty-timeout-kwarg default to `runtime._OSASCRIPT_TIMEOUT`; numeric (not textual) `N >= host` comparison; the ordering rule (handler backstop before `on run` does not count, confirmed via `_MOVE`/`_TRASH`/`_DEDUPE`'s shared `mailboxFor` handler); fail-closed-never-skipped on unresolvable expressions.
- Both required artifacts present with their required substrings (`tests/test_applescript_timeout.py` contains `on run`; `mail.py` contains `with timeout of 900 seconds`).
- No scope creep: diff touches exactly the two files the plan's `files_modified` names, no `pyproject.toml` edit, spike 9's `framed_script` wrapper correctly not reintroduced.
- No open issue on either axis.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- GATE-10 fully satisfied on `develop`; the tripwire is now a permanent guard against a future template/call-site timeout inversion.
- Cross-phase note carried forward from PLAN.md: Phase 02.1 (MAIL-01, batch-size-scaled `_MOVE`/`_TRASH`/`_PRESENT` host timeouts) must extend this tripwire deliberately — it fails closed on any timeout expression shape it can't yet resolve (e.g. a computed per-batch timeout), so that phase's implementer should re-run `tests/test_applescript_timeout.py` after any host-timeout change there.
- No blockers for the remaining Phase 1 plans (01-02 native-seam, cards 3/4/9-adjacent Mail work continuing).

---
*Phase: 01-gate-land-the-spiked-architecture-cuts*
*Completed: 2026-09-25*

## Self-Check: PASSED

- `tests/test_applescript_timeout.py` present in the main checkout — FOUND
- `macos_apps_mcp/adapters/mail.py` present in the main checkout — FOUND
- `.planning/phases/01-gate-land-the-spiked-architecture-cuts/01-03-SUMMARY.md` present — FOUND
- Both task commits present on `origin/develop` (`0cfc0f0`, `36624be`) — FOUND
- `git show origin/develop:macos_apps_mcp/adapters/mail.py | grep -c "with timeout of 900 seconds"` → `1` — PASS
- `gh pr view 213 --json state,mergedAt` → `MERGED 2026-09-25T11:54:54Z` — PASS
