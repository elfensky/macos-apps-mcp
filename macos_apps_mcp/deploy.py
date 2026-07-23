"""Agent lifecycle + grant-identity reporting (#71). SMAppService registers plists
from the CALLING bundle — so register/unregister run as argv roles of the bundle
executable; the pip-side install-agent invokes them (never SMAppService directly)."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from .errors import NativeError

_PLIST = "ren.lav.macos-apps-mcp.plist"
_TCC_DB = Path.home() / "Library/Application Support/com.apple.TCC/TCC.db"
_SERVICES = [
    "kTCCServiceCalendar",
    "kTCCServiceReminders",
    "kTCCServiceAddressBook",
    "kTCCServiceAppleEvents",
    "kTCCServiceSystemPolicyAllFiles",
]
# SMAppService.status() ints (ServiceManagement.h)
_STATUS = {0: "not-registered", 1: "enabled", 2: "requires-approval", 3: "not-found"}


def _agent_service():
    import Foundation
    from ServiceManagement import SMAppService

    if Foundation.NSBundle.mainBundle().bundleIdentifier() is None:
        raise NativeError(
            "not running from the .app bundle — SMAppService registers plists from "
            "the calling bundle. Build with scripts/build_app.sh and invoke the "
            "bundle executable. Do not retry from the venv."
        )
    return SMAppService.agentServiceWithPlistName_(_PLIST)


def register_agent() -> None:
    ok, err = _agent_service().registerAndReturnError_(None)
    if not ok:
        raise NativeError(f"SMAppService register failed: {err}")


def unregister_agent() -> None:
    ok, err = _agent_service().unregisterAndReturnError_(None)
    if not ok:
        raise NativeError(f"SMAppService unregister failed: {err}")


def agent_status() -> str:
    return _STATUS.get(int(_agent_service().status()), "unknown")


def grant_identities(services: list[str] | None = None) -> dict | None:
    """Which identity holds each TCC grant — None when TCC.db is unreadable
    (reading it needs FDA for OUR responsible process: the spec §E chicken-and-egg).
    Never raises; a wrong claim is worse than no claim."""
    wanted = services or _SERVICES
    try:
        conn = sqlite3.connect(f"file:{_TCC_DB}?mode=ro", uri=True)
        try:
            marks = ",".join("?" for _ in wanted)
            rows = conn.execute(
                f"SELECT service, client, auth_value FROM access "  # noqa: S608
                f"WHERE service IN ({marks})",
                wanted,
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    out: dict[str, list[dict]] = {}
    for service, client, auth in rows:
        out.setdefault(service, []).append({"client": client, "granted": auth == 2})
    return out


def _run_bundle_role(app: Path, role: str) -> None:
    # -E -s -P: ignore PYTHON* env vars, skip user site-packages, no unsafe
    # sys.path[0] prepend. Runtime must honor the same env-free guarantee that
    # scripts/build_app.sh smoke-tests with `env -i` — the bundled interpreter
    # must not let a caller's PYTHONPATH/PYTHONHOME/user-site shadow the
    # bundled macos_apps_mcp package or break getpath.
    exe = app / "Contents/MacOS/macos-apps-mcp"
    subprocess.run(
        [str(exe), "-E", "-s", "-P", "-m", "macos_apps_mcp", role],
        check=True,
        timeout=60,
    )


def _wait_for_socket(timeout: float = 30) -> None:
    from .daemon import socket_path

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if socket_path().exists():
            return
        time.sleep(0.25)
    raise NativeError("daemon socket never appeared — check `launchctl print` / logs")


def _request_grants_via_daemon() -> None:
    """Fire every consent prompt FROM the daemon process (bundle identity — prompts
    from this terminal would attach to the terminal instead). doctor(request=True)
    is the existing proactive-prompt pass."""
    import asyncio

    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport

    from .daemon import _uds_client_factory, socket_path

    async def go():
        transport = StreamableHttpTransport(
            "http://daemon/mcp", httpx_client_factory=_uds_client_factory(socket_path())
        )
        async with Client(transport) as c:
            await c.call_tool("doctor", {"request": True})

    asyncio.run(go())


def _quarantine_guard(app: Path) -> None:
    q = subprocess.run(
        ["xattr", "-p", "com.apple.quarantine", str(app)], capture_output=True
    )
    if q.returncode == 0:  # quarantined download — verify, then strip (translocation)
        try:
            subprocess.run(["spctl", "-a", str(app)], check=True)
        except subprocess.CalledProcessError:
            raise NativeError(
                "bundle failed Gatekeeper assessment — sign and notarize it "
                "(scripts/build_app.sh --sign … --notarize …), or remove the "
                "quarantine manually. Do not retry."
            ) from None
        subprocess.run(["xattr", "-dr", "com.apple.quarantine", str(app)], check=True)


def install_agent(argv: list[str]) -> None:
    app = Path("/Applications/macos-apps-mcp.app")
    if argv[:1] == ["--app"]:
        if len(argv) < 2:
            print("usage: install-agent [--app <path-to.app>]", file=sys.stderr)
            raise SystemExit(2)
        app = Path(argv[1])
    if not (app / "Contents/MacOS/macos-apps-mcp").exists():
        print(
            f"no bundle at {app} — build one with scripts/build_app.sh "
            "(then copy to /Applications)",
            file=sys.stderr,
        )
        raise SystemExit(2)
    _quarantine_guard(app)
    _run_bundle_role(app, "register")
    _wait_for_socket()
    _request_grants_via_daemon()
    exe = app / "Contents/MacOS/macos-apps-mcp"
    snippet = {
        "command": str(exe),
        "args": ["-E", "-s", "-P", "-m", "macos_apps_mcp", "shim"],
    }
    print(
        "Full Disk Access must be granted by hand — opening the pane:\n"
        "  open 'x-apple.systempreferences:com.apple.preference.security"
        "?Privacy_AllFiles'\n"
        f"Point each MCP client at the shim:\n{json.dumps(snippet, indent=2)}"
    )


def uninstall_agent() -> None:
    from .daemon import socket_path

    app = Path("/Applications/macos-apps-mcp.app")
    if (app / "Contents/MacOS/macos-apps-mcp").exists():
        _run_bundle_role(app, "unregister")
    socket_path().unlink(missing_ok=True)
    print(
        "agent unregistered. To wipe grants: tccutil reset All ren.lav.macos-apps-mcp"
    )
