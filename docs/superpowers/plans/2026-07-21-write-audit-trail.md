# Write Audit Trail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An append-only JSONL audit trail of every write (with before-state on update/delete), plus an `audit()` read tool — so a user can see and hand-reverse what the server changed.

**Architecture:** A central `AuditMiddleware` (mirrors `UntrustedDataNotice`) logs every write's envelope and, for update/delete/complete, captures before-state via a per-tool registry calling a new `adapter.snapshot(id)` read (through `anyio.to_thread`). Storage + rotation live in `runtime` and never raise. Adapters gain only a `snapshot` read.

**Tech Stack:** Python 3.12+, FastMCP 2.0 middleware, anyio, EventKit/sqlite reads, `json` (stdlib), pytest, uv, ruff.

## Global Constraints

- Tools in `server.py` are THIN dispatch; audit logic lives in one central middleware, not in adapters or tool bodies.
- **Auditing must never fail a user's write** — every audit path (`audit_write`, snapshot, record build) swallows its own exceptions.
- Before-state is read on the serialized native worker immediately before the write (atomic w.r.t. our own writes); a concurrent external edit in that window is accepted/documented.
- Storage: `$XDG_STATE_HOME/macos-apps-mcp/audit.jsonl` (default `~/.local/state/macos-apps-mcp`), append-only, ~5 MB rotation to one `.1` backup.
- The `before`/`after` fields use the same `Pointer`→dict shape (`_emit`) as `dry_run` previews.
- Reads uniform (`Pointer`); `snapshot(id) -> Pointer | None` is a plain by-id read reusing each adapter's existing resolve — no `contracts.py` Protocol change.
- Every registered write tool must be classified audit-wise (`_AUDIT_SNAPSHOT` or `_ENVELOPE_ONLY`) — self-enforced by a test.
- Style: ruff (line-length 88; E, F, I, UP, B, SIM). No mypy. `except Exception` in audit paths carries a `# noqa: BLE001` with the "must never break a write" reason.
- Verify: `uv run pytest && uv run ruff check . && uv run ruff format --check .`. Integration (`-m integration`) manual only, never CI.
- Branch: `feat/67-audit-trail` (already created).

---

### Task 1: Storage — `state_dir` + `audit_write` + `audit_read`

**Files:**
- Modify: `macos_apps_mcp/runtime.py` (add `state_dir`, `_audit_path`, `audit_write`, `audit_read`, `AUDIT_LIMIT`, `_AUDIT_MAX_BYTES`; `json`, `os`, `Path`, `log` are already imported — verify and add any missing)
- Test: `tests/test_audit.py` (create)

**Interfaces:**
- Produces:
  - `runtime.state_dir() -> Path` — the XDG state dir, created on use.
  - `runtime.audit_write(record: dict) -> None` — append one JSON line; rotates at the cap; never raises.
  - `runtime.audit_read(since: str | None = None, limit: int = AUDIT_LIMIT) -> list[dict]` — recent entries newest-first, `since`-filtered, malformed lines skipped.
  - `runtime.AUDIT_LIMIT = 50`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_audit.py`:

```python
"""Unit tests for the write audit log — storage, rotation, reader (no TCC)."""

from __future__ import annotations

import json

import macos_apps_mcp.runtime as rt


def test_audit_write_appends(tmp_path, monkeypatch):
    monkeypatch.setattr(rt, "state_dir", lambda: tmp_path)
    rt.audit_write({"tool": "create_event", "op": "create"})
    rt.audit_write({"tool": "delete_note", "op": "delete"})
    lines = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["tool"] == "create_event"


def test_audit_write_rotates_at_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(rt, "state_dir", lambda: tmp_path)
    monkeypatch.setattr(rt, "_AUDIT_MAX_BYTES", 200)
    for i in range(40):
        rt.audit_write({"n": i, "pad": "x" * 40})
    assert (tmp_path / "audit.jsonl.1").exists()  # rotated at least once
    assert (tmp_path / "audit.jsonl").exists()  # a fresh current file remains


