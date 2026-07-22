"""Doctor — one-shot, read-only permission + health self-diagnosis (#48).

TCC failure is the ecosystem's #1 support burden: every surveyed server documents the
pain, none ships a programmatic diagnosis, so users are left guessing which Settings
pane to open (griches #10 was a permanent dead-end where no prompt ever appeared).
``diagnose()`` reports, per surface, the exact authorization state + the precise
remediation, and names the **responsible process** — TCC attributes grants to whatever
launched the server (Claude Desktop vs a terminal differ), so the user must grant
permission to *that* app.

Read-only and prompt-free by default: EventKit status is *read* (never requested), and
the Automation probes — which can surface a one-time consent dialog for a never-used
app — run only when called with ``request=True``. Every probe is classified through the
shared error taxonomy (errors.py, #47); a denied surface is *reported*, never raised —
diagnosis is the one place a swallowed error is correct, because it re-emerges as an
explicit report line carrying the same directive.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import EventKit as EK

from .errors import PRIVACY_PANE, NativeError
from .runtime import request_access_each, run_native, run_osascript

# Apps reached via osascript/Automation — the adapters that aren't EventKit-native.
# Part of the add-an-adapter checklist (CLAUDE.md "Architecture"): a new
# Automation-backed adapter must add its app name here so doctor probes it.
_AUTOMATION_APPS = ("Mail", "Notes", "Contacts", "Photos", "Safari", "Messages")

# The app name is passed via argv (never interpolated), matching the injection-safe
# osascript convention even though these targets are constants. name/id/version/
# running/frontmost are host-resolved since AppleScript 10.5 — no Apple event, no TCC
# check — so a probe asking for them proves nothing; it must send a REAL event, and
# `count windows` is the cheapest read-only command that does. Trade-off: it launches
# a quit app, and a never-authorized one can surface the one-time consent dialog.
_PROBE = "on run argv\n  tell application (item 1 of argv) to count windows\nend run"
# Budget for the one-time Automation consent dialog — a human answer, same rationale as
# runtime._ACCESS_TIMEOUT; already-granted/denied probes return in well under a second.
_PROBE_TIMEOUT = 120.0

# A read of this path is gated by Full Disk Access and it always exists on macOS, so a
# PermissionError vs a clean read cleanly separates FDA-denied from FDA-granted. The
# 0.5.0 sqlite read planes (chat.db, NoteStore.sqlite) need FDA — surface it now.
_FDA_PATH = Path.home() / "Library/Application Support/com.apple.TCC/TCC.db"

# EKAuthorizationStatus integer values (stable across SDKs — map by value, not by
# constant name, so a missing WriteOnly symbol on an older pyobjc can't crash import).
_EK_STATUS = {
    0: "not_determined",
    1: "restricted",
    2: "denied",
    3: "full_access",
    4: "write_only",
}
_EK_ENTITIES = (
    ("calendar", EK.EKEntityTypeEvent, "Calendars"),
    ("reminders", EK.EKEntityTypeReminder, "Reminders"),
)


def _surface(
    name: str, kind: str, ok: bool | None, status: str, remediation: str | None = None
) -> dict:
    """One surface's verdict. ``ok`` is None when a surface is unprobed/indeterminate —
    distinct from False (probed and failing), so the summary never over-reports."""
    out: dict = {"surface": name, "kind": kind, "ok": ok, "status": status}
    if remediation:
        out["remediation"] = remediation
    return out


def _ek_status(entity: int) -> int:
    """Read one EventKit surface's authorization status. A class method that only
    *reads* TCC — never prompts — so it's safe in the default read-only path."""
    return run_native(lambda: EK.EKEventStore.authorizationStatusForEntityType_(entity))


def _try_request_access() -> None:
    """request=True: trigger the EventKit consent prompt for any not-yet-determined
    surface, then let the caller re-read status. A denial isn't fatal to a diagnosis —
    request_access_each is per-entity and non-fatal, and the caller's re-read reports
    the resulting (denied) status."""
    run_native(request_access_each)


