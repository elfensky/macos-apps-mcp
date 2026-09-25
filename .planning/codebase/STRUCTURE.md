# Codebase Structure

**Analysis Date:** 2026-08-28

## Directory Layout

```
macos-apps-mcp/                          # Root — FastMCP server for native macOS apps
├── macos_apps_mcp/                      # Main package
│   ├── __init__.py                      # Package root (imports from server at module load)
│   ├── __main__.py                      # CLI entry point (stdio + daemon/shim startup)
│   ├── server.py                        # FastMCP app + tool registration (thin dispatch)
│   ├── contracts.py                     # Pointer + PointerSource Protocol + write dataclasses
│   ├── runtime.py                       # Single serialized EventKit worker thread + osascript dispatch
│   ├── errors.py                        # Typed error taxonomy (pure, no native imports)
│   ├── text.py                          # Output hygiene (truncation, punct norm, summaries)
│   ├── audit.py                         # Write-audit JSONL + AuditMiddleware + usage tally
│   ├── doctor.py                        # Read-only diagnostics (TCC, EventKit, Automation)
│   ├── lifecycle.py                     # Orphan watcher + atexit cleanup + signal handlers
│   ├── daemon.py                        # Unix socket bind/listen + StreamableHTTPTransport proxy
│   ├── deploy.py                        # Dual-mode detection (stdio/daemon) + allow_send toggle + install-agent roles
│   └── adapters/                        # One module per app (+ mail support modules)
│       ├── __init__.py
│       ├── calendar.py                  # Calendar adapter (EventKit, PyObjC)
│       ├── reminders.py                 # Reminders adapter (EventKit, PyObjC)
│       ├── mail.py                      # Mail adapter (thin delegation to mail_* modules)
│       ├── mail_index.py                # Envelope Index reader (sqlite, mode=ro)
│       ├── mail_addressing.py           # RFC822 Message-ID mapping + id resolution
│       ├── mail_recover.py              # Recoverable destructive plane (locate→backup→log→act→receipt)
│       ├── mail_outgoing.py             # Outbound lifecycle (send/reply_all/forward/send_mail)
│       ├── mail_triage.py               # Triage reads (needs-response/awaiting-reply)
│       ├── mail_drafts.py               # Draft lifecycle (create/open/resend)
│       ├── mail_attachments.py          # Attachment reads (per-message list)
│       ├── mail_files.py                # Save-attachment-to-disk (safety: basename, symlink, containment)
│       ├── mailbox_url.py               # Mailbox URL grammar (scheme://uuid/path parser/builder)
│       ├── notes.py                     # Notes adapter (EventKit read; osascript write; NoteStore.sqlite fallback)
│       ├── contacts.py                  # Contacts adapter (osascript + AddressBook)
│       ├── messages.py                  # Messages adapter (chat.db sqlite reader, mode=ro)
│       ├── photos.py                    # Photos adapter (osascript)
│       ├── safari.py                    # Safari adapter (osascript)
│       ├── shortcuts.py                 # Shortcuts adapter (CLI: shortcuts list/run)
│       └── music.py                     # Music adapter (osascript + MediaPlayer.framework)
├── tests/                               # Unit + integration tests
│   ├── conftest.py                      # Pytest fixtures (fake adapters, audit fixture, runtime seam guard)
│   ├── test_*.py                        # Unit tests (~1,500 tests, Protocol-based mocking)
│   ├── test_native_seam.py              # Tripwire: fails if adapter imports run_native/osascript by-name
│   ├── test_applescript_timeout.py      # Timeout behavior per adapter
│   ├── test_contracts.py                # Pointer, dataclass parsing, datetime normalization
│   ├── test_errors.py                   # Error taxonomy, write policies
│   ├── test_server_capabilities.py      # Capability gating (read/write/outbound)
│   ├── test_tool_annotations.py         # Asserts every write tool has correct annotations
│   └── integration/                     # Device/real-app tests (marked @pytest.mark.integration, never in CI)
│       └── test_*.py                    # Real EventKit, Mail, Contacts, etc. (run manually on macOS)
├── docs/                                # Documentation
│   ├── DAEMON.md                        # Daemon/shim deployment (#71), installation, troubleshooting
│   ├── ROADMAP.md                       # Features + architecture reviews (features 0.9.x–0.11.x)
│   ├── RELEASING.md                     # Version bump + build + tag + release procedure
│   ├── mail-applescript-facts.md        # Device-verified Mail traps (delete behavior, autosave lag, etc.)
│   ├── superpowers/                     # Guides for related tools (Claude Code, vault, etc.)
│   └── ...                              # Other reference docs
├── scripts/                             # Build scripts
│   ├── build_app.sh                     # Build signed .app (inside-out code sign, notarize, zip)
│   └── ...
├── packaging/                           # LaunchAgent + code-signing
│   ├── ren.lav.macos-apps-mcp.plist     # LaunchAgent plist (daemon startup, KeepAlive, log redirection)
│   ├── entitlements.plist               # Code signing entitlements (hardened runtime, etc.)
│   └── ...
├── .planning/                           # GSD codebase docs (this directory)
│   └── codebase/
│       ├── ARCHITECTURE.md              # Architecture & layers (this file)
│       ├── STRUCTURE.md                 # Directory layout & naming (this file)
│       └── ...
├── pyproject.toml                       # uv + pytest + ruff config
├── uv.lock                              # Locked dependencies (FastMCP 3.x, uvicorn, httpx, etc.)
├── DESIGN.md                            # Design rationale (settled decisions, adversarial debate)
├── CLAUDE.md                            # Project conventions + architecture constraints
├── README.md                            # User-facing quick-start
└── .gitignore

```