def test_audit_write_swallows_errors(tmp_path, monkeypatch):
    # state_dir points at a path whose parent does not exist and is not created →
    # opening the file raises, and audit_write must swallow it (never break a write)
    monkeypatch.setattr(rt, "state_dir", lambda: tmp_path / "missing" / "nested")
    rt.audit_write({"tool": "x"})  # must not raise


def test_audit_read_newest_first_and_since(tmp_path, monkeypatch):
    monkeypatch.setattr(rt, "state_dir", lambda: tmp_path)
    for ts, tool in [
        ("2026-07-21T10:00:00", "a"),
        ("2026-07-21T11:00:00", "b"),
        ("2026-07-21T12:00:00", "c"),
    ]:
        rt.audit_write({"ts": ts, "tool": tool})
    assert [r["tool"] for r in rt.audit_read()] == ["c", "b", "a"]
    assert [r["tool"] for r in rt.audit_read(since="2026-07-21T11:00:00")] == ["c", "b"]


def test_audit_read_skips_malformed(tmp_path, monkeypatch):
    monkeypatch.setattr(rt, "state_dir", lambda: tmp_path)
    (tmp_path / "audit.jsonl").write_text(
        '{"tool":"ok"}\nNOT JSON\n{"tool":"ok2"}\n', encoding="utf-8"
    )
    assert {r["tool"] for r in rt.audit_read()} == {"ok", "ok2"}


def test_audit_read_missing_file_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(rt, "state_dir", lambda: tmp_path)
    assert rt.audit_read() == []


def test_audit_read_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(rt, "state_dir", lambda: tmp_path)
    for i in range(rt.AUDIT_LIMIT + 10):
        rt.audit_write({"ts": f"2026-07-21T00:00:{i:02d}", "tool": str(i)})
    assert len(rt.audit_read()) == rt.AUDIT_LIMIT
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_audit.py -v`
Expected: FAIL with `AttributeError`/`module ... has no attribute 'audit_write'`.

- [ ] **Step 3: Implement in `macos_apps_mcp/runtime.py`**

Confirm `json`, `os`, `log`, and `Path` (from `pathlib`) are imported at the top of runtime.py; add any that are missing. Add near the other module-level helpers:

```python
AUDIT_LIMIT = 50
_AUDIT_MAX_BYTES = 5 * 1024 * 1024  # rotate past ~5 MB; one backup


def state_dir() -> Path:
    """The XDG state dir for this server, created on use."""
    base = os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state")
    d = Path(base) / "macos-apps-mcp"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _audit_path() -> Path:
    return state_dir() / "audit.jsonl"


def audit_write(record: dict) -> None:
    """Append one JSON record to the audit log. NEVER raises — auditing must not fail a
    user's write, so a logging error (disk full, permission, missing dir) is swallowed."""
    try:
        path = _audit_path()
        if path.exists() and path.stat().st_size > _AUDIT_MAX_BYTES:
            path.replace(path.with_name(path.name + ".1"))  # rotate; one backup
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:  # noqa: BLE001 — audit must never break a write
        log.debug("audit_write failed: %s", e)


def audit_read(since: str | None = None, limit: int = AUDIT_LIMIT) -> list[dict]:
    """Recent audit entries, newest first, at most ``limit``. ``since`` (ISO datetime)
    drops older entries by lexical ts compare (entries are naive-local, one format).
    Malformed lines are skipped; a missing log is empty."""
    path = _audit_path()
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue  # skip a truncated/corrupt line, never fail the read
        if since and rec.get("ts", "") < since:
            continue
        out.append(rec)
    out.reverse()  # newest first
    return out[:limit]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_audit.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Full verify + commit**

Run: `uv run pytest && uv run ruff check . && uv run ruff format --check .`

