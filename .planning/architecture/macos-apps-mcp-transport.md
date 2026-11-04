---
kind: component
title: Transport
component: transport
status: implemented
source_revision: 18dcbf6594bbd62330f71c89376a54155dda1d63
source_evidence_date: 2026-11-04
review_status: independent-review-complete
publication_status: published
first_published_at: "2026-11-04T01:34:18Z"
first_published_revision: 93c7f0928d2534ddae2392e78ec722f55491a2ae
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

## Discovery failures

The single-backend proxy uses public `provider_error_strategy="raise"`.
Failed discovery preserves the connection MCP error, including a tool lookup with a cold catalogue.
Tool, resource, resource-template, and prompt list failures return errors instead of successful empty lists.
Healthy empty lists and genuine `Unknown tool` responses retain their existing meaning.
Connection refusal before dispatch receives no uncertain-outcome warning.
A later explicit call can succeed through the same shim after backend replacement; there is no automatic replay or readiness wait.

**eli14:** The workshop cable must report a failed connection instead of an empty inventory.
This prevents a misleading answer now. Normal restart recovery passed through one installed stdio client. A deliberately stopped interval and real frontend behavior remain untested.

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
- [Discovery-error regression](../phases/05.4-mcp-2-fastmcp-4-migration/05.4-02-SUMMARY.md): both protocol eras, explicit recovery, failed lists, and healthy missing names.

Status is implemented in source. [Installed arm64 evidence](../overnight/2026-11-04-installed-acceptance.md) covers both protocol eras, bounded native reads, notices, and normal restart recovery.
Controlled absence, a native call exceeding five seconds, and real frontend acceptance remain open.
The synthetic reproduction does not prove the original November 1 incident in issue #543.
