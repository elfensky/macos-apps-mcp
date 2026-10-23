"""The Adapters page: switch an app on or off, see what waits for a restart (D-11).

Two write endpoints exist on the whole dashboard and both live here: the toggle
(``POST /adapters``) and, from the restart bar, ``POST /restart``. Both sit behind the
Guard (Host, Origin, token). A toggle rewrites the ``adapters_off`` file and logs itself
with ``audit.audit_write`` as caller ``dashboard``: it goes around ``AuditMiddleware``
and never counts as a tool call in the usage tally (D-15).
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from urllib.parse import parse_qs

from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.responses import PlainTextResponse, RedirectResponse

from .. import audit, deploy, registry, tiers
from . import grants
from .html import Safe, h, join
from .html import page as render_page

log = logging.getLogger(__name__)

_write_lock = threading.Lock()  # one read-modify-write of the file at a time
# The last dashboard audit write failed. Assigned only under ``_write_lock``; shown on
# the Adapters page until the next good write (owner default O3, #430 WR-06).
_audit_lost = False
_LOST_NOTE = (
    "The last change was applied, but its audit record could not be written to "
    "audit.jsonl, so the Writes page does not show it. Check free disk space and the "
    "permissions of ~/.local/state/macos-apps-mcp."
)
_ENV_NOTE = (
    "MACOS_APPS_ADAPTERS_OFF is set for this daemon and wins over the file. "
    "Unset it to use these switches."
)
# D-20: a file that exists but cannot be read turns every adapter off (tiers.py). A
# write would replace what the operator meant with a guess, so the switches lock.
_UNREADABLE_NOTE = (
    "The adapters_off file cannot be read, so every adapter is off after a restart. "
    "Fix the file's permissions, then reload this page."
)


def _lock_reason() -> str | None:
    """Why the switches are locked, or None when they work."""
    if os.environ.get("MACOS_APPS_ADAPTERS_OFF", "").strip():
        return _ENV_NOTE
    if deploy.ADAPTERS_ALL_OFF in tiers.adapters_off():
        return _UNREADABLE_NOTE
    return None


def _sub(adapter: str, calls: dict[str, dict]) -> str:
    """``Automation · Full Disk Access · 27 tools · 3 calls`` (no calls: left out)."""
    tools = [n for n, r in registry.TOOLS.items() if r.adapter == adapter]
    perms = {p for n in tools for p in registry.TOOLS[n].permission}
    used = sum(calls.get(n, {}).get("count", 0) for n in tools)
    live = sum(registry.TOOLS[n].registered for n in tools)  # what this process serves
    parts = [*sorted(perms), f"{live} tool{'' if live == 1 else 's'}"]
    if used:
        parts.append(f"{used} call{'' if used == 1 else 's'}")
    return " · ".join(parts)


def _chips(grant: str | None, after_restart: bool | None) -> Safe:
    """The grant chip (denied / not asked) and the pending chip, when they apply."""
    out = []
    if grant in ("denied", "not asked"):
        out.append(
            h(
                '<span class="chip{}">{}</span>',
                " danger" if grant == "denied" else "",
                grant,
            )
        )
    if after_restart is not None:
        out.append(
            h(
                '<span class="chip pending">{} after restart</span>',
                "on" if after_restart else "off",
            )
        )
    return join(out)


def _hidden(token: str, **fields) -> Safe:
    return join(
        h('<input type="hidden" name="{}" value="{}">', k, v)
        for k, v in {"token": token, **fields}.items()
    )


def _pending(known: list[str]) -> list[tuple[str, bool]]:
    """(adapter, on after restart) for every adapter whose setting differs from what
    registered at start."""
    st = registry.adapter_status()
    registered, configured = set(st["registered"]), set(st["configured"])
    return [
        (n, n in configured) for n in known if (n in registered) != (n in configured)
    ]


def _bar(token: str, pending: list[tuple[str, bool]]) -> Safe:
    n = len(pending)
    what = ", ".join(f"{a.capitalize()} {'on' if on else 'off'}" for a, on in pending)
    return h(
        '<div class="restart-bar"><div class="grow"><b>{}</b> <span class="muted">'
        "{}. A restart drops open MCP connections for a moment and stops a Mail batch "
        "that is running; its receipt and backups stay.</span></div>"
        '<form method="post" action="/adapters">{}'
        '<button class="btn" type="submit">Discard</button></form>'
        '<form method="post" action="/restart">{}'
        '<button class="btn primary" type="submit">Restart daemon</button>'
        "</form></div>",
        f"{n} change waits for a restart."
        if n == 1
        else f"{n} changes wait for a restart.",
        what,
        _hidden(token, action="discard"),
        _hidden(token),
    )


def _row(
    token: str, name: str, on: bool, sub: str, chips: Safe, disabled: bool
) -> Safe:
    label = name.capitalize()
    return h(
        '<div class="row"><span class="appico {}">{}</span>'
        '<div class="grow"><div class="title">{}</div><div class="sub">{}</div></div>'
        '{}<form method="post" action="/adapters" class="switch-form">{}'
        '<button type="submit" class="switch" '
        'aria-pressed="{}" aria-label="{} adapter, {}"{}>'
        "<span></span></button></form></div>",
        label,
        label[0],
        label,
        sub,
        chips,
        _hidden(token, action="toggle", adapter=name, on="0" if on else "1"),
        "true" if on else "false",
        label,
        "on" if on else "off",
        Safe(" disabled") if disabled else Safe(""),
    )


def outbound_command(sending: list[str]) -> str:
    """The Terminal command that flips the gate: the Adapters and Health pages show it
    and never a control."""
    return "macos-apps-mcp allow-send " + ("off" if sending else "mail")


def cmd_box(command: str) -> Safe:
    """A command in mono with a Copy button (``data-copy``, dashboard.js)."""
    return h(
        '<div class="cmd"><code>{}</code>'
        '<button class="btn" type="button" data-copy="{}">Copy</button></div>',
        command,
        command,
    )


def _outbound() -> Safe:
    """The locked Outbound group (D-14, sketch rule 5): text and a command, never a
    form or an input. Any website can POST to 127.0.0.1, so the gate that lets the
    model send mail stays a Terminal command."""
    sending = registry.outbound_status()["registered"]
    return h(
        '<div class="group-title">Sending off this Mac</div>\n'
        '<div class="group"><div class="row locked"><div class="grow">'
        '<div class="title">Outbound: {}</div><div class="sub">'
        "Never changed from this page — any website could send a request to "
        "127.0.0.1. Change it in Terminal:</div>{}</div></div></div>\n",
        ", ".join(sending) or "off",
        cmd_box(outbound_command(sending)),
    )


_RESTARTING_BAR = Safe(
    '<div class="restart-bar"><span class="spin"></span><div class="grow">'
    "<b>Restarting the daemon…</b> "
    '<span class="muted">This page reconnects by itself. MCP clients reconnect on '
    'their next call.</span> <a href="/adapters">Reload</a></div></div>'
)


def _banner(notice: str | None, why: str | None) -> Safe:
    """The one warning: a refusal with a way back, else the standing lock reason."""
    if notice:
        return h(
            '<div class="banner warn"><div>{} '
            '<a href="/adapters">Back to the switches</a></div></div>\n',
            notice,
        )
    return h('<div class="banner warn"><div>{}</div></div>\n', why) if why else Safe("")


def _lost_banner() -> Safe:
    if not _audit_lost:
        return Safe("")
    return h('<div class="banner warn"><div>{}</div></div>\n', _LOST_NOTE)


async def _render(
    request, *, restarting: bool = False, status: int = 200, notice: str | None = None
):
    """The Adapters page. ``notice`` is a refusal (409 lock, 400 bad action): it takes
    the banner with a way back, under ``status``. Only handlers the Guard let through
    call this, so no unauthenticated caller reads the sidebar's counts."""
    token = request.app.state.token
    known = registry.adapter_names()
    configured = set(registry.adapter_status()["configured"])
    pending = _pending(known)
    after = dict(pending)
    why = _lock_reason()
    report = await run_in_threadpool(deploy.grant_report)
    calls = await run_in_threadpool(audit.usage_read)
    complete = all(v is None for v in report["reasons"].values())
    rows = join(
        _row(
            token,
            n,
            n in configured,
            _sub(n, calls),
            _chips(
                grants.grant_state(report["identities"], n, complete=complete),
                after.get(n),
            ),
            restarting or why is not None,
        )
        for n in known
    )
    if restarting:
        top = _RESTARTING_BAR
    elif pending and why is None:  # D-20 / O5: Restart locks with the switches
        top = _bar(token, pending)
    else:
        top = Safe("")
    body = h(
        "{}<h1>Adapters</h1>\n"
        '<p class="lede">Turn an app off and its tools disappear after the daemon '
        "restarts.</p>\n{}"
        '<div class="group{}">{}</div>\n{}'
        '<p class="muted note">Toggles write '
        "~/.local/state/macos-apps-mcp/adapters_off. Each change is logged in "
        "audit.jsonl with caller <b>dashboard</b>.</p>\n",
        top,
        join([_banner(notice, why), _lost_banner()]),
        " restarting" if restarting else "",
        rows,
        _outbound(),
    )
    return render_page(
        request,
        title="Adapters",
        active="adapters",
        body=body,
        refresh=(12, "/adapters") if restarting else None,
        status=status,
    )


