"""Unit tests for the per-tool usage tally — log, rotation, aggregation (no TCC)."""

from __future__ import annotations

import asyncio

import macos_apps_mcp.audit as au


def test_usage_read_aggregates(tmp_path, monkeypatch):
    monkeypatch.setattr(au, "state_dir", lambda: tmp_path)
    for tool in ["list_pointers", "audit", "list_pointers", "list_pointers"]:
        au.usage_log(tool)
    tally = au.usage_read()
    assert tally["list_pointers"]["count"] == 3
    assert tally["audit"]["count"] == 1
    # first/last bracket the run
    assert tally["list_pointers"]["first"] <= tally["list_pointers"]["last"]


def test_usage_read_missing_file_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(au, "state_dir", lambda: tmp_path)
    assert au.usage_read() == {}


def test_usage_read_skips_malformed(tmp_path, monkeypatch):
    monkeypatch.setattr(au, "state_dir", lambda: tmp_path)
    (tmp_path / "usage.jsonl").write_text(
        '{"tool":"ok","ts":"t"}\nNOT JSON\n{"no_tool":1}\n{"tool":"ok2","ts":"t"}\n',
        encoding="utf-8",
    )
    assert set(au.usage_read()) == {"ok", "ok2"}


def test_usage_log_swallows_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(au, "state_dir", lambda: tmp_path / "missing" / "nested")
    au.usage_log("x")  # must not raise


def test_usage_read_unreadable_is_empty(tmp_path, monkeypatch):
    # never-raise contract: an unreadable log reads as an empty tally, no OSError.
    monkeypatch.setattr(au, "state_dir", lambda: tmp_path)
    au.usage_log("some_tool")
    path = tmp_path / "usage.jsonl"
    path.chmod(0o000)
    try:
        assert au.usage_read() == {}
    finally:
        path.chmod(0o600)


def test_usage_log_rotates_at_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(au, "state_dir", lambda: tmp_path)
    monkeypatch.setattr(au, "_AUDIT_MAX_BYTES", 200)
    for _ in range(40):
        au.usage_log("some_tool_with_a_longish_name")
    assert (tmp_path / "usage.jsonl.1").exists()  # rotated at least once
    assert (tmp_path / "usage.jsonl").exists()  # a fresh current file remains


def test_usage_report_builds_the_whole_report(tmp_path, monkeypatch):
    # C5b: the report logic lives in audit (no async, no mcp) — the tool is a
    # one-line delegation over the registered-tool names.
    monkeypatch.setattr(au, "state_dir", lambda: tmp_path)
    au.usage_log("busy")
    au.usage_log("busy")
    au.usage_log("quiet")
    report = au.usage_report({"busy", "quiet", "never"})
    assert [e["tool"] for e in report["tools"]] == ["busy", "quiet"]  # busiest first
    assert report["tools"][0]["count"] == 2
    assert report["never_used"] == ["never"]
    assert report["total_calls"] == 3


def test_usage_report_empty_tally(tmp_path, monkeypatch):
    monkeypatch.setattr(au, "state_dir", lambda: tmp_path)
    report = au.usage_report({"a", "b"})
    assert report == {"tools": [], "never_used": ["a", "b"], "total_calls": 0}


def test_usage_tool_reports_never_used(tmp_path, monkeypatch):
    from macos_apps_mcp.server import usage as usage_tool

    monkeypatch.setattr(au, "state_dir", lambda: tmp_path)
    au.usage_log("audit")  # a real registered tool, so it is NOT in never_used
    result = asyncio.run(usage_tool())
    assert result["total_calls"] == 1
    assert result["tools"][0]["tool"] == "audit"
    # a registered tool we never logged shows up in the pruning list
    assert "usage" in result["never_used"]
    assert "audit" not in result["never_used"]
