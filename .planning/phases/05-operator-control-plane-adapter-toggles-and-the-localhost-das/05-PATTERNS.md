# Phase 5: Operator Control Plane - Pattern Map

**Mapped:** 2026-10-21
**Files analyzed:** 39 in the planned layout of 05-01..05-08 (18 new, 21 modified)
**Analogs found:** every modified file has an in-repo analog; of the new files, the CSS/JS ports map to the tracked sketches and the HTTP handlers have none (see "No Analog Found")

All analog paths below are git-tracked (verified with `git ls-files` for `tiers.py`, `daemon.py`, `audit.py`, `tests/test_daemon.py`, `tests/test_audit.py`, and `.planning/sketches/**`). The skill folder `.claude/skills/sketch-findings-macos-apps-mcp/` is NOT tracked (git-ignored). Cite the tracked `.planning/sketches/*` instead; the skill references are a convenience copy only.

Apply 05-RESEARCH.md corrections C1-C8 on top of every excerpt below. Where an excerpt and a correction disagree, the correction wins (notably: `Referrer-Policy: same-origin`, restart watchdog `os._exit`, UDS test `server[1] is None` with fail-closed default).

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match |
|---|---|---|---|---|
| `macos_apps_mcp/deploy.py` (+`_ADAPTERS_OFF_FILE`, `adapters_off_file()` in 05-01; `write_adapters_off()` in 05-03) | config | file-I/O | same file: `_ALLOW_SEND_FILE` / `allow_send_file()` (:295-332), the `allow_send` write (:340-345) | exact |
| `macos_apps_mcp/tiers.py` (+`adapters_off()`, `adapter_enabled()`, 05-01) | utility (gate) | request-response | same file: `allow_send()` (:38-69) | exact |
| `macos_apps_mcp/server.py` `_tool` (:153-165, 05-01) | registration | transform | same block | exact |
| `macos_apps_mcp/registry.py` (+`adapter_status()`, edit `outbound_status()`, 05-01) | model/ledger | transform | `outbound_status()` (:177-196) | exact |
| `macos_apps_mcp/doctor.py` (adapter keys and `adapter_off` surfaces in 05-01; `deployment.dashboard` in 05-05) | service | request-response | same file: `outbound_pending` block (:413-419), `_automation_surfaces` (:164-188) | exact |
| `macos_apps_mcp/eventkit.py` (skip OFF entities, 05-01) | service | event-driven | same file `request_access_each` (:107-124) | exact |
| `macos_apps_mcp/audit.py` (+`read_all()`, `_audit_receipt()`, 05-04) | utility | file-I/O | `audit_read` (:84-118), `_audit_after` | exact |
| `macos_apps_mcp/daemon.py` (`DASHBOARD_PORT`, `dashboard_state`, `assert_loopback`, `bind_dashboard`, `make_dispatcher`, `serve()` in 05-02; `restart()` in 05-03) | service | streaming / request-response | `bind_socket` (:54-80), `serve()` (:202-224) | role-match |
| `macos_apps_mcp/dashboard/` subpackage (NEW): `__init__.py`, `guard.py`, `html.py`, `usage.py` (05-02); `adapters.py`, `grants.py` (05-03); `writes.py`, `recovery.py` (05-04); `health.py`, `backups.py` (05-05) | controller + view | request-response | none in repo for HTTP handlers; helper style from `audit.py`; HTML from sketches | partial |
| `macos_apps_mcp/dashboard/dashboard.css` (NEW, 05-02; page blocks appended by 05-03..05-05) | config (style) | n/a | `.planning/sketches/themes/default.css` + `_shared/base.css` + `_shared/shell.css` + per-sketch `<style>` | exact (port) |
| `macos_apps_mcp/dashboard/dashboard.js` (NEW, 05-02) | utility | event-driven | `copy()` helper in `.planning/sketches/004-toggles-and-health/index.html:~48` | role-match |
| `pyproject.toml`, `packaging/Info.plist`, `uv.lock` (05-08) | config | n/a | `docs/RELEASING.md` two-file bump | exact |
| `scripts/build_app.sh`, `tests/test_packaging.py:164` (bundle smoke, 05-02) | config / test | n/a | same lines | exact |
| `tests/conftest.py` (`adapters_off` file patch, 05-01) | test fixture | n/a | `_isolated_state` (:30-37) | exact |
| `tests/test_registry.py` (ADAPTERS_OFF subprocess cases, 05-01) | test | request-response | `_subprocess_registry_snapshot` (:155-205) | exact |
| `tests/test_adapters_off.py` (NEW, 05-01: gate grammar, doctor keys, `adapter_off` surfaces, EventKit skip) | test | request-response | `tests/test_registry.py`, `tests/test_doctor_deploy.py:136-171`, `tests/test_doctor.py:46-155`, `tests/test_eventkit.py:285-313` | role-match |
| `tests/test_doctor_deploy.py` (extend in 05-05: `deployment.dashboard`) | test | request-response | `test_deployment_section_outbound_pending_*` (:136-171) | exact |
| `tests/test_daemon.py` (module autouse `DASHBOARD_PORT = 0`, real-bind and taken-port tests, 05-02) | test | event-driven | `_no_role_leak`, `test_serve_two_concurrent_sessions` (:102-123) | exact |
| `tests/test_daemon_dispatch.py` (NEW, 05-02; restart tests in 05-03) | test | event-driven | `tests/test_daemon.py:102-123` | role-match |
| `tests/test_dashboard_guard.py` (05-02), `tests/test_dashboard_adapters.py` (05-03), `tests/test_dashboard_writes.py` (05-04), `tests/test_dashboard_system.py` (05-05) (NEW) | test | request-response | `tests/test_daemon.py` (`asyncio.run` inside sync tests) + `httpx.ASGITransport` | partial |
| `tests/test_audit.py` (extend for `read_all` and the middleware `receipt` key, 05-04) | test | file-I/O | existing audit tests | exact |
| `docs/DAEMON.md`, `README.md`, `CHANGELOG.md` | docs | n/a | DAEMON.md section 5 "Outbound (send) mode" | role-match |

