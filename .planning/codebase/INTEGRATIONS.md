# External Integrations

**Analysis Date:** 2026-08-28

## Native macOS Surfaces

### EventKit (Calendar & Reminders)

**Framework:** PyObjC `pyobjc-framework-EventKit>=10.0`

- **What it's used for:** Bidirectional read/write for Calendar events and Reminders tasks
- **Access method:** Direct PyObjC bridge via `EKEventStore` created in `macos_apps_mcp/runtime.py` (line 113-127)
- **Thread model:** Single `ThreadPoolExecutor(max_workers=1)` serializes all `EKEventStore` calls through dedicated worker thread to maintain thread affinity and TCC authorization consistency
- **Adapters:**
  - `macos_apps_mcp/adapters/calendar.py` — Events: read, create, update, delete (supports recurrence via RFC 5545 `RRULE` subset)
  - `macos_apps_mcp/adapters/reminders.py` — Reminders: read, create, update, complete (supports recurrence)
- **Auth:** TCC service `kTCCServiceCalendar` and `kTCCServiceReminders` (queried in `macos_apps_mcp/deploy.py`, line 24-28)
- **Grant identity:** Under daemon mode, single bundle identity `ren.lav.macos-apps-mcp` holds all grants (line 18); stdio mode varies by calling process

### AppleScript / Automation (via osascript)

**Access:** `/usr/bin/osascript` subprocess invocation from `macos_apps_mcp/runtime.py` (line 130-150 serialized on same worker thread)

**Adapters using Automation:**
- `macos_apps_mcp/adapters/mail.py` — Mail Envelope Index read (subject search, inbox queries); no send (draft creation via Mail database layer)
- `macos_apps_mcp/adapters/notes.py` — Notes title search (fallback path; primary is sqlite read)
- `macos_apps_mcp/adapters/contacts.py` — Contact search and creation via Contacts.app AppleScript dictionary
- `macos_apps_mcp/adapters/photos.py` — Photos search command invocation
- `macos_apps_mcp/adapters/safari.py` — List open tabs, open URLs
- `macos_apps_mcp/adapters/messages.py` — Conversation list (primary read path via sqlite `chat.db`)
- `macos_apps_mcp/adapters/shortcuts.py` — List and run shortcuts (via `shortcuts` CLI, not AppleScript)

**Auth:** TCC service `kTCCServiceAppleEvents` (line 24, `deploy.py`) for all Automation prompts

**Error handling:** OSStatus codes parsed from stderr (line 139-141, `runtime.py`):
- `-1743` (`_AUTOMATION_DENIED`) — Automation consent not granted
- `-609`, `-10810` (`_APP_NOT_RUNNING`) — Connection invalid / app not launchable
- `-1712` (`_APPLE_EVENT_TIMEOUT`) — App never answered; wedge detection checks process CPU (line 149)

**Timeout:** 30.0 seconds per osascript call (`_OSASCRIPT_TIMEOUT`, line 134)

### SQLite Read Planes (Read-Only via URI Parameters)

**Mode:** `?mode=ro&immutable=1` for all reads (write-protected)

**Stores:**

