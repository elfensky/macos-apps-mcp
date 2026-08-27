# Project Research Summary

**Project:** macos-apps-mcp (target milestone: spiked architecture review gate → adapter depth parity → new domains → platform & DX)
**Research Completed:** 2026-08-28
**Research Files:** STACK.md, FEATURES.md, ARCHITECTURE.md, PITFALLS.md

---

## Executive Summary

This is a **subsequent-milestone synthesis** on a shipped MCP server (0.10.1). The research confirms both the gate's technical soundness and its critical sequencing constraint: the refactor of registration, tier policy, and module boundaries (cards 1, 7, 5, 2) must land before adapter-depth work begins, because three of those cards directly reshape the files (server.py, runtime.py, doctor.py) that every new adapter will touch. The milestone's real complexity is not in new adapter logic — Calendar alarms, Messages attachments, Photos export are all precedent-heavy, medium-complexity integrations — but in (1) landing the gate's pure-move refactors in dependency order without reintroducing the timing-dependent bugs that #166 already had to fix, and (2) device-probing five genuinely open feasibility questions (headless CoreLocation, MapKit throttling, CNContactStore TCC in daemon mode, Reminders private-API tags, Notes embeddings refresh policy) before committing scope around them.

The stack research confirms all recommended technologies are available at current versions, with two key findings: the osxphotos dependency conflict claimed in pyproject.toml is **very likely stale** (should be re-verified with `uv add osxphotos` on the actual deployment target), and **MapKit's last PyObjC binding update was March 2024**, so the first Maps adapter work should include a spike to confirm all relevant MapKit symbols are covered. Weather is decidedly keyless HTTP (WeatherKit is confirmed entitlement-blocked per the issue itself), and the Home Assistant integration requires not just auth-gated Tailscale transport but also an SSE-speaking bridge — streamable-HTTP alone (today's transport) will not work with HA's MCP Client integration.

## Key Findings

### From STACK.md

**Recommended Core Technologies:**

| Domain | Technology | Rationale |
|--------|-----------|-----------|
| Contacts | `CNContactStore` (daemon mode only, via PyObjC) | Same thread-affinity pattern as EventKit; daemon's TCC bundle identity makes it viable; **exclude notes field (entitlement-gated, unachievable)** |
| Contacts search | `sqlite3` on `AddressBook-v22.abcddb` | Fast search (100× speedup) via existing `read_via_sqlite` pattern; needs Full Disk Access |
| Photos (read) | `osxphotos` 0.73.x | Mature, schema-aware; **verify dependency conflict is stale before committing** |
| Maps / Location | `pyobjc-framework-MapKit>=10.2`, `pyobjc-framework-CoreLocation>=12.2.2` | Only bindings available; MapKit last updated Mar 2024 (LOW-MEDIUM confidence — spike early) |
| Weather | `httpx` + Open-Meteo REST (keyless) | No auth needed; 10k calls/day free tier; WeatherKit ruled out as entitlement-blocked |
| Safari | `plistlib` (stdlib) + `sqlite3` | Bookmarks.plist + History.db; no new dependencies |
| Messages send | `osascript` + existing outbound tier | No native Messages send API exists; reuses Mail's 0.9.0 tier infrastructure |
| Capture | `/usr/bin/screencapture` via `subprocess` | Apple's own CLI handles Sonoma/Sequoia ScreenCaptureKit migration internally |
| Platform auth | FastMCP 3.2+ bearer token + Tailscale bind | No new dependency; static token on loopback-only until #127 adds network transport |
| Platform distribution | `@anthropic-ai/mcpb` (npm, dev-time) + Homebrew cask | `.mcpb` is the current spec (`.dxt` is legacy); brew cask requires code-signing + notarization (already done) |
| Menubar companion | Swift 6 + SwiftUI `MenuBarExtra` | **Not Python** — a separate binary client of the daemon over UDS, not a second interpreter |

**Critical Confidence Notes:**

- **osxphotos dependency conflict (HIGH-RISK TODO before adapter-depth planning):** pyproject.toml comments a `pyobjc-core` conflict that STACK research traces to a conditional floor (`<10.0` only on Monterey + Python < 3.12). The repo already targets Ventura+ and tests Python 3.12/3.13, so the conflict **is very likely stale**. Run `uv add osxphotos` on the actual deployment target to confirm it resolves to `pyobjc-core>=10.0` (same as shipped EventKit floor) before scoping #96 (Photos) into a phase.

