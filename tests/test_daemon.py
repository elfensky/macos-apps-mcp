import asyncio
import os
import shutil
import socket
import stat
import tempfile
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport

from macos_apps_mcp import daemon


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
