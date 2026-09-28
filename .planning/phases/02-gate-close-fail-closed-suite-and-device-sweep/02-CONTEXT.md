# Phase 2: Gate Close — Fail-Closed Suite and Device Sweep - Context

**Gathered:** 2026-09-28
**Status:** Ready for planning

<domain>
## Phase Boundary

The suite tells the truth in three shapes:

- **Read-only** (GATE-07): `MACOS_APPS_READ_ONLY=1 uv run pytest` is green, and CI keeps it green.
- **Unit** (GATE-11): `uv run pytest` runs no live `pgrep` or `ps` on the dev machine.
- **On device** (GATE-12): `uv run pytest -m integration` is green on macOS 27.0 against a daemon
  rebuilt from `develop`. `ruff check` and `ruff format --check` pass.

The phase closes with the v0.12.0 release (D-09). The phase adds no tool features. It changes
adapter code only for small bugs that the sweep finds (D-07).

Measured on `develop` `c75fa76` (2026-09-26):

- GATE-07: 12 failed, 1458 passed, 1 skipped, 80 deselected. These are the same 12 as before
  Phase 1 (01-13-SUMMARY).
- GATE-11: the `pgrep` calls are gone (plan 01-02). **15** tests still spawn a live `ps` through
  `doctor._process_name`. The roadmap says 17. That count is stale.
- GATE-12: 80 integration tests in 7 files. Phase 1 ran only parts of this suite on device.

</domain>

<decisions>
## Implementation Decisions

### Read-only suite (GATE-07)
- **D-01:** Split the 12 failing tests by intent.
  - **4 fact tests** check what a tool IS. They read `registry.TOOLS` (every record, whether or
    not it is registered), so they run in both modes. The tests are
    `test_mail_duplicates_is_registered_read_only`, `test_every_write_tool_is_audit_classified`,
    `test_server_snapshot_sources_are_derived_and_satisfy_the_protocol` and
    `test_run_shortcut_carries_open_world_hint`. The last one reads the hint from the record
    (`open_world` / `annotations`), not from the FastMCP tool list.
  - **8 call tests** in `tests/test_server.py` call a write tool and expect `ToolError`. They skip
    in read-only mode through **one** named marker that carries a reason. The marker has the same
    shape as `_gate_off_only` (`tests/test_doctor_deploy.py:25`).
  - No test wraps a plain function in `_guard` itself. A test copy of the server's wrapping would
    prove the copy, not the server.
  - The absence proof stays with `tests/test_gate_on_dispatch.py`. It compares the registered set
    to the FastMCP list in a read-only subprocess.
- **D-02:** CI gets a second test step, `MACOS_APPS_READ_ONLY=1 uv run pytest`, in
  `.github/workflows/ci.yml`. It costs about 15 s. Reason: the read-only debt has grown before.
  Card 2 added 2 new read-only failures, and only a manual check caught them (01-13).

### Device sweep (GATE-12)
- **D-03:** The session shape comes from plan 01-08:
  1. The owner confirms that they are at the Mac.
  2. Before any Mail test, Claude checks that the watchdog is loaded
     (`launchctl list | grep ren.lav.mail-watchdog`), that its log line is fresh, and that Mail is
     idle.
  3. Claude runs the commands.
- **D-04:** The Mail write tests use **2 marker mails, never real mail**.
  - One plan step seeds them once, before the sweep: it sends 2 mails with a fixed marker subject
    to `andrei@lav.ren`.
  - The mails stay in the INBOX, and each run reuses them.
  - The `inbox_messages` fixture (`tests/test_integration.py:1524`) selects by marker subject only.
  - When it finds fewer than 2, it fails with a message that names the seed command. It **never
    falls back** to other INBOX messages.

  This applies to every test that takes `inbox_messages`: the dry-run move, move → undo, the
  cross-account move and the status flip. Each run must leave the marker mails back in the INBOX.
  If a run does not, the next run fails loudly, which is the intended behaviour.
- **D-05:** The sweep runs with `MACOS_APPS_ALLOW_SEND=mail`, so
  `test_send_to_self_and_delete_draft_round_trip` runs. The only address in that file stays
  `SELF_ADDRESS` (`andrei@lav.ren`).
