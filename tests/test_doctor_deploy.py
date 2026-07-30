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


def test_deployment_section_outbound_pending_when_configured_not_registered(
    monkeypatch,
):
    # C6: registration happened at import (gate off in this test process), so setting
    # ALLOW_SEND now can NOT retroactively register send tools. doctor must report the
    # REGISTERED truth (off) plus the configured-but-not-live delta as outbound_pending
    # with a restart directive — never claim sending is ON while the daemon serves no
    # send tools (the `allow-send` + failed-kickstart branch, deploy.py).
    monkeypatch.setenv("MACOS_APPS_ALLOW_SEND", "mail")
    monkeypatch.delenv("MACOS_APPS_READ_ONLY", raising=False)
    monkeypatch.setattr("macos_apps_mcp.deploy.grant_identities", lambda: None)
    monkeypatch.setattr(
        "macos_apps_mcp.deploy.agent_status",
        lambda: (_ for _ in ()).throw(Exception("no bundle")),
    )
    d = doctor.diagnose()["deployment"]
    assert d["outbound"] == []  # what actually got registered at import
    assert d["outbound_pending"] == ["mail"]  # what the config now asks for
    assert "restart" in d["outbound_note"].lower()


def test_deployment_section_outbound_off_when_read_only(monkeypatch):
    # MACOS_APPS_READ_ONLY wins unconditionally over MACOS_APPS_ALLOW_SEND (#104) —
    # the outbound report must reflect that, not the raw ALLOW_SEND value; and with
    # nothing configured there is no pending delta either.
    monkeypatch.setenv("MACOS_APPS_ALLOW_SEND", "all")
    monkeypatch.setenv("MACOS_APPS_READ_ONLY", "1")
    monkeypatch.setattr("macos_apps_mcp.deploy.grant_identities", lambda: None)
    monkeypatch.setattr(
        "macos_apps_mcp.deploy.agent_status",
        lambda: (_ for _ in ()).throw(Exception("no bundle")),
    )
    d = doctor.diagnose()["deployment"]
    assert d["outbound"] == []
    assert "outbound_pending" not in d


def test_outbound_status_splits_capable_registered_configured(monkeypatch):
    # C6: three distinct truths. capable = every adapter a @_send_tool names;
    # registered = gate state at import (off in the test process); configured = what
    # the env/toggle enables RIGHT NOW.
    from macos_apps_mcp import server

    monkeypatch.setenv("MACOS_APPS_ALLOW_SEND", "mail")
    monkeypatch.delenv("MACOS_APPS_READ_ONLY", raising=False)
    st = server.outbound_status()
    assert st["capable"] == ["mail"]
    assert st["registered"] == []  # the import-time gate was off in this process
    assert st["configured"] == ["mail"]


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
