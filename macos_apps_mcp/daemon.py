"""Deployment plane (#71): the launchd daemon serves the existing FastMCP server over a
unix domain socket (streamable-http), and the shim bridges a client's stdio to it via
a FastMCP proxy. The daemon OWNS the socket bind (perms + single-instance); uvicorn is
handed the sockets, never a path (uvicorn's own bind would create the socket 0666)."""

from __future__ import annotations

import asyncio
import errno
import ipaddress
import logging
import os
import secrets
import socket
import sys
import threading
import uuid
from dataclasses import replace
from pathlib import Path

import httpx
import uvicorn
from fastmcp import Client as _Client
from fastmcp.client.transports import StreamableHttpTransport as _HttpTransport
from fastmcp.server.dependencies import get_context
from fastmcp.server.providers.proxy import FastMCPProxy
from mcp.shared.message import SessionMessage
from mcp.types import (
    ErrorData,
    Implementation,
    JSONRPCError,
    JSONRPCMessage,
    JSONRPCResponse,
)

log = logging.getLogger(__name__)

DASHBOARD_HOST = "127.0.0.1"
# Tests set this to 0 (an ephemeral port); no override exists for the daemon itself.
DASHBOARD_PORT = 47632
# `http://127.0.0.1:<port>` or `not bound: <reason>`, set by serve() and read by doctor.
dashboard_state: str | None = None


class AlreadyRunning(Exception):
    """A live daemon already owns the socket."""


# Home-relative, NOT via audit.state_dir(): three processes must agree on this path —
# the launchd daemon (no shell env at all), the shell-invoked install-agent, and a
# client-spawned shim (whatever env the client passes) — and XDG_STATE_HOME is not
# guaranteed identical across those three. Rooting the default here instead of on
# state_dir()'s XDG_STATE_HOME lookup keeps the rendezvous point stable regardless of
# what any one of them has exported.
_DEFAULT_SOCKET_DIR = Path.home() / ".local" / "state" / "macos-apps-mcp" / "daemon"


def socket_path() -> Path:
    override = os.environ.get("MACOS_APPS_MCP_SOCKET")
    if override:
        return Path(override)
    _DEFAULT_SOCKET_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    return _DEFAULT_SOCKET_DIR / "mcp.sock"


def bind_socket(path: Path) -> socket.socket:
    """Bind+listen the daemon socket with single-instance semantics (spec §D):
    EADDRINUSE → connect-probe; live owner → AlreadyRunning; refused → stale file
    from a crash → unlink + rebind. File 0600, parent 0700."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.bind(str(path))
    except OSError as e:
        if e.errno != errno.EADDRINUSE:
            s.close()
            raise
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            probe.connect(str(path))
        except (ConnectionRefusedError, FileNotFoundError):
            path.unlink(missing_ok=True)  # stale — crashed owner never unlinked
            s.bind(str(path))
        else:
            s.close()
            raise AlreadyRunning(f"a daemon already owns {path}") from e
        finally:
            probe.close()
    os.chmod(path, 0o600)
    s.listen()
    return s


def assert_loopback(host: str) -> str:
    """Return ``host`` when it is a literal loopback IP; raise ``ValueError`` otherwise.
    A name such as ``localhost`` is refused too: a name can be re-pointed, a literal
    cannot (PLAT-02 criterion 4)."""
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    if not loopback:
        raise ValueError(f"dashboard refuses to bind {host!r}: not a loopback address")
    return host


def bind_dashboard(host: str, port: int) -> socket.socket:
    """Bind+listen the dashboard TCP socket on a loopback address (the `bind_socket`
    shape). SO_REUSEADDR lets a relaunch after a hard exit meet TIME_WAIT."""
    assert_loopback(host)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host, port))
        s.listen()
    except OSError:
        s.close()
        raise
    return s


def _not_found_app():
    async def app(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 404,
                "headers": [(b"content-type", b"text/plain; charset=utf-8")],
            }
        )
        await send({"type": "http.response.body", "body": b"Not Found"})

    return app


def make_dispatcher(mcp_app, dash_app):
    """One ASGI entry for the one uvicorn Server that listens on both sockets.
    MCP is reachable only on the UDS: lifespan and scopes whose ``server`` is
    ``(path, None)``. Everything else HTTP goes to the dashboard, or 404 when there is
    none. Fail closed (RESEARCH C4): uvicorn can report ``client`` as None on a racing
    TCP reset, so ``client`` is not the discriminator; ``server[1]`` is."""
    dash_app = dash_app or _not_found_app()

    async def dispatcher(scope, receive, send):
        if scope["type"] == "lifespan":
            return await mcp_app(scope, receive, send)  # one startup, one shutdown
        if scope["type"] != "http":
            return  # ws="none"; nothing else is served
        server = scope.get("server")
        if isinstance(server, tuple | list) and len(server) == 2 and server[1] is None:
            return await mcp_app(scope, receive, send)
        return await dash_app(scope, receive, send)

    return dispatcher


# #170: httpx defaults to Timeout(5.0) on ALL four phases, so the shim gave up reading
# the response SSE stream 5s after the POST — device-confirmed cliff: a 4.5s tool call
# returned, a 6s one did not. A tool call's duration is the *daemon's* business (a bulk
# Mail pass is HOURS: a `whose` lookup is an O(mailbox) scan), and this hop is a local
# unix socket with no network to time out on, so the read has no deadline at all. Only
# connect keeps one — the daemon must accept promptly or say why it cannot.
_UDS_TIMEOUT = httpx.Timeout(None, connect=10.0)


def _drop_cancelled_wait(loop, context):
    """asyncio exception handler that drops ONE benign teardown race (#302) and hands
    every other context to `loop.default_exception_handler`.

    anyio's UNIX socket stream registers the bare `Future.set_result` as the selector
    callback and removes it one loop turn later. A wait cancelled in the same turn in
    which the socket becomes ready makes asyncio log `InvalidStateError` for a future
    nothing awaits, so no result changes; upstream anyio fixed only the `aclose()`
    variant.

    A handler, not a patch of anyio's private I/O methods: anyio is uncapped, so an
    override could silently diverge from a future anyio. This changes logging only,
    and goes inert once anyio guards the callback. It drops only when the exception is
    an `InvalidStateError` raised by the bound `set_result` of a CANCELLED
    `asyncio.Future`."""
    callback = getattr(context.get("handle"), "_callback", None)
    future = getattr(callback, "__self__", None)
    if (
        isinstance(context.get("exception"), asyncio.InvalidStateError)
        and getattr(callback, "__name__", None) == "set_result"
        and isinstance(future, asyncio.Future)
        and future.cancelled()
    ):
        return
    loop.default_exception_handler(context)


def _uds_client_factory(path: Path):
    """httpx AsyncClient factory routing all requests over the unix socket. The URL
    host is a dummy — never resolved. It also installs `_drop_cancelled_wait` on the
    client's running loop, unless the loop already has a handler (#302)."""

    def factory(**kwargs):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # no running loop: nothing to install on
            pass
        else:
            if loop.get_exception_handler() is None:
                loop.set_exception_handler(_drop_cancelled_wait)
        kwargs.pop("transport", None)
        kwargs["timeout"] = _UDS_TIMEOUT
        return httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(uds=str(path)), **kwargs
        )

    return factory


