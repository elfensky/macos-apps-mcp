---
kind: component
title: Tools and policy
component: tools-and-policy
status: implemented
source_revision: f91dbed988745ff2d7847907a53d8927b7b2809f
source_evidence_date: 2026-11-04
review_status: pending
publication_status: pending
---

# Tools and policy

[Architecture overview](macos-apps-mcp-architecture.md)

## Responsibility and interfaces

`server.py` exposes thin tool dispatch. Adapters own app behavior.
`PointerSource` defines the uniform `get_pointers(query) -> list[Pointer]` read boundary.
`Snapshotter` supplies optional before-state. Typed records such as `ReminderData` and `CalendarEventData` carry app-specific write input.
These are typed boundaries, without an adapter base class or plugin loader.

A `Pointer` contains `id`, `summary`, and `deeplink`, with optional contextual fields.
Bodies and exports require explicit tools. Bounded reads use `read_result()` to report truncation, alternate access paths, incomplete coverage, or stale indexes.
Native failures become tool errors with remediation text; a genuine empty result remains distinct from a failure.

**eli14:** The workshop desk offers a menu of permitted jobs and returns short collection tickets.
A ticket identifies the item without carrying its entire contents.
Removing a job from the menu prevents a client from requesting that tool through MCP.
It does not authenticate the name printed on the ticket.

## Implemented gates

One `ToolRecord` per tool supplies tier, adapter, permission labels, audit verb, snapshot source, and notice policy.
This registry records tool facts; it is not a plugin registry.
Gates run during registration. A disabled tool is absent from the MCP tool list.

| Gate | Effect |
|---|---|
| Adapter deny-list | Removes every tier for the selected adapter; metadata tools remain available. |
| Read | Available when its adapter is enabled. |
| Write | Additive and destructive tools are absent when `MACOS_APPS_READ_ONLY` is enabled. |
| Outbound | Send tools require `MACOS_APPS_ALLOW_SEND` or the daemon's persisted operator setting. Read-only mode always takes precedence. |

Send tools carry destructive and `openWorldHint` annotations and default to `dry_run=True`.
Content-removing tools also default to previews. This does not imply that every additive tool has a preview parameter.
Shortcut execution is a write with an open-world annotation because a shortcut can contact external services.

## Preview and content limits

Outbound previews construct no outgoing message and do not send.
New-message and forward previews make no native call.
Stored-draft and reply-all builders currently read existing Mail data before `deliver()` returns their preview.
Thus the broader native-free outbound rule is not a universal description of the current implementation.
Local destructive previews can also read native state to validate their targets.

`UntrustedDataNotice` prepends a warning to successful content-bearing results and preserves structured content.
The warning marks app data as untrusted; it is not a prompt-injection containment boundary.
Caller identity remains advisory, as described in [transport](macos-apps-mcp-transport.md).

## Sources and planned work

- [server.py](../../macos_apps_mcp/server.py), [contracts.py](../../macos_apps_mcp/contracts.py), [registry.py](../../macos_apps_mcp/registry.py), and [tiers.py](../../macos_apps_mcp/tiers.py).
- [notices.py](../../macos_apps_mcp/notices.py), [mail_outgoing.py](../../macos_apps_mcp/adapters/mail_outgoing.py), and [preview tests](../../tests/test_mail_outgoing.py).
- [Gate tests](../../tests/test_tool_annotations.py), [registration tests](../../tests/test_gate_on_dispatch.py), and [import boundaries](../../tests/test_import_layers.py).
- [Phase 1 verification](../phases/01-gate-land-the-spiked-architecture-cuts/01-VERIFICATION.md).

Status is implemented, with the preview qualification above.
Tool naming and parameter revisions in Phase 05.10, query-bound pagination in Phase 05.11, and agent guidance in Phase 05.7 remain planned.
Their scope belongs to the [roadmap](../ROADMAP.md).
