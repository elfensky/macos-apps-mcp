"""The localhost dashboard through httpx.ASGITransport: no socket, no port."""

import asyncio
import re

import httpx

from macos_apps_mcp import dashboard
from macos_apps_mcp import server as _server  # noqa: F401 — fills registry.TOOLS

PORT = 47632
TOKEN = "tok"


def _get(path, *, app=None, host=f"127.0.0.1:{PORT}"):
    """One request through the ASGI app; returns the httpx response."""

    async def go():
        transport = httpx.ASGITransport(
            app=app or dashboard.build_app(port=PORT, token=TOKEN)
        )
        async with httpx.AsyncClient(
            transport=transport, base_url=f"http://{host}"
        ) as c:
            return await c.get(path)

    return asyncio.run(go())


def test_static_assets_and_the_console_frame():
    css = _get("/static/dashboard.css")
    assert css.status_code == 200 and css.headers["content-type"].startswith("text/css")
    js = _get("/static/dashboard.js")
    assert js.status_code == 200
    assert js.headers["content-type"].startswith("text/javascript")

    page = _get("/usage")
    assert page.status_code == 200
    text = page.text
    assert '<link rel="stylesheet" href="/static/dashboard.css">' in text
    assert 'class="b-shell"' in text
    assert re.search(r'<a class="nav-item active" href="/usage"', text)
    assert "127.0.0.1 only" in text
    assert " style=" not in text and "<style" not in text and "onclick=" not in text
    assert not re.search(r"<script(?![^>]*\bsrc=)", text)
