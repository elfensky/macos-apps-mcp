# Tools and policy

## What it does

`server.py` exposes thin tool dispatch. Adapters own app behavior.
`PointerSource` defines the `get_pointers(query) -> list[Pointer]` boundary for query-shaped reads.
Enumeration reads, such as `safari_tabs`, have a typed method per adapter.
`Snapshotter` supplies optional before-state. Typed records such as `ReminderData` and `CalendarEventData` carry app-specific write input.
These are typed boundaries, without an adapter base class or plugin loader.

A `Pointer` contains `id`, `summary`, and `deeplink`, with optional contextual fields.
Bodies and exports require explicit tools. Bounded reads use `read_result()` to report truncation, alternate access paths, incomplete coverage, or stale indexes.
Native failures become tool errors with remediation text; a genuine empty result remains distinct from a failure.

## Rules it keeps

### Implemented gates

One `ToolRecord` per tool supplies tier, adapter, permission labels, audit verb, snapshot source, and notice policy.
This registry records tool facts; it is not a plugin registry.
Gates run during registration. A disabled tool is absent from the MCP tool list.

| Gate | Effect |
|---|---|
| Adapter deny-list | Removes every tier of the named adapter. The five meta tools `ping`, `now`, `doctor`, `usage` and `audit` stay. The list comes from `MACOS_APPS_ADAPTERS_OFF` or the daemon's `adapters_off` file. |
| Read | Available when its adapter is enabled. |
| Write | Additive and destructive tools are absent when `MACOS_APPS_READ_ONLY` is enabled. |
| Outbound | Send tools require `MACOS_APPS_ALLOW_SEND` or the daemon's persisted operator setting. Read-only mode always takes precedence. |

Send tools carry destructive and `openWorldHint` annotations and default to `dry_run=True`.
Content-removing tools also default to previews. This does not imply that every additive tool has a preview parameter.
Shortcut execution is a write with an open-world annotation because a shortcut can contact external services.

### Preview and content limits

Outbound previews construct no outgoing message and do not send.
New-message and forward previews make no native call.
The stored-draft and reply-all builders read stored Mail before `deliver()` runs.
`mail_outgoing.py` states the rule: a preview never builds a message, and it can read stored mail.
A send that times out reports that Mail possibly sent the message. The error asks for a check of Outbox and Sent before a retry (#573).
Local destructive previews can also read native state to validate their targets.

`UntrustedDataNotice` prepends a warning to every successful result except `ping`, `now`, `doctor` and `usage`. It does not change the structured content.
The warning marks app data as untrusted; it is not a prompt-injection containment boundary.
Caller identity remains advisory, as described in [transport](https://github.com/elfensky/macos-apps-mcp/blob/834691b4ab771698a09d63e7546a0781caf4b548/.planning/architecture/macos-apps-mcp-transport.md).

## Code paths

- [server.py](https://github.com/elfensky/macos-apps-mcp/blob/834691b4ab771698a09d63e7546a0781caf4b548/macos_apps_mcp/server.py), [contracts.py](https://github.com/elfensky/macos-apps-mcp/blob/834691b4ab771698a09d63e7546a0781caf4b548/macos_apps_mcp/contracts.py), [registry.py](https://github.com/elfensky/macos-apps-mcp/blob/834691b4ab771698a09d63e7546a0781caf4b548/macos_apps_mcp/registry.py), and [tiers.py](https://github.com/elfensky/macos-apps-mcp/blob/834691b4ab771698a09d63e7546a0781caf4b548/macos_apps_mcp/tiers.py).
- [notices.py](https://github.com/elfensky/macos-apps-mcp/blob/834691b4ab771698a09d63e7546a0781caf4b548/macos_apps_mcp/notices.py), [mail_outgoing.py](https://github.com/elfensky/macos-apps-mcp/blob/834691b4ab771698a09d63e7546a0781caf4b548/macos_apps_mcp/adapters/mail_outgoing.py), and [preview tests](https://github.com/elfensky/macos-apps-mcp/blob/834691b4ab771698a09d63e7546a0781caf4b548/tests/test_mail_outgoing.py).
- [Annotation and send-gate tests](https://github.com/elfensky/macos-apps-mcp/blob/834691b4ab771698a09d63e7546a0781caf4b548/tests/test_tool_annotations.py), [registry and gate tests](https://github.com/elfensky/macos-apps-mcp/blob/834691b4ab771698a09d63e7546a0781caf4b548/tests/test_registry.py), [send dispatch tests](https://github.com/elfensky/macos-apps-mcp/blob/834691b4ab771698a09d63e7546a0781caf4b548/tests/test_gate_on_dispatch.py), and [import boundaries](https://github.com/elfensky/macos-apps-mcp/blob/834691b4ab771698a09d63e7546a0781caf4b548/tests/test_import_layers.py).
- [Dispatch test for every tool](https://github.com/elfensky/macos-apps-mcp/blob/834691b4ab771698a09d63e7546a0781caf4b548/tests/test_tool_dispatch.py) and [send timeout tests](https://github.com/elfensky/macos-apps-mcp/blob/834691b4ab771698a09d63e7546a0781caf4b548/tests/test_mail_send_timeout.py).

## Sources

- [Phase 1 verification](https://github.com/elfensky/macos-apps-mcp/blob/834691b4ab771698a09d63e7546a0781caf4b548/.planning/phases/01-gate-land-the-spiked-architecture-cuts/01-VERIFICATION.md).

Phase 05.12 is in progress. Its PR #584 added the dispatch test over `registry.TOOLS` (#581).
Phase 05.10 plans tool names, parameter descriptions, error codes (#502) and the omitted-field rule (#572).
Phase 05.11 plans query-bound paging. Phase 05.7 plans agent guidance.
Their scope belongs to the [roadmap](https://github.com/elfensky/macos-apps-mcp/blob/834691b4ab771698a09d63e7546a0781caf4b548/.planning/ROADMAP.md).
