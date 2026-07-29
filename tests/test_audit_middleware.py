"""Unit tests for AuditMiddleware — envelope + before-state, failure isolation.

The middleware accepts its write-tool set and snapshot sources at construction
(the Snapshotter seam, contracts.py) — so these tests build one with fakes instead
of patching server globals.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import macos_apps_mcp.audit as au
from macos_apps_mcp.contracts import Pointer, Snapshotter

_WRITES = {"create_event", "update_event"}


def _mw(snapshot_sources=None):
    return au.AuditMiddleware(
        write_tools=_WRITES, snapshot_sources=snapshot_sources or {}
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
    # Snapshotter Protocol — no duck-typed method, no hand-maintained dict.
    import macos_apps_mcp.server as srv

    expected = {
        "update_event",
        "delete_event",
        "update_reminder",
        "complete_reminder",
        "update_note",
        "delete_note",
        "delete_draft",
    }
    assert set(srv._SNAPSHOT_SOURCES) == expected
    for source in srv._SNAPSHOT_SOURCES.values():
        assert isinstance(source, Snapshotter)
    # every snapshot-capable tool is also a registered write tool
    assert set(srv._SNAPSHOT_SOURCES) <= srv._WRITE_TOOLS
