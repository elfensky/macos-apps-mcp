import asyncio
import os
import shutil
import socket
import stat
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import uvicorn
from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.providers.proxy import FastMCPProxy
from mcp.types import Implementation

from macos_apps_mcp import audit as au
from macos_apps_mcp import daemon, registry


@pytest.fixture(autouse=True)
def _no_role_leak():
    """daemon.serve() sets MACOS_APPS_MCP_ROLE=daemon as its first act (before the
    server import), and test_serve_two_concurrent_sessions runs it in a daemon=True
    background thread. monkeypatch can't undo a write made by another thread after
    the test function returns, so without this the role leaks into every later test
    in the process (#141). Restore directly via os.environ regardless of what the
    thread did."""
    original = os.environ.get("MACOS_APPS_MCP_ROLE")
    yield
    if original is None:
        os.environ.pop("MACOS_APPS_MCP_ROLE", None)
    else:
        os.environ["MACOS_APPS_MCP_ROLE"] = original


@pytest.fixture
def sockdir():
    # AF_UNIX sun_path is ~104 bytes on macOS; pytest's default tmp_path nesting
    # exceeds it. mkdtemp at the tmp root keeps paths ~50 chars — daemon tests only.
    d = Path(tempfile.mkdtemp(prefix="mcpsock-"))
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_socket_path_env_override(sockdir, monkeypatch):
    p = sockdir / "s.sock"
    monkeypatch.setenv("MACOS_APPS_MCP_SOCKET", str(p))
    assert daemon.socket_path() == p


def test_socket_path_default_ignores_xdg_state_home(tmp_path, monkeypatch):
    # launchd agents don't inherit shell exports — the daemon (launchd), install-agent
    # (shell), and a client-spawned shim must all rendezvous at the SAME default path
    # regardless of what any one of them has in XDG_STATE_HOME.
    monkeypatch.delenv("MACOS_APPS_MCP_SOCKET", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))
    expected = (
        Path.home() / ".local" / "state" / "macos-apps-mcp" / "daemon" / "mcp.sock"
    )
    assert daemon.socket_path() == expected


def test_bind_socket_perms(sockdir):
    p = sockdir / "d" / "mcp.sock"
    s = daemon.bind_socket(p)
    try:
        assert stat.S_IMODE(p.stat().st_mode) == 0o600
        assert stat.S_IMODE(p.parent.stat().st_mode) == 0o700
    finally:
        s.close()


def test_bind_socket_live_owner_raises(sockdir):
    p = sockdir / "mcp.sock"
    s1 = daemon.bind_socket(p)
    try:
        with pytest.raises(daemon.AlreadyRunning):
            daemon.bind_socket(p)
    finally:
        s1.close()


def test_bind_socket_stale_file_rebinds(sockdir):
    p = sockdir / "mcp.sock"
    daemon.bind_socket(p).close()  # closed listener leaves a stale file
    assert p.exists()
    s = daemon.bind_socket(p)  # ECONNREFUSED probe → unlink → rebind
    try:
        c = socket.socket(socket.AF_UNIX)
        c.connect(str(p))  # proves it is live again
        c.close()
    finally:
        s.close()


def test_serve_two_concurrent_sessions(sockdir, monkeypatch):
    p = sockdir / "mcp.sock"
    monkeypatch.setenv("MACOS_APPS_MCP_SOCKET", str(p))
    t = threading.Thread(target=daemon.serve, daemon=True)
    t.start()
    for _ in range(100):  # wait for the socket
        if p.exists():
            break
        time.sleep(0.05)

    async def go():
        def transport():
            return StreamableHttpTransport(
                "http://daemon/mcp",
                httpx_client_factory=daemon._uds_client_factory(p),
            )

        async with Client(transport()) as c1, Client(transport()) as c2:
            r1, r2 = await asyncio.gather(c1.call_tool("ping"), c2.call_tool("ping"))
            assert "ok" in r1.content[0].text and "ok" in r2.content[0].text

    asyncio.run(go())


