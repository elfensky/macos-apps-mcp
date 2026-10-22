---
phase: 05-operator-control-plane-adapter-toggles-and-the-localhost-das
plan: 05
subsystem: dashboard-system
tags: [dashboard, health, backups, doctor, single-flight, tcc, docs, page-key, d-14, d-13, d-07]
status: complete
requires:
  - phase: 05-operator-control-plane-adapter-toggles-and-the-localhost-das
    provides: "05-03 grants.ADAPTER_GRANTS/grant_state, adapters page; 05-04 recovery helpers, writes.build_rows; 05-09 page key and tests/_dashboard.py"
provides:
  - "dashboard.health: page, last_dot(), _lock, _last, _dot, _WAIT, _STARTED, _run (single-flight doctor off the event loop)"
  - "dashboard.backups: page, receipt (read-only list and view)"
  - "doctor deployment.dashboard (daemon role only)"
  - "routes GET /health, /backups, /backups/{receipt}; sidebar entries Health (with dot) and Backups"
  - "adapters.outbound_command, adapters.cmd_box; grants.grant_state(..., service=)"
  - "docs/DAEMON.md section 7, README Dashboard, CHANGELOG line"
affects: [05-06, 05-07]
key-files:
  created:
    - macos_apps_mcp/dashboard/health.py
    - macos_apps_mcp/dashboard/backups.py
    - tests/test_dashboard_system.py
  modified:
    - macos_apps_mcp/doctor.py
    - macos_apps_mcp/dashboard/__init__.py
    - macos_apps_mcp/dashboard/html.py
    - macos_apps_mcp/dashboard/dashboard.css
    - macos_apps_mcp/dashboard/adapters.py
    - macos_apps_mcp/dashboard/grants.py
    - tests/test_doctor_deploy.py
    - docs/DAEMON.md
    - README.md
    - CHANGELOG.md
key-decisions:
  - "D-14/C7: the lock is taken and released inside the worker thread, so a request that stops waiting can never leave it held"
  - "PM-20: Health reads TCC completeness from deploy.grant_report() reasons; an unreadable database reads as 'could not be read', never 'not asked'"
  - "D-13: the Backups summary counts what it lists, not backup_usage()"
requirements: [PLAT-02]
requirements-completed: [PLAT-02]
pr: 421
merge_sha: 68c984d2b7229bdd79fada239dea2399797fee60
commits: 7
plan_head_before: be8822a5f86cce1d75377182cad0c5b7711ce49a
plan_head_after: 68c984d2b7229bdd79fada239dea2399797fee60
actuals:
  tokens: 14700
  tasks: 4
  commits: 7
