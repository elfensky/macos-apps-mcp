# Phase 5: Operator Control Plane — Adapter Toggles and the Localhost Dashboard - Research

**Researched:** 2026-10-21
**Domain:** Python daemon (FastMCP + uvicorn 0.52.4 + Starlette 1.6.0), launchd KeepAlive, server-rendered localhost admin UI
**Confidence:** HIGH (every load-bearing claim below was read in this session or probed on this Mac; the few `[ASSUMED]` items are listed in the Assumptions Log)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Adapter toggle setting and gate (PLAT-01, criterion 1)
- **D-01:** The setting is a **deny-list**, the exact twin of `allow_send`. A home-pinned plain-text
  file `~/.local/state/macos-apps-mcp/adapters_off` (beside `allow_send`, same comma grammar) lists
  the adapters that are OFF. `MACOS_APPS_ADAPTERS_OFF` wins when set and non-empty. The file is
  read only in the daemon role (`deploy.is_daemon_role()`, argv). An absent or empty file means
  every adapter is on, so every existing install is unchanged and a new adapter is on by default.
  Valid names are the registry's adapter names (`ToolRecord.adapter`: reminders, calendar,
  contacts, mail, notes, safari, music, photos, messages, shortcuts). An unknown name is ignored
  and named in `doctor` (`adapters_unknown`); the dashboard never writes one.
- **D-02:** One new pure predicate `tiers.adapter_enabled(name)`. `server._tool` ANDs it into
  `registered` for every record that names an adapter, in every tier, the send tier included
  (`server.py:161-165`). Meta tools (`adapter=None`: ping, now, doctor, audit, usage) are never
  gated. A gated-off tool keeps its `registry.TOOLS` record with `registered=False`, as today. The
  adapter instances at `server.py:45-55` stay at module scope: no constructor touches native, so
  an OFF adapter is still instantiated and never called. `registry.audit_verbs()`,
  `snapshot_sources()` and `write_tools()` already filter on `registered`, so the audit
  middleware and `usage` follow with no edit.
- **D-03:** `registry.adapter_status()` mirrors `outbound_status()` (`registry.py:177-196`):
  `registered` = adapters with at least one registered record; `configured` = adapters enabled by
  the setting, read again on each call. `outbound_status()["configured"]` must also AND
  `adapter_enabled`, or "allow_send=mail and Mail off" reports an `outbound_pending` that no
  restart clears. `doctor.diagnose()` adds to `deployment`: `adapters` (the active list),
  `adapters_off`, and `adapters_pending` plus a "restart the daemon to apply it" directive when
  configured differs from registered, the same shape as `outbound_pending` (`doctor.py:413-419`).
  The report stays under the existing token budget (`tests/test_doctor.py:426`).
- **D-04:** `doctor` makes **no TCC prompt and no Apple Event for an OFF adapter**. Its Automation
  surface stays in the report with `status: "adapter_off"` and `ok: None`, and is left out of the
  `needs` and `unknown` counts; `doctor(request=True)` skips its probe. The EventKit request and
  the stdio `bootstrap()` request cover only enabled entities (`eventkit.py:107-124`). The app to
  adapter map is `app.lower()` for `_AUTOMATION_APPS`, the entity name for calendar and
  reminders, and `shortcuts_cli → shortcuts`. The Full Disk Access and Mail index surfaces stay
  as they are (shared by several adapters).
- **D-05:** **No `macos-apps-mcp adapters` CLI twin in this phase.** The dashboard and the file are
  the two interfaces. The fallback when the dashboard port cannot bind is to edit the file and
  run `launchctl kickstart -k gui/$(id -u)/ren.lav.macos-apps-mcp`; the `doctor` adapters note
  and `docs/DAEMON.md` name the file path and that command.

#### Dashboard transport and security (PLAT-02, criteria 2 and 4)
- **D-06:** **One uvicorn `Server`, `run(sockets=[uds, tcp])`, behind a small ASGI dispatcher.**
  Lifespan scopes and UDS scopes go to `mcp.http_app()`; TCP scopes go to the dashboard Starlette
  app; anything else gets 404. The UDS discriminator is `scope["client"] is None` (equivalently
  `scope["server"][1] is None`): on uvicorn 0.52.4 a UDS scope has `server == (path, None)`, not
  `None` (`uvicorn/protocols/utils.py:36-37`, verified by probe). **`/mcp` is never reachable over
  TCP**, so no website can POST to the MCP endpoint. Two uvicorn Servers on one loop are not used:
  each `capture_signals` overwrites the other's SIGTERM handler (`uvicorn/server.py:330`).
  `mcp.http_app()` keeps its one lifespan (one startup, one shutdown, verified).
- **D-07:** The daemon binds the TCP socket itself, after the UDS single-instance bind: host
  `127.0.0.1`, **fixed port 47632** (the sketch's number; outside macOS's ephemeral range), through
  a guard function that raises on any host whose `ipaddress.ip_address(host).is_loopback` is
  false. The daemon passes only the constant; the guard exists so criterion 4 has a testable
  refusal path. A failed port bind (EADDRINUSE) is logged and **MCP keeps serving**; the dashboard
  is then absent and `doctor` reports `deployment.dashboard` as `"not bound: <reason>"` instead
  of `"http://127.0.0.1:47632"`. The dashboard exists only in the daemon role: `daemon.serve()`
  imports `dashboard` lazily; the stdio server never imports it.
- **D-08:** **Layered request checks.** Every request: `Host` must be `127.0.0.1` or `localhost`
  (with or without the port), else 400 (Starlette `TrustedHostMiddleware` strips the port and
  answers 400; a hand-rolled check that includes the port is equally acceptable). Every POST:
  a per-session token (`secrets.token_urlsafe` at daemon start, a hidden form field, compared
  with `hmac.compare_digest`) AND an `Origin` equal to `http://127.0.0.1:47632` or
  `http://localhost:47632`; when `Origin` is absent, `Sec-Fetch-Site: same-origin` is required;
  anything else is 403. No GET has a side effect. Every response carries
  `Content-Security-Policy: default-src 'self'; frame-ancestors 'none'; form-action 'self'`,
  `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`.
  `frame-ancestors 'none'` closes a gap the sketch rules do not name: a framed dashboard could be
  click-jacked into a toggle that carries its own valid Origin and token. No inline styles or
  scripts: the sketches' `style="…"` attributes become classes; the backup meter is a `<meter>`.
  The clipboard API works on `http://127.0.0.1` (loopback is a secure context).

#### Rendering and data sources (criterion 2)
- **D-09:** **Starlette routes and hand-rolled HTML through one escape-by-default helper; no
  jinja2.** Every interpolated value is escaped unless explicitly marked safe, so sketch rule 8
  holds even when one call site is missed; the CSP is the backstop. jinja2 is in neither
  `uv.lock` nor the venv. `starlette` becomes a listed dependency in `pyproject.toml`
  ("imported directly", the repo's rule); the PR that edits `pyproject.toml` must bump the
  version (`.github/workflows/version.yml` fails any pyproject edit without one), so that PR
  carries the **0.15.0 bump** in `pyproject.toml`, `packaging/Info.plist` and the root version
  line of `uv.lock` (RELEASING.md's two-file bump; the lock's revision field is left alone). The
  release at phase close (D-18) reuses that version.
- **D-10:** Layout: one module `macos_apps_mcp/dashboard.py` plus `dashboard.css` and a small
  `dashboard.js` (Copy buttons only), shipped as package files (hatchling includes non-`.py` files
  under `packages = ["macos_apps_mcp"]`, verified with a wheel build) and served by one static
  route. Split into a `dashboard/` subpackage only when the module passes about 800 lines; the
  planner decides. The CSS is ported from `.planning/sketches/themes/default.css` (tokens),
  `.planning/sketches/_shared/base.css` (components) and `.planning/sketches/_shared/shell.css`
  (frame), 14 KB together, plus the per-page CSS in each sketch's `<style>`.
- **D-11:** Routes: `/` (the Console-style list of writes beside the detail of one write, with
  GET params `q`, `previews`, `filter=all|receipt|outbound|app:<adapter>`), `/write/<ts>`,
  `/health`, `/adapters` (GET; POST toggle; POST discard), `/restart` (POST), `/usage`,
  `/backups`, `/backups/<receipt>`, `/static/<file>`. Every page works without JS: nav items and
  rows are links, the filter is a GET form, each switch is a POST form. JS exists only for Copy.
  Page texts, chips (`adds` / `changes` / `sends` / `preview`), day headers, the preview banner,
  the word diff and the resolved `dry_run` row follow the sketch references word for word.
- **D-12:** **The write list reads `audit.jsonl.1` and `audit.jsonl` on every request** through a
  new reader in `audit.py` (all records, oldest to newest, no cache; both files parse in about
  40 ms here). `audit_read` and the `audit` tool stay unchanged. A record with no `dry_run`
  (390 legacy records on this Mac) gets it resolved from the tool's default via
  `registry.dry_run_defaults()`; a record with no `caller` shows nothing. Batches: plan and done
  records group by `receipt`; each target's outcome comes from `done["results"][id]`, never from
  the plan target's `status` (always `"planned"`); the middleware record is linked by adjacency
  (the first record of the same tool after the done record; held 369 of 369 here). A
  `dedupe-mail` CLI batch (plan and done, no middleware record) shows as a batch row.
- **D-13:** **Recovery is read-only.** The batch detail shows each message's backup (file name,
  size, fidelity chip, dimmed when its outcome is not `ok`), the receipt's `backup_dir` as text
  with Copy, and the prompt `Undo mail receipt <id>` with Copy, plus the collapsed exact
  `mail_undo(...)` call. `Open` and `Reveal` are **path + Copy, no endpoint**. The undo prompt is
  offered only when `find_receipt` resolves the plan; otherwise the page says the plan has
  rotated out of the log and the files remain. There is **no live "watching audit.jsonl"
  update**; a Reload link instead. The Backups page lists receipts from the disk tree
  (`state_dir()/backup/mail/*`) joined to plan metadata where found; it never calls
  `_backup_dir()` (it runs `mkdir`). `backup_usage()` runs only on the Backups and Health pages,
  never in the sidebar. No delete, prune, clean-up or dedupe control anywhere (#163, sketch
  rule 10). This supersedes the #126 comment of 2026-08-04 and the `docs/landscape.md` floating
  note that asked for a clean-up button and a dedupe runner.
