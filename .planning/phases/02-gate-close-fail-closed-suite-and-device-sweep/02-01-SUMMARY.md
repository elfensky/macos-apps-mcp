---
phase: 02-gate-close-fail-closed-suite-and-device-sweep
plan: 01
subsystem: testing
tags: [pytest, registry, ci, gate-07]

# Dependency graph
requires:
  - phase: 01-gate-land-the-spiked-architecture-cuts
    provides: "the registry.TOOLS / ToolRecord seam (registered=False kept for gated-off tools), the _gate_off_only marker shape, and the read-only baseline of 12 failures"
provides:
  - "MACOS_APPS_READ_ONLY=1 uv run pytest green (0 failed, 0 error) in default, READ_ONLY=1, ALLOW_SEND=mail and READ_ONLY=1+ALLOW_SEND=mail modes"
  - "the registry-record-first / registration-state-second reading pattern applied to all 4 remaining 'what IS this tool' fact tests"
  - "one named skip marker (_write_gate_on_only) for call tests that require the write tier to be registered"
  - "CI enforces the read-only suite on every PR and push to develop"
affects: [02-02, 02-03, GATE-11, GATE-12]

# Actuals (#2632)
actuals:
  tokens: 2356
  tasks: 2
  commits: 2

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Fact tests about a tool's declared nature read registry.TOOLS.items() unfiltered (never r.registered); call tests that need _guard to be applied skip read-only through one named marker."

key-files:
  created: []
  modified:
    - tests/test_tool_annotations.py
    - tests/test_audit_middleware.py
    - tests/test_mail_cleanup.py
    - tests/test_server.py
    - .github/workflows/ci.yml

key-decisions:
  - "D-01 (locked): 4 fact tests read registry.TOOLS directly (every record, registered or not); 8 call tests skip read-only through one named marker (_write_gate_on_only, same shape as _gate_off_only). No test re-implements _guard."
  - "D-02 (locked): CI runs the suite a second time with MACOS_APPS_READ_ONLY=1, directly after the existing uv run pytest step, same job."

requirements-completed: [GATE-07]

coverage:
  - id: D1
    description: "MACOS_APPS_READ_ONLY=1 uv run pytest exits 0 with no failed/error, in default, READ_ONLY=1, ALLOW_SEND=mail and combined READ_ONLY=1+ALLOW_SEND=mail modes"
    requirement: "GATE-07"
    verification:
      - kind: unit
        ref: "MACOS_APPS_READ_ONLY=1 uv run pytest -q (local, and the develop CI run after merge)"
        status: pass
      - kind: unit
        ref: "uv run pytest -q && MACOS_APPS_ALLOW_SEND=mail uv run pytest -q && MACOS_APPS_READ_ONLY=1 MACOS_APPS_ALLOW_SEND=mail uv run pytest -q"
        status: pass
    human_judgment: false
  - id: D2
    description: "The 4 fact tests read registry.TOOLS.items() unfiltered and run (not skip) in read-only mode; the 8 call tests skip read-only through exactly one named marker"
    requirement: "GATE-07"
    verification:
      - kind: unit
        ref: "grep -c '^@_write_gate_on_only' tests/test_server.py == 8; grep -c '_write_gate_on_only = pytest.mark.skipif(' tests/test_server.py == 1"
        status: pass
      - kind: unit
        ref: "MACOS_APPS_READ_ONLY=1 uv run pytest tests/test_tool_annotations.py tests/test_audit_middleware.py tests/test_mail_cleanup.py -q (52 passed, 0 skipped)"
        status: pass
    human_judgment: false
  - id: D3
    description: "CI runs MACOS_APPS_READ_ONLY=1 uv run pytest as a second step, directly after the default uv run pytest step; the develop CI run after the merge is green with it"
    requirement: "GATE-07"
    verification:
      - kind: integration
        ref: "gh run watch (develop, post-merge run 36577346257) — check job green, lists 'Run MACOS_APPS_READ_ONLY=1 uv run pytest'"
        status: pass
    human_judgment: false

duration: 15min
completed: 2026-09-29
status: complete
---

# Phase 2 Plan 01: Read-Only Suite Green (GATE-07) Summary

GATE-07 green: read-only suite passes, CI runs it — PR #227.

## Performance

- **Duration:** ~15 min
- **Started:** 2026-09-29T13:41:00Z
- **Completed:** 2026-09-29T13:46:01Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- The 4 read-only fact tests (`test_mail_duplicates_is_registered_read_only`,
  `test_every_write_tool_is_audit_classified`,
  `test_server_snapshot_sources_are_derived_and_satisfy_the_protocol`,
  `test_run_shortcut_carries_open_world_hint`) now read `registry.TOOLS` directly (every
  record, registered or not) instead of the registration-filtered
  `write_tools()`/`snapshot_sources()`/live-tool-list views, so they pass unskipped in every
  mode.
- `send_mail`/`reply_all`/`forward_mail` are `envelope_only` unconditionally in
  `test_every_write_tool_is_audit_classified` (matching `registry.TOOLS`'s always-present
  records); the now-unused `tiers.allow_send("mail")` branch and its local import were
  removed.
