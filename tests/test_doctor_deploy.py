from macos_apps_mcp import doctor


def _mock_grants(monkeypatch, identities, reasons=None):
    # doctor reads deploy.grant_report (identities + classified read reasons, C7).
    monkeypatch.setattr(
        "macos_apps_mcp.deploy.grant_report",
        lambda: {
            "identities": identities,
            "reasons": reasons
            or {"user": "no-full-disk-access", "system": "no-full-disk-access"},
        },
    )


def test_deployment_section_stdio_graceful(monkeypatch):
    monkeypatch.delenv("MACOS_APPS_MCP_ROLE", raising=False)
    monkeypatch.delenv("MACOS_APPS_ALLOW_SEND", raising=False)
    monkeypatch.delenv("MACOS_APPS_READ_ONLY", raising=False)
    _mock_grants(monkeypatch, None)
    monkeypatch.setattr(
        "macos_apps_mcp.deploy.agent_status",
        lambda: (_ for _ in ()).throw(Exception("no bundle")),
    )
    d = doctor.diagnose()["deployment"]
    assert d["mode"] == "stdio"
    assert d["grant_identities"] is None
    # the FDA-blame branch specifically — "FDA" alone is vacuous, the OTHER branch
    # says "not an FDA denial" and contains the substring too.
    assert "grant Full Disk Access" in d["note"]
    assert d["agent"].startswith("unavailable")
    # #130: the gate must be OBSERVABLE — off by default, never a bare "".
    assert d["outbound"] == []
    assert "OFF" in d["outbound_note"]


def test_deployment_note_does_not_blame_fda_for_a_missing_tcc_db(monkeypatch):
    # C7: the whole point of the classified reasons is that a missing db, schema drift
    # and an FDA denial stop collapsing into one unconditional "grant FDA". A machine
    # with no TCC.db must NOT be told to grant a permission that can't fix it.
    monkeypatch.delenv("MACOS_APPS_MCP_ROLE", raising=False)
    _mock_grants(monkeypatch, None, reasons={"user": "absent", "system": "absent"})
    monkeypatch.setattr(
        "macos_apps_mcp.deploy.agent_status",
        lambda: (_ for _ in ()).throw(Exception("no bundle")),
    )
    note = doctor.diagnose()["deployment"]["note"]
    assert "not an FDA denial" in note
    assert "grant Full Disk Access" not in note
    assert "user db: absent" in note and "system db: absent" in note


def test_deployment_note_reports_a_partial_tcc_read(monkeypatch):
    # C7 follow-up: FDA rows live ONLY in the system db (#123), so a readable user db
    # plus a denied system db yields an identity map with no FDA row — which reads as
    # "FDA not granted" unless the reason is surfaced. Reporting reasons only when BOTH
    # dbs failed left the #123 misdiagnosis alive in exactly the partial case.
    monkeypatch.delenv("MACOS_APPS_MCP_ROLE", raising=False)
    _mock_grants(
        monkeypatch,
        {"kTCCServiceAppleEvents": [{"client": "com.example.app", "granted": True}]},
        reasons={"user": None, "system": "no-full-disk-access"},
    )
    monkeypatch.setattr(
        "macos_apps_mcp.deploy.agent_status",
        lambda: (_ for _ in ()).throw(Exception("no bundle")),
    )
    d = doctor.diagnose()["deployment"]
    assert d["grant_identities"] is not None  # the user db DID answer
    assert "PARTIAL read" in d["note"]
    assert "system db: no-full-disk-access" in d["note"]
    assert "user db" not in d["note"]  # only the db that actually failed is named


def test_deployment_note_has_no_partial_marker_when_both_dbs_read(monkeypatch):
    monkeypatch.delenv("MACOS_APPS_MCP_ROLE", raising=False)
    _mock_grants(
        monkeypatch,
        {"kTCCServiceAppleEvents": []},
        reasons={"user": None, "system": None},
    )
    monkeypatch.setattr(
        "macos_apps_mcp.deploy.agent_status",
        lambda: (_ for _ in ()).throw(Exception("no bundle")),
    )
    assert "PARTIAL" not in doctor.diagnose()["deployment"]["note"]


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
    _mock_grants(monkeypatch, None)
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
    _mock_grants(monkeypatch, None)
    monkeypatch.setattr(
        "macos_apps_mcp.deploy.agent_status",
        lambda: (_ for _ in ()).throw(Exception("no bundle")),
    )
    d = doctor.diagnose()["deployment"]
    assert d["outbound"] == []
    assert "outbound_pending" not in d


