"""The localhost operator dashboard (PLAT-02), served by the daemon on loopback TCP.

``daemon.serve()`` imports this lazily after a successful TCP bind, so the stdio server
never loads it. The package reads tool facts from ``registry.TOOLS`` and must not
import the FastMCP server module (``tests/test_import_layers.py``).
"""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.responses import RedirectResponse
from starlette.routing import Route

from . import usage
from .guard import Guard


async def _home(request):
    return RedirectResponse("/usage")  # 05-04 replaces this with the write list


def build_app(*, port: int, token: str) -> Guard:
    """The dashboard ASGI app: every route sits behind the Guard."""
    app = Starlette(
        routes=[
            Route("/", _home),
            Route("/usage", usage.page),
        ]
    )
    app.state.port, app.state.token = port, token  # later pages render the token
    return Guard(app, port=port, token=token)
