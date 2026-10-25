---
gsd_state_version: "1.0"
milestone: v0.11.0
current_phase: "05.2"
current_phase_name: "Bug fixes — every open bug before Phase 6 (#455, #399, #348)"
status: executing
stopped_at: Phase 05.2 planned (7 plans, 4 waves); ready to execute wave 1 (05.2-01, FIX-17)
last_updated: "2026-10-25T19:51:18.070Z"
last_activity: 2026-10-25
last_activity_desc: "Phase 05.2 planned: 7 plans in 4 waves (FIX-14..17: #455, #399, #348, #464); researcher defaults O1-O14 adopted, owner vetoes at verify-work"
state_head: 9c5d4a65f61e8d69d90eb8f2eccbed3f150552c7
progress:
  total_phases: 13
  completed_phases: 9
  total_plans: 79
  completed_plans: 72
  percent: 90
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-10-25)

**Core value:** Safe writes — every write gated by tier, addressed by id, dry-runnable, audited and recoverable; the model can never lose, destroy or send something by accident.
**Current focus:** Phase 05.2 — Bug fixes — every open bug before Phase 6 (#455, #399, #348)

## Current Position

Phase: 05.2 (Bug fixes — every open bug before Phase 6 (#455, #399, #348)) — READY TO EXECUTE
Plan: Not started
Status: Ready to execute
Last activity: 2026-10-25 - Phase 05.2 planned: 7 plans in 4 waves (FIX-14..17: #455, #399, #348, #464); records PR docs/phase-05.2-records

Progress: [█████████░] 90%

## Performance Metrics

**Velocity:**

- Total plans completed: 72
- Average duration: —
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01 | 14 | - | - |
| 02 | 6 | - | - |
| 02.1 | 8 | - | - |
| 03 | 10 | - | - |
| 03.1 | 7 | - | - |
| 04 | 6 | - | - |
| 04.1 | 5 | - | - |
| 05 | 9 | - | - |
| 05.1 | 7 | - | - |

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

- [Phase 03.1]: #335 premise overturned on the iMac (2026-10-13): the SQLite plane, Notes.app and `notes_all` all count 1 live note; the 2 titled rows of the device report sit in Recently Deleted. No filter change; #335 closed with the record.
- [Phase 03.1]: Contacts route a (PR #355): on the Intel iMac every `whose` reference re-runs the scan, so each property is read with one Apple event over the whole match list (5 scans, 9 s measured) instead of one per person; a length mismatch across the five lists raises instead of mixing two people's fields. No host cap (route b) yet — 03.1-07 proves it through the daemon.
- [Phase 03.1]: `mail_overview` labels an id absent from a NON-empty account map `(account not in Mail)` (PR #356; cause: a removed account whose rows stay in the Envelope Index). An empty map keeps the uuid, so a cold cache never makes every account look removed.
- [Phase 04.1]: Bugs before any feature: #373 (hash-locked `build` group, the bundled wheel installed `--no-deps`), #383 (an existing target and a failed `mkdir` raise `WriteRefused`; `_guard` untouched), #384 (ruff on py312 with a drift-guard test), #387 (pid-tagged staging, a dead-pid sweep with five guards, a cleanup error never replaces a written result) — PRs #390/#392/#394/#396, close PR #398.
- [Phase 05.1]: Owner decisions 2026-10-24: O3/O4/O5 confirmed, O1 overturned → #450 (file-backed account-name cache; a Mail call at daemon start would launch Mail, so refresh only when Mail already runs). PM-04/PM-16 fixed by #451 on the owner's word.
- [Phase 05.1]: A wave that changes UI files needs a `<phase>-UI-SPEC.md`; the pointer form (sketches + plan truths) satisfies `ui.safety-gate`.
- [Phase 05.1]: Device UAT delegated to the session: sign-only same-Mac build, `ditto` over the moved-aside bundle, kickstart, `doctor().build` proof; a retrying port holder for the "port held" check; the page key never enters a transcript (Chrome gets the link through osascript on stdin).
- [Phase 04.1]: The Photos device fixture builds its `POSIX file` list outside the Photos tell: inside it Photos gets an object specifier and fails -1728. FIX-08 proven on device on the import path; the one test photo removed by the owner by hand (D-15), album by script, probe `([], [], [])` — PR #402.

### Pending Todos

- Phase 3 security advisory A1: the spike 008 alarm harness (`.claude/skills/spike-findings-macos-apps-mcp/sources/008-eventkit-alarms/probe_alarms.py`) takes the first (source, title) match; add a several-match stop before it is reused (03-SECURITY.md).
- Phase 3 security advisory A2: the `google_calendar` device fixture checks only that `MACOS_APPS_IT_GOOGLE_CALENDAR_ID` exists and is writable; assert its source is "Google" (03-SECURITY.md).
- `adapters/messages.py` `_apple_date_to_dt` docstring still names `runtime.from_nsdate`, which card 7 moved to `eventkit.py`. Left out of PR #216 because the file was outside plan 01-06's scope; fix in a later card or a `/gsd-quick` task.

### Blockers/Concerns

- [Phase 04.1] Deferred: `export_mail` refuses mid-batch after earlier files were written, and the typed refusal hides that (review WR-02, tracked in #399).

- Spike-first items must open their phase, not follow it: REM-04 (Reminders tags — public write route may not exist), PHO-01 (`uv add osxphotos` resolution — pyproject conflict note likely stale), NOTE-01 (semantic search decision before any indexing code).
- [Phase 1] Code review WR-01 is open: `update_note(dry_run=True)` reports `body_chars: 0` when the current body fails to hydrate (`adapters/notes.py` `_update_preview`). IN-01 (the `delete` audit-verb prefix is looser than the GATE-05 `delete_` class) cannot fire today. See `01-REVIEW.md`.
- The installed daemon is a develop build: 0.15.0 at 6e4aee5 (2026-10-24, signed, not notarized), installed with `ditto` after moving the 0.15.0 release bundle (7b26e22) to `~/Library/Caches/macos-apps-mcp-build/previous-0.15.0-7b26e22/`; `doctor().build` proves it. A release cut (version bump, notarization, PyPI) has not been made for the 05.1 work.
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
| 20 | Release bump 0.14.3 — Local reminders: pyproject, Info.plist, uv.lock root line, CHANGELOG header (PR #325; release PR #326, tag v0.14.3) | 2026-10-11 | c38a32b | — |
| 261011-imn | doctor counts an answered -1728 probe as ok (#317); grant map names the TCC denial reason, prompt-timeout reset command and AppleEvents target (#318); PR #328. Also: PyPI 0.14.3 published, Gmail test label removed | 2026-10-11 | ff345a5 | [261011-imn-317-318-doctor-counts-an-answered-1728-p](./quick/261011-imn-317-318-doctor-counts-an-answered-1728-p/) |
| 261011-p90 | uvx on an Intel Mac installs without Rust: cryptography<49 on darwin x86_64 only (48.0.1 is the last Intel wheel); PR #330, closes #322 | 2026-10-11 | 2fa3524 | [261011-p90-322-uvx-on-an-intel-mac-installs-without](./quick/261011-p90-322-uvx-on-an-intel-mac-installs-without/) |
| 261012-utn | Ship the macOS app icon: packaging/AppIcon.icon (Icon Composer), actool compile step in build_app.sh, Info.plist icon keys, packaging test, DAEMON.md note | 2026-10-12 | 22870dc | [261012-utn-ship-the-macos-app-icon-packaging-appico](./quick/261012-utn-ship-the-macos-app-icon-packaging-appico/) |
| 261018-1sb | mail_overview re-reads the account map once (per minute) before labelling an unknown id; a failed re-read keeps the known names (#359) | 2026-10-18 | 3fbc3d0 | [261018-1sb-fix-359-one-map-re-read-before-the-label](./quick/261018-1sb-fix-359-one-map-re-read-before-the-label/) |
| 261025-2fq | Dependabot on the uv ecosystem: lockfile-only, 7-day cooldown, one group per ecosystem incl. security (CI/security plan item 2) | 2026-10-25 | b4ced7e | [261025-2fq-move-dependabot-from-pip-to-uv-and-group](./quick/261025-2fq-move-dependabot-from-pip-to-uv-and-group/) |
| 261025-2s7 | Version gate runs only on release PRs (no paths filter) with root permissions contents: read for CodeQL alert #1 (CI/security plan item 4) | 2026-10-25 | 8c15cd2 | [261025-2s7-version-gate-runs-only-on-release-prs-wi](./quick/261025-2s7-version-gate-runs-only-on-release-prs-wi/) |
| 261025-3kk | Fix Dependabot alerts #21-#23 (fastmcp 3.4.11, opentelemetry-api 1.45.1), 29 other lock updates inside the limits with a 7-day cooldown, setup-uv v10.3.2 | 2026-10-25 | 000308f | [261025-3kk-fix-dependabot-alerts-21-23-and-refresh-](./quick/261025-3kk-fix-dependabot-alerts-21-23-and-refresh-/) |
| 261025-4qn | Dependabot uv cooldown 7 -> 3 days; uv.lock refreshed with a 3-day cutoff (12 updates inside the limits, python-dateutil 3.0.0 and starlette 1.9.0 among them) | 2026-10-25 | a038683 | [261025-4qn-set-the-dependabot-cooldown-to-3-days-an](./quick/261025-4qn-set-the-dependabot-cooldown-to-3-days-an/) |
| 261025-64s | ruff 0.16.10 -> 0.17.1 (cap <0.18); docs/DAEMON.md records why cryptography stays at 48.0.1 (nothing imports it; Intel stays supported; arm64-only revisit 2028) | 2026-10-25 | 60885e2 | [261025-64s-upgrade-ruff-to-0-17-and-document-why-cr](./quick/261025-64s-upgrade-ruff-to-0-17-and-document-why-cr/) |
| 261025-5sy | README first screen for new visitors (pitch, safety and privacy, first 5 minutes, why not apple-mcp) and CREDITS provenance fix; multi-AI review after each step; #471 filed | 2026-10-25 | 21434d3 | [261025-5sy-launch-readiness-readme-first-screen-and](./quick/261025-5sy-launch-readiness-readme-first-screen-and/) |
| 261025-h09 | server.json + glama.json + README mcp-name marker; CI publishes to the MCP Registry after PyPI (mcp-publisher v1.8.1 pinned, sha256-checked) behind a release-tag guard; in-repo Claude Code plugin marketplace (macos-apps + dry-run skill); multi-AI review after each step | 2026-10-25 | 6495e9a | [261025-h09-official-mcp-registry-metadata-and-an-in](./quick/261025-h09-official-mcp-registry-metadata-and-an-in/) |
| 32 | README pitch: 'destructive ones preview first' overclaimed (update_event/update_reminder/update_mail_status act when called) — now 'deletes, moves and sends preview first' (found by the multi-AI review of the awesome-mcp-servers entry) | 2026-10-25 | de5f293 | — |
| 33 | AGENTS.md rule: clean a lane only after gh pr view <n> says MERGED (a cleanup after a failed merge deleted #474's branch and closed the PR, 2026-10-25) | 2026-10-25 | 4b1c9f3 | — |
| 34 | README dashboard screenshots (invented data, served from a scratch state dir): batch detail (light/dark) in the first screen, word diff and adapter switches in the Dashboard section | 2026-10-25 | a8249a1 | — |
| 35 | README: Claude Desktop needs the full uvx path (it does not read the shell PATH) — found while writing the tester brief | 2026-10-25 | 9c5d4a6 | — |

### Roadmap Evolution

- Phase 1 edited: edited fields: success_criteria (5: fixture carries Sequoia shape, byte-identity baseline is pre-cut develop; 6: rebase onto current develop, 16 commits past the spike base)
- Phase 6 edited: edited fields: requirements (+DIST-06), success_criteria (+6: Intel build, #205)
- Phase 02.1 inserted after Phase 2: Mail fixes (#206 move/trash timeout + receipt, #208 create_draft from_address) — email before any feature phase (owner, 2026-09-24) (URGENT)
- Phase 3 edited: edited fields: depends_on (Phase 02.1), requirements (+CAL-04, +REM-06), success_criteria (+6: container id in Pointer.folder, #207)
- Phase 3 edited: edited fields: goal, requirements (+MAIL-05, +MAIL-06), success_criteria (+7: #229 rollback decision, +8: #230 five device runs) — carried over from Phase 02.1
- Phase 3 edited: edited fields: success_criteria (5: subtasks and tags read-only from the Reminders store — spike 002 found no public `parentReminder`); REM-03 and PROJECT.md reworded to match (2026-10-05, discuss-phase)
- Phase 03.1 inserted after Phase 3: Bug Fixes — Device-Report Findings Before Any Feature: #333-#337 from the Intel iMac report (PR #332) and #222; bugs and errors come before any feature (owner, 2026-10-11) (URGENT)
- Phase 04.1 inserted after Phase 4: Bug Fixes — Phase 4 Follow-ups Before Any Feature (#373, #383, #384, #387) (URGENT)
- Phase 05.1 inserted after Phase 5: Bug fixes — dashboard follow-ups (#427, #428, #430) (URGENT)
- Phase 05.2 inserted after Phase 5: Bug fixes — Automation grants unreadable on macOS 27 (#455) (URGENT)
- Phase 05.2 edited: edited fields: title, goal, requirements — #399 and #348 added beside #455, so every open bug is fixed before Phase 6 (owner, 2026-10-25)
- Phase 05.3 inserted after Phase 05.2: Feedback — problem reports and improvement suggestions (#465); before Phase 6 so the first outside users can report (owner, 2026-10-25)
- Phase 05.4 inserted after Phase 05.3: Migration — mcp 2 and fastmcp 4 (#470); after Phase 05.3 and before Phase 6 (owner, 2026-10-25)

## Deferred Items

Items acknowledged and deferred at milestone close, most recent first:

| Category | Item | Status | Deferred At | Milestone |
|----------|------|--------|-------------|-----------|
| *(none)* | | | | |

## Session Continuity

Last session: 2026-10-24T23:03:30Z
Stopped at: Phase 05.2 planned (7 plans, 4 waves); ready to execute wave 1 (05.2-01, FIX-17)
Resume file: None
