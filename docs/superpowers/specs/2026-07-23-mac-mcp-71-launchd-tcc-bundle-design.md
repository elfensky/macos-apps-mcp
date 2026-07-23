# #71 — launchd daemon + TCC-to-bundle attachment — design

**Issue:** [#71](https://github.com/elfensky/macos-apps-mcp/issues/71) · **Milestone:** 0.8.0 · **Date:** 2026-07-23 · **Status:** design v2 (spike-validated, review-amended) · **Supersedes:** the Phase-0 spike doc (same date)

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

## Two supported modes (review amendment — binding)

The `.app` is a **deployment shape, not a replacement**. Both modes stay first-class:

1. **stdio/venv mode (dev + CI, unchanged):** `<repo>/.venv/bin/python -m macos_apps_mcp`,
   per-launcher TCC as today. All unit tests, CI, and the edit-run loop live here — no rebuild, no
   signing. PyPI keeps shipping exactly this.
2. **daemon mode (deployment):** the signed `.app` under launchd, one shared grant set.

`doctor` must report which mode is serving and which identity holds each grant, so a user never
debugs the wrong one.

## Architecture

```
launchd user agent (gui domain)  ──runs──▶  ren.lav.macos-apps-mcp.app   ← ONE responsible process
  (SMAppService, in-bundle plist)              (Developer ID signed,        ← holds ALL TCC grants
                                                notarized, stapled)
                                                      │ listens on
                                                      ▼
                                    unix domain socket (0700 dir / 0600 file)
                                    one MCP SESSION per accepted connection
                                                      ▲ connect
   Claude Desktop / VS Code / Claude Code ──spawn──▶ stdio↔socket shim  (client `command:` stays)
```

### A. The signed `.app` bundle
- **Bundle id `ren.lav.macos-apps-mcp`** (reverse-DNS of `lav.ren`; **permanent** — TCC's stored
  csreq keys on bundle id + Team ID, renaming orphans every grant). **Team `VUMUR696L9`**,
  **Developer ID Application** signed. No provisioning profile is needed: Developer ID
  distribution with only unrestricted entitlements has no profile/App-Review/capability step.
- **Signing recipe (review-corrected):** **inside-out** — sign every nested Mach-O (interpreter,
  every `.dylib`/`.so` in the vendored site-packages) individually, then the bundle. **Never
  `codesign --deep`** (deprecated; notarization rejects its ordering/missed-nested-items).
  **Always `--timestamp --options runtime`** — both are notarization requirements, and the secure
  timestamp is what keeps existing installs valid (and TCC grants intact) across the cert's 5-year
  expiry/renewal, since a renewed same-Team cert still satisfies the stored csreq.
- **Library validation stays ON (first attempt):** validation permits libraries signed by the same
  Team ID, and we re-sign every `.so` with `VUMUR696L9` anyway — so
  `com.apple.security.cs.disable-library-validation` should be unnecessary. Keep it as a documented
  fallback only if a vendored binary can't be re-signed. Fewer entitlements = better posture for an
  app holding Mail/FDA grants.
- **Entitlements:** `com.apple.security.automation.apple-events` (hardened runtime blocks
  AppleEvents to Mail/Notes without it). On-device test item — NOT granted by default:
  `com.apple.security.cs.allow-unsigned-executable-memory` (PyObjC/ctypes libffi closure
  trampolines historically needed it; modern static trampolines on arm64 usually don't — verify,
  add only if imports/callbacks fail under hardened runtime).
- **Main executable = a real file** (codesign rejects a symlink): the bundled
  python-build-standalone interpreter (statically-linked libpython → only system dylibs) at
  `Contents/MacOS/<exe>`, run **in-process, never `exec`-replaced**. Stdlib under
  `Contents/Resources/` (`PYTHONHOME`); **pyobjc + the server package + deps vendored inside the
  bundle** (no external venv reference — the spike's `PYTHONPATH` to the repo venv was
  spike-only).
- **Info.plist:** usage strings `NSCalendarsFullAccessUsageDescription`,
  `NSRemindersFullAccessUsageDescription`, `NSContactsUsageDescription`,
  `NSAppleEventsUsageDescription`; `LSUIElement` (no dock icon).
- **Licensing (distribution):** all vendored components are permissive — python-build-standalone
  (PSF/BSD; libedit, not GNU readline), PyObjC (MIT), this project (MIT). No copyleft obligations
  for the distributed binary.
- **Packaging tool:** open fork (see Risks) — hand-rolled bundle vs briefcase/py2app. Spike proved
  the hand-rolled shape; a tool may be lazier for inside-out signing + notarization ergonomics.

### B. launchd registration — SMAppService (review-amended)
- **Primary path:** the LaunchAgent plist ships **inside the bundle**
  (`Contents/Library/LaunchAgents/ren.lav.macos-apps-mcp.plist`) and is registered via
  **`SMAppService.agent(plistName:)`** through the pyobjc ServiceManagement bridge. This is the
  Ventura+ blessed shape: a user-visible, toggleable entry in System Settings → Login Items,
  Background-Task-Management attribution to the signed developer name, and `unregister()` on
  uninstall (no orphaned plist).
- **Fallback:** a hand-dropped `~/Library/LaunchAgents` plist (legacy-but-working; triggers the
  "Background Items Added" notification). Keep only if the pyobjc SM bridge misbehaves on-device.
- Plist: `Label` = bundle id, `ProgramArguments` = the bundle's main executable, `RunAtLoad`,
  `KeepAlive` **plus `ThrottleInterval`** (no tight crash-loops), stdout/err → rotating logs in
  `state_dir()`. `doctor` surfaces the agent's last exit status.
- gui-domain only: the daemon runs while the user is logged in — correct for this product; no
  headless/SSH-only operation (documented caveat).

### C. Transport — unix socket, one MCP session per connection (review-corrected)
- The daemon listens on a **unix domain socket** in a `0700` state dir, `0600` socket file —
  **not** a localhost TCP port (a listening port is a DNS-rebinding surface against a server
  holding Mail/calendar data; filesystem perms are tighter and off the network stack).
- **MCP is session-oriented — a single stdio-style session behind a dumb pipe serves exactly one
  client.** Multi-client therefore requires one of (implementation fork, spike before the plan
  locks it):
  - **(a) streamable-http over the socket:** FastMCP's http transport via uvicorn `uds=`; the shim
    becomes a small stdio↔HTTP bridge (no longer a dumb pipe, still no TCC surface).
  - **(b) session-per-connection framing:** daemon `accept()`s each connection and runs an
    independent framed MCP session on that socket pair; the shim stays bytes-in/bytes-out.
- Either way: shim ships as a second tiny signed binary in the bundle (stable path for client
  config, updates atomically with the daemon), and **fails fast** when the socket is
  absent/refused — one actionable stderr line ("daemon not running — run
  `macos-apps-mcp install-agent`"), never a hang (a hanging shim looks like a wedged client).
- Downstream concurrency is already safe regardless of session count: `run_native`'s single worker
  serializes all native access.

### D. Single-instance
- launchd `Label` gives one-per-label already; belt-and-suspenders: on startup `bind()` the socket,
  and on `EADDRINUSE` `connect()`-probe — success ⇒ a live daemon owns it (exit); `ECONNREFUSED` ⇒
  stale socket from a crash (unlink, rebind). Single instance also retires the multi-writer
  hazards (audit JSONL, FTS builds) in daemon mode.

### E. `doctor`
- Extend `_responsible_process()` to report **which identity holds each grant** (read `TCC.db`
  `access.client` per service), which **mode** is serving (stdio vs daemon), and the agent's
  registration/last-exit status.
- **Chicken-and-egg caveat:** reading `TCC.db` itself requires FDA *for the reader's responsible
  process* — pre-grant, the identity report is unavailable. Degrade gracefully (report "cannot
  read TCC.db — FDA not yet granted to <identity>"), and treat the private, version-mobile schema
  like the other fingerprinted reads (never mis-parse into a wrong claim).

### F. Install / grant UX — scripted (review-amended)
- **`macos-apps-mcp install-agent`** (in the pip package) automates the documented path:
  1. Locate/verify the signed `.app`; ensure it lives in `/Applications` (or `~/Applications`) —
     **App Translocation guard:** a quarantined app launched from `~/Downloads` runs from a
     randomized read-only mount, breaking the agent's path; verify the staple, clear quarantine
     after verification (or require a Finder move) before registering.
  2. Register via SMAppService; start the daemon.
  3. **Trigger every consent prompt proactively** (the existing `doctor request=True` pattern):
     EventKit, Contacts, per-app Automation probes — so prompts appear in install context, not
     mid-tool-call while the user is elsewhere (an ignored/timed-out prompt records a denial).
     FDA never prompts: deep-link the pane
     (`x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles`) and instruct the
     drag.
  4. Print the per-client `command:` snippet pointing at the shim.
- **Uninstall:** `unregister()`, remove socket/logs, `tccutil reset All ren.lav.macos-apps-mcp`.

### G. Release channel (review amendment — new)
- The `.app` **cannot ship through PyPI**; it is a second artifact with its own pipeline:
  **v1 = local build on this Mac** (`make app`: bundle → inside-out sign → notarize → staple →
  zip) attached to the GitHub release. **CI signing is deferred** — it would put the `.p12` +
  notary credentials into GitHub secrets; a deliberate later decision, not a default.
- PyPI keeps shipping stdio mode unchanged. Third-party users of `install-agent` build locally —
  with their own Developer ID, or ad-hoc (works, but ad-hoc csreq is the cdhash: grants must be
  re-approved after every rebuild; documented limitation).
- Local dev builds skip notarization entirely (no quarantine xattr on never-downloaded builds) —
  the dev loop needs sign-only, not notarize.

## Testing

Unit (mockable, no TCC): shim framing round-trip + fail-fast-on-absent-socket; single-instance
bind/EADDRINUSE/stale-socket logic; `doctor` identity/mode mapping from a fake `TCC.db` row set
(plus the FDA-unreadable degradation); socket path perms (0700/0600).

On-device (`-m integration`, this Mac — the real gate):
- **Cross-host grant sharing (the acceptance test):** grant once via the daemon, then exercise
  Calendar/Mail/FDA tools from Terminal, Claude Desktop, and VS Code — all succeed, no re-prompt.
- **Persistence across rebuild** under Developer ID (stable Team csreq; ad-hoc would not persist).
- **Hardened-runtime import test:** pyobjc + every native `.so` load with library validation ON;
  ctypes/PyObjC callbacks work (else add `allow-unsigned-executable-memory`, documented).
- **Notarized Gatekeeper-on-spawn:** a client spawning the shim launches without friction.
- **Automation to Mail** from the daemon identity (no `-1743`; verifies the apple-events
  entitlement + source-pair grant on the bundle).
- **Multi-client sessions:** two clients connected concurrently, interleaved tool calls, no
  cross-session bleed; single daemon process; clean start/stop; kill -9 → stale-socket recovery.
- **SMAppService round-trip:** register → visible in Login Items → unregister leaves no residue.

## Acceptance (issue #71 + expanded)
- [ ] Grants survive switching hosts (Terminal ↔ Claude Desktop ↔ VS Code) — one grant set.
- [ ] Two clients served concurrently by one daemon; clean start/stop documented.
- [ ] `.app` Developer-ID signed (inside-out, `--timestamp --options runtime`) + notarized +
      stapled; spawns without Gatekeeper friction.
- [ ] `doctor` reports mode + which identity holds each grant (graceful pre-FDA).
- [ ] stdio/venv mode still fully working (CI + dev loop untouched).
- [ ] `install-agent` / uninstall round-trip leaves no residue.

## Risks & open implementation forks
1. **Python packaging tool** — hand-rolled bundle (spike-proven, full control, we own inside-out
   sign + notarize scripting) vs **briefcase / py2app** (handles bundling + signing, less control,
   another dep). Evaluate briefcase first for the sign+notarize ergonomics.
2. **Transport fork (§C):** streamable-http-over-UDS vs session-per-connection framing. Spike
   against the FastMCP 2.0 API before the plan locks it — this decides the shim's complexity.
3. **Automation prompt surfacing from a background agent** — a gui-domain agent can present
   prompts, but the flow is validated on-device during `install-agent` (§F.3 makes it proactive).
4. **Notarization credentials** — one-time `xcrun notarytool store-credentials` (app-specific
   password or ASC API key). Gates release builds only, not dev.
5. **PyObjC under hardened runtime** — libffi trampoline behavior (see §A entitlements); on-device
   test decides whether an extra entitlement is needed.

## Out of scope
- `mail_download_bodies` (#119) and other adapter features.
- Auto-update / Sparkle for the `.app` (later; nothing to update until it ships).
- CI-side signing/notarization (deliberate later decision — see §G).
- Multi-user / system-daemon (`/Library/LaunchDaemons`) — this is a per-user, gui-domain agent.