- **D-14:** Health runs `diagnose(request=False)` and Usage runs `usage_report(...)` in Starlette's
  thread pool (`run_in_threadpool`), never on the event loop and never with EventKit off the
  `run_native` worker. Health bounds its wait (about 10 s) and, when the worker is busy with an
  in-flight native call, renders the EventKit rows as "worker busy, a native call is in flight".
  A danger banner appears only for an **active** adapter whose grant is denied. `Open Settings`
  is a plain `x-apple.systempreferences:…` link (the browser asks to open System Settings); no
  endpoint. The Outbound row is locked and shows `macos-apps-mcp allow-send <adapters>` with Copy.

#### Writes, restart, tests and the device proof (criterion 3)
- **D-15:** A toggle POST rewrites `adapters_off` (parent directory 0700, as `deploy.allow_send`
  does) and appends one record through `audit_write`:
  `{ts, tool: "dashboard", op: "toggle", args: {adapter, on}, dry_run: false, caller: "dashboard",
  target_id: <adapter>, before: null, after: null}`. Discard is the same write back to the
  running set. Restart appends `op: "restart"`. These records go around `AuditMiddleware` and
  never call `usage_log`. `audit_read`, the `audit` tool and `find_receipt` already accept
  records without `receipt`; the dashboard list shows them like any other write.
- **D-16:** **Restart = the daemon exits itself; launchd relaunches it.** After the response is
  flushed (a Starlette `BackgroundTask` or `loop.call_later`), the handler sets uvicorn's
  `should_exit = True` and `force_exit = True` on the module-level `Server` in `daemon.py`;
  uvicorn then skips the wait for open connections and tasks (`uvicorn/server.py:301-317`) and
  exits 0; `KeepAlive` relaunches at once when the daemon ran longer than `ThrottleInterval`
  (10 s). No `launchctl` is run from inside the job. The response page shows the sketch's
  "Restarting the daemon…" text and meta-refreshes to `/adapters` after about 10 s. The restart
  bar names both consequences: open MCP connections drop, and an in-flight Mail batch is killed
  mid-act (its plan record and its backups survive; launchd's exit timeout is 5 s here). A daemon
  run by hand, outside launchd, simply exits; that is accepted, the dashboard is a daemon feature.
- **D-17:** Tests. The per-gate subprocess harness in `tests/test_registry.py:155-205` gains
  `{"MACOS_APPS_ADAPTERS_OFF": "photos"}`: the listed tools equal the registered set, no photos
  tool is listed, all four are recorded. The file path is tested in a subprocess with
  `HOME=<tmp>` and the daemon role argv. `tests/conftest.py` patches the new file constant the way
  it patches `deploy._ALLOW_SEND_FILE` (`conftest.py:30-37`), so a developer's real file never
  reaches a test. The dispatcher is tested with fake scopes (lifespan, UDS, TCP). HTTP tests use
  `httpx.ASGITransport` directly, not Starlette's `TestClient` (it already warns about its httpx
  fallback): bad Host → 400, foreign Origin → 403, missing or wrong token → 403, no Origin and no
  `Sec-Fetch-Site` → 403, a `<script>` in an audit summary renders escaped, the loopback guard
  refuses `0.0.0.0` and a LAN address, a toggle writes the file and the audit record, a restart
  sets `should_exit` and `force_exit` on a fake server. `doctor` tests pin the `adapters_pending`
  shape as `test_doctor_deploy.py:136-171` pins `outbound_pending`. `tests/test_tool_annotations.py`
  needs no change in default runs.
- **D-18:** **Phase close cuts release 0.15.0** (owner, 2026-10-21). The last plan: the owner
  approves the cut before `main` and the tag are pushed; then the `--no-ff` cut to `main`, the
  tag, build, sign, notarize, staple, zip after stapling, install with `ditto` (old app moved to
  `~/.local/state/macos-apps-mcp/app-backup/`), kickstart, and the proof `doctor().version ==
  "0.15.0"` with the tagged build sha. `CHANGELOG.md` turns `[Unreleased]` into `[0.15.0]`: Photos
  (Phase 4), the 04.1 fixes, the adapter toggles and the dashboard. The device proof then runs on
  the **installed release**: open `http://127.0.0.1:47632` in a browser; turn Photos off; Restart;
  the page reconnects; `doctor` through a shim client reports `adapters` without photos and the
  four photos tools are absent from the tool list; turn Photos back on and restart. — **Reversibility:**
  one-way; a pushed tag and a GitHub release publish the version.

### Claude's Discretion

