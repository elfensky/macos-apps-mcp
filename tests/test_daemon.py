import asyncio
import shutil
import socket
import stat
import tempfile
import threading
import time
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from macos_apps_mcp import daemon


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
