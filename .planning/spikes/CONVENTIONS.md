# Spike Conventions

Patterns and stack choices established across spike sessions. New spikes follow these unless
the question requires otherwise.

## Stack

- Python in the project venv (`uv run`), PyObjC for native frameworks — the same plane the
  adapters use, so a finding transfers to the build unchanged (002, 003, 004).
- A spike-only dependency goes through `uv run --with <pkg>` (dateutil, fastembed,
  `pyobjc-framework-NaturalLanguage`). Never `uv add`: `pyproject.toml` and `uv.lock` stay
  untouched (003, 004).

## Structure

- `.planning/spikes/NNN-name/` holds the probe scripts, `README.md` and `results-*.json`.
- `.planning/` is inside ruff's scope: probe scripts pass `ruff check` and `ruff format`.
- Work happens in a worktree under `.worktrees/`, never in the main checkout.

## Patterns

- **The repo is public.** A probe prints and commits aggregates only: counts, schema, timings,
  scores. Personal text (titles, tag names, note bodies, queries that paraphrase them) stays in
  `$SPIKE_PRIVATE_DIR` outside the repo (002, 004). Addresses and ids become roles
  (`account:Business`), position labels (`oldest`) or masked shapes (`A@a.a <A@A.A>`); grep
  the `results-*.json` for `@` and UUIDs before committing (005, 006, 007).
- **Device writes use a scratch container** named `gsd-spike-NNN` (a Reminders list, an iCloud
  calendar). Remove it in a `finally`, then check that nothing is left (002, 003).
  A source that refuses new containers (Google, `EKErrorDomain 17`) gets writes in an
  existing container only with the owner's approval: every item titled `gsd-spike-NNN …`,
  deleted by id and then by a sweep, with `left=0` checked before and after. Test the sweep
  on a scratch container first (003).
- **"Public API" means the SDK.** Grep the current SDK's headers and `.tbd`
  (`/Library/Developer/CommandLineTools/SDKs/MacOSX27.0.sdk`). A selector that exists only at
  runtime is private, even when it works (002, 004).
- **Reuse the adapter's own code path** where one exists (`CalendarAdapter.create_event`,
  `notes._decode_note_data`, `notes._FROM`), so the spike measures what ships (003, 004).
- **Distrust a clean first pass.** Add an edge case designed to break it (no-midnight DST days,
  tombstone rows, raw-count cross-check against the daemon, an occurrence ON a DST-change
  day, a control that separates two explanations of one result).
- **Mail probes run with the watchdog on and address only named mailboxes** (facts §8b).
  Nothing is sent; a real move goes through `mail_recover.recoverable()` so it leaves a
  receipt `mail_undo` accepts. Family accounts (Grandma, Mama) are never targets (005, 006).
- **Check Mail's health before timing it.** The facts §3c state (a windowless `delete` that
  no-ops) made every Apple Event 5–9× slower. A timing taken in that state is labelled as
  such, and the healthy numbers come after an owner-approved restart (006).
- **A fixture only a human can build is checked before the probe acts.** The probe stops
  with a named assertion when the fixture is not in the store (007).
- **One `EKEventStore` per operation.** An `EKCalendar` from one store passed to another
  store's predicate raises `NSNull backingObject`; re-fetch by identifier instead (003, 008).
- **A timing test re-reads over time**, from a fresh store, at fixed steps (0/10/30/60/120 s),
  because a remote source can rewrite a saved item after the local read succeeds (008).

## Tools & Libraries

- `python-dateutil` `rrulestr` as the RFC 5545 reference. It drops a DTSTART that does not
  match the rule; RFC 5545 and EventKit count it.
- Shortcuts ToolKit index (`~/Library/Shortcuts/ToolKit/Tools-*.sqlite`, read-only) lists every
  App Intent and its parameters. It is the way to find public, Shortcuts-only routes.
- `doctor()` over MCP shows which TCC grants the daemon identity holds.
- Timing inside AppleScript: `use framework "Foundation"` and
  `current application's NSDate's timeIntervalSinceReferenceDate()` give millisecond timing
  without the osascript start-up cost (006).
- `runtime.run_osascript(..., timeout=…)` for a long script; raw `osascript -` via
  `subprocess` only when the probe must wait longer than one call (facts §2) (005, 006).
