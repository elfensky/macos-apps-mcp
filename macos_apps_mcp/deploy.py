"""Agent lifecycle + grant-identity reporting (#71). SMAppService registers plists
from the CALLING bundle — so register/unregister run as argv roles of the bundle
executable; the pip-side install-agent invokes them (never SMAppService directly)."""

from __future__ import annotations

import sqlite3
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
