import sqlite3

import pytest

from macos_apps_mcp import deploy
from macos_apps_mcp.errors import NativeError


def _fake_tcc(path):
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE access (service TEXT, client TEXT, auth_value INT)")
    c.executemany(
        "INSERT INTO access VALUES (?,?,?)",
        [
            ("kTCCServiceCalendar", "com.apple.Terminal", 2),
            ("kTCCServiceCalendar", "ren.lav.macos-apps-mcp", 2),
            ("kTCCServiceSystemPolicyAllFiles", "ren.lav.macos-apps-mcp", 0),
        ],
    )
    c.commit()
    c.close()


def test_grant_identities_maps_rows(tmp_path, monkeypatch):
    db = tmp_path / "TCC.db"
    _fake_tcc(db)
    monkeypatch.setattr(deploy, "_TCC_DB", db)
    # pin the system db away — on a dev Mac with FDA the REAL one is readable and
    # its rows would leak into the assertions (#123)
    monkeypatch.setattr(deploy, "_TCC_SYSTEM_DB", tmp_path / "absent-sys" / "TCC.db")
    out = deploy.grant_identities(
        ["kTCCServiceCalendar", "kTCCServiceSystemPolicyAllFiles"]
    )
    cal = out["kTCCServiceCalendar"]
    assert {"client": "ren.lav.macos-apps-mcp", "granted": True} in cal
    assert {"client": "com.apple.Terminal", "granted": True} in cal
    assert out["kTCCServiceSystemPolicyAllFiles"] == [
        {"client": "ren.lav.macos-apps-mcp", "granted": False}
    ]


def test_grant_identities_merges_system_db_fda(tmp_path, monkeypatch):
    # #123: FDA rows live ONLY in the system TCC db — the merge must surface them
    # even when the user db has no AllFiles row at all.
    user_db = tmp_path / "user.db"
    c = sqlite3.connect(user_db)
    c.execute("CREATE TABLE access (service TEXT, client TEXT, auth_value INT)")
    c.execute(
        "INSERT INTO access VALUES ('kTCCServiceCalendar','ren.lav.macos-apps-mcp',2)"
    )
    c.commit()
    c.close()
    sys_db = tmp_path / "system.db"
    c = sqlite3.connect(sys_db)
    c.execute("CREATE TABLE access (service TEXT, client TEXT, auth_value INT)")
    c.execute(
        "INSERT INTO access VALUES "
        "('kTCCServiceSystemPolicyAllFiles','ren.lav.macos-apps-mcp',2)"
    )
    c.commit()
    c.close()
    monkeypatch.setattr(deploy, "_TCC_DB", user_db)
    monkeypatch.setattr(deploy, "_TCC_SYSTEM_DB", sys_db)
    out = deploy.grant_identities()
    assert out["kTCCServiceSystemPolicyAllFiles"] == [
        {"client": "ren.lav.macos-apps-mcp", "granted": True}
    ]
    assert out["kTCCServiceCalendar"] == [
        {"client": "ren.lav.macos-apps-mcp", "granted": True}
    ]


def test_grant_identities_partial_when_one_db_unreadable(tmp_path, monkeypatch):
    db = tmp_path / "TCC.db"
    _fake_tcc(db)
    monkeypatch.setattr(deploy, "_TCC_DB", db)
    monkeypatch.setattr(deploy, "_TCC_SYSTEM_DB", tmp_path / "absent" / "TCC.db")
    out = deploy.grant_identities(["kTCCServiceCalendar"])
    assert out is not None and "kTCCServiceCalendar" in out


def test_grant_identities_unreadable_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy, "_TCC_DB", tmp_path / "absent" / "TCC.db")
    monkeypatch.setattr(deploy, "_TCC_SYSTEM_DB", tmp_path / "absent2" / "TCC.db")
    assert deploy.grant_identities() is None


def test_agent_status_maps_ints(monkeypatch):
    class FakeSvc:
        def status(self):
            return 1

    monkeypatch.setattr(deploy, "_agent_service", lambda: FakeSvc())
    assert deploy.agent_status() == "enabled"


def test_register_agent_failure_raises(monkeypatch):
    class FakeSvc:
        def registerAndReturnError_(self, _):
            return (False, "boom")

    monkeypatch.setattr(deploy, "_agent_service", lambda: FakeSvc())
    with pytest.raises(NativeError, match="boom"):
        deploy.register_agent()


def test_unregister_agent_failure_raises(monkeypatch):
    class FakeSvc:
        def unregisterAndReturnError_(self, _):
            return (False, "boom")

    monkeypatch.setattr(deploy, "_agent_service", lambda: FakeSvc())
    with pytest.raises(NativeError, match="boom"):
        deploy.unregister_agent()


