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
