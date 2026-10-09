"""Unit tests for the Reminders store sidecar (REM-03, REM-04, #91).

A synthetic Core Data store built in ``tmp_path`` with only the fingerprint columns —
the real store is never opened (public repo, owner data). The tombstone rows are the
point: Reminders keeps deleted tags and reminders in the store with
``ZMARKEDFORDELETION = 1``, and a read that forgets the filter reports ghosts. A row on
a Local (not iCloud) list has a NULL ``ZCKIDENTIFIER`` (#307).
"""

from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

import pytest

from macos_apps_mcp.adapters import reminders_store
from macos_apps_mcp.errors import FullDiskAccessDenied, NativeError, SchemaDrift

_OBJECT_COLS = (
    "Z_ENT INTEGER, ZNAME1 TEXT, ZREMINDER3 INTEGER, ZMARKEDFORDELETION INTEGER"
)
_REMINDER_COLS = (
    "Z_PK INTEGER PRIMARY KEY, ZCKIDENTIFIER TEXT, "
    "ZDACALENDARITEMUNIQUEIDENTIFIER TEXT, ZPARENTREMINDER INTEGER, "
    "ZMARKEDFORDELETION INTEGER"
)


def _add_reminders(path, rows, *, local=False):
    """Append rows ``(pk, EventKit id, parent pk, tombstone)`` to a built store.

    An iCloud row carries the id in both key columns; a Local row (``local=True``) has a
    NULL CloudKit id (#307). A ``None`` id is NULL in both."""
    conn = sqlite3.connect(path)
    conn.executemany(
        "INSERT INTO ZREMCDREMINDER (Z_PK, ZCKIDENTIFIER, "
        "ZDACALENDARITEMUNIQUEIDENTIFIER, ZPARENTREMINDER, ZMARKEDFORDELETION) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (pk, None if local else ek, ek, parent, dead)
            for pk, ek, parent, dead in rows
        ],
    )
    conn.commit()
    conn.close()
    return path


def _create_store(path, hashtag_ent=30, reminder_ent=31):
    """An empty store: the three fingerprint tables and the entity numbers."""
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE Z_PRIMARYKEY (Z_ENT INTEGER, Z_NAME TEXT)")
    conn.execute(f"CREATE TABLE ZREMCDOBJECT ({_OBJECT_COLS})")
    conn.execute(f"CREATE TABLE ZREMCDREMINDER ({_REMINDER_COLS})")
    conn.executemany(
        "INSERT INTO Z_PRIMARYKEY VALUES (?, ?)",
        [(hashtag_ent, "REMCDHashtag"), (reminder_ent, "REMCDReminder")],
    )
    conn.commit()
    conn.close()
    return path


def _make_reminders_store(
    path,
    *,
    hashtag_ent=30,
    reminder_ent=31,
    tags=None,
    drop_parent_column=False,
):
    """Reminders R1, R2 (child of R1), R3 (child of the tombstoned RP), R4 (tombstoned,
    tagged "gone"); live tags "home" and "Work" on R1, a tombstoned tag "old" on R1, and
    a non-hashtag object row that points at R1 (it must not read as a tag).

    ``tags`` replaces the live tag names on R1."""
    _create_store(path, hashtag_ent, reminder_ent)
    _add_reminders(
        path,
        [  # pk, EventKit id, parent pk, tombstone
            (1, "R1", None, 0),
            (2, "R2", 1, 0),
            (3, "R3", 4, 0),  # child of a tombstoned parent
            (4, "RP", None, 1),
            (5, "R4", None, 1),
        ],
    )
    conn = sqlite3.connect(path)
    live = tags if tags is not None else ["home", "Work"]
    objects = [(hashtag_ent, name, 1, 0) for name in live]
    objects += [
        (hashtag_ent, "old", 1, 1),  # tombstoned tag on a live reminder
        (hashtag_ent, "gone", 5, 0),  # live tag on a tombstoned reminder
        (reminder_ent, "notatag", 1, 0),  # another entity that points at R1
    ]
    conn.executemany("INSERT INTO ZREMCDOBJECT VALUES (?, ?, ?, ?)", objects)
    if drop_parent_column:
        conn.execute("ALTER TABLE ZREMCDREMINDER DROP COLUMN ZPARENTREMINDER")
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def store_file(tmp_path, monkeypatch):
    path = _make_reminders_store(tmp_path / "Data-live.sqlite")
    monkeypatch.setattr(reminders_store, "store_paths", lambda: [path])
    return path


