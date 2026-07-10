# Changelog

All notable changes to mac-mcp are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/); the project is pre-1.0, so the public
surface may still shift between minor versions.

## [0.3.0] - 2026-07-09 — Reliability, safety & depth

Trust hardening: loud typed failures, self-diagnosis, and verify-after-write.

### Added

- **Typed error taxonomy** (#47) — every native failure is a loud, agent-directed
  `NativeError` subclass; the dispatch layer turns it into a tool result carrying the
  remediation directive, never a silent empty list masquerading as "no matches".
- **`doctor` tool** (#48) — per-surface macOS permission + health self-diagnosis with
  exact remediation; read-only and prompt-free by default.
- **`now()` tool + timezone normalization** (#50) — grounds relative dates ("tomorrow");
  every date parameter is interpreted in local wall-time at the contracts boundary, so a
  naive ISO datetime is never silently read as UTC (the ecosystem's day-shift bug).

### Changed

- **Verify-after-write** (#49) — every create/update re-fetches the item by id and diffs
  the persisted fields, failing loudly on a fabricated id or a dropped/reverted field
  (iCloud can revert a write ~1s later).
- **Explicit span on recurring update/delete** (#51) — editing or deleting a recurring
  event requires an explicit `this-event` / `future-events` span, so one occurrence is
  never silently rewritten as the whole series.

### Fixed

- **Trust-core hardening** (#72) — fixes from a multi-agent adversarial review:
  recurrence presence-vs-cadence comparison, a DST fall-back fold shifting an instant by
  an hour, and `str.strip` eating control-char field separators.

## [0.2.0] - 2026-06-29 — Rebrand

### Changed

- Renamed the project and distribution **apple-mcp → mac-mcp** (package `mac_mcp`, the
  env var, and all imports); added an MIT license, packaging metadata, and a
  TestPyPI → PyPI publish workflow.

## [0.1.2] - 2026-06-28

### Fixed

- **All-day events** store date-only (midnight) bounds, so a stray time on an
  `all_day=True` create/update can't drift on CalDAV roundtrips. A same-day event is now
  stored as a single day (EventKit's all-day end date is inclusive — verified on-device —
  so it was previously persisted as a two-day event); a reversed range clamps to one day;
  and a mixed timezone-aware/naive start/end pair no longer crashes the worker.
- **Contacts read** no longer mis-parses a contact whose name/org/phone/email contains a
  tab or newline — the osascript payload is delimited by control chars (US/RS), so an
  in-field tab/newline can't split a row or spoof a pointer. A broad name match is also
  capped inside AppleScript, so a common query can't fetch thousands of records before
  Python truncates them.
- **`run_shortcut`** writes its result to a temp file and reads back only a bounded
  prefix, so a shortcut that returns a huge blob can't balloon the worker's memory; a
  shortcut whose output is a directory (not a file) is tolerated instead of crashing.

## [0.1.1] - 2026-06-28

Docs-only release — the shipped tool surface was unchanged; the narrative docs
had drifted behind it.

### Changed

- **README** rewritten around the actual surface: the stale "Calendar + Reminders,
  Mail next / v1 in progress" framing is replaced by tables covering the read/write
  Calendar & Reminders tools, the read-only context adapters (Mail, Notes, Contacts,
  Photos, Safari, Messages, Shortcuts), and the actions — with real args, query
  selectors, the `RRULE` subset, and the `APPLE_MCP_READ_ONLY` guard.
- **DESIGN.md** reconciled with shipped reality: the read adapters it had listed as
  "dropped" / "YAGNI" / "maybe-never" (Notes, Messages, Contacts, Photos) are
  documented as shipped; the layout block lists all nine adapters; Photos is noted as
  AppleScript (not `osxphotos`).

### Removed

- **`docs/superpowers/`** — the executed v1 plan and its design spec. Both were spent
  build-time scaffolding; their durable decisions live in DESIGN.md / CLAUDE.md, and
  the spec had gone stale (it predated the CHANGELOG and the recurrence/Notes/Messages/
  Contacts work). The living cross-repo contracts (`docs/projection-contract.md`,
  `docs/parity-checklist.md`) are kept.

## [0.1.0] - 2026-06-27

First tagged release.

### Added

- **Recurrence** for Calendar events and Reminders — pass an RFC 5545 `RRULE` string
  (the `FREQ` / `INTERVAL` / `COUNT` / `UNTIL` subset) to `create_event` / `update_event`
  and `create_reminder` / `update_reminder`. A recurring reminder requires a due date
  (enforced at the boundary as a clear error); `INTERVAL`/`COUNT` must be positive, a
  date-only `UNTIL` includes the whole final day, and unsupported RRULE parts (e.g.
  `BYDAY`) are rejected rather than silently ignored.
- **`run_shortcut`** — run a Shortcut by name with optional text input, via the
  `shortcuts` CLI; returns a bounded snippet of any output.
- **`safari_open`** — open a URL in a new Safari tab; a bare host defaults to `https://`,
  and only `http`/`https` URLs are opened (non-web schemes are refused at the boundary).
- **Calendar `all_day`** flag on event create/update.
- **Reminder `priority`** (0–9) and **`start`** date on reminder create/update.
- **Contacts** read now surfaces the first phone + email in the pointer summary — a
  reachable handle, not just name + organization.

### Removed

- **Music adapter** — track search and the proposed playback control are dropped as the
  weakest tool, following the earlier removal of the Files and Maps adapters.

### Notes

- The new action tools (`run_shortcut`, `safari_open`) are guarded by
  `APPLE_MCP_READ_ONLY` like every other write, so a read-only deployment still skips them.
