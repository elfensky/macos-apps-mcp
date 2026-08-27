# Architecture Research

**Domain:** In-repo architecture integration — macOS native-app MCP server (Python + FastMCP)
**Researched:** 2026-08-28
**Confidence:** HIGH (every claim below verified against source in this repo, not the ecosystem)

## Standard Architecture

### System Overview — current state, with target work marked

```
┌────────────────────────────────────────────────────────────────────────────┐
│  server.py — FastMCP app, thin dispatch, tier decorators                   │
│  (target: tier logic MOVES OUT to tiers.py; registration becomes 1 record) │
├──────────────┬──────────────┬──────────────┬───────────────┬──────────────┤
│  EventKit    │  osascript   │  sqlite RO   │  CLI subprocess│  HTTP (new)  │
│  Calendar    │  Mail*       │  Messages    │  Shortcuts    │  Weather     │
│  Reminders   │  Contacts    │  Notes       │  screencapture│  (target)    │
│              │  Photos      │  (dual-plane)│  (target,     │              │
│              │  Safari      │              │   shortcuts-  │              │
│              │  Music       │  target:     │   shaped)     │              │
│              │              │  Contacts    │               │              │
│              │  target:     │  AddressBook,│               │              │
│              │  Maps/       │  Safari      │               │              │
│              │  Location    │  Bookmarks   │               │              │
│              │  (MapKit/    │  .plist,     │               │              │
│              │  CoreLocation│  History.db  │               │              │
│              │  — NOT       │              │               │              │
│              │  osascript)  │              │               │              │
├──────────────┴──────────────┴──────────────┴───────────────┴──────────────┤
│  contracts.py — Pointer, PointerSource Protocol, typed write dataclasses   │
├──────────────────────────────────────────────────────────────────────────┤
│  runtime.py — ONE serialized worker (max_workers=1) + run_native_async     │
│  (target: EventKit-only 13 names split OUT to eventkit.py; ~10 stay shared)│
├──────────────────────────────────────────────────────────────────────────┤
│  errors.py / audit.py / doctor.py / lifecycle.py                          │
│  (target: doctor's circular import into server.py closes via tiers.py)    │
├──────────────────────────────────────────────────────────────────────────┤
│  daemon.py — UDS bind/listen, streamable-http proxy, no read deadline     │
│  (target: a SECOND transport — TCP/TLS+auth — sits BESIDE this, unchanged)│
├──────────────────────────────────────────────────────────────────────────┤
│  deploy.py — argv role detection (stdio/daemon/shim), allow_send toggle   │
│  (target: menubar companion is a NEW client role, not a new server role)  │
└──────────────────────────────────────────────────────────────────────────┘
```

The shape does not change for the target milestone — it deepens. Every numbered item
below is an addition to an existing layer, never a new layer.

### Component Responsibilities

