"""On-device gate for #71 (run manually: uv run pytest -m integration -k daemon).
The full acceptance (grants shared across Terminal/Claude Desktop/VS Code after ONE
grant to the daemon identity) needs human grant clicks — the manual checklist lives
in docs/DAEMON.md; these tests cover what automation can reach."""

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

BUILD = Path(__file__).resolve().parents[1] / "scripts" / "build_app.sh"

# AF_UNIX sun_path is capped at 104 bytes on macOS. pytest's tmp_path lives under
# /private/var/folders/.../pytest-of-<user>/pytest-<n>/<test-name>0/, which routinely
# blows that budget (confirmed on-device: 122+ chars → `OSError: AF_UNIX path too
# long`, raised before bind() even runs — daemon never gets a socket up). Sockets use
# a short /tmp-rooted dir instead; everything else keeps pytest's tmp_path.


def test_build_unsigned_bundle_and_smoke(tmp_path):
    subprocess.run([str(BUILD), "--out", str(tmp_path)], check=True, timeout=600)
    exe = tmp_path / "macos-apps-mcp.app/Contents/MacOS/macos-apps-mcp"
    out = subprocess.run(  # env-free: proves the getpath layout, no PYTHONHOME
        ["env", "-i", str(exe), "-c", "import macos_apps_mcp; print('ok')"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert out.stdout.strip() == "ok", out.stderr


def test_daemon_shim_end_to_end(monkeypatch):
    """venv daemon + venv shim over a private socket: real subprocesses, real UDS."""
    import os

    with tempfile.TemporaryDirectory(dir="/tmp") as d_sock:
        sock = Path(d_sock) / "mcp.sock"
        env = {  # HOME is required: adapters compute Path.home() constants at import
            "MACOS_APPS_MCP_SOCKET": str(sock),
            "PATH": "/usr/bin:/bin",
            "HOME": os.environ["HOME"],
        }
        d = subprocess.Popen(
            [sys.executable, "-m", "macos_apps_mcp", "daemon"], env=env
        )
        try:
            for _ in range(100):
                if sock.exists():
                    break
                __import__("time").sleep(0.1)
            assert sock.exists(), "daemon never bound its socket"
            probe = subprocess.run(  # live daemon → shim connects, EOF → clean exit
                [sys.executable, "-m", "macos_apps_mcp", "shim"],
                env=env,
                input=b"",  # immediate EOF: must exit 0 promptly, never hang
                timeout=30,
            )
            assert probe.returncode == 0
        finally:
            d.terminate()
            d.wait(timeout=10)


def test_shim_fail_fast_no_daemon():
    import os

    with tempfile.TemporaryDirectory(dir="/tmp") as d_sock:
        out = subprocess.run(
            [sys.executable, "-m", "macos_apps_mcp", "shim"],
            env={
                "MACOS_APPS_MCP_SOCKET": str(Path(d_sock) / "none.sock"),
                "PATH": "/usr/bin:/bin",
                "HOME": os.environ["HOME"],
            },
            capture_output=True,
            timeout=15,
        )
        assert out.returncode == 2
        assert b"install-agent" in out.stderr
