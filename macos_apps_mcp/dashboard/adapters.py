"""The Adapters page: switch an app on or off, see what waits for a restart (D-11).

Two write endpoints exist on the whole dashboard and both live here: the toggle
(``POST /adapters``) and, from the restart bar, ``POST /restart``. Both sit behind the
Guard (Host, Origin, token). A toggle rewrites the ``adapters_off`` file and logs itself
with ``audit.audit_write`` as caller ``dashboard``: it goes around ``AuditMiddleware``
and never counts as a tool call in the usage tally (D-15).
"""

from __future__ import annotations

import threading
from datetime import datetime
from urllib.parse import parse_qs

from starlette.concurrency import run_in_threadpool
from starlette.responses import PlainTextResponse, RedirectResponse

from .. import audit, deploy, registry, tiers
from .html import Safe, h, join
from .html import page as render_page

_write_lock = threading.Lock()  # one read-modify-write of the file at a time


def known_adapters() -> list[str]:
    """The adapter names the registry holds, sorted; read per call."""
    return sorted({r.adapter for r in registry.TOOLS.values() if r.adapter})


def _permissions(adapter: str) -> str:
    perms = {
        p for r in registry.TOOLS.values() if r.adapter == adapter for p in r.permission
    }
    return " · ".join(sorted(perms)) or "No permission"


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


def _row(token: str, name: str, on: bool, pending: dict[str, bool]) -> Safe:
    label = name.capitalize()
    chip = (
        h(
            '<span class="chip pending">{} after restart</span>',
            "on" if pending[name] else "off",
        )
        if name in pending
        else Safe("")
    )
    return h(
        '<div class="row"><span class="appico {}">{}</span>'
        '<div class="grow"><div class="title">{}</div><div class="sub">{}</div></div>'
        '{}<form method="post" action="/adapters" class="switch-form">{}'
        '<button type="submit" class="switch" aria-pressed="{}" aria-label="{}">'
        "<span></span></button></form></div>",
        label,
        label[0],
        label,
        _permissions(name),
        chip,
        _hidden(token, action="toggle", adapter=name, on="0" if on else "1"),
        "true" if on else "false",
        label,
    )


async def page(request):
    token = request.app.state.token
    known = known_adapters()
    configured = set(registry.adapter_status()["configured"])
    pending = _pending(known)
    rows = join(_row(token, n, n in configured, dict(pending)) for n in known)
    body = h(
        "{}<h1>Adapters</h1>\n"
        '<p class="lede">Turn an app off and its tools disappear after the daemon '
        "restarts.</p>\n"
        '<div class="group">{}</div>\n',
        _bar(token, pending) if pending else Safe(""),
        rows,
    )
    return render_page(request, title="Adapters", active="adapters", body=body)


def _log(op: str, args: dict, target_id: str | None) -> None:
    audit.audit_write(
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


def _apply_toggle(adapter: str, on: bool) -> None:
    with _write_lock:
        off = tiers.adapters_off() & set(known_adapters())  # known names only (D-01)
        off = off - {adapter} if on else off | {adapter}
        deploy.write_adapters_off(off)
        _log("toggle", {"adapter": adapter, "on": on}, adapter)


async def toggle(request):
    form = parse_qs((await request.body()).decode("utf-8", "replace"))
    adapter, on = form.get("adapter", [""])[0], form.get("on", [""])[0]
    if adapter not in known_adapters() or on not in ("0", "1"):
        return PlainTextResponse("Unknown adapter or value.", 400)
    await run_in_threadpool(_apply_toggle, adapter, on == "1")
    return RedirectResponse("/adapters", 303)