async def page(request):
    return await _render(request)


def _log(op: str, args: dict, target_id: str | None) -> bool:
    """Write the dashboard audit record; call under ``_write_lock``."""
    global _audit_lost
    ok = audit.audit_write(
        {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "tool": "dashboard",
            "op": op,
            "args": args,
            "dry_run": False,
            "caller": "dashboard",
            "target_id": target_id,
            "before": None,
            "after": None,
        }
    )
    _audit_lost = not ok
    if not ok:
        log.warning("dashboard %s applied but its audit record was not written", op)
    return ok


def _apply_toggle(adapter: str, on: bool) -> str | None:
    """The write, or the lock reason when the switches locked since the early check
    (re-read under the lock: an unreadable file must never be replaced by a guess)."""
    with _write_lock:
        if (why := _lock_reason()) is not None:
            return why
        known = set(registry.adapter_names())  # known names only (D-01)
        off = tiers.adapters_off() & known
        off = off - {adapter} if on else off | {adapter}
        deploy.write_adapters_off(off)
        _log("toggle", {"adapter": adapter, "on": on}, adapter)
    return None


def _apply_discard() -> str | None:
    """Write the running set back: every known adapter that did not register is OFF."""
    with _write_lock:
        if (why := _lock_reason()) is not None:
            return why
        off = sorted(
            set(registry.adapter_names()) - set(registry.adapter_status()["registered"])
        )
        deploy.write_adapters_off(off)
        _log("discard", {"adapters_off": off}, None)
    return None


