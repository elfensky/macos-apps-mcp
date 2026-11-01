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
import sys
from pathlib import Path

# Off macOS the server must still import and list its tools; diagnose() refuses
# through runtime.require_macos().
if sys.platform == "darwin":
    import EventKit as EK
else:
    EK = None

from . import deploy, registry, runtime, tiers
from .adapters import mail_ids, mail_index
from .errors import ACCESSIBILITY_PANE, PRIVACY_PANE, NativeError, SchemaDrift
from .eventkit import request_access_each
from .runtime import app_process_info, run_native

# Apps reached via osascript/Automation — the adapters that aren't EventKit-native.
# Part of the add-an-adapter checklist (CLAUDE.md "Architecture"): a new
# Automation-backed adapter must add its app name here so doctor probes it.
# Photos is absent on purpose: its reads go through osxphotos under Full Disk Access
# (Phase 4), so doctor sends Photos no Apple Event.
_AUTOMATION_APPS = (
    "Mail",
    "Notes",
    "Contacts",
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
# #317: an app the probe itself launched can come up with no window and answer
# `count windows` with -1728. The event was delivered and answered, which is all the
# probe proves, so -1728 counts as ok; every other error, the -1743 denial included,
# re-raises with its original message and number, so runtime._classify_osascript_failure
# still types it.
_PROBE = (
    "on run argv\n"
    "  with timeout of 120 seconds\n"
    "    tell application (item 1 of argv)\n"
    "      try\n"
    "        count windows\n"
    "      on error errMsg number errNum\n"
    "        if errNum is not -1728 then error errMsg number errNum\n"
    "      end try\n"
    "    end tell\n"
    "  end timeout\n"
    "end run"
)
# Budget for the one-time Automation consent dialog — a human answer, same rationale as
# runtime._ACCESS_TIMEOUT; already-granted/denied probes return in well under a second.
_PROBE_TIMEOUT = 120.0

# A read of a TCC.db is gated by Full Disk Access, so a PermissionError vs a clean read
# cleanly separates FDA-denied from FDA-granted. The 0.5.0 sqlite read planes (chat.db,
# NoteStore.sqlite) need FDA — surface it now. The probe takes the first db that exists:
# macOS 27 has no per-user TCC.db at all (#261), only the system one. One declaration:
# deploy owns both paths (it also reads grant rows from them).
_FDA_PATHS = (deploy._TCC_DB, deploy._TCC_SYSTEM_DB)

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
    (
        ("calendar", EK.EKEntityTypeEvent, "Calendars"),
        ("reminders", EK.EKEntityTypeReminder, "Reminders"),
    )
    if EK is not None
    else ()
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
    # D-04: an OFF adapter's entity is neither read nor requested.
    on = [e for e in _EK_ENTITIES if tiers.adapter_enabled(e[0])]
    codes = {entity: _ek_status(entity) for _, entity, _ in on}
    if request and any(
        code == EK.EKAuthorizationStatusNotDetermined for code in codes.values()
    ):
        _try_request_access()
        codes = {entity: _ek_status(entity) for _, entity, _ in on}
    out = []
    for name, entity, pane in _EK_ENTITIES:
        if entity not in codes:
            out.append(_surface(name, "eventkit", None, "adapter_off"))
            continue
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


def _process_line(app: str) -> str:
    """The app's pid + uptime, so "did the force-quit actually restart it?" is
    answerable from a doctor report (#183 — a UI quit left a 37-minute-old wedged
    Mail process alive). ps-only, no Apple Event, no TCC."""
    info = app_process_info(app)
    if info is None:
        return "not running"
    return (
        f"pid {info['pid']}, up {info['etime']}, state {info['state']}, "
        f"{info['cpu']:.1f}% CPU"
    )


# Must equal the EVENTS targets of dashboard/grants.py ADAPTER_GRANTS, which doctor may
# not import (pinned by test_automation_bundle_ids_match_the_grant_map).
_AUTOMATION_BUNDLES = {
    "mail": "com.apple.mail",
    "notes": "com.apple.Notes",
    "contacts": "com.apple.AddressBook",
    "safari": "com.apple.Safari",
    "messages": "com.apple.MobileSMS",
    "music": "com.apple.Music",
}

# runtime.automation_permission OSStatus -> (status, ok); anything else is probe_error.
_AE_STATUS = {
    0: ("granted", True),
    -1743: ("denied", False),
    -1744: ("not_asked", None),
    -600: ("not_running", None),
}
_AE_REMEDIATION = {
    "denied": (
        f"Automation for {{app}} is off: switch it on in {PRIVACY_PANE} → Automation."
    ),
    "not_asked": (
        "{app} has not been asked yet: run doctor(request=True) with someone at the "
        "screen (one-time dialog)."
    ),
    "not_running": (
        "{app} is not running, so its Automation state cannot be told yet: open "
        "{app}, then run doctor again."
    ),
    "probe_error": (
        "Automation check returned OSStatus {rc}; run doctor(request=True) to probe "
        "by Apple Event."
    ),
}


def _live_automation(name: str, app: str) -> dict:
    """One Automation surface from the live, non-prompting check (no Apple Event)."""
    try:
        rc = runtime.automation_permission(_AUTOMATION_BUNDLES[name])
    except (OSError, AttributeError) as e:
        # A missing framework or symbol is reported, never raised — diagnosis is the
        # one place a swallowed error is correct (module docstring).
        return _surface(
            name,
            "automation",
            None,
            "probe_error",
            f"Automation check failed ({type(e).__name__}); run "
            "doctor(request=True) to probe by Apple Event.",
        )
    status, ok = _AE_STATUS.get(rc, ("probe_error", None))
    remediation = _AE_REMEDIATION.get(status, "").format(app=app, rc=rc)
    return _surface(name, "automation", ok, status, remediation or None)


def _automation_surfaces(request: bool) -> list[dict]:
    out = []
    for app in _AUTOMATION_APPS:
        name = app.lower()
        if not tiers.adapter_enabled(name):
            out.append(_surface(name, "automation", None, "adapter_off"))
            continue  # D-04: no Apple Event, no process line
        if not request:
            out.append(_live_automation(name, app))
        else:
            try:
                runtime.run_osascript(_PROBE, app, timeout=_PROBE_TIMEOUT)
                out.append(_surface(name, "automation", True, "ok"))
            except NativeError as e:
                # #47 already fingerprinted it (automation_denied / app_not_running /
                # …); str(e) is the agent-directed remediation. Report, don't raise.
                out.append(_surface(name, "automation", False, e.kind, str(e)))
        out[-1]["process"] = _process_line(app)
    return out


def _shortcuts_surface() -> dict:
    if not tiers.adapter_enabled("shortcuts"):
        return _surface("shortcuts_cli", "cli", None, "adapter_off")
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
    for path in _FDA_PATHS:
        try:
            with open(path, "rb") as f:
                f.read(1)
            return _surface("full_disk_access", "fda", True, "ok")
        except FileNotFoundError:
            continue
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
        except OSError as e:
            return _surface("full_disk_access", "fda", None, "error", str(e))
    return _surface(
        "full_disk_access",
        "fda",
        None,
        "unknown",
        f"no TCC.db found to probe ({', '.join(map(str, _FDA_PATHS))}).",
    )


# No restart clause: the seam reads the switch in a fresh process on every call
# (05.2-13 G2).
_AX_REMEDIATION = (
    "Accessibility is off for macos-apps-mcp, so mail_reply and reply_all refuse: "
    f"switch it on in {ACCESSIBILITY_PANE}."
)


def _accessibility_surface() -> dict:
    """The Accessibility grant the Mail reply tools need (FIX-16, #348). Only the plain
    trust read through the seam: it never prompts and sends no Apple Event (D-14)."""
    if not tiers.adapter_enabled("mail"):
        return _surface("accessibility", "accessibility", None, "adapter_off")
    try:
        trusted = runtime.accessibility_trusted()
    except Exception as e:  # PyObjC fails with ImportError/KeyError too: report it
        return _surface(
            "accessibility",
            "accessibility",
            None,
            "probe_error",
            f"Accessibility check failed ({type(e).__name__}); mail_reply and "
            "reply_all may refuse.",
        )
    if trusted:
        return _surface("accessibility", "accessibility", True, "granted")
    return _surface(
        "accessibility", "accessibility", False, "not_granted", _AX_REMEDIATION
    )


def _mail_index_surface() -> dict:
    """The Envelope Index schema (#199) — read-only and prompt-free, like the sqlite
    reads it stands for. A pre-Tahoe macOS reports ok=False carrying the platform-
    floor diagnosis; before this surface existed, doctor said "no denied surfaces"
    on a machine where every sqlite-backed mail read was broken. FDA-unreadable is
    ok=None (indeterminate), not False — the full_disk_access surface already owns
    that failure, and double-counting it would misname the problem."""
    try:
        status = mail_index.check_index_schema()
    except SchemaDrift as e:
        return _surface("mail_index", "sqlite", False, "schema_unsupported", str(e))
    except NativeError as e:
        return _surface("mail_index", "sqlite", None, e.kind, str(e))
    if status == "no_mail_data":
        return _surface(
            "mail_index",
            "sqlite",
            None,
            "no_mail_data",
            "No Envelope Index found — open Mail once to create it.",
        )
    if status == "sidecar":
        # #201: a pre-Tahoe store served through the Message-ID sidecar. ok=True —
        # the plane works — with coverage as remediation-free detail, because a
        # partial or stale sidecar degrades the DETAIL, never the verdict (the reads
        # themselves carry staleness honesty).
        out = _surface("mail_index", "sqlite", True, "sidecar")
        out["coverage"] = mail_ids.coverage_line(mail_index.require_index_path())
        return out
    return _surface("mail_index", "sqlite", True, "ok")


def _process_name(pid: int) -> str:
    """Best-effort executable path for a pid (no TCC needed). ponytail: immediate parent
    only — walk the ancestor chain to the first *.app if the .app is ever ambiguous."""
    try:
        proc = runtime.tracked_run(["ps", "-o", "comm=", "-p", str(pid)], timeout=5.0)
    except (OSError, subprocess.SubprocessError):
        return f"pid {pid}"
    return proc.stdout.strip() or f"pid {pid}"


def _responsible_process() -> str:
    ppid = os.getppid()
    return f"{_process_name(os.getpid())} (this), launched by {_process_name(ppid)}"


def version(dist: str = "macos-apps-mcp") -> str:
    """The version of the code actually SERVING this call. The daemon is a separate
    long-lived process from the repo you edit — it sat three releases behind for weeks
    with nothing surfacing the gap. Rebuild + `launchctl kickstart -k` when this trails
    the repo. ``libs`` reuses it for the bundled libraries, and the dashboard footer
    reads it too (#430 IN-02): one lookup, one fallback."""
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as dist_version

    try:
        return dist_version(dist)
    except PackageNotFoundError:
        return "unknown"


# Baked into the installed package by scripts/build_app.sh — absent in a dev checkout.
_BUILD_STAMP_PATH = Path(__file__).with_name("build_stamp")


def build_stamp() -> str:
    """Which BUILD is serving this call (#143) — `version` alone cannot see a
    same-version rebuild (every 0.x.y re-deploy sits in that gap). The stamp is
    `<short-sha> <utc-build-time>`, written by scripts/build_app.sh; a dev checkout
    has no stamp file and honestly reports "dev"."""
    try:
        return _BUILD_STAMP_PATH.read_text().strip() or "dev"
    except OSError:
        return "dev"


def _outbound_state() -> dict[str, list[str]]:
    """The registered vs configured outbound adapters (#130, C6), read from the
    registration record. doctor.py imports down into registry.py, never up into
    server.py — the former lazy reach-in into the server module (a local import
    inside this very function) is gone (GATE-03). Card 2 (GATE-04, RESEARCH
    Pitfall 3): the registry is the ONE outbound ledger now — this used to read a
    provisional second ledger in ``tiers.py`` that card 5 introduced before
    ``registry.py`` existed."""
    return registry.outbound_status()


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
    triggers the EventKit consent prompt and runs the Automation probes. Refuses off
    macOS with ``UnsupportedPlatform``.
    """
    runtime.require_macos()
    surfaces = [
        *_eventkit_surfaces(request),
        *_automation_surfaces(request),
        _shortcuts_surface(),
        _fda_surface(),
        _accessibility_surface(),
        _mail_index_surface(),
    ]
    # An OFF adapter's surface is not probed, so it is neither a need nor unverified.
    probed = [s for s in surfaces if s["status"] != "adapter_off"]
    needs = [s["surface"] for s in probed if s["ok"] is False]
    unknown = [s["surface"] for s in probed if s["ok"] is None]
    if needs:
        summary = (
            f"{len(needs)} of {len(probed)} surfaces need attention: "
            + ", ".join(needs)
        )
    else:
        # An unprobeable surface (ok=None) must not be counted as OK.
        summary = (
            f"all {len(probed)} surfaces OK"
            if not unknown
            else f"no denied surfaces; {len(unknown)} unverified: " + ", ".join(unknown)
        )

    grants = deploy.grant_report()
    ids = grants["identities"]
    try:
        agent = deploy.agent_status()
    except Exception as e:  # not in a bundle / SM bridge absent — report, don't die
        agent = f"unavailable: {e}"
    ob = _outbound_state()
    outbound = ob["registered"]  # what this process actually serves, not the config
    deployment = {
        # argv, not the env var alone — see deploy.is_daemon_role()
        "mode": "daemon" if deploy.is_daemon_role() else "stdio",
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
            'granted=False plus status="limited" — not a plain denial. A '
            'reason="prompt-timeout" entry is a consent prompt nobody answered, which '
            "macOS keeps as a denial (#318): run its `remediation` command, then "
            "doctor(request=True) with someone at the screen."
        ),
    }
    # A PARTIAL read (one db answered, the other did not) still has to say so. FDA rows
    # live only in the SYSTEM db (#123), so an unreadable system db yields an identity
    # map with no FDA row — indistinguishable, to the reader, from "FDA not granted".
    # That is the misdiagnosis C7 exists to end; reporting it only when BOTH dbs fail
    # left it alive in exactly the case it started as. An ABSENT user db is not a
    # partial read: macOS 27 has no per-user TCC.db at all (#261).
    failed = {
        k: v for k, v in grants["reasons"].items() if v and (k, v) != ("user", "absent")
    }
    if ids is not None and failed:
        deployment["note"] += " PARTIAL read — " + ", ".join(
            f"{k} db: {v}" for k, v in failed.items()
        )
    # Adapter deny-list (PLAT-01, D-03/D-05): `adapters` is what this process serves,
    # `adapters_off` what it does not. No CLI twin — the note names the file instead.
    ad = registry.adapter_status()
    known = set(registry.adapter_names())
    deployment["adapters"] = ad["registered"]
    deployment["adapters_off"] = sorted(known - set(ad["registered"]))
    deployment["adapters_note"] = (
        "OFF adapters: a comma list in ~/.local/state/macos-apps-mcp/adapters_off; "
        "apply: launchctl kickstart -k gui/$(id -u)/ren.lav.macos-apps-mcp."
    )
    off = tiers.adapters_off()
    if unknown_adapters := off - known - {deploy.ADAPTERS_ALL_OFF}:
        # operator input, so unbounded in count AND length: three names of at most 40
        # characters keep the report in budget
        names = sorted(n if len(n) <= 40 else n[:40] + "…" for n in unknown_adapters)
        deployment["adapters_unknown"] = names[:3] + (
            [f"+{len(names) - 3} more"] if len(names) > 3 else []
        )
    if deploy.ADAPTERS_ALL_OFF in off:
        deployment["adapters_note"] += (
            " The adapters_off file exists but cannot be read, so every adapter is off"
            " until it is readable."
        )
    if ad["configured"] != ad["registered"]:
        deployment["adapters_pending"] = ad["configured"]
        deployment["adapters_note"] += (
            " Changed since launch: restart the daemon to apply adapters_pending."
        )
    # Daemon role only: only the daemon serves the dashboard (and the stdio budget test
    # stays as it is). The note never reads the key file.
    if deploy.is_daemon_role():
        # D-07: read here, not stored in deploy.py: only the daemon module knows
        # whether the dashboard bound, and in the daemon role it is already loaded
        # (the stdio server never reaches this branch, so it never imports it).
        from . import daemon

        if daemon.dashboard_state:
            deployment["dashboard"] = daemon.dashboard_state
        deployment["dashboard_note"] = (
            "pages need the page key: the USER runs `macos-apps-mcp dashboard`."
        )
    # Registration is fixed at import; the toggle/env is re-read per call. When they
    # differ (allow-send flipped the toggle but the daemon kept running — deploy's
    # "no daemon restarted" branch), say so instead of reporting config as live state.
    if ob["configured"] != ob["registered"]:
        deployment["outbound_pending"] = ob["configured"]
        deployment["outbound_note"] += (
            " Changed since launch: restart the daemon to apply outbound_pending."
        )

    # #163: the recoverable plane keeps every backup forever (no pruning code exists, on
    # purpose — see mail_recover), so the ONE thing that makes that safe is saying out
    # loud how much disk it holds. Terse for the same token-budget reason as
    # outbound_note; the advisory that fires past the threshold carries the remedy.
    from .adapters.mail_recover import backup_usage

    usage = backup_usage()
    # The absolute path is deliberately NOT here: it is long, it rides in every report,
    # and the advisory that fires past the threshold carries it with the rm command.
    deployment["mail_backups"] = (
        f"{usage['bytes'] / 1024**2:.1f} MB in {usage['receipts']} receipts"
        + (f" (oldest {usage['oldest']})" if usage["oldest"] else "")
        + ", kept forever in <state>/backup/mail"
    )

    return {
        "version": version(),
        "build": build_stamp(),
        # #285: a bundle once shipped another mcp than uv.lock; this shows the bundled
        # versions without opening the bundle.
        "libs": {name: version(name) for name in ("mcp", "fastmcp")},
        "responsible_process": _responsible_process(),
        "note": (
            "Grant each permission to the launching app (above). Automation and "
            "Accessibility need no restart; Full Disk Access, Calendars and Reminders "
            "may need one."
        ),
        "probed_automation": request,
        "summary": summary,
        "surfaces": surfaces,
        "deployment": deployment,
    }
