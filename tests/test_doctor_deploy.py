from macos_apps_mcp import doctor


def test_deployment_section_stdio_graceful(monkeypatch):
    monkeypatch.delenv("MACOS_APPS_MCP_ROLE", raising=False)
    monkeypatch.delenv("MACOS_APPS_ALLOW_SEND", raising=False)
    monkeypatch.delenv("MACOS_APPS_READ_ONLY", raising=False)
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
    # #130: the gate must be OBSERVABLE — off by default, never a bare "".
    assert d["outbound"] == []
    assert "OFF" in d["outbound_note"]


def test_deployment_section_outbound_reports_enabled_adapters(monkeypatch):
    # Derived from server._allow_send, never a re-read of the raw env var (#130) — so
    # doctor can't disagree with what actually got registered.
    monkeypatch.setenv("MACOS_APPS_ALLOW_SEND", "mail")
    monkeypatch.delenv("MACOS_APPS_READ_ONLY", raising=False)
    monkeypatch.setattr("macos_apps_mcp.deploy.grant_identities", lambda: None)
    monkeypatch.setattr(
        "macos_apps_mcp.deploy.agent_status",
        lambda: (_ for _ in ()).throw(Exception("no bundle")),
    )
    d = doctor.diagnose()["deployment"]
    assert d["outbound"] == ["mail"]
    assert "mail" in d["outbound_note"]


def test_deployment_section_outbound_off_when_read_only(monkeypatch):
    # MACOS_APPS_READ_ONLY wins unconditionally over MACOS_APPS_ALLOW_SEND (#104) —
    # the outbound report must reflect that, not the raw ALLOW_SEND value.
    monkeypatch.setenv("MACOS_APPS_ALLOW_SEND", "all")
    monkeypatch.setenv("MACOS_APPS_READ_ONLY", "1")
    monkeypatch.setattr("macos_apps_mcp.deploy.grant_identities", lambda: None)
    monkeypatch.setattr(
        "macos_apps_mcp.deploy.agent_status",
        lambda: (_ for _ in ()).throw(Exception("no bundle")),
    )
    d = doctor.diagnose()["deployment"]
    assert d["outbound"] == []


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


def test_report_carries_the_serving_version(monkeypatch):
    """Which code is answering — the daemon is a different process from the repo, and
    nothing else in the report reveals when it has gone stale."""
    import tomllib
    from pathlib import Path

    from macos_apps_mcp import doctor as doc

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    assert doc._version() == tomllib.loads(pyproject.read_text())["project"]["version"]
