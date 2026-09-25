# Feature Research

**Domain:** MCP server exposing native macOS apps to an LLM agent — pointers-not-payload reads, gated/dry-runnable/audited writes
**Researched:** 2026-08-28
**Confidence:** HIGH — every prior-art repo below was fetched directly (README content quoted), every issue number was read directly via `gh issue view`, and the Home Assistant claim was verified against `home-assistant.io/integrations/mcp/` directly rather than inferred.

This research covers the three areas of the current milestone: **(A)** adapter depth parity for the
nine shipped adapters, **(B)** four new domains, **(C)** platform/DX including the Home Assistant
remote-access requirement. Every finding is framed against the two invariants that never change:
every read returns `Pointer(id, summary, deeplink)` — never a payload dump — and every write is
tier-gated, id-addressed, dry-runnable, and audited.

## Feature Landscape

### Table Stakes (Users Expect These)

Features the best-in-class specialist for that domain already ships. Missing these = this server
reads as shallower than the single-purpose tool a user would otherwise reach for.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Contacts full card + `contacts_me` (#94) | iMCP ships `contacts_me`/`contacts_search`/`contacts_update`; "email it to me" needs a self-card | LOW | `CNContactStore` via PyObjC, not AppleScript. **Exclude the notes field from update** — writing it needs `com.apple.developer.contacts.notes`, an entitlement Apple grants case-by-case (iMCP#148 hit this; silently fails without it) |
| Contacts sqlite fast search (#95) | apple-mcp-pro's headline fix: AppleScript iterates per-card; sqlite is claimed ~100× (12s→100ms at ~1,250 cards) | MEDIUM | Dual-backend per the repo's own #58 pattern: sqlite (`AddressBook-v22.abcddb`) when FDA present, AppleScript fallback otherwise; `doctor` reports which plane is active — same shape as the Contacts/Notes/Mail native-store precedent already shipped |
| Calendar alarms on create/update (#89) | Every calendar tool users compare this to (mcp-ical) has them; an event with no notification is a silent-failure class | LOW | `EKAlarm(relativeOffset:)`, minutes-before list. **Test recurring all-day alarms explicitly** — mcp-ical's own README documents an off-by-one day bug there; don't repeat it uncaught |
| Calendar extended recurrence — BYDAY etc. (#90) | "Every Tue/Thu" is an ordinary human schedule; v1's RRULE subset can't create it | MEDIUM | Extend the parser: `BYDAY` (with ordinals for monthly), `BYMONTHDAY`, `BYMONTH` → `EKRecurrenceRule` day/month fields. **Keep rejecting loudly** what EventKit can't express — mcp-ical's README admits "non-standard recurring schedules may not always be set correctly"; a loud reject beats a silent misfire |
| Reminders delete + list management (#92) | CRUD asymmetry today: create/update/complete exist, delete does not; public EventKit, trivial | LOW | `delete_reminder(id, dry_run)` mirrors `delete_event` exactly; `create_reminder_list(name)`. Same verify-after-write convention already proven on Calendar |
| Messages unread + date-range filters (#88) | `messages_with` has only `limit` today; cheap `chat.db` WHERE clauses | LOW | `since`/`until` + `is_read=0` filter. Demanded upstream too (iMCP#154 open) |
| Messages attachments via progressive disclosure (#87) | Attachments are currently invisible; every messaging-domain specialist surfaces them | MEDIUM | **Copy carterlasalle/mac_messages_mcp's pattern exactly, not just the feature**: annotate reads with `[attachment: name/type]`, a separate bounded `message_attachment(id, dest_dir)` fetch, HEIC→PNG, size cap. This pattern (annotate → search → explicit fetch) is the pointers-not-payload discipline applied to binary blobs — see Anti-Features below for what NOT to do here |
| Messages gated send (#86) | The category-leading iMessage server (carterlasalle, 302★) sends with iMessage/SMS auto-routing + group-chat targeting; iMCP's own top feature request (iMCP#78) is send | LOW–MEDIUM | Reuses the **outbound tier already shipped for Mail (0.9.0)** — `MACOS_APPS_ALLOW_SEND` names `messages`, `dry_run=True` default, `openWorldHint`. `imessage_available(handle)` ships **ungated** (a read). Group chats via `chat_id`. Number normalization reuses `messages_with`'s existing logic |
| Photos albums, metadata, export (#96) | Three separate prior-art servers (apple-mcp-pro, sweetrb, osxphotos) all ship this triad; today's Photos surface is one search call, nothing else | MEDIUM | `photo_albums()`, `photo_info(id)` (dates/location/persons/EXIF, bounded), `export_photo(id, dest_dir)` — **export writes to disk, never returns bytes**. Decide the `osxphotos` dependency question first (CREDITS.md already flags a prior dep conflict) vs. raw PhotoKit/PyObjC |
| Safari bookmarks + reading list (#97) | Shipped by apple-mcp-pro already; iMCP's own most-requested unshipped issue (iMCP#83) is bookmarks | LOW | `Bookmarks.plist` read for bookmarks (no FDA); reading list needs FDA — `doctor` detects and reports |
| Zero-thought install via `uvx`/PyPI (#113) | Every server with real traction (iMCP: brew cask; patrickfreyer: uvx + `.mcpb`) has a copy-paste install; this repo's README still leads with git-clone | LOW | The package is **already published** (`macos-apps-mcp` on PyPI, console script wired) — this is a doc fix, not new code. `[project.urls]` (#111) is a five-line adjacent fix |
| User-preferences env context (#105) | patrickfreyer's `USER_EMAIL_PREFERENCES` precedent: one env var, zero schema work, every interaction gets better | LOW | `MAC_MCP_PREFERENCES` (free text, size-capped) appended to server instructions at startup. **Treat as user-trusted config, not untrusted store content** — no sanitization notice, unlike mail/message bodies |
| Weather current/hourly/daily via keyless HTTP (#100) | iMCP ships 4 weather tools (WeatherKit); apple-mcp-pro ships the same data keyless via `wttr.in` | LOW | **WeatherKit is not a real option for this project** — it needs a paid Apple Developer entitlement tied to a signed bundle, and "for us" the issue itself calls it entitlement-blocked. Ship keyless HTTP (wttr.in / open-meteo) — no auth, no Apple dependency, matches apple-mcp-pro's proven approach |
| Capture: screenshot (#101) | The one iMCP + apple-mcp-pro capture feature with obvious agent utility ("what's on my screen", visual verification of a change) | LOW | `screencapture` CLI wrapped, `screenshot(mode, dest_dir)` — full/silent/window/region. Screen Recording TCC, `doctor`-checked. **Ship this alone**; camera/audio are a separate decision (see Differentiators) |

### Differentiators (Competitive Advantage)

Features where either nobody in the surveyed ecosystem ships it well, or shipping it in this
server's idiom (pointers, dual-backend fallback, gated tiers) is itself the advantage over a
same-named feature elsewhere.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Notes semantic search sidecar (#93) | The one prior-art project (RafalWilinski/mcp-apple-notes, 404★) that filled this gap died 19 months ago; nobody else attempts it | HIGH | Fix the dead project's own documented gaps rather than repeat them: it has **no chunking**, **HTML-only output** (not markdown), **no index management**, and never shipped a write-back path. Ship as an **optional extra** (`mac-mcp[semantic]`) so embedding-model deps (`all-MiniLM-L6-v2`-class, LanceDB-class) never bloat the default install — mirrors the FTS5 Mail-body sidecar (#70) precedent: index lives in this project's own state dir, lazily built, size-capped. **This is explicitly an evaluate-first issue** — decide the build/refresh policy before writing the indexer |
| Reminders tags + subtasks (#91) | Only one surveyed server (FradSer, 164★) ships this at all; it's what power users actually organize Reminders by | HIGH | **EventKit has no public tags/subtasks API.** FradSer's Swift binary is the only reference for "which private/adjacent route works" — that route may not be safely portable. The right call, stated in the issue itself: investigate FradSer's mechanism first; **if it needs a private API, ship read-only via the Reminders SQLite store and document the write limitation rather than shipping a fragile private-API write path.** A documented gap beats a write that silently corrupts data on the next macOS point release |
| Safari history search (#97) | "What was that page last Tuesday?" — surveyed and confirmed **zero** MCP servers ship this; a genuinely open niche, not a catch-up feature | LOW–MEDIUM | `~/Library/Safari/History.db`, read-only, FDA-gated, `doctor`-detected. Same shape as every other native-sqlite read plane already proven in this codebase (Messages, Notes, Mail) |
| Maps search/directions/ETA (#98) | iMCP's strongest unique domain; pairs naturally with this server's existing Calendar write surface ("how long to the dentist, leave when?") | MEDIUM–HIGH | MapKit via PyObjC on the single worker thread, same completion-handler pattern already used elsewhere in `runtime.py`. **Read-only to start**: `map_search`, `map_directions(mode)`, `map_eta`; deeplinks as `maps://` URLs. This project's own earlier closed issue flagged an `MKLocalSearch`-from-bare-python throttling/bundle-id caveat — now partially mitigated by the signed `.app` bundle #71 already shipped, but still worth a device probe before committing scope |
| Location geocode/reverse-geocode (#99, half) | Bridges contact addresses ↔ directions; no auth needed | LOW | `CLGeocoder`, no TCC prompt, no auth — the easy half of #99 |
| Location current-position (#99, half) | "Near me" context for Maps + travel-time math | HIGH | The issue's own risk flag: a **TCC Location prompt from a headless process** is unverified territory, distinct from EventKit's already-solved thread-affinity story. Spike this specifically before committing — it may lean on the same signed-helper-binary work that made EventKit/TCC-to-bundle work for #71, or it may not transfer at all |
| Localhost onboarding/dashboard (#126) | Every field-facing competitor's #1 support burden is "which permission is missing and how do I fix it" — `doctor`/`usage`/`audit` already answer it, they're just not visible without a tool call | LOW | **Not a native SwiftUI app.** The daemon already serves HTTP — serve a plain localhost page off the same process, backed by the three tools that already exist. The one open design question, flagged in the issue itself: a web page can't open System Settings panes itself, so the daemon endpoint must shell `open "x-apple.systempreferences:…"` and TCC prompts only fire when the actual **bundle** process makes the call — pin the exact grant-trigger sequence before building the UI around it |
| Menubar companion — lifetime stats + browsable recovery/history (PROJECT.md, extends #126) | Makes the audit trail and Mail's recoverable-plane backups (already built for #159) *visible* without a tool call — the human control panel for what the model can't touch | MEDIUM | A **client of the daemon's existing HTTP surface** (same `doctor`/`usage`/`audit` endpoints the dashboard uses), not a new server. #126 itself scoped this as "deferred… a ~30-line `rumps` shim" — **PROJECT.md's current Active list has since promoted it to committed scope for this milestone**, which is a real scope increase worth flagging to whoever plans the phase, not silently absorbed |
| Companion skill + Claude Code plugin (#106) | patrickfreyer's adoption engine isn't the server, it's the plugin — two commands install server + slash command + a workflow-teaching skill; this repo has richer surface and no equivalent | LOW–MEDIUM | `.claude-plugin/` with `plugin.json` + `marketplace.json`; one skill covering pointer-citation discipline and the draft-review flow already proven on Mail. Sequence **after** the PyPI/uvx doc fix (#113) — a plugin that installs a stale README path is worse than no plugin |
| `.mcpb` bundle + brew tap (#107) | iMCP = brew cask + one-click Claude config; patrickfreyer = uvx + `.mcpb`; this repo's ceiling today is git-clone | LOW (mcpb) / LOW (tap, once demand exists) | Order per the issue: PyPI (done) → `.mcpb` in CI → brew tap iff demand. **Verify `uvx` cold-start time** — PyObjC wheels are the one thing that could make `uvx` slower than the venv path this repo already recommends internally |

### Anti-Features (Commonly Requested, Often Problematic)

Features that a prior-art server ships, or that look like an obvious next step, but that violate
this server's actual constitution — pointers not payload, dry-runnable and audited writes, no
disambiguation-by-guessing.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|------------------|-------------|
| Inline base64 image bytes as the default photo/attachment response | sweetrb/apple-photos-mcp's `get-thumbnail` returns an inline base64 JPEG/PNG content block (capped 8MB) — looks convenient, MCP clients render it | This is exactly the shape of payload this server exists to avoid returning by default; a "helpful" thumbnail becomes the same context-bloat failure mode that got the 3.1k★ category leader archived, just in image bytes instead of text | `export_photo`/`message_attachment` write to disk and return a path + `Pointer`; if an inline preview is ever wanted, it is a separate, explicitly-named, tiny-and-capped opt-in tool — never the default shape of a search/list result |
| Full note/message/mail body returned in list or search results | Looks efficient — "just give me everything in one call" | This is the *exact* bug ("every note returned in full") that got supermemoryai/apple-mcp (3.1k★) archived, cited by this project's own DESIGN.md as the reason it exists | Bounded `Pointer` (id/summary/deeplink) from search; a separate bounded get-by-id call for full content, exactly as Mail/Notes/Messages already do |
| Fuzzy auto-pick contact/recipient resolution on a write | Feels smoother — "just send it to whoever matches" | DESIGN.md already records the concrete failure: "fuzzy auto-pick has sent iMessages to the wrong human." An ambiguous name must never silently resolve before a destructive or outbound write | Ambiguous search returns candidate Pointers; sends/writes accept `Pointer.id` only — the existing disambiguation rule, extended to Messages/Contacts rather than re-invented per adapter |
| Static map image generation (iMCP's `maps_generate`) | iMCP ships it; "just render me a map" is an obvious ask once Maps exists | Returns an image payload as the primary output of a read tool — the same anti-pattern as inline photo thumbnails, applied to a domain that doesn't need it (a `maps://` deeplink opens the real, interactive map) | `maps://` deeplink in the `Pointer`, same as every other adapter's "open in the real app" convention |
| Reminders private-API tags/subtasks writes if the public route doesn't exist | #91's prior art (FradSer) ships it, so "just do what they did" is tempting | A private/undocumented API can silently break on the next macOS point release with no warning — and a write that used to work and now fails open (rather than erroring loudly) is the worst failure shape for a server whose entire value proposition is trustworthy writes | Ship read-only via the Reminders SQLite store if the public EventKit route doesn't exist; document the write gap explicitly rather than shipping a write nobody can trust past the next OS update |
| WeatherKit as the weather mechanism | It's Apple's own, "proper" API, and iMCP uses it | Requires a paid Apple Developer Program entitlement tied to the signed bundle — the issue that scoped this for *this* project states plainly it is entitlement-blocked here, not merely harder | Keyless HTTP (wttr.in / open-meteo); Shortcuts-based weather via the already-shipped `run_shortcut` gateway is the fallback if the HTTP option is ever undesirable |
| Cherry-picking all 12 of apple-mcp-pro's system-utility tools (#102) | "More tools = more capable," and they're each individually tiny (<50 lines) | The server's caller already has a `Bash` tool. `system_info` (`system_profiler`), `sound_volume` (`osascript`/`nircmd`-equivalent), `finder` selection, `textedit`, `voice_memos`, `books`, `time_machine`, `dictionary` are all reachable from Bash/AppleScript one-liners the caller can already issue directly — wrapping them as MCP tools adds registered-tool surface (more for the model to consider on every call) without adding capability | Ship only what Bash genuinely cannot do cleanly: **clipboard** (rich content — images/RTF — is where `pbcopy`/`pbpaste` text piping breaks down), **Spotlight search** (`mdfind`, path-scoped — a real search index Bash can't replicate with `find`), and **notifications** (Notification Center posting needs an actual app-level API, not a shell one-liner). Treat even clipboard as debatable if the caller's Bash usage never needs non-text clipboard content |
| Streamable-HTTP-only network transport for #127 | FastMCP already serves streamable-http today; "just expose the existing daemon on the tailnet" looks like the whole job | **Verified directly against Home Assistant's own docs**: the *Model Context Protocol* integration (HA acting as MCP **client** — the one #127 exists for) supports **only SSE transport**, configured with an "SSE Server URL" (e.g. `http://host/sse`); streamable-HTTP client support is an open, unresolved GitHub discussion (home-assistant/discussions#1383) as of this research. Shipping streamable-http alone, even correctly authenticated over Tailscale, will **not** plug into HA's MCP Client integration | Front the daemon with an SSE-speaking bridge (`mcp-proxy` in SSE mode is the pattern HA's own docs recommend for stdio servers; the same shape works for a streamable-http backend) — this is a transport decision **independent of and in addition to** the auth decision (Tailscale/token/mTLS) the issue already scopes. See Gaps below |
| A general dashboard framework / SPA for #126 | "While we're building a UI, make it nice" | DESIGN.md's earlier settled-skips list explicitly named "HTML dashboards" a non-goal; a heavier dashboard reopens the "is this becoming a GUI app" question PROJECT.md deliberately narrowed rather than reversed | A single localhost page, served by the existing daemon process, that calls the three tools that already exist (`doctor`/`usage`/`audit`) — no new framework, no new process, no client-side build step |
| Bundling ML/embedding dependencies into the base package for #93 | "Semantic search should just work out of the box" | PyObjC + FastMCP + embedding-model + vector-store dependencies compound install size/time for every user, including the majority who will never call `notes_semantic` | Optional extra (`mac-mcp[semantic]`), exactly as scoped in #93's own sketch |

## Feature Dependencies

```
Messages send (#86) ──reuses──> Outbound tier infrastructure (shipped 0.9.0, Mail)
Messages attachments (#87) ──independent of──> Messages send (#86)
                                (both read from the existing chat.db plane, shipped 0.5.0)

Contacts full cards/update (#94) ──independent of──> Contacts sqlite fast search (#95)
                                     (different concerns: card completeness vs. read latency)

Calendar BYDAY recurrence (#90) ──shares parser with──> Calendar alarms (#89)
                                    (both touch create_event/update_event; sequence together)

Location geocode (#99, easy half) ──feeds──> Maps directions/ETA (#98)
                                       (address → coordinates → route is the natural chain,
                                        but Maps can ship with explicit coordinate input first)
Location current-position (#99, hard half) ──gated by──> TCC-to-bundle spike
                                               (partially de-risked by #71's signed daemon,
                                                not proven to transfer to CLLocationManager)

Weather (#100) ──independent──> (decision-only issue, no code dependency on anything else)

Distribution: [project.urls] (#111) + uvx docs (#113) + .mcpb (#107)
    └──precedes──> Companion skill + plugin (#106)
                      (a plugin that installs via a stale/incomplete README path
                       undermines the thing it's trying to fix)

Dashboard (#126) ──reuses──> doctor / usage / audit (all shipped)
Menubar companion ──is a client of──> Dashboard's HTTP endpoints (#126)
                       (same data, different surface — build dashboard's endpoints first)

Network transport (#127) ──requires BOTH──> Auth decision (Tailscale/token/mTLS)
                              AND──requires──> Transport-compatibility fix (streamable-http → SSE)
                              (the issue as filed only scopes the auth half; the transport half
                               is a research finding this document adds, not yet reflected in #127)

Notes semantic sidecar (#93) ──mirrors precedent of──> Mail FTS5 sidecar (#70, shipped)
                                 (same "own state dir, lazily built, size-capped, optional" shape)
```

### Dependency Notes

- **Messages send reuses the outbound tier, not a new one:** the `MACOS_APPS_ALLOW_SEND` mechanism, the `dry_run=True` default, and the `openWorldHint` annotation all already exist from Mail's 0.9.0 cut — #86 is a second adapter parametrizing an existing tier, not new safety machinery. This should keep it LOW complexity despite touching a sensitive capability.
- **Calendar's two issues (#89, #90) share the RRULE-parsing and EventKit-recurrence-object code path** — sequencing them in the same cut (as the roadmap already does: both land as `0.10.0`) avoids touching `create_event`/`update_event` twice.
- **Location's two halves have opposite risk profiles.** Geocode/reverse-geocode is a same-day LOW-complexity win (no TCC, no auth). Current-position is the one item in this entire research pass with a genuinely open feasibility question — it should not block the rest of #99, and probably shouldn't share a release with it.
- **The transport/auth split on #127 is the single most consequential dependency finding here.** The issue as filed treats "pick an auth model" as the whole brainstorm-before-code gate. Home Assistant's own documentation shows a second, independent gate: transport compatibility. Both need resolving before #127 can close; neither implies the other is done.
- **Dashboard before menubar, not the reverse.** The menubar app has nothing of its own to show — it is explicitly a thin client over the dashboard's HTTP endpoints. Building it first would mean building the same `doctor`/`usage`/`audit` glue twice.

## MVP Definition

PROJECT.md has already committed to a phase order — Gate → adapter depth parity → new domains →
platform — so "MVP" here means "what's genuinely load-bearing within each already-committed phase,"
not a re-litigation of that order.

### Launch With (Adapter Depth Parity — this milestone's second phase)

- [ ] Calendar alarms + BYDAY recurrence (#89, #90) — LOW/MEDIUM complexity, public EventKit only, no open feasibility questions
- [ ] Reminders delete + list management (#92) — LOW, trivial CRUD symmetry fix
- [ ] Contacts full cards + `contacts_me` + sqlite fast search (#94, #95) — LOW/MEDIUM, no open feasibility questions, high daily-use value (self-card, full address/birthday data)
- [ ] Messages unread/date filters + attachments + gated send (#88, #87, #86) — reuses existing tier and read-plane infrastructure; the send tool is the one to verify device-side exactly as rigorously as Mail's outbound lifecycle was
- [ ] Photos albums/metadata/export (#96) — MEDIUM, no open feasibility questions once the `osxphotos`-dependency decision is made
- [ ] Safari bookmarks/reading list/history (#97) — LOW/MEDIUM, no open feasibility questions

### Add After (this milestone's third phase — new domains)

- [ ] Location geocode/reverse-geocode (#99 easy half) — ships cleanly once decided
- [ ] Weather via keyless HTTP (#100) — decision is already made by this research (WeatherKit is out); implementation is LOW
- [ ] Capture: screenshot only (#101) — ship this slice; defer camera/audio
- [ ] System utilities: clipboard + Spotlight + notifications only (#102) — the three genuinely Bash-can't-do-this-cleanly tools; skip the other nine pending explicit demand
- [ ] Maps search/directions/ETA (#98) — MEDIUM/HIGH; spike the `MKLocalSearch` throttling question early in this slice, not after tools are built around it
- [ ] Reminders tags + subtasks (#91) — HIGH; resolve as a genuine investigate-first issue (public route vs. read-only-with-documented-gap), don't default to "ship whatever FradSer did"
- [ ] Notes semantic search sidecar (#93) — HIGH, evaluate-first as scoped; land the build/refresh policy decision before any indexing code

### Future Consideration (defer past this milestone or until demand is explicit)

- [ ] Location current-position (#99 hard half) — spike the headless-TCC feasibility question in isolation before committing scope around it
- [ ] Capture: camera/audio — explicitly "maybe" in the issue itself; only if a concrete use case appears
- [ ] Brew tap (#107, second half) — sequence after `.mcpb`, "iff demand" per the issue's own wording
- [ ] mTLS for #127 — only if exposure ever needs to go beyond a trusted tailnet/LAN; Tailscale is the right default
- [ ] Menubar companion's full scope — the dashboard's web surface is the load-bearing deliverable; treat the native menubar wrapper as separable and lower-urgency than PROJECT.md's current phrasing implies, unless the owner explicitly wants both in one cut

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Messages gated send (#86) | HIGH | LOW (reuses tier) | P1 |
| Contacts full cards + me-card (#94) | HIGH | LOW | P1 |
| Calendar alarms + BYDAY (#89/#90) | HIGH | LOW/MEDIUM | P1 |
| Messages attachments (#87) | HIGH | MEDIUM | P1 |
| Reminders delete + lists (#92) | MEDIUM | LOW | P1 |
| Safari bookmarks/reading list/history (#97) | MEDIUM | LOW/MEDIUM | P1 |
| Photos albums/metadata/export (#96) | MEDIUM | MEDIUM | P1 |
| Contacts sqlite fast search (#95) | MEDIUM | MEDIUM | P2 |
| Weather via keyless HTTP (#100) | MEDIUM | LOW | P2 |
| Location geocode (#99 easy half) | MEDIUM | LOW | P2 |
| Capture: screenshot (#101) | MEDIUM | LOW | P2 |
| System utils: clipboard/Spotlight/notify (#102, subset) | LOW/MEDIUM | LOW | P2 |
| Maps search/directions/ETA (#98) | MEDIUM | MEDIUM/HIGH | P2 |
| Distribution: uvx docs, `.mcpb`, project.urls (#113/#107/#111) | HIGH (adoption) | LOW | P2 |
| User-preferences env context (#105) | MEDIUM | LOW | P2 |
| Localhost dashboard (#126) | HIGH (support burden) | LOW | P2 |
| HA network transport + auth (#127) | HIGH (stated use case) | MEDIUM (now: transport + auth, not just auth) | P2 |
| Companion skill + plugin (#106) | MEDIUM (adoption) | LOW/MEDIUM | P3 |
| Reminders tags/subtasks (#91) | MEDIUM | HIGH (feasibility unresolved) | P3 |
| Notes semantic search (#93) | MEDIUM | HIGH (evaluate-first) | P3 |
| Location current-position (#99 hard half) | LOW/MEDIUM | HIGH (feasibility unresolved) | P3 |
| Menubar companion app | LOW/MEDIUM | MEDIUM | P3 |
| Capture: camera/audio | LOW | MEDIUM | P3 |
| Brew tap | LOW | LOW | P3 |

**Priority key:**
- P1: Adapter-depth items with no open feasibility question — build these first
- P2: New-domain and platform items with a settled mechanism decision (this research resolved most of them)
- P3: Items with a genuinely open feasibility question (private APIs, headless TCC, evaluate-first sidecars) — spike before committing a phase around them

## Competitor Feature Analysis

| Feature | mattt/iMCP | jasonpaulso/apple-mcp-pro | This server's approach |
|---------|------------|---------------------------|-------------------------|
| Data shape | JSON-LD / Schema.org documents | Not documented as bounded | `Pointer(id, summary, deeplink)` on every read, uniformly — neither competitor states this as an invariant |
| Mail/Notes/Photos/Safari | **Not supported at all** (iMCP's own two most-requested gaps) | Photos/Safari yes (basic), no Mail depth | Already the widest combination surveyed (per ROADMAP.md's 2026-07-14 finding); this milestone deepens rather than catches up |
| Contacts | Read-only search | SQLite-backed fast search (~100×) | Adopting apple-mcp-pro's storage mechanism (#95) while keeping iMCP's full-card/update/me-card completeness (#94) — best of both, not a copy of either |
| Messages | Read-only, date-range filter, **no send** | Send + schedule + read unread | Adopting apple-mcp-pro's send scope but through this server's own outbound-tier gating (#86) — apple-mcp-pro's own docs don't describe a gate |
| Messages attachments | Not mentioned | Not mentioned | Neither competitor solves this; carterlasalle/mac_messages_mcp (a third project, messaging-only) is the actual source of the progressive-disclosure pattern adopted here (#87) |
| Weather | WeatherKit (needs Apple entitlement) | Keyless `wttr.in` | Following apple-mcp-pro's mechanism — WeatherKit is confirmed entitlement-blocked for this project specifically |
| System utilities | N/A (different domain split) | 12 tools, all ungated | Cherry-pick 3 (clipboard/Spotlight/notify); explicitly reject the other 9 as Bash-redundant — this server's caller has a Bash tool, apple-mcp-pro's likely doesn't assume that |
| Distribution | brew cask, one-click config | uvx + `.mcpb` | Already on PyPI; catching up on docs (#113) and `.mcpb` (#107), then brew "iff demand" |
| GUI | Native menubar app is the *whole* product (a Swift app with a bundled CLI) | N/A | Deliberately narrower: the daemon stays the server; a menubar app is one more thin *client* of it, not a replacement (PROJECT.md's explicit framing) |
| Remote/network access | Not offered (local menubar app only) | Not offered | New requirement unique to this project's use case (Home Assistant) — no direct prior art; solved from HA's own client-side documentation instead (#127) |

## Sources

- [mattt/iMCP](https://github.com/mattt/iMCP) — fetched directly; JSON-LD data shape, menubar-app architecture, confirmed no Mail/Notes/Photos/Safari support
- [jasonpaulso/apple-mcp-pro](https://github.com/jasonpaulso/apple-mcp-pro) — fetched directly; 12-tool system-utilities inventory, sqlite Contacts mechanism, Messages send/Safari scope
- [FradSer/mcp-server-apple-events](https://github.com/FradSer/mcp-server-apple-events) — fetched directly; Reminders tags/subtasks/list-management tool inventory
- [Omar-V2/mcp-ical](https://github.com/Omar-V2/mcp-ical) — fetched directly; alarm support, recurrence limitations, documented off-by-one bug
- [carterlasalle/mac_messages_mcp](https://github.com/carterlasalle/mac_messages_mcp) — fetched directly; chat.db read plane, progressive-disclosure attachment pattern, send routing/security notes
- [sweetrb/apple-photos-mcp](https://github.com/sweetrb/apple-photos-mcp) — fetched directly; album/metadata/export scope, inline-thumbnail anti-pattern identified here
- [RafalWilinski/mcp-apple-notes](https://github.com/RafalWilinski/mcp-apple-notes) — fetched directly; semantic-search mechanism and its documented gaps (no chunking, HTML-only, dead 19mo)
- [home-assistant.io/integrations/mcp/](https://www.home-assistant.io/integrations/mcp/) — fetched directly; confirmed SSE-only transport, OAuth Application Credentials auth, `/sse` URL format
- Web search: home-assistant/discussions#1383 (streamable-HTTP client support still an open request)
- `gh issue view` on elfensky/macos-apps-mcp — issues #86–#102, #105–#107, #111, #113, #126, #127 read directly for scope, prior-art citations, and each issue's own risk/sketch notes
- `.planning/PROJECT.md`, `docs/ROADMAP.md`, `DESIGN.md` (this repo) — required reading, source of the pointers-not-payload/tier-gating invariants and the "Settled skips"/"Not planned" anti-feature baseline

---
*Feature research for: macos-apps-mcp — adapter depth parity, new domains, platform & DX*
*Researched: 2026-08-28*