- One named skip marker `_write_gate_on_only` (same shape as the existing `_gate_off_only`)
  decorates exactly the 8 named `tests/test_server.py` call tests that require a
  `_guard`-wrapped write tool to raise `ToolError`; no test re-implements `_guard`.
- `.github/workflows/ci.yml` runs `MACOS_APPS_READ_ONLY=1 uv run pytest` as a second step
  directly after the default `uv run pytest` step, in the same job.
- PR #227 rebase-merged to `develop`; the develop CI run after the merge (run 36577346257)
  is green and lists the new read-only step.

## Task Commits

Each task was committed atomically in the lane `.worktrees/gate-07-read-only`
(branch `test/gate-07-read-only`, cut from `origin/develop`):

1. **Task 1: Fact tests read registry.TOOLS; call tests skip read-only by one marker**
   - `4cf628b` (test)
2. **Task 2: CI runs the suite read-only as a second step; land the PR on develop**
   - `e8f8fdd` (ci)

**PR:** #227, rebase-merged to `develop`. **Merge commit:** `7e8a079892b2cdcb97bdac78136f453cf022ba19`.

*Note: SUMMARY.md itself is not committed by this executor — the orchestrator commits it
with the wave tracking.*

## Files Created/Modified

- `tests/test_tool_annotations.py` — `test_run_shortcut_carries_open_world_hint` and
  `test_every_write_tool_is_audit_classified` read `registry.TOOLS` unfiltered
- `tests/test_audit_middleware.py` —
  `test_server_snapshot_sources_are_derived_and_satisfy_the_protocol` reads `registry.TOOLS`
  unfiltered
- `tests/test_mail_cleanup.py` — `test_mail_duplicates_is_registered_read_only` reads
  `registry.TOOLS` unfiltered
- `tests/test_server.py` — new `_write_gate_on_only` marker; decorates the 8 named call
  tests
- `.github/workflows/ci.yml` — new `- run: MACOS_APPS_READ_ONLY=1 uv run pytest` step +
  header comment sentence

## Baseline and Post-Fix Verification Output

**Baseline (before the fix), re-confirmed live in the lane:**
```
$ MACOS_APPS_READ_ONLY=1 uv run pytest -q
12 failed, 1458 passed, 1 skipped, 80 deselected in 16.43s
```
The 12 failing test names matched 02-RESEARCH.md's `GATE-07 Evidence` list exactly.

**Post-fix, all four modes:**
```
$ uv run pytest -q --no-header
Pytest: 1471 passed

$ MACOS_APPS_READ_ONLY=1 uv run pytest -q --no-header
Pytest: 1462 passed, 0 failed, 9 skipped

$ MACOS_APPS_ALLOW_SEND=mail uv run pytest -q --no-header
Pytest: 1467 passed, 0 failed, 4 skipped

$ MACOS_APPS_READ_ONLY=1 MACOS_APPS_ALLOW_SEND=mail uv run pytest -q --no-header
Pytest: 1462 passed, 0 failed, 9 skipped
```
1458 base passes + 4 fixed fact tests = 1462; the 8 call tests skip only under
`MACOS_APPS_READ_ONLY=1` (9 = 8 + the 1 pre-existing skip). `ruff check .` and
`ruff format --check .` both clean.

**Fact-tests-run-not-skip check:**
```
$ MACOS_APPS_READ_ONLY=1 uv run pytest tests/test_tool_annotations.py tests/test_audit_middleware.py tests/test_mail_cleanup.py -q
Pytest: 52 passed
```
No skips among these 3 files — the 4 fact tests run in every mode, per D-01.

## Decisions Made

None beyond the plan's own locked D-01/D-02 — followed as specified.

## Deviations from Plan

None - plan executed exactly as written.

## Code Review Pass

No sub-agent dispatch tool was available in this executor's environment, so the
`code-review` skill's two-axis process (Standards / Spec) was run directly against
`origin/develop...HEAD` instead of via parallel sub-agents. No open issues on either
axis:

- **Standards:** ruff clean (0 violations); no test re-implements `_guard`; no fact test
  filters `registry.TOOLS` by `registered`; `_write_gate_on_only`'s shape matches
  `_gate_off_only`; `macos_apps_mcp/server.py` and `macos_apps_mcp/registry.py` are
  untouched (confirmed via `git diff origin/develop...HEAD -- macos_apps_mcp/` — empty).
- **Spec:** exactly the 4 fact tests + 8 named call tests were touched per D-01; the CI
  step is placed directly after the existing `uv run pytest` step per D-02; no
  architectural or scope changes.

Minor non-blocking observation: the unfiltered `{n for n, r in registry.TOOLS.items() if
r.is_write}` idiom is now written out inline in 3 different test files rather than as a
shared `registry.py` helper (mirroring `removes_content_tools()`). This matches the
pattern the plan and research explicitly prescribed (Pattern 1: registry-record-first),
so it is not a deviation — flagged only as a possible future consolidation if a 5th test
needs the same read.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

GATE-07 holds on `develop` and CI enforces it on every PR and push. Ready for the
remaining phase 2 plans (GATE-11 unit fix, GATE-12 device sweep, release cut).
No blockers.

---
*Phase: 02-gate-close-fail-closed-suite-and-device-sweep*
*Completed: 2026-09-29*
