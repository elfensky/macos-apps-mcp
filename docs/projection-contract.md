# Outbound projection contract (#4)

**Status:** contract only. macos-apps-mcp provides the tools; the projection command is built in the
life-cockpit repo (this repo does not touch the cockpit vault).

## Grammar (cockpit `conventions.md` extension)

A projected vault task carries a stable backlink id, written **before the date emoji** (Obsidian
Tasks-plugin ordering gotcha — fields after the emoji are mis-parsed):

```
- [ ] Call dentist [rem:: <reminder-id>] 📅 2026-06-23
- [ ] Submit taxes [cal:: <event-id>] 📅 2026-06-23
```

`<reminder-id>` / `<event-id>` is the `Pointer.id` returned by the macos-apps-mcp write tools
(EventKit `calendarItemIdentifier`).

## Idempotent algorithm (run by the cockpit command)

For each vault task with a deadline:
1. **No `[rem::]`/`[cal::]`** → call `create_reminder` / `create_event`; write the returned `id`
   back into the task line as `[rem:: id]` / `[cal:: id]`.
2. **Has the id** → call `update_reminder` / `update_event` with the current task fields
   (full replace — macos-apps-mcp writes are idempotent re-derivations; an absent due date/notes is
   *cleared*, not left stale).
3. **Vault task checked done** → call `complete_reminder`.
4. **Reminder completed in Apple** (seen via the `reminders` read) → check the vault task off.

No conflict-merge engine: conflicts are *avoided* by the stable id, not resolved (DESIGN.md
out-of-scope). The id is the single source of identity in both directions.

## Tools the cockpit command calls
- `create_reminder`, `update_reminder`, `complete_reminder`
- `create_event`, `update_event`
- `reminders` (to detect Apple-side completion)
