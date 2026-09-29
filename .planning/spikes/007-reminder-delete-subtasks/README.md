---
spike: 007
idea: eventkit-depth
name: reminder-delete-subtasks
type: standard
validates: "Given a scratch list with a parent and 2 subtasks, when EventKit removes the parent, then the sqlite store shows whether the subtasks are deleted, orphaned or promoted, and how fast"
verdict: VALIDATED
related: [002]
tags: [reminders, subtasks, delete, complete, sqlite, eventkit]
---

# Spike 007: What happens to subtasks when EventKit deletes or completes a parent

## What This Validates

Given a scratch Reminders list with parents that have subtasks made in Reminders.app, when
EventKit removes a parent, removes a child, or completes a parent, then the Reminders sqlite
store and EventKit show what happens to the other items, and when. REM-01's
`delete_reminder` must know this before its dry run can say what it will destroy.

**Answer: removing a parent through EventKit deletes its subtasks too, at once.** One id in,
N+1 reminders gone. EventKit cannot see the subtasks, so a caller that asks EventKit what a
delete will touch hears "one reminder". **Completing a parent does not complete its
subtasks:** they stay open under a completed parent.

## Research

- Spike 002: `EKReminder` has no public parent API; subtasks are read from the store
  (`ZREMCDREMINDER.ZPARENTREMINDER`), joined to EventKit by `ZCKIDENTIFIER`. No public write
  exists, so EventKit cannot build this fixture.
- REM-04 excludes a private-API write, so the private `setParentID:` was not used to build
  the fixture either. The owner indented the subtasks in Reminders.app by hand.
- No external dependency: the probe is EventKit (PyObjC) plus a read-only sqlite read.

## How to Run

```sh
P=.planning/spikes/007-reminder-delete-subtasks/probe_cascade.py
uv run python $P setup   # scratch list gsd-spike-007: A, A.1, A.2, B, B.1, B.2, C, C.1, C.2
# Reminders.app on THIS Mac: indent A.1+A.2 under A and B.1+B.2 under B (select, ⌘])
uv run python $P run     # checks the 4 links, then 3 acts, 60 s watch each; removes the list
```

## What to Expect

`fixture: 4/4 subtasks linked`, then one snapshot per act (a new line only when either plane
changes), then `scratch list removed: True`.

## Investigation Trail

1. **Fixture.** The probe created 9 flat reminders in `gsd-spike-007` through EventKit. The
   first two `run` attempts stopped at the fixture check: no parent link in any store file,
   and no row modified since creation. EventKit's private `parentID` getter (read only, for
   diagnosis) also returned nothing.
2. **The indent landed later.** After the owner indented A and B in Reminders.app, the store
   showed all 4 links within the same minute, with new modification times on the 6 rows.
   EventKit's private `parentID` still returned None for the 4 children: EventKit does not
   expose app-made subtasks even privately. The store is the only read route (spike 002).
3. **A: remove parent A.** At the first snapshot, A, A.1 and A.2 were all
   `ZMARKEDFORDELETION = 1`, and all three were gone from EventKit. No change in 60 s. The
   deleted children keep their parent link as tombstones.
4. **B: remove child B.1.** Parent B and sibling B.2 unchanged in both planes. B.1's parent
   link was cleared.
5. **C: complete parent B** (B.2 still its child; the owner indented A and B only, so C
   stayed a flat control). B completed in both planes; B.2 stayed open and linked. No change
   in 60 s.

## Results

**Verdict: VALIDATED.**

| Act (EventKit) | Parent | Subtasks | When |
|---|---|---|---|
| Remove a parent | deleted | **all deleted** (tombstones keep the link) | at once |
| Remove a child | unchanged | sibling unchanged | at once |
| Complete a parent | completed | **stay open**, still linked | at once, stable 60 s |

`results-cascade.json` holds every snapshot, with labels instead of ids.

**Signal for the build (Phase 3, REM-01)**

- **`delete_reminder` must read the subtasks from the store before it acts.** The dry run
  and the confirmation say "and N subtasks" and list them as Pointers; the audit snapshot
  records them, so an undo can recreate them (as flat reminders, since no public write can
  re-nest them). EventKit alone would report one reminder and delete N+1.
- **Consider refusing a parent delete** unless the caller confirms the subtasks, the same
  shape as `SpanRequired` on a recurring event: a typed error that names the count.
- **`complete_reminder` on a parent leaves open subtasks under a completed parent,** which
  the app's default view can hide. Report them in the result.
- **The subtask read is the store's.** EventKit has no public or private route that sees
  app-made subtasks.

**Not tested**

- Nested subtasks (Reminders allows one level) and a parent with dozens of subtasks.
- A parent delete made in Reminders.app or on iPhone (only EventKit's delete was tested).
- Whether the cascade also runs on a non-iCloud reminders source.
