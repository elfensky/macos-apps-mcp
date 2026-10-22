"""Escape-by-default HTML for the dashboard (D-09).

Tool names, audit strings and, on later pages, mail subjects are written by strangers.
Every value interpolated into markup goes through ``esc`` unless it is a ``Safe`` that
dashboard code itself built; ``h`` applies that to a whole template. There is no
template engine on purpose: one audited function is the whole attack surface.
"""

from __future__ import annotations

import html

from starlette.responses import HTMLResponse


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


def page(*, title: str, body: Safe) -> HTMLResponse:
    return HTMLResponse(
        h(
            '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            "<title>{}</title>\n</head>\n<body>\n{}\n</body>\n</html>\n",
            title,
            body,
        )
    )