## Directory Purposes

**macos_apps_mcp/:**
- Purpose: Main package — FastMCP server + adapter dispatch + cross-cutting concerns
- Contains: server.py (tool registration), contracts.py (Pointer + Protocol), runtime.py (EventKit worker), audit/doctor/errors/text/lifecycle (middleware), daemon/deploy (dual-mode), adapters/ (per-app modules)
- Key files: `server.py` (entry point for registration), `contracts.py` (read/write seam), `runtime.py` (native worker)

**macos_apps_mcp/adapters/:**
- Purpose: One module per app; implement PointerSource (reads) + typed write methods
- Contains: calendar.py, reminders.py, mail.py (+ 9 support modules), notes.py, contacts.py, messages.py, photos.py, safari.py, shortcuts.py, music.py
- Pattern: No cross-imports. Each adapter file is ~200–600 lines; mail.py is delegation-only (~2,000 lines total across 9 modules for the subsystem)
- Key imports: adapters import contracts (Pointer, dataclasses) + runtime (run_native, osascript) + errors; server.py imports all

**tests/:**
- Purpose: Unit tests (Protocol-based mocking) + integration tests (real native calls on device)
- Contains: conftest.py (fixtures, audit capture, runtime seam guard), ~1,500 unit test definitions (mocked at Protocol boundary), test_native_seam.py (tripwire for by-name imports), integration/ (device tests, @pytest.mark.integration)
- Pattern: Unit tests import fake adapters implementing contracts.Protocol; no native calls. Integration tests use real adapters; run manually, never in CI.
- Coverage: audit.py, doctor.py, errors.py, text.py, contracts.py have unit test files; each adapter has unit tests; mail.py has 277 test defs (mail subsystem is complex); integration/ has device-specific tests

**docs/:**
- Purpose: Reference docs for operators, developers, troubleshooters
- Contains: DAEMON.md (deployment + TCC grant flow + troubleshooting), ROADMAP.md (feature plan + architecture reviews), RELEASING.md (version bump checklist), mail-applescript-facts.md (device-verified Mail quirks), superpowers/ (integration guides with Claude Code, vault, etc.)
- Key reads: DAEMON.md for daemon mode installation; ROADMAP.md for architecture rationale; mail-applescript-facts.md before touching Mail code

