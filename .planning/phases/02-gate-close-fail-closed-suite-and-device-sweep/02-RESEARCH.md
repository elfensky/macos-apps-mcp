# Phase 2: Gate Close — Fail-Closed Suite and Device Sweep - Research

**Researched:** 2026-09-28
**Domain:** pytest test-infrastructure fidelity, CI, macOS daemon device verification, release cut
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

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
- **D-09:** The last plan cuts **v0.12.0** per `docs/RELEASING.md`, after the sweep is green. The
  version is 0.12.0 because there are `feat` commits and a contract change since v0.11.0.
  - The owner approves the cut before `main` and the tag are pushed.
  - Then the release is built, signed, notarized and stapled, and the zip is made after stapling.
    The daemon is installed and kickstarted.
  - Proof: `doctor().version` reports `0.12.0` and `doctor().build` reports the tagged sha.
  - The release notes state Phase 1's dry-run contract change: `delete_event`, `delete_draft` and
    `delete_note` now default to `dry_run=True`, and `update_note` gained a dry run.
  - Reversibility: one-way — pushing a tag and a GitHub release publishes the version.

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

### Deferred Ideas (OUT OF SCOPE)

- **Daemon code seal** (STATE.md pending todo, found in 01-10): the daemon writes
  `__pycache__/*.pyc` into the signed `Contents/lib` after its first launch. The fix belongs in
  `scripts/build_app.sh`: precompile the `.pyc` files before signing, or run with `-B`. The
  discussion did not decide whether this fix goes into the D-09 release build. Nothing fails today.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| GATE-07 | `MACOS_APPS_READ_ONLY=1 uv run pytest` passes | Exact 12 failing tests re-confirmed live (§GATE-07 Evidence); root cause traced to `server.py:181` gate-off short-circuit and `registry.py` `registered=True`-only filters; fix shape (fact tests read `registry.TOOLS` directly, call tests get one skip marker) is fully specified with prior-art from 01-13 |
| GATE-11 | Doctor unit tests no longer run live `pgrep`/`ps` | Exact leak isolated to `doctor._process_name` (`doctor.py:250-262`), NOT `app_process_info` (already locked); fix is a one-line seam swap; AST-tripwire extension designed to distinguish a `subprocess.run`/`Popen` **call** from a mere `subprocess.TimeoutExpired` exception reference (shortcuts.py has the latter, legitimately) |
| GATE-12 | `uv run pytest -m integration` green on-device | 80 integration tests in 7 files confirmed by live collection; `scratch_mailbox`/`inbox_messages` account-agreement gap identified with fix shape; daemon dev-build rebuild/reinstall/kickstart steps sourced from 01-10/01-13/01-14 SUMMARYs (already run 3x this milestone); release cut steps and version-match enforcement (`tests/test_packaging.py`) confirmed |
</phase_requirements>

## Summary

This phase touches no new library, no new adapter, and (mostly) no new dependency — it makes three
existing claims about the test suite true, then cuts a release. All three failure modes were
reproduced live in this research session, not assumed from CONTEXT.md's prior measurement.

**GATE-07** (12 read-only failures) has one shared root cause across all 12 tests, not twelve
separate bugs: `server.py`'s `_tool` decorator (`server.py:181`, `if not registered: return f`)
hands back the **undecorated** function for a gated-off tool — no `_guard`, so a raw `ValueError`
escapes instead of a `ToolError`. That explains the 8 call tests. The 4 fact tests fail for a
different, related reason: `registry.write_tools()` and `registry.snapshot_sources()`
(`registry.py:105-118`) filter to `r.registered` — true by construction in a normal process, always
false under `MACOS_APPS_READ_ONLY=1` — so every "which tools are writes" assertion collapses to the
empty set. `registry.removes_content_tools()` (`registry.py:140-148`) already shows the fix
pattern: it iterates **every** record, registered or not.

**GATE-11** (live `ps`) is not spread across 15 tests independently either — it is one function,
`doctor._process_name` (`doctor.py:250-262`), called twice per `diagnose()` invocation (self pid +
parent pid) by `_responsible_process`. It is the **only** direct `subprocess.run` call left in the
codebase's native-reaching modules; `app_process_info` (`runtime.py:103-114`, used by the
Automation-surface process line) already goes through the locked `tracked_run` seam and is already
faked by both doctor test files' `_no_live_process_probe` autouse fixtures. The fix is a drop-in
seam swap, already covered by tests that exist today.

**GATE-12** (device sweep) is process, not code: rebuild-and-install is a well-worn path (run three
times already in Phase 1 — 01-10, 01-13, 01-14 — with an identical, working command sequence).
The one real design gap is that `inbox_messages` (`tests/test_integration.py:1524`) currently picks
"the first non-empty INBOX in `overview()` order" with no account preference, while
`scratch_mailbox` (`tests/test_integration.py:1493`) deterministically prefers a **non-Gmail**
account. On a multi-account Mac these two fixtures can silently disagree about which account they
operate on, which breaks the same-account move tests' implicit assumption. D-04's rewrite must
make `inbox_messages` select by marker subject **within the same account** `scratch_mailbox` chose.

**Primary recommendation:** Do GATE-07 and GATE-11 first, as small pure-unit PRs (no device
needed, both fixes are mechanical and already covered by existing tests/fixtures) — then the device
sweep only has to prove GATE-12 and any small D-07 bug fixes, not chase read-only/pgrep noise
during a live Mail session.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Tool registration gate (read-only) | API / Backend (`server.py` `_tool` decorator) | — | Decides at import time whether a write tool's dispatch function is wrapped in `_guard`; this IS the gate |
| Tool fact surface (`registry.TOOLS`) | API / Backend (`registry.py`) | — | Source of truth for "what a tool IS" independent of whether it registered — the seam the 4 fact tests must read |
| Process introspection (`ps`/`pgrep`) | API / Backend (`runtime.py` native seam) | — | All subprocess spawning for diagnostics must route through `runtime.tracked_run`, the one locked seam `conftest.py` fakes/refuses |
| Doctor self-diagnosis | API / Backend (`doctor.py`) | — | Consumer of the process-introspection seam; must not hold its own `subprocess` call |
| Device integration proof | Database / Storage + OS (real EventKit, Mail, Contacts, TCC) | API / Backend (daemon under test) | Runs against the actual daemon bundle rebuilt from `develop`, not the repo checkout — "the repo is not the daemon" |
| Release/version identity | Build / CI (pyproject.toml + Info.plist + build_stamp) | API / Backend (`doctor.py:_version`/`_build_stamp`) | Two files must agree (`tests/test_packaging.py`); the daemon's own report is the only proof a rebuild actually took |

