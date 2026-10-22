---
phase: 05-operator-control-plane-adapter-toggles-and-the-localhost-das
plan: 02
subsystem: dashboard-transport
tags: [dashboard, uvicorn, asgi, starlette, csrf, dns-rebinding, loopback, csp]
requires:
  - phase: 05-operator-control-plane-adapter-toggles-and-the-localhost-das
    provides: "05-08 starlette>=0.48 declaration and the 0.15.0 bump on develop"
provides:
  - "one uvicorn Server on the UDS and a loopback TCP socket behind daemon.make_dispatcher; MCP only on the UDS"
  - "daemon.assert_loopback, daemon.bind_dashboard, DASHBOARD_HOST/DASHBOARD_PORT, dashboard_state"
  - "macos_apps_mcp/dashboard/ package: Guard, escape-by-default html helper, build_app, /static allow-list, Console frame, Usage page"
  - "dashboard.css ported from the sketches, dashboard.js (Copy buttons only)"
  - "bundle import smoke covers macos_apps_mcp.dashboard"
affects: [05-03, 05-04, 05-05, 05-07]
tech-stack:
  added: []
  patterns:
    - "pure-ASGI Guard wrapper: Host on every request, Origin + token on every unsafe method, security headers on every response"
    - "fail-closed dispatcher: only lifespan and server==(path, None) scopes reach MCP"
    - "escape-by-default Safe/esc/h/join; no template engine"
    - "fixed static dict read at import; no path from the URL"
key-files:
  created:
    - macos_apps_mcp/dashboard/__init__.py
    - macos_apps_mcp/dashboard/guard.py
    - macos_apps_mcp/dashboard/html.py
    - macos_apps_mcp/dashboard/usage.py
    - macos_apps_mcp/dashboard/dashboard.css
    - macos_apps_mcp/dashboard/dashboard.js
    - tests/test_dashboard_guard.py
    - tests/test_daemon_dispatch.py
  modified:
    - macos_apps_mcp/daemon.py
    - tests/test_daemon.py
    - scripts/build_app.sh
    - tests/test_packaging.py
    - CHANGELOG.md
decisions:
  - "D-06: dispatcher keyed on scope server[1] is None, never on client (RESEARCH C4); dash_app None answers 404"
  - "D-07: bind outcome lives in daemon.dashboard_state (05-01 owns deploy.py); 05-05 makes doctor report it"
  - "D-08/C1: Referrer-Policy same-origin; Origin: null refused; token parsed with parse_qs under an 8 KiB cap (C8)"
  - "Guard checks every method except GET and HEAD, not only POST (Rule 2)"
  - "Phone sidebar is a horizontal strip, group headings hidden (the sketch's open item)"
requirements: [PLAT-02]
requirements-completed: [PLAT-02]
status: complete
commits: 8
plan_head_before: 65379a2d7b1124612079dc9ecf19ef5e01f72480
plan_head_after: a2f8ad6c52509a91689afa500c64565fe5d03cce
pr: 408
merge_sha: a2f8ad6c52509a91689afa500c64565fe5d03cce
actuals:
  tokens: 12700
  tasks: 4
  commits: 8
