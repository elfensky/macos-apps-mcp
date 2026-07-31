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

import EventKit as EK

from . import deploy
from .errors import PRIVACY_PANE, NativeError
from .runtime import request_access_each, run_native, run_osascript

# Apps reached via osascript/Automation — the adapters that aren't EventKit-native.
# Part of the add-an-adapter checklist (CLAUDE.md "Architecture"): a new
# Automation-backed adapter must add its app name here so doctor probes it.
_AUTOMATION_APPS = (
    "Mail",
    "Notes",
    "Contacts",
    "Photos",
    "Safari",
    "Messages",
    "Music",
)

# The app name is passed via argv (never interpolated), matching the injection-safe
# osascript convention even though these targets are constants. name/id/version/
# running/frontmost are host-resolved since AppleScript 10.5 — no Apple event, no TCC
# check — so a probe asking for them proves nothing; it must send a REAL event, and
# `count windows` is the cheapest read-only command that does. Trade-off: it launches
# a quit app, and a never-authorized one can surface the one-time consent dialog.
# with timeout (#56's second line of defense): self-terminates a hung child even if
# the Python side died first — this probe launches each quit app in turn, making it
# the template most likely to strand an orphan. test_applescript_timeout.py sweeps
# only the adapters package, so this one is pinned by test_doctor.py instead.
_PROBE = (
    "on run argv\n"
    "  with timeout of 120 seconds\n"
    "  tell application (item 1 of argv) to count windows\n"
    "  end timeout\n"
    "end run"
)
# Budget for the one-time Automation consent dialog — a human answer, same rationale as
# runtime._ACCESS_TIMEOUT; already-granted/denied probes return in well under a second.
_PROBE_TIMEOUT = 120.0

# A read of this path is gated by Full Disk Access and it always exists on macOS, so a
# PermissionError vs a clean read cleanly separates FDA-denied from FDA-granted. The
# 0.5.0 sqlite read planes (chat.db, NoteStore.sqlite) need FDA — surface it now.
# One declaration: deploy owns the user TCC.db path (it also reads grant rows from it).
_FDA_PATH = deploy._TCC_DB

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


def _version() -> str:
    """The version of the code actually SERVING this call. The daemon is a separate
    long-lived process from the repo you edit — it sat three releases behind for weeks
    with nothing surfacing the gap. Rebuild + `launchctl kickstart -k` when this trails
    the repo."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("macos-apps-mcp")
    except PackageNotFoundError:
        return "unknown"


def _outbound_state() -> dict[str, list[str]]:
    """``server.outbound_status()`` — registered vs configured outbound adapters
    (#130, C6). Imported LOCALLY: ``server.py`` does ``from .doctor import diagnose``
    at module level, so a module-level `import server` here would be circular — this
    is the one place doctor.py reaches into server.py, and it does so lazily."""
    from . import server

    return server.outbound_status()


def _tcc_note(reasons: dict[str, str | None]) -> str:
    """Why the grant-identity report is empty — the CLASSIFIED reason (C7), not an
    unconditional FDA blame: a missing db, schema drift, and an FDA denial used to
    collapse into the same swallowed None."""
    detail = ", ".join(f"{k} db: {v or 'ok'}" for k, v in reasons.items())
    if "no-full-disk-access" in reasons.values():
        return (
            f"TCC.db unreadable ({detail}) — grant Full Disk Access (FDA) to THIS "
            "process's responsible identity (grant it, or run via the daemon)."
        )
    return f"TCC.db unreadable ({detail}) — not an FDA denial; see the reason codes."


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

    grants = deploy.grant_report()
    ids = grants["identities"]
    try:
        agent = deploy.agent_status()
    except Exception as e:  # not in a bundle / SM bridge absent — report, don't die
        agent = f"unavailable: {e}"
    ob = _outbound_state()
    outbound = ob["registered"]  # what this process actually serves, not the config
    deployment = {
        "mode": "daemon"
        if os.environ.get("MACOS_APPS_MCP_ROLE") == "daemon"
        else "stdio",
        "agent": agent,
        "grant_identities": ids,
        "outbound": outbound,
        # Terse by design: this rides in EVERY doctor report and the whole report has a
        # hard context budget (test_report_stays_under_token_budget). The daemon's
        # launchctl steps live in README "Outbound (send) mode", not here.
        "outbound_note": (
            "sending ON for: " + ", ".join(outbound)
            if outbound
            else "sending OFF — the USER (not the model) enables it by running "
            "`macos-apps-mcp allow-send mail`, which restarts the daemon; a client env "
            "block cannot reach it (see README 'Outbound (send) mode')."
        ),
        "note": (
            _tcc_note(grants["reasons"])
            if ids is None
            else "grants listed per identity; the daemon identity is "
            "ren.lav.macos-apps-mcp. A limited(3) grant (partial access) reports "
            'granted=False plus status="limited" — not a plain denial.'
        ),
    }
    # A PARTIAL read (one db answered, the other did not) still has to say so. FDA rows
    # live only in the SYSTEM db (#123), so an unreadable system db yields an identity
    # map with no FDA row — indistinguishable, to the reader, from "FDA not granted".
    # That is the misdiagnosis C7 exists to end; reporting it only when BOTH dbs fail
    # left it alive in exactly the case it started as.
    if ids is not None and any(grants["reasons"].values()):
        deployment["note"] += " PARTIAL read — " + ", ".join(
            f"{k} db: {v}" for k, v in grants["reasons"].items() if v
        )
    # Registration is fixed at import; the toggle/env is re-read per call. When they
    # differ (allow-send flipped the toggle but the daemon kept running — deploy's
    # "no daemon restarted" branch), say so instead of reporting config as live state.
    if ob["configured"] != ob["registered"]:
        deployment["outbound_pending"] = ob["configured"]
        deployment["outbound_note"] += (
            " Outbound config changed since this process launched (configured: "
            + (", ".join(ob["configured"]) or "none")
            + ") — restart the daemon to apply it."
        )

    return {
        "version": _version(),
        "responsible_process": _responsible_process(),
        "note": (
            "TCC attributes permissions to the process that launched macos-apps-mcp "
            "(above). Grant each permission to THAT app, then restart macos-apps-mcp."
        ),
        "probed_automation": request,
        "summary": summary,
        "surfaces": surfaces,
        "deployment": deployment,
    }
