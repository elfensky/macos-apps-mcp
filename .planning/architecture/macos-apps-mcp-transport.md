---
kind: component
title: Transport
component: transport
status: implemented
source_revision: 18dcbf6594bbd62330f71c89376a54155dda1d63
source_evidence_date: 2026-11-04
review_status: independent-review-complete
publication_status: pending
---

# Transport

[Architecture overview](macos-apps-mcp-architecture.md)

## Responsibility and interfaces

Bare invocation serves FastMCP through standard input/output in the client process tree.
The `daemon` role serves Streamable HTTP over an owned Unix domain socket.
The `shim` role connects client standard input/output to that daemon through public `FastMCPProxy` and `ProxyClient` interfaces.
The shim performs no native app access.

The daemon socket has mode `0600`; its containing directory has mode `0700`.
One ASGI dispatcher separates MCP socket traffic from dashboard TCP traffic.
The dashboard cannot reach MCP through its TCP port.

**eli14:** The shim is a cable from the client's desk to the workshop.
The cable carries commands and answers, while the workshop operates the machines.
A broken cable can lose an answer after the work finishes.

## Implemented transport contract

| Boundary | Behavior |
|---|---|
| SDKs | MCP 2.3.0 and FastMCP 4.1.6; httpx2 2.16.0 supplies the local HTTP client. |
| Connect | `httpx2.Timeout(None, connect=10.0)` gives connection establishment a ten-second limit. |
| Read | No read deadline. Operation-specific native limits belong to adapters and runtime helpers. |
| Responses | `max_sse_event_size=None` removes the SSE event-size cap for the local connection. Adapter output limits still apply. |
| Requests | The upstream HTTP limit is 4 MiB, including the serialized request envelope. Oversized requests receive HTTP 413 before tool execution. |
| Protocol | The public request context selects the backend protocol era. Modern requests preserve their exact protocol version. |
| Initialization | Missing request context and legacy ping use a legacy backend. Modern MCP has no ping. |
| Identity | Public `client_info` carries client name/version. `x-macos-apps-shim-id` carries one advisory identifier per shim. |
| Notifications | Public proxy support forwards logs and progress. Incoming client headers are not generally forwarded. |

The shim uses an HTTP URL routed through the Unix socket; its dummy hostname is not resolved.
The advisory shim header is not a model extra and grants no permission.

## Interrupted operations

MCP 2 reports abandoned response streams. `_InterruptedToolWarning` adds an uncertain-outcome warning to relevant connection failures.
It also covers a connection lost before response headers arrive.
The frontend receives a tool error with its cause retained. The shim does not replay the request.
Definite connection refusal and HTTP 413 do not receive this warning.

The warning asks for inspection before another destructive attempt.
Because [audit persistence is best-effort](macos-apps-mcp-audit-and-recovery.md), an absent audit record cannot prove that nothing happened.

## Evidence and acceptance

- [daemon.py](../../macos_apps_mcp/daemon.py): `_uds_client_factory`, `_shim_client_factory`, `build_shim`, `_InterruptedToolWarning`, and `make_dispatcher`.
- [cli.py](../../macos_apps_mcp/cli.py): role dispatch.
- [Transport regressions](../../tests/test_mcp_transport.py) and [stream smoke](../../scripts/smoke_stream.py): execution counts, long calls, protocol eras, request sizes, and interrupted responses.
- [Phase 05.4 implementation](../phases/05.4-mcp-2-fastmcp-4-migration/05.4-IMPLEMENTATION.md) and [decisions](../phases/05.4-mcp-2-fastmcp-4-migration/05.4-DECISIONS.md).

Status is implemented in source. Installed-daemon and native application acceptance remain separate from the synthetic transport evidence.