coverage:
  - id: D1
    description: "The real daemon.serve() answers /usage on loopback TCP (guarded, security headers) and keeps MCP on the UDS: unsigned POST /mcp is 403 from the Guard, GET /mcp 404, no jsonrpc body, ping over the UDS works"
    requirement: PLAT-02
    verification:
      - kind: integration
        ref: "tests/test_daemon.py#test_serve_two_concurrent_sessions"
        status: pass
    human_judgment: false
  - id: D2
    description: "Dispatcher routes MCP to lifespan and UDS scopes only; every other scope fails closed to the dashboard or a 404"
    requirement: PLAT-02
    verification:
      - kind: unit
        ref: "tests/test_daemon_dispatch.py#test_dispatcher_routes_mcp_to_the_unix_socket_only"
        status: pass
    human_judgment: false
  - id: D3
    description: "Non-loopback binds are refused (0.0.0.0, LAN, localhost, ::, empty); a taken port leaves MCP serving and sets dashboard_state to 'not bound: ...'"
    requirement: PLAT-02
    verification:
      - kind: unit
        ref: "tests/test_daemon_dispatch.py#test_assert_loopback_refuses_everything_but_a_loopback_literal"
        status: pass
      - kind: unit
        ref: "tests/test_daemon.py#test_serve_keeps_mcp_up_when_the_dashboard_port_is_in_use"
        status: pass
    human_judgment: false
  - id: D4
    description: "Guard: foreign Host 400 on every route; foreign/null/absent Origin, bad or missing token and an oversize body 403; five security headers on 200/400/403/404"
    requirement: PLAT-02
    verification:
      - kind: unit
        ref: "tests/test_dashboard_guard.py"
        status: pass
    human_judgment: false
  - id: D5
    description: "Stored-XSS escape on /usage and static-path traversal refusal"
    requirement: PLAT-02
    verification:
      - kind: unit
        ref: "tests/test_dashboard_guard.py#test_usage_escapes_tool_names"
        status: pass
      - kind: unit
        ref: "tests/test_dashboard_guard.py#test_static_allow_list_has_two_entries_and_no_traversal"
        status: pass
    human_judgment: false
  - id: D6
    description: "The page looks like the sketches in a real browser (light and dark, phone strip, the styled <meter> bar)"
    verification: []
    human_judgment: true
    rationale: "No browser was driven in this run; the markup, CSP-clean structure and asset serving are tested, the rendering is not"
  - id: D7
    description: "A same-origin form POST carries a real Origin in Safari and Firefox, and navigator.clipboard works on http://127.0.0.1 in Safari (RESEARCH A1, A2)"
    verification: []
    human_judgment: true
    rationale: "Only Chrome 155 was probed; 05-07's device proof in the owner's browser is the check"
duration: 38min
completed: 2026-10-22
---

# Phase 5 Plan 02: The daemon serves a guarded dashboard on 127.0.0.1:47632 — PR #408

The daemon now answers a browser on `http://127.0.0.1:47632` with a styled Usage page behind a Host/Origin/token Guard, while the MCP endpoint stays on the unix socket. PR #408 was rebase-merged into develop; the last of its 8 commits is `a2f8ad6`.

## Performance

- **Duration:** about 38 min (first commit 10:30, merge 10:48, local time)
- **Tasks:** 4 of 4
- **Files:** 13 changed (8 new), +1108 / -5
- **Tests:** 2229 passed before, 2299 after (full run); 2284 passed and 15 skipped under `MACOS_APPS_READ_ONLY=1`; 2294 passed and 5 skipped under `MACOS_APPS_ALLOW_SEND=mail`

## Accomplishments

- **Transport (D-06, D-07).** `daemon.serve()` binds the UDS, then tries `bind_dashboard("127.0.0.1", DASHBOARD_PORT)`, and runs one `uvicorn.Server` over both sockets with `proxy_headers=False`. `make_dispatcher` sends lifespan and `server == (path, None)` scopes to MCP and everything else to the dashboard (or a plain 404 when no dashboard is mounted). A taken port is logged, `dashboard_state` becomes `not bound: <reason>`, and MCP keeps serving.
- **Guard (D-08).** Port of `05-proto/guard_proto.py` with `Referrer-Policy: same-origin`. A stale token answers a 403 that says to reload the page (RESEARCH Pitfall 3).
- **Escaping (D-09).** `Safe`, `esc`, `h`, `join`; every interpolated value is escaped. A tool name `<script>alert(1)</script>` renders as `&lt;script&gt;` on `/usage`.
- **Assets and frame (D-10, D-11).** `dashboard.css` is the sketch theme, shared components and frame, with every inline width turned into a class and the usage bar into a `<meter>`. `dashboard.js` holds one delegated `data-copy` listener with an `execCommand` fallback. `/static/{name}` serves a two-entry dict read at import. `page()` renders the Console frame with a sidebar entry list (`SIDEBAR`) that 05-03, 05-04 and 05-05 extend. `/` redirects to `/usage` until 05-04.
- **Bundle (D-10).** The `.app` import smoke imports `macos_apps_mcp.dashboard`; the wheel holds both assets (count 2 verified with `uv build --wheel`).

