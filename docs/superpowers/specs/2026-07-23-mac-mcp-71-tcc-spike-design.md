# #71 — launchd + TCC-to-bundle: Phase-0 spike design

**Issue:** [#71](https://github.com/elfensky/macos-apps-mcp/issues/71) · **Milestone:** 0.8.0 · **Date:** 2026-07-23 · **Status:** spike (pre-spec)

## Why a spike first

A 3-model design panel (ponytail-minimalist, macOS-platform-realist on Opus, correctness/ops
skeptic) converged on a finding that **overturns the "just ship a signed .app" plan**:

> **TCC attributes grants to the _responsible process_, not to the bundle id.** macOS stamps a
> responsible pid at `exec` time: a process launched **top-level by launchd/LaunchServices** is
> responsible for itself; a process **`posix_spawn`'d by a parent** inherits the parent as
> responsible — unless the parent sets `POSIX_SPAWN_DISCLAIM`, which Claude Desktop / VS Code /
> Claude Code do **not**, and we cannot change.

Consequences (hold for EventKit, Automation/AppleEvents source-pairing, and FDA alike):

- **Option A is dead.** Signing the `.app` and having each client stdio-spawn it does *not* move
  attribution to `ren.lav.macos-apps-mcp` — TCC still keys the grant to the launching client.
  (Same mechanism as "drag Terminal into Full Disk Access → everything Terminal spawns gets it.")
- **launchd is required for the _core_ goal (criterion 1), not just single-instance (criterion 2).**
  Only a launchd top-level launch makes the bundle its own responsible process.

The whole architecture therefore rests on one empirical claim about *this* Mac's macOS version.
Prove it before building anything.

## The Python `exec` trap (second crux)

The running image must **be** the signed bundle executable. If `CFBundleExecutable` is a launcher
that `exec`s `.venv/bin/python`, the exec **replaces the image** — the process is now `python`, and
TCC/codesign read *python's* signature, not the bundle's. Attribution is lost.

Fix (for the eventual product, and for spike Stage 2): bundle a **relocatable Python**
(python-build-standalone) as `Contents/MacOS/<CFBundleExecutable>`, run it in-process (PyObjC loads
frameworks in-process, no exec), and **deep-sign** the interpreter + every `.dylib`/`.so`.

## Target architecture (to be confirmed by the spike, then specced)

- One **launchd LaunchAgent** runs `ren.lav.macos-apps-mcp.app` top-level → own responsible process
  → grant once, works from every client.
- **Developer ID signed**, hardened runtime, **notarized + stapled** (a client `posix_spawn`ing a
  *quarantined* binary gets a silent Gatekeeper kill). Bundle id **`ren.lav.macos-apps-mcp`**.
- Entitlements: `com.apple.security.automation.apple-events` (hardened runtime blocks AppleEvents to
  Mail/Notes without it), `com.apple.security.cs.disable-library-validation` (Python dlopens native
  modules not signed by our Team ID). Info.plist usage strings: `NSCalendarsFullAccessUsageDescription`,
  `NSRemindersFullAccessUsageDescription`, `NSContactsUsageDescription`, `NSAppleEventsUsageDescription`.
- **Transport: unix domain socket** in a `0700` state dir, `0600` socket — *not* a localhost TCP
  port (DNS-rebinding surface against a server holding Mail/calendar data). Clients keep their
  `command:`-spawn config but spawn a tiny **stdio↔socket shim** instead of the interpreter.
- **`doctor`** reports which identity currently holds each grant (extends `_responsible_process()`).

## The spike — two stages

### Stage 1 (NOW, ad-hoc signed — no Apple enrollment needed)
Answers the architecture-deciding question: does launchd-top-level launch attribute to the bundle,
while stdio-spawn attributes to the parent? Responsible-process resolution is kernel behavior,
independent of signing *identity*, so ad-hoc is enough for a strong early read (grant *persistence*
may be flaky ad-hoc — that's Stage 2).

1. Build a minimal `.app` (bundle id `ren.lav.macos-apps-mcp.spike`) whose main executable, on
   launch, (a) requests Calendar via EventKit and (b) tries to open `~/Library/Messages/chat.db`
   (FDA). Ad-hoc sign (`codesign -s -`). Two variants: a compiled binary (clean attribution
   baseline) and the bundled-relocatable-Python variant (proves the Python-image case).
2. Launch it via a **LaunchAgent** (launchd top-level). Approve Calendar; drag into FDA. Confirm
   the grant row is keyed to the bundle id.
3. Now spawn the **same binary** two other ways: directly from Terminal, and from a tiny
   `child_process.spawn` mimicking an MCP client.
4. Observe: `log stream --predicate 'subsystem == "com.apple.TCC"' --info` (watch the responsible /
   client field) and
   `sqlite3 ~/Library/Application\ Support/com.apple.TCC/TCC.db "select service,client,client_type,auth_value from access;"`
   — is the row keyed to `ren.lav.macos-apps-mcp*` or to the parent (Terminal / the mock client)?

**Decision gate:** launchd launch attributes to the bundle AND stdio-spawn attributes to the parent
→ proceed with the launchd-agent + unix-socket + shim architecture. If launchd launch does *not*
attribute to the bundle → the whole approach is dead; stop and rethink (escalate).

### Stage 2 (after Apple Developer enrollment)
Developer ID sign + hardened runtime + notarize + staple the bundled-Python variant; confirm:
grant **persists** across rebuilds/relaunches; a client spawning the notarized binary launches
without Gatekeeper friction; AppleEvents to Mail works (no `-1743 errAEEventNotPermitted`); a
protected read (chat.db) succeeds under the bundle's FDA grant.

### Detection commands (both stages)
- `codesign -dvvv <running-exe>` → `Identifier=ren.lav.macos-apps-mcp*`, `flags=…runtime`.
- `codesign -d --entitlements - <exe>` → entitlements actually present.
- `spctl -a -vvv MyApp.app` → Gatekeeper verdict (Stage 2).
- `log stream --predicate 'eventMessage CONTAINS "Library Validation"'` → native `.so` load kills.
- `sw_vers` → record the macOS build the result is valid for (13→14→15 differ on FDA/agent-consent).

## Blocked-on / owner actions
- **Andrei:** enrol in Apple Developer Program (developer.apple.com/programs, $99/yr) + create a
  **Developer ID Application** certificate → gates Stage 2. Enrollment can take up to ~2 days.
- Stage 1 can run immediately (ad-hoc).

## Out of scope / deferred
- The daemon's value for single-instance (criterion 2) is real but secondary; the same
  launchd+socket design delivers it for free once Stage 1 validates the model.
- FTS-sidecar concurrency (a separate shipped-#70 bug) already fixed on develop (PR #121).
