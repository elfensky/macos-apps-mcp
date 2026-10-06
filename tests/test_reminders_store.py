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
from macos_apps_mcp.errors import SchemaDrift

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
