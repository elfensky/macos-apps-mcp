---
phase: quick-261011-imn
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - macos_apps_mcp/doctor.py
  - tests/test_doctor.py
  - macos_apps_mcp/deploy.py
  - tests/test_deploy.py
  - docs/DAEMON.md
  - CHANGELOG.md
autonomous: true
requirements: [ISSUE-317, ISSUE-318]

estimate:
  tokens: 50000
  raw_tokens: 50000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "`doctor(request=True)` reports an Automation surface as `ok` when the app answers the probe's `count windows` with -1728. This applies to every app in `_AUTOMATION_APPS`, not only Photos, and Photos stays in that tuple (#317)"
    - "An Automation denial (-1743) still leaves osascript with its original message and the text `(-1743)` on stderr, so `runtime._classify_osascript_failure` still returns `AutomationDenied`. Every other probe error (for example -609, -1712) also re-raises with its own number"
    - "The probe keeps `with timeout of 120 seconds`, the argv convention (`tell application (item 1 of argv)`) and `count windows`; `_PROBE_TIMEOUT` stays 120.0"
    - "The TCC read selects `auth_reason` and `indirect_object_identifier`, and both are in `_TCC_FINGERPRINT`. A TCC.db `access` table without either column reads `schema-drift` (#318)"
    - "Every grant-map entry keeps `client` and `granted` with today's meaning. An entry carries `target` only when `indirect_object_identifier` is a real value (not NULL, empty or `UNUSED`)"
    - "A denied entry (`auth_value` 0) carries `reason` from `_TCC_REASON`, or `unknown(<n>)` for any other value. Reason 9 (`prompt-timeout`) also carries `remediation`, which names `tccutil reset <Service> <client>` with the `kTCCService` prefix stripped, then `doctor(request=True)` with someone at the screen. No other reason carries a remediation, and a granted or limited entry carries no `reason`"
    - "Three commits on `fix/317-318-doctor-probes`; subjects end `(#317)`, `(#318)` or `(#317, #318)`; each body ends with the Claude co-author trailer; no `.planning/` file in any commit; nothing pushed"
  artifacts:
    - path: "macos_apps_mcp/doctor.py"
      provides: "`_PROBE` swallows only -1728 from `count windows`"
      contains: "-1728"
    - path: "tests/test_doctor.py"
      provides: "template, osacompile and osascript error-filter tests for the probe"
      contains: "#317"
    - path: "macos_apps_mcp/deploy.py"
      provides: "`_TCC_REASON`, the widened fingerprint and SELECT, `target`/`reason`/`remediation` on grant-map entries"
      contains: "_TCC_REASON"
    - path: "tests/test_deploy.py"
      provides: "five-column TCC fixtures; timed-out, user-denied, granted-with-target, no-target and schema-drift tests"
      contains: "#318"
    - path: "docs/DAEMON.md"
      provides: "the grant map's new fields and the prompt-timeout recovery"
      contains: "prompt-timeout"
    - path: "CHANGELOG.md"
      provides: "[Unreleased] / ### Fixed bullets for #317 and #318"
      contains: "(#318)"
  key_links:
    - from: "doctor._PROBE `on error errMsg number errNum`"
      to: "runtime._classify_osascript_failure (matches `(-1743)`, `(-609)`, `(-1712)` in stderr)"
      via: "`error errMsg number errNum` re-raises every error except -1728 with its original number"
      pattern: "error errMsg number errNum"
    - from: "deploy._tcc_rows SELECT (5 columns)"
      to: "deploy.grant_report entry builder -> doctor.diagnose deployment.grant_identities"
      via: "rows unpack as (service, client, auth, reason, target)"
      pattern: "indirect_object_identifier FROM access"
---

<objective>
Fix two doctor issues on one branch.

- #317: `doctor(request=True)` reports Photos as `native_error` ("Can't get every window", -1728) on a granted, working surface. The probe launches Photos, Photos has no window yet, and it answers `count windows` with -1728. The answer proves that the event was delivered and answered, which is all the probe must prove.
- #318: the grant map reads only `auth_value`. A consent prompt that nobody answered (TCC `auth_reason` 9) looks the same as a click on Don't Allow, and the output gives no way out. AppleEvents rows also name no target app, so seven identical entries cannot say which app is granted.