def test_tags_and_parents_read_live_rows_only(store_file):
    tags, parents = reminders_store.tags_and_parents()
    assert tags == {"R1": ("Work", "home")}  # sorted; "old" and "gone" are tombstones
    assert parents == {"R2": "R1"}  # R3's parent is a tombstone: no link


def test_two_reads_of_one_store_are_equal(store_file):
    assert reminders_store.tags_and_parents() == reminders_store.tags_and_parents()


def test_entity_numbers_come_from_z_primarykey_not_a_constant(tmp_path, monkeypatch):
    path = _make_reminders_store(
        tmp_path / "Data-other.sqlite", hashtag_ent=7, reminder_ent=8
    )
    monkeypatch.setattr(reminders_store, "store_paths", lambda: [path])
    tags, _ = reminders_store.tags_and_parents()
    assert tags == {"R1": ("Work", "home")}


def test_a_store_missing_the_parent_column_is_schema_drift(tmp_path, monkeypatch):
    path = _make_reminders_store(
        tmp_path / "Data-drift.sqlite", drop_parent_column=True
    )
    monkeypatch.setattr(reminders_store, "store_paths", lambda: [path])
    with pytest.raises(SchemaDrift, match=r"missing column.*ZPARENTREMINDER"):
        reminders_store.tags_and_parents()


def test_a_tag_reaches_the_caller_as_one_clean_line(tmp_path, monkeypatch):
    path = _make_reminders_store(
        tmp_path / "Data-dirty.sqlite", tags=["line one\nline\x07 two", "dup", "dup"]
    )
    monkeypatch.setattr(reminders_store, "store_paths", lambda: [path])
    tags, _ = reminders_store.tags_and_parents()
    assert tags == {"R1": ("dup", "line one line two")}


def test_subtasks_of_lists_live_children_of_a_live_parent(store_file):
    _add_reminders(
        store_file,
        [
            (10, "P1", None, 0),
            (11, "C1", 10, 0),
            (12, "C2", 10, 0),
            (13, "C3", 10, 1),  # tombstoned child: not a subtask any more
        ],
    )
    assert reminders_store.subtasks_of("P1") == ["C1", "C2"]
    assert reminders_store.subtasks_of("R2") == []  # a leaf


def test_subtasks_of_a_parent_the_store_has_no_row_for_raises(store_file):
    # "[]" must mean "no subtasks", never "the store cannot see this reminder"
    with pytest.raises(NativeError, match="not in the Reminders store"):
        reminders_store.subtasks_of("absent")
    with pytest.raises(NativeError, match="not in the Reminders store"):
        reminders_store.subtasks_of("RP")  # tombstoned: no live row either


def test_a_null_id_row_is_never_a_subtask_parent_or_tag_owner(store_file):
    _add_reminders(
        store_file,
        [(10, "P1", None, 0), (11, None, 10, 0), (12, "C2", 10, 0)],
    )
    conn = sqlite3.connect(store_file)
    conn.execute("INSERT INTO ZREMCDOBJECT VALUES (30, 'ghost', 11, 0)")
    conn.commit()
    conn.close()
    assert reminders_store.subtasks_of("P1") == ["C2"]
    tags, parents = reminders_store.tags_and_parents()
    assert parents == {"R2": "R1", "C2": "P1"}  # no None key
    assert None not in tags


def test_live_ids_are_the_live_non_null_rows(store_file):
    _add_reminders(store_file, [(10, None, None, 0)])
    assert reminders_store.live_ids() == {"R1", "R2", "R3"}


# --- Local-list rows: ZCKIDENTIFIER is NULL, the EventKit id is in the other column ---


def test_a_local_list_row_is_live(store_file):
    # #307: a Local row has a NULL CloudKit id; it was invisible to live_ids()
    _add_reminders(store_file, [(10, "L1", None, 0), (11, "L2", None, 1)], local=True)
    assert reminders_store.live_ids() == {"R1", "R2", "R3", "L1"}


def test_subtasks_of_a_local_list_parent(store_file):
    # #307
    _add_reminders(
        store_file,
        [
            (10, "LP", None, 0),
            (11, "LC1", 10, 0),
            (12, "LC2", 10, 0),
            (13, "LC3", 10, 1),
        ],
        local=True,
    )
    assert reminders_store.subtasks_of("LP") == ["LC1", "LC2"]


