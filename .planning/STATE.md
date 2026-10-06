---
gsd_state_version: "1.0"
milestone: v0.11.0
current_phase: 03
current_phase_name: EventKit Depth — Calendar Alarms & Recurrence, Reminders CRUD & Subtasks
status: executing
stopped_at: Completed 03-07-PLAN.md
last_updated: "2026-10-06T09:06:03.553Z"
last_activity: 2026-10-05
last_activity_desc: Phase 03 execution started
state_head: db2905bb3ef585248782f5ea3e5c8e85fdaae184
progress:
  total_phases: 7
  completed_phases: 3
  total_plans: 38
  completed_plans: 35
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-10-05)

**Core value:** Safe writes — every write gated by tier, addressed by id, dry-runnable, audited and recoverable; the model can never lose, destroy or send something by accident.
**Current focus:** Phase 03 — EventKit Depth — Calendar Alarms & Recurrence, Reminders CRUD & Subtasks

## Current Position

Phase: 03 (EventKit Depth — Calendar Alarms & Recurrence, Reminders CRUD & Subtasks) — EXECUTING
Plan: 8 of 10
Status: Ready to execute
Last activity: 2026-10-05 — Phase 03 execution started

Progress: [████░░░░░░] 43%

## Performance Metrics

**Velocity:**

- Total plans completed: 28
- Average duration: —
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01 | 14 | - | - |
| 02 | 6 | - | - |
| 02.1 | 8 | - | - |

**Recent Trend:**

- Last 5 plans: —
- Trend: —

*Updated after each plan completion*
**Per-Plan Metrics:**

