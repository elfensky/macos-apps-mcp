"""PLAT-01: the adapter deny-list (D-01..D-05, D-17).

``MACOS_APPS_ADAPTERS_OFF`` (env) or, in the daemon role only, the home-pinned
``adapters_off`` file lists adapters whose tools are not registered. The predicates read
a process-start fact per call, so these tests set the variable after import and assert
the PREDICATE and the views; the import-time registration effect is pinned by the
subprocess cases in ``tests/test_registry.py``.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

import macos_apps_mcp.server  # noqa: F401  (populates registry.TOOLS)
from macos_apps_mcp import deploy, doctor, eventkit, registry, runtime, tiers
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


# --- D-04: an OFF adapter is neither probed nor prompted -----------------------------


def test_off_adapter_gets_no_apple_event(monkeypatch):
    monkeypatch.setenv("MACOS_APPS_ADAPTERS_OFF", "mail")
    apps = []
    monkeypatch.setattr(
        runtime, "run_osascript", lambda _src, app, **kw: apps.append(app) or "ok"
    )
    monkeypatch.setattr(doctor, "app_process_info", lambda app: None)
    by_name = {s["surface"]: s for s in doctor._automation_surfaces(request=True)}
    assert by_name["mail"] == {
        "surface": "mail",
        "kind": "automation",
        "ok": None,
        "status": "adapter_off",
    }
    assert "Mail" not in apps
    assert sorted(apps) == ["Contacts", "Messages", "Music", "Notes", "Safari"]


def test_off_eventkit_entity_is_not_read_or_requested(monkeypatch):
    monkeypatch.setenv("MACOS_APPS_ADAPTERS_OFF", "reminders")
    reads, requests = [], []

    def fake_run_native(fn):
        if fn is doctor.request_access_each:
            requests.append(fn)
            return None
        reads.append(fn)
        return 0  # not_determined: a request pass is due

    monkeypatch.setattr(doctor, "run_native", fake_run_native)
    monkeypatch.setattr(doctor, "_ek_status", lambda entity: reads.append(entity) or 0)
    surfaces = {s["surface"]: s for s in doctor._eventkit_surfaces(request=True)}
    assert surfaces["reminders"]["status"] == "adapter_off"
    assert surfaces["reminders"]["ok"] is None
    assert surfaces["calendar"]["status"] == "not_determined"
    assert set(reads) == {doctor.EK.EKEntityTypeEvent}
    assert len(requests) == 1


def test_off_shortcuts_cli_reads_adapter_off(monkeypatch):
    monkeypatch.setenv("MACOS_APPS_ADAPTERS_OFF", "shortcuts")
    monkeypatch.setattr(
        shutil, "which", lambda _: pytest.fail("the CLI must not be looked up")
    )
    s = doctor._shortcuts_surface()
    assert (s["surface"], s["status"], s["ok"]) == (
        "shortcuts_cli",
        "adapter_off",
        None,
    )


def test_summary_counts_only_probed_surfaces(monkeypatch):
    monkeypatch.setenv("MACOS_APPS_ADAPTERS_OFF", "mail")
    monkeypatch.setattr(doctor, "run_native", lambda fn: 3)
    monkeypatch.setattr(runtime, "run_osascript", lambda *a, **k: "ok")
    monkeypatch.setattr(doctor, "app_process_info", lambda app: None)
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/shortcuts")
    ok = doctor._surface
    monkeypatch.setattr(
        runtime,
        "tracked_run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", ""),
    )
    monkeypatch.setattr(
        doctor, "_fda_surface", lambda: ok("full_disk_access", "fda", True, "ok")
    )
    monkeypatch.setattr(
        doctor, "_mail_index_surface", lambda: ok("mail_index", "fda", True, "ok")
    )
    _mock_grants(monkeypatch, None)
    monkeypatch.setattr(
        deploy, "agent_status", lambda: (_ for _ in ()).throw(Exception("no bundle"))
    )
    report = doctor.diagnose(request=True)
    names = [s["surface"] for s in report["surfaces"]]
    assert "mail" in names  # listed, as adapter_off
    assert report["summary"] == f"all {len(names) - 1} surfaces OK"


def test_request_access_each_skips_an_off_entity(monkeypatch):
    requested = []
    monkeypatch.setattr(eventkit, "store", lambda: object())
    monkeypatch.setattr(eventkit, "_request_one", lambda _s, e: requested.append(e))
    monkeypatch.setenv("MACOS_APPS_ADAPTERS_OFF", "calendar")
    eventkit.request_access_each()
    assert requested == [eventkit.EK.EKEntityTypeReminder]
    requested.clear()
    monkeypatch.delenv("MACOS_APPS_ADAPTERS_OFF")
    eventkit.request_access_each()
    assert requested == [
        eventkit.EK.EKEntityTypeEvent,
        eventkit.EK.EKEntityTypeReminder,
    ]
