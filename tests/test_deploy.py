import sqlite3

from macos_apps_mcp import deploy


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
