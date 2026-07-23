import pytest

from macos_apps_mcp import cli


def test_bare_invocation_is_stdio(monkeypatch):
    called = []
    monkeypatch.setattr("macos_apps_mcp.server.main", lambda: called.append("stdio"))
    monkeypatch.setattr("sys.argv", ["macos-apps-mcp"])
    cli.main()
    assert called == ["stdio"]


def test_daemon_role(monkeypatch):
    called = []
    monkeypatch.setattr("macos_apps_mcp.daemon.serve", lambda: called.append("daemon"))
    monkeypatch.setattr("sys.argv", ["macos-apps-mcp", "daemon"])
    cli.main()
    assert called == ["daemon"]


def test_shim_role(monkeypatch):
    called = []
    monkeypatch.setattr("macos_apps_mcp.daemon.run_shim", lambda: called.append("shim"))
    monkeypatch.setattr("sys.argv", ["macos-apps-mcp", "shim"])
    cli.main()
    assert called == ["shim"]


def test_unknown_role_exits_nonzero(monkeypatch):
    monkeypatch.setattr("sys.argv", ["macos-apps-mcp", "bogus"])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code != 0
