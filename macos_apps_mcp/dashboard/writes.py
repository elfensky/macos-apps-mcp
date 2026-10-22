"""The write list and the detail of one write (PLAT-02, D-11, D-12).

``GET /`` is the Console list of every write the audit log holds, newest first, with the
detail of one write beside it (``GET /write/<ts>/<n>``). Both are plain server-rendered
pages that read ``audit.read_all()`` on every request: the log is the source of truth
and the page never keeps a copy. A GET here changes nothing, anywhere.

Everything from the log (summaries, args, tool names, ids, error text) was written by
strangers, so every value goes through ``html.h``/``esc``; nothing here wraps request or
audit data in ``Safe`` except markup this module builds from escaped parts.
"""

from __future__ import annotations

import difflib
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from urllib.parse import quote, urlencode

from starlette.concurrency import run_in_threadpool
from starlette.responses import PlainTextResponse

from .. import audit, registry
from .html import Safe, appico, esc, h, join, page, safe_href

_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)

# audit op -> (past tense, base form for a preview: "Would move …").
_VERBS = {
    "create": ("Created", "create"),
    "update": ("Updated", "update"),
    "delete": ("Deleted", "delete"),
    "complete": ("Completed", "complete"),
    "move": ("Moved", "move"),
    "trash": ("Trashed", "trash"),
    "send": ("Sent", "send"),
    "export": ("Exported", "export"),
    "save": ("Saved", "save"),
    "undo": ("Undid", "undo"),
}
# registry tier -> the list chip, and the chip's CSS class.
_TIER_CHIP = {"additive": "adds", "destructive": "changes", "send": "sends"}
_CHIP_CLASS = {
    "adds": "chip additive",
    "changes": "chip destructive",
    "sends": "chip outbound",
    "preview": "chip",
}


@dataclass(frozen=True)
class Row:
    """One write as the list shows it. ``ts`` and ``n`` address it (RESEARCH C5)."""

    ts: str
    n: int  # zero-based ordinal among rows sharing ``ts``, in file order
    when: datetime
    tool: str
    adapter: str | None
    tier: str | None
    kind: str  # "write" | "dashboard"
    title: str
    chip: str  # adds | changes | sends | preview
    preview: bool
    record: dict  # the record the row is about (the middleware or dashboard line)
    records: tuple[dict, ...]  # every raw audit line behind the row, in file order


def _today() -> date:
    return date.today()


def _d(v) -> dict:
    return v if isinstance(v, dict) else {}


def _summary(pointer) -> str:
    s = _d(pointer).get("summary")
    return "" if s is None else str(s)


def _when(ts) -> datetime | None:
    try:
        dt = datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None
    return dt.astimezone().replace(tzinfo=None) if dt.tzinfo else dt


def _day(d: date) -> str:
    today = _today()
    if d == today:
        return "Today"
    if d == today - timedelta(days=1):
        return "Yesterday"
    s = f"{_WEEKDAYS[d.weekday()]} {d.day} {_MONTHS[d.month - 1]}"
    return s if d.year == today.year else f"{s} {d.year}"


def _title(rec: dict, preview: bool) -> str:
    if rec.get("tool") == "dashboard":
        op, args = rec.get("op"), _d(rec.get("args"))
        if op == "toggle" and isinstance(args.get("adapter"), str):
            return f"Turned {args['adapter'].capitalize()} " + (
                "on" if args.get("on") else "off"
            )
        return {
            "discard": "Discarded pending adapter changes",
            "restart": "Restarted the daemon",
        }.get(op, f"Dashboard {op}")
    op = rec.get("op")
    past, base = _VERBS.get(op) or (str(op).capitalize(), str(op))
    verb = f"Would {base}" if preview else past
    text = _summary(rec.get("after")) or _summary(rec.get("before"))
    return f"{verb} {text}" if text else f"{verb} ({rec['tool']})"


def _is_preview(rec: dict, defaults: dict[str, bool]) -> bool:
    if "dry_run" in rec:
        return bool(rec["dry_run"])
    # A record from before #222: the tool's own default decides (D-12).
    return audit._resolve_dry_run(rec["tool"], _d(rec.get("args")), defaults)


def build_rows(records: list[dict]) -> list[Row]:
    """The rows of the list, newest first. A line that is not a write record (an
    ``error`` entry, no ``tool``, no readable ``ts``) is not a row."""
    defaults = registry.dry_run_defaults()
    seen: Counter[str] = Counter()
    rows: list[Row] = []
    for rec in records:
        tool, ts = rec.get("tool"), rec.get("ts")
        when = _when(ts)
        if not isinstance(tool, str) or when is None or tool == "mail_recover":
            continue
        preview = _is_preview(rec, defaults)
        reg = registry.TOOLS.get(tool)
        tier = reg.tier if reg else None
        rows.append(
            Row(
                ts=ts,
                n=seen[ts],
                when=when,
                tool=tool,
                adapter=reg.adapter if reg else None,
                tier=tier,
                kind="dashboard" if tool == "dashboard" else "write",
                title=_title(rec, preview),
                chip="preview" if preview else _TIER_CHIP.get(tier, "changes"),
                preview=preview,
                record=rec,
                records=(rec,),
            )
        )
        seen[ts] += 1
    rows.reverse()
    return rows


