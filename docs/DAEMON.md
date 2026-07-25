# Daemon deployment (#71)

`macos-apps-mcp` ships **two supported modes**. Both stay first-class — neither replaces the
other.

| | stdio/venv mode | daemon mode |
|---|---|---|
| **When** | dev + CI, the edit-run loop | deployment: one shared grant set across all your MCP clients |
| **How it runs** | `<repo>/.venv/bin/python -m macos_apps_mcp`, spawned per-launcher | the signed `.app` under launchd (gui-domain `SMAppService` agent), one long-lived process |
| **TCC identity** | whichever app spawned it (Terminal, Claude Desktop, VS Code — each separately) | the bundle, `ren.lav.macos-apps-mcp`, Developer-ID signed — **one** identity holds every grant |
| **Transport** | stdio, unchanged | unix domain socket (`0700` dir / `0600` file) → a small stdio↔socket shim per client |
| **Ships via** | PyPI / `git clone` + `uv sync` | local build (`scripts/build_app.sh`), attached to a GitHub release — not on PyPI |

Run `doctor` in either mode — it reports which mode is serving (`deployment.mode`) and which
identity holds each grant (`deployment.grant_identities`), so you never end up debugging the
wrong one.

Use stdio/venv mode if you only ever use one client, or you're developing the server itself. Use
daemon mode if you want Claude Desktop, VS Code, and a Terminal-spawned client to all share one
set of Calendar/Reminders/Contacts/Automation/Full-Disk-Access grants instead of re-approving
each launcher separately.

## Install (daemon mode)

### 1. Build the signed `.app`

```sh
scripts/build_app.sh \
  --sign "Developer ID Application: Andrei M. Lavrenov (VUMUR696L9)" \
  --out dist
```

This produces `dist/macos-apps-mcp.app`, signed **inside-out** (every vendored `.so`/`.dylib`,
then the main executable, then the bundle — never `codesign --deep`) with
`--timestamp --options runtime`. Omit `--sign` for an unsigned dev build (no Login Items
registration will work without a signature, but the bundle still smoke-tests).

**Notarize** (needed once the `.app` leaves this Mac — e.g. before distributing it, or if
Gatekeeper is going to see it as freshly downloaded):

```sh
# one-time: store notary credentials under a keychain profile
xcrun notarytool store-credentials PROFILE \
  --apple-id you@example.com --team-id VUMUR696L9 --password APP_SPECIFIC_PW

scripts/build_app.sh \
  --sign "Developer ID Application: Andrei M. Lavrenov (VUMUR696L9)" \
  --notarize PROFILE \
  --out dist
```

`--notarize` submits `dist/macos-apps-mcp.zip` with `notarytool submit --wait`, then staples the
ticket onto the `.app`. Local same-Mac builds you never downloaded don't need this step —
notarization only matters once Gatekeeper sees a quarantine xattr.

### 2. Move it to `/Applications`

```sh
cp -R dist/macos-apps-mcp.app /Applications/
```

The bundle **must** live in `/Applications` (or `~/Applications`) before registering — a
quarantined app run from `~/Downloads` executes under App Translocation (a randomized read-only
mount), which breaks the agent's on-disk path. `install-agent` verifies the staple and clears
quarantine for you, but it still expects the app to already be in a real `/Applications` location
(a Finder drag, not a `Downloads` double-click).

### 3. Install the agent

