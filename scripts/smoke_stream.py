"""Build smoke: ONE streamed (SSE) tool call through the shim's own transport.

Proves a streamed response comes back through the shim's transport and the #170
dead-stream wrapper (`daemon.fail_loud_on_dead_stream`). The `ctx.info`
notification is what forces the SSE response path; without it a short call can
answer as plain JSON and prove nothing.

Run it on the BUNDLE's interpreter: CI tests the `uv.lock` versions, this tests
the libraries that ship (#286 - an uncapped build shipped mcp 2, which the
wrapper does not support). Exits non-zero on any failure;
`scripts/build_app.sh` runs it and fails the build on a non-zero exit.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import threading
from pathlib import Path

import uvicorn
from fastmcp import Client, Context, FastMCP
from fastmcp.client.transports import StreamableHttpTransport

from macos_apps_mcp import daemon

daemon.fail_loud_on_dead_stream()
app = FastMCP("smoke")


@app.tool
async def slow(ctx: Context) -> dict:
    await ctx.info("working")
    await asyncio.sleep(1)
    return {"ok": True}


# /tmp, not the default temp dir: AF_UNIX sun_path is capped at 104 bytes on macOS.
with tempfile.TemporaryDirectory(dir="/tmp") as d:
    p = Path(d) / "s.sock"
    s = daemon.bind_socket(p)
    cfg = uvicorn.Config(app.http_app(), fd=s.fileno(), log_level="warning", ws="none")
    threading.Thread(target=uvicorn.Server(cfg).run, daemon=True).start()

    async def go():
        t = StreamableHttpTransport(
            "http://daemon/mcp", httpx_client_factory=daemon._uds_client_factory(p)
        )
        async with Client(t) as c:
            return await asyncio.wait_for(c.call_tool("slow"), 60)

    r = asyncio.run(go())
    if "ok" not in r.content[0].text:
        sys.exit(f"stream smoke FAILED: unexpected result {r!r}")
print("stream smoke ok")