## Task Commits

Hashes are the ones on develop after the rebase-merge.

| Task | Commit | Message |
| ---- | ------ | ------- |
| 1 RED | 2564e3c | test(dashboard): the daemon serves /usage on loopback TCP, MCP on the UDS only |
| 1 GREEN | b03a979 | feat(dashboard): the daemon serves a guarded /usage page on 127.0.0.1 |
| 2 RED | 7fde843 | test(dashboard): static assets and the frame |
| 2 GREEN | ada9eb5 | feat(dashboard): sketch styles, Copy script and the Console frame |
| 3 | fbedeca | test(dashboard): guard, header, escape, traversal and loopback matrix |
| 4 | 6f29cbb | chore(build): the bundle smoke imports the dashboard package |
| 4 | 49a8389 | docs(changelog): the localhost dashboard |
| review | a2f8ad6 | fix(dashboard): the Guard checks Origin and token on every method but GET and HEAD |

## TDD Gate Compliance

- **Task 1 RED:** `test_serve_two_concurrent_sessions` failed on the planned assertion (`dashboard_state` stayed `None`, so the `http://127.0.0.1:` check failed). The fixture used `raising=False` in the RED commit only, so the missing `DASHBOARD_PORT` attribute did not crash every test in the module; GREEN removed it. Semantic assessment: target test executed, failed on the intended assertion, no fixture or import fault. `gsd_run check tdd-red-evidence` was not run: the plan is `type: execute`, not `type: tdd`.
- **Task 2 RED:** `test_static_assets_and_the_console_frame` failed with a 404 on `/static/dashboard.css`, the planned assertion.
- **Task 3:** every case already passed against the Task 1-2 code, so no case was red first and no code changed in that task. To prove the matrix is not vacuous, seven mutations were applied and reverted, one at a time; each turned the suite red: no Host check, `null` accepted as an Origin, `X-Frame-Options` dropped, body cap removed, dispatcher routing every scope to MCP, `assert_loopback` removed from `bind_dashboard`, escaping removed.
- RED precedes GREEN in git for Tasks 1 and 2.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] The Guard checked Origin and token only on POST**
- **Found during:** inline self-review in Task 4
- **Issue:** a later PUT, PATCH or DELETE route would have been served with no Origin or token check; D-08 names POST, the dashboard has no such route yet.
- **Fix:** the check applies to every method except GET and HEAD. Three parametrized tests (PUT, DELETE, PATCH from a foreign Origin answer 403).
- **Files modified:** `macos_apps_mcp/dashboard/guard.py`, `tests/test_dashboard_guard.py`
- **Commit:** a2f8ad6

### Other notes

- **Commit trailer.** The repo rules named `Claude Opus 5.5`; the plan says to use the attribution trailer the session reminder gives, which is `Claude Sonnet 5.5`. All commits carry the latter.
- **Rebases.** The branch was rebased twice onto develop while CI ran: once for 05-08 (`ce8bb3b`), once for 05-01 (`65379a2`). Neither rebase stopped on CHANGELOG.md; the dashboard bullet is last under `### Added`, after 05-01's first bullet. The full local suite was rerun after each rebase.
- **Plan-level `plan_head_before`.** The ledger recorded `d053ec1` at the start; the frontmatter uses `65379a2`, the base of the rebased commits that are on develop.

**Total deviations:** 1 auto-fixed (Rule 2). **Impact:** none on scope; the Guard is stricter than D-08 requires.