def _counts(rows: list[Row]) -> dict:
    real = [r for r in rows if not r.preview]
    return {
        "all": len(real),
        "receipt": 0,
        "outbound": sum(r.tier == "send" for r in real),
        "apps": dict(Counter(r.adapter for r in real if r.adapter)),
    }


def sidebar_counts(records: list[dict] | None = None) -> dict:
    """The sidebar's write counts (previews left out). Reads the log unless the caller
    already has it."""
    return _counts(build_rows(audit.read_all() if records is None else records))


# --- the list ---------------------------------------------------------------------


def _qs(request) -> str:
    items = request.query_params.multi_items()
    return "?" + urlencode(items) if items else ""


def _chip(label: str) -> Safe:
    return h('<span class="{}">{}</span>', _CHIP_CLASS[label], label)


def _row_html(row: Row, qs: str, selected: bool) -> Safe:
    cls = "row clickable" + (" preview" if row.preview else "")
    cls += " selected" if selected else ""
    return h(
        '<a class="{}" href="/write/{}/{}{}"><span class="time">{}</span>{}'
        '<div class="grow"><div class="title">{}</div>'
        '<div class="sub"><span class="mono">{}</span></div></div>{}</a>',
        cls,
        Safe(quote(row.ts, safe=":")),
        row.n,
        qs,
        row.when.strftime("%H:%M"),
        appico(row.adapter),
        row.title,
        row.tool,
        _chip(row.chip),
    )


def _listing(rows: list[Row], selected: Row | None, qs: str) -> Safe:
    parts: list[Safe] = []
    day = None
    for row in rows:
        if row.when.date() != day:
            day = row.when.date()
            parts.append(h('<div class="day">{}</div>', _day(day)))
        parts.append(_row_html(row, qs, row is selected))
    return join(parts)


# --- the detail -------------------------------------------------------------------

_TOKEN = re.compile(
    r'("(?:[^"\\]|\\.)*")(\s*:)?|\b(?:true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?'
)


def _highlight(text: str) -> Safe:
    """JSON text with keys, strings and literals marked up. The text is tokenised and
    every token is escaped on its own, so a hostile string stays inert."""
    out: list[str] = []
    pos = 0
    for m in _TOKEN.finditer(text):
        out.append(esc(text[pos : m.start()]))
        if m.group(1):
            cls = "k" if m.group(2) else "s"
            out.append(
                h('<span class="{}">{}</span>{}', cls, m.group(1), m.group(2) or "")
            )
        else:
            out.append(h('<span class="n">{}</span>', m.group(0)))
        pos = m.end()
    out.append(esc(text[pos:]))
    return Safe("".join(out))


def _raw(records: tuple[dict, ...]) -> Safe:
    n = len(records)
    body = "\n".join(
        json.dumps(r, indent=2, ensure_ascii=False, default=str) for r in records
    )
    return h(
        '<details class="raw"><summary>{} line{} in audit.jsonl</summary>'
        '<pre class="json">{}</pre></details>',
        n,
        "" if n == 1 else "s",
        _highlight(body),
    )


def _worddiff(before: str, after: str) -> Safe:
    a, b = before.split(), after.split()
    out: list[str] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(
        a=a, b=b, autojunk=False
    ).get_opcodes():
        if op == "equal":
            out.append(esc(" ".join(a[i1:i2])))
            continue
        if i2 > i1:
            out.append(h('<del class="w">{}</del>', " ".join(a[i1:i2])))
        if j2 > j1:
            out.append(h('<ins class="w">{}</ins>', " ".join(b[j1:j2])))
    return Safe(" ".join(out))


def _argval(v) -> Safe:
    if isinstance(v, str):
        return h("{}", v)
    if isinstance(v, bool):
        return h('<span class="mono">{}</span>', "true" if v else "false")
    return h(
        '<span class="mono">{}</span>', json.dumps(v, ensure_ascii=False, default=str)
    )


def _preview_banner(row: Row, in_order: list[Row]) -> Safe:
    why = (
        Safe('The caller passed <span class="mono">dry_run=true</span>.')
        if "dry_run" in _d(row.record.get("args"))
        else h(
            'The caller did not pass <span class="mono">dry_run</span>, and '
            '<span class="mono">{}</span> defaults to a preview.',
            row.tool,
        )
    )
    after = in_order[in_order.index(row) + 1 :]
    real = next(
        (
            r
            for r in after
            if r.tool == row.tool and not r.preview and r.when.date() == row.when.date()
        ),
        None,
    )
    later = (
        h(
            " The real call came {} s later, at {}.",
            max(0, round((real.when - row.when).total_seconds())),
            real.when.strftime("%H:%M"),
        )
        if real
        else Safe("")
    )
    return h(
        '<div class="banner"><span>ⓘ</span><div><b>Preview only — nothing '
        "changed.</b> {}{}</div></div>",
        why,
        later,
    )


