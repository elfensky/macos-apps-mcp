"""The Health page: what ``doctor`` reports right now (PLAT-02, D-14, RESEARCH C7).

``doctor.diagnose(request=False)`` reads EventKit status through ``runtime.run_native``,
which waits behind any native call on the one serialized worker (a bulk Mail pass holds
it for hours) and has no timeout. A page that called it on the event loop would freeze
the MCP server with it, and a reload-happy operator would queue a thread per click. So
the call runs in a worker thread, behind a lock that admits one call at a time, and the
request stops waiting after ``_WAIT`` seconds: it then renders what it knows without
the worker and says so. The abandoned thread finishes by itself and frees the lock.

Nothing here prompts: doctor runs in its read-only mode only, so no EventKit request
and no Apple Event leaves this page (D-14). "Open Settings" is a plain link.
"""

from __future__ import annotations

import json
import os
import threading
import time

import anyio

from .. import deploy, doctor, registry
from . import adapters
from .html import Safe, h, join
from .html import page as render_page

_lock = threading.Lock()  # held by the one thread that is running doctor
_last: dict | None = None  # the last full report, with the TCC read reasons
_dot: str | None = None  # the sidebar dot of the last full render
_WAIT = 10.0  # seconds a request waits for doctor before it renders the busy state
_STARTED = time.time()  # the daemon imports the dashboard at start: uptime
_BUSY = "worker busy, a native call is in flight"


def _run() -> dict | None:
    """Runs in a worker thread: the lock is taken and released here, in the same thread,
    so a request that gave up waiting can never leave it held. None when another call
    is already in flight."""
    global _last
    if not _lock.acquire(blocking=False):
        return None
    try:
        report = doctor.diagnose(request=False)
        # doctor reports the identities but not why a TCC database could not be read;
        # the reasons decide between "not asked" and "cannot tell" (PM-20).
        _last = {"report": report, "reasons": deploy.grant_report()["reasons"]}
        return _last
    finally:
        _lock.release()


