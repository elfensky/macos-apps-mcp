# Spike Wrap-Up Summary

**Date:** 2026-09-28 (002–004), 2026-09-29 (005–008)
**Spikes processed:** 7
**Feature areas:** Mail sender and replies, Mail batch moves, Reminders tags and subtasks,
Calendar recurrence and all-day, Calendar alarms, Notes search
**Skill output:** `./.claude/skills/spike-findings-macos-apps-mcp/` (main checkout; `.claude/`
is git-ignored, so the skill is local to this machine and is rebuilt from this directory)

## Processed Spikes

| # | Name | Type | Verdict | Feature Area |
|---|------|------|---------|--------------|
| 002 | reminders-tags-route | standard | VALIDATED | Reminders tags and subtasks |
| 003 | eventkit-allday-rrule | standard | VALIDATED | Calendar recurrence and all-day |
| 004 | notes-semantic-cost | standard | VALIDATED | Notes search |
| 005 | mail-unowned-from | standard | VALIDATED | Mail sender and replies |
| 006 | mail-move-budget | standard | VALIDATED | Mail batch moves |
| 007 | reminder-delete-subtasks | standard | VALIDATED | Reminders tags and subtasks |
| 008 | eventkit-alarms | standard | VALIDATED | Calendar alarms |

## Key Findings

- **Reminders tags and subtasks are read-only.** No public, id-addressed write exists.
  `EKReminder.parentReminder` is not in the SDK, so REM-03's premise is false. The Shortcuts
  App Intents route is public but cannot address a reminder by id. Both tags and subtasks
  read cleanly from the Reminders sqlite store: `ZCKIDENTIFIER` equals the EventKit id for
  1372 of 1372 reminders. The reader needs a schema fingerprint, because the Core Data column
  suffixes (`ZNAME1`, `ZREMINDER3`) can shift between OS releases.
- **A parent delete takes its subtasks with it.** When EventKit removes a parent, the store
  deletes its subtasks at once, and EventKit cannot see them. `delete_reminder` must read
  the subtasks from the store first and name them in the dry run, the confirmation and the
  audit snapshot. Completing a parent leaves its subtasks open.
- **EventKit recurrence is exact with the full initializer, except BYWEEKNO.** 21 of 22
  RRULE shapes read back exactly. BYWEEKNO is saved unchanged but expands to DTSTART only,
  with no error, so it must be rejected before any native call. BYHOUR, BYMINUTE, BYSECOND
  and WKST have no EventKit field and are rejected too. Verify-after-write must compare every
  BY* part, not only `(frequency, interval, count)`. Google CalDAV gives the same results as
  iCloud.
- **All-day events are correct with the current adapter path** in every creator and reader
  zone tested, across DST ends. On a day whose local midnight does not exist, the start reads
  01:00, so the all-day date comes from `.date()`, never from a 00:00 assumption.
- **Alarms: relative only, at most 5.** Relative alarms round-trip exactly on iCloud and
  Google, and all-day alarms (offset from local midnight) fire on the right local day in 4
  zones. Google keeps at most 5 alarms and converts an absolute alarm to a relative one,
  10–30 s after the save, so a verify-after-write cannot see it. Both shapes are refused
  before the write. Alarm lists are compared as sorted multisets.
- **Notes semantic search is not adopted (NOTE-01).** The corpus is 17 notes, about 6K
  tokens. The largest gap is lexical: `notes()` never searches bodies. FTS5 over decoded
  bodies needs no new dependency and lifts hit@1 from 0.31 to 0.54. Native macOS embeddings
  score below the current matcher. If a `[semantic]` extra ships later, the choice is
  `all-MiniLM-L6-v2` through fastembed (142 MB of packages plus an 87 MB model).
- **Mail never refuses an unowned From (MAIL-04).** `set sender` to an address no account
  owns raises no error and silently uses the default account, with no domain match. The
  refusal is therefore done in Python, before any native write, against the accounts'
  `email addresses` (compared case-insensitively). A reply to mail FROM a configured account
  is sent as that account, which on this Mac is a family member's identity, so `reply_all`
  needs a sender guard.
- **A batch move's cost is the per-id `whose` scan (MAIL-01).** Each scan reads the whole
  mailbox, about 0.1–0.25 ms per stored message on a healthy Mail and 5–9× more in the facts
  §3c state. The shipped `_MOVE` needs about 460 s for 25 messages INBOX → Archive, over the
  300 s cap. A bulk read of Mail's internal ids plus the raw-class reference
  `«class mssg» id n of mb` (O(1)) moved and verified 25 messages in 63 s through
  `recoverable()`. A timeout that scales with n is a patch; the by-ID act is the fix.

## Open

- Server-side storage of RRULEs and alarms is not proven on iCloud or Google: the
  after-sync re-read can come from this Mac's cache.
- The Shortcuts route for tag and subtask writes was not tested end to end.
- The method to detect a DTSTART that does not match its rule was not spiked.
- Which of 08:00 / 09:00 Calendar fires for a "+540" all-day alarm on a DST-change day is not
  observed (next chance: 2026-10-25, Europe/Brussels).
- How the outbound dry run checks sender ownership without a native call is not decided
  (only on the real call, or from a cached address list).
- The duplicate rule for a by-ID move (move every copy, or refuse) is not decided.
- `_TRASH` with real messages, the by-ID act across accounts and on a Gmail label mailbox,
  and a 25-message undo were not run.
