---
phase: "2"
slug: "gate-close-fail-closed-suite-and-device-sweep"
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: "2026-09-28"
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x (`pyproject.toml`: `pytest >=8,<10`) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` — `addopts = "-m 'not integration'"` |
| **Quick run command** | `MACOS_APPS_READ_ONLY=1 uv run pytest -q` |
| **Full suite command** | `uv run pytest && MACOS_APPS_READ_ONLY=1 uv run pytest && uv run ruff check . && uv run ruff format --check .` |
| **Device command** | `MACOS_APPS_ALLOW_SEND=mail uv run pytest -m integration` (manual, owner at the Mac, watchdog loaded — never in CI) |
| **Estimated runtime** | ~60 seconds (unit, both modes); device sweep minutes |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest -q` and `MACOS_APPS_READ_ONLY=1 uv run pytest -q`
- **After every plan wave / before each PR merge:** Run the full suite command
- **GATE-11 proof:** the Popen-spy run once after the doctor fix, not per commit
- **Before `/gsd-verify-work`:** full suite green in both modes, plus the device sweep at 0 failed / 0 errors (D-06)
- **Max feedback latency:** 60 seconds (unit)

---

## Per-Task Verification Map

Seeded from RESEARCH.md §Validation Architecture; task IDs from the 6 plans. The executor updates status.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 02-01 T1 | 02-01 | 1 | GATE-07 | — | Read-only deployment: gated-off tools absent, not registered-and-erroring; 4 fact tests read `registry.TOOLS`; 8 call tests skip by one named marker | unit | `MACOS_APPS_READ_ONLY=1 uv run pytest -q` | ✅ | ⬜ pending |
| 02-01 T2 | 02-01 | 1 | GATE-07 | — | CI runs the read-only suite as a second step (D-02) | CI | `grep -c "MACOS_APPS_READ_ONLY=1 uv run pytest" .github/workflows/ci.yml` | ✅ | ⬜ pending |
| 02-02 T1 | 02-02 | 1 | GATE-11 | — | `doctor._process_name` reaches `ps` only through `runtime.tracked_run` | unit | `uv run pytest tests/test_doctor.py tests/test_doctor_deploy.py -q` | ✅ | ⬜ pending |
| 02-02 T1 | 02-02 | 1 | GATE-11 | — | A direct `subprocess` call in `doctor.py` / `adapters/*.py` fails the tripwire | unit | `uv run pytest tests/test_native_seam.py -v` | ❌ W0 | ⬜ pending |
| 02-02 T1 | 02-02 | 1 | GATE-11 | — | Unit suite spawns 0 `ps` / `pgrep` processes | unit (proof) | `uv run pytest -p <popen-spy plugin> -q` | ❌ W0 | ⬜ pending |
| 02-03 T1; 02-04 T3 | 02-03, 02-04 | 1, 2 | GATE-12 | — | `inbox_messages` selects marker mails only, account-matched to `scratch_mailbox`, fails loud naming the seed command (D-04) | integration | `uv run pytest -m integration -k inbox` | ✅ (rewrite) | ⬜ pending |
| 02-05 T3 | 02-05 | 3 | GATE-12 | — | Device suite green on macOS 27.0 against a daemon rebuilt from `develop` | integration | `MACOS_APPS_ALLOW_SEND=mail uv run pytest -m integration` | ✅ | ⬜ pending |
| 02-05 T3 | 02-05 | 3 | GATE-12 | — | Lint and format clean at gate close | CI + local | `uv run ruff check . && uv run ruff format --check .` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] Popen-spy pytest plugin (GATE-11 proof) — scratch file, not committed
- [ ] New test in `tests/test_native_seam.py`: no `ast.Call` to `subprocess.*` in `doctor.py` or `adapters/*.py` (`subprocess.TimeoutExpired` references stay legal)
- [ ] `inbox_messages` rewrite in `tests/test_integration.py` (D-04)
- [ ] One-time seed of the 2 marker mails before the first sweep run

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Device integration sweep | GATE-12 | Touches real apps, TCC and Mail; never in CI | Owner at the Mac; watchdog loaded and log fresh; Mail idle (D-03); run the device command; record each skip/xfail with its reason in `02-VERIFICATION.md` (D-06) |
| Daemon rebuilt from `develop` | GATE-12 | Needs signing identity and launchd | Build, sign, install, kickstart; `doctor().build` reports the `develop` sha |
| v0.12.0 release | D-09 | One-way publish; owner approval required | `docs/RELEASING.md`; `doctor().version` = `0.12.0`, `doctor().build` = tagged sha |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
