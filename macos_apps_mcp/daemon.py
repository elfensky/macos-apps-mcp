"""Deployment plane (#71): the launchd daemon serves the existing FastMCP server over a
unix domain socket (streamable-http), and the shim bridges a client's stdio to it via
a FastMCP proxy. The daemon OWNS the socket bind (perms + single-instance); uvicorn is
handed the fd, never the path (uvicorn's own bind would create the socket 0666)."""

from __future__ import annotations

import asyncio
import errno
import os
import socket
import sys
from dataclasses import replace
from pathlib import Path

import httpx
import uvicorn
from fastmcp import Client as _Client
from fastmcp.client.transports import StreamableHttpTransport as _HttpTransport
from fastmcp.server import create_proxy
from mcp.shared.message import SessionMessage
from mcp.types import ErrorData, JSONRPCError, JSONRPCMessage, JSONRPCResponse


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

    path = socket_path()
    s = bind_socket(path)
    try:
        # ws="none": streamable-http is POST/SSE only — skipping uvicorn's websocket
        # autodetection avoids importing the deprecated websockets.legacy stack.
        config = uvicorn.Config(
            mcp.http_app(), fd=s.fileno(), log_level="warning", ws="none"
        )
        uvicorn.Server(config).run()
    finally:
        s.close()
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


def run_shim() -> None:
    """Bridge the client's stdio to the daemon over the UDS (FastMCP proxy — the
    fork-resolved ~15-line shim). No TCC surface: this process only moves bytes."""
    path = socket_path()
    shim_check(path)
    fail_loud_on_dead_stream()
    proxy = create_proxy(
        _Client(
            _HttpTransport(
                "http://daemon/mcp", httpx_client_factory=_uds_client_factory(path)
            )
        )
    )
    proxy.run()  # stdio transport
