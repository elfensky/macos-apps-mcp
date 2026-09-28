# Phase 2: Gate Close — Pattern Map

**Mapped:** 2026-09-28
**Files analyzed:** 10 (all existing — this phase creates no new files)
**Analogs found:** 10 / 10 (every file IS its own analog — this phase edits existing
functions/tests in place, following an adjacent function/test already in the same
file or its sibling test file)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|--------------------|------|-----------|-----------------|---------------|
| `macos_apps_mcp/doctor.py` (`_process_name`) | utility (native seam consumer) | request-response | `macos_apps_mcp/runtime.py` (`app_process_info`) | exact — same seam, same call shape |
| `tests/test_native_seam.py` (extend AST walk) | test (static-analysis tripwire) | transform | same file, `test_native_module_does_not_import_the_seam_by_name` | exact — same file, same AST-walk idiom |
| `tests/test_tool_annotations.py` (2 fact tests) | test | request-response (registry read) | `macos_apps_mcp/registry.py` (`removes_content_tools`) | exact — the unfiltered-iteration template these 2 tests must copy |
| `tests/test_audit_middleware.py` (1 fact test) | test | request-response (registry read) | `macos_apps_mcp/registry.py` (`removes_content_tools`) | exact — same fix shape |
| `tests/test_mail_cleanup.py` (1 fact test) | test | request-response (registry read) | `macos_apps_mcp/registry.py` (`removes_content_tools`) | exact — same fix shape |
| `tests/test_server.py` (8 call tests, add skip marker) | test | request-response | `tests/test_doctor_deploy.py` (`_gate_off_only`) | exact — same marker shape, same file already imports `tiers` |
| `.github/workflows/ci.yml` (+1 step) | config (CI pipeline) | batch | same file, existing `- run: uv run pytest` step | exact — sibling step, same job |
| `tests/test_integration.py` (`inbox_messages` fixture) | test (fixture) | CRUD (mail search) | same file, `scratch_mailbox` fixture | exact — account-selection logic to reuse |
| `pyproject.toml` (version bump) | config | transform | `packaging/Info.plist` (version bump) | exact — the two-file pair `test_packaging.py` enforces |
| `packaging/Info.plist` (version bump) | config | transform | `pyproject.toml` (version bump) | exact — the two-file pair `test_packaging.py` enforces |

## Pattern Assignments

### `macos_apps_mcp/doctor.py` (`_process_name`, utility, request-response)

**Analog:** `macos_apps_mcp/runtime.py` — `app_process_info` (lines 103–114), the only
other function that shells out to `ps`/`pgrep`, already routed through the locked seam.

**Current code to replace** (`macos_apps_mcp/doctor.py:250-261`):
```python
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

**Analog pattern — the qualified seam call** (`macos_apps_mcp/runtime.py:103-114`):
```python
def app_process_info(app: str) -> dict | None:
    """pid/state/%cpu/etime of the running app named ``app``, via one ``pgrep`` + one
    ``ps`` (no TCC needed). ``None`` when it isn't running or ps is unreadable."""
    try:
        pid = int(tracked_run(["pgrep", "-x", app], timeout=5.0).stdout.split()[0])
        state, cpu, etime = tracked_run(
            ["ps", "-o", "state=,%cpu=,etime=", "-p", str(pid)], timeout=5.0
        ).stdout.split()
        return {"pid": pid, "state": state, "cpu": float(cpu), "etime": etime}
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None
```

**Fix shape** — `doctor.py` already imports `runtime` qualified at line 28
(`from . import runtime` or equivalent — grep confirms `runtime.` is already used
elsewhere in the file):
```python
def _process_name(pid: int) -> str:
    try:
        proc = runtime.tracked_run(["ps", "-o", "comm=", "-p", str(pid)], timeout=5.0)
    except (OSError, subprocess.SubprocessError):
        return f"pid {pid}"
    return proc.stdout.strip() or f"pid {pid}"
