---
gsd_state_version: "1.0"
milestone: v0.11.0
current_phase: 04
current_phase_name: Notes & Photos — Settle the Mechanism, Then Ship the Read Plane
status: planning
stopped_at: Phase 03 complete, ready to plan Phase 04
last_updated: "2026-10-11T01:23:05.573Z"
last_activity: 2026-10-11
last_activity_desc: Phase 03 complete, transitioned to Phase 04
state_head: 4b404ebdd179e48eb7d28a6be33ef452d695f391
progress:
  total_phases: 7
  completed_phases: 4
  total_plans: 38
  completed_plans: 38
  percent: 57
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-10-05)

**Core value:** Safe writes — every write gated by tier, addressed by id, dry-runnable, audited and recoverable; the model can never lose, destroy or send something by accident.
**Current focus:** Phase 03 — EventKit Depth — Calendar Alarms & Recurrence, Reminders CRUD & Subtasks

## Current Position

Phase: 04 — Notes & Photos — Settle the Mechanism, Then Ship the Read Plane
Plan: Not started
Status: Ready to plan
Last activity: 2026-10-11 — Phase 03 complete, transitioned to Phase 04

Progress: [██████░░░░] 57%

## Performance Metrics

**Velocity:**

- Total plans completed: 38
- Average duration: —
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01 | 14 | - | - |
| 02 | 6 | - | - |
| 02.1 | 8 | - | - |
| 03 | 10 | - | - |

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
| Phase 03 P08 | 8min | 2 tasks | 11 files |
| Phase 03 P09 | 15min | 3 tasks | 0 files |
| Phase 03 P10 | 25min | 2 tasks | 0 files |

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

- Phase 3 security advisory A1: the spike 008 alarm harness (`.claude/skills/spike-findings-macos-apps-mcp/sources/008-eventkit-alarms/probe_alarms.py`) takes the first (source, title) match; add a several-match stop before it is reused (03-SECURITY.md).
- Phase 3 security advisory A2: the `google_calendar` device fixture checks only that `MACOS_APPS_IT_GOOGLE_CALENDAR_ID` exists and is writable; assert its source is "Google" (03-SECURITY.md).
- `adapters/messages.py` `_apple_date_to_dt` docstring still names `runtime.from_nsdate`, which card 7 moved to `eventkit.py`. Left out of PR #216 because the file was outside plan 01-06's scope; fix in a later card or a `/gsd-quick` task.

### Blockers/Concerns

