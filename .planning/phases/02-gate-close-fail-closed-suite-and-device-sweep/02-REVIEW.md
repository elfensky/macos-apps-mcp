---
phase: 02-gate-close-fail-closed-suite-and-device-sweep
reviewed: 2026-10-01T05:48:56Z
depth: standard
files_reviewed: 11
files_reviewed_list:
  - .github/workflows/ci.yml
  - macos_apps_mcp/doctor.py
  - pyproject.toml
  - tests/integration/test_mail_outbound.py
  - tests/test_audit_middleware.py
  - tests/test_doctor.py
  - tests/test_integration.py
  - tests/test_mail_cleanup.py
  - tests/test_native_seam.py
  - tests/test_server.py
  - tests/test_tool_annotations.py
findings:
  critical: 0
  warning: 5
  info: 4
  total: 9
status: issues_found
---

# Phase 2: Code Review Report

**Reviewed:** 2026-10-01T05:48:56Z
**Depth:** standard
**Files Reviewed:** 11
**Status:** issues_found

## Summary

Scope: the Phase 2 diff `e3713ae..origin/develop` across 11 files — GATE-07 (read-only
suite gating), GATE-11 (`doctor._process_name` through `runtime.tracked_run` plus the AST
spawn tripwire), GATE-12 (marker-mail fixtures, strict/non-strict xfails, stale-assertion
fixes), the CI second run, and the 0.12.0 version bump.

Verified in place: `uv run ruff check .` clean, `uv run ruff format --check .` clean,
`uv run pytest -q` 1492 passed, `MACOS_APPS_READ_ONLY=1 uv run pytest -q` 1483 passed /
9 skipped. `packaging/Info.plist` carries 0.12.0, matching `pyproject.toml`. The
`_write_gate_on_only` comment's claim about `server.py`'s `_tool` returning the plain
function when gated off is true (`server.py:181-183`). The marker-account selection in
`test_integration.py` is sound against the search plane: `mail_index` dedupes per
Message-ID and ranks INBOX copies first (`mailbox_url.rank_case`, rank 0), so an
unscoped marker search does report the INBOX folder, and the mailbox-scoped search ranks
inside the filtered set, so `inbox_messages` sees the INBOX copy.

No Critical finding. The warnings are about guards and tests that are weaker than their
own docstrings claim: a tie-break that is not deterministic, a tripwire a one-token alias
evades, a positive code path that went from live-exercised to never-exercised, a live MCP
annotation that lost its only check, and a strict xfail whose reason is a device-state
condition.

## Warnings

### WR-01: `_pick_account` tie-break is not deterministic under hash randomization

**File:** `tests/test_integration.py:1536-1547`
**Issue:** The helper's docstring promises a deterministic choice, and the whole helper
exists to end the day-to-day account flip the old `overview()`-order pick caused. The
tie-break is:

```python
return max(set(candidates), key=candidates.count) if candidates else fallback
```

`max` over a `set[str]` with equal keys returns the first element in set iteration
order, and string hashing is randomized per interpreter process. With one marker in each
of two non-Gmail INBOXes (the state a half-finished seed, or a partially restored run,
leaves behind), the picked account changes from run to run. `inbox_messages` then
fails loud on whichever account lost the coin flip, so nothing is destroyed, but the
failure message names a different account on each run and the "deterministic" promise is
false.
**Fix:**
```python
return (
    max(sorted(set(candidates)), key=candidates.count) if candidates else fallback
)
```
Ties then resolve to the lowest account id, in line with the sorted fallback.

### WR-02: The spawn tripwire is evaded by a module alias and misses other spawn routes

**File:** `tests/test_native_seam.py:52-75`
**Issue:** The tripwire is documented as "the only door to a subprocess is
`runtime.tracked_run` (GATE-11)", but it only matches `ast.Call` nodes whose receiver is
the literal name `subprocess`, plus `from subprocess import <spawner>`. All of these
pass it unflagged in a native module:

- `import subprocess as sp; sp.run([...])` — the receiver id is `sp`.
- `subprocess.getoutput(...)` / `subprocess.getstatusoutput(...)` — not in `_SPAWNERS`.
- `os.system(...)`, `os.popen(...)`, `os.posix_spawn(...)`, `os.exec*` — different module.
- `asyncio.create_subprocess_exec(...)`.
- `run = subprocess.run; run([...])` — the spawn is a bare `ast.Name` call.

