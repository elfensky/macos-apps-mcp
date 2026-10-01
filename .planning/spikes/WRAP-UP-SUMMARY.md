# Spike Wrap-Up Summary

**Date:** 2026-09-28
**Spikes processed:** 3
**Feature areas:** Reminders tags and subtasks, Calendar recurrence and all-day, Notes search
**Skill output:** `./.claude/skills/spike-findings-macos-apps-mcp/` (main checkout; `.claude/`
is git-ignored, so the skill is local to this machine and is rebuilt from this directory)

## Processed Spikes

| # | Name | Type | Verdict | Feature Area |
|---|------|------|---------|--------------|
| 002 | reminders-tags-route | standard | VALIDATED | Reminders tags and subtasks |
| 003 | eventkit-allday-rrule | standard | VALIDATED | Calendar recurrence and all-day |
| 004 | notes-semantic-cost | standard | VALIDATED | Notes search |

## Key Findings

- **Reminders tags and subtasks are read-only.** No public, id-addressed write exists.
  `EKReminder.parentReminder` is not in the SDK, so REM-03's premise is false. The Shortcuts
  App Intents route is public but cannot address a reminder by id. Both tags and subtasks
  read cleanly from the Reminders sqlite store: `ZCKIDENTIFIER` equals the EventKit id for
  1372 of 1372 reminders. The reader needs a schema fingerprint, because the Core Data column
  suffixes (`ZNAME1`, `ZREMINDER3`) can shift between OS releases.
- **EventKit recurrence is exact with the full initializer, except BYWEEKNO.** 21 of 22
  RRULE shapes read back exactly. BYWEEKNO is saved unchanged but expands to DTSTART only,
  with no error, so it must be rejected before any native call. BYHOUR, BYMINUTE, BYSECOND
  and WKST have no EventKit field and are rejected too. Verify-after-write must compare every
  BY* part, not only `(frequency, interval, count)`. Google CalDAV gives the same results as
  iCloud.
- **All-day events are correct with the current adapter path** in every creator and reader
  zone tested, across DST ends. On a day whose local midnight does not exist, the start reads
  01:00, so the all-day date comes from `.date()`, never from a 00:00 assumption.
- **Notes semantic search is not adopted (NOTE-01).** The corpus is 17 notes, about 6K
  tokens. The largest gap is lexical: `notes()` never searches bodies. FTS5 over decoded
  bodies needs no new dependency and lifts hit@1 from 0.31 to 0.54. Native macOS embeddings
  score below the current matcher. If a `[semantic]` extra ships later, the choice is
  `all-MiniLM-L6-v2` through fastembed (142 MB of packages plus an 87 MB model).

## Open

- Server-side storage of RRULEs is not proven on iCloud or Google: the after-sync re-read
  can come from this Mac's cache.
- The Shortcuts route for tag and subtask writes was not tested end to end.
- The method to detect a DTSTART that does not match its rule was not spiked.