def _serve(app, path):
    """Serve `app` over a UDS the way daemon.serve() does; returns the listener."""
    s = daemon.bind_socket(path)
    config = uvicorn.Config(
        app.http_app(), fd=s.fileno(), log_level="warning", ws="none"
    )
    threading.Thread(target=uvicorn.Server(config).run, daemon=True).start()
    for _ in range(100):
        if path.exists():
            break
        time.sleep(0.05)
    return s


def test_slow_tool_returns_over_the_socket(sockdir):
    """#170: httpx's DEFAULT Timeout(5.0) applied to the response SSE stream, so a
    tool call taking longer than 5s never came back — the daemon did the work, the
    shim gave up reading, and the swallowed ReadTimeout (see the test below) turned
    that into a 1800s client hang. Device-confirmed cliff: 4.5s returned, 6s did not.
    This call MUST exceed 5s to fail on the old behaviour."""
    app = FastMCP("slowtest")

    @app.tool
    def slow() -> dict:
        time.sleep(6)  # > the old 5s cliff; a real bulk Mail pass runs for HOURS
        return {"ok": True}

    p = sockdir / "mcp.sock"
    s = _serve(app, p)

    async def go():
        async with Client(
            StreamableHttpTransport(
                "http://daemon/mcp", httpx_client_factory=daemon._uds_client_factory(p)
            )
        ) as c:
            return await asyncio.wait_for(c.call_tool("slow"), timeout=60)

    try:
        assert "ok" in asyncio.run(go()).content[0].text
    finally:
        s.close()


def test_dead_response_stream_errors_instead_of_hanging(sockdir):
    """#170 second bug: mcp swallows any error on a request's SSE stream and returns
    without answering, so the request hangs forever instead of failing. Simulated with
    a deliberately tiny client timeout — on the old behaviour this never returns."""
    daemon.fail_loud_on_dead_stream()
    app = FastMCP("deadtest")

    @app.tool
    def slow() -> dict:
        time.sleep(3)
        return {"ok": True}

    p = sockdir / "mcp.sock"
    s = _serve(app, p)

    def impatient(**kwargs):  # 0.5s read deadline → the stream dies mid-call
        kwargs.pop("transport", None)
        kwargs["timeout"] = httpx.Timeout(0.5)
        return httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(uds=str(p)), **kwargs
        )

    async def go():
        async with Client(
            StreamableHttpTransport("http://daemon/mcp", httpx_client_factory=impatient)
        ) as c:
            await asyncio.wait_for(c.call_tool("slow"), timeout=30)

    try:
        with pytest.raises(Exception) as e:  # noqa: B017 — the point is *anything* loud
            asyncio.run(go())
        assert not isinstance(e.value, TimeoutError), "hung instead of erroring"
        assert "ended without a result" in str(e.value)
    finally:
        s.close()


def test_shim_check_absent_socket_exits_2(sockdir):
    with pytest.raises(SystemExit) as e:
        daemon.shim_check(sockdir / "missing.sock")
    assert e.value.code == 2


def test_shim_check_stale_socket_exits_2(sockdir):
    p = sockdir / "mcp.sock"
    daemon.bind_socket(p).close()  # stale file, nobody listening
    with pytest.raises(SystemExit) as e:
        daemon.shim_check(p)
    assert e.value.code == 2


def test_shim_check_live_socket_passes(sockdir):
    p = sockdir / "mcp.sock"
    s = daemon.bind_socket(p)
    try:
        daemon.shim_check(p)  # no raise
    finally:
        s.close()


# --- #302: anyio's cancelled-wait InvalidStateError on UDS client loops -----------


@pytest.fixture
def rec_loop():
    """A fresh loop whose default exception handler records instead of logging; a
    custom handler is NOT set, so the factory still sees `get_exception_handler()`
    as None (#302)."""
    loop = asyncio.new_event_loop()
    seen: list[dict] = []
    loop.default_exception_handler = seen.append
    try:
        yield loop, seen
    finally:
        loop.close()