No current module uses any of these (grep over `macos_apps_mcp/` is empty), so this is a
guard-completeness defect, not a live violation. The alias case is the one that matters:
it is the first thing a future edit reaches for when the direct form fails the tripwire.
**Fix:** Resolve aliases from the module's own `import` statements and extend the name
sets; keep the `ast.Call`-only scope so `except subprocess.TimeoutExpired` stays legal.
```python
_SPAWNERS = frozenset(
    {"run", "Popen", "call", "check_call", "check_output", "getoutput", "getstatusoutput"}
)
_OS_SPAWNERS = frozenset({"system", "popen", "posix_spawn", "posix_spawnp"})

def _module_aliases(tree: ast.AST, module: str) -> set[str]:
    return {
        a.asname or a.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for a in node.names
        if a.name == module
    }

# in the test:
subprocess_names = _module_aliases(tree, "subprocess")
os_names = _module_aliases(tree, "os")
...
    and (
        (node.func.value.id in subprocess_names and node.func.attr in _SPAWNERS)
        or (node.func.value.id in os_names
            and (node.func.attr in _OS_SPAWNERS or node.func.attr.startswith(("exec", "spawn"))))
    )
```
Add a negative self-test (a tiny source string with `import subprocess as sp; sp.run(...)`)
so the tripwire's own coverage is pinned, the same way `test_the_tripwire_sees_the_native_modules`
pins the glob.

### WR-03: `_process_name`'s positive path is no longer exercised by any test

**File:** `macos_apps_mcp/doctor.py:250-257`; `tests/test_doctor.py:22-35`
**Issue:** Before GATE-11 the function ran a real `ps` in 15 tests, so
`proc.stdout.strip()` returning the executable path was exercised live (that was the leak
being closed). After the swap, the autouse `_no_live_process_probe` fakes every
`tracked_run` call to `CompletedProcess(cmd, 1, "", "")`, so the only branch any unit
test reaches is the `or f"pid {pid}"` fallback. The 02-02 summary records "no test
needed a behavior change"; the behavior went from live-tested to untested. A regression
such as reading `proc.stderr`, dropping `.strip()`, or passing the wrong `ps` flags would
not fail the suite — `test_diagnose_shape` only asserts `"launched by" in ...`, which the
fallback also satisfies.
**Fix:** One test with a per-command fake, plus the timeout branch:
```python
def test_process_name_reads_ps_comm_through_the_seam(monkeypatch):
    seen = []

    def fake(cmd, **kw):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "/sbin/launchd\n", "")

    monkeypatch.setattr(runtime, "tracked_run", fake)
    assert doc._process_name(1) == "/sbin/launchd"
    assert seen == [["ps", "-o", "comm=", "-p", "1"]]


def test_process_name_falls_back_on_timeout(monkeypatch):
    def slow(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])

    monkeypatch.setattr(runtime, "tracked_run", slow)
    assert doc._process_name(42) == "pid 42"
```

### WR-04: The live `openWorldHint` on `run_shortcut` lost its only check

**File:** `tests/test_tool_annotations.py:65-73`, `tests/test_tool_annotations.py:48-62`
**Issue:** `test_run_shortcut_carries_open_world_hint` used to read the live FastMCP tool
list; it now asserts `registry.TOOLS["run_shortcut"].annotations["openWorldHint"]`, which
is the `ToolRecord.annotations` property computing from `open_world=True` — the record's
own input, not what FastMCP serves. The live loop
`test_every_tool_is_annotated_from_the_read_write_seam` checks `readOnlyHint` and
`destructiveHint` only. `test_send_annotations_are_destructive_and_open_world`
(`tests/test_server.py:671-676`) checks the `srv._SEND_ANNOTATIONS` constant, not a
registered tool. So in every mode, nothing now proves that
`mcp.tool(annotations=rec.annotations)` (`server.py:183`) hands `openWorldHint` to the
client for a non-send tool — the C6c guarantee the test's own comment describes. The
GATE-07 goal (run, not skip, in read-only mode) is met at the cost of the live assertion
in default mode.
**Fix:** Keep the record assertion, and add the live comparison to the loop that already
runs in every mode over whatever is registered:
```python
def test_every_tool_is_annotated_from_the_read_write_seam():
    for t in _tools():
        a = t.annotations
        ...
        want_open = registry.TOOLS[t.name].annotations.get("openWorldHint", False)
        assert bool(a.openWorldHint) is want_open, (
            f"{t.name} openWorldHint={a.openWorldHint}, want {want_open}"
        )
```
In default mode this covers `run_shortcut`; under `MACOS_APPS_ALLOW_SEND=mail` it covers
the three send tools as well.

### WR-05: `#229` strict xfail is conditioned on a device state, not a code fact

