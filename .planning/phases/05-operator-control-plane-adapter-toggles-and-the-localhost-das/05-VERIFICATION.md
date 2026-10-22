---
phase: 05-operator-control-plane-adapter-toggles-and-the-localhost-das
verified: 2026-10-22T23:00:00Z
status: passed
score: 4/4 must-haves verified
covered_files:
  - ".planning/phases/05-operator-control-plane-adapter-toggles-and-the-localhost-das/05-01-PLAN.md"
  - ".planning/phases/05-operator-control-plane-adapter-toggles-and-the-localhost-das/05-01-SUMMARY.md"
  - ".planning/phases/05-operator-control-plane-adapter-toggles-and-the-localhost-das/05-02-PLAN.md"
  - ".planning/phases/05-operator-control-plane-adapter-toggles-and-the-localhost-das/05-02-SUMMARY.md"
  - ".planning/phases/05-operator-control-plane-adapter-toggles-and-the-localhost-das/05-03-PLAN.md"
  - ".planning/phases/05-operator-control-plane-adapter-toggles-and-the-localhost-das/05-03-SUMMARY.md"
  - ".planning/phases/05-operator-control-plane-adapter-toggles-and-the-localhost-das/05-04-PLAN.md"
  - ".planning/phases/05-operator-control-plane-adapter-toggles-and-the-localhost-das/05-04-SUMMARY.md"
  - ".planning/phases/05-operator-control-plane-adapter-toggles-and-the-localhost-das/05-05-PLAN.md"
  - ".planning/phases/05-operator-control-plane-adapter-toggles-and-the-localhost-das/05-05-SUMMARY.md"
  - ".planning/phases/05-operator-control-plane-adapter-toggles-and-the-localhost-das/05-06-PLAN.md"
  - ".planning/phases/05-operator-control-plane-adapter-toggles-and-the-localhost-das/05-06-SUMMARY.md"
  - ".planning/phases/05-operator-control-plane-adapter-toggles-and-the-localhost-das/05-07-PLAN.md"
  - ".planning/phases/05-operator-control-plane-adapter-toggles-and-the-localhost-das/05-07-SUMMARY.md"
  - ".planning/phases/05-operator-control-plane-adapter-toggles-and-the-localhost-das/05-08-PLAN.md"
  - ".planning/phases/05-operator-control-plane-adapter-toggles-and-the-localhost-das/05-08-SUMMARY.md"
  - ".planning/phases/05-operator-control-plane-adapter-toggles-and-the-localhost-das/05-09-PLAN.md"
  - ".planning/phases/05-operator-control-plane-adapter-toggles-and-the-localhost-das/05-09-SUMMARY.md"
  - "macos_apps_mcp/audit.py"
  - "macos_apps_mcp/daemon.py"
  - "macos_apps_mcp/dashboard/__init__.py"
  - "macos_apps_mcp/dashboard/adapters.py"
  - "macos_apps_mcp/dashboard/backups.py"
  - "macos_apps_mcp/dashboard/dashboard.css"
  - "macos_apps_mcp/dashboard/dashboard.js"
  - "macos_apps_mcp/dashboard/grants.py"
  - "macos_apps_mcp/dashboard/guard.py"
  - "macos_apps_mcp/dashboard/health.py"
  - "macos_apps_mcp/dashboard/html.py"
  - "macos_apps_mcp/dashboard/recovery.py"
  - "macos_apps_mcp/dashboard/usage.py"
  - "macos_apps_mcp/dashboard/writes.py"
  - "macos_apps_mcp/deploy.py"
  - "macos_apps_mcp/doctor.py"
  - "macos_apps_mcp/registry.py"
  - "macos_apps_mcp/server.py"
  - "macos_apps_mcp/tiers.py"
  - "pyproject.toml"
covered_digest: "v3:sha256:a6a44075b095d2df60a383b8005c9e57458247e08f322b096ea7463bba99e5ea"
behavior_unverified: 0
overrides_applied: 0
---

# Phase 5: Operator Control Plane Verification Report

