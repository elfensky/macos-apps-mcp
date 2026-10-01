# Spike Manifest

## Ideas

### eventkit-depth
Phase 3 of milestone v0.11.0 takes Calendar and Reminders to Mail-level depth: alarms and real
recurrence on events, deletion, lists, subtasks and tags on reminders. Two parts of that scope
must be proven on device before any code: whether Reminders tags have a public write route, and
whether EventKit stores all-day events and RRULE shapes exactly as asked.

**Requirements:**

- No private-API write, in any outcome (REM-04, owner decision in REQUIREMENTS.md).
- A recurrence shape EventKit cannot express is rejected loudly with a typed error, never saved
  in a changed form (Phase 3 success criterion 2).
- Subtasks ship read-only, the same as tags: read from the Reminders sqlite store, with the
  write gap named in the tool docstring (owner, 2026-09-28, after spike 002).
- A DTSTART that does not match its rule is accepted with RFC 5545 semantics; the extra first
  occurrence is stated in the Pointer summary (owner, 2026-09-28, after spike 003).
- RRULE fidelity is proven on Google CalDAV too, because Google holds the default calendar for
  new events (owner, 2026-09-28).

### notes-semantic-search
NOTE-01: a written decision on Notes semantic search (embedding model, chunking, index build and
refresh policy, size cap, optional-extra boundary) before any indexing code. The spike measures
the real corpus so the decision rests on numbers, not guesses.

**Requirements:**

- The base install gains no ML dependency; semantic search lives behind a `[semantic]` extra.
- The index is a sidecar in the server's own state dir, the same shape as the Mail FTS sidecar.
- NOTE-01 closes as "not adopted": `notes()` gains FTS5 full-body search instead, with no new
  dependency (owner, 2026-09-28, after spike 004).

## Spikes

| # | Idea | Name | Type | Validates | Verdict | Tags |
|---|------|------|------|-----------|---------|------|
| 002 | eventkit-depth | reminders-tags-route | standard | Given macOS 27, when every public surface is checked for a tag write and sqlite for a tag read, then REM-04 resolves | ✓ VALIDATED — read-only from sqlite; `parentReminder` is not public (REM-03 premise false) | reminders, tags, subtasks, sqlite, app-intents |
| 003 | eventkit-depth | eventkit-allday-rrule | standard | Given a scratch calendar in a non-UTC zone, when all-day and RRULE events are created, then each reads back on the correct days, or EventKit rejects it | ✓ VALIDATED — all-day correct in every zone; 21/22 RRULE shapes exact; BYWEEKNO saved but never expanded (must be rejected); identical on Google CalDAV | calendar, rrule, all-day, timezone, dst |
| 004 | notes-semantic-search | notes-semantic-cost | standard | Given the real Notes corpus, when lexical and embedding retrievers index it, then size, build time, index size, dependency weight and quality are measured | ✓ VALIDATED — 17 notes (too small to need an index); native macOS embeddings below lexical; FTS5 over bodies is the zero-dep win; MiniLM-L6 (ONNX) if ever adopted | notes, embeddings, fts5, onnx |
