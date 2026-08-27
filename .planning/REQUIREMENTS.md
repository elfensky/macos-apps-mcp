# Requirements: macos-apps-mcp

**Defined:** 2026-08-28
**Core Value:** Safe writes — every write is gated by tier, addressed by id, dry-runnable, audited, and recoverable; the model can never lose, destroy, or send something by accident.

## v1 Requirements

Requirements for this project. Each maps to roadmap phases. Order of areas = phase order (gate → adapter depth → platform/distribution). Contacts and Messages depth moved to v2 at the 2026-08-28 roadmap review.

### Gate — land the spiked architecture review, make the suite fail-closed

- [ ] **GATE-01**: A unit test that forgets to fake the native seam raises instead of dialing a real app, for every adapter, `doctor`, and `shortcuts` (`run_osascript`, `body_file`, `tracked_run` all locked once in conftest; tripwire globs `adapters/*.py` + `doctor.py`)
- [ ] **GATE-02**: `runtime.py` exposes only the native door (~10 public names); the EventKit cluster (store, NSDate/RRULE coercion, TCC request, `run_native_async`) lives in its own module that Calendar/Reminders import by one name; bodies byte-identical; device proof `-m integration -k "request_access or create_event or create_reminder"`
- [ ] **GATE-03**: Tier policy (`read_only`, `allow_send`, `admit_send`, `outbound_status`, env grammar, consent file, role) lives in its own module below `server`, `doctor`, `deploy`; `doctor` no longer imports `server` (no import cycle in the package); the untrusted-data notice middleware lives beside audit, not in `server`
- [ ] **GATE-04**: Every tool is registered through one record (tier, adapter, permission, audit verb, notice policy); annotations, gates, guard, snapshot registry, notice exemption, audit verb and the tests' expectations are all derived from it; gated-off tools are still recorded pre-gate (never derived from FastMCP `Tool` objects)
- [ ] **GATE-05**: Every destructive tool defaults `dry_run=True` (`delete_event`, `delete_draft`, `delete_note` gain it), enforced by a registry test that fails when a new destructive tool omits it
- [ ] **GATE-06**: Writes audit under their own verb — `trash_mail`, `move_mail`, `mail_undo`, `export_mail`, `save_mail_attachment`, `music_control`, `play_playlist`, `set_mode`, `set_volume`, `create_contact` no longer log as bare `"write"` / unlogged
- [ ] **GATE-07**: `MACOS_APPS_READ_ONLY=1 uv run pytest` passes (12 failures on develop today)
- [ ] **GATE-08**: `_fake_envelope` is a shared fixture (`tests/envelope.py`) whose schema carries every column any `query_*` executor reads (incl. `m.size`, `message_references`); Mail tests that stubbed `query_*` only to compensate for a missing store go through the fixture; `HEADER_FINGERPRINT` covers those columns so a real store missing them surfaces as drift, not a query-time error
- [ ] **GATE-09**: The recoverable destructive plane runs its own preflight — `recoverable(op, targets, act, *, dry_run, present)` performs check_batch → present → preview; a dry run without a stated `present` is an error; `dedupe_batch(dry_run=True)` can no longer report "planned" for targets it never checked; device-verified on a scratch mailbox with the Mail watchdog running, dry-run envelopes and osascript argv byte-identical to before
- [ ] **GATE-10**: A tripwire test asserts every AppleScript template's `with timeout` backstop ≥ the host-side `timeout=` at every call site; `mail._DEDUPE` (600 < 900) fixed; `check_batch`'s refusal text no longer claims a backup for `update_status`; stale `daemon.py` comment removed
- [ ] **GATE-11**: Doctor unit tests no longer run live `pgrep`/`ps` on the dev machine (17 tests go through the locked `tracked_run` seam)
- [ ] **GATE-12**: The full device integration suite (`uv run pytest -m integration`) is green on the current macOS after the gate lands
- [ ] **GATE-13**: Each gate cut is re-landed by rebasing onto the previous PR on `develop` (1 → 7 → 5 → 2; Mail-scoped 3/4/9 in parallel); after cards 5 and 2 the daemon is rebuilt, restarted and `doctor().version` + one outbound dry run confirm the gates still read correctly; `spike/arch-review-*` branches and `.claude/worktrees/` are deleted afterwards

### Calendar

- [ ] **CAL-01**: User can set alarms (minutes-before list) when creating or updating an event; they land as `EKAlarm`s and are read back by verify-after-write
- [ ] **CAL-02**: Alarms on all-day and recurring all-day events fire on the right day in a non-UTC timezone (device-probed first, not fixed later)
- [ ] **CAL-03**: User can create/update recurring events with `BYDAY` (incl. ordinals for monthly), `BYMONTHDAY`, `BYMONTH`; shapes EventKit cannot express are rejected loudly as today; accepted shapes are read back over six months and match RFC 5545 expansion

