# macos-apps-mcp

## What This Is

One consolidated MCP server (Python + FastMCP, `uv`) that gives a Claude session citable, bounded
access to native macOS apps — Mail, Messages, Notes, Calendar, Reminders, Contacts, Photos,
Safari, Music, Shortcuts — through a signed launchd daemon so one TCC grant serves every client.
Its primary caller is a Claude Code session rooted in the life-cockpit Obsidian vault; every read
returns Pointers (id + summary + deeplink), never payload dumps, and every write is gated,
id-addressed, dry-runnable, audited and recoverable.

## Core Value

**Safe writes.** Every write is gated by tier, addressed by id, dry-runnable, audited, and
recoverable — the model can never lose, destroy, or send something by accident. If reads slow
down or a domain is missing, that is a gap; if a write is unsafe, that is a failure.

## Requirements

### Validated

<!-- Shipped and relied upon — see docs/ROADMAP.md "Shipped" and .planning/codebase/. -->

- ✓ Calendar + Reminders read/write via EventKit, RRULE subset, EKSpan, verify-after-write — v1 / 0.3.0
- ✓ Typed errors, `doctor`, `now`, output hygiene, dry-run + batch caps, untrusted-data notice, id-only writes, tool annotations — 0.3.0 / 0.4.0
- ✓ Native read planes: Messages via `chat.db`, Notes via `NoteStore.sqlite`, Mail via Envelope Index + FTS body sidecar — 0.5.0 / 0.8.0
- ✓ Three capability tiers gated at registration: read → write (`MACOS_APPS_READ_ONLY`) → outbound (`MACOS_APPS_ALLOW_SEND`, flipped only by the `allow-send` CLI) — 0.4.0 / 0.9.0
- ✓ Signed `.app` + launchd daemon + unix-socket shim; TCC keyed to the bundle; Full-Disk-Access visibility — 0.8.0 (#71, #123)
- ✓ JSONL write audit trail + `audit()`; `free_busy`; Notes create/update with stable ids; Mail triage (needs-response / awaiting-reply) — 0.7.0
- ✓ Music adapter — search / now-playing / additive playback — 0.8.0 (#69)
- ✓ Mail complete as a mail-client API: addressing triple, recoverable destructive plane (locate → backup → log → act → receipt, `mail_undo`), mailbox hierarchy, status flags, trash, same- and cross-account dedupe, outgoing lifecycle (drafts / send / reply-all / forward), attachments, stats/export, bulk bodies, awaiting_reply on the index — 0.9.0 → 0.10.1
- ✓ Device-verified Mail facts (`docs/mail-applescript-facts.md`) and the probe-first discipline: ten consecutive 0.9.x cuts had their premise revised on device before code was written

### Active

<!-- Current scope, in the order the phases run. -->

**Gate — land the 2026-08-28 spiked architecture review, make the suite fail-closed**
- [ ] Native seam fail-closed for all 20 modules (every adapter + doctor + shortcuts `tracked_run`), tripwire globs `adapters/*.py` — spike card 1
- [ ] `runtime.py` split: EventKit cluster to its own module, runtime 25 → ~10 public names — card 7
- [ ] Tier policy in its own module; `doctor` no longer imports `server` (the package's only import cycle) — card 5
- [ ] One registration record per tool; the eight hand tables derived from it; every destructive tool defaults `dry_run=True`; audit verbs for the nine writes that log as bare `"write"` — card 2
- [ ] Script-timeout tripwire (script backstop ≥ host cap) + the `_DEDUPE` inversion, `check_batch` text, stale daemon comment — card 9 (tripwire only)
- [ ] `_fake_envelope` promoted to a shared fixture with every column executors read; `HEADER_FINGERPRINT` covers them — card 3
- [ ] Recoverable plane owns its preflight (`present` injected, dry-run inside the plane) — card 4, device-verified
- [ ] `MACOS_APPS_READ_ONLY=1 uv run pytest` green (12 failures today); doctor tests no longer run live `pgrep`
- [ ] Full device integration sweep (`uv run pytest -m integration`) green on the current OS

**Adapter depth parity — every adapter we ship is stable and as fully featured as Mail**
- [ ] Calendar: alarms on create/update, correct for all-day/recurring in non-UTC timezones (#89); extended recurrence — BYDAY and friends, unsupported shapes rejected loudly (#90)
- [ ] Reminders: delete + list management (#92); subtasks via the public `parentReminder` route, tags investigate-first and read-only if no public write exists (#91)
- [ ] Notes: semantic search sidecar — decision first, then an optional `[semantic]` extra (#93)
- [ ] Photos: settle osxphotos vs PhotoKit by running `uv add`; albums, bounded metadata, export to disk (#96)

**Platform & distribution — let others use it, safely**
- [ ] Per-adapter enable/disable (want Mail, not Photos) read at daemon start; a disabled adapter's tools are absent, `doctor` reports the active set
- [ ] Localhost dashboard served by the daemon: grants/`doctor`, `usage`, audit trail, browsable recoverable-plane backups, adapter toggles; loopback-only (#126)
- [ ] Distribution: README leads with `uvx` (#113), `[project.urls]` (#111), `.mcpb` per release + Homebrew cask for the notarized `.app` (#107), companion skill + Claude Code plugin whose `skills/` layout is also `npx skills`-installable (#106)

**Deferred to v2 (tracked in REQUIREMENTS.md):** Contacts depth (#94/#95) and Messages depth (#86–#88) — owner's call at the 2026-08-28 roadmap review; Safari bookmarks/reading list/history (#97); Maps, geocode, current position, Weather (#98–#100, low priority); user-preferences env context (#105); menubar companion (Swift `MenuBarExtra`, pure client of the daemon); network transport + auth + SSE bridge for Home Assistant (#127); alarms on reminders.

### Out of Scope

- **Screenshot, camera, audio capture (#101) and the system-utilities cluster (#102)** — "an apps MCP, not a Mac-control MCP" (owner, 2026-08-28); the caller already has Bash and a screenshot capability.
- **Generic AppleScript/JXA escape hatch (#103)** — bypasses the typed-safety design; run `steipete/macos-automator-mcp` alongside if needed. Roadmap marks it likely-wontfix.
- **Journal** — no API at all (settled in DESIGN.md).
- **Rewriting as an iMCP-shaped GUI app** — the stdio server + signed helper stays. The menubar companion (above) is a *client* of the daemon, not a replacement for the server; this narrows, not reverses, the DESIGN.md "not planned" note.
- **Contributing Mail support to iMCP** — evaluated 2026-07-14, declined.
- **Targeted permanent delete in Mail; `download-bodies`; `download-attachments`** — device probing proved the mechanisms do not exist (0.9.3 / 0.9.5 / 0.9.9); recorded so they are not re-filed.
- **Merging the spike branches as-is** — `spike/arch-review-N-*` are throwaway primary sources; each cut is re-landed by rebasing onto the previous PR, then the branches and `.claude/worktrees/` are deleted.
- **Timeouts on the shim↔daemon hop** — #170; a dead stream must answer, never time out.

## Context

- **Codebase map:** `.planning/codebase/` (2026-08-28) — ARCHITECTURE, STRUCTURE, STACK, INTEGRATIONS, CONVENTIONS, TESTING, CONCERNS. CONCERNS.md records the spiked review's findings with file:line evidence.
- **Primary architecture sources:** `CLAUDE.md` ("Architecture (don't drift)"), `DESIGN.md`, `docs/DAEMON.md`, `docs/ROADMAP.md` (including the 2026-08-03 and 2026-08-13 review write-ups), `docs/mail-applescript-facts.md`.
- **The 2026-08-28 spiked architecture review** (develop @ d9ac75f, 0.10.1): nine cards, each spiked in an isolated worktree with the unit suite (baseline 1196) + ruff run and the diff measured. Cards 1, 7, 5 are pure moves, byte-identical bodies, green; card 2 has a real precedent (`usage` shipped mis-classified; nine writes audit as `"write"`); card 3 found `query_duplicate_rows` (the #140 byte-identity gate) has never run through sqlite in a unit test; card 8 withdrawn on trial; card 9's wrapper withdrawn, replaced by a 25-line tripwire. Branches `spike/arch-review-{1,2,3,4,5,6,7,9}-*` exist locally, never pushed.
- **Caller:** the life-cockpit Obsidian vault's Claude Code session; the mail-vs-vault debate (2026-08-02) established that citation *rendering* was never the gap — reads must carry `id + folder + account`.
- **Landscape (2026-07-14 survey):** apple-mcp (3.1k★) archived; iMCP is the only maintained multi-app suite and ships no Mail/Notes/Photos/Safari. No surveyed server combines uniform bounded reads across Mail + Messages + Notes + Calendar + Reminders — that combination is this repo.
- **Verification culture:** Mail writes are verified by running them and inspecting the resulting message; three reviews and a green suite once passed a forward that delivered empty mail and ate seven attachments. Device probing routinely overturns an issue's premise — the probe result is a valid deliverable.

## Constraints

- **Tech stack**: Python 3 + FastMCP, `uv`, `ruff` (E, F, I, UP, B, SIM; line-length 88), no mypy — same setup as the sibling repos; the Protocol seam keeps the tool layer testable without it.
- **Architecture**: tools are thin dispatch; adapters are typed `Protocol`s (reads uniform → `list[Pointer]`, writes per-adapter typed); one adapter module per app, no cross-adapter reach; all native access through `runtime.run_native()` on the single serialized worker (`max_workers=1`, never widened) — EventKit thread affinity + TCC.
- **Safety tiers**: read → write (`@_write_tool`/`@_additive_tool`, skipped by `MACOS_APPS_READ_ONLY`) → outbound (`@_send_tool("<adapter>")`, only when `MACOS_APPS_ALLOW_SEND` names the adapter; `READ_ONLY` wins). A gated-off tool is absent, never registered-and-erroring. Outbound defaults `dry_run=True` and its dry-run path makes no native call.
- **Shim↔daemon hop**: no read deadline (`Timeout(None, connect=10.0)`); per-operation limits belong in the adapter.
- **Testing**: `uv run pytest` mocks at the adapter boundary with Protocol fakes and fails closed on the native seam; `uv run pytest -m integration` touches real apps/TCC and is run manually, never in CI. Every Mail write is verified on device with the watchdog running.
- **Branches & releases**: `develop` is the trunk, every PR rebase-merged (linear); `main` is release-only, `--no-ff` cuts tagged `vX.Y.Z`; two-file version bump + `doctor().version` proof per `docs/RELEASING.md`. Merging changes nothing until the `.app` is rebuilt and reinstalled. Ship in small cuts; milestones and releases need not line up.
- **Reporting**: progress is reported by opening/closing GitHub issues and PRs (tracker `elfensky/macos-apps-mcp`); the life-cockpit vault pulls from the tracker — nothing to mirror there.
- **Vault journal**: as work lands (commit / merge / release), a bullet goes to the day's vault journal under `#personal`.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Core value is safe writes, not read breadth | Reads that are slow or missing are gaps; an unsafe write is a failure the caller cannot recover from | — Pending |
| Gate first: land the spiked review before any feature work | Cards 1/7/5 are green pure moves that rot if left; card 1 makes the whole suite fail-closed before server.py/runtime.py are reshaped; Contacts work would touch the same files | — Pending |
| Existing nine adapters stable and full-featured before new domains | Owner's call 2026-08-28: "make sure the ones we have now are all working, stable, and as fully featured as possible" | — Pending |
| Phase order: Gate → adapter depth → new domains → platform | Platform (#127 network transport, menubar) is the largest job and benefits from a settled registry/tier module | — Pending |
| Contacts and Messages depth deferred to v2 | Owner's call at roadmap review 2026-08-28: v1 depth is Calendar/Reminders, Notes, Photos | — Pending |
| Apps MCP, not a Mac-control MCP | Capture and system utilities (#101/#102) are out; Bash and the host already cover them | ✓ Good |
| Menubar companion deferred to v2; dashboard first | The dashboard builds the endpoints the menubar would consume; the companion stays a Swift client of the daemon, never a second TCC identity | — Pending |
| Home Assistant access (#127) deferred to v2, rescoped as SSE bridge + auth | HA's MCP Client is SSE-only; auth alone would not connect | — Pending |
| #103 escape hatch out of scope | Bypasses typed safety; an external server covers the need | ✓ Good |
| Spike branches are primary sources, not landing branches | Each cut re-lands by rebasing onto the previous PR; branches + worktrees deleted afterwards | — Pending |
| `dry_run=True` on every destructive tool, enforced from the registry | Today `delete_event`/`delete_draft` default False and `delete_note` has none — three safety contracts for one class of call | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-08-28 after roadmap review*
