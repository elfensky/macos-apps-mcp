"""Escape-by-default HTML for the dashboard (D-09).

Tool names, audit strings and, on later pages, mail subjects are written by strangers.
Every value interpolated into markup goes through ``esc`` unless it is a ``Safe`` that
dashboard code itself built; ``h`` applies that to a whole template. There is no
template engine on purpose: one audited function is the whole attack surface.
"""

from __future__ import annotations

import html
import re
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


# The URL schemes the adapters' Pointer deeplinks use (calendar ``calshow:``, contacts
# ``addressbook://``, mail ``message://``, messages ``imessage://``, reminders
# ``x-apple-reminderkit://``, shortcuts ``shortcuts://``, Safari's own page URLs). A
# stored deeplink with any other scheme (``javascript:``, ``data:``, ``vbscript:``,
# ``file:``) is text on the page, never a link (D-09, sketch rule 8).
_DEEPLINK_SCHEMES = frozenset(
    {
        "addressbook",
        "calshow",
        "http",
        "https",
        "imessage",
        "message",
        "shortcuts",
        "x-apple-reminderkit",
    }
)
_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*):")


def safe_href(url: str) -> str | None:
    """``url`` when its scheme is an allowed deeplink scheme, else None. Whitespace and
    control characters are refused outright: browsers strip them inside a scheme, so
    ``java<TAB>script:`` must not pass as something else."""
    if not isinstance(url, str) or any(ord(c) <= 32 or ord(c) == 127 for c in url):
        return None
    m = _SCHEME.match(url)
    return url if m and m.group(1).lower() in _DEEPLINK_SCHEMES else None


def appico(adapter: str | None) -> Safe:
    """The app's icon chip (``.appico.<App>`` in the CSS); a generic one for the
    dashboard's own writes."""
    name = adapter.capitalize() if adapter else "Dashboard"
    return h('<span class="appico {}">{}</span>', name, name[0])


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


def _nav(active: str, key: str, href: str, label, badge) -> Safe:
    on = key == active
    return h(
        '<a class="nav-item{}" href="{}"{}>{}{}</a>',
        " active" if on else "",
        href,
        Safe(' aria-current="page"') if on else Safe(""),
        label,
        badge,
    )


def _count(n) -> Safe:
    return h('<span class="count">{}</span>', n)


def _writes_nav(active: str, counts: dict) -> list[Safe]:
    """The Writes and Apps groups (sketch 001, frame D): filters of ``/``."""
    parts = [
        h("<h6>Writes</h6>"),
        _nav(active, "writes:all", "/", "All writes", _count(counts["all"])),
        _nav(
            active,
            "writes:receipt",
            "/?filter=receipt",
            "Batches with receipts",
            _count(counts["receipt"]),
        ),
        _nav(
            active,
            "writes:outbound",
            "/?filter=outbound",
            "Sent off this Mac",
            _count(counts["outbound"]),
        ),
    ]
    if counts["apps"]:
        parts.append(h("<h6>Apps</h6>"))
    for app, n in sorted(counts["apps"].items()):
        parts.append(
            _nav(
                active,
                f"writes:app:{app}",
                f"/?filter=app:{app}",
                join([appico(app), app.capitalize()]),
                _count(n),
            )
        )
    return parts


def _sidebar(active: str, counts: dict | None = None) -> Safe:
    from . import writes  # lazy: writes imports this module

    parts = _writes_nav(active, counts or writes.sidebar_counts())
    group = None
    for g, label, href, key in SIDEBAR:
        if g != group:
            group = g
            parts.append(h("<h6>{}</h6>", g))
        parts.append(_nav(active, key, href, label, _badge(key)))
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
    listing: Safe | None = None,
    selected: bool = False,
    counts: dict | None = None,
):
    """The Console frame of sketch 001 (variant D): sidebar plus content.

    ``mode="page"`` puts ``body`` in a full-width ``<main>`` (the System pages).
    ``mode="console"`` expects ``body`` to be the list and detail columns itself.
    ``mode="list"`` is the write list: ``listing`` is the list column and ``body`` the
    detail column; ``selected`` marks a detail as open (the phone shows it instead of
    the list). ``counts`` are the sidebar's write counts when the caller already read
    the log. ``refresh=(seconds, path)`` adds a meta refresh to a page dashboard code
    builds."""
    meta = (
        h('<meta http-equiv="refresh" content="{};url={}">\n', refresh[0], refresh[1])
        if refresh
        else Safe("")
    )
    if mode == "list":
        content = h(
            '<div class="b-list">{}</div><div class="b-detail">{}</div>',
            listing or Safe(""),
            body,
        )
    elif mode == "page":
        content = h('<main class="b-page">{}</main>', body)
    else:
        content = body
    return HTMLResponse(
        h(
            '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            "{}<title>{} · macos-apps-mcp</title>\n"
            '<link rel="stylesheet" href="/static/dashboard.css">\n'
            '<script src="/static/dashboard.js" defer></script>\n</head>\n<body>\n'
            '<div class="b-shell{}">{}{}</div>\n</body>\n</html>\n',
            meta,
            title,
            " detail-open" if selected else "",
            _sidebar(active, counts),
            content,
        )
    )
