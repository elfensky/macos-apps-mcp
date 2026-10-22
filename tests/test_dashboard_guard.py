"""The localhost dashboard through httpx.ASGITransport: no socket, no port."""

import asyncio
import json
import re
from urllib.parse import parse_qs

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from macos_apps_mcp import audit, dashboard
from macos_apps_mcp import server as _server  # noqa: F401 — fills registry.TOOLS
from macos_apps_mcp.dashboard.guard import Guard

PORT = 47632
TOKEN = "tok"
HOST = f"127.0.0.1:{PORT}"
ORIGIN = f"http://{HOST}"
FORM = {"content-type": "application/x-www-form-urlencoded"}
SECURITY_HEADERS = {
    "content-security-policy": (
        "default-src 'self'; frame-ancestors 'none'; form-action 'self'"
    ),
    "x-frame-options": "DENY",
    "x-content-type-options": "nosniff",
    "referrer-policy": "same-origin",
    "cache-control": "no-store",
}


def _request(method, path, *, app=None, host=HOST, headers=None, content=None):
    """One request through the ASGI app (no socket); returns the httpx response."""

    async def go():
        transport = httpx.ASGITransport(
            app=app or dashboard.build_app(port=PORT, token=TOKEN)
        )
        async with httpx.AsyncClient(
            transport=transport, base_url=f"http://{host}"
        ) as c:
            return await c.request(method, path, headers=headers, content=content)

    return asyncio.run(go())


def _get(path, **kw):
    return _request("GET", path, **kw)


async def _echo(request):
    form = parse_qs((await request.body()).decode())
    return PlainTextResponse(form.get("adapter", ["-"])[0])


def _echo_app():
    """A POST-only app behind a real Guard: proves the replayed body reaches a route."""
    return Guard(
        Starlette(routes=[Route("/echo", _echo, methods=["POST"])]),
        port=PORT,
        token=TOKEN,
    )


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


@pytest.mark.parametrize("host", ["evil.example", "evil.example:47632", "127.0.0.1:1"])
def test_foreign_host_is_refused_on_every_route_and_method(host):
    for method, path in (
        ("GET", "/usage"),
        ("GET", "/static/dashboard.css"),
        ("POST", "/usage"),
    ):
        headers = {"origin": ORIGIN, **FORM} if method == "POST" else None
        r = _request(method, path, host=host, headers=headers, content="token=tok")
        assert r.status_code == 400, (method, path, host)


@pytest.mark.parametrize("host", [HOST, f"localhost:{PORT}"])
def test_loopback_host_with_the_port_is_served(host):
    assert _get("/usage", host=host).status_code == 200


@pytest.mark.parametrize(
    ("extra", "want"),
    [
        ({"origin": "https://evil.example"}, 403),
        ({"origin": "http://127.0.0.1:1"}, 403),
        ({}, 403),  # no Origin and no Sec-Fetch-Site
        ({"sec-fetch-site": "cross-site"}, 403),
        ({"sec-fetch-site": "same-site"}, 403),
        ({"origin": ORIGIN}, 200),
        ({"origin": f"http://localhost:{PORT}"}, 200),
        ({"sec-fetch-site": "same-origin"}, 200),  # no Origin, same-origin fetch
    ],
)
def test_post_origin_matrix(extra, want):
    r = _request(
        "POST",
        "/echo",
        app=_echo_app(),
        headers={**FORM, **extra},
        content="token=tok&adapter=photos",
    )
    assert r.status_code == want
    if want == 200:
        assert r.text == "photos"  # the body the Guard read was replayed


def test_post_origin_null_refused():
    """RESEARCH C1: `Origin: null` is what Chrome sends for a same-origin form POST
    under `Referrer-Policy: no-referrer`; it is foreign here, and the page sends
    `same-origin` so a real post carries the real Origin."""
    r = _request(
        "POST",
        "/echo",
        app=_echo_app(),
        headers={**FORM, "origin": "null", "sec-fetch-site": "same-origin"},
        content="token=tok",
    )
    assert r.status_code == 403
    assert "Forbidden origin" in r.text


@pytest.mark.parametrize(
    "content",
    [
        "adapter=photos",  # no token
        "token=bad&adapter=photos",
        "token=tok&x=" + "a" * (9 * 1024),  # over the 8 KiB cap, token correct
    ],
)
def test_post_token_and_body_cap(content):
    r = _request(
        "POST",
        "/echo",
        app=_echo_app(),
        headers={**FORM, "origin": ORIGIN},
        content=content,
    )
    assert r.status_code == 403


def test_stale_token_says_to_reload():
    r = _request(
        "POST",
        "/echo",
        app=_echo_app(),
        headers={**FORM, "origin": ORIGIN},
        content="token=old",
    )
    assert r.status_code == 403 and "Reload" in r.text


def test_client_gone_mid_body_never_reaches_the_handler():
    """A form cut short by a disconnect must not run as if it were complete: the
    valid token and the first field arrive, then the client goes away."""
    ran = []

    async def inner(scope, receive, send):
        ran.append(scope["path"])

    msgs = iter(
        [
            {
                "type": "http.request",
                "body": b"token=tok&adapter=photos",
                "more_body": True,
            },
            {"type": "http.disconnect"},
        ]
    )

    async def receive():
        return next(msgs)

    async def send(msg):
        pass

    headers = {"host": HOST, "origin": ORIGIN, **FORM}
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/echo",
        "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
    }
    asyncio.run(Guard(inner, port=PORT, token=TOKEN)(scope, receive, send))
    assert ran == []


def test_mcp_is_not_a_dashboard_route():
    assert _get("/mcp").status_code == 404
    guarded = _request(
        "POST", "/mcp", headers={**FORM, "origin": ORIGIN}, content=f"token={TOKEN}"
    )
    assert guarded.status_code == 404
    unsigned = _request("POST", "/mcp", content="{}")
    assert unsigned.status_code == 403
    assert "Forbidden origin" in unsigned.text


def test_security_headers_on_200_400_403_404():
    responses = [
        _get("/usage"),  # 200
        _get("/usage", host="evil.example"),  # 400
        _request("POST", "/usage", content="{}"),  # 403
        _get("/nope"),  # 404
    ]
    assert [r.status_code for r in responses] == [200, 400, 403, 404]
    for r in responses:
        for name, value in SECURITY_HEADERS.items():
            assert r.headers[name] == value, (r.status_code, name)


def test_usage_escapes_tool_names(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    lines = [
        {"ts": "2026-01-01T00:00:00", "tool": "<script>alert(1)</script>"},
        {"ts": "2026-01-01T00:00:01", "tool": '" onmouseover="x'},
    ]
    audit._usage_path().write_text("\n".join(json.dumps(r) for r in lines) + "\n")
    text = _get("/usage").text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in text
    assert "&quot; onmouseover=&quot;x" in text
    assert "<script>alert(1)" not in text
    assert '" onmouseover="x' not in text


@pytest.mark.parametrize(
    "path",
    [
        "/static/nope.css",
        "/static/../dashboard.py",
        "/static/%2e%2e%2fdashboard.py",
        "/static/dashboard.css%00",
        "/static/",
    ],
)
def test_static_allow_list_has_two_entries_and_no_traversal(path):
    assert _get(path).status_code == 404


@pytest.mark.parametrize("method", ["PUT", "DELETE", "PATCH"])
def test_every_unsafe_method_needs_origin_and_token(method):
    """The Guard checks by method class, so a future non-POST route is born guarded."""
    r = _request(method, "/usage", headers={"origin": "https://evil.example"})
    assert r.status_code == 403