### Reminders

- [ ] **REM-01**: User can delete a reminder by id (`dry_run=True` default, verify-after-write, mirrors `delete_event`)
- [ ] **REM-02**: User can create a reminder list
- [ ] **REM-03**: User can read and create subtasks via the public `parentReminder` route (macOS 14+)
- [ ] **REM-04**: Tags are investigated first; if no public write route exists they ship read-only (Reminders sqlite) with the write gap documented in the tool docstring — never a private-API write



### Notes

- [ ] **NOTE-01**: Semantic search is evaluated first — a written decision on embedding model, chunking, index build/refresh policy, size cap and the optional-extra boundary before any indexing code
- [ ] **NOTE-02**: If adopted: `notes_semantic(query)` returns Pointers from a sidecar index in the server's state dir (lazily built, size-capped, same shape as the Mail FTS sidecar), available only when the `[semantic]` extra is installed; base install gains no ML dependencies

### Photos

- [ ] **PHO-01**: The Photos mechanism is settled by running `uv add osxphotos` on the deployment target (the pyproject "deferred: pyobjc conflict" note is likely stale); PhotoKit via PyObjC is the fallback
- [ ] **PHO-02**: User can list albums as Pointers
- [ ] **PHO-03**: User can read bounded metadata for a photo by id (dates, location, persons, EXIF subset)
- [ ] **PHO-04**: User can export a photo by id to a destination directory (write-to-disk discipline; never inline image bytes)

### Platform

- [ ] **PLAT-01**: Operator can enable/disable adapters per app (e.g. Mail on, Photos off) via a config setting read at daemon start; a disabled adapter's tools are absent, never registered-and-erroring — the same rule as the tiers; `doctor` reports the active set
- [ ] **PLAT-02**: A localhost dashboard served by the daemon shows grants/`doctor`, `usage`, the audit trail, and the recoverable-plane backups (browsable recovery/history), and exposes the adapter toggles; loopback-only, no framework SPA

### Distribution