Fix (orchestrator decisions, locked):
- #317 decision: change the probe AppleScript for every app. Inside `tell application (item 1 of argv)`, wrap `count windows` in `try … on error`. Swallow ONLY -1728. Re-raise everything else (the -1743 denial included) with its original message and number. Keep `with timeout of 120 seconds` and the argv convention. Do not remove Photos from `_AUTOMATION_APPS`; that belongs to the Phase 4 Photos decision.
- #318 decision: select `auth_reason` and `indirect_object_identifier`, add both to `_TCC_FINGERPRINT`, keep `client` and `granted` wire-stable, add `target`, `reason` and the reason-9 `remediation` as specified in Task 2. The optional `install-agent` re-read of the map (item 3 of #318) is out of scope.

Purpose: doctor is the user's only diagnosis tool for TCC. A false `native_error` sends the user to fix a grant that works. A silent timed-out denial leaves a surface broken with no remediation.

Output: three commits on `fix/317-318-doctor-probes`, nothing pushed, and a SUMMARY in the records lane.

Tracer note: no separate `type="tracer"` task. Each fix is one thin vertical slice (template → osascript → classifier → doctor surface; TCC.db → `_tcc_rows` → `grant_report` → doctor `deployment`). Task 1 and Task 2 each run RED first through the real seam.
</objective>

<lanes>
- **Code lane:** `/Users/andrei/Developer/macos-apps-mcp/.worktrees/doctor-probes`, branch `fix/317-318-doctor-probes` from `origin/develop` at `7c759d9`; `.venv` is synced. Every repo path in this plan is relative to it, and every `<automated>` command runs with it as cwd. Never touch the main checkout or another worktree.
- **Records lane:** `/Users/andrei/Developer/macos-apps-mcp/.worktrees/records-261011/.planning/quick/261011-imn-317-318-doctor-counts-an-answered-1728-p/`. This PLAN and the SUMMARY live there and stay uncommitted. No `.planning/` file in any code commit.
- Commit rules for every task: stage ONLY the files the task names (`git add <paths>`, never `add -A` / `add .`); one commit per task; the body ends with the trailer line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Nothing is pushed.
- PUBLIC repo: tests and docs use `ren.lav.macos-apps-mcp` and Apple bundle ids (`com.apple.mail`, `com.apple.Photos`, `com.apple.Notes`) only. The SUMMARY names no TCC client other than `ren.lav.macos-apps-mcp`.
- `rtk` filters pytest and grep output on this machine. For exact counts use `rtk proxy uv run pytest --collect-only -q | tail -1`. Baseline at `7c759d9`: **1960 unit tests** (97 integration deselected). The count goes up, never down.
</lanes>

<execution_context>
@~/.claude/gsd-core/workflows/execute-plan.md
@~/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@CLAUDE.md
@.claude/CLAUDE.md (main checkout; the code lane has AGENTS.md as CLAUDE.md)
@macos_apps_mcp/doctor.py (lines 47-66 `_PROBE` and its comment; 152-176 `_automation_surfaces`; 350-362 grant map into `deployment`)
@macos_apps_mcp/runtime.py (lines 88-92 the stderr markers; 156-183 `_classify_osascript_failure`)
@macos_apps_mcp/deploy.py (lines 76-147: `_TCC_FINGERPRINT`, `_TCC_AUTH`, `_tcc_rows`, `grant_report`, `grant_identities`)
@tests/test_doctor.py (lines 129-161 the probe tests; 361-399 the token-budget and `with timeout` tests)
@tests/test_deploy.py (lines 13-158: `_fake_tcc` and every TCC test)
@tests/test_mail_cleanup.py (lines 592-641: the house `osacompile -o /dev/null -` pattern)
@docs/DAEMON.md (lines 118-126 install-agent step 3; 281-285 the `grant_identities` bullet)
Issue text: `gh issue view 317` and `gh issue view 318` (repo `elfensky/macos-apps-mcp`)

