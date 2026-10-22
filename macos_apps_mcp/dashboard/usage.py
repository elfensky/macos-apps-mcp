"""The Usage page: calls per tool since the log started (D-11).

Facts come from ``audit.usage_report`` (the same report the ``usage`` tool returns) and
the registered tool names from ``registry.TOOLS``, never from importing the FastMCP
server module (the import-layer rule).
"""

from __future__ import annotations

from starlette.concurrency import run_in_threadpool

from .. import audit, registry
from .html import Safe, h, join
from .html import page as render_page


async def page(request):
    registered = {n for n, r in registry.TOOLS.items() if r.registered}
    report = await run_in_threadpool(audit.usage_report, registered)
    tools = report["tools"]
    top = max((t["count"] for t in tools), default=1)
    rows = join(
        h(
            '<div class="row"><span class="mono usage-tool">{}</span>'
            '<div class="grow"><meter class="usage-meter" min="0" max="{}" '
            'value="{}"></meter></div><span class="muted usage-count">{}</span></div>',
            t["tool"],
            top,
            t["count"],
            t["count"],
        )
        for t in tools
    )
    if not tools:
        rows = Safe('<div class="row muted">No calls recorded yet.</div>')
    never = report["never_used"]
    tail = (
        h('<p class="muted">Never used: {}</p>', ", ".join(never))
        if never
        else Safe("")
    )
    body = h(
        "<h1>Usage</h1>\n"
        '<p class="lede">Calls per tool since the log started.</p>\n'
        '<div class="group">{}</div>\n{}',
        rows,
        tail,
    )
    return render_page(title="Usage", body=body)
