"""#580: ps formats %cpu in the process locale ("0,0" in nl_BE, "0٫0" in ar_SA), and
float() refuses both. The ps child must run with LC_ALL=C."""

import subprocess

from macos_apps_mcp import runtime


def test_ps_runs_in_the_c_locale(monkeypatch):
    calls = []

    def fake_tracked_run(cmd, *, timeout):
        calls.append(cmd)
        out = "838\n" if cmd[0] == "pgrep" else "S    0.9 05:28:53\n"
        return subprocess.CompletedProcess(cmd, 0, out, "")

    monkeypatch.setattr(runtime, "tracked_run", fake_tracked_run)
    assert runtime.app_process_info("Mail")["cpu"] == 0.9
    ps = calls[1]
    assert ps[: ps.index("ps")] == ["env", "LC_ALL=C"]
