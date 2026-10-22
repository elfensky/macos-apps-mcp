"""Escape-by-default HTML for the dashboard (D-09).

Tool names, audit strings and, on later pages, mail subjects are written by strangers.
Every value interpolated into markup goes through ``esc`` unless it is a ``Safe`` that
dashboard code itself built; ``h`` applies that to a whole template. There is no
template engine on purpose: one audited function is the whole attack surface.
"""

from __future__ import annotations

import html
from importlib.metadata import PackageNotFoundError, version

from starlette.responses import HTMLResponse

from .. import registry


class Safe(str):
    """Markup built by dashboard code. Only dashboard code constructs it."""


def esc(v) -> str:
    """HTML-escape ``v``, quotes too (safe in an attribute), unless it is Safe."""
    return v if isinstance(v, Safe) else html.escape(str(v), quote=True)


def h(tpl: str, *vals, **kw) -> Safe:
    """Format ``tpl`` with every value escaped. ``h("<td>{}</td>", subject)``."""
    return Safe(tpl.format(*map(esc, vals), **{k: esc(v) for k, v in kw.items()}))


def join(parts) -> Safe:
    """Concatenate parts, escaping any that is not Safe."""
    return Safe("".join(map(esc, parts)))


# (group, label, href, key): one list, so a page plan adds its entry in one line.
SIDEBAR: list[tuple[str, str, str, str]] = [
    ("System", "Adapters", "/adapters", "adapters"),
    ("System", "Usage", "/usage", "usage"),
]


def _version() -> str:
    try:
        return version("macos-apps-mcp")
    except PackageNotFoundError:
        return "dev"


def _badge(key: str) -> Safe:
    """The Adapters entry shows ``registered/known``, or a chip while changes wait."""
    if key != "adapters":
        return Safe("")
    st = registry.adapter_status()
    registered, configured = set(st["registered"]), set(st["configured"])
    known = {r.adapter for r in registry.TOOLS.values() if r.adapter}
    pending = len(registered ^ configured)
    inner = (
        h('<span class="chip pending">{} pending</span>', pending)
        if pending
        else h("{}/{}", len(registered), len(known))
    )
    return h('<span class="count">{}</span>', inner)


def _sidebar(active: str) -> Safe:
    parts: list[Safe] = []
    group = None
    for g, label, href, key in SIDEBAR:
        if g != group:
            group = g
            parts.append(h("<h6>{}</h6>", g))
        on = key == active
        parts.append(
            h(
                '<a class="nav-item{}" href="{}"{}>{}{}</a>',
                " active" if on else "",
                href,
                Safe(' aria-current="page"') if on else Safe(""),
                label,
                _badge(key),
            )
        )
    foot = h('<div class="sidebar-foot">v{} · 127.0.0.1 only</div>', _version())
    return h('<aside class="sidebar">{}{}</aside>', join(parts), foot)


def page(
    request,
    *,
    title: str,
    active: str,
    body: Safe,
    mode: str = "page",
    refresh: tuple[int, str] | None = None,
):
    """The Console frame of sketch 001 (variant D): sidebar plus content.

    ``mode="page"`` puts ``body`` in a full-width ``<main>`` (the System pages).
    ``mode="console"`` expects ``body`` to be the list and detail columns itself.
    ``refresh=(seconds, path)`` adds a meta refresh to a page dashboard code builds."""
    meta = (
        h('<meta http-equiv="refresh" content="{};url={}">\n', refresh[0], refresh[1])
        if refresh
        else Safe("")
    )
    content = h('<main class="b-page">{}</main>', body) if mode == "page" else body
    return HTMLResponse(
        h(
            '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            "{}<title>{} · macos-apps-mcp</title>\n"
            '<link rel="stylesheet" href="/static/dashboard.css">\n'
            '<script src="/static/dashboard.js" defer></script>\n</head>\n<body>\n'
            '<div class="b-shell">{}{}</div>\n</body>\n</html>\n',
            meta,
            title,
            _sidebar(active),
            content,
        )
    )
