---
phase: 05-operator-control-plane-adapter-toggles-and-the-localhost-das
plan: 03
subsystem: dashboard-adapters
tags: [dashboard, adapters, toggle, restart, launchd, audit, csrf, tcc]
requires:
  - phase: 05-operator-control-plane-adapter-toggles-and-the-localhost-das
    provides: "05-01 deny-list (tiers.adapters_off, registry.adapter_status) and 05-02 Guard, html.page, SIDEBAR, app.state.token"
provides:
  - "deploy.write_adapters_off(names): atomic adapters_off writer (temp file, fsync, os.replace, directory 0700)"
  - "GET/POST /adapters and POST /restart behind the one Guard; audit records tool=dashboard op=toggle|discard|restart"
  - "daemon.restart(server, *, timer, delay) and _restart_armed; serve() passes restart= to build_app"
  - "dashboard.grants: ADAPTER_GRANTS and grant_state(identities, adapter, client, *, complete)"
  - "html.page(refresh=...), the Adapters sidebar entry and its badge"
affects: [05-04, 05-05, 05-06, 05-07, 05-09]
tech-stack:
  added: []
  patterns:
    - "switch as a submit button in a POST form carrying the token: works with no JS"
    - "restart hook handed to build_app; the route answers first, a BackgroundTask flags the Server after the body"
    - "one watchdog (os._exit after 3 s) per process; launchd KeepAlive relaunches"
    - "lock the switches (409) when the setting cannot be changed truthfully: env override, unreadable file"
key-files:
  created:
    - macos_apps_mcp/dashboard/adapters.py
    - macos_apps_mcp/dashboard/grants.py
    - tests/test_dashboard_adapters.py
  modified:
    - macos_apps_mcp/deploy.py
    - macos_apps_mcp/daemon.py
    - macos_apps_mcp/dashboard/__init__.py
    - macos_apps_mcp/dashboard/html.py
    - macos_apps_mcp/dashboard/dashboard.css
    - tests/test_daemon_dispatch.py
    - CHANGELOG.md
key-decisions:
  - "D-15: one audit record per toggle, discard and restart, written with audit.audit_write only (no middleware, no usage tally)"
  - "D-16 as amended by RESEARCH C2: the Server stays local to serve(); a closure carries it to the restart route"
  - "D-20: an unreadable adapters_off file (or the env override) locks the switches and answers 409 on toggle and Discard; Discard is not offered in that state"
  - "grant_state returns unknown (no chip) when a TCC database could not be read, never 'not asked'"
requirements: [PLAT-01, PLAT-02]
requirements-completed: [PLAT-01, PLAT-02]
status: complete
commits: 7
plan_head_before: c33e7ba6d68285367fcc172049da59c57ef6cd23
plan_head_after: 59591305ced10ddd69257c53f466ac0f186ab43c
pr: 412
merge_sha: 59591305ced10ddd69257c53f466ac0f186ab43c
actuals:
  tokens: 9500
  tasks: 4
  commits: 7