```
`runtime.tracked_run`'s signature (`macos_apps_mcp/runtime.py:222-251`, `timeout` is
keyword-only, returns `subprocess.CompletedProcess[str]` with `text=True` always on)
is a drop-in replacement — `capture_output=True, text=True` collapse into the seam's
own `Popen(stdout=PIPE, stderr=PIPE, text=True)`. Keep `import subprocess` — the
`except` clause still references `subprocess.SubprocessError`.

**Why no new fake is needed:** `tests/test_doctor.py:21-35` and
`tests/test_doctor_deploy.py:9-19`'s `_no_live_process_probe` autouse fixtures already
monkeypatch `runtime.tracked_run` to `subprocess.CompletedProcess(cmd, 1, "", "")`
(see excerpt below) — once `_process_name` calls `runtime.tracked_run`, the existing
fake makes `proc.stdout.strip()` empty and the function falls through to
`f"pid {pid}"`.

---

### `tests/test_native_seam.py` (regression guard, test, transform)

**Analog:** same file, `test_native_module_does_not_import_the_seam_by_name`
(lines 32-41) — the existing AST-walk idiom over `_NATIVE_MODULES`.

**Existing pattern to extend** (`tests/test_native_seam.py:22-41`):
```python
_SEAM = frozenset({"run_osascript", "body_file", "tracked_run"})
_ADAPTERS_DIR = pathlib.Path(__file__).parent.parent / "macos_apps_mcp" / "adapters"
_NATIVE_MODULES = sorted(
    [p for p in _ADAPTERS_DIR.glob("*.py") if p.name != "__init__.py"]
    + [_ADAPTERS_DIR.parent / "doctor.py"]
)


@pytest.mark.parametrize("path", _NATIVE_MODULES, ids=lambda p: p.name)
def test_native_module_does_not_import_the_seam_by_name(path):
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("runtime"):
            offenders = _SEAM.intersection(a.name for a in node.names)
            assert not offenders, (...)
```
`_NATIVE_MODULES` already includes `doctor.py` — no new glob needed, only a new
parametrized test function walking the same list.

**New test to add** — same `ast.walk` shape, new node type
(`ast.Call` with `func = ast.Attribute(value=ast.Name(id="subprocess"), attr in
{"run", "Popen", "call", "check_call", "check_output"})`). Must NOT flag a bare
`ast.Attribute` reference outside a `Call` — `macos_apps_mcp/adapters/shortcuts.py`
has 3 legitimate `except subprocess.TimeoutExpired as e:` references (an exception
class, not a spawn) that a naive "any `subprocess.` attribute" rule would false-flag.
Scope the walk to `isinstance(node, ast.Call)` only, mirroring the existing test's
`isinstance(node, ast.ImportFrom)` scoping style.

---

### `tests/test_tool_annotations.py` (2 fact tests, test, request-response)

**Analog:** `macos_apps_mcp/registry.py` — `removes_content_tools()` (lines 140-148),
the unfiltered-iteration template already in the codebase.

**Template to copy** (`macos_apps_mcp/registry.py:140-148`):
```python
def removes_content_tools() -> frozenset[str]:
    """Every ALL-records (registered or not) tool that "removes or replaces
    content" (GATE-05, D-04) ... Iterates every record, not just registered ones."""
    return frozenset(
        n for n, r in TOOLS.items() if r.removes_content or n.startswith("delete_")
    )
```

**Fix 1 — `test_run_shortcut_carries_open_world_hint`**
(`tests/test_tool_annotations.py:65-71`, current code):
```python
def test_run_shortcut_carries_open_world_hint():
    by_name = {t.name: t for t in _tools()}
    assert by_name["run_shortcut"].annotations.openWorldHint is True
```
`_tools()` is a live `Client(srv.mcp).list_tools()` call — empty for `run_shortcut`
under `MACOS_APPS_READ_ONLY=1` (gated off), so `by_name["run_shortcut"]` raises
`KeyError`. Replace with a direct `registry.TOOLS` read — `ToolRecord.annotations`
(`macos_apps_mcp/registry.py:62-67`) computes the identical dict FastMCP registration
uses, unconditionally of `registered`:
```python
def test_run_shortcut_carries_open_world_hint():
    assert registry.TOOLS["run_shortcut"].annotations["openWorldHint"] is True