def _up() -> str:
    m = int((time.time() - _STARTED) // 60)
    days, rest = divmod(m, 1440)
    hours, mins = divmod(rest, 60)
    if days:
        return f"up {days} d {hours} h"
    if hours:
        return f"up {hours} h {mins} min"
    return f"up {mins} min" if mins else "up under 1 min"


_NONE = Safe("")


def _row(dot, title, sub, *, locked=False, extra=_NONE, action=_NONE) -> Safe:
    return h(
        '<div class="row{}"><span class="dot {}"></span><div class="grow">'
        '<div class="title">{}</div><div class="sub">{}</div>{}</div>{}</div>',
        " locked" if locked else "",
        dot,
        title,
        sub,
        extra,
        action,
    )


def _kv(title, value) -> Safe:
    return h(
        '<div class="row"><div class="grow"><div class="title">{}</div></div>'
        '<span class="muted">{}</span></div>',
        title,
        value,
    )


def _daemon_row() -> Safe:
    if deploy.is_daemon_role():
        sub = f"Running as {deploy._BUNDLE_ID}, pid {os.getpid()}, {_up()}"
        return _row("ok", "Daemon", sub)
    sub = f"Not the daemon: a stdio process serves this page, pid {os.getpid()}"
    return _row("warn", "Daemon", sub)


def _adapters_row() -> Safe:
    st = registry.adapter_status()
    active, configured = st["registered"], st["configured"]
    pending = len(set(active) ^ set(configured))
    sub = f"{len(active)} active: " + ", ".join(a.capitalize() for a in active)
    if pending:
        sub += f" — {pending} pending restart"
    show = Safe('<a class="btn" href="/adapters">Show</a>') if pending else Safe("")
    return _row("warn" if pending else "ok", "Adapters", sub, action=show)


def _outbound_row() -> Safe:
    sending = registry.outbound_status()["registered"]
    sub = "Send enabled for: " + ", ".join(sending) if sending else "Send off"
    return _row(
        "ok",
        "Outbound",
        sub,
        locked=True,  # never changed from this page: the command is the control
        extra=adapters.cmd_box(adapters.outbound_command(sending)),
    )


def _surfaces(report: dict) -> dict[str, dict]:
    return {s.get("surface"): s for s in report.get("surfaces", [])}


def _fda_row(report: dict) -> Safe:
    s = _surfaces(report).get("full_disk_access", {})
    if s.get("ok") is True:
        return _row("ok", "Full Disk Access", "Granted")
    sub = s.get("remediation") or s.get("status") or "unknown"
    return _row("bad" if s.get("ok") is False else "", "Full Disk Access", sub)


def _eventkit_row(report: dict) -> Safe:
    surfaces = _surfaces(report)
    label = {"full_access": "full access", "adapter_off": "adapter is off"}
    parts, states = [], []
    for name in ("calendar", "reminders"):
        status = surfaces.get(name, {}).get("status", "unknown")
        states.append((surfaces.get(name, {}).get("ok"), status))
        parts.append(f"{name.capitalize()}: {label.get(status, status)}")
    sub = ", ".join(parts)
    if all(st == "full_access" for _, st in states):
        sub = "Calendar and Reminders: full access"
    live = [(ok, st) for ok, st in states if st != "adapter_off"]
    if any(st == "denied" for _, st in live):
        dot = "bad"
    elif any(ok is not True for ok, _ in live):
        dot = "warn"
    else:
        dot = "ok" if live else ""
    return _row(dot, "EventKit", sub)


def _deployment(request, report: dict | None) -> Safe:
    version = report["version"] if report else doctor._version()
    build = report["build"] if report else doctor._build_stamp()
    mode = "daemon" if deploy.is_daemon_role() else "stdio"
    return join(
        [
            _kv("Version", f"{version} · built {build}"),
            _kv("Mode", f"{mode}, pid {os.getpid()}, {_up()}"),
            _kv("Listens on", f"127.0.0.1:{request.app.state.port} (loopback only)"),
            _kv("Grant identity", deploy._BUNDLE_ID),
        ]
    )


def _render(request, got: dict | None, failure: str | None):
    report = got["report"] if got else None
    if report:
        rows = [
            _daemon_row(),
            _adapters_row(),
            _fda_row(report),
            _eventkit_row(report),
            _outbound_row(),
            _row("ok", "Mail backups", report["deployment"].get("mail_backups", "")),
        ]
        banner = Safe("")
        tail = h(
            '<details class="raw"><summary>Full doctor report</summary>'
            '<pre class="json">{}</pre></details>',
            json.dumps(report, indent=2, ensure_ascii=False, default=str),
        )
    else:
        rows = [_daemon_row(), _adapters_row()]
        if failure is None:
            rows.append(_row("", "EventKit", _BUSY))
        rows.append(_outbound_row())
        banner = (
            h(
                '<div class="banner bad"><span>●</span><div><b>doctor could not run:'
                "</b> {}</div></div>\n",
                failure,
            )
            if failure
            else Safe("")
        )
        tail = Safe(
            '<p class="muted note">The rest of the report waits for the native call '
            "that is running. Reload in a moment.</p>"
            if failure is None
            else ""
        )
    body = h(
        "<h1>Health</h1>\n"
        '<p class="lede">What <span class="mono">doctor</span> reports right now.</p>\n'
        '{}<div class="group health">{}</div>\n'
        '<div class="group-title">Deployment</div>\n'
        '<div class="group health">{}</div>\n{}',
        banner,
        join(rows),
        _deployment(request, report),
        tail,
    )
    return render_page(request, title="Health", active="health", body=body)


async def page(request):
    got, failure = None, None
    if not _lock.locked():  # a call in flight: render the busy state at once
        try:
            with anyio.move_on_after(_WAIT):
                got = await anyio.to_thread.run_sync(_run, abandon_on_cancel=True)
        except Exception as e:  # doctor itself failed: say so, never a 500
            failure = f"{type(e).__name__}: {e}"
    return _render(request, got, failure)
