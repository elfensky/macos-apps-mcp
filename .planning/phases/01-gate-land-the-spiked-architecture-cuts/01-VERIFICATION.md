---
phase: 01-gate-land-the-spiked-architecture-cuts
verified: 2026-09-26T00:00:00Z
status: human_needed
score: 6/6 must-haves verified
covered_files: [".planning/phases/01-gate-land-the-spiked-architecture-cuts/01-01-PLAN.md", ".planning/phases/01-gate-land-the-spiked-architecture-cuts/01-01-SUMMARY.md", ".planning/phases/01-gate-land-the-spiked-architecture-cuts/01-02-PLAN.md", ".planning/phases/01-gate-land-the-spiked-architecture-cuts/01-02-SUMMARY.md", ".planning/phases/01-gate-land-the-spiked-architecture-cuts/01-03-PLAN.md", ".planning/phases/01-gate-land-the-spiked-architecture-cuts/01-03-SUMMARY.md", ".planning/phases/01-gate-land-the-spiked-architecture-cuts/01-04-PLAN.md", ".planning/phases/01-gate-land-the-spiked-architecture-cuts/01-04-SUMMARY.md", ".planning/phases/01-gate-land-the-spiked-architecture-cuts/01-05-PLAN.md", ".planning/phases/01-gate-land-the-spiked-architecture-cuts/01-05-SUMMARY.md", ".planning/phases/01-gate-land-the-spiked-architecture-cuts/01-06-PLAN.md", ".planning/phases/01-gate-land-the-spiked-architecture-cuts/01-06-SUMMARY.md", ".planning/phases/01-gate-land-the-spiked-architecture-cuts/01-07-PLAN.md", ".planning/phases/01-gate-land-the-spiked-architecture-cuts/01-07-SUMMARY.md", ".planning/phases/01-gate-land-the-spiked-architecture-cuts/01-08-PLAN.md", ".planning/phases/01-gate-land-the-spiked-architecture-cuts/01-08-SUMMARY.md", ".planning/phases/01-gate-land-the-spiked-architecture-cuts/01-09-PLAN.md", ".planning/phases/01-gate-land-the-spiked-architecture-cuts/01-09-SUMMARY.md", ".planning/phases/01-gate-land-the-spiked-architecture-cuts/01-10-PLAN.md", ".planning/phases/01-gate-land-the-spiked-architecture-cuts/01-10-SUMMARY.md", ".planning/phases/01-gate-land-the-spiked-architecture-cuts/01-11-PLAN.md", ".planning/phases/01-gate-land-the-spiked-architecture-cuts/01-11-SUMMARY.md", ".planning/phases/01-gate-land-the-spiked-architecture-cuts/01-12-PLAN.md", ".planning/phases/01-gate-land-the-spiked-architecture-cuts/01-12-SUMMARY.md", ".planning/phases/01-gate-land-the-spiked-architecture-cuts/01-13-PLAN.md", ".planning/phases/01-gate-land-the-spiked-architecture-cuts/01-13-SUMMARY.md", ".planning/phases/01-gate-land-the-spiked-architecture-cuts/01-14-PLAN.md", ".planning/phases/01-gate-land-the-spiked-architecture-cuts/01-14-SUMMARY.md", ".planning/phases/01-gate-land-the-spiked-architecture-cuts/01-CONTEXT.md", ".planning/phases/01-gate-land-the-spiked-architecture-cuts/01-DISCUSSION-LOG.md", ".planning/phases/01-gate-land-the-spiked-architecture-cuts/01-PATTERNS.md", ".planning/phases/01-gate-land-the-spiked-architecture-cuts/01-RESEARCH.md", ".planning/phases/01-gate-land-the-spiked-architecture-cuts/01-VALIDATION.md", "macos_apps_mcp/adapters/calendar.py", "macos_apps_mcp/adapters/contacts.py", "macos_apps_mcp/adapters/mail.py", "macos_apps_mcp/adapters/mail_index.py", "macos_apps_mcp/adapters/mail_recover.py", "macos_apps_mcp/adapters/messages.py", "macos_apps_mcp/adapters/music.py", "macos_apps_mcp/adapters/notes.py", "macos_apps_mcp/adapters/photos.py", "macos_apps_mcp/adapters/reminders.py", "macos_apps_mcp/adapters/safari.py", "macos_apps_mcp/adapters/shortcuts.py", "macos_apps_mcp/audit.py", "macos_apps_mcp/contracts.py", "macos_apps_mcp/daemon.py", "macos_apps_mcp/deploy.py", "macos_apps_mcp/doctor.py", "macos_apps_mcp/eventkit.py", "macos_apps_mcp/lifecycle.py", "macos_apps_mcp/notices.py", "macos_apps_mcp/registry.py", "macos_apps_mcp/runtime.py", "macos_apps_mcp/server.py", "macos_apps_mcp/tiers.py", "tests/conftest.py", "tests/envelope.py", "tests/mail_recover_dry_run_baseline.json", "tests/test_applescript_timeout.py", "tests/test_audit.py", "tests/test_audit_middleware.py", "tests/test_contacts.py", "tests/test_deploy.py", "tests/test_doctor.py", "tests/test_doctor_deploy.py", "tests/test_eventkit.py", "tests/test_gate_on_dispatch.py", "tests/test_import_layers.py", "tests/test_integration.py", "tests/test_mail.py", "tests/test_mail_addressing.py", "tests/test_mail_cleanup.py", "tests/test_mail_drafts.py", "tests/test_mail_extras.py", "tests/test_mail_ids.py", "tests/test_mail_index.py", "tests/test_mail_recover.py", "tests/test_mail_recover_dry_run_identity.py", "tests/test_mail_search.py", "tests/test_mail_triage.py", "tests/test_music.py", "tests/test_native_seam.py", "tests/test_notes.py", "tests/test_registry.py", "tests/test_runtime.py", "tests/test_safari.py", "tests/test_server.py", "tests/test_shortcuts.py", "tests/test_tool_annotations.py"]
covered_digest: "v1:sha256:973bce9aff4d16f4de3b03d91d4051b3a21069ee22b989306d0d4498aad69006"
behavior_unverified: 0
overrides_applied: 0
human_verification:
  - test: "Reconnect a Claude Code session with /mcp against the running daemon; call doctor() and delete_event(id=<any real event>) with no other arguments."
    expected: "doctor() reports build 8885ad0 2026-09-26T08:48:01Z (or later); delete_event with only an id returns a dry-run preview (no deletion)."
    why_human: "Requires the owner's own live MCP client session (/mcp reconnect) — this verifier confirmed the identical facts via a scripted unix-socket probe (.worktrees/.daemon_probe.py), but the plan's own acceptance check (01-14-PLAN.md <human-check>) is the owner exercising the real client path, which no automated check can stand in for. Per 01-14-SUMMARY.md this was still pending as of the plan's completion."
