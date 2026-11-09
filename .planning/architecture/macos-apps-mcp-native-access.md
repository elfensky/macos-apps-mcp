---
kind: component
title: Native access
component: native-access
status: implemented
source_revision: 67a668c39484ebc2017c092d008f1dd705ccff73
source_evidence_date: 2026-11-09
---

# Native access

[Architecture overview](macos-apps-mcp-architecture.md)

## What it does

The `runtime` module owns one `ThreadPoolExecutor(max_workers=1)` for adapter native access. `run_native()` submits each job to this worker.
EventKit, AppleScript, native database readers, osxphotos, the Automation permission probe and the Accessibility reply seam use this worker.
The Shortcuts CLI and the locale read run on the calling thread.
`eventkit.py` owns the single lazy `EKEventStore`; its `store()` refuses access outside the native worker.
FastMCP can dispatch concurrent calls, but this worker serializes their native work.

`run_osascript()` sends user values through arguments rather than script interpolation.
`read_via_sqlite()` opens native stores read-only and checks schema fingerprints before interpreting rows.
Live reads include SQLite's write-ahead log. Immutable mode is reserved for static stores.
An unavailable store uses an adapter's explicit fallback, or raises a typed error.

**eli14:** The workshop has one machine station because its tools must stay with the same operator.
Jobs wait their turn at that station.
A jam can delay later jobs, so individual operations have stop conditions.
Adding operators without separating the tools would break this arrangement.

## Rules it keeps

AppleScript has a default 30-second host limit; adapters provide operation-specific limits where needed.
EventKit callback waits are bounded. Permission requests have a separate 120-second wait limit.
`run_osascript()` maps osascript status codes to typed errors. A timeout message tells a stuck app from a busy app, from a `ps` read in the C locale.
These limits do not introduce a read deadline on the [shim connection](macos-apps-mcp-transport.md).
Serialization is not a transaction across separate native reads and writes.

`tracked_run()` and AppleScript dispatch register child processes for cleanup.
Timed-out subprocesses are killed and reaped. This cannot prove that an Apple Event already accepted by an app had no effect.
The direct stdio server installs parent-death monitoring and child cleanup.
The daemon installs no lifecycle guards and no exit-path child cleanup. launchd `KeepAlive` starts it again after each exit.

`NativeError` subclasses distinguish denied access, a stopped app, timeouts, schema drift, unsupported platforms, ambiguous targets, oversized batches or output, and refused or unverified writes.
The [tool layer](macos-apps-mcp-tools-and-policy.md) converts these failures to actionable tool errors.
macOS-only imports are platform-guarded. Off macOS, imports and tool listing work; native operations refuse through `require_macos()`.

## Code paths

- [runtime.py](../../macos_apps_mcp/runtime.py): worker, AppleScript, read-only SQLite, osxphotos, permission probes, the Accessibility reply seam, and subprocess ownership.
- [eventkit.py](../../macos_apps_mcp/eventkit.py), [lifecycle.py](../../macos_apps_mcp/lifecycle.py), and [errors.py](../../macos_apps_mcp/errors.py).
- [Native seam tests](../../tests/test_native_seam.py), [runtime tests](../../tests/test_runtime.py), and [off-macOS tests](../../tests/test_off_macos.py).

## Sources

- [Phase 1 verification](../phases/01-gate-land-the-spiked-architecture-cuts/01-VERIFICATION.md) and [Phase 3 verification](../phases/03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub/03-VERIFICATION.md).
- [Phase 05.2-16 device acceptance](../phases/05.2-bug-fixes-automation-grants-unreadable-on-macos-27-455/05.2-16-SUMMARY.md): failed on installed build `926ec99`. #348 and #516 remain open.

Device evidence applies to its recorded builds, not to the current installed daemon. Phase 05.2 device acceptance remains incomplete.