```

**Fix 2 — `test_every_write_tool_is_audit_classified`**
(`tests/test_tool_annotations.py:101-128`, current final assertion at line 128):
```python
    assert set(registry.snapshot_sources()) | envelope_only == registry.write_tools()
```
Both `registry.snapshot_sources()` and `registry.write_tools()`
(`macos_apps_mcp/registry.py:105-118`) filter `r.registered` — empty under read-only.
Replace with the unfiltered equivalents, matching the `removes_content_tools()` shape:
```python
    all_writes = {n for n, r in registry.TOOLS.items() if r.is_write}
    all_snapshot_sources = {
        n for n, r in registry.TOOLS.items() if r.snapshot is not None
    }
    assert all_snapshot_sources | envelope_only == all_writes
```
`ToolRecord.is_write` (`macos_apps_mcp/registry.py:58-60`: `return self.tier != "read"`)
is already unfiltered — only the two derived-view calls need replacing.

**Precedent for this exact move** (Phase 1, already landed): `01-13-SUMMARY.md:51`
records `test_audit.py::test_audit_op_labels_send_tools_distinctly_from_write` being
rewritten from `registry.audit_verbs()` (registered-filtered) to
`registry.TOOLS[name].audit_verb` (unfiltered), for the identical reason.

---

### `tests/test_audit_middleware.py` (1 fact test, test, request-response)

**Analog:** same fix shape as above — `macos_apps_mcp/registry.py:140-148`
(`removes_content_tools`) unfiltered-iteration template.

**Current code** (`tests/test_audit_middleware.py:163-183`):
```python
def test_server_snapshot_sources_are_derived_and_satisfy_the_protocol():
    import macos_apps_mcp.registry as registry

    expected = {
        "update_event", "delete_event", "update_reminder", "complete_reminder",
        "update_note", "delete_note", "delete_draft",
    }
    snapshot_sources = registry.snapshot_sources()
    assert set(snapshot_sources) == expected
    for source in snapshot_sources.values():
        assert isinstance(source, Snapshotter)
    # every snapshot-capable tool is also a registered write tool
    ...
```
`registry.snapshot_sources()` is `registered`-filtered → empty set under read-only.

**Fix:**
```python
    snapshot_sources = {
        n: r.snapshot for n, r in registry.TOOLS.items() if r.snapshot is not None
    }
    assert set(snapshot_sources) == expected
    for source in snapshot_sources.values():
        assert isinstance(source, Snapshotter)
```
Keep whatever the trailing "also a registered write tool" assertion checks — if it
reads `registry.write_tools()` too, that call site needs the same unfiltered swap
(`{n for n, r in registry.TOOLS.items() if r.is_write}`).

---

### `tests/test_mail_cleanup.py` (1 fact test, test, request-response)

**Analog:** same fix shape — `macos_apps_mcp/registry.py:140-148`.

**Current code** (`tests/test_mail_cleanup.py:490-494`):
```python
def test_mail_duplicates_is_registered_read_only():
    import macos_apps_mcp.registry as registry

    assert "mail_duplicates" not in registry.write_tools()
    assert "trash_mail" in registry.write_tools()
```
The negative assertion (`mail_duplicates not in ...`) still holds against an empty
set under read-only; the positive assertion (`trash_mail in ...`) fails.

**Fix:**
```python
def test_mail_duplicates_is_registered_read_only():
    import macos_apps_mcp.registry as registry

    all_writes = {n for n, r in registry.TOOLS.items() if r.is_write}
    assert "mail_duplicates" not in all_writes
    assert "trash_mail" in all_writes
