"""Agent lifecycle + grant-identity reporting (#71). SMAppService registers plists
from the CALLING bundle — so register/unregister run as argv roles of the bundle
executable; the pip-side install-agent invokes them (never SMAppService directly)."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from .errors import NativeError

_PLIST = "ren.lav.macos-apps-mcp.plist"
_BUNDLE_ID = _PLIST.removesuffix(".plist")  # our signed .app's CFBundleIdentifier
_TCC_DB = Path.home() / "Library/Application Support/com.apple.TCC/TCC.db"
# FDA (kTCCServiceSystemPolicyAllFiles) rows live in the SYSTEM db, not the user one
# (#123 — found during #71 acceptance: FDA granted + functional, yet invisible here).
_TCC_SYSTEM_DB = Path("/Library/Application Support/com.apple.TCC/TCC.db")
_SERVICES = [
    "kTCCServiceCalendar",
    "kTCCServiceReminders",
    "kTCCServiceAddressBook",
    "kTCCServiceAppleEvents",
    "kTCCServiceSystemPolicyAllFiles",
]
# SMAppService.status() ints (ServiceManagement.h)
_STATUS = {0: "not-registered", 1: "enabled", 2: "requires-approval", 3: "not-found"}


def _main_bundle_id():
    """The running process's main-bundle CFBundleIdentifier (None off-bundle). A one-
    line seam so the bundle-gate is testable by injection, not by whatever the test
    host's Python reports."""
    import Foundation

    return Foundation.NSBundle.mainBundle().bundleIdentifier()


def _agent_service():
    # Must be OUR signed bundle, not merely SOME bundle: a venv/CI Python can itself be
    # a bundle with an identifier (e.g. org.python.python on the GitHub runner), so an
    # `is None` check let this proceed off-bundle and register the wrong plist. Pin
    # the exact CFBundleIdentifier. Guard BEFORE importing ServiceManagement so the
    # off-bundle error path never depends on that framework.
    if _main_bundle_id() != _BUNDLE_ID:
        raise NativeError(
            "not running from the ren.lav.macos-apps-mcp .app bundle — SMAppService "
            "registers plists from the calling bundle. Build with scripts/build_app.sh "
            "and invoke the bundle executable. Do not retry from the venv."
        )
    from ServiceManagement import SMAppService

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


def _tcc_rows(db: Path, wanted: list[str]) -> list | None:
    """Rows from ONE TCC db, or None if unreadable. Values bound; only `?` marks
    are interpolated."""
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            marks = ",".join("?" for _ in wanted)
            return conn.execute(
                f"SELECT service, client, auth_value FROM access "  # noqa: S608
                f"WHERE service IN ({marks})",
                wanted,
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return None


def grant_identities(services: list[str] | None = None) -> dict | None:
    """Which identity holds each TCC grant — merged from the USER db and the SYSTEM
    db (FDA rows live only in the latter, #123). None when NEITHER is readable
    (reading either needs FDA for OUR responsible process: the spec §E
    chicken-and-egg). Never raises; a wrong claim is worse than no claim."""
    wanted = services or _SERVICES
    per_db = [_tcc_rows(db, wanted) for db in (_TCC_DB, _TCC_SYSTEM_DB)]
    if all(rows is None for rows in per_db):
        return None
    out: dict[str, list[dict]] = {}
    for rows in per_db:
        for service, client, auth in rows or []:
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
            await c.call_tool("doctor", {"request": True}, timeout=200)

    try:
        # Hard ceiling (#123): the streamable-http client can hang in TEARDOWN after
        # the doctor call already completed (seen once during #71 acceptance). The
        # prompts fired server-side by then, so a timeout here is a note, not a
        # failure — never leave install-agent wedged on a cosmetic close.
        asyncio.run(asyncio.wait_for(go(), timeout=240))
    except TimeoutError:
        print(
            "note: prompt pass finished but the connection close timed out "
            "(harmless); continuing.",
            file=sys.stderr,
        )


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


# Home-relative, and deliberately NOT audit.state_dir() — same rationale as the daemon
# socket (see the comment above daemon._DEFAULT_SOCKET_DIR): three processes must agree
# on this path — the launchd daemon that READS it (no shell env at all), the
# shell-invoked `allow-send` that WRITES it, and a client-spawned shim — and
# XDG_STATE_HOME is not guaranteed identical across them. Routing this through
# state_dir() (as #141 briefly did) makes the consent gate fail OPEN: an operator with
# XDG_STATE_HOME exported runs `macos-apps-mcp allow-send off`, the write and the
# confirming read both land in the XDG dir, and the daemon keeps reading the home path
# and keeps send_mail/reply_all/forward_mail registered while telling the operator the
# gate is closed. Tests isolate this by monkeypatching the constant itself (see
# tests/conftest.py), never by moving the path.
_ALLOW_SEND_FILE = Path.home() / ".local/state/macos-apps-mcp/allow_send"


def allow_send_file() -> str:
    """The persisted outbound opt-in (``""`` when absent) — see server._allow_send."""
    try:
        return _ALLOW_SEND_FILE.read_text()
    except OSError:
        return ""


def allow_send(argv: list[str]) -> None:
    """`allow-send [mail|messages|all|off]` — show or set the outbound gate, then
    restart the daemon so it re-registers. Deliberately NOT an MCP tool: the gate is the
    operator's consent, so the model must not be able to grant itself sending (and the
    restart would drop the caller's own connection)."""
    current = allow_send_file().strip()
    if not argv:
        print(current or "off")
        return
    value = "" if argv[0] in ("off", "none", "") else argv[0]
    _ALLOW_SEND_FILE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _ALLOW_SEND_FILE.write_text(value)
    # Registration happens at import, so the running daemon still has the old gate.
    # No agent registered (stdio-only user) → nothing to restart, and that is fine.
    kick = subprocess.run(
        ["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{_BUNDLE_ID}"],
        capture_output=True,
        text=True,
    )
    print(
        f"outbound: {value or 'off'}"
        + (
            "\ndaemon restarted — reconnect your MCP client"
            if kick.returncode == 0
            else f"\nno daemon restarted ({kick.stderr.strip()}); restart your "
            "stdio server for this to take effect"
        )
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
