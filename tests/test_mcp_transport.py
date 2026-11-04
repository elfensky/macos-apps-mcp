"""MCP 2 migration contracts over real UDS and synthetic tools (#470)."""

import asyncio
import json

import httpx2
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware
from mcp.shared.exceptions import MCPError
from mcp.types import CONNECTION_CLOSED, INTERNAL_ERROR, Implementation
from mcp_types.version import LATEST_MODERN_VERSION

from macos_apps_mcp import daemon
from macos_apps_mcp.notices import UNTRUSTED_NOTICE
from scripts.smoke_stream import WARNING, executions, probe_server, stdio_shim

MODES = ["legacy", LATEST_MODERN_VERSION]


class _Errors(Middleware):
    def __init__(self):
        self.errors = []

    async def on_call_tool(self, context, call_next):
        try:
            return await call_next(context)
        except Exception as error:
            self.errors.append(error)
            raise


def _causes(error):
    while error is not None:
        yield error
        error = error.__cause__


@pytest.mark.parametrize("mode", MODES)
def test_identity_audit_and_independent_shims(mode):
    with probe_server() as (root, _):
        shims = [daemon.build_shim(root / "s.sock") for _ in range(2)]

        async def go():
            ids = []
            for shim in shims:
                async with Client(
                    shim,
                    mode=mode,
                    client_info=Implementation(name="front", version="42"),
                ) as client:
                    if mode == "legacy":
                        assert await client.ping()
                    await client.list_tools()  # Must not create an audit write.
                    for arguments in ({"id": "A"}, {"id": "B", "dry_run": "false"}):
                        result = await client.call_tool("write_probe", arguments)
                        data = result.structured_content
                        assert (data["name"], data["version"]) == ("front", "42")
                        assert data["protocol"] == client.protocol_version
                        assert result.content[0].text == UNTRUSTED_NOTICE
                        assert (
                            sum(c.text == UNTRUSTED_NOTICE for c in result.content) == 1
                        )
                        ids.append(data["shim"])
            return ids

        ids = asyncio.run(go())
        assert ids[0] == ids[1] and ids[2] == ids[3] and ids[0] != ids[2]
        assert all(len(value) == 32 for value in ids)
        records = [
            json.loads(line)
            for line in (root / "macos-apps-mcp/audit.jsonl").read_text().splitlines()
        ]
        assert [r["tool"] for r in records] == ["write_probe"] * 4
        assert [r["session"] for r in records] == ids
        assert all(r["caller"] == "front 42" for r in records)
        assert [r["dry_run"] for r in records] == [True, False, True, False]
        assert records[0]["args"] == {"id": "A"}
        assert records[1]["args"] == {"id": "B", "dry_run": "false"}


def test_no_context_client_can_initialize_ping_and_call():
    with probe_server() as (root, _):
        client = daemon.build_shim(root / "s.sock").client_factory()

        async def go():
            async with client:
                assert await client.ping()
                return await client.call_tool("write_probe", {"id": "fallback"})

        data = asyncio.run(go()).structured_content
        assert (data["name"], data["version"]) == (
            daemon._SHIM_NAME,
            daemon._SHIM_VERSION,
        )
        assert data["protocol"] not in daemon.MODERN_PROTOCOL_VERSIONS
        assert data["shim"]


@pytest.mark.parametrize("mode", MODES)
def test_long_call_forwards_logs_and_progress_through_stdio_shim(mode):
    with probe_server() as (root, _):
        logs, progress = [], []

        async def log_handler(message):
            logs.append(message)

        async def progress_handler(value, total, message):
            progress.append((value, total, message))

        async def go():
            async with Client(
                stdio_shim(root),
                mode=mode,
                log_handler=log_handler,
                progress_handler=progress_handler,
            ) as client:
                result = await asyncio.wait_for(client.call_tool("slow"), 30)
                assert result.structured_content == {"ok": True}

        asyncio.run(go())
        assert any("working" in str(log.data) for log in logs)
        assert progress[-1] == (1, 1, "done")
        assert executions(root, "slow") == 1