---

# Phase 1: Gate — Land the Spiked Architecture Cuts Verification Report

**Phase Goal:** The architecture the rest of the milestone builds on is landed — a native seam that fails closed, module boundaries no adapter PR has to fight, and one registration record that makes tier, audit verb and dry-run default correct by construction.
**Verified:** 2026-09-26
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | A unit test that forgets to fake the native seam raises instead of dialing a real app, for every `adapters/*.py` module, `doctor.py`, and `shortcuts`' `tracked_run` | ✓ VERIFIED | `tests/test_native_seam.py` — AST tripwire (`test_native_module_does_not_import_the_seam_by_name`, parametrized over every file in `macos_apps_mcp/adapters/*.py` + `doctor.py`), a "sees the whole plane" guard (`test_the_tripwire_sees_the_native_modules`, asserts `len >= 10` and `doctor.py`/`shortcuts.py` present), and per-seam raise proofs (`test_unit_tests_cannot_reach_a_seam_unfaked`, parametrized `run_osascript`/`body_file`/`tracked_run`). All pass (`uv run pytest tests/test_native_seam.py` — part of the 1471-pass full run). |
| 2 | `runtime` exposes only the native door (~10/11 public names) with the EventKit cluster in its own module Calendar/Reminders import by one name; `doctor` imports no `server` symbol; tier policy and the notice middleware live in their own modules; no import cycle; bodies byte-identical; device proof `-m integration -k "request_access or create_event or create_reminder"` green | ✓ VERIFIED | `macos_apps_mcp/runtime.py` public surface = exactly `run_native, on_worker, app_process_info, terminate_children, tracked_run, run_osascript, body_file, verify_sqlite_schema, read_via_sqlite, mac_region` + logger `log` (pinned by `tests/test_runtime.py::test_runtime_public_surface_is_the_native_door`). `macos_apps_mcp/eventkit.py` holds `store, request_access, request_access_each, run_native_async, to_nsdate, to_recurrence_rule, …`; `calendar.py`/`reminders.py` import it as `from ..eventkit import (...)`. `doctor.py` has no `import ... server` / `from . import server` at module scope (`grep` returned nothing). `tests/test_import_layers.py` walks `server.py`'s whole import closure (incl. function-body lazy imports) and fails if anything below it imports back into `server`. Device proof documented in `01-08-SUMMARY.md` (7/7 `test_integration.py` cases green against real EventKit/TCC, watchdog running) — not independently re-run per task instructions (device-only evidence accepted from SUMMARY). |
| 3 | Every tool's tier/adapter/permission/audit-verb/notice come from one registration record built pre-gate (gated-off tools recorded, never derived from FastMCP `Tool` objects); every destructive tool reports `dry_run=True` by default; a registry test fails when a new one omits it | ✓ VERIFIED | `macos_apps_mcp/registry.py` — `ToolRecord` dataclass (tier, adapter, permission, audit_verb, notice, backup_notice, removes_content, snapshot, registered, fn) and `TOOLS: dict[str, ToolRecord]`, populated by `_tool`/`_read_tool`/`_additive_tool`/`_write_tool`/`_send_tool` decorators in `server.py` at import time, `registered=False` retained (not dropped) for gated-off tools. `tests/test_gate_on_dispatch.py`, `tests/test_registry.py`, `tests/test_tool_annotations.py` (37 tests) all pass — including registered-set-equals-FastMCP-list checks in default/`ALLOW_SEND=mail`/`READ_ONLY=1` subprocess modes, duplicate-name-raises-at-import, and the D-04 fail-closed `removes_content` dry_run-default sweep. `delete_event`, `delete_draft`, `delete_note`, `update_note` all default `dry_run: bool = True` in `server.py` (verified by direct grep of each signature). |
| 4 | `audit()` shows `trash_mail`, `move_mail`, `mail_undo`, `export_mail`, `save_mail_attachment`, `music_control`, `play_playlist`, `set_mode`, `set_volume`, `create_contact` under their own verbs — no bare `"write"`, nothing unlogged | ✓ VERIFIED | `registry.derive_audit_verb` raises `TypeError` for any write tier tool with no prefix match and no explicit `audit=` (no `"write"` fallback exists in the code). Each of the ten named tools carries an explicit `audit=` kwarg on its `@_write_tool`/`@_additive_tool` decorator in `server.py`: `move`, `trash`, `undo`, `export`, `save`, `control`, `play`, `set` (×2), and `create_contact` derives `create` from the prefix rule. `registry.audit_verbs()` is the one source `AuditMiddleware` reads (confirmed in `tests/test_audit_middleware.py`, `tests/test_registry.py`). |
| 5 | Mail's plane holds under the new seam: shared `tests/envelope.py` fixture with widened schema/`HEADER_FINGERPRINT`, `sequoiaify_envelope` + #201 sidecar; `recoverable(...)` runs its own preflight so `dedupe_batch(dry_run=True)` cannot report "planned" for unchecked targets and a dry run without `present` errors; `_DEDUPE` timeout fixed; verified on a scratch mailbox with the watchdog running, dry-run envelopes/argv byte-identical to pre-cut `develop` | ✓ VERIFIED | `tests/envelope.py` is the one fake Envelope Index (widened `MSG_COLS`/`SCHEMA`, both native and Sequoia shapes via `sequoiaify_envelope`); `mail_index.HEADER_FINGERPRINT` coverage pinned by tests in `tests/test_mail_index.py` (64 tests incl. `test_mail_recover.py`/`test_mail_recover_dry_run_identity.py` all pass). `macos_apps_mcp/adapters/mail_recover.py::recoverable()` requires `present` on every `dry_run=True` call (raises `TypeError` naming the op otherwise) and never calls `act`/`_backup`/`audit_write` on that path — confirmed by reading the function body. `_DEDUPE_TIMEOUT = 900.0` in `mail.py` (was 600, GATE-10). Scratch-mailbox device verification (real move→undo round trip, watchdog confirmed running via `launchctl list`, byte-identical dry-run envelope/argv diffs) is documented with concrete tool output in `01-08-SUMMARY.md` — accepted per task instructions as device-only evidence, not re-run. |
| 6 | Cuts land 1 → 7 → 5 → 2 (Mail-scoped 3/4/9 in parallel), each rebased onto the previous PR; after cards 5 and 2 a rebuilt/restarted daemon answers `doctor().version` with the new build and one outbound dry run reports gated correctly; `spike/arch-review-*` branches and `.claude/worktrees/` deleted | ✓ VERIFIED | `git log --oneline --merges v0.11.0..origin/develop` = 0 merge commits (fully linear rebase history, per CLAUDE.md). `git log --oneline --reverse v0.11.0..origin/develop` shows first-commit order: card 9 (`0cfc0f0`) → card 1 (`dbcb326`) → card 4 (`3ba1c9a`) → card 7 (`32d0f20`) → card 3 (`1978bdd`) → card 5 (`c7a9e88`) → card 2 (`43346ed`..`8885ad0`) — sequential cards 1→7→5→2 in required order, Mail-scoped 3/4/9 interleaved as the plan allows. `git branch --list 'spike/arch-review-*'` and `git worktree list` both confirm zero spike branches/worktrees remain (verified directly by this verifier, not just SUMMARY narration). This verifier independently re-ran `uv run python .worktrees/.daemon_probe.py` (read-only, dry-run-only per task instructions) against the currently installed daemon and got: `version: 0.11.0`, `build: 8885ad0 2026-09-26T08:48:01Z`, `deployment.outbound: ['mail']`, `send_mail in tool list: True`, all four `dry_run` defaults `True`, and a `dry_run: true` `send_mail` preview — identical to `01-14-SUMMARY.md`'s claimed output, independently confirming the post-card-2 daemon proof. The one remaining piece — the owner reconnecting a live Claude Code `/mcp` session to confirm the same facts through the real client path (01-14-PLAN.md's `<human-check>`) — was still marked pending in `01-14-SUMMARY.md` at completion; **see Human Verification below.** |