**Phase Goal:** An operator who wants Mail but not Photos gets exactly that, and can see the server's grants, usage, audit trail and recoverable backups without reading JSONL by hand.
**Verified:** 2026-10-22
**Status:** passed
**Re-verification:** No, initial verification
**Code verified:** origin/develop at 3cab97e. It has no source difference from tag v0.15.0 (`git diff --stat v0.15.0 origin/develop -- macos_apps_mcp` is empty), and no `macos_apps_mcp/` or `tests/` difference from the records lane HEAD.

## Goal Achievement

### Observable Truths (ROADMAP success criteria, D-01..D-20)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | A config setting read at daemon start enables/disables adapters per app; a disabled adapter's tools are absent (never registered-and-erroring); `doctor` reports the active set | VERIFIED | `tiers.adapters_off()` / `adapter_enabled()` (env wins, else the home-pinned file in the daemon role only); `server._tool` ANDs `adapter_enabled` into `registered` for every tier (server.py:165-171). Live probe, `HOME=<tmp> MACOS_APPS_ADAPTERS_OFF=photos`: FastMCP lists 64 tools, none named photo*; `registry.adapter_status()` registered = 9 adapters without photos. `doctor.py:422-460` adds `adapters`, `adapters_off`, `adapters_unknown`, `adapters_pending` and the restart note. `tests/test_adapters_off.py` (22 tests) pins the grammar, the fail-closed unreadable file (D-20), FIFO and non-UTF-8 cases, and no Apple Event for an OFF adapter. |
| 2 | A dashboard served by the daemon shows grants and `doctor` output, `usage`, the audit trail and browsable recoverable-plane backups, with no SPA framework | VERIFIED | Routes in `dashboard/__init__.py`: `/` and `/write/{ts}/{n}` (audit list and detail, `writes.py`, `recovery.py`), `/health` (`health.py`, `grants.py`), `/usage`, `/backups` and `/backups/{receipt}`, `/adapters`, `/restart`, `/static/{name}`. In-process ASGI probe with the page key: `/`, `/usage`, `/health`, `/backups`, `/adapters` all answer 200. Rendering is Starlette plus a hand-rolled escape-by-default helper; no jinja2 in `pyproject.toml`; the only script is the 1 KB Copy handler in `dashboard.js`; no inline `style=` or `<script>` bodies. |
| 3 | The dashboard exposes the adapter toggles; a change there shows in `doctor` and in tool presence after a daemon restart | VERIFIED | `adapters.toggle` rewrites `adapters_off` and appends an audit record (probe: file content `photos`; record `tool: dashboard, op: toggle, args {adapter: photos, on: false}, caller: dashboard`). Unknown adapter answers 400. `POST /restart` calls `daemon.restart` (`should_exit`, `force_exit`, watchdog `os._exit(0)`; launchd relaunches). Device proof on the installed 0.15.0 (05-07 SUMMARY): the owner's browser switched Photos off, the daemon relaunched with a new pid, 9 adapters, no Photos tools, `adapters_pending` null; the scripted restore and `on` runs returned 10 adapters and the four Photos tools; audit records with caller `dashboard` exist. |
| 4 | The dashboard answers on loopback only; a non-loopback bind is refused | VERIFIED | `daemon.assert_loopback` requires a literal loopback IP (a host name such as `localhost` is refused); `bind_dashboard` calls it before `bind`. `serve()` binds `127.0.0.1:47632`. `make_dispatcher` sends only UDS scopes (`server == (path, None)`) to MCP; TCP scopes reach the dashboard or a 404, so `/mcp` is unreachable over TCP (device proof: `POST /mcp` 403, `GET /mcp` 404). `lsof` on the installed daemon: `127.0.0.1:47632 (LISTEN)` (05-06). A taken port logs and MCP keeps serving (`dashboard_state = "not bound: ..."`). Tests cover the refusal of `0.0.0.0` and a LAN address. |
| 5 | Request protection (D-08, D-19): Host on every request, page key cookie on every request, Origin plus token on every non-GET, five security headers, 8 KiB body cap | VERIFIED | `guard.py` read in full. Probe: no cookie 403; wrong token 403; foreign Origin 403; foreign Host 400; the key link sets an HttpOnly, SameSite=Strict cookie and redirects. Post-merge probes (#409, #416) covered cookie variants, FIFO and symlink key files, and mutants. |
| 6 | Only two write actions exist (toggle, restart); recovery is read-only; no delete or prune control; the Outbound gate is not a switch | VERIFIED | Only three POST forms (`/adapters` toggle and discard, `/restart`) in the dashboard package. No `subprocess`, `launchctl` call, `unlink`, `rmtree` or `os.remove` in `dashboard/*.py`. The CLI role list has no `adapters` role (D-05). Dashboard audit records go through `audit_write`, not `AuditMiddleware` or `usage_log`. |

**Score:** 4/4 roadmap criteria verified (6/6 including the D-decision truths). 0 behavior-unverified.

### Required Artifacts

| Artifact | Status | Details |
|----------|--------|---------|
| `macos_apps_mcp/tiers.py` (`adapters_off`, `adapter_enabled`) | VERIFIED | Wired into `server._tool`, `registry.adapter_status`, `doctor`. |
| `macos_apps_mcp/dashboard/` (guard, adapters, health, usage, writes, recovery, backups, html, grants, css, js) | VERIFIED | All wired through `build_app`; static files read at import. |
| `macos_apps_mcp/daemon.py` (`assert_loopback`, `bind_dashboard`, `make_dispatcher`, `restart`, `serve`) | VERIFIED | One uvicorn Server on `[uds, tcp]`; late dashboard import. |
| `macos_apps_mcp/deploy.py` (`adapters_off_file`, `dashboard_key`, `dashboard` CLI role) | VERIFIED | Home-pinned files; key file 0600, `O_NOFOLLOW`, regular-file-only reads (#416). |
| `pyproject.toml`, `packaging/Info.plist`, `uv.lock` | VERIFIED | `starlette>=0.48` declared; version 0.15.0 (PR #406). |

### Key Link Verification

| From | To | Status | Details |
|------|----|--------|---------|
| `server._tool` | `tiers.adapter_enabled` | WIRED | Probe shows photos tools absent from the FastMCP list. |
| `daemon.serve` | `dashboard.build_app` + dispatcher | WIRED | Lazy import after TCP bind; key from `deploy.dashboard_key(create=True)`. |
| `dashboard.adapters.toggle` | `adapters_off` file + `audit_write` | WIRED | Probe shows file and audit record. |
| `dashboard /restart` | `daemon.restart(server)` | WIRED | Lambda over the module `server`; device proof shows relaunch. |
| `doctor.diagnose` | `registry.adapter_status`, `daemon.dashboard_state` | WIRED | Fields at `doctor.py:422-460`; device proof read `dashboard` and `adapters_pending`. |

### Data-Flow Trace (Level 4)

| Page | Source | Real data | Status |
|------|--------|-----------|--------|
| `/` and `/write/..` | `audit.jsonl.1` + `audit.jsonl` read per request, `registry.dry_run_defaults()` | Yes (probe: the toggle record appears in the list) | FLOWING |
| `/health` | `doctor.diagnose(request=False)` in a worker thread, bounded wait | Yes (200, 12 KB) | FLOWING |
| `/usage` | `usage_report` | Yes | FLOWING |
| `/backups` | `state_dir()/backup/mail/*` disk tree joined to plan metadata | Yes | FLOWING |
| `/adapters` | `registry.adapter_status()` + file | Yes | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full unit suite | `uv run pytest -q` | 2460 passed, 102 deselected, exit 0 | PASS |
| Lint and format | `uv run ruff check .` / `ruff format --check .` | No issues; 128 files formatted | PASS |
| Photos absent when off | scratch-HOME subprocess, `MACOS_APPS_ADAPTERS_OFF=photos` | 64 tools, 0 photo tools | PASS |
| Dashboard end to end | in-process ASGI, scratch HOME, page key | 5 pages 200; toggle 303; bad token/Origin 403; bad Host 400; file and audit record written | PASS |

The ALLOW_SEND and READ_ONLY suite variants were not re-run here; 05-06 SUMMARY records them green (2454 and 2445 passed) before the cut.

### Probe Execution

SKIPPED: the phase declares no `probe-*.sh`. The release plan used `.daemon_probe.py`; its recorded result is `PROBE PASSED`, version 0.15.0, build token 7b26e22 resolving to the tagged sha (05-06 SUMMARY).

### Requirements Coverage

| Requirement | Source plans | Status | Evidence |
|-------------|--------------|--------|----------|
| PLAT-01 (per-app adapter on/off, absent tools, `doctor` reports the active set) | 05-01, 05-03, 05-06, 05-07 | SATISFIED | Truths 1 and 3. |
| PLAT-02 (localhost dashboard: grants/doctor, usage, audit trail, recoverable backups, adapter toggles; loopback-only; no SPA) | 05-02, 05-03, 05-04, 05-05, 05-06, 05-07, 05-08, 05-09 | SATISFIED | Truths 2, 3, 4, 5, 6. |

Both IDs appear in plan frontmatter and in REQUIREMENTS.md. No orphaned requirement: REQUIREMENTS.md maps only PLAT-01 and PLAT-02 to Phase 5.
Records item: REQUIREMENTS.md still shows both as `Pending` (lines 77-78 unchecked, lines 201-202 `Pending`). The phase-close step must tick them.

### Prohibitions (`verification: flagged`)

All plan prohibitions are covered by the device proof or by static and probe evidence: no meta-tool gating (probe: meta tools remain), no CLI `adapters` role (CLI role list), MCP not reachable over TCP, loopback-IP-literal-only bind, no filesystem path from the URL (`_STATIC` dict), no template engine or inline script/style, no Outbound switch, no `launchctl` from the job, no GET side effect, no middleware routing for dashboard writes, no delete/prune/open endpoints, no release push before owner approval (05-06 Task 2: owner answered "cut-and-pypi"). None is silently passed; none is a gap.

### Decision honoring

| Decision | Status | Note |
|----------|--------|------|
| D-01 to D-07, D-09 to D-18 | Honored | Seen in code or device evidence above. |
| D-08 `Referrer-Policy: no-referrer` | Deliberate deviation | `guard.py` sends `same-origin` because Chrome sends `Origin: null` on a same-origin form POST under `no-referrer` (RESEARCH C1). The owner's browser toggled and restarted without `Forbidden origin` (05-07). Not a gap. |
| D-19 page key, D-20 fail-closed unreadable file | Honored | `guard.py`, `deploy.py`, #410, #416. |
| D-13 "Open/Reveal are path + Copy" | Honored | No open endpoint. |

### Anti-Patterns Found

None. No `TBD`, `FIXME` or `XXX` markers in `macos_apps_mcp/dashboard/`, `tiers.py` or `registry.py`.

### Accepted Residuals (05-POSTMERGE-REVIEW.md, none blocking)

PM-03, PM-06, PM-07, PM-08, PM-10, PM-11, PM-16 (a `CancelledError` traceback in the daemon log at each restart), PM-23, PM-28, PM-29, PM-30 (page render reads the log on the shared event loop, +0.3-0.7 s MCP latency on a 25k-record log), PM-33, PM-38, PM-39, PM-41. PM-04 (no test for `deployment.adapters_off` while an adapter is off at registration) is an open test gap, advisory. PM-20 is resolved as documented: this Mac has no user TCC database, so the AppleEvents target ids in `grants.ADAPTER_GRANTS` are unconfirmed against live rows; confirmable only on the iMac (macOS 15). T-05-44 (the cookie reaches every 127.0.0.1 port) is accepted by the owner.

### Human Verification Required

None new. The owner's browser sitting and the scripted off/restore/on runs (05-07) and the release and install (05-06) cover criteria 1, 3 and 4 and the flagged prohibitions. Two items remain unconfirmed and are not must-haves: the browser was not named (Safari, Firefox and Chrome are not confirmed individually), and the "Copy" button was not separately reported.

### Deferred / Follow-up Items

- GitHub issue #427: the write detail and recovery pages show raw `imap://<account-UUID>/...` mailbox URLs instead of account names. A display bug, filed for an inserted phase; not a must-have of this phase.
- PM-04 test gap; the iMac confirmation of the grant target ids (PM-20).

### Gaps Summary

No gaps. The goal holds in the shipped code: an operator can turn Photos off with a file or the dashboard, restart, and find the Photos tools absent from the tool list and from `doctor`; the dashboard shows Health/grants, Usage, the audit trail and the recoverable backups behind loopback, Host, page-key, Origin and token checks. The unit suite (2460 tests) and lint pass on the released code, and the owner exercised the installed 0.15.0.

---

_Verified: 2026-10-22_
_Verifier: Claude (gsd-verifier)_
