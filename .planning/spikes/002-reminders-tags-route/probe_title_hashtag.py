"""Spike 002 — does a public EventKit write with "#tag" text create a real tag?

Writes: one scratch list `gsd-spike-002` with one reminder, both removed at the end.
Polls the sqlite store for a REMCDHashtag row on the new reminder.

    uv run python .planning/spikes/002-reminders-tags-route/probe_title_hashtag.py
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import EventKit as EK

STORES = Path.home() / "Library/Group Containers/group.com.apple.reminders"
TAG = "gsdspike002"


def store_db() -> sqlite3.Connection:
    dbs = (STORES / "Container_v1/Stores").glob("Data-*.sqlite")
    best = max(dbs, key=lambda p: p.stat().st_size)
    return sqlite3.connect(f"file:{best}?mode=ro", uri=True)


def tag_rows(ident: str) -> tuple[int, int]:
    """(rows in store for the reminder, live hashtag rows on it)."""
    db = store_db()
    try:
        ent = db.execute(
            "select Z_ENT from Z_PRIMARYKEY where Z_NAME='REMCDHashtag'"
        ).fetchone()[0]
        (seen,) = db.execute(
            "select count(*) from ZREMCDREMINDER where ZCKIDENTIFIER=?", (ident,)
        ).fetchone()
        (tags,) = db.execute(
            "select count(*) from ZREMCDOBJECT h join ZREMCDREMINDER r "
            "on r.Z_PK = h.ZREMINDER3 where h.Z_ENT=? and r.ZCKIDENTIFIER=? "
            "and h.ZMARKEDFORDELETION = 0",
            (ent, ident),
        ).fetchone()
        return seen, tags
    finally:
        db.close()


def main() -> None:
    store = EK.EKEventStore.alloc().init()
    src = store.defaultCalendarForNewReminders().source()
    cal = EK.EKCalendar.calendarForEntityType_eventStore_(
        EK.EKEntityTypeReminder, store
    )
    cal.setTitle_("gsd-spike-002")
    cal.setSource_(src)
    ok, err = store.saveCalendar_commit_error_(cal, True, None)
    assert ok, err
    try:
        r = EK.EKReminder.reminderWithEventStore_(store)
        r.setTitle_(f"spike probe #{TAG}")
        r.setNotes_(f"note body #{TAG}")
        r.setCalendar_(cal)
        ok, err = store.saveReminder_commit_error_(r, True, None)
        assert ok, err
        ident = str(r.calendarItemIdentifier())
        t0 = time.monotonic()
        seen = tags = 0
        while time.monotonic() - t0 < 30:
            seen, tags = tag_rows(ident)
            if seen and tags:
                break
            time.sleep(1)
        waited = time.monotonic() - t0
        print(
            f"reminder row in store: {bool(seen)}; hashtag rows: {tags} "
            f"(polled {waited:.0f}s)"
        )
        print("title read back via EK:", r.title() == f"spike probe #{TAG}")
    finally:
        ok, err = store.removeCalendar_commit_error_(cal, True, None)
        print("scratch list removed:", ok, err or "")


if __name__ == "__main__":
    main()
