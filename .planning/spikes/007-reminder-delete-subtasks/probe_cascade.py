"""Spike 007 — what happens to subtasks when EventKit removes or completes a parent?

EventKit cannot make a subtask (spike 002), so a human builds the fixture:

    uv run python .planning/spikes/007-reminder-delete-subtasks/probe_cascade.py setup
    # Reminders.app, list "gsd-spike-007": indent A.1 and A.2 under A (select, ⌘]),
    # and the same for B and C.
    uv run python .planning/spikes/007-reminder-delete-subtasks/probe_cascade.py run

`run` checks the parent links in the Reminders sqlite store, then over 60 s watches both
planes after each act:  A — EventKit removes the parent;  B — EventKit removes one
child;  C — EventKit completes that child's parent (B), whose other child remains.
It removes the scratch list at the end.
Only the probe's own reminders are read (by EventKit id = ZCKIDENTIFIER, spike 002).
"""

from __future__ import annotations

import json
import sqlite3
import sys
import threading
import time
from pathlib import Path

import EventKit as EK

HERE = Path(__file__).parent
LIST = "gsd-spike-007"
TITLES = ["A", "A.1", "A.2", "B", "B.1", "B.2", "C", "C.1", "C.2"]
STORES = Path.home() / "Library/Group Containers/group.com.apple.reminders"
STORES = STORES / "Container_v1/Stores"
WATCH = 60


def db() -> sqlite3.Connection:
    best = max(STORES.glob("Data-*.sqlite"), key=lambda p: p.stat().st_size)
    return sqlite3.connect(f"file:{best}?mode=ro", uri=True)


def row(ident: str) -> dict | None:
    """The store's view of one reminder: deleted, completed, parent EK id."""
    c = db()
    try:
        r = c.execute(
            "select r.ZMARKEDFORDELETION, r.ZCOMPLETED, p.ZCKIDENTIFIER "
            "from ZREMCDREMINDER r left join ZREMCDREMINDER p "
            "on p.Z_PK = r.ZPARENTREMINDER where r.ZCKIDENTIFIER = ?",
            (ident,),
        ).fetchone()
    finally:
        c.close()
    return r and {"deleted": r[0], "completed": r[1], "parent": r[2]}


def scratch_list(store) -> EK.EKCalendar | None:
    for cal in store.calendarsForEntityType_(EK.EKEntityTypeReminder):
        if cal.title() == LIST:
            return cal
    return None


def ek_items(store, cal) -> dict[str, EK.EKReminder]:
    """Title -> reminder, completed ones included (the C act completes one)."""
    done = threading.Event()
    out: dict[str, EK.EKReminder] = {}

    def got(items):
        out.update({str(r.title()): r for r in items or []})
        done.set()

    pred = store.predicateForRemindersInCalendars_([cal])
    store.fetchRemindersMatchingPredicate_completion_(pred, got)
    if not done.wait(60):
        raise TimeoutError("EventKit reminder fetch did not complete in 60s")
    return out


def ek_alive(store, ident: str) -> dict | None:
    store.refreshSourcesIfNecessary()
    r = store.calendarItemWithIdentifier_(ident)
    return r and {"completed": bool(r.isCompleted())}


def setup() -> None:
    store = EK.EKEventStore.alloc().init()
    if scratch_list(store):
        sys.exit(f"{LIST} already exists; run `run` or remove it first")
    cal = EK.EKCalendar.calendarForEntityType_eventStore_(
        EK.EKEntityTypeReminder, store
    )
    cal.setTitle_(LIST)
    cal.setSource_(store.defaultCalendarForNewReminders().source())
    ok, err = store.saveCalendar_commit_error_(cal, True, None)
    assert ok, err
    for t in TITLES:
        r = EK.EKReminder.reminderWithEventStore_(store)
        r.setTitle_(t)
        r.setCalendar_(cal)
        ok, err = store.saveReminder_commit_error_(r, True, None)
        assert ok, err
    print(f"created list {LIST} with {len(TITLES)} reminders")
    print("now indent A.1+A.2 under A, B.1+B.2 under B, C.1+C.2 under C (⌘])")


def watch(store, ids: dict[str, str], names: list[str]) -> list[dict]:
    """Both planes for `names`, at 0 s and whenever the store changes, up to WATCH."""
    t0, last, trail = time.monotonic(), None, []
    while True:
        t = time.monotonic() - t0
        snap = {n: {"store": row(ids[n]), "ek": ek_alive(store, ids[n])} for n in names}
        if snap != last:
            trail.append({"t": round(t, 1), **snap})
            print(f"  t={t:5.1f}s {json.dumps(snap)}")
            last = snap
        if t >= WATCH:
            return trail
        time.sleep(2)


def run() -> None:
    store = EK.EKEventStore.alloc().init()
    cal = scratch_list(store)
    assert cal, f"no list {LIST}; run `setup` first"
    items = ek_items(store, cal)
    ids = {t: str(items[t].calendarItemIdentifier()) for t in TITLES}
    links = {t: row(ids[t])["parent"] for t in TITLES}
    # The owner indented A and B only; C stays a flat control, removed with the list.
    want = {f"{p}.{i}": ids[p] for p in "AB" for i in (1, 2)}
    wrong = [c for c, p in want.items() if links[c] != p]
    print(f"fixture: {len(want) - len(wrong)}/{len(want)} subtasks linked; {wrong=}")
    assert not wrong, "indent the subtasks in Reminders.app, then re-run"
    res = {}
    try:
        print("A: remove parent A")
        ok, err = store.removeReminder_commit_error_(items["A"], True, None)
        res["A"] = {"ok": bool(ok), "trail": watch(store, ids, ["A", "A.1", "A.2"])}
        print("B: remove child B.1")
        ok, err = store.removeReminder_commit_error_(items["B.1"], True, None)
        res["B"] = {"ok": bool(ok), "trail": watch(store, ids, ["B", "B.1", "B.2"])}
        print("C: complete parent B (B.2 is still its child)")
        items["B"].setCompleted_(True)
        ok, err = store.saveReminder_commit_error_(items["B"], True, None)
        res["C"] = {"ok": bool(ok), "trail": watch(store, ids, ["B", "B.2"])}
    finally:
        ok, err = store.removeCalendar_commit_error_(cal, True, None)
        res["list_removed"] = bool(ok) and scratch_list(store) is None
        print(f"scratch list removed: {res['list_removed']}")
    # Ids are the probe's own scratch items; the file keeps labels only.
    for act in ("A", "B", "C"):
        for step in res[act]["trail"]:
            for n in list(step):
                st = step[n] if n != "t" else None
                if st and st["store"] and st["store"]["parent"]:
                    parent = next(
                        k for k, v in ids.items() if v == st["store"]["parent"]
                    )
                    st["store"]["parent"] = parent
    (HERE / "results-cascade.json").write_text(json.dumps(res, indent=2) + "\n")


if __name__ == "__main__":
    {"setup": setup, "run": run}[sys.argv[1] if len(sys.argv) > 1 else "run"]()
