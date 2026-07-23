from macos_apps_mcp import doctor


def test_deployment_section_stdio_graceful(monkeypatch):
    monkeypatch.delenv("MACOS_APPS_MCP_ROLE", raising=False)
    monkeypatch.setattr("macos_apps_mcp.deploy.grant_identities", lambda: None)
    monkeypatch.setattr(
        "macos_apps_mcp.deploy.agent_status",
        lambda: (_ for _ in ()).throw(Exception("no bundle")),
    )
    d = doctor.diagnose()["deployment"]
    assert d["mode"] == "stdio"
    assert d["grant_identities"] is None
    assert "FDA" in d["note"]
    assert d["agent"].startswith("unavailable")


def test_deployment_section_daemon_mode(monkeypatch):
    monkeypatch.setenv("MACOS_APPS_MCP_ROLE", "daemon")
    monkeypatch.setattr(
        "macos_apps_mcp.deploy.grant_identities",
        lambda: {
            "kTCCServiceCalendar": [
                {"client": "ren.lav.macos-apps-mcp", "granted": True}
            ]
        },
    )
    monkeypatch.setattr("macos_apps_mcp.deploy.agent_status", lambda: "enabled")
    d = doctor.diagnose()["deployment"]
    assert d["mode"] == "daemon" and d["agent"] == "enabled"
    assert d["grant_identities"]["kTCCServiceCalendar"][0]["granted"] is True
