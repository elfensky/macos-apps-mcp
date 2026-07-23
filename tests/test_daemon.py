import socket
import stat

import pytest

from macos_apps_mcp import daemon


def test_socket_path_env_override(tmp_path, monkeypatch):
    p = tmp_path / "s.sock"
    monkeypatch.setenv("MACOS_APPS_MCP_SOCKET", str(p))
    assert daemon.socket_path() == p


def test_bind_socket_perms(tmp_path):
    p = tmp_path / "d" / "mcp.sock"
    s = daemon.bind_socket(p)
    try:
        assert stat.S_IMODE(p.stat().st_mode) == 0o600
        assert stat.S_IMODE(p.parent.stat().st_mode) == 0o700
    finally:
        s.close()


def test_bind_socket_live_owner_raises(tmp_path):
    p = tmp_path / "mcp.sock"
    s1 = daemon.bind_socket(p)
    try:
        with pytest.raises(daemon.AlreadyRunning):
            daemon.bind_socket(p)
    finally:
        s1.close()


def test_bind_socket_stale_file_rebinds(tmp_path):
    p = tmp_path / "mcp.sock"
    daemon.bind_socket(p).close()  # closed listener leaves a stale file
    assert p.exists()
    s = daemon.bind_socket(p)  # ECONNREFUSED probe → unlink → rebind
    try:
        c = socket.socket(socket.AF_UNIX)
        c.connect(str(p))  # proves it is live again
        c.close()
    finally:
        s.close()