def test_agent_service_outside_bundle_raises(monkeypatch):
    # off-bundle: main-bundle id is None (a bare venv). Inject it so the test doesn't
    # depend on what the host's Python reports.
    monkeypatch.setattr(deploy, "_main_bundle_id", lambda: None)
    with pytest.raises(NativeError, match="build_app.sh"):
        deploy._agent_service()


def test_agent_service_foreign_bundle_raises(monkeypatch):
    # a NON-None but foreign bundle id (e.g. the runner's org.python.python) must still
    # raise — the `is None` check missed this and reddened CI. Reproduce it.
    monkeypatch.setattr(deploy, "_main_bundle_id", lambda: "org.python.python")
    with pytest.raises(NativeError, match="build_app.sh"):
        deploy._agent_service()


def test_agent_service_our_bundle_proceeds(monkeypatch):
    # our exact bundle id passes the gate: _agent_service goes on to call SMAppService.
    # Stub the framework seam so the positive path is asserted without a real bundle.
    monkeypatch.setattr(deploy, "_main_bundle_id", lambda: deploy._BUNDLE_ID)
    import sys
    import types

    fake_sm = types.ModuleType("ServiceManagement")
    fake_sm.SMAppService = types.SimpleNamespace(
        agentServiceWithPlistName_=lambda name: ("svc", name)
    )
    monkeypatch.setitem(sys.modules, "ServiceManagement", fake_sm)
    assert deploy._agent_service() == ("svc", deploy._PLIST)


def test_install_agent_missing_app_fails_actionably(tmp_path, capsys):
    with pytest.raises(SystemExit) as e:
        deploy.install_agent(["--app", str(tmp_path / "nope.app")])
    assert e.value.code == 2
    assert "build_app.sh" in capsys.readouterr().err


def test_install_agent_orchestrates(tmp_path, monkeypatch, capsys):
    app = tmp_path / "macos-apps-mcp.app"
    (app / "Contents/MacOS").mkdir(parents=True)
    exe = app / "Contents/MacOS/macos-apps-mcp"
    exe.write_text("")
    exe.chmod(0o755)
    calls = []
    monkeypatch.setattr(deploy, "_run_bundle_role", lambda a, role: calls.append(role))
    monkeypatch.setattr(
        deploy, "_wait_for_socket", lambda timeout=30: calls.append("socket")
    )
    monkeypatch.setattr(
        deploy, "_request_grants_via_daemon", lambda: calls.append("prompts")
    )
    deploy.install_agent(["--app", str(app)])
    assert calls == ["register", "socket", "prompts"]
    out = capsys.readouterr().out
    assert "Privacy_AllFiles" in out  # FDA deep-link printed
    assert '"shim"' in out  # client config snippet
    assert '"-E"' in out  # isolation flags pinned in printed snippet


def test_allow_send_round_trip(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(
        deploy.subprocess, "run", lambda *a, **k: _Kick(1, "not registered")
    )
    deploy.allow_send([])
    assert capsys.readouterr().out.strip() == "off"
    deploy.allow_send(["mail"])
    assert "outbound: mail" in capsys.readouterr().out
    deploy.allow_send([])
    assert capsys.readouterr().out.strip() == "mail"
    deploy.allow_send(["off"])
    assert "outbound: off" in capsys.readouterr().out
    assert deploy.allow_send_file() == ""


class _Kick:
    def __init__(self, returncode, stderr):
        self.returncode, self.stderr = returncode, stderr


def test_allow_send_file_reaches_the_gate_only_under_the_daemon(tmp_path, monkeypatch):
    """The persisted toggle exists because env cannot reach the launchd daemon — a
    stdio server (and every test run) must stay driven by the env var alone."""
    from macos_apps_mcp import server

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    deploy._allow_send_file().write_text("mail")  # state_dir() creates the parent
    monkeypatch.delenv("MACOS_APPS_ALLOW_SEND", raising=False)
    monkeypatch.delenv("MACOS_APPS_READ_ONLY", raising=False)

    monkeypatch.delenv("MACOS_APPS_MCP_ROLE", raising=False)
    assert server._allow_send("mail") is False

    monkeypatch.setenv("MACOS_APPS_MCP_ROLE", "daemon")
    assert server._allow_send("mail") is True

    # READ_ONLY still wins unconditionally (#104)
    monkeypatch.setenv("MACOS_APPS_READ_ONLY", "1")
    assert server._allow_send("mail") is False
