"""Unit tests for the Reminders store sidecar (REM-03, REM-04, #91).

A synthetic Core Data store built in ``tmp_path`` with only the fingerprint columns —
the real store is never opened (public repo, owner data). The tombstone rows are the
point: Reminders keeps deleted tags and reminders in the store with
``ZMARKEDFORDELETION = 1``, and a read that forgets the filter reports ghosts.
"""

from __future__ import annotations

import sqlite3

import pytest

from macos_apps_mcp.adapters import reminders_store
from macos_apps_mcp.errors import FullDiskAccessDenied, NativeError, SchemaDrift

_OBJECT_COLS = (
    "Z_ENT INTEGER, ZNAME1 TEXT, ZREMINDER3 INTEGER, ZMARKEDFORDELETION INTEGER"
)
_REMINDER_COLS = (
    "Z_PK INTEGER PRIMARY KEY, ZCKIDENTIFIER TEXT, ZPARENTREMINDER INTEGER, "
    "ZMARKEDFORDELETION INTEGER"
)


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
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE Z_PRIMARYKEY (Z_ENT INTEGER, Z_NAME TEXT)")
    conn.execute(f"CREATE TABLE ZREMCDOBJECT ({_OBJECT_COLS})")
    reminder_cols = _REMINDER_COLS
    if drop_parent_column:
        reminder_cols = reminder_cols.replace("ZPARENTREMINDER INTEGER, ", "")
    conn.execute(f"CREATE TABLE ZREMCDREMINDER ({reminder_cols})")
    conn.executemany(
        "INSERT INTO Z_PRIMARYKEY VALUES (?, ?)",
        [(hashtag_ent, "REMCDHashtag"), (reminder_ent, "REMCDReminder")],
    )
    reminders = [  # pk, ckid, parent pk, tombstone
        (1, "R1", None, 0),
        (2, "R2", 1, 0),
        (3, "R3", 4, 0),  # child of a tombstoned parent
        (4, "RP", None, 1),
        (5, "R4", None, 1),
    ]
    if drop_parent_column:
        conn.executemany(
            "INSERT INTO ZREMCDREMINDER VALUES (?, ?, ?)",
            [(pk, ck, dead) for pk, ck, _parent, dead in reminders],
        )
    else:
        conn.executemany("INSERT INTO ZREMCDREMINDER VALUES (?, ?, ?, ?)", reminders)
    live = tags if tags is not None else ["home", "Work"]
    objects = [(hashtag_ent, name, 1, 0) for name in live]
    objects += [
        (hashtag_ent, "old", 1, 1),  # tombstoned tag on a live reminder
        (hashtag_ent, "gone", 5, 0),  # live tag on a tombstoned reminder
        (reminder_ent, "notatag", 1, 0),  # another entity that points at R1
    ]
    conn.executemany("INSERT INTO ZREMCDOBJECT VALUES (?, ?, ?, ?)", objects)
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def store_file(tmp_path, monkeypatch):
    path = _make_reminders_store(tmp_path / "Data-live.sqlite")
    monkeypatch.setattr(reminders_store, "store_path", lambda: path)
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
    monkeypatch.setattr(reminders_store, "store_path", lambda: path)
    tags, _ = reminders_store.tags_and_parents()
    assert tags == {"R1": ("Work", "home")}


def test_a_store_missing_the_parent_column_is_schema_drift(tmp_path, monkeypatch):
    path = _make_reminders_store(
        tmp_path / "Data-drift.sqlite", drop_parent_column=True
    )
    monkeypatch.setattr(reminders_store, "store_path", lambda: path)
    with pytest.raises(SchemaDrift, match="ZPARENTREMINDER"):
        reminders_store.tags_and_parents()


def test_a_tag_reaches_the_caller_as_one_clean_line(tmp_path, monkeypatch):
    path = _make_reminders_store(
        tmp_path / "Data-dirty.sqlite", tags=["line one\nline\x07 two", "dup", "dup"]
    )
    monkeypatch.setattr(reminders_store, "store_path", lambda: path)
    tags, _ = reminders_store.tags_and_parents()
    assert tags == {"R1": ("dup", "line one line two")}


def _add_reminders(path, rows):
    """Append reminder rows ``(pk, ckid, parent pk, tombstone)`` to a built store."""
    conn = sqlite3.connect(path)
    conn.executemany("INSERT INTO ZREMCDREMINDER VALUES (?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()
    return path


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
    assert reminders_store.subtasks_of("absent") == []


def test_subtasks_of_a_tombstoned_parent_is_empty(store_file):
    # R3 is a child of the tombstoned RP: no live parent, so no link to report
    assert reminders_store.subtasks_of("RP") == []


def test_subtasks_of_binds_the_id_never_formats_it_into_the_sql(store_file):
    assert reminders_store.subtasks_of("R1' OR '1'='1") == []
    assert reminders_store.subtasks_of("R1") == ["R2"]


# --- store_path: the directory listing (RESEARCH Pitfall 5) ---------------------------


def test_store_path_picks_the_largest_data_file(tmp_path, monkeypatch):
    (tmp_path / "Data-a.sqlite").write_bytes(b"x" * 10)
    (tmp_path / "Data-b.sqlite").write_bytes(b"x" * 20)
    (tmp_path / "Data-c.sqlite-wal").write_bytes(b"x" * 99)  # not a store file
    monkeypatch.setattr(reminders_store, "_STORES", tmp_path)
    assert reminders_store.store_path() == tmp_path / "Data-b.sqlite"


def test_store_path_on_a_missing_directory_says_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr(reminders_store, "_STORES", tmp_path / "absent")
    with pytest.raises(NativeError, match="not found") as exc:
        reminders_store.store_path()
    assert not isinstance(exc.value, FullDiskAccessDenied)


def test_store_path_on_an_empty_directory_says_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr(reminders_store, "_STORES", tmp_path)
    with pytest.raises(NativeError, match="not found"):
        reminders_store.store_path()


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
            reminders_store.store_path()
    finally:
        locked.chmod(0o700)


def test_store_path_on_something_that_is_not_a_directory_stays_typed(
    tmp_path, monkeypatch
):
    # any other OSError (here ENOTDIR) must reach the adapter as a NativeError so
    # `reminders()` can name it in `coverage` instead of losing the EventKit pointers
    afile = tmp_path / "Stores"
    afile.write_bytes(b"x")
    monkeypatch.setattr(reminders_store, "_STORES", afile)
    with pytest.raises(NativeError, match="could not be listed"):
        reminders_store.store_path()