- Spike-first items must open their phase, not follow it: REM-04 (Reminders tags — public write route may not exist), PHO-01 (`uv add osxphotos` resolution — pyproject conflict note likely stale), NOTE-01 (semantic search decision before any indexing code).
- [Phase 1] Code review WR-01 is open: `update_note(dry_run=True)` reports `body_chars: 0` when the current body fails to hydrate (`adapters/notes.py` `_update_preview`). IN-01 (the `delete` audit-verb prefix is looser than the GATE-05 `delete_` class) cannot fire today. See `01-REVIEW.md`.
- The installed daemon is release v0.14.2 (universal2, build `aa27d32`, notarized, installed with `ditto`; `doctor()` proven over the socket 2026-10-08: version 0.14.2, libs mcp 1.29.0 / fastmcp 3.4.7; code seal intact after the first run; TestPyPI only so far — the PyPI dispatch for 0.14.1/0.14.2 is the operator's). It adds #304 (#296), #305 (#299) and #308 (#205: universal2, macOS 15 floor, no cryptography, Intel-only allow-unsigned-executable-memory) to v0.14.1. Install with `ditto`, not `cp -R` (#297).
- [Phase 02.1] #229 (`rollback()` cannot verify a windowless delete) and #230 (reply quote content read exceeds 30 s on some messages, intermittent) were settled in 0.13.1, ahead of Phase 3 (MAIL-05/06 complete): #230 by a 120 s cap on every script that acts on the original (5 of 5 device runs, xfail removed); #229 by deciding that the loud leftover warning is the caller contract (xfail stays as the detector). The skip `test_mail_reads_return_id_triple_real_inbox` names a data property of this Mac (large inbox) rather than absent data — flagged in 02-VERIFICATION.md, unchanged.
- [Phase 2] Release install step: read the daemon probe's exit directly (`$?`), never `${PIPESTATUS[0]}` — under zsh it is empty and the 0.12.0 install was rolled back once by mistake before being redone.
- [Phase 02.1] Fixed in 0.13.1 (#261): macOS 27 has no per-user TCC.db; `doctor()`'s FDA probe now falls back to the system db, and an absent user db is not a partial grant read.
- The repo is not the daemon: merging changes nothing about what a Claude Code session sees until the `.app` is rebuilt and reinstalled.
- Every Mail write is verified by running it on device with the watchdog running — a green suite has passed a broken forward before.

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 261006-uff | Harden PR #251 (Gmail label membership): locate backs up the target account's copy, deterministic label citation, UNION ALL, docs + device-verified facts | 2026-10-06 | 9de12e5 | [261006-uff-harden-pr-251-gmail-label-membership-bef](./quick/261006-uff-harden-pr-251-gmail-label-membership-bef/) |
| 261006-vu3 | Build the daemon bundle from uv.lock; cap mcp<2/fastmcp<4; smoke a streamed call in the build (#286, PR #288) | 2026-10-06 | 328ccec | [261006-vu3-build-the-daemon-bundle-from-uv-lock-and](./quick/261006-vu3-build-the-daemon-bundle-from-uv-lock-and/) |
| 261006-wa0 | Gmail follow-ups: refuse label-folder write sources; labels in thread, sent triage, stats; parity guard (#287, PR #289) | 2026-10-06 | 328ccec | [261006-wa0-gmail-follow-ups-to-251-label-source-gua](./quick/261006-wa0-gmail-follow-ups-to-251-label-source-gua/) |
| 4 | Precompile the daemon bundle's bytecode before signing so its code seal survives first launch | 2026-10-07 | 26baa9a | — |
| 261007-11j | Release bump 0.14.0 (EventKit depth): changelog corrections, version sites, Phase 3 device re-run record | 2026-10-07 | e672a4b | [261007-11j-release-bump-0-14-0-with-changelog-corre](./quick/261007-11j-release-bump-0-14-0-with-changelog-corre/) |
| 6 | Record v0.14.0 as the installed daemon (build a5766c9, ditto install, probe-proven 2026-10-07) | 2026-10-07 | 01972d9 | — |
| 7 | Release bump 0.14.1 — Gmail label fixes (#291, #285) | 2026-10-07 | c6ef3fa | — |
| 261007-1bq | Gmail write gaps: canonical source refused, label match in any spelling, label destination refused after a device run, undo explains, new labels without source detected (#291, PR #295); doctor reports bundled mcp/fastmcp (#285) | 2026-10-07 | f7967f4 | [261007-1bq-gmail-write-gaps-291-and-doctor-mcp-vers](./quick/261007-1bq-gmail-write-gaps-291-and-doctor-mcp-vers/) |
| 261007-o5a | Reads count a Gmail label without mailboxes.source: bare_label arm by the write guard's rule; deleted rows ignored; ~+20 ms per id lookup (#299, PR #305) | 2026-10-07 | b252353 | [261007-o5a-reads-count-a-gmail-label-without-mailbo](./quick/261007-o5a-reads-count-a-gmail-label-without-mailbo/) |
| 261007-o5d | save_mail_attachment names an id-only save after the attachment; stale-folder error; 120 s listing cap (#296, PR #304) | 2026-10-07 | b252353 | [261007-o5d-save-mail-attachment-names-an-id-only-sa](./quick/261007-o5d-save-mail-attachment-names-an-id-only-sa/) |
| 261007-tu3 | Universal2 .app (Apple silicon + Intel), macOS 15 floor, no cryptography; Intel-only allow-unsigned-executable-memory, notarization Accepted (#205, PR #308) | 2026-10-08 | e0a2264 | [261007-tu3-universal2-app-build-intel-apple-silicon](./quick/261007-tu3-universal2-app-build-intel-apple-silicon/) |
| 261009-l1b | pyproject [project.urls] (Homepage, Repository, Issues, Changelog) so the PyPI page links back from the next upload (#111, PR #314) | 2026-10-09 | cf23238 | [261009-l1b-111-add-project-urls-to-pyproject-toml-s](./quick/261009-l1b-111-add-project-urls-to-pyproject-toml-s/) |
| 261009-l1d | README recommends uvx macos-apps-mcp; from source becomes the development path; dated DESIGN.md amendment (#113, PR #315) | 2026-10-09 | 0203e2e | [261009-l1d-113-readme-recommends-uvx-macos-apps-mcp](./quick/261009-l1d-113-readme-recommends-uvx-macos-apps-mcp/) |
| 261009-l2j | Hash-based .pyc (checked-hash, +7% import) plus conversion of import-hook opt-* caches: a cp -R install keeps the code seal, proven on device; DAEMON.md installs with ditto (#297, PR #316) | 2026-10-09 | 1feab0c | [261009-l2j-297-keep-the-app-code-seal-after-a-cp-r-](./quick/261009-l2j-297-keep-the-app-code-seal-after-a-cp-r-/) |
| 261009-t11 | UDS clients drop anyio's cancelled-wait InvalidStateError (root cause in anyio's selector callback); the stream smoke fails on any other loop exception (#302, PR #319) | 2026-10-09 | c2d66e6 | [261009-t11-302-drop-anyio-s-cancelled-wait-invalids](./quick/261009-t11-302-drop-anyio-s-cancelled-wait-invalids/) |
| 261009-tqc | facts 5f: the Gmail-label undo on a healthy Mail still returns the copy; reply, reply_all and forward verified from a label (#291, PR #320) | 2026-10-09 | 5a456f1 | [261009-tqc-291-facts-5f-label-undo-on-a-healthy-mai](./quick/261009-tqc-291-facts-5f-label-undo-on-a-healthy-mai/) |
| 261009-ha3 | Local-list reminders are found: the Reminders store is keyed on ZDACALENDARITEMUNIQUEIDENTIFIER and every per-account store file is read; device-verified on iCloud and on a Local account (Intel iMac) (#307, PR #313) | 2026-10-11 | 39e2a33 | [261009-ha3-fix-307-key-reminders-store-reads-on-zda](./quick/261009-ha3-fix-307-key-reminders-store-reads-on-zda/) |
| 261011-4iv | The 0.14.2 universal .app verified on an Intel CPU (iMac, macOS 15): daemon, doctor, reads, seal; found #317, #318, #322 (#205, PR #323) | 2026-10-11 | 4b404eb | [261011-4iv-205-item-3-the-0-14-2-universal-app-veri](./quick/261011-4iv-205-item-3-the-0-14-2-universal-app-veri/) |
| 12 | Release bump 0.14.2 — Universal app (#205, #296, #299) | 2026-10-08 | 36827fe | — |

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

Last session: 2026-10-09T17:56:33.702Z
Stopped at: Phase 03 complete, ready to plan Phase 04
Resume file: .planning/phases/04-notes-photos-settle-the-mechanism-then-ship-the-read-plane/04-CONTEXT.md
