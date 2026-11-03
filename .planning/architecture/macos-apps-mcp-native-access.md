---
kind: component
title: Native access
component: native-access
status: implemented
source_revision: f91dbed988745ff2d7847907a53d8927b7b2809f
source_evidence_date: 2026-11-04
review_status: pending
publication_status: pending
---

# Native access

[Architecture overview](macos-apps-mcp-architecture.md)

## Responsibility and interfaces

`runtime.run_native()` owns one `ThreadPoolExecutor(max_workers=1)` for adapter native access.
EventKit, AppleScript, native database readers, and osxphotos use this shared boundary.
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

## Implemented limits and lifecycle

AppleScript has a default 30-second host limit; adapters provide operation-specific limits where needed.
EventKit callback waits are bounded. Permission requests have a separate 120-second wait limit.
These limits do not introduce a read deadline on the [shim connection](macos-apps-mcp-transport.md).
Serialization is not a transaction across separate native reads and writes.

`tracked_run()` and AppleScript dispatch register child processes for cleanup.
Timed-out subprocesses are killed and reaped. This cannot prove that an Apple Event already accepted by an app had no effect.
The direct stdio server installs parent-death monitoring and child cleanup.
The daemon instead relies on launchd for its lifecycle and restart.

`NativeError` subclasses distinguish denied access, timeout, schema drift, unsupported platforms, and refused or unverified writes.
The [tool layer](macos-apps-mcp-tools-and-policy.md) converts these failures to actionable tool errors.
macOS-only imports are platform-guarded. Off macOS, imports and tool listing work; native operations refuse through `require_macos()`.

## Sources and acceptance

- [runtime.py](../../macos_apps_mcp/runtime.py): worker, AppleScript, read-only SQLite, and subprocess ownership.
- [eventkit.py](../../macos_apps_mcp/eventkit.py), [lifecycle.py](../../macos_apps_mcp/lifecycle.py), and [errors.py](../../macos_apps_mcp/errors.py).
- [Native seam tests](../../tests/test_native_seam.py), [runtime tests](../../tests/test_runtime.py), and [off-macOS tests](../../tests/test_off_macos.py).
- [Phase 1 verification](../phases/01-gate-land-the-spiked-architecture-cuts/01-VERIFICATION.md) and [Phase 3 verification](../phases/03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub/03-VERIFICATION.md).
- [Phase 05.2 acceptance plan](../phases/05.2-bug-fixes-automation-grants-unreadable-on-macos-27-455/05.2-13-PLAN.md): native permission and Mail reply acceptance.

Status is implemented in source. Historical device evidence applies to its recorded builds, not automatically to the current installed daemon.