class _WatchedWriter:
    """Read-stream writer that remembers whether a JSON-RPC *answer* went through it
    (progress notifications on the same stream don't count)."""

    def __init__(self, inner):
        self._inner = inner
        self.answered = False

    async def send(self, item) -> None:
        root = getattr(getattr(item, "message", None), "root", None)
        if isinstance(root, JSONRPCResponse | JSONRPCError):
            self.answered = True
        await self._inner.send(item)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def fail_loud_on_dead_stream() -> None:
    """#170, second bug: mcp's StreamableHTTPTransport catches EVERY error on a
    request's SSE stream, logs it at DEBUG (`SSE stream ended: …`) and returns without
    answering — so the caller waits forever on a request that will never come back,
    indistinguishable from a hang. That is what turned a 5s timeout into a 1800s
    client abort. Answer the dead stream with a JSON-RPC error instead: loud, and
    pointing at the record that says whether the work actually happened.

    Written against mcp 1.x; mcp 2 changed `_handle_sse_response` and
    `JSONRPCMessage`, so `pyproject.toml` caps mcp below 2 and the build's stream
    smoke catches drift (#286)."""
    from mcp.client import streamable_http

    original = streamable_http.StreamableHTTPTransport._handle_sse_response

    async def _handle_sse_response(self, response, ctx, is_initialization=False):
        watched = _WatchedWriter(ctx.read_stream_writer)
        await original(
            self, response, replace(ctx, read_stream_writer=watched), is_initialization
        )
        request_id = getattr(ctx.session_message.message.root, "id", None)
        if watched.answered or request_id is None:  # answered, or a notification
            return
        await ctx.read_stream_writer.send(
            SessionMessage(
                JSONRPCMessage(
                    JSONRPCError(
                        jsonrpc="2.0",
                        id=request_id,
                        error=ErrorData(
                            code=-32001,
                            message="daemon response stream ended without a result — "
                            "the operation may have COMPLETED; check the audit log "
                            "before retrying anything destructive",
                        ),
                    )
                )
            )
        )

    streamable_http.StreamableHTTPTransport._handle_sse_response = _handle_sse_response


_restart_armed = (
    False  # one watchdog per process: a second restart only repeats the first
)