duration: 17min
completed: 2026-10-22
coverage:
  - id: D1
    description: "Health runs doctor(request=False) off the event loop behind a one-call lock; a call in flight renders 'worker busy' with the Deployment group and starts no second call; an exception in doctor leaves the lock free"
    requirement: PLAT-02
    verification:
      - kind: unit
        ref: "tests/test_dashboard_system.py#test_health_busy_and_single_flight"
        status: pass
      - kind: unit
        ref: "tests/test_dashboard_system.py#test_health_an_exception_in_doctor_never_sticks_the_lock"
        status: pass
    human_judgment: false
  - id: D2
    description: "Health rows, Deployment group and the full report as escaped JSON; the locked Outbound row with its command and no form"
    requirement: PLAT-02
    verification:
      - kind: unit
        ref: "tests/test_dashboard_system.py#test_health_shows_what_doctor_reports"
        status: pass
      - kind: unit
        ref: "tests/test_dashboard_system.py#test_health_outbound_row_is_locked_text_with_the_command"
        status: pass
    human_judgment: false
  - id: D3
    description: "The danger banner names only active adapters with a denied grant; Automation rows with Open Settings; off adapters raise nothing; the sidebar dot follows the last report"
    requirement: PLAT-02
    verification:
      - kind: unit
        ref: "tests/test_dashboard_system.py#test_banner_names_every_active_adapter_macos_refused"
        status: pass
      - kind: unit
        ref: "tests/test_dashboard_system.py#test_an_off_adapter_raises_no_banner_and_says_it_does_not_matter"
        status: pass
      - kind: unit
        ref: "tests/test_dashboard_system.py#test_the_sidebar_dot_follows_the_last_health_report"
        status: pass
    human_judgment: false
  - id: D4
    description: "An unreadable or partly readable TCC database says the grants could not be read and never claims 'not asked' (PM-20)"
    requirement: PLAT-02
    verification:
      - kind: unit
        ref: "tests/test_dashboard_system.py#test_an_unreadable_tcc_database_says_so_and_never_claims_not_asked"
        status: pass
      - kind: unit
        ref: "tests/test_dashboard_system.py#test_a_partial_tcc_read_never_claims_not_asked"
        status: pass
    human_judgment: false
  - id: D5
    description: "doctor reports deployment.dashboard in the daemon role only; the stdio server never imports the daemon or dashboard module"
    requirement: PLAT-02
    verification:
      - kind: unit
        ref: "tests/test_doctor_deploy.py#test_deployment_names_where_the_dashboard_listens"
        status: pass
      - kind: unit
        ref: "tests/test_doctor_deploy.py#test_deployment_has_no_dashboard_key_in_stdio_mode"
        status: pass
    human_judgment: false
  - id: D6
    description: "Backups lists real receipt folders newest first (a 4-digit counter included), joined to the log; opens the read-only batch or the files of a rotated-out plan; bad names, symlinks and non-regular files never reach a page; nothing is created or pruned"
    requirement: PLAT-02
    verification:
      - kind: unit
        ref: "tests/test_dashboard_system.py#test_backups_page_lists_the_receipts_on_disk_newest_first"
        status: pass
      - kind: unit
        ref: "tests/test_dashboard_system.py#test_backups_page_lists_a_receipt_with_a_four_digit_counter"
        status: pass
      - kind: unit
        ref: "tests/test_dashboard_system.py#test_bad_receipts_are_404_and_regex_comes_before_the_disk"
        status: pass
      - kind: unit
        ref: "tests/test_dashboard_system.py#test_without_a_backup_root_the_page_is_empty_and_creates_nothing"
        status: pass
    human_judgment: false
  - id: D7
    description: "docs/DAEMON.md section 7 describes the page key, its rotation, the cookie residual and the port fallback"
    requirement: PLAT-02
    verification:
      - kind: command
        ref: "git show origin/develop:docs/DAEMON.md | grep -c -e '### 7. The localhost dashboard' -e 'Every page needs the page key.' (prints 2)"
        status: pass
    human_judgment: false
  - id: D8
    description: "The pages look like sketches 003 and 004 in a real browser (dots, banner, Deployment group, meter, receipt rows; light, dark, phone); Open Settings opens the right pane; the AppleEvents target ids hold on a Mac whose user TCC database is readable"
    verification: []
    human_judgment: true
    rationale: "No browser was driven and the installed daemon was not touched; 05-07 proves it on the installed release"
---

# Phase 5 Plan 05: Health, Backups and the dashboard docs — PR #421

Health and Backups on the dashboard, and docs/DAEMON.md section 7 with the page key. PR #421 was rebase-merged into develop with the required `check` green (1m56s). Part of #126.

## Performance

- **Tasks:** 4 of 4. **Commits:** 7 (RED before GREEN for Tasks 1 to 3, one docs commit). Task 4 added no review-fix commit: the inline review found nothing open.
- **Files:** 13 changed (3 new), +1289 / -13.
- **Tests:** baseline 2429 passed. After: 2456 passed (full); 2441 passed and 15 skipped under `MACOS_APPS_READ_ONLY=1`; 2450 passed and 6 skipped under `MACOS_APPS_ALLOW_SEND=mail`. `ruff check` clean; `ruff format --check`: 128 files already formatted.
- After the suite, the real `~/.local/state/macos-apps-mcp/daemon/dashboard_key` and `adapters_off` were still absent, nothing listened on port 47632, and the installed daemon was not touched.
- `pyproject.toml` and `uv.lock` are not in the PR (T-05-SC).

## Accomplishments