**scripts/:**
- Purpose: Build automation
- Contains: build_app.sh (code-sign + notarize + zip the .app), optional CI scripts
- Key script: build_app.sh — only safe way to produce a signed/notarized bundle for distribution

**packaging/:**
- Purpose: LaunchAgent + code-signing artifacts
- Contains: ren.lav.macos-apps-mcp.plist (LaunchAgent registration, KeepAlive/RunAtLoad, environment, socket path), entitlements.plist (hardened runtime, network/socket entitlements)
- Pattern: Not deployed by setup.py; deployed by scripts/build_app.sh into the .app bundle structure

## Key File Locations

**Entry Points:**
- `macos_apps_mcp/__main__.py`: stdio/daemon/shim startup (role detection via argv; calls server/__main__ or daemon.serve() or daemon.run_shim())
- `macos_apps_mcp/server.py` (line 47): `mcp = FastMCP("macos-apps-mcp")` — the app instance; tool registration at module scope
- `macos_apps_mcp/daemon.py` (serve): daemon socket bind + uvicorn startup
- `packaging/ren.lav.macos-apps-mcp.plist`: LaunchAgent plist for daemon auto-start

**Configuration:**
- `pyproject.toml`: uv (dependencies, lock), pytest (markers, coverage), ruff (lint/format, line-length 88)
- `pyproject.toml` [project.scripts]: `macos-apps-mcp` CLI (install-agent, uninstall-agent, allow-send, doctor roles)
- `macos_apps_mcp/deploy.py`: MACOS_APPS_READ_ONLY (env var), MACOS_APPS_ALLOW_SEND (env var or file), MACOS_APPS_MCP_SOCKET (socket path override), MACOS_APPS_MCP_ROLE (daemon vs stdio, set by __main__)
- `.env` (not checked in): test-only overrides (MACOS_APPS_ALLOW_SEND=mail for integration tests)

**Core Logic:**
- `macos_apps_mcp/server.py`: Tool registration (@_read_tool, @_write_tool, @_send_tool, @_additive_tool), capability gating (_read_only, _allow_send), dispatch to adapters
- `macos_apps_mcp/contracts.py`: Pointer (citation), PointerSource (read Protocol), write dataclasses (CalendarEventData, etc.), parse functions (datetime, recurrence)
- `macos_apps_mcp/runtime.py`: run_native (ThreadPoolExecutor), EventKit store creation, run_osascript with timeout + error parsing
- `macos_apps_mcp/errors.py`: 9 NativeError subclasses + write-policy helpers

**Testing:**
- `tests/conftest.py`: pytest fixtures (audit fixture, fake_store, fake_adapters per Protocol, runtime seam patcher)
- `tests/test_contracts.py`: Pointer, parse functions, datetime normalization (naive-local DST handling)
- `tests/test_errors.py`: Error taxonomy, write policies (resolve_container, verify_persisted)
- `tests/test_server_capabilities.py`: Capability gating (MACOS_APPS_READ_ONLY skips writes, MACOS_APPS_ALLOW_SEND gates sends)
- `tests/test_tool_annotations.py`: Asserts every write tool has destructiveHint=True, every send tool has openWorldHint=True

## Naming Conventions

**Files:**
- Adapter files: lowercase app name (calendar.py, reminders.py, mail.py, contacts.py, notes.py, photos.py, safari.py, messages.py, shortcuts.py, music.py)
- Mail support modules: mail_<subsystem>.py (mail_index.py, mail_addressing.py, mail_outgoing.py, mail_recover.py, mail_triage.py, mail_drafts.py, mail_attachments.py, mail_files.py, mailbox_url.py)
- Cross-cutting: lowercase + purpose (audit.py, errors.py, text.py, doctor.py, runtime.py, lifecycle.py, daemon.py, deploy.py)
- Tests: test_<module>.py (test_contracts.py, test_server_capabilities.py, test_mail_index.py, etc.)

