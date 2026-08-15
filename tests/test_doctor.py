"""Doctor unit tests — every native probe is mocked at the doctor/runtime seam, so no
EventKit, osascript, or TCC is touched. One @integration test exercises the real thing.
"""

from __future__ import annotations

import json

import pytest

import macos_apps_mcp.doctor as doc
from macos_apps_mcp.errors import AppNotRunning, AutomationDenied


def _boom_osascript(*args, **kwargs):
    raise AssertionError("run_osascript must not be called when request=False")


# --- EventKit surfaces ---------------------------------------------------------------


def test_eventkit_all_granted(monkeypatch):
    monkeypatch.setattr(doc, "run_native", lambda fn: 3)  # full access
    surfaces = doc._eventkit_surfaces(request=False)
    assert [s["surface"] for s in surfaces] == ["calendar", "reminders"]
    assert all(s["ok"] is True and s["status"] == "full_access" for s in surfaces)
    assert all("remediation" not in s for s in surfaces)


def test_eventkit_denied_reports_pane(monkeypatch):
    monkeypatch.setattr(doc, "run_native", lambda fn: 2)  # denied
    surfaces = doc._eventkit_surfaces(request=False)
    assert all(s["ok"] is False and s["status"] == "denied" for s in surfaces)
    assert "Calendars" in surfaces[0]["remediation"]
    assert "Reminders" in surfaces[1]["remediation"]


def test_eventkit_writeonly_is_not_ok(monkeypatch):
    monkeypatch.setattr(doc, "run_native", lambda fn: 4)  # write-only ≠ full
    surfaces = doc._eventkit_surfaces(request=False)
    assert all(s["ok"] is False and s["status"] == "write_only" for s in surfaces)


def test_eventkit_request_routes_request_access_each_through_run_native(monkeypatch):
    # An undetermined surface triggers one per-entity request pass — the module-top
    # request_access_each handed to run_native — then status is re-read.
    def fake_request():
        raise AssertionError("request_access_each must go through run_native")

    monkeypatch.setattr(doc, "request_access_each", fake_request)
    codes = iter([0, 0, 3, 3])  # not_determined on first read; granted on re-read
    requested = []

    def fake_run_native(fn):
        if fn is fake_request:
            requested.append(True)
            return None
        return next(codes)

    monkeypatch.setattr(doc, "run_native", fake_run_native)
    surfaces = doc._eventkit_surfaces(request=True)
    assert requested == [True]
    assert all(s["ok"] is True and s["status"] == "full_access" for s in surfaces)


# --- Automation surfaces (prompt-gated) ----------------------------------------------


def test_automation_unprobed_when_request_false(monkeypatch):
    # The no-prompt guarantee: with request=False we never send an Apple event.
    monkeypatch.setattr(doc, "run_osascript", _boom_osascript)
    surfaces = doc._automation_surfaces(request=False)
    assert [s["surface"] for s in surfaces] == [
        "mail",
        "notes",
        "contacts",
        "photos",
        "safari",
        "messages",
        "music",
    ]
    assert all(s["ok"] is None and s["status"] == "unprobed" for s in surfaces)
    assert all("request=True" in s["remediation"] for s in surfaces)


def test_automation_surfaces_carry_process_line(monkeypatch):
    # #183: pid + uptime answer "did the force-quit actually restart Mail?" — a UI
    # quit once left a 37-minute-old wedged process alive. Reported even unprobed
    # (request=False): a ps read is not an Apple Event and needs no TCC.
    monkeypatch.setattr(doc, "run_osascript", _boom_osascript)
    monkeypatch.setattr(
        doc,
        "app_process_info",
        lambda app: (
            {"pid": 838, "state": "S", "cpu": 0.9, "etime": "37:12"}
            if app == "Mail"
            else None
        ),
    )
    surfaces = doc._automation_surfaces(request=False)
    by_name = {s["surface"]: s for s in surfaces}
    assert by_name["mail"]["process"] == "pid 838, up 37:12, state S, 0.9% CPU"
    assert by_name["notes"]["process"] == "not running"


