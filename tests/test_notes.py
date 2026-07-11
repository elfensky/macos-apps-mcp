"""Unit tests for the notes adapter — pure parsing (no osascript)."""

from __future__ import annotations

import pytest

from mac_mcp.adapters.notes import (
    MAX_BODIES,
    NotesAdapter,
    _parse_all,
    _parse_bodies,
)
from mac_mcp.contracts import Pointer


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

import gzip  # noqa: E402
import os  # noqa: E402
import sqlite3  # noqa: E402

from mac_mcp.adapters import notes as notes_mod  # noqa: E402
from mac_mcp.adapters.notes import (  # noqa: E402
    _decode_note_data,
    _note_pointer,
    _pk_from_id,
)

_NS_COLS = (
    "Z_PK INTEGER PRIMARY KEY, ZTITLE1 TEXT, ZSNIPPET TEXT, ZFOLDER INTEGER, "
    "ZNOTEDATA INTEGER, ZMARKEDFORDELETION INTEGER, ZISPINNED INTEGER, "
    "ZISPASSWORDPROTECTED INTEGER, ZTITLE2 TEXT, ZOWNER INTEGER, ZNAME TEXT"
)


# --- protobuf wire-format builders (craft the real ZDATA byte layout, not our output)
def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | 0x80 if n else b)
        if not n:
            return bytes(out)


def _len_field(field: int, payload: bytes) -> bytes:
    return bytes([(field << 3) | 2]) + _varint(len(payload)) + payload


def _varint_field(field: int, value: int) -> bytes:
    return bytes([(field << 3) | 0]) + _varint(value)


def _note_proto(text: bytes) -> bytes:
    """gzip(NoteStoreProto): document(2){ version(2 varint), note(3){ note_text(2 str),
    attribute_run(5) } } — with non-target fields the decoder must skip to reach it."""
    note = _varint_field(1, 0) + _len_field(2, text) + _len_field(5, b"\x08\x01")
    document = _varint_field(2, 1) + _len_field(3, note)  # version before note
    return gzip.compress(_len_field(2, document))


