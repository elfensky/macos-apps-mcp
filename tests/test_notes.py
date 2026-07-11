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


# --- dry_run delete (#54) ------------------------------------------------------------


def test_delete_dry_run_reads_title_and_deletes_nothing(monkeypatch):
    from mac_mcp.adapters.notes import _DELETE, _PREVIEW_DELETE

    calls = []

    def fake(script, *args):
        calls.append((script, args))
        return "Groceries"  # the preview script returns the live title

    monkeypatch.setattr("mac_mcp.adapters.notes.run_osascript", fake)
    p = NotesAdapter().delete("N-1", dry_run=True)
    assert isinstance(p, Pointer) and p.id == "N-1" and p.summary == "Groceries"
    assert calls == [(_PREVIEW_DELETE, ("N-1",))]  # only id passed, no expect_title
    assert all(s != _DELETE for s, _ in calls)  # ACCEPTANCE: nothing was deleted


def test_delete_dry_run_delegates_expect_title_guard_to_applescript(monkeypatch):
    # #54 review: the expect_title guard MUST run in AppleScript (same `is not` compare
    # as _DELETE — case-insensitive, whitespace-significant), NOT a Python `!=`, or the
    # preview can report the OPPOSITE of the real delete. Assert expect_title is
    # forwarded to the preview script as argv so the guard is delegated, not re-done.
    from mac_mcp.adapters.notes import _DELETE, _PREVIEW_DELETE

    calls = []
    monkeypatch.setattr(
        "mac_mcp.adapters.notes.run_osascript",
        lambda script, *a: calls.append((script, a)) or "Groceries",
    )
    NotesAdapter().delete("N-1", expect_title="groceries", dry_run=True)
    assert calls == [
        (_PREVIEW_DELETE, ("N-1", "groceries"))
    ]  # guard delegated verbatim
    assert all(s != _DELETE for s, _ in calls)  # nothing deleted


def test_delete_dry_run_title_mismatch_surfaces_native_error(monkeypatch):
    # the AppleScript guard raises on mismatch (via run_osascript → NativeError), just
    # as the real delete does — the preview must not swallow it into a "would delete".
    from mac_mcp.adapters.notes import _DELETE
    from mac_mcp.runtime import NativeError

    scripts = []

    def fake(script, *args):
        scripts.append(script)
        raise NativeError("osascript failed: note title does not match expect_title")

    monkeypatch.setattr("mac_mcp.adapters.notes.run_osascript", fake)
    with pytest.raises(NativeError, match="does not match expect_title"):
        NotesAdapter().delete("N-1", expect_title="Wrong", dry_run=True)
    assert _DELETE not in scripts  # a mismatch previews nothing and deletes nothing


# --- sqlite read plane (#60) — synthetic NoteStore fixtures --------------------------

import os  # noqa: E402
import sqlite3  # noqa: E402

from mac_mcp.adapters import notes as notes_mod  # noqa: E402
from mac_mcp.adapters.notes import _escape_like, _note_pointer  # noqa: E402

_NS_COLS = (
    "Z_PK INTEGER PRIMARY KEY, ZTITLE1 TEXT, ZSNIPPET TEXT, ZFOLDER INTEGER, "
    "ZNOTEDATA INTEGER, ZMARKEDFORDELETION INTEGER, ZISPINNED INTEGER, "
    "ZISPASSWORDPROTECTED INTEGER, ZTITLE2 TEXT, ZOWNER INTEGER, ZNAME TEXT"
)


def _make_notestore(path, *, uuid="STORE-UUID"):
    """A synthetic NoteStore: one account, one folder, and a few notes (one pinned, one
    locked, one tombstoned) — only the columns the reader queries."""
    conn = sqlite3.connect(path)
    conn.execute(f"CREATE TABLE ZICCLOUDSYNCINGOBJECT ({_NS_COLS})")
    conn.execute("CREATE TABLE Z_METADATA (Z_UUID TEXT)")
    conn.execute("INSERT INTO Z_METADATA (Z_UUID) VALUES (?)", (uuid,))
    # cols: Z_PK, ZTITLE1, ZSNIPPET, ZFOLDER, ZNOTEDATA, ZMARKEDFORDELETION, ZISPINNED,
    #       ZISPASSWORDPROTECTED, ZTITLE2, ZOWNER, ZNAME
    rows = [
        (1, None, None, None, None, None, None, None, None, None, "iCloud"),  # account
        (2, None, None, None, None, None, None, None, "Groceries", 1, None),  # folder
        (
            6,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            "Recently Deleted",
            1,
            None,
        ),  # trash
        (
            3,
            "Milk",
            "Milk, eggs, bread",
            2,
            99,
            0,
            1,
            0,
            None,
            None,
            None,
        ),  # pinned note
        (4, "Secret", "", 2, 98, 0, 0, 1, None, None, None),  # locked, empty snippet
        (5, "Gone", "deleted", 2, 97, 1, 0, 0, None, None, None),  # tombstoned (purged)
        # a note MOVED to Recently Deleted stays live (ZMARKEDFORDELETION=0) — excluded
        # by folder, exactly as the AppleScript reader excludes it (#60 review).
        (7, "Trashed", "in the bin", 6, 96, 0, 0, 0, None, None, None),
    ]
    conn.executemany(
        f"INSERT INTO ZICCLOUDSYNCINGOBJECT VALUES ({','.join('?' * 11)})", rows
    )
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def notestore(tmp_path, monkeypatch):
    path = _make_notestore(tmp_path / "NoteStore.sqlite")
    monkeypatch.setattr(notes_mod, "NOTESTORE", path)
    return path