## Pattern Assignments

### `deploy.py` (config, file-I/O) - analog: same file, `allow_send` twin

**Constant + reader** (`deploy.py:295, 327-332`): copy verbatim, rename.
```python
_ALLOW_SEND_FILE = Path.home() / ".local/state/macos-apps-mcp/allow_send"   # comment above it (:289-294) explains: home-pinned, never state_dir(), tests patch the constant

def allow_send_file() -> str:
    """The persisted outbound opt-in (``""`` when absent) - see tiers.allow_send."""
    try:
        return _ALLOW_SEND_FILE.read_text()
    except OSError:
        return ""
```
New: `_ADAPTERS_OFF_FILE = Path.home() / ".local/state/macos-apps-mcp/adapters_off"` and `adapters_off_file()` with the same body. Keep the home-pinned comment (a `state_dir()` path would make the gate fail open under an exported `XDG_STATE_HOME`).

**Write pattern for the dashboard toggle** (`deploy.py:340-345`): `parent.mkdir(mode=0o700, parents=True, exist_ok=True)` then write. Deviation required by research: write a temp file in the same dir and `os.replace` (a truncated file reads as "all on").

**Kickstart text** to name in `doctor`/`docs/DAEMON.md` (`deploy.py:347-350`): `["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{_BUNDLE_ID}"]`. The dashboard itself never runs it (D-16).

**Daemon role** (`deploy.py:304-324`): reuse `is_daemon_role()` unchanged (argv first; env var `MACOS_APPS_MCP_ROLE` honoured for tests).

### `tiers.py` (utility, request-response) - analog: `allow_send` (`tiers.py:38-69`)

**Core gate pattern** (`tiers.py:61-69`): env first, file only in daemon role.
```python
val = os.environ.get("MACOS_APPS_ALLOW_SEND", "")
if not val and deploy.is_daemon_role():
    val = deploy.allow_send_file()
val = val.strip().lower()
...
return adapter in {p.strip() for p in val.split(",") if p.strip()}
```
New functions per RESEARCH Pattern 1: `adapters_off() -> set[str]` (same env-then-file shape, `MACOS_APPS_ADAPTERS_OFF`), `adapter_enabled(name) -> bool` = `name not in adapters_off()`. Re-read on every call. Give each a docstring in the module's style (long, issue-referencing, states "read at registration time"). `tiers` already imports `deploy`; keep it so.

### `server.py` `_tool` (registration) - analog: lines 153-165

**Existing block to edit:**
```python
if tier == "send":
    ...
    registered = tiers.allow_send(adapter)
elif tier == "read":
    registered = True
else:
    registered = not tiers.read_only()
```
Change to `on = adapter is None or tiers.adapter_enabled(adapter)` and AND it into all three branches (send: `on and tiers.allow_send(adapter)`). Leave the `f.__doc__` mail-autosave composition before the gate (it must stay composed whether or not the tool registers). Adapter instances at `server.py:45-55` are untouched.

