---
spike: 002
idea: eventkit-depth
name: reminders-tags-route
type: standard
validates: "Given macOS 27, when every public surface is checked for a Reminders tag write and the sqlite store for a tag read, then REM-04 resolves to public write, read-only, or drop"
verdict: VALIDATED
related: [003]
tags: [reminders, eventkit, tags, subtasks, sqlite, app-intents, shortcuts]
---

# Spike 002: Reminders tags route

## What This Validates

Given macOS 27.0 (SDK `MacOSX27.0.sdk`), when every public surface is checked for a way to
write a Reminders tag, and the Reminders sqlite store is checked for a way to read tags, then
REM-04 resolves to one of: public write, read-only from sqlite, or drop.

**Answer: read-only from sqlite.** No public, id-addressed write route exists. The read route
joins cleanly to the ids the adapter already returns.

**Scope change found on the way:** `EKReminder.parentReminder` does not exist in the public
SDK. REM-03 ("subtasks via the public `parentReminder` route, macOS 14+") rests on a false
premise. Subtasks have the same shape as tags: readable from sqlite, no public id-addressed write.

## Research

| Surface | Tag write? | Subtask write? | Evidence |
|---------|-----------|----------------|----------|
| EventKit public API | No | No | `EKReminder.h` in the macOS 27.0 SDK declares 5 properties only: `startDateComponents`, `dueDateComponents`, `completed`, `completionDate`, `priority`. No tag, parent, section symbol in any EventKit header or in `EventKit.tbd`. |
| EventKit runtime (private) | No | Private only | ObjC runtime on macOS 27: `EKReminder` has `parentID` / `setParentID:` / `clearParentID`; no `parentReminder` selector; no tag selector on `EKReminder`, `EKCalendarItem`, `EKObject`. Private → excluded by REM-04. |
| AppleScript (`Reminders.sdef`) | No | No | Classes `account`, `list`, `reminder`; no tag, parent or section property. (It does declare `flagged`, which EventKit does not.) |
| App Intents via Shortcuts | Yes | Yes | Shortcuts ToolKit index lists `com.apple.reminders.AddOrRemoveTagsAppIntent` (operation, reminders, tags), `MoveRemindersToParentReminderAppIntent` (reminders, position, parentReminder), `TTRCreateReminderAppIntent` (title … tags, section, parentReminder, subtasks). **But** `ReminderEntity` exposes no identifier property, and neither "Find Reminders" query (App-Intent or legacy `WFReminderContentItem`) filters by id — only title, dates, tags, list. Not id-addressed. |
| `#tag` text via EventKit | No | — | Probe: an EK reminder titled and noted with `#gsdspike002` produces 0 hashtag rows after 30 s. |
| Reminders sqlite (read) | Read only | Read only | See Results. |