- [ ] **DIST-01**: README leads with the published PyPI package (`uvx macos-apps-mcp`); clone-and-venv becomes the contributor path
- [ ] **DIST-02**: `pyproject.toml` has `[project.urls]` so the PyPI page links to repo, issues, changelog
- [ ] **DIST-03**: Each release publishes a `.mcpb` bundle for one-click Claude Desktop install
- [ ] **DIST-04**: The notarized `.app` installs via a Homebrew cask (`brew install --cask …`), with the staple-then-zip order preserved
- [ ] **DIST-05**: A companion skill + Claude Code plugin live in-repo (`.claude-plugin/plugin.json`, `skills/<name>/SKILL.md`, `.mcp.json`) so `claude plugin install` wires skill + MCP server config in one step; the same `skills/` layout installs into other agents via `npx skills add elfensky/macos-apps-mcp`; the skill teaches the cockpit workflows (triage reads, pointer citation, draft-review) (#106)

## v2 Requirements

Deferred. Tracked but not in the current roadmap.

### Contacts (deferred 2026-08-28 — owner's call at roadmap review)
- **CON-01**: User can fetch a full, bounded contact card by id — all handles, addresses, birthday, organisation; the notes field is excluded by design (entitlement-gated, crashes updates)
- **CON-02**: User can fetch their own card (`contacts_me`)
- **CON-03**: User can update a contact by id (write tier, dry-runnable, audited, verify-after-write); native `CNContactStore` if the daemon's bundle identity is granted Contacts TCC (device spike), else the osascript update path — notes excluded either way
- **CON-04**: Contact search reads the AddressBook sqlite store when Full Disk Access is present and falls back to AppleScript otherwise; the schema fingerprint covers every column the queries read; `doctor` reports which plane is active

### Messages (deferred 2026-08-28 — owner's call at roadmap review)
- **MSG-01**: User can filter `messages_with` and `messages_search` by `since`/`until`
- **MSG-02**: User can filter for unread incoming messages
- **MSG-03**: Message Pointers are annotated with attachment name/type when present
- **MSG-04**: User can search attachments (by contact, date, MIME) as bounded Pointers
- **MSG-05**: User can save one attachment to disk by id (`mail_files` discipline: derived basename, allowlisted root, no silent overwrite, size cap; never inline bytes)
- **MSG-06**: User can send an iMessage/SMS (outbound tier: registered only under `allow-send messages`, `dry_run=True` default, dry-run makes no native call); recipient is an id-addressed handle or `chat_id` — no fuzzy auto-pick; iMessage-vs-SMS routing and group chats device-verified like Mail's outbound lifecycle
- **MSG-07**: User can check whether a handle is iMessage-reachable (ungated read)

### Safari
- **SAF-01**: Bookmarks + reading list as Pointers (Bookmarks.plist; reading list needs FDA) (#97)
- **SAF-02**: History search (`History.db`, read-only, FDA) — an open niche no surveyed server ships (#97)

### New domains (low priority)
- **MAP-01**: Maps search/directions/ETA via MapKit after a throttle measurement and NSRunLoop pump (#98)
- **LOC-01**: Geocode/reverse-geocode via CLGeocoder (#99a)
- **LOC-02**: Current position — spike-gated on headless CoreLocation authorization (#99b)
- **WX-01**: Weather via keyless Open-Meteo HTTP (#100)

### Platform
- **PLAT-03**: User-preferences env context injected into server instructions (#105)
- **PLAT-04**: Menubar companion — Swift `MenuBarExtra`, pure client of the daemon (stats, recovery/history, adapter toggles); never a second TCC identity, never Python
- **PLAT-05**: Network transport + auth for remote MCP clients — Tailscale-bound listener + bearer auth AND an SSE bridge (Home Assistant's MCP Client is SSE-only); dashboard/MCP route auth parity decided before code (#127)
- **REM-05**: Alarms on reminders (same mechanism as CAL-01)

## Out of Scope

| Feature | Reason |
|---------|--------|
| Screenshot, camera, audio capture (#101) | "An apps MCP, not a Mac-control MCP" (owner, 2026-08-28); screenshot already exists as a default Claude Code capability |
| System utilities — clipboard, Spotlight, notifications, system info, volume, Finder… (#102) | Same rule; the caller already has Bash |
| Generic AppleScript/JXA escape hatch (#103) | Bypasses typed safety; run `steipete/macos-automator-mcp` alongside |
| Journal | No API (DESIGN.md) |
| Rewriting as an iMCP-shaped GUI app | The server stays a server; any UI is a client of the daemon |
| Contributing Mail support to iMCP | Evaluated 2026-07-14, declined |
| Targeted permanent delete in Mail; `download-bodies`; `download-attachments` | Device probing proved the mechanisms do not exist (0.9.3 / 0.9.5 / 0.9.9) |
| WeatherKit | Paid entitlement tied to a signed bundle — blocked for this project |
| Contacts notes field (read or write) | `com.apple.developer.contacts.notes` unobtainable outside App Store review; touching it crashes updates (iMCP#148) |
| Private-API writes (Reminders tags) | Silent breakage on the next macOS point release contradicts the core value |
| Inline binary payloads (photo thumbnails, attachment bytes), full bodies in list results, static map images | Pointers-not-payload — the reason the repo exists |
| Fuzzy auto-pick of a recipient on any write | DESIGN.md records it sending iMessages to the wrong human |
| Timeouts on the shim↔daemon hop | #170 — a dead stream must answer |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| GATE-01 | Phase 1 | Pending |
| GATE-02 | Phase 1 | Pending |
| GATE-03 | Phase 1 | Pending |
| GATE-04 | Phase 1 | Pending |
| GATE-05 | Phase 1 | Pending |
| GATE-06 | Phase 1 | Pending |
| GATE-07 | Phase 2 | Pending |
| GATE-08 | Phase 1 | Pending |
| GATE-09 | Phase 1 | Pending |
| GATE-10 | Phase 1 | Pending |
| GATE-11 | Phase 2 | Pending |
| GATE-12 | Phase 2 | Pending |
| GATE-13 | Phase 1 | Pending |
| CAL-01 | Phase 3 | Pending |
| CAL-02 | Phase 3 | Pending |
| CAL-03 | Phase 3 | Pending |
| REM-01 | Phase 3 | Pending |
| REM-02 | Phase 3 | Pending |
| REM-03 | Phase 3 | Pending |
| REM-04 | Phase 3 | Pending |
| NOTE-01 | Phase 4 | Pending |
| NOTE-02 | Phase 4 | Pending |
| PHO-01 | Phase 4 | Pending |
| PHO-02 | Phase 4 | Pending |
| PHO-03 | Phase 4 | Pending |
| PHO-04 | Phase 4 | Pending |
| PLAT-01 | Phase 5 | Pending |
| PLAT-02 | Phase 5 | Pending |
| DIST-01 | Phase 6 | Pending |
| DIST-02 | Phase 6 | Pending |
| DIST-03 | Phase 6 | Pending |
| DIST-04 | Phase 6 | Pending |
| DIST-05 | Phase 6 | Pending |

**Coverage:**
- v1 requirements: 33 total
- Mapped to phases: 33
- Unmapped: 0 ✓

**Phase totals:** Phase 1: 10 · Phase 2: 3 · Phase 3: 7 · Phase 4: 6 · Phase 5: 2 · Phase 6: 5

---
*Requirements defined: 2026-08-28*
*Last updated: 2026-08-28 after roadmap revision (Contacts + Messages deferred to v2; 33/33 mapped across 6 phases)*