def _log_restart() -> None:
    with _write_lock:
        _log("restart", {}, None)


async def toggle(request):
    """``POST /adapters``: ``action=toggle`` (adapter, on) or ``action=discard``."""
    why = _lock_reason()
    if why is not None:
        return await _render(request, status=409, notice=why)
    form = parse_qs((await request.body()).decode("utf-8", "replace"))
    action, adapter, on = (form.get(k, [""])[0] for k in ("action", "adapter", "on"))
    if action == "discard":
        why = await run_in_threadpool(_apply_discard)
    elif (
        action == "toggle" and adapter in registry.adapter_names() and on in ("0", "1")
    ):
        why = await run_in_threadpool(_apply_toggle, adapter, on == "1")
    else:
        return await _render(
            request,
            status=400,
            notice="Unknown action, adapter or value. Nothing changed.",
        )
    if why is not None:
        return await _render(request, status=409, notice=why)
    return RedirectResponse("/adapters", 303)


async def restart(request):
    """``POST /restart``: log the restart once per daemon process, answer, then ask
    the daemon to exit after the response (D-16). The record comes first so the
    restarting page can show a lost one (#430)."""
    hook = request.app.state.restart
    if hook is None:
        return PlainTextResponse("restart is available only in the daemon", 503)
    if (why := _lock_reason()) is not None:  # D-20: before the hook and the audit log
        return await _render(request, status=409, notice=why)

    if not getattr(request.app.state, "restart_logged", False):  # one exit, one record
        request.app.state.restart_logged = True
        await run_in_threadpool(_log_restart)
    response = await _render(request, restarting=True)
    response.background = BackgroundTask(hook)  # runs after the body is sent
    return response