### `registry.py` (ledger, transform) - analog: `outbound_status` (`registry.py:177-196`)

**Pattern to mirror** (a view over `TOOLS`, not a second ledger):
```python
send_adapters = {r.adapter for r in TOOLS.values() if r.tier == "send"}
registered = {r.adapter for r in TOOLS.values() if r.tier == "send" and r.registered}
return {"registered": sorted(registered),
        "configured": sorted(a for a in send_adapters if tiers.allow_send(a))}
```
`adapter_status()`: `registered` = sorted adapters with a registered record; `configured` = sorted `{r.adapter for r in TOOLS.values() if r.adapter}` minus `tiers.adapters_off()`. Edit `outbound_status()["configured"]` to also require `tiers.adapter_enabled(a)`. Adapter names for the dashboard come from `registry.TOOLS`, never `await mcp.list_tools()` (import-layer test).

### `doctor.py` - analog: same file

**OFF adapter surface**: mirror the `request=False` branch in `_automation_surfaces` (`doctor.py:164-188`):
```python
out.append(_surface(name, "automation", None, "unprobed", "..."))
out[-1]["process"] = _process_line(app)
```
Use `_surface(name, "automation", None, "adapter_off")` BEFORE any probe or `_process_line` call (no Apple Event; `_process_line` is ps-only but skip it too). `_eventkit_surfaces` (:127-148) iterates `_EK_ENTITIES` as `(name, entity, pane)`; skip the OFF names and do not call `_try_request_access` for them. `_shortcuts_surface` name `shortcuts_cli` maps to adapter `shortcuts`.

**Counts** (`doctor.py:345-346`): `needs = [... ok is False]`, `unknown = [... ok is None]`. Add `and s["status"] != "adapter_off"` to `unknown`, and compute the "all N OK" N from probed surfaces only (Pitfall 5).

**Pending delta** (`doctor.py:413-419`) - copy the shape for `adapters_pending`:
```python
if ob["configured"] != ob["registered"]:
    deployment["outbound_pending"] = ob["configured"]
    deployment["outbound_note"] += (
        " Outbound config changed since this process launched (configured: "
        + (", ".join(ob["configured"]) or "none")
        + ") - restart the daemon to apply it."
    )
```
Terse by design (token budget `< 7000`, 6141 today; print length before/after). Planned form (RESEARCH Open Question 4): `deployment["dashboard"]` comes from `daemon.dashboard_state`, a `daemon.py` module global set by `daemon.serve()` (05-02 cannot edit `deploy.py`, which 05-01 owns in wave 1). `doctor` imports `daemon` inside `diagnose()` only in the daemon role, where the module is already loaded; the stdio server never imports it (05-05 Task 1).

### `eventkit.py` - analog: `request_access_each` (:107-124)

```python
_ENTITIES = (EK.EKEntityTypeEvent, EK.EKEntityTypeReminder)
def request_access_each() -> None:
    s = store()
    for entity in _ENTITIES:
        try:
            _request_one(s, entity)
        except AccessDenied as e:
            log.warning("EventKit surface not granted: %s", e)
```
Pair each entity with its adapter name (`calendar`, `reminders`), skip when `not tiers.adapter_enabled(name)`. Keep the per-entity try/except (one denial never blocks the other). `bootstrap()` stays `run_native(request_access_each)`; `test_doctor.py:68` pins that route.

### `audit.py` (+`read_all`) - analog: `audit_read` (`audit.py:84-118`)

Reuse: `_audit_path()` (:57), per-line `json.loads` with `except ValueError: continue`, `read_text(encoding="utf-8")`. Difference: no limit, oldest to newest, both `audit.jsonl.1` then `audit.jsonl`. An unreadable file must surface explicitly (CLAUDE.md: never an empty list masquerading as "no writes") - `audit_read` returns `[{"error": f"audit log unreadable: {e}"}]`; `read_all` should expose the same state so the page renders "log unreadable". RESEARCH Pattern 6 snippet silently `continue`s on `OSError`; amend: continue only for a missing file, report other `OSError`.

**Dashboard records** go through `audit_write` only (it never raises, `audit.py:61-72`), never `AuditMiddleware`, never `usage_log`. Record literal in RESEARCH "Dashboard record".

