"""PLAT-01: the adapter deny-list (D-01..D-05, D-17).

``MACOS_APPS_ADAPTERS_OFF`` (env) or, in the daemon role only, the home-pinned
``adapters_off`` file lists adapters whose tools are not registered. The predicates read
a process-start fact per call, so these tests set the variable after import and assert
the PREDICATE and the views; the import-time registration effect is pinned by the
subprocess cases in ``tests/test_registry.py``.
"""

from __future__ import annotations

import subprocess

import pytest

import macos_apps_mcp.server  # noqa: F401  (populates registry.TOOLS)
from macos_apps_mcp import deploy, doctor, registry, runtime, tiers
from tests.test_doctor_deploy import _gate_off_only, _mock_grants


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("MACOS_APPS_ADAPTERS_OFF", raising=False)
    monkeypatch.delenv("MACOS_APPS_MCP_ROLE", raising=False)


def _adapters() -> list[str]:
    return sorted({r.adapter for r in registry.TOOLS.values() if r.adapter})


def test_env_grammar_trims_lowercases_and_dedupes(monkeypatch):
    monkeypatch.setenv("MACOS_APPS_ADAPTERS_OFF", " Photos ,photos,")
    assert tiers.adapters_off() == {"photos"}
    assert tiers.adapter_enabled("photos") is False
    assert tiers.adapter_enabled("mail") is True


@pytest.mark.parametrize("val", [None, "", "  ", " , ,"])
def test_unset_or_empty_means_every_adapter_on(monkeypatch, val):
    if val is not None:
        monkeypatch.setenv("MACOS_APPS_ADAPTERS_OFF", val)
    assert tiers.adapters_off() == set()
    assert all(tiers.adapter_enabled(a) for a in _adapters())


def test_file_is_the_daemon_fallback(monkeypatch, tmp_path):
    f = tmp_path / "adapters_off"
    monkeypatch.setattr(deploy, "_ADAPTERS_OFF_FILE", f)
    f.write_text("music\n")
    # stdio role: the file is ignored
    assert tiers.adapters_off() == set()
    monkeypatch.setenv("MACOS_APPS_MCP_ROLE", "daemon")
    assert tiers.adapters_off() == {"music"}
    # a non-empty env var wins over the file
    monkeypatch.setenv("MACOS_APPS_ADAPTERS_OFF", "photos")
    assert tiers.adapters_off() == {"photos"}


def test_whitespace_only_file_means_every_adapter_on(monkeypatch, tmp_path):
    f = tmp_path / "adapters_off"
    f.write_text("  \n\n ")
    monkeypatch.setattr(deploy, "_ADAPTERS_OFF_FILE", f)
    monkeypatch.setenv("MACOS_APPS_MCP_ROLE", "daemon")
    assert tiers.adapters_off() == set()


def test_conftest_isolates_the_adapters_off_file(tmp_path_factory):
    # D-17: a developer's real file never reaches a test.
    assert deploy._ADAPTERS_OFF_FILE.name == "adapters_off"
    assert ".local/state/macos-apps-mcp" not in str(deploy._ADAPTERS_OFF_FILE)


def test_adapter_status_shows_configured_against_registered(monkeypatch):
    monkeypatch.setenv("MACOS_APPS_ADAPTERS_OFF", "photos")
    st = registry.adapter_status()
    everything = _adapters()
    assert len(everything) == 10
    assert st["registered"] == everything
    assert st["configured"] == [a for a in everything if a != "photos"]


def test_every_adapter_has_a_read_tool():
    # Keeps adapter_status() truthful under MACOS_APPS_READ_ONLY: every enabled adapter
    # still has a registered record.
    for adapter in _adapters():
        assert any(
            r.tier == "read" for r in registry.TOOLS.values() if r.adapter == adapter
        ), adapter


def _quiet_diagnose(monkeypatch):
    """doctor.diagnose() with no live pgrep/ps, no TCC read and no bundle."""
    monkeypatch.setattr(
        runtime,
        "tracked_run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", ""),
    )
    _mock_grants(monkeypatch, None)
    monkeypatch.setattr(
        deploy, "agent_status", lambda: (_ for _ in ()).throw(Exception("no bundle"))
    )
    return doctor.diagnose()["deployment"]


def test_allow_send_does_not_reopen_an_off_adapter(monkeypatch):
    # T-05-04: allow_send=mail with Mail OFF leaves no outbound delta a restart
    # cannot clear.
    monkeypatch.setenv("MACOS_APPS_ALLOW_SEND", "mail")
    monkeypatch.setenv("MACOS_APPS_ADAPTERS_OFF", "mail")
    assert registry.outbound_status()["configured"] == []


def test_doctor_reports_the_active_adapters(monkeypatch):
    d = _quiet_diagnose(monkeypatch)
    assert d["adapters"] == _adapters()
    assert d["adapters_off"] == []
    assert "adapters_pending" not in d
    assert "adapters_unknown" not in d
    assert "adapters_off" in d["adapters_note"]
    assert "kickstart" in d["adapters_note"]


@_gate_off_only
def test_doctor_reports_pending_and_unknown_adapters(monkeypatch):
    monkeypatch.setenv("MACOS_APPS_ADAPTERS_OFF", "photos,nosuch,Photos")
    d = _quiet_diagnose(monkeypatch)
    # registration ran with everything on, so this process still serves all ten
    assert d["adapters"] == _adapters()
    assert d["adapters_pending"] == [a for a in _adapters() if a != "photos"]
    assert "restart the daemon" in d["adapters_note"]
    assert d["adapters_unknown"] == ["nosuch"]
