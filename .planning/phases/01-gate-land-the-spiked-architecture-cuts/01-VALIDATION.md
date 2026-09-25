---
phase: "1"
slug: "gate-land-the-spiked-architecture-cuts"
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
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
| TBD | TBD | TBD | GATE-01 | T-1-01 | A test that forgets the seam fake raises; no real Apple Event | unit | `uv run pytest tests/test_native_seam.py -v` | ✅ (widen) | ⬜ pending |
| TBD | TBD | TBD | GATE-01 | T-1-01 | `body_file` / `tracked_run` locked at runtime | unit | `uv run pytest tests/test_native_seam.py -v` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | GATE-02 | — | `runtime` ~10 public names; EventKit in own module | unit | `uv run pytest tests/test_runtime.py tests/test_eventkit.py -v` | ⚠️ new file | ⬜ pending |
| TBD | TBD | TBD | GATE-03 | T-1-02 | `doctor` imports no `server`; no import cycle; tier gate unchanged | unit | `uv run pytest tests/test_doctor.py tests/test_server.py tests/test_deploy.py tests/test_gate_on_dispatch.py -v` | ❌ W0 (cycle test) | ⬜ pending |
| TBD | TBD | TBD | GATE-04 | T-1-02 | One record drives annotations/gates/guard/snapshot/notice/verb; gated-off tools recorded | unit | `uv run pytest tests/test_registry.py tests/test_tool_annotations.py -v` | ⚠️ new file | ⬜ pending |
| TBD | TBD | TBD | GATE-05 | T-1-03 | Destructive class defaults `dry_run=True`; `delete_*` caught fail-closed | unit | `uv run pytest tests/test_registry.py -v` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | GATE-06 | — | Every write logs its own verb; no `"write"` fallback | unit | `uv run pytest tests/test_audit.py tests/test_audit_middleware.py -v` | ✅ (extend) | ⬜ pending |
| TBD | TBD | TBD | GATE-08 | — | `HEADER_FINGERPRINT` covers every read column; both shapes | unit | `uv run pytest tests/test_mail_search.py tests/test_mail_cleanup.py tests/test_mail_index.py -v` | ❌ W0 (coverage test) | ⬜ pending |
| TBD | TBD | TBD | GATE-09 | T-1-03 | `recoverable()` preflight; no "planned" for unchecked targets | unit | `uv run pytest tests/test_mail_recover.py tests/test_mail.py -v` | ⚠️ extend | ⬜ pending |
| TBD | TBD | TBD | GATE-10 | — | Script backstop ≥ host cap; `_DEDUPE` fixed | unit | `uv run pytest tests/test_timeout_tripwire.py -v` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | GATE-13 | — | Two-file version bump matches | unit | `uv run pytest tests/test_packaging.py -v` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/conftest.py` — lock `body_file` and `tracked_run`, not only `run_osascript` (RESEARCH Pitfall 1)
- [ ] `tests/test_native_seam.py` — tripwire over every `adapters/*.py` + `doctor.py`
- [ ] `HEADER_FINGERPRINT` coverage test (RESEARCH Pitfall 2)
- [ ] Registry test for the D-04 fail-closed `delete_*` dry-run-default rule
- [ ] Static import-cycle test for `doctor.py` / the package
- [ ] `tests/test_timeout_tripwire.py` — GATE-10 tripwire (RESEARCH Pitfall 5)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Pre-gate 0.11.0 release installed; daemon answers new version + build | GATE-13 (D-05) | Daemon identity cannot be verified from the repo | `docs/RELEASING.md` + `docs/DAEMON.md`: build → sign → notarize → staple → install → kickstart; then `doctor()` shows `version: 0.11.0` and the tagged `build` sha |
| EventKit works after the runtime split | GATE-02 (D-08 step 2) | Needs real EventKit + TCC | `uv run pytest -m integration -k "request_access or create_event or create_reminder"` green on device |
| `recoverable()` preflight on real Mail; dry-run envelopes and osascript argv byte-identical to the pre-cut tag | GATE-09 (D-08 step 3) | Mail writes cannot be verified by reading code (`docs/mail-applescript-facts.md`) | Start `~/mail-watchdog/capture.sh`; run against `Personal/macos-apps-mcp-test`; diff against the v0.11.0 baseline |
| Dev-build daemon after card 5 and after card 2 | GATE-13 (D-06, D-08 step 4) | Daemon identity cannot be verified from the repo | Rebuild + install dev build; `doctor().build` = built sha; one outbound dry run reports gated correctly |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