def test_a_local_list_reminder_has_its_tag_and_parent(store_file):
    # #307
    _add_reminders(store_file, [(10, "LP", None, 0), (11, "LC", 10, 0)], local=True)
    conn = sqlite3.connect(store_file)
    conn.execute("INSERT INTO ZREMCDOBJECT VALUES (30, 'errand', 11, 0)")
    conn.commit()
    conn.close()
    tags, parents = reminders_store.tags_and_parents()
    assert tags["LC"] == ("errand",)
    assert parents["LC"] == "LP"
    assert tags["R1"] == ("Work", "home")
    assert parents["R2"] == "R1"


def test_a_store_missing_the_eventkit_id_column_is_schema_drift(store_file):
    conn = sqlite3.connect(store_file)
    conn.execute(
        "ALTER TABLE ZREMCDREMINDER DROP COLUMN ZDACALENDARITEMUNIQUEIDENTIFIER"
    )
    conn.commit()
    conn.close()
    with pytest.raises(
        SchemaDrift, match=r"missing column.*ZDACALENDARITEMUNIQUEIDENTIFIER"
    ):
        reminders_store.tags_and_parents()


def test_a_cloudkit_only_row_fails_closed(store_file):
    # #307: a NULL EventKit-id column is never live; subtasks_of refuses, not "[]"
    conn = sqlite3.connect(store_file)
    conn.execute(
        "INSERT INTO ZREMCDREMINDER (Z_PK, ZCKIDENTIFIER, "
        "ZDACALENDARITEMUNIQUEIDENTIFIER, ZPARENTREMINDER, ZMARKEDFORDELETION) "
        "VALUES (10, 'CK-ONLY', NULL, NULL, 0)"
    )
    conn.commit()
    conn.close()
    assert "CK-ONLY" not in reminders_store.live_ids()
    with pytest.raises(NativeError, match="not in the Reminders store"):
        reminders_store.subtasks_of("CK-ONLY")


def test_subtasks_of_binds_the_id_never_formats_it_into_the_sql(store_file):
    # bound, so the quote is part of an id that matches no row (never an OR-true)
    with pytest.raises(NativeError, match="not in the Reminders store"):
        reminders_store.subtasks_of("R1' OR '1'='1")
    assert reminders_store.subtasks_of("R1") == ["R2"]


# --- One store file per account: every file with a Reminders table is read (#307) ----