## Standard Stack

No new libraries. This phase is entirely test-infrastructure, CI configuration, and a release
process — stdlib (`subprocess`, `ast`, `unittest.mock`/pytest `monkeypatch`) plus the project's
existing `uv`/`ruff`/`pytest` toolchain, already pinned in `pyproject.toml`:

| Tool | Pinned version | Verified |
|------|-----------------|----------|
| pytest | `>=8,<10` | `pyproject.toml:52` [VERIFIED: pyproject.toml:52] |
| pytest-cov | `>=6,<8` | `pyproject.toml:53` [VERIFIED: pyproject.toml:52] |
| ruff | `>=0.15,<0.17` | `pyproject.toml:54` [VERIFIED: pyproject.toml:52] |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| One shared `_gate_off_only`-shaped skip marker for the 8 call tests | `pytest.mark.skipif(tiers.read_only(), reason=...)` per-test | CONTEXT.md D-01 explicitly locks "one named marker" — a per-test skipif duplicates the reason string 8 times and is what the marker exists to avoid |
| Ad hoc `subprocess.Popen.__init__` patch for the GATE-11 proof, living permanently in `tests/` | A throwaway proof script under `.worktrees/` (git-ignored), mirroring the `.daemon_probe.py` convention (STATE.md: "One-off daemon proofs live at .worktrees/.daemon_probe.py, reused across plans 01-10 and 01-14") | The plugin is a **measurement tool for this phase's proof**, not a permanent regression guard — the AST tripwire extension is the permanent guard. Recommend the `.worktrees/` scratch convention already established in this repo, reused before/after the fix, not committed to `tests/` |

**Installation:** none — no new dependency.

## Package Legitimacy Audit

**Not applicable.** This phase installs no external package. Every fix described below uses stdlib
(`subprocess`, `ast`) or the project's own existing modules (`registry`, `runtime`, `tiers`).

## Architecture Patterns

### System Architecture Diagram

```
 ┌─────────────────────────────────────────────────────────────────────┐
 │  import time (module load)                                          │
 │                                                                       │
 │   server.py: for each @_tool(...) call site                         │
 │     registry.add(ToolRecord(..., registered = gate_check()))  ──┐    │
 │     if registered: mcp.tool()(_guard(fn))   # wrapped, dispatched│   │
 │     else:          return fn                # RAW, no _guard   ─┘    │
 │                                                                       │
 │   registry.TOOLS[name] now holds the record EITHER WAY               │
 └─────────────────────────────────┬─────────────────────────────────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              │                     │                     │
   registry.write_tools()   registry.TOOLS.values()   FastMCP tool list
   (registered=True only)   (every record, always)    (registered=True only,
   → 4 fact tests must          → what the 4 fact        via mcp.list_tools())
     NOT use this in RO          tests must read           → only source the
                                                              8 call tests and
                                                              test_gate_on_dispatch
                                                              may use
              │                                                     │
              ▼                                                     ▼
   MACOS_APPS_READ_ONLY=1 uv run pytest (GATE-07)      test_gate_on_dispatch.py
   — every write tool's raw fn is called directly        subprocess (gate ON,
     by unit tests; ToolError only appears if the         ALLOW_SEND=mail) —
     tool WAS wrapped, i.e. only when registered=True      the only place the
                                                             registered-set claim
                                                             is proven true

 ┌─────────────────────────────────────────────────────────────────────┐
 │  doctor.diagnose() request path                                     │
 │                                                                       │
 │   _automation_surfaces()  →  _process_line()  →  app_process_info() │
 │        (per-app probe)                              → runtime.       │
 │                                                        tracked_run    │
 │                                                        (LOCKED, faked│
 │                                                         by conftest) │
 │                                                                       │
 │   _responsible_process()  →  _process_name(pid)  →  subprocess.run  │
 │   (called on EVERY diagnose(), request=True or False)  ← THE LEAK   │
 │                                                        (GATE-11 fix:  │
 │                                                         swap for      │
 │                                                         runtime.       │
 │                                                         tracked_run)  │
 └─────────────────────────────────────────────────────────────────────┘

 ┌─────────────────────────────────────────────────────────────────────┐
 │  Device sweep (GATE-12) — separate process entirely                 │
 │                                                                       │
 │   develop (worktree, detached) → build_app.sh --sign → dist/.app    │
 │        → ditto backup → rm+cp /Applications → codesign --verify     │
 │        → launchctl kickstart -k → unix socket answers               │
 │        → uv run pytest -m integration (this repo checkout's tests,  │
 │              run AGAINST the reinstalled daemon's real native state)│
 └─────────────────────────────────────────────────────────────────────┘
```

### Recommended Project Structure (files this phase touches — no new files, all existing)

