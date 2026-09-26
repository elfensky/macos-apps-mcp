---
phase: "1"
slug: "gate-land-the-spiked-architecture-cuts"
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: validated
nyquist_compliant: true
wave_0_complete: true
created: "2026-09-25"
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x (`pyproject.toml`: `pytest 8.x, <10`) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` — `addopts = "-m 'not integration'"` |
| **Quick run command** | `uv run pytest` |
| **Full suite command** | `uv run pytest && uv run ruff check . && uv run ruff format --check .` |
| **Device command** | `uv run pytest -m integration -k "<selector>"` (manual, never in CI) |
| **Estimated runtime** | ~60 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest`
- **After every plan wave / before each card PR merge (D-07):** Run the full suite command
- **Before `/gsd-verify-work`:** Full suite must be green
- **Device checkpoints (D-08):** at their named point in the landing sequence, not deferred to phase end
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

Seeded from RESEARCH.md §Validation Architecture. The planner fills task IDs; the executor updates status.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 01-02 T1, 01-04 T1–T3 | 01-02, 01-04 | 2, 3 | GATE-01 | T-1-05, T-1-10 | A test that forgets the seam fake raises; no real Apple Event; tripwire over every `adapters/*.py` + `doctor.py` | unit | `uv run pytest tests/test_native_seam.py -v` | ✅ | ✅ green |
| 01-02 T1, T2 | 01-02 | 2 | GATE-01 | T-1-05 | `body_file` / `tracked_run` locked at runtime (conftest), lock self-tests | unit | `uv run pytest tests/test_native_seam.py tests/test_shortcuts.py -v` | ✅ | ✅ green |
| 01-06 T1, T2 | 01-06 | 4 | GATE-02 | T-1-15, T-1-16 | `runtime` 11 public names; EventKit in `eventkit.py`; one worker | unit | `uv run pytest tests/test_runtime.py tests/test_eventkit.py -v` | ✅ | ✅ green |
| 01-09 T1, T2; 01-12 T3 | 01-09, 01-12 | 6, 9 | GATE-03 | T-1-25, T-1-27 | `doctor` imports no `server`; nothing below server imports server; tier gate unchanged; one ledger | unit | `uv run pytest tests/test_import_layers.py tests/test_doctor_deploy.py tests/test_server.py tests/test_deploy.py tests/test_gate_on_dispatch.py -v` | ✅ | ✅ green |
| 01-11 T1; 01-12 T1–T3 | 01-11, 01-12 | 8, 9 | GATE-04 | T-1-31, T-1-34 | One record drives annotations/gates/guard/snapshot/notice/verb/ledger; gated-off tools recorded | unit | `uv run pytest tests/test_registry.py tests/test_tool_annotations.py -v` | ✅ | ✅ green |
| 01-13 T1, T2 | 01-13 | 10 | GATE-05 | T-1-37, T-1-38 | Removes-content class defaults `dry_run=True`; `delete_*` caught fail-closed; update_note preview writes nothing | unit | `uv run pytest tests/test_registry.py tests/test_notes.py tests/test_server.py -v` | ✅ | ✅ green |
| 01-11 T1, T2 | 01-11 | 8 | GATE-06 | T-1-32 | Every write logs its own verb; `_audit_op` removed; create_contact logged | unit | `uv run pytest tests/test_audit.py tests/test_audit_middleware.py tests/test_registry.py -v` | ✅ | ✅ green |
| 01-07 T1–T3 | 01-07 | 4 | GATE-08 | T-1-18, T-1-19 | `HEADER_FINGERPRINT` covers every read column; fixture runs both shapes | unit | `uv run pytest tests/test_mail_search.py tests/test_mail_triage.py tests/test_mail_cleanup.py tests/test_mail_index.py tests/test_mail_ids.py -v` | ✅ | ✅ green |
| 01-05 T1, T2 | 01-05 | 3 | GATE-09 | T-1-12, T-1-13 | `recoverable()` preflight; no "planned" for unchecked targets; move/trash/undo dry runs byte-identical to v0.11.0 | unit | `uv run pytest tests/test_mail_recover.py tests/test_mail_recover_dry_run_identity.py tests/test_mail.py -v` | ✅ | ✅ green |
| 01-03 T1; 01-05 T2; 01-09 T2 | 01-03, 01-05, 01-09 | 2, 3, 6 | GATE-10 | T-1-08 | Script backstop ≥ host cap at every call site; `_DEDUPE` fixed; honest refusal text; stale comment gone | unit | `uv run pytest tests/test_applescript_timeout.py -v` | ✅ | ✅ green |
| 01-01 T1 | 01-01 | 1 | GATE-13 | T-1-01 | Two-file version bump matches | unit | `uv run pytest tests/test_packaging.py -v` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `tests/conftest.py` — lock `body_file` and `tracked_run`, not only `run_osascript` (RESEARCH Pitfall 1) — plan 01-02 T1/T2
- [x] `tests/test_native_seam.py` — tripwire over every `adapters/*.py` + `doctor.py` — plan 01-04 T3
- [x] `HEADER_FINGERPRINT` coverage test (RESEARCH Pitfall 2) — plan 01-07 T2, in `tests/test_mail_index.py`
- [x] Registry test for the D-04 fail-closed `delete_*` dry-run-default rule — plan 01-13 T1, in `tests/test_registry.py`
- [x] Layering test: nothing below `server` imports `server` (the measured lazy-import graph keeps the entry-point chain server → deploy → daemon → server, so a blanket "no cycle" test would be false) — plan 01-09 T1, `tests/test_import_layers.py`
- [x] GATE-10 tripwire (RESEARCH Pitfall 5) — plan 01-03 T1, added to the existing `tests/test_applescript_timeout.py` (the #56 template test's home) instead of a new `tests/test_timeout_tripwire.py`

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Pre-gate 0.11.0 release installed; daemon answers new version + build | GATE-13 (D-05) — plan 01-01 T2/T3 | Daemon identity cannot be verified from the repo | `docs/RELEASING.md` (#209 PR form) + `docs/DAEMON.md`: build → sign → notarize → staple → install → kickstart; `.worktrees/.daemon_probe.py` shows `version: 0.11.0` and the tag's build token |
| EventKit works after the runtime split | GATE-02 (D-08 step 2) — plan 01-08 T2 | Needs real EventKit + TCC | `uv run pytest -m integration -k "request_access or create_event or create_reminder"` green on device, ≥ 3 tests selected |
| `recoverable()` preflight on real Mail; dry-run envelopes and osascript argv identical to the pre-cut tag | GATE-09 (D-08 step 3) — plan 01-08 T3 | Mail writes cannot be verified by reading code (`docs/mail-applescript-facts.md`) | Watchdog LaunchAgent `ren.lav.mail-watchdog` loaded and logging (`capture.sh` only if Mail hangs); `-m integration -k "move_mail_dry_run or move_then_undo"`; read-back of moved ids; device dry-run diff v0.11.0 tree vs card-4 tree |
| Dev-build daemon after card 5 and after card 2 | GATE-13 (D-06, D-08 step 4) — plans 01-10 T2, 01-14 T2 | Daemon identity cannot be verified from the repo | Rebuild + install signed dev build from origin/develop; probe: `build` = built sha, no `-dirty`; one outbound check gated correctly; mail_index ok/sidecar; (after card 2) dry_run defaults true on the four tools |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 60s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-09-26

---

## Validation Audit 2026-09-26

| Metric | Count |
|--------|-------|
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 |

All 11 per-task commands run green against `8885ad0`+docs (`uv run pytest <files>`; 26 + 65 + 59 + 143 + 24 + 200 + 37 + 318 + 184 + 53 + 5 passed). Each Wave 0 test is present and targets its behavior: conftest locks all three seams; `test_native_seam.py` tripwire + raise proofs; `test_mail_index.py` HEADER_FINGERPRINT coverage; `test_registry.py::test_content_removing_tools_default_to_dry_run`; `test_import_layers.py::test_nothing_below_server_imports_server`; `test_applescript_timeout.py::test_every_call_site_backstop_covers_host_cap`. Manual-only rows stay manual; their device evidence is in 01-08, 01-10 and 01-14 SUMMARY and 01-UAT test 1.