**Functions:**
- camelCase: Never used in this codebase
- snake_case: All functions + methods (run_native, get_pointers, row_to_pointer, resolve_container, audit_read, etc.)
- Private: Prefix with _ (e.g., _read_tool, _guard, _executor, _store, _ek_status, _open_sqlite_ro)

**Variables/Constants:**
- UPPERCASE: For module-level constants (AUDIT_LIMIT, _FULL_ACCESS, _OSASCRIPT_TIMEOUT, _SEND_ANNOTATIONS, _AUTOMATION_DENIED, _TCC_FINGERPRINT)
- snake_case: Local + instance variables (store, event_id, query, pointer, before_state)

**Types/Dataclasses:**
- PascalCase: Pointer, CalendarEventData, ReminderData, ContactData, NoteData, PointerSource, Snapshotter, NativeError (+ subclasses: AccessDenied, AutomationDenied, etc.)

**Modules:**
- Lowercase, hyphen-joined in display (macos-apps-mcp on PyPI), snake_case in code (macos_apps_mcp package)
- Adapter shorthand: calendar, reminders, mail, notes, contacts, messages, photos, safari, shortcuts, music (used in MACOS_APPS_ALLOW_SEND list)

## Where to Add New Code

**New Adapter (New App):**
1. Create `macos_apps_mcp/adapters/<appname>.py` implementing:
   - class `<AppName>Adapter` with method `get_pointers(query: str, limit: int = 50) -> list[Pointer]`
   - Typed write methods: `create_<item>(data: TypedDataclass) -> Pointer`, etc.
   - Optional: `snapshot(id: str) -> Pointer | None` for audit before-state
2. Add the adapter to `macos_apps_mcp/server.py` (instantiate at module scope line 49–58, register tools via dispatch)
3. If the app is accessed via osascript, add its name to `macos_apps_mcp/doctor.py` `_AUTOMATION_APPS` tuple (line 35)
4. Create typed write dataclass in `macos_apps_mcp/contracts.py` if not reusing an existing one
5. Add unit tests in `tests/test_<appname>.py` (Protocol fakes, no real native calls)
6. Add integration tests in `tests/integration/test_<appname>_integration.py` (marked @pytest.mark.integration, real calls)
7. Document in ROADMAP.md under the appropriate milestone (0.9.x, 0.10.x, 0.11.x)

**New Read Tool:**
1. In adapter, implement a method `search_<thing>(query: str, limit: int = 50) -> list[Pointer]` (or add to PointerSource.get_pointers)
2. In `macos_apps_mcp/server.py`, add `@_read_tool` decorated function dispatching to the adapter method
3. If reading from native store (EventKit / sqlite), no runtime seam needed; if osascript, wrap in run_osascript
4. Return `read_result(pointers, cap=limit, plane=None, coverage=None)` if result may be truncated; plain list if always complete
5. Add unit test (Protocol fake adapter)
6. Tool is automatically registered at import time; no activation step

**New Write Tool:**
1. Create typed dataclass in `macos_apps_mcp/contracts.py` (e.g., EventData with fields + defaults)
2. In adapter, implement a method `create_<item>(data: TypedDataclass) -> Pointer` (or update_*, delete_*)
3. If id-addressed (update/delete), add a `snapshot(id: str) -> Pointer | None` method to the adapter
4. In `macos_apps_mcp/server.py`, add:
   - `@_write_tool(snapshot=adapter.snapshot)` for id-addressed destructive writes
   - `@_additive_tool` for create operations (only adds, never modifies)
   - `@_send_tool("<adapter>")` for outbound (mail send, iMessage send) — requires adapter name in MACOS_APPS_ALLOW_SEND
5. Wrap native call in run_native (EventKit) or run_osascript (Mail/etc.)
6. Verify after write (re-fetch by id, diff against request, raise VerificationFailed if mismatch)
7. Return Pointer (create/update) or deletion_result(id, preview_pointer) (delete)
8. Add unit test with audit fixture (before-state capture)
9. Tool is automatically registered and gated by MACOS_APPS_READ_ONLY / MACOS_APPS_ALLOW_SEND (for sends)

