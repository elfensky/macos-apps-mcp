---
phase: 01-gate-land-the-spiked-architecture-cuts
plan: 02
subsystem: testing
tags: [pytest, monkeypatch, native-seam, gate-01, shortcuts, doctor, mail]

# Dependency graph
requires:
  - phase: 01-01
    provides: v0.11.0 cut on develop (the base this lane branched from)
provides:
  - conftest.py's autouse lock refuses runtime.run_osascript, runtime.body_file AND
    runtime.tracked_run at runtime, not just statically
  - shortcuts.py reaches tracked_run qualified (runtime.tracked_run)
  - doctor's unit tests never run a live pgrep/ps
  - runtime-lock self-tests in tests/test_native_seam.py proving all three refusals
    and the fake-overrides-the-lock behavior
affects: [01-04 (finishes card 1 on this same branch — static _SEAM/glob widening to
  every adapters/*.py + doctor.py), Phase 2 GATE-11 (doctor tests off live pgrep,
  landed early here as a side effect)]

# Actuals (#2632)
actuals:
  tokens: 6106
  tasks: 2
  commits: 3

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Runtime seam lock: conftest's autouse fixture refuses a named seam by
      monkeypatching runtime.<seam> to a raiser; a test's own
      monkeypatch.setattr(runtime, <seam>, ...) overrides it (last write wins);
      a seam's own self-tests bind the real function at module-import time instead"
    - "Module-level autouse override: a test module that needs a whole-file safe
      fake (test_doctor.py, test_doctor_deploy.py) adds its OWN autouse fixture
      that runs after conftest's and overrides the refusal with a deterministic
      fake — never a bypass of the lock, a per-module substitute for it"

key-files:
  created: []
  modified:
    - tests/conftest.py
    - macos_apps_mcp/adapters/shortcuts.py
    - tests/test_shortcuts.py
    - tests/test_doctor.py
    - tests/test_doctor_deploy.py
    - tests/test_runtime.py
    - tests/test_mail.py
    - tests/test_mail_drafts.py
    - tests/test_native_seam.py

key-decisions:
  - "Split conftest.py's seam-lock extension across the two tasks: Task 1 added only
    tracked_run to the refused set (needed for shortcuts.py + doctor); Task 2 added
    body_file, TDD-style, so the new parametrized test genuinely went RED (the
    body_file case failing) before the conftest edit made it GREEN."
  - "The three send() tests in test_mail.py that reach body_file but don't assert
    tempfile content/cleanup were faked with the existing nullcontext pattern
    instead of restoring the real function — simpler and matches the plan's (b)
    branch; the ten tests that DO assert tempfile semantics restore the real
    function via a module-level _real_body_file bind (the (a) branch)."
  - "doctor.py's tests get a fake tracked_run (pgrep-found-nothing), not a
    refusal-bypass: diagnose()'s automation surfaces read every app's process
    line via app_process_info even at request=False (#183), so a bare refusal
    would break every test that doesn't explicitly patch doc.app_process_info."

requirements-completed: [GATE-01]  # runtime half only — the static widening
  # (_SEAM frozenset, adapters/*.py + doctor.py glob) is plan 01-04's job; GATE-01
  # is not marked complete project-wide until that plan lands on this same branch.

coverage:
  - id: D1
    description: "runtime.tracked_run fails closed at runtime for any unfaked unit test"
    requirement: "GATE-01"
    verification:
      - kind: unit
        ref: "tests/test_native_seam.py#test_unit_tests_cannot_reach_a_seam_unfaked[tracked_run]"
        status: pass
    human_judgment: false
  - id: D2
    description: "runtime.body_file fails closed at runtime for any unfaked unit test"
    requirement: "GATE-01"
    verification:
      - kind: unit
        ref: "tests/test_native_seam.py#test_unit_tests_cannot_reach_a_seam_unfaked[body_file]"
        status: pass
    human_judgment: false
  - id: D3
    description: "ShortcutsAdapter reaches tracked_run qualified; an unfaked call is refused end-to-end"
    requirement: "GATE-01"
    verification:
      - kind: unit
        ref: "tests/test_shortcuts.py#test_unfaked_tracked_run_is_refused"
        status: pass
    human_judgment: false
  - id: D4
    description: "doctor's unit tests never invoke a live pgrep/ps"
    requirement: "GATE-01"
    verification:
      - kind: unit
        ref: "tests/test_doctor.py, tests/test_doctor_deploy.py (full files, module-level _no_live_process_probe autouse fixture)"
        status: pass
    human_judgment: false
  - id: D5
    description: "A test's own seam fake overrides the autouse lock"
    requirement: "GATE-01"
    verification:
      - kind: unit
        ref: "tests/test_native_seam.py#test_a_test_fake_overrides_the_lock"
        status: pass
    human_judgment: false

duration: 35min
completed: 2026-09-25
status: complete
---

# Phase 01 Plan 02: Lock the native seam (run_osascript, body_file, tracked_run) at runtime Summary

**All three native-seam names — `run_osascript`, `body_file`, `tracked_run` — now fail closed at runtime in `tests/conftest.py`, closing the gap the 2026-08-28 spike left (its diff touched only a docstring).**

## Performance

- **Duration:** ~35 min
- **Tasks:** 2 completed
- **Files modified:** 9
- **Commits:** 3 (feat, test/RED, feat/GREEN)

## Accomplishments

- `tests/conftest.py`'s autouse `_no_real_osascript` fixture refuses `runtime.tracked_run` (Task 1) and `runtime.body_file` (Task 2), in addition to the pre-existing `run_osascript` refusal — a unit test that forgets to fake any of the three now raises `AssertionError` naming the seam, instead of spawning a real process or writing a real tempfile.
- `macos_apps_mcp/adapters/shortcuts.py` reaches `tracked_run` qualified (`runtime.tracked_run(...)`, per #176) instead of importing it by name — its two call sites (`_list_entries`, `run_shortcut`) now share the one patch point every other seam-qualified module uses.
- `tests/test_doctor.py` and `tests/test_doctor_deploy.py` each got a module-level autouse `_no_live_process_probe` fixture that fakes `runtime.tracked_run` to a "pgrep found nothing" result, so `doctor`'s automation surfaces (which read `app_process_info` even at `request=False`, #183) never run a live `pgrep`/`ps` during `uv run pytest`. This lands the test-side half of Phase 2's GATE-11 early, as the objective anticipated.
- `tests/test_native_seam.py` gained the runtime-lock self-tests: a parametrized `test_unit_tests_cannot_reach_a_seam_unfaked` (all three names) and `test_a_test_fake_overrides_the_lock` — the proof that the lock fires, and that a test's own fake still wins over it.
- The 13 Mail tests measured failing under the three-name lock (9 in `test_mail.py`, 4 in `test_mail_drafts.py`) and the 2 `body_file` self-tests in `test_runtime.py` all pass again: 10 restore the real `body_file` explicitly (asserting tempfile content/cleanup), 3 fake it (asserting only the send/reply outcome), and the 2 self-tests bind the real function at module-import time, matching the existing `run_osascript` convention.

## Task Commits

Each task was committed atomically (Task 2 as a TDD RED/GREEN pair per its `tdd="true"` frontmatter):

1. **Task 1: tracked_run locked end-to-end through the shortcuts adapter (tracer)** — `58e1e9d` (feat)
2. **Task 2, RED: failing test for the body_file lock** — `bf10ca6` (test)
3. **Task 2, GREEN: body_file locked; dependent tempfile tests made explicit** — `45a6fc3` (feat)

No REFACTOR commit — the GREEN implementation needed no cleanup.

**Lane branch:** `refactor/gate-card-1-native-seam` (`.worktrees/gate-card-1-native-seam`), tip `45a6fc30246c9b800cd0f232009a17728660f00c`, pushed to `origin/refactor/gate-card-1-native-seam`. No PR opened — plan 01-04 continues on this same branch and opens the one card-1 PR (D-07).

## Files Created/Modified

- `tests/conftest.py` — `_no_real_osascript` extended to refuse all three seam names
- `macos_apps_mcp/adapters/shortcuts.py` — qualified `runtime.tracked_run(...)` at both call sites
- `tests/test_shortcuts.py` — setattr targets moved to `macos_apps_mcp.runtime.tracked_run`; identity test now asserts `shortcuts.runtime is runtime` / no module-global `tracked_run`; new `test_unfaked_tracked_run_is_refused`; the two `tracked_run` self-tests call `_real_tracked_run` bound at module import
- `tests/test_doctor.py`, `tests/test_doctor_deploy.py` — module-level autouse `_no_live_process_probe`
- `tests/test_runtime.py` — the two `body_file` self-tests bind the real function at module-import time
- `tests/test_mail.py`, `tests/test_mail_drafts.py` — the 13 tests reaching `body_file` now fake or restore it explicitly, per test
- `tests/test_native_seam.py` — `test_unit_tests_cannot_reach_a_seam_unfaked` (parametrized ×3), `test_a_test_fake_overrides_the_lock`

## Decisions Made

- Split the conftest seam-lock extension across the two tasks (`tracked_run` in Task 1, `body_file` in Task 2) so Task 2's TDD cycle produced a genuine RED against the target test before the fix.
- The three `send()` tests that don't assert tempfile content were faked with the existing `nullcontext` pattern rather than restoring the real `body_file` — simpler, and matches the plan's "(b) otherwise fake it" branch.
- `doctor`'s unit tests get a deterministic fake for `tracked_run`, not a bare refusal-bypass — `diagnose()` always computes the process line for every automation surface, so a plain refusal would have broken every test that doesn't already patch `doc.app_process_info` directly.

## Deviations from Plan

None — plan executed exactly as written, including the TDD RED/GREEN split for Task 2's `body_file` lock.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Plan 01-04 continues card 1 on `refactor/gate-card-1-native-seam`: widens `test_native_seam.py`'s static `_SEAM`/`_MAIL_MODULES` glob to every `adapters/*.py` plus `doctor.py`, and qualifies the remaining by-name seam imports (`doctor.py:31` among them).
- GATE-01 is not yet complete project-wide — this plan lands its runtime half only; the static-check widening is plan 01-04's job, and the requirement stays open in `.planning/REQUIREMENTS.md` until that plan's SUMMARY exists (shared-ID gate, #2388).
- `uv run pytest`, `uv run ruff check .` and `uv run ruff format --check .` all pass on the lane (1339 tests, up from the 1335 baseline — 4 new runtime-lock self-tests, net of the pre-existing `test_shortcuts_spawns_through_runtime_seam` replaced by two: the identity assertion and `test_unfaked_tracked_run_is_refused`).

---
*Phase: 01-gate-land-the-spiked-architecture-cuts*
*Completed: 2026-09-25*
