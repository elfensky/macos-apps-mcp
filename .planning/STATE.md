---
gsd_state_version: "1.0"
milestone: v0.11.0
current_phase: 01
current_phase_name: Gate — Land the Spiked Architecture Cuts
status: executing
stopped_at: "Wave 10 complete; 01-14 owner go answered swap-and-clean (2026-09-26) — dispatch 01-14 from a NEW chat (this one is Toyota-locked)"
last_updated: "2026-09-25T23:48:15.000Z"
last_activity: 2026-09-25
last_activity_desc: Phase 01 execution started
state_head: aa412da1317e06e9fb2317f363c54f1a164a09de
progress:
  total_phases: 7
  completed_phases: 0
  total_plans: 14
  completed_plans: 14
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-08-28)

**Core value:** Safe writes — every write gated by tier, addressed by id, dry-runnable, audited and recoverable; the model can never lose, destroy or send something by accident.
**Current focus:** Phase 01 — Gate — Land the Spiked Architecture Cuts

## Current Position

Phase: 01 (Gate — Land the Spiked Architecture Cuts) — EXECUTING
Plan: 14 of 14
Status: Plans complete — phase gates next (code review, verifier, update_roadmap)
Last activity: 2026-09-26 — 01-14 done: dev build 8885ad0 installed and probed; 11 spike branches + 9 worktrees deleted; GATE-13 ticked

Progress: [░░░░░░░░░░] 0%

## Performance Metrics

**Velocity:**

- Total plans completed: 0
- Average duration: —
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| - | - | - | - |

**Recent Trend:**

- Last 5 plans: —
- Trend: —

*Updated after each plan completion*
**Per-Plan Metrics:**

| Plan | Duration | Tasks | Files |
|------|----------|-------|-------|
| Phase 01 P01 | 11min | 3 tasks | 0 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Gate first: land the 2026-08-28 spiked review before any adapter work — cards 1/7/5 reshape `server.py`/`runtime.py`/`doctor.py`, the files every adapter PR touches.
- Gate build order is load-bearing: 1 → 7 → 5 → 2 sequentially, Mail-scoped 3/4/9 in parallel; after cards 5 and 2 rebuild the daemon and prove `doctor().version`.
- Spike branches (`spike/arch-review-*`) are primary sources, never landing branches — each cut re-lands by rebasing onto the previous PR.
- `dry_run=True` on every destructive tool, enforced from the registration record (today `delete_event`/`delete_draft` default False, `delete_note` has none).
- Contacts and Messages depth are v2, not v1 (owner, 2026-08-28 roadmap review) — the requirements stay tracked under `## v2 Requirements`, out of this milestone's phases.
- Email work comes before any new or additional feature (owner, 2026-09-24). Mail fixes are Phase 02.1, right after the gate; the gate stays first because card 4 rewrites `recoverable()`, the function #206 fixes.
- #205 (Intel build) is DIST-06 in Phase 6 but depends on nothing before it — it may land early as a `/gsd-quick` task.
- The Sequoia plane (#199/#201) landed outside the phases as bug-driven work; it is recorded as Validated in PROJECT.md, not back-filled as a phase.
- A probe that overturns an issue's premise is a valid deliverable — ten consecutive 0.9.x cuts were revised on device before code was written.
- [Phase 01]: Release cut: PR develop→main merged with --merge (never rebase, never --delete-branch since head=develop); tag the merge commit; build only in a detached tag worktree; re-zip after stapling.
- [Phase 01]: One-off daemon proofs live at .worktrees/.daemon_probe.py (git-ignored), reused across plans 01-10 and 01-14 instead of rewritten per plan.

### Pending Todos

- The installed daemon bundle's code seal breaks after first launch: the daemon's Python writes `__pycache__/*.pyc` into the signed `Contents/lib`. Nothing fails today (launch and TCC use the main executable's signature). Fix in `scripts/build_app.sh`: precompile `.pyc` before signing, or run the interpreter with `-B`. Found in plan 01-10.
- `adapters/messages.py` `_apple_date_to_dt` docstring still names `runtime.from_nsdate`, which card 7 moved to `eventkit.py`. Left out of PR #216 because the file was outside plan 01-06's scope; fix in a later card or a `/gsd-quick` task.

### Blockers/Concerns

- Spike-first items must open their phase, not follow it: REM-04 (Reminders tags — public write route may not exist), PHO-01 (`uv add osxphotos` resolution — pyproject conflict note likely stale), NOTE-01 (semantic search decision before any indexing code).
- Phase 1 rebase risk: all `spike/arch-review-*` branches are 16 commits behind `develop`, and each one overlaps files the Sequoia plane changed (`doctor.py`, `server.py`, `runtime.py`, `contracts.py`, `mail.py`, `mail_index.py`, `tests/conftest.py`). Expect conflicts. Card 3's shared fixture must absorb `sequoiaify_envelope` and the sidecar.
- `develop` carries unreleased work since v0.10.1 (#199/#201/#204). The installed daemon does not have it until a release build is installed; release timing stays the operator's call.
- The repo is not the daemon: merging changes nothing about what a Claude Code session sees until the `.app` is rebuilt and reinstalled.
- Every Mail write is verified by running it on device with the watchdog running — a green suite has passed a broken forward before.

### Roadmap Evolution

- Phase 1 edited: edited fields: success_criteria (5: fixture carries Sequoia shape, byte-identity baseline is pre-cut develop; 6: rebase onto current develop, 16 commits past the spike base)
- Phase 6 edited: edited fields: requirements (+DIST-06), success_criteria (+6: Intel build, #205)
- Phase 02.1 inserted after Phase 2: Mail fixes (#206 move/trash timeout + receipt, #208 create_draft from_address) — email before any feature phase (owner, 2026-09-24) (URGENT)
- Phase 3 edited: edited fields: depends_on (Phase 02.1), requirements (+CAL-04, +REM-06), success_criteria (+6: container id in Pointer.folder, #207)

## Deferred Items

Items acknowledged and deferred at milestone close, most recent first:

| Category | Item | Status | Deferred At | Milestone |
|----------|------|--------|-------------|-----------|
| *(none)* | | | | |

## Session Continuity

Last session: 2026-09-25T11:41:17.935Z
Stopped at: Wave 10 done (13/14). 01-14 Task 1 answered swap-and-clean. Next: dispatch 01-14 from a NEW chat, then the phase gates
Resume file: None
