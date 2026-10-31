"""Doctor unit tests — every native probe is mocked at the doctor/runtime seam, so no
EventKit, osascript, or TCC is touched. One @integration test exercises the real thing.
"""

from __future__ import annotations

import ctypes
import json
import shutil
import subprocess
import sys

import pytest

import macos_apps_mcp.doctor as doc
from macos_apps_mcp import runtime
from macos_apps_mcp.errors import (
    AppNotRunning,
    AutomationDenied,
    FullDiskAccessDenied,
    SchemaDrift,
)
from tests._fakes import fake_automation

# Bound at import: the conftest seam lock replaces runtime.automation_permission.
_REAL_AUTOMATION_PERMISSION = runtime.automation_permission


@pytest.fixture(autouse=True)
def _no_live_process_probe(monkeypatch):
    """doctor's automation surfaces read every app's process line via
    ``runtime.app_process_info`` -> ``runtime.tracked_run`` (pgrep + ps), even with
    request=False (#183). The conftest lock refuses tracked_run outright; here it's
    faked instead of refused, so ``app_process_info`` gets a normal "not running"
    result (returncode 1, empty stdout) and no live pgrep/ps ever runs (GATE-01). A
    test that patches ``doc.app_process_info`` directly bypasses this fake entirely
    and keeps working unchanged."""

    def _fake_pgrep_or_ps(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, "", "")

    monkeypatch.setattr(runtime, "tracked_run", _fake_pgrep_or_ps)
    fake_automation(monkeypatch)


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


_APPS = ["mail", "notes", "contacts", "safari", "messages", "music"]


@pytest.mark.parametrize(
    ("rc", "ok", "status"),
    [
        (0, True, "granted"),
        (-1743, False, "denied"),
        (-1744, None, "not_asked"),
        (-600, None, "not_running"),
        (-1, None, "probe_error"),
        (42, None, "probe_error"),
    ],
)
def test_automation_live_status_table(monkeypatch, rc, ok, status):
    fake_automation(monkeypatch, rc)
    surfaces = doc._automation_surfaces(request=False)
    assert [s["surface"] for s in surfaces] == _APPS
    for s in surfaces:
        assert s["ok"] is ok and s["status"] == status
    if status == "granted":
        assert all("remediation" not in s for s in surfaces)
    if status == "not_running":
        for s, app in zip(surfaces, doc._AUTOMATION_APPS, strict=True):
            assert app in s["remediation"] and "Settings" not in s["remediation"]
    if status == "probe_error":
        assert all("OSStatus" in s["remediation"] for s in surfaces)
        assert all(str(rc) in s["remediation"] for s in surfaces)


def test_denied_automation_remediation_needs_no_restart(monkeypatch):
    # FIX-14 follow-up: a grant switched back on reads `granted` at once on device
    # (2026-10-27), so the text asks only for the switch.
    fake_automation(monkeypatch, -1743)
    for s, app in zip(
        doc._automation_surfaces(request=False), doc._AUTOMATION_APPS, strict=True
    ):
        assert app in s["remediation"] and "Automation" in s["remediation"]
        assert "restart" not in s["remediation"].lower()


def test_automation_live_check_sends_no_apple_event(monkeypatch):
    # The no-prompt guarantee: with request=False we never send an Apple event.
    monkeypatch.setattr(runtime, "run_osascript", _boom_osascript)
    calls = fake_automation(monkeypatch, 0)
    surfaces = doc._automation_surfaces(request=False)
    assert [s["surface"] for s in surfaces] == _APPS
    assert calls == [
        "com.apple.mail",
        "com.apple.Notes",
        "com.apple.AddressBook",
        "com.apple.Safari",
        "com.apple.MobileSMS",
        "com.apple.Music",
    ]
    assert all(s["status"] != "unprobed" for s in surfaces)


def test_automation_live_check_skips_off_adapters(monkeypatch):
    monkeypatch.setenv("MACOS_APPS_ADAPTERS_OFF", ",".join(_APPS))
    calls = fake_automation(monkeypatch, 0)
    surfaces = doc._automation_surfaces(request=False)
    assert calls == []
    assert all(s["status"] == "adapter_off" for s in surfaces)