### `daemon.py` `serve()` (service) - analog: `bind_socket` + `serve`

**Owned-bind pattern** (`daemon.py:54-80`): `socket.socket(...)`, `bind`, on `OSError` close and re-raise, `listen()`. The TCP twin (`bind_dashboard`, RESEARCH Code Examples) adds the `ipaddress.ip_address(host).is_loopback` guard and `SO_REUSEADDR`.

**Existing serve** (`daemon.py:202-224`) to extend:
```python
from .server import mcp  # late: importing server pulls the adapter tree
path = socket_path()
s = bind_socket(path)
try:
    config = uvicorn.Config(mcp.http_app(), fd=s.fileno(), log_level="warning", ws="none")
    uvicorn.Server(config).run()
finally:
    s.close()
    path.unlink(missing_ok=True)
```
Becomes: bind UDS, then `try: tcp = bind_dashboard("127.0.0.1", DASHBOARD_PORT) except OSError as e: log.warning(...); dashboard_state = f"not bound: {e}"` (a `daemon.py` module global); `from . import dashboard` lazily; `Config(make_dispatcher(mcp.http_app(), dash_app), log_level="warning", ws="none", proxy_headers=False)` (no `fd=`); `server = uvicorn.Server(config)`; `server.run(sockets=[s] + ([tcp] if tcp else []))`; close both in `finally`. Dispatcher, restart closure: RESEARCH Patterns 2 and 5 (apply C2, C4). Read `DASHBOARD_PORT` at call time (C6). Logging via `log = logging.getLogger(__name__)`.

### `dashboard/` subpackage (NEW; controller/view, request-response) - no handler analog

Planned layout (D-10 lets the planner split; the pages of this phase pass the ~800-line mark): `__init__.py` (`build_app`, routes, the static dict), `guard.py` (Guard, headers), `html.py` (`Safe`, `esc`, `h`, `page`, sidebar), one module per page group (`usage.py`, `adapters.py` + `grants.py`, `writes.py` + `recovery.py`, `health.py`, `backups.py`), and the two assets beside them.

Follow repo conventions: `from __future__ import annotations`, relative imports (`from . import audit, deploy, doctor, registry, tiers`), module logger, typed errors not swallowed, docstrings that explain WHY and cite issues. Do not import `server` (layer test). Use only `mail_recover.backup_usage`, `find_receipt`, `OPS` from adapters.

Patterns to copy from RESEARCH (all probed in `05-proto/`): Guard (Pattern 3, `05-proto/guard_proto.py`), `esc`/`h`/`Safe` (Pattern 4), `parse_qs` body with 8 KiB cap (C8), single-flight lock around `diagnose()` (C7), fixed static dict (no `StaticFiles`), receipt regex `^\d{8}-\d{6}-\d{6}-\d{3}-(move|trash|dedupe)$` before any FS access (Pattern 7), `/write/<ts>/<n>` (C5).

**Backups data**: `backup_usage()` (`mail_recover.py:661-688`) is the walk to copy (read-only, never raises, `oldest` from the receipt id). List `state_dir() / "backup" / "mail"` directly; never `_backup_dir()` (it runs `mkdir`), and note `audit.state_dir()` itself `mkdir`s `~/.local/state/macos-apps-mcp`, which is fine.

**Data sources**: write list = `audit.read_all()` + `registry.dry_run_defaults()`; usage = `audit.usage_report`/`usage_read`; health = `doctor.diagnose(request=False)` in `run_in_threadpool`; adapters = `registry.adapter_status()`.

### `dashboard/dashboard.css` (NEW) - analog: tracked sketches

Concatenate in this order: `.planning/sketches/themes/default.css` (95 lines; tokens `--color-*`, `--font-*`, `--text-*`, `--space-*`, `--radius-*`, dark theme via `:root[data-theme="dark"]`), `_shared/base.css` (159 lines; `.chip`, `.btn`, `.switch`, `.group`, `.row`, `.sidebar`, `.nav-item`, `.appico`, `.diff`, `.statusline`, `.mono/.muted/.faint/.sr`), `_shared/shell.css` (46 lines; `.b-shell` 3-column grid `200px minmax(280px,380px) 1fr`, `.b-list`, `.b-detail`, `.b-page`, `.banner`, `.section-label`, `.kv`, `.actions`, `.usage-bar`). Then per-page blocks: 004 `<style>` lines 10-31 (`.restart-bar`, `.chip.pending`, `.state`, `.spin`, `.cmd`, `.row.expand`, `.row.locked .title::after`, `.restarting`), 002 `<style>` lines 10-52 (word diff, args, raw lines), 003 `<style>` lines 10-36 (backup meter, undo prompt), 001 `<style>` lines 9-104.