def test_outbound_status_splits_registered_from_configured(monkeypatch):
    # C6: the two truths that can DISAGREE. registered = gate state at import (off in
    # this process); configured = what the env/toggle enables RIGHT NOW. The former
    # third key, `capable`, was read by nothing and is gone — _SEND_ADAPTERS serves
    # anyone who needs it. The non-empty `registered` case is pinned by the gate-on
    # subprocess in test_gate_on_dispatch.py, the only process where the gate is on.
    from macos_apps_mcp import server

    monkeypatch.setenv("MACOS_APPS_ALLOW_SEND", "mail")
    monkeypatch.delenv("MACOS_APPS_READ_ONLY", raising=False)
    st = server.outbound_status()
    assert set(st) == {"registered", "configured"}
    assert st["registered"] == []  # the import-time gate was off in this process
    assert st["configured"] == ["mail"]


def test_deployment_section_daemon_mode(monkeypatch):
    monkeypatch.setenv("MACOS_APPS_MCP_ROLE", "daemon")
    _mock_grants(
        monkeypatch,
        {
            "kTCCServiceCalendar": [
                {"client": "ren.lav.macos-apps-mcp", "granted": True}
            ]
        },
        reasons={"user": None, "system": None},
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


def test_daemon_role_is_detected_from_argv_not_only_the_env_var(monkeypatch):
    """#165: `daemon.serve()` sets MACOS_APPS_MCP_ROLE, but
    `macos_apps_mcp/__init__.py` has already done `from .server import mcp` by then —
    every tool is registered, and the outbound gate already read, several frames
    earlier. Reading only the env var therefore meant the daemon's outbound tier could
    NEVER register: a freshly restarted daemon whose toggle plainly said `mail`
    reported `{"registered": [], "configured": ["mail"]}`, and doctor blamed a stale
    restart that could not possibly fix it. argv is available at the earliest moment
    and is what cli.main() dispatches on."""
    from macos_apps_mcp import deploy

    monkeypatch.delenv("MACOS_APPS_MCP_ROLE", raising=False)
    monkeypatch.setattr("sys.argv", ["macos_apps_mcp", "daemon"])
    assert deploy.is_daemon_role() is True

    monkeypatch.setattr("sys.argv", ["macos_apps_mcp", "shim"])
    assert deploy.is_daemon_role() is False
    monkeypatch.setattr("sys.argv", ["macos_apps_mcp"])
    assert deploy.is_daemon_role() is False

    # the env var still works — that is how a test or an embedder says the same thing
    monkeypatch.setenv("MACOS_APPS_MCP_ROLE", "daemon")
    assert deploy.is_daemon_role() is True


def test_the_daemon_outbound_gate_reads_the_toggle_from_argv_alone(
    monkeypatch, tmp_path
):
    """The end the bug actually broke: with no env var at all, argv=daemon and a toggle
    saying `mail`, the gate must be ON."""
    import macos_apps_mcp.server as srv
    from macos_apps_mcp import deploy

    monkeypatch.delenv("MACOS_APPS_MCP_ROLE", raising=False)
    monkeypatch.delenv("MACOS_APPS_ALLOW_SEND", raising=False)
    monkeypatch.delenv("MACOS_APPS_READ_ONLY", raising=False)
    toggle = tmp_path / "allow_send"
    toggle.write_text("mail")
    monkeypatch.setattr(deploy, "_ALLOW_SEND_FILE", toggle)

    monkeypatch.setattr("sys.argv", ["macos_apps_mcp"])
    assert srv._allow_send("mail") is False  # stdio: env var is the whole story
    monkeypatch.setattr("sys.argv", ["macos_apps_mcp", "daemon"])
    assert srv._allow_send("mail") is True
    assert srv._allow_send("messages") is False  # named adapters only

    # READ_ONLY still wins unconditionally
    monkeypatch.setenv("MACOS_APPS_READ_ONLY", "1")
    assert srv._allow_send("mail") is False
