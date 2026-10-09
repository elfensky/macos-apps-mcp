"""reminders_store — tags and parent links from the Reminders store, read-only.

REM-03, REM-04, #91.

EventKit has no public tag or parent property (spike 002), so the only read route for
either is the Reminders sqlite store: a fingerprinted, read-only plane BESIDE the
EventKit plane. The two join on ``ZDACALENDARITEMUNIQUEIDENTIFIER`` = EventKit
``calendarItemIdentifier`` (1371 of 1371 live reminders on an iCloud store, 2026-10-09,
with no NULL and no duplicate), so a Pointer id stays the EventKit id.
``ZCKIDENTIFIER`` is the CloudKit record id and is NULL on a Local list (#307). Parent
links use the Core Data key ``ZPARENTREMINDER`` -> ``Z_PK``, so they need no CloudKit
id. Reminders keeps ONE store file per account, so every file with a Reminders table
is read (#307). Needs **Full Disk Access**.

Imported only by ``reminders.py`` (the ``mail_index.py``-beside-``mail.py`` precedent).
Nothing here writes: the store is opened ``mode=ro`` by ``runtime.read_via_sqlite``,
and no public API writes a tag or a subtask link (D-16).
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable
from fnmatch import fnmatch
from pathlib import Path
from typing import TypeVar

from ..errors import PRIVACY_PANE, FullDiskAccessDenied, NativeError, SchemaDrift
from ..runtime import read_via_sqlite
from ..text import clean_summary

T = TypeVar("T")

_STORES = (
    Path.home()
    / "Library/Group Containers/group.com.apple.reminders/Container_v1/Stores"
)

# The EventKit id on every row, iCloud and Local alike; the CloudKit id is NULL on a
# Local list (#307). The one key column of every query below.
_EK_ID = "ZDACALENDARITEMUNIQUEIDENTIFIER"

# Core Data table.column names move with macOS releases; a mismatch trips SchemaDrift,
# which `reminders()` reports in `coverage` (D-13) rather than mis-reading the store.
_FINGERPRINT = {
    # entity numbers are looked up by name at run time, never hardcoded
    "Z_PRIMARYKEY": {"Z_ENT", "Z_NAME"},
    # hashtag rows: the tag text is ZNAME1 (inheritance suffix), the owner ZREMINDER3
    "ZREMCDOBJECT": {"Z_ENT", "ZNAME1", "ZREMINDER3", "ZMARKEDFORDELETION"},
    # reminder rows: the EventKit id, and the parent link
    "ZREMCDREMINDER": {
        "Z_PK",
        _EK_ID,
        "ZPARENTREMINDER",
        "ZMARKEDFORDELETION",
    },
}

# Both rows of a tag, and both ends of a parent link, must be live: Reminders keeps
# deleted rows with ZMARKEDFORDELETION = 1 (3 of 14 hashtag rows on the spike Mac).
_TAGS = f"""SELECT r.{_EK_ID}, h.ZNAME1 FROM ZREMCDOBJECT h
  JOIN ZREMCDREMINDER r ON r.Z_PK = h.ZREMINDER3
  WHERE h.Z_ENT = (SELECT Z_ENT FROM Z_PRIMARYKEY WHERE Z_NAME = 'REMCDHashtag')
    AND h.ZMARKEDFORDELETION = 0 AND r.ZMARKEDFORDELETION = 0
    AND r.{_EK_ID} IS NOT NULL"""
_PARENTS = f"""SELECT c.{_EK_ID}, p.{_EK_ID} FROM ZREMCDREMINDER c
  JOIN ZREMCDREMINDER p ON p.Z_PK = c.ZPARENTREMINDER
  WHERE c.ZMARKEDFORDELETION = 0 AND p.ZMARKEDFORDELETION = 0
    AND c.{_EK_ID} IS NOT NULL AND p.{_EK_ID} IS NOT NULL"""
# A parent's live children, in creation order. The id is a bound parameter, never
# formatted in: it is a model-chosen string (D-18).
_SUBTASKS_OF = f"""SELECT c.{_EK_ID} FROM ZREMCDREMINDER c
  JOIN ZREMCDREMINDER p ON p.Z_PK = c.ZPARENTREMINDER
  WHERE p.{_EK_ID} = ? AND c.ZMARKEDFORDELETION = 0
    AND p.ZMARKEDFORDELETION = 0 AND c.{_EK_ID} IS NOT NULL
  ORDER BY c.Z_PK"""
# Is the reminder in the store at all? (a bound parameter, like _SUBTASKS_OF)
_LIVE_ROW = (
    f"SELECT 1 FROM ZREMCDREMINDER WHERE {_EK_ID} = ? AND ZMARKEDFORDELETION = 0"
)
# A store file can lack the Reminders tables (the #307 rig's Data-local.sqlite had no
# ZREMCDBASELIST); _read_all skips a file without ZREMCDREMINDER.
_HAS_TABLE = (
    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'ZREMCDREMINDER'"
)
_LIVE_IDS = (
    f"SELECT {_EK_ID} FROM ZREMCDREMINDER "
    f"WHERE ZMARKEDFORDELETION = 0 AND {_EK_ID} IS NOT NULL"
)


def store_paths() -> list[Path]:
    """Every ``Data-*.sqlite``, largest first, ties by name (deterministic).

    Reminders keeps one store file per account, so a Mac with an iCloud and a Local
    account holds its Local reminders in a smaller file (#307). A file without the
    Reminders table is skipped by ``_read_all``.

    Lists the directory with ``os.scandir``, NOT ``Path.glob``: glob swallows a
    ``PermissionError`` into an empty result, which would report a missing Full Disk
    Access grant as "store not found" (RESEARCH Pitfall 5). Tests patch this function.
    """
    try:
        with os.scandir(_STORES) as entries:
            found = [
                e for e in entries if fnmatch(e.name, "Data-*.sqlite") and e.is_file()
            ]
            sizes = {e.name: e.stat().st_size for e in found}
    except PermissionError as e:
        raise FullDiskAccessDenied(
            "macos-apps-mcp could not list the Reminders store — Full Disk Access is "
            f"not granted. Grant it in {PRIVACY_PANE} → Full Disk Access to the app "
            "that launched macos-apps-mcp, then restart macos-apps-mcp. Do not retry "
            "until the next user message."
        ) from e
    except FileNotFoundError:
        sizes = {}
    except OSError as e:  # ENOTDIR, EIO … stay typed: never a raw error past `read()`
        raise NativeError(
            f"the Reminders store directory {_STORES} could not be listed: {e}. "
            "Do not retry."
        ) from e
    if not sizes:
        raise NativeError(
            f"Reminders store not found under {_STORES} (Reminders may never have "
            "been used). This is not a Full Disk Access problem; do not retry."
        )
    return [_STORES / name for name in sorted(sizes, key=lambda n: (-sizes[n], n))]


def _read_all(query: Callable[[sqlite3.Connection], T]) -> list[T]:
    """``query`` against every store file that has the Reminders table, in order.

    A file without ``ZREMCDREMINDER`` is an account shell and is skipped; if no file has
    it, that is ``SchemaDrift``, never an empty answer. A file that has the table but
    fails ``_FINGERPRINT`` raises for the whole read: no partial answer.
    """
    kept = [
        path
        for path in store_paths()
        if read_via_sqlite(path, {}, lambda c: c.execute(_HAS_TABLE).fetchone())
    ]
    if not kept:
        raise SchemaDrift(
            f"no store file under {_STORES} has the table 'ZREMCDREMINDER' — macOS "
            "likely changed the schema. Do not trust a sqlite result until the "
            "fingerprint is updated."
        )
    return [read_via_sqlite(path, _FINGERPRINT, query) for path in kept]


def tags_and_parents() -> tuple[dict[str, tuple[str, ...]], dict[str, str]]:
    """``({reminder id: sorted tags}, {child id: parent id})`` for every live reminder.

    Ids are EventKit ids; the answers of all store files are merged. One read-only
    open per file, no fallback: a missing grant, a drifted schema or a store that fails
    mid-read raises its typed error (``FullDiskAccessDenied`` / ``SchemaDrift``) for
    the caller to name in ``coverage`` — never a partial answer presented as complete.
    Tag text is user-typed, so it passes through ``clean_summary`` before it nears a
    model.
    """

    def query(conn: sqlite3.Connection):
        tags: dict[str, set[str]] = {}
        for ident, name in conn.execute(_TAGS):
            if clean := clean_summary(name):
                tags.setdefault(ident, set()).add(clean)
        return tags, dict(conn.execute(_PARENTS))

    tags: dict[str, set[str]] = {}
    parents: dict[str, str] = {}
    for file_tags, file_parents in _read_all(query):
        for ident, names in file_tags.items():
            tags.setdefault(ident, set()).update(names)
        parents.update(file_parents)
    return {i: tuple(sorted(t)) for i, t in tags.items()}, parents


def live_ids() -> set[str]:
    """The ids of every live reminder row — what ``read`` checks its EventKit pointers
    against, so a store that does not know them (a wrong file, not synced) is named."""

    def query(conn: sqlite3.Connection):
        return {ident for (ident,) in conn.execute(_LIVE_IDS)}

    return set().union(*_read_all(query))


def subtasks_of(parent_id: str) -> list[str]:
    """The EventKit ids of ``parent_id``'s live subtasks, in creation order.

    The delete's guard (D-18): EventKit cannot see subtasks and removes them with the
    parent, so the store is the only witness of what a delete takes. A typed store error
    (``FullDiskAccessDenied`` / ``SchemaDrift``) propagates — the caller refuses rather
    than delete blind. So does a parent that no store file has a live row for: ``[]``
    must mean "no subtasks", never "the store cannot see this reminder" (a wrong store
    file, a NULL join key, a reminder not synced yet). Runs inline when already on the
    worker, so one ``run_native`` block can read here and then act through EventKit.
    """

    def query(conn: sqlite3.Connection):
        # Device, 2026-10-06 (3 of 3): a reminder created through EventKit is in the
        # store within 0.00-0.05 s and gone from it within 0.01 s of a delete — so a
        # missing row is refused at once, with no wait loop.
        if conn.execute(_LIVE_ROW, (parent_id,)).fetchone() is None:
            return None
        return [ident for (ident,) in conn.execute(_SUBTASKS_OF, (parent_id,))]

    for children in _read_all(query):
        if children is not None:
            return children
    raise NativeError(
        f"reminder {parent_id!r} is not in the Reminders store (not synced "
        "yet, or a different store file), so its subtasks cannot be seen. "
        "Re-read with `reminders`, then retry."
    )
