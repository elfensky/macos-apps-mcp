"""reminders_store — tags and parent links from the Reminders store, read-only.

REM-03, REM-04, #91.

EventKit has no public tag or parent property (spike 002), so the only read route for
either is the Reminders sqlite store: a fingerprinted, read-only plane BESIDE the
EventKit plane. The two join on ``ZCKIDENTIFIER`` = EventKit ``calendarItemIdentifier``
(1372 of 1372 live reminders on the spike Mac, spike 007), so a Pointer id stays the
EventKit id. Needs **Full Disk Access**.

Imported only by ``reminders.py`` (the ``mail_index.py``-beside-``mail.py`` precedent).
Nothing here writes: the store is opened ``mode=ro`` by ``runtime.read_via_sqlite``,
and no public API writes a tag or a subtask link (D-16).
"""

from __future__ import annotations

import os
import sqlite3
from fnmatch import fnmatch
from pathlib import Path

from ..errors import PRIVACY_PANE, FullDiskAccessDenied, NativeError
from ..runtime import read_via_sqlite
from ..text import clean_summary

_STORES = (
    Path.home()
    / "Library/Group Containers/group.com.apple.reminders/Container_v1/Stores"
)

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
        "ZCKIDENTIFIER",
        "ZPARENTREMINDER",
        "ZMARKEDFORDELETION",
    },
}

# Both rows of a tag, and both ends of a parent link, must be live: Reminders keeps
# deleted rows with ZMARKEDFORDELETION = 1 (3 of 14 hashtag rows on the spike Mac).
_TAGS = """SELECT r.ZCKIDENTIFIER, h.ZNAME1 FROM ZREMCDOBJECT h
  JOIN ZREMCDREMINDER r ON r.Z_PK = h.ZREMINDER3
  WHERE h.Z_ENT = (SELECT Z_ENT FROM Z_PRIMARYKEY WHERE Z_NAME = 'REMCDHashtag')
    AND h.ZMARKEDFORDELETION = 0 AND r.ZMARKEDFORDELETION = 0"""
_PARENTS = """SELECT c.ZCKIDENTIFIER, p.ZCKIDENTIFIER FROM ZREMCDREMINDER c
  JOIN ZREMCDREMINDER p ON p.Z_PK = c.ZPARENTREMINDER
  WHERE c.ZMARKEDFORDELETION = 0 AND p.ZMARKEDFORDELETION = 0"""


def store_path() -> Path:
    """The live store: the largest ``Data-*.sqlite`` (the others are empty shells).

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
    if not sizes:
        raise NativeError(
            f"Reminders store not found under {_STORES} (Reminders may never have "
            "been used). This is not a Full Disk Access problem; do not retry."
        )
    return _STORES / max(sizes, key=sizes.__getitem__)


def tags_and_parents() -> tuple[dict[str, tuple[str, ...]], dict[str, str]]:
    """``({reminder id: sorted tags}, {child id: parent id})`` for every live reminder.

    Ids are EventKit ids. One read-only open, two queries, no fallback: a missing
    grant, a drifted schema or a store that fails mid-read raises its typed error
    (``FullDiskAccessDenied`` / ``SchemaDrift``) for the caller to name in
    ``coverage`` — never a partial answer presented as complete. Tag text is
    user-typed, so it passes through ``clean_summary`` before it nears a model.
    """

    def query(conn: sqlite3.Connection):
        tags: dict[str, set[str]] = {}
        for ident, name in conn.execute(_TAGS):
            if clean := clean_summary(name):
                tags.setdefault(ident, set()).add(clean)
        parents = dict(conn.execute(_PARENTS))
        return {i: tuple(sorted(t)) for i, t in tags.items()}, parents

    return read_via_sqlite(store_path(), _FINGERPRINT, query)