```

---

### `tests/test_server.py` (8 call tests, test, request-response)

**Analog:** `tests/test_doctor_deploy.py:25-29` — `_gate_off_only`, the named
skip-marker shape D-01 requires copying.

**Marker to copy verbatim in shape** (`tests/test_doctor_deploy.py:22-29`):
```python
# Four tests below assert "the import-time gate was off in this process" — false by
# construction under the RELEASING checklist's gated run (MACOS_APPS_ALLOW_SEND=mail
# set before import registers the send tools). The gate-ON half of every claim is
# pinned by test_gate_on_dispatch.py's subprocess; skipping here loses nothing.
_gate_off_only = pytest.mark.skipif(
    bool(registry.outbound_status()["registered"]),
    reason="valid only in a gate-off process (see test_gate_on_dispatch.py)",
)
```

**New marker for `test_server.py`** — `tiers` is already imported at
`tests/test_server.py:19` (`import macos_apps_mcp.tiers as tiers`), so the predicate
needs no new import:
```python
_write_gate_on_only = pytest.mark.skipif(
    tiers.read_only(),
    reason="valid only when write tools are registered (see server.py's _tool gate)",
)
```
Apply as a decorator to exactly the 8 named tests (verified live at these line
numbers): `test_create_reminder_rejects_out_of_range_priority` (426),
`test_create_event_all_day_rejects_utc_offset` (452),
`test_update_event_all_day_rejects_utc_offset` (465),
`test_create_reminder_recurrence_without_due_rejected` (501),
`test_create_event_rejects_bad_rrule` (538), `test_create_event_rejects_empty_start`
(585), `test_write_tool_converts_native_error_to_agent_directive` (815),
`test_optional_datetime_parse_error_names_the_field` (873).

**Example of one call test unchanged except the added decorator**
(`tests/test_server.py:426-429`):
```python
@_write_gate_on_only
def test_create_reminder_rejects_out_of_range_priority(monkeypatch):
    monkeypatch.setattr(srv, "_reminders", _FakeWriter())
    with pytest.raises(ToolError, match="priority must be"):
        srv.create_reminder("x", priority=11)
```
**Do not** add a try/except-to-`ToolError` re-implementation inside any of these
tests — D-01 states explicitly that a test-side copy of `_guard` proves the copy,
not the server.

**Why `tiers.read_only()` over a `registry.TOOLS[...]` read**: it is the exact
predicate `server.py:164` (`registered = not tiers.read_only()`) uses to decide the
write tier's gate — same boolean, no dependency on any one tool's record existing.

---

### `.github/workflows/ci.yml` (config, batch)

**Analog:** same file, the existing lint→test step sequence.

**Current file** (full, `.github/workflows/ci.yml:20-30`):
```yaml
jobs:
  check:
    runs-on: macos-latest
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v7
      - run: uv sync --locked
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run pytest
```

**Fix (D-02) — append one step:**
```yaml
      - run: uv run pytest
      - run: MACOS_APPS_READ_ONLY=1 uv run pytest
```
No new job, no matrix — GATE-07's own evidence is that this costs ~15s. Runs after
the default suite so a plain `pytest` failure surfaces first (existing step order
convention: lint before test, so a lint failure short-circuits before the slower
step — same logic argues the fast default suite runs before the read-only rerun,
which shares nearly the entire same 1458+ test collection).

---

### `tests/test_integration.py` (`inbox_messages` fixture, test/fixture, CRUD)

**Analog:** same file, `scratch_mailbox` fixture (lines 1493-1513) — its
non-Gmail account-selection logic is the join key `inbox_messages` must reuse per
D-04/Pitfall 2.

**`scratch_mailbox`'s account-selection logic to reuse** (`tests/test_integration.py:1493-1516`):
```python
@pytest.fixture
def scratch_mailbox():
    m = _mail_adapter()
    rows = [r for r in m.overview() if r["folder"].startswith("imap://")]
    if not rows:
        pytest.skip("no IMAP account in Mail on this Mac")
    gmail_accounts = {r["account_id"] for r in rows if "%5BGmail%5D" in r["folder"]}
    account_ids = sorted({r["account_id"] for r in rows})
    account = next((a for a in account_ids if a not in gmail_accounts), account_ids[0])
    name = "macos-apps-mcp-test"
    folder = f"imap://{account}/{name}"
    with contextlib.suppress(Exception):
        m.create_mailbox(name, account)
    return folder