```
macos_apps_mcp/
├── doctor.py            # _process_name: swap subprocess.run → runtime.tracked_run
tests/
├── test_doctor_deploy.py    # _gate_off_only marker (existing shape to copy)
├── test_server.py           # 8 call tests need the new read-only skip marker
├── test_tool_annotations.py # test_run_shortcut_carries_open_world_hint,
│                             # test_every_write_tool_is_audit_classified — read
│                             # registry.TOOLS directly instead of the live tool list
├── test_audit_middleware.py # test_server_snapshot_sources_are_derived...
├── test_mail_cleanup.py     # test_mail_duplicates_is_registered_read_only
├── test_native_seam.py      # extend AST tripwire: flag a direct subprocess.run/
│                             # Popen/call/check_call/check_output CALL in doctor.py
│                             # or adapters/*.py (not a bare exception-class reference)
├── test_integration.py      # scratch_mailbox / inbox_messages account agreement
├── integration/test_mail_outbound.py  # SELF_ADDRESS pattern, unchanged
.github/workflows/ci.yml     # + one step: MACOS_APPS_READ_ONLY=1 uv run pytest
pyproject.toml                # version bump (D-09, last plan only)
packaging/Info.plist           # CFBundleShortVersionString bump (D-09, last plan only)
```

### Pattern 1: Registry-record-first, registration-state-second

**What:** `registry.py` already establishes the pattern the D-01 fixes must extend: a "fact about
the tool" view iterates `TOOLS.values()` unconditionally; a "what's live right now" view filters
`r.registered`. `removes_content_tools()` is the existing template:

```python
# Source: macos_apps_mcp/registry.py:140-148 [VERIFIED: registry.py:140-148]
def removes_content_tools() -> frozenset[str]:
    """Every ALL-records (registered or not) tool that "removes or replaces
    content" (GATE-05, D-04) — the class the fail-closed dry-run-default test walks.
    Iterates every record, not just registered ones..."""
    return frozenset(
        n for n, r in TOOLS.items() if r.removes_content or n.startswith("delete_")
    )
```

**When to use:** Any test asserting "this tool IS a write / IS audit-classified / carries this
annotation" — a claim about the tool's declared nature, not about the current process's gate state.

**Fix shape for the two registry-filtered fact tests** (`test_every_write_tool_is_audit_classified`
in `tests/test_tool_annotations.py:101-129` and
`test_server_snapshot_sources_are_derived_and_satisfy_the_protocol` in
`tests/test_audit_middleware.py:163-181`): replace `registry.write_tools()` /
`registry.snapshot_sources()` with an all-records equivalent, e.g.
`{n for n, r in registry.TOOLS.items() if r.is_write}` and
`{n: r.snapshot for n, r in registry.TOOLS.items() if r.snapshot is not None}`. Precedent for this
exact move already exists in Phase 1: `01-13-SUMMARY.md` (line 51) records
`test_audit.py::test_audit_op_labels_send_tools_distinctly_from_write` being rewritten from
`registry.audit_verbs()` (registered-filtered) to `registry.TOOLS[name].audit_verb` (unfiltered),
for the identical reason [VERIFIED: .planning/phases/01-gate-land-the-spiked-architecture-cuts/01-13-SUMMARY.md:51 — "rewritten to read registry.TOOLS[name].audit_verb directly, since the test's INTENT is verb derivation, not registration gating"].

**Fix shape for `test_run_shortcut_carries_open_world_hint`** (`tests/test_tool_annotations.py:65-71`):
currently built on `_tools()`, a live `Client(srv.mcp).list_tools()` call — which under
`MACOS_APPS_READ_ONLY=1` never contains `run_shortcut` (a destructive-tier write, gated off) and
`KeyError`s at `by_name["run_shortcut"]`. Replace with
`registry.TOOLS["run_shortcut"].annotations["openWorldHint"] is True` — `ToolRecord.annotations`
(`registry.py:63-67`) already computes the same value the FastMCP registration used, from the same
record, unconditionally of `registered`.

**Fix shape for `test_mail_duplicates_is_registered_read_only`**
(`tests/test_mail_cleanup.py:489-494`): the negative half of its own assertion
(`assert "mail_duplicates" not in registry.write_tools()`) still holds under read-only (empty set
still excludes it), but the positive half (`assert "trash_mail" in registry.write_tools()`) fails
for the same reason as the others — swap to the unfiltered form.

### Pattern 2: One named skip marker for a call test that needs `_guard` to exist

**What:** D-01 requires the 8 `tests/test_server.py` call tests (which call `srv.create_reminder(...)`
etc. directly and assert `pytest.raises(ToolError, ...)`) to skip under read-only, because a
gated-off tool's dispatch function is handed back **undecorated**
(`server.py:180-182` [VERIFIED: server.py:180-182] — quoted verbatim:
```
        if not registered:
            return f
        return mcp.tool(annotations=rec.annotations)(_guard(f) if guard else f)
```
), so the raw `ValueError`/`NativeError` propagates instead of the `_guard`-wrapped `ToolError`.

**When to use:** Exactly these 8 named tests — `test_create_reminder_rejects_out_of_range_priority`,
`test_create_event_all_day_rejects_utc_offset`, `test_update_event_all_day_rejects_utc_offset`,
`test_create_reminder_recurrence_without_due_rejected`, `test_create_event_rejects_bad_rrule`,
`test_create_event_rejects_empty_start`, `test_write_tool_converts_native_error_to_agent_directive`,
`test_optional_datetime_parse_error_names_the_field` — all in `tests/test_server.py` (re-verified
live this session, see §GATE-07 Evidence).

