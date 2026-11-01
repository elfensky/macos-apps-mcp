# Requirements: macos-apps-mcp

**Defined:** 2026-08-28
**Core Value:** Safe writes — every write is gated by tier, addressed by id, dry-runnable, audited, and recoverable; the model can never lose, destroy, or send something by accident.

## v1 Requirements

Requirements for this project. Each maps to roadmap phases. Order of areas = phase order (gate → Mail → adapter depth → platform/distribution). Contacts and Messages depth moved to v2 at the 2026-08-28 roadmap review.

### Gate — land the spiked architecture review, make the suite fail-closed

- [x] **GATE-01**: A unit test that forgets to fake the native seam raises instead of dialing a real app, for every adapter, `doctor`, and `shortcuts` (`run_osascript`, `body_file`, `tracked_run` all locked once in conftest; tripwire globs `adapters/*.py` + `doctor.py`)
- [x] **GATE-02**: `runtime.py` exposes only the native door (~10 public names); the EventKit cluster (store, NSDate/RRULE coercion, TCC request, `run_native_async`) lives in its own module that Calendar/Reminders import by one name; bodies byte-identical; device proof `-m integration -k "request_access or create_event or create_reminder"`
- [x] **GATE-03**: Tier policy (`read_only`, `allow_send`, `admit_send`, `outbound_status`, env grammar, consent file, role) lives in its own module below `server`, `doctor`, `deploy`; `doctor` no longer imports `server` (no import cycle in the package); the untrusted-data notice middleware lives beside audit, not in `server`
- [x] **GATE-04**: Every tool is registered through one record (tier, adapter, permission, audit verb, notice policy); annotations, gates, guard, snapshot registry, notice exemption, audit verb and the tests' expectations are all derived from it; gated-off tools are still recorded pre-gate (never derived from FastMCP `Tool` objects)
- [x] **GATE-05**: Every destructive tool defaults `dry_run=True` (`delete_event`, `delete_draft`, `delete_note` gain it), enforced by a registry test that fails when a new destructive tool omits it
- [x] **GATE-06**: Writes audit under their own verb — `trash_mail`, `move_mail`, `mail_undo`, `export_mail`, `save_mail_attachment`, `music_control`, `play_playlist`, `set_mode`, `set_volume`, `create_contact` no longer log as bare `"write"` / unlogged
- [x] **GATE-07**: `MACOS_APPS_READ_ONLY=1 uv run pytest` passes (12 failures on develop today)
- [x] **GATE-08**: `_fake_envelope` is a shared fixture (`tests/envelope.py`) whose schema carries every column any `query_*` executor reads (incl. `m.size`, `message_references`); Mail tests that stubbed `query_*` only to compensate for a missing store go through the fixture; `HEADER_FINGERPRINT` covers those columns so a real store missing them surfaces as drift, not a query-time error
- [x] **GATE-09**: The recoverable destructive plane runs its own preflight — `recoverable(op, targets, act, *, dry_run, present)` performs check_batch → present → preview; a dry run without a stated `present` is an error; `dedupe_batch(dry_run=True)` can no longer report "planned" for targets it never checked; device-verified on a scratch mailbox with the Mail watchdog running, dry-run envelopes and osascript argv byte-identical to before
- [x] **GATE-10**: A tripwire test asserts every AppleScript template's `with timeout` backstop ≥ the host-side `timeout=` at every call site; `mail._DEDUPE` (600 < 900) fixed; `check_batch`'s refusal text no longer claims a backup for `update_status`; stale `daemon.py` comment removed
- [x] **GATE-11**: Doctor unit tests no longer run live `pgrep`/`ps` on the dev machine (17 tests go through the locked `tracked_run` seam)
- [x] **GATE-12**: The full device integration suite (`uv run pytest -m integration`) is green on the current macOS after the gate lands
- [x] **GATE-13**: Each gate cut is re-landed by rebasing onto the previous PR on `develop` (1 → 7 → 5 → 2; Mail-scoped 3/4/9 in parallel); after cards 5 and 2 the daemon is rebuilt, restarted and `doctor().version` + one outbound dry run confirm the gates still read correctly; `spike/arch-review-*` branches and `.claude/worktrees/` are deleted afterwards

