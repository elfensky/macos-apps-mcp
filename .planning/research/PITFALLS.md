# Pitfalls Research

**Domain:** MCP server exposing native macOS apps (Python + FastMCP + PyObjC, launchd daemon, TCC/FDA)
**Researched:** 2026-08-28
**Confidence:** MEDIUM (mix of device-verified repo history — HIGH within itself — and external web/forum sourcing that is directionally right but not device-proven for this repo)

This file has two source classes, kept distinguishable throughout:

- **Device-verified** — already proven on this Mac, cited to `docs/mail-applescript-facts.md`, `docs/ROADMAP.md`, or `.planning/codebase/CONCERNS.md`. Treat as fact.
- **External** — from Apple docs, forums, or prior-art repos (iMCP, mcp-ical, osxphotos, FradSer, etc.), fetched this session. Treat as a strong hypothesis to be device-probed before it ships, per this repo's own discipline: *"ten consecutive 0.9.x cuts had their premise overturned by device probing before code was written."* Every pitfall below that is External says so, and says what probe would settle it.

## Critical Pitfalls

### Pitfall 1: The registration-record refactor silently drops gated-off tools from its own source of truth

**What goes wrong:**
Card 2 (consolidate eight tool-fact "clipboards" into one registration record) is tempting to build by calling `mcp.tool(meta={...})` unconditionally for every tool, then filtering visibility afterward with FastMCP's own tag API (`mcp.disable(tags=...)` / `mcp.enable(tags=..., only=True)`) — because that is the API FastMCP's docs actually show for this exact use case. If the record is then built by iterating registered `Tool` objects and reading `Tool.meta`, every capability a tier-gate holds off (a write tool under `MACOS_APPS_READ_ONLY`, a send tool whose adapter isn't in `MACOS_APPS_ALLOW_SEND`) simply never existed as a `Tool` and is invisible to that iteration — the same silent-omission failure class as `usage` shipping mis-classified (`_NO_NOTICE`), except now it can hide an entire capability, not one flag.

**Why it happens:**
FastMCP 3.x (this repo pins `fastmcp-slim` 3.4.7 via `fastmcp>=2.0`) has the decorator return a `Tool`/`FunctionTool` **object**, not the original callable — the "decorators return the original function" behavior is a FastMCP 4.0 change, not yet true here. So the natural refactor — "call `mcp.tool()` always, hide later" — collides with this repo's actual gating contract: *"A gated-off tool is absent, never registered-and-erroring"* (CLAUDE.md). The existing code already gets this right by construction: `_write_tool`'s `deco(f)` returns the bare `f` when `_read_only()` is true, and `_send_tool`'s `deco(f)` records into `_SEND_ADAPTERS` **before** the gate check and only calls `mcp.tool()` after it passes. A registration-record refactor that doesn't preserve that "record capability before the gate, register conditionally after" ordering regresses this.

**How to avoid:**
Keep the "record intent, then conditionally register" two-phase shape the current code already uses (`_SEND_ADAPTERS` recorded pre-gate, `_SEND_REGISTERED` post-gate). The registration record's per-tool facts (tier, audit verb, backup-notice flag, snapshot source) must be captured in a plain Python structure at decoration time — before any `mcp.tool()` call — never derived by walking `Tool.meta` on whatever happens to be registered. `doctor()`'s "capable vs configured" split (`outbound_status()`) is the existing pattern to generalize, not replace.

**Warning signs:**
- A new derived table (e.g. the eight clipboards' successor) that only has entries for tools visible under the current process's env vars.
- `MACOS_APPS_READ_ONLY=1 uv run pytest` (already known-red, 12 failures) gaining *new* failures in the registration-record's own tests once card 2 lands, rather than the count shrinking.
- Any test that asserts on `mcp.list_tools()` / `Tool.meta` as the sole source for a fact that used to live in `_WRITE_TOOLS` or `_SEND_ADAPTERS`.

**Phase to address:**
Gate phase (card 2), same phase that lands the registration record — this is the one design decision inside that card that determines whether the refactor is actually safer than the eight clipboards it replaces.

---

### Pitfall 2: Rebasing overlapping spike branches onto server.py/doctor.py/runtime.py reintroduces the bug a later spike already fixed

**What goes wrong:**
Per `PROJECT.md`, the nine `spike/arch-review-N-*` branches are throwaway primary sources re-landed by "rebasing onto the previous PR" — but cards 1 (native seam), 5 (tier policy), 7 (runtime split), and 2 (registration record) all touch `server.py`, `doctor.py`, and `runtime.py` in overlapping regions (the exact three files CLAUDE.md marks "don't drift"). A naive rebase of, say, card 7's `runtime.py` split onto a `develop` that has already absorbed card 5's tier-policy extraction can silently resurrect the stale import-cycle comment style bug class this repo already shipped once (`daemon.py:158`'s comment going stale after commit `0f01e09` moved gate-reading logic) — or worse, resurrect #166 itself: the daemon "could never register the outbound tier" because `__init__.py` imported `server` before `daemon.serve()` set `MACOS_APPS_MCP_ROLE`. That bug was fixed by reading the role from `sys.argv` instead of import order; a rebase that reintroduces an eager `from . import server` at package `__init__` time (exactly what card 5's tier-policy extraction is trying to eliminate as "the package's only import cycle") can quietly put the timing dependency back.

**Why it happens:**
Git rebase conflict resolution on hand-edited overlapping regions of three tightly-coupled files is exactly the situation where "pick the version that compiles" silently discards the specific ordering invariant (import-before-role-is-set, tier-policy-read-after-gate-write) that made the previous fix work, without any test failing — because the existing tests target behavior, and the bug is about *timing of a module-level read*, which most unit tests don't exercise (that's precisely why #166 shipped silently and was only caught by *running the actual daemon*).

**How to avoid:**
Land cards in the dependency order PROJECT.md already commits to (1 → 7 → 5 → 2 → 3 → 4 → 9), one at a time on top of `develop`, never combining two spike branches into a single rebase. After each land, re-run the specific device-level check the earlier fix was for — for #166 specifically: kill and restart the daemon, run `doctor().version` plus a real `send_mail` dry run, and confirm outbound tools appear only when `allow-send mail` was called before daemon start. Do this again after card 5 (tier policy extraction) since it directly touches the code #166 lives in.

**Warning signs:**
- A rebase touching `daemon.py` near the `MACOS_APPS_MCP_ROLE` assignment or `server.py`'s `_allow_send`/`_read_only` functions.
- Any diff that reintroduces a module-level `from . import server` inside `__init__.py`, `doctor.py`, or `daemon.py` above where `sys.argv`/env is read.
- `doctor()` reporting `outbound_pending` immediately after a fresh daemon restart with `allow-send` already configured (the exact symptom #166 produced).

**Phase to address:**
The Gate phase, specifically the sequencing of cards 1/7/5/2 — call out the #166 regression check as an explicit device-verification step at the end of card 5 and card 2, not just at final integration.

---

### Pitfall 3: A menubar companion app becomes a second TCC identity, silently splitting "one grant serves every client"

**What goes wrong:**
CLAUDE.md's architecture states TCC is keyed to the responsible **process** — that's why #71 needed a launchd agent + unix socket instead of stdio-spawn in the first place (own MEMORY.md: *"TCC keys grants to the responsible process → #71 needs a launchd agent + unix socket, not stdio-spawn"*). A menubar companion app (Platform & DX phase) is a **separate process**. If it ever makes its own Apple Event, EventKit, or Contacts call directly — even just to show a quick status glance, "is Mail responding" — instead of asking the daemon over its API, macOS treats it as a distinct responsible process and prompts for (or silently denies) its own TCC grant, independent of the daemon's. That fragments the "one grant, every client" guarantee PROJECT.md names as a design goal, and worse, a companion app bundle with a *different* bundle id than `ren.lav.macos-apps-mcp` needs its own Full Disk Access entry in System Settings that a user has to discover and grant separately — the opposite of the onboarding UX #126 is trying to build.

**Why it happens:**
It is much easier to write "read Mail's process state directly from the menubar app for a snappy status icon" than to add another daemon endpoint — especially once the menubar app already links AppKit/PyObjC for its own UI needs and the native call is "right there."

**How to avoid:**
The menubar companion must be a pure HTTP/UDS client of the running daemon for every fact it displays (lifetime stats via `usage`, recovery history via `audit`, grant status via `doctor`) — it must never import `runtime`, `EventKit`, or call `osascript` itself. This is also why #126's dashboard is built as a served localhost web page rather than a native SwiftUI shell: reusing the running daemon process is what keeps the identity singular. Enforce this the same way the native-seam tripwire (card 1) enforces "adapters call only `runtime`" — a lint/import-boundary check that fails if the companion's source tree imports anything native.

**Warning signs:**
- Any companion-app code path with `import EventKit`, `subprocess` calling `osascript`, or a `Contacts`/`AddressBook` framework import.
- A System Settings > Privacy grant list showing two macOS-apps-mcp-related bundle ids instead of one.
- The companion app prompting for its own permission the first time a user clicks a status icon.

**Phase to address:**
Platform & DX phase, at menubar-companion design time — bake "companion talks to daemon only" into its module boundary before writing its first native-looking convenience call.

---

### Pitfall 4: Exposing the daemon's network transport (#127) also exposes the localhost dashboard (#126) unless they are separately gated

**What goes wrong:**
The daemon already serves FastMCP over streamable-HTTP (today bound to a local UDS, mode `0700`/`0600`), and #126's onboarding dashboard is designed to reuse that same running process ("the daemon already serves HTTP — have it serve a localhost dashboard page"). #127's job is to bind that HTTP surface to a network interface (Tailscale tailnet, per the recommended option) so Home Assistant can reach it. If the dashboard's routes live on the same HTTP listener as the MCP protocol routes, binding the interface for #127 makes the dashboard — which has **unauthenticated "Grant Calendar/Contacts" buttons that shell out to `open x-apple.systempreferences:...`** — reachable from anywhere on the tailnet too, not just the MCP tool surface. That is a materially different risk profile than "a Home Assistant MCP client can call `list_events`": it is a web UI that can be driven by anyone with tailnet access to nudge System Settings panes open on the user's Mac.

**Why it happens:**
Reusing one HTTP listener for two purposes (MCP protocol + human dashboard) is the "lazy architecture" #126 explicitly chooses ("Zero Swift, reuses the running process") — a good call for a localhost-only listener, but the tradeoff changes the moment #127 makes that listener reachable off-box.

**How to avoid:**
Treat the dashboard routes as requiring the same auth gate #127 puts in front of the MCP routes (Tailscale identity, bearer token, or mTLS — whichever #127 picks), or bind the dashboard to loopback-only on a **different** port/listener than the one #127 exposes to the tailnet, so "network transport for MCP tools" and "local onboarding UI" can never be conflated by a future change to either. Decide this explicitly in #127's design rather than discovering it once both features exist.

**Warning signs:**
- #127's implementation binds the *same* FastMCP HTTP app object that also serves `/dashboard` to a non-loopback interface without an explicit route-level auth check on the dashboard paths.
- A `curl http://<tailscale-ip>:<port>/dashboard` from a second tailnet device succeeding without credentials once #127 ships.

**Phase to address:**
Platform & DX phase — resolve this at #127's design time (before code), since #126 will likely already be shipped and its routing shape is what #127 inherits.

---

### Pitfall 5: EventKit all-day events + alarms shift by one calendar day depending on timezone

**What goes wrong (External — device-probe before shipping #89):**
mcp-ical, this repo's own named prior art for #89 (calendar alarms) and #90 (extended recurrence), shipped and then fixed exactly this bug (mcp-ical PR #20, fetched from GitHub): all-day events are represented internally as spanning UTC midnight, so in a timezone ahead of UTC (their example: NZDT, UTC+13) an event stored as "Dec 21 00:00 local" becomes "Dec 20 11:00 UTC," and naive code that doesn't re-normalize to local midnight/23:59:59 shows the event a day early. An `EKAlarm` built as a `relativeOffset` from that same raw start inherits the identical shift on *recurring* all-day events specifically, because each occurrence's start is recomputed from the UTC-anchored recurrence rule, not from a per-occurrence local-midnight recompute — which is exactly the "known off-by-one bug on recurring all-day alarms" this repo's own #89 issue already flags from mcp-ical as prior art, with the instruction "test that case."

**Why it happens:**
EventKit models `isAllDay` events as a UTC time span rather than a timezone-naive calendar date, so any code path that treats `event.startDate`/`alarm.absoluteDate` as "already local" silently accumulates a one-day error the moment the host timezone isn't UTC — which for this repo's own developer/user (a European timezone) is not a hypothetical.

**How to avoid:**
When adding alarms to all-day events (#89), explicitly re-normalize the event's start to local midnight before computing any `relativeOffset`, and write a **recurring all-day event with a timezone that isn't UTC** as the very first device probe — not a same-day, non-recurring, UTC-adjacent test case, which is exactly the case that would pass while the bug is live. Mirror this repo's own Mail discipline: reading the code cannot verify this; creating the event and inspecting where it lands on the actual calendar day can.

**Warning signs:**
- A test suite for #89 that only exercises `EKAlarm(relativeOffset:)` on timed (non-all-day) events, or on all-day events with `relativeOffset: 0`.
- Any alarm-on-all-day-event test that passes identically regardless of `TZ` env var — that's the signature of a test that never touches the actual bug, since the bug is timezone-dependent by construction.

**Phase to address:**
Adapter depth parity phase, #89 (Calendar alarms) — the device probe belongs in that phase's plan, not deferred to a bug report after ship.

---

### Pitfall 6: EventKit's RRULE surface accepts recurrence shapes it cannot reliably fire

**What goes wrong (External — device-probe before shipping #90):**
`EKRecurrenceRule`'s `daysOfTheWeek`/`daysOfTheMonth`/`monthsOfTheYear`/`setPositions` (Apple's BYSETPOS) API will happily construct and save a rule for a shape that combines properties in ways EventKit's calendar engine doesn't reliably resolve into occurrences — mcp-ical's own README warns that non-standard/complex custom recurrence rules built this way are "unreliable" even though the object constructs without error. This repo's own #90 issue already scopes around this ("keep rejecting what EventKit can't represent — loudly, as today"), which is the right posture, but the boundary of "what EventKit can't represent" is not documented by Apple with the precision needed to write a static validator — it has to be probed.

**Why it happens:**
`EKRecurrenceRule` is a thin wrapper over the underlying calendar engine's recurrence resolution, and Apple's documentation states the *validity conditions* for each property (e.g. `daysOfTheWeek` only for weekly/monthly/yearly) but not which *valid-per-the-docs* combinations actually produce the occurrences a human would expect versus silently truncating or producing an empty set.

**How to avoid:**
Build the extended-recurrence parser (#90) to accept only the specific BYDAY/BYMONTHDAY/BYMONTH combinations that have been device-probed to produce correct EventKit occurrences (start with the common human shapes: "every Tue/Thu," "last weekday of the month," "the 15th of every month") — reject everything else loudly, exactly as v1 already does for the wider RRULE surface. Do not treat "the object saved without throwing" as validation; read back `event.hasRecurrenceRules` occurrences over a several-month window and diff against the RFC5545 expectation before calling any new BYDAY/BYSETPOS shape supported.

**Warning signs:**
- A newly accepted RRULE shape whose occurrence count over a 6-month probe window doesn't match hand-computed expectations.
- Any BYSETPOS value combined with a property EventKit's docs don't explicitly list as compatible (e.g. `setPositions` without one of `daysOfTheWeek`/`daysOfTheMonth`/`weeksOfTheYear`/`monthsOfTheYear` set).

**Phase to address:**
Adapter depth parity phase, #90 — scope the accepted-shapes allowlist as the phase's actual deliverable, not "implement BYDAY."

---

### Pitfall 7: Reminders tags and rich subtasks have no public API — only a private, version-fragile one exists

**What goes wrong (External, confirmed against this repo's own #91 framing):**
`EKReminder.parentReminder` (macOS 14+) gives exactly one level of public, documented subtask nesting — confirmed by an open, unimplemented iMCP feature request (#145) asking for precisely this. Tags, sections, smart lists, and richer subtask ordering/toggling have **no public EventKit or AppleScript surface at all**; the only prior art that reaches them (FradSer/mcp-server-apple-events, this repo's own named reference for #91) does it through Reminders' private `ReminderKit` framework, which is undocumented, unversioned, and can break on any Reminders.app update with no deprecation notice — the same risk class as Mail's private/undeclared properties (`sendLaterDate` in `docs/mail-applescript-facts.md` §3d), except there Apple's Mail.sdef at least *declares* things dishonestly; here there is no declaration to even be dishonest in.

**Why it happens:**
Apple has never shipped a public tags/subtasks API for Reminders despite the feature existing in the app since iOS/macOS updates years ago — third-party tools that want it have to reverse-engineer the private framework FradSer's binary uses, which this repo's own issue explicitly flags as needing investigation before committing to a write path.

**How to avoid:**
Follow #91's own sketch: investigate FradSer's mechanism as research, not as a dependency to vendor. If it turns out to require the private `ReminderKit` route, ship **read-only** via a Reminders SQLite read (mirroring #95's approach to Contacts) and document the write limitation explicitly rather than shipping a write path that can silently stop working on the next macOS point release with no error surface to catch it (the same "declared but lying" vs "undeclared, no signal at all" distinction Mail's facts doc draws — private-API tags/subtasks are the *undeclared* case, strictly worse for detectability). One level of parent/child via public `EKReminder.parentReminder` is safe to ship as a write; anything beyond that needs the read-only fallback decision made explicit in the phase plan, not discovered mid-implementation.

**Warning signs:**
- Any reminders-adapter code importing anything other than `EventKit`/`Foundation` via PyObjC, or shelling to a private binary, to write a tag.
- A "write tag" test that only exercises the happy path on the current macOS version with no version-guard or capability probe.

**Phase to address:**
Adapter depth parity phase, #91 — the "public subtasks (write) vs tags (read-only, private-API risk)" split should be the phase's stated scope, decided before implementation starts.

---

### Pitfall 8: Contacts notes field requires an Apple-gated entitlement — and merely reading an existing contact can trip it

**What goes wrong (External, primary source: iMCP issue #148, fetched directly):**
iMCP's `contacts_update` fails on **every** existing contact with `NSCocoaErrorDomain` code 134092 the moment CoreData faults in that contact's `notes` field — which happens even when the caller never touches notes, because CoreData lazily loads the whole record. The fix requires `com.apple.developer.contacts.notes`, an entitlement Apple gates behind a separate approval **form**, with roughly a week's turnaround and no guarantee of approval — not something that can be added to an entitlements plist and shipped. `contacts_create` works fine in iMCP precisely because a brand-new contact has no notes to fault in; the bug is specific to **updating** (or, by the same mechanism, potentially just fully reading) an existing card that has ever had a notes field, which iMCP's own issue notes is "most contacts" once synced via iCloud. This repo's own #94 issue already names this exact pitfall and the mitigation ("exclude notes from update") as inherited prior art.

**Why it happens:**
Apple restricts programmatic notes access broadly (privacy-sensitive free text), and the restriction applies at the entitlement layer regardless of distribution channel — it is not an App Store-only requirement, though the approval **process** assumes App Store submission review context, which is a poor fit for a Developer-ID-signed, non-sandboxed tool like this one; it is unclear from public documentation whether or how a non-App-Store app can even successfully request/receive the entitlement.

**How to avoid:**
Scope #94's `update_contact` (and any future `contact_card` full-read) to **never touch or request the notes field** — read only the properties `CNContactStore` exposes without the notes entitlement, and if a future need for notes access is filed, treat "can this repo obtain the entitlement outside the App Store at all" as its own device-and-paperwork spike before any code, because unlike almost every other pitfall in this document, this one cannot be resolved by clever engineering — it is gated by an Apple approval process this repo may not qualify for.

**Warning signs:**
- Any `CNContactStore` fetch request whose `keysToFetch` includes `CNContactNoteKey`, directly or via a full-card fetch descriptor that pulls "all keys."
- A `contacts_update`/`contact_card` call raising `NSCocoaErrorDomain` 134092 on an existing contact during device testing — the exact signature iMCP hit.

**Phase to address:**
Adapter depth parity phase, #94 (Contacts full cards + update) — exclude notes from the fetch keys and the update payload at the interface-design step, not as a bug-fix after the first 134092 on device.

---

### Pitfall 9: Sqlite-backed reads (Contacts AddressBook store, Photos.sqlite, Reminders) drift schema across macOS releases with no fingerprint to catch it early

**What goes wrong (External for Photos/Contacts, but this repo already lived this exact failure mode with Mail's Envelope Index):**
osxphotos' own maintainer opened an issue (RhetTbull/osxphotos#1651) describing exactly this: `Photos.sqlite` table/column names are hardcoded per Photos version in `_DB_TABLE_NAMES`, and "a few tables/columns change in each version of Photos... when a new schema is updated, as happened in macOS 14.6, osxphotos breaks" — with the fix direction being schema self-discovery via `sqlite_master` introspection rather than hardcoded names. #95's own sketch for Contacts already plans to read `AddressBook-v22.abcddb` directly (FDA-gated), and that filename's own version suffix (`v22`) is itself evidence the schema has already moved multiple times historically; no authoritative source describes the exact deltas, meaning this repo would be probing blind the same way #70's Envelope Index fingerprinting had to be built from scratch. This repo's own CONCERNS.md documents the identical failure class already **shipped and caught**: `HEADER_FINGERPRINT` (the Mail Envelope Index schema check) doesn't cover six columns two executors actually read, so a real schema mismatch surfaces late, at query time, as a confusing error rather than an early, named "your Mail store changed shape" directive.

**Why it happens:**
Apple's private sqlite stores (Photos, AddressBook, Envelope Index, chat.db) are implementation details of their respective apps, not stable public formats — every one of them has drifted across macOS releases in ways only discoverable by diffing schemas release-to-release, and there is no changelog to consult.

**How to avoid:**
Apply the exact pattern #95's own sketch already names ("schema fingerprint + fallback per our #70 pattern") to every new sqlite-backed read plane, and — learning directly from the Mail `HEADER_FINGERPRINT` gap in CONCERNS.md — make the fingerprint's column list generated from (or tested against) the actual set of columns every query executor reads, not hand-maintained separately from the queries. A test that walks every `query_*` function's SQL and asserts each referenced column appears in the fingerprint closes exactly the gap Mail shipped with.

**Warning signs:**
- A new adapter's schema-version constant that is a bare tuple of column names typed by hand, with no test cross-checking it against the SQL the adapter's queries actually issue.
- A query-time `sqlite3.OperationalError: no such column` in integration testing rather than a named `NativeError`/`SchemaMismatch` at `doctor()` or first-read time.

**Phase to address:**
Adapter depth parity phase for #95 (Contacts) and #96 (Photos) — build the fingerprint-and-test pattern into each adapter's first cut, and retrofit the Mail `HEADER_FINGERPRINT` gap (already tracked in CONCERNS.md) in the Gate phase since it's a known, already-filed defect.

---

### Pitfall 10: CoreLocation authorization may be structurally unreachable from a headless launchd agent

**What goes wrong (External, and already flagged as this repo's own spike target for #99):**
Apple Developer Forum guidance (thread 739712) states plainly that **daemons cannot obtain Core Location authorization** — the prompt is rendered by `CoreLocationAgent`, which does not present UI for a background/daemon process, full stop. The documented workaround is a **global launchd agent** (distinct from the `LaunchDaemon` this repo already runs for #71) running in the user's login session — but Apple's modern `SMAppService` API, which this repo presumably uses or would use for launchd registration, does **not support installing global launchd agents**, closing off the "just switch agent types" escape hatch. This repo's own #99 issue already names "headless CoreLocation TCC is the spike" — the research here confirms that framing is not overcautious; it may be a hard architectural wall, not a configuration detail.

**Why it happens:**
Location is one of the most privacy-sensitive TCC categories, and Apple's authorization UI model assumes a foreground, bundle-identified app requesting it interactively — a background daemon (even one that's launchd-managed and TCC-visible for other categories like Full Disk Access) doesn't fit that model, and Apple has not built an equivalent for the daemon case the way it has for, say, Automation.

**How to avoid:**
Spike #99 **before** committing to any Maps/Location feature shape: on this actual Mac, attempt `CLLocationManager.requestWhenInUseAuthorization()` from the existing daemon process and separately from a foreground-launched helper, and record which one (if either) produces a system prompt. If neither works, the honest scope for #99 is "geocode/reverse-geocode only" (via `CLGeocoder`, which needs no location authorization at all, per iMCP's own `Location.swift` prior art) with `location_current` cut entirely or shipped as "ask the user to paste coordinates" rather than attempting a permission flow that structurally cannot succeed. This decision gates #98 (Maps) too, since "near me" search depends on it.

**Warning signs:**
- Any implementation of `location_current` that assumes a standard `requestWhenInUseAuthorization()` prompt will appear when run under the launchd daemon, with no device confirmation that it does.
- Time spent building UI/retry logic around a location permission prompt before confirming the prompt can appear at all in this process model.

**Phase to address:**
New domains phase, #99 — this is explicitly a spike-first issue in this repo's own roadmap; keep it that way, and let the spike's answer determine whether #98 (Maps) ships with or without "current location."

---

### Pitfall 11: A native process's MapKit search throttles at an undocumented, empirically-discovered rate

**What goes wrong (External, and already an open question in this repo's own history):**
`MKLocalSearch`/`MKReverseGeocodingRequest` enforces a rate limit — Apple Developer Forum reports converge on roughly 50 requests per 60 seconds — returning `MKError.loadingThrottled` once exceeded, with the exact number undocumented by Apple and explicitly left for developers to discover empirically. This repo's own **previously closed** #17 issue already flagged "a bundle-id/throttling caveat... from a bare Python process" as unresolved, and #98's sketch repeats the same caveat verbatim. Nothing found in this research confirms or denies whether an unsigned/unbundled Python process is throttled harder, more leniently, or identically to a signed app — that is genuinely unknown until probed.

**Why it happens:**
MapKit's search backend is a network service behind the framework API, and Apple protects it the way most map-tile/geocoding services protect themselves — rate limiting by client identity, which for MapKit is presumably tied to the requesting process's code-signing identity/bundle id rather than an API key a developer manages directly, since MapKit famously needs no separate API key.

**How to avoid:**
Before shipping #98's `map_search`, run a scripted burst of ~60 `MKLocalSearch` requests in under a minute from the actual daemon process and record whether/when `loadingThrottled` fires, then design the adapter's own client-side rate limiting (a token bucket, or simply serializing map calls the way `runtime`'s single worker already serializes AppleScript) to stay under whatever the device probe measures — with real headroom, since Apple's own forum answers say the number isn't guaranteed stable across app types or OS versions.

**Warning signs:**
- Multiple `map_search`/`map_directions` calls issued back-to-back in a short session (e.g. a multi-stop itinerary query) with no client-side throttling, discovered only when a burst of Claude-driven calls starts failing.
- No `doctor()` visibility into "how many Maps calls has this process made recently" the way there is for Mail's script-timeout backstop.

**Phase to address:**
New domains phase, #98 (Maps) — device-measure the throttle as the first concrete task in that phase's plan, not something discovered by a user hitting it in production.

---

### Pitfall 12: A headless daemon calling `screencapture` can lose Screen Recording access silently, with no code change

**What goes wrong (External):**
macOS Tahoe's TCC model evaluates Screen Recording by **responsible process** (the process actually invoking capture), and macOS 15+ introduced a **monthly re-prompt** for standing Screen Recording grants — meaning a working, previously-granted `screencapture` call from the daemon can start failing purely because a month elapsed and the user hasn't re-acknowledged a prompt they may never see if the daemon has no UI session to show it in (the openclaw project's own issue #14138, filed against a nearly identical Gateway-LaunchAgent shape, is literally titled "screencapture via exec tool fails — TCC Screen Recording permission not inherited by Gateway LaunchAgent"). There is also no command-line path to **grant** the permission — only `tccutil reset ScreenCapture` to clear it — so recovery from a lapsed grant requires a human to open System Settings, not a CLI fix `doctor` could self-heal.

**Why it happens:**
Apple's monthly Screen Recording re-consent is a deliberate, relatively new (macOS 15 Sequoia) anti-spyware measure that assumes an interactive app can show its own re-prompt UI when the OS asks it to; a background daemon has no session to surface that UI in, so the grant can silently lapse from the daemon's point of view.

**How to avoid:**
Have `doctor()` explicitly probe Screen Recording status (the same TCC-status read pattern already used for Calendar/Reminders/Contacts/FDA) and surface a named "Screen Recording grant needs monthly re-confirmation" directive rather than letting a `screenshot()` tool call fail with a generic native error. Document in the tool's own docstring that a working screenshot today does not guarantee one next month, unlike this repo's other TCC grants (Calendar, FDA) which don't currently re-prompt periodically.

**Warning signs:**
- A `screenshot()` tool call that worked in device testing starting to fail weeks later with no code or config change — the specific symptom this pitfall predicts.
- `doctor()` reporting Screen Recording status only at daemon startup rather than re-checked per call or per session.

**Phase to address:**
New domains phase, #101 (Capture) — build the recurring-reprompt possibility into the doctor check and the tool's error message from the first cut, since it is a known Sequoia+ behavior, not a hypothetical.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|--------------------|-----------------|------------------|
| Ship a new sqlite-backed read (Contacts, Photos) without a schema fingerprint, "just get it working first" | Faster first cut, mirrors what Mail's Envelope Index reader looked like before #70 hardened it | Query-time `OperationalError` on the next macOS point release instead of a named, early "store changed shape" directive — exactly the gap CONCERNS.md already records for Mail's own `HEADER_FINGERPRINT` | Never for a shipped release; acceptable only inside a same-day spike branch that gets the fingerprint before merge |
| Build the registration record (card 2) by reading `Tool.meta` off `mcp.list_tools()` instead of a pre-gate record | Reuses FastMCP's own tag/meta API exactly as documented, less bespoke code | Silently omits every tier-gated-off tool from the derived tables (Pitfall 1) | Never — the pre-gate record is the only version compatible with "absent, never registered-and-erroring" |
| Ship Reminders tags/subtasks via the private `ReminderKit` route to match FradSer's feature parity | Full write parity with the best competing server | Undocumented API, can break silently on any Reminders.app update, with no deprecation signal at all (worse than Mail's "declared but lying" `sendLaterDate` case, which at least has a symbol to grep for) | Never for a write path; acceptable only for a read-only, clearly-labeled experimental fallback |
| Menubar companion reads native app/process state directly for a "snappier" status icon instead of calling the daemon | Avoids one more HTTP round-trip in the UI | Splits the TCC identity (Pitfall 3), silently defeating "one grant, every client" | Never |
| Weather via WeatherKit "since we'll eventually have a signed helper binary anyway" (#100 option c) | Native, no external HTTP dependency | Blocked entirely until the signed-helper-binary Platform work lands — an indefinite dependency for a comparatively low-value feature | Only once the Platform & DX signed-helper work has *already* shipped for other reasons; not as a reason to start it |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|------------------|--------------------|
| EventKit (`EKAlarm` on all-day events) | Compute `relativeOffset` from the raw (UTC-anchored) event start | Re-normalize to local midnight before computing the offset; device-probe with a non-UTC timezone and a recurring event, per Pitfall 5 |
| EventKit (`EKRecurrenceRule` BYDAY/BYSETPOS) | Treat "the object saved without throwing" as validation | Read back several months of occurrences and diff against hand-computed expectations before accepting a new recurrence shape, per Pitfall 6 |
| Contacts (`CNContactStore`) | Fetch or update with a keys descriptor that includes notes, even incidentally via a "fetch everything" convenience call | Scope `keysToFetch` explicitly, excluding `CNContactNoteKey`, on every read and write path (Pitfall 8) |
| Reminders private tags API | Vendor/replicate FradSer's private-framework calls for write parity | Ship one level of public `parentReminder` subtasks as a write; treat tags/deep subtasks as read-only-or-cut (Pitfall 7) |
| CoreLocation from launchd agent | Assume `requestWhenInUseAuthorization()` behaves the same from a daemon as from a foreground app | Device-probe from the actual daemon process before writing any Location code; the prompt may never appear at all (Pitfall 10) |
| MapKit (`MKLocalSearch`) | Fire searches back-to-back with no client-side throttling | Serialize/rate-limit Maps calls the way `runtime`'s single worker already serializes AppleScript; measure the actual throttle on device first (Pitfall 11) |
| Home Assistant MCP Client | Assume a specific transport (SSE vs streamable-HTTP) is required beyond standard MCP | HA's MCP Client integration is transport-agnostic at the network layer and supports OAuth via Application Credentials when the server implements it; Tailscale-mediated streamable-HTTP (this repo's #127 plan) is compatible |
| `.mcpb` distribution | Assume packaging as `.mcpb` provides its own code-signing/trust boundary | `.mcpb` is a zip of `manifest.json` + server files with no bundle-level signature scheme documented; the Developer-ID signing + notarization of the underlying `.app`/binary remains the actual trust boundary regardless of `.mcpb` packaging |
| Notarization + distribution (`.dmg`/`.zip` + brew cask) | Staple the ticket to the `.app`, then serve an older zip made before stapling | Re-zip **after** stapling, every time — already captured in this repo's own MEMORY.md, worth re-stating for the Platform phase's brew-tap work since it's an easy step to drop in a release script rewrite |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|-----------------|
| Unbounded MapKit search bursts | `MKError.loadingThrottled` mid-session on a multi-stop itinerary query | Client-side rate limiting sized to the device-measured throttle (Pitfall 11) | Somewhere above ~50 requests/minute, per Apple forum reports — unconfirmed for this repo's exact process shape |
| Photos.sqlite / AddressBook store walks without bounds | A `photo_albums()`/contacts-search call that's fast on a 1k-item library and slow or memory-heavy on a 50k-photo library | Bound every list/search the same way Mail's `MAX_MAILS`/batch caps already do; paginate rather than materializing full result sets | Scales with library size, not user count — a single power-user library can already be large enough to matter at ship time |
| Screen Recording monthly re-prompt treated as a one-time grant | A `screenshot()` tool silently starts failing weeks after ship with no deploy in between | `doctor()` re-checks Screen Recording status per session, not just at daemon startup (Pitfall 12) | Roughly monthly, per Apple's documented Sequoia+ re-consent cadence |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Binding the daemon's HTTP transport to a network interface for #127 without gating the dashboard routes from #126 identically | FDA-level "Grant Calendar" buttons become reachable to anyone with tailnet/LAN access, not just MCP tool calls | Gate dashboard and MCP routes under the same auth boundary, or keep them on physically separate listeners (Pitfall 4) |
| Token-over-plain-HTTP for #127's auth, even "just on the LAN" | A bearer token that unlocks FDA-level EventKit/Mail/Contacts access travels in cleartext on the local network, interceptable by anything else on that LAN/tailnet segment | TLS 1.2+ minimum (1.3 preferred) for any token-bearing endpoint; Tailscale (this repo's own ranked-first option) sidesteps the whole cert-management problem by encrypting at the tailnet layer instead |
| Treating a signed `.mcpb`/brew-cask artifact as inherently more trustworthy than the raw `.app` it wraps | A `.mcpb`'s manifest schema is validated by Claude Desktop, but the bundle itself carries no independent signature — a compromised build pipeline could ship a bad server inside a syntactically valid `.mcpb` | Keep Developer-ID signing + notarization of the actual `.app`/binary as the real trust boundary; treat `.mcpb`/brew packaging as convenience, not a security control |
| A menubar companion with its own TCC identity making native calls "just for convenience" | Splits the audit trail and grant surface across two processes, undermining the single-grant model this repo is built around | Companion is API-client-only (Pitfall 3) |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-------------------|
| A Location/Maps feature that silently never prompts for authorization | User asks "where am I" and gets a confusing native error with no actionable next step, because the OS never surfaces a permission dialog for a daemon | Ship geocode-only (no location auth needed) if the device probe (Pitfall 10) confirms the daemon can't get the prompt; say so plainly in the tool's docstring rather than pretending the capability exists |
| A `screenshot()` tool that worked at install time failing a month later with a generic error | User loses trust in a previously-working feature for no visible reason | `doctor()` names "Screen Recording needs monthly re-confirmation" explicitly (Pitfall 12), matching this repo's existing pattern of naming *why* a grant lapsed rather than a bare failure |
| Reminders "tags" advertised as a feature but silently no-op or erroring on the next macOS release | User builds a workflow around private-API tags, then it breaks with an update they didn't even choose to review | Label tags/deep-subtasks support explicitly as best-effort/experimental in its own docstring if shipped via the private route at all (Pitfall 7) |

## "Looks Done But Isn't" Checklist

- [ ] **Calendar alarms on all-day events (#89):** Often verified only on a same-day, non-recurring, near-UTC test case — verify with a *recurring*, non-UTC-timezone all-day event, the exact shape mcp-ical's own off-by-one bug lived in.
- [ ] **Extended recurrence (#90):** Often verified by confirming the `EKRecurrenceRule` object saves without error — verify by reading back several months of actual occurrences and diffing against hand-computed expectations.
- [ ] **Contacts full cards/update (#94):** Often verified against a *freshly created* test contact with no notes field — verify against a real, iCloud-synced existing contact, the case iMCP's #148 actually failed on.
- [ ] **A new sqlite-backed read plane (Contacts #95, Photos #96):** Often shipped with a hand-typed schema-version tuple — verify a test cross-checks that tuple against every column the adapter's own queries actually reference (the Mail `HEADER_FINGERPRINT` gap, CONCERNS.md).
- [ ] **Location current position (#99):** Often "implemented" against a foreground manual test run from a terminal session with an active login — verify against the actual long-running launchd daemon process, headless, with no interactive session.
- [ ] **Registration record (card 2):** Often verified by confirming all *currently-registered* tools' facts are correct — verify that a tool tier-gated OFF in the test's env (`MACOS_APPS_READ_ONLY=1`, no `allow-send`) still has its facts captured somewhere the derived tables can find, not silently absent (Pitfall 1).
- [ ] **Network transport (#127):** Often verified by confirming an MCP tool call succeeds over the new transport with auth — verify the dashboard (#126) routes on the same listener are *not* reachable without the same auth (Pitfall 4).

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|-----------------|------------------|
| Registration record silently drops gated-off tools (Pitfall 1) | MEDIUM | Add the pre-gate capability record retroactively (mirror `_SEND_ADAPTERS`'s existing pattern); backfill a test asserting every `@_write_tool`/`@_send_tool` name appears in the record regardless of env |
| A spike-branch rebase reintroduces #166-class import-order bug (Pitfall 2) | LOW–MEDIUM | Bisect to the rebase commit, re-apply the specific ordering fix (`sys.argv`-based role detection), re-run the daemon-restart device check that originally caught it |
| Menubar companion ships with its own TCC identity (Pitfall 3) | MEDIUM | Strip native imports from the companion, route every fact through the daemon's existing API surface, ask the user to revoke the companion's separate TCC grant in System Settings |
| Dashboard exposed unauthenticated over the network (Pitfall 4) | LOW (if caught pre-release) / HIGH (if already shipped) | Immediately rebind the dashboard to loopback-only or add the same auth check as the MCP routes; if already shipped, treat as a security incident requiring a point release, not a routine bugfix |
| All-day alarm off-by-one ships (Pitfall 5) | LOW | Patch the offset computation to re-normalize to local midnight first; add the recurring-non-UTC regression test that should have existed from the start |
| Contacts notes-field 134092 crash ships (Pitfall 8) | LOW | Narrow `keysToFetch`/update payload to exclude notes; no entitlement to chase since the fix is scope reduction, not permission acquisition |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|--------------------|----------------|
| Registration record drops gated-off tools | Gate (card 2) | Test asserts every tier-decorated tool name appears in the record under every env combination, including fully gated-off |
| Spike-branch rebase reintroduces #166-class bug | Gate (cards 1/7/5/2, sequenced) | Manual device check after each card: restart daemon, run `doctor().version` + a real outbound dry run, confirm `outbound_pending` behaves correctly |
| Menubar companion splits TCC identity | Platform & DX (menubar companion) | Import-boundary lint/test: companion source tree contains no native (`EventKit`/`osascript`/`Contacts`) imports |
| Dashboard exposed via #127's network bind | Platform & DX (#127 design, before code) | `curl` the dashboard route from a second tailnet device without credentials; must fail |
| All-day alarm off-by-one | Adapter depth parity (#89) | Device test: recurring all-day event in a non-UTC timezone, alarm fires/reads on the correct calendar day |
| Non-standard recurrence shapes silently misfire | Adapter depth parity (#90) | Device test: read back occurrences over 6 months for each newly-accepted BYDAY/BYSETPOS shape, diff against hand computation |
| Reminders private-API tags/subtasks fragility | Adapter depth parity (#91) | Phase plan explicitly states public-subtask-write vs private-tag-read-only-or-cut decision before implementation |
| Contacts notes entitlement crash | Adapter depth parity (#94) | Device test against a real, existing, iCloud-synced contact (not a freshly created one) |
| Sqlite schema drift (Contacts/Photos) | Adapter depth parity (#95, #96) | Test cross-checks the schema fingerprint against every column every query executor reads |
| Headless CoreLocation authorization | New domains (#99, spike-first) | Device probe from the actual launchd daemon process before any Location code is written |
| MapKit undocumented throttle | New domains (#98) | Device-measured burst test recorded in the phase's plan before `map_search` ships |
| Screen Recording monthly re-prompt | New domains (#101) | `doctor()` check re-run per session, not just at daemon start; docstring names the monthly-lapse behavior |

## Sources

**Device-verified (this repo, HIGH confidence within their own claims):**
- [docs/mail-applescript-facts.md](../../docs/mail-applescript-facts.md) — the device-verification discipline this file's External/Device-verified split is modeled on
- [docs/ROADMAP.md](../../docs/ROADMAP.md) — the 0.9.x table (ten consecutive premise-overturning device probes), #99/#100/#127 issue sketches
- [.planning/codebase/CONCERNS.md](../codebase/CONCERNS.md) — native seam leak, tool registration clipboards, `HEADER_FINGERPRINT` gap, tier-policy import cycle, #166's daemon-role timing bug
- `.planning/PROJECT.md` — spike-branch rebase discipline, menubar companion / platform decisions

**External (fetched this session, confidence noted per claim above):**
- [mcp-ical PR #20](https://github.com/Omar-V2/mcp-ical/issues/20) — all-day event/timezone off-by-one (verified via `gh api`, MEDIUM)
- [EKRecurrenceRule — Apple Developer Documentation](https://developer.apple.com/documentation/eventkit/ekrecurrencerule) — BYDAY/BYSETPOS validity conditions (LOW-MEDIUM, docs don't cover reliability of accepted combinations)
- [iMCP issue #145](https://github.com/mattt/iMCP/issues/145) — `EKReminder.parentReminder` subtasks, unimplemented (verified via `gh api`, MEDIUM)
- [FradSer/mcp-server-apple-events](https://github.com/FradSer/mcp-server-apple-events) / [viticci/remctl](https://github.com/viticci/remctl) — private ReminderKit route for tags/subtasks (MEDIUM)
- [iMCP issue #148](https://github.com/mattt/iMCP/issues/148) — Contacts notes entitlement crash, `NSCocoaErrorDomain` 134092 (verified via `gh api`, primary source, MEDIUM-HIGH)
- [com.apple.developer.contacts.notes — Apple Developer Documentation](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.developer.contacts.notes) — entitlement approval requirement
- [RhetTbull/osxphotos issue #1651](https://github.com/RhetTbull/osxphotos/issues/1651) — Photos.sqlite schema drift, self-discovery proposal (MEDIUM)
- [dgelessus/python-typedstream](https://github.com/dgelessus/python-typedstream) — chat.db `attributedBody` typedstream decoding (MEDIUM, confirms already-solved approach)
- Apple Developer Forums thread 739712 — CoreLocation authorization unavailable to daemons/launchd agents (MEDIUM)
- Apple Developer Forums (MKLocalSearch throttling threads) — ~50 req/60s `loadingThrottled` (LOW, unconfirmed for unsigned processes)
- [openclaw/openclaw issue #14138](https://github.com/openclaw/openclaw/issues/14138) — `screencapture` Screen Recording TCC not inherited by a launchd Gateway agent (MEDIUM)
- MCP security guidance (multiple vendor blogs, modelcontextprotocol/modelcontextprotocol discussion #1247) — TLS/bearer-token/mTLS best practices for remote MCP (MEDIUM)
- [Home Assistant MCP Client integration docs](https://www.home-assistant.io/integrations/mcp/) — OAuth Application Credentials support (MEDIUM)
- [modelcontextprotocol/mcpb](https://github.com/modelcontextprotocol/mcpb) / [MCPB blog post](https://blog.modelcontextprotocol.io/posts/2025-11-20-adopting-mcpb/) — `.mcpb` format, no independent bundle-signing scheme found (LOW)
- FastMCP docs via Context7 (`/prefecthq/fastmcp`) — `Tool.from_function`/`meta`, tag-based `enable`/`disable`, and the FastMCP 4.0 "decorators return functions" migration note that implies 3.x does not (MEDIUM) — cross-checked against this repo's own pinned `fastmcp-slim==3.4.7` in `uv.lock`

---
*Pitfalls research for: macos-apps-mcp — Contacts/Calendar/Reminders depth, Messages depth, Photos/Safari, new domains (Maps/Location/Weather/Capture), and Platform (network transport, menubar companion, distribution)*
*Researched: 2026-08-28*