| Component | Responsibility today | Target-work touch |
|-----------|----------------------|--------------------|
| `server.py` (1358 lines) | FastMCP app, `@_read_tool`/`@_write_tool`/`@_additive_tool`/`@_send_tool` decorators (server.py:159–246), eight hand-maintained tool-fact lists (`_WRITE_TOOLS`, `_SNAPSHOT_SOURCES`, `_SEND_ADAPTERS`, `_NO_NOTICE` at 281, `_BACKUP_NOTICE_TOOLS` at 290) | Card 2 (registration record) collapses the eight lists into one `@_tool()` decorator carrying tier/adapter/permission/audit-verb/notice as parameters; every NEW adapter tool (Contacts update, Photos export, Maps, Weather, screencapture) is registered through that record from day one, not hand-added to eight places |
| `tiers.py` (new, card 5) | — | Extracted from `server.py:61–103`: `_read_only()`, `_allow_send()`, the tier-gate policy. `doctor.py`, `deploy.py`, and `mail_recover.py` import it instead of `doctor` lazily importing `server` (the package's only cycle, `doctor.py:264`) |
| `runtime.py` (734 lines) | Shared: `run_native`, `run_osascript`, `tracked_run`/`track_child`, `run_native_async`, `_open_sqlite_ro`/`verify_sqlite_schema`/`read_via_sqlite` (the #58 dual-backend seam), `mac_region`, `app_process_info`. EventKit-only (13 names): `store()`, `container_id`, `to_nsdate`/`epoch_nsdate`/`from_nsdate`/`due_components`, `_FREQUENCIES`/`to_recurrence_rule`/`recurrence_signature`/`persisted_recurrence_signature`/`rrule_text`, `request_access`/`request_access_each`/`bootstrap` | Card 7 moves the EventKit-only 13 to a new `eventkit.py` at the package root (same tier as `runtime`/`errors`/`text`). `calendar.py`/`reminders.py` import `eventkit` instead of pulling 9–10 names out of `runtime`. **This split must land before Contacts/Photos/Maps work touches `runtime.py`**, or new code keeps adding to the file the cut is trying to shrink |
| `contracts.py` | Pointer, `PointerSource` Protocol, `Snapshotter` Protocol, typed write dataclasses (`ContactData` today has only `given_name`/`family_name`/`organization` — no id/phone/email field for update) | New: `ContactData` grows fields for `update_contact` (#94); no new Protocol needed — reads stay `get_pointers`, writes stay typed per-adapter methods |
| `doctor.py` (395 lines) | `_AUTOMATION_APPS` tuple (line 35: Mail, Notes, Contacts, Photos, Safari, Messages, Music) drives which apps get the Automation-consent probe; lazy `from . import server` at line 264 for `outbound_status()` | Adding Maps/Weather/screencapture: Maps and Location are **not** osascript — they don't go in `_AUTOMATION_APPS` at all (see New Domains below); Weather is HTTP — also not in that tuple; screencapture is a CLI (`tracked_run`), same as `shortcuts` — also not Automation. So the *new* domains mostly do NOT extend `_AUTOMATION_APPS`; only a Contacts/Safari extension of existing adapters does |
| `audit.py` | `AuditMiddleware`, `Snapshotter`-driven before-state capture, `_audit_op` verb map (currently 9 writes fall through to bare `"write"`) | Card 2 fixes this generically — new adapters' writes (Contacts update, Reminders delete, Notes body write) get correct verbs "for free" once the registration record derives `_audit_op` instead of a ninth hand-edit |
| `mail_index.py` (1347 lines) | `_open_sqlite_ro`/`verify_sqlite_schema` (from runtime) + a schema fingerprint (`HEADER_FINGERPRINT`) + the FTS5 body sidecar (`build_body_index`, `fts_path`, `fts_max_bytes`, lines 1119–1253): sidecar lives in **our own state dir**, size-capped (512 MB default, `MACOS_APPS_MCP_FTS_MAX_BYTES` override), resumable (keyed by path+mtime+size), never touches Mail's data | **This is the exact precedent for a Notes embeddings sidecar (#93).** Same shape: `notes_embeddings.sqlite` in `state_dir()`, lazily built by an explicit tool (mirrors `mail_index_bodies`), size-capped, resumable by `(note id, ZDATA hash)` instead of `(path, mtime, size)` since Notes has no files to stat |
| `daemon.py` (206 lines) | UDS-only: `bind_socket`, `_uds_client_factory` (httpx over `AF_UNIX`, `Timeout(None, connect=10.0)`), `fail_loud_on_dead_stream`, `run_shim`/`serve` | Network transport (#127) is a **second bind**, not a UDS replacement — see Platform section |
| `deploy.py` (338 lines) | `is_daemon_role()` (argv-based, `deploy.py:268-286`), `install_agent`/`uninstall_agent`, `allow_send`/`allow_send_file`, TCC grant reporting | Menubar companion is a **new client**, not a new role here — it connects the same way a shim does (see Platform section) |

## Recommended Integration Structure

No new top-level package. New adapters are new files in `macos_apps_mcp/adapters/`; new
cross-cutting policy is new files at the package root, same tier as `runtime.py`/`errors.py`:

```
macos_apps_mcp/
├── tiers.py              # NEW (card 5) — _read_only(), _allow_send(), gate policy
├── notices.py            # NEW (card 5) — UntrustedDataNotice extraction
├── eventkit.py           # NEW (card 7) — the 13 EventKit-only names out of runtime.py
├── runtime.py            # SHRINKS to ~10 shared names (run_native, run_osascript,
│                         #   tracked_run, run_native_async, the sqlite dual-plane trio,
│                         #   mac_region, app_process_info)
├── server.py             # tool registration derives from ONE record (card 2);
│                         #   imports tiers instead of defining gates inline
├── adapters/
│   ├── contacts.py        # DEPTH: sqlite fast search (#95) + update (#94) added
│   │                       #   alongside the existing osascript create/read
│   ├── safari.py           # DEPTH: Bookmarks.plist + History.db readers added
│   │                       #   alongside the existing osascript tab-list/open
│   ├── notes.py             # DEPTH: embeddings sidecar module or notes_embeddings.py
│   ├── messages.py          # DEPTH: attachment progressive disclosure added
│   ├── photos.py            # DEPTH: albums/metadata/export (write-to-disk)
│   ├── maps.py              # NEW — MapKit/CoreLocation, run_native_async pattern
│   ├── weather.py           # NEW — first adapter with NO native app behind it
│   ├── capture.py           # NEW — screencapture, tracked_run (shortcuts-shaped)
│   └── mail_*.py            # unchanged; the mail_files.py write-to-disk pattern
│                             #   is the model Photos export should copy
```

### Structure Rationale

- **`tiers.py`/`eventkit.py` go in BEFORE any adapter depth work touches the files they
  extract from.** Card 5 pulls tier policy out of `server.py`; card 7 pulls EventKit
  specifics out of `runtime.py`. Contacts depth (#94/#95) and Calendar depth (#89/#90)
  are the adapters most likely to touch exactly those two files next — landing the
  splits first means the depth work edits the smaller, already-settled files instead of
  colliding with an in-flight extraction.
- **New domain adapters (`maps.py`, `weather.py`, `capture.py`) are still "one adapter
  module per app,"** even though two of the three have no macOS `.app` to open (Weather
  has no native app; Location/Maps use frameworks, not automation). The rule's intent —
  no cross-adapter reach, all native calls through `runtime` — holds regardless of
  which native surface an adapter uses.
- **`mail_files.py`'s write-to-disk discipline is generic, not Mail-specific,** and
  should be lifted (or its rules restated) for Photos export rather than reinvented:
  derived basename (never concatenated), allowlisted root with post-`resolve()`
  containment check, no silent overwrite, size cap.

## Architectural Patterns

### Pattern 1: Dual-backend read plane (#58/#70) — Contacts and Safari fit it

**What:** `runtime.read_via_sqlite(path, fingerprint, query, fallback=None, immutable=)`
opens a system store strictly read-only (`mode=ro`, optional `immutable=1`), verifies a
column-level schema fingerprint, and degrades to an AppleScript `fallback` on missing
Full Disk Access or schema drift — never a silent empty result, never a raw exception.
Notes (`notes.py`) and Messages (`messages.py`) already build on this with zero new
plumbing; that is the design's proof point.

**When to use:** Any read that's currently AppleScript-only and slow (O(n) enumeration)
where Apple keeps a queryable file on disk.

**Applies to Contacts:** `~/Library/Application Support/AddressBook/Sources/<uuid>/AddressBook-v22.abcddb`
(also a top-level `AddressBook-v22.abcddb` for the local source) is a real sqlite store.
Contacts today (`adapters/contacts.py`) is 100% osascript — no sqlite plane exists yet.
#95's "sqlite-backed fast search" is a **new** dual-backend build on `read_via_sqlite`,
fingerprinted against whatever columns the search needs (name, org, phone, email),
falling back to the existing `_SEARCH` AppleScript on drift/no-FDA. **Needs Full Disk
Access** (same tier as Messages/Notes) — verify the exact schema on-device before
committing to column names; this store is one of the least-documented Apple sqlite
formats and multi-source (iCloud + on-My-Mac + Exchange) fan-out is the likely
complication, mirroring Messages' handle fan-out problem.

**Applies to Safari:** Two DIFFERENT stores, not one dual-backend plane:
- **Bookmarks + Reading List** live in `~/Library/Safari/Bookmarks.plist` — a
  **binary/XML plist**, not sqlite. `read_via_sqlite` doesn't apply as-is; this needs a
  parallel `read_via_plist`-shaped helper (or a thin wrapper using `plistlib` with the
  same FDA-preflight-then-typed-error discipline `_open_sqlite_ro` uses) — a good
  candidate to add as a sibling primitive in `runtime.py` (or, if landed after card 7,
  in whichever module owns "shared native-store readers").
- **History** lives in `~/Library/Safari/History.db` — this one IS sqlite, and
  `read_via_sqlite` applies directly with a fingerprint over `history_items`/`history_visits`.
Both need Full Disk Access. Safari currently has NO plist or sqlite reading at all
(`adapters/safari.py` is 99 lines of pure osascript) — this is greenfield relative to
the codebase, unlike Contacts which at least shares the AppleScript-adapter shape.

**Trade-offs:** Every dual-backend read plane is a new schema fingerprint that macOS
can silently move on an OS update — the existing Notes/Messages fingerprints are each
scoped to only the columns actually read (`_FINGERPRINT` in `notes.py` vs the separate
`_BODY_FINGERPRINT`), which CONCERNS.md's `HEADER_FINGERPRINT`-gap finding shows is easy
to under-scope. Any new fingerprint for Contacts/Safari should be built with the query
executors first, fingerprint second — not guessed ahead of the queries.

### Pattern 2: Native worker + completion-handler bridge (`run_native_async`)

**What:** `runtime.run_native_async(start, timeout=30.0)` (runtime.py:382–410) blocks on
a GCD-delivered completion handler: `start(finish)` kicks off an async native call and
arranges for `finish(result)` to be invoked; `run_native_async` returns that result or
raises `NativeTimeout`. It already generalizes the EventKit fetch pattern and its own
docstring flags the exact gap the target work needs to close: *"APIs that deliver on
the main run loop (MapKit, NSMetadataQuery) need an NSRunLoop pump here — add it with
the first such consumer (Maps #17 / Photos #20) to validate it."*

**When to use:** Maps/Location (#98/#99) — CoreLocation's one-shot location and MapKit's
geocoding/search/ETA APIs are completion-handler-based, and (per the existing docstring)
CoreLocation callbacks may deliver on the **main run loop**, not a GCD queue, which is
a different completion path than EventKit's. This is exactly the kind of premise a
device probe should confirm before writing the adapter — same discipline the Mail
subsystem's "device-verified facts" file enforces. **Spike this on-device before coding
the Maps/Location adapter**: does `CLLocationManager`'s delegate fire on the
`mac-native` worker thread, or does it need an explicit `NSRunLoop` pump added to
`run_native_async` first? If the pump is needed, that's a `runtime.py` (or post-card-7
`eventkit.py`-adjacent) change made ONCE, reused by both Maps and any future
run-loop-delivered API — not per-adapter plumbing.

**Trade-offs:** Headless CoreLocation TCC is called out in the roadmap itself as *"the
spike"* (#99) — a server with no bundled `.app`/Info.plist usage-description historically
struggles to get `CLLocationManager` authorization at all outside a full app bundle. The
daemon's signed `.app` bundle (already required for TCC identity, per `docs/DAEMON.md`)
is the only context this has a chance of working in — stdio/venv mode almost certainly
cannot request Location authorization the way it can request EventKit access. This
should be spiked in daemon mode specifically, not stdio, before the roadmap assumes it
works in both.

### Pattern 3: One adapter, no native app behind it (Weather)

**What:** Every existing adapter maps 1:1 to a macOS app or framework (EventKit →
Calendar/Reminders app; osascript → Mail/Notes/Contacts/Photos/Safari/Music apps; CLI →
Shortcuts). Weather (#100) breaks that: WeatherKit is entitlement-blocked for a
non-Apple-Developer-Program-registered server (per ROADMAP.md's own note), so the two
live options are a keyless HTTP weather API or shelling out to the Shortcuts app's
weather actions. Either way, "the app" Weather talks to isn't on this Mac.

**Does "one adapter per app" still hold?** Yes, structurally — a `weather.py` module
implementing `get_pointers` (or a narrower `WeatherAdapter.current(location)` method,
since "search" doesn't really apply to weather) still: imports only `contracts`/`errors`
(and `httpx`, already a dependency via `daemon.py`, so no new package for the HTTP
option), never reaches into another adapter, and is instantiated once in `server.py`
alongside the other nine/ten. The "no cross-adapter reach" and "typed Protocol" rules
don't reference native calls at all — they're about module boundaries, which apply
identically to an HTTP client.

**What changes for `doctor`:** `doctor._AUTOMATION_APPS` (the tuple that drives the
Automation-consent probe) is for osascript-reached apps specifically — Weather has no
Automation surface to probe, so it does NOT get added there. What `doctor` SHOULD report
for Weather is closer to what it does for Full Disk Access checks: reachability (can the
HTTP endpoint be resolved / does the API key exist, if the chosen provider needs one) —
a new, narrower check function, not a slot in the existing Automation-probe loop. If the
Shortcuts-actions option is chosen instead, Weather isn't a new pattern at all — it's a
`run_shortcut` call against a user-authored weather shortcut, and arguably shouldn't be
its own adapter.

**Trade-offs:** A keyless HTTP weather API means an outbound network call from a
tool that today makes none (every other adapter, including Mail's send tools, acts
*through* macOS, never *out to the internet* directly) — worth flagging in the tool's
`openWorldHint`/annotation the same way `_send_tool` marks Mail/Messages sends, even
though Weather is a read, not a write. Also worth noting: this is the FIRST adapter
where `doctor`'s "responsible process holds the TCC grant" model doesn't apply at
all — there's no TCC surface for an outbound HTTPS call.

### Pattern 4: Progressive disclosure for large/attacker-controlled content (Messages attachments, Mail bodies)

**What:** The Mail subsystem already establishes the shape needed for Messages
attachments: **annotate → search → explicit bounded fetch**, never inline payload.
`mail.py`'s bodies are FTS-indexed (sidecar) then fetched by id, bounded; `mail_files.py`
writes attachments to disk only on explicit request, through an allowlisted root with a
derived (never concatenated) basename, size-capped, no silent overwrite. This is a
direct precedent for Messages attachments (#87): `chat.db`'s `attachment` table already
has paths under `~/Library/Messages/Attachments/`; the read plane should (1) list
attachment Pointers (filename, mime type, size) via the existing `messages.py`
`read_via_sqlite` plane — no new fetch needed for the LIST step — then (2) an explicit
`save_message_attachment`-shaped tool that copies to an allowlisted root using
`mail_files.py`'s exact discipline (basename derivation strips the same RTL-override/
control-char classes regardless of which app the filename came from — an attacker-picked
filename is an attacker-picked filename whether it arrived via Mail or iMessage).

**When to use:** Any binary/large payload an adapter's read plane discovers but must
not inline. Photos export (#96) is the same shape again: list Pointers cheaply, export
explicitly to disk on request — never returned inline in a tool result.

## Data Flow

### New Read Flow — Contacts sqlite fast search (#95)

```
contacts_search(query) [tool]
    ↓
ContactsAdapter.get_pointers(query)   [adapter, existing method signature unchanged]
    ↓
runtime.read_via_sqlite(ADDRESSBOOK_DB, _FINGERPRINT, _query_contacts,
                         fallback=self._search_via_osascript)
    ↓ (sqlite path)                              ↓ (FDA-denied or schema drift)
query columns → row_to_pointer                   existing _SEARCH AppleScript (osascript)
    ↓                                             ↓
read_result(pointers, plane="sqlite")   read_result(pointers, plane="applescript")
```

The `plane` field in the bounded-read envelope (contracts.py's `read_result()`) already
exists for exactly this — Mail/Notes/Messages populate it today. Contacts joining the
dual-backend pattern is additive to that envelope, not a new wire shape.

### New Write Flow — Contacts CNContactStore fit with `run_native()`

**Constraint the existing design already states (contacts.py:1–9):** a non-bundled
server can't get `CNContactStore` TCC authorization at all — no usage-description
bundle — which is *why* Contacts is osascript-only today, not an oversight. The signed
`.app` (daemon mode) DOES carry an `Info.plist` with usage descriptions, so
`CNContactStore` may become viable **in daemon mode only** once the target work reaches
Contacts writes beyond `create_contact`. If `#94`'s "update" work moves to
`CNContactStore`:
1. It goes through `run_native()` exactly like EventKit — `CNContactStore` has its own
   thread/TCC considerations documented by Apple, and the codebase's own rule ("never
   call native frameworks off arbitrary threads") applies identically.
2. It does NOT go into `eventkit.py` post-card-7 — that module is EventKit-specific by
   the card's own description. A `CNContactStore` bootstrap belongs either in
   `contacts.py` itself (adapter-owned, since Contacts is the only consumer) or, if the
   pattern is judged likely to recur (a `lyfe` native adapter that needs an authorized
   store the same shape as EventKit's), a new sibling module — decide this WHEN #94
   is planned, not now; today only Calendar/Reminders need a store, so speculative
   abstraction here is unwarranted.
3. **Spike first, on-device, in daemon mode**: does a non-Developer-Program bundle
   identity (`ren.lav.macos-apps-mcp`, self-signed Developer ID) actually get a
   `CNContactStore` grant prompt at all? If not, `#94`'s update stays osascript
   (extend the existing `_CREATE`/`_VERIFY` pattern in `contacts.py` with an `_UPDATE`
   template) and the CNContactStore idea is a dead end recorded like the Mail
   permanent-delete non-goal in CONCERNS.md.

### New Write Flow — Photos export (write-to-disk, never inline)

```
export_photo(id, dest_dir) [tool, @_write_tool or @_additive_tool — a copy, not a delete]
    ↓
PhotosAdapter.export(id, dest_dir)
    ↓
mail_files-shaped discipline (new module, e.g. adapters/photo_files.py, or reuse
  mail_files.py's helpers if they're generalized — evaluate at implementation time):
  1. resolve dest_dir against an allowlisted root (same MACOS_APPS_FILE_ROOT env var
     pattern, or a Photos-specific override)
  2. derive a safe basename from the photo's filename (same Unicode-category strip)
  3. refuse if the target already exists (no silent overwrite)
  4. osascript `export` verb (Photos IS scriptable for export, per photos.py's header
     note that Photos.app's own `search`/scripting dictionary works — export needs
     device verification of the exact AppleScript verb and its overwrite behavior,
     the same way Mail's `save` was device-verified to overwrite silently)
  5. size-cap + empty-file-is-a-failure check
    ↓
Pointer(id=photo_id, summary="exported to <path>", deeplink="")
```

**Device-verify the AppleScript `export` command's overwrite behavior before trusting
it** — `mail_files.py`'s own comment records that Mail's `save` verb silently
overwrote a 0-byte placeholder with 192 KB of real content (device-verified 2026-08-05).
Photos' `export` verb should not be assumed safe until it's been probed the same way.

## Build Order

The milestone context asks specifically about the order of the gate cuts and how they
interact with adapter depth and new-domain work. Ordering, with the dependency reason
for each step:

1. **Card 1 — native seam fail-closed for all 20 modules.** Widens
   `test_native_seam.py`'s glob from `mail*.py` (verified: `tests/test_native_seam.py`
   currently globs only `adapters/mail*.py` — the six other adapters, `doctor.py`, and
   `shortcuts.py`'s `tracked_run` are NOT covered) to `adapters/*.py` plus `doctor.py`.
   **Goes first because every other card's device-verification claims rest on tests
   actually failing closed** — if a Contacts/Photos/Safari depth change is planned
   next and its unit tests can silently dial the real app, a green suite proves
   nothing. Device proof needed: none — this is a test-harness-only change (conftest
   fixture + glob), confirmed byte-identical in the spike per PROJECT.md.

2. **Card 7 — `runtime.py` split (EventKit cluster → `eventkit.py`).** Goes before
   card 5 and before any adapter work touches `runtime.py`, because **Contacts depth
   (#94/#95) and Calendar depth (#89/#90) are the two most likely next PRs to edit
   `runtime.py`** — landing the split first means they edit the smaller, settled files.
   Byte-identical per PROJECT.md's spike summary; device proof needed: run the full
   EventKit integration suite once post-split to confirm `calendar.py`/`reminders.py`
   still resolve `eventkit.<name>` correctly (import-path change only, not logic).

3. **Card 5 — tier policy → `tiers.py`, closing doctor's import cycle.** Goes after
   1 and 7 (independent of both, but sequenced third because it's the smallest/lowest-
   risk of the three "pure move" cards and closing the cycle unblocks any future module
   that wants to read tier state without importing `server.py` — e.g., a menubar
   companion's read-only HTTP endpoint, see Platform section, will want `tiers`-derived
   state without pulling in the whole tool-registration module). Device proof needed:
   none — gates are read once at process start; moving the file doesn't change *when*
   they're evaluated (confirmed in CONCERNS.md's own fix-approach note).

4. **Card 2 — the registration record.** Goes AFTER 1/7/5 land, because the record's
   whole point is to be the single source new tools register through — landing it
   before the module boundaries settle means the record's shape has to be redesigned
   once `tiers.py` exists. This is the biggest of the gate cards (~4–6h per PROJECT.md)
   and the one every subsequent adapter-depth PR benefits from: a new Contacts `update`
   tool, a new Photos `export` tool, and a new Maps `search` tool all register through
   it with tier/audit-verb/notice-exemption correct by construction, instead of adding
   a ninth "shipped mis-classified" incident to the `usage`-tool history CONCERNS.md
   already records. Device proof needed: full `uv run pytest` + a spot-check that
   `doctor()`, `usage()`, and one destructive write (e.g. `delete_event`) still carry
   the annotations `test_tool_annotations.py` expects.

5. **Cards 3/4/9 (fake-envelope fixture, recoverable-plane preflight, timeout
   tripwire) are Mail-scoped** and can land in parallel with 1/7/5/2 — they touch only
   `mail_recover.py`/`mail_index.py`/`mail.py`/test fixtures, not the files the other
   four cards reshape. Sequence relative to each other is unconstrained by this
   milestone's target work; sequence relative to 1/7/5/2 doesn't matter because they
   share no files.

6. **`MACOS_APPS_READ_ONLY=1 uv run pytest` green + the full integration sweep** close
   the gate. This must be the LAST step before adapter-depth work starts, because it's
   the only item that validates the gate's actual promise (a regression in read-only
   mode "would not be caught" per CONCERNS.md) rather than validating one card's diff.

7. **THEN adapter depth** (Contacts/Calendar/Reminders/Messages/Photos/Safari/Notes,
   #88–#97), in any order — these are independent adapters with no cross-file
   collisions with each other. Contacts (#94/#95) and Safari (#97) are the two with the
   least existing scaffolding (no sqlite/plist plane at all today) and should get a
   device-schema-probe pass FIRST, before code, matching the Mail subsystem's
   "device-verified facts before code" discipline (`docs/mail-applescript-facts.md`).

8. **THEN new domains** (#98–#102), because PROJECT.md's own Key Decisions table
   states the owner's call explicitly: *"make sure the ones we have now are all
   working, stable, and as fully featured as possible"* before new domains. Within new
   domains, Weather (#100, no native app, no TCC) and Capture (#101, `tracked_run`-
   shaped like `shortcuts.py`) are the lowest-risk/most-precedented; Maps/Location
   (#98/#99, `run_native_async` + a from-scratch headless-CoreLocation-TCC spike) is
   the highest-uncertainty item in the whole milestone and should be spiked
   standalone, on-device, in daemon mode, before it's scheduled as a normal phase.

9. **THEN platform** (#107/#111/#113/#106, #105, #126, #127) — deliberately last per
   PROJECT.md's Key Decisions table (*"Platform … is the largest job and benefits from
   a settled registry/tier module"*). The network transport (#127) and menubar
   companion (#126) both consume `tiers.py`/the card-2 registration record most
   cleanly once those exist; building them against the pre-gate `server.py` would mean
   redoing the consumption logic when the gate lands anyway.

## Anti-Patterns (target-work-specific)

### Anti-Pattern 1: Widening the native worker for a new async surface

**What people might do:** Maps/Location's completion-handler calls, or a Weather HTTP
call, "feel" independent enough to run on their own thread/executor rather than through
the single `mac-native` worker.

**Why it's wrong:** `runtime.py`'s own comment is explicit: *"If a future app needs a
second isolated native context, give it its own executor — don't widen this one to
max_workers>1."* Widening breaks EKEventStore's thread affinity for every OTHER adapter,
not just the new one. A second dedicated executor for a specific isolated need is
allowed by that same comment; casually bumping `max_workers` is not.

**Do this instead:** Route Maps/Location through the existing `run_native`/
`run_native_async` on the same worker unless a device-verified reason (e.g. CoreLocation
genuinely needs its own run loop pumped continuously, not just per-call) requires a
second, EXPLICITLY separate executor — and if so, document why in the same style as the
existing comment, not silently.

### Anti-Pattern 2: Treating Weather as needing a native-store fingerprint

**What people might do:** Reflexively apply the dual-backend sqlite pattern (fingerprint
+ fallback) to Weather because every other new-domain adapter in this milestone uses
some native read plane.

**Why it's wrong:** There is no local store to fingerprint — an HTTP response schema is
versioned by the API provider, not by a macOS OS update, so `verify_sqlite_schema`'s
whole rationale (macOS silently renames a column) doesn't transfer. Forcing the pattern
here is speculative generality for a problem Weather doesn't have.

**Do this instead:** Weather's own defensive layer is ordinary HTTP-client hygiene
(timeout, typed error on non-2xx / malformed JSON) — reuse `errors.NativeError`'s
error-as-result philosophy (never a silent empty), but the mechanism is a `try`/`except`
around an `httpx` call, not a fingerprint.

### Anti-Pattern 3: Menubar companion re-implementing tool dispatch

**What people might do:** Build the menubar app's "browsable recovery/history" and
"lifetime stats" views by re-reading `audit.jsonl`/`usage.jsonl` directly from Swift/
whatever the companion is written in, bypassing the daemon.

**Why it's wrong:** Two readers of the same JSONL file (the daemon's `audit.py` writer
and an independent companion reader) is a race the moment the daemon ever rotates or
truncates that file — `audit.py`'s rotation logic wasn't designed with a second
concurrent reader in mind. It also duplicates the tier/permission logic the companion
would need to decide what it's allowed to show.

**Do this instead:** Per PROJECT.md's own framing (*"a client of the daemon, not a
replacement for the server"*), the menubar app should be an MCP client (the same shim
role the stdio clients use) calling `usage()`/`audit()` as regular tool calls over the
existing UDS, OR — if a always-on background poller talking full MCP is heavier than
wanted — a narrow, additional read-only HTTP endpoint the daemon itself serves (see
Platform section), never a second process reading the daemon's on-disk state files
directly.

## Integration Points

### External Services / Native Frameworks (new for this milestone)

| Service/Framework | Integration Pattern | Notes |
|---|---|---|
| AddressBook (`AddressBook-v22.abcddb`) | `runtime.read_via_sqlite`, new fingerprint | Needs Full Disk Access; multi-source (iCloud/on-My-Mac/Exchange) — verify fan-out on device before assuming one flat table |
| Safari `Bookmarks.plist` | New primitive needed (plist, not sqlite) — `read_via_plist`-shaped sibling to `_open_sqlite_ro`, same FDA-preflight discipline | Binary or XML plist; `plistlib` in stdlib, no new dependency |
| Safari `History.db` | `runtime.read_via_sqlite`, new fingerprint | Needs Full Disk Access; separate store from Bookmarks — two read paths, one adapter |
| CNContactStore | `run_native()`, same worker | Only viable in daemon mode (bundle usage-description) if at all — SPIKE before committing; osascript `_UPDATE` template is the fallback plan, and the fallback is likely the actual outcome |
| MapKit/CoreLocation | `run_native_async`, possibly needs an NSRunLoop pump added (flagged in the function's own docstring) | Headless CoreLocation TCC for a non-.app-bundle process is explicitly "the spike" per ROADMAP.md; test in daemon mode specifically |
| Weather HTTP API (keyless) | Plain `httpx` call (already a dependency via `daemon.py`) — no PyObjC framework, no new package | First adapter with an outbound network call as its core mechanism, not just a fallback; consider whether it needs `openWorldHint` despite being a read |
| `screencapture` CLI | `runtime.tracked_run`, same shape as `shortcuts.py`'s `_list_entries`/`run_shortcut` | Output is a file path (an image), not stdout text — the bounded-snippet-of-stdout pattern in `shortcuts.py` doesn't directly transfer; this is closer to Photos export's write-to-disk shape |
| `chat.db` `attachment` table | `runtime.read_via_sqlite`, EXTEND existing `messages.py` fingerprint | List step is a read-plane extension, no new store; save-to-disk step reuses `mail_files.py`'s discipline |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| `server.py` ↔ `tiers.py` (new) | Direct import, no cycle | `doctor.py` and `deploy.py` import `tiers` too — this is what removes doctor's lazy `from . import server` |
| `calendar.py`/`reminders.py` ↔ `eventkit.py` (new) | Direct import, replaces `from .runtime import <9-10 names>` | Pure rename at the call sites; `runtime.run_native` itself is still imported from `runtime`, not `eventkit` |
| New adapters (`maps.py`, `weather.py`, `capture.py`) ↔ `runtime.py` | Same as existing adapters: `run_native`/`run_native_async`/`tracked_run`, never a by-name seam import (card 1 makes this enforced, not just conventional) | No new boundary type — same contract every existing adapter already honors |
| Menubar companion ↔ daemon | MCP client over UDS (preferred, matches "client not replacement") OR a new narrow read-only HTTP endpoint served alongside the MCP `http_app()` in `daemon.py`'s `serve()` | Decide based on how "always-on background poller" the companion needs to be; either way it is NOT a new process reading `audit.jsonl` directly |
| Remote MCP client (#127) ↔ daemon | New transport (TCP+TLS+auth) bound BESIDE the existing UDS `bind_socket()` in `daemon.py`'s `serve()` — uvicorn can serve two listeners from one `Config`/one process, or a second `uvicorn.Server` on the same asyncio loop | **Must not touch `_uds_client_factory`/`_UDS_TIMEOUT`/`fail_loud_on_dead_stream`** — those are shim-specific and already document why no read deadline exists (#170). A network transport gets its OWN client factory and its OWN timeout policy (a real network, unlike a local socket, DOES need bounded reads) — the "no read deadline" reasoning explicitly does not transfer to a remote link with actual network failure modes |
| `.mcpb` / brew cask / Claude Code plugin (#107/#106) ↔ `scripts/build_app.sh` | Packaging wraps the EXISTING signed `.app` output; it does not change what `build_app.sh` produces | A `.mcpb` bundle is a manifest pointing at the same shim invocation `docs/DAEMON.md` already documents (`command`/`args` with `-E -s -P -m macos_apps_mcp shim`); a brew cask installs the `.app` to `/Applications` and can drive `install-agent` as its `postflight` — neither requires a new build target |

## Sources

- In-repo, read directly (all HIGH confidence, verified against current `develop`
  @ d9ac75f):
  - `macos_apps_mcp/runtime.py` (734 lines, full read)
  - `macos_apps_mcp/server.py` (lines 1–300 read directly; registries/decorators)
  - `macos_apps_mcp/doctor.py` (`_AUTOMATION_APPS`, circular-import note)
  - `macos_apps_mcp/daemon.py` (full read — UDS bind, timeout policy, shim/proxy)
  - `macos_apps_mcp/deploy.py` (role detection function list)
  - `macos_apps_mcp/adapters/contacts.py`, `safari.py`, `notes.py`, `messages.py`,
    `photos.py`, `shortcuts.py` (full or header+key-section reads)
  - `macos_apps_mcp/adapters/mail_index.py` (FTS5 sidecar section, lines 1119–1257)
  - `macos_apps_mcp/adapters/mail_files.py` (write-to-disk safety discipline)
  - `macos_apps_mcp/contracts.py` (`ContactData`/`NoteData` dataclass shapes)
  - `tests/test_native_seam.py` (confirms the glob is Mail-scoped today)
  - `pyproject.toml` (confirms `httpx` already a dependency; MapKit/CoreLocation/
    WeatherKit frameworks NOT currently vendored)
  - `docs/ROADMAP.md` (issue numbers, prior-art column, "entitlement-blocked"/
    "headless CoreLocation TCC is the spike" phrasing)
  - `docs/DAEMON.md`, `CLAUDE.md`, `DESIGN.md`, `.planning/codebase/{ARCHITECTURE,
    STRUCTURE,CONCERNS}.md`, `.planning/PROJECT.md` (required reading, cited
    throughout)

---
*Architecture research for: macos-apps-mcp target milestone (spiked review gate → adapter depth → new domains → platform)*
*Researched: 2026-08-28*
