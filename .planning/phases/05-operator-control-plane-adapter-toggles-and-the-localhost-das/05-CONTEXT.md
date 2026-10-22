# Phase 5: Operator Control Plane — Adapter Toggles and the Localhost Dashboard - Context

**Gathered:** 2026-10-21 (assumptions mode)
**Status:** Ready for planning

<domain>
## Phase Boundary

An operator who wants Mail but not Photos gets exactly that, and can see the server's grants,
usage, audit trail and recoverable backups without reading JSONL by hand. Requirements PLAT-01
and PLAT-02. Four success criteria (ROADMAP.md): (1) a config setting read at daemon start
enables and disables adapters per app; a disabled adapter's tools are absent from the tool list,
never registered-and-erroring, and `doctor` reports the active set; (2) a dashboard served by the
daemon shows grants and `doctor` output, `usage`, the audit trail and browsable recoverable-plane
backups, rendered without an SPA framework; (3) the dashboard exposes the adapter toggles, and a
toggle changed there is reflected by `doctor` and by tool presence after the daemon restarts;
(4) the dashboard answers on loopback only; a non-loopback bind is refused.

The design is fixed by the four sketches of 2026-09-28 (see canonical refs). Their ten hard
rules bind every page: two write actions only (adapter toggle, daemon restart); every write
checks Host, Origin and a per-session token; every read checks Host; each toggle and restart
writes an audit record with caller `dashboard`; the Outbound gate is shown locked, never a
switch; the restart bar says a restart drops open MCP connections; a non-loopback bind is
refused; every string from the audit trail and the receipts is escaped; a preview never reads as
a write; nothing on the page deletes or prunes a backup.

Out of this phase: the menubar companion (PLAT-04, v2), network transport and auth (PLAT-05,
v2), any grant-trigger endpoint, any clean-up or dedupe runner, an undo button, a JSON API.
</domain>

<decisions>
## Implementation Decisions

### Adapter toggle setting and gate (PLAT-01, criterion 1)
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

### Dashboard transport and security (PLAT-02, criteria 2 and 4)
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

### Rendering and data sources (criterion 2)
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
  rule 10). This supersedes the #126 comment of 2026-08-04 and the `docs/ROADMAP.md` floating
  note that asked for a clean-up button and a dedupe runner.
- **D-14:** Health runs `diagnose(request=False)` and Usage runs `usage_report(...)` in Starlette's
  thread pool (`run_in_threadpool`), never on the event loop and never with EventKit off the
  `run_native` worker. Health bounds its wait (about 10 s) and, when the worker is busy with an
  in-flight native call, renders the EventKit rows as "worker busy, a native call is in flight".
  A danger banner appears only for an **active** adapter whose grant is denied. `Open Settings`
  is a plain `x-apple.systempreferences:…` link (the browser asks to open System Settings); no
  endpoint. The Outbound row is locked and shows `macos-apps-mcp allow-send <adapters>` with Copy.

### Writes, restart, tests and the device proof (criterion 3)
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
- **D-19:** **Every dashboard request needs a page key** (owner, 2026-10-22; replaces the RESEARCH
  A5 / T-05-31 acceptance). The post-merge security review of #408 confirmed that
  `127.0.0.1:47632` is reachable by other macOS accounts and by sandboxed apps with network
  access, and from 05-03/05-04 the pages carry the form token and show the audit trail. The daemon
  keeps a key in a 0600 file in its 0700 state folder, stable across restarts. Every request,
  reads included, needs that key as an HttpOnly, `SameSite=Strict` cookie, set once by a link that
  only the operator's account can produce: a CLI role prints and opens it. `doctor` says that the
  dashboard needs the key and names the CLI command, but never shows the key; the key never
  reaches a log or the audit trail. A request without the key gets a refusal that names the
  command. One plan, 05-09, after 05-03 and before 05-04; 05-05's docs describe the key instead of
  the single-user assumption, and 05-07's device proof opens the dashboard through the link.
  — **Reversibility:** reversible; a code change before the 0.15.0 release.
