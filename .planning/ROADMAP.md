# Roadmap: macos-apps-mcp

## Overview

The server already ships nine adapters, three capability tiers, a signed daemon and a Mail plane
that is a complete mail-client API. This milestone makes the rest of it match. It opens by landing
the 2026-08-28 spiked architecture review — a fail-closed native seam, settled module boundaries
and one registration record — because those cuts reshape the exact files (`server.py`,
`runtime.py`, `doctor.py`) every later adapter PR touches, and because a suite that can dial a real
app cannot verify anything that follows. With the gate closed and the read-only suite green, Mail
fixes come next (Phase 02.1): on 2026-09-24 the owner put email work ahead of every new or
additional feature. Then the work becomes adapter depth, one native plane at a time: EventKit (Calendar alarms and real
recurrence, Reminders deletion, lists and subtasks), then the two adapters whose mechanism is still
open (Notes semantic search, Photos). Those last two open with a probe, and the probe's answer —
including "the premise was wrong, here is the documented gap" — is the deliverable. Contacts and
Messages depth were moved to v2 at the 2026-08-28 review (owner's call); their requirements stay
tracked in REQUIREMENTS.md but are out of this milestone. The milestone closes by letting other
people run it safely: per-adapter toggles and a loopback dashboard, then distribution via `uvx`,
`.mcpb`, a Homebrew cask and a companion plugin.

Every phase that adds a write carries the same three criteria the core value demands: `dry_run=True`
by default, its own audit verb, and verification by running it on device and inspecting the result.

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Gate — Land the Spiked Architecture Cuts** - Native seam fail-closed, module boundaries settled, one registration record, Mail's fixture and recoverable preflight fixed
- [ ] **Phase 2: Gate Close — Fail-Closed Suite and Device Sweep** - The read-only suite goes green, doctor stops touching the dev machine, the device integration sweep passes
- [ ] **Phase 02.1: Mail Fixes — Batch Moves Fit Their Timeout, Drafts Pick Their Account** (INSERTED) - A full 25-message move or trash finishes and always leaves a receipt; a draft starts from the account the caller names
- [ ] **Phase 3: EventKit Depth — Calendar Alarms & Recurrence, Reminders CRUD & Subtasks** - The shared EventKit plane reaches Mail-level completeness
- [ ] **Phase 4: Notes & Photos — Settle the Mechanism, Then Ship the Read Plane** - Two open mechanisms are probed on device first; what survives ships bounded, what does not ships documented
- [ ] **Phase 5: Operator Control Plane — Adapter Toggles and the Localhost Dashboard** - An operator picks which apps are exposed and can see grants, usage, audit and backups
- [ ] **Phase 6: Distribution — uvx, Bundles, Cask, and the Companion Plugin** - Someone who is not the author can install and use it in one step

## Phase Details

### Phase 1: Gate — Land the Spiked Architecture Cuts

**Goal**: The architecture the rest of the milestone builds on is landed — a native seam that fails closed, module boundaries no adapter PR has to fight, and one registration record that makes tier, audit verb and dry-run default correct by construction.
**Depends on**: Nothing (first phase)
**Requirements**: GATE-01, GATE-02, GATE-03, GATE-04, GATE-05, GATE-06, GATE-08, GATE-09, GATE-10, GATE-13
**Success Criteria** (what must be TRUE):

  1. A unit test that forgets to fake the native seam raises instead of dialing a real app — for every module under `adapters/*.py`, for `doctor.py`, and for `shortcuts`' `tracked_run` (`run_osascript`, `body_file`, `tracked_run` all locked once in conftest); the tripwire fails when a new adapter module is added without a lock.
  2. `runtime` exposes only the native door (~10 public names) with the EventKit cluster — store, NSDate/RRULE coercion, TCC request, `run_native_async` — in its own module that Calendar and Reminders import by one name; `doctor` imports no `server` symbol, tier policy and the untrusted-data notice middleware live in their own modules, the package has no import cycle, bodies are byte-identical, and `-m integration -k "request_access or create_event or create_reminder"` is green on device.
  3. Every tool's tier, adapter, permission, audit verb and notice policy come from one registration record built pre-gate (gated-off tools recorded, never derived from FastMCP `Tool` objects); annotations, gates, guard, snapshot registry, notice exemption and the tests' expectations all read from it; every destructive tool reports `dry_run=True` by default and a registry test fails when a new one omits it.
  4. `audit()` shows `trash_mail`, `move_mail`, `mail_undo`, `export_mail`, `save_mail_attachment`, `music_control`, `play_playlist`, `set_mode`, `set_volume` and `create_contact` under their own verbs — no bare `"write"`, nothing unlogged.
  5. Mail's plane holds under the new seam: `query_*` executors run through the shared `tests/envelope.py` fixture (schema carrying `m.size`, `message_references` and every other column read, `HEADER_FINGERPRINT` covering them; the fixture carries both the native shape and the Sequoia shape — `sequoiaify_envelope` plus the #201 sidecar), `recoverable(...)` runs its own preflight so `dedupe_batch(dry_run=True)` cannot report "planned" for unchecked targets and a dry run without a stated `present` is an error, the script-timeout tripwire passes with `_DEDUPE` fixed — verified on a scratch mailbox with the watchdog running, dry-run envelopes and osascript argv byte-identical to `develop` before the cut (not 0.10.1: #201 changed `mail.py` after the tag).
  6. The cuts land 1 → 7 → 5 → 2 by rebasing each onto the previous PR (Mail-scoped 3/4/9 in parallel); after cards 5 and 2 a rebuilt, restarted daemon answers `doctor().version` with the new version and one outbound dry run still reports gated correctly; `spike/arch-review-*` branches and `.claude/worktrees/` are deleted. The first card rebases onto current `develop`: the spikes are 16 commits behind, and the #199/#201 Sequoia plane changed `doctor.py`, `server.py`, `runtime.py`, `contracts.py`, `mail.py`, `mail_index.py` and `tests/conftest.py` — every card touches at least one of them.

**Plans**: 11/14 plans executed in 11 waves

Plans:
**Wave 1**

- [x] 01-01-PLAN.md — Pre-gate release v0.11.0: bump PR, owner-gated cut + tag, notarized build, daemon install, doctor proof (D-05)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 01-02-PLAN.md — Card 1a: conftest locks run_osascript/body_file/tracked_run at runtime; shortcuts qualified; doctor tests off live pgrep
- [x] 01-03-PLAN.md — Card 9: backstop ≥ host-cap tripwire over every osascript call site; `_DEDUPE` backstop 900 s; landed

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 01-04-PLAN.md — Card 1b: every adapter + doctor reach the seam qualified; tripwire widened to adapters/*.py + doctor.py; card 1 landed
- [x] 01-05-PLAN.md — Card 4: `recoverable()` owns the dry-run read; v0.11.0 byte-identity baseline; check_batch text; PR open

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 01-06-PLAN.md — Card 7: EventKit cluster to `eventkit.py`; runtime = 11-name native door; landed
- [x] 01-07-PLAN.md — Card 3: shared `tests/envelope.py` fixture in both shapes; HEADER_FINGERPRINT coverage test; landed

**Wave 5** *(blocked on Wave 4 completion)*

- [x] 01-08-PLAN.md — Device session: card 7 EventKit proof; card 4 scratch-mailbox verification with the watchdog; card 4 merged

**Wave 6** *(blocked on Wave 5 completion)*

- [x] 01-09-PLAN.md — Card 5: `tiers.py` + `notices.py`; doctor's server reach-in removed; layering test; landed

**Wave 7** *(blocked on Wave 6 completion)*

- [x] 01-10-PLAN.md — Dev-build daemon check after card 5 (D-06)

**Wave 8** *(blocked on Wave 7 completion)*

- [x] 01-11-PLAN.md — Card 2a: one `_tool` registration record; audit verbs from the record; `_audit_op` removed

**Wave 9** *(blocked on Wave 8 completion)*

- [ ] 01-12-PLAN.md — Card 2b: adapter/permission/notice facts on the record; registry becomes the one outbound ledger

**Wave 10** *(blocked on Wave 9 completion)*

- [ ] 01-13-PLAN.md — Card 2c: D-01/D-02 dry-run defaults, D-04 fail-closed registry test, CHANGELOG; card 2 landed

**Wave 11** *(blocked on Wave 10 completion)*

- [ ] 01-14-PLAN.md — Dev-build daemon check after card 2; landing order recorded; spike branches and worktrees deleted (D-09)

### Phase 2: Gate Close — Fail-Closed Suite and Device Sweep

**Goal**: The suite tells the truth in every deployment shape — read-only, unit, and on-device — so the adapter phases can trust it.
**Depends on**: Phase 1
**Requirements**: GATE-07, GATE-11, GATE-12
**Success Criteria** (what must be TRUE):

  1. `MACOS_APPS_READ_ONLY=1 uv run pytest` is green (12 failures on `develop` today) — a read-only deployment's tests prove gated-off tools are absent, not registered-and-erroring.
  2. `uv run pytest` runs no live `pgrep`/`ps` against the dev machine: doctor's 17 process-probe tests go through the locked `tracked_run` seam.
  3. `uv run pytest -m integration` is green on the current macOS against a daemon rebuilt and reinstalled from the gate, and `uv run ruff check .` plus `uv run ruff format --check .` pass.

**Plans**: TBD

### Phase 02.1: Mail Fixes — Batch Moves Fit Their Timeout, Drafts Pick Their Account (INSERTED)

**Goal**: Mail's existing write tools keep their documented promises on a large, real mailbox: a batch within the cap finishes and always leaves a receipt, and a draft carries the sender the caller chose. Email work comes before any feature phase (owner, 2026-09-24).
**Depends on**: Phase 2
**Requirements**: MAIL-01, MAIL-02, MAIL-03, MAIL-04
**Success Criteria** (what must be TRUE):

  1. On an IMAP mailbox with 9k+ messages, a 25-message `move_mail` and `trash_mail` finish inside their host timeout, and so do their dry runs. The host timeout of `_MOVE`, `_TRASH` and every `_PRESENT` call (the move and trash previews and the status read) scales with the batch size, and each script's `with timeout` backstop stays ≥ its host cap (the Phase 1 tripwire). `mail_undo` of a 25-message move receipt also finishes. Verified on device with the Mail watchdog running.
  2. A host timeout inside `recoverable()` still leaves a receipt: the audit gets a `done` record with the unfinished ids marked `unknown`, and the error names the receipt and the two safe next steps — re-run the same batch (moved ids report `not-in-source`) or `mail_undo(<receipt>)` — never the generic "dismiss any stuck prompt" text.
  3. `create_draft(..., from_address=<a non-default account's address>)` opens a draft with that From address, checked on device. The locator reports `from` (the requested address, or "(Mail default account)"). The docstring states that a new draft is unthreaded and sends replies to `mail_reply`.
  4. On a Mac with more than one account, `mail_reply` keeps the receiving account and the thread headers — checked on device and recorded in `docs/mail-applescript-facts.md`.
  5. A device probe runs first and settles what Mail does with a `from_address` that no account owns: reject it, fall back to the default, or keep a bare From header. The finding goes into `docs/mail-applescript-facts.md`. If Mail does not reject it, `send_mail` and `create_draft` refuse an unowned address before any native write, and `send_mail`'s dry run still makes no native call.

**Plans**: TBD

### Phase 3: EventKit Depth — Calendar Alarms & Recurrence, Reminders CRUD & Subtasks

**Goal**: The one native plane Calendar and Reminders share reaches Mail-level completeness — alarms and real recurrence on events, deletion, lists and subtasks on reminders.
**Depends on**: Phase 02.1
**Requirements**: CAL-01, CAL-02, CAL-03, CAL-04, REM-01, REM-02, REM-03, REM-04, REM-06
**Success Criteria** (what must be TRUE):

  1. Creating or updating an event with a minutes-before alarm list lands `EKAlarm`s that verify-after-write reads back; an all-day event and a recurring all-day event created in a non-UTC timezone fire on the correct day on device, probed before the code is written rather than fixed after.
  2. A recurring event created with `BYDAY` (including monthly ordinals), `BYMONTHDAY` or `BYMONTH` reads back six months of occurrences matching RFC 5545 expansion; a shape EventKit cannot express is rejected loudly with a typed error naming the shape, never silently saved.
  3. `delete_reminder(id)` defaults `dry_run=True`, logs its own audit verb, and its verify-after-write read confirms the reminder is gone on device — the same contract as `delete_event`.
  4. A reminder list can be created and the new list appears in the adapter's list read.
  5. Subtasks read and create through the public `parentReminder` route on macOS 14+ and read back under their parent; the tags probe runs as the phase's first task and its answer is the deliverable — tags ship read-only from the Reminders sqlite store with the write gap named in the tool docstring, or the probe's finding is documented and the surface is dropped. No private-API write in either outcome.
  6. `events()` and `reminders()` Pointers carry the owning calendar or list id in `folder` — the same container token `free_busy(calendars=…)` and the write tools already take; a unit test on `_event_pointer` and `_reminder_pointer` with a fake `calendar()` passes, and a caller filters by calendar without the per-calendar `free_busy` workaround (#207).

**Plans**: TBD

### Phase 4: Notes & Photos — Settle the Mechanism, Then Ship the Read Plane

**Goal**: The two adapters whose mechanism is still open are settled on device before any feature code; what survives the probe ships as a bounded read plane, what does not ships as a documented gap.
**Depends on**: Phase 3
**Requirements**: NOTE-01, NOTE-02, PHO-01, PHO-02, PHO-03, PHO-04
**Success Criteria** (what must be TRUE):

  1. `uv add osxphotos` is run on the deployment target as the phase's first task and the resolver's actual output decides the plane — osxphotos adopted and the stale pyproject "deferred: pyobjc conflict" note corrected, or PhotoKit via PyObjC taken as the fallback with the conflict quoted in the decision.
  2. Albums list as Pointers and a photo's metadata reads back bounded by id (dates, location, persons, EXIF subset) — no thumbnails, no inline image bytes, no full library dumps.
  3. Exporting a photo by id writes the file to an allowlisted destination directory under the write-to-disk discipline, and the exported file opens as the expected image.
  4. A written decision on Notes semantic search lands before any indexing code exists — embedding model, chunking, index build and refresh policy, size cap, and the optional-extra boundary — and "not adopted, here is why" closes the requirement legitimately.
  5. If adopted, `notes_semantic(query)` returns Pointers from a lazily built, size-capped sidecar in the server's state dir (same shape as the Mail FTS sidecar), available only when the `[semantic]` extra is installed, and a plain `uv sync` pulls no ML dependency.

**Plans**: TBD

### Phase 5: Operator Control Plane — Adapter Toggles and the Localhost Dashboard

**Goal**: An operator who wants Mail but not Photos gets exactly that, and can see the server's grants, usage, audit trail and recoverable backups without reading JSONL by hand.
**Depends on**: Phase 4
**Requirements**: PLAT-01, PLAT-02
**Success Criteria** (what must be TRUE):

  1. A config setting read at daemon start enables and disables adapters per app; a disabled adapter's tools are absent from the tool list — never registered-and-erroring — and `doctor` reports the active adapter set.
  2. A dashboard served by the daemon shows grants and `doctor` output, `usage`, the audit trail, and browsable recoverable-plane backups (recovery/history), rendered without an SPA framework.
  3. The dashboard exposes the adapter toggles, and a toggle changed there is reflected by `doctor` and by tool presence after the daemon restarts.
  4. The dashboard answers on loopback only — a non-loopback bind is refused — so nothing is exposed beyond the machine.

**Plans**: TBD
**UI hint**: yes

### Phase 6: Distribution — uvx, Bundles, Cask, and the Companion Plugin

**Goal**: Someone who is not the author installs the server, the daemon and the companion skill without cloning the repo.
**Depends on**: Phase 5
**Requirements**: DIST-01, DIST-02, DIST-03, DIST-04, DIST-05, DIST-06
**Success Criteria** (what must be TRUE):

  1. A machine that has never seen the repo runs the server by following the README's first code block (`uvx macos-apps-mcp`); clone-and-venv is documented as the contributor path, not the user path.
  2. The PyPI project page links to repo, issues and changelog from `[project.urls]`.
  3. A release publishes a `.mcpb` bundle that installs into Claude Desktop in one click, and the notarized `.app` installs via `brew install --cask …` with the staple-then-zip order preserved.
  4. `claude plugin install` wires the companion skill and the MCP server config in one step from the in-repo `.claude-plugin/plugin.json`, `skills/<name>/SKILL.md` and `.mcp.json`; the same `skills/` layout installs into another agent via `npx skills add elfensky/macos-apps-mcp`.
  5. The companion skill teaches the cockpit workflows — triage reads, pointer citation, draft-review — and a session using it cites a Mail pointer by id + folder + account instead of pasting a body.
  6. `scripts/build_app.sh` builds the bundle on an x86_64 Mac — `cryptography<49` (48.0.1, the last universal2 wheel) constrains the install on x86_64 only, arm64 keeps current cryptography — and the Intel bundle passes its env-free import smoke (#205). DIST-06 has no dependency on Phases 1–5 and may land early as a `/gsd-quick` task.

**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 02.1 → 3 → 4 → 5 → 6

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Gate — Land the Spiked Architecture Cuts | 11/14 | In Progress|  |
| 2. Gate Close — Fail-Closed Suite and Device Sweep | 0/TBD | Not started | - |
| 02.1. Mail Fixes (INSERTED) | 0/TBD | Not started | - |
| 3. EventKit Depth — Calendar & Reminders | 0/TBD | Not started | - |
| 4. Notes & Photos | 0/TBD | Not started | - |
| 5. Operator Control Plane | 0/TBD | Not started | - |
| 6. Distribution | 0/TBD | Not started | - |
