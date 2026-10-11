---
phase: quick-261011-imn
plan: 01
subsystem: doctor
tags: [doctor, tcc, automation, "#317", "#318"]
requires: []
provides:
  - "doctor Automation probe counts an answered -1728 as ok (#317)"
  - "grant map entries carry target, reason and prompt-timeout remediation (#318)"
key-files:
  modified:
    - macos_apps_mcp/doctor.py
    - tests/test_doctor.py
    - macos_apps_mcp/deploy.py
    - tests/test_deploy.py
    - docs/DAEMON.md
    - CHANGELOG.md
metrics:
  tasks: 3
  commits: 3
  plan_head_before: 7c759d9b94f3f84f0abb313e5323160ad18b6f06
  plan_head_after: bdc04ba60dd1f5fd596be5c7eac0598609bb0a0d
actuals:
  tasks: 3
  commits: 3
status: complete
---

# Quick 261011-imn: doctor probe and grant-map fixes (#317, #318)

The Automation probe now swallows only -1728 from `count windows`. The grant map names the denial reason and the AppleEvents target. Nothing is pushed.

## Commits (branch fix/317-318-doctor-probes)

- 95f6f60 fix(doctor): count an answered -1728 probe as a working grant (#317)
- add1f17 fix(doctor): the grant map names the TCC denial reason and the AppleEvents target (#318)
- bdc04ba docs(changelog): doctor probe and grant-map fixes (#317, #318)

## RED lists

Task 1 (`tests/test_doctor.py`, 2 failed, 35 passed):
- `test_probe_template_swallows_only_1728` — `At index 2 diff: 'tell application (item 1 of argv) to count windows' != 'tell application (item 1 of argv)'`
- `test_probe_error_filter_under_real_osascript[-1728-...]` — `AssertionError: 78:124: execution error: Photos got an error: Can't get every window. (-1728)`, `assert 1 == 0`
- Passing against the old template, as the plan expected: `test_probe_compiles`, the -1743 and -609 cases.

Task 2 (`tests/test_deploy.py`, 8 failed, 23 passed):
- `test_grant_identities_maps_rows` (now expects `reason: user-set`)
- `test_timed_out_prompt_is_prompt_timeout_with_remediation`
- `test_remediation_names_the_rows_own_service` (KeyError)
- `test_user_denial_has_reason_and_no_remediation`
- `test_unknown_denial_reason` (KeyError: 'reason')
- `test_granted_entry_carries_target_not_reason`
- `test_tcc_rows_missing_new_column_is_schema_drift[auth_reason]`
- `test_tcc_rows_missing_new_column_is_schema_drift[indirect_object_identifier]`
- `test_no_real_target_means_no_target_key[None, "", UNUSED]` passed in RED: today's code never emits `target`, so they guard against over-emitting.

## Checks (code lane)

| Check | Exit | Result |
|-------|------|--------|
| `uv run pytest -q` | 0 | 1975 passed, 97 deselected |
| `MACOS_APPS_ALLOW_SEND=mail uv run pytest -q` | 0 | 1971 passed, 4 skipped, 97 deselected |
| `uv run ruff check .` | 0 | clean |
| `uv run ruff format --check .` | 0 | clean |
| `pytest --collect-only -q` | 0 | 1975 unit tests (baseline 1960) |

Also: exactly 3 commits, subjects end `(#317)`, `(#318)`, `(#317, #318)`, 3 trailers, only the six planned files changed, no `.planning/` file committed, `origin/fix/317-318-doctor-probes` does not exist.

## Grant-map check (read-only, `deploy.grant_report()`)

- `reasons`: `{'user': 'absent', 'system': None}`
- entries: 16 total; 0 with `target`; 8 with `reason`; 0 with `remediation`
- entries for `ren.lav.macos-apps-mcp`: `kTCCServiceSystemPolicyAllFiles {'client': 'ren.lav.macos-apps-mcp', 'granted': True}`

`test_report_stays_under_token_budget` passed in both full runs.

## Device gate

Device probe skipped: no Automation grant for Photos is readable for this shell's app. The user TCC.db is absent on this macOS (27) and the system db holds zero `kTCCServiceAppleEvents` / `com.apple.Photos` / `auth_value 2` rows. No probe ran, so no consent prompt could appear. The -1728 / -1743 / -609 behavior was proven through real `osascript` with `tell current application` (no Apple event sent).

## Deviations from Plan

None. The plan was executed as written.

## Known Stubs

None.

## Follow-up candidates

- #318 item 3: `install-agent` re-reads the grant map after its prompt pass and prints every `prompt-timeout` row with its reset command, because that pass is where unattended timeouts happen.
- `test_report_stays_under_token_budget` reads this Mac's real TCC dbs through `deploy.grant_report`; pinning both TCC paths in that test is a separate change.
- On-device confirmation after the next daemon rebuild (operator): `doctor(request=True)` with Photos quit reports `photos` as `ok`; `deployment.grant_identities` on the Sequoia rig shows one AppleEvents entry per `target`.

## Self-Check: PASSED

All three commits are ancestors of HEAD; all six files are changed in the branch diff.

## After the executor (orchestrator, 2026-10-11)

- **CI failure, fixed in the same PR.** `test_report_stays_under_token_budget` read the CI
  runner's real TCC.db; with the new per-entry fields the report reached 7587 > 7000. Made
  deterministic (the daemon's rows, all seven AppleEvents targets timed out — the Intel rig's
  real failure), it was ~7300: each entry repeated a 235-character explanation. Fix (`816b432`,
  merged as `ff345a5`): an entry's `remediation` is only `tccutil reset <Service> <client>`;
  doctor's grant note says the why once; the test pins TCC.db. 1975 / 1971 passed, CI green,
  PR #328 merged, #317 and #318 closed.
- **Ops items from the same request.** Production PyPI publish dispatched on `v0.14.3` (run
  38134760437, success; `pypi.org/pypi/macos-apps-mcp/0.14.3/json` 200, `project_urls` from #111
  live). The empty Gmail label `mcp-291-rerun` removed in Gmail's label settings (0
  conversations; Gmail confirmed); Mail synced it away (no index row, no mailbox). The leftover
  reply window was already closed.
- Not proven on device: the #317 probe on the Intel rig needs the next daemon build there.