def restart(server, *, timer=threading.Timer, delay: float = 3.0) -> bool:
    """Make this daemon exit so launchd starts it again (D-16): the dashboard's restart.

    Sets uvicorn's ``should_exit`` and ``force_exit`` (the Server skips the wait for
    open connections and tasks) and arms a watchdog that calls ``os._exit(0)`` after
    ``delay`` seconds. The watchdog exists because a sync tool thread, or the native
    worker (a non-daemon thread ``concurrent.futures`` joins at exit), keeps the process
    alive forever otherwise (RESEARCH C2). ``os._exit`` skips ``serve()``'s ``finally``;
    ``bind_socket`` removes the stale socket file on the next start. launchd's
    ``KeepAlive`` relaunches the exited daemon: nothing here runs ``launchctl``.
    Returns False when a restart is already under way."""
    global _restart_armed
    if _restart_armed:
        return False
    _restart_armed = True
    server.should_exit = True
    server.force_exit = True
    watchdog = timer(delay, os._exit, (0,))
    watchdog.daemon = True
    watchdog.start()
    return True


def serve() -> None:
    """Run the FastMCP server as the daemon: streamable-http over the owned UDS.
    One MCP session per client connection (fork resolution, spec)."""
    os.environ["MACOS_APPS_MCP_ROLE"] = (
        # Registration already ran when the package was first imported, and the
        # outbound gate reads argv (deploy.is_daemon_role()), not this variable —
        # setting it here is for embedders/tests only, not the gate itself.
        "daemon"
    )
    from .server import mcp  # late: importing server pulls the adapter tree

    global dashboard_state
    path = socket_path()
    s = bind_socket(path)
    tcp = None
    try:
        try:
            tcp = bind_dashboard(DASHBOARD_HOST, DASHBOARD_PORT)  # read at call time
        except OSError as e:  # a taken port must not take MCP down (T-05-13)
            log.warning("dashboard not bound: %s", e)
            dashboard_state = f"not bound: {e}"
        dash_app = None
        if tcp is not None:
            port = tcp.getsockname()[1]
            dashboard_state = f"http://{DASHBOARD_HOST}:{port}"
            from . import dashboard, deploy  # late: the stdio server never imports it

            dash_app = dashboard.build_app(
                port=port,
                token=secrets.token_urlsafe(32),
                key=deploy.dashboard_key(create=True),
                restart=lambda: restart(server),  # `server` is assigned below
            )
        # ws="none": streamable-http is POST/SSE only — skipping uvicorn's websocket
        # autodetection avoids importing the deprecated websockets.legacy stack.
        # One Server for both sockets: two Servers on one loop overwrite each other's
        # SIGTERM handler. Proxy headers stay off: none may rewrite client or server.
        config = uvicorn.Config(
            make_dispatcher(mcp.http_app(), dash_app),
            log_level="warning",
            ws="none",
            proxy_headers=False,
            # the link's query string carries the page key, and an access line prints it
            access_log=False,
        )
        server = uvicorn.Server(config)
        server.run(sockets=[s] + ([tcp] if tcp else []))
    finally:
        s.close()
        if tcp is not None:
            tcp.close()
        path.unlink(missing_ok=True)


def shim_check(path: Path) -> None:
    """Fail FAST when no daemon is serving — a hanging shim looks like a wedged
    client (spec §C). One actionable stderr line, exit 2."""
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.connect(str(path))
    except OSError:
        print(
            f"macos-apps-mcp: daemon not running (no socket at {path}) — "
            "run `macos-apps-mcp install-agent`",
            file=sys.stderr,
        )
        raise SystemExit(2) from None
    finally:
        probe.close()


_SHIM_NAME = "macos-apps-mcp-shim"
_SHIM_VERSION = "0"


def _shim_client_factory(transport, shim_id: str):
    """The proxy's per-request client factory (#222): each upstream client carries the
    REAL client's ``clientInfo`` (name, version) plus ``shim_id`` as an extra field, so
    the daemon's audit record names who called and which shim carried it. Without it
    the daemon saw ``mcp 0.1.0`` and a new session on every call.

    Two paths have no client params and use the fixed shim identity: ``initialize``
    (``proxy.py:90`` — the front client's params are not stored yet) and ``ping``
    (``proxy.py:921`` — ``get_context()`` raises outside a request)."""

    def f():
        try:
            info = get_context().session.client_params.clientInfo
            name, version = info.name, info.version
        except Exception:  # noqa: BLE001 — either fallback path above
            name, version = _SHIM_NAME, _SHIM_VERSION
        return _Client(
            transport,
            client_info=Implementation(name=name, version=version, session=shim_id),
        )

    return f


def run_shim() -> None:
    """Bridge the client's stdio to the daemon over the UDS (FastMCP proxy — the
    fork-resolved ~15-line shim). No TCC surface: this process only moves bytes."""
    path = socket_path()
    shim_check(path)
    fail_loud_on_dead_stream()
    transport = _HttpTransport(
        "http://daemon/mcp", httpx_client_factory=_uds_client_factory(path)
    )
    shim_id = uuid.uuid4().hex[:8]  # once per shim process
    proxy = FastMCPProxy(client_factory=_shim_client_factory(transport, shim_id))
    proxy.run()  # stdio transport
