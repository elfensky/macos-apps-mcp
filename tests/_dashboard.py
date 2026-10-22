"""The one dashboard request helper (not collected, like ``tests/_fakes.py``).

Builds the app with a fixed test page key (D-19) and sends its cookie, so a test
reads like a request from the operator's browser. A test of the keyless path passes
``cookie=False``. Requests go through ``httpx.ASGITransport`` inside ``asyncio.run``:
no socket, no port, and no read of the real key file.
"""

import asyncio

import httpx

from macos_apps_mcp import dashboard
from macos_apps_mcp.dashboard.guard import KEY_COOKIE

PORT = 47632
TOKEN = "tok"
KEY = "T3st_page_key-0123456789abcdefABCDEFGHIJKLM"  # 43 urlsafe chars; a fixed fake
HOST = f"127.0.0.1:{PORT}"
ORIGIN = f"http://{HOST}"
FORM = {"content-type": "application/x-www-form-urlencoded"}
COOKIE = f"{KEY_COOKIE}={KEY}"


def build(**overrides):
    """The dashboard app with the test token and key; ``key=None`` is overridable."""
    return dashboard.build_app(
        **{"port": PORT, "token": TOKEN, "key": KEY, **overrides}
    )


def request(
    method,
    path,
    *,
    app=None,
    host=HOST,
    headers=None,
    content=None,
    cookie=True,
):
    """One request through the ASGI app; returns the httpx response (redirects not
    followed). The page-key cookie is added unless ``cookie`` is false or ``headers``
    carries a ``cookie`` of its own."""
    headers = dict(headers or {})
    if cookie and "cookie" not in {k.lower() for k in headers}:
        headers["cookie"] = COOKIE

    async def go():
        transport = httpx.ASGITransport(app=app or build())
        async with httpx.AsyncClient(
            transport=transport, base_url=f"http://{host}"
        ) as c:
            return await c.request(method, path, headers=headers, content=content)

    return asyncio.run(go())


def get(path, **kw):
    return request("GET", path, **kw)