@pytest.fixture
def two_stores(tmp_path, monkeypatch):
    """A big iCloud store and a smaller Local-account store, found by listing."""
    big = _make_reminders_store(tmp_path / "Data-icloud.sqlite")
    # tombstones with no id: they change no answer, but make this the largest file
    _add_reminders(big, [(100 + i, None, None, 1) for i in range(400)])
    small = _create_store(tmp_path / "Data-local.sqlite")
    _add_reminders(
        small, [(1, "LP", None, 0), (2, "LC", 1, 0), (3, "LC2", 1, 0)], local=True
    )
    conn = sqlite3.connect(small)
    conn.execute("INSERT INTO ZREMCDOBJECT VALUES (30, 'errand', 2, 0)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(reminders_store, "_STORES", tmp_path)
    return small


def test_live_ids_are_the_union_over_every_store_file(two_stores):
    assert reminders_store.live_ids() == {"R1", "R2", "R3", "LP", "LC", "LC2"}


def test_tags_and_parents_merge_every_store_file(two_stores):
    tags, parents = reminders_store.tags_and_parents()
    assert tags == {"R1": ("Work", "home"), "LC": ("errand",)}
    assert parents == {"R2": "R1", "LC": "LP", "LC2": "LP"}


def test_subtasks_of_asks_the_store_file_that_has_the_parent(two_stores):
    assert reminders_store.subtasks_of("LP") == ["LC", "LC2"]  # the smaller file
    assert reminders_store.subtasks_of("R1") == ["R2"]  # the larger file
    with pytest.raises(NativeError, match="not in the Reminders store"):
        reminders_store.subtasks_of("absent")  # in no file: still refused


def test_a_drifted_store_file_fails_the_whole_read(two_stores):
    conn = sqlite3.connect(two_stores)
    conn.execute("ALTER TABLE ZREMCDREMINDER DROP COLUMN ZPARENTREMINDER")
    conn.commit()
    conn.close()
    with pytest.raises(SchemaDrift, match=r"missing column.*ZPARENTREMINDER"):
        reminders_store.live_ids()


def test_a_shell_file_beside_a_real_store_is_skipped(two_stores, tmp_path):
    shell = sqlite3.connect(tmp_path / "Data-shell.sqlite")
    shell.execute("CREATE TABLE ZSOMETHINGELSE (x INTEGER)")
    shell.commit()
    shell.close()
    assert reminders_store.live_ids() == {"R1", "R2", "R3", "LP", "LC", "LC2"}


def test_a_directory_of_only_shell_files_is_schema_drift(tmp_path, monkeypatch):
    shell = sqlite3.connect(tmp_path / "Data-shell.sqlite")
    shell.execute("CREATE TABLE ZSOMETHINGELSE (x INTEGER)")
    shell.commit()
    shell.close()
    monkeypatch.setattr(reminders_store, "_STORES", tmp_path)
    with pytest.raises(SchemaDrift, match="ZREMCDREMINDER"):
        reminders_store.live_ids()


# --- store_paths: the directory listing (RESEARCH Pitfall 5) ---------------------


def test_store_paths_lists_every_data_file_largest_first(tmp_path, monkeypatch):
    # sizes 10, 20 and a tie at 20: size descending, then name (deterministic, #307)
    (tmp_path / "Data-a.sqlite").write_bytes(b"x" * 10)
    (tmp_path / "Data-c.sqlite").write_bytes(b"x" * 20)
    (tmp_path / "Data-b.sqlite").write_bytes(b"x" * 20)
    (tmp_path / "Data-d.sqlite-wal").write_bytes(b"x" * 99)  # not a store file
    monkeypatch.setattr(reminders_store, "_STORES", tmp_path)
    assert reminders_store.store_paths() == [
        tmp_path / "Data-b.sqlite",
        tmp_path / "Data-c.sqlite",
        tmp_path / "Data-a.sqlite",
    ]


def test_store_paths_on_a_missing_directory_says_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr(reminders_store, "_STORES", tmp_path / "absent")
    with pytest.raises(NativeError, match="not found") as exc:
        reminders_store.store_paths()
    assert not isinstance(exc.value, FullDiskAccessDenied)


def test_store_paths_on_an_empty_directory_says_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr(reminders_store, "_STORES", tmp_path)
    with pytest.raises(NativeError, match="not found"):
        reminders_store.store_paths()


def test_an_unreadable_directory_is_a_full_disk_access_denial_not_not_found(
    tmp_path, monkeypatch
):
    # Path.glob would return [] here and read as "store not found": a denied grant
    # must stay a denied grant.
    locked = tmp_path / "Stores"
    locked.mkdir()
    (locked / "Data-a.sqlite").write_bytes(b"x")
    locked.chmod(0o000)
    try:
        monkeypatch.setattr(reminders_store, "_STORES", locked)
        with pytest.raises(FullDiskAccessDenied, match="Full Disk Access"):
            reminders_store.store_paths()
    finally:
        locked.chmod(0o700)


def test_store_paths_on_something_that_is_not_a_directory_stays_typed(
    tmp_path, monkeypatch
):
    # any other OSError (here ENOTDIR) must reach the adapter as a NativeError so
    # `reminders()` can name it in `coverage` instead of losing the EventKit pointers
    afile = tmp_path / "Stores"
    afile.write_bytes(b"x")
    monkeypatch.setattr(reminders_store, "_STORES", afile)
    with pytest.raises(NativeError, match="could not be listed"):
        reminders_store.store_paths()


# REM-04 / D-16: tags and subtasks are read-only; Apple's private selectors that could
# write them are never referenced (exact names, so a docstring naming them is fine).
_PRIVATE_SELECTORS = {
    "parentID",
    "setParentID_",
    "setParentID",
    "setParentID:",
    "parentReminder",
    "setParentReminder_",
}


def _private_selectors(source: str) -> list[str]:
    return [
        name
        for node in ast.walk(ast.parse(source))
        for name in (
            node.attr if isinstance(node, ast.Attribute) else None,
            node.value if isinstance(node, ast.Constant) else None,
        )
        if isinstance(name, str) and name in _PRIVATE_SELECTORS
    ]


@pytest.mark.parametrize(
    "source", ["store.setParentID_(child)", 'getattr(r, "parentReminder")']
)
def test_the_private_selector_scan_bites(source):
    assert _private_selectors(source)


def test_the_package_never_references_a_private_subtask_selector():
    root = Path(__file__).resolve().parent.parent
    offenders = {
        str(path.relative_to(root)): found
        for path in (root / "macos_apps_mcp").rglob("*.py")
        if (found := _private_selectors(path.read_text()))
    }
    assert offenders == {}