- **D-20:** **An `adapters_off` file that exists but cannot be read turns every adapter off**
  (owner, 2026-10-22, from the post-merge review of #407), and the `doctor` note says so.
  Undecodable bytes are replaced, so a stray byte costs one name (listed as `adapters_unknown`)
  and never the server import; `allow_send` gets the same decoding and stays closed when
  unreadable. Landed by PR #410.

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
</decisions>

<specifics>
## Specific Ideas

- The sketch texts are the copy: "Turn an app off and its tools disappear after the daemon
  restarts."; "**2 changes wait for a restart.** Photos on, Music off. A restart drops open MCP
  connections for a moment."; "Never changed from this page — any website could send a request
  to 127.0.0.1. Change it in Terminal:"; "Preview only — nothing changed."; "No backup for this
  write. Recovery covers batch Mail writes — move, trash and dedupe."; "Every batch Mail write
  copies its messages to disk first. Nothing here is ever pruned."
- This Mac, 2026-10-21: installed daemon v0.14.3; `audit.jsonl` 5.2 MB / 1795 records and
  `audit.jsonl.1` 3.3 MB / 1141 records, 390 legacy middleware records without `dry_run`/`caller`;
  935 receipt folders, 188 MB, oldest 2026-08-03; `backup_usage()` 0.56 s; a daemon import
  0.9–1.4 s; `launchctl print` shows `exit timeout = 5`. Rotation at 5 MiB keeps one backup and
  overwrites it, so the next rotation drops about 600 plans while their backups stay.
- Record shapes: middleware `ts, tool, op, args, dry_run, caller, [session], target_id, before,
  after`; plan `{ts, tool:"mail_recover", op, phase:"plan", receipt, destination, backup_dir,
  targets:[{id, folder, fidelity?, account?, rowid?, backup?, status:"planned"}]}`; done
  `{ts, tool:"mail_recover", op, phase:"done", receipt, results:{id: status}}`.
  `find_receipt(receipt_id) -> (plan, outcomes)` scans the last 2000 lines of the current file
  and raises `NativeError` when the plan is not found.
- `deploy.allow_send` precedent: read current → write file → `launchctl kickstart -k
  gui/<uid>/<label>`; exit 0 prints "daemon restarted — reconnect your MCP client", else the
  "no daemon restarted" branch (`deploy.py:340-362`).
- The analyzer's three external-research items were settled by design, not researched: no
  `launchctl` from inside the job (D-16); Origin-or-`Sec-Fetch-Site` plus the token (D-08);
  `httpx.ASGITransport` instead of `TestClient` (D-17). The relaunch after a self-exit is proven
  on device in D-18.
</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design (the sketches of 2026-09-28; owner decisions)
- `.planning/sketches/MANIFEST.md` — the four sketches, their winners and the design direction
- `.planning/sketches/001-dashboard-shell/README.md` — frame D: Console list + detail, System pages
- `.planning/sketches/002-audit-review/README.md` — variant D: word diff, resolved args, raw lines collapsed
- `.planning/sketches/003-recovery-flow/README.md` — variant D: read-only recovery, ask-Claude undo prompt
- `.planning/sketches/004-toggles-and-health/README.md` — variant A: switch, pending chip, restart bar; Outbound locked
- `.planning/sketches/themes/default.css`, `.planning/sketches/_shared/base.css`, `.planning/sketches/_shared/shell.css` — the tokens, components and frame to port
- `.claude/skills/sketch-findings-macos-apps-mcp/SKILL.md` and its `references/*.md` — the same decisions as a local skill (git-ignored; rebuild with `/gsd-sketch --wrap-up` if lost): the ten hard rules, CSS patterns, HTML structures, "what to avoid"

### Architecture and conventions
- `CLAUDE.md` § "Architecture (don't drift)" — tiers gated at registration; `run_native` single worker; no cross-adapter reach; the shim↔daemon hop has no read deadline
- `macos_apps_mcp/tiers.py`, `macos_apps_mcp/deploy.py` (`allow_send_file`, `allow_send`, `is_daemon_role`), `macos_apps_mcp/registry.py` (`outbound_status`, `dry_run_defaults`) — the gate pattern D-01..D-03 twin
- `macos_apps_mcp/daemon.py` — socket ownership, the shim, `serve()`
- `docs/DAEMON.md` § 5 "Outbound (send) mode under the daemon" — why a home-pinned file, not an env var; the kickstart
- `.planning/codebase/CONVENTIONS.md`, `.planning/codebase/TESTING.md` — style, seams, fail-closed suite
- `docs/RELEASING.md` — the release procedure for D-18

### Prior decisions this phase builds on
- `.planning/phases/03.1-bug-fixes-device-report-findings-before-any-feature/03.1-CONTEXT.md` D-01..D-06 — the `dry_run` and `caller` audit fields (#222) the dashboard reads
- `.planning/phases/02-gate-close-fail-closed-suite-and-device-sweep/02-CONTEXT.md` D-09 — the release-at-phase-close shape
- `.planning/phases/01-gate-land-the-spiked-architecture-cuts/01-CONTEXT.md` D-05, D-06 — release vs dev-build daemon proofs

### Issues
- #126 — the dashboard's scope history; D-13 supersedes its 2026-08-04 clean-up and dedupe additions
- #163 — retention is keep-forever; `doctor` backup line
- #222 (closed) — resolved `dry_run` and `caller` on every audit record
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `tiers.allow_send` + `deploy.allow_send_file` / `_ALLOW_SEND_FILE`: the env-then-file, daemon-role-only gate D-01 copies.
- `registry.outbound_status()` and `doctor`'s `outbound_pending`: the configured-vs-registered view D-03 mirrors.
- `registry.dry_run_defaults()`: resolves `dry_run` for legacy records (D-12).
- `audit.audit_write`, `audit_read`, `usage_read`, `usage_report`: the write path for dashboard records and the data for Usage.
- `adapters/mail_recover.find_receipt`, `backup_usage`, the plan/done record shapes: the Backups and batch-detail data.
- `doctor.diagnose`, `deploy.grant_report`, `deploy.agent_status`, `doctor._version`, `_build_stamp`: Health and the footer.
- `daemon.bind_socket`: the owned-bind pattern the TCP guard follows; `deploy.allow_send`'s file write with `mkdir(mode=0o700)`.
- Starlette 1.6.0 (transitive via mcp) and httpx 0.28.1 are installed; `starlette.concurrency.run_in_threadpool`, `TrustedHostMiddleware`, `httpx.ASGITransport`.

### Established Patterns
- Every gate reads a process-start fact (env or argv); registration happens at import; a gated-off tool keeps its record with `registered=False`.
- Home-pinned state files (`~/.local/state/macos-apps-mcp/...`), never XDG, so daemon, CLI and shim agree.
- All native access through `runtime.run_native` on the single `max_workers=1` worker; a bulk Mail pass can hold it for hours.
- Unit tests mock at the adapter boundary; conftest seals `run_osascript` and isolates `XDG_STATE_HOME` and the `allow_send` file; tool absence is proven in a subprocess per gate mode.
- Every directly imported dependency is listed in `pyproject.toml`; any pyproject edit needs a version bump (CI).
- Planning records land by PR from a records lane; code by PR from its own worktree; `develop` is rebase-merged; `main` is release-only.

### Integration Points
- `server._tool` (`server.py:161-165`): the `registered` expression gains the adapter AND.
- `tiers.py`: `adapter_enabled(name)`; `deploy.py`: the `adapters_off` file constant and reader.
- `registry.py`: `adapter_status()`; `outbound_status()["configured"]` ANDs `adapter_enabled`.
- `doctor.diagnose()`: `deployment.adapters`, `adapters_off`, `adapters_pending`, `adapters_unknown`, `dashboard`; `_automation_surfaces` and the EventKit request skip OFF adapters.
- `daemon.serve()`: the TCP bind through the loopback guard, the ASGI dispatcher, `run(sockets=[...])`, the module-level `Server` for D-16, the lazy `dashboard` import.
- New `macos_apps_mcp/dashboard.py` (+ `dashboard.css`, `dashboard.js`); new reader in `audit.py`.
- `pyproject.toml` (`starlette`, version 0.15.0), `packaging/Info.plist`, `uv.lock` root version line, `CHANGELOG.md`.
- `tests/conftest.py` (file patch), `tests/test_registry.py` (gate harness), new dashboard, dispatcher, doctor tests.
- `docs/DAEMON.md` (adapters file, dashboard, restart), `README.md`.
</code_context>

<deferred>
## Deferred Ideas

- A `macos-apps-mcp adapters [on|off <name>…]` CLI role beside `allow-send` (D-05) — add if the file-plus-kickstart fallback proves too thin.
- `Open` / `Reveal` endpoints for `.eml` backups under the toggle's token check, limited to the backup root (D-13).
- A live "watching audit.jsonl" update by poll or server-sent events (D-13).
- Grant-trigger endpoints that shell `open x-apple.systempreferences:…` and re-probe (#126 body) — a plain link covers it (D-14).
- A backup clean-up button and a dedupe runner (#126 comment, 2026-08-04) — ruled out by sketch rule 10 and #163; dedupe stays the `dedupe-mail` CLI.
- A JSON API for the menubar companion (PLAT-04, v2) — the pages are the API for now.
- A dashboard port override — an env var cannot reach a launchd daemon; a plist key or state file is the only route, and nothing asks for it yet.
- Network transport, auth and dashboard/MCP auth parity (PLAT-05, v2, #127).
- A graceful restart that waits for an in-flight Mail batch before exiting (D-16 accepts the kill, as `kickstart -k` does today).

### Reviewed Todos (not folded)
None — `todo.match-phase 5` found no matching todos.
</deferred>

---

*Phase: 05-operator-control-plane-adapter-toggles-and-the-localhost-das*
*Context gathered: 2026-10-21*