**Marker to copy** (mirror `_gate_off_only`'s exact shape, per D-01):
```python
# Source: tests/test_doctor_deploy.py:25-29 [VERIFIED: test_doctor_deploy.py:25-29]
_gate_off_only = pytest.mark.skipif(
    bool(registry.outbound_status()["registered"]),
    reason="valid only in a gate-off process (see test_gate_on_dispatch.py)",
)
```
A parallel `_write_gate_on_only = pytest.mark.skipif(tiers.read_only(), reason="…")` (or equivalent
predicate reading `registry.TOOLS["create_reminder"].registered`) placed once near the top of
`tests/test_server.py`, applied to the 8 named tests. `tiers.read_only()` is the same predicate
`server.py`'s own `_tool` decorator calls to decide `registered` in the first place — using it keeps
the skip condition and the gate condition provably the same boolean.

### Pattern 3: The locked native seam — a qualified `runtime.<name>` call is the only permitted door

**What:** `runtime.tracked_run` (`runtime.py:222-251`) is the one function that registers a spawned
child in the `#56` cleanup set and is what `conftest.py`'s autouse `_no_real_osascript` fixture
locks (fakes to a refusal for any unit test that doesn't monkeypatch it itself). `doctor._process_name`
(`doctor.py:250-262`) is the last holdout calling `subprocess.run` directly:

```python
# Source: macos_apps_mcp/doctor.py:250-262 [VERIFIED: doctor.py:250-262]
def _process_name(pid: int) -> str:
    """Best-effort executable path for a pid (no TCC needed). ponytail: immediate parent
    only — walk the ancestor chain to the first *.app if the .app is ever ambiguous."""
    try:
        proc = subprocess.run(
            ["ps", "-o", "comm=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return f"pid {pid}"
    return proc.stdout.strip() or f"pid {pid}"
```

**Fix (one-line seam swap, `doctor.py` already imports `runtime` qualified at line 28):**
```python
def _process_name(pid: int) -> str:
    try:
        proc = runtime.tracked_run(["ps", "-o", "comm=", "-p", str(pid)], timeout=5.0)
    except (OSError, subprocess.SubprocessError):
        return f"pid {pid}"
    return proc.stdout.strip() or f"pid {pid}"
```
`tracked_run`'s signature (`timeout` keyword-only, returns
`subprocess.CompletedProcess[str]` with `text=True` always on) is a drop-in replacement — no
caller-visible shape change. `import subprocess` stays (still used for the `except` clause's
`subprocess.SubprocessError`) [VERIFIED: doctor.py:23 + only other use is line 260's except clause,
confirmed by grep — no other `subprocess.` reference in doctor.py].

**Why the existing fakes already cover it:** both `tests/test_doctor.py:21-35` and
`tests/test_doctor_deploy.py:9-19`'s `_no_live_process_probe` autouse fixtures already monkeypatch
`runtime.tracked_run` to `subprocess.CompletedProcess(cmd, 1, "", "")` (returncode 1, empty stdout)
— once `_process_name` routes through `tracked_run`, that fake makes `proc.stdout.strip()` empty,
so the function falls through to `f"pid {pid}"`, matching CONTEXT.md's discretion note exactly.

**AST-tripwire extension** (`tests/test_native_seam.py`): the existing
`test_native_module_does_not_import_the_seam_by_name` only catches a **by-name import**
(`from ..runtime import tracked_run`) — it does not catch a same-named-but-unrelated call like
`subprocess.run(...)`. A new test must walk each of `doctor.py` + `adapters/*.py` for an
`ast.Call` node whose `func` is `ast.Attribute(value=ast.Name(id="subprocess"), attr in
{"run", "Popen", "call", "check_call", "check_output"})`, and fail if found. **This must NOT flag
a bare name reference** — `shortcuts.py:52,172,181` legitimately catches
`except subprocess.TimeoutExpired as e:` [VERIFIED: grep `subprocess\.` macos_apps_mcp/adapters/*.py
macos_apps_mcp/doctor.py — shortcuts.py's three hits are all `subprocess.TimeoutExpired`, an
exception-class reference, not a spawn call], and a naive "any `subprocess.` attribute access"
check would false-positive there. Scope the AST walk to `ast.Call` nodes only.

### Anti-Patterns to Avoid

- **A test-side re-implementation of `_guard`:** CONTEXT.md D-01 states this explicitly — a test
  that wraps a plain function in its own try/except-to-ToolError proves the test's copy of the
  logic, not the server's. Every one of the 8 call tests must keep calling the real
  `srv.<tool_fn>` and rely on the real decorator having applied `_guard`.
- **Filtering `registry.TOOLS` by `registered` in a "what IS this tool" assertion:** this is
  precisely the bug in all 4 fact tests today — `write_tools()`, `snapshot_sources()`, and the live
  `Client(...).list_tools()` view are all `registered`-filtered by design (they answer "what's live
  in THIS process"), and none of them is the right source for a claim about the tool's declared
  nature.
- **A bare `subprocess.` string/attribute grep as the AST tripwire's detection rule:** would
  false-flag `shortcuts.py`'s legitimate `except subprocess.TimeoutExpired` references. Must be
  scoped to `ast.Call`.
- **Fixing `inbox_messages` to pick "any INBOX with 2+ messages" without matching `scratch_mailbox`'s
  account:** breaks the same-account move-test assumption D-04 names explicitly on a multi-account
  Mac; `overview()`'s `account_id` must be the join key between the two fixtures.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Counting live `ps`/`pgrep` spawns during a pytest run | A custom subprocess-tracing sitecustomize.py or an env-var wrapper script around `ps` | A `pytest -p` plugin patching `subprocess.Popen.__init__` (stdlib `unittest.mock`/monkeypatch, no new dependency) | This is exactly what pytest's plugin loading (`-p`) exists for; a wrapper script around the real `ps` binary risks masking a real spawn instead of just counting it |
| Skipping 8 tests under one condition | Repeating `@pytest.mark.skipif(<same predicate>, reason="<same string>")` 8 times | One named marker object (`_gate_off_only`'s shape), applied 8 times | D-01 requires this explicitly; a duplicated literal is also how the CONTEXT.md-cited "two regressions caught only by manual check" (01-13) class of bug recurs — one definition, one place to fix it |
| Version consistency between `pyproject.toml` and `Info.plist` | A new release-time check script | `tests/test_packaging.py::test_bundle_version_tracks_pyproject` — already exists, already enforced | GATE-13 in Phase 1 already ran this release checklist twice; nothing new needed here except running the existing test as `docs/RELEASING.md` step 1 prescribes |

**Key insight:** every "don't hand-roll" in this phase is really "don't hand-roll a **second**
mechanism next to one that already exists in this codebase" — the registry, the seam lock, and the
packaging test are all already-built machinery; the phase's job is closing the last gaps in each,
not adding a parallel system.

## Common Pitfalls

### Pitfall 1: Fixing the symptom test instead of the shared root cause

**What goes wrong:** Patching each of the 12 failing tests individually (e.g. wrapping each call
site in its own try/except) instead of recognizing the 8 call-test failures share one cause
(`server.py:181`'s undecorated-function return) and the 4 fact-test failures share a different one
(`registered`-filtered registry views).
**Why it happens:** The 12 failures look superficially unrelated (different files, different
assertion styles) until you trace each traceback to its origin.
**How to avoid:** Group by the actual raise site, not by test file — this research groups all 12 by
their true origin above.
**Warning signs:** A fix that touches 12 test files individually with 12 different patterns is a
sign the grouping was missed.

### Pitfall 2: `inbox_messages`/`scratch_mailbox` account mismatch on a multi-account Mac

**What goes wrong:** `scratch_mailbox` (`tests/test_integration.py:1493-1513`
[VERIFIED: test_integration.py:1493-1513]) deterministically excludes Gmail accounts when possible
(`gmail_accounts = {...}`, `account = next((a for a in account_ids if a not in gmail_accounts), account_ids[0])`);
`inbox_messages` (`tests/test_integration.py:1516-1527`
[VERIFIED: test_integration.py:1516-1527]) currently just takes `rows[0]` from
`m.overview()` filtered to `/INBOX` with `total > 0` — no Gmail exclusion, no coordination with
`scratch_mailbox`'s choice. If `overview()`'s natural (unread-first) order puts a Gmail INBOX first
while `scratch_mailbox` picks a different, non-Gmail account, the cross-account and same-account
move tests operate against two different accounts without either fixture or the test noticing.
**Why it happens:** The two fixtures were written independently, and today's `inbox_messages` body
(picking any 2 messages, not marker-subject messages) never needed to agree with
`scratch_mailbox`'s account choice — D-04 is what introduces the requirement.
**How to avoid:** D-04's rewritten `inbox_messages` should derive its account from the same
selection logic `scratch_mailbox` uses (ideally by requesting `scratch_mailbox`'s chosen account,
e.g. having `inbox_messages` depend on `scratch_mailbox` or share a helper), then search for the
marker subject scoped to that account's INBOX folder (`m.search(subject=MARKER, mailbox=folder,
limit=2)` — `search()`'s `subject=`/`mailbox=` kwargs confirmed at `mail.py:1663-1678`
[VERIFIED: mail.py:1663-1678]).
**Warning signs:** A device sweep run where the cross-account move test passes but silently never
touched the account `scratch_mailbox`'s mailbox actually lives under.

### Pitfall 3: Believing `_no_live_process_probe`'s existing fake already covers GATE-11

**What goes wrong:** Both doctor test files already fake `runtime.tracked_run` — it is tempting to
assume "the fake exists, so the live-`ps` problem must already be fixed." It is not: the fake covers
`app_process_info` (which already calls `tracked_run`), but `_process_name` — called by
`_responsible_process`, itself called on **every** `diagnose()` invocation whether or not
`request=True` — still calls raw `subprocess.run`, which the fake never touches (it only
monkeypatches `runtime.tracked_run`, not the stdlib `subprocess` module).
**Why it happens:** The fixture's docstring only names `app_process_info`, so a reader can miss
that a second, unrelated code path also spawns `ps`.
**How to avoid:** Confirmed by direct grep — `grep -n "subprocess\." macos_apps_mcp/doctor.py`
shows exactly two call sites (`doctor.py:254` and `260`), both inside `_process_name`; no other
`doctor.py` function calls `subprocess` directly.
**Warning signs:** The GATE-11 "proof" (Popen-spy count) still shows a nonzero count for
`test_doctor.py`/`test_doctor_deploy.py` tests after only fixing `app_process_info`-adjacent code —
that would mean `_process_name` was missed.

## Code Examples

### GATE-07 Evidence — the exact 12 failing tests, re-run live this session

```
$ cd /Users/andrei/Developer/macos-apps-mcp && MACOS_APPS_READ_ONLY=1 uv run pytest -q
1458 passed, 12 failed, 1 skipped

$ MACOS_APPS_READ_ONLY=1 uv run pytest -q --no-header -rf | grep '^FAILED'
FAILED tests/test_audit_middleware.py::test_server_snapshot_sources_are_derived_and_satisfy_the_protocol
FAILED tests/test_mail_cleanup.py::test_mail_duplicates_is_registered_read_only
FAILED tests/test_server.py::test_create_reminder_rejects_out_of_range_priority
FAILED tests/test_server.py::test_create_event_all_day_rejects_utc_offset
FAILED tests/test_server.py::test_update_event_all_day_rejects_utc_offset
FAILED tests/test_server.py::test_create_reminder_recurrence_without_due_rejected
FAILED tests/test_server.py::test_create_event_rejects_bad_rrule
FAILED tests/test_server.py::test_create_event_rejects_empty_start
FAILED tests/test_server.py::test_write_tool_converts_native_error_to_agent_directive
FAILED tests/test_server.py::test_optional_datetime_parse_error_names_the_field
FAILED tests/test_tool_annotations.py::test_run_shortcut_carries_open_world_hint
FAILED tests/test_tool_annotations.py::test_every_write_tool_is_audit_classified
```
[VERIFIED: live pytest run, main checkout, `develop`, this session — no source file edited before
the run]. **This is a byte-identical match to CONTEXT.md's D-01 list of 4 fact tests + 8 call
tests** — the phase context's measurement is confirmed current, not stale.

### GATE-11 Evidence — where the two remaining live-`ps` call sites are

```
$ grep -n "subprocess\." macos_apps_mcp/doctor.py
23:import subprocess
254:        proc = subprocess.run(
260:    except (OSError, subprocess.SubprocessError):
```
Both are inside `_process_name`, called twice per `diagnose()` by `_responsible_process()`
(`os.getpid()` and `os.getppid()`) — matching CONTEXT.md's "each spawns `ps -o comm=` twice" note
exactly.

```
$ grep -c "diagnose()" tests/test_doctor.py tests/test_doctor_deploy.py
tests/test_doctor.py:0          # calls doc.diagnose(request=...) — grep for the literal
tests/test_doctor_deploy.py:8   # confirms doctor tests exercise diagnose() repeatedly
```
[VERIFIED: live grep, this session]. CONTEXT.md's count (8 in test_doctor.py, 7 in
test_doctor_deploy.py) is a test-**count**, not a call-**count** — accepted as-is per D-05/D-01
framing ("the roadmap count is stale [for GATE-11's total]" already resolved as 15, not 17, per
CONTEXT.md domain section).

### GATE-12 Evidence — 80 integration tests, 7 files, confirmed live

```
$ uv run pytest -m integration --collect-only -q 2>&1 | grep -c "::"
80
$ find tests -name "test_*.py" | xargs grep -l "pytest.mark.integration"
tests/test_mail_search_integration.py
tests/test_doctor.py
tests/test_daemon_integration.py
tests/test_integration.py
tests/integration/test_mail_reads_integration.py
tests/integration/test_mail_outbound.py
tests/integration/test_music_integration.py
```
[VERIFIED: live pytest collection + grep, this session — matches CONTEXT.md's "80 integration
tests in 7 files" exactly].

### Dev-build rebuild/reinstall/kickstart — the proven sequence (run 3x already in Phase 1)

```bash
# Source: .planning/phases/01-gate-land-the-spiked-architecture-cuts/01-13-SUMMARY.md
# (most recent of three identical runs: 01-10, 01-13, 01-14)
git worktree add --detach .worktrees/devbuild-<slug> origin/develop
cd .worktrees/devbuild-<slug>
git status --porcelain                      # must be empty
git describe --always --dirty --exclude '*' # the sha to expect in build_stamp

scripts/build_app.sh \
  --sign "Developer ID Application: Andrei M. Lavrenov (VUMUR696L9)" \
  --out dist
# check: dist/macos-apps-mcp.app's build_stamp == "<sha> <utc-time>", no "-dirty"
# check: CFBundleShortVersionString, CFBundleIdentifier, TeamIdentifier
# check: codesign -dvv shows flags=0x10000(runtime)

ditto /Applications/macos-apps-mcp.app <scratchpad>/backup-<label>/macos-apps-mcp.app
diff -rq /Applications/macos-apps-mcp.app <backup>   # must be empty output

rm -rf /Applications/macos-apps-mcp.app
cp -R dist/macos-apps-mcp.app /Applications/
codesign --verify --strict /Applications/macos-apps-mcp.app   # before first launch
launchctl kickstart -k gui/$(id -u)/ren.lav.macos-apps-mcp
# probe the unix socket within ~1s; doctor().build must equal the built sha
```
[VERIFIED: .planning/phases/01-gate-land-the-spiked-architecture-cuts/01-13-SUMMARY.md:8-50 and
01-14-SUMMARY.md:60-118 — this exact sequence, with rollback via the ditto backup, has already
succeeded 3 times this milestone with zero probe failures recorded].

**Rollback (never yet needed, but documented):** restore the `ditto` backup over `/Applications/`,
re-`codesign --verify`, `launchctl kickstart -k` again, confirm `doctor().version`/`.build` show the
prior sha.

### Marker-mail seeding and selection shape

`MailAdapter().send(SELF_ADDRESS, subject=MARKER_SUBJECT, body="...", dry_run=False)` via the
daemon's `send_mail` tool under `MACOS_APPS_ALLOW_SEND=mail` — the same lifecycle
`tests/integration/test_mail_outbound.py:44-49` already exercises for its own `SELF_ADDRESS =
"andrei@lav.ren"` round trip [VERIFIED: integration/test_mail_outbound.py:22-49]. Run it **twice**
(2 marker mails) before the sweep, once, per D-04.

Selection (rewrite of `inbox_messages`) should read, scoped to `scratch_mailbox`'s chosen account's
INBOX folder:
```python
# shape only — exact subject text and helper wiring are the planner's call (CONTEXT.md discretion)
hits = m.search(subject=MARKER_SUBJECT, mailbox=folder, limit=2)["results"]
if len(hits) < 2:
    pytest.fail(f"fewer than 2 marker mails in {folder} — run: <seed command>")
```
`search(subject=..., mailbox=...)` kwargs confirmed at `mail.py:1663-1678`
[VERIFIED: mail.py:1663-1678].

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The GATE-11 Popen-spy plugin should live under `.worktrees/` (scratch, git-ignored) rather than `tests/`, mirroring the `.daemon_probe.py` convention | Standard Stack / Alternatives Considered | Low — this is a tooling-placement recommendation, not a correctness claim; the planner may reasonably choose `tests/` instead without breaking anything, since CONTEXT.md explicitly leaves this "the planner's call" |
| A2 | The exact marker-mail subject text and seed-command wiring (e.g. a `dedupe-mail`-CLI-style one-off script vs. an ad hoc `python -c` invocation) | Code Examples / Marker-mail seeding | Low-Medium — CONTEXT.md explicitly defers this to the planner; getting the account-matching join right (Pitfall 2) matters more than the exact subject string |
| A3 | `inbox_messages` should be rewritten to *depend on* `scratch_mailbox` (fixture composition) rather than duplicate its account-selection logic inline | Common Pitfalls / Pitfall 2 | Low — either shape satisfies D-04's "agree on the same account" requirement; fixture composition is a style preference, not observed in this codebase's existing fixtures, so flagged as unverified against project convention |

## Open Questions

1. **Should GATE-07's shared skip-marker predicate be `tiers.read_only()` directly, or a fresh read
   of `registry.TOOLS["create_reminder"].registered`?**
   - What we know: both are true/false-identical at any point in time — `server.py:180`'s gate
     check for the destructive tier is literally `not tiers.read_only()`.
   - What's unclear: whether the marker should reference `tiers` (the pure gate predicate module)
     or `registry` (the derived-fact module) — a style choice with no behavioral difference.
   - Recommendation: use `tiers.read_only()` — it's the more direct predicate and avoids a
     dependency on any one tool's record existing.

2. **Does the Popen-spy plugin need to run as part of the phase's committed CI, or only as a
   one-time manual proof for `02-VERIFICATION.md`?**
   - What we know: CONTEXT.md frames it as "one run of the unit suite" for the proof, not a
     permanent gate — the AST tripwire is the permanent regression guard.
   - What's unclear: whether the planner wants it reusable for a *future* regression check, which
     would argue for `tests/` placement despite the ponytail-lazy recommendation above.
   - Recommendation: one-time proof only, `.worktrees/` scratch placement (Standard Stack
     Alternatives) — the AST tripwire extension is what prevents regression going forward.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `uv` | every test/lint command | ✓ | (repo-pinned via `astral-sh/setup-uv@v7` in CI; locally already in use per this session's `uv run` calls) | — |
| `ruff` | verification gate | ✓ (via `uv run`) | `>=0.15,<0.17` per `pyproject.toml:54` | — |
| `pytest` | all three gates | ✓ (via `uv run`) | `>=8,<10` per `pyproject.toml:52` | — |
| `launchctl` | device sweep, GATE-12 | ✓ (macOS built-in) | n/a | — |
| `codesign` / `xcrun notarytool` | D-09 release cut | ✓ per memory (notary keychain profile "notary" already set up, Team Key / Developer role) | n/a | — |
| macOS Mail.app + IMAP account(s) | device sweep marker mails, `scratch_mailbox` | ✓ (multi-account Mac; `andrei@lav.ren` is the send target) | macOS 27.0 (build 26A428) per CONTEXT.md | — |
| `ren.lav.mail-watchdog` launchd agent | D-03 precondition before any Mail test | Must be reconfirmed live at sweep time (`launchctl list \| grep ren.lav.mail-watchdog`) — not probed in this research session (Claude does not touch Mail during research per the task's explicit prohibition) | — | If not loaded: start it before any Mail test, per memory "Run the Mail watchdog while developing Mail" |

**Missing dependencies with no fallback:** none identified — every tool this phase needs is
already present and already used successfully by Phase 1's identical rebuild/reinstall/sweep
pattern.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest `>=8,<10` [VERIFIED: pyproject.toml:52] |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (`pyproject.toml:77-80`) |
| Quick run command | `MACOS_APPS_READ_ONLY=1 uv run pytest -q` (~seconds; measured this session against 1458+12+1 tests) |
| Full suite command | `uv run pytest` (unit, default `-m 'not integration'`); `uv run pytest -m integration` (device, 80 tests) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| GATE-07 | Read-only deployment: gated-off tools absent, not erroring | unit | `MACOS_APPS_READ_ONLY=1 uv run pytest -q` (all 12 named tests above) | ✅ (all 12 tests already exist; fixes edit assertions/skip markers, not new test files) |
| GATE-07 | Read-only mode stays green in CI, regression caught automatically | CI | `.github/workflows/ci.yml` new step (D-02) | ✅ Wave 0 — add one `- run:` line after `ci.yml:30` |
| GATE-11 | No live `pgrep`/`ps` spawned by the unit suite | unit (proof) | one-off Popen-spy plugin run: `uv run pytest -p <plugin> -q` | ❌ Wave 0 — plugin does not exist yet (recommend `.worktrees/` scratch, not committed) |
| GATE-11 | Regression guard: a new direct `subprocess` call in `doctor.py`/`adapters/*.py` fails the suite | unit | `uv run pytest tests/test_native_seam.py -x` | ❌ Wave 0 — new test function to add to the existing file |
| GATE-12 | Full device integration suite green | integration (manual, on-device only) | `uv run pytest -m integration` | ✅ (80 tests exist; some may need `xfail(strict=True, reason="#<issue>")` per D-07/D-08 findings during the sweep) |
| GATE-12 | Lint/format clean at gate close | CI + manual | `uv run ruff check .` / `uv run ruff format --check .` | ✅ already in CI |

### Sampling Rate

- **Per task commit:** `MACOS_APPS_READ_ONLY=1 uv run pytest -q` for GATE-07/GATE-11 plans; the
  Popen-spy proof run once per fix, not per commit.
- **Per wave merge:** full `uv run pytest` (both gated and ungated per `docs/RELEASING.md`
  checklist item 2).
- **Phase gate:** `uv run pytest -m integration` green on-device (0 failed, 0 errors, D-06), plus
  `ruff check`/`ruff format --check`, before `/gsd-verify-work`; then the D-09 release checklist.

### Wave 0 Gaps

- [ ] A Popen-spy pytest plugin (GATE-11 proof) — recommend `.worktrees/` scratch, git-ignored,
      mirroring `.daemon_probe.py`; not a permanent test file.
- [ ] A new test in `tests/test_native_seam.py` asserting no `ast.Call` to
      `subprocess.{run,Popen,call,check_call,check_output}` exists in `doctor.py` or
      `adapters/*.py` (GATE-11 regression guard).
- [ ] `inbox_messages` fixture rewrite in `tests/test_integration.py` — marker-subject selection,
      account-matched to `scratch_mailbox`, fail-loud with the seed command named (D-04).
- [ ] A one-time seed step (script or plan task) that sends the 2 marker mails before the first
      sweep run.

## Security Domain

This phase adds no new attack surface, no new tool, and no new external input path — it is test
infrastructure, CI, and a release cut. ASVS categories are assessed for completeness, not because
new risk is expected.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | No new auth surface — TCC/EventKit auth is unchanged by this phase |
| V3 Session Management | No | N/A |
| V4 Access Control | Yes (indirectly) | The whole point of GATE-07 is proving the capability-tier gate (`MACOS_APPS_READ_ONLY`) actually removes write/send tools rather than leaving them registered-and-erroring — this IS an access-control fail-closed guarantee, already the project's core architecture (`registry.ToolRecord.registered`) |
| V5 Input Validation | No new surface | The 8 call tests under GATE-07 exercise EXISTING input validation (`contracts.py` parse functions) — no new validation code is added, only the error-channel (`ToolError` vs raw exception) is fixed |
| V6 Cryptography | Yes (release only) | Code signing (`codesign`) and notarization (`xcrun notarytool`) for D-09 — standard Apple toolchain, never hand-rolled; keychain profile "notary" already configured per memory |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| A gated-off tool silently stays reachable (registered-and-erroring instead of absent) | Elevation of Privilege | Already the architecture's stated defense (`registry.py`'s docstring: "a record that says `registered=False` must never actually be reachable through FastMCP") — GATE-07's fix makes the *test suite* prove this, it does not change the mechanism |
| A live `ps`/`pgrep` spawn during CI leaks process-table information or behaves nondeterministically on a shared runner | Information Disclosure / Repudiation (nondeterministic CI) | GATE-11's seam lock — all process introspection routes through one function (`tracked_run`) that tests fake deterministically |
| A rebuilt `.app` shipped without re-verifying its code signature before first launch | Tampering | `codesign --verify --strict` is already in the proven rebuild sequence (Code Examples above), run before every `launchctl kickstart` |
| A release tag pushed before the owner approves | Repudiation | D-09 explicitly requires owner approval before `main`/tag push — a human gate, not a technical control, already stated in the locked decision |

## Sources

### Primary (HIGH confidence — read this session, this repo, this checkout)

- `macos_apps_mcp/server.py:1-230` — `_tool` decorator, gate-check, `_guard` wrapping
- `macos_apps_mcp/registry.py` (full file) — `ToolRecord`, `write_tools()`, `snapshot_sources()`,
  `removes_content_tools()`, `outbound_status()`
- `macos_apps_mcp/doctor.py` (full file) — `_process_name`, `_responsible_process`, `diagnose()`
- `macos_apps_mcp/runtime.py:95-251` — `app_process_info`, `tracked_run`
- `tests/test_doctor_deploy.py:1-60` — `_gate_off_only`, `_no_live_process_probe`
- `tests/test_doctor.py:1-40` — `_no_live_process_probe`
- `tests/test_tool_annotations.py` (full file) — the two fact tests, `_WRITE_TOOLS`/`_PERMISSION`
  views
- `tests/test_audit_middleware.py:150-181` — snapshot-sources fact test
- `tests/test_mail_cleanup.py:470-510` — duplicates-registered fact test
- `tests/test_server.py:400-560, 790-845` — the 8 call tests
- `tests/test_gate_on_dispatch.py` (full file) — the subprocess-based gate-ON absence proof
- `tests/test_native_seam.py` (full file) — existing AST tripwire, seam lock self-tests
- `tests/conftest.py:190-220` — `_no_real_osascript` autouse lock
- `tests/test_integration.py:1470-1560` — `scratch_mailbox`, `inbox_messages`
- `tests/integration/test_mail_outbound.py:1-80` — `SELF_ADDRESS`, real-send skipif
- `macos_apps_mcp/adapters/mail.py:918-930, 1663-1678` — `send()`, `search()` signatures
- `.github/workflows/ci.yml` (full file) — current single pytest step
- `pyproject.toml` (full file) — version, pytest/ruff config
- `packaging/Info.plist`, `tests/test_packaging.py` — version-match enforcement
- `docs/RELEASING.md`, `docs/DAEMON.md` (full files) — release + deploy procedure
- `docs/mail-applescript-facts.md:1-60` — device-verified Mail facts, D-08 record location
- Live shell commands this session: `MACOS_APPS_READ_ONLY=1 uv run pytest -q` (12 failures
  confirmed), `uv run pytest -m integration --collect-only -q` (80 tests confirmed), `git log
  v0.11.0..develop` (61 commits / multiple `feat` commits confirmed, D-09 version bump rationale)

### Secondary (MEDIUM confidence — prior-phase artifacts, same repo)

- `.planning/phases/01-gate-land-the-spiked-architecture-cuts/01-13-SUMMARY.md` — the exact
  rewrite precedent for a `registered`-filtered → unfiltered registry read, and the byte-identical
  12-failure baseline diff
- `.planning/phases/01-gate-land-the-spiked-architecture-cuts/01-14-SUMMARY.md`,
  `01-10-SUMMARY.md` — the proven dev-build rebuild/reinstall/kickstart sequence, run twice already
- `.planning/phases/01-gate-land-the-spiked-architecture-cuts/01-08-SUMMARY.md:140-175` — the
  watchdog precondition commands (D-03)
- `.planning/STATE.md` — the `.daemon_probe.py` scratch-tooling convention

### Tertiary (LOW confidence)

- None used — every claim in this document traces to a file read or a live command this session,
  or to a prior-phase artifact in this same repo.

## Metadata

**Confidence breakdown:**
- GATE-07 root cause and fix shape: HIGH — reproduced live, traced to exact line numbers, confirmed
  against Phase 1 prior art
- GATE-11 root cause and fix shape: HIGH — reproduced via grep, confirmed the fix is a drop-in seam
  swap already covered by existing fakes
- GATE-12 process (rebuild/reinstall/sweep): HIGH — this exact sequence has succeeded 3 times this
  milestone with documented output
- GATE-12 marker-mail account-matching design: MEDIUM — the gap is confirmed by reading both
  fixtures, but the exact fix implementation (subject text, seed command, fixture composition
  style) is explicitly left to the planner by CONTEXT.md
- Popen-spy plugin placement recommendation: MEDIUM — a style/convention recommendation, not a
  correctness claim

**Research date:** 2026-09-28
**Valid until:** This research is tied to `develop` at the commit measured this session
(`c75fa76`-era, no source edits made). Any code change on `develop` before planning begins
(especially to `server.py`, `registry.py`, `doctor.py`, or the named test files) invalidates the
line-number citations and should trigger a re-check of the exact 12-failure list before the plan
locks task details.