Deviations forced by the CSP (`default-src 'self'`): no `style="..."` attributes - turn each inline style used in the sketch markup into a class; `.usage-bar` width and the backup meter become `<meter>`. Drop the sketch-only chrome (`.variant`, `.variant-tab`, sketch switcher). The sketch markup is built in each `index.html`'s script template strings (004 lines 43-154, 003/002/001 likewise); port those strings into server-side `h(...)` templates, replacing `onclick` with `data-copy` attributes handled by `dashboard.js`, and `data-sw` checkboxes with `<form method="post">` switches.

### `dashboard/dashboard.js` (NEW) - analog: `copy()` in `.planning/sketches/004-toggles-and-health/index.html`

```js
const copy = (v) => `<button class="btn" onclick="navigator.clipboard?.writeText('${v}');toast('Copied')">Copy</button>`;
```
Replace with one delegated `click` listener on `[data-copy]` using `navigator.clipboard.writeText(el.dataset.copy)`; fallback `document.execCommand("copy")` (A2). No inline handlers (CSP). Copy buttons only.

### `pyproject.toml` / `Info.plist` / `uv.lock` - analog: `docs/RELEASING.md` two-file bump

Add `"starlette>=0.48",  # imported directly (dashboard/)` beside `httpx` (see the "imported directly" comment style on `anyio`, `pyproject.toml` ~line 32). Version `0.15.0` in `pyproject.toml` and `packaging/Info.plist` `CFBundleShortVersionString`. Run `uv lock --offline`; expect exactly three `uv.lock` hunks (C3), `revision` untouched. Flag: starlette `[SUS]` -> `checkpoint:human-verify` before the edit. Planned form (05-08, its own wave-1 plan beside 05-02): no checkpoint, because starlette 1.6.0 is already locked and installed as a hard dependency of `mcp` and `fastmcp`; the edit declares it with `uv lock --offline`, downloads nothing, and 05-08 Task 1 asserts the starlette entry is unchanged; the evidence goes in the SUMMARY and the PR body. 05-02 merges only after the declaration is on origin/develop.

### `tests/conftest.py` - analog: `_isolated_state` (:30-37)

```python
mp.setattr(deploy, "_ALLOW_SEND_FILE", state_home / "allow_send")
```
Add `mp.setattr(deploy, "_ADAPTERS_OFF_FILE", state_home / "adapters_off")` on the next line (05-01). The `DASHBOARD_PORT = 0` isolation (C6) is planned as a module autouse fixture in `tests/test_daemon.py` (05-02), the only module that runs the real `serve()` (`test_daemon.py:102-123`); 05-02 cannot edit `conftest.py`, which 05-01 owns in wave 1.

### `tests/test_registry.py` + `tests/test_adapters_off.py` - analog: `_subprocess_registry_snapshot` (:155-205)

Harness runs `python -c` with `env = {"PATH": "/usr/bin:/bin", "HOME": os.environ["HOME"], **env_extra}` and returns `tools`, `registered`, `all_recorded`. New case beside the READ_ONLY one (:196-205):
```python
got_off = _subprocess_registry_snapshot({"MACOS_APPS_ADAPTERS_OFF": "photos"})
assert got_off["tools"] == got_off["registered"]
assert not any(t for t in got_off["tools"] if "photo" in t)   # use reg.by_adapter("photos") names
assert {the four photos tools} <= set(got_off["all_recorded"])
```
File-path case: pass `HOME=<tmp>` (written file at `<tmp>/.local/state/macos-apps-mcp/adapters_off`) and `MACOS_APPS_MCP_ROLE=daemon`; stdio case without the role var must ignore the file. Outbound interplay: `MACOS_APPS_ALLOW_SEND=mail` + `MACOS_APPS_ADAPTERS_OFF=mail` -> no send tool listed. Reuse `_live()` (:150-152) for in-process listing.

### `tests/test_doctor_deploy.py` extensions - analog: :136-171