- **D-06:** "Green" means 0 failed and 0 errors. `02-VERIFICATION.md` names each skip and each xfail
  with its reason. A skip is acceptable when this Mac does not have the data (for example "no user
  playlists").

### Sweep failure policy (GATE-12)
- **D-07:** Small fixes land in this phase. Other bugs are filed.
  - A bug is fixed in Phase 2 when the fix fits one PR, touches one adapter and is not a Mail
    write path. The fix lands with a unit test.
  - Any other bug gets a GitHub issue for the phase that owns it: Mail goes to 02.1,
    Calendar/Reminders to 3, Notes/Photos to 4. The test is then marked
    `xfail(strict=True, reason="#<issue>")`. A strict xfail fails the run when the bug is fixed,
    so the mark cannot go stale.
- **D-08:** When the test is wrong and the code is right (for example, macOS 27 changed a
  behaviour), an assertion changes only when the new behaviour is observed on device **and
  recorded**. For Mail, the record goes in `docs/mail-applescript-facts.md`. For other apps, it
  goes in the PR body. No test is changed only to make it pass.

### Release at phase close
- **D-09:** The last plan cuts **v0.12.0** per `docs/RELEASING.md`, after the sweep is green. The
  version is 0.12.0 because there are `feat` commits and a contract change since v0.11.0.
  - The owner approves the cut before `main` and the tag are pushed.
  - Then the release is built, signed, notarized and stapled, and the zip is made after stapling.
    The daemon is installed and kickstarted.
  - Proof: `doctor().version` reports `0.12.0` and `doctor().build` reports the tagged sha.
  - The release notes state Phase 1's dry-run contract change: `delete_event`, `delete_draft` and
    `delete_note` now default to `dry_run=True`, and `update_note` gained a dry run.

  — **Reversibility:** one-way — pushing a tag and a GitHub release publishes the version. After
  that, only a new version can change it.

### Claude's Discretion
- **GATE-11 fix:** `doctor._process_name` (`macos_apps_mcp/doctor.py:250`) calls
  `subprocess.run(["ps", "-o", "comm=", ...])` directly, so it skips the locked seam. Route it
  through `runtime.tracked_run`, qualified. The existing `_no_live_process_probe` fakes in
  `tests/test_doctor.py` and `tests/test_doctor_deploy.py` then cover it: an empty stdout makes the
  function return `"pid <n>"`. Also extend `tests/test_native_seam.py`, so that a direct
  `subprocess` call in `doctor.py` or `adapters/*.py` fails the tripwire.
- **GATE-11 proof:** one run of the unit suite with a `Popen` spy that counts spawned `ps`/`pgrep`
  processes per test (see Specifics). The count must be 0.
- **Plan order:**
  1. GATE-07 and GATE-11, unit-only PRs.
  2. Seed the marker mails.
  3. Rebuild and reinstall a dev-build daemon from `develop` (Phase 1 D-06 pattern).
  4. Run the sweep.
  5. Add the fixes and strict xfails. Run the affected tests on device again.
  6. Cut the release (D-09).
- **Other side effects:** Music playback, volume and shuffle, and the Safari tab run as written.
  Each of these tests restores the state it changed.
- **Marker-mail details:** the subject text, the seed command and the choice of account are the
  planner's call. Check how `scratch_mailbox` (`tests/test_integration.py:1493`) picks its account,
  so that the marker INBOX and the scratch mailbox agree for the same-account move tests.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Scope and requirements
- `.planning/ROADMAP.md` §"Phase 2: Gate Close" — goal and three success criteria.
- `.planning/REQUIREMENTS.md` — GATE-07, GATE-11, GATE-12.
- `.planning/phases/01-gate-land-the-spiked-architecture-cuts/01-CONTEXT.md` — D-06 (dev builds in
  the gate, release after Phase 2), D-07 (landing flow: rebase-merge, Claude merges when CI, local
  checks and review are clean), D-08 (stop for the owner at device steps only).

### Prior evidence
- `.planning/phases/01-gate-land-the-spiked-architecture-cuts/01-02-SUMMARY.md` — the GATE-11 test
  half that already landed. It describes the `_no_live_process_probe` pattern.
- `.planning/phases/01-gate-land-the-spiked-architecture-cuts/01-08-SUMMARY.md` — the device
  session shape and the watchdog precondition commands (D-03).
- `.planning/phases/01-gate-land-the-spiked-architecture-cuts/01-13-SUMMARY.md` — the read-only
  baseline of 12 failures, and the `_gate_off_only` convention.

### Architecture and Mail rules
- `CLAUDE.md` — the three tiers gated at registration (a gated-off tool is absent), the worktree
  lanes and the verification commands.
- `docs/mail-applescript-facts.md` — read FIRST before any Mail change. D-08 records new Mail
  behaviour here.
- `.planning/codebase/TESTING.md` — test seams and fixtures.

### Release and daemon
- `docs/RELEASING.md` — two-file version bump, `--no-ff` cut, `doctor().version` and
  `doctor().build` proof.
- `docs/DAEMON.md` — build, sign, notarize, staple, install, kickstart.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `registry.TOOLS` / `ToolRecord` (`macos_apps_mcp/registry.py`): every tool's record, with
  `registered=False` kept for gated-off tools. The record also carries `open_world` and
  `annotations`. D-01's 4 fact tests read these.
- `tests/test_doctor_deploy.py:25` `_gate_off_only`: the skip-marker shape for D-01.
- `tests/test_gate_on_dispatch.py`: the subprocess absence proof in default, `ALLOW_SEND=mail`
  and `READ_ONLY=1` modes.
- `tests/conftest.py:213`: the autouse lock on `run_osascript`, `body_file` and `tracked_run`.
- `tests/test_doctor.py:21` and `tests/test_doctor_deploy.py:9` `_no_live_process_probe`: the fakes
  that the GATE-11 fix reuses.
- `tests/test_integration.py:1493` `scratch_mailbox`, `:1524` `inbox_messages`: the fixtures that
  D-04 changes.
- `tests/integration/test_mail_outbound.py`: `SELF_ADDRESS` and the real-send `skipif` for D-05.

### Established Patterns
- In read-only mode, a gated-off tool gets its record, and the decorator returns the plain function
  without `_guard` (`macos_apps_mcp/server.py:180-182`). That is why the 8 call tests raise a raw
  `ValueError` or `AppNotRunning` in that mode.
- Seam calls are qualified: `from .. import runtime`, then `runtime.tracked_run(...)` (#176).
- Every Mail write is verified by running it on device with the watchdog running.

### Integration Points
- `macos_apps_mcp/doctor.py:250` `_process_name`: the one direct `subprocess` call that is left.
- `.github/workflows/ci.yml:30`: the current single `uv run pytest` step. D-02 adds a second step
  after it.

</code_context>

<specifics>
## Specific Ideas

- This Mac runs macOS 27.0 (build 26A428).
- The 15 live-`ps` tests are 8 in `tests/test_doctor.py` and 7 in `tests/test_doctor_deploy.py`.
  Each spawns `ps -o comm=` twice: once for its own pid and once for its parent pid.
- The GATE-11 measurement method: a pytest plugin, loaded with `-p`, patches
  `subprocess.Popen.__init__`. It records each argv whose basename is `ps` or `pgrep`, keyed by the
  running test's nodeid, and prints the count at session end. The same plugin proves 0 after the
  fix.
- The 8 call tests: `test_create_reminder_rejects_out_of_range_priority`,
  `test_create_event_all_day_rejects_utc_offset`, `test_update_event_all_day_rejects_utc_offset`,
  `test_create_reminder_recurrence_without_due_rejected`, `test_create_event_rejects_bad_rrule`,
  `test_create_event_rejects_empty_start`, `test_write_tool_converts_native_error_to_agent_directive`
  and `test_optional_datetime_parse_error_names_the_field`.

</specifics>

<deferred>
## Deferred Ideas

- **Daemon code seal** (STATE.md pending todo, found in 01-10): the daemon writes
  `__pycache__/*.pyc` into the signed `Contents/lib` after its first launch. The fix belongs in
  `scripts/build_app.sh`: precompile the `.pyc` files before signing, or run with `-B`. The
  discussion did not decide whether this fix goes into the D-09 release build. Nothing fails today.

</deferred>

---

*Phase: 02-gate-close-fail-closed-suite-and-device-sweep*
*Context gathered: 2026-09-28*
