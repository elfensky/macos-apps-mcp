# Stack Research

**Domain:** New-capability stack for macos-apps-mcp (Contacts, Calendar/Reminders depth, Messages depth, Photos, Safari, Maps/Location, Weather, Capture/System, Platform/Distribution)
**Researched:** 2026-08-28
**Confidence:** MEDIUM overall (library/version facts verified against official repo sources and PyPI; several macOS-behavior facts — headless CoreLocation, MapKit throttling — rest on community/forum reports rather than Apple documentation, and are flagged LOW/MEDIUM individually; the project's own "probe first" discipline applies directly to those)

This is a **subsequent-milestone** stack doc. It assumes everything in `.planning/codebase/STACK.md` (FastMCP, `uv`, PyObjC EventKit, sqlite read planes, launchd daemon, `httpx`/`uvicorn`) is already shipped and does not re-justify it. Every recommendation below is scoped to the eight new-capability areas in the milestone brief.

## Recommended Stack

### Core Technologies — by domain

| Domain | Technology | Version | Purpose | Why Recommended |
|--------|------------|---------|---------|-----------------|
| Contacts | `pyobjc-framework-Contacts` | `>=10.0` (latest 12.1, Nov 2025) | `CNContactStore` full cards, `me` card, update | Same PyObjC-bridge shape as the shipped EventKit adapter; version floor matches the repo's existing `pyobjc-framework-EventKit>=10.0` pin so `uv` resolves one consistent `pyobjc-core` |
| Contacts | `sqlite3` (stdlib) + existing `_open_sqlite_ro()` | n/a | Fast fuzzy/prefix search over `AddressBook-v22.abcddb` | Same read-plane pattern as `chat.db`/`NoteStore.sqlite` — CNContactStore's own `CNContactFetchRequest` predicate matching is slow/limited for "search-as-you-type"; the sqlite index is what Contacts.app itself uses for search |
| Calendar/Reminders | `pyobjc-framework-EventKit` | `>=10.0` (already pinned) | `EKAlarm` relative offsets, `EKRecurrenceRule` full initializer for BYDAY/BYMONTHDAY/BYSETPOS | No new dependency — the gap is API usage, not library choice (see Patterns below) |
| Messages | stdlib `sqlite3` (existing `chat.db` read plane) | n/a | `attachment` / `message_attachment_join` join, `is_read`, date-range filters | No new dependency; schema is stable and already partially read by the shipped adapter |
| Messages (send) | `osascript` (existing dispatch path) | n/a | iMessage/SMS routing through `Messages.app`'s scripting dictionary | No native Messages send API exists at all (public or private) — AppleScript is the only mechanism, same as Mail's outbound story |
| Photos (read) | `osxphotos` | `0.73.x` (PyPI, actively released; Context7 `/rhettbull/osxphotos`) | Albums, metadata, export, Photos library introspection | Mature (RhetTbull), tracks every Photos DB schema change back to Photos 2.0 through macOS 26/27 previews; parses `Photos.sqlite` directly — no PhotoKit round-trip needed for read-only work |
| Photos (write, deferred) | `photokit` (RhetTbull) | `0.2.x`, wraps `pyobjc-framework-Photos>=9.2,<11.0` | Album creation/membership, favorite toggling — only if a write requirement actually lands | Thin, actively maintained Pythonic wrapper over PhotoKit; don't hand-roll raw `PHPhotoLibrary` PyObjC calls for the same result |
| Safari | stdlib `plistlib` + `sqlite3` | n/a | `Bookmarks.plist` (bookmarks + Reading List), `History.db` | No dependency needed at all — both are stdlib-readable formats; this is the cheapest of every new domain |
| Maps | `pyobjc-framework-MapKit` | `>=10.2` (latest; last released Mar 2024 — see flag below) | `MKLocalSearch`, `MKDirections` | Only PyObjC binding that exposes these classes; no alternative exists outside Swift |
| Location | `pyobjc-framework-CoreLocation` | `>=12.2.2` | `CLLocationManager`, `CLGeocoder` | Only PyObjC binding for CoreLocation; actively released in lockstep with `pyobjc-core` |
| Weather | none (plain `httpx`, already a dependency) | n/a | REST calls to Open-Meteo | Open-Meteo is a clean JSON API with no SDK needed; adding a weather SDK would be the only new dependency in this domain and buys nothing over two `httpx.get()` calls |
| Capture | `/usr/bin/screencapture` via `subprocess` (existing osascript/CLI dispatch pattern) | n/a (OS-bundled) | Screenshot capture | Apple's own first-party CLI already handles the ScreenCaptureKit migration internally; no PyObjC ScreenCaptureKit bindings needed |
| System utilities | `/usr/bin/pbcopy`, `/usr/bin/pbpaste`, `/usr/bin/mdfind`, `osascript "display notification"` | n/a (OS-bundled) | Clipboard, Spotlight, notifications | Same dispatch pattern as `shortcuts` CLI — no library needed |
| Platform: auth | `fastmcp.server.auth` bearer verifier (built into `fastmcp`, already a dependency) | fastmcp `>=3.2` (Context7 `/prefecthq/fastmcp`, current 3.2.4) | Gate `streamable-http` transport with a static long-lived token | No new dependency; FastMCP ships bearer-token verification and `OAuthProxy` out of the box |
| Platform: distribution | `@anthropic-ai/mcpb` (npm, dev-time only, not a runtime dep) | current (spec adopted Nov 2025, successor to `.dxt`) | Package the server as a `.mcpb` bundle | Now the cross-client, Anthropic-maintained spec — `.dxt` is legacy naming |
| Platform: menubar companion | Swift + SwiftUI `MenuBarExtra` (new, separate target — NOT a Python dependency) | Swift 6 / macOS 13+ SDK | Lifetime stats, browsable recovery/history UI, client of the daemon | See "What NOT to Use" — a second Python interpreter (`rumps`/`pystray`) is the wrong shape for a UI-only client of an already-running daemon |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pyobjc-framework-Cocoa` | `>=10.0` (already pinned) | `NSRunLoop` pumping for async PyObjC completion-handler APIs | `MKLocalSearch`/`MKDirections`/`CLLocationManager` are all async/delegate-based — the worker thread needs to pump a run loop (or block on a semaphore released from the completion handler) the same way any PyObjC async call would, inside `runtime.run_native()`'s existing single worker |
| `CoreLocationCLI` (external signed binary, not a pip package) | n/a | Fallback location source if headless `CLLocationManager` proves TCC-blocked | Only if the device probe for #99 confirms the daemon cannot get a location prompt at all when launched by launchd with no GUI session (see Pitfalls-adjacent flag below) |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| `mcpb` CLI (`npx @anthropic-ai/mcpb pack` / `validate`) | Build and lint the `.mcpb` bundle for #107 | Dev-time only, no runtime footprint on the daemon |
| Homebrew `brew audit`/`brew style` | Validate the cask formula for #107 | Homebrew now requires code-signing + notarization for any cask on the official tap (deprecation of unsigned casks lands by September 2026) — this repo already signs+notarizes, so the formula itself is the only new work |

## Installation

```bash
# Contacts
uv add "pyobjc-framework-Contacts>=10.0"

# Photos (read plane) — verify pyobjc-core resolution before committing (see Version Compatibility)
uv add osxphotos

# Maps / Location
uv add "pyobjc-framework-MapKit>=10.2" "pyobjc-framework-CoreLocation>=12.2"

# Weather, Capture, System utilities, Safari — no new packages
# (httpx already present; screencapture/pbcopy/pbpaste/mdfind are OS binaries; plistlib/sqlite3 are stdlib)

# Dev-time only (bundle packaging, not a runtime dependency)
npx -y @anthropic-ai/mcpb pack .
```

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|--------------------------|
| Contacts sqlite for search, `CNContactStore` for full-card read/write | AppleScript/Automation dictionary (today's shipped adapter, per pyproject.toml comment) | Only if the daemon's bundle identity (#71) turns out **not** to hold `kTCCServiceContacts` cleanly — the comment blocking `CNContactStore` predates #71's signed-daemon architecture and should be re-probed, not assumed still true |
| `osxphotos` for reads | `photokit` / raw `pyobjc-framework-Photos` for reads too | Never for pure reads — `osxphotos` is faster (no live PhotoKit round-trip) and more complete (keywords, faces, albums, geolocation in one pass) |
| `.mcpb` | `.dxt` | Never — `.dxt` is the deprecated predecessor name; any doc or tool still referencing it should be treated as legacy |
| Open-Meteo | wttr.in | Only for a throwaway/manual CLI check — wttr.in's plaintext/ASCII-art output format is a bad fit for a typed `Pointer`-based tool response; Open-Meteo's JSON contract fits the architecture directly |
| Open-Meteo | WeatherKit | Never for this project — WeatherKit requires enrolling in the paid Apple Developer Program and JWT-signing service tokens; already ruled entitlement-blocked in PROJECT.md #100 |
| SwiftUI `MenuBarExtra` companion | `rumps` (Python/PyObjC) | Only if the team decides the companion must stay 100% Python for maintenance-locality reasons — accept the cost of a second bundled interpreter and the coupling risk CLAUDE.md's "companion must not become the server" note is guarding against |
| Bearer-token auth on `streamable-http` | `OAuthProxy` + `JWTVerifier` (full OAuth) | Only if a real third-party IdP or multi-user access model shows up later — for a single-operator LAN/Tailscale tool, standing up OAuth redirect/callback endpoints is attack surface with no corresponding benefit |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|--------------|
| `rumps` / `pystray` for the menubar companion | Both require a second Python interpreter idling in the menu bar; `rumps` is a low-activity solo-maintainer PyObjC/AppKit wrapper, `pystray` is a cross-platform lowest-common-denominator library that doesn't use native macOS menu idioms at all. Either risks import-time coupling back into the daemon's own venv/adapters, undermining CLAUDE.md's "the companion must not become the server" | A standalone SwiftUI `MenuBarExtra` binary that only talks to the daemon's existing unix socket / reads its existing `audit.jsonl` — a structurally separate process, not a shared runtime |
| Raw `pyobjc-framework-Photos` (`PHPhotoLibrary`/`PHAsset`) for anything read-only | Duplicates what `osxphotos` already does faster and more completely by parsing the library database directly | `osxphotos` |
| WeatherKit | Entitlement-gated behind the paid Apple Developer Program + signed JWT service tokens — heavyweight for a personal-scale tool and already ruled out in PROJECT.md #100 | Open-Meteo (keyless REST/JSON) |
| A bespoke ScreenCaptureKit PyObjC integration | Apple's own `screencapture` CLI already handles the Sonoma/Sequoia ScreenCaptureKit migration internally; hand-rolling `SCContentSharingPicker`/`SCStream` bindings is materially more code for the same "take one screenshot" outcome | `/usr/bin/screencapture` via subprocess, same dispatch shape as the existing `shortcuts` CLI adapter |
| Building Reminders "tags"/"subtasks" against a real EventKit property | **No public API exists.** `FradSer/mcp-server-apple-events` — the named prior-art reference — implements "subtasks" by encoding a checklist as text inside the reminder's `notes` field, and there is no public `EKReminder` tags property at all (Reminders' UI-visible tags/flags live in a private, unversioned store outside EventKit) | Either explicitly scope #91 down to the notes-field-encoding convention (documented as a hack, matching prior art) or mark tags/subtasks out-of-scope like Journal — do not attempt to read/write Reminders' private database |
| Full OAuth (`OAuthProxy`) as the first cut of #127 remote auth | Requires a real upstream IdP and callback infrastructure; adds attack surface disproportionate to a single-operator tailnet tool | FastMCP's built-in static bearer-token verification, combined with binding the socket to the Tailscale interface IP (not `0.0.0.0`) and `allowed_hosts`/`allowed_origins` |
| `wttr.in` as the weather backend | Undocumented rate-limit behavior, single-maintainer service, plaintext/ASCII-art-first output that would need scraping/parsing to fit the typed response contract | Open-Meteo |

## Stack Patterns by Variant

**Contacts — full cards + `me` card + update (#94):**
- Use `CNContactStore.requestAccessForEntityType_completionHandler_(CNEntityTypeContacts, ...)` then `CNContactStore.unifiedMeContactWithKeysToFetch_error_()` for the `me` card and `CNContactFetchRequest`/`CNSaveRequest` for read/update — this is a synchronous-callback pattern, same run-loop-pumping shape as the Maps/Location APIs below.
- **Exclude the `notes` key from `keysToFetch`.** Reading or writing `CNContact.note` requires the `com.apple.developer.contacts.notes` entitlement, which Apple grants only through a manual request-and-justification process per developer account — treat this exactly like WeatherKit: explicitly out of scope, not a bug.
- Because #71 already ships the daemon as a signed bundle holding its own TCC identity for EventKit, the same bundle identity is the correct place to hold `kTCCServiceContacts` too — re-probe (don't assume) whether the AppleScript-only decision in the current `pyproject.toml` comment is still necessary now that the signed-daemon architecture exists.

**Calendar/Reminders — alarms + extended recurrence (#89, #90):**
- `EKAlarm.alarmWithRelativeOffset_(seconds)` is a classmethod usable identically on `EKEvent.alarms` and `EKReminder.alarms` — same alarm object type for both, no per-adapter divergence needed.
- BYDAY-with-ordinal (e.g. "2nd Tuesday") and BYSETPOS require dropping the simple `initRecurrenceWithFrequency_interval_end_` initializer (likely what's shipped today) for the full designated initializer: `initRecurrenceWithFrequency_interval_daysOfTheWeek_daysOfTheMonth_monthsOfTheYear_weeksOfTheYear_daysOfTheYear_setPositions_end_`. `daysOfTheWeek` takes a list of `EKRecurrenceDayOfWeek` objects (`dayOfTheWeek` + `weekNumber`), **not** plain weekday integers — this is the concrete trap: a naive port of the simple initializer's weekday list will not compile against the ordinal-aware signature.
- **Tags and subtasks have no public EventKit API at all** — see "What NOT to Use" above. This should be a scoping conversation for #91 before planning, not a research gap to close later.

**Messages — depth (#87, #88, #86):**
- `attachment` and `message_attachment_join` join on `message.ROWID` / `attachment.ROWID`; attachment file paths are stored with a `~/`-relative prefix needing `os.path.expanduser` before opening.
- `is_read` is a plain boolean column on `message` — trivially filterable.
- Message `date` columns are Apple's Mac-absolute-time-in-nanoseconds (post-High Sierra) vs seconds (pre-High Sierra) — reuse whatever epoch-conversion helper the existing `messages.py` read path already has rather than re-deriving it; do not assume Unix epoch.
- Send: `tell application "Messages" to send "<text>" to buddy "<handle>" of (service 1 whose service type is iMessage)` for iMessage; `of service "SMS"` for SMS. **Guard SMS sends with `exists service "SMS"` first** — a Mac with no paired iPhone doing SMS relay/Continuity has no SMS service registered at all, and the naive `of service "SMS"` form will error rather than silently falling back to iMessage.

**Photos (#96):**
- Read plane: `osxphotos.PhotosDB()` against the default library path; export via its existing `export()` machinery, which already handles Live Photos, edited-vs-original selection, and sidecar metadata — do not reimplement export logic.
- **Re-verify the pyproject.toml "pyobjc-core conflict" before treating Photos as blocked.** `osxphotos`'s actual dependency floor (fetched directly from its `requirements.txt`) is conditional: `pyobjc-core<10` only applies when `platform_release < '22.0'` (pre-Ventura) **and** `python_version < '3.12'`. This repo already prefers "Ventura or later" and already tests Python 3.12/3.13 — on that combination `osxphotos` requires `pyobjc-core>=10.0`, the same floor as the shipped `pyobjc-framework-EventKit>=10.0`. The conflict recorded in `pyproject.toml` is very likely stale for the actual deployment target and should be re-checked with a real `uv add osxphotos` before being treated as a blocker in the roadmap.
- Defer `photokit`/write access entirely until a specific write requirement (e.g. "add to album") is confirmed — YAGNI.

**Safari (#97):**
- Reading List is **not** a separate file — it's nested inside `Bookmarks.plist` as a child bookmark bar folder entry with `WebBookmarkType == "ReadingListBookmark"`, carrying its own `ReadingList` sub-dict (`DateAdded`, `PreviewText`, fetch status). Parsing code should walk the existing bookmark tree, not look for a second plist.
- `History.db`: query `history_visits` (per-visit `visit_time`) joined to `history_items` (URL) for any time-range work; `history_items.last_visit_time` is only the aggregate, not a substitute for the visits table.
- Dates in both files are Mac absolute time (seconds since 2001-01-01 UTC) — a different epoch than the Messages `chat.db` nanosecond convention above; do not share a conversion constant between the two adapters without checking units.

**Maps / Location — new domain (#98, #99):**
- `MKLocalSearch` and `MKDirections` are async/completion-handler APIs — the worker thread needs a run-loop pump or a blocking semaphore released from the completion handler, the same integration shape needed for `CLLocationManager`.
- **Bundle-identity throttling is shared across every caller of this daemon**, because every Maps request goes out under the one `ren.lav.macos-apps-mcp` bundle identity (same TCC-identity design as #71). Community reports put the informal ceiling around 50 requests/60s before `MKErrorDomain` code 4 (`loadingThrottled`). The adapter should self-throttle client-side well under that ceiling and surface throttling as a typed, retryable error — do not let one caller's Maps burst exhaust the daemon-wide budget silently.
- **CoreLocation is the one area where the "probe first" project discipline is load-bearing, not optional.** Multiple independent reports say that since macOS Sonoma, CLI/headless processes requesting location are denied *without any prompt at all* — there is no GUI session for `tccd` to show a dialog against, and a bootstrapped launchd agent has nowhere to render one. This is qualitatively different from EventKit/Contacts/Automation, whose one-time consent dialogs a background process CAN still trigger. Before planning #99: run the actual signed `.app` under launchd with no user logged in and check whether `CLLocationManager.authorizationStatus()` ever leaves `notDetermined`. If it's confirmed blocked, `CLGeocoder` (forward/reverse geocoding, no location permission needed at all) should ship regardless, and "current location" should either be deferred, take a user-supplied coordinate, or shell out to a known community workaround binary (`CoreLocationCLI`) rather than trying to force a GUI-only permission model into a headless daemon.

**Weather (#100):**
- Open-Meteo's forecast + geocoding endpoints are unauthenticated GET requests returning JSON — implement with the already-present `httpx`, no SDK. 10,000 calls/day free-tier ceiling is far beyond what a personal-scale tool will hit.

**Platform — auth, distribution, companion (#127, #107, #106, menubar):**
- Auth: FastMCP's `http_app()` already exposes `allowed_hosts`/`allowed_origins` alongside its `auth=` parameter — layer a static bearer token with a Tailscale-only bind address and a Host-header allowlist rather than reaching for `OAuthProxy` on day one.
- Distribution: adopt `.mcpb` (not `.dxt`) for one-click local install, and a Homebrew cask formula for the signed `.app` — both are packaging-only work since the repo already signs+notarizes.
- Companion: SwiftUI `MenuBarExtra`, a genuinely separate binary/target, talking only to the daemon's existing unix socket and reading its existing `audit.jsonl` — no new IPC mechanism needed, and no shared Python runtime with the daemon.

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|------------------|-------|
| `pyobjc-framework-EventKit>=10.0` (shipped) | `pyobjc-framework-Contacts>=10.0`, `pyobjc-framework-MapKit>=10.2`, `pyobjc-framework-CoreLocation>=12.2` | All `pyobjc-framework-*` packages are released in lockstep with `pyobjc-core` from the same upstream monorepo (`ronaldoussoren/pyobjc`) — leave every framework package unbounded (matching the repo's existing convention: "Runtime deps stay unbounded above — capping them downgraded EventKit/fastmcp, so don't") and let `uv` converge on one `pyobjc-core` version across all of them |
| `osxphotos` | `pyobjc-core>=10.0` (Ventura+/Python 3.12+) or `pyobjc-core>=9.0,<10.0` (Monterey/Python<3.12) | Conditional pin verified directly from `osxphotos`'s `requirements.txt` (`sys_platform == 'darwin' and platform_release < '22.0' and python_version < '3.12'` for the `<10.0` branch). On this repo's preferred deployment target (Ventura+, Python 3.12/3.13 already in the test matrix) the two floors already agree — run `uv add osxphotos` to confirm the resolver picks the `>=10.0` branch before relying on this in the roadmap |
| `pyobjc-framework-MapKit` | last released 10.2 (Mar 2024) | Flagged LOW-MEDIUM confidence: this is the least-recently-updated PyObjC framework binding surveyed here. MapKit's Objective-C surface is stable, so this is likely a non-issue, but it means less real-world coverage of very new MapKit symbols than the other frameworks — spike `MKLocalSearch` from a bare script early rather than assuming full coverage |
| `fastmcp>=2.0` (shipped, unbounded) | fastmcp `3.2.x` current | Confirmed via Context7 (`/prefecthq/fastmcp`) that `OAuthProxy`, `JWTVerifier`, and `http_app(allowed_hosts=..., allowed_origins=...)` are all present in the 3.x line already installed by the unbounded pin — no version bump needed for the platform work |

## Sources

- Context7 `/rhettbull/osxphotos` — `_constants.py` tested DB/model versions through macOS 26/27 previews, `PhotosDB` API surface. MEDIUM confidence.
- Context7 `/prefecthq/fastmcp` — bearer auth, `OAuthProxy`/`JWTVerifier`, `http_app()` signature (`allowed_hosts`, `allowed_origins`, `host_origin_protection`). MEDIUM confidence.
- Direct fetch of `https://raw.githubusercontent.com/RhetTbull/osxphotos/main/requirements.txt` — exact conditional `pyobjc-core` pin. MEDIUM confidence (primary source file, not narrated).
- Direct fetch of `https://raw.githubusercontent.com/RhetTbull/photokit/main/pyproject.toml` — `pyobjc-framework-Photos>=9.2` floor. MEDIUM confidence.
- PyPI listings for `pyobjc-framework-Contacts` (12.1), `pyobjc-framework-MapKit` (10.2), `pyobjc-framework-CoreLocation` (12.2.2), `pyobjc-framework-EventKit` (12.2.1). MEDIUM confidence (WebSearch-summarized PyPI pages).
- `github.com/johnlarkin1/imessage-schema`, `michaelwornow.net` (2024-12) — `chat.db` and `AddressBook-v22.abcddb` table schemas. MEDIUM confidence (community-maintained schema docs, cross-checked against multiple independent sources).
- Apple Developer Forums threads (multiple, aggregated via WebSearch) — `com.apple.developer.contacts.notes` entitlement approval process; headless `CLLocationManager` denial on Sonoma+; `MKLocalSearch`/`MKDirections` throttling behavior (~50 req/60s, `MKErrorDomain` code 4). LOW-MEDIUM confidence — forum reports, not Apple's written documentation; treat the CoreLocation and MapKit-throttling claims as **probe targets**, not settled facts, consistent with this project's own verification culture.
- `github.com/FradSer/mcp-server-apple-events` (README, via WebSearch) — confirms no public EventKit API for Reminders tags/subtasks; that project encodes subtasks as notes-field text. MEDIUM confidence (project's own documentation of its own workaround).
- `blog.modelcontextprotocol.io/posts/2025-11-20-adopting-mcpb`, `github.com/modelcontextprotocol/mcpb` — `.mcpb` spec adoption, successor to `.dxt`. MEDIUM confidence.
- Homebrew cask signing/notarization requirement (deprecation of unsigned casks by September 2026) — aggregated via WebSearch from Homebrew-adjacent sources. MEDIUM confidence.
- `docs.brew.sh/Acceptable-Casks`, `anthropics/claude-code` `.claude-plugin/marketplace.json` (via WebSearch) — plugin/marketplace packaging shape. MEDIUM confidence.
- Open-Meteo pricing page, general weather-API comparison roundups (via WebSearch) — keyless rate limits (10,000 calls/day). MEDIUM confidence.
- cmsj.net (2015) AppleScript Messages send syntax, cross-checked against multiple current (2026) forum threads reporting the same `service "SMS"` / `service type is iMessage` syntax still works. MEDIUM confidence.

---
*Stack research for: macos-apps-mcp new-capability milestone (Contacts, Calendar/Reminders depth, Messages depth, Photos, Safari, Maps/Location, Weather, Capture/System, Platform)*
*Researched: 2026-08-28*