**File:** `tests/integration/test_mail_outbound.py:96-100`
**Issue:** The reason text reads "rollback() cannot verify delete of a windowless
outgoing message **when Mail is in the §3c zombie-delete state**". A reason that names a
Mail state is a reason that can be absent on a given run, and `strict=True` turns that
pass into an XPASS failure of the D-06 gate. This is the exact sequence `#230` went
through in this phase (strict → XPASS → owner decision → `strict=False`, 02-05
summary). The one diagnostic re-run at triage time is thin evidence against a state
that `docs/mail-applescript-facts.md` §3c describes as something Mail enters, not
something it is.
**Fix:** Either mark it `strict=False` with the same "also passes" wording as `#230`, or
keep `strict=True` and reword the reason to the code-level fact the test proves (the
rollback handler reads back a windowless `outgoing message` and gets no `-1728`) once
Phase 02.1 confirms it reproduces on every run. Do not leave a state-conditional
sentence under a strict mark.

## Info

### IN-01: `registry.write_tools()` has no consumer left; `snapshot_sources()`'s filter is unpinned

**File:** `macos_apps_mcp/registry.py:105-118`; `tests/test_audit_middleware.py:183-190`; `tests/test_mail_cleanup.py:490-498`; `tests/test_tool_annotations.py:135-139`
**Issue:** This phase moved the last three test consumers of `registry.write_tools()` to
an inline `{n for n, r in registry.TOOLS.items() if r.is_write}`. Production never called
it (grep: only `registry.py` defines it; the only other hit is an unrelated test function
name). It is now dead code. The same move left `registry.snapshot_sources()`'s
`registered` filter with one consumer (`server.py:1312`, AuditMiddleware wiring) and no
test — the old `assert set(snapshot_sources) <= registry.write_tools()` was the only
check on that view. The 02-01 summary itself flags the triplicated comprehension.
**Fix:** Delete `write_tools()`, or replace the three inline comprehensions with one
`registry.all_write_tools()` next to `removes_content_tools()` (which already uses the
all-records convention). Pin `snapshot_sources()` with one line in
`test_server_snapshot_sources_are_derived_and_satisfy_the_protocol`:
`assert set(registry.snapshot_sources()) == {n for n in expected if registry.TOOLS[n].registered}`.

### IN-02: CI never runs the `MACOS_APPS_ALLOW_SEND=mail` mode

**File:** `.github/workflows/ci.yml:32-33`; `tests/test_tool_annotations.py:190-202`
**Issue:** The phase added the read-only run because "read-only debt has grown unseen
before". The send-gated mode has the same shape of debt: the ON branch of
`test_send_tools_registered_only_when_gate_is_on` (whose comment says this is "exactly
the scenario `MACOS_APPS_ALLOW_SEND=mail uv run pytest` must exercise and pass") and the
counterparts of the `_gate_off_only` skips only run when someone remembers the RELEASING
checklist. `test_gate_on_dispatch.py` pins registration in a subprocess, but not the rest
of the suite under that gate. The gate acts at registration only, so the run makes no
native call.
**Fix:** `- run: MACOS_APPS_ALLOW_SEND=mail uv run pytest` as a third step, or state in
the header comment that send-mode is a manual RELEASING step on purpose.

### IN-03: The owner address is a literal in two integration files

**File:** `tests/test_integration.py:1522-1527`; `tests/integration/test_mail_outbound.py:22`
**Issue:** `SEED_MARKERS` embeds `andrei@lav.ren`; `test_mail_outbound.py` already names
it as `SELF_ADDRESS`. Two literals to keep in sync, and D-05 ("never change it to a
third party") is asserted in a comment only.
**Fix:** `from tests.integration.test_mail_outbound import SELF_ADDRESS` and build
`SEED_MARKERS` with an f-string, or hoist `SELF_ADDRESS` to `tests/integration/__init__.py`.

### IN-04: `inbox_messages` calls `overview()` twice; summary names a different signature

**File:** `tests/test_integration.py:1551-1577`, `1595-1618`
**Issue:** `_scratch_account(m)` calls `m.overview()`, then `inbox_messages` calls it
again to find the INBOX row. `overview()` is a sqlite read plus a cached account-name
lookup, so the cost is small, but it is the same rows twice. The 02-03 summary documents
the helper as `_scratch_account(rows)`; the code is `_scratch_account(m)`.
**Fix:** Have `_scratch_account` return `(account, rows)` and reuse `rows` in both
fixtures, or leave the code and correct the summary.

---

_Reviewed: 2026-10-01T05:48:56Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