- **Health (D-14, RESEARCH C7).** `GET /health` runs `doctor.diagnose(request=False)` through `anyio.to_thread.run_sync(..., abandon_on_cancel=True)` inside `move_on_after(_WAIT)` (10 s). `_run` takes the non-blocking lock and releases it in the same thread, so an abandoned call cannot leave it held and a reload starts no second call. A request that finds the lock held renders at once: the EventKit row reads `worker busy, a native call is in flight`, the Deployment group renders from cheap sources, and a muted line says to reload. An exception in doctor renders a `doctor could not run` banner, not a 500, and frees the lock. Rows: Daemon, Adapters (with `Show` when a restart is pending), Full Disk Access, EventKit, one `Automation → App` row per Automation grant that is not granted, Outbound (locked, command and Copy), Mail backups, Deployment (Version, Mode, Listens on, Grant identity), and the full report as escaped JSON in a collapsed `<details>`.
- **Banner and dot.** The danger banner appears only for an active adapter with a denied TCC row or a refused live probe (EventKit `denied`, Full Disk Access `denied`). An off adapter's row says `adapter is off, so this does not matter` and raises nothing. The sidebar Health item carries the dot of the last full report (`bad`, `warn` for a pending restart, `ok`), and none before the first one. `Open Settings` is a constant `x-apple.systempreferences:` link; no endpoint opens anything.
- **PM-20 handled.** On a Mac whose user TCC database cannot be read, Health reads completeness from `deploy.grant_report()["reasons"]`. A missing row then means "cannot tell": one `Automation` row says the grants could not be read for the active Automation adapters, and a warn banner names the database reasons. The banner falls back to the live probes. "Not asked" is claimed only when both databases answered. `grants.grant_state` gained a `service` argument so an `Automation → Mail` row is about AppleEvents only (Mail's Full Disk Access denial does not make an Automation row).
- **doctor (D-07).** In the daemon role `deployment.dashboard` is `daemon.dashboard_state` (the URL, or `not bound: …`); absent in stdio mode and before the daemon decided. The `daemon` module is imported inside the daemon-role branch, so `import macos_apps_mcp.server` loads neither `daemon` nor `dashboard` (checked: `False False`). **Token budget:** the existing worst-case test measures in stdio mode; measured in the daemon role with the longest `not bound:` string, the report is 6655 characters, under 7000.
- **Backups (D-13).** `GET /backups` scans `<state>/backup/mail` (never created), keeps names that match `RECEIPT_RE` and are real directories, lists them newest first with file count and size, joined to the plan record where the log still has it (`move · 2 messages → Archive`). It shows `N MB in K receipts`, the oldest date, the advisory limit, a `<meter>`, and the root path with Copy. `GET /backups/<receipt>` checks the regex before any filesystem call (404), then `receipt_dir`; with the batch in the log it renders 05-04's `render_batch` (undo prompt gated by `find_receipt`, a banner when undone), otherwise the file list with "The plan for this receipt has rotated out of the audit log; the backup files remain." and no prompt. A 4-digit-counter receipt (#419) lists and opens (test). Symlinked receipts and symlink, FIFO or other non-regular entries inside a receipt are skipped. Nothing deletes, prunes or creates.
- **Docs (D-05, D-19).** docs/DAEMON.md `### 7. The localhost dashboard`: URL and loopback bind, the page key (`macos-apps-mcp dashboard`, the key file, rotation by removing the file and restarting, the refusal without it, the unreadable-file refusal), the cross-port cookie residual (T-05-44), the pages, Health's read-only behaviour, the two write actions, the restart consequences, the locked Outbound gate, and the port fallback (`not bound: …`, the `adapters_off` file and the kickstart). README `### Dashboard` and one CHANGELOG bullet. No key value appears in the docs. The section-6 sentence "later in this phase" now points to section 7.

## Deviations from Plan

**1. [Rule 1 - Inconsistent spec] The Backups summary does not use `backup_usage()`.** The plan's fixture holds a non-receipt folder and a symlinked folder, and expects "2 receipts" "from `backup_usage()`". `backup_usage()` counts every directory (symlinks to directories included), so it would say 4. The page counts what it lists. The doctor "Mail backups" string may therefore differ from the page when stray entries exist. Commit a6e58a5.

**2. [Rule 3 - Blocking] Tests import `health` lazily in RED.** The module did not exist, so the RED commit guarded the import with `try/except ImportError` to keep the file collectable; the GREEN commit removed the guard. Same shape as 05-03.

**3. [Layout] Two files outside `files_modified`.** `dashboard/adapters.py` (extracted `outbound_command` and `cmd_box` so Health and Adapters share one command box) and `dashboard/grants.py` (`service=` argument, see PM-20). 13 files changed, under the 15-file line. The daemon-role token-budget measurement was a one-off run, not committed.

**4. [Layout] Singular "1 receipt".** The summary reads `1 receipt` for one; the plan's wording is plural. `0.0 MB in 0 receipts` and `in 2 receipts` match.

**5. [Layout] The lock is taken in the worker, not by the page.** The plan sketched `_lock.acquire` in `page`. Taking it in the thread removes the case where a cancellation before the thread starts leaves the lock held. The page checks `_lock.locked()` only to answer a busy request at once; two near-simultaneous requests can both start a thread, and the second exits at once (`_run` returns None) so no second diagnose runs.

**6. [Process] Pre-commit assertion.** The lane's `.git` is a file, but the lane is the plan's own and its branch is `feat/dashboard-system`, so the agent-namespace allow-list of the executor protocol was not applied; the protected-branch check and the step-0p pin ran before every commit.

**Total deviations:** 1 spec inconsistency, 1 blocking test-collection, 4 layout or process notes. **Impact:** none on scope.

## Code review (inline, no sub-agent tool)

Reviewed `origin/develop...HEAD` against the plan, D-05, D-07, D-13, D-14 and RESEARCH C7.

- **Single-flight diagnose.** The event loop never runs doctor (thread plus `abandon_on_cancel`). One lock, taken and released in the worker, so an exception (tested), a cancellation, or a late finish frees it. Only one native call runs at a time; a second request renders busy without a call (tested with a blocked fake). The abandoned thread keeps the lock until it ends, so reloads cannot pile threads up (an unreleased forever-hung native call keeps the page "busy", which is the truth). No `request=True` anywhere.
- **Path handling.** `RECEIPT_RE` runs in the route before `receipt_dir` (test: `backup_root` raises for `..%2f`, `notes`, a wrong op, a trailing character, `%2e%2e`). A symlinked receipt folder is 404 and not listed. Files inside are read by `recovery.backup_files` (regular, non-symlink only; names and sizes). No file content is read or served.
- **GET side effects.** Health and Backups write nothing. The one `mkdir` is `audit.state_dir()` for the state folder (PM-33, accepted). The backup tree stays absent (test); `purge_backup` and `_backup_dir` are patched to fail and are never called.
- **Escaping.** Every dynamic value goes through `h`; `Safe(` wraps constants only. Tests render `<script>` in the doctor summary (inside the JSON), in a doctor failure message and in a plan destination. Backup file names and the folder path are escaped.
- **Residual, not fixed:** (a) `/backups` lists every receipt with no paging (935 receipts is about 400 KB of HTML); (b) `backups.py` uses two private helpers of sibling modules (`recovery._size`, `writes._recovery_facts`); (c) Health calls `deploy.grant_report()` a second time after `diagnose` (two small sqlite reads) because doctor does not return the read reasons; (d) `_last` is stored but nothing reads it yet; (e) the daemon-role token-budget worst case is measured here but not asserted by a test (PM-05 stays open); (f) the sidebar still parses the audit log on every page (PM-30, accepted).

## For 05-07 (device proof)

- **PM-20, T-05-44.** This Mac's sessions see no readable user TCC database, so `grant_identities` may be `None` or hold only system rows and the Automation rows read "could not be read". 05-07 must confirm the `grants.ADAPTER_GRANTS` AppleEvents target ids (the bundle identifiers of Mail, Notes, Contacts, Safari, Messages, Music) against live rows on the installed release, on a Mac whose user database is readable.
- Also on the installed release: Health with a real busy worker, `Open Settings` opening the right pane, the look of both pages against sketches 003 and 004, and the page-key flow described in section 7.

## Known Stubs

None.

## Threat Flags

None beyond the plan's register (T-05-27 to T-05-31 mitigated and tested; T-05-SC by the untouched `pyproject.toml` and `uv.lock`).

## Issues Encountered

None blocking. The `rtk` output filter hid pytest tracebacks; `rtk proxy` showed them.

## Self-Check: PASSED

`macos_apps_mcp/dashboard/health.py`, `backups.py` and `tests/test_dashboard_system.py` exist on develop; `git rev-list --count be8822a..68c984d` prints 7; `gh pr view 421` state is MERGED, the body says `Part of #126` and holds no closing keyword; `origin/develop:docs/DAEMON.md` holds both required sentences (count 2); the lane and branch are removed; the vault journal bullet is logged. STATE.md and ROADMAP.md were not touched.
