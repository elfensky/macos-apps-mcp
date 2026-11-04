---
kind: architecture
title: macos-apps-mcp architecture
status: implemented
source_revision: 4a7c26287b108c9c81f42db0bdf5280ed537e986
source_evidence_date: 2026-11-04
review_status: source-checked-update
publication_status: published
first_published_at: "2026-11-04T01:34:18Z"
first_published_revision: 93c7f0928d2534ddae2392e78ec722f55491a2ae
---

# macos-apps-mcp architecture

macos-apps-mcp gives MCP clients bounded access to ten native macOS app families.
Python adapters return citable pointers and perform explicitly requested actions.
FastMCP exposes the tools directly through standard input/output, or through a shim connected to a local daemon.
The daemon also provides a separate local operator dashboard.

**eli14:** The server is a workshop with a reception desk, specialist benches, and one shared machine station.
The desk accepts permitted jobs, and each bench knows its app.
The station handles native app access in order.
A job can finish even when its receipt is lost; the missing receipt does not make repetition safe.

## Components

The diagram describes implemented responsibilities. Arrows show communication or dependency, rather than permission grants.

```mermaid
flowchart TD
    client["MCP client"] --> transport["Transport: stdio or shim and daemon"]
    transport --> tools-and-policy["Tools and policy"]
    tools-and-policy --> adapters["App adapters"]
    tools-and-policy --> audit-and-recovery["Audit and recovery"]
    adapters --> audit-and-recovery
    adapters --> native-access["Native access"]
    native-access --> apps["macOS apps and local stores"]
    operator["Local operator"] --> operator-controls["Dashboard and CLI"]
    operator-controls --> audit-and-recovery
    operator-controls --> native-access
    operator-controls --> transport
    packaging-and-release["Packaging and release"] --> transport
```

- [Transport](macos-apps-mcp-transport.md): client connections, protocol compatibility, and interrupted calls.
- [Tools and policy](macos-apps-mcp-tools-and-policy.md): typed boundaries, capability gates, and result notices.
- [Native access](macos-apps-mcp-native-access.md): serialized framework access, native readers, and process cleanup.
- [Adapters](macos-apps-mcp-adapters.md): app-specific reads, actions, and limits.
- [Audit and recovery](macos-apps-mcp-audit-and-recovery.md): best-effort records, Mail backups, and recovery receipts.
- [Operator controls](macos-apps-mcp-operator-controls.md): dashboard access, diagnostics, adapter settings, and restart.
- [Packaging and release](macos-apps-mcp-packaging-and-release.md): locked dependencies, universal bundle, notices, and release evidence.

## Implemented boundaries

The lock selects MCP 2.3.0, FastMCP 4.1.6, mcp-types 2.3.0, and httpx2 2.16.0.
Tool registration applies capability gates before tools become visible to clients.
The native worker preserves EventKit thread affinity.
Native database access uses read-only connections; app-specific actions use frameworks, AppleScript, or the Shortcuts CLI.
Caller names and shim identifiers are advisory labels, not authenticated identities.

Audit logging is explicitly best-effort. A native action can finish without a persisted audit record.
Private storage checks protect particular file writes; they do not disable every native action when storage fails.
Mail recovery does not provide universal undo. Notes write guards and full-body backups remain planned.

## Lifecycle and acceptance

- `active` describes project lifecycle, not runtime health.
- Completion dates describe historical records, not future delivery promises.
- A phase requires its acceptance checks; implementation or a checked roadmap box alone does not complete acceptance.
- Implementation, installed-device acceptance, and release are separate states.

Migration #550, private storage #552, and distribution notices #553 are implemented in the source revision above.
Localization #554 is merged in this baseline. Notes uses folder types with translated fallback names; Mail names remain heuristics.
Ambiguous Trash candidates remain tracked in #556. Non-English device acceptance and real-index timing are still open.
Adapters permission chips use the last completed Health report under #497, with its local completion time.
Explicit Full Disk Access and EventKit refusals override stale grant rows. Real macOS 27 acceptance remains pending.
The latest published release remains `v0.15.1`. GSD's `v0.11.0` milestone label is not the software version.

The migration evidence covers an unsigned universal bundle and both executable slices on an Apple-silicon host.
It does not establish signing, notarization, installation, physical Intel acceptance, or native application acceptance for this baseline.
The currently installed build is unverified here.

**eli14:** A workshop can be active while a machine needs repair.
A finished part, a machine tested in its installed position, and a delivered product have different completion records.

## Sources and phase links

The source evidence date records source inspection. Earlier architecture content has independent Claude review.
Grant-chip additions have source validation; that earlier architecture review does not cover the later wording. User review remains pending.
`source_revision` identifies the inspected code baseline. The published page commit must be derived separately from Git.
No `as_of` user-review date is asserted.
The Garage roadmap and architecture were first published on 2026-11-04. [Publication evidence](../overnight/garage-publication-2026-11-04.md) records the source and verification.

- [Project scope](../PROJECT.md) and [phase roadmap](../ROADMAP.md).
- [Tool server](../../macos_apps_mcp/server.py), [transport](../../macos_apps_mcp/daemon.py), and [dependency lock](../../uv.lock).
- [Migration implementation and acceptance limits](../phases/05.4-mcp-2-fastmcp-4-migration/05.4-IMPLEMENTATION.md).
- [Private storage implementation](../phases/05.6-bug-fixes-notes-write-safety-and-system-folders-in-any-langu/05.6-01-SUMMARY.md).
- [Distribution notice inventory](../../packaging/licenses/README.md).
- [Planned Notes safety](../phases/05.6-bug-fixes-notes-write-safety-and-system-folders-in-any-langu/05.6-CONTEXT.md).

- [Implemented grant chips and acceptance limits](../phases/05.6-bug-fixes-notes-write-safety-and-system-folders-in-any-langu/05.6-04-SUMMARY.md).

## Display contract

These Markdown files are the local sources. The frontmatter describes content; it does not imply an implemented publisher validator.
The published overview path is `/macos-apps-mcp/architecture/`.
Component paths are `/macos-apps-mcp/architecture/<component>/`, using the seven linked filenames without `macos-apps-mcp-` or `.md`.
All eight architecture paths were verified after publication.

Publication uses the existing plain HTML publisher after merge and vault cutover.
The Mermaid block remains source text; the component list provides equivalent navigation without a renderer.
Display assets must remain local. Working notes are excluded from display content.