def _turn(loop, *calls):
    """Queue each (fn, *args) with call_soon, then run the loop for one turn."""
    for fn, *args in calls:
        loop.call_soon(fn, *args)
    loop.call_soon(loop.stop)
    loop.run_forever()


def test_cancelled_wait_race_is_dropped(rec_loop):
    """#302: set_result queued on a future cancelled in the same turn is logged by
    asyncio (the reproduction is real) and dropped by the handler."""
    loop, seen = rec_loop
    f = loop.create_future()
    f.cancel()
    _turn(loop, (f.set_result, None))
    assert len(seen) == 1
    assert isinstance(seen[0]["exception"], asyncio.InvalidStateError)

    seen.clear()
    loop.set_exception_handler(daemon._drop_cancelled_wait)
    g = loop.create_future()
    g.cancel()
    _turn(loop, (g.set_result, None))
    assert seen == []


@pytest.mark.parametrize("case", ["set_result_on_done", "set_exception_on_cancelled"])
def test_other_invalid_state_errors_still_log(rec_loop, case):
    """#302: only set_result on a CANCELLED future is dropped; the same
    InvalidStateError from any other handle reaches the default handler."""
    loop, seen = rec_loop
    loop.set_exception_handler(daemon._drop_cancelled_wait)
    f = loop.create_future()
    if case == "set_result_on_done":
        f.set_result(1)
        _turn(loop, (f.set_result, None))
    else:
        f.cancel()
        _turn(loop, (f.set_exception, ValueError()))
    assert len(seen) == 1
    assert isinstance(seen[0]["exception"], asyncio.InvalidStateError)


@pytest.mark.parametrize("case", ["other_exception_type", "no_handle"])
def test_crafted_contexts_pass_through(rec_loop, case):
    """#302: a non-InvalidStateError, or a context without a handle, is passed on as
    the identical dict."""
    loop, seen = rec_loop
    f = loop.create_future()
    f.cancel()
    if case == "other_exception_type":
        ctx = {
            "message": "boom",
            "exception": ValueError(),
            "handle": loop.call_soon(f.set_result, None),
        }
    else:
        ctx = {"message": "boom", "exception": asyncio.InvalidStateError()}
    daemon._drop_cancelled_wait(loop, ctx)
    assert len(seen) == 1
    assert seen[0] is ctx


def test_factory_installs_the_handler_once_per_loop(sockdir):
    """#302: the factory installs `_drop_cancelled_wait` on the running loop, and
    repeated calls leave it in place."""

    async def go():
        loop = asyncio.get_running_loop()
        assert loop.get_exception_handler() is None
        factory = daemon._uds_client_factory(sockdir / "s.sock")
        first = factory()
        second = factory()
        got = loop.get_exception_handler()
        await first.aclose()
        await second.aclose()
        return got

    assert asyncio.run(go()) is daemon._drop_cancelled_wait


def test_factory_keeps_an_existing_handler(sockdir):
    """#302: a handler the host already set on the loop is never replaced."""

    def mine(loop, context):  # pragma: no cover - never invoked
        pass

    assert mine is not daemon._drop_cancelled_wait

    async def go():
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(mine)
        client = daemon._uds_client_factory(sockdir / "s.sock")()
        got = loop.get_exception_handler()
        await client.aclose()
        return got

    assert asyncio.run(go()) is mine


def test_factory_without_a_running_loop_still_builds_the_client(sockdir):
    """#302: no running loop means nothing to install on; the client is returned."""
    client = daemon._uds_client_factory(sockdir / "s.sock")()
    assert isinstance(client, httpx.AsyncClient)


