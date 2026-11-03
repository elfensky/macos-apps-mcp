# MCP migration debate: Codex position

**Revision:** `926ec99`
**Participant:** GPT-6 Astra through Codex
**Evidence date:** 2026-11-03
**Question:** Which migration preserves existing behavior with the smallest supported implementation?

## Position

Prefer FastMCP 4.1.6 and MCP 2.3.0 with supported httpx2 transport and public request context.
Retire the private MCP 1 stream patch after behavioral regression tests establish equivalent failure handling.
Keep the operation-outcome warning in an application-owned boundary, preserving error codes and avoiding retries.
The previous patch exists because MCP 1 could silently abandon a request. The new SDK already answers that failure.
Porting the private patch would duplicate the new SDK's responsibility and expose the application to private API drift.

Use an explicit shim HTTP header for correlation. MCP 2 discards the extra `Implementation.session` field.
Request `_meta` is another supported channel, but injecting it through every proxy request adds more application code.
The header fits the existing local transport and was verified through the actual proxy and UDS stack.
Read it through the public FastMCP HTTP-context accessor. Sanitize it and retain advisory-only semantics.

```python
httpx2.AsyncClient(
    transport=httpx2.AsyncHTTPTransport(uds=str(path)),
    timeout=httpx2.Timeout(None, connect=10.0),
)
```

## Required objections and checks

The new default SSE size limit may reject legitimate large tool responses. Resolve that behavior explicitly before accepting the migration.
Test both modern and legacy frontend clients. Prefer the library's supported protocol forwarding where practical.
Ensure failure translation covers the actual proxy exception boundary and preserves useful context without labeling definite refusals as uncertain writes.
Test initialization and ping fallbacks, two shim instances, notifications and complete answers before a stream closes.
Use synthetic tools for transport tests. Mock-only tests cannot prove the request reaches the daemon or the error reaches the caller.

The independent Claude participant should challenge these assumptions using installed source and the recorded probe.
Disagreement supported by a failing probe takes precedence over agreement by model count.

## Sources

- [Migration research](../phases/05.4-mcp-2-fastmcp-4-migration/05.4-RESEARCH.md).
- [MCP 2.3.0 transport source](https://raw.githubusercontent.com/modelcontextprotocol/python-sdk/v2.3.0/src/mcp/client/streamable_http.py).
- `macos_apps_mcp/daemon.py`: existing UDS factory, private stream patch and proxy client factory.
- `macos_apps_mcp/audit.py`: caller metadata and audit error behavior.

The T3 host requires cross-provider dispatch through `delegate_task`.
The Octopus debate structure is used with that host transport instead of direct provider CLI dispatch.