## Merge gate (D-09)

`git show origin/develop:pyproject.toml | grep -c '"starlette>=0.48",'` printed `1` at 2026-10-22T08:40:07Z, 08:43:55Z and 08:48:19Z (UTC). 05-08 had merged before the PR was opened. The required `check` job passed on the final head (`fd2f87c` before merge); no dropped-runner failure occurred. PR body: `Part of #126`, no closing keyword.

`git diff --name-only origin/develop...HEAD` listed none of `pyproject.toml`, `uv.lock`, `packaging/Info.plist`.

## Verification (five local summary lines, after the last rebase)

- `uv run pytest -q`: 2299 passed
- `MACOS_APPS_READ_ONLY=1 uv run pytest -q`: 2284 passed, 15 skipped
- `MACOS_APPS_ALLOW_SEND=mail uv run pytest -q`: 2294 passed, 5 skipped
- `uv run ruff check .`: no issues
- `uv run ruff format --check .`: 117 files already formatted

Acceptance checks run and passed: `records-present`; the three daemon `def` lines (3); `proxy_headers=False` once; `same-origin` in the Guard (5); no `server` import in `dashboard/`; `macos_apps_mcp.dashboard` absent from `sys.modules` after importing `macos_apps_mcp.server`; `onclick` count 0 in the JS; `prefers-color-scheme` and the 700px media query present in the CSS; the bundle-smoke string present once in each of `scripts/build_app.sh` and `tests/test_packaging.py`; the CHANGELOG bullet last under `### Added`; the wheel holds both assets; `lsof -nP -iTCP:47632 -sTCP:LISTEN` showed nothing while the suite ran; the lane `.worktrees/dashboard-transport` and branch were removed after the merge.

## Code review (inline self-review of `origin/develop...HEAD`)

No sub-agent was available, so the review was done inline against PLAT-02, D-06..D-11 and RESEARCH C1, C4, C6, C8.

- One finding, fixed: the POST-only check (Deviation 1).
- Checked and found sound: MCP is unreachable over TCP (dispatcher keyed on `server[1]`, `proxy_headers` off, unsigned `POST /mcp` refused by the Guard before routing); `bind_dashboard` refuses before creating a socket; the body read in the Guard is bounded and replayed; the static route builds no path from the URL; `serve()` closes both sockets and unlinks the UDS path in `finally`; the stdio server never imports the dashboard; the dashboard never imports `server`.
- Not verified, passed to the independent review and to 05-07: browser behaviour for A1 and A2, and the visual result of `dashboard.css`.

## Known Stubs

- `GET /` redirects to `/usage` by design; 05-04 replaces it with the write list. Not added to the broken-windows ledger because the plan names its resolver.

## Issues Encountered

- A one-off read-only check of `/usage` outside pytest read this Mac's real `usage.jsonl` (no write, no output kept). The test suite itself uses the isolated state dir.

## Next Phase Readiness

- 05-03 (adapters page and toggle) can use `html.page`, `SIDEBAR`, `Guard`, `app.state.token` and `app.state.port`.
- 05-05 reads `daemon.dashboard_state` in `doctor`.
- 05-07 must check, in the owner's own browser, that the first toggle is not answered "Forbidden origin" (A1) and that Copy works (A2), and look at the page once in light and dark.

## Self-Check: PASSED

- Files exist on develop: `macos_apps_mcp/dashboard/{__init__,guard,html,usage}.py`, `dashboard.css`, `dashboard.js`, `tests/test_dashboard_guard.py`, `tests/test_daemon_dispatch.py`.
- Merge commit `a2f8ad6` is an ancestor of `origin/develop`; `origin/develop` holds `def bind_dashboard(` and `def make_dispatcher(` (2) and the `starlette>=0.48` line (1).
- `gh pr view 408` state is `MERGED`; the body has no `Closes`, `Fixes` or `Resolves`.