```

**Current `inbox_messages`** (`tests/test_integration.py:1524-1533`, the D-04 target):
```python
@pytest.fixture
def inbox_messages():
    """Up to two real INBOX message ids plus the mailbox token they live in."""
    m = _mail_adapter()
    rows = [r for r in m.overview() if r["folder"].endswith("/INBOX") and r["total"]]
    if not rows:
        pytest.skip("no non-empty INBOX in Mail on this Mac")
    folder = rows[0]["folder"]
    hits = m.search(mailbox=folder, limit=2)["results"]
    if not hits:
        pytest.skip("no messages resolvable in the INBOX")
    return folder, [h["id"] for h in hits]
```
No account preference, no marker-subject filter — picks whichever INBOX `overview()`
lists first (unread-first order), independent of `scratch_mailbox`'s deterministic
non-Gmail choice.

**Fix shape (D-04)** — derive the account the same way `scratch_mailbox` does (either
by depending on the `scratch_mailbox` fixture directly, or by factoring the
account-selection block into a shared helper both fixtures call), then search by
marker subject within that account's INBOX, fail loud instead of skipping:
```python
MARKER_SUBJECT = "macos-apps-mcp integration marker"  # planner's call on exact text


@pytest.fixture
def inbox_messages(scratch_mailbox):
    # scratch_mailbox is "imap://<account>/macos-apps-mcp-test" — same account,
    # different folder; reuse its account so the cross-account and same-account
    # move tests agree on which account they operate on (D-04, Pitfall 2).
    account = scratch_mailbox.split("/")[2]
    m = _mail_adapter()
    inbox_rows = [
        r for r in m.overview()
        if r["folder"] == f"imap://{account}/INBOX"
    ]
    if not inbox_rows:
        pytest.fail(f"no INBOX for account {account} — check Mail is set up")
    folder = inbox_rows[0]["folder"]
    hits = m.search(subject=MARKER_SUBJECT, mailbox=folder, limit=2)["results"]
    if len(hits) < 2:
        pytest.fail(
            f"fewer than 2 marker mails in {folder} — seed them first: "
            f"MailAdapter().send('andrei@lav.ren', {MARKER_SUBJECT!r}, 'seed', "
            f"dry_run=False) x2"
        )
    return folder, [h["id"] for h in hits]
