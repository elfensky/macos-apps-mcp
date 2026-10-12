"""Unit tests for AuditMiddleware — envelope + before-state, failure isolation.

The middleware accepts its audit-verb map and snapshot sources at construction (the
Snapshotter seam, contracts.py) — so these tests build one with fakes instead of
patching server globals. GATE-06: a write is a KEY of ``audit_verbs`` — the map IS
the write-tool set, and the verb rides with it — so a write cannot be tracked
without a verb (no ``_audit_op`` fallback).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

import macos_apps_mcp.audit as au
import macos_apps_mcp.registry as registry
import macos_apps_mcp.server as srv
import macos_apps_mcp.tiers as tiers
from macos_apps_mcp.contracts import Pointer, Snapshotter

_AUDIT_VERBS = {"create_event": "create", "update_event": "update"}


def _mw(snapshot_sources=None, audit_verbs=None, dry_run_defaults=None):
    return au.AuditMiddleware(
        audit_verbs=_AUDIT_VERBS if audit_verbs is None else audit_verbs,
        snapshot_sources=snapshot_sources or {},
        dry_run_defaults=dry_run_defaults,
    )


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


def _capture(monkeypatch):
    records = []
    monkeypatch.setattr(au, "audit_write", records.append)
    monkeypatch.setattr(au, "usage_log", lambda tool: None)  # keep tests hermetic
    return records


def test_op_comes_from_the_verb_map(monkeypatch):
    # GATE-06: the verb is a per-tool FACT stated once at registration and read back
    # from the map — not re-derived from the tool name at audit time.
    records = _capture(monkeypatch)
    mw = _mw(audit_verbs={"t": "move"})
    _run(mw, _ctx("t", {}), _Result({"id": "X-1"}))
    assert records[0]["op"] == "move"
    _run(mw, _ctx("untracked", {}), _Result({"id": "X-2"}))
    assert len(records) == 1  # a tool not in the map is never logged


def test_create_logs_envelope_no_before(monkeypatch):
    records = _capture(monkeypatch)
    _run(
        _mw(),
        _ctx("create_event", {"title": "x"}),
        _Result({"id": "E-9", "summary": "s", "deeplink": "d"}),
    )
    assert len(records) == 1
    r = records[0]
    assert r["tool"] == "create_event" and r["op"] == "create"
    assert r["before"] is None and r["after"]["id"] == "E-9"
    assert r["target_id"] == "E-9" and "ts" in r


def test_update_captures_before(monkeypatch):
    records = _capture(monkeypatch)
    fake = SimpleNamespace(
        snapshot=lambda ident: Pointer(id=ident, summary="was", deeplink="")
    )
    _run(
        _mw({"update_event": fake}),
        _ctx("update_event", {"id": "E-1|9", "title": "x"}),
        _Result({"id": "E-1|9", "summary": "now", "deeplink": "d"}),
    )
    assert records[0]["before"]["summary"] == "was"
    assert records[0]["after"]["summary"] == "now"
    assert records[0]["target_id"] == "E-1|9"


def test_before_state_is_captured_for_every_id_addressed_write(monkeypatch):
    # #161b's guard rail. The seam was measured (~0.65s per snapshot) and deliberately
    # left alone; this pins WHY, so an optimizer who skips the snapshot to save a spawn
    # breaks a test instead of quietly shipping an audit log that cannot answer "what
    # was it before?" — the one thing mail_undo and the audit trail rest on.
    calls = []
    fake = SimpleNamespace(
        snapshot=lambda ident: (
            calls.append(ident)
            or Pointer(id=ident, summary="was", deeplink="d", folder="drafts")
        )
    )
    records = _capture(monkeypatch)
    _run(
        _mw({"update_event": fake}),
        _ctx("update_event", {"id": "E-1", "title": "x"}),
        _Result({"id": "E-1", "summary": "now", "deeplink": "d"}),
    )
    assert calls == ["E-1"], "the write's before-state must be snapshotted, once"
    assert records[0]["before"] == {
        "id": "E-1",
        "summary": "was",
        "deeplink": "d",
        "folder": "drafts",
    }


def test_tool_error_writes_no_record(monkeypatch):
    records = _capture(monkeypatch)
    _run(_mw(), _ctx("create_event", {}), _Result(None, is_error=True))
    assert records == []


def test_snapshot_failure_never_propagates(monkeypatch):
    records = _capture(monkeypatch)

    def _boom(_ident):
        raise RuntimeError("snapshot blew up")

    # must still return the result and still log (before=None)
    res = _run(
        _mw({"update_event": SimpleNamespace(snapshot=_boom)}),
        _ctx("update_event", {"id": "E-1"}),
        _Result({"id": "E-1", "summary": "s", "deeplink": "d"}),
    )
    assert res.structured_content["id"] == "E-1"
    assert records[0]["before"] is None


def test_non_write_tool_not_logged(monkeypatch):
    records = _capture(monkeypatch)
    _run(_mw(), _ctx("events", {"when": "today"}), _Result([]))
    assert records == []


def test_audit_write_failure_never_propagates(monkeypatch):
    # the record-build/audit_write path must swallow its own errors too — a logging
    # failure must never break the user's write (the load-bearing guarantee)
    def _boom(_record):
        raise RuntimeError("audit_write blew up")

    monkeypatch.setattr(au, "audit_write", _boom)
    monkeypatch.setattr(au, "usage_log", lambda tool: None)
    res = _run(
        _mw(),
        _ctx("create_event", {"title": "x"}),
        _Result({"id": "E-1", "summary": "s", "deeplink": "d"}),
    )
    assert res.structured_content["id"] == "E-1"  # tool result returned unchanged


def test_server_snapshot_sources_are_derived_and_satisfy_the_protocol():
    # #67 deepening: the tool→adapter map is DERIVED at registration
    # (@_write_tool(snapshot=…)), and every registered source satisfies the declared
    # Snapshotter Protocol — no duck-typed method, no hand-maintained dict. GATE-04:
    # the registry (not a hand-maintained server.py set) is the one record now.
    # Read registry.TOOLS directly (every record, registered or not, GATE-07/D-01) —
    # registry.snapshot_sources()/write_tools() filter to r.registered, empty under
    # MACOS_APPS_READ_ONLY=1. This is a fact about a write tool (every record,
    # registered or not), not about what's live in this process.
    import macos_apps_mcp.registry as registry

    expected = {
        "update_event",
        "delete_event",
        "update_reminder",
        "complete_reminder",
        "delete_reminder",
        "update_note",
        "delete_note",
        "delete_draft",
    }
    snapshot_sources = {
        n: r.snapshot for n, r in registry.TOOLS.items() if r.snapshot is not None
    }
    assert set(snapshot_sources) == expected
    for source in snapshot_sources.values():
        assert isinstance(source, Snapshotter)
    all_writes = {n for n, r in registry.TOOLS.items() if r.is_write}
    # every snapshot-capable tool is also a write tool (every record, registered or not)
    assert set(snapshot_sources) <= all_writes


# --- #222: the record tells a preview from a write, and names the client -------------


def _delete_x_app():
    """A local app with the REAL middleware: `delete_x` previews by default."""

    def delete_x(id: str, dry_run: bool = True) -> dict:
        return {"id": id, "dry_run": dry_run}

    app = FastMCP("t")
    app.add_middleware(
        _mw(
            audit_verbs={"delete_x": "delete"},
            dry_run_defaults={"delete_x": registry._dry_run_default(delete_x)},
        )
    )
    app.tool(delete_x)
    return app


def _call(app, arguments):
    async def go():
        async with Client(app) as c:
            return await c.call_tool("delete_x", arguments)

    return asyncio.run(go())


_OMITTED = object()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (_OMITTED, True),
        ("false", False),
        ("FALSE", False),
        ("0", False),
        ("no", False),
        (0, False),
        (False, False),
        ("1", True),
        ("yes", True),
        (True, True),
    ],
    ids=repr,
)
def test_dry_run_coercion_matches_the_tools_own(monkeypatch, value, expected):
    # A real write is never recorded as a preview, nor a preview as a write.
    records = _capture(monkeypatch)
    args = {"id": "A"} if value is _OMITTED else {"id": "A", "dry_run": value}
    _call(_delete_x_app(), args)
    assert [r["dry_run"] for r in records] == [expected]
    assert records[0]["args"] == args  # as the client sent them


@pytest.mark.parametrize("value", ["banana", " false", None], ids=repr)
def test_dry_run_rejected_value_fails_the_call_and_writes_no_record(monkeypatch, value):
    records = _capture(monkeypatch)
    with pytest.raises(ToolError):
        _call(_delete_x_app(), {"id": "A", "dry_run": value})
    assert records == []


def test_dry_run_sent_default_and_omitted_record_the_same(monkeypatch):
    records = _capture(monkeypatch)
    _call(_delete_x_app(), {"id": "A", "dry_run": True})
    _call(_delete_x_app(), {"id": "A"})
    sent, omitted = records
    assert sent["dry_run"] is True and omitted["dry_run"] is True
    assert sent["args"] == {"id": "A", "dry_run": True}
    assert omitted["args"] == {"id": "A"}


def test_dry_run_no_arguments_records_the_tools_default(monkeypatch):
    records = _capture(monkeypatch)
    mw = _mw(audit_verbs={"t": "x"}, dry_run_defaults={"t": True})
    _run(mw, _ctx("t", None), _Result({"id": "X-1"}))
    _run(mw, _ctx("t", {}), _Result({"id": "X-2"}))
    assert [r["dry_run"] for r in records] == [True, True]


def test_dry_run_false_default_and_unknown_tool_record_false(monkeypatch):
    records = _capture(monkeypatch)
    mw = _mw(
        audit_verbs={"a": "x", "b": "x"},
        dry_run_defaults={"a": False},  # b has no dry_run parameter at all
    )
    _run(mw, _ctx("a", {}), _Result({"id": "1"}))
    _run(mw, _ctx("b", {}), _Result({"id": "2"}))
    assert [r["dry_run"] for r in records] == [False, False]


def test_caller_without_a_fastmcp_context_is_the_fallback(monkeypatch):
    records = _capture(monkeypatch)
    _run(_mw(), _ctx("create_event", {}), _Result({"id": "E-1"}))
    assert records[0]["caller"] == "unknown-client"
    assert "session" not in records[0]


def _ctx_with_client(info, name="create_event"):
    ctx = _ctx(name, {})
    ctx.fastmcp_context = SimpleNamespace(
        session=SimpleNamespace(client_params=SimpleNamespace(clientInfo=info))
    )
    return ctx


def test_caller_names_the_client_and_the_shim_session(monkeypatch):
    records = _capture(monkeypatch)
    info = SimpleNamespace(name="claude-code", version="2.1.9", session="abc12345")
    _run(_mw(), _ctx_with_client(info), _Result({"id": "E-1"}))
    assert records[0]["caller"] == "claude-code 2.1.9"
    assert records[0]["session"] == "abc12345"


def test_caller_without_a_shim_session_has_no_session_key(monkeypatch):
    records = _capture(monkeypatch)
    info = SimpleNamespace(name="claude-code", version="2.1.9")
    _run(_mw(), _ctx_with_client(info), _Result({"id": "E-1"}))
    assert records[0]["caller"] == "claude-code 2.1.9"
    assert "session" not in records[0]


def test_caller_is_one_bounded_line(monkeypatch):
    records = _capture(monkeypatch)
    info = SimpleNamespace(name="x" * 500 + "\nforged", version="1", session="s\n2")
    _run(_mw(), _ctx_with_client(info), _Result({"id": "E-1"}))
    for key in ("caller", "session"):
        assert "\n" not in records[0][key] and len(records[0][key]) <= 200


@pytest.mark.parametrize(
    "info", [SimpleNamespace(name="", version=""), None], ids=["blank", "no-info"]
)
def test_caller_blank_or_missing_client_info_is_the_fallback(monkeypatch, info):
    records = _capture(monkeypatch)
    _run(_mw(), _ctx_with_client(info), _Result({"id": "E-1"}))
    assert records[0]["caller"] == "unknown-client"
    assert "session" not in records[0]


def test_caller_outside_a_request_is_the_fallback(monkeypatch):
    # `fastmcp_context.session` raises RuntimeError when no request is active
    class _Ctx:
        @property
        def session(self):
            raise RuntimeError("no active request")

    records = _capture(monkeypatch)
    ctx = _ctx("create_event", {})
    ctx.fastmcp_context = _Ctx()
    _run(_mw(), ctx, _Result({"id": "E-1"}))
    assert records[0]["caller"] == "unknown-client"


@pytest.mark.skipif(
    tiers.read_only(), reason="write tools are absent under MACOS_APPS_READ_ONLY"
)
def test_dry_run_server_write_tool_called_without_it_records_a_preview(monkeypatch):
    # ROADMAP 03.1 criterion 1 (#222): the real server, a real write tool, no dry_run.
    class _Notes:
        def delete(self, id, expect_title, dry_run):
            return {"dry_run": dry_run, "would_delete": {"id": id}}

    records = _capture(monkeypatch)
    monkeypatch.setattr(srv, "_notes", _Notes())

    async def go():
        async with Client(srv.mcp) as c:
            await c.call_tool("delete_note", {"id": "N-1"})

    asyncio.run(go())
    assert [r["tool"] for r in records] == ["delete_note"]
    assert records[0]["dry_run"] is True
    assert records[0]["args"] == {"id": "N-1"}
