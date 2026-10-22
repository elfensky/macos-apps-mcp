"""Probe server for Phase 5 D-06 / D-16 (throwaway; lives under .planning/ so ruff and
pytest ignore it). Run: uv run python dispatch_server.py <uds-path>
Prints one JSON line {"port": N} when both listeners are up, then serves.
One uvicorn Server, run(sockets=[uds, tcp]), behind an ASGI dispatcher."""

from __future__ import annotations

import json
import os
import socket
import sys
import time

import uvicorn
from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

uds_path = sys.argv[1]

mcp = FastMCP("probe")


@mcp.tool
def ping() -> str:
    return "ok"


@mcp.tool
async def aslow(seconds: float = 30) -> str:
    import asyncio
    await asyncio.sleep(seconds)
    return "done"


@mcp.tool
def slow(seconds: float = 30) -> str:
    time.sleep(seconds)  # sync tool: FastMCP runs it in a worker thread
    return "done"


async def home(request):
    scope = request.scope
    return PlainTextResponse(
        f"dash client={scope.get('client')} server={scope.get('server')}"
    )


def _do_restart():
    """D-16 as amended: flags + hard-exit watchdog (a sync tool thread or the native
    worker would otherwise keep the process alive forever)."""
    import threading
    server.should_exit = True
    server.force_exit = True
    t = threading.Timer(float(os.environ.get("PROBE_WATCHDOG", "3")), os._exit, (0,))
    t.daemon = True
    t.start()


async def restart(request):
    from starlette.background import BackgroundTask
    return PlainTextResponse("restarting", background=BackgroundTask(_do_restart))


dash = Starlette(routes=[Route("/", home), Route("/restart", restart, methods=["POST"])])
mcp_app = mcp.http_app()
lifespan_events = []


async def dispatcher(scope, receive, send):
    if scope["type"] == "lifespan":
        async def spy_receive():
            m = await receive()
            lifespan_events.append(m["type"])
            return m
        return await mcp_app(scope, spy_receive, send)
    if scope["type"] != "http":
        return
    if scope.get("client") is None:  # UDS: uvicorn gives client None, server (path, None)
        return await mcp_app(scope, receive, send)
    return await dash(scope, receive, send)


us = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
us.bind(uds_path)
os.chmod(uds_path, 0o600)
us.listen()
ts = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
ts.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
ts.bind(("127.0.0.1", 0))
ts.listen()
config = uvicorn.Config(dispatcher, log_level="warning", ws="none")
server = uvicorn.Server(config)
print(json.dumps({"port": ts.getsockname()[1]}), flush=True)
t0 = None
try:
    server.run(sockets=[us, ts])
finally:
    print(json.dumps({"lifespan_events": lifespan_events}), flush=True)
    os.unlink(uds_path)