Sources for the false premise: the research's claim came from
[mattt/iMCP#145](https://github.com/mattt/iMCP/issues/145), an open feature request with no
reply that asserts `EKReminder.parentReminder` "available since macOS 14+". The SDK disproves
it. Other MCP servers document the same gap: "EventKit has no public API for the parent/child
relationship Reminders.app shows"; the hierarchy lives in the private ReminderKit framework.

**Chosen approach:** read-only from sqlite, for tags and for subtasks. The Shortcuts route is
recorded as an open option, not validated end to end (see Results › Open).

## How to Run

```sh
uv run python .planning/spikes/002-reminders-tags-route/probe_store.py          # read-only
uv run python .planning/spikes/002-reminders-tags-route/probe_title_hashtag.py  # scratch write
```

Both print aggregates only. The repo is public: no tag name, title or id is printed.

## What to Expect

`probe_store.py`: the live store name, counts, the populated columns on hashtag rows, join
rates, and the id-column match rates against EventKit. `probe_title_hashtag.py`: `hashtag
rows: 0`, then `scratch list removed: True`.

## Investigation Trail

1. **SDK headers.** Grepped the macOS 27.0 SDK's EventKit headers and `.tbd` for tag, hashtag,
   parent, subtask, section. Zero hits. `EKReminder.h` is 5 properties long.
2. **Surprise: no `parentReminder`.** REM-03 and PITFALLS.md both call it public (macOS 14+).
   Checked the runtime: only private `parentID` selectors. Traced the claim to iMCP#145 — an
   unanswered feature request, not documentation.
3. **AppleScript.** Read `Reminders.sdef` from the bundle (`sdef` needs full Xcode). No tag term.
4. **App Intents.** Reminders.app's own `Metadata.appintents` lists one intent. But the
   Shortcuts ToolKit index (`~/Library/Shortcuts/ToolKit/Tools-*.sqlite`) lists ~40 Reminders
   intents, including tag and parent writes. That is a public route — through Shortcuts only.
5. **Can a shortcut target a reminder by id?** Read `ReminderEntity`'s 20 properties and both
   "Find Reminders" predicate templates. No identifier property, no id search. The route is
   addressed by title/list/date filters only.
6. **Store read.** The live store is the largest `Data-*.sqlite` (three others are empty
   shells). First join attempt used `ZNAME`: wrong — the tag text is `ZNAME1`. `ZHASHTAGLABEL`
   links only 1 of 14 rows: the label table is an autocomplete list, not the source of truth.
7. **Unjoined rows.** 3 of 14 hashtag rows did not join: all 3 are tombstones
   (`ZMARKEDFORDELETION = 1`). Live tags must filter deletion on both the tag and the reminder.
8. **Id match.** `ZCKIDENTIFIER`, `ZDACALENDARITEMUNIQUEIDENTIFIER` and `ZIDENTIFIER` (16-byte
   blob → UUID) each equal EK `calendarItemIdentifier` for 1372/1372 live reminders.
9. **Implicit tags.** Wrote `#gsdspike002` into an EK title and note. The reminder row reached
   the store; no hashtag row appeared in 30 s. Scratch list removed and confirmed gone.
10. **Subtask read.** 316 live subtasks; child → `ZPARENTREMINDER` → parent: 316/316 have both
    ids in EventKit, 0 dangling parents.
11. **Daemon access.** `doctor()` grant list: `ren.lav.macos-apps-mcp` holds
    `kTCCServiceSystemPolicyAllFiles` (FDA). FDA covers the Reminders group container.

## Results

**Verdict: VALIDATED — REM-04 resolves to read-only from sqlite.**

Tag read recipe (macOS 27.0):

```sql
-- entity numbers come from Z_PRIMARYKEY, never hardcoded
SELECT r.ZCKIDENTIFIER AS reminder_id, h.ZNAME1 AS tag
FROM ZREMCDOBJECT h
JOIN ZREMCDREMINDER r ON r.Z_PK = h.ZREMINDER3
WHERE h.Z_ENT = (SELECT Z_ENT FROM Z_PRIMARYKEY WHERE Z_NAME = 'REMCDHashtag')
  AND h.ZMARKEDFORDELETION = 0 AND r.ZMARKEDFORDELETION = 0;
```

Subtask read recipe: `ZREMCDREMINDER c JOIN ZREMCDREMINDER p ON p.Z_PK = c.ZPARENTREMINDER`,
both ids via `ZCKIDENTIFIER`, same deletion filter.

| Measure | Value |
|---------|-------|
| Live reminders (store) / (EventKit) | 1372 / 1372 |
| `ZCKIDENTIFIER` == EK `calendarItemIdentifier` | 1372 / 1372 |
| Hashtag rows: live / tombstone | 11 / 3 |
| Live reminders with ≥ 1 live tag | 10 |
| Live subtasks, both ids in EK | 316 / 316 |
| EK `#tag` text → tag row | 0 (30 s poll) |

**Surprises**

- `parentReminder` is not public API. REM-03 must change before Phase 3 plans.
- The public write route exists, but only through Shortcuts App Intents, which cannot address a
  reminder by id.
- The tag column names carry Core Data inheritance suffixes (`ZNAME1`, `ZREMINDER3`). Apple's
  model changes can shift these suffixes between OS releases, as happened to osxphotos
  (RhetTbull/osxphotos#1651). A reader needs a schema fingerprint and a loud `SchemaDrift`,
  the same as `mail_index.HEADER_FINGERPRINT`.

**Open (not tested):** the Shortcuts route end to end. That test needs a user-built shortcut
("Find Reminders where Title is Input and List is …" → "Add Tags"). It would show whether
`shortcuts run` works from the daemon without UI, and how fast the store sees the change. It
is worth running only if the owner wants tag or subtask writes despite the missing id filter.
