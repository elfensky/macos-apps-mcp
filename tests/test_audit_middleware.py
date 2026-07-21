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

    monkeypatch.setitem(
        srv._AUDIT_SNAPSHOT, "update_event", SimpleNamespace(snapshot=_boom)
    )
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