```bash
git add macos_apps_mcp/runtime.py tests/test_audit.py
git commit -m "feat(runtime): audit log storage — state_dir, audit_write, audit_read (#67)"
```

---

### Task 2: Adapter `snapshot(id)` reads

**Files:**
- Modify: `macos_apps_mcp/adapters/calendar.py`, `macos_apps_mcp/adapters/reminders.py`, `macos_apps_mcp/adapters/notes.py`
- Test: `tests/test_notes.py`, `tests/test_calendar.py`, `tests/test_reminders.py` (extend)

**Interfaces:**
- Produces: `CalendarAdapter.snapshot(ident) -> Pointer | None`, `RemindersAdapter.snapshot(ident) -> Pointer | None`, `NotesAdapter.snapshot(ident) -> Pointer | None` — the current pointer for an id, or `None` if it no longer resolves.

- [ ] **Step 1: Write the failing tests**

To `tests/test_notes.py` append (reuses `_make_title_notestore` from the #66 tests, and `NOTESTORE` monkeypatch pattern):

```python
def test_notes_snapshot_found(tmp_path, monkeypatch):
    import macos_apps_mcp.adapters.notes as notes_mod

    db = _make_title_notestore(tmp_path / "NoteStore.sqlite", rows=((1, "My note"),))
    monkeypatch.setattr(notes_mod, "NOTESTORE", db)
    p = notes_mod.NotesAdapter().snapshot("x-coredata://STORE-UUID/ICNote/p1")
    assert p is not None and p.id.endswith("/p1") and p.summary == "My note"


def test_notes_snapshot_missing_returns_none(tmp_path, monkeypatch):
    import macos_apps_mcp.adapters.notes as notes_mod

    db = _make_title_notestore(tmp_path / "NoteStore.sqlite")
    monkeypatch.setattr(notes_mod, "NOTESTORE", db)
    assert notes_mod.NotesAdapter().snapshot("x-coredata://STORE-UUID/ICNote/p999") is None
```

To `tests/test_calendar.py` append:

```python
def test_calendar_snapshot_missing_returns_none(monkeypatch):
    import macos_apps_mcp.adapters.calendar as cal

    monkeypatch.setattr(cal, "run_native", lambda fn: fn())
    monkeypatch.setattr(cal, "store", lambda: object())

    def _raise(_s, _i):
        raise ValueError("no such event")

    monkeypatch.setattr(cal, "_resolve_event", _raise)
    assert cal.CalendarAdapter().snapshot("E-1|123") is None


def test_calendar_snapshot_found(monkeypatch):
    import macos_apps_mcp.adapters.calendar as cal

    monkeypatch.setattr(cal, "run_native", lambda fn: fn())
    monkeypatch.setattr(cal, "store", lambda: object())
    ev = _fake_event(
        "Standup", "E-1", datetime(2026, 6, 23, 9, 0), datetime(2026, 6, 23, 9, 15)
    )
    monkeypatch.setattr(cal, "_resolve_event", lambda _s, _i: ev)
    p = cal.CalendarAdapter().snapshot("E-1|123")
    assert p is not None and "Standup" in p.summary
```

To `tests/test_reminders.py` append (mirror that file's existing fake-store / fake-reminder helpers; if it has none, use `SimpleNamespace`):

```python
def test_reminders_snapshot_missing_returns_none(monkeypatch):
    import macos_apps_mcp.adapters.reminders as rem

    monkeypatch.setattr(rem, "run_native", lambda fn: fn())
    fake_store = SimpleNamespace(calendarItemWithIdentifier_=lambda i: None)
    monkeypatch.setattr(rem, "store", lambda: fake_store)
    assert rem.RemindersAdapter().snapshot("R-1") is None
```

(Add `from types import SimpleNamespace` and any `datetime` import at the top of the test files if absent — check first.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_notes.py tests/test_calendar.py tests/test_reminders.py -k snapshot -v`
Expected: FAIL with `AttributeError: 'CalendarAdapter' object has no attribute 'snapshot'` (etc.).

- [ ] **Step 3: Implement the three methods**

`macos_apps_mcp/adapters/calendar.py` — add to `CalendarAdapter`:

```python
    def snapshot(self, ident: str) -> Pointer | None:
        """The event's current pointer by id, or None if it no longer resolves — the
        before-state the audit layer captures just before an update/delete."""

        def work():
            s = store()
            try:
                return _event_pointer(_resolve_event(s, ident))
            except ValueError:
                return None

        return run_native(work)
```

`macos_apps_mcp/adapters/reminders.py` — add to `RemindersAdapter`:

```python
    def snapshot(self, ident: str) -> Pointer | None:
        """The reminder's current pointer by id, or None if absent — audit before-state."""

        def work():
            r = store().calendarItemWithIdentifier_(ident)
            return _reminder_pointer(r) if r is not None else None

        return run_native(work)
```

`macos_apps_mcp/adapters/notes.py` — add to `NotesAdapter` (`clean_summary`, `Pointer`, `_read_title_by_id` already available):

```python
    def snapshot(self, ident: str) -> Pointer | None:
        """The note's current pointer by id (title only), or None if absent — audit
        before-state. Pointer-level suffices for manual undo; a full-field snapshot is a
        non-breaking later enhancement."""
        title = self._read_title_by_id(ident)
        if title is None:
            return None
        return Pointer(
            id=ident,
            summary=clean_summary(title) or "(untitled note)",
            deeplink="",
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_notes.py tests/test_calendar.py tests/test_reminders.py -k snapshot -v`
Expected: PASS.

- [ ] **Step 5: Full verify + commit**

Run: `uv run pytest && uv run ruff check . && uv run ruff format --check .`

```bash
git add macos_apps_mcp/adapters/calendar.py macos_apps_mcp/adapters/reminders.py macos_apps_mcp/adapters/notes.py tests/test_notes.py tests/test_calendar.py tests/test_reminders.py
git commit -m "feat(adapters): snapshot(id) by-id pointer read for audit before-state (#67)"
```

---

### Task 3: `AuditMiddleware` + write-tool registry

**Files:**
- Modify: `macos_apps_mcp/server.py` (add `import anyio`; import `audit_write` from `.runtime`; populate `_WRITE_TOOLS` in the write decorators; add `_AUDIT_SNAPSHOT`, op/args/result helpers, `AuditMiddleware`, register it)
- Test: `tests/test_audit_middleware.py` (create)

**Interfaces:**
- Consumes: `runtime.audit_write` (T1), `adapter.snapshot` (T2), `_emit`, `Pointer` (existing in server).
- Produces: `server._WRITE_TOOLS: set[str]`, `server._AUDIT_SNAPSHOT: dict[str, object]`, `server.AuditMiddleware`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_audit_middleware.py`:

```python
"""Unit tests for AuditMiddleware — envelope + before-state, failure isolation."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import macos_apps_mcp.server as srv
from macos_apps_mcp.contracts import Pointer


class _Result:
    def __init__(self, structured, is_error=False):
        self.structured_content = structured
        self.is_error = is_error


def _ctx(name, arguments):
    return SimpleNamespace(message=SimpleNamespace(name=name, arguments=arguments))


def _run(mw, ctx, result):
    async def call_next(_c):
        return result

    return asyncio.run(mw.on_call_tool(ctx, call_next))


def test_create_logs_envelope_no_before(monkeypatch):
    records = []
    monkeypatch.setattr(srv, "audit_write", records.append)
    _run(
        srv.AuditMiddleware(),
        _ctx("create_event", {"title": "x"}),
        _Result({"id": "E-9", "summary": "s", "deeplink": "d"}),
    )
    assert len(records) == 1
    r = records[0]
    assert r["tool"] == "create_event" and r["op"] == "create"
    assert r["before"] is None and r["after"]["id"] == "E-9"
    assert r["target_id"] == "E-9" and "ts" in r


def test_update_captures_before(monkeypatch):
    records = []
    monkeypatch.setattr(srv, "audit_write", records.append)
    fake = SimpleNamespace(
        snapshot=lambda ident: Pointer(id=ident, summary="was", deeplink="")
    )
    monkeypatch.setitem(srv._AUDIT_SNAPSHOT, "update_event", fake)
    _run(
        srv.AuditMiddleware(),
        _ctx("update_event", {"id": "E-1|9", "title": "x"}),
        _Result({"id": "E-1|9", "summary": "now", "deeplink": "d"}),
    )
    assert records[0]["before"]["summary"] == "was"
    assert records[0]["after"]["summary"] == "now"
    assert records[0]["target_id"] == "E-1|9"


def test_tool_error_writes_no_record(monkeypatch):
    records = []
    monkeypatch.setattr(srv, "audit_write", records.append)
    _run(srv.AuditMiddleware(), _ctx("create_event", {}), _Result(None, is_error=True))
    assert records == []


def test_snapshot_failure_never_propagates(monkeypatch):
    records = []
    monkeypatch.setattr(srv, "audit_write", records.append)

    def _boom(_ident):
        raise RuntimeError("snapshot blew up")

    monkeypatch.setitem(srv._AUDIT_SNAPSHOT, "update_event", SimpleNamespace(snapshot=_boom))
    # must still return the result and still log (before=None)
    res = _run(
        srv.AuditMiddleware(),
        _ctx("update_event", {"id": "E-1"}),
        _Result({"id": "E-1", "summary": "s", "deeplink": "d"}),
    )
    assert res.structured_content["id"] == "E-1"
    assert records[0]["before"] is None


def test_non_write_tool_not_logged(monkeypatch):
    records = []
    monkeypatch.setattr(srv, "audit_write", records.append)
    _run(srv.AuditMiddleware(), _ctx("events", {"when": "today"}), _Result([]))
    assert records == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_audit_middleware.py -v`
Expected: FAIL with `AttributeError: module 'macos_apps_mcp.server' has no attribute 'AuditMiddleware'`.

- [ ] **Step 3: Implement in `macos_apps_mcp/server.py`**

Add `import anyio` to the imports and `audit_write` to the `.runtime` import. Add a module-level `_WRITE_TOOLS: set[str] = set()` near the annotation constants, and record names in BOTH write decorators (in the non-read-only branch, before returning):

```python
def _write_tool(fn):
    """..."""
    if _read_only():
        return fn
    _WRITE_TOOLS.add(fn.__name__)
    return mcp.tool(annotations=_DESTRUCTIVE_ANNOTATIONS)(_guard(fn))


def _additive_tool(fn):
    """..."""
    if _read_only():
        return fn
    _WRITE_TOOLS.add(fn.__name__)
    return mcp.tool(annotations=_ADDITIVE_ANNOTATIONS)(_guard(fn))
```

After the adapter instances (`_calendar`/`_reminders`/`_notes`) and after `_emit` are defined, add the registry, helpers, and middleware:

```python
# Audit trail (#67). before-state is captured only for the id-addressed update/delete/
# complete tools; create_* and non-id writes are envelope-only.
_AUDIT_SNAPSHOT = {
    "update_event": _calendar,
    "delete_event": _calendar,
    "update_reminder": _reminders,
    "complete_reminder": _reminders,
    "update_note": _notes,
    "delete_note": _notes,
}


def _audit_op(tool: str) -> str:
    for prefix in ("create", "update", "delete"):
        if tool.startswith(prefix):
            return prefix
    return {
        "complete_reminder": "complete",
        "run_shortcut": "action",
        "safari_open": "open",
        "mail_reply": "reply",
    }.get(tool, "write")


def _audit_args(args: dict) -> dict:
    # truncate long string values so a big note body can't bloat the log
    return {
        k: (v[:200] + "…" if isinstance(v, str) and len(v) > 200 else v)
        for k, v in args.items()
    }


def _audit_after(result) -> dict | None:
    sc = getattr(result, "structured_content", None)
    if isinstance(sc, dict):
        inner = sc.get("result", sc)  # FastMCP may wrap a scalar under "result"
        if isinstance(inner, dict) and "id" in inner:
            return inner
    return None


def _safe_snapshot(adapter, ident: str) -> dict | None:
    try:
        p = adapter.snapshot(ident)
        return _emit(p) if p is not None else None
    except Exception:  # noqa: BLE001 — audit must never break a write
        return None


class AuditMiddleware(Middleware):
    """Append an audit record for every write; capture before-state on update/delete
    (#67). Central seam — adapters hold no audit logic. All failures are swallowed."""

    async def on_call_tool(self, context, call_next):
        tool = context.message.name
        args = dict(context.message.arguments or {})
        before = None
        adapter = _AUDIT_SNAPSHOT.get(tool)
        if adapter is not None and args.get("id"):
            before = await anyio.to_thread.run_sync(_safe_snapshot, adapter, args["id"])
        result = await call_next(context)
        if tool in _WRITE_TOOLS and not result.is_error:
            try:
                after = _audit_after(result)
                audit_write(
                    {
                        "ts": datetime.now().isoformat(timespec="seconds"),
                        "tool": tool,
                        "op": _audit_op(tool),
                        "args": _audit_args(args),
                        "target_id": args.get("id") or (after or {}).get("id"),
                        "before": before,
                        "after": after,
                    }
                )
            except Exception:  # noqa: BLE001 — audit must never break a write
                pass
        return result


mcp.add_middleware(AuditMiddleware())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_audit_middleware.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Full verify + commit**

Run: `uv run pytest && uv run ruff check . && uv run ruff format --check .`

```bash
git add macos_apps_mcp/server.py tests/test_audit_middleware.py
git commit -m "feat(server): AuditMiddleware — log writes + before-state (#67)"
```

---

### Task 4: `audit()` read tool + self-enforcement + integration

**Files:**
- Modify: `macos_apps_mcp/server.py` (add the `audit` tool; import `audit_read`)
- Modify: `tests/test_server.py` (dispatch test) and `tests/test_tool_annotations.py` (classify `audit` + the write-audit self-enforcement test)
- Modify: `tests/test_integration.py` (end-to-end via in-process Client)

**Interfaces:**
- Consumes: `runtime.audit_read` (T1), `_WRITE_TOOLS`/`_AUDIT_SNAPSHOT` (T3).
- Produces: the `audit` MCP read tool.

- [ ] **Step 1: Write the failing dispatch + self-enforcement tests**

To `tests/test_server.py` add:

```python
def test_audit_tool_reads(monkeypatch):
    import macos_apps_mcp.server as srv2

    monkeypatch.setattr(srv2, "audit_read", lambda since=None: [{"tool": "create_event"}])
    out = srv2.audit()
    assert out == [{"tool": "create_event"}]


def test_audit_tool_passes_since(monkeypatch):
    import macos_apps_mcp.server as srv2

    seen = {}
    monkeypatch.setattr(
        srv2, "audit_read", lambda since=None: seen.setdefault("since", since) or []
    )
    srv2.audit("2026-07-21T00:00:00")
    assert seen["since"] == "2026-07-21T00:00:00"
```

To `tests/test_tool_annotations.py` add the self-enforcement test and classify `audit` (a read tool needing no macOS permission → `_PERMISSION["audit"] = None`):

```python
def test_every_write_tool_is_audit_classified():
    import macos_apps_mcp.server as srv

    # writes with no id-addressed before-state: creates + non-id actions
    envelope_only = {
        "create_reminder",
        "create_event",
        "create_note",
        "create_contact",
        "create_draft",
        "mail_reply",
        "safari_open",
        "run_shortcut",
    }
    assert srv._WRITE_TOOLS == set(srv._AUDIT_SNAPSHOT) | envelope_only
```

Add `"audit": None` to the `_PERMISSION` map in that file.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_server.py -k audit_tool tests/test_tool_annotations.py -v`
Expected: FAIL (`audit` attr missing / permission-map mismatch).

- [ ] **Step 3: Add the `audit` tool**

In `macos_apps_mcp/server.py`, add `audit_read` to the `.runtime` import and the tool near the read tools:

```python
@_read_tool
def audit(since: str | None = None) -> list[dict]:
    """Recent write audit entries (newest first) — what macos-apps-mcp changed, with
    before/after pointers, enough to reverse a change by hand. `since` optional ISO
    datetime (call now() to ground it) drops older entries; bounded to the last 50.
    Read-only; no permission (reads a local log at ~/.local/state/macos-apps-mcp)."""
    return audit_read(since)
```

- [ ] **Step 4: Run the dispatch + annotation tests**

Run: `uv run pytest tests/test_server.py -k audit_tool tests/test_tool_annotations.py -v`
Expected: PASS.

- [ ] **Step 5: Add the integration test (manual, on-device, end-to-end via Client)**

In `tests/test_integration.py` add (mirror the file's marker style; `Client` is imported in test_server — add `from fastmcp import Client` locally in the test if needed):

```python
@pytest.mark.integration
def test_audit_records_update_with_before(tmp_path, monkeypatch):
    import asyncio
    from datetime import datetime, timedelta

    from fastmcp import Client

    import macos_apps_mcp.runtime as rt
    import macos_apps_mcp.server as srv
    from macos_apps_mcp.adapters.calendar import CalendarAdapter
    from macos_apps_mcp.contracts import CalendarEventData

    monkeypatch.setattr(rt, "state_dir", lambda: tmp_path)  # audit to a temp log
    run_native(request_access)
    a = CalendarAdapter()
    start = datetime.now().replace(microsecond=0) + timedelta(days=1)
    created = a.create_event(
        CalendarEventData(
            title=f"{TITLE_PREFIX} audit", start=start, end=start + timedelta(hours=1)
        )
    )
    try:

        async def _drive():
            async with Client(srv.mcp) as c:
                await c.call_tool(
                    "update_event",
                    {
                        "id": created.id,
                        "title": f"{TITLE_PREFIX} audit (edited)",
                        "start": (start + timedelta(hours=2)).isoformat(),
                        "end": (start + timedelta(hours=3)).isoformat(),
                    },
                )

        asyncio.run(_drive())
        entries = rt.audit_read()
        upd = next(e for e in entries if e["tool"] == "update_event")
        assert upd["before"] and "audit" in upd["before"]["summary"]
        assert upd["after"] and "edited" in upd["after"]["summary"]
        assert upd["target_id"].split("|")[0] == created.id.split("|")[0]
    finally:
        a.delete_event(created.id)
```

- [ ] **Step 6: Full verification**

Run:
```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```
Expected: all pass; the integration test deselected by default. Confirm collectible:
`uv run pytest -m integration --collect-only tests/test_integration.py 2>&1 | grep audit_records_update`

- [ ] **Step 7: Commit**

```bash
git add macos_apps_mcp/server.py tests/test_server.py tests/test_tool_annotations.py tests/test_integration.py
git commit -m "feat(server): audit() read tool + write-audit self-enforcement (#67)"
```

---

## Post-plan

- [ ] Open a PR from `feat/67-audit-trail` → `develop`, closing #67. Note that `audit()` returns local-store text (titles) and rides the untrusted-data notice; the before-state atomicity caveat (external edit in the pre-write window) is documented in the middleware.