def test_sqlite_all_maps_snippet_id_folder_and_flags(notestore):
    ptrs = NotesAdapter().get_all()
    assert [
        p.id for p in ptrs
    ] == [  # newest (Z_PK DESC) first; folder/account/tombstone out
        "x-coredata://STORE-UUID/ICNote/p4",
        "x-coredata://STORE-UUID/ICNote/p3",
    ]
    by_id = {p.id: p for p in ptrs}
    milk = by_id["x-coredata://STORE-UUID/ICNote/p3"]
    assert milk.summary == "📌 Milk, eggs, bread"  # pinned prefix + ZSNIPPET
    assert milk.folder == "iCloud / Groceries"
    secret = by_id["x-coredata://STORE-UUID/ICNote/p4"]
    assert secret.summary == "🔒 Secret"  # locked; empty snippet falls back to title


def test_sqlite_all_excludes_tombstoned(notestore):
    assert all("/p5" not in p.id for p in NotesAdapter().get_all())


def test_sqlite_all_excludes_recently_deleted(notestore):
    # a note moved to Recently Deleted stays live (ZMARKEDFORDELETION=0) but sits in the
    # trash folder — it must NOT appear, matching the AppleScript reader (#60 review).
    # The tombstone filter alone would leak it (ZMARKEDFORDELETION is the purge flag).
    ids = {p.id for p in NotesAdapter().get_all()}
    assert "x-coredata://STORE-UUID/ICNote/p7" not in ids
    assert ids == {  # only the two live, non-trashed notes
        "x-coredata://STORE-UUID/ICNote/p3",
        "x-coredata://STORE-UUID/ICNote/p4",
    }


def test_escape_like_makes_wildcards_literal():
    assert _escape_like("50%_off\\") == "50\\%\\_off\\\\"


def test_note_pointer_folder_null_branches():
    # folder label degrades gracefully: no account → folder name only; no folder → None.
    row = (9, "T", "snip", 0, 0, "Work", None)  # folder present, account NULL
    assert _note_pointer(row, "U").folder == "Work"
    row = (9, "T", "snip", 0, 0, None, None)  # neither folder nor account
    assert _note_pointer(row, "U").folder is None
    row = (9, "T", "snip", 0, 0, "Work", "iCloud")  # both
    assert _note_pointer(row, "U").folder == "iCloud / Work"


def test_sqlite_search_matches_title_or_snippet(notestore):
    ids = {p.id for p in NotesAdapter().get_pointers("eggs")}  # only in p3's snippet
    assert ids == {"x-coredata://STORE-UUID/ICNote/p3"}
    ids = {p.id for p in NotesAdapter().get_pointers("secret")}  # p4's title
    assert ids == {"x-coredata://STORE-UUID/ICNote/p4"}


def test_sqlite_search_empty_query_raises(notestore):
    with pytest.raises(ValueError, match="title substring"):
        NotesAdapter().get_pointers("  ")


def test_schema_drift_falls_back_to_applescript(tmp_path, monkeypatch):
    # a NoteStore missing an expected column → fingerprint mismatch → transparent
    # fallback to the AppleScript enumeration (no FDA needed, no regression).
    bad = tmp_path / "NoteStore.sqlite"
    conn = sqlite3.connect(bad)
    conn.execute("CREATE TABLE ZICCLOUDSYNCINGOBJECT (Z_PK INTEGER)")  # missing columns
    conn.execute("CREATE TABLE Z_METADATA (Z_UUID TEXT)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(notes_mod, "NOTESTORE", bad)
    canned = "x-coredata://S/ICNote/p1\tiCloud / Notes\tFrom AppleScript\n"
    monkeypatch.setattr(notes_mod, "run_osascript", lambda *a: canned)
    ptrs = NotesAdapter().get_all()
    assert [p.summary for p in ptrs] == ["From AppleScript"]  # the fallback ran
    assert ptrs[0].folder == "iCloud / Notes"


@pytest.mark.skipif(os.getuid() == 0, reason="root bypasses file permissions")
def test_missing_fda_falls_back_to_applescript(notestore, monkeypatch):
    # missing Full Disk Access (a permission-denied read) → fall back, not hard-error
    # (the whole reason Notes keeps its AppleScript reader).
    os.chmod(notestore, 0o000)
    try:
        canned = "x-coredata://S/ICNote/p1\tiCloud / Notes\tFallback\n"
        monkeypatch.setattr(notes_mod, "run_osascript", lambda *a: canned)
        ptrs = NotesAdapter().get_all()
        assert [p.summary for p in ptrs] == ["Fallback"]
    finally:
        os.chmod(notestore, 0o644)


def test_x_coredata_id_built_from_store_uuid(notestore):
    # the x-coredata id must match what AppleScript returns for the same note (one id
    # across both backends) — built from Z_METADATA.Z_UUID + the note's Z_PK.
    ptrs = NotesAdapter().get_all()
    assert all(p.id.startswith("x-coredata://STORE-UUID/ICNote/p") for p in ptrs)
