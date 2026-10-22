---
phase: "05"
slug: "operator-control-plane-adapter-toggles-and-the-localhost-das"
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: "2026-10-21"
---

# Phase 05 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x (`>=8,<10`, pytest-cov); `asyncio.run(...)` inside sync tests (no pytest-asyncio); `httpx.ASGITransport` for dashboard HTTP tests (not Starlette's `TestClient`) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]`: `testpaths = ["tests"]`, `addopts = "-m 'not integration'"`; fail-closed native seams and isolated state in `tests/conftest.py` (gains the `adapters_off` file patch and `daemon.DASHBOARD_PORT = 0`) |
| **Quick run command** | `uv run pytest -q -k "adapters_off or dashboard or daemon or registry or doctor or eventkit or audit or packaging"` (a `-k` filter, so it runs at every point of the phase whichever test files exist yet) |
| **Full suite command** | `uv run pytest -q && MACOS_APPS_READ_ONLY=1 uv run pytest -q && MACOS_APPS_ALLOW_SEND=mail uv run pytest -q && uv run ruff check . && uv run ruff format --check .` |
| **Device check (manual, never CI)** | D-18 device proof on the installed 0.15.0 release: dashboard at `http://127.0.0.1:47632`, Photos off, Restart, `doctor` via a shim client, tool list, Photos back on |
| **Estimated runtime** | quick under 10 s; full suite ~22 s per tier (baseline 2229 passed, 102 deselected; `MACOS_APPS_READ_ONLY=1` 2214 passed, 15 skipped) |

---

## Sampling Rate

- **After every task commit:** Run the quick run command.
- **After every plan wave:** Run the full suite command (all three tiers and both ruff checks).
- **Before `/gsd-verify-work`:** Full suite must be green.
- **Max feedback latency:** 30 seconds.

---

## Per-Task Verification Map