| Plan | Duration | Tasks | Files |
|------|----------|-------|-------|
| Phase 01 P01 | 11min | 3 tasks | 0 files |
| Phase 03 P01 | 20min | 3 tasks | 0 files |
| Phase 03 P02 | 9min | 3 tasks | 11 files |
| Phase 03 P03 | 14min | 3 tasks | 13 files |
| Phase 03 P04 | 11min | 3 tasks | 10 files |
| Phase 03 P05 | 9min | 3 tasks | 9 files |
| Phase 03 P06 | 11min | 3 tasks | 11 files |
| Phase 03 P07 | 23min | 3 tasks | 13 files |

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
- [Phase 02.1]: Mail does not reject an unowned `from_address` — it sends from the default account. `send_mail`/`create_draft` refuse it before any native write; `owned_addresses()` fails closed (the opposite of `account_map()`'s fail-open label lookup).
- [Phase 02.1]: Batch moves and trashes act by internal id from one bulk read (`«class mssg» id n of src`), behind a per-copy `considering case` identity guard; `ok` needs the source reference dead (-1728) plus a destination count rise.
- [Phase 02.1]: A timeout receipt marks its targets `unknown`, and `undo_plan` replays `unknown` as well as `ok`.
- [Phase 02.1]: No device probe targets a family account (Personal, Grandma, Mama) — this rule skipped the five #230 runs; both #229 and #230 stay open behind non-strict xfails with device evidence.
- [Phase 02.1]: Phase close runs validate-phase and secure-phase from the verify:post hooks; their files land in the same records PR as the UAT.
- [Phase 03]: Pre-code probes (03-01) overturned no premise: reminder lists save on the default source; Google refuses a list save with EKErrorDomain 24; reminder BY* parts and UNTIL (day granularity) round-trip; Google alarms unchanged from spike 008. — Measured on device 2026-10-06 before any Phase 3 code (D-23).
- [Phase 03]: Owner rulings after the 03-01 probes: A3 and A4 confirmed (alarms refuse a negative value on a timed event and a duplicate offset); A5 changed — reminders compare UNTIL at day granularity too (03-03); A9 changed — complete_reminder refuses with WriteRefused, no save, when the Reminders store cannot be read (03-08). — Probe 2 showed reminders keep UNTIL exactly; the owner prefers a refusal to a blind completion of a possible parent.

### Pending Todos

- The installed daemon bundle's code seal breaks after first launch: the daemon's Python writes `__pycache__/*.pyc` into the signed `Contents/lib`. Nothing fails today (launch and TCC use the main executable's signature). Fix in `scripts/build_app.sh`: precompile `.pyc` before signing, or run the interpreter with `-B`. Found in plan 01-10.
- `adapters/messages.py` `_apple_date_to_dt` docstring still names `runtime.from_nsdate`, which card 7 moved to `eventkit.py`. Left out of PR #216 because the file was outside plan 01-06's scope; fix in a later card or a `/gsd-quick` task.

### Blockers/Concerns

- Spike-first items must open their phase, not follow it: REM-04 (Reminders tags — public write route may not exist), PHO-01 (`uv add osxphotos` resolution — pyproject conflict note likely stale), NOTE-01 (semantic search decision before any indexing code).
- [Phase 1] Code review WR-01 is open: `update_note(dry_run=True)` reports `body_chars: 0` when the current body fails to hydrate (`adapters/notes.py` `_update_preview`). IN-01 (the `delete` audit-verb prefix is looser than the GATE-05 `delete_` class) cannot fire today. See `01-REVIEW.md`.
- The installed daemon is release v0.13.1 (build `4b13dba`, installed and probe-proven 2026-10-05; on PyPI too). It carries #229, #230 and #261.
- [Phase 02.1] #229 (`rollback()` cannot verify a windowless delete) and #230 (reply quote content read exceeds 30 s on some messages, intermittent) were settled in 0.13.1, ahead of Phase 3 (MAIL-05/06 complete): #230 by a 120 s cap on every script that acts on the original (5 of 5 device runs, xfail removed); #229 by deciding that the loud leftover warning is the caller contract (xfail stays as the detector). The skip `test_mail_reads_return_id_triple_real_inbox` names a data property of this Mac (large inbox) rather than absent data — flagged in 02-VERIFICATION.md, unchanged.
- [Phase 2] Release install step: read the daemon probe's exit directly (`$?`), never `${PIPESTATUS[0]}` — under zsh it is empty and the 0.12.0 install was rolled back once by mistake before being redone.
- [Phase 02.1] Fixed in 0.13.1 (#261): macOS 27 has no per-user TCC.db; `doctor()`'s FDA probe now falls back to the system db, and an absent user db is not a partial grant read.
- The repo is not the daemon: merging changes nothing about what a Claude Code session sees until the `.app` is rebuilt and reinstalled.
- Every Mail write is verified by running it on device with the watchdog running — a green suite has passed a broken forward before.

### Roadmap Evolution

- Phase 1 edited: edited fields: success_criteria (5: fixture carries Sequoia shape, byte-identity baseline is pre-cut develop; 6: rebase onto current develop, 16 commits past the spike base)
- Phase 6 edited: edited fields: requirements (+DIST-06), success_criteria (+6: Intel build, #205)
- Phase 02.1 inserted after Phase 2: Mail fixes (#206 move/trash timeout + receipt, #208 create_draft from_address) — email before any feature phase (owner, 2026-09-24) (URGENT)
- Phase 3 edited: edited fields: depends_on (Phase 02.1), requirements (+CAL-04, +REM-06), success_criteria (+6: container id in Pointer.folder, #207)
- Phase 3 edited: edited fields: goal, requirements (+MAIL-05, +MAIL-06), success_criteria (+7: #229 rollback decision, +8: #230 five device runs) — carried over from Phase 02.1
- Phase 3 edited: edited fields: success_criteria (5: subtasks and tags read-only from the Reminders store — spike 002 found no public `parentReminder`); REM-03 and PROJECT.md reworded to match (2026-10-05, discuss-phase)

## Deferred Items

Items acknowledged and deferred at milestone close, most recent first:

| Category | Item | Status | Deferred At | Milestone |
|----------|------|--------|-------------|-----------|
| *(none)* | | | | |

## Session Continuity

Last session: 2026-10-06T09:06:03.504Z
Stopped at: Completed 03-07-PLAN.md
Resume file: None
