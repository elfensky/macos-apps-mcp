"""Exercise the actual shim with synthetic UDS tools, never native applications.

The bundle build runs this on both interpreter slices. The same server fixture
supports pytest's migration regressions. Every child and socket belongs to this
run; no installed daemon is contacted. Asyncio leaks fail the client smoke (#302).
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

import uvicorn
from fastmcp import Client, Context, FastMCP
from fastmcp.client.transports import StdioTransport
from fastmcp.server.dependencies import get_http_headers
from mcp.types import Implementation

from macos_apps_mcp import audit, daemon
from macos_apps_mcp.notices import UNTRUSTED_NOTICE, UntrustedDataNotice

WARNING = "MAY HAVE COMPLETED"


def python_command() -> list[str]:
    # Preserve the slice selected by build_app.sh when spawning a universal binary.
    prefix = (
        ["/usr/bin/arch", f"-{platform.machine()}"] if sys.platform == "darwin" else []
    )
    return [*prefix, sys.executable, "-E", "-s", "-P"]


def serve_probe(root: Path) -> None:
    """Serve only synthetic tools in a disposable child process."""
    os.environ["XDG_STATE_HOME"] = str(root)
    calls = root / "calls.jsonl"
    app = FastMCP(
        "transport-probe",
        middleware=[
            audit.AuditMiddleware({"write_probe": "delete"}, {}, {"write_probe": True}),
            UntrustedDataNotice(),
        ],
    )

    def record(tool: str) -> None:
        with calls.open("a") as out:
            out.write(json.dumps({"tool": tool}) + "\n")

    @app.tool
    async def write_probe(ctx: Context, id: str, dry_run: bool = True) -> dict:
        record("write_probe")
        info = ctx.session.client_params.client_info
        return {
            "id": id,
            "dry_run": dry_run,
            "name": info.name,
            "version": info.version,
            "protocol": ctx.request_context.protocol_version,
            "shim": get_http_headers().get(audit.SHIM_ID_HEADER),
        }

    @app.tool
    async def slow(ctx: Context) -> dict:
        record("slow")
        await ctx.info("working")
        await ctx.report_progress(0, 1, "working")
        await asyncio.sleep(6)  # Must exceed the historical five-second cliff.
        await ctx.report_progress(1, 1, "done")
        return {"ok": True}

    @app.tool
    async def large(ctx: Context) -> str:
        record("large")
        await ctx.info("large response")
        return "x" * (2 * 1024 * 1024)

    @app.tool
    async def accept_text(text: str) -> int:
        record("accept_text")
        return len(text)

    @app.tool
    async def disconnect(ctx: Context, kind: str = "eof") -> dict:
        record("disconnect")
        await ctx.info("dispatched")
        await asyncio.sleep(0.1)
        if kind == "kill":
            os._exit(23)  # This synthetic child only; never the installed daemon.
        return {"done": True}

    http_app = app.http_app()
    listener = daemon.bind_socket(root / "s.sock")
    server = uvicorn.Server(
        uvicorn.Config(
            drop_result_app(http_app, record),
            log_level="error",
            ws="none",
            access_log=False,
        )
    )
    try:
        server.run(sockets=[listener])
    finally:
        listener.close()


def drop_result_app(http_app, record):
    async def drop_result(scope, receive, send):
        # Discard only the terminal result of the synthetic EOF call. Notifications
        # and the HTTP/SSE framing still travel through the real server and socket.
        body = bytearray()
        drop = False

        async def receive_request():
            nonlocal drop
            event = await receive()
            if event["type"] == "http.request":
                body.extend(event.get("body", b""))
                if not event.get("more_body", False) and body:
                    message = json.loads(body)
                    params = message.get("params") or {}
                    drop = params.get("name") == "disconnect" and (
                        params.get("arguments", {}).get("kind", "eof") == "eof"
                    )
            return event

        async def send_response(event):
            if event.get("status") == 413:
                record("http_413")
            if drop and b'"result":' in event.get("body", b""):
                record("discarded_result")
                event = {**event, "body": b""}
            await send(event)

        await http_app(scope, receive_request, send_response)

    return drop_result


@contextmanager
def probe_server():
    """A process that owns only disposable state and a short AF_UNIX path."""
    with tempfile.TemporaryDirectory(dir="/tmp", prefix="mcp-smoke-") as directory:
        root = Path(directory)
        with (root / "server.log").open("w+") as log:
            process = subprocess.Popen(
                [
                    *python_command(),
                    str(Path(__file__).resolve()),
                    "--serve",
                    str(root),
                ],
                stdout=log,
                stderr=log,
            )
            try:
                deadline = time.monotonic() + 20
                while not (root / "s.sock").exists():
                    if process.poll() is not None or time.monotonic() > deadline:
                        log.seek(0)
                        raise RuntimeError(f"synthetic server failed: {log.read()}")
                    time.sleep(0.02)
                yield root, process
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(5)


def stdio_shim(root: Path) -> StdioTransport:
    command = python_command()
    return StdioTransport(
        command=command[0],
        args=[*command[1:], "-m", "macos_apps_mcp", "shim"],
        env={
            "MACOS_APPS_MCP_SOCKET": str(root / "s.sock"),
            "XDG_STATE_HOME": str(root),
        },
    )


def executions(root: Path, tool: str) -> int:
    path = root / "calls.jsonl"
    return sum(
        json.loads(line)["tool"] == tool
        for line in (path.read_text().splitlines() if path.exists() else [])
    )


async def exercise(root: Path, mode: str) -> None:
    """Real stdio frontend -> actual shim -> UDS -> synthetic backend."""
    logs, progress = [], []

    async def log_handler(message):
        logs.append(message)

    async def progress_handler(value, total, message):
        progress.append((value, total, message))

    async with Client(
        stdio_shim(root),
        mode=mode,
        client_info=Implementation(name="stream-smoke", version="1"),
        log_handler=log_handler,
        progress_handler=progress_handler,
    ) as client:
        if mode == "legacy":
            assert await client.ping()
        await client.list_tools()
        identity = await client.call_tool("write_probe", {"id": "synthetic"})
        data = identity.structured_content
        assert data["name"] == "stream-smoke" and data["version"] == "1"
        assert data["protocol"] == client.protocol_version and data["shim"]
        assert identity.content[0].text == UNTRUSTED_NOTICE
        result = await client.call_tool("slow")
        assert result.structured_content == {"ok": True}
        assert logs and any(item[0] == 1 for item in progress)
        result = await client.call_tool("large")
        assert len(result.structured_content["result"]) == 2 * 1024 * 1024
        result = await client.call_tool("disconnect", raise_on_error=False)
        assert result.is_error and WARNING in result.content[0].text
        assert executions(root, "disconnect") == 1
        assert executions(root, "discarded_result") == 1


def main() -> None:
    leaked = []

    async def run(root, mode):
        loop = asyncio.get_running_loop()
        original = loop.default_exception_handler

        def record(context):
            leaked.append(context)
            original(context)

        loop.default_exception_handler = record
        await asyncio.wait_for(exercise(root, mode), 60)
        # Also run the in-process proxy so its UDS loop's teardown is observable.
        async with Client(daemon.build_shim(root / "s.sock"), mode=mode) as client:
            await client.list_tools()
            result = await client.call_tool("large")
            assert len(result.structured_content["result"]) == 2 * 1024 * 1024
            result = await asyncio.wait_for(
                client.call_tool("disconnect", raise_on_error=False), 15
            )
            assert result.is_error and WARNING in result.content[0].text
            assert executions(root, "disconnect") == 2  # One per explicit call.

    for mode in ("legacy", "auto"):
        with probe_server() as (root, _process):
            asyncio.run(run(root, mode))
    if leaked:
        raise AssertionError(f"stream smoke FAILED: {len(leaked)} asyncio leaks (#302)")
    print(
        "stream smoke ok: legacy + modern, notifications, "
        "large response, EOF, no replay"
    )


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--serve":
        serve_probe(Path(sys.argv[2]))
    else:
        main()
