"""#574: doctor reports the version and build of the RUNNING process. A bundle
replaced on disk under a daemon that was not restarted must not change them."""

import subprocess
from importlib import metadata

from macos_apps_mcp import doctor as doc
from macos_apps_mcp import runtime
from tests._fakes import fake_automation


def test_version_does_not_follow_the_disk_after_import(monkeypatch):
    serving = {d: doc.version(d) for d in ("macos-apps-mcp", "mcp", "fastmcp")}
    monkeypatch.setattr(metadata, "version", lambda dist: "99.0.0-on-disk")
    assert {d: doc.version(d) for d in serving} == serving
    assert doc.version() == serving["macos-apps-mcp"]


def test_build_does_not_follow_the_disk_after_import(tmp_path, monkeypatch):
    serving = doc.build_stamp()
    stamp = tmp_path / "build_stamp"
    stamp.write_text("deadbee 2099-01-01T00:00:00Z\n")
    monkeypatch.setattr(doc, "_BUILD_STAMP_PATH", stamp)
    assert doc.build_stamp() == serving


def test_report_names_the_captured_identity(tmp_path, monkeypatch):
    serving = (doc.version(), doc.build_stamp(), doc.version("mcp"))
    monkeypatch.setattr(metadata, "version", lambda dist: "99.0.0-on-disk")
    stamp = tmp_path / "build_stamp"
    stamp.write_text("deadbee 2099-01-01T00:00:00Z\n")
    monkeypatch.setattr(doc, "_BUILD_STAMP_PATH", stamp)
    monkeypatch.setattr(  # no live pgrep/ps: every app reads "not running"
        runtime,
        "tracked_run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", ""),
    )
    fake_automation(monkeypatch)
    monkeypatch.setattr(doc, "run_native", lambda fn: 3)
    report = doc.diagnose(request=False)
    assert (report["version"], report["build"], report["libs"]["mcp"]) == serving