def _changed(row: Row) -> Safe:
    rec = row.record
    before, after = _summary(rec.get("before")), _summary(rec.get("after"))
    if row.kind == "dashboard":
        inner = h('<div class="card">{}</div>', row.title)
    elif before and after:
        inner = h('<div class="card diffline">{}</div>', _worddiff(before, after))
    elif after:
        inner = h(
            '<div class="card diffline"><ins class="w">{}</ins></div>'
            '<p class="muted note">New — it did not exist before.</p>',
            after,
        )
    elif before:
        inner = h('<div class="card diffline"><del class="w">{}</del></div>', before)
    else:
        inner = Safe(
            '<div class="card muted">No before or after state was recorded.</div>'
        )
    label = "What it would have changed" if row.preview else "What changed"
    if row.preview:
        inner = h('<div class="dim">{}</div>', inner)
    return h('<div class="section-label">{}</div>{}', label, inner)


def _asked(row: Row) -> Safe:
    rec = row.record
    args = _d(rec.get("args"))
    rows = [h('<dt>tool</dt><dd class="mono">{}</dd>', row.tool)]
    rows += [h("<dt>{}</dt><dd>{}</dd>", k, _argval(v)) for k, v in args.items()]
    if "dry_run" not in args:
        default = registry.dry_run_defaults().get(row.tool)
        rows.append(
            h(
                '<dt>dry_run</dt><dd class="muted">not passed — {}</dd>',
                "not a dry-run tool"
                if default is None
                else f"defaulted to {'true' if default else 'false'}",
            )
        )
    for key in ("caller", "session"):
        if rec.get(key):
            rows.append(h("<dt>{}</dt><dd>{}</dd>", key, rec[key]))
    return h(
        '<div class="section-label">What the model asked for</div>'
        '<dl class="kv">{}</dl>',
        join(rows),
    )


def _actions(row: Row) -> Safe:
    rec = row.record
    pointer = _d(rec.get("after")) or _d(rec.get("before"))
    href = safe_href(pointer.get("deeplink", ""))
    parts: list[Safe] = []
    if href and row.adapter:
        parts.append(
            h(
                '<a class="btn" href="{}" rel="noreferrer">Open in {}</a>',
                href,
                row.adapter.capitalize(),
            )
        )
    if rec.get("target_id"):
        parts.append(
            h(
                '<button class="btn" type="button" data-copy="{}">Copy id</button>',
                rec["target_id"],
            )
        )
    return h('<div class="actions">{}</div>', join(parts)) if parts else Safe("")


def _no_backup(row: Row) -> Safe:
    if row.preview or row.kind != "write":
        return Safe("")
    return h(
        '<div class="banner"><span>ⓘ</span><div><b>No backup for this write.</b> '
        "Recovery covers batch Mail writes — move, trash and dedupe. To reverse this, "
        "open it in {}, or ask Claude to change it back.</div></div>",
        row.adapter.capitalize() if row.adapter else "the app",
    )


def _detail(row: Row, in_order: list[Row], qs: str) -> Safe:
    head = h(
        '<a class="btn link b-back" href="/{}">‹ Back</a>'
        '<div class="head">{}{}<span class="muted">{} {}</span></div><h2>{}</h2>',
        qs,
        appico(row.adapter),
        _chip(row.chip),
        _day(row.when.date()),
        row.when.strftime("%H:%M"),
        row.title,
    )
    return join(
        [
            head,
            _preview_banner(row, in_order) if row.preview else Safe(""),
            _changed(row),
            _no_backup(row),
            _asked(row),
            _actions(row),
            _raw(row.records),
        ]
    )


# --- routes -----------------------------------------------------------------------


def _render(request, rows: list[Row], selected: Row | None, counts: dict):
    qs = _qs(request)
    body = (
        _detail(selected, rows[::-1], qs)
        if selected
        else Safe('<div class="b-empty">Select a write</div>')
    )
    return page(
        request,
        title=selected.title if selected else "Writes",
        active="writes:all",
        body=body,
        mode="list",
        listing=_listing(rows, selected, qs),
        selected=selected is not None,
        counts=counts,
    )


async def index(request):
    rows = build_rows(await run_in_threadpool(audit.read_all))
    return _render(request, rows, None, _counts(rows))


async def detail(request):
    ts, n = request.path_params["ts"], request.path_params["n"]
    rows = build_rows(await run_in_threadpool(audit.read_all))
    row = next((r for r in rows if r.ts == ts and r.n == n), None)
    if row is None:
        return PlainTextResponse("Not Found", 404)
    return _render(request, rows, row, _counts(rows))
