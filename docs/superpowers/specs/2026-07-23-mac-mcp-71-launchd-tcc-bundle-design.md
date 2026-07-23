# #71 — launchd daemon + TCC-to-bundle attachment — design

**Issue:** [#71](https://github.com/elfensky/macos-apps-mcp/issues/71) · **Milestone:** 0.8.0 · **Date:** 2026-07-23 · **Status:** design (spike-validated) · **Supersedes:** the Phase-0 spike doc (same date)

## Why

macOS TCC attributes every permission grant (Calendar, Full Disk Access, Automation) to the
**responsible process** — resolved at `exec` to the nearest launchd-top-level ancestor. Because
Claude Desktop / VS Code / Claude Code each `posix_spawn` the stdio MCP server, the grant attaches
to *them*, not to us. Grant permissions from a terminal, switch to Claude Desktop, and every grant
is "missing" again. This is the ecosystem's #1 documented support burden (`doctor` explains it;
#71 fixes it).

## Spike evidence (on-device, macOS 26.5.2, 2026-07-23)

Live baseline confirmed the problem: `TCC.db` held **separate** Calendar grants for
`com.apple.Terminal` **and** `com.microsoft.VSCode` — per-launcher rows, none for macos-apps-mcp.

A signed probe (bundle id `ren.lav.macos-apps-mcp.spike*`) run two ways proved the fix, for both a
compiled Swift binary and a **bundled python-build-standalone interpreter as the main executable**:

| Launched by | responsible id | Calendar status | chat.db (FDA) |
|---|---|---|---|
| Terminal (child) | Terminal | `3` fullAccess (inherited) | readable (inherited) |
| **launchd** (ppid=1) | **the bundle itself** | `0` notDetermined | PermissionError |

A launchd-launched process is its **own responsible process** with a distinct, bundle-keyed TCC
identity that inherits nothing. Grant *that* identity once → every client riding the shared instance
uses it. **Confirmed: launchd is required and sufficient for grant-sharing; the Python "exec trap"
is avoidable** (real-file main executable, statically-linked libpython, `PYTHONHOME`).

## Architecture

```
launchd user agent (top-level)  ──runs──▶  ren.lav.macos-apps-mcp.app   ← ONE responsible process
        (ren.lav.macos-apps-mcp)              (Developer ID signed,        ← holds ALL TCC grants
                                               notarized, hardened runtime)
                                                     │ listens on
                                                     ▼
                                        unix domain socket (0700 dir / 0600 file)
                                                     ▲ connect
   Claude Desktop / VS Code / Claude Code ──spawn──▶ tiny stdio↔socket shim  (client `command:` stays)
```

### A. The signed `.app` bundle
- **Bundle id `ren.lav.macos-apps-mcp`** (reverse-DNS of `lav.ren`; permanent — renaming orphans
  every grant). **Team `VUMUR696L9`**, **Developer ID Application** signed, **hardened runtime**,
  **notarized + stapled** (a client `posix_spawn`ing a *quarantined* binary gets a silent Gatekeeper
  kill).
- **Main executable = a real file** (codesign rejects a symlink): the bundled python-build-standalone
  interpreter (statically-linked libpython → only system dylibs) at `Contents/MacOS/<exe>`, run
  **in-process, never `exec`-replaced**. The Python stdlib ships under `Contents/Resources/`
  (`PYTHONHOME`); **pyobjc + the server package + deps ship *inside* the bundle** and are
  **deep-signed** (interpreter + every `.dylib`/`.so`).
- **Entitlements:** `com.apple.security.cs.disable-library-validation` (Python dlopens native modules
  not signed by our Team), `com.apple.security.automation.apple-events` (hardened runtime blocks
  AppleEvents to Mail/Notes without it). **Info.plist usage strings:**
  `NSCalendarsFullAccessUsageDescription`, `NSRemindersFullAccessUsageDescription`,
  `NSContactsUsageDescription`, `NSAppleEventsUsageDescription`. `LSUIElement` (no dock icon).
- **Packaging tool:** open fork (see Risks) — hand-rolled bundle vs py2app/briefcase/PyInstaller.
  Spike proved the hand-rolled shape works; a tool may be lazier for deep-signing + notarization.

### B. launchd user agent
- LaunchAgent `~/Library/LaunchAgents/ren.lav.macos-apps-mcp.plist`, `Label` = the bundle id,
  `ProgramArguments` = the bundle's main executable, `RunAtLoad` + `KeepAlive` (restart on crash).
- launchd top-level launch is what makes the bundle its own responsible process (spike-proven).

### C. Transport — unix domain socket + stdio shim
- The daemon listens on a **unix domain socket** in a `0700` state dir, `0600` socket file —
  **not** a localhost TCP port (a listening port is a DNS-rebinding surface against a server holding
  Mail/calendar data; filesystem perms are tighter and off the network stack).
- Clients keep their `command:`-spawn config but spawn a **tiny stdio↔socket shim** (bytes-in/bytes-out;
  no MCP logic, no TCC surface) that forwards the client's stdio to the daemon socket. Ship the shim
  as a second tiny signed binary in the bundle so client config points at a stable path.
- FastMCP transport choice (streamable-http over the socket vs a raw framed pipe) is an open fork
  (see Risks); the shim isolates clients from it.

### D. Single-instance
- launchd `Label` gives one-per-label already; belt-and-suspenders: on startup `bind()` the socket,
  and on `EADDRINUSE` `connect()`-probe — success ⇒ a live daemon owns it (exit); `ECONNREFUSED` ⇒
  stale socket from a crash (unlink, rebind). This also fixes the multi-writer hazards a single
  instance removes (audit JSONL, FTS builds) — now moot once there's one process.

### E. `doctor`
- Extend `_responsible_process()` to report **which identity holds each grant** (read `TCC.db`
  `access.client` per service) and whether the daemon is the responsible process — so a user who
  granted the *old* per-launcher way sees exactly what to re-grant against the bundle.

### F. Install / grant UX
- A documented `install` path: build → notarize → staple → copy the `.app` into `/Applications` (or
  `~/Applications`) → load the LaunchAgent → grant Calendar/Reminders/Contacts/Automation/FDA **once**
  to `ren.lav.macos-apps-mcp` (prompts + a System Settings drag for FDA) → point each client's config
  at the shim. Clean `uninstall` (bootout, remove agent, `tccutil reset … ren.lav.macos-apps-mcp`).

## Testing

Unit (mockable, no TCC): shim stdio↔socket framing round-trip; single-instance bind/EADDRINUSE/stale
socket logic; `doctor` identity mapping from a fake `TCC.db` row set; socket path perms (0700/0600).

On-device (`-m integration`, this Mac — the real gate):
- **Cross-host grant sharing (the acceptance test):** grant once via the launchd instance, then
  exercise Calendar/Mail/FDA tools driven from Terminal, Claude Desktop, and VS Code — all succeed
  with no re-prompt (one grant, every host).
- **Persistence across rebuild** under Developer ID (stable Team id; ad-hoc cdhash would not persist).
- **Notarized Gatekeeper-on-spawn:** a client spawning the shim/daemon launches without friction.
- **Automation to Mail** from the launchd identity (no `-1743 errAEEventNotPermitted`; verifies the
  apple-events entitlement + source-pair grant on the bundle).
- **Single-instance:** two client connections → one daemon process; clean start/stop.

## Acceptance (issue #71 + expanded)
- [ ] Grants survive switching hosts (Terminal ↔ Claude Desktop ↔ VS Code) — one grant set.
- [ ] Single-instance semantics; clean start/stop documented.
- [ ] `.app` Developer-ID signed + notarized + stapled; spawns without Gatekeeper friction.
- [ ] `doctor` reports which identity holds each grant.

## Risks & open implementation forks
1. **Python packaging tool** — hand-rolled bundle (spike-proven, full control, but we own deep-sign +
   notarization scripting) vs **py2app / briefcase / PyInstaller** (handles bundling + signing, less
   control, another dep). Recommend evaluating briefcase/py2app first for the sign+notarize ergonomics.
2. **FastMCP-over-socket transport** — does FastMCP 2.0 expose a clean unix-socket/framed transport, or
   do we frame MCP JSON-RPC over the socket ourselves in the shim + a small server adapter? Spike this
   against the FastMCP API before the plan locks it.
3. **Automation prompt surfacing from a background agent** — a headless LaunchAgent triggering the
   first Automation/Calendar consent prompt may need an active GUI session; validate the grant flow
   on-device (the install step may need to run the app foreground once to collect consent).
4. **Notarization credentials** — needs `notarytool store-credentials` (app-specific password or ASC
   API key) set up; one-time.

## Out of scope
- `mail_download_bodies` (#119) and other adapter features.
- Auto-update / Sparkle for the `.app` (later; nothing to update until it ships).
- Multi-user / system-daemon (`/Library/LaunchDaemons`) — this is a per-user agent.
