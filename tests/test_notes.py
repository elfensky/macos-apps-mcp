"""Unit tests for the notes adapter — pure parsing (no osascript)."""

from __future__ import annotations

import pytest

from mac_mcp.adapters.notes import (
    MAX_BODIES,
    NotesAdapter,
    _parse,
    _parse_all,
    _parse_bodies,
)
from mac_mcp.contracts import Pointer


def test_parse_id_and_title():
    raw = "x-coredata://S/ICNote/p1\tGroceries\nx-coredata://S/ICNote/p2\tIdeas\n"
    ptrs = _parse(raw)
    assert len(ptrs) == 2
    assert isinstance(ptrs[0], Pointer)
    assert ptrs[0].id == "x-coredata://S/ICNote/p1"
    assert ptrs[0].summary == "Groceries"
    assert ptrs[0].deeplink == ""
    assert ptrs[1].summary == "Ideas"


def test_parse_untitled():
    ptrs = _parse("x-coredata://S/ICNote/p3\t\n")
    assert ptrs[0].summary == "(untitled note)"


def test_parse_skips_blank():
    assert _parse("\n   \n") == []


def test_parse_all_id_folder_title():
    raw = (
        "x-coredata://S/ICNote/p1\tiCloud / Groceries\tMilk\n"
        "x-coredata://S/ICNote/p2\tOn My Mac / Ideas\tRocket\n"
    )
    ptrs = _parse_all(raw)
    assert len(ptrs) == 2
    assert ptrs[0].id == "x-coredata://S/ICNote/p1"
    assert ptrs[0].folder == "iCloud / Groceries"
    assert ptrs[0].summary == "Milk"
    assert ptrs[0].deeplink == ""
    assert ptrs[1].folder == "On My Mac / Ideas"


def test_parse_all_untitled():
    ptrs = _parse_all("x-coredata://S/ICNote/p3\tiCloud / Notes\t\n")
    assert ptrs[0].summary == "(untitled note)"
    assert ptrs[0].folder == "iCloud / Notes"


def test_parse_all_skips_blank():
    assert _parse_all("\n   \n") == []


def test_parse_bodies_basic():
    raw = "id1\x1fHello\x1eid2\x1fWorld\x1e"
    assert _parse_bodies(raw) == [
        {"id": "id1", "body": "Hello"},
        {"id": "id2", "body": "World"},
    ]


def test_parse_bodies_preserves_newlines_and_tabs():
    raw = "id1\x1fline one\nline two\tindented\x1e"
    out = _parse_bodies(raw)
    assert out == [{"id": "id1", "body": "line one\nline two\tindented"}]


def test_parse_bodies_keeps_empty_body():
    assert _parse_bodies("id1\x1f\x1e") == [{"id": "id1", "body": ""}]


def test_parse_bodies_skips_trailing_and_malformed():
    # trailing "" after final RS, and a record with no US separator, are skipped
    assert _parse_bodies("id1\x1fHi\x1emalformed\x1e") == [{"id": "id1", "body": "Hi"}]


def test_get_bodies_rejects_empty():
    with pytest.raises(ValueError, match="at least one note id"):
        NotesAdapter().get_bodies([])


def test_get_bodies_rejects_oversize():
    with pytest.raises(ValueError, match="at most 50"):
        NotesAdapter().get_bodies([f"id{i}" for i in range(MAX_BODIES + 1)])


def test_delete_rejects_empty():
    with pytest.raises(ValueError, match="needs a note id"):
        NotesAdapter().delete("")


def test_delete_rejects_whitespace():
    with pytest.raises(ValueError, match="needs a note id"):
        NotesAdapter().delete("   ")


def test_delete_passes_id_and_title(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "mac_mcp.adapters.notes.run_osascript",
        lambda script, *args: calls.append(args) or "",
    )
    NotesAdapter().delete("N-1", expect_title="Milk")
    assert calls == [("N-1", "Milk")]


def test_delete_without_title_passes_only_id(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "mac_mcp.adapters.notes.run_osascript",
        lambda script, *args: calls.append(args) or "",
    )
    NotesAdapter().delete("N-1")
    assert calls == [("N-1",)]


def test_get_bodies_sanitizes_and_preserves_structure(monkeypatch):
    # #52: a hydrated body is control-stripped but keeps its line/tab structure (it is
    # legitimately multi-line — unlike a one-line summary, it must not be flattened).
    raw = "N-1\x1fLine1\nLine2\x00\tend\x1e"
    monkeypatch.setattr("mac_mcp.adapters.notes.run_osascript", lambda *a: raw)
    out = NotesAdapter().get_bodies(["N-1"])
    assert out == [{"id": "N-1", "body": "Line1\nLine2\tend"}]


def test_get_bodies_huge_body_downgrades_without_failing_batch(monkeypatch):
    # a single pathological body (a pasted dump) must not fail the whole batch: it
    # downgrades to a per-item notice while the sibling note hydrates normally.
    from mac_mcp.runtime import BODY_HARD_MAX

    huge = "z" * (BODY_HARD_MAX + 1)
    raw = f"N-1\x1f{huge}\x1eN-2\x1fok body\x1e"
    monkeypatch.setattr("mac_mcp.adapters.notes.run_osascript", lambda *a: raw)
    out = NotesAdapter().get_bodies(["N-1", "N-2"])
    assert out[0]["id"] == "N-1" and out[0]["body"].startswith("[not hydrated:")
    assert out[1] == {"id": "N-2", "body": "ok body"}