def test_automation_probe_ok(monkeypatch):
    monkeypatch.setattr(doc, "run_osascript", lambda *a, **k: "AppName")
    surfaces = doc._automation_surfaces(request=True)
    assert all(s["ok"] is True and s["status"] == "ok" for s in surfaces)


def test_automation_probe_denied_carries_directive(monkeypatch):
    def denied(*a, **k):
        raise AutomationDenied("grant Automation in System Settings, then restart")

    monkeypatch.setattr(doc, "run_osascript", denied)
    surfaces = doc._automation_surfaces(request=True)
    assert all(
        s["ok"] is False and s["status"] == "automation_denied" for s in surfaces
    )
    assert "System Settings" in surfaces[0]["remediation"]


def test_automation_probe_app_not_running_is_reported_not_raised(monkeypatch):
    def not_running(*a, **k):
        raise AppNotRunning("open the app, then try again")

    monkeypatch.setattr(doc, "run_osascript", not_running)
    surfaces = doc._automation_surfaces(request=True)  # must not raise
    assert all(s["status"] == "app_not_running" for s in surfaces)


def test_probe_is_a_real_apple_event_with_consent_budget():
    # Pins the vacuous-probe regression: host-resolved properties (name/version/…)
    # never hit TCC, so the probe must send a real Apple event; the timeout budgets
    # for the one-time Automation consent dialog (a human answer).
    assert "count windows" in doc._PROBE
    assert doc._PROBE_TIMEOUT == 120.0


# --- Shortcuts CLI + Full Disk Access ------------------------------------------------


def test_shortcuts_present(monkeypatch):
    monkeypatch.setattr(doc.shutil, "which", lambda _: "/usr/bin/shortcuts")
    s = doc._shortcuts_surface()
    assert s["ok"] is True and s["status"] == "present" and "remediation" not in s


def test_shortcuts_missing(monkeypatch):
    monkeypatch.setattr(doc.shutil, "which", lambda _: None)
    s = doc._shortcuts_surface()
    assert s["ok"] is False and s["status"] == "missing"


def test_fda_granted(monkeypatch, tmp_path):
    probe = tmp_path / "TCC.db"
    probe.write_bytes(b"x")
    monkeypatch.setattr(doc, "_FDA_PATH", probe)
    s = doc._fda_surface()
    assert s["ok"] is True and s["status"] == "ok"


def test_fda_denied(monkeypatch):
    def denied_open(*a, **k):
        raise PermissionError("Operation not permitted")

    # Injecting `open` into the module globals shadows the builtin only inside doctor.
    monkeypatch.setattr(doc, "open", denied_open, raising=False)
    s = doc._fda_surface()
    assert s["ok"] is False and s["status"] == "denied"
    assert "Full Disk Access" in s["remediation"]


# --- whole-report shape / summary / budget -------------------------------------------


def _all_granted(monkeypatch, tmp_path):
    monkeypatch.setattr(doc, "run_native", lambda fn: 3)
    monkeypatch.setattr(doc, "run_osascript", lambda *a, **k: "AppName")
    monkeypatch.setattr(doc.shutil, "which", lambda _: "/usr/bin/shortcuts")
    probe = tmp_path / "TCC.db"
    probe.write_bytes(b"x")
    monkeypatch.setattr(doc, "_FDA_PATH", probe)


def test_diagnose_shape(monkeypatch, tmp_path):
    _all_granted(monkeypatch, tmp_path)
    report = doc.diagnose(request=True)
    assert set(report) == {
        "version",
        "responsible_process",
        "note",
        "probed_automation",
        "summary",
        "surfaces",
        "deployment",
    }
    assert len(report["surfaces"]) == 11  # 2 EventKit + 7 Automation + shortcuts + FDA
    assert "launched by" in report["responsible_process"]
    assert report["probed_automation"] is True
    assert report["summary"] == "all 11 surfaces OK"