def _eventkit_surfaces(request: bool) -> list[dict]:
    codes = {entity: _ek_status(entity) for _, entity, _ in _EK_ENTITIES}
    if request and any(
        code == EK.EKAuthorizationStatusNotDetermined for code in codes.values()
    ):
        _try_request_access()
        codes = {entity: _ek_status(entity) for _, entity, _ in _EK_ENTITIES}
    out = []
    for name, entity, pane in _EK_ENTITIES:
        code = codes[entity]
        status = _EK_STATUS.get(code, f"unknown({code})")
        ok = code == EK.EKAuthorizationStatusFullAccess
        remediation = (
            None
            if ok
            else (
                f"Grant full access in {PRIVACY_PANE} → {pane}, then restart "
                "macos-apps-mcp."
            )
        )
        out.append(_surface(name, "eventkit", ok, status, remediation))
    return out


def _automation_surfaces(request: bool) -> list[dict]:
    out = []
    for app in _AUTOMATION_APPS:
        name = app.lower()
        if not request:
            out.append(
                _surface(
                    name,
                    "automation",
                    None,
                    "unprobed",
                    f"Run doctor(request=True) to probe Automation consent for {app} "
                    "(a never-authorized app may show a one-time dialog).",
                )
            )
            continue
        try:
            run_osascript(_PROBE, app, timeout=_PROBE_TIMEOUT)
            out.append(_surface(name, "automation", True, "ok"))
        except NativeError as e:
            # #47 already fingerprinted it (automation_denied / app_not_running / …);
            # str(e) is the agent-directed remediation. Report, don't raise.
            out.append(_surface(name, "automation", False, e.kind, str(e)))
    return out


def _shortcuts_surface() -> dict:
    present = shutil.which("shortcuts") is not None
    return _surface(
        "shortcuts_cli",
        "cli",
        present,
        "present" if present else "missing",
        None
        if present
        else "The `shortcuts` CLI is missing (it ships with macOS 12+). Update macOS.",
    )


def _fda_surface() -> dict:
    try:
        with open(_FDA_PATH, "rb") as f:
            f.read(1)
        return _surface("full_disk_access", "fda", True, "ok")
    except PermissionError:
        return _surface(
            "full_disk_access",
            "fda",
            False,
            "denied",
            f"Grant Full Disk Access in {PRIVACY_PANE} → Full Disk Access to the "
            "app that launched macos-apps-mcp, then restart it (needed for sqlite "
            "read planes).",
        )
    except FileNotFoundError:
        return _surface(
            "full_disk_access",
            "fda",
            None,
            "unknown",
            f"{_FDA_PATH} not found to probe.",
        )
    except OSError as e:
        return _surface("full_disk_access", "fda", None, "error", str(e))


def _process_name(pid: int) -> str:
    """Best-effort executable path for a pid (no TCC needed). ponytail: immediate parent
    only — walk the ancestor chain to the first *.app if the .app is ever ambiguous."""
    try:
        proc = subprocess.run(
            ["ps", "-o", "comm=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return f"pid {pid}"
    return proc.stdout.strip() or f"pid {pid}"


def _responsible_process() -> str:
    ppid = os.getppid()
    return f"{_process_name(os.getpid())} (this), launched by {_process_name(ppid)}"


def diagnose(request: bool = False) -> dict:
    """Per-surface macOS permission + health report with exact remediation (#48).

    ``request=False`` (default) is read-only and prompt-free. ``request=True`` also
    triggers the EventKit consent prompt and runs the Automation probes.
    """
    surfaces = [
        *_eventkit_surfaces(request),
        *_automation_surfaces(request),
        _shortcuts_surface(),
        _fda_surface(),
    ]
    needs = [s["surface"] for s in surfaces if s["ok"] is False]
    unknown = [s["surface"] for s in surfaces if s["ok"] is None]
    if needs:
        summary = (
            f"{len(needs)} of {len(surfaces)} surfaces need attention: "
            + ", ".join(needs)
        )
    elif request:
        # An unprobeable surface (ok=None) must not be counted as OK.
        summary = (
            f"all {len(surfaces)} surfaces OK"
            if not unknown
            else f"no denied surfaces; {len(unknown)} unverified: " + ", ".join(unknown)
        )
    else:
        summary = "no denied surfaces; Automation unprobed — run doctor(request=True)"
    return {
        "responsible_process": _responsible_process(),
        "note": (
            "TCC attributes permissions to the process that launched macos-apps-mcp "
            "(above). Grant each permission to THAT app, then restart macos-apps-mcp."
        ),
        "probed_automation": request,
        "summary": summary,
        "surfaces": surfaces,
    }