1. **Mail Envelope Index** (not fully integrated — see design #156)
   - Database: Mail's internal cache (envelope metadata only, no body)
   - Use: Fast subject/sender search without opening Mail
   - Adapter: `macos_apps_mcp/adapters/mail.py` (primarily AppleScript; envelope read deferred)

2. **Messages chat.db** (`~/Library/Messages/chat.db`)
   - Database: iMessage + SMS conversation history
   - Primary source for messages adapter read (`macos_apps_mcp/adapters/messages.py`, line 15)
   - Schema: `chat`, `message`, `handle` tables; message bodies in `attributedBody` (typedstream binary format)
   - Auth required: Full Disk Access (TCC service `kTCCServiceSystemPolicyAllFiles`)
   - Adapter: `macos_apps_mcp/adapters/messages.py` — read-only conversation list, ID-first pointers

3. **Notes NoteStore.sqlite** (`~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite`)
   - Database: Apple Notes storage; schema includes `ZSNIPPET` (pre-indexed summary) and `ZDATA` (gzip+protobuf note content)
   - Primary path: `macos_apps_mcp/adapters/notes.py` — read via sqlite, write via AppleScript (write path is AppleScript-only)
   - Auth required: Full Disk Access
   - Adapter: `macos_apps_mcp/adapters/notes.py` (line 34 notes integration docs/projection-contract.md)
   - Schema fingerprint verification: Columns checked against expected set (`verify_sqlite_schema`, `macos_apps_mcp/runtime.py`)

**Shared read layer:** `macos_apps_mcp/runtime.py` — `_open_sqlite_ro()` hardened opener (percent-quoted URI + FDA-vs-absent preflight, lazy import to avoid dragging EventKit into CLI-only roles)

### Full Disk Access (FDA)

**Service:** TCC service `kTCCServiceSystemPolicyAllFiles` (line 28, `deploy.py`)

**Required for:**
- Reading `chat.db` (Messages adapter)
- Reading `NoteStore.sqlite` (Notes adapter)
- Reading `TCC.db` itself (grant identity reporting in `doctor`)
- Reading Mail Envelope Index (Mail data plane, future)

**Grant identity:** In daemon mode, bundle `ren.lav.macos-apps-mcp` holds FDA grant; grant must be manually enabled in System Settings → Privacy & Security → Full Disk Access (since launchd has no consent UI). See `docs/DAEMON.md` line 88-92.

### Shortcuts CLI

**Access:** `/usr/bin/shortcuts` command-line tool (not osascript)

- **What it's used for:** List available shortcuts (with UUIDs) and run shortcuts by ID
- **Adapter:** `macos_apps_mcp/adapters/shortcuts.py` — read-only list, action to run
- **Output handling:** stdout empty for most shortcuts; `-o tmpfile` flag redirects output to temp file for later read (design note, DESIGN.md line 161)
- **No permission prompt:** Shortcuts CLI does not trigger TCC consent (gateway to user automation without Automation prompt)

### Mail System Database

**No direct write access** (by design — see CLAUDE.md Mail notes).

**Read via:**
- AppleScript for Envelope Index queries (subject search, awaiting-reply triage markers)
- Outgoing message database for draft creation (via `macos_apps_mcp/adapters/mail_outgoing.py` — in-process binary manipulation, no native call)

**Write approach (future):**
- Draft creation: Open Mail, create empty message, return its ID (no auto-send)
- Send: Not exposed (outbound tier gated by `@_send_tool`, requires `MACOS_APPS_ALLOW_SEND=mail`; currently unimplemented)

## TCC (Transparency, Consent & Control) Database

**Location:**
- User TCC: `~/Library/Application Support/com.apple.TCC/TCC.db`
- System FDA: `/Library/Application Support/com.apple.TCC/TCC.db` (read-only from user process)

**Access:** Read-only sqlite for grant identity reporting in `doctor` tool (`macos_apps_mcp/deploy.py` line 88-123)

**Fingerprinting:** Column set verified against expected schema (`_TCC_FINGERPRINT` line 81)

**Auth values:** `{0: "denied", 1: "unknown", 2: "granted", 3: "limited"}` (line 85); `granted` maps to `auth_value==2`

## Launchd (Daemon Mode #71)

**Service:** LaunchAgent via `SMAppService` (not raw `.plist` files)

**Plist:** `packaging/ren.lav.macos-apps-mcp.plist` — LaunchAgent configuration
- `CFBundleIdentifier`: `ren.lav.macos-apps-mcp`
- `KeepAlive: true` + `ThrottleInterval: 10` — Auto-restart daemon on crash
- `RunAtLoad: true` — Start at login
- Executable: Bundle's Python executable with `-E -s -P -m macos_apps_mcp daemon` flags

**Registration:** `SMAppService.agentServiceWithPlistName_()` called by `macos_apps_mcp deploy.register_agent()` (line 60-63); requires running from the signed bundle, not venv

**Socket:** Unix domain socket (`SOCK_STREAM`) at `~/.local/state/macos-apps-mcp/daemon/mcp.sock` (home-pinned, not XDG-relative, so shell env doesn't matter across launchd + install-agent + shim processes)

**Transport:** FastMCP proxy over HTTP StreamableHTTPTransport (httpx AsyncHTTPTransport with `uds=str(path)`)

**Timeout tuning:** Read stream has NO deadline (`Timeout(None, connect=10.0)`) to prevent premature closure on long-running operations like bulk Mail passes (issue #170 details in `daemon.py` line 74-87)

**Error handling:** `fail_loud_on_dead_stream()` (line 115-149) patches MCP's StreamableHTTPTransport to answer JSON-RPC errors instead of silent hangs when SSE stream dies mid-response

## Unix Domain Socket Communication (Daemon Mode)

**File permissions:** Socket 0600 (owner read/write only), parent dir 0700

**Port binding:** `macos_apps_mcp/daemon.py` `bind_socket()` (line 45-71) with single-instance semantics:
- `EADDRINUSE` → probe for live owner; if refused → unlink stale socket + rebind
- If live owner detected → `AlreadyRunning` exception

**Shim process:** Per-client unix socket client spawned via `macos_apps_mcp daemon.run_shim()` (line 37-94, daemon.py)

## Outbound Integration (Send Tools — Gated)

**Gating:** Registered only when `MACOS_APPS_ALLOW_SEND` names adapter (env var, daemon-startup-time read; file fallback for daemon mode: `~/.local/state/macos-apps-mcp/allow_send`)

**Send adapters (if enabled):**
- **Mail send** (placeholder for future) — `@_send_tool("mail")` decorator, dry_run defaults True
- **Messages send** (placeholder) — `@_send_tool("messages")` decorator
- **Not implemented yet** — Infrastructure in place; actual send methods would call into draft/message builders

**Hint:** All send tools carry `openWorldHint=true` (they act off this machine, unlike local deletes)

## Audit Trail & Logging

**Write audit log:** JSONL trail of every write operation with undo info

**Location:** `~/.local/state/macos-apps-mcp/audit.jsonl` (or `$XDG_STATE_HOME/macos-apps-mcp/audit.jsonl`)

**Middleware:** `AuditMiddleware` in `macos_apps_mcp/audit.py` — tracks operations, write timestamps, and per-tool usage tally

**Usage report:** `usage_report` tool for checking tool invocation history

**Logging:** Python `logging` module; in daemon mode, output to unified log via `log show --predicate 'process == "macos-apps-mcp"'` (docs/DAEMON.md line 252-258)

## CI/CD & Publishing

**GitHub Actions:**
- **Publish workflow** (`.github/workflows/publish.yml`): Runs on macOS runner (`macos-latest`)
- **Triggers:**
  - Push to `main` → auto-publish to TestPyPI
  - Manual `workflow_dispatch` → select testpypi or pypi target
- **Auth:** Trusted Publishing (OIDC) — no stored API tokens
- **Verification step:** `uv sync --locked`, `pytest`, `ruff check` + format check before build

**Notarization (daemon builds):**
- Tool: `xcrun notarytool` (one-time keychain profile setup: `notarytool store-credentials PROFILE --apple-id ... --team-id VUMUR696L9`)
- Invoked by: `scripts/build_app.sh --notarize PROFILE --out dist`
- Result: Stapled ticket attached to `.app` bundle

**Code signing:**
- Certificate: Developer ID Application: Andrei M. Lavrenov (VUMUR696L9)
- Flags: `--timestamp --options runtime` (hardened runtime enabled)
- Process: Inside-out (every `.so`/`.dylib` → executable → bundle, never `--deep`)

## Blocked Integrations (By Design)

**Not integrated:**
- **Apple Journal** — No write API, no AppleScript dictionary, E2E-encrypted entries (DESIGN.md line 183)
- **Apple Photos PhotoKit** — Conflicts with EventKit's pyobjc-core pin; Photos search via osascript only (pyproject.toml line 43)
- **Arbitrary osascript execution** — Scoped to typed adapters only; no `execute_applescript` tool (DESIGN.md line 175)
- **Cloud storage** — No iCloud sync, backup, or reconciliation (v1 is outbound projection + id-mediated reconcile, not a general sync engine)

---

*Integration audit: 2026-08-28*