def test_summary_names_denied_surfaces(monkeypatch, tmp_path):
    _all_granted(monkeypatch, tmp_path)
    monkeypatch.setattr(doc, "run_native", lambda fn: 2)  # EventKit denied
    report = doc.diagnose(request=True)
    assert "calendar" in report["summary"] and "reminders" in report["summary"]
    assert report["summary"].startswith("2 of 11 surfaces need attention")


def test_default_summary_flags_unprobed_automation(monkeypatch, tmp_path):
    _all_granted(monkeypatch, tmp_path)
    report = doc.diagnose(request=False)
    assert report["probed_automation"] is False
    assert "Automation unprobed" in report["summary"]


def test_summary_reports_unverified_surface_not_all_ok(monkeypatch, tmp_path):
    # An unprobeable surface (ok=None) must not be counted as OK: FDA probe path
    # missing → ok=None → the request=True summary says unverified, never all-OK.
    _all_granted(monkeypatch, tmp_path)
    monkeypatch.setattr(doc, "_FDA_PATH", tmp_path / "nope" / "TCC.db")
    report = doc.diagnose(request=True)
    assert "unverified" in report["summary"]
    assert "full_disk_access" in report["summary"]
    assert "all 11 surfaces OK" not in report["summary"]


def test_diagnose_reads_eventkit_status_once_per_entity(monkeypatch, tmp_path):
    # All-granted request=True takes exactly one status read per entity — no
    # request pass, no re-read.
    _all_granted(monkeypatch, tmp_path)
    reads = []

    def counting_run_native(fn):
        reads.append(fn)
        return 3  # full access

    monkeypatch.setattr(doc, "run_native", counting_run_native)
    doc.diagnose(request=True)
    assert len(reads) == 2


def test_report_stays_under_token_budget(monkeypatch, tmp_path):
    # Acceptance: output stays under ~2k tokens. Worst case = everything denied (longest
    # remediation strings). ~4 chars/token, so 2k tokens ≈ 8k chars — assert well under.
    def denied_automation(*a, **k):
        raise AutomationDenied(
            "grant Automation in System Settings, then restart macos-apps-mcp"
        )

    def denied_open(*a, **k):
        raise PermissionError()

    monkeypatch.setattr(doc, "run_native", lambda fn: 2)
    monkeypatch.setattr(doc, "run_osascript", denied_automation)
    monkeypatch.setattr(doc.shutil, "which", lambda _: None)
    monkeypatch.setattr(doc, "open", denied_open, raising=False)
    # deterministic worst case for the #183 process lines: every automation app
    # running (a live pgrep would make this test's length machine-dependent).
    monkeypatch.setattr(
        doc,
        "app_process_info",
        lambda app: {"pid": 99999, "state": "S+", "cpu": 99.9, "etime": "11-22:33:44"},
    )
    report = doc.diagnose(request=True)
    assert len(json.dumps(report, ensure_ascii=False)) < 7000


def test_probe_carries_applescript_side_timeout():
    # #56's second line of defense: the in-script `with timeout` self-terminates a
    # hung child even if the Python side died first. _PROBE — the template most
    # likely to strand an orphan (it launches each quit app in turn) — was the one
    # template without it; test_applescript_timeout.py sweeps only the adapters
    # package, so it never saw this one.
    assert "with timeout of" in doc._PROBE
    assert doc._PROBE.count("with timeout of") == doc._PROBE.count("end timeout")


# --- integration: real TCC on this Mac (never in CI) ---------------------------------


@pytest.mark.integration
def test_doctor_integration_real():
    report = doc.diagnose(request=False)
    assert len(report["surfaces"]) == 11
    assert "launched by" in report["responsible_process"]
    # every surface is well-formed regardless of grant state (the acceptance contract)
    for s in report["surfaces"]:
        assert {"surface", "kind", "ok", "status"} <= set(s)