```python
@_gate_off_only
def test_deployment_section_outbound_pending_when_configured_not_registered(monkeypatch):
    monkeypatch.setenv("MACOS_APPS_ALLOW_SEND", "mail")
    monkeypatch.delenv("MACOS_APPS_READ_ONLY", raising=False)
    _mock_grants(monkeypatch, None)
    monkeypatch.setattr("macos_apps_mcp.deploy.agent_status",
                        lambda: (_ for _ in ()).throw(Exception("no bundle")))
    d = doctor.diagnose()["deployment"]
    assert d["outbound_pending"] == ["mail"]
    assert "restart" in d["outbound_note"].lower()
```
Twin for `adapters_pending` using `monkeypatch.setenv("MACOS_APPS_ADAPTERS_OFF", "photos")` (registration already happened with photos on, so configured != registered). Reuse `_mock_grants` and the `agent_status` stub verbatim; `_gate_off_only` skips when a gate env var is set in the run. Planned form: 05-01 puts this twin, and its `adapter_off` surface and EventKit-skip tests, in `tests/test_adapters_off.py`, importing `_gate_off_only` and `_mock_grants` from `tests.test_doctor_deploy` (`tests` is a package); 05-05 extends `tests/test_doctor_deploy.py` itself with the `deployment.dashboard` tests.

### `tests/test_daemon_dispatch.py`, `test_dashboard_*.py` - analogs: `tests/test_daemon.py`

`asyncio.run(go())` inside sync tests (repo has no pytest-asyncio); `sockdir` fixture and `monkeypatch.setenv("MACOS_APPS_MCP_SOCKET", str(p))` (`test_daemon.py:102-123`). HTTP tests use `httpx.ASGITransport(app=...)`, not `TestClient`. Dispatcher tests feed hand-built scope dicts: lifespan, `server=(path, None)` -> MCP stub, `server=("127.0.0.1", 47632)` -> dashboard stub, `server=None` -> dashboard (C4), websocket ignored. Real-bind test extends `test_serve_two_concurrent_sessions` and reads the actual TCP port from the socket (port 0).

## Shared Patterns

### Gate read at process start, tool kept with `registered=False`
**Source:** `macos_apps_mcp/tiers.py:38-69`, `server.py:153-165`. **Apply to:** all PLAT-01 files. Absent tools are never registered-and-erroring.

### Home-pinned state file, tests patch the constant
**Source:** `deploy.py:289-332`, `tests/conftest.py:30-37`. **Apply to:** `adapters_off`; never reach it through `state_dir()` or `XDG_STATE_HOME`.

### Registered vs configured pending report
**Source:** `registry.py:177-196`, `doctor.py:413-419`, `tests/test_doctor_deploy.py:136-171`. **Apply to:** `adapter_status`, `adapters_pending`, the dashboard pending chip and restart bar (read `adapter_status()` per request).

### Typed errors, explicit failure states
**Source:** `audit.py:96-102` (unreadable log yields an explicit error entry). **Apply to:** every dashboard read: show "log unreadable" or "worker busy", never an empty list.

### Native access only through the worker
**Source:** CLAUDE.md Architecture; `runtime.run_native`. **Apply to:** Health (`diagnose(request=False)` in `run_in_threadpool`, single-flight). No EventKit off the worker; no TCC prompt or Apple Event for an OFF adapter.

### Module conventions
`from __future__ import annotations`; relative imports (`from . import x`); `log = logging.getLogger(__name__)`; ruff `E,F,I,UP,B,SIM`, line 88; no `print`. Mail modules use qualified `runtime.` imports (not relevant here, dashboard calls no osascript).

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| `macos_apps_mcp/dashboard/` request handlers (the page modules), Guard (`guard.py`), `esc`/`h` (`html.py`) | controller/view | request-response | The repo has no HTTP handler or HTML renderer. Use RESEARCH Patterns 2-5 and the probes in `.planning/phases/05-operator-control-plane-adapter-toggles-and-the-localhost-das/05-proto/` (`dispatch_server.py`, `guard_proto.py`, `origin_probe.py`, `dispatch_client.py`) |
| `tests/test_dashboard_guard.py` HTTP harness | test | request-response | No ASGI test exists; build on `httpx.ASGITransport` per D-17 and `05-proto/guard_proto.py` cases |

## Metadata

**Analog search scope:** `macos_apps_mcp/{tiers,deploy,server,registry,doctor,eventkit,audit,daemon}.py`, `adapters/mail_recover.py`, `tests/{conftest,test_registry,test_daemon,test_doctor_deploy}.py`, `.planning/sketches/**`
**Files scanned:** ~20
**Pattern extraction date:** 2026-10-21
