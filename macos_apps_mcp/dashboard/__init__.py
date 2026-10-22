"""The localhost operator dashboard (PLAT-02), served by the daemon on loopback TCP.

``daemon.serve()`` imports this lazily after a successful TCP bind, so the stdio server
never loads it. The package reads tool facts from ``registry.TOOLS`` and must not
import the FastMCP server module (``tests/test_import_layers.py``).
"""

from __future__ import annotations

from pathlib import Path

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse, RedirectResponse, Response
from starlette.routing import Route

from . import adapters, usage
from .guard import Guard

# The only files /static serves, read once at import: a bundle that lacks one fails
# here (the build's import smoke catches it), and no path is ever built from the URL.
_STATIC = {
    name: (Path(__file__).with_name(name).read_bytes(), ctype)
    for name, ctype in (
        ("dashboard.css", "text/css; charset=utf-8"),
        ("dashboard.js", "text/javascript; charset=utf-8"),
    )
}


async def _home(request):
    return RedirectResponse("/usage")  # 05-04 replaces this with the write list


async def _static(request):
    hit = _STATIC.get(request.path_params["name"])
    if hit is None:
        return PlainTextResponse("Not Found", 404)
    return Response(hit[0], media_type=hit[1])


def build_app(*, port: int, token: str, key: str | None, restart=None) -> Guard:
    """The dashboard ASGI app: every route sits behind the Guard.

    ``key`` is the page key (D-19); it lives in the Guard only and never on
    ``app.state``, because pages render ``app.state`` values and the key must never
    reach a page. ``restart`` is the daemon's hook for ``POST /restart``; a test app
    has none."""
    app = Starlette(
        routes=[
            Route("/", _home),
            Route("/usage", usage.page),
            Route("/adapters", adapters.page, methods=["GET"]),
            Route("/adapters", adapters.toggle, methods=["POST"]),
            Route("/restart", adapters.restart, methods=["POST"]),
            Route("/static/{name}", _static),
        ]
    )
    app.state.port, app.state.token = port, token  # later pages render the token
    app.state.restart = restart
    return Guard(app, port=port, token=token, key=key)
