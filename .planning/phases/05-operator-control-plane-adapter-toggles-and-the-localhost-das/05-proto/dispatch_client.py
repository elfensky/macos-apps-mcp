"""Client half of the D-06 / D-16 probe. Run: uv run python dispatch_client.py"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

HERE = Path(__file__).parent


def uds_factory(path):
    def f(**kw):
        kw.pop("transport", None)
        kw["timeout"] = httpx.Timeout(None, connect=10.0)
        return httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=str(path)), **kw)
    return f


async def main(mode: str):
    d = Path(tempfile.mkdtemp(prefix="p5-"))
    uds = d / "s.sock"
    proc = subprocess.Popen(
        [sys.executable, str(HERE / "dispatch_server.py"), str(uds)],
        stdout=subprocess.PIPE, text=True,
    )
    port = json.loads(proc.stdout.readline())["port"]
    base = f"http://127.0.0.1:{port}"
    async with httpx.AsyncClient() as h:
        r = await h.get(base + "/")
        print("TCP GET /      ->", r.status_code, r.text)
        r = await h.post(base + "/mcp", json={})
        print("TCP POST /mcp  ->", r.status_code, repr(r.text[:40]))
    transport = StreamableHttpTransport("http://daemon/mcp", httpx_client_factory=uds_factory(uds))
    async with Client(transport) as c:
        print("UDS ping       ->", (await c.call_tool("ping")).content[0].text)
        inflight = None
        if mode in ("inflight", "inflight-async"):
            tool = "slow" if mode == "inflight" else "aslow"
            inflight = asyncio.create_task(c.call_tool(tool, {"seconds": 40}, timeout=90))
            await asyncio.sleep(1)
        t0 = time.monotonic()
        async with httpx.AsyncClient() as h:
            r = await h.post(base + "/restart")
            print("TCP POST /restart ->", r.status_code, r.text)
        try:
            await asyncio.to_thread(proc.wait, 20)
            print(f"exit code {proc.returncode} after {time.monotonic()-t0:.2f}s (mode={mode})")
        except subprocess.TimeoutExpired:
            print(f"STILL RUNNING after 20s (mode={mode}) -> killing")
            proc.kill()
        out = proc.stdout.read()
        print("server tail:", out.strip())
        if inflight:
            inflight.cancel()


asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "idle"))
