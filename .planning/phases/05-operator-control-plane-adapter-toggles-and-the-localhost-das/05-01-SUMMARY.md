---
phase: 05-operator-control-plane-adapter-toggles-and-the-localhost-das
plan: 01
subsystem: platform
tags: [adapters, deny-list, registration-gate, doctor, eventkit, tdd]
requires: []
provides:
  - "tiers.adapters_off() / tiers.adapter_enabled(name): the adapter deny-list (env first, daemon-role file fallback)"
  - "deploy._ADAPTERS_OFF_FILE and deploy.adapters_off_file(): the home-pinned ~/.local/state/macos-apps-mcp/adapters_off"
  - "server._tool ANDs the adapter gate into every tier (send tier included); meta tools are never gated"
  - "registry.adapter_status(); registry.outbound_status() also requires the adapter to be ON"
  - "doctor deployment keys adapters, adapters_off, adapters_note, adapters_unknown, adapters_pending; surface status adapter_off"
  - "eventkit.request_access_each() skips an OFF calendar or reminders entity"
affects: [05-03, 05-07]
tech-stack:
  added: []
  patterns: ["deny-list twin of allow_send: env wins, file only in the daemon role", "configured-vs-registered view with a pending delta (adapter_status mirrors outbound_status)"]
key-files:
  created: [tests/test_adapters_off.py]
  modified: [macos_apps_mcp/tiers.py, macos_apps_mcp/server.py, macos_apps_mcp/registry.py, macos_apps_mcp/deploy.py, macos_apps_mcp/doctor.py, macos_apps_mcp/eventkit.py, tests/conftest.py, tests/test_registry.py, docs/DAEMON.md, README.md, CHANGELOG.md]
decisions:
  - "D-01: deny-list; MACOS_APPS_ADAPTERS_OFF wins; the adapters_off file is read only in the daemon role and is home-pinned (never state_dir())"
  - "D-02: one predicate ANDed into server._tool's registered in every tier; meta tools (adapter=None) are never gated"
  - "D-03: adapter_status() mirrors outbound_status(); outbound_status().configured also requires the adapter ON"
  - "D-04: an OFF adapter gets no Apple Event and no EventKit request; its surface reads adapter_off and is left out of the summary counts"
  - "D-05: no CLI role; the doctor note and docs/DAEMON.md section 6 name the file and the kickstart"
  - "D-17: tests/conftest.py patches deploy._ADAPTERS_OFF_FILE into the isolated state dir"
requirements: [PLAT-01]
status: complete
commits: 7
plan_head_before: d053ec151ed176c03cc27c13a27965370b3a5483
plan_head_after: 65379a2d7b1124612079dc9ecf19ef5e01f72480
actuals:
  tokens: 7660
  tasks: 4
  commits: 7
pr: 407
merge_sha: 65379a2d7b1124612079dc9ecf19ef5e01f72480
---

# Phase 5 Plan 01: Adapter deny-list Summary

Adapters turn off with a deny-list read at start, and their tools are absent from the tool list. Landed as PR #407 (rebase-merged, required `check` green), head `65379a2`.

## What shipped

- **Gate (Task 1, tracer).** `tiers.adapters_off()` reads `MACOS_APPS_ADAPTERS_OFF` first. In the daemon role only, an empty env var falls back to `~/.local/state/macos-apps-mcp/adapters_off`. Names are trimmed, lower-cased and de-duplicated. `server._tool` ANDs `tiers.adapter_enabled(adapter)` into `registered` in every tier. Subprocess tests prove the listed tools equal the registered records and that all four photos tools stay recorded.
- **Doctor report (Task 2).** `deployment.adapters` (what this process serves), `adapters_off`, `adapters_note` (names the file and the kickstart), `adapters_unknown` and, when the setting changed after start, `adapters_pending` plus a restart directive. `outbound_status()["configured"]` requires the adapter to be ON, so `allow_send=mail` with Mail off leaves no pending delta.
- **No probe, no prompt (Task 3).** Automation, EventKit and `shortcuts_cli` surfaces of an OFF adapter read `adapter_off` with `ok: None`, before any `run_osascript`, process line or EventKit call. The summary and the need/unverified lists count only probed surfaces. `request_access_each()` skips an OFF entity.
- **Docs and landing (Task 4).** docs/DAEMON.md section "6. Turn adapters off under the daemon", README "Turning adapters off", CHANGELOG bullet first under `### Added`.

## TDD record

| Task | RED commit | GREEN commit |
| ---- | ---------- | ------------ |
| 1 | `6006ed4` test(adapters): the adapter deny-list gate (PLAT-01, D-17) | `b6aa19a` feat(adapters): an adapter deny-list gates every tier at registration |
| 2 | `43f8c9b` test(adapters): doctor keys and the outbound interplay (PLAT-01) | `477a81b` feat(adapters): doctor reports active, off, unknown and pending adapters |
| 3 | `bd50def` test(doctor): no probe and no prompt for an OFF adapter (PLAT-01, D-04) | `14e630a` feat(doctor): an OFF adapter gets no Apple Event and no EventKit request |
| 4 | none (docs) | `65379a2` docs(adapters): the adapters_off file and its kickstart |