@pytest.mark.parametrize("exc", [OSError("dlopen"), AttributeError("no symbol")])
def test_automation_live_check_survives_a_broken_seam(monkeypatch, tmp_path, exc):
    def broken(bundle_id):
        raise exc

    monkeypatch.setattr(runtime, "automation_permission", broken)
    surfaces = doc._automation_surfaces(request=False)
    assert [s["surface"] for s in surfaces] == _APPS
    for s in surfaces:
        assert s["ok"] is None and s["status"] == "probe_error"
        assert type(exc).__name__ in s["remediation"]
    _all_granted(monkeypatch, tmp_path)
    assert doc.diagnose(request=False)["surfaces"]


def test_automation_bundle_ids_match_the_grant_map():
    from macos_apps_mcp.dashboard.grants import ADAPTER_GRANTS, EVENTS

    assert set(doc._AUTOMATION_BUNDLES) == {a.lower() for a in doc._AUTOMATION_APPS}
    for name, bundle in doc._AUTOMATION_BUNDLES.items():
        assert [t for svc, t in ADAPTER_GRANTS[name] if svc == EVENTS] == [bundle]


def test_automation_surfaces_carry_process_line(monkeypatch):
    # #183: pid + uptime answer "did the force-quit actually restart Mail?" — a UI
    # quit once left a 37-minute-old wedged process alive. Reported even unprobed
    # (request=False): a ps read is not an Apple Event and needs no TCC.
    monkeypatch.setattr(runtime, "run_osascript", _boom_osascript)
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
    monkeypatch.setattr(runtime, "run_osascript", lambda *a, **k: "AppName")
    surfaces = doc._automation_surfaces(request=True)
    assert all(s["ok"] is True and s["status"] == "ok" for s in surfaces)


def test_automation_probe_denied_carries_directive(monkeypatch):
    def denied(*a, **k):
        raise AutomationDenied("grant Automation in System Settings, then restart")

    monkeypatch.setattr(runtime, "run_osascript", denied)
    surfaces = doc._automation_surfaces(request=True)
    assert all(
        s["ok"] is False and s["status"] == "automation_denied" for s in surfaces
    )
    assert "System Settings" in surfaces[0]["remediation"]


def test_automation_probe_app_not_running_is_reported_not_raised(monkeypatch):
    def not_running(*a, **k):
        raise AppNotRunning("open the app, then try again")

    monkeypatch.setattr(runtime, "run_osascript", not_running)
    surfaces = doc._automation_surfaces(request=True)  # must not raise
    assert all(s["status"] == "app_not_running" for s in surfaces)


def test_probe_is_a_real_apple_event_with_consent_budget():
    # Pins the vacuous-probe regression: host-resolved properties (name/version/…)
    # never hit TCC, so the probe must send a real Apple event; the timeout budgets
    # for the one-time Automation consent dialog (a human answer).
    assert "count windows" in doc._PROBE
    assert doc._PROBE_TIMEOUT == 120.0


def test_probe_template_swallows_only_1728():
    """#317: the probe wraps `count windows` and re-raises every error but -1728."""
    lines = [ln.strip() for ln in doc._PROBE.splitlines() if ln.strip()]
    assert lines == [
        "on run argv",
        "with timeout of 120 seconds",
        "tell application (item 1 of argv)",
        "try",
        "count windows",
        "on error errMsg number errNum",
        "if errNum is not -1728 then error errMsg number errNum",
        "end try",
        "end tell",
        "end timeout",
        "end run",
    ]


