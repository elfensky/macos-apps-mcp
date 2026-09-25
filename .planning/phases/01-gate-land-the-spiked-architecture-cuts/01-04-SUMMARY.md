---
phase: 01-gate-land-the-spiked-architecture-cuts
plan: 04
subsystem: testing
tags: [pytest, monkeypatch, native-seam, gate-01, gate-13, doctor, adapters, code-review, landing]

# Dependency graph
requires:
  - phase: 01-02
    provides: the runtime lock (conftest refuses run_osascript/body_file/tracked_run unfaked) and the shared lane branch this plan continues on
provides:
  - Every adapter under macos_apps_mcp/adapters/ plus doctor.py reaches the native seam qualified (from .. import runtime, then runtime.<seam>(...))
  - tests/test_native_seam.py's static tripwire widened from adapters/mail*.py to every adapters/*.py + doctor.py, with tracked_run in the seam set
  - Card 1 (parts A + B) merged to origin/develop as one PR (#214, rebase-merge, merge commit 7a3194b)
affects: [Phase 1 wave 4+ (card 7/3/4/9 all branch from a develop that now carries card 1), Phase 2 GATE-11 (doctor tests off live pgrep, already landed as a 01-02 side effect)]

# Actuals (#2632)
actuals:
  tokens: 9354
  tasks: 3
  commits: 3
  plan_head_before: 767e344  # 01-02's last lane commit (pre-01-04); replayed as bfbb0ec on origin/develop by PR #214's rebase-merge
confidence_note: "estimate was 90000 tokens (low confidence); actual realized diff for this plan's own 3 commits was ~9354 (chars/4) — the estimate did not anticipate how mechanical the remaining 6 adapters would be once notes.py set the pattern in Task 1"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Qualified native seam import generalized project-wide: from .. import runtime,
      then runtime.<seam>(...) — previously a Mail-only convention (#176), now every
      adapter (contacts, messages, music, notes, photos, safari, shortcuts) and
      doctor.py follow it, closing every by-name copy the conftest lock couldn't see"
    - "Static tripwire covers the whole native plane by construction: _NATIVE_MODULES
      globs adapters/*.py (minus __init__.py) plus doctor.py, sorted, with a sanity
      assertion (>=10 modules, doctor.py and shortcuts.py present) so a NEW adapter
      module is checked without anyone remembering to add it"

key-files:
  created: []
  modified:
    - macos_apps_mcp/adapters/notes.py
    - macos_apps_mcp/adapters/contacts.py
    - macos_apps_mcp/adapters/photos.py
    - macos_apps_mcp/adapters/messages.py
    - macos_apps_mcp/adapters/music.py
    - macos_apps_mcp/adapters/safari.py
    - macos_apps_mcp/doctor.py
    - tests/test_notes.py
    - tests/test_contacts.py
    - tests/test_music.py
    - tests/test_safari.py
    - tests/test_doctor.py
    - tests/test_native_seam.py

key-decisions:
  - "Verify triple (uv run pytest, uv run ruff check ., uv run ruff format --check .) re-run clean in the lane before landing: 1403 passed, 0 lint findings, 134 files already formatted."
  - "Scratch tripwire probe (macos_apps_mcp/adapters/zz_probe.py with a bare `from ..runtime import tracked_run`) confirmed the widened static check fails closed on a brand-new unlocked module — 1 failed, 26 passed, exact AssertionError naming zz_probe.py:1 and tracked_run. Probe deleted immediately after; git status confirmed clean."
  - "Code-review pass (Standards + Spec, run sequentially myself — no sub-agent tool available) over origin/develop...HEAD found zero findings on both axes. No fix commits were needed."
  - "Lane was already rebased on origin/develop (merge-base == origin/develop tip, 36624be) — no rebase/force-push/CI-rewatch cycle was needed before merge."
  - "PR #214 merged via `gh pr merge 214 --rebase --delete-branch` — merge commit 7a3194b on origin/develop. Verify command 2 (grep tracked_run count in origin/develop's test_native_seam.py) returned 4, confirming card 1 is live on develop."
  - "Lane cleanup ran from the main checkout only: worktree unlock/remove, local branch delete, fetch --prune. No pull/commit/stash/reset/checkout touched the main checkout's own git state."

requirements-completed: [GATE-01, GATE-13]

coverage:
  - id: D1
    description: "Every adapters/*.py module plus doctor.py reaches the native seam (run_osascript/body_file/tracked_run) qualified via runtime.<seam>(...), never by-name"
    requirement: "GATE-01"
    verification:
      - kind: unit
        ref: "tests/test_native_seam.py#test_native_module_does_not_import_the_seam_by_name (parametrized, 21 module cases, all pass)"
        status: pass
    human_judgment: false
  - id: D2
    description: "The static tripwire covers the whole native plane by construction (glob + doctor.py, sanity-asserted >=10 modules including doctor.py and shortcuts.py) — a new adapter module is checked automatically"
    requirement: "GATE-01"
    verification:
      - kind: unit
        ref: "tests/test_native_seam.py#test_the_tripwire_sees_the_native_modules"
        status: pass
      - kind: manual_procedural
        ref: "scratch macos_apps_mcp/adapters/zz_probe.py tripwire probe: created with an unqualified `from ..runtime import tracked_run`, confirmed `uv run pytest tests/test_native_seam.py -q` failed (1 failed, 26 passed) naming zz_probe.py:1 and tracked_run, then deleted; git status confirmed clean afterward"
        status: pass
    human_judgment: false
  - id: D3
    description: "notes' write path is proven end-to-end to hit the runtime lock (create() with no fakes raises, naming body_file or run_osascript)"
    requirement: "GATE-01"
    verification:
      - kind: unit
        ref: "tests/test_notes.py#test_create_without_fakes_is_refused"
        status: pass
    human_judgment: false
  - id: D4
    description: "Card 1 (plan 01-02's runtime lock + this plan's static widening) is on origin/develop by one rebase-merged PR whose CI, local verify triple, and code-review pass were all clean"
    requirement: "GATE-13"
    verification:
      - kind: other
        ref: "gh pr view 214 --json state,mergeCommit,mergedAt -> state=MERGED, mergeCommit=7a3194bdfcea578f7bb9b54b00aa8b6e9c66536f; git show origin/develop:tests/test_native_seam.py | grep -c tracked_run -> 4"
        status: pass
    human_judgment: false

duration: ~20min (resumed landing flow only — Tasks 1-3 code was committed in a prior session before a computer restart interrupted the plan)
completed: 2026-09-25
status: complete
---

# Phase 01 Plan 04: Card 1 part B — every adapter + doctor reach the native seam qualified; card 1 merged to develop (GATE-01, GATE-13) Summary

**Verify triple green (1403 passed, 0 lint, formatted), tripwire probe confirmed fail-closed on a new unlocked module, code review clean on both axes, PR #214 merged via rebase (7a3194b) — GATE-01's static half lands, closing out card 1 alongside plan 01-02's runtime half.**

## Performance

- **Duration:** ~20 min (this resumed session only — the verify/review/merge/cleanup landing flow)
- **Tasks:** 3 completed (across this session and the prior one that was interrupted by a computer restart)
- **Files modified:** 13 (this plan's own commits) + 20 total in the card-1 PR (combined with plan 01-02)

## Accomplishments

- `notes.py`, `contacts.py`, `photos.py`, `messages.py`, `music.py`, `safari.py` and `doctor.py` all reach the native seam qualified (`from .. import runtime`, then `runtime.run_osascript(...)` / `runtime.body_file(...)`), closing every by-name copy that plan 01-02's runtime lock couldn't see statically.
- `tests/test_native_seam.py`'s static tripwire widened from `adapters/mail*.py` (>=3 modules) to every `adapters/*.py` (minus `__init__.py`) plus `doctor.py` (>=10 modules, `doctor.py` and `shortcuts.py` asserted present) — the parametrized test renamed to `test_native_module_does_not_import_the_seam_by_name`, now covering 21 module cases.
- **Verify triple re-confirmed green in the lane before landing:** `uv run pytest` — 1403 passed; `uv run ruff check .` — `[]` (no findings); `uv run ruff format --check .` — 134 files already formatted.
- **Tripwire probe (acceptance criterion):** created a scratch `macos_apps_mcp/adapters/zz_probe.py` containing a bare `from ..runtime import tracked_run`. `uv run pytest tests/test_native_seam.py -q` failed as required (1 failed, 26 passed), the AssertionError naming `zz_probe.py:1` and `tracked_run`. Probe deleted immediately after; `git status --short` confirmed clean.
- **Code-review pass** (Standards + Spec, run myself sequentially since sub-agents aren't available to this executor) over `origin/develop...HEAD` (6 commits, 20 files, +262/-131): **zero findings on both axes.** No fix commits were needed.
  - Standards: import qualification matches the established #176 Mail convention, now generalized project-wide; ruff (E/F/I/UP/B/SIM, line-length 88) already enforces import ordering and unused-import removal, both clean. One judgement-call smell considered — the identical `_no_live_process_probe` autouse fixture duplicated across `test_doctor.py` and `test_doctor_deploy.py` — but this is the explicit, documented 01-02 pattern ("a test module that needs a whole-file safe fake adds its own autouse fixture"), so the repo-override rule suppresses it; not a finding.
  - Spec: every Task 1–3 action item and acceptance criterion in `01-04-PLAN.md` is satisfied by the diff (qualified imports per adapter, test patch-target migrations, doctor's import/call changes, the widened `_SEAM`/`_NATIVE_MODULES`/renamed test/sanity assertion); no scope creep found; no requirement gaps found.
- The lane was already rebased on `origin/develop` (merge-base equalled `origin/develop`'s tip, `36624be`) — no rebase, force-push, or CI re-watch cycle was needed.
- `gh pr merge 214 --rebase --delete-branch` succeeded — merge commit `7a3194bdfcea578f7bb9b54b00aa8b6e9c66536f` on `origin/develop`; `gh pr view 214` confirms `state: MERGED`.
- Task 3's second `<verify>` command confirmed card 1 live on `develop`: `git show origin/develop:tests/test_native_seam.py | grep -c tracked_run` → `4`.
- Lane cleanup from the main checkout: `git worktree unlock` + `git worktree remove .worktrees/gate-card-1-native-seam` + `git branch -D refactor/gate-card-1-native-seam` + `git fetch -q --prune origin` — all succeeded; `git worktree list` confirms the lane is gone.
- Vault journal bullet landed: `elfensky/obsidian` MR 799, merged — one line noting card 1's landing (PR #214, merge commit 7a3194b, GATE-01).

## Task Commits

This plan's own 3 task commits, authored in the shared card-1 lane as `e783cbf`, `d65befa`,
`26b13ed`. GitHub's rebase-merge for PR #214 replayed every commit onto `origin/develop` with new
SHAs (rebase-merge always does this) — the hashes below are the ones that actually exist on
`origin/develop` today; the lane-local hashes no longer resolve anywhere once the branch was
deleted post-merge:

1. **Task 1: notes, contacts and photos reach the seam qualified (tracer)** — `b5d8ece` on `origin/develop` (lane-local: `e783cbf`) (feat)
2. **Task 2: messages, music and safari reach the seam qualified** — `d6dd31d` on `origin/develop` (lane-local: `d65befa`) (feat)
3. **Task 3: doctor qualified, tripwire widened to every adapter + doctor** — `7a3194b` on `origin/develop` (lane-local: `26b13ed`) (feat)

Preceding commits from plan 01-02 (same lane, same PR, already summarized in `01-02-SUMMARY.md`),
likewise replayed: `dbcb326` (was `fcde18b`), `1266f33` (was `6c902a4`), `bfbb0ec` (was `767e344`).

**Merge / PR tip commit:** `7a3194bdfcea578f7bb9b54b00aa8b6e9c66536f` on `origin/develop` (PR #214's
final replayed commit — `gh pr view 214` reports this as `mergeCommit`).

No code-review fix commits were needed — the review pass found zero findings on both axes.

## Files Created/Modified

- `macos_apps_mcp/adapters/notes.py` — qualified `runtime.run_osascript` / `runtime.body_file` at every call site (list/search/read/delete/create/update paths, including the `fallback=lambda: …` branch)
- `macos_apps_mcp/adapters/contacts.py` — qualified `runtime.run_osascript` in `get_pointers`, `create_contact`, and the re-read verification
- `macos_apps_mcp/adapters/photos.py` — qualified `runtime.run_osascript` in `get_pointers`
- `macos_apps_mcp/adapters/messages.py` — qualified `runtime.run_osascript` in `get_chats`; `mac_region`/`read_via_sqlite` stay by-name (not seam names)
- `macos_apps_mcp/adapters/music.py` — qualified `runtime.run_osascript` at all six call sites (search, now_playing, control, play_playlist, set_volume, set_mode)
- `macos_apps_mcp/adapters/safari.py` — qualified `runtime.run_osascript` in `get_tabs` and `open_url`
- `macos_apps_mcp/doctor.py` — `from . import deploy, runtime`; `run_osascript` dropped from the by-name `.runtime` import; `_automation_surfaces` calls `runtime.run_osascript(...)`
- `tests/test_notes.py` — every seam patch target moved to `runtime`; new `test_create_without_fakes_is_refused` (end-to-end lock proof)
- `tests/test_contacts.py`, `tests/test_music.py`, `tests/test_safari.py` — seam patch targets moved to `runtime`
- `tests/test_doctor.py` — every `monkeypatch.setattr(doc, "run_osascript", …)` moved to `monkeypatch.setattr(runtime, "run_osascript", …)`
- `tests/test_native_seam.py` — `_SEAM` gains `tracked_run`; `_NATIVE_MODULES` replaces `_MAIL_MODULES` (every `adapters/*.py` + `doctor.py`, sorted); parametrized test renamed; sanity test widened (`>=10`, `doctor.py`/`shortcuts.py` present); module docstring updated

## Decisions Made

- No rebase was needed before merging — the lane's merge-base with `origin/develop` already equalled `origin/develop`'s tip, so PR #214 merged cleanly on the first attempt.
- The code-review pass ran as two sequential self-directed passes (Standards, then Spec) instead of parallel sub-agents, since this executor cannot spawn sub-agents — matching the phase-level decision recorded in `.continue-here.md` ("Executors cannot start sub-agents, so they run the code-review skill's Standards and Spec axes themselves, one after the other").
- The duplicated `_no_live_process_probe` autouse fixture across `test_doctor.py`/`test_doctor_deploy.py` was evaluated as a possible DRY smell but not flagged as a finding — it matches the explicit, already-documented 01-02 pattern of a per-module autouse override, which the repo's own established convention overrides the generic baseline heuristic.

## Deviations from Plan

None — plan executed exactly as written, including the tripwire probe/delete/git-status-clean check and the full landing flow (verify triple, code review, merge, lane cleanup, journal).

## Issues Encountered

None. The plan resumed cleanly from a prior session's interruption (computer restart) — Tasks 1–2 and all of Task 3's code were already committed and verified consistent (`git log`, `git status --short`, PR state) before continuing at the landing-flow step.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- GATE-01 and GATE-13 are both fully satisfied by card 1's merge — this was GATE-01's last plan (per the shared-ID gate in `.continue-here.md`), so the orchestrator should tick GATE-01 complete now that this SUMMARY exists. GATE-13 stays open until later cards in this phase also land (this plan only closes card 1's contribution to it).
- `origin/develop` now carries card 1 (native seam fails closed for every adapter, doctor, and shortcuts). Wave 4 plans (01-06 card 7, 01-07 card 3) branch from this `develop` state.
- The lane `.worktrees/gate-card-1-native-seam` and branch `refactor/gate-card-1-native-seam` are both gone (locally and on the remote). No stale worktree or branch remains for card 1.
- Parallel lane `.worktrees/gate-card-4-recoverable-preflight` (plan 01-05, card 4) was left untouched throughout — no shared files, no interference.

## Self-Check: PASSED

- SUMMARY.md exists on disk: FOUND.
- Task commits: `e783cbf`/`d65befa`/`26b13ed` (this plan's lane-local hashes) no longer resolve
  after the lane branch was deleted post-merge — expected, since GitHub's rebase-merge for PR
  #214 replayed every commit onto `origin/develop` with new SHAs. The replayed hashes all verify:
  `b5d8ece`, `d6dd31d`, `7a3194b` (this plan) and `bfbb0ec`, `1266f33`, `dbcb326` (01-02,
  carried in the same PR) — all FOUND in `origin/develop`'s log.
- Task 3's `<verify>` command 2 re-confirmed: `git show origin/develop:tests/test_native_seam.py
  | grep -c tracked_run` → `4`.
- All Task 1–3 acceptance criteria re-verified passing (see Accomplishments above).

---
*Phase: 01-gate-land-the-spiked-architecture-cuts*
*Completed: 2026-09-25*
