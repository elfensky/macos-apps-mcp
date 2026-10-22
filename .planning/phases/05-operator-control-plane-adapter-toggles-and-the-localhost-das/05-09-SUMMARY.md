---
phase: 05-operator-control-plane-adapter-toggles-and-the-localhost-das
plan: 09
subsystem: dashboard-page-key
tags: [dashboard, page-key, cookie, guard, cli, doctor, d-19, pm-12]
status: complete
requires:
  - phase: 05-operator-control-plane-adapter-toggles-and-the-localhost-das
    provides: "05-02 Guard and build_app, 05-03 adapters page, write_adapters_off, test harnesses"
provides:
  - "deploy.dashboard_key(*, create=False) -> str | None, deploy._DASHBOARD_KEY_FILE, deploy._KEY_RE, deploy._atomic_write(path, text)"
  - "deploy.dashboard(argv) and the `dashboard` CLI role (cli._ROLES)"
  - "dashboard.guard: KEY_COOKIE, KEY_PATH, KEY_MAX_AGE, NEEDS_KEY, KEY_UNUSABLE; Guard(app, *, port, token, key)"
  - "dashboard.build_app(*, port, token, key, restart=None)"
  - "doctor deployment.dashboard_note (daemon role only)"
  - "tests/_dashboard.py: PORT, TOKEN, KEY, HOST, ORIGIN, FORM, COOKIE, build, request, get"
affects: [05-04, 05-05, 05-06, 05-07]
tech-stack:
  added: []
  patterns:
    - "key checked in the one Guard after Host, before routing; the key lives in the Guard only, never on app.state"
    - "cookie scan on raw header bytes; any matching cookie of the name passes"
    - "fail closed: unusable key file -> 503 on every dashboard request, never rewritten"
    - "browser opened through osascript stdin (webbrowser.MacOSXOSAScript), never a process argument"
key-files:
  created:
    - tests/_dashboard.py
    - tests/test_dashboard_key.py
  modified:
    - macos_apps_mcp/deploy.py
    - macos_apps_mcp/daemon.py
    - macos_apps_mcp/cli.py
    - macos_apps_mcp/doctor.py
    - macos_apps_mcp/dashboard/guard.py
    - macos_apps_mcp/dashboard/__init__.py
    - tests/conftest.py
    - tests/test_daemon.py
    - tests/test_dashboard_guard.py
    - tests/test_dashboard_adapters.py
    - CHANGELOG.md
key-decisions:
  - "D-19: one key in a 0600 file in the 0700 daemon folder, written only when absent; every request but GET /key needs it as a cookie"
  - "D-19 fail closed: only a urlsafe token of 32+ characters is a key; an existing file is never rewritten; 503 on every request while it is unusable"
  - "D-19: `macos-apps-mcp dashboard` opens the link with webbrowser.MacOSXOSAScript('default').open (stdin to osascript), not `open` or webbrowser.open"
  - "T-05-44 accepted: browsers send the cookie to every 127.0.0.1 port (RFC 6265 section 8.5)"
requirements-completed: [PLAT-02]
requirements: [PLAT-02]
pr: 415
commits: 7
plan_head_before: e3c0d1f0550cdb4abe4055374588a0a93388ea86
plan_head_after: 6db18c9245482cd5378dd2a5e6edd45e467085cf
actuals:
  tokens: 40000
  tasks: 4
  commits: 7
completed: 2026-10-22
---

# Phase 5 Plan 09: Page key Summary

Every dashboard page needs the page key (D-19) — PR #415, rebase-merged to `develop` with the required `check` green. Part of #126.

## What landed

- **Key file.** `deploy.dashboard_key(create=True)` runs once at daemon start. It writes `secrets.token_urlsafe(32)` through `_atomic_write` (temp file, fsync, `os.replace`) only when the file is absent. The file is 0600 and the folder 0700, set again at every start. `write_adapters_off` now calls the same `_atomic_write`; its 05-03 test passes unchanged.
- **Guard.** Order is Host (400), no key (503), `GET /key` link, cookie check (403), then the unchanged Origin and form-token checks. Cookies are scanned on raw header bytes with `hmac.compare_digest`; any cookie named `macos_apps_mcp_key` that equals the key passes. The link answers 303 to `/` with `macos_apps_mcp_key=<key>; HttpOnly; Max-Age=34560000; Path=/; SameSite=strict`. A bad `k` answers the 403 with no cookie. All responses carry the five security headers.
- **Daemon.** `serve()` passes `key=deploy.dashboard_key(create=True)` to `build_app` and runs uvicorn with `access_log=False`.
- **CLI role.** `macos-apps-mcp dashboard` reads the key file only, prints the link and opens it through `webbrowser.MacOSXOSAScript('default').open`. Without a usable key it prints the path and the remedy to stderr and exits 2. It prints a hint when the opener returns False.
- **doctor.** In the daemon role, `deployment.dashboard_note` says every page needs the page key and the USER runs `macos-apps-mcp dashboard`. It never reads the key file.
- **Tests.** `tests/_dashboard.py` is the one request helper (fixed fake key and cookie). The guard and adapters harnesses moved onto it with every assertion kept, including the 05-03/#413 `_OneShot` restart fake. `tests/test_dashboard_key.py` has 44 tests: key file lifecycle and modes, every unusable-file case, Host before key, the cookie matrix, tossed duplicates, non-ASCII cookie bytes, the form token kept, no key in pages, audit or usage, the CLI role, and the doctor note. `test_serve_two_concurrent_sessions` drives the real `serve()` over TCP (key file modes, keyless 403, link 303 and cookie, cookie GET 200, `/mcp` still unreachable, no key in captured output).