Facts verified by the planner at `7c759d9` on this Mac (macOS 27.0.1), 2026-10-11 (do not re-derive):
- `_PROBE` today is the five lines `on run argv` / `with timeout of 120 seconds` / `tell application (item 1 of argv) to count windows` / `end timeout` / `end run`. `_automation_surfaces` reports `ok` when `run_osascript` returns, and `(False, e.kind, str(e))` on a `NativeError`. It needs no change.
- `_classify_osascript_failure` matches substrings of stderr: `(-1743)` → `AutomationDenied`, `(-609)` or `(-10810)` → `AppNotRunning`, `(-1712)` → `NativeTimeout`, anything else → plain `NativeError` (kind `native_error`). A -1728 today falls to plain `NativeError`, which is the #317 symptom.
- The new probe shape compiles with `osacompile -o /dev/null -`: `on run argv`, `with timeout of 120 seconds`, `tell application (item 1 of argv)`, `try`, `count windows`, `on error errMsg number errNum`, `if errNum is not -1728 then error errMsg number errNum`, `end try`, `end tell`, `end timeout`, `end run`.
- With `tell application (item 1 of argv)` replaced by `tell current application` and `count windows` replaced by `error "<msg>" number <n>`, the script runs under `osascript - Photos` (script on stdin, `Photos` as argv) and talks to no app. Measured: -1728 → exit 0, no stderr. -1743 → exit 1, stderr `…execution error: Not authorized to send Apple events to Photos. (-1743)`. -609 → exit 1, stderr ends `(-609)`. So the re-raise keeps the number that the classifier matches.
- The conftest fail-close seals `runtime.run_osascript` and `runtime.tracked_run` only. A test that calls `subprocess.run(["osascript", …])` or `osacompile` directly is not refused; `test_mail_cleanup.py` already runs `osacompile` that way.
- The system TCC.db on this Mac has both `auth_reason` and `indirect_object_identifier` in `access`. Its non-AppleEvents rows hold `UNUSED` in `indirect_object_identifier`. There is no user TCC.db on macOS 27 (#261). The system db holds no `kTCCServiceAppleEvents` rows. `grant_report()` today returns `reasons {'user': 'absent', 'system': None}` and 16 `kTCCServiceSystemPolicyAllFiles` entries, about 1.1k characters.
- Today every TCC fixture in `tests/test_deploy.py` builds a three-column `access` table (lines 15, 51, 59, 141). After the fingerprint grows, each of those reads `schema-drift`, so each must move to the five-column schema. `tests/test_doctor_deploy.py` fakes `deploy.grant_report` and builds no TCC.db.
- `test_report_stays_under_token_budget` (`tests/test_doctor.py`) calls `doc.diagnose(request=True)`, which reads this Mac's real TCC dbs through `deploy.grant_report`. The limit is 7000 characters.
- `CHANGELOG.md` `## [Unreleased]` is empty (line 7), with the 0.14.3 section below it in the house bullet form.
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: The Automation probe counts an answered -1728 as granted (#317, RED first)</name>
  <files>tests/test_doctor.py, macos_apps_mcp/doctor.py</files>
  <behavior>
    - Template: the stripped, non-empty lines of `doc._PROBE` equal, in this order, `on run argv`, `with timeout of 120 seconds`, `tell application (item 1 of argv)`, `try`, `count windows`, `on error errMsg number errNum`, `if errNum is not -1728 then error errMsg number errNum`, `end try`, `end tell`, `end timeout`, `end run`.
    - Compile: `doc._PROBE` compiles with `osacompile -o /dev/null -` (skip when `osacompile` is absent).
    - Error filter under real osascript, parametrized over -1728, -1743 and -609: the test first asserts that `tell application (item 1 of argv)` and `count windows` each occur exactly once in `doc._PROBE`. Then it replaces the first with `tell current application` and the second with `error "<message>" number <n>`, and runs `osascript - Photos` with the script on stdin (`timeout=30`, skip when `osascript` is absent). For -1728: exit 0. For -1743: exit non-zero, `(-1743)` in stderr, and `runtime._classify_osascript_failure(proc.stderr)` is an `AutomationDenied`. For -609: exit non-zero, `(-609)` in stderr, and the classifier returns an `AppNotRunning`.
    - The existing tests `test_probe_is_a_real_apple_event_with_consent_budget`, `test_probe_carries_applescript_side_timeout`, `test_automation_probe_ok` and `test_automation_probe_denied_carries_directive` pass unchanged.
  </behavior>
  <action>
1. RED, in `tests/test_doctor.py`, directly after `test_probe_is_a_real_apple_event_with_consent_budget`. Add the three tests from the behavior block; name them for #317 and give each a one-line docstring that cites #317. For the compile test, copy the house pattern of `test_every_applescript_constant_actually_compiles` (`shutil.which("osacompile")` skip, `subprocess.run(["osacompile", "-o", "/dev/null", "-"], input=…, capture_output=True, text=True)`). In the error-filter test, add one comment: `tell current application` plus `error` sends no Apple event, so no app launches and no consent prompt can appear. Use synthetic messages, for example `Photos got an error: Can't get every window.`, `Not authorized to send Apple events to Photos.` and `Connection is invalid.`. Import `AppNotRunning` and `AutomationDenied` from the existing import block (both are already imported). Run `uv run pytest -q tests/test_doctor.py`. The template test and the -1728 case must fail; the compile test and the -1743/-609 cases pass against today's template. Record the failing test ids in the SUMMARY.
2. GREEN, in `macos_apps_mcp/doctor.py` (per the #317 decision): rewrite `_PROBE` to the eleven-line shape from the behavior block, keeping the existing parenthesized string-concatenation style and two-space indentation per nesting level. Use the variable names `errMsg` and `errNum` (avoid one- or two-letter names; `st` is an AppleScript reserved word in this repo's history). Extend the comment above `_PROBE` by two or three sentences: an app that the probe itself launched can come up with no window and answer `count windows` with -1728 (#317, Photos); the event was delivered and answered, which is all the probe proves, so -1728 counts as `ok`; every other error, the -1743 denial included, re-raises with its original message and number, so `runtime._classify_osascript_failure` still types it. Do not change `_PROBE_TIMEOUT`, `_AUTOMATION_APPS` or `_automation_surfaces`.
3. Run the test file and the lints. Commit the two files only, with the subject `fix(doctor): count an answered -1728 probe as a working grant (#317)` and the trailer from the lanes block.
  </action>
  <verify>
    <automated>uv run pytest -q tests/test_doctor.py && uv run ruff check . && uv run ruff format --check . && grep -q "#317" macos_apps_mcp/doctor.py && grep -q "if errNum is not -1728 then error errMsg number errNum" macos_apps_mcp/doctor.py && grep -q '"Photos",' macos_apps_mcp/doctor.py && grep -q "#317" tests/test_doctor.py && git diff --quiet origin/develop -- macos_apps_mcp/runtime.py macos_apps_mcp/deploy.py</automated>
  </verify>
  <done>RED was recorded, then GREEN. `_PROBE` swallows only -1728 from `count windows`. The real-osascript test proves that -1728 exits 0 and that -1743 and -609 still classify as `AutomationDenied` and `AppNotRunning`. The probe compiles. Photos stays in `_AUTOMATION_APPS`. `runtime.py` is untouched. ruff is clean. There is one commit with a subject that ends `(#317)`.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: The grant map names the denial reason and the AppleEvents target (#318, RED first)</name>
  <files>tests/test_deploy.py, macos_apps_mcp/deploy.py, docs/DAEMON.md</files>
  <behavior>
    - Timed-out denial: the row (`kTCCServiceAppleEvents`, `ren.lav.macos-apps-mcp`, auth 0, reason 9, target `com.apple.mail`) gives an entry with `client` `ren.lav.macos-apps-mcp`, `target` `com.apple.mail`, `granted` False, `reason` `prompt-timeout`, and a `remediation` that contains `tccutil reset AppleEvents ren.lav.macos-apps-mcp` and `doctor(request=True)`.
    - The remediation uses the row's own service: a timed-out `kTCCServiceCalendar` row (target `UNUSED`) gives a remediation that contains `tccutil reset Calendar ren.lav.macos-apps-mcp`.
    - User denial: (`kTCCServiceAppleEvents`, `ren.lav.macos-apps-mcp`, 0, 2, `com.apple.Notes`) gives exactly `{"client": "ren.lav.macos-apps-mcp", "target": "com.apple.Notes", "granted": False, "reason": "user-consent"}` (no `remediation`).
    - Unknown reason: a denied row with reason 42 gives `reason` `unknown(42)` and no `remediation`.
    - Granted with target: (`kTCCServiceAppleEvents`, `ren.lav.macos-apps-mcp`, 2, 3, `com.apple.Photos`) gives exactly `{"client": "ren.lav.macos-apps-mcp", "target": "com.apple.Photos", "granted": True}` (no `reason`).
    - No target: granted rows whose `indirect_object_identifier` is NULL, `""` or `UNUSED` give entries without a `target` key.
    - Schema drift: an `access` table that lacks `auth_reason`, and one that lacks `indirect_object_identifier` (each with the other four columns), make `deploy._tcc_rows` return `(None, "schema-drift")`.
    - Existing tests keep passing after their fixtures move to the five-column schema. The only expectation change is in `test_grant_identities_maps_rows`: its denied `kTCCServiceSystemPolicyAllFiles` row now carries `"reason": "user-set"`, because its fixture row gets `auth_reason` 3.
  </behavior>
  <action>
1. RED, in `tests/test_deploy.py`. Add one module helper `_tcc_db(path, rows)` that creates `access (service TEXT, client TEXT, auth_value INT, auth_reason INT, indirect_object_identifier TEXT)` and inserts the given 5-tuples. Rewrite `_fake_tcc` on top of it with realistic rows: the two Calendar grants become `(…, 2, 2, "UNUSED")`, and the FDA denial becomes `(…, 0, 3, "UNUSED")`. Move the inline three-column fixtures in `test_grant_identities_merges_system_db_fda` and `test_grant_identities_limited_carries_status` onto `_tcc_db` (granted rows: reason 2, target `UNUSED`; the limited row: reason 2, target `UNUSED`). Leave `test_tcc_rows_dropped_column_is_schema_drift` with its own explicit table. Update the `test_grant_identities_maps_rows` expectation as the behavior block says. Add the new tests from the behavior block in a `# --- #318 …` section after the C7 block, each with a one-line docstring or comment that cites #318; parametrize where it keeps the code short (the reason cases; the three no-target values; the two dropped columns). Pin `deploy._TCC_SYSTEM_DB` to an absent path in every `grant_identities`/`grant_report` test, as the existing tests do, so this Mac's real rows cannot leak in. Run `uv run pytest -q tests/test_deploy.py`. The new tests fail, and the moved fixtures still pass (they have extra columns that today's code ignores), except `test_grant_identities_maps_rows`, which now expects `reason`. Record the failing test ids in the SUMMARY.
2. GREEN, in `macos_apps_mcp/deploy.py` (per the #318 decision):
   - Add `auth_reason` and `indirect_object_identifier` to `_TCC_FINGERPRINT["access"]`. Extend its comment by one line: both columns exist in `access` since macOS 11 / 10.14, and the project floor is macOS 14.
   - Below `_TCC_AUTH`, add `_TCC_REASON`, a dict from TCC `auth_reason` integers to names: 1 `error`, 2 `user-consent`, 3 `user-set`, 4 `system-set`, 5 `service-policy`, 6 `mdm`, 7 `override`, 8 `missing-usage-string`, 9 `prompt-timeout`, 10 `preflight-unknown`, 11 `entitled`, 12 `app-type-policy`. Give it a one-line comment that cites #318: a prompt that nobody answers is stored as a denial with reason 9.
   - In `_tcc_rows`, select `service, client, auth_value, auth_reason, indirect_object_identifier`. Keep the bound `?` marks; interpolate nothing else.
   - In `grant_report`, unpack each row as `service, client, auth, reason, target`. Build the entry as `client`, then `target` only when `target not in (None, "", "UNUSED")`, then `granted` (`auth == 2`, unchanged), then the existing `status` rule unchanged. When `auth == 0`, add `reason` = `_TCC_REASON.get(reason, f"unknown({reason})")`. When `auth == 0` and the reason is 9, add `remediation`: one or two sentences, for example "The consent prompt timed out with nobody at the screen; macOS keeps that as a denial and does not ask again. Run `tccutil reset <Service> <client>`, then doctor(request=True) with someone at the screen." Here `<Service>` is `service.removeprefix("kTCCService")` and `<client>` is the row's client. Name the row's own service only, never `All`. Update the `grant_report` docstring by one sentence about the new keys (#318).
   - Do not change `grant_identities`, `_TCC_AUTH`, the read reasons or `doctor.py`.
3. In `docs/DAEMON.md`:
   - Extend the `deployment.grant_identities` bullet (around line 283) by one or two sentences. Each entry has `client` and `granted`. An AppleEvents entry also has `target`, the bundle id of the controlled app. A denied entry has `reason` (TCC's `auth_reason`, for example `user-consent` or `prompt-timeout`). A `prompt-timeout` entry also has a `remediation` with the `tccutil reset <Service> ren.lav.macos-apps-mcp` command.
   - After install-agent step 3 (around line 124), add one sentence: if a prompt times out anyway, doctor shows that row with `reason: "prompt-timeout"` and the reset command to run before `doctor(request=True)` with someone at the screen.
4. Run `uv run pytest -q tests/test_deploy.py tests/test_doctor.py tests/test_doctor_deploy.py` and the lints. Commit the three files only, with the subject `fix(doctor): the grant map names the TCC denial reason and the AppleEvents target (#318)` and the trailer from the lanes block.
  </action>
  <verify>
    <automated>uv run pytest -q tests/test_deploy.py tests/test_doctor.py tests/test_doctor_deploy.py && uv run ruff check . && uv run ruff format --check . && grep -q "_TCC_REASON" macos_apps_mcp/deploy.py && grep -q "indirect_object_identifier FROM access" macos_apps_mcp/deploy.py && grep -q "prompt-timeout" macos_apps_mcp/deploy.py && grep -q "tccutil reset" macos_apps_mcp/deploy.py && grep -q "#318" tests/test_deploy.py && grep -q "prompt-timeout" docs/DAEMON.md && T1="$(git log -1 --format=%H --grep='(#317)$')" && test -n "$T1" && git diff --quiet "$T1" -- macos_apps_mcp/doctor.py</automated>
  </verify>
  <done>RED was recorded, then GREEN. The TCC read selects and fingerprints the two new columns, and an old three-column table reads `schema-drift`. Entries keep `client` and `granted`; AppleEvents entries carry `target`; denied entries carry `reason`; a timed-out entry carries the exact `tccutil reset <Service> <client>` remediation. DAEMON.md names the new fields and the recovery. `doctor.py` is unchanged by this task. ruff is clean. There is one commit with a subject that ends `(#318)`.</done>
</task>

<task type="auto">
  <name>Task 3: CHANGELOG, full verification and the careful device check</name>
  <files>CHANGELOG.md</files>
  <action>
1. In `CHANGELOG.md`, under `## [Unreleased]`, add a `### Fixed` heading with two bullets in the house form `- **bold lead** (#NNN) — why.`. Wrap them like the 0.14.3 bullets (two-space hanging indent, about 88 columns), with one blank line around the heading.
   - #317: doctor reports an Automation surface `ok` when the app answers its probe with -1728. Photos launched by the probe had no window yet and answered `count windows` with "Can't get every window" (-1728), so doctor reported a granted, working surface as `native_error`. The probe now counts that answer for every app. A denial (-1743) and every other error report as before.
   - #318: doctor's grant map says why a TCC row is denied and which app an Automation row targets. A consent prompt that nobody answers is stored by macOS as a denial (`auth_reason` 9), and doctor showed it as a plain `granted: false`. A denied entry now carries `reason` (`prompt-timeout`, `user-consent`, …), and a `prompt-timeout` entry also carries the `tccutil reset` command that clears it. AppleEvents entries carry `target`, the controlled app's bundle id.
2. Commit `CHANGELOG.md` only, with the subject `docs(changelog): doctor probe and grant-map fixes (#317, #318)` and the trailer from the lanes block.
3. Final checks from the code-lane root. Run each one separately, write its output to a scratch file outside the repo, and record its exit code (`echo "exit=$?"` right after the command; never pipe the command into `tail` before the code is saved): `uv run pytest -q`; `MACOS_APPS_ALLOW_SEND=mail uv run pytest -q`; `uv run ruff check .`; `uv run ruff format --check .`. Then run `rtk proxy uv run pytest --collect-only -q | tail -1`; the unit count must be above 1960. Record all four exit codes and the count in the SUMMARY. If any check fails, report the actual output; do not weaken a test.
4. Read-only grant-map check. From the code-lane venv, call `deploy.grant_report()` once and print: the `reasons` dict, the total number of entries, the number with `target`, the number with `reason`, the number with `remediation`, and the full entries whose `client` is `ren.lav.macos-apps-mcp` (no other client). Record that output in the SUMMARY. On this Mac (macOS 27, no user TCC.db) expect zero `target` entries: the system db has no AppleEvents rows. Denied FDA rows may carry `reason`.
5. Device check of the new probe (careful; per the #317 decision). Read both TCC dbs read-only (`sqlite3 -readonly "file:<path>?mode=ro"` on `~/Library/Application Support/com.apple.TCC/TCC.db` and `/Library/Application Support/com.apple.TCC/TCC.db`; an absent or unreadable db counts as no rows). Look for rows with `service = 'kTCCServiceAppleEvents' AND indirect_object_identifier = 'com.apple.Photos' AND auth_value = 2`.
   - If there are no such rows, SKIP the device run. A consent prompt with nobody at the screen is exactly the #318 timeout. Write in the SUMMARY: "device probe skipped: no Automation grant for Photos is readable for this shell's app". The planner expects this result on this Mac.
   - If rows exist, find this shell's responsible app: walk the parent chain with `ps -o ppid= -o comm= -p <pid>` from `$$` to the first command path that contains `.app/`, and read that bundle's `CFBundleIdentifier` with `defaults read "<path>.app/Contents/Info" CFBundleIdentifier`. Run the probe only if that bundle id has a granted row. Note first whether Photos runs (`pgrep -x Photos`). Then run `uv run python -c` that imports `doctor` and `runtime` from `macos_apps_mcp` and prints `repr(runtime.run_osascript(doctor._PROBE, "Photos", timeout=doctor._PROBE_TIMEOUT))`; record the exit code and the output or the error. If the probe launched Photos, quit it afterwards with `osascript -e 'tell application "Photos" to quit'`. Do not name the shell's bundle id in the SUMMARY; write "this shell's app".
6. Write the SUMMARY in the records lane. Include the RED test ids of Tasks 1 and 2, the three commit hashes and subjects, the four exit codes, the unit count, the grant-map counts, and the device-check result or the skip line. Under "Follow-up candidates", name #318 item 3: `install-agent` re-reads the grant map after its prompt pass and prints every `prompt-timeout` row with its reset command, because that pass is where unattended timeouts happen.
  </action>
  <verify>
    <automated>uv run pytest -q && MACOS_APPS_ALLOW_SEND=mail uv run pytest -q && uv run ruff check . && uv run ruff format --check . && awk '/^## \[Unreleased\]/{u=1;next} /^## \[/{u=0} u&&/^### /{s=$2} u&&s=="Fixed"&&/\(#317\)/{a++} u&&s=="Fixed"&&/\(#318\)/{b++} END{exit !(a>=1&&b>=1)}' CHANGELOG.md && N="$(git rev-list --count origin/develop..HEAD)" && test "$N" -eq 3 && S="$(git log --format=%s origin/develop..HEAD)" && ! printf '%s\n' "$S" | grep -qvE '\((#317|#318|#317, #318)\)$' && B="$(git log --format=%B origin/develop..HEAD)" && printf '%s\n' "$B" | awk '/^Co-Authored-By: Claude Opus 5\.5 <noreply@anthropic\.com>$/{n++} END{exit !(n==3)}' && F="$(git diff --name-only origin/develop..HEAD)" && ! printf '%s\n' "$F" | grep -q '^\.planning/' && ! git rev-parse -q --verify refs/remotes/origin/fix/317-318-doctor-probes >/dev/null</automated>
  </verify>
  <done>`[Unreleased]` / `### Fixed` has one #317 bullet and one #318 bullet. Both pytest runs, ruff check and ruff format exit 0, and the unit count is above 1960. There are exactly three commits, each with a subject that ends `(#317)`, `(#318)` or `(#317, #318)` and the trailer. No `.planning/` file is in any commit, and nothing is pushed. The SUMMARY in the records lane records the exit codes, the count, the grant-map counts (no client other than `ren.lav.macos-apps-mcp`), the device-probe result or its skip line, and the `install-agent` follow-up.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| doctor → target app (Apple event) | The probe sends one real event to each Automation app; its error number decides the surface verdict |
| TCC.db → doctor output | Rows from a system-owned SQLite db become strings in the doctor report |
| doctor output → user / model | A remediation string tells a person which command to run |
| Code lane → public repo | Code, tests, docs, CHANGELOG and commit text become public after the PR |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-imn-01 | Spoofing (false `ok`) | `_PROBE` error filter | high | mitigate | Only -1728 is swallowed; the -1743 denial and every other error re-raise with the original number. Task 1 runs the filter under real osascript and proves -1743 → `AutomationDenied` and -609 → `AppNotRunning` |
| T-imn-02 | Tampering (SQL) | `_tcc_rows` SELECT | medium | mitigate | Read-only opener unchanged (`_open_sqlite_ro`); only column names change; service values stay bound through `?` marks; nothing else is interpolated |
| T-imn-03 | Tampering (mis-parse on a changed schema) | grant map | medium | mitigate | Both new columns join `_TCC_FINGERPRINT`, so a TCC.db without them reads `schema-drift` instead of a wrong claim; Task 2 tests both dropped columns |
| T-imn-04 | Denial of service (destructive advice) | reason-9 `remediation` | medium | mitigate | The command names the row's own service and client only (never `All`); doctor never runs it; no remediation for any other reason |
| T-imn-05 | Elevation of privilege (unattended consent prompt) | Task 3 device check | medium | mitigate | The probe runs only after a read-only TCC check proves an existing Photos grant for this shell's app; otherwise the run is skipped |
| T-imn-06 | Information disclosure | SUMMARY, tests, docs | low | mitigate | Only `ren.lav.macos-apps-mcp` and Apple bundle ids appear; the grant-map check prints counts plus our own entries; the shell's bundle id is not named |
| T-imn-SC | Tampering | npm/pip/cargo installs | high | mitigate | No package is added; `uv.lock` is not touched |
</threat_model>

<verification>
Run in the code lane after Task 3:

- `uv run pytest -q`, `MACOS_APPS_ALLOW_SEND=mail uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`: each exits 0, and each exit code is recorded.
- `rtk proxy uv run pytest --collect-only -q | tail -1`: unit count above 1960.
- `git log --oneline origin/develop..HEAD`: exactly three commits, with subjects ending `(#317)`, `(#318)` and `(#317, #318)`; each body ends with the `Co-Authored-By: Claude Opus 5.5` trailer.
- `git diff --name-only origin/develop..HEAD` lists only `macos_apps_mcp/doctor.py`, `tests/test_doctor.py`, `macos_apps_mcp/deploy.py`, `tests/test_deploy.py`, `docs/DAEMON.md` and `CHANGELOG.md`. `git status -sb` shows no push.
- On-device confirmation after the next daemon rebuild (orchestrator or operator, not the executor): `doctor(request=True)` with Photos quit beforehand reports `photos` as `ok`; `doctor().deployment.grant_identities` on the Sequoia rig shows one AppleEvents entry per `target`.
</verification>

<success_criteria>
- An Automation probe that the app answers with -1728 reports `ok`; a denial still reports `automation_denied`, and other errors keep their kinds.
- The grant map names each AppleEvents row's target, names the reason of each denied row, and gives the exact `tccutil reset` command for a timed-out prompt.
- A TCC.db without the two new columns reads `schema-drift`.
- The CHANGELOG carries both fixes, and the suite is green with more than 1960 unit tests.
</success_criteria>

<out_of_scope_flags>
Record these in the SUMMARY as follow-up candidates. Do not implement them here.
- #318 item 3: `install-agent` re-reads the grant map after its prompt pass and prints each `prompt-timeout` row with its reset command.
- `test_report_stays_under_token_budget` reads this Mac's real TCC dbs through `deploy.grant_report`, so its size depends on the machine. If it fails in Task 2 or Task 3 because of real rows, stop and report the length; pinning both TCC paths in that test is a separate change.
</out_of_scope_flags>

<output>
Create `/Users/andrei/Developer/macos-apps-mcp/.worktrees/records-261011/.planning/quick/261011-imn-317-318-doctor-counts-an-answered-1728-p/261011-imn-SUMMARY.md` when done (uncommitted).
</output>