@pytest.mark.parametrize("mode", MODES)
def test_cold_discovery_refusal_and_explicit_recovery(mode):
    with probe_server(generation="first") as (root, process):
        shim = daemon.build_shim(root / "s.sock")

        async def go():
            async with Client(shim, mode=mode) as client:
                process.kill()
                process.wait(5)
                assert (root / "s.sock").exists()  # A stale path is not readiness.
                with pytest.raises(
                    MCPError, match="Client failed to connect"
                ) as caught:
                    await asyncio.wait_for(
                        client.call_tool("doctor", raise_on_error=False), 10
                    )
                assert caught.value.error.code == INTERNAL_ERROR
                assert "Unknown tool" not in str(caught.value)
                assert WARNING not in str(caught.value)
                assert executions(root, "doctor") == 0

                with probe_server(root, generation="second"):
                    assert (root / "ready-second").read_text() == "second"
                    assert executions(root, "doctor") == 0
                    result = await asyncio.wait_for(client.call_tool("doctor"), 10)
                    assert result.structured_content == {"generation": "second"}
                    assert executions(root, "doctor") == 1

        asyncio.run(go())
        assert executions(root, "doctor") == 1


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    "listing",
    ["list_tools", "list_resources", "list_resource_templates", "list_prompts"],
)
def test_discovery_lists_preserve_connection_errors(mode, listing):
    with probe_server(generation="lists") as (root, process):
        shim = daemon.build_shim(root / "s.sock")

        async def go():
            async with Client(shim, mode=mode) as client:
                process.kill()
                process.wait(5)
                with pytest.raises(
                    MCPError, match="Client failed to connect"
                ) as caught:
                    await asyncio.wait_for(getattr(client, listing)(), 10)
                assert caught.value.error.code == INTERNAL_ERROR
                assert WARNING not in str(caught.value)

        asyncio.run(go())
        assert not (root / "calls.jsonl").exists()


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("warm", [False, True], ids=["cold", "warm"])
def test_healthy_discovery_keeps_unknown_tools_and_empty_lists(mode, warm):
    with probe_server(generation="healthy") as (root, _):
        shim = daemon.build_shim(root / "s.sock")

        async def go():
            async with Client(shim, mode=mode) as client:
                if warm:
                    assert "doctor" in {tool.name for tool in await client.list_tools()}
                result = await client.call_tool("no_such_tool", raise_on_error=False)
                assert result.is_error
                assert "Unknown tool: 'no_such_tool'" in result.content[0].text
                assert WARNING not in result.content[0].text
                assert "doctor" in {tool.name for tool in await client.list_tools()}
                assert await client.list_resources() == []
                assert await client.list_resource_templates() == []
                assert await client.list_prompts() == []

        asyncio.run(asyncio.wait_for(go(), 15))
        assert not (root / "calls.jsonl").exists()


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("kind", ["eof", "kill", "silent-kill"])
def test_abandoned_stream_warns_once_without_replaying(mode, kind):
    with probe_server() as (root, process):
        shim = daemon.build_shim(root / "s.sock")
        errors = _Errors()
        shim.add_middleware(errors)

        async def go():
            async with Client(shim, mode=mode) as client:
                await client.list_tools()
                result = await asyncio.wait_for(
                    client.call_tool(
                        "disconnect", {"kind": kind}, raise_on_error=False
                    ),
                    15,
                )
                assert result.is_error and len(result.content) == 1
                assert WARNING in result.content[0].text
                assert "audit log" in result.content[0].text
                if kind in {"kill", "silent-kill"}:
                    assert process.wait(5) == 23
                    refused = await client.call_tool("disconnect", raise_on_error=False)
                    assert refused.is_error and WARNING not in refused.content[0].text

        asyncio.run(go())
        assert executions(root, "disconnect") == 1
        assert executions(root, "discarded_result") == (1 if kind == "eof" else 0)
        causes = list(_causes(errors.errors[0]))
        assert any(
            (isinstance(cause, MCPError) and cause.error.code == CONNECTION_CLOSED)
            or isinstance(cause, httpx2.RemoteProtocolError)
            for cause in causes
        ), "upstream interrupted-response exception chain changed"


@pytest.mark.parametrize("mode", MODES)
def test_large_response_and_oversized_request(mode):
    with probe_server() as (root, _):
        shim = daemon.build_shim(root / "s.sock")
        errors = _Errors()
        shim.add_middleware(errors)

        async def go():
            async with Client(shim, mode=mode) as client:
                result = await client.call_tool("large")
                assert len(result.structured_content["result"]) == 2 * 1024 * 1024
                # The argument fits 4 MiB; the serialized envelope exceeds it.
                result = await client.call_tool(
                    "accept_text",
                    {"text": "a" * (4 * 1024 * 1024)},
                    raise_on_error=False,
                )
                assert result.is_error and WARNING not in result.content[0].text
                accepted = await client.call_tool("accept_text", {"text": "small"})
                assert accepted.data == 5

        asyncio.run(go())
        assert executions(root, "large") == 1
        assert executions(root, "accept_text") == 1  # Only the small request executed.
        assert executions(root, "http_413") == 1


@pytest.mark.parametrize(
    "cause",
    [
        MCPError(code=CONNECTION_CLOSED, message="closed"),
        httpx2.RemoteProtocolError("disconnected"),
        httpx2.ReadError("disconnected"),
        httpx2.ReadTimeout("no response"),
        httpx2.WriteError("partial request"),
        httpx2.WriteTimeout("partial request"),
    ],
)
def test_warning_preserves_cause_and_leaves_other_errors_alone(cause):
    async def go():
        mw = daemon._InterruptedToolWarning()
        error = ToolError("upstream")
        error.__cause__ = cause

        async def fail(_):
            raise error

        with pytest.raises(ToolError, match=WARNING) as caught:
            await mw.on_call_tool(None, fail)
        assert caught.value.__cause__ is error
        assert caught.value.__cause__.__cause__ is cause
        for definite in (
            ValueError("tool validation"),
            httpx2.ConnectError("refused"),
            httpx2.ConnectTimeout("not connected"),
            httpx2.PoolTimeout("no connection available"),
        ):
            error.__cause__ = definite
            with pytest.raises(ToolError) as caught:
                await mw.on_call_tool(None, fail)
            assert caught.value is error

    asyncio.run(go())
