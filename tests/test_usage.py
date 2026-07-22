"""Unit tests for the per-tool usage tally — log, rotation, aggregation (no TCC)."""

from __future__ import annotations

import asyncio

import macos_apps_mcp.runtime as rt


def test_usage_read_aggregates(tmp_path, monkeypatch):
    monkeypatch.setattr(rt, "state_dir", lambda: tmp_path)
    for tool in ["list_pointers", "audit", "list_pointers", "list_pointers"]:
        rt.usage_log(tool)
    tally = rt.usage_read()
    assert tally["list_pointers"]["count"] == 3
    assert tally["audit"]["count"] == 1
    # first/last bracket the run
    assert tally["list_pointers"]["first"] <= tally["list_pointers"]["last"]


def test_usage_read_missing_file_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(rt, "state_dir", lambda: tmp_path)
    assert rt.usage_read() == {}


def test_usage_read_skips_malformed(tmp_path, monkeypatch):
    monkeypatch.setattr(rt, "state_dir", lambda: tmp_path)
    (tmp_path / "usage.jsonl").write_text(
        '{"tool":"ok","ts":"t"}\nNOT JSON\n{"no_tool":1}\n{"tool":"ok2","ts":"t"}\n',
        encoding="utf-8",
    )
    assert set(rt.usage_read()) == {"ok", "ok2"}


def test_usage_log_swallows_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(rt, "state_dir", lambda: tmp_path / "missing" / "nested")
    rt.usage_log("x")  # must not raise


def test_usage_log_rotates_at_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(rt, "state_dir", lambda: tmp_path)
    monkeypatch.setattr(rt, "_AUDIT_MAX_BYTES", 200)
    for _ in range(40):
        rt.usage_log("some_tool_with_a_longish_name")
    assert (tmp_path / "usage.jsonl.1").exists()  # rotated at least once
    assert (tmp_path / "usage.jsonl").exists()  # a fresh current file remains


def test_usage_tool_reports_never_used(tmp_path, monkeypatch):
    from macos_apps_mcp.server import usage as usage_tool

    monkeypatch.setattr(rt, "state_dir", lambda: tmp_path)
    rt.usage_log("audit")  # a real registered tool, so it is NOT in never_used
    result = asyncio.run(usage_tool())
    assert result["total_calls"] == 1
    assert result["tools"][0]["tool"] == "audit"
    # a registered tool we never logged shows up in the pruning list
    assert "usage" in result["never_used"]
    assert "audit" not in result["never_used"]