**New Mail-Specific Feature:**
1. Determine which mail_* module owns it (mail_index for reads, mail_recover for destructive, mail_outgoing for sends, mail_triage for ranking, mail_drafts for draft lifecycle, mail_attachments for attachments, mail_files for file I/O, mailbox_url for URL parsing)
2. Implement feature in that module (pure functions + class methods)
3. Add call site to `macos_apps_mcp/adapters/mail.py` (the MailAdapter class)
4. Register tool in `macos_apps_mcp/server.py` dispatching to MailAdapter method
5. Add unit test in `tests/test_mail_<subsystem>.py`
6. Run `uv run pytest tests/test_mail*.py` to verify no regressions
7. Device-verify on real Mail if the feature is destructive or involves attachment handling (device-facts may overturn premise; see ROADMAP.md pattern)

**Shared Utility:**
- Text hygiene → `macos_apps_mcp/text.py` (control-strip, truncation, punct normalization)
- Error handling → `macos_apps_mcp/errors.py` (write policies, error taxonomy)
- Runtime seam → `macos_apps_mcp/runtime.py` (run_native, run_osascript)
- Contracts → `macos_apps_mcp/contracts.py` (Pointer, parse functions, write dataclasses)

## Special Directories

**macos_apps_mcp/adapters/mail_* (Mail subsystem):**
- Purpose: Decompose Mail adapter for clean seams (each module handles one concern)
- Generated: No (hand-written)
- Committed: Yes
- Pattern: No cross-imports between mail_* modules. mail.py is thin delegation. Unit tests verify no circular deps (grep -r "from.*mail\." macos_apps_mcp/adapters/mail_*.py | grep -v mail_index/_deeplink).
- Key modules:
  - `mail_index.py`: Envelope Index reader (Pointer builder + FTS sidecar builder)
  - `mail_addressing.py`: RFC822 Message-ID mapping (three id formats) + resolution (find account/folder/message)
  - `mail_recover.py`: Destructive-write safety (backup + log + act + receipt + undo)
  - `mail_outgoing.py`: Send/reply/forward discipline + quote preamble
  - Other modules: mail_triage.py, mail_drafts.py, mail_attachments.py, mail_files.py, mailbox_url.py

**~/.local/state/macos-apps-mcp/ (Runtime state):**
- Purpose: Audit log, usage tally, backups, socket (daemon mode)
- Generated: Yes (created at first write/daemon startup)
- Committed: No (user's local state)
- Contents:
  - `audit.jsonl`: Append-only write log (every tool, before/after, undo info, ~5 MB rotation)
  - `usage.jsonl`: Per-tool invocation tally (reads/writes/errors, ~50 KB)
  - `backups/`: Mail message .emlx copies (one per destructive op; clean on release)
  - `fts_sidecar.sqlite`: Full-text search index over Mail body texts (built by `mail_index_bodies` tool)
  - `daemon/mcp.sock`: Unix socket for daemon mode (mode 0600)
  - `allow_send`: Toggle file for daemon mode (plain text: "mail" or "messages" or "all" or "")

**dist/ (Build output):**
- Purpose: Signed .app bundle (daemon mode distribution)
- Generated: Yes (by scripts/build_app.sh)
- Committed: No (built artifact)
- Contents: macos-apps-mcp.app (signed bundle with vendored Python + macos_apps_mcp package)

**.planning/codebase/ (GSD mapping):**
- Purpose: Codebase documentation for orchestrator/planner
- Generated: By `/gsd-map-codebase` skill
- Committed: Yes (reference docs)
- Contents: ARCHITECTURE.md, STRUCTURE.md, (others per focus: STACK.md, CONVENTIONS.md, CONCERNS.md, etc.)

---

*Structure analysis: 2026-08-28*
