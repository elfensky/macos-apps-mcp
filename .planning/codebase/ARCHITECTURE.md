<!-- refreshed: 2026-08-28 -->
# Architecture

**Analysis Date:** 2026-08-28

## System Overview

```text
┌───────────────────────────────────────────────────────────────────┐
│              FastMCP Server (macos-apps-mcp)                      │
│  `macos_apps_mcp/server.py` — tool registration + thin dispatch  │
├─────────────────┬───────────────────────┬─────────────────────────┤
│   Event-Kit     │   AppleScript/CLI     │     SQLite/Swift        │
│   Adapters      │   Adapters            │     Adapters            │
├─────────────────┼───────────────────────┼─────────────────────────┤
│ • Calendar      │ • Mail                │ • Notes                 │
│ • Reminders     │ • Contacts            │ • Messages              │
│                 │ • Photos              │                         │
│                 │ • Safari              │                         │
│                 │ • Shortcuts           │                         │
│                 │ • Music               │                         │
└─────────────────┴───────────────────────┴─────────────────────────┘
         ↓                ↓                      ↓
┌───────────────────────────────────────────────────────────────────┐
│   Contracts Layer (`macos_apps_mcp/contracts.py`)                 │
│   PointerSource Protocol + typed write dataclasses                │
│   (read uniform, writes per-adapter typed)                        │
└───────────────────────────────────────────────────────────────────┘
         ↓
┌───────────────────────────────────────────────────────────────────┐
│  Runtime + Native Layer (`macos_apps_mcp/runtime.py`)            │
│  • Single serialized worker thread (EventKit thread affinity)     │
│  • run_native(fn) executor + osascript dispatch                  │
│  • EventKit store (owned, shared, lazy-created)                  │
└───────────────────────────────────────────────────────────────────┘
         ↓                ↓                      ↓
┌────────────────┬─────────────────┬───────────────────────────────┐
│  EventKit      │  osascript      │  Native stores                │
│  (Calendar,    │  (Mail, Notes,  │  • Envelope Index (Mail)      │
│   Reminders)   │   Contacts,     │  • chat.db (Messages)         │
│                │   Photos,       │  • NoteStore.sqlite (Notes)   │
│                │   Safari)       │  • other read-at-rest sources │
└────────────────┴─────────────────┴───────────────────────────────┘

DUAL MODES:
┌──────────────────────────┐  ┌───────────────────────────────────┐
│  stdio/venv mode (dev)   │  │  daemon mode (production, #71)     │
│                          │  │                                   │
│ • spawned per-launcher   │  │ • signed .app + launchd           │
│ • TCC identity per       │  │ • TCC identity: bundle identity   │
│   launcher               │  │   (one grant set for all clients) │
│ • stdio transport        │  │ • unix socket: ~/.local/state/... │
└──────────────────────────┘  │ • shim per-connection             │
                              │ • daemonmode's `run_shim()`       │
                              └───────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| **server** | FastMCP app + tool registration with three capability tiers (read/write/outbound) gated at registration; thin 1–2 line dispatch to adapters | `macos_apps_mcp/server.py` |
| **contracts** | Pointer + PointerSource Protocol (reads); typed write dataclasses; datetime normalization (naive-local); bounded-read envelope; deletion result | `macos_apps_mcp/contracts.py` |
| **runtime** | Single serialized ThreadPoolExecutor (max_workers=1) for EventKit thread affinity; EventKit store ownership; osascript dispatch with timeout + error classification | `macos_apps_mcp/runtime.py` |
| **errors** | Typed error taxonomy (9 NativeError subclasses); write-policy helpers (resolve_container, verify_persisted, refused_write); agent-directed remediation strings | `macos_apps_mcp/errors.py` |
| **text** | Output hygiene (control-strip, smart-punct normalization, truncation with markers), summary builders | `macos_apps_mcp/text.py` |
| **audit** | Append-only JSONL audit trail for every write; before-state capture via Snapshotter Protocol; per-tool usage tally; AuditMiddleware seam | `macos_apps_mcp/audit.py` |
| **doctor** | Read-only diagnostics (EventKit status, Automation probes, Full Disk Access check, TCC grant inventory, deployment mode/agent status) | `macos_apps_mcp/doctor.py` |
| **lifecycle** | PPID orphan watcher (stdio), atexit child cleanup, AppleScript-side `with timeout` for self-termination | `macos_apps_mcp/lifecycle.py` |
| **daemon** | Unix socket bind/listen (0700 dir / 0600 file, single-instance semantics), StreamableHTTPTransport proxy (no read deadline), fail-loud-on-dead-stream | `macos_apps_mcp/daemon.py` |
| **deploy** | Dual-mode detection (argv-based role); allow_send toggle (file + env); bundle identity verification; install-agent CLI roles (register/unregister agent, check status, grant identity map from TCC) | `macos_apps_mcp/deploy.py` |
| **Adapters** | One per app; implement PointerSource (get_pointers) and typed write methods (create_*, update_*, delete_*); no cross-adapter imports | `macos_apps_mcp/adapters/*.py` |
| **mail_index** | Envelope Index reader (mode=ro); FTS5 body sidecar builder; row-to-Pointer mapper with schema fingerprint | `macos_apps_mcp/adapters/mail_index.py` |
| **mail_addressing** | RFC822 Message-ID mapping (three id types: global_message_id, RFC822, url-friendly); id resolution (locate → account + folder + exact message); the one bounded-read envelope builder per tool | `macos_apps_mcp/adapters/mail_addressing.py` |
| **mail_recover** | Recoverable destructive plane (locate → backup → log → act → receipt); dry-run support; undo plan assembly | `macos_apps_mcp/adapters/mail_recover.py` |
| **mail_outgoing** | Outbound lifecycle (envelope → would_send shape → construct → send → outbox verification); unified quote preamble | `macos_apps_mcp/adapters/mail_outgoing.py` |
| **mail_triage** | Needs-response / awaiting-reply reads (ranked Pointers with reason field) | `macos_apps_mcp/adapters/mail_triage.py` |
| **mail_drafts** | Draft lifecycle (create / open-compose / resend); refusals for attachment + reply/forward cases | `macos_apps_mcp/adapters/mail_drafts.py` |
| **mail_attachments** | Attachment read (list by message) with per-attachment id (MIME part path) | `macos_apps_mcp/adapters/mail_attachments.py` |
| **mail_files** | Untrusted-mail-to-filesystem safety (basename derivation, symlink resolution, containment check, overwrite refusal, size cap); root allowlist + env var override | `macos_apps_mcp/adapters/mail_files.py` |
| **mailbox_url** | Mailbox URL grammar parser/builder (`<scheme>://<uuid>/<path>`); account extraction; copy-rank + trash-ness classification from one shared vocabulary | `macos_apps_mcp/adapters/mailbox_url.py` |

## Pattern Overview

**Overall:** FastMCP adapter-dispatch server with Protocol-based contracts, typed errors, and a serialized native worker thread.

**Key Characteristics:**
- **Reads are uniform** (`PointerSource.get_pointers(query) → list[Pointer]`); **writes are per-adapter typed** (no stringly-typed create_item(dict))
- **One adapter per app** — module boundaries are load-bearing (clean seams for future `lyfe` native adapters)
- **Error-as-result, never exceptions** — NativeError taxonomy wrapped as ToolError by dispatch layer; agent sees `isError` with remediation directive
- **Typed native errors** — distinguishes access-denied / app-not-running / automation-denied / timeout / verification-failed / schema-drift
- **All EventKit access serialized** — single max_workers=1 executor owns thread affinity + TCC prompt handling
- **Capability gating at registration** — read/write/outbound tools are present or absent, never registered-and-erroring; a gated-off tool is *absent* to the agent

## Layers

**Tool Layer:**
- Purpose: FastMCP @mcp.tool() registrations; categorize by capability tier (_read_tool / _additive_tool / _write_tool / _send_tool)
- Location: `macos_apps_mcp/server.py` (lines 159–195, 200+)
- Contains: One-line dispatchers to adapters; error wrapping via @_guard; Pointer serialization via delegation to adapter
- Depends on: contracts (parse functions, Pointer, NativeError), adapters (all 10 adapters instantiated at module scope)
- Used by: FastMCP runtime; audit middleware (reads _WRITE_TOOLS registry for coverage)

**Adapter Layer:**
- Purpose: Implement PointerSource (reads) and typed write methods per app
- Location: `macos_apps_mcp/adapters/` (calendar.py, reminders.py, mail.py, notes.py, contacts.py, photos.py, safari.py, messages.py, shortcuts.py, music.py) + mail support modules
- Contains: read methods (implement PointerSource; return Pointers or bounded-read envelope); write methods (take typed dataclasses; return Pointer or deletion_result); native dispatch via runtime.run_native or osascript
- Depends on: contracts (Pointer, dataclasses, datetime helpers), runtime (run_native, run_osascript), errors (typed taxonomy)
- Used by: server.py (tool dispatch); audit middleware (snapshot sources)

**Contracts Seam:**
- Purpose: Define reads (PointerSource Protocol) and writes (typed dataclasses); Pointer citation grammar; bounded-read envelope
- Location: `macos_apps_mcp/contracts.py`
- Contains: Pointer (id, summary, deeplink, optional folder/account); PointerSource Protocol; CalendarEventData / ReminderData / ContactData / NoteData; parse functions (datetime, optional, recurrence); deletion_result / read_result envelopes
- Depends on: nothing (contracts is foundational; adapters import it, never vice-versa)

**Runtime/Native Layer:**
- Purpose: Serialize EventKit to one thread; dispatch osascript; classify native errors; manage lifecycle
- Location: `macos_apps_mcp/runtime.py` (core); `macos_apps_mcp/errors.py` (taxonomy); `macos_apps_mcp/doctor.py` (diagnosis); `macos_apps_mcp/lifecycle.py` (cleanup)
- Contains: run_native(fn) executor; EventKit store creation + thread affinity check; osascript with timeout + error parsing; error classification (automation denied / app not running / timeout → native codes); TCC-identity probing (doctor)
- Depends on: EventKit (PyObjC), Foundation, subprocess (osascript), errors (NativeError, AccessDenied, etc.)
- Used by: adapters (every native call wrapped in run_native or osascript dispatch)

**Audit/Deployment Layer:**
- Purpose: Audit trail (write logging with before-state); daemon/shim split; capability gating
- Location: `macos_apps_mcp/audit.py` (JSONL log + AuditMiddleware); `macos_apps_mcp/daemon.py` (socket + proxy); `macos_apps_mcp/deploy.py` (role detection + allow_send)
- Contains: audit_write (append-only JSONL + rotation); AuditMiddleware (captures before-state via Snapshotter on id-addressed writes); socket bind (single-instance semantics) + StreamableHTTPTransport; role detection (argv, not env); allow_send file reader
- Depends on: contracts (Snapshotter Protocol), httpx/uvicorn (proxy), pathlib, sqlite3 (TCC read)

**Mail Subsystem (specialized):**
- The Mail adapter (`mail.py`) is decomposed across 9 modules for clean seams (verified by grep for no cross-imports):
  - `mail_index.py`: Envelope Index reader (locates messages by header/subject/sender; builds FTS body sidecar)
  - `mail_addressing.py`: RFC822 Message-ID mapping + id resolution + bounded-read envelope
  - `mail_recover.py`: Recoverable destructive plane (locate → backup → log → act → receipt; dry-run support)
  - `mail_outgoing.py`: Outbound lifecycle (unified quote, send/reply_all/forward/send_mail discipline)
  - `mail_triage.py`: Triage reads (needs-response / awaiting-reply ranked Pointers)
  - `mail_drafts.py`: Draft lifecycle (create / open-compose / resend; refusals for attachment + reply/forward)
  - `mail_attachments.py`: Attachment reads with per-attachment id
  - `mail_files.py`: Save-attachment-to-filesystem with safety (basename, symlink, containment, size)
  - `mailbox_url.py`: Mailbox URL grammar (`scheme://uuid/path`) parser/builder
  - `mail.py`: Delegation to the above modules; the MailAdapter class that registers read/write tools

## Data Flow

### Primary Read Path (Search/List)

1. **Tool call** → `@_read_tool` wrapper (server.py, line 159)
2. **Dispatch** → adapter.get_pointers(query) or adapter.list_* (server.py, one-line tool bodies)
3. **Read** → adapter queries Envelope Index / EventKit / chat.db / NoteStore / osascript (adapters/\*.py)
4. **Conversion** → Pointer(id, summary, deeplink, optional folder/account) (adapters/\*.py)
5. **Bounds check** → read_result(results, cap, truncated?, plane?, coverage?) (contracts.py)
6. **Return** → JSON array of Pointer dicts via TextContent (FastMCP marshaling)

**For Mail specifically (deepest/slowest path):**
1. Tool call (e.g., `mail_search(query)`)
2. `mail_index.build_query_* + execute` (Envelope Index read-at-rest, never Mail.app)
3. OR fallback to `run_osascript(mail.sdef AppleScript)` on schema drift
4. `mail_index.row_to_pointer` + `mail_addressing.resolve` (id verification, account+folder context)
5. `read_result` envelope (truncated if exact cap, coverage note if index incomplete)

### Primary Write Path (Create/Update/Delete)

1. **Tool call** → `@_write_tool(snapshot=snapshotter)` or `@_send_tool(adapter)` (server.py)
2. **Argument parsing** → typed dataclass (e.g., CalendarEventData, ContactData) at tool boundary
3. **AuditMiddleware pre-hook** → snapshotter(id) → before-state Pointer (only for id-addressed updates/deletes)
4. **Dispatch** → adapter.create_*/update_*/delete_* (server.py, one-line bodies)
5. **Native call** → run_native(fn) on serialized worker, OR run_osascript for Mail/Contacts/etc.
6. **Verify-after-write** → re-fetch by id, diff against request (mail verify is per-message location check; EventKit recurrence-signature verification)
7. **Audit write** → append {ts, tool, args, before, after, duration} to audit.jsonl (AuditMiddleware post-hook)
8. **Return** → Pointer (create/update) or deletion_result({deleted: id}) (delete); dry_run invokes 5-6 only, skips 7-8

