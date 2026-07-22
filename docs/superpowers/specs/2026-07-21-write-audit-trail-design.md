# Write audit trail with undo info — design

**Issue:** [#67](https://github.com/elfensky/macos-apps-mcp/issues/67) · **Milestone:** 0.7.0 — Differentiators · **Date:** 2026-07-21

## Why

No PIM MCP server can answer "what did Claude change in my calendar last night?" — the missing
trust primitive for overnight `/loop` runs against personal data. We already return stable ids, so
an append-only audit trail with before-state makes undo *real* (manual-first), not cosmetic.

## Storage

- `runtime.state_dir() -> Path` — `$XDG_STATE_HOME/macos-apps-mcp` (default `~/.local/state/macos-apps-mcp`),
  created on first use.
- `runtime.audit_write(record: dict) -> None` — append one JSON object + `\n` to
  `state_dir()/audit.jsonl`. **Never raises** — a logging failure (disk full, permission) is
  swallowed (logged at debug), because auditing must never fail a user's write.
- **Rotation:** before appending, if `audit.jsonl` exceeds ~5 MB, rename it to `audit.jsonl.1`
  (replacing any existing `.1`), then start a fresh file. One backup; bounded disk.

## Record shape

One JSON object per write:

```json
{
  "ts": "2026-07-21T22:14:03",         // local ISO, seconds
  "tool": "update_event",
  "op": "update",                       // create | update | delete | action
  "args": { "id": "…|…", "title": "…", "start": "…" },   // per-value truncated
  "target_id": "x-apple…|…",            // from args["id"], or the result id on create
  "before": { "id": "…", "summary": "Standup 09:00–09:15", "deeplink": "…" },  // update/delete
  "after":  { "id": "…", "summary": "Standup 10:00–11:00", "deeplink": "…" }   // create/update
}
```

- `before` is null for creates and for envelope-only writes; `after` is null for deletes.
- `args` values are truncated (strings > ~200 chars) so a large note body can't bloat the log.
- `before`/`after` use the same `Pointer`→dict shape (`_emit`) as `dry_run` previews, so a delete's
  `dry_run` `would_delete` pointer equals its audit `before` (acceptance: dry_run parity).

## Central `AuditMiddleware`

Mirrors `UntrustedDataNotice` — one central hook, adapters hold no audit logic, a new write cannot
silently skip it.

- The `_write_tool` / `_additive_tool` decorators add each tool name to a module-level
  `_WRITE_TOOLS` set as they register (the "hooked where `_write_tool` dispatches" seam).
- `on_call_tool(context, call_next)`:
  1. `tool = context.message.name`; `args = context.message.arguments or {}`.
  2. **Before-state:** if `tool` is in `_AUDIT_SNAPSHOT` (the update/delete/complete registry) and
     `args.get("id")`, capture `before = await anyio.to_thread.run_sync(lambda: _safe_snapshot(adapter, ident))`.
     `to_thread` keeps the event loop unblocked; `_safe_snapshot` swallows errors → `None`. The read
     runs on the serialized native worker immediately before the write, so it is the pre-write state
     modulo a concurrent *external* edit (Calendar.app / iCloud) in a microsecond window — documented,
     acceptable for "what did Claude change".
  3. `result = await call_next(context)`.
  4. If `tool in _WRITE_TOOLS` and not `result.is_error`: build the record and `_safe_audit(...)`
     (swallows errors). `after`/`target_id` derived from the result's structured pointer where present.
- `_AUDIT_SNAPSHOT = {update_event: _calendar, delete_event: _calendar, update_reminder: _reminders,
  complete_reminder: _reminders, update_note: _notes, delete_note: _notes}` — all take an `id` arg.
  Creates and non-id writes (`create_*`, `safari_open`, `run_shortcut`, `mail_reply`) are
  envelope-only (no snapshot).

## Adapter `snapshot(id) -> Pointer | None`

The single adapter change — a plain read, reusing each adapter's existing by-id resolve; returns the
current pointer, or `None` if the id no longer resolves:

- `CalendarAdapter.snapshot(id)` — `run_native` → `_resolve_event(s, id)` → `_event_pointer`; `None`
  on the resolve `ValueError`.
- `RemindersAdapter.snapshot(id)` — `run_native` → `store().calendarItemWithIdentifier_(id)` →
  `_reminder_pointer`; `None` if absent.
- `NotesAdapter.snapshot(id)` — `_read_title_by_id(id)` → `Pointer(id, summary=title, deeplink="")`;
  `None` if the title read is `None`. (Pointer-level before-state — enough for manual undo; a
  full-field snapshot is a non-breaking later enhancement.)

`snapshot` lives directly on the three write adapters — no `contracts.py` Protocol change, since
the middleware holds the concrete adapter instances (`_calendar`/`_reminders`/`_notes`) and calls it
only for tools in the `_AUDIT_SNAPSHOT` registry.

## `audit(since=None)` read tool

`@_read_tool` — reads the tail of `audit.jsonl`, returns recent entries **newest-first**, bounded to
the last ~50, output-hygiene budgeted (entries embed user-store text like titles → the `_read_tool`
path already prepends the untrusted-data notice). `since` is an optional ISO datetime; entries with
`ts < since` are dropped. Malformed lines are skipped (never fail the read). Permission: none beyond
file read (documented "no permission"); classified in the annotation map.

## Self-enforcement

Extend the annotation-style test: every member of `_WRITE_TOOLS` is either in `_AUDIT_SNAPSHOT` or in
an explicit `_ENVELOPE_ONLY` set — so a newly added write tool must be consciously classified as
snapshot-audited or envelope-only, and can't silently skip the audit.

## Tests

Unit (no TCC):
- `audit_write`: appends valid JSON lines; rotation at the size cap (write past 5 MB → `.1` created,
  fresh file); a write to an unwritable path is swallowed (no raise). Uses `tmp_path` +
  monkeypatched `state_dir`.
- `AuditMiddleware`: a fake write tool call produces one record with the right op/args/target_id;
  `snapshot` is invoked for a registered update/delete and NOT for a create; a `snapshot`/`audit`
  exception never propagates (the tool result is returned unchanged); a `result.is_error` produces
  no record.
- `audit()` reader: `since` filter, newest-first, bound, malformed-line skip — over a `tmp_path`
  fixture file.

Integration (`-m integration`, manual only): a real `update_event` writes an audit entry whose
`before` carries the pre-edit pointer and `after` the post-edit pointer; a `create_*` logs
`before: null`.

## Out of scope (YAGNI)

- `undo(entry)` tool — the log is undo-*ready*; reversal stays manual-first (issue-stated).
- Full field-level before-snapshots (pointer-level suffices for manual undo).
- Auditing reads (only writes are logged).