coverage:
  - id: D1
    description: "A guarded POST turns an adapter off or on, rewrites adapters_off atomically with known names only, and appends one dashboard audit record; unknown name or bad value is 400 with no write"
    requirement: PLAT-01
    verification:
      - kind: unit
        ref: "tests/test_dashboard_adapters.py#test_toggle_off_writes_the_file_and_one_dashboard_audit_record"
        status: pass
      - kind: unit
        ref: "tests/test_dashboard_adapters.py#test_toggle_unknown_adapter_or_bad_value_is_400_and_changes_nothing"
        status: pass
    human_judgment: false
  - id: D2
    description: "The atomic writer keeps the old file and leaves no temp file when os.replace fails; the directory is 0700; GET is side-effect free"
    requirement: PLAT-02
    verification:
      - kind: unit
        ref: "tests/test_dashboard_adapters.py#test_atomic_write_failure_keeps_the_old_file_and_leaves_no_temp"
        status: pass
      - kind: unit
        ref: "tests/test_dashboard_adapters.py#test_get_is_side_effect_free"
        status: pass
    human_judgment: false
  - id: D3
    description: "Restart answers the restarting page first, then flags the Server and arms one 3 s watchdog; a second call arms none; token and POST are required (403, 405, 503 without a hook)"
    requirement: PLAT-02
    verification:
      - kind: unit
        ref: "tests/test_daemon_dispatch.py#test_restart_flags_the_server_and_arms_one_watchdog_once"
        status: pass
      - kind: unit
        ref: "tests/test_dashboard_adapters.py#test_restart_answers_the_restarting_page_then_runs_the_hook_once"
        status: pass
    human_judgment: false
  - id: D4
    description: "Discard writes the running set back; the env override and the D-20 unreadable-file state lock the switches and answer 409 without writing"
    requirement: PLAT-02
    verification:
      - kind: unit
        ref: "tests/test_dashboard_adapters.py#test_unreadable_file_reads_every_switch_off_and_refuses_writes"
        status: pass
      - kind: unit
        ref: "tests/test_dashboard_adapters.py#test_env_override_disables_the_switches_and_refuses_writes"
        status: pass
    human_judgment: false
  - id: D5
    description: "Grant chips, tool and call counts, the locked Outbound row (no form, no input), the footer note and the sidebar badge"
    requirement: PLAT-02
    verification:
      - kind: unit
        ref: "tests/test_dashboard_adapters.py#test_outbound_row_is_locked_text_with_the_command_and_no_form"
        status: pass
      - kind: unit
        ref: "tests/test_dashboard_adapters.py#test_grant_chips_and_the_row_sub_with_tool_and_call_counts"
        status: pass
    human_judgment: false
  - id: D6
    description: "The page looks like sketch 004 in a real browser (switch button, restart bar, light and dark); a same-origin form POST in the owner's browser is not answered Forbidden origin; the real daemon exits and launchd relaunches it"
    verification: []
    human_judgment: true
    rationale: "No browser was driven and the installed daemon was not restarted (owner's MCP clients use it); 05-07 proves it on the installed release"
duration: 14min
completed: 2026-10-22
---

# Phase 5 Plan 03: Adapter switches and restart on the dashboard — PR #412

`/adapters` now turns an app on or off, shows what waits for a restart, discards pending changes and restarts the daemon (it exits itself, launchd starts it again). PR #412 was rebase-merged into develop; the last of its 7 commits is `5959130`.

## Performance

- **Duration:** about 14 min (lane created 10:35 UTC, merge 10:48 UTC)
- **Tasks:** 4 of 4
- **Files:** 10 changed (3 new), +959 / -9
- **Tests:** 2330 passed (full); 2315 passed and 15 skipped under `MACOS_APPS_READ_ONLY=1`; 2324 passed and 6 skipped under `MACOS_APPS_ALLOW_SEND=mail`. 25 of the new tests are in `tests/test_dashboard_adapters.py`, 1 in `tests/test_daemon_dispatch.py`.

## Accomplishments