## Commits (on develop, after the rebase merge)

| Task | Hash | Message |
| ---- | ---- | ------- |
| 1 RED | 4174a13 | test(dashboard): the page key opens the dashboard end to end |
| 1 GREEN | 62af2ae | feat(dashboard): every request needs the page key; the link sets it |
| 2 RED | 2297f6a | test(dashboard): the page key fails closed and leaks nowhere |
| 2 GREEN | bed369d | feat(dashboard): an unusable page key refuses every request |
| 3 RED | 251c5fe | test(cli): the dashboard role prints and opens the page-key link |
| 3 GREEN | c74a480 | feat(cli): macos-apps-mcp dashboard opens the page with its key; doctor names it |
| 4 | 6db18c9 | docs(changelog): the dashboard page key |

## Verification

Baseline (before the change) and after:

| Run | Baseline | After |
| --- | -------- | ----- |
| `uv run pytest -q` | 2337 passed, 102 deselected | 2381 passed, 102 deselected |
| `MACOS_APPS_READ_ONLY=1 uv run pytest -q` | 2322 passed, 15 skipped, 102 deselected | 2366 passed, 15 skipped, 102 deselected |
| `MACOS_APPS_ALLOW_SEND=mail uv run pytest -q` | 2331 passed, 6 skipped, 102 deselected | 2375 passed, 6 skipped, 102 deselected |
| `uv run ruff check .` | | All checks passed |
| `uv run ruff format --check .` | | 122 files already formatted |

- Acceptance greps: `dashboard_key(create=True)` 1, `access_log=False` 1, `KEY_COOKIE = "macos_apps_mcp_key"` 1, `hmac.compare_digest` 3 in guard.py, `def _atomic_write(` 1 and `_atomic_write(` 3, `"dashboard",` in cli.py 1, `MacOSXOSAScript("default").open(` 1, `webbrowser.open(` 0, `Dashboard page key` in CHANGELOG 1, token-budget test 1 passed.
- `grep -rl -e "build_app(" -e "Guard(" tests/` lists `tests/_dashboard.py`, `tests/test_dashboard_guard.py` (its `_echo_app` and mid-body cases pass `key=`). No other file needed to move. `tests/test_dashboard_key.py` builds apps only through the helper.
- The real `~/.local/state/macos-apps-mcp/daemon/dashboard_key` and `adapters_off` were absent before and after the suite. The installed daemon was never touched, and no test bound port 47632.
- PR #415 files name neither `pyproject.toml` nor `uv.lock`; the body says `Part of #126` and holds no closing keyword. The lane and branch are removed; `origin/develop` holds both `def dashboard_key(` and `def dashboard(argv`.

## Code review (inline self-review of origin/develop...HEAD)

No sub-agent tool was available, so the review was done inline against the plan, D-08, D-17, D-19 and PM-12. No open finding.

- **Guard order.** Host check first (foreign Host answers 400 for `/key` too); then the unusable-key 503; then the `/key` link; then the cookie; then Origin and token. `/key` is exempt only for a GET of that exact decoded path; HEAD and other methods of `/key` need the cookie. Tests cover every route, HEAD, `/static`, unknown paths and a token-without-cookie POST.
- **Key reaching a log, page, audit or usage record, `doctor` or a process argument.** uvicorn `access_log=False`; no `log.` call in `dashboard/`; refusals are constant text and echo no request value; the key is held by the Guard only; `doctor` builds a constant note; the CLI passes the URL through `osascript` stdin. Tests assert absence from captured output, the `doctor` JSON, page bodies, `audit.jsonl` and `usage.jsonl`.
- **Fail-closed paths.** Absent file without `create`, empty, short, bad-character, unreadable, directory and failed-write cases all give None; the existing file is never rewritten or chmod-ed when invalid; the Guard answers 503 and MCP keeps serving. A non-ASCII cookie byte is a mismatch, never a 500 (raw-bytes scan).
- **Residual risk (accepted, T-05-44).** The cookie reaches any 127.0.0.1 port the operator's browser opens. The history entry of the link stays in the operator's browser profile; the remedy is to remove the key file and restart the daemon. Same-account processes can read the key file (T-05-49, accepted).

## Deviations from Plan

**1. [Minor] conftest grep count.** The acceptance criterion `grep -c "_DASHBOARD_KEY_FILE" tests/conftest.py` expects `1`, and the plan also asks to name the constant in the module docstring, so the file holds 2 matching lines (docstring and `setattr`). Both plan instructions are met; the count criterion cannot hold with both.

**2. [Rule 3 - Blocking] doctor test stub.** `doctor.diagnose()` reaches `runtime.tracked_run` (pgrep) through the automation surfaces, which the conftest seam guard refuses. The new doctor tests fake `runtime.tracked_run`, as `tests/test_doctor_deploy.py` does.

**Total deviations:** 2 (1 count mismatch inside the plan, 1 test stub). **Impact:** none on behavior.

## Known Stubs

None.

## Threat Flags

None beyond the plan's register. New surface is `GET /key` on the existing dashboard listener, covered by T-05-40 to T-05-47.

## Notes for the next plans

- 05-04 and later dashboard tests must use `tests/_dashboard.py` (`build`, `request`, `get`) and must not read the real key file.
- 05-05 documents the key, the `dashboard` command and the rotation (remove the file, restart the daemon). 05-07 proves it on the installed release. The vault journal bullet for #415 is logged.

## Self-Check: PASSED

Created files exist (`tests/_dashboard.py`, `tests/test_dashboard_key.py` on `develop`), all seven commits are on `origin/develop`, the PR is MERGED, and the lane is removed.