**Score:** 6/6 truths verified (0 present, behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `tests/test_native_seam.py` | GATE-01 tripwire over adapters + doctor + shortcuts | ✓ VERIFIED | Present, substantive (AST-walk + raise proofs), wired (imports `runtime`, walks real `adapters/` dir) |
| `macos_apps_mcp/eventkit.py` | EventKit cluster split from runtime | ✓ VERIFIED | 16 public functions (`store`, `request_access`, `run_native_async`, NSDate/RRULE helpers); imported by `calendar.py`/`reminders.py` |
| `macos_apps_mcp/tiers.py` | Tier policy module | ✓ VERIFIED | Present; `doctor.py` no longer imports `server` |
| `macos_apps_mcp/notices.py` | Untrusted-data notice middleware | ✓ VERIFIED | Present, separate from `server.py` |
| `macos_apps_mcp/registry.py` | One `ToolRecord` registration record | ✓ VERIFIED | `ToolRecord` dataclass + `TOOLS` dict + `derive_audit_verb`/`audit_verbs`/`removes_content_tools`/`write_tools`/`snapshot_sources` views |
| `tests/envelope.py` | Shared fake Envelope Index fixture | ✓ VERIFIED | Widened `SCHEMA`/`MSG_COLS`, both native + Sequoia shapes |
| `macos_apps_mcp/adapters/mail_recover.py` | `recoverable()` preflight | ✓ VERIFIED | `present` required on every `dry_run=True` call; no `act`/`_backup`/`audit_write` on that path |
| `tests/test_applescript_timeout.py` | GATE-10 backstop ≥ host-cap tripwire | ✓ VERIFIED | 53 tests, all pass |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `macos_apps_mcp/adapters/calendar.py`, `reminders.py` | `macos_apps_mcp/eventkit.py` | `from ..eventkit import (...)` | ✓ WIRED | Confirmed by grep |
| `macos_apps_mcp/server.py` (`_tool`/`_read_tool`/`_additive_tool`/`_write_tool`/`_send_tool`) | `macos_apps_mcp/registry.py` (`registry.add`) | Decorator populates `TOOLS` at import time | ✓ WIRED | Confirmed by reading decorator source + passing `test_registry.py`/`test_tool_annotations.py` |
| `macos_apps_mcp/audit.py` (`AuditMiddleware`) | `macos_apps_mcp/registry.py` (`audit_verbs()`) | Reads verb per tool from the record, not a hand table | ✓ WIRED | Confirmed by passing `test_audit_middleware.py`; no `_audit_op` symbol remains in the codebase (removed per 01-11 plan) |
| `.worktrees/.daemon_probe.py` | running daemon (unix socket) | fastmcp `Client` over `_uds_client_factory` | ✓ WIRED | Independently re-run by this verifier; output matches SUMMARY claims exactly |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full unit suite green | `uv run pytest -q` (via `rtk proxy` to bypass output filtering) | `1471 passed, 80 deselected in 16.75s` | ✓ PASS |
| Lint clean | `uv run ruff check .` | `[]` (no findings) | ✓ PASS |
| Format clean | `uv run ruff format --check .` | `158 files already formatted` | ✓ PASS |
| GATE-10 tripwire | `uv run pytest tests/test_applescript_timeout.py -q` | `53 passed` | ✓ PASS |
| GATE-04/06 registry+audit | `uv run pytest tests/test_gate_on_dispatch.py tests/test_registry.py tests/test_tool_annotations.py tests/test_audit_middleware.py -q` | `37 passed` | ✓ PASS |
| GATE-08/09 mail plane | `uv run pytest tests/test_mail_recover_dry_run_identity.py tests/test_mail_index.py -q` | `64 passed` | ✓ PASS |
| Zero spike branches | `git branch --list 'spike/arch-review-*'` | (empty) | ✓ PASS |
| Zero spike worktrees | `git worktree list` | only main checkout | ✓ PASS |
| No merge commits since v0.11.0 | `git log --oneline --merges v0.11.0..origin/develop \| wc -l` | `0` | ✓ PASS |
| Live daemon probe (read-only, dry-run only, per task instructions) | `uv run python .worktrees/.daemon_probe.py` | `version: 0.11.0`, `build: 8885ad0 2026-09-26T08:48:01Z`, all 4 dry_run defaults `True`, outbound ledger agrees, `send_mail` dry-run-only preview, `PROBE PASSED` | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|--------------|--------|----------|
| GATE-01 | 01-02, 01-04 | Native-seam tripwire raises instead of dialing a real app | ✓ SATISFIED | `tests/test_native_seam.py` |
| GATE-02 | 01-06, 01-08 | `runtime` = native door; EventKit cluster split; no import cycle; device proof | ✓ SATISFIED | `runtime.py`/`eventkit.py` surfaces; `01-08-SUMMARY.md` device proof |
| GATE-03 | 01-09 | Tier policy + notice middleware in own modules; no `doctor`→`server` import | ✓ SATISFIED | `tiers.py`, `notices.py`, `tests/test_import_layers.py` |
| GATE-04 | 01-11, 01-12 | One registration record; gated-off tools still recorded | ✓ SATISFIED | `registry.py`, `tests/test_gate_on_dispatch.py` |
| GATE-05 | 01-13 | Destructive tools default `dry_run=True`, fail-closed registry test | ✓ SATISFIED | `server.py` signatures; `tests/test_registry.py` D-04 test |
| GATE-06 | 01-11 | Writes audit under their own verb, no bare `"write"` | ✓ SATISFIED | `registry.derive_audit_verb`; per-tool `audit=` kwargs |
| GATE-08 | 01-07 | Shared `tests/envelope.py` fixture; widened `HEADER_FINGERPRINT` | ✓ SATISFIED | `tests/envelope.py`, `tests/test_mail_index.py` |
| GATE-09 | 01-05, 01-08 | `recoverable()` preflight; `dedupe_batch` can't report "planned" unchecked | ✓ SATISFIED | `mail_recover.py::recoverable()`; `01-08-SUMMARY.md` device proof |
| GATE-10 | 01-03, 01-09 | AppleScript timeout backstop ≥ host-cap tripwire; `_DEDUPE` fixed | ✓ SATISFIED | `tests/test_applescript_timeout.py`; `_DEDUPE_TIMEOUT = 900.0` |
| GATE-13 | 01-01, 01-08, 01-10, 01-14 | Sequential landing order; daemon rebuilt/proven after cards 5 & 2; spikes deleted | ✓ SATISFIED | git history order; independently re-run daemon probe; zero spike branches/worktrees |

No orphaned requirements: REQUIREMENTS.md maps exactly GATE-01 through GATE-06, GATE-08, GATE-09, GATE-10, GATE-13 to "Phase 1 — Complete", matching the ten IDs this phase declared. GATE-07, GATE-11, GATE-12 are correctly scoped to Phase 2 (out of scope here, per task instructions).

### Anti-Patterns Found

None. Scanned every file changed since `v0.11.0` (58 files under `macos_apps_mcp/` and `tests/`) for `TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/`PLACEHOLDER`/"not yet implemented"/"coming soon". The only "not yet implemented"-adjacent hits are legitimate runtime error-message text in `mail.py` (`"the message body is not available locally (HTML-only, or not yet ...)"`) describing a real, tested Mail limitation — not a code stub.

### Human Verification Required

### 1. Owner `/mcp` reconnect and live `doctor()`/`delete_event` check

**Test:** Reconnect a Claude Code session with `/mcp` against the running daemon; call `doctor()`, then call `delete_event` with only an `id` argument.
**Expected:** `doctor()` reports build `8885ad0 2026-09-26T08:48:01Z` (or a later build); `delete_event` with only an id returns a dry-run preview (no deletion made).
**Why human:** This is 01-14-PLAN.md's own acceptance check, exercised through the owner's real MCP client path — a scripted socket probe (which this verifier ran and which passed, confirming the identical underlying facts) is not a substitute for the actual client-reconnect flow the plan calls for. `01-14-SUMMARY.md` records this as still pending at the time the plan completed ("owner should reconnect... this is the owner's own follow-up").

### Gaps Summary

No gaps. All 6 ROADMAP success criteria and all 10 declared requirement IDs (GATE-01 through GATE-06, GATE-08, GATE-09, GATE-10, GATE-13) are backed by passing tests, direct code inspection, an independently re-run daemon probe, and (for device-only claims) concrete, detailed evidence already captured in 01-08-SUMMARY.md and 01-14-SUMMARY.md. The full unit suite (1471 tests), ruff lint, and ruff format all pass cleanly on `origin/develop` tip `8885ad0`. The sole open item is a single owner-side confirmation step (the `/mcp` reconnect + live `doctor()`/`delete_event` check from 01-14-PLAN.md) that was already known to be outstanding and is not a defect — it routes this report to `human_needed` rather than `passed`, per the decision tree, but does not block architecture correctness: this verifier independently reproduced the same facts via the daemon's own socket protocol.

---

*Verified: 2026-09-26*
*Verifier: Claude (gsd-verifier)*
