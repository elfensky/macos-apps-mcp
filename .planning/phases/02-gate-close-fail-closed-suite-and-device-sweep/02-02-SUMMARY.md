---
phase: 02-gate-close-fail-closed-suite-and-device-sweep
plan: 02
subsystem: testing
tags: [pytest, ast, native-seam, gate-11, doctor, ci]

# Dependency graph
requires:
  - phase: 01-02
    provides: the runtime seam lock (conftest.py refuses an unfaked run_osascript/body_file/tracked_run) and the _NATIVE_MODULES glob this plan's tripwire extends
provides:
  - doctor._process_name reaches ps only through runtime.tracked_run (qualified) — the last direct subprocess call in the native modules is gone
  - a permanent AST regression guard (test_native_module_spawns_no_subprocess_directly) failing any future direct subprocess.{run,Popen,call,check_call,check_output} spawn in doctor.py or adapters/*.py
affects: [02-03 (device sweep — GATE-11 is a prerequisite fact, not a blocking dependency), any future adapter touching subprocess]

# Actuals (#2632)
actuals:
  tokens: 1170
  tasks: 2
  commits: 1

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "GATE-11 proof pattern: a one-off pytest plugin (loaded via -p, never committed)
      wraps subprocess.Popen.__init__ to count ps/pgrep spawns per test nodeid — used
      once to measure a leak's before/after count, superseded going forward by the
      permanent AST tripwire"

key-files:
  created: []
  modified:
    - macos_apps_mcp/doctor.py
    - tests/test_native_seam.py

key-decisions:
  - "Popen-spy plugin kept as scratch under the main checkout's git-ignored .worktrees/ (popen_spy.py), never committed to tests/ — mirrors the .daemon_probe.py convention (STATE.md); the AST tripwire is the permanent guard, the spy is a one-time measurement tool"
  - "AST tripwire scoped to ast.Call nodes only (plus a by-name ImportFrom), so shortcuts.py's three legitimate `except subprocess.TimeoutExpired as e:` references are not flagged"

requirements-completed: [GATE-11]

coverage:
  - id: D1
    description: "doctor._process_name reaches ps only through the locked runtime.tracked_run seam"
    requirement: "GATE-11"
    verification:
      - kind: unit
        ref: "tests/test_doctor.py, tests/test_doctor_deploy.py (full files, _no_live_process_probe autouse fixture — unchanged, now exercised through the swapped call)"
        status: pass
      - kind: other
        ref: "one-off Popen-spy run: POPEN_SPY total=0 tests=0 after the fix (was total=30 tests=15 before)"
        status: pass
    human_judgment: false
  - id: D2
    description: "A direct subprocess spawn in doctor.py or any adapters/*.py fails the AST tripwire; a bare subprocess.TimeoutExpired reference does not"
    requirement: "GATE-11"
    verification:
      - kind: unit
        ref: "tests/test_native_seam.py#test_native_module_spawns_no_subprocess_directly"
        status: pass
    human_judgment: false
  - id: D3
    description: "The unit suite stays green in default, READ_ONLY=1 and ALLOW_SEND=mail modes after the swap"
    requirement: "GATE-11"
    verification:
      - kind: unit
        ref: "uv run pytest -q; MACOS_APPS_READ_ONLY=1 uv run pytest -q; MACOS_APPS_ALLOW_SEND=mail uv run pytest -q"
        status: pass
    human_judgment: true
    rationale: "READ_ONLY=1 run still shows the same 12 pre-existing GATE-07 failures (02-01's scope, unrelated to this doctor.py/test_native_seam.py change) — a human/verifier should confirm no NEW failure was introduced by diffing the failing-test list against RESEARCH.md's documented 12, since this plan's own suite runs alone cannot distinguish 'pre-existing' from 'newly broken' without that external reference."

duration: 20min
completed: 2026-09-29
status: complete
---

# Phase 2 Plan 02: GATE-11 — doctor's process probe through the locked seam Summary

**GATE-11 green: 0 live ps/pgrep (was 30 spawns across 15 tests), doctor._process_name now calls runtime.tracked_run qualified, and a new AST tripwire fails any future direct subprocess spawn in doctor.py or adapters/*.py — PR #226 rebase-merged to develop.**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-09-29T13:25:00Z (approx.)
- **Completed:** 2026-09-29T13:45:45Z
- **Tasks:** 2 completed
- **Files modified:** 2

## Accomplishments

- `doctor._process_name` (`macos_apps_mcp/doctor.py`) now calls `runtime.tracked_run(["ps", "-o", "comm=", "-p", str(pid)], timeout=5.0)` instead of a bare `subprocess.run(...)` — the last direct `subprocess` spawn in the native-reaching modules is gone. The `except (OSError, subprocess.SubprocessError)` clause, the `f"pid {pid}"` fallback, and `import subprocess` are unchanged, so no test needed a behavior change: the existing `_no_live_process_probe` autouse fakes in `tests/test_doctor.py` and `tests/test_doctor_deploy.py` already monkeypatch `runtime.tracked_run` to an empty-stdout result, which now covers this call path too.
- `tests/test_native_seam.py` gained `test_native_module_spawns_no_subprocess_directly`, an AST tripwire parametrized over the same `_NATIVE_MODULES` glob as the existing by-name-import check. It fails on an `ast.Call` to `subprocess.{run,Popen,call,check_call,check_output}` (qualified attribute access) or an `ast.ImportFrom` that pulls one of those names from `subprocess` — scoped to those two node types so `shortcuts.py`'s three `except subprocess.TimeoutExpired as e:` references (a bare exception-class reference, not a spawn) are never flagged.
- One-off Popen-spy proof (`.worktrees/popen_spy.py`, git-ignored, never committed — the main checkout's scratch convention): baseline `POPEN_SPY total=30 tests=15` before the fix (all 15 nodeids under `tests/test_doctor.py` (8) or `tests/test_doctor_deploy.py` (7), 2 spawns each — self pid + parent pid, matching CONTEXT.md's measurement exactly), `POPEN_SPY total=0 tests=0` after.
- Pre-swap tripwire run (`uv run pytest tests/test_native_seam.py -q -k spawns_no_subprocess`): exactly 1 failed — `test_native_module_spawns_no_subprocess_directly[doctor.py]` — 20 passed. The tripwire bites before the fix and stays green on all 21 native modules after it.
- PR #226 (`fix/gate-11-doctor-seam` → `develop`) rebase-merged after CI green, local `uv run pytest` / `MACOS_APPS_ALLOW_SEND=mail uv run pytest` / `ruff check .` / `ruff format --check .` all clean, and a code-review pass over `origin/develop...HEAD` (Standards + Spec axes) found no open issue. Merge commit `6098194` on `develop`.

## Task Commits

Each task was committed atomically:

1. **Task 1: Spy baseline, tripwire that bites, seam swap, spy at 0 (tracer)** — `a93f77d` (fix), rebase-merged onto `develop` as `6098194`

**Task 2 (Land the GATE-11 PR)** produced no new source commit in the lane — its work was the code-review pass, push, PR #226, CI wait, rebase-merge, and lane cleanup. No plan metadata commit was made in the lane per the sequential-mode instructions (the orchestrator commits this SUMMARY.md centrally with the wave).

## Files Created/Modified

- `macos_apps_mcp/doctor.py` — `_process_name` now calls `runtime.tracked_run(...)` qualified instead of `subprocess.run(...)` directly
- `tests/test_native_seam.py` — new `_SPAWNERS` frozenset and `test_native_module_spawns_no_subprocess_directly` (AST tripwire); one docstring sentence added

Scratch (not committed): `/Users/andrei/Developer/macos-apps-mcp/.worktrees/popen_spy.py` — the one-off Popen-spy pytest plugin, kept for the verifier to re-run.

## Decisions Made

- Popen-spy plugin lives as scratch under the main checkout's git-ignored `.worktrees/`, never committed to `tests/` — it is a one-time measurement tool, superseded going forward by the permanent AST tripwire (per CONTEXT.md's explicit framing and the `.daemon_probe.py` precedent).
- AST tripwire scoped strictly to `ast.Call`/`ast.ImportFrom` node types so it cannot false-flag `shortcuts.py`'s legitimate `except subprocess.TimeoutExpired` exception-class references.

## Deviations from Plan

None - plan executed exactly as written.

One process note: the code-review pass in Task 2 was performed inline by this executor (Standards + Spec axes assessed directly) rather than via the `code-review` skill's parallel `general-purpose` sub-agents, because this executor's toolset has no `Agent`/`Task` tool to spawn sub-agents. Both axes were still assessed against the plan spec and CLAUDE.md standards; no open issue was found on either axis. Also per the orchestrator's explicit instruction to this dispatch, the plan's own "Record the landing with the `vault-journal` skill" step was skipped here — the orchestrator records vault-journal landings once per wave, not per plan, to avoid duplicate entries for the same wave's parallel plans (02-01/02-02/02-03).

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Owner summary (one line, per Phase 1 D-07)

GATE-11 green: 0 live ps/pgrep in the unit suite (was 30 spawns across 15 doctor tests), `doctor._process_name` now routed through `runtime.tracked_run`, and a new AST tripwire blocks any future direct `subprocess` spawn in `doctor.py`/`adapters/*.py` — PR #226 merged to `develop`.

## Next Phase Readiness

- GATE-11 holds on `develop`: `origin/develop:macos_apps_mcp/doctor.py` contains `runtime.tracked_run(` (grep confirms 1 hit) and `origin/develop:tests/test_native_seam.py` contains `test_native_module_spawns_no_subprocess_directly` (grep confirms 1 hit).
- The `MACOS_APPS_READ_ONLY=1 uv run pytest` run in this lane still showed the same 12 pre-existing GATE-07 failures documented in `.planning/phases/02-gate-close-fail-closed-suite-and-device-sweep/02-RESEARCH.md` — those are plan 02-01's scope; no new read-only failure was introduced by this plan's change.
- `.worktrees/popen_spy.py` is kept (git-ignored, not committed) in case the verifier wants to re-run the proof.
- Lane `fix/gate-11-doctor-seam` / `.worktrees/gate-11-doctor-seam` fully cleaned up: unlocked, removed, local branch deleted; remote branch deleted by `gh pr merge --delete-branch`.

## Self-Check: PASSED

- `grep -c "runtime.tracked_run(" macos_apps_mcp/doctor.py` (on `origin/develop`, post-merge): `1`
- `grep -c "def test_native_module_spawns_no_subprocess_directly" tests/test_native_seam.py` (on `origin/develop`, post-merge): `1`
- `git log --oneline --all --grep="gate-11"` finds commit `a93f77d` / `6098194`: confirmed
- PR #226: `state: MERGED`, merge commit `6098194071003eeba47d53394ed900a0e12ef303`
- `git worktree list` no longer lists `.worktrees/gate-11-doctor-seam`: confirmed

---
*Phase: 02-gate-close-fail-closed-suite-and-device-sweep*
*Completed: 2026-09-29*