### Mail — email work comes before any new or additional feature (owner, 2026-09-24)

- [x] **MAIL-01**: A full batch within the documented cap (25) finishes on a large IMAP mailbox: the host timeout for `_MOVE`, `_TRASH` and every `_PRESENT` call scales with the batch size (per-message budget × ids), each script's `with timeout` backstop stays ≥ its host cap, and `mail_undo` of a 25-message receipt finishes; device-verified on a 9k+ message mailbox with the watchdog running (#206)
- [x] **MAIL-02**: A timeout inside `recoverable()` still leaves a receipt — a `done` record with the unfinished ids as `unknown`, and an error that names the receipt and the safe next steps (re-run the batch; `mail_undo(<receipt>)`), never the generic `NativeTimeout` text (#206)
- [x] **MAIL-03**: `create_draft` takes an optional `from_address`, applied the way `send_mail` applies it; the locator reports `from`; the docstring says a new draft is unthreaded and routes replies to `mail_reply`; device-verified with a non-default account, and `mail_reply` keeps the receiving account on a multi-account Mac (#208)
- [x] **MAIL-04**: A device probe settles what Mail does with a `from_address` that no account owns; the finding lands in `docs/mail-applescript-facts.md`; if Mail does not reject it, `send_mail` and `create_draft` refuse an unowned address before any native write, and the outbound dry run still makes no native call (#208)
- [x] **MAIL-05**: `rollback()`'s unverified delete of a windowless outgoing message has a decided, device-probed handling (retry, another mitigation, or a documented caller contract); an outbound call that leaves a message behind says so loudly; the #229 xfail is removed or its reason names the decision (#229)
- [x] **MAIL-06**: Five dedicated device runs, on a message in an account a probe may target, decide the reply quote's read of the original: 5 of 5 passing removes the non-strict xfail; any failure ships a mitigation and a facts entry that separates a transient event-queue stall from the permanent wedge (#230)

### Bugs — bugs and errors come before any feature (owner, 2026-10-11)

- [x] **FIX-01**: Every audit record carries `dry_run: true|false`, resolved from the tool's signature default when the caller omits it, and a `caller` field; a test covers a write tool called without `dry_run` and its record states `dry_run: true` (#222)
- [x] **FIX-02**: The cause of the `contacts("an")` 30 s timeout on the Intel iMac is found (narrow-query timing, Script Editor timing, Contacts state) and fixed — by a bulk read that runs the `whose` scan once, a contacts-specific host timeout with the script backstop at or above the host cap, or an error text that names the cause (the SQLite plane of #95 stays v2, CON-04); on the Intel iMac the broad query answers, or fails with an error that names the real cause (#334)
- [x] **FIX-03**: On the Intel iMac, `notes_all` returns the count Notes.app shows outside Recently Deleted; if the tool's SQLite filter drops a live note, the filter is fixed (#335)
- [x] **FIX-04**: On the Intel iMac, every account in `mail_overview` has a name, or a label that says why it has none; the cause of the raw UUID (removed account, stale name cache, or an account kind `every account` omits) is recorded (#336)
- [x] **FIX-05**: Through the daemon, `doctor(request=True)` with Photos quit reports the photos surface ok — or Phase 4 removes the Photos Automation probe and the issue closes as moot (#317, #337)
- [x] **FIX-06**: The Intel iMac device report carries the three corrections: the pass count, the Local-list subtask conclusion, and the machine line without firmware and security details; the same detail leaves every other tracked file (`docs/DAEMON.md`, the quick-task 261011-4iv PLAN and SUMMARY) (#333)
- [x] **FIX-07**: `scripts/build_app.sh` installs the bundled `macos_apps_mcp` package from a wheel built in a hash-pinned build environment — hatchling and its build dependencies come from a hashed constraints file or lock, never fresh and unhashed from PyPI under build isolation; the `--no-deps` install and the D-16 export guard stay as they are (#373)
- [x] **FIX-08**: A `FileExistsError` from `files.target_path` and an `OSError` from the `mkdir` in `files.resolve_dest` reach the client as a typed tool error with an error kind and the agent-directed text, for `save_mail_attachment`, `export_mail` and `export_photo`, so a caller can tell the never-overwrite refusal from a crash; the Mail tests that pin the raw exception types follow (#383)
- [x] **FIX-09**: `[tool.ruff] target-version` is `py312`, matching `requires-python = ">=3.12"` (D-16), and the UP047 rewrites it raises land in the same PR with the suite and ruff green (#384)
- [x] **FIX-10**: `export_photo` leaves no hidden staging copy behind when the process is killed (SIGTERM, orphan `_exit`, SIGKILL): the staging prefix carries the pid and a later call removes only staging directories whose pid is dead, never a live one; and a staging cleanup error after a successful publish does not replace the written result — the outcome stands, the error is logged and the leftover directory is named (#387)
- [x] **FIX-11**: On the dashboard's write detail and recovery pages, a Mail mailbox renders as the account's name or address plus the decoded folder name (`Personal › INBOX`) — in the batch title, the `from` sources, the destination, the target rows and the undone banner — while the `imap://` URL stays internal; the name comes from the Mail adapter's process-local account cache through the existing seam, never a native call from a page load — the cache fills on the first Mail tool call after a daemon start, so until then the raw URL shows; every value is escaped (D-09) and an unknown account falls back to the raw URL (#427)
- [x] **FIX-12**: The dashboard passes the Phase 5 UI review's actionable findings: the `:focus-visible` ring is a solid `--color-primary` outline; the faint, success, outbound and orange text tokens measure at least 4.5:1 for text and 3:1 for UI glyphs in light mode; a refused toggle (409, 400) renders inside the page frame with a `banner warn`, a way back and the same status code, and the Restart form locks with the switches when the adapters file is unreadable; banner glyphs are `aria-hidden`, the switch `aria-label` names the adapter and its state, the sidebar links sit in a `<nav>` landmark behind a skip link, raw font sizes map to the type tokens, switch and sidebar rows reach 44px targets on phone and the System pages stay reachable in the phone strip — all inside the CSP (D-08), the sketch copy (D-11) and escaping (D-09) (#428)
- [x] **FIX-13**: The Phase 5 close review's deferred findings are closed: the test session patches `deploy._TCC_DB` and `deploy._TCC_SYSTEM_DB` to absent paths so no unit test opens the developer's TCC databases (WR-01); a `tool: "dashboard"` toggle or restart record renders on the write pages as an operator action with no `dry_run` row and no model chip (WR-03); a dashboard build or import failure in `daemon.serve()` is logged, sets `dashboard_state = "not built: …"` and MCP serves alone, with a test (WR-05); a toggle or restart whose audit record could not be written says so on the next page instead of a silent 303 (WR-06); and the adapter-name set and `_version` have one home, `dashboard/` modules import no underscore names across modules, `doctor` reports the dashboard URL only when a page can answer, and the deny-list is read once at import (IN-02..IN-05) (#430)
- [ ] **FIX-14**: On a Mac where no readable TCC database holds AppleEvents rows (macOS 27), the dashboard Health page and `doctor(request=False)` report each Automation adapter's grant from a live, non-prompting check — granted, denied, or not asked yet — and both give the same answer; a target app that is not running shows that its state cannot be told until the app runs, never a remediation to a setting that may already be on; the check sends no Apple Event and shows no prompt (D-14) and runs through `runtime.run_native()` on the single worker, so the Health page's `_WAIT` busy state still covers a worker held by a long Mail pass; unit tests pin `0`, `-1743`, `-1744`, `-600` and an unexpected return at the native seam with no real call; a device check from the installed daemon shows the bundle's own grants on the Health page (#455)
- [ ] **FIX-15**: `export_mail` never hides a written file: either every target path is checked before the first write and a collision refuses the whole batch with nothing written, or each id reports its own status (`written` / `exists`, as `absent` does today) and the call returns the files it wrote — so a retry after a refusal writes no duplicate; a unit test covers a batch whose later id meets an existing file (#399)
- [ ] **FIX-16**: A `mail_reply` or `reply_all` reply keeps Mail's native quote — quote bar, Mail's own attribution line, formatting and inline images, the whole original — with the reply text ahead of it. The plain-text `> ` quote failed the owner's look test on device (2026-10-27) and is removed. A device probe settles the route, and its finding lands in `docs/mail-applescript-facts.md`: (a) first, Mail's untouched native reply with the reply text pasted on top through the Accessibility API, never a write to the reply's `content` (every such write destroys the native quote, facts §4d); (b) only if (a) fails, a self-built styled HTML quote opened as the draft. When the proven route cannot run — its permission is off, the compose window is not the one the tool opened, or the reply text cannot be confirmed in place — the tool refuses, leaves no draft and sends nothing, and the error names the setting to change (owner, 2026-10-27). `doctor()` and the Health page report any new permission the route needs. Verified on device by inspecting the resulting draft and one delivered `reply_all`, with the Mail watchdog running (#348)
- [ ] **FIX-17**: `tests/test_doctor.py::test_report_stays_under_token_budget` pins `responsible_process` to its worst case (two 5-digit PIDs) as #183 and #318 pinned `app_process_info` and the TCC grant map, and the worst-case report stays under the budget — the report is shortened or the budget is restated with its reason in the test's comment — so the test passes whatever PIDs the test process has (#464)
- [ ] **FIX-18**: `reply_all(dry_run=True)` previews the reply's own recipients, not the original's header: `to` is the original's sender (its Reply-To when present), `cc` is the original's to + cc, minus every address of the sending account (read as the account that holds the original: the dry run builds no reply, so Mail's own pick of the sending account cannot be read; an original in one account addressed to another account's alias can preview that alias in cc — 2026-11-01, 05.2-15), without duplicates — the set Mail's reply-all addresses; the original's header, if still returned, sits under a separate key; the dry run still builds no outgoing message; a unit test with an original addressed to the account itself pins it (#516)

### Calendar

- [x] **CAL-01**: User can set alarms (minutes-before list) when creating or updating an event; they land as `EKAlarm`s and are read back by verify-after-write (#89)
- [x] **CAL-02**: Alarms on all-day and recurring all-day events fire on the right day in a non-UTC timezone (device-probed first, not fixed later) (#89)
- [x] **CAL-03**: User can create/update recurring events with `BYDAY` (incl. ordinals for monthly), `BYMONTHDAY`, `BYMONTH`; shapes EventKit cannot express are rejected loudly as today; accepted shapes are read back over six months and match RFC 5545 expansion (#90)
- [x] **CAL-04**: `events()` Pointers carry the owning calendar's id in `Pointer.folder` — the token `free_busy(calendars=…)`, `create_event` and `update_event` already take; `calendars()` maps ids to names; unit test on `_event_pointer` with a fake `calendar()` (#207)

### Reminders

- [x] **REM-01**: User can delete a reminder by id (`dry_run=True` default, verify-after-write, mirrors `delete_event`) (#92)
- [x] **REM-02**: User can create a reminder list (#92)
- [x] **REM-03**: User can read subtasks — `reminders()` Pointers carry the parent's id, read from the Reminders sqlite store and joined by id; no public write route exists (spike 002), so the write gap is named in the docstring (#91)
- [x] **REM-04**: Tags are investigated first; if no public write route exists they ship read-only (Reminders sqlite) with the write gap documented in the tool docstring — never a private-API write (#91)
- [x] **REM-06**: `reminders()` Pointers carry the owning list's id in `Pointer.folder` — same rule and test shape as CAL-04; `reminder_lists()` maps ids to names (#207)

### Notes

- [x] **NOTE-01**: Semantic search is evaluated first — a written decision on embedding model, chunking, index build/refresh policy, size cap and the optional-extra boundary before any indexing code (#93)
- [x] **NOTE-02**: If adopted: `notes_semantic(query)` returns Pointers from a sidecar index in the server's state dir (lazily built, size-capped, same shape as the Mail FTS sidecar), available only when the `[semantic]` extra is installed; base install gains no ML dependencies (#93)

### Photos

- [x] **PHO-01**: The Photos mechanism is settled by running `uv add osxphotos` on the deployment target (the pyproject "deferred: pyobjc conflict" note is likely stale); PhotoKit via PyObjC is the fallback (#96)
- [x] **PHO-02**: User can list albums as Pointers (#96)
- [x] **PHO-03**: User can read bounded metadata for a photo by id (dates, location, persons, EXIF subset) (#96)
- [x] **PHO-04**: User can export a photo by id to a destination directory (write-to-disk discipline; never inline image bytes) (#96)

### Platform

- [x] **PLAT-01**: Operator can enable/disable adapters per app (e.g. Mail on, Photos off) via a config setting read at daemon start; a disabled adapter's tools are absent, never registered-and-erroring — the same rule as the tiers; `doctor` reports the active set
- [x] **PLAT-02**: A localhost dashboard served by the daemon shows grants/`doctor`, `usage`, the audit trail, and the recoverable-plane backups (browsable recovery/history), and exposes the adapter toggles; loopback-only, no framework SPA (#126)

### Distribution

- [x] **DIST-01**: README leads with the published PyPI package (`uvx macos-apps-mcp`); clone-and-venv becomes the contributor path (#113)
- [x] **DIST-02**: `pyproject.toml` has `[project.urls]` so the PyPI page links to repo, issues, changelog (#111)
- [ ] **DIST-03**: Each release publishes a `.mcpb` bundle for one-click Claude Desktop install (#107)
- [ ] **DIST-04**: The notarized `.app` installs via a Homebrew cask (`brew install --cask …`), with the staple-then-zip order preserved (#107)
- [ ] **DIST-05**: A companion skill + Claude Code plugin live in-repo (`.claude-plugin/plugin.json`, `skills/<name>/SKILL.md`, `.mcp.json`) so `claude plugin install` wires skill + MCP server config in one step; the same `skills/` layout installs into other agents via `npx skills add elfensky/macos-apps-mcp`; the skill teaches the cockpit workflows (triage reads, pointer citation, draft-review) (#106)
- [x] **DIST-06**: `scripts/build_app.sh` builds the bundle on x86_64 (Intel) Macs — on x86_64 only, `cryptography<49` constrains the install (48.0.1, the last universal2 wheel); arm64 keeps current cryptography; the Intel bundle passes its env-free import smoke. Transitive and unused at runtime (`mcp → pyjwt[crypto] → cryptography`). Full Intel daemon deployment still needs a Developer-ID-signed build (#205)

## v2 Requirements

Deferred. Tracked but not in the current roadmap.

### Contacts (deferred 2026-08-28 — owner's call at roadmap review)

- **CON-01**: User can fetch a full, bounded contact card by id — all handles, addresses, birthday, organisation; the notes field is excluded by design (entitlement-gated, crashes updates) (#94)
- **CON-02**: User can fetch their own card (`contacts_me`) (#94)
- **CON-03**: User can update a contact by id (write tier, dry-runnable, audited, verify-after-write); native `CNContactStore` if the daemon's bundle identity is granted Contacts TCC (device spike), else the osascript update path — notes excluded either way (#94)
- **CON-04**: Contact search reads the AddressBook sqlite store when Full Disk Access is present and falls back to AppleScript otherwise; the schema fingerprint covers every column the queries read; `doctor` reports which plane is active (#95)

### Messages (deferred 2026-08-28 — owner's call at roadmap review)

- **MSG-01**: User can filter `messages_with` and `messages_search` by `since`/`until` (#88)
- **MSG-02**: User can filter for unread incoming messages (#88)
- **MSG-03**: Message Pointers are annotated with attachment name/type when present (#87)
- **MSG-04**: User can search attachments (by contact, date, MIME) as bounded Pointers (#87)
- **MSG-05**: User can save one attachment to disk by id (`mail_files` discipline: derived basename, allowlisted root, no silent overwrite, size cap; never inline bytes) (#87)
- **MSG-06**: User can send an iMessage/SMS (outbound tier: registered only under `allow-send messages`, `dry_run=True` default, dry-run makes no native call); recipient is an id-addressed handle or `chat_id` — no fuzzy auto-pick; iMessage-vs-SMS routing and group chats device-verified like Mail's outbound lifecycle (#86)
- **MSG-07**: User can check whether a handle is iMessage-reachable (ungated read) (#86)

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

### Mail

- **MAIL-05**: Move/trash dry-run previews answered from the Envelope Index (message-id → mailbox url) with no Apple Events; the index can lag Mail, which is why #174's re-check exists (#206 follow-up)

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
| GATE-01 | Phase 1 | Complete |
| GATE-02 | Phase 1 | Complete |
| GATE-03 | Phase 1 | Complete |
| GATE-04 | Phase 1 | Complete |
| GATE-05 | Phase 1 | Complete |
| GATE-06 | Phase 1 | Complete |
| GATE-07 | Phase 2 | Complete |
| GATE-08 | Phase 1 | Complete |
| GATE-09 | Phase 1 | Complete |
| GATE-10 | Phase 1 | Complete |
| GATE-11 | Phase 2 | Complete |
| GATE-12 | Phase 2 | Complete |
| GATE-13 | Phase 1 | Complete |
| MAIL-01 | Phase 02.1 | Complete |
| MAIL-02 | Phase 02.1 | Complete |
| MAIL-03 | Phase 02.1 | Complete |
| MAIL-04 | Phase 02.1 | Complete |
| MAIL-05 | Phase 3 | Complete (0.13.1, ahead of the phase) |
| MAIL-06 | Phase 3 | Complete (0.13.1, ahead of the phase) |
| CAL-01 | Phase 3 | Complete |
| CAL-02 | Phase 3 | Complete |
| CAL-03 | Phase 3 | Complete |
| CAL-04 | Phase 3 | Complete |
| REM-01 | Phase 3 | Complete |
| REM-02 | Phase 3 | Complete |
| REM-03 | Phase 3 | Complete |
| REM-04 | Phase 3 | Complete |
| REM-06 | Phase 3 | Complete |
| FIX-01 | Phase 03.1 | Complete |
| FIX-02 | Phase 03.1 | Complete |
| FIX-03 | Phase 03.1 | Complete |
| FIX-04 | Phase 03.1 | Complete |
| FIX-05 | Phase 03.1 | Complete |
| FIX-06 | Phase 03.1 | Complete |
| FIX-07 | Phase 04.1 | Complete |
| FIX-08 | Phase 04.1 | Complete |
| FIX-09 | Phase 04.1 | Complete |
| FIX-10 | Phase 04.1 | Complete |
| NOTE-01 | Phase 4 | Complete |
| NOTE-02 | Phase 4 | Complete |
| PHO-01 | Phase 4 | Complete |
| PHO-02 | Phase 4 | Complete |
| PHO-03 | Phase 4 | Complete |
| PHO-04 | Phase 4 | Complete |
| PLAT-01 | Phase 5 | Complete |
| PLAT-02 | Phase 5 | Complete |
| FIX-11 | Phase 05.1 | Complete |
| FIX-12 | Phase 05.1 | Complete |
| FIX-13 | Phase 05.1 | Complete |
| FIX-14 | Phase 05.2 | Pending |
| FIX-15 | Phase 05.2 | Pending |
| FIX-16 | Phase 05.2 | Pending |
| FIX-17 | Phase 05.2 | Pending |
| FIX-18 | Phase 05.2 | Pending |
| DIST-01 | Phase 6 | Complete |
| DIST-02 | Phase 6 | Complete |
| DIST-03 | Phase 6 | Pending |
| DIST-04 | Phase 6 | Pending |
| DIST-05 | Phase 6 | Pending |
| DIST-06 | Phase 6 | Complete |

**Coverage:**

- v1 requirements: 60 total
- Mapped to phases: 60
- Unmapped: 0 ✓

**Phase totals:** Phase 1: 10 · Phase 2: 3 · Phase 02.1: 4 · Phase 3: 11 · Phase 03.1: 6 · Phase 4: 6 · Phase 04.1: 4 · Phase 5: 2 · Phase 05.1: 3 · Phase 05.2: 5 · Phase 6: 6

**Open issues with no requirement:** #180 is a convention decision, recorded in PROJECT.md Key Decisions; #101, #102 and #103 are Out of Scope.

---
*Requirements defined: 2026-08-28*
*Last updated: 2026-10-31 — DIST-01, DIST-02 and DIST-06 marked complete: landed as quick tasks in October (#113, #111, #205 closed); 60/60 mapped*
