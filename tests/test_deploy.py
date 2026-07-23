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
    out = deploy.grant_identities(
        ["kTCCServiceCalendar", "kTCCServiceSystemPolicyAllFiles"]
    )
    cal = out["kTCCServiceCalendar"]
    assert {"client": "ren.lav.macos-apps-mcp", "granted": True} in cal
    assert {"client": "com.apple.Terminal", "granted": True} in cal
    assert out["kTCCServiceSystemPolicyAllFiles"] == [
        {"client": "ren.lav.macos-apps-mcp", "granted": False}
    ]


def test_grant_identities_unreadable_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy, "_TCC_DB", tmp_path / "absent" / "TCC.db")
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


def test_agent_service_outside_bundle_raises():
    with pytest.raises(NativeError, match="build_app.sh"):
        deploy._agent_service()


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
