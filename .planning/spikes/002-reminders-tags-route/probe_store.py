"""Spike 002 — can Reminders tags be read from the sqlite store and joined to EK ids?

Read-only. Prints aggregates only (counts, column names, match rates) — never a tag
name, title or id, because this repo is public.

    uv run python .planning/spikes/002-reminders-tags-route/probe_store.py
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from pathlib import Path

import EventKit as EK

STORES = Path.home() / "Library/Group Containers/group.com.apple.reminders/Container_v1"
STORES = STORES / "Stores"


def open_store() -> sqlite3.Connection:
    # The live store is the one with reminders in it; the others are empty shells.
    best = max(STORES.glob("Data-*.sqlite"), key=lambda p: p.stat().st_size)
    print(f"store: {best.name} ({best.stat().st_size // 1024} KiB)")
    return sqlite3.connect(f"file:{best}?mode=ro", uri=True)


def ek_reminder_ids() -> set[str]:
    store = EK.EKEventStore.alloc().init()
    pred = store.predicateForRemindersInCalendars_(None)
    done = threading.Event()
    out: list[str] = []

    def got(items):
        out.extend(str(r.calendarItemIdentifier()) for r in items or [])
        done.set()

    store.fetchRemindersMatchingPredicate_completion_(pred, got)
    if not done.wait(60):
        raise TimeoutError("EventKit reminder fetch did not complete in 60s")
    return set(out)


def main() -> None:
    db = open_store()
    q = lambda sql, *a: db.execute(sql, a).fetchall()  # noqa: E731
    e = {
        n: q("select Z_ENT from Z_PRIMARYKEY where Z_NAME=?", n)[0][0]
        for n in ("REMCDHashtag", "REMCDReminder")
    }

    live = "ZMARKEDFORDELETION = 0"
    n_rem = q(f"select count(*) from ZREMCDREMINDER where {live}")[0][0]
    n_lab = q("select count(*) from ZREMCDHASHTAGLABEL")[0][0]
    n_tag = q("select count(*) from ZREMCDOBJECT where Z_ENT=?", e["REMCDHashtag"])[0][
        0
    ]
    print(f"live reminders: {n_rem}  hashtag labels: {n_lab}  hashtag rows: {n_tag}")

    # Which ZREMCDOBJECT columns are populated on hashtag rows? (schema, not data)
    cols = [r[1] for r in q("pragma table_info(ZREMCDOBJECT)")]
    counts = q(
        "select "
        + ",".join(f"count({c})" for c in cols)
        + " from ZREMCDOBJECT where Z_ENT=?",
        e["REMCDHashtag"],
    )[0]
    filled = [c for c, n in zip(cols, counts, strict=True) if n]
    print("hashtag-row populated columns:", " ".join(filled))

    # Join: hashtag → reminder (by Z_PK) → label. Try every populated FK-ish column.
    for fk in [c for c in filled if c.startswith("ZREMINDER")]:
        hit = q(
            f"select count(*) from ZREMCDOBJECT h join ZREMCDREMINDER r "
            f"on r.Z_PK = h.{fk} where h.Z_ENT=?",
            e["REMCDHashtag"],
        )[0][0]
        print(f"  hashtag.{fk} -> ZREMCDREMINDER.Z_PK joins: {hit}/{n_tag}")
    # The tag text lives in ZNAME1; ZHASHTAGLABEL is the FK to the label table.
    lab_fk, lab_name = q(
        "select sum(l.Z_PK is not null), sum(l.ZNAME = h.ZNAME1) from ZREMCDOBJECT h "
        "left join ZREMCDHASHTAGLABEL l on l.Z_PK = h.ZHASHTAGLABEL where h.Z_ENT=?",
        e["REMCDHashtag"],
    )[0]
    print(
        f"  hashtag.ZHASHTAGLABEL -> label joins: {lab_fk}/{n_tag}, "
        f"ZNAME1 == label.ZNAME: {lab_name}/{n_tag}"
    )

    # Classify every hashtag row: live tag on a live reminder, or why not.
    for state, n in q(
        "select case when h.ZMARKEDFORDELETION = 1 then 'hashtag marked deleted' "
        "when r.Z_PK is null then 'reminder row missing' "
        "when r.ZMARKEDFORDELETION = 1 then 'reminder marked deleted' "
        "else 'live' end s, count(*) from ZREMCDOBJECT h "
        "left join ZREMCDREMINDER r on r.Z_PK = h.ZREMINDER3 "
        "where h.Z_ENT=? group by s",
        e["REMCDHashtag"],
    ):
        print(f"  hashtag rows [{state}]: {n}")

    tagged = q(
        "select count(distinct h.ZREMINDER3) from ZREMCDOBJECT h join ZREMCDREMINDER r "
        "on r.Z_PK = h.ZREMINDER3 where h.Z_ENT=? and h.ZMARKEDFORDELETION = 0 "
        f"and r.{live}",
        e["REMCDHashtag"],
    )[0][0]
    print(f"live reminders carrying >=1 live tag: {tagged}")

    n_child = q(
        f"select count(*) from ZREMCDREMINDER where {live} "
        "and ZPARENTREMINDER is not null"
    )[0][0]
    print(f"live reminders with a parent (subtasks): {n_child}")

    # Does any store id column equal EventKit's calendarItemIdentifier?
    ek = ek_reminder_ids()
    print(f"EventKit reminders: {len(ek)}")
    rows = q(
        f"select ZIDENTIFIER, ZCKIDENTIFIER, ZDACALENDARITEMUNIQUEIDENTIFIER, "
        f"ZEXTERNALIDENTIFIER from ZREMCDREMINDER where {live}"
    )
    cand = {
        "ZIDENTIFIER(blob→uuid)": [
            str(uuid.UUID(bytes=bytes(r[0]))).upper() if r[0] else None for r in rows
        ],
        "ZCKIDENTIFIER": [r[1] for r in rows],
        "ZDACALENDARITEMUNIQUEIDENTIFIER": [r[2] for r in rows],
        "ZEXTERNALIDENTIFIER": [r[3] for r in rows],
    }
    for name, vals in cand.items():
        m = sum(1 for v in vals if v and (v in ek or v.upper() in ek))
        print(f"  {name} == EK calendarItemIdentifier: {m}/{len(rows)}")

    # Subtask read: child -> parent row -> parent's EK id. Both ends must be in EK.
    pairs = q(
        "select c.ZCKIDENTIFIER, p.ZCKIDENTIFIER, p.ZMARKEDFORDELETION "
        "from ZREMCDREMINDER c left join ZREMCDREMINDER p "
        "on p.Z_PK = c.ZPARENTREMINDER "
        f"where c.{live} and c.ZPARENTREMINDER is not null"
    )
    both = sum(1 for c, p, _ in pairs if c in ek and p in ek)
    dead = sum(1 for _, p, d in pairs if p is None or d)
    print(
        f"subtask -> parent, both ids in EK: {both}/{len(pairs)}; "
        f"parent missing or deleted: {dead}"
    )


if __name__ == "__main__":
    main()