**For Mail Destructive (recoverable plane, #159):**
1. Locate (Envelope Index search)
2. Backup (copy .emlx file to ~.local/state/macos-apps-mcp/backups/)
3. Log (append target + dry-run result to audit before native call)
4. Act (run osascript move/trash on concrete IDs)
5. Receipt (append completion + undo-plan to audit)
6. Dry-run returns {would_delete: <Pointer>}; real run returns {deleted: id}; undo is appended separately

### State Management

**No module-level mutable state** except:
- `_executor` (ThreadPoolExecutor, immutable handle in runtime.py)
- `_store` (EKEventStore, lazy-created on worker thread, immutable after init)
- Registries in server.py (`_WRITE_TOOLS`, `_SNAPSHOT_SOURCES`, `_SEND_TOOLS`) populated at import time, read-only after

**Audit state** lives on disk (audit.jsonl under XDG_STATE_HOME); read on-demand, not cached.

**Daemon socket** lives on disk (~/.local/state/macos-apps-mcp/daemon/mcp.sock); bound once at startup, single-instance.

## Key Abstractions

**Pointer:**
- Purpose: Citation grammar (cockpit convention `[src:: system:id]` + open-in-app deeplink)
- Location: `macos_apps_mcp/contracts.py` (dataclass, ~50 lines)
- Fields: id (required), summary (required), deeplink (required), folder (optional for Mail), account (optional for Mail/Messages)
- Pattern: Built by adapter row-to-Pointer mappers; never the full body (pointers-not-payload); serialized to dict via as_dict()
- Example: `Pointer(id="event_abc", summary="Team standup 9am–10am", deeplink="calshow:123456")`

**PointerSource Protocol:**
- Purpose: Uniform read interface (every search/list implements this)
- Location: `macos_apps_mcp/contracts.py` (Protocol, ~3 lines)
- Method: `get_pointers(query: str, limit: int = 50) -> list[Pointer]`
- Pattern: Adapters implement; all SearchPointerSource instances share signature; tests mock via Protocol-conforming fakes
- Usage: Calendar/Reminders/Notes/Mail/Contacts/Photos/Messages/Safari implement it; tools call via adapter method

**Snapshotter Protocol:**
- Purpose: Before-state capture for audit trail, without coupling audit to every adapter
- Location: `macos_apps_mcp/contracts.py` (Protocol, ~3 lines)
- Method: `snapshot(id: str) -> Pointer | None`
- Pattern: Adapters register their snapshotter at tool registration (`@_write_tool(snapshot=adapter.snapshot)`); AuditMiddleware calls it before the write
- Usage: calendar.snapshot(event_id) → Pointer; reminders.snapshot(reminder_id) → Pointer

**NativeError Hierarchy:**
- Purpose: Typed, loud error handling (agent-directed remediation)
- Location: `macos_apps_mcp/errors.py` (9 subclasses)
- Kinds: AccessDenied, AutomationDenied, AppNotRunning, NativeTimeout, OutputOverflow, SchemaDrift, VerificationFailed, SpanRequired, WriteRefused, RecurrenceRequired, BatchTooLarge
- Pattern: Raised in runtime/adapters; wrapped by @_guard as ToolError; str(e) is the remediation message
- Example: `raise AccessDenied("… needs Calendar access. Grant it in System Settings → Privacy & Security → Calendars, then restart.")`

**Recoverable Destructive Plane (Mail only):**
- Purpose: Make destructive writes auditable and undoable (locate → backup → log → act → receipt)
- Location: `macos_apps_mcp/adapters/mail_recover.py` (~150 lines)
- Pattern: Every mail delete/move/trash invokes `recoverable(targets, dry_run=False)` which: (1) locates .emlx paths in Envelope Index, (2) copies to backup, (3) logs to audit, (4) invokes osascript, (5) appends receipt + undo-plan
- Usage: move_mail, trash_mail, delete_draft all use the same plane; undo chain is built from audit.jsonl
- Guarantee: Every destructive Mail operation is logged BEFORE the native call, so audit.jsonl is authoritative

**Bounded-Read Envelope:**
- Purpose: Signal truncation + fallback plane + index coverage in ONE wire shape
- Location: `macos_apps_mcp/contracts.py` read_result() function (~50 lines)
- Shape: `{results: [...], truncated?: true, plane?: "applescript", coverage?: "9713 of 22382"}`
- Pattern: Every read tool returns this (not a plain list); defect it solves: a silent under-answer reads as authoritative
- Usage: mail_search, calendar_events, notes_search all return it; plane field explains AppleScript fallback; coverage field shows index incomplete (e.g., body search only indexed 99.5% of mail)

## Entry Points

**Server Startup (stdio mode):**
- Location: `macos_apps_mcp/__main__.py`
- Invocation: `python -m macos_apps_mcp` or `<repo>/.venv/bin/python -m macos_apps_mcp`
- Responsibilities: Import server, bootstrap runtime, install lifecycle guards, invoke mcp.run()
- Flow: __main__ → server module (tool registration at import) → runtime.bootstrap() → mcp.run()

**Shim Startup (daemon mode):**
- Location: `macos_apps_mcp/__main__.py`, argv role detection
- Invocation: `<app>/Contents/MacOS/macos-apps-mcp -E -s -P -m macos_apps_mcp shim`
- Responsibilities: Detect shim role (argv check in deploy.py), connect to daemon socket, proxy client stdio to daemon
- Flow: shim role → daemon.run_shim() → _uds_client_factory() → StreamableHTTPTransport → proxy MCP messages

**Daemon Startup (daemon mode):**
- Location: `packaging/ren.lav.macos-apps-mcp.plist` (launchd) → app executable → __main__.py
- Invocation: launchd launches `/Applications/macos-apps-mcp.app/Contents/MacOS/macos-apps-mcp -E -s -P -m macos_apps_mcp daemon`
- Responsibilities: Detect daemon role (argv), bind socket (single-instance check), start uvicorn on socket fd, run FastMCP server
- Flow: daemon role → deploy.is_daemon_role() → daemon.bind_socket() → daemon.serve() → uvicorn + FastMCP

**Doctor Entry Point:**
- Location: Tool registration (server.py @_read_tool); also CLI invocation via `macos-apps-mcp` command (deploy.py)
- Invocation: `doctor()` tool call or `macos-apps-mcp doctor` CLI
- Responsibilities: Read EventKit authorization (no prompts), probe Automation (one-time consent dialog if requested), read TCC.db, report deployment mode + grant identities
- Flow: doctor() → deploy.is_daemon_role() → _check_* per service → _surface() reports → combined dict with deployment info

## Architectural Constraints

- **Threading:** All EventKit access on one `ThreadPoolExecutor(max_workers=1)` dedicated worker. osascript runs on the same worker (serialized with EventKit, never concurrent).
- **Global state:** _executor (immutable), _store (lazy, immutable after init), audit/daemon socket (on-disk, single-instance). No mutable module-level state.
- **Circular imports:** None; adapters never import server.py or each other. Contracts is foundational (imported by everyone). Errors imported by contracts + adapters + runtime.
- **Capability gating:** At registration time (module import), not runtime. MACOS_APPS_READ_ONLY and MACOS_APPS_ALLOW_SEND read once; tools are present or absent, never erroring at registration.
- **Unix socket:** ~/.local/state/macos-apps-mcp/daemon/mcp.sock (hardcoded path, not XDG_STATE_HOME, so all three processes — daemon, install-agent, client-spawned shim — agree on one rendezvous). Permissions 0700 (dir) / 0600 (file).
- **Shim/Daemon hop deadline:** No read deadline on shim↔daemon unix socket (httpx.Timeout(None, connect=10.0)). A tool's duration is the daemon's business; bulk Mail reads take hours. Only connect has a timeout (10s).
- **Read planes:** SQLite first (Envelope Index / chat.db / NoteStore); AppleScript fallback on schema drift (never silent; surfaces plane field in bounded-read envelope). Never tries both unless necessary.

## Anti-Patterns

### Stringly-Typed Writes

**What happens:** Early adopter pattern was `create_item(type: str, **kwargs)` (dictated type + kwargs)

**Why it's wrong:** No type checking; easy to miss new/renamed parameters; dispatch logic lives in the adapter; caller can't tell what's required vs optional

**Do this instead:** Typed dataclasses per adapter (CalendarEventData, ReminderData, ContactData in contracts.py; tool boundaries parse these). One write method per operation: `create_event(CalendarEventData)`, not `create_item(dict)`. Type checker catches caller errors.

### Swallowing Errors as Empty Lists

**What happens:** Early ecosystem pattern (archived supermemoryai/apple-mcp): permission denied / app crashed / timeout all returned `[]`

**Why it's wrong:** Caller can't distinguish "nothing matches" from "permission denied"; agent hammers a denied tool until timeout; no remediation path

**Do this instead:** Raise typed NativeError (AccessDenied, AppNotRunning, NativeTimeout, etc.) with str(e) = agent-directed remediation. Wrapped by @_guard as ToolError. Empty result stays `[]` when legitimate.

### Per-Adapter Native Seam Patching in Tests

**What happens:** Each adapter test file imported run_osascript / run_native into its namespace, then tests patched the import: `_patch_run_osascript()` in mail test, `_patch_run_native()` in calendar test

**Why it's wrong:** Missed patch in one module lets a test dial real Mail (#160 incident). Hard to audit which adapters are patched.

**Do this instead:** Patch once in runtime (`setattr(runtime, 'run_osascript', fake)` in conftest). Seam-tripwire test (`test_native_seam.py`) fails if an adapter imports by-name rather than calling `runtime.qualified`. All 10 adapters now call `runtime.run_*`.

### Adapter-to-Adapter Imports

**What happens:** None now, but historical risk: mail.py importing something from notes.py to reuse

**Why it's wrong:** Breaks the "one adapter per app, clean module boundary" rule. Seam cannot later harden to separate `lyfe` native adapter.

**Do this instead:** Shared logic goes to runtime.py, contracts.py, text.py, or errors.py. Adapters are read-only from each other; only server.py imports them all.

### Silent Timeouts on Shim↔Daemon Hop

**What happens:** Issue #170 — httpx default Timeout(5.0) cut the response SSE stream 5s after POST while daemon was working; client saw hang, audit.jsonl showed successful operation

**Why it's wrong:** Operation may have completed; blind retry repeats a destructive call that already succeeded; silent stream end with no error lets agent assume failure

**Do this instead:** No read deadline (Timeout(None, connect=10.0)). Fail loud on dead stream (fail_loud_on_dead_stream) returns JSON-RPC error naming audit.jsonl. Adapter enforce per-op limits (30s osascript timeout is the right layer).

## Error Handling

**Strategy:** Typed NativeError hierarchy (9 subclasses); str(e) is agent-directed remediation; wrapped by @_guard as ToolError so FastMCP never sees raw exception.

**Patterns:**
- EventKit denied → AccessDenied with grant path (System Settings → Privacy & Security → Calendars)
- osascript automation denied (-1743) → AutomationDenied with app name
- App not running (-609, -10810) → AppNotRunning ("launch Mail first")
- osascript timeout (-1712) + app IDLE → NativeTimeout with "force-quit and restart" direction
- Create/update returns wrong id → VerificationFailed with "iCloud may have reverted; check manually"
- Recurring event update without span param → SpanRequired (refuse; ask for span)
- Output too large → OutputOverflow with truncation marker
- Schema drift (OS/app change) → SchemaDrift with fallback strategy

**Write-policy helpers** (errors.py):
- `resolve_container(item, context)` → container_id or raise WriteRefused (read-only / no account)
- `verify_persisted(id, expected_fields)` → re-fetch + diff or raise VerificationFailed
- `refused_write(reason)` → raise WriteRefused with direction
- `require_batch_within(count, cap)` → raise BatchTooLarge or allow

## Cross-Cutting Concerns

**Logging:**
- Handler: Python logging module, logger name `macos_apps_mcp`
- Levels: DEBUG (audit_write failures, native dispatch), INFO (startup, deployment info), WARNING (schema drift, timeouts)
- Destination: stdout (stdio mode); unified log + launchctl output (daemon mode; not rotated by macos-apps-mcp)
- Audit trail: Separate JSONL file (~/.local/state/macos-apps-mcp/audit.jsonl) captures every write operation with before/after + undo info

**Validation:**
- Tool boundary: typed dataclass parsing (datetime, recurrence, optional fields) in contracts.py
- Adapter boundary: Pointer verification (id must exist on re-fetch), write policies (refuse read-only containers), span/recurrence/coverage checks
- Native boundary: schema fingerprint check (adapters/mail_index.py + runtime.py _open_sqlite_ro); SchemaDrift raised on mismatch

**Authentication/Authorization:**
- TCC (System Privacy & Security database) grants Calendar/Reminders/Automation/Contacts/Full Disk Access to the responsible process (app that launched the server)
- Daemon mode: One grant set per bundle identity (`ren.lav.macos-apps-mcp`); all clients share via socket
- Stdio mode: One grant set per launcher (Terminal vs Claude Desktop vs VS Code) — each needs separate grant
- Doctor tool reports the current state + remediation; doctor CLI (`macos-apps-mcp doctor`) available at deployment time to proactively request missing grants
- Capability tiers (read/write/outbound) gated at registration via MACOS_APPS_READ_ONLY (env var) and MACOS_APPS_ALLOW_SEND (env var in stdio mode, file in daemon mode)

---

*Architecture analysis: 2026-08-28*