Mapped from 05-01..05-09 (05-08, the packaging plan, runs in wave 1 beside 05-01 and 05-02; 05-09, the page key, runs in wave 3 between 05-03 and 05-04) (each plan's own lane; commands run from `.worktrees/<lane>`).

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 05-01-01..03 | 01 | 1 | PLAT-01 | T-05-01..05 | an OFF adapter's tools are absent in every tier, send included; meta tools never gated; `doctor` reports `adapters`, `adapters_off`, `adapters_unknown`, `adapters_pending`; no Apple Event or TCC prompt for an OFF adapter | subprocess + unit | `uv run pytest -q tests/test_adapters_off.py tests/test_registry.py tests/test_doctor.py tests/test_eventkit.py tests/test_doctor_deploy.py` | ❌ W0 (`test_adapters_off.py` holds the new doctor and EventKit cases) | ⬜ pending |
| 05-02-01..03 | 02 | 1 | PLAT-02 | T-05-06..13 | non-loopback bind refused; `/mcp` unreachable over TCP; Host / Origin / token / headers enforced; escaped output; static allow-list | unit (`ASGITransport`) + thread | `uv run pytest -q tests/test_daemon_dispatch.py tests/test_dashboard_guard.py tests/test_daemon.py` | ❌ W0 | ⬜ pending |
| 05-02-04 | 02 | 1 | PLAT-02 | — | dashboard assets in the wheel; the bundle smoke imports `macos_apps_mcp.dashboard`; merges only after 05-08 declared `starlette` | unit + build | `uv run pytest -q tests/test_packaging.py` | extend | ⬜ pending |
| 05-08-01..02 | 08 | 1 | PLAT-02 | T-05-SC | `starlette` declared, 0.15.0 in three places, a four-line three-hunk `uv.lock` diff, nothing downloaded | lock check | `uv lock --check --offline && uv sync --locked --offline && uv run pytest -q tests/test_packaging.py` | extend | ⬜ pending |
| 05-03-01..03 | 03 | 2 | PLAT-01, PLAT-02 | T-05-14..20 | toggle writes `adapters_off` atomically plus one `caller: "dashboard"` audit record; restart sets the exit flags and arms the watchdog; Outbound locked | unit | `uv run pytest -q tests/test_dashboard_adapters.py tests/test_daemon_dispatch.py tests/test_daemon.py` | ❌ W0 | ⬜ pending |
| 05-09-01..03 | 09 | 3 | PLAT-02 | T-05-40..48 | every request but `/key` needs the page-key cookie (HttpOnly, `SameSite=Strict`, `Path=/`), checked after Host; key file 0600 in a 0700 folder, atomic, stable, written only when absent; an unusable key refuses every request; the form token kept; the CLI role prints and opens the link and starts no server; `doctor` names the command, never the key | unit (`ASGITransport`) + thread | `uv run pytest -q tests/test_dashboard_key.py tests/test_dashboard_guard.py tests/test_dashboard_adapters.py tests/test_daemon.py` | ❌ W0 (`test_dashboard_key.py`, `_dashboard.py`) | ⬜ pending |
| 05-04-01..03 | 04 | 4 | PLAT-02 | T-05-21..26 | audit and receipt strings render escaped; batches group by receipt; recovery read-only; legacy `dry_run` resolved | unit | `uv run pytest -q tests/test_audit.py tests/test_dashboard_writes.py tests/test_dashboard_guard.py` | ❌ W0 | ⬜ pending |
| 05-05-01..03 | 05 | 5 | PLAT-02 | T-05-27..31 | Health single-flight off the loop; danger banner only for an active adapter; Backups never creates a directory; receipt path validated before disk access | unit | `uv run pytest -q tests/test_dashboard_system.py tests/test_dashboard_adapters.py tests/test_dashboard_writes.py` | ❌ W0 | ⬜ pending |
| 05-0[1-5]-04, 05-09-04 | 01..05, 09 | 1..5 | PLAT-01, PLAT-02 | — | each lane lands by PR with all suites green | full suite | `uv run pytest -q && MACOS_APPS_READ_ONLY=1 uv run pytest -q && uv run ruff check . && uv run ruff format --check .` | exists | ⬜ pending |
| 05-06-01..03 | 06 | 6 | PLAT-01, PLAT-02 | T-05-32..36 | one-way cut only after the owner's decision; notarized build from the tag; old bundle kept; `doctor().version == "0.15.0"` | full suite + device | `uv run pytest -q && MACOS_APPS_READ_ONLY=1 uv run pytest -q && MACOS_APPS_ALLOW_SEND=mail uv run pytest -q` | exists | ⬜ pending |
| 05-07-01..03 | 07 | 7 | PLAT-01, PLAT-02 | T-05-37..39 | on the installed release: refusals over HTTP (the page-key refusal included), Photos off then absent after relaunch, back on | device (manual sitting) | proof script in 05-07 Task 1 | ❌ W0 (script) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_adapters_off.py` — gate, file, outbound interplay (05-01)
- [ ] `tests/test_daemon_dispatch.py` — loopback guard, dispatcher with fake scopes, restart closure (05-02, 05-03)
- [ ] `tests/test_dashboard_guard.py` — Host / Origin / token / headers / escape / traversal via `httpx.ASGITransport` (05-02)
- [ ] `tests/test_dashboard_adapters.py` — toggle, discard, restart, grant chips, Outbound row (05-03)
- [ ] `tests/_dashboard.py` — the shared request helper with the page-key cookie; `tests/test_dashboard_key.py` — key file, Guard key matrix, CLI role, `doctor` note (05-09)
- [ ] `tests/test_dashboard_writes.py` — write list, detail, batches, recovery (05-04)
- [ ] `tests/test_dashboard_system.py` — Health, Backups (05-05)
- [ ] `tests/conftest.py` — `adapters_off` file patch (05-01); `tests/test_daemon.py` — module autouse `DASHBOARD_PORT = 0` (05-02)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| A toggle changed in the dashboard is reflected by `doctor` and by tool presence after a real launchd relaunch | PLAT-01, PLAT-02 (SC3) | needs the installed signed daemon, launchd `KeepAlive` and a real browser (Origin behavior per browser) | D-18: open the dashboard through the bundle's `dashboard` page-key link (D-19), turn Photos off, Restart, page reconnects, `doctor` via a shim client lists `adapters` without photos, the four photos tools are absent; turn Photos back on and restart |
| The pages match the four sketch references | PLAT-02 (SC2) | visual comparison | compare each page with `.planning/sketches/00{1..4}-*/README.md` at desktop and phone width |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
