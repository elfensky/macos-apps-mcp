"""FIX-27 (#568) prototype: read the running daemon's version and build over the unix
socket with a plain HTTP GET, with no MCP session, no tool call and no native worker.

Run from the repo root:  uv run python <this file>

Hermetic: every socket lives in a fresh temp folder. No launchd, no real daemon, no
native call. It answers four questions:

1. Does a ``custom_route`` on the FastMCP app answer on the UDS through
   ``daemon.make_dispatcher`` (the daemon's real ASGI entry)?
2. What does a daemon WITHOUT the route (every release up to 0.16.1) answer?
3. Does the route answer while a sync tool holds a worker thread for seconds?
4. What does a client see on a socket file that nothing listens on (the state right
   after ``launchctl kickstart -k``)?
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import threading
import time
from pathlib import Path

import httpx2
import uvicorn
from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from starlette.responses import JSONResponse

from macos_apps_mcp import daemon


def serve(app: FastMCP, path: Path):
    """Serve like daemon.serve(): one uvicorn Server, the dispatcher, the owned UDS."""
    s = daemon.bind_socket(path)
    config = uvicorn.Config(
        daemon.make_dispatcher(app.http_app(), None),
        log_level="warning",
        ws="none",
        proxy_headers=False,
        access_log=False,
    )
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, kwargs={"sockets": [s]}, daemon=True).start()
    for _ in range(100):
        try:
            read_identity(path, timeout=0.2)
            break
        except httpx2.TransportError:
            time.sleep(0.05)
    return s, server


def read_identity(path: Path, timeout: float = 2.0):
    """``(status, body)`` of GET /identity over the socket. The sync twin of
    ``daemon._uds_client_factory``: the same library, the same ``uds=`` transport."""
    with httpx2.Client(
        transport=httpx2.HTTPTransport(uds=str(path)), timeout=timeout
    ) as client:
        answer = client.get("http://daemon/identity")
    return answer.status_code, answer.text


def main() -> None:
    with tempfile.TemporaryDirectory(dir="/tmp", prefix="p0512-") as tmp:
        root = Path(tmp)

        new = FastMCP("new-daemon")

        @new.custom_route("/identity", methods=["GET"], include_in_schema=False)
        async def identity(request):
            return JSONResponse({"version": "9.9.9", "build": "abc1234 2026-11-20T00:00:00Z"})

        @new.tool
        def slow() -> str:
            time.sleep(3)
            return "done"

        s_new, _ = serve(new, root / "new.sock")
        status, body = read_identity(root / "new.sock")
        print("1. route on the UDS:", status, json.loads(body))

        old = FastMCP("old-daemon")
        s_old, _ = serve(old, root / "old.sock")
        print("2. a daemon without the route:", read_identity(root / "old.sock")[0])

        async def call_slow():
            transport = StreamableHttpTransport(
                "http://daemon/mcp",
                httpx_client_factory=daemon._uds_client_factory(root / "new.sock"),
            )
            async with Client(transport) as c:
                return (await c.call_tool("slow")).content[0].text

        result: list = []
        t = threading.Thread(target=lambda: result.append(asyncio.run(call_slow())))
        t.start()
        time.sleep(1.0)  # the tool is running now
        started = time.perf_counter()
        status, _ = read_identity(root / "new.sock")
        print(
            f"3. route during a running tool: {status} in "
            f"{(time.perf_counter() - started) * 1000:.0f} ms"
        )
        t.join()
        print("   the tool then answered:", result)

        # 4. a stale socket file: bind, then close without unlinking (a killed daemon)
        import socket

        stale = root / "stale.sock"
        dead = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        dead.bind(str(stale))
        dead.close()
        try:
            read_identity(stale)
        except httpx2.TransportError as e:
            print("4. stale socket file (exists:", stale.exists(), "):", type(e).__name__, e)
        try:
            read_identity(root / "absent.sock")
        except httpx2.TransportError as e:
            print("   absent socket file:", type(e).__name__, e)
        s_new.close()
        s_old.close()


if __name__ == "__main__":
    main()