- **Toggle (D-01, D-15).** `POST /adapters` takes `action=toggle` (adapter, on) or `action=discard`. The new deny-list is `tiers.adapters_off() & known_adapters()` with the adapter added or removed, written by `deploy.write_adapters_off`. A read-modify-write holds a module lock. One `audit.audit_write` record per POST, written after the file; never `usage_log`.
- **Atomic writer.** `mkstemp` in the same directory, fsync, `os.replace`; any exception removes the temp file and re-raises, and the old file stays. The directory is created 0700.
- **Page (D-11).** Rows are alphabetical, each switch a POST form with the token and a submit button styled as the switch. A pending chip reads `off after restart` or `on after restart`. The sticky bar reads `1 change waits for a restart.` or `n changes wait for a restart.`, lists the adapters, and names both consequences (open MCP connections drop; a running Mail batch stops, its receipt and backups stay). The sidebar entry shows `registered/known` or a `n pending` chip.
- **Restart (D-16, C2).** `POST /restart` logs `op: "restart"`, renders the "Restarting the daemon…" page (meta refresh 12 s to `/adapters`, visible Reload link, switches disabled) and sets the hook as a `BackgroundTask`, so the flags are set only after the body is sent. `daemon.restart` sets `should_exit` and `force_exit`, arms one 3 s `os._exit(0)` daemon timer and returns False on a second call. `serve()` builds the app with `restart=lambda: restart(server)`. `GET /restart` is 405; with no hook (a test app) the route is 503.
- **Locked states.** `MACOS_APPS_ADAPTERS_OFF` set: switches disabled with the planned note, toggle and Discard answer 409. D-20 (unreadable `adapters_off`, from #410): every switch reads off, a banner says the file cannot be read and to fix its permissions, toggle and Discard answer 409 with that text, and the unreadable file is left as it was. `*` is never rendered (rows come from the registry names). The Discard button is omitted in both locked states.
- **Rows say why (Task 3).** `grants.ADAPTER_GRANTS` and `grant_state`; the sub reads `Automation · Full Disk Access · 27 tools · 3 calls` (calls left out at zero); `denied` (`chip danger`) and `not asked` (`chip`) chips. The Outbound group is text, a `<code>` command (`allow-send off` when sending is on, else `allow-send mail`) and a Copy button, with no form and no input. Footer note as the sketch.

## Task Commits

Hashes are the ones on develop after the rebase-merge.

| Task | Commit | Message |
| ---- | ------ | ------- |
| 1 RED | 575bbb2 | test(dashboard): toggle an adapter from the Adapters page (PLAT-01, PLAT-02, D-15) |
| 1 GREEN | 31086f4 | feat(dashboard): turn an adapter on or off from the Adapters page (PLAT-01, PLAT-02, D-01, D-11, D-15) |
| 2 RED | 282e587 | test(dashboard): restart, Discard, the env override and an unreadable file (PLAT-02, D-15, D-16, D-20) |
| 2 GREEN | a49a384 | feat(dashboard): restart the daemon and discard pending changes from the page (PLAT-02, D-15, D-16, D-20) |
| 3 RED | 1c14f37 | test(dashboard): grant chips, counts and the locked Outbound row (PLAT-02, D-11, D-14) |
| 3 GREEN | 8eaa28e | feat(dashboard): grant chips, counts, the locked Outbound row and the badge (PLAT-02, D-11, D-14) |
| 4 | 5959130 | docs(changelog): adapter switches on the dashboard (PLAT-02) |

## TDD Gate Compliance

RED precedes GREEN in git for Tasks 1 to 3. `gsd_run check tdd-red-evidence` was not run: the plan is `type: execute` and pytest text output is not a supported report format. Semantic assessment of each RED run:

- **Task 1:** 11 failed. The page and POST tests failed on the planned status codes (`404 == 200`, `404 == 303`, `404 == 400`); the two writer tests failed with `AttributeError: module 'deploy' has no attribute 'write_adapters_off'` (the function under test did not exist). No fixture or import fault.
- **Task 2:** 8 failed. Four restart tests failed with `TypeError: build_app() got an unexpected keyword argument 'restart'` or 404 vs 503; Discard failed `400 == 303`; the env test `0 >= 10` disabled switches; the unreadable-file test failed on `'cannot be read' in page`; the daemon test with `AttributeError: no attribute '_restart_armed'` (the flag under test did not exist).
- **Task 3:** 7 failed. Three grant tests failed with `ImportError` for `dashboard.grants` (imported inside the tests so the module still collected and the other tests were not masked); four failed on the missing chip, Outbound title, footer and badge.

## Deviations from Plan

**1. [Rule 3 - Blocking] The AppleEvents target ids could not be listed from the installed daemon's `doctor`.**
- **Found during:** Task 3
- **Issue:** The plan asked to list `deployment.grant_identities.kTCCServiceAppleEvents` targets for `ren.lav.macos-apps-mcp` over the daemon socket. The installed daemon (0.14.3) returned only system-database rows (FDA); no AppleEvents, Calendar or Reminders rows. `deploy.grant_report()` run from a shell gave `reasons: {user: "absent", system: null}`: `~/Library/Application Support/com.apple.TCC/` does not exist on this Mac (macOS 27.0.1, build 26A434). There was no mismatch, only no data.
- **Fix:** read `CFBundleIdentifier` from the installed apps' Info.plist instead (read-only). Ids seen: Mail `com.apple.mail`, Notes `com.apple.Notes`, Contacts `com.apple.AddressBook`, Safari `com.apple.Safari`, Messages `com.apple.MobileSMS`, Music `com.apple.Music`. These are the ids in `ADAPTER_GRANTS`. The ids were not confirmed against a live TCC row; 05-07's device proof or 05-05's Health page on a Mac with a readable user database should confirm them.
- **Commit:** 8eaa28e

**2. [Rule 1 - Bug] `grant_state` would have said `not asked` for every Automation adapter on this Mac.**
- **Found during:** Task 3, from the finding above
- **Issue:** with the user TCC database unreadable, a missing AppleEvents row proves nothing; "not asked" would be a wrong claim shown on the page.
- **Fix:** `grant_state(..., *, complete=True)`; the page passes `complete = all(v is None for v in report["reasons"].values())`. An incomplete read gives unknown (no chip) unless a row says denied. Two assertions in `test_grant_state_is_unknown_when_it_cannot_tell`.
- **Commit:** 8eaa28e

**3. [Layout] Page test uses Calendar for the `denied` chip, not Photos.** Photos and Mail both need the single FDA service for one client, so one fixture cannot make Photos denied and Mail "not asked". The page test denies `kTCCServiceCalendar`; `grant_state` has a separate Photos-denied case.

**4. [Layout] `mkstemp` instead of `NamedTemporaryFile`.** Same behavior (same-directory temp, `delete=False` semantics), fewer lines.

**5. [Layout] CSS blocks landed with the task that needs them** (switch button, restart bar and pending chip in Task 1; spin, restarting, locked row, cmd, note in Task 3), so no commit leaves the page unstyled.

**6. [Process] Commit trailer.** All commits carry `Co-Authored-By: Claude Sonnet 5.5`, the trailer the session reminder names.

**Total deviations:** 2 auto-fixed (Rule 1, Rule 3), 4 layout or process notes. **Impact:** none on scope.

## Verification

- `uv run pytest -q`: 2330 passed, 102 deselected
- `MACOS_APPS_READ_ONLY=1 uv run pytest -q`: 2315 passed, 15 skipped, 102 deselected
- `MACOS_APPS_ALLOW_SEND=mail uv run pytest -q`: 2324 passed, 6 skipped, 102 deselected
- `uv run ruff check .`: All checks passed
- `uv run ruff format --check .`: 120 files already formatted
- Acceptance checks: `records-present`; `def write_adapters_off(` 1; `os.replace` 2; `"caller": "dashboard"` 1; `usage_log` in `adapters.py` 0; `def restart(`/`_restart_armed` 5; `os._exit` in `daemon.py` 3; `BackgroundTask` in `adapters.py` 2; `test_serve_two_concurrent_sessions` passes with the closure wired; `def grant_state(` 1; `Never changed from this page` 1; `restart-bar` in the CSS 4; CHANGELOG bullet 1.
- `~/.local/state/macos-apps-mcp/adapters_off` was absent before and after every suite run; no process listened on 47632 afterwards.
- `git diff --name-only origin/develop...HEAD` listed neither `pyproject.toml` nor `uv.lock` (T-05-SC).
- CI: required `check` passed in 1m11s on the pushed head; no dropped runner. PR #412 MERGED; the body says `Part of #126` and holds no `Closes`, `Fixes` or `Resolves`. The lane `.worktrees/dashboard-adapters` and branch `feat/dashboard-adapters` are removed; the main checkout is on `develop` = `origin/develop` (`5959130`).

## Code review (inline self-review of `origin/develop...HEAD`)

No sub-agent was available, so the review was done inline against D-01, D-08, D-11, D-14, D-15, D-16, D-20 and RESEARCH C2.

- **POST handlers.** Both routes sit in `build_app`'s one route list behind the `Guard` (Host, Origin, token; tested 403 without a token, 405 for `GET /restart`). A form cut short never reaches the handler (#409). The file is written before the audit record, so a failed write (OSError) leaves the old file, no temp file and no record, and answers 500. A lock serializes the read-modify-write.
- **Self-exit.** The hook runs as a `BackgroundTask` after the body is sent; `restart()` runs once per process; the watchdog is a daemon thread that calls `os._exit(0)` after 3 s; nothing runs `launchctl`. Not proven here: a real exit and a launchd relaunch (05-07).
- **Escaping.** Every interpolated value goes through `h()`; adapter names come from the registry, the pending list is built as text and escaped.
- **Accepted, not fixed:** (a) `_lock_reason()` is checked before the lock, so a file that turns unreadable in the microseconds between the check and the write would be replaced by the known-names write; (b) `adapter_status()` reads the file once per adapter per request (about 20 small reads), on the event loop; (c) a file that holds a literal `*` reads as the D-20 state and the note says "cannot be read"; (d) a restart within 10 s of the daemon start waits for launchd's `ThrottleInterval`, longer than the 12 s refresh may cover (the Reload link covers it).
- No open finding. Passed to the independent review and 05-07: real-browser behaviour (Origin on a same-origin form POST in Safari and Firefox, RESEARCH A1), the look of `dashboard.css`, and the real exit and relaunch.

## Known Stubs

None.

## Issues Encountered

- **The user TCC database is absent on this Mac** (macOS 27.0.1): `deploy._TCC_DB` points at `~/Library/Application Support/com.apple.TCC/TCC.db`, which does not exist. `doctor` and `deploy.grant_report()` therefore see only system-database rows here, and the grant chips for Calendar, Reminders and every Automation adapter stay empty (unknown) on this Mac. This looks like a path or layout change on macOS 27, not specific to this plan. 05-05's Health page reads the same mapping and will hit it too; worth an issue or a deferred item before 05-05 and 05-07.
- The `rtk` output filter hid pytest tracebacks; `rtk proxy uv run pytest` showed them.

## Threat Flags

None beyond the plan's threat register. T-05-14 to T-05-19 are mitigated and tested; T-05-18 by the group-markup assertion; T-05-SC by the untouched `pyproject.toml` and `uv.lock`.

## Next Phase Readiness

- 05-09 (page key) can wrap the same `Guard`; no route bypasses it.
- 05-04 and 05-05 can reuse `html.page(refresh=...)`, `grants.grant_state(..., complete=...)` and the CSS blocks (`.chip.pending`, `.cmd`, `.spin`, `.restarting`, `.note`).
- 05-07 must prove on the installed release: a toggle is not answered "Forbidden origin" in the owner's browser, the daemon exits and launchd relaunches it within the throttle, the page reconnects, and the AppleEvents target ids hold on a Mac whose user TCC database is readable.

## Self-Check: PASSED

- Files exist on develop: `macos_apps_mcp/dashboard/adapters.py`, `macos_apps_mcp/dashboard/grants.py`, `tests/test_dashboard_adapters.py`; `origin/develop:macos_apps_mcp/dashboard/adapters.py` holds `async def toggle(` and `async def restart(` (count 2).
- `git rev-list --count c33e7ba6d68285367fcc172049da59c57ef6cd23..59591305ced10ddd69257c53f466ac0f186ab43c` prints 7.
- `gh pr view 412` state is `MERGED`.
- The vault journal bullet for #412 was landed (MR 1720 in the vault repo).