def test_shim_forwards_client_and_records_resolved_dry_run(sockdir, monkeypatch):
    """#222 tracer: front client -> FastMCPProxy(shim client factory) -> real unix
    socket -> daemon-side AuditMiddleware. The record names the REAL client (not the
    daemon's `mcp 0.1.0`), carries the shim id, and states the resolved dry_run."""

    def delete_x(id: str, dry_run: bool = True) -> dict:
        return {"id": id, "dry_run": dry_run}

    records: list[dict] = []
    monkeypatch.setattr(au, "audit_write", records.append)
    monkeypatch.setattr(au, "usage_log", lambda tool: None)
    app = FastMCP("t")
    app.add_middleware(
        au.AuditMiddleware(
            audit_verbs={"delete_x": "delete"},
            snapshot_sources={},
            dry_run_defaults={"delete_x": registry._dry_run_default(delete_x)},
        )
    )
    app.tool(delete_x)
    p = sockdir / "mcp.sock"
    s = _serve(app, p)
    transport = StreamableHttpTransport(
        "http://daemon/mcp", httpx_client_factory=daemon._uds_client_factory(p)
    )
    proxy = FastMCPProxy(
        client_factory=daemon._shim_client_factory(transport, "abc12345")
    )

    async def go():
        async with Client(
            proxy, client_info=Implementation(name="claude-code", version="2.1.9")
        ) as c:
            await asyncio.wait_for(c.call_tool("delete_x", {"id": "A"}), timeout=30)
            await asyncio.wait_for(
                c.call_tool("delete_x", {"id": "B", "dry_run": "false"}), timeout=30
            )

    try:
        asyncio.run(go())
    finally:
        s.close()
    assert len(records) == 2
    first, second = records
    assert first["op"] == "delete" and first["args"] == {"id": "A"}
    assert first["dry_run"] is True
    assert first["caller"] == "claude-code 2.1.9" and first["session"] == "abc12345"
    assert second["args"] == {"id": "B", "dry_run": "false"}
    assert second["dry_run"] is False
    assert second["caller"] == "claude-code 2.1.9"


def _factory_calls(monkeypatch, get_context, shim_id="abc12345", n=1):
    """Drive `_shim_client_factory` with `daemon.get_context` and `daemon._Client`
    patched; returns the `client_info` of each client the factory built."""
    seen = []
    monkeypatch.setattr(daemon, "get_context", get_context)
    monkeypatch.setattr(
        daemon, "_Client", lambda transport, client_info: seen.append(client_info)
    )
    f = daemon._shim_client_factory(object(), shim_id)
    for _ in range(n):
        f()
    return seen


def _context_with(client_params):
    return lambda: SimpleNamespace(session=SimpleNamespace(client_params=client_params))


def test_shim_client_factory_copies_the_client_info(monkeypatch):
    params = SimpleNamespace(
        clientInfo=Implementation(name="claude-code", version="2.1.9")
    )
    (info,) = _factory_calls(monkeypatch, _context_with(params))
    assert (info.name, info.version) == ("claude-code", "2.1.9")
    assert info.session == "abc12345"


def test_shim_client_factory_initialize_path_uses_the_shim_identity(monkeypatch):
    # proxy.py:90 — initialize runs before the front session stores client_params
    (info,) = _factory_calls(monkeypatch, _context_with(None))
    assert (info.name, info.version) == ("macos-apps-mcp-shim", "0")
    assert info.session == "abc12345"


def test_shim_client_factory_ping_path_uses_the_shim_identity(monkeypatch):
    # proxy.py:921 — ping_remote runs outside a request, so get_context() raises
    def no_context():
        raise RuntimeError("No active context found.")

    (info,) = _factory_calls(monkeypatch, no_context)
    assert (info.name, info.version) == ("macos-apps-mcp-shim", "0")
    assert info.session == "abc12345"


def test_shim_client_factory_session_is_stable_per_factory(monkeypatch):
    first, second = _factory_calls(monkeypatch, _context_with(None), n=2)
    assert first.session == second.session == "abc12345"
    (other,) = _factory_calls(monkeypatch, _context_with(None), shim_id="def67890")
    assert other.session == "def67890"