(SHAs are the rebased ones on `origin/develop`.) RED evidence, semantic assessment: each RED run failed on the planned behavior. Task 1: three subprocess tests failed on `assert not {photos tools} & set(tools)`, and the predicate tests failed with `AttributeError: module 'tiers' has no attribute 'adapters_off'` (the function under test does not exist yet). Task 2: `configured == ['mail']` assertion failure and `KeyError: 'adapters'` in doctor. Task 3: five tests failed on assertions (`status 'ok' != 'adapter_off'`, `'not_determined' == 'adapter_off'`, the shortcuts lookup called, `'all 11 surfaces OK' != 'all 10'`, `[0, 1] != [1]`). No test was green before its GREEN commit. The `gsd_run check tdd-red-evidence` classifier was not run: the pytest text output is not one of its supported report formats.

## Check results

Baseline on `origin/develop` before any change: `uv run pytest -q` 2229 passed; `MACOS_APPS_READ_ONLY=1` 2214 passed, 15 skipped.

Final, after the rebase onto the 0.15.0 release commit:

| Command | Result |
| ------- | ------ |
| `uv run pytest -q` | 2250 passed, 102 deselected |
| `MACOS_APPS_READ_ONLY=1 uv run pytest -q` | 2235 passed, 15 skipped, 102 deselected |
| `MACOS_APPS_ALLOW_SEND=mail uv run pytest -q` | 2245 passed, 5 skipped, 102 deselected |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 111 files already formatted |

- `test_report_stays_under_token_budget` measured length: 6113 before, 6446 after (cap 7000). The plan's 6141 figure was a research measurement; the same test measured 6113 in this lane.
- `~/.local/state/macos-apps-mcp/adapters_off` did not exist before the suite and did not exist after it (no test wrote the real path).
- `git diff --name-only origin/develop...HEAD` lists neither `pyproject.toml` nor `uv.lock` (T-05-SC).
- CI: required `check` passed in 2m1s on the rebased head. The PR body says `Part of #126` with no closing keyword.

## Deviations from Plan

**1. [Rule 3 - Blocking] The `_ADAPTERS_OFF_FILE` constant landed in the RED commit.**
- **Issue:** the plan's RED step patches `deploy._ADAPTERS_OFF_FILE` in `tests/conftest.py`, but the constant is a GREEN deliverable. With the patch and no constant, every test in the suite errored in the session fixture. That is an INVALID_RED (fixture failure), not a RED on the planned behavior.
- **Fix:** the one-line constant (plus its comment) moved into the RED commit as test infrastructure. The reader `adapters_off_file()` and all behavior stayed in GREEN.
- **Commit:** `6006ed4`.

**2. [Layout] The Task 1 env case is a separate test, not an extra case inside `test_fastmcp_lists_exactly_the_registered_records`.** Three new subprocess tests in `tests/test_registry.py` (env var, daemon-role file vs stdio, `allow_send=mail` with Mail OFF). The `_subprocess_registry_snapshot` helper gained an `adapters` map (tool name to adapter) for the Mail check. The Mail send-tier subprocess test belongs to the Task 2 behavior list but runs in Task 1, because the send-tier AND ships in Task 1.

**3. [Process] Commit trailer.** The orchestrator brief asked for `Co-Authored-By: Claude Opus 5.5`; the plan says to use the session reminder's trailer, and that reminder names `Claude Sonnet 5.5`, the model that ran. All seven commits carry the Sonnet 5.5 trailer.

**4. [Process] No `vault-journal` call and no sub-agent code review.** Per the brief: three executors run in parallel, so the orchestrator records the landing (PR #407, merge head `65379a2`). The independent review runs after the merge.

## Inline self-review (origin/develop...HEAD against PLAT-01, D-01..D-05, D-17)

- D-01: the file is read only when `deploy.is_daemon_role()` is true and the env var is empty or unset; the path is a home-pinned constant, not `state_dir()`. Pass.
- D-02: `on = adapter is None or tiers.adapter_enabled(adapter)` feeds all three tier branches; `registered=False` records are kept, so the tool is absent, never registered-and-erroring. Pass.
- D-03: `adapter_status()` and `outbound_status()` as specified; lists are sorted sets, so no duplicates. Pass.
- D-04: OFF check precedes `run_osascript` and `_process_line` in `_automation_surfaces`; FDA and Mail-index surfaces stay (shared by several adapters). Pass.
- D-05: no CLI role added. D-17: conftest patch present, and a test asserts the path is not the real home path. Pass.
- Residual notes (not defects): `adapters_off` in the doctor report is `known - registered`, so under a registration-time `MACOS_APPS_READ_ONLY` an enabled adapter still shows as active because every adapter has a read tool (pinned by `test_every_adapter_has_a_read_tool`). The doctor still lists Photos nowhere in Automation probes (already absent per Phase 4 D-07).

## Known Stubs

None.

## Threat Flags

None. No new network endpoint, auth path or schema; one new operator-written file, covered by T-05-02.

## Auth gates

None.

## Self-Check: PASSED

- `origin/develop:macos_apps_mcp/tiers.py` holds both predicates (grep count 2).
- `git rev-list --count ce8bb3b..65379a2` prints 7 (the commit count above).
- `tests/test_adapters_off.py`, `docs/DAEMON.md` section 6 and the CHANGELOG bullet are on `develop` (PR #407 state MERGED).
- Lane `.worktrees/adapter-toggles` and branch `feat/adapter-toggles` are removed; the main checkout is on `develop` = `origin/develop`.