```
`search(subject=..., mailbox=...)` kwargs confirmed live at
`macos_apps_mcp/adapters/mail.py:1663-1678`. Exact subject text, seed-command
wording and whether `inbox_messages` depends on `scratch_mailbox` vs. shares a
factored helper are explicitly the planner's call (CONTEXT.md discretion) — this is
the shape, not the literal diff.

**Existing marker-mail idiom to reuse for the subject text** — sibling file already
has a stable send-marker convention (`tests/integration/test_mail_outbound.py:21-22`):
```python
SELF_ADDRESS = "andrei@lav.ren"
MARKER = "macos-apps-mcp integration"
```
Reusing this exact `MARKER` string (or a clearly-related variant) as the seed
subject keeps one naming convention for "mail this suite sent to itself" across
both files, instead of inventing a second one.

---

### `pyproject.toml` / `packaging/Info.plist` (config, transform, D-09 last plan only)

**Analog:** each other — `tests/test_packaging.py::test_bundle_version_tracks_pyproject`
already enforces the two stay equal; no new check needed, just the D-09 bump itself.

**Current values:**
```toml
# pyproject.toml:3
version = "0.11.0"
```
```xml
<!-- packaging/Info.plist:9 -->
<key>CFBundleShortVersionString</key><string>0.11.0</string>
```

**Fix (D-09, release plan only):** both bumped to `"0.12.0"` in the same commit, per
`docs/RELEASING.md`'s two-file version bump step. Verify with
`uv run pytest tests/test_packaging.py` before tagging, then `doctor().version` /
`doctor().build` prove the built daemon matches, per D-09.

## Shared Patterns

### Registered-vs-unfiltered registry read (GATE-07 root cause)
**Source:** `macos_apps_mcp/registry.py:140-148` (`removes_content_tools`, the
unfiltered template) vs. `:105-118` (`write_tools`/`snapshot_sources`/`audit_verbs`,
all `registered`-filtered by design).
**Apply to:** every one of the 4 fact tests
(`test_run_shortcut_carries_open_world_hint`, `test_every_write_tool_is_audit_classified`,
`test_server_snapshot_sources_are_derived_and_satisfy_the_protocol`,
`test_mail_duplicates_is_registered_read_only`) — each currently calls a
`registered`-filtered view to answer a "what IS this tool" question, which must
instead read `registry.TOOLS.items()` directly (optionally filtered on `r.is_write`
/ `r.snapshot is not None`, never on `r.registered`).
```python
# the unfiltered idiom, verbatim from registry.py:140-148
frozenset(n for n, r in TOOLS.items() if <fact-about-the-record>)
```

### Qualified native seam — never a bare `subprocess.*` call
**Source:** `macos_apps_mcp/runtime.py:222-251` (`tracked_run`); locked by
`tests/conftest.py`'s autouse `_no_real_osascript`-family fixture and
`tests/test_native_seam.py`'s AST tripwire.
**Apply to:** `macos_apps_mcp/doctor.py`'s `_process_name` (the GATE-11 fix) — the
same rule every `adapters/*.py` module already follows (`from .. import runtime`,
then `runtime.tracked_run(...)`, never `from ..runtime import tracked_run`).

### One named skip marker, never a repeated literal
**Source:** `tests/test_doctor_deploy.py:25-29` (`_gate_off_only`).
**Apply to:** `tests/test_server.py`'s new `_write_gate_on_only` marker for the 8
call tests — one definition near the top of the file, applied 8 times, so the skip
reason and predicate live in one place (D-01's explicit requirement, and the same
"one place to fix it" principle 01-13 already used for the analogous read-only gap).

### Account-agreement join key across fixtures
**Source:** `tests/test_integration.py:1493-1513` (`scratch_mailbox`'s deterministic
non-Gmail account selection).
**Apply to:** `tests/test_integration.py`'s `inbox_messages` rewrite (D-04) — must
derive its account from the same selection `scratch_mailbox` makes, not pick
independently from `overview()`'s natural order.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| GATE-11 Popen-spy plugin (one-time measurement, CONTEXT.md discretion) | test tooling | event-driven (subprocess spawn counting) | Not a committed repo file — CONTEXT.md/RESEARCH.md both frame this as a one-time proof, recommended to live under `.worktrees/` (git-ignored scratch), mirroring the `.daemon_probe.py` convention noted in `.planning/STATE.md`. No tracked-source analog exists because nothing like it has ever been committed; write it as scratch, not as a `tests/` file. |
| Marker-mail seed step (D-04) | operational step, not source | file I/O (one `send()` call x2, via the daemon) | Not a file — it is a plan task that calls the already-existing `send_mail` tool (or `MailAdapter().send(...)` directly) twice before the sweep. The pattern to copy is `tests/integration/test_mail_outbound.py:44-49`'s real-send round trip, already cited above; no new script or module is implied. |

## Metadata

**Analog search scope:** `macos_apps_mcp/` (doctor.py, registry.py, runtime.py,
tiers.py, server.py), `tests/` (test_native_seam.py, test_doctor.py,
test_doctor_deploy.py, test_tool_annotations.py, test_audit_middleware.py,
test_mail_cleanup.py, test_server.py, test_gate_on_dispatch.py, test_integration.py,
integration/test_mail_outbound.py), `.github/workflows/ci.yml`, `pyproject.toml`,
`packaging/Info.plist`.
**Files scanned:** 17 (all git-tracked, verified via `git ls-files`).
**Pattern extraction date:** 2026-09-28.
**Note:** every excerpt above was re-read live from the current `develop` checkout in
this session (not copied from RESEARCH.md verbatim) and matches RESEARCH.md's
line-number citations exactly — no drift since the research pass.
