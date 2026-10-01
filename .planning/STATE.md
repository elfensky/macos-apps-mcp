---
gsd_state_version: "1.0"
milestone: v0.11.0
current_phase: "02.1"
current_phase_name: mail-fixes-batch-moves-fit-their-timeout-drafts-pick-their-a
status: executing
stopped_at: Phase 02.1 context gathered (assumptions mode)
last_updated: "2026-10-01T20:27:51.308Z"
last_activity: 2026-10-01
last_activity_desc: Phase 02 complete, transitioned to Phase 02.1
state_head: 452e1681c38473e64304d872a99c59454615860b
progress:
  total_phases: 7
  completed_phases: 2
  total_plans: 28
  completed_plans: 20
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-10-01)

**Core value:** Safe writes — every write gated by tier, addressed by id, dry-runnable, audited and recoverable; the model can never lose, destroy or send something by accident.
**Current focus:** Phase 02.1 — Mail Fixes — Batch Moves Fit Their Timeout, Drafts Pick Their Account

## Current Position

Phase: 02.1 (mail-fixes-batch-moves-fit-their-timeout-drafts-pick-their-a) — READY TO EXECUTE
Plan: Not started
Status: Ready to execute
Last activity: 2026-10-01 — Phase 02 complete, transitioned to Phase 02.1

Progress: [███░░░░░░░] 29%

## Performance Metrics

**Velocity:**

- Total plans completed: 20
- Average duration: —
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01 | 14 | - | - |
| 02 | 6 | - | - |

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
- `dry_run=True` on every destructive tool, enforced from the registration record — done in Phase 1 (GATE-05), live-verified 2026-09-26.
- Contacts and Messages depth are v2, not v1 (owner, 2026-08-28 roadmap review) — the requirements stay tracked under `## v2 Requirements`, out of this milestone's phases.
- Email work comes before any new or additional feature (owner, 2026-09-24). Mail fixes are Phase 02.1, right after the gate; the gate stays first because card 4 rewrites `recoverable()`, the function #206 fixes.
- #205 (Intel build) is DIST-06 in Phase 6 but depends on nothing before it — it may land early as a `/gsd-quick` task.
- The Sequoia plane (#199/#201) landed outside the phases as bug-driven work; it is recorded as Validated in PROJECT.md, not back-filled as a phase.
- A probe that overturns an issue's premise is a valid deliverable — ten consecutive 0.9.x cuts were revised on device before code was written.
- [Phase 01]: Release cut: PR develop→main merged with --merge (never rebase, never --delete-branch since head=develop); tag the merge commit; build only in a detached tag worktree; re-zip after stapling.
- [Phase 01]: One-off daemon proofs live at .worktrees/.daemon_probe.py (git-ignored), reused across plans 01-10 and 01-14 instead of rewritten per plan.
- [Phase 02]: An intermittent device test is held by a non-strict xfail with evidence (#230): a strict mark flips the sweep gate on a pass; the mechanism question (content read of an undownloaded body) goes to 02.1.
- [Phase 02]: A new session re-asks the owner before any device run; one diagnostic re-run per failed nodeid; the watchdog precondition before every Mail run; Mail is never force-quit on a timeout hint alone — a bare Apple Event decides whether it is wedged.
- [Phase 02]: Planning records land by PR from a locked worktree like code (the main checkout had drifted 11 ahead / 8 behind by direct commits); `.planning/` is excluded from `ruff format` because ruff 0.16 formats Python fences in markdown.

### Pending Todos

- The installed daemon bundle's code seal breaks after first launch: the daemon's Python writes `__pycache__/*.pyc` into the signed `Contents/lib`. Nothing fails today (launch and TCC use the main executable's signature). Fix in `scripts/build_app.sh`: precompile `.pyc` before signing, or run the interpreter with `-B`. Found in plan 01-10.
- `adapters/messages.py` `_apple_date_to_dt` docstring still names `runtime.from_nsdate`, which card 7 moved to `eventkit.py`. Left out of PR #216 because the file was outside plan 01-06's scope; fix in a later card or a `/gsd-quick` task.

### Blockers/Concerns

- Spike-first items must open their phase, not follow it: REM-04 (Reminders tags — public write route may not exist), PHO-01 (`uv add osxphotos` resolution — pyproject conflict note likely stale), NOTE-01 (semantic search decision before any indexing code).
- [Phase 1] Code review WR-01 is open: `update_note(dry_run=True)` reports `body_chars: 0` when the current body fails to hydrate (`adapters/notes.py` `_update_preview`). IN-01 (the `delete` audit-verb prefix is looser than the GATE-05 `delete_` class) cannot fire today. See `01-REVIEW.md`.
- [Phase 2] The installed daemon is release v0.12.0 (build `5ce98ab`, installed 2026-10-01). The next dev build is needed only when 02.1 lands adapter code.
- [Phase 2] #229 (`rollback()` cannot verify a windowless delete) and #230 (reply quote content read exceeds 30 s on some messages, intermittent) are xfailed in the integration suite and owned by 02.1. The skip `test_mail_reads_return_id_triple_real_inbox` names a data property of this Mac (large inbox) rather than absent data — flagged in 02-VERIFICATION.md, unchanged.
- [Phase 2] Release install step: read the daemon probe's exit directly (`$?`), never `${PIPESTATUS[0]}` — under zsh it is empty and the 0.12.0 install was rolled back once by mistake before being redone.
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

Last session: 2026-10-01T12:54:13.197Z
Stopped at: Phase 02.1 context gathered (assumptions mode)
Resume file: .planning/phases/02.1-mail-fixes-batch-moves-fit-their-timeout-drafts-pick-their-a/02.1-CONTEXT.md
