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
then the bundle once per entitlement set, joining the main executable's slices with `lipo` —
see "Hardened-runtime check"; never `codesign --deep`) with
`--timestamp --options runtime`. Omit `--sign` for an unsigned dev build (no Login Items
registration will work without a signature, but the bundle still smoke-tests).

The build compiles `packaging/AppIcon.icon`, an Icon Composer file, with Xcode's `actool`
into `Contents/Resources` (`Assets.car` for macOS 26 and later, `AppIcon.icns` for older
macOS). The build needs full Xcode, because the Command Line Tools have no `actool`. When
`xcode-select` points at the Command Line Tools, the build uses `/Applications/Xcode.app`.
For an Xcode at a different path, set `DEVELOPER_DIR` to its `Contents/Developer`.

The build installs the exact versions in `uv.lock`, including cryptography (see below), then
runs `scripts/smoke_stream.py` on
each slice of the bundled interpreter through the actual stdio shim.
The synthetic checks cover both protocol eras, six-second calls, log/progress notifications,
large responses, abandoned streams and no replay. They also check for asyncio teardown errors.
A failing smoke fails the build; a good build log shows `stream smoke ok` (#286).
The build drops osxphotos's two thin `libdisclaim` dylibs (CLI only) from both trees, and
both smokes import osxphotos.
`doctor().libs` reports the `mcp` and `fastmcp` versions the bundle carries (#285).

**Universal2, macOS 15 floor.** The `.app` carries arm64 and x86_64 slices of the
interpreter and of every extension (#205). The build runs on an Apple-silicon Mac and needs
Rosetta 2 (`softwareupdate --install-rosetta --agree-to-license`), because the import and
stream smokes run on both slices. An Intel Mac cannot run the arm64 smoke, so it installs a
release build instead of building one. The build downloads a pinned python-build-standalone
CPython (3.14.5, release 20260510) for each arch and checks its sha256. It caches the
tarballs in `~/Library/Caches/macos-apps-mcp-build`; `PBS_CACHE` overrides the path.
`LSMinimumSystemVersion` in `packaging/Info.plist` is 15.0, the oldest macOS tested on a
device (15.6.1 and 15.7.9). The code itself needs macOS 14 (the EventKit full-access APIs).
The build reads that key and picks wheels for it. Before signing, it fails unless every
Mach-O is `x86_64 arm64` and no slice needs a newer macOS. A good build log shows
`smokes ok: arm64`, `smokes ok: x86_64` and `universal2 gate ok`. The build smokes both
slices on an Apple-silicon Mac (x86_64 under Rosetta). The signed 0.14.2 release also runs on
an Intel CPU: an iMac (2012) on macOS 15, 2026-10-09..11.
There, the release zip installed and `install-agent` registered the daemon; `doctor()`
reported 0.14.2 in daemon mode with Calendar, Reminders and Full Disk Access granted to
`ren.lav.macos-apps-mcp`; Mail, Calendar and Reminders reads worked through the shim; and
`codesign --verify --strict` was valid after the daemon ran.

**cryptography ships in the `.app`** (#470). MCP 2 imports it for request-state encryption,
even when authentication is disabled. Its public request-state codec uses AES-GCM, HKDF and SHA-256.
The bundle includes the locked package and its native extensions in both architecture slices.
cffi and pycparser also ship for osxphotos → osxmetadata → xattr.

**Intel cap:** `pyproject.toml` retains `cryptography<49` on Intel Macs (#322).
Versions 49 and later have no x86_64 macOS wheel. The lock currently selects 48.0.1 for every platform.
The bundle and PyPI installation therefore retain Intel support without compiling that package from source.

**Limited compatibility exception (2026-11-03).** No reachable vulnerability was found in the reviewed
local, unauthenticated AES-GCM/HKDF path. The retained package is affected by X.509 verification advisories
(GHSA-m2h6-j472-rp4c, GHSA-jwv3-5hgf-82ww; fixed in 49.0.0) and a PKCS#7 decryption advisory
(GHSA-g6cj-pr64-35w5; fixed in 50.0.0). The application does not call those affected operations.
X.509 modules are imported indirectly, so absence of imports is not the justification.
Keep Dependabot alerts #2, #17 and #18 open. Reassess before enabling authentication, certificate-chain
verification or PKCS#7 processing, or changing the relevant dependencies.
[Evidence, primary advisories and verification limits](../.planning/phases/05.4-mcp-2-fastmcp-4-migration/05.4-SECURITY.md).

**eli14:** The toolbox contains defective attachments. The current job uses a different attachment, which passed its checks.
Future jobs must not assume that every attachment works.

**Notarize** (needed once the `.app` leaves this Mac — e.g. before distributing it, or if
Gatekeeper is going to see it as freshly downloaded):

#### Notarization profile

The maintainer's existing Keychain profile is **`notary`**. It is a local profile name, not an Apple account email.
The recorded setup uses an App Store Connect **Team Key**, with the **Developer** role.
The signing team is `VUMUR696L9`; the signing identity is `Developer ID Application: Andrei M. Lavrenov (VUMUR696L9)`.
The profile is configured on the build Mac. Its presence on another Mac must be checked separately.

Check the existing setup before requesting or creating credentials:

```sh
security find-identity -v -p codesigning
xcrun notarytool history --keychain-profile notary
```

Both checks passed on 2026-11-04 after the owner accepted Apple's pending Developer agreement.
The history check proves service access. It does not inspect the stored key or independently confirm its current role.
The [v0.13.0 record](../.planning/phases/02.1-mail-fixes-batch-moves-fit-their-timeout-drafts-pick-their-a/02.1-08-SUMMARY.md) records the same profile and agreement recovery.

- **Missing or expired agreement:** accept it in the Apple Developer account, then repeat the history check.
- **Keychain access prompt:** approve access to the existing item through macOS. Do not send the Keychain password to an agent.
- **Missing profile:** check the exact name `notary` and the build Mac's Keychain first. An email-named profile can be absent while `notary` works.
- **Authentication refusal after those checks:** investigate the existing key's access or revocation. Restore or replace credentials only when needed.

Signing and notarization use different credentials. An Xcode sign-in does not prove that a named `notarytool` profile exists.
No new app-specific password is needed while the existing team-key profile works.
Keep secret material in 1Password; use the supported Keychain profile for `notarytool` access. Never put credentials in documentation or command arguments.

**eli14:** Signing stamps the parcel with its sender. The saved `notary` key opens Apple's inspection desk.
If that key works, no new key is needed. Each new parcel still needs its own inspection.

Build with the verified profile:

```sh
scripts/build_app.sh \
  --sign "Developer ID Application: Andrei M. Lavrenov (VUMUR696L9)" \
  --notarize notary \
  --out dist
```

`--notarize` submits `dist/macos-apps-mcp.zip` with `notarytool submit --wait`, then staples the
ticket onto the `.app`. Re-create the distribution zip after stapling; the submission zip does not contain the ticket.
Verify with `xcrun stapler validate dist/macos-apps-mcp.app` and `spctl -a -vv -t install dist/macos-apps-mcp.app`.
Local same-Mac builds you never downloaded don't need this step —
notarization only matters once Gatekeeper sees a quarantine xattr.

### 2. Move it to `/Applications`

```sh
ditto dist/macos-apps-mcp.app /Applications/macos-apps-mcp.app
```

Use `ditto` (it keeps file times; a Finder drag is also fine), not `cp -R`. `cp -R` resets every
file's modification time, so a build made before #297 rewrites its `.pyc` inside the signed bundle
on the first run and breaks the code seal. If an older `/Applications/macos-apps-mcp.app` is
there, move it away first: `ditto` merges into an existing bundle, and a stale file breaks the seal.

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
   tool-call later) keeps a stray timeout from recording as a denial. If a prompt times out anyway, doctor shows
   that row with `reason: "prompt-timeout"` and the reset command to run before
   `doctor(request=True)` with someone at the screen.
4. Print the FDA deep-link and the shim `command:`/`args:` snippet to paste into your MCP
   clients.

**Full Disk Access does not prompt** — step 4 prints the command to open the pane
(`open 'x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles'` — run it
yourself); drag
`macos-apps-mcp.app` into the Full Disk Access list and enable it (this is what lets the daemon
read `chat.db` for Messages, and `TCC.db` itself for the `doctor` identity report).

**Accessibility does not prompt either** (#348) — `mail_reply` and `reply_all` keep Mail's own
quote by putting your text on top of Mail's reply window through Accessibility. Open
`x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility` (on macOS 27 the
list is named "Device Control and Data Access" in System Settings → Privacy & Security), add
`/Applications/macos-apps-mcp.app` and switch it on. Grant it to the bundle, never to a terminal:
a terminal's grant gives every program run in it control of the Mac's windows. While a reply is
built, Mail comes to the front for about a second, and the clipboard is borrowed and restored.
Without the grant those two tools refuse and leave nothing. `doctor` reports it as
`accessibility`, and the Health page shows an `Accessibility` row. A change to the switch takes
effect at once: the daemon reads it through a fresh check process on every call, so it needs no
restart.

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

**The shim is per-connection, so rebuilding the `.app` only half-lands.** The daemon picks up
a new bundle the moment launchd restarts it, but a client that is *already connected* keeps
running the shim process it spawned at connect time — old code, until it reconnects. Beyond
"the repo is not the daemon": after a rebuild, restart the daemon **and** reconnect every
client, or you are testing one build's daemon against another build's shim.

### 5. Outbound (send) mode under the daemon

```sh
macos-apps-mcp allow-send mail    # or: messages / mail,messages / all / off
macos-apps-mcp allow-send         # print the current setting
```

This writes `~/.local/state/macos-apps-mcp/allow_send` and runs the kickstart for you.

Why a file and not an environment variable: `MACOS_APPS_ALLOW_SEND` is read once, at import time,
by the process that registers the tools — **the daemon**, not the shim. An MCP client's `env`
block reaches the *shim* process only, and the shipped
`packaging/ren.lav.macos-apps-mcp.plist` has no `EnvironmentVariables` key, so setting it in a
client config is a silent no-op for daemon users — the send tools just never register, with no
error anywhere. The toggle file is home-pinned for the same reason as the daemon socket: the
shell that writes it and the launchd process that reads it do not share an environment, so
`XDG_STATE_HOME` would let them disagree. A *set* `MACOS_APPS_ALLOW_SEND` still wins over the
file, and the file is consulted **only** in the daemon role — stdio and CI stay env-driven.

The kickstart is what makes it take effect: registration happens at import, so a running daemon
keeps whatever gate it started with. Any client connected at that moment sees its transport drop
— respawn the shim to reconnect.

`launchctl setenv MACOS_APPS_ALLOW_SEND mail` + the same kickstart also works, but does not
survive a reboot. Baking an `EnvironmentVariables` dict into the plist persists too; the shipped
plist deliberately does **not** ship that key — sending stays off by default under the daemon.
Whichever route, `doctor()`'s
`deployment.outbound` (list of adapters currently send-enabled) and `deployment.outbound_note`
report the *effective* state as read by the daemon that's actually serving your client — run
`doctor` after the kickstart to confirm it took.

### 6. Turn adapters off under the daemon

The file `~/.local/state/macos-apps-mcp/adapters_off` holds a comma list of the adapters that
are OFF. The names are `calendar`, `contacts`, `mail`, `messages`, `music`, `notes`, `photos`,
`reminders`, `safari` and `shortcuts`; case does not matter. An unknown name is ignored and
`doctor` lists it as `adapters_unknown`. An absent or empty file means every adapter is on. A
file that exists but cannot be read (wrong owner or mode) turns every adapter off, and the
`doctor` note says so: the list fails closed, never open.

```sh
echo photos > ~/.local/state/macos-apps-mcp/adapters_off
launchctl kickstart -k gui/$(id -u)/ren.lav.macos-apps-mcp
```

The daemon reads the file once, at start, so apply a change with the kickstart above. An OFF
adapter's tools are absent from the tool list (never registered-and-erroring) and `doctor` gives
it no Automation probe and no EventKit request. Meta tools (`ping`, `now`, `doctor`, `audit`,
`usage`) always stay. `doctor()`'s `deployment.adapters`, `deployment.adapters_off` and
`deployment.adapters_pending` report the state the serving daemon read; `adapters_pending`
appears when the file changed after the daemon started.

`MACOS_APPS_ADAPTERS_OFF` sets the same list for a stdio server and, when set and non-empty,
wins over the file. The file is read **only** in the daemon role, and it is home-pinned for the
same reason as `allow_send` (see section 5). The localhost dashboard (section 7) writes the
same file.

### 7. The localhost dashboard

The daemon serves a dashboard at `http://127.0.0.1:47632`. It binds the loopback address only: a
non-loopback bind is refused. The MCP endpoint stays on the unix socket and is not reachable from
this port. Every request checks the `Host` header, and every form post checks `Origin` and a
per-session token.

Every page needs the page key. Run `macos-apps-mcp dashboard` in Terminal (bundle form:
`/Applications/macos-apps-mcp.app/Contents/MacOS/macos-apps-mcp -E -s -P -m macos_apps_mcp dashboard`).
It prints a link and opens it. The browser keeps the key as a cookie, so you run the command
again only on a new browser or after a key change. The key lives in
`~/.local/state/macos-apps-mcp/daemon/dashboard_key` (mode 0600, in a 0700 folder) and survives
restarts. To change the key, remove that file, restart the daemon (the kickstart in section 6)
and run the command again. Other accounts on this Mac and sandboxed apps can reach
`127.0.0.1:47632`, but they get a refusal that names the command. An unreadable key file refuses
every page until you remove it and restart the daemon. Browsers send a cookie to every port of 127.0.0.1, so a page
that another program serves there could receive the key when this browser opens it; if that may
have happened, change the key.

The pages:

| Page | What it shows |
|---|---|
| Writes (`/`) | every write in `audit.jsonl`, newest first; one click shows the word diff, the arguments and the raw log lines; a batch Mail write shows each message's backup |
| Health (`/health`) | what `doctor` reports; a danger banner only for an adapter that is on and whose macOS grant is denied; a row says when macOS grants could not be read |
| Adapters (`/adapters`) | one switch per app, what waits for a restart, the restart button |
| Usage (`/usage`) | calls per tool |
| Backups (`/backups`) | every Mail backup receipt on disk, each opened read-only |

Health runs `doctor` in its read-only mode: it never asks for a permission and never sends an
Apple Event. It runs one `doctor` call at a time. While a native call holds the worker (a bulk
Mail pass can hold it for hours), Health says `worker busy, a native call is in flight` and
still shows the Deployment group. Backups never deletes or prunes a backup, and it never creates
the backup folder.

The dashboard has **two write actions**: the adapter switches (they rewrite the `adapters_off`
file of section 6) and the restart. Each is logged in `audit.jsonl` with caller `dashboard`.
Recovery stays read-only: to undo a batch, copy the prompt on its page to Claude, which runs
`mail_undo` through the gated, audited MCP path.

A restart makes the daemon exit, and launchd starts it again. Open MCP connections drop for a
moment, and clients reconnect on their next call. A Mail batch that is running stops; its
receipt and its backups stay.

The Outbound gate is shown locked. It changes only with `macos-apps-mcp allow-send` (section 5),
because any website can send a request to `127.0.0.1`.

If the dashboard port is taken, the daemon logs it and keeps serving MCP. `doctor()` reports
`deployment.dashboard` as `not bound: …`; when the dashboard is up, it reports the URL. Without
the dashboard, change adapters through the `adapters_off` file and the kickstart of section 6:

```sh
launchctl kickstart -k gui/$(id -u)/ren.lav.macos-apps-mcp
```

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
   codesign -dvv --arch arm64 /Applications/macos-apps-mcp.app
   codesign -dvv --arch x86_64 /Applications/macos-apps-mcp.app
   ```
   Each slice has its own signature. Look for `flags=0x10000(runtime)` in both outputs — confirms hardened runtime is actually on,
   not just requested.

2. **Each slice carries its own entitlements, and both start under the runtime** (#205).
   The x86_64 slice carries one exception, `com.apple.security.cs.allow-unsigned-executable-memory`;
   the arm64 slice carries only `packaging/entitlements.plist`. Why: libffi has no pre-built
   trampoline pages on x86_64, neither the PBS copy nor Apple's `/usr/lib/libffi.dylib`, so
   ctypes and PyObjC write closure code at startup, which the hardened runtime refuses (the
   process hangs; with `env -i` it raises `MemoryError`). arm64 has the pages and needs no
   exception. Verified 2026-10-07: the python.org and BeeWare Pythons, which use Apple's libffi,
   fail the same way on x86_64, so a different interpreter does not avoid it.
   `codesign` takes one entitlement set per run, so the build signs the bundle once per set and
   joins the matching slices of the main executable with `lipo`. It then fails unless the log
   shows `entitlements ok: x86_64 has the exception, arm64 is strict`, `signed smoke ok: arm64`
   and `signed smoke ok: x86_64` (each signed slice loads the server and allocates a ctypes
   closure, with a 120-second cap). To check an installed app:
   ```sh
   codesign -d --entitlements - --arch x86_64 /Applications/macos-apps-mcp.app
   codesign -d --entitlements - --arch arm64 /Applications/macos-apps-mcp.app
   ```
   Never add the exception to `packaging/entitlements.plist`: that file is the arm64 set, and
   the build derives the x86_64 set from it.

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
    asking (chicken-and-egg: reading `TCC.db` itself needs FDA for the reader). Each entry has
    `client` and `granted`. An AppleEvents entry also has `target`, the bundle id of the
    controlled app. A denied entry has `reason` (TCC's `auth_reason`, for example
    `user-consent` or `prompt-timeout`). A `prompt-timeout` entry also has a `remediation` with
    the `tccutil reset <Service> ren.lav.macos-apps-mcp` command.
  - `deployment.outbound`: adapters with outbound send currently enabled (derived straight from
    the running process's `MACOS_APPS_ALLOW_SEND` state, `[]` if none) + `deployment.outbound_note`
    with the human-readable explanation — see "Outbound (send) mode under the daemon" above if
    it's `[]` and you expected sending to be on.
  - If `deployment.agent` shows `requires-approval`, open Login Items (above) and approve it.

- **Automation grants (macOS 27, #455).** macOS 27 keeps no readable per-user grant database,
  so `doctor` and the dashboard Health page read each Automation grant live with
  `AEDeterminePermissionToAutomateTarget`. The call sends no Apple Event and opens no dialog.
  Both read the same check, so they agree. The OSStatus maps to a status:

  | Code | Status | Meaning |
  |------|--------|---------|
  | `0` | `granted` | Automation is on for this app |
  | `-1743` | `denied` | switched off in System Settings → Privacy & Security → Automation |
  | `-1744` | `not_asked` | never asked: run `doctor(request=True)` with someone at the screen |
  | `-600` | `not_running` | the app is quit or unknown, so its state cannot be told yet |
  | other | `probe_error` | the check failed; `doctor(request=True)` probes by Apple Event |

  The grant belongs to the bundle's own identity, which differs from a terminal's: on
  2026-10-25 Finder answered `0` to a terminal and `-1744` to the bundle. Check it from the
  daemon, never from a terminal. Switching Notes off under the bundle's Automation list
  changed the answer from `0` to `-1743`, and switching it back on returned `0`
  (installed bundle, 2026-10-26). An app that is not running cannot be checked: open it and
  run `doctor` again, or reload the Health page.

- **Which permission changes need a restart.** Automation and Accessibility changes take
  effect at once, with no restart. A Full Disk Access, Calendars or Reminders change may need a
  daemon restart (the kickstart in section 6): this was not tested on a device, so restart when
  `doctor` does not show the change. `doctor`'s `note` says the same.

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
  (a fresh `shim` invocation), which re-probes the socket from scratch. That "not a silent hang"
  uses MCP 2 abandoned-stream handling and the shim warning middleware.
  The warning is a frontend tool error; the former `-32001` wire code is not preserved.

- **A tool call takes as long as it takes: there is NO read deadline on the shim↔daemon hop.**
  `_uds_client_factory` sets `httpx2.Timeout(None, connect=10.0)` on purpose. A call's duration
  is the *daemon's* business — a bulk Mail pass runs for **hours**, because a `whose` lookup is
  an O(mailbox) scan — and this hop is a local unix socket with no network to time out on. Only
  connect keeps a deadline. Adapters enforce their own per-operation limits (the AppleScript
  timeout surfaces as *"The macOS app didn't respond within 30.0s"*), which is the right layer:
  it knows what it asked for and can say so. **Do not "fix" a hang by adding a timeout here** —
  that is precisely [#170](https://github.com/elfensky/macos-apps-mcp/issues/170), where httpx's
  own default `Timeout(5.0)` cut the response stream 5s after the POST while the daemon was
  still working, and every destructive Mail call over ~5s died. The cliff moves with the value:
  4.5s returned and 6s did not; set it to 2s and 3s died; set it to `None` and 12s returned.

- **Discovery cannot connect to the daemon.** The shim uses public `provider_error_strategy="raise"`.
  A failed lookup preserves the connection MCP error, including a first call with no cached catalogue.
  Failed tool, resource, resource-template, and prompt lists return errors instead of successful empty lists.
  Healthy empty lists remain valid. A missing tool on a healthy backend still returns `Unknown tool`.

  Connection refusal before dispatch receives no `MAY HAVE COMPLETED` warning.
  A later explicit call can recover through the same shim after the backend returns.
  The shim adds no readiness wait or automatic replay. A connection error does not establish why the daemon is unavailable.
  Synthetic tests cover both protocol eras; the original November 1 incident and installed/frontend acceptance remain unproved (#543).

  **eli14:** The receptionist reports a disconnected phone instead of inventing an empty staff list.
  This prevents a misleading answer now. Actual client recovery still needs its own acceptance test.

- **A response stream ends without an answer.** MCP 2 reports the abandoned request.
  The shim recognizes `ToolError` caused by `MCPError(CONNECTION_CLOSED)` or an interrupted
  httpx2 read/write. This also covers a modern call that ran before sending response headers.
  Connect and pool failures retain their original error. Interrupted calls receive this warning:

  > daemon connection ended without a result — the operation MAY HAVE COMPLETED; check the
  > audit log before retrying anything destructive

  Inspect `~/.local/state/macos-apps-mcp/audit.jsonl` before repeating a destructive call.
  Completed audit records precede the response. A missing record does not prove that nothing changed.
  The shim retains the exception cause and never repeats the request automatically.
  Refused connections before dispatch and HTTP 413 responses do not receive this warning.

- **Large local messages.** The UDS transport sets `max_sse_event_size=None` through the public API.
  This permits responses larger than the SDK's default 1 MiB SSE limit.
  The peer is the application's own daemon behind a restricted socket.
  HTTP request bodies retain MCP 2's **4 MiB limit, including the serialized request envelope**.
  An oversized request receives HTTP 413 before tool execution. No private request handler is patched.
  Direct stdio mode has no HTTP envelope limit.

- **Caller identity and protocol.** The daemon reads name/version from public `client_info`.
  Each shim sends a stable `X-Macos-Apps-Shim-Id` header. Audit sanitizes it and caps it at 200 characters.
  These labels are advisory and never grant permission. Backend clients mirror each frontend's protocol era.
  Legacy ping works; the modern protocol removes ping. Without request context, the backend uses legacy mode.

**eli14:** The SDK is the cable between the client and server.
A broken cable does not prove that the command stopped. Repeating it could repeat a completed change.
The request-size limit rejects a large command before the server executes it.

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