def _make_notestore(path, *, uuid="STORE-UUID", bodies=None, extra_notes=()):
    """A synthetic NoteStore: one account, folders (incl. trash), a few notes, and their
    ZICNOTEDATA body blobs. `bodies` maps a note's ZNOTEDATA fk → plain text (gzipped
    protobuf); default gives p3/p4 bodies. `extra_notes` is [(pk, title, snippet)] live
    notes in the Groceries folder (for fold/search cases). Only the columns the reader
    queries."""
    if bodies is None:
        bodies = {99: "Milk, eggs, bread — the full note body", 98: "Secret full body"}
    conn = sqlite3.connect(path)
    conn.execute(f"CREATE TABLE ZICCLOUDSYNCINGOBJECT ({_NS_COLS})")
    conn.execute("CREATE TABLE Z_METADATA (Z_UUID TEXT)")
    conn.execute("CREATE TABLE ZICNOTEDATA (Z_PK INTEGER PRIMARY KEY, ZDATA BLOB)")
    conn.execute("INSERT INTO Z_METADATA (Z_UUID) VALUES (?)", (uuid,))
    conn.executemany(
        "INSERT INTO ZICNOTEDATA (Z_PK, ZDATA) VALUES (?, ?)",
        [(pk, _note_proto(text.encode())) for pk, text in bodies.items()],
    )
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
    # live notes in the Groceries folder (pk 2). ZNOTEDATA must be non-null (the
    # note-row discriminator the query filters on) — reuse pk; no body needed here.
    rows += [
        (pk, title, snippet, 2, pk, 0, 0, 0, None, None, None)
        for pk, title, snippet in extra_notes
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


@pytest.fixture
def fold_notestore(tmp_path, monkeypatch):
    # titles Apple would store typographically; queries a model would type in ASCII.
    path = _make_notestore(
        tmp_path / "NoteStore.sqlite",
        extra_notes=[
            (20, "Café résumé", "morning notes"),  # diacritics
            (21, "Andrei’s list", "todo"),  # U+2019 curly apostrophe
            (22, "Quote “hello”", "…and more…"),  # curly quotes/ellipsis
            (23, "well-known facts", "hyphen stays"),  # hyphen must NOT be folded away
        ],
    )
    monkeypatch.setattr(notes_mod, "NOTESTORE", path)
    return path


def test_search_is_diacritic_insensitive(fold_notestore):
    # ASCII query finds the accented title (#64 café == cafe).
    ids = {p.id for p in NotesAdapter().get_pointers("cafe resume")}
    assert "x-coredata://STORE-UUID/ICNote/p20" in ids


def test_search_folds_smart_apostrophe(fold_notestore):
    # ASCII apostrophe finds the U+2019 title and vice-versa.
    assert {p.id for p in NotesAdapter().get_pointers("andrei's list")} == {
        "x-coredata://STORE-UUID/ICNote/p21"
    }
    assert {p.id for p in NotesAdapter().get_pointers("Andrei’s")} == {
        "x-coredata://STORE-UUID/ICNote/p21"
    }


def test_search_folds_curly_quotes_and_ellipsis(fold_notestore):
    assert {p.id for p in NotesAdapter().get_pointers('quote "hello"')} == {
        "x-coredata://STORE-UUID/ICNote/p22"
    }
    assert {p.id for p in NotesAdapter().get_pointers("and more...")} == {
        "x-coredata://STORE-UUID/ICNote/p22"
    }


def test_search_leaves_hyphens_intact(fold_notestore):
    # a hyphenated title is found by its hyphenated form (acceptance: unaffected)...
    assert {p.id for p in NotesAdapter().get_pointers("well-known")} == {
        "x-coredata://STORE-UUID/ICNote/p23"
    }
    # ...and the fold does NOT collapse "well-known" into "wellknown".
    assert NotesAdapter().get_pointers("wellknown") == []


def test_sqlite_search_empty_query_raises(notestore):
    with pytest.raises(ValueError, match="title substring"):
        NotesAdapter().get_pointers("  ")


def test_sqlite_search_query_that_folds_to_empty_raises(fold_notestore):
    # #64 review: a non-empty query made only of fold-away chars must NOT slip past the
    # guard and match nearly every note. "¨" folds to a space, a lone combining accent
    # folds to "" — both must raise, not return the whole store.
    for degenerate in ("¨", "́"):  # spacing diaeresis → " "; combining accent → ""
        with pytest.raises(ValueError, match="title substring"):
            NotesAdapter().get_pointers(degenerate)


def test_search_fallback_enumerates_and_folds(tmp_path, monkeypatch):
    # on drift, get_pointers falls back to the AppleScript enumeration and folds there
    # too: an ASCII query still finds a typographically-titled note (no FDA regression).
    bad = tmp_path / "NoteStore.sqlite"
    conn = sqlite3.connect(bad)
    conn.execute("CREATE TABLE ZICCLOUDSYNCINGOBJECT (Z_PK INTEGER)")  # drift
    conn.execute("CREATE TABLE Z_METADATA (Z_UUID TEXT)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(notes_mod, "NOTESTORE", bad)
    canned = (
        "x-coredata://S/ICNote/p1\tiCloud / Notes\tCafé résumé\n"
        "x-coredata://S/ICNote/p2\tiCloud / Notes\tOther\n"
    )
    monkeypatch.setattr(notes_mod, "run_osascript", lambda *a: canned)
    ptrs = NotesAdapter().get_pointers("cafe resume")
    assert [p.id for p in ptrs] == ["x-coredata://S/ICNote/p1"]


def test_search_fallback_ignores_untitled_placeholder(tmp_path, monkeypatch):
    # #64 review: an untitled note must NOT match "note"/"untitled" via the
    # "(untitled note)" display placeholder — the fallback matches the RAW title, so an
    # empty title folds to "" and matches nothing (as the sqlite path and old
    # `whose name contains` did).
    bad = tmp_path / "NoteStore.sqlite"
    conn = sqlite3.connect(bad)
    conn.execute("CREATE TABLE ZICCLOUDSYNCINGOBJECT (Z_PK INTEGER)")  # drift
    conn.execute("CREATE TABLE Z_METADATA (Z_UUID TEXT)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(notes_mod, "NOTESTORE", bad)
    canned = (
        "x-coredata://S/ICNote/p1\tiCloud / Notes\t\n"  # untitled (empty title)
        "x-coredata://S/ICNote/p2\tiCloud / Notes\tShopping\n"
    )
    monkeypatch.setattr(notes_mod, "run_osascript", lambda *a: canned)
    assert NotesAdapter().get_pointers("note") == []  # placeholder must not match
    assert NotesAdapter().get_pointers("untitled") == []


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


# --- ZDATA gzip+protobuf body decode (#60 commit 2) ----------------------------------


def test_decode_note_data_roundtrip():
    assert _decode_note_data(_note_proto(b"Hello body")) == "Hello body"


def test_decode_note_data_multibyte():
    text = "café 🎉 note".encode()
    assert _decode_note_data(_note_proto(text)) == "café 🎉 note"


def test_decode_note_data_empty_text():
    assert _decode_note_data(_note_proto(b"")) == ""


def test_decode_note_data_non_gzip_declines():
    assert _decode_note_data(b"not gzip at all") is None


def test_decode_note_data_none_and_nonbytes_decline():
    assert _decode_note_data(None) is None
    assert _decode_note_data("a string") is None  # type: ignore[arg-type]


def test_decode_note_data_truncated_gzip_declines():
    full = _note_proto(b"Hello body")
    assert _decode_note_data(full[: len(full) // 2]) is None  # cut mid-stream


def test_decode_note_data_gzip_of_garbage_declines():
    # valid gzip, but the payload isn't the expected protobuf → decline, not garbage.
    assert _decode_note_data(gzip.compress(b"\xff\xff\xff not protobuf")) is None


def test_decode_note_data_missing_text_field_declines():
    # a well-formed proto whose Note has no note_text(2) field → None (no fabrication).
    note = _len_field(5, b"\x08\x01")  # only an attribute_run, no note_text
    document = _len_field(3, note)
    assert _decode_note_data(gzip.compress(_len_field(2, document))) is None


def test_pk_from_id():
    assert _pk_from_id("x-coredata://STORE-UUID/ICNote/p42") == 42
    assert _pk_from_id("garbage") is None
    assert _pk_from_id("x-coredata://S/ICNote/pABC") is None


def test_get_bodies_decodes_via_sqlite(notestore):
    out = NotesAdapter().get_bodies(["x-coredata://STORE-UUID/ICNote/p3"])
    assert out == [
        {
            "id": "x-coredata://STORE-UUID/ICNote/p3",
            "body": "Milk, eggs, bread — the full note body",
        }
    ]


def test_get_bodies_gap_fills_undecodable_via_applescript(notestore, monkeypatch):
    # p5's ZNOTEDATA fk (97) has no ZICNOTEDATA row → sqlite can't decode it → the id is
    # gap-filled via AppleScript, so it is NOT silently dropped.
    pid = "x-coredata://STORE-UUID/ICNote/p5"
    monkeypatch.setattr(
        notes_mod, "run_osascript", lambda *a: f"{pid}\x1ffrom applescript\x1e"
    )
    out = NotesAdapter().get_bodies([pid])
    assert out == [{"id": pid, "body": "from applescript"}]


def test_get_bodies_store_unavailable_falls_back_whole_batch(tmp_path, monkeypatch):
    # a drifted store (no ZICNOTEDATA table) → SchemaDrift → the whole batch degrades to
    # the AppleScript body reader.
    bad = tmp_path / "NoteStore.sqlite"
    conn = sqlite3.connect(bad)
    conn.execute("CREATE TABLE ZICCLOUDSYNCINGOBJECT (Z_PK INTEGER)")
    conn.execute("CREATE TABLE Z_METADATA (Z_UUID TEXT)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(notes_mod, "NOTESTORE", bad)
    monkeypatch.setattr(
        notes_mod, "run_osascript", lambda *a: "N-1\x1ffallback body\x1e"
    )
    out = NotesAdapter().get_bodies(["N-1"])
    assert out == [{"id": "N-1", "body": "fallback body"}]


def test_get_bodies_foreign_uuid_id_not_mis_attributed(notestore, monkeypatch):
    # a stale/foreign id whose pN collides with a local note must NOT get that local
    # note's body — the store UUID must match. Here AppleScript resolves nothing → the
    # foreign id is simply absent (never the local p3 body).
    monkeypatch.setattr(notes_mod, "run_osascript", lambda *a: "")
    out = NotesAdapter().get_bodies(["x-coredata://OTHER-UUID/ICNote/p3"])
    assert out == []  # not [{'…OTHER…/p3', 'Milk, eggs, bread — …'}]


def test_get_bodies_gap_fill_failure_keeps_sqlite_bodies(notestore, monkeypatch):
    # a gap-fill (AppleScript) failure must NOT discard bodies sqlite already decoded.
    from mac_mcp.runtime import AutomationDenied

    def boom(*a):
        raise AutomationDenied("Automation not granted")

    monkeypatch.setattr(notes_mod, "run_osascript", boom)
    # p3 decodes via sqlite (ZICNOTEDATA 99); p5 has no body row → gap-fill → raises →
    # suppressed, so p3 still comes back.
    out = NotesAdapter().get_bodies(
        [
            "x-coredata://STORE-UUID/ICNote/p3",
            "x-coredata://STORE-UUID/ICNote/p5",
        ]
    )
    assert out == [
        {
            "id": "x-coredata://STORE-UUID/ICNote/p3",
            "body": "Milk, eggs, bread — the full note body",
        }
    ]


def test_body_table_drift_keeps_enumeration_working(tmp_path, monkeypatch):
    # the body-table fingerprint is decoupled from the enumeration fingerprint (#60
    # review): dropping ZICNOTEDATA drifts get_bodies (→ AppleScript) but get_all keeps
    # working on sqlite.
    path = _make_notestore(tmp_path / "NoteStore.sqlite")
    conn = sqlite3.connect(path)
    conn.execute("DROP TABLE ZICNOTEDATA")
    conn.commit()
    conn.close()
    monkeypatch.setattr(notes_mod, "NOTESTORE", path)
    monkeypatch.setattr(notes_mod, "run_osascript", lambda *a: "")  # inert for get_all
    ids = {p.id for p in NotesAdapter().get_all()}  # sqlite still serves enumeration
    assert "x-coredata://STORE-UUID/ICNote/p3" in ids
    # get_bodies drifts (needs ZICNOTEDATA) → AppleScript fallback
    monkeypatch.setattr(
        notes_mod,
        "run_osascript",
        lambda *a: "x-coredata://STORE-UUID/ICNote/p3\x1ffallback body\x1e",
    )
    out = NotesAdapter().get_bodies(["x-coredata://STORE-UUID/ICNote/p3"])
    assert out == [{"id": "x-coredata://STORE-UUID/ICNote/p3", "body": "fallback body"}]