- Exact names (`adapter_enabled`, `adapter_status`, the audit reader, the guard), the Host check
  implementation (middleware vs five lines), the word diff (`difflib.SequenceMatcher` over split
  words, as the sketch suggests), en-GB date formatting without locale, the phone navigation
  (the sketch's open item: a horizontal strip of nav items), where dashboard records sit in the
  sidebar, and whether the toggle rows show tool and call counts from `usage_read()`.
- Adding a `receipt` key to the `AuditMiddleware` record so new batch records link exactly
  (old records still link by adjacency) is allowed when it stays a few lines with a test.
- `_AUTOMATION_APPS` may drop `Photos` if nothing sends Photos an Apple Event (Phase 4 D-07).
- The sketches are the UI contract. If `/gsd-ui-phase 5` produces a UI-SPEC.md, it must not
  contradict the four sketch references; the references win.

### Deferred Ideas (OUT OF SCOPE)

- A `macos-apps-mcp adapters [on|off <name>…]` CLI role beside `allow-send` (D-05) — add if the file-plus-kickstart fallback proves too thin.
- `Open` / `Reveal` endpoints for `.eml` backups under the toggle's token check, limited to the backup root (D-13).
- A live "watching audit.jsonl" update by poll or server-sent events (D-13).
- Grant-trigger endpoints that shell `open x-apple.systempreferences:…` and re-probe (#126 body) — a plain link covers it (D-14).
- A backup clean-up button and a dedupe runner (#126 comment, 2026-08-04) — ruled out by sketch rule 10 and #163; dedupe stays the `dedupe-mail` CLI.
- A JSON API for the menubar companion (PLAT-04, v2) — the pages are the API for now.
- A dashboard port override — an env var cannot reach a launchd daemon; a plist key or state file is the only route, and nothing asks for it yet.
- Network transport, auth and dashboard/MCP auth parity (PLAT-05, v2, #127).
- A graceful restart that waits for an in-flight Mail batch before exiting (D-16 accepts the kill, as `kickstart -k` does today).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PLAT-01 | Per-app adapter toggles read at daemon start; a disabled adapter's tools are absent; `doctor` reports the active set | Integration points 1-8 below (gate in `tiers`/`deploy`/`server._tool`/`registry`/`doctor`/`eventkit`); subprocess gate test pattern; `adapters_pending` shape; token-budget headroom measured |
| PLAT-02 | Localhost dashboard served by the daemon: grants and `doctor`, `usage`, audit trail, browsable recoverable backups; no SPA; loopback only; toggles + restart | Dispatcher + TCP bind probe (D-06/D-07), guard layer proto (D-08), restart probe and watchdog (D-16), audit reader and receipt facts (D-12/D-13), threat model |
</phase_requirements>

## Summary

CONTEXT.md settled the design and I verified its load-bearing facts against the installed stack (Python 3.14.5, uvicorn 0.52.4, Starlette 1.6.0, httpx 0.28.1, mcp 1.29.0, fastmcp 3.4.7). Almost everything holds: one uvicorn `Server` with `run(sockets=[uds, tcp])` behind an ASGI dispatcher works, keeps one lifespan, and makes `/mcp` unreachable over TCP; the audit files parse in 37 ms; the gate pattern copies `allow_send` cleanly; the wheel ships `dashboard.css` and `dashboard.js` when they sit in the package.

Five things in CONTEXT.md do **not** work as written and must be amended in the plans (the intent of each decision is unchanged). They are the "Corrections" section right below. The most dangerous: `Referrer-Policy: no-referrer` (D-08) makes Chrome send `Origin: null` on every same-origin form POST, so the Origin check would 403 every legitimate toggle; and `should_exit`+`force_exit` (D-16) never exits while a sync tool thread or the native worker is busy, so the daemon would hang instead of restarting.

**Primary recommendation:** Build tracer-first in two parallel wave-1 plans (PLAT-01 adapter gate with no UI; transport + guard + one real page behind the loopback bind), then the Adapters page with toggle and restart (criterion 3), then the read pages (criterion 2), and end with the non-autonomous 0.15.0 release plus the device proof (D-18). Apply the corrections C1-C8 below in the plan actions.

## Corrections to CONTEXT.md (read first; the planner applies these without re-opening the decisions)

| # | CONTEXT says | Finding | Amendment |
|---|--------------|---------|-----------|
| C1 | D-08: `Referrer-Policy: no-referrer` with an `Origin` equality check | `[VERIFIED: probe 05-proto/origin_probe.py, headless Chrome 155.0.8059.85]` a same-origin form POST sent `{'origin': 'null', 'sfs': 'same-origin', 'referer': None}` under `no-referrer`, and `{'origin': 'http://127.0.0.1:54206', ...}` under `same-origin` and under `strict-origin-when-cross-origin`. | Send `Referrer-Policy: same-origin` (nothing leaves the origin, Origin is sent). Treat `Origin: null` as foreign (403). Safari and Firefox behaviour is `[ASSUMED]` to match the Fetch spec; the D-18 device proof in a real browser confirms it. |
| C2 | D-16: `should_exit = True` and `force_exit = True` then uvicorn "exits 0" | `[VERIFIED: probe 05-proto/dispatch_client.py]` idle: exit 0 after 0.66 s. In-flight async call: exit 0 after 0.64 s. **In-flight SYNC tool (a thread): still running after 20 s** (killed by the probe). Real tools are sync functions on threads, and `runtime.run_native` uses a non-daemon `ThreadPoolExecutor` thread that `concurrent.futures` joins at interpreter exit. A KeepAlive job that does not exit is never relaunched. | After the response is flushed, set both flags **and arm `threading.Timer(3, os._exit, (0,))`** (daemon thread). Probe result with the watchdog: exit 0 after 3.07 s with a 40 s sync tool in flight, response body still delivered (`BackgroundTask`). `os._exit` skips `serve()`'s `finally`, so the socket file stays; `bind_socket` already unlinks a stale file on relaunch (`daemon.py:54-80`). |
| C3 | D-09: the lock edit is "the root version line of `uv.lock`" | `[VERIFIED: uv lock --offline on a copy]` adding `starlette` to `pyproject.toml` changes **three** places in `uv.lock`: the root `version` line, a `{ name = "starlette" }` entry in the root `dependencies`, and `{ name = "starlette", specifier = ">=0.40" }` in `[package.metadata] requires-dist`. CI runs `uv sync --locked` (`.github/workflows/ci.yml:29`), which fails on the other two. | Run `uv lock --offline` in the worktree after the `pyproject.toml` edit; `git diff uv.lock` must show exactly those three hunks and leave `revision = 5` alone. Use specifier `>=0.48` (mcp requires `starlette>=0.48.0` on Python 3.14; fastmcp 3 requires `>=1.0.1`). |
| C4 | D-06: UDS discriminator `scope["client"] is None` (equivalently `server[1] is None`) | `uvicorn/protocols/utils.py` `get_remote_addr` returns `None` when `getpeername()` raises `OSError` ("appears to inconsistently occur"). A TCP connection that races a reset could therefore look like a UDS scope and reach `/mcp`. `get_local_addr` has no such catch. `ProxyHeadersMiddleware` cannot set `client` to `None` (checked). | Route to MCP only when `scope["server"]` is a tuple whose port is `None`; **anything else goes to the dashboard** (fail closed: the dashboard answers `/mcp` with 404). Also pass `proxy_headers=False` to `uvicorn.Config`. |
| C5 | D-11: `/write/<ts>` | `[VERIFIED: read-only scan of this Mac's audit files]` 1057 primary records contain 2 timestamp groups with more than one record (max 3) and 2 `(ts, tool)` duplicates. Timestamps have 1 s resolution. | Use `/write/<ts>/<n>` where `n` is the zero-based ordinal among primary rows sharing that `ts` in file order. A batch's primary row is its plan record (or its middleware record when one links). |
| C6 | D-07/D-17: bind 47632 in `daemon.serve()` | `tests/test_daemon.py:102-123` runs the real `daemon.serve()` in a daemon thread (`test_serve_two_concurrent_sessions`). Unpatched, a unit test binds 47632 for real (collides with an installed v0.15 daemon, and the thread never exits so the port stays bound for the session). | Add a module constant `daemon.DASHBOARD_PORT = 47632`, read at call time in `serve()`. `tests/conftest.py` gets an autouse fixture that sets it to `0`. The bound-port assertion tests read the actual port from the socket. |
| C7 | D-14: `run_in_threadpool` with a 10 s bound | `run_native` has no timeout (`runtime.py:50-57`: `_executor.submit(fn).result()`). A timed-out `wait_for` leaves the thread blocked behind a multi-hour Mail batch; every page reload adds another blocked thread from anyio's shared limiter (default 40), which FastMCP's sync tools also use. | Single-flight: a module-level non-blocking lock around the Health `diagnose()` call; when the previous call is still running, render "worker busy" immediately without starting another thread. |
| C8 | D-08: "a hidden form field" (parsing unspecified) | Starlette's `request.form()` needs `python-multipart`, which is only a transitive dependency. | Parse the urlencoded body with `urllib.parse.parse_qs` under an 8 KiB cap (proved in `guard_proto.py`); no new dependency. |

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Adapter on/off setting (file + env) | Daemon process (registration at import) | Filesystem (`adapters_off`) | Gates are process-start facts (`tiers.py` docstring); the file is home-pinned like `allow_send` |
| Tool absence for an off adapter | MCP server registration (`server._tool`) | `registry.TOOLS` records | A gated-off tool keeps a record with `registered=False`, never registered-and-erroring |
| Dashboard HTTP surface | Daemon process, TCP listener on 127.0.0.1 | UDS listener (MCP only) | Browsers cannot speak UDS; the dispatcher keeps `/mcp` off TCP |
| Request authentication (Host/Origin/token) | Dashboard ASGI layer | — | Loopback bind stops other machines, not other websites or DNS rebinding |
| Audit / usage / backup reads | Dashboard handlers via `audit.py`, `mail_recover` | Filesystem under `~/.local/state/macos-apps-mcp` | Read-only views over existing files |
| Health / `doctor` | Dashboard handler → `doctor.diagnose` in a thread | `run_native` worker (EventKit) | Native access stays on the single worker |
| Restart | Daemon (self-exit) | launchd KeepAlive | No `launchctl` from inside the job |
| Outbound gate | CLI `allow-send` only | — | Shown locked on the page (sketch rule 5) |
| Static assets | Dashboard route with a fixed allow-list | Package data (hatchling) | No filesystem path derives from user input |

## Standard Stack

### Core
| Library | Version (installed) | Purpose | Why Standard |
|---------|---------------------|---------|--------------|
| uvicorn | 0.52.4 | ASGI server, `Server.run(sockets=[...])` | Already the daemon's server `[VERIFIED: .venv/lib/python3.14/site-packages/uvicorn-0.52.4.dist-info]` |
| starlette | 1.6.0 | Routes, responses, `BackgroundTask`, `run_in_threadpool`, `TrustedHostMiddleware` | Transitive via mcp/fastmcp today; becomes a listed dependency (`>=0.48`) `[VERIFIED: uv.lock:2455-2456; mcp-1.29.0 METADATA]` |
| httpx | 0.28.1 | Test client via `httpx.ASGITransport` | Already direct dependency |
| stdlib | 3.14 (bundle) / 3.12+ floor | `html.escape`, `hmac`, `secrets`, `ipaddress`, `difflib`, `urllib.parse` | No new code dependency |

### Supporting
None. No jinja2 (absent from `uv.lock` and the venv), no python-multipart (C8), no JS framework.

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Hand-rolled Host check | Starlette `TrustedHostMiddleware` | `[VERIFIED: starlette/middleware/trustedhost.py]` it strips the port (`host.split(":")[0]`) and answers 400; the strict `host:port` set in `guard_proto.py` is five lines and stricter. Either is acceptable (D-08). |
| `StaticFiles` | Fixed dict route | StaticFiles takes a path from the URL; a two-entry allow-list removes the traversal class entirely. Use the dict. |
| `TestClient` | `httpx.ASGITransport` | `from starlette.testclient import TestClient` already emits `StarletteDeprecationWarning` with httpx 0.28.1 `[VERIFIED: ran it]` (D-17). |

**Installation:** `pyproject.toml` gains `"starlette>=0.48",  # imported directly (dashboard.py)` beside `httpx`; version `0.15.0` in `pyproject.toml`, `packaging/Info.plist` (`CFBundleShortVersionString`) and the three `uv.lock` hunks (C3).

**Version verification:** starlette 1.6.0 is what `uv.lock` pins `[VERIFIED: uv.lock:2455-2456]`. No new package is downloaded.

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| starlette | PyPI | years (Encode/Kludex project; latest upload 2026-10-18) | n/a from the seam | github.com/Kludex/starlette | [SUS] (`too-new`, `unknown-downloads`: the seam judged the latest upload 3 days old) | Flagged — planner adds `checkpoint:human-verify` before the `pyproject.toml` edit. Mitigating fact: 1.6.0 is **already locked and installed** as a hard dependency of `mcp` and `fastmcp`, so the edit declares an existing dependency and downloads nothing. |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** starlette (see above; false positive driven by release recency)
`[VERIFIED: gsd-tools query package-legitimacy check --ecosystem pypi starlette]` returned the SUS verdict above.

## Architecture Patterns

### System Architecture Diagram

```
 browser (operator) ──HTTP──► 127.0.0.1:47632 ─┐
                                                │ TCP socket (daemon binds it, loopback guard)
 MCP client ► shim ─HTTP/UDS─► mcp.sock ───────┤ UDS socket (daemon binds it, 0600, single-instance)
                                                ▼
                       ONE uvicorn.Server.run(sockets=[uds, tcp])
                                                │
                              ASGI dispatcher (daemon.py)
          lifespan ─────────────┤────────────────────────┐
                                │                        │
        server[1] is None (UDS) │      anything else (TCP)│
                                ▼                        ▼
                      mcp.http_app()            dashboard app (Starlette)
                       (/mcp, 1 lifespan)         Guard: Host ─► (POST) Origin ─► token ─► headers
                                                          │
            ┌─────────────┬───────────────┬──────────────┼───────────────┬─────────────┐
            ▼             ▼               ▼              ▼               ▼             ▼
       GET / , /write   GET /health    GET /usage   GET /backups*   GET/POST /adapters  POST /restart
            │             │ run_in_threadpool        │                  │ toggle             │ BackgroundTask
            ▼             ▼ single-flight            ▼                  ▼                    ▼
   audit.read_all()   doctor.diagnose()      usage_report()      write adapters_off      should_exit=True
   (both .jsonl files) └─► run_native         mail_recover        + audit_write           force_exit=True
   + registry                worker           backup tree walk    (caller "dashboard")    Timer(3s, os._exit(0))
                                                                                          └► launchd KeepAlive relaunch
```

### Recommended Project Structure
```
macos_apps_mcp/
├── tiers.py          # + adapters_off(), adapter_enabled(name)
├── deploy.py         # + _ADAPTERS_OFF_FILE, adapters_off_file()
├── registry.py       # + adapter_status(); outbound_status() ANDs adapter_enabled
├── server.py         # _tool: registered = on and <tier rule>
├── doctor.py         # + adapters keys, adapter_off surfaces, dashboard state
├── eventkit.py       # request_access_each() skips OFF entities
├── audit.py          # + read_all() (oldest to newest, both files)
├── daemon.py         # serve(): TCP bind, dispatcher, run(sockets=...), restart closure
├── dashboard.py      # NEW: Starlette app, Guard, escape helper, pages (split at ~800 lines)
├── dashboard.css     # NEW: ported from the sketches
└── dashboard.js      # NEW: Copy buttons only
tests/
├── conftest.py       # + _ADAPTERS_OFF_FILE patch, + DASHBOARD_PORT=0 autouse
├── test_registry.py  # + ADAPTERS_OFF subprocess cases
├── test_adapters_off.py, test_dashboard_*.py, test_daemon_dispatch.py   # NEW
└── test_packaging.py # smoke string + version
```

### Integration points (exact, current)

| # | File:lines | Current | Change |
|---|-----------|---------|--------|
| 1 | `deploy.py:301` | `_ALLOW_SEND_FILE = Path.home() / ".local/state/macos-apps-mcp/allow_send"` | Add `_ADAPTERS_OFF_FILE = Path.home() / ".local/state/macos-apps-mcp/adapters_off"` beside it, with the same "home-pinned, tests patch the constant" comment; `adapters_off_file() -> str` mirrors `allow_send_file()` (`deploy.py:327-332`, `try: return _ALLOW_SEND_FILE.read_text()` / `except OSError: return ""`). |
| 2 | `deploy.py:304-324` | `is_daemon_role()` returns `os.environ.get("MACOS_APPS_MCP_ROLE") == "daemon" or sys.argv[1:2] == ["daemon"]` | Reuse as is. |
| 3 | `tiers.py:38-69` | `allow_send(adapter)`: env first, `if not val and deploy.is_daemon_role(): val = deploy.allow_send_file()` | Add `adapters_off() -> set[str]` and `adapter_enabled(name) -> bool` with the same env-then-file, daemon-only rule. |
| 4 | `server.py:153-165` | `if tier == "send": ... registered = tiers.allow_send(adapter)` / `elif tier == "read": registered = True` / `else: registered = not tiers.read_only()` | `on = adapter is None or tiers.adapter_enabled(adapter)`; send: `on and tiers.allow_send(adapter)`; read: `on`; else: `on and not tiers.read_only()`. The `f.__doc__` mail-autosave composition at `server.py:156-160` stays before the gate. |
| 5 | `registry.py:177-196` | `outbound_status()` returns `{"registered": sorted(registered), "configured": sorted(a for a in send_adapters if tiers.allow_send(a))}` | `configured` also requires `tiers.adapter_enabled(a)`. Add `adapter_status()`: `registered` = sorted adapters with a registered record; `configured` = sorted adapters in `{r.adapter for r in TOOLS.values() if r.adapter}` minus `tiers.adapters_off()`. |
| 6 | `doctor.py:164-188`, `:127-148`, `:191-201`, `:345-346` | `_automation_surfaces`, `_eventkit_surfaces`, `_shortcuts_surface`; `needs = [s["surface"] for s in surfaces if s["ok"] is False]`, `unknown = [... if s["ok"] is None]` | OFF adapter → `_surface(name, kind, None, "adapter_off")` without probing; exclude `status == "adapter_off"` from `needs`, `unknown` and from the "all N surfaces OK" count (otherwise the summary says "N unverified"). Mapping per D-04. |
| 7 | `doctor.py:368-419` | `ob = _outbound_state()`; `deployment = {...}`; `if ob["configured"] != ob["registered"]: deployment["outbound_pending"] = ...` | Add `adapters`, `adapters_off`, `adapters_unknown`, `adapters_pending` (+ one terse note naming `~/.local/state/macos-apps-mcp/adapters_off` and the kickstart command), `dashboard`. |
| 8 | `eventkit.py:97,107-115,118-124` | `_ENTITIES = (EK.EKEntityTypeEvent, EK.EKEntityTypeReminder)`; `request_access_each()` loops `_ENTITIES`; `bootstrap()` = `run_native(request_access_each)` | Pair each entity with its adapter name (`calendar`, `reminders`) and skip OFF ones. `doctor._try_request_access` calls the same function. Existing test `test_doctor.py:68` pins that it goes through `run_native`. |
| 9 | `daemon.py:202-224` | `serve()`: `s = bind_socket(path)`; `uvicorn.Config(mcp.http_app(), fd=s.fileno(), log_level="warning", ws="none")`; `uvicorn.Server(config).run()`; `finally: s.close(); path.unlink(missing_ok=True)` | Build the TCP socket after the UDS bind (loopback guard, EADDRINUSE logged, MCP keeps serving); `Config(dispatcher, log_level="warning", ws="none", proxy_headers=False)`; keep a handle on the `Server`; `server.run(sockets=[s] + ([tcp] if tcp else []))`; close both in `finally`. |
| 10 | `audit.py:61-72, 84-118` | `audit_write(record)` never raises, rotates at 5 MiB keeping `.1`; `audit_read` reads only `audit.jsonl`, newest first, limit 50 | Add `read_all()` (below). Leave `audit_read` and the `audit` tool untouched. |
| 11 | `adapters/mail_recover.py:562-593, 661-688, 316-322` | `find_receipt` scans `audit_read(limit=_RECEIPT_SCAN)` (current file only), raises `NativeError` if the plan is gone; `backup_usage()` returns `{path, bytes, receipts, oldest}`; `_backup_dir` runs `d.mkdir(parents=True, exist_ok=True)` | Backups page lists `state_dir()/"backup"/"mail"` directly; never call `_backup_dir`. |
| 12 | `cli.py:12-22` | `_ROLES` tuple | No change (D-05: no CLI twin). |
| 13 | `tests/test_registry.py:155-180, 183-209` | `_subprocess_registry_snapshot(env_extra)` runs `python -c` with `env = {"PATH": "/usr/bin:/bin", "HOME": os.environ["HOME"], **env_extra}` and returns `tools`, `registered`, `all_recorded` | Add the `MACOS_APPS_ADAPTERS_OFF=photos` case beside the READ_ONLY case; the file path case passes `HOME=<tmp>` and `MACOS_APPS_MCP_ROLE=daemon` (`is_daemon_role()` honours the env var; `sys.argv` is `['-c']` in `python -c`). |
| 14 | `tests/conftest.py:30-37` | session fixture `mp.setattr(deploy, "_ALLOW_SEND_FILE", state_home / "allow_send")` | Add the same line for `_ADAPTERS_OFF_FILE`, plus the autouse `DASHBOARD_PORT = 0` (C6). |
| 15 | `tests/test_packaging.py:164` | asserts the build script contains `'-E -s -P -c "import macos_apps_mcp, osxphotos, UniformTypeIdentifiers"'` | If the bundle smoke gains `macos_apps_mcp.dashboard` (recommended: it proves bundled starlette), edit `scripts/build_app.sh` and this string in the same commit. |

`[VERIFIED: read this session]` for all of the above; quoted values are verbatim from the cited lines.

### Pattern 1: the adapter gate (twin of `allow_send`)
```python
# tiers.py — Source: twin of allow_send (tiers.py:38-69), read this session
def adapters_off() -> set[str]:
    val = os.environ.get("MACOS_APPS_ADAPTERS_OFF", "").strip()
    if not val and deploy.is_daemon_role():
        val = deploy.adapters_off_file()
    return {p.strip().lower() for p in val.split(",") if p.strip()}

def adapter_enabled(name: str) -> bool:
    return name not in adapters_off()
```
Per-call re-read is what lets `registry.adapter_status()["configured"]` differ from `["registered"]` after the file changes (the `outbound_pending` shape).

### Pattern 2: the dispatcher (proved by `05-proto/dispatch_server.py`)
```python
# Source: 05-proto/dispatch_server.py; UDS scope on uvicorn 0.52.4 is server == (path, None)
def make_dispatcher(mcp_app, dash_app):
    async def dispatcher(scope, receive, send):
        if scope["type"] == "lifespan":
            return await mcp_app(scope, receive, send)          # one startup, one shutdown
        if scope["type"] != "http":
            return                                              # ws="none"; ignore the rest
        server = scope.get("server")
        if isinstance(server, tuple | list) and server[1] is None:   # UDS only (C4)
            return await mcp_app(scope, receive, send)
        return await dash_app(scope, receive, send)             # TCP, and fail-closed default
    return dispatcher
```
Probe results `[VERIFIED]`: TCP `GET /` → 200 with `client=('127.0.0.1', n)`, TCP `POST /mcp` → 404, UDS `ping` → `ok`, lifespan events seen: `["lifespan.startup"]` (no second startup).

### Pattern 3: the request layer (proved by `05-proto/guard_proto.py`, 14 cases pass)
Strict `Host` set `{"127.0.0.1:<port>", "localhost:<port>"}` on every request; on POST: `Origin` in `{http://127.0.0.1:<port>, http://localhost:<port>}`, else (Origin absent) `Sec-Fetch-Site == "same-origin"`, `Origin: null` rejected; then token via `hmac.compare_digest(got.encode(), token.encode())` on the urlencoded body, 8 KiB cap, body replayed to the handler. Headers on every response: CSP `default-src 'self'; frame-ancestors 'none'; form-action 'self'`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin` (C1), `Cache-Control: no-store`. Run the HTTP tests through `httpx.ASGITransport(app=...)`.

### Pattern 4: escape-by-default HTML (D-09)
```python
import html
class Safe(str): """Marked-safe markup. Only dashboard code constructs it."""
def esc(v) -> str: return v if isinstance(v, Safe) else html.escape(str(v), quote=True)
def h(tpl: str, *vals, **kw) -> Safe:      # h("<td>{}</td>", subject) escapes subject
    return Safe(tpl.format(*map(esc, vals), **{k: esc(v) for k, v in kw.items()}))
```
Attribute URLs built from record data (a Pointer `deeplink`) get a scheme allow-list check besides `esc` (reject `javascript:`, `data:`, `vbscript:`); the CSP also blocks `javascript:` navigation, as a backstop only.

### Pattern 5: restart (C2)
```python
# daemon.py — closure handed to dashboard.build_app(restart=...)
def _restart() -> None:                       # runs as a Starlette BackgroundTask: after the body is sent
    server.should_exit = True
    server.force_exit = True                  # skips the wait for connections and tasks
    t = threading.Timer(3.0, os._exit, (0,))  # a sync tool thread / the native worker would block exit
    t.daemon = True
    t.start()
```
Plist `KeepAlive` is `true` and `ThrottleInterval` is `10` `[VERIFIED: packaging/ren.lav.macos-apps-mcp.plist]`: any exit relaunches, immediately when the job ran longer than 10 s. `launchctl print` here shows `exit timeout = 5`, `runs = 3`, `keepalive` `[VERIFIED: ran it]`. Logging noise on forced exit ("ASGI callable returned without completing response", a `CancelledError` traceback from the lifespan task) is expected and harmless `[VERIFIED: probe stderr]`.

### Pattern 6: the audit reader (D-12)
```python
# audit.py — new; same file logic as audit_read, no limit, oldest to newest
def read_all() -> list[dict]:
    recs = []
    for path in (_audit_path().with_name("audit.jsonl.1"), _audit_path()):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            try:
                recs.append(json.loads(line))
            except ValueError:
                continue
    return recs
```
`[VERIFIED: ran against this Mac, read-only]` 2936 records, 0.037 s. Record facts used by the page: plan/done records have `phase`, `receipt`; `done["results"]` maps id to status; a middleware record for `move_mail` has `after: null` and `target_id: null` because `_audit_after` only keeps a dict containing `"id"` (`audit.py:202-208`) while the move result carries `receipt`, `count`, `succeeded`, `targets` and no `id` (`mail_recover.py` result dict). So the adjacency link (first record of the same tool after the done record) is the only link today: it held for all 928 done records of `move`/`trash` here. It can mislink after a failed call (a `NativeTimeout` writes `done` and then raises, so no middleware record follows). The optional exact link (CONTEXT discretion): in `AuditMiddleware.on_call_tool` add `receipt` from `result.structured_content["result"]["receipt"]` when present; a few lines plus one test.

### Pattern 7: Backups page data
Receipt directory names match `^\d{8}-\d{6}-\d{6}-\d{3}-(move|trash|dedupe)$` `[VERIFIED: mail_recover.py:337-339 f"{stamp}-{next(_MINTED):03d}-{op}" with "%Y%m%d-%H%M%S-%f"; OPS = frozenset({"move", "trash", "dedupe"}) at :71; this Mac's 935 dirs are 883 move + 52 trash]`. Validate `<receipt>` against that regex **before** touching the filesystem, then `(root / receipt)` must be a real directory, not a symlink, whose parent is `root`. List file names and sizes only; there is no file-content endpoint.

### Anti-Patterns to Avoid
- **Two uvicorn Servers on one loop:** each `capture_signals` overwrites the other's SIGTERM handler (D-06, `uvicorn/server.py`).
- **`StaticFiles` or any path built from the URL:** use the fixed dict.
- **`request.form()`:** needs python-multipart (C8).
- **Calling `_backup_dir()` from a read page:** it runs `mkdir`.
- **`backup_usage()` in the sidebar:** 0.56 s on this Mac's 935 receipts (D-13); only Backups and Health.
- **A health/discovery endpoint that triggers prompts:** `diagnose(request=False)` only; no EventKit request, no Apple Event.
- **Dashboard importing `server`:** `tests/test_import_layers.py` forbids anything in `server.py`'s import closure from importing `server`; `daemon.serve()` imports `dashboard` lazily, and `dashboard` needs only `registry`, `audit`, `doctor`, `deploy`, `tiers`, `mail_recover`. Get registered tool names from `registry.TOOLS`, not `await mcp.list_tools()`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HTML escaping | custom replace chains | `html.escape(s, quote=True)` behind `esc()` | One audited function; every value passes through it |
| Constant-time token compare | `==` | `hmac.compare_digest` on encoded bytes | Timing; `str` with non-ASCII raises `TypeError` |
| Token generation | random/time based | `secrets.token_urlsafe(32)` | CSPRNG |
| Loopback test | string prefix check | `ipaddress.ip_address(host).is_loopback` | `localhost`/`0.0.0.0`/LAN/`::` all handled; a name raises `ValueError` and is refused |
| Word diff | custom LCS | `difflib.SequenceMatcher` over `str.split()` | Stdlib, as the sketch suggests |
| Thread offload | `threading` in handlers | `starlette.concurrency.run_in_threadpool` | Existing, cancellation-aware |
| Response after-send hook | sleeping task | `starlette.background.BackgroundTask` | Runs after the body is sent `[VERIFIED: probe: client received "restarting" before exit]` |
| Atomic file write | partial `write_text` | write temp file in the same dir + `os.replace` | A daemon killed mid-write must not leave a truncated `adapters_off` (a truncated file would read as "everything on"); mode dir `0o700` as `deploy.allow_send` does |
| Multipart/form parsing | python-multipart | `parse_qs` | C8 |

**Key insight:** every hard problem here (transport split, CSRF layers, restart) has a small stdlib or already-installed answer; the risk is in the interactions (C1, C2, C4), which the probes cover.

## Common Pitfalls

### Pitfall 1: Origin check 403s every real toggle
**What goes wrong:** the page is served with `Referrer-Policy: no-referrer`; the browser sends `Origin: null`; the check rejects it. **Why:** Fetch spec "append a request Origin header" sets the serialized origin to `null` for non-cors, non-GET requests under `no-referrer` `[VERIFIED: Chrome 155 probe]`. **Avoid:** `same-origin` (C1) and a test that posts `Origin: null` expecting 403. **Warning sign:** the device proof's first toggle returns "Forbidden origin".

### Pitfall 2: restart hangs, daemon is never relaunched
See C2. **Warning sign:** after "Restart daemon", `launchctl print gui/$UID/ren.lav.macos-apps-mcp` still shows the same pid minutes later. The unit test for restart asserts that `os._exit` is armed (inject a fake timer factory), and the device proof asserts a new pid.

### Pitfall 3: stale token after a restart
The new process mints a new token. A tab opened before the restart holds the old one and its next POST gets 403. **Avoid:** the 403 page for a token mismatch says "Reload the page; the daemon restarted" and links to `/adapters`. The restart page meta-refreshes to `/adapters` (a GET) after about 12 s: import takes 0.9-1.4 s (D-16 facts) and a relaunch is immediate for a job older than 10 s, but a job restarted within its first 10 s waits out `ThrottleInterval`. A refresh that lands on a closed port leaves a browser error page, which is why the page also carries a visible Reload link `[ASSUMED: browsers do not retry a failed meta-refresh]`.

### Pitfall 4: the test suite binds the real port
C6.

### Pitfall 5: `doctor` summary lies when adapters are off
`unknown = [... ok is None]` would count `adapter_off` surfaces and print "no denied surfaces; 3 unverified: ..." under `request=True`. Exclude them and compute the "all N surfaces OK" N from the probed surfaces only. The report budget test asserts `len(json.dumps(report)) < 7000` and measures 6141 today `[VERIFIED: ran test_report_stays_under_token_budget under a length spy]`; the new keys cost about 250 characters in the default case. Print the length before and after.

### Pitfall 6: `/write/<ts>` collisions
C5.

### Pitfall 7: Health starves the thread limiter
C7.

### Pitfall 8: dashboard records reach `AuditMiddleware`/`usage_log`
D-15 says dashboard records go around the middleware. `usage` must not count dashboard calls and `registry.audit_verbs()` must not gain a `dashboard` key. `audit_write` is the only call. `find_receipt` and `audit_read` accept records without `receipt`.

### Pitfall 9: file constant read at import vs HOME in tests
`_ADAPTERS_OFF_FILE = Path.home() / ...` is evaluated at import. The subprocess test sets `HOME=<tmp>` **before** the interpreter starts (as `_subprocess_registry_snapshot` does for env), so the constant is right. In-process tests patch the constant (conftest), never `HOME`.

### Pitfall 10: version-bump rule bites a later PR
`.github/workflows/version.yml` triggers on `paths: ['src/**', 'package.json', 'pyproject.toml']` and fails when `version` equals the base branch's `[VERIFIED: file read]`. Only the first PR touching `pyproject.toml` needs the 0.15.0 bump (D-09); a later phase-5 PR that does not touch `pyproject.toml` needs none. If a later PR touches it again, the version would have to differ from `develop`, so do not touch it again.

## Code Examples

The dispatcher, guard, restart, gate and reader above are the examples. Two more:

### Loopback bind guard and TCP socket
```python
# daemon.py — D-07; test the refusal with assert_loopback("0.0.0.0") and a LAN address
def bind_dashboard(host: str, port: int) -> socket.socket:
    ipaddress.ip_address(host)                       # ValueError for a name
    if not ipaddress.ip_address(host).is_loopback:
        raise ValueError(f"dashboard refuses to bind {host!r}: not a loopback address")
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)   # restart-in-place after os._exit
    try:
        s.bind((host, port))
    except OSError:
        s.close()
        raise
    s.listen()
    return s
```
`serve()` catches `OSError` from this call only, logs `"not bound: <reason>"`, stores that string for `doctor`, and continues with the UDS alone. `SO_REUSEADDR` matters: after `os._exit` the old TCP socket can sit in TIME_WAIT and the relaunched daemon would otherwise hit EADDRINUSE `[ASSUMED: macOS TIME_WAIT semantics; the probe ran with SO_REUSEADDR and never tested without]`.

### Dashboard record
```python
audit_write({"ts": datetime.now().isoformat(timespec="seconds"), "tool": "dashboard",
             "op": "toggle", "args": {"adapter": name, "on": on}, "dry_run": False,
             "caller": "dashboard", "target_id": name, "before": None, "after": None})
```
(D-15; restart uses `"op": "restart"` and `"args": {}`.)

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Starlette `TestClient` with httpx | `httpx.ASGITransport` (or httpx2 for TestClient) | starlette 1.x | `StarletteDeprecationWarning` on `TestClient` here |
| `server.wait_closed()` returned at once | Python 3.12.1+ waits for open connections | 3.12.1 | One reason a forced exit still needs the watchdog; bundle runs 3.14 (`scripts/build_app.sh` stdlib path `python3.14`) |

**Deprecated/outdated:** none relevant.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Safari and Firefox send the real Origin under `Referrer-Policy: same-origin` (spec behaviour; only Chrome 155 was probed) | C1 | A toggle 403s in that browser; the D-18 device proof in the owner's browser catches it; fallback: `Sec-Fetch-Site` branch already covers a missing Origin |
| A2 | `navigator.clipboard.writeText` works on `http://127.0.0.1` in Safari (D-08 says loopback is a secure context) | Copy buttons | Copy does nothing; fallback `document.execCommand("copy")` on a selected `<code>` |
| A3 | Browsers do not retry a meta-refresh whose target refused the connection | Pitfall 3 | None; a Reload link is shown regardless |
| A4 | `SO_REUSEADDR` is needed to rebind 47632 straight after `os._exit` | Code Examples | Harmless if wrong (the option is standard for servers) |
| A5 | Other local macOS users can reach 127.0.0.1:47632 (loopback is machine-wide) and read the audit trail or toggle adapters; accepted as residual for ASVS L1 on a single-user Mac | Security | A multi-user Mac exposes the dashboard to the other accounts; owner should confirm the single-user assumption and `docs/DAEMON.md` should state it |
| A6 | New subprocess gate cases cost about 1.1 s each (a bare `import macos_apps_mcp.server` took 1.075 s total) | Validation | Suite time rises by a few seconds more than budgeted |
| A7 | `starlette>=0.48` is a safe floor for the APIs used (`Starlette`, `Route`, responses, `BackgroundTask`, `run_in_threadpool`) | C3 | CI only tests the locked 1.6.0; a floor mismatch would show only for users on an older resolve |

## Open Questions (RESOLVED)

1. **Does C1 re-open D-08?** (RESOLVED) No. The decision's intent (Origin plus token plus Host on writes) is unchanged; only the `Referrer-Policy` value changes, because the literal header breaks the check in the real browser. Plans implement `same-origin`.
2. **Does the restart need a graceful path for an in-flight Mail batch?** (RESOLVED) No: D-16 and Deferred already accept the kill; the plan record and backups survive, and the page text says so.
3. **Should the dashboard port be configurable?** (RESOLVED) No (Deferred). Only the module constant exists, for tests.
4. **Where does `doctor` read the dashboard state?** (RESOLVED, planner's discretion) A module attribute in `deploy.py` (`dashboard_state: str`), written by `daemon.serve()`, read by `doctor.diagnose()`: `"http://127.0.0.1:47632"`, `"not bound: <reason>"`, or absent in stdio mode. `doctor` must not import `daemon`. Planned form: the holder is `daemon.dashboard_state` (05-02 runs beside 05-01, which owns `deploy.py` in wave 1); `doctor` imports `daemon` inside `diagnose()` only in the daemon role, where the module is already loaded (05-05 Task 1).
5. **Does the owner accept the other-local-user exposure (A5)?** (RESOLVED for planning) Left open for the owner, low urgency: it changes only a documentation sentence, not the code. If no answer, ship with the sentence in `docs/DAEMON.md`. RESOLVED: the plans ship the no-answer default — 05-05 Task 4 adds the single-user sentence to `docs/DAEMON.md` § 7 (threat T-05-31, accepted at ASVS L1); the item is surfaced to the owner as a flagged assumption.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| uv | all plans | yes | 0.13.4 | — |
| Python (venv / bundle) | all | yes | 3.14.5 / bundle 3.14 | — |
| uvicorn, starlette, httpx | PLAT-02 | yes | 0.52.4 / 1.6.0 / 0.28.1 | — |
| Google Chrome (headless, for the Origin probe and the visual check) | UI checkpoint | yes | 155.0.8059.85 | Safari manual |
| gh | PRs, release cut | yes | installed | — |
| codesign + Developer ID identity | D-18 | yes | 1 valid identity | — |
| xcrun notarytool | D-18 | yes | 1.1.3 (42) | — (memory: profile "notary"; check exit 0 first, a pending Apple agreement returns 403) |
| launchctl, ditto | D-18 | yes | system | — |
| port 47632 | probes/proof | free at research time (`lsof` empty); installed daemon is v0.14.3 and does not bind it | — | tests use port 0 |

**Missing dependencies with no fallback:** none.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x (`>=8,<10`), `pytest-cov`; `asyncio.run(...)` inside sync tests (the repo has no pytest-asyncio) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]`: `testpaths = ["tests"]`, `addopts = "-m 'not integration'"` |
| Quick run command | `uv run pytest -q tests/test_adapters_off.py tests/test_dashboard_guard.py tests/test_dashboard_pages.py tests/test_daemon_dispatch.py tests/test_registry.py tests/test_doctor.py tests/test_doctor_deploy.py` |
| Full suite command | `uv run pytest -q`, then `MACOS_APPS_READ_ONLY=1 uv run pytest -q`, then `MACOS_APPS_ALLOW_SEND=mail uv run pytest -q` (RELEASING.md step 2), then `uv run ruff check .` and `uv run ruff format --check .` |
| Runtime budget | Baseline `[VERIFIED: ran this session]`: `uv run pytest -q` → 2229 passed, 102 deselected, 22 s; `MACOS_APPS_READ_ONLY=1` → 2214 passed, 15 skipped, 22 s. Phase budget: stay under 30 s (new HTTP tests are in-process, tens of ms each; the subprocess gate cases add about 1-2 s each). |

### Phase Requirements → Test Map
| Req / criterion | Behavior | Test Type | Automated Command | File Exists? |
|-----------------|----------|-----------|-------------------|-------------|
| PLAT-01 / SC1 | env `MACOS_APPS_ADAPTERS_OFF=photos`: no photos tool listed, all four recorded, `tools == registered` | subprocess | `uv run pytest -q tests/test_registry.py -k adapters_off` | extend (Wave 0 for the case) |
| PLAT-01 / SC1 | file `adapters_off` read only in daemon role (HOME=tmp, `MACOS_APPS_MCP_ROLE=daemon`); absent/empty = all on; stdio ignores the file | subprocess | `uv run pytest -q tests/test_adapters_off.py -k file` | ❌ Wave 0 |
| PLAT-01 / SC1 | send tool of an OFF adapter is not registered; `outbound_status()["configured"]` drops it (no phantom `outbound_pending`) | unit + subprocess (`MACOS_APPS_ALLOW_SEND=mail` + off mail) | `uv run pytest -q tests/test_adapters_off.py -k outbound` | ❌ Wave 0 |
| PLAT-01 / SC1 | meta tools never gated; unknown name ignored and reported as `adapters_unknown` | unit | `... -k meta or unknown` | ❌ Wave 0 |
| PLAT-01 / SC1 | `doctor` reports `adapters`, `adapters_off`, `adapters_pending` + restart directive; OFF surfaces `adapter_off`, no `run_osascript` call, `request=True` skips the probe; EventKit request skips OFF entities | unit | `uv run pytest -q tests/test_doctor.py tests/test_doctor_deploy.py tests/test_eventkit.py` | extend |
| PLAT-01 | token budget `< 7000` chars still holds | unit | `uv run pytest -q tests/test_doctor.py -k token_budget` | exists (6141 now) |
| PLAT-02 / SC4 | `assert_loopback`/`bind_dashboard` refuse `0.0.0.0`, a LAN address, `localhost`, `::`; accept `127.0.0.1`, `::1` | unit | `uv run pytest -q tests/test_daemon_dispatch.py -k loopback` | ❌ Wave 0 |
| PLAT-02 / SC4 | dispatcher with fake scopes: lifespan → MCP, `server=(path, None)` → MCP, TCP → dashboard, `server=None` → dashboard, websocket ignored | unit | `... -k dispatcher` | ❌ Wave 0 |
| PLAT-02 / SC4 | real bind: dashboard on port 0 answers 200 on TCP, `/mcp` over TCP is 404, `/mcp` over UDS works (extends `test_serve_two_concurrent_sessions`); EADDRINUSE → MCP still serves and `doctor` says `not bound` | integration-lite (thread) | `uv run pytest -q tests/test_daemon.py` | extend |
| PLAT-02 / SC2 | Host 400 on every route; foreign/`null` Origin 403; wrong/missing token 403; no Origin and no `Sec-Fetch-Site` 403; security headers present; GET has no side effect | unit (`httpx.ASGITransport`) | `uv run pytest -q tests/test_dashboard_guard.py` | ❌ Wave 0 |
| PLAT-02 / SC2 | `<script>` in an audit summary / receipt string renders escaped on `/`, `/write/..`, `/backups/..`; `javascript:` deeplink not rendered as href | unit | `... -k escape` | ❌ Wave 0 |
| PLAT-02 / SC2 | `/static/<file>` serves only the allow-list; `../x`, `%2e%2e%2f` → 404; `/backups/<bad>` → 404 without touching disk | unit | `... -k traversal` | ❌ Wave 0 |
| PLAT-02 / SC2 | audit reader: both files, order, legacy record without `dry_run` resolves from `registry.dry_run_defaults()`, batch grouping by receipt, outcome from `done["results"]`, `/write/<ts>/<n>` disambiguation, `dedupe-mail` batch without middleware record | unit | `uv run pytest -q tests/test_audit.py tests/test_dashboard_pages.py` | extend / ❌ |
| PLAT-02 / SC2 | Health page: runs `diagnose(request=False)` off the loop, single-flight returns "worker busy" while a call is in flight, danger banner only for an active adapter with a denied grant | unit | `... -k health` | ❌ Wave 0 |
| PLAT-02 / SC2 | Backups page lists a fixture tree, never creates a directory (`state_dir()/backup` absent stays absent), `backup_usage()` not called by `/` | unit | `... -k backups` | ❌ Wave 0 |
| PLAT-02 + PLAT-01 / SC3 | toggle POST writes `adapters_off` (atomic, dir 0700) and one `audit.jsonl` record with `caller: "dashboard"`; Discard restores the running set; pending chip and restart bar render from `adapter_status()`; Outbound row is locked text with the `allow-send` command and no input | unit | `... -k toggle` | ❌ Wave 0 |
| PLAT-02 / SC3 | restart POST sets `should_exit`, `force_exit` on a fake server and arms the watchdog (fake timer factory); writes the `restart` record; response body is the "Restarting the daemon…" page | unit | `... -k restart` | ❌ Wave 0 |
| SC3 end to end | toggle Photos off, Restart, new pid, `doctor` via shim reports `adapters` without photos, the four photos tools absent, toggle back | manual (D-18 device proof on the installed 0.15.0) | n/a — checkpoint | n/a |
| packaging | version 0.15.0 matches `pyproject.toml` and `Info.plist`; wheel contains `dashboard.css`/`dashboard.js`; bundle smoke imports `macos_apps_mcp.dashboard` | unit + build | `uv run pytest -q tests/test_packaging.py`; wheel listing in the build script | extend |

### Sampling Rate
- **Per task commit:** the Quick run command (under 10 s).
- **Per wave merge:** `uv run pytest -q` plus `uv run ruff check .` and `uv run ruff format --check .`.
- **Phase gate:** all three pytest passes (default, `MACOS_APPS_READ_ONLY=1`, `MACOS_APPS_ALLOW_SEND=mail`) green, then the D-18 device proof.

### Wave 0 Gaps
- [ ] `tests/test_adapters_off.py` — gate, file, outbound interplay (PLAT-01)
- [ ] `tests/test_daemon_dispatch.py` — loopback guard, dispatcher with fake scopes, restart closure
- [ ] `tests/test_dashboard_guard.py` — Host/Origin/token/headers/escape/traversal via `httpx.ASGITransport`
- [ ] `tests/test_dashboard_pages.py` — list/detail/usage/backups/health/adapters
- [ ] `tests/conftest.py` — `_ADAPTERS_OFF_FILE` patch and `DASHBOARD_PORT = 0` autouse
- [ ] fixture helper writing a fake `audit.jsonl`/`.1` and a fake backup tree under the isolated `XDG_STATE_HOME`
- Framework install: none

## Security Domain

`security_enforcement` is on (`.planning/config.json`: `security_enforcement: true`, `security_asvs_level: 1`, `security_block_on: "high"`).

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no (no user accounts; single-operator loopback) | — ; the per-session token is CSRF protection, not authentication |
| V3 Session Management | partial | `secrets.token_urlsafe(32)` minted at daemon start, held in memory, hidden form field, `hmac.compare_digest` |
| V4 Access Control | yes | only two write endpoints; Outbound never a control; MCP endpoint unreachable on TCP |
| V5 Input Validation | yes | allow-list route params (`ts`/`n` ints, receipt regex, adapter name against the registry set), 8 KiB body cap, method allow-list, `escape` on output |
| V6 Cryptography | no hand-rolled crypto | `secrets`, `hmac` only |
| V13/V14 config & headers | yes | CSP, `frame-ancestors 'none'`, `X-Frame-Options`, `nosniff`, `Referrer-Policy: same-origin`, `Cache-Control: no-store` |

### Known Threat Patterns (liftable into each plan's `<threat_model>`)

| Threat | STRIDE | Severity | Mitigation | Verification |
|--------|--------|----------|------------|--------------|
| DNS rebinding reads the audit trail or posts to the dashboard | Information disclosure / Tampering | high | Strict `Host` allow-list `{127.0.0.1:47632, localhost:47632}` on every request, reads included | `test_dashboard_guard`: `Host: evil.com[:47632]` → 400 on `/`, `/health`, `/static/..` and POST |
| CSRF from a website to 127.0.0.1 (toggle, restart) | Tampering / EoP | high | POST needs token + same-origin `Origin` (or `Sec-Fetch-Site: same-origin` when absent); `Origin: null` refused; token compared constant-time; GETs side-effect free; `Referrer-Policy: same-origin` so legitimate posts carry a real Origin (C1) | guard tests (foreign, null, absent, wrong token) + device proof |
| Click-jacking a valid toggle | Tampering | high | CSP `frame-ancestors 'none'` + `X-Frame-Options: DENY` | header assertion on every response |
| Stored XSS through audit/receipt strings (mail subjects written by strangers) | Tampering / Elevation | high | escape-by-default `esc()`/`h()`, no inline script or style, CSP `default-src 'self'`; href scheme allow-list | test renders `<script>alert(1)</script>` and `" onmouseover="` in summary, tool, args, receipt, folder; asserts escaped output |
| MCP reachable from a web page over TCP | EoP | high | dispatcher routes only `server[1] is None` to MCP; TCP is dashboard-only; `/mcp` → 404 | dispatcher fake-scope tests + real-bind test (C4) |
| Non-loopback bind | Information disclosure | high | `bind_dashboard` guard raises for any non-loopback literal; constant host `127.0.0.1` | guard unit test (`0.0.0.0`, LAN, `localhost`, `::`) |
| Path traversal on `/static/<file>` and `/backups/<receipt>` | Information disclosure | high | static dict allow-list; receipt regex before any FS access, directory-not-symlink check, names and sizes only | traversal test (`..`, `%2e%2e`, absolute, NUL, symlink fixture) |
| Restart abuse / repeated restarts | DoS | medium | restart needs token+Origin; response page names the consequence; ignore a second restart while one is armed (module flag); launchd `ThrottleInterval` bounds relaunch rate | restart test posts twice, one timer |
| Dashboard thread starvation via Health reloads | DoS | medium | single-flight lock around `diagnose()` (C7) | health test with a blocked fake `diagnose` |
| `adapters_off` truncated by a mid-write kill reads as "all on" | Tampering | medium | write to a temp file in the same directory + `os.replace` | toggle test checks no partial file after a simulated failure |
| Other local macOS user reads/toggles over loopback | Information disclosure / EoP | low (accepted) | none at L1; document the single-user assumption in `docs/DAEMON.md` (A5) | doc check |
| Secrets/PII on the page | Information disclosure | medium | pointers only (summaries are already in the audit log); no message bodies; backup paths shown as text, no file endpoint | review of the rendered detail pages |

## Suggested Plan Decomposition (tracer-first; one PR per lane)

| Plan | Wave | Autonomous | Slice | Depends on | Lanes / files |
|------|------|------------|-------|------------|---------------|
| 05-01 | 1 | yes | **PLAT-01 tracer, no UI.** `adapters_off` file + env, `tiers.adapter_enabled`, `server._tool` AND, `registry.adapter_status`/`outbound_status`, `doctor` adapter keys and `adapter_off` surfaces, `eventkit` skip, conftest patch, subprocess gate tests, `docs/DAEMON.md` file + kickstart note. Proves SC1 end to end (criterion 1) through `doctor` and the tool list. | — | `deploy.py tiers.py registry.py server.py doctor.py eventkit.py` + tests |
| 05-02 | 1 (parallel to 05-01) | yes | **Transport + guard tracer.** `pyproject.toml` (`starlette>=0.48`, version 0.15.0) + `Info.plist` + `uv.lock` (3 hunks); `daemon.serve()` dispatcher, loopback bind, `DASHBOARD_PORT` constant, restart closure stub; `dashboard.py` skeleton with Guard, headers, escape helper, static route, CSS port, and ONE real page (`/health` or `/usage`) so the whole path browser → Host check → handler is live; bundle smoke + `test_packaging`; dispatcher/loopback/guard tests. Proves SC4. Includes a `checkpoint:human-verify` for the starlette SUS flag before the `pyproject.toml` edit. | — | `daemon.py dashboard.py dashboard.css pyproject.toml uv.lock packaging/Info.plist scripts/build_app.sh tests/*` |
| 05-03 | 2 | yes | **Writes (SC3).** `/adapters` GET/POST toggle/discard, sidebar badge, Outbound locked row, `/restart` with `BackgroundTask` + watchdog, dashboard audit records, `deploy.dashboard_state` + `doctor` `dashboard` field. | 05-01, 05-02 | `dashboard.py daemon.py deploy.py doctor.py` + tests |
| 05-04 | 3 | yes, then a human-verify checkpoint | **Reads (SC2).** `audit.read_all`, `/` list + filters + `/write/<ts>/<n>` detail (word diff, resolved `dry_run`, preview banner, raw lines), batch/recovery detail (read-only), `/usage`, `/backups`, `/backups/<receipt>`, full `/health`; optional `receipt` key in `AuditMiddleware`. Ends with a checkpoint comparing the rendered pages to the four sketches in Chrome (no login needed). | 05-02 (and 05-03 for the shared module and the sidebar counts) | `dashboard.py audit.py dashboard.css` + tests |
| 05-05 | 4 | **no** (owner approval gates `main` and the tag, D-18) | **Release 0.15.0 and device proof.** CHANGELOG `[Unreleased]` → `[0.15.0]` (Photos, 04.1 fixes, toggles, dashboard); full three-pass green; `develop` → `main` `--no-ff` PR, tag, build, sign, notarize (check `notarytool` exits 0), staple, zip after stapling, `ditto` install with the old app moved to `~/.local/state/macos-apps-mcp/app-backup/`, kickstart, `doctor().version == "0.15.0"` with the tagged build sha, then the browser proof (turn Photos off, Restart, new pid, `doctor` via shim lacks photos, four photos tools absent, turn it back). Verifies C1 in the owner's real browser. | 05-01..05-04 | release lane |

The `dashboard.py` collisions between 05-03 and 05-04 are why they are sequential waves, not parallel; split into a `dashboard/` subpackage (`app.py`, `guard.py`, `pages_*.py`) at the start of 05-02 if the planner prefers parallel page work.

Planned form (differs from this sketch): 05-01 adapter gate; 05-02 transport, Guard and Usage page in the `dashboard/` subpackage; 05-03 toggles and restart; 05-04 write list and recovery; 05-05 Health, Backups and docs; 05-06 release; 05-07 device proof; 05-08 the starlette declaration and the 0.15.0 bump, in wave 1 beside 05-02, which merges only after it. No starlette checkpoint is inserted: 1.6.0 is already locked and installed, and 05-08 downloads nothing (its context states the evidence).

## Project Constraints (from CLAUDE.md)

- Python + FastMCP, `uv`; `ruff` rules `E, F, I, UP, B, SIM`, line length 88, **no mypy**; `from __future__ import annotations` at the top of modules; relative imports.
- Tools in `server.py` stay thin dispatch; no logic in the tool layer. This phase adds **no new MCP tool** (the dashboard is not a tool; consent gates are not tools).
- Adapters stay typed Protocols; no cross-adapter reach; `dashboard.py` is not an adapter but must not reach into adapter internals beyond `mail_recover.backup_usage`/`find_receipt`/`OPS`.
- All native access through `runtime.run_native()` on the single worker (`max_workers=1`, never widened); never call EventKit off it.
- Tiers gated **at registration**: a gated-off tool is absent, never registered-and-erroring (the whole point of PLAT-01). Outbound defaults `dry_run=True`; `READ_ONLY` wins.
- Shim↔daemon hop has **no read deadline**; do not add a timeout there. The Health 10 s bound is on the dashboard's own wait, not on that hop.
- Errors typed, never swallowed into empty results: the pages show an explicit "log unreadable" state, not an empty list.
- Logging via `logging.getLogger(__name__)`, no `print`.
- Every directly imported dependency is listed in `pyproject.toml`; a `pyproject.toml` edit needs a version bump (CI).
- Worktree lanes: each plan works in its own `.worktrees/<slug>`; PRs rebase-merged into `develop`; `main` is release-only; merging changes nothing until the `.app` is rebuilt and reinstalled. Planning records land from a records lane.
- Bugs before features (owner): any open bug found while building goes to an inserted phase ahead of the next feature phase.
- Verify before reporting success: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`; report real failures.
- Never touch the real `~/.local/state/macos-apps-mcp/` files from tests; the installed daemon is v0.14.3 and is not restarted until D-18.
- Mail: no change to the Mail adapter is planned; if the optional `receipt` key touches `AuditMiddleware`, it is not a Mail write and needs no device Mail proof, but keep the dry-run/no-native-call invariant.

## Sources

### Primary (HIGH confidence)
- Repo files read this session: `macos_apps_mcp/{daemon,tiers,registry,deploy,doctor,audit,eventkit,cli,runtime}.py`, `server.py:1-300,1480-1504`, `adapters/mail_recover.py:96-130,300-350,470-700`, `tests/{test_registry,conftest,test_daemon,test_import_layers}.py`, `tests/test_doctor.py:400-500`, `tests/test_doctor_deploy.py:120-180`, `tests/test_packaging.py`, `pyproject.toml`, `uv.lock:1005-1075,2455-2462`, `packaging/ren.lav.macos-apps-mcp.plist`, `.github/workflows/{version,ci}.yml`, `scripts/build_app.sh`, `docs/RELEASING.md`
- Installed libraries read: `uvicorn/server.py` (`startup`, `shutdown`, `_wait_tasks_to_complete`, `capture_signals`), `uvicorn/protocols/utils.py`, `uvicorn/middleware/proxy_headers.py`, `starlette/middleware/trustedhost.py`, `starlette/concurrency.py`, `mcp-1.29.0` and `fastmcp_slim-3.4.7` METADATA
- Probes (in `05-proto/`): dispatcher + restart (uvicorn 0.52.4, Python 3.14.5), Origin under Referrer-Policy (Chrome 155.0.8059.85), guard layer through `httpx.ASGITransport`
- `uv lock --offline` on a copy of the repo; `gsd-tools query package-legitimacy check`; `launchctl print`; baseline pytest runs
- `.claude/skills/sketch-findings-macos-apps-mcp/SKILL.md` and `references/{layout-and-navigation,adapters-and-health,audit-review,recovery}.md`

### Secondary / Tertiary
- Fetch spec behaviour for `Origin` under `no-referrer` — confirmed by the Chrome probe; other browsers `[ASSUMED]` (A1).

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — installed, locked, probed
- Architecture: HIGH — dispatcher, guard and restart proved end to end in probes
- Pitfalls: HIGH for C1-C8 (each reproduced or read); MEDIUM for browser variance (A1-A3)

**Research date:** 2026-10-21
**Valid until:** 2026-11-20 (uvicorn/starlette release often; re-run `05-proto/dispatch_client.py` if either is bumped before execution)