From the pip-installed package (or the repo venv — `install-agent` is a role of the *pip* CLI,
which drives the *bundle's* executable for the SMAppService-registering steps):

```sh
macos-apps-mcp install-agent
# or, if the bundle isn't at the default /Applications path:
macos-apps-mcp install-agent --app /path/to/macos-apps-mcp.app
```

This will:
1. Verify the staple / clear quarantine (App Translocation guard).
2. Register the LaunchAgent via `SMAppService` and start the daemon.
3. **Trigger every consent prompt proactively** (Calendar, Reminders, Contacts, per-app
   Automation) — approve each one as it appears. Approving in this context (rather than mid
   tool-call later) keeps a stray timeout from recording as a denial.
4. Print the FDA deep-link and the shim `command:`/`args:` snippet to paste into your MCP
   clients.

**Full Disk Access does not prompt** — step 4 prints the command to open the pane
(`open 'x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles'` — run it
yourself); drag
`macos-apps-mcp.app` into the Full Disk Access list and enable it (this is what lets the daemon
read `chat.db` for Messages, and `TCC.db` itself for the `doctor` identity report).

### 4. Point every MCP client at the shim

The bundled interpreter runs with `-E -s -P` (ignore `PYTHON*` env vars, skip user
site-packages, no unsafe `sys.path[0]` prepend) — this is required so a caller's environment
can never shadow the bundled `macos_apps_mcp` package or break `getpath`. Use exactly this
`args:` shape:

```json
{
  "mcpServers": {
    "macos-apps": {
      "command": "/Applications/macos-apps-mcp.app/Contents/MacOS/macos-apps-mcp",
      "args": ["-E", "-s", "-P", "-m", "macos_apps_mcp", "shim"]
    }
  }
}
```

Same snippet for Claude Desktop's `claude_desktop_config.json` and VS Code's MCP server config
(`.vscode/mcp.json` or the equivalent client-scoped settings) — only the surrounding config key
differs, `command`/`args` stay identical. A Terminal-spawned shim uses the same `command` +
`args` directly on the CLI.

## Manual acceptance checklist

This is the part automation can't reach (it needs human grant clicks) — the on-device gate for
issue #71's actual promise: **grant once, every client benefits**. Run through it after
`install-agent` finishes and every prompt from step 3 has been answered.

1. **Terminal.** Spawn the shim directly and drive one tool call of each kind:
   ```sh
   /Applications/macos-apps-mcp.app/Contents/MacOS/macos-apps-mcp -E -s -P -m macos_apps_mcp shim
   ```
   (or via any MCP-capable CLI client pointed at that command) — run:
   - a **calendar read** (e.g. `events`)
   - a **mail read** (e.g. `mail` with a subject substring, or `mail_search`)
   - a **chat.db-backed read** (e.g. `messages_search` or `messages_chats`)

   All three must succeed with **no permission prompt**.

2. **Claude Desktop.** Add the shim snippet from step 4 above to
   `~/Library/Application Support/Claude/claude_desktop_config.json`, restart Claude Desktop, and
   run the same three calls from a chat. No prompt.

3. **VS Code.** Add the same snippet to the MCP server config, reload the window, and run the
   same three calls. No prompt.

**Pass criterion:** all nine calls (3 surfaces × 3 clients) succeed, and after the very first
grant (during `install-agent`) **zero** additional prompts appear across any of the three
clients — because all three shims talk to the same daemon, which holds the one
`ren.lav.macos-apps-mcp` grant set. Confirm this by running `doctor` from any client afterward
and checking `deployment.grant_identities` — every relevant service should show
`ren.lav.macos-apps-mcp` as `granted: true`, and no *other* client identity (Terminal, Claude
Desktop, Code) should appear as a separate grantee.

If you have to re-approve anything after the first grant, that's a regression of the whole
feature — stop and diagnose (see Troubleshooting) rather than clicking through it.

## Hardened-runtime check

The bundle runs under the hardened runtime (`--options runtime`). Two things to verify once per
build:

1. **The signature carries the runtime flag:**
   ```sh
   codesign -dvv /Applications/macos-apps-mcp.app
   ```
   Look for `flags=0x10000(runtime)` in the output — confirms hardened runtime is actually on,
   not just requested.

2. **PyObjC imports and callbacks still work under it.** If every tool call that touches
   EventKit/Contacts/ServiceManagement works (i.e. the acceptance checklist above passes), this
   is implicitly verified — PyObjC's libffi closure trampolines are exercised by every native
   call `run_native()` makes. If instead you see crashes or `EXC_BAD_ACCESS` specifically inside
   a PyObjC callback (not a normal TCC denial), add the escape-hatch entitlement from spec §A and
   re-sign:
   ```xml
   <key>com.apple.security.cs.allow-unsigned-executable-memory</key><true/>
   ```
   in `packaging/entitlements.plist`, then rebuild. Modern arm64 static trampolines usually don't
   need this — treat it as a documented fallback, not a default.

## Troubleshooting

- **Is the agent registered / running?**
  ```sh
  launchctl print gui/$UID/ren.lav.macos-apps-mcp
  ```
  Shows the service state, last exit status, and (if configured) log redirection. A
  `NotFound`/no-such-service result means `install-agent` didn't register it — re-run
  `macos-apps-mcp install-agent`, or check the printed error.

- **Login Items toggle.** System Settings → General → Login Items & Extensions → look under
  "Allow in the Background" for `macos-apps-mcp`. You can disable/re-enable the agent from here
  without uninstalling; toggling it off stops the daemon, toggling it on restarts it (subject to
  `RunAtLoad`/`KeepAlive` in the LaunchAgent plist).

- **`doctor` deployment section.** Run the `doctor` tool from any connected client (or
  `macos-apps-mcp` via any MCP client in either mode) — it reports:
  - `deployment.mode`: `"daemon"` if you're talking to the launchd-run bundle, `"stdio"`
    otherwise.
  - `deployment.agent`: the `SMAppService` status (`not-registered` / `enabled` /
    `requires-approval` / `not-found`).
  - `deployment.grant_identities`: per-service, per-client-identity grant map read straight from
    `TCC.db` — `None`/unreadable until Full Disk Access is granted to whichever process is
    asking (chicken-and-egg: reading `TCC.db` itself needs FDA for the reader).
  - If `deployment.agent` shows `requires-approval`, open Login Items (above) and approve it.

- **Log locations.**
  - Audit log and usage log live under `~/.local/state/macos-apps-mcp/` (or
    `$XDG_STATE_HOME/macos-apps-mcp` if set). The daemon's socket does **not** follow
    `XDG_STATE_HOME` — it is always `~/.local/state/macos-apps-mcp/daemon/mcp.sock` (unless
    `MACOS_APPS_MCP_SOCKET` overrides it), so that the launchd daemon, `install-agent`, and
    client-spawned shims — three processes with different environments — agree on one
    rendezvous path.
  - The current `ren.lav.macos-apps-mcp.plist` does not redirect the daemon's stdout/stderr to a
    file, so `launchctl print` (above) is the primary source for last-exit info. For anything the
    process itself logged (Python's `logging` module, `macos_apps_mcp` logger), use the unified
    log:
    ```sh
    log show --predicate 'process == "macos-apps-mcp"' --last 1h
    ```
    or stream it live with `log stream --predicate 'process == "macos-apps-mcp"'` while
    reproducing an issue.

- **Socket exists but nothing responds / stale socket.** The daemon's `bind_socket()` already
  self-heals a stale socket left by a crash (connect-probe on `EADDRINUSE`, unlink + rebind if
  refused) — if a client still can't connect, confirm the daemon process is actually running
  (`launchctl print`, above) before assuming the socket is the problem.

- **Shim fails immediately with `daemon not running`.** This is the fail-fast path
  (`shim_check`), exit code 2 — expected when no daemon is listening at
  `MACOS_APPS_MCP_SOCKET`/the default socket path. Run `macos-apps-mcp install-agent` (or check
  why the daemon isn't up per the steps above) rather than treating this as a hang.

- **Daemon dies mid-session.** Any shim connected at that moment surfaces the failure as a
  transport error to its client (not a silent hang) — launchd's `KeepAlive` restarts the daemon
  (`ThrottleInterval` 10s) automatically, and a client reconnects simply by respawning the shim
  (a fresh `shim` invocation), which re-probes the socket from scratch.

## Uninstall

```sh
macos-apps-mcp uninstall-agent
```

Unregisters the `SMAppService` agent and removes the daemon's socket. To also wipe every TCC
grant held by the daemon identity (so a future reinstall starts from a clean prompt state):

```sh
tccutil reset All ren.lav.macos-apps-mcp
```

Then remove the `.app` itself (`rm -rf /Applications/macos-apps-mcp.app`) if you're not
reinstalling.