def test_probe_compiles():
    """#317: the rewritten probe is valid AppleScript."""
    if not shutil.which("osacompile"):
        pytest.skip("osacompile not available")
    proc = subprocess.run(
        ["osacompile", "-o", "/dev/null", "-"],
        input=doc._PROBE,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize(
    ("number", "message", "expected"),
    [
        (-1728, "Photos got an error: Can't get every window.", None),
        (-1743, "Not authorized to send Apple events to Photos.", AutomationDenied),
        (-609, "Connection is invalid.", AppNotRunning),
    ],
)
def test_probe_error_filter_under_real_osascript(number, message, expected):
    """#317: -1728 exits 0; -1743 and -609 keep their number and classify."""
    if not shutil.which("osascript"):
        pytest.skip("osascript not available")
    tell, count = "tell application (item 1 of argv)", "count windows"
    assert doc._PROBE.count(tell) == 1 and doc._PROBE.count(count) == 1
    # `tell current application` plus `error` sends no Apple event, so no app
    # launches and no consent prompt can appear.
    script = doc._PROBE.replace(tell, "tell current application").replace(
        count, f'error "{message}" number {number}'
    )
    proc = subprocess.run(
        ["osascript", "-", "Photos"],
        input=script,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if expected is None:
        assert proc.returncode == 0, proc.stderr
        return
    assert proc.returncode != 0
    assert f"({number})" in proc.stderr
    assert isinstance(runtime._classify_osascript_failure(proc.stderr), expected)


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
    monkeypatch.setattr(doc, "_FDA_PATHS", (probe,))
    s = doc._fda_surface()
    assert s["ok"] is True and s["status"] == "ok"


def test_fda_falls_back_to_the_system_db_when_the_user_db_is_absent(
    monkeypatch, tmp_path
):
    # #261: macOS 27 has no per-user TCC.db; the system db still answers the probe.
    system = tmp_path / "system" / "TCC.db"
    system.parent.mkdir()
    system.write_bytes(b"x")
    monkeypatch.setattr(doc, "_FDA_PATHS", (tmp_path / "user" / "TCC.db", system))
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


# --- mail_index surface (#199) -------------------------------------------------------


def test_mail_index_surface_ok(monkeypatch):
    monkeypatch.setattr(doc.mail_index, "check_index_schema", lambda: "ok")
    s = doc._mail_index_surface()
    assert s["ok"] is True and s["status"] == "ok"


def test_mail_index_surface_reports_floor_drift(monkeypatch):
    def drift():
        raise SchemaDrift("platform floor — needs macOS 26+")

    monkeypatch.setattr(doc.mail_index, "check_index_schema", drift)
    s = doc._mail_index_surface()
    assert s["ok"] is False
    assert s["status"] == "schema_unsupported"
    assert "macOS 26" in s["remediation"]


def test_mail_index_surface_sidecar_reports_coverage(monkeypatch):
    # #201: a pre-Tahoe store served through the Message-ID sidecar is a WORKING
    # surface (ok=True) whose coverage rides as remediation-free detail — a partial
    # sidecar degrades the detail line, never the verdict.
    monkeypatch.setattr(doc.mail_index, "check_index_schema", lambda: "sidecar")
    monkeypatch.setattr(doc.mail_index, "require_index_path", lambda: "idx")
    monkeypatch.setattr(
        doc.mail_ids,
        "coverage_line",
        lambda path: "9 of 10 ids mapped (90.0%), high-water ROWID 42, built T",
    )
    s = doc._mail_index_surface()
    assert s["ok"] is True and s["status"] == "sidecar"
    assert s["coverage"].startswith("9 of 10 ids mapped")
    assert "remediation" not in s


def test_mail_index_surface_no_mail_data_is_indeterminate(monkeypatch):
    monkeypatch.setattr(doc.mail_index, "check_index_schema", lambda: "no_mail_data")
    s = doc._mail_index_surface()
    assert s["ok"] is None and s["status"] == "no_mail_data"


def test_mail_index_surface_fda_denied_is_indeterminate_not_false(monkeypatch):
    # The full_disk_access surface owns that failure — this one must not double-
    # count it as a schema problem.
    def denied():
        raise FullDiskAccessDenied("grant FDA")

    monkeypatch.setattr(doc.mail_index, "check_index_schema", denied)
    s = doc._mail_index_surface()
    assert s["ok"] is None
    assert s["status"] == "full_disk_access_denied"


def test_summary_names_mail_index_drift(monkeypatch, tmp_path):
    # The #199 acceptance: a Sequoia machine must NOT report "no denied surfaces".
    _all_granted(monkeypatch, tmp_path)

    def drift():
        raise SchemaDrift("platform floor — needs macOS 26+")

    monkeypatch.setattr(doc.mail_index, "check_index_schema", drift)
    report = doc.diagnose(request=False)
    assert "mail_index" in report["summary"]
    assert "need attention" in report["summary"]


def _all_granted(monkeypatch, tmp_path):
    monkeypatch.setattr(doc, "run_native", lambda fn: 3)
    monkeypatch.setattr(runtime, "run_osascript", lambda *a, **k: "AppName")
    monkeypatch.setattr(doc.shutil, "which", lambda _: "/usr/bin/shortcuts")
    probe = tmp_path / "TCC.db"
    probe.write_bytes(b"x")
    monkeypatch.setattr(doc, "_FDA_PATHS", (probe,))
    monkeypatch.setattr(doc.mail_index, "check_index_schema", lambda: "ok")


def test_diagnose_shape(monkeypatch, tmp_path):
    _all_granted(monkeypatch, tmp_path)
    report = doc.diagnose(request=True)
    assert set(report) == {
        "version",
        "build",
        "libs",
        "responsible_process",
        "note",
        "probed_automation",
        "summary",
        "surfaces",
        "deployment",
    }
    assert set(report["libs"]) == {"mcp", "fastmcp"}
    # 2 EventKit + 6 Automation + shortcuts + FDA + mail_index
    assert len(report["surfaces"]) == 11
    assert "launched by" in report["responsible_process"]
    assert report["probed_automation"] is True
    assert report["summary"] == "all 11 surfaces OK"


def test_version_reads_any_distribution():
    from importlib.metadata import version

    assert doc.version("mcp") == version("mcp")
    assert doc.version("no-such-dist-291") == "unknown"


def test_the_dashboard_footer_names_the_doctor_version(monkeypatch):
    """#430 IN-02: the sidebar footer and the Health page share one version lookup."""
    from tests import _dashboard

    monkeypatch.setattr(
        doc,
        "version",
        lambda dist="macos-apps-mcp": {"macos-apps-mcp": "9.9.9"}[dist],
    )
    r = _dashboard.get("/usage")
    assert r.status_code == 200
    assert "v9.9.9 · 127.0.0.1 only" in r.text


def test_summary_names_denied_surfaces(monkeypatch, tmp_path):
    _all_granted(monkeypatch, tmp_path)
    monkeypatch.setattr(doc, "run_native", lambda fn: 2)  # EventKit denied
    report = doc.diagnose(request=True)
    assert "calendar" in report["summary"] and "reminders" in report["summary"]
    assert report["summary"].startswith("2 of 11 surfaces need attention")


def test_default_summary_reads_live_automation(monkeypatch, tmp_path):
    _all_granted(monkeypatch, tmp_path)
    fake_automation(monkeypatch, 0)
    report = doc.diagnose(request=False)
    assert report["probed_automation"] is False
    assert report["summary"] == "all 11 surfaces OK"
    fake_automation(monkeypatch, -600)
    report = doc.diagnose(request=False)
    assert report["summary"].startswith("no denied surfaces; 6 unverified:")
    assert "Automation unprobed" not in report["summary"]


def test_summary_reports_unverified_surface_not_all_ok(monkeypatch, tmp_path):
    # An unprobeable surface (ok=None) must not be counted as OK: FDA probe path
    # missing → ok=None → the request=True summary says unverified, never all-OK.
    _all_granted(monkeypatch, tmp_path)
    monkeypatch.setattr(doc, "_FDA_PATHS", (tmp_path / "nope" / "TCC.db",))
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


def _budget_cases():
    from macos_apps_mcp import daemon

    return [
        pytest.param("stdio", None, id="stdio"),
        pytest.param("daemon", "not bound: [Errno 48] in use", id="daemon-not-bound"),
        pytest.param("daemon", daemon.KEY_UNUSABLE_STATE, id="daemon-key-unusable"),
        pytest.param(
            "daemon",
            "not built: " + '"' * daemon.NOT_BUILT_MAX,
            id="daemon-not-built-worst-escape",
        ),
    ]


@pytest.mark.parametrize(
    "probes", [pytest.param(True, id="probed"), pytest.param(False, id="live")]
)
@pytest.mark.parametrize(("role", "state"), _budget_cases())
def test_report_stays_under_token_budget(monkeypatch, tmp_path, role, state, probes):
    # Acceptance: output stays under ~2k tokens. Worst case = everything denied (longest
    # remediation strings). ~4 chars/token, so 2k tokens ≈ 8k chars. The largest
    # request=False live report (daemon, not-built state) measures, per status of the
    # six Automation surfaces: denied 7301, not_running 7138, not_asked 7120,
    # probe_error 7072 (OSStatus -1708). Denied is the worst case, so 7500 keeps 199
    # chars of margin; a `ps` executable name longer by 199 chars would fail it.
    if role == "daemon":
        # The daemon adds the dashboard keys, and the deny-list is operator input:
        # pending deltas both ways and many unknown names (PM-05, #421 review).
        from macos_apps_mcp import daemon, registry

        monkeypatch.setenv("MACOS_APPS_MCP_ROLE", "daemon")
        junk = ",".join(f"no-such-adapter-{i}" for i in range(10))
        junk += (
            "," + "a" * 4000
        )  # WR-04: one long unknown name must not break the budget
        monkeypatch.setenv("MACOS_APPS_ADAPTERS_OFF", f"photos,{junk}")
        sending = registry.outbound_status()["registered"]
        monkeypatch.setenv("MACOS_APPS_ALLOW_SEND", "" if sending else "mail")
        monkeypatch.setattr(daemon, "dashboard_state", state)

    def denied_automation(*a, **k):
        raise AutomationDenied(
            "grant Automation in System Settings, then restart macos-apps-mcp"
        )

    def denied_open(*a, **k):
        raise PermissionError()

    def floor_drift():
        # The longest string this surface can carry: the #199 platform-floor message.
        raise SchemaDrift(doc.mail_index._FLOOR_MESSAGE.format(ver="15.7.9"))

    monkeypatch.setattr(doc, "run_native", lambda fn: 2)
    monkeypatch.setattr(runtime, "run_osascript", denied_automation)
    monkeypatch.setattr(doc.shutil, "which", lambda _: None)
    monkeypatch.setattr(doc, "open", denied_open, raising=False)
    monkeypatch.setattr(doc.mail_index, "check_index_schema", floor_drift)
    # deterministic worst case for the #183 process lines: every automation app
    # running (a live pgrep would make this test's length machine-dependent).
    monkeypatch.setattr(
        doc,
        "app_process_info",
        lambda app: {"pid": 99999, "state": "S+", "cpu": 99.9, "etime": "11-22:33:44"},
    )
    # #464: the unpinned field made the length depend on the runner's PIDs.
    monkeypatch.setattr(
        doc, "_responsible_process", lambda: "pid 99999 (this), launched by pid 99999"
    )
    # deterministic grant map too: the machine's real TCC.db made this length depend
    # on the runner (#318). The daemon's own rows, every AppleEvents target denied by a
    # timed-out prompt — the longest entry the map can carry.
    from tests.test_deploy import _tcc_db

    me = "ren.lav.macos-apps-mcp"
    targets = ("mail", "Notes", "AddressBook", "Photos", "Safari", "MobileSMS", "Music")
    db = tmp_path / "TCC.db"
    _tcc_db(
        db,
        [(s, me, 2, 3, "UNUSED") for s in doc.deploy._SERVICES[:3]]
        + [("kTCCServiceAppleEvents", me, 0, 9, f"com.apple.{t}") for t in targets]
        + [("kTCCServiceSystemPolicyAllFiles", me, 2, 3, "UNUSED")],
    )
    monkeypatch.setattr(doc.deploy, "_TCC_DB", db)
    monkeypatch.setattr(doc.deploy, "_TCC_SYSTEM_DB", tmp_path / "absent" / "TCC.db")
    # O14: the live path (request=False) with every app denied, the longest live text.
    fake_automation(monkeypatch, -1743)
    report = doc.diagnose(request=probes)
    assert report["deployment"]["grant_identities"]["kTCCServiceAppleEvents"]
    assert "doctor(request=True)" in report["deployment"]["note"]  # the #318 why, once
    sizes = {k: len(json.dumps(v, ensure_ascii=False)) for k, v in report.items()}
    sizes |= {
        f"deployment.{k}": len(json.dumps(v, ensure_ascii=False))
        for k, v in report["deployment"].items()
    }
    largest = sorted(sizes.items(), key=lambda kv: -kv[1])[:8]
    assert len(json.dumps(report, ensure_ascii=False)) < 7500, largest


@pytest.mark.skipif(sys.platform != "darwin", reason="loads CoreServices")
def test_ae_lib_binds_the_three_calls_with_exact_types():
    # PM-07: the fakes in test_runtime.py never reach the real ctypes bindings, and a
    # wrong restype (an unsigned OSStatus) turns -1743 into 4294965553. Loads the real
    # CoreServices and calls no Apple Event function.
    lib = runtime._ae_lib()
    desc = ctypes.POINTER(runtime._AEDesc)
    create = lib.AECreateDesc
    assert create.restype is ctypes.c_int16
    assert create.argtypes == [
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_long,
        desc,
    ]
    assert lib.AEDisposeDesc.restype is ctypes.c_int16
    determine = lib.AEDeterminePermissionToAutomateTarget
    assert determine.restype is ctypes.c_int32
    assert determine.argtypes == [
        desc,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_ubyte,
    ]


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
    # 2 eventkit (calendar, reminders) + 6 automation (mail, notes, contacts,
    # safari, messages, music) + shortcuts_cli + full_disk_access + mail_index = 11.
    # Photos left the Automation list in Phase 4 (osxphotos reads it at rest).
    assert len(report["surfaces"]) == 11
    assert "launched by" in report["responsible_process"]
    # every surface is well-formed regardless of grant state (the acceptance contract)
    for s in report["surfaces"]:
        assert {"surface", "kind", "ok", "status"} <= set(s)


@pytest.mark.integration
def test_automation_permission_real_is_non_prompting():
    # Real CoreServices call, never prompts; run manually, never in CI.
    assert isinstance(_REAL_AUTOMATION_PERMISSION("com.apple.finder"), int)
    assert _REAL_AUTOMATION_PERMISSION("com.example.nope") == -600


# --- #143: the build stamp — version alone cannot see a same-version rebuild ---------


def test_build_stamp_reports_dev_without_a_stamp_file(tmp_path, monkeypatch):
    # a dev checkout (and any bundle whose build script predates #143) has no stamp
    monkeypatch.setattr(doc, "_BUILD_STAMP_PATH", tmp_path / "build_stamp")
    assert doc.build_stamp() == "dev"


def test_build_stamp_reads_the_baked_file(tmp_path, monkeypatch):
    stamp = tmp_path / "build_stamp"
    stamp.write_text("b7fbde6 2026-08-20T10:00:00Z\n")
    monkeypatch.setattr(doc, "_BUILD_STAMP_PATH", stamp)
    assert doc.build_stamp() == "b7fbde6 2026-08-20T10:00:00Z"


def test_report_carries_the_build_stamp(monkeypatch):
    monkeypatch.setattr(doc, "run_native", lambda fn: 3)
    monkeypatch.setattr(doc, "build_stamp", lambda: "b7fbde6 2026-08-20T10:00:00Z")
    report = doc.diagnose(request=False)
    assert report["build"] == "b7fbde6 2026-08-20T10:00:00Z"