- **MapKit binding coverage (MEDIUM-CONFIDENCE, spike-required):** Last PyObjC update for MapKit was March 2024 (oldest in the surveyed set). Objective-C MapKit API surface is stable, so this is likely not an issue, but spike the exact `MKLocalSearch`/`MKDirections` symbols from a bare script early rather than assuming full coverage.

- **Headless CoreLocation TCC (OPEN FEASIBILITY QUESTION, spike-gated):** Multiple independent forum reports (not Apple documentation) claim CLLocationManager authorization prompts don't appear from a launchd daemon at all on Sonoma+. Confirmation needed: run the actual signed `.app` daemon process headless and check whether `CLLocationManager.authorizationStatus()` ever leaves `notDetermined`. If blocked, #99's scope shrinks to geocode/reverse-geocode only (no auth needed).

### From FEATURES.md

**Adapter Depth Parity (P1 group — no open feasibility questions unless noted):**
- Calendar alarms + BYDAY recurrence (#89, #90) — public EventKit API only; ship together
- Reminders delete + list management (#92) — trivial CRUD symmetry
- Contacts full cards + me-card + sqlite search (#94, #95)
- Messages unread/date filters + attachments + gated send (#88, #87, #86) — reuses the existing outbound tier; **verify Messages send device-side as rigorously as Mail's outbound lifecycle**
- Photos albums/metadata/export (#96) — once the osxphotos question is resolved
- Safari bookmarks/reading list/history (#97) — dual-source (plist + sqlite), both read-only

**New Domains (P2 group unless noted):**
- Location geocode/reverse-geocode (#99 easy half) — LOW complexity, no TCC
- Weather current/hourly/daily (#100) — decided keyless HTTP
- Capture: screenshot only (#101) — `screencapture` CLI
- System utilities: clipboard + Spotlight + notifications only (#102) — the 3 tools Bash can't do cleanly; skip the other 9
- Maps search/directions/ETA (#98) — MEDIUM-HIGH, **spike MapKit throttling before building**
- Reminders tags + subtasks (#91) — P3, **investigate-first** (public `parentReminder` subtasks vs private-API tags)
- Notes semantic search sidecar (#93) — P3, **evaluate-first**, optional extra (`macos-apps-mcp[semantic]`)
- Location current-position (#99 hard half) — P3, spike-gated

**Platform & DX:**
- Dashboard + recovery history (#126) — served localhost, reuses `doctor`/`usage`/`audit`
- Network transport + auth (#127) — **requires BOTH** Tailscale-bound TCP + bearer token AND an SSE-speaking bridge (HA's MCP Client supports SSE only)
- Menubar companion (#126 extension) — **Swift MenuBarExtra, pure HTTP/UDS client of the daemon**; dashboard endpoints first
- `.mcpb` bundle + brew tap (#107), `[project.urls]` (#111), uvx docs (#113) — packaging-only
- Companion skill + Claude Code plugin (#106) — after #113
- User-preferences env context (#105) — one env var, trusted config

**Critical Feature Decision — Home Assistant Remote Access (#127):** verified directly against HA's own docs: the MCP Client integration supports **SSE transport only** ("SSE Server URL"); streamable-HTTP client support is an unresolved upstream discussion as of August 2026. #127's auth layer is only half the job; the SSE bridge is a transport adapter, not an auth choice. Both gates must resolve before #127 closes.

### From ARCHITECTURE.md

**Gate Phase Build Order (load-bearing):**

1. **Card 1 (native seam fail-closed)** — widens `test_native_seam.py` from `mail*.py` to `adapters/*.py` + `doctor.py`; conftest lock covers `tracked_run`. First, because every later card's verification rests on tests failing closed. No device proof needed. Mail-scoped cards 3/4/9 can run in parallel.
2. **Card 7 (EventKit cluster → `eventkit.py`)** — 13 EventKit-only names leave `runtime.py`. Before adapter-depth work, because Contacts/Calendar PRs would otherwise edit `runtime.py`. Device proof: `-m integration -k "request_access or create_event or create_reminder"`.
3. **Card 5 (tier policy → `tiers.py`)** — extracted from `server.py:61–103`; closes doctor's lazy import cycle; the notice middleware moves to `notices.py` (audit.py cannot host it — import order). Unblocks any module reading tier state without importing `server` (e.g. a dashboard endpoint).
4. **Card 2 (registration record)** — after 1/7/5 so the record is built against settled module boundaries. Every subsequent adapter PR registers through it with tier/audit-verb/notice policy correct by construction. Device proof: full suite + spot-check `doctor()`, `usage()`, one destructive write's annotations.
5. **Cards 3/4/9 (Mail-scoped)** — parallel; touch only `mail_recover.py`/`mail_index.py`/fixtures. Card 4 needs a scratch-mailbox run with the watchdog.
6. **Close:** `MACOS_APPS_READ_ONLY=1 uv run pytest` green, then the full device integration sweep.

**Integration Patterns for Target Work:**
- **Dual-backend read plane (Contacts sqlite, Safari plist+sqlite):** existing `read_via_sqlite` + a `read_via_plist` sibling. The schema-fingerprint test must cross-check the fingerprint against every column every query reads (Mail's `HEADER_FINGERPRINT` gap is the cautionary tale).
- **Native worker + completion-handler bridge (Maps/Location):** `runtime.run_native_async`'s own docstring flags the gap: APIs delivering on the main run loop need an NSRunLoop pump — add it with the first such consumer.
- **No native app behind it (Weather):** `weather.py` obeys "one adapter per app" structurally (imports only contracts/errors/httpx) but `doctor` probes HTTP reachability, not Automation consent. Don't force a sqlite-style fingerprint onto an HTTP response.
- **Progressive disclosure for large content (Messages attachments, Photos export):** copy `mail_files.py`'s write-to-disk discipline — derived basename, allowlisted root, no silent overwrite, size cap; never inline bytes.
- **Network transport must not reuse the UDS "no read deadline" reasoning** — a remote TCP link has a network to time out on; it needs its own timeout/auth policy without changing the shim↔daemon contract.

### From PITFALLS.md

| Pitfall | Phase | Prevention |
|---------|-------|-----------|
| Registration record silently drops gated-off tools (FastMCP 3.x never creates a `Tool` for them) | Gate (card 2) | Record intent pre-gate, register conditionally; derive the registry from the pre-gate structure, never from `Tool.meta` off `list_tools()` |
| Spike rebase reintroduces the #166/0f01e09 import-order bug | Gate | Land 1→7→5→2 one at a time; after cards 5 and 2: restart daemon, `doctor().version` + one outbound dry run |
| Menubar companion splits TCC identity | Platform | Companion is a pure HTTP/UDS client; an import-boundary check fails if it touches EventKit/osascript/native frameworks |
| Dashboard exposed unauthenticated over the #127 network bind | Platform (#127 design) | Same auth on dashboard and MCP routes, or separate listeners (dashboard loopback-only) |
| All-day alarm off-by-one by timezone (mcp-ical's bug) | Adapter depth (#89) | Normalise to local midnight; first device test = recurring all-day event in a non-UTC timezone |
| RRULE shapes save but don't reliably fire | Adapter depth (#90) | Allowlist device-probed shapes; read back 6 months of occurrences and diff vs RFC 5545 |
| Reminders tags have no public API | #91 | Investigate first; `parentReminder` subtasks are public (macOS 14+); ship tags read-only via sqlite with a documented gap, never a private-API write |
| Contacts notes field entitlement crashes updates (iMCP#148) | Adapter depth (#94) | Exclude notes from `keysToFetch` and the update payload entirely — not "v2" |
| Sqlite schema drift (Contacts/Photos/Reminders) | Adapter depth | Fingerprint + test cross-check against every column read; retrofit Mail's gap in the gate |
| Headless CoreLocation authorization unreachable | New domains (#99) | Spike first in daemon mode; if no prompt, scope shrinks to geocode-only and "near me" leaves #98 |
| MapKit search throttles (~50 req/60 s, undocumented) | New domains (#98) | Device-measure the throttle first; serialize/rate-limit via the existing worker |
| Screen Recording grant re-prompts monthly on Sequoia+ | New domains (#101) | `doctor()` re-checks per session; docstring names the lapse |

---

## Implications for Roadmap

**Phase 1 — Gate.** Cards 1→7→5→2 in sequence; Mail-scoped 3/4/9 in parallel; close with the read-only suite and the device integration sweep. Pure refactor: device proof is regression, not feature verification. Measured spike costs: 2–3 h each for 1/7/5, 4–6 h for 2, 3–4 h for 3, 2–3 h + device for 4. **No adapter work until this closes.**

**Phase 2 — Adapter depth parity.** Calendar (#89/#90 together), Reminders (#92), Contacts (#94/#95), Messages (#88/#87/#86), Photos (#96), Safari (#97). Spikes that gate scope: `uv add osxphotos` resolution; CNContactStore TCC under the daemon's bundle identity (else extend the osascript `_UPDATE` template). Device probes (all-day alarm timezone, recurrence read-back, sqlite fingerprints, Messages send routing) are phase deliverables, not follow-ups. #91 and #93 are investigate/evaluate-first and should not be scheduled as ordinary feature work.

**Phase 3 — New domains.** Ship-now: geocode (#99a), Weather (#100), screenshot (#101), clipboard/Spotlight/notify (#102), Maps (#98, after the throttle measurement). Spike-gated: current location (#99b) — its answer decides whether "near me" exists at all.

**Phase 4 — Platform & DX.** #113/#111 first (cheap, unblocks #106), `.mcpb` (#107), #105, dashboard (#126) before menubar, #127 as transport bridge + auth with route-auth parity decided up front.

## Confidence Assessment

| Area | Confidence | Rationale | Gaps |
|------|-----------|-----------|------|
| Stack | MEDIUM–HIGH | Versions verified against PyPI/GitHub/Context7 | osxphotos resolution; MapKit symbol coverage |
| Features | HIGH | Every prior-art repo and issue fetched directly; HA docs verified directly | None beyond spike-gated items |
| Architecture | HIGH | Read directly from `develop`; gate order confirmed by file-collision analysis | Card 2 design (pre-gate record) proven only at review + device time |
| Pitfalls | MEDIUM | 7/12 device-verified from repo history; 5/12 external, flagged spike-required | CoreLocation, MapKit throttle, Contacts TCC, AddressBook schema history |

**Research gaps to close during planning (device probes, not more reading):** osxphotos resolution; CNContactStore TCC in daemon mode; headless CoreLocation; MapKit throttling; Reminders private-API route; Notes embeddings build/refresh policy; dashboard/MCP route auth separation.

## Settled Decisions (No Further Research Needed)

| Decision | Source | Scope impact |
|----------|--------|--------------|
| Weather = keyless HTTP (Open-Meteo) | WeatherKit entitlement-blocked; apple-mcp-pro precedent | No WeatherKit exploration |
| Contacts notes field excluded entirely | iMCP#148; entitlement unobtainable outside App Store review | Hardwired at interface design |
| osxphotos conflict likely stale | Conditional floor analysis; target is Ventura+/3.12+ | Re-verify, then unblock #96 |
| HA MCP Client requires SSE | HA docs | #127 = SSE bridge + auth |
| Menubar companion = Swift MenuBarExtra client | TCC-identity split risk; "companion must not become the server" | No second Python interpreter |
| Dashboard and menubar reuse the daemon's HTTP surface | #126 design | No new IPC; dashboard endpoints first |
| Subtask writes via `parentReminder` are public; tags are investigate-first | iMCP#145; FradSer uses private API | #91 scoped as investigation |
| All-day alarms and recurrence need device probes before shipping | mcp-ical#20 + README | Probes are phase deliverables |
| Sqlite fingerprint pattern must cover every column read | Mail's `HEADER_FINGERPRINT` gap | Retrofit Mail in the gate; build in from the first cut elsewhere |

## Sources

- `.planning/research/STACK.md`, `FEATURES.md`, `ARCHITECTURE.md`, `PITFALLS.md` (each cites its primary sources: prior-art repos fetched directly, `gh issue view` on #86–#127, home-assistant.io/integrations/mcp, Apple developer forums, PyPI/Context7 for versions, and this repo's `CLAUDE.md`, `DESIGN.md`, `docs/ROADMAP.md`, `docs/mail-applescript-facts.md`, `.planning/codebase/CONCERNS.md`).

---
*Research synthesized for: macos-apps-mcp target milestone (gate → adapter depth → new domains → platform & DX)*
*Synthesis date: 2026-08-28*
