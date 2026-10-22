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
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from urllib.parse import quote, urlencode

from starlette.concurrency import run_in_threadpool
from starlette.responses import PlainTextResponse

from .. import audit, registry
from ..adapters import mail_recover
from ..errors import NativeError
from ..text import fold_text
from . import recovery
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
    kind: str  # "write" | "dashboard" | "batch"
    title: str
    chip: str  # adds | changes | sends | preview
    preview: bool
    record: dict  # the record the row is about (the middleware or dashboard line)
    records: tuple[dict, ...]  # every raw audit line behind the row, in file order
    # A batch Mail write (D-12): the receipt and its plan and done records.
    receipt: str | None = None
    plan: dict | None = None
    done: dict | None = None
    undone: bool = False  # a later, real mail_undo named this batch's receipt


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


# The tools whose adapter methods call ``mail_recover.recoverable``, with the plan op
# each writes. ``mail_undo`` replays a move, so its plan op is "move".
_BATCH_TOOLS = {"move_mail": "move", "trash_mail": "trash", "mail_undo": "move"}
# What a batch is called when no middleware line names it (the dedupe-mail CLI writes
# only plan and done records).
_BATCH_LABEL = {"move": "move_mail", "trash": "trash_mail", "dedupe": "dedupe-mail"}
_BATCH_VERBS = {"move": "Moved", "trash": "Trashed", "dedupe": "Deduplicated"}


def _in(groups: dict, rid) -> bool:
    return isinstance(rid, str) and rid in groups


def _batches(records: list[dict], defaults: dict[str, bool]):
    """Group ``mail_recover`` plan and done records by receipt and link each batch to
    its middleware line: exactly, by the line's ``receipt`` key, else by adjacency (the
    first record after the done record, when it is a real call of a batch tool).
    Returns ``(groups, linked)``: receipt -> {plan, done, mw, lines}, and the index of
    every record that belongs to a batch -> its receipt."""
    groups: dict[str, dict] = {}
    for i, rec in enumerate(records):
        rid, phase = rec.get("receipt"), rec.get("phase")
        if (
            rec.get("tool") == "mail_recover"
            and isinstance(rid, str)
            and phase in ("plan", "done")
            and phase not in groups.setdefault(rid, {})
        ):
            groups[rid][phase] = rec
            groups[rid].setdefault("lines", []).append((i, rec))
    groups = {rid: g for rid, g in groups.items() if "lines" in g}
    linked: dict[int, str] = {}

    def link(i: int, rec: dict, rid: str) -> None:
        groups[rid]["mw"] = rec
        groups[rid]["lines"].append((i, rec))
        linked[i] = rid

    for i, rec in enumerate(records):
        rid = rec.get("receipt")
        # the first line naming a receipt wins
        if (
            rec.get("tool") != "mail_recover"
            and _in(groups, rid)
            and "mw" not in groups[rid]
        ):
            link(i, rec, rid)
    for i, rec in enumerate(records[:-1]):
        rid = rec.get("receipt")
        if rec.get("phase") != "done" or rec.get("tool") != "mail_recover":
            continue
        if not _in(groups, rid) or "mw" in groups[rid]:
            continue
        nxt = records[i + 1]
        g = groups[rid]
        op = (g.get("plan") or g["done"]).get("op")
        if (
            isinstance(nxt.get("tool"), str)
            and _BATCH_TOOLS.get(nxt["tool"]) == op
            and "receipt" not in nxt
            and not _is_preview(nxt, defaults)
        ):
            link(i + 1, nxt, rid)
    return groups, linked


def _batch_row(g: dict, rid: str, primary: dict, ts: str, n: int) -> Row | None:
    when = _when(primary.get("ts"))
    if when is None:
        return None
    head = g.get("plan") or g["done"]
    mw = g.get("mw")
    op, dest = head.get("op"), head.get("destination")
    tool = mw["tool"] if mw else _BATCH_LABEL.get(op, "mail_recover")
    k = len(recovery.targets(g.get("plan"), g.get("done")))
    noun = f"{k} message{'' if k == 1 else 's'}"
    if tool == "mail_undo":
        title = f"Undid a batch: moved {noun} back" + (f" to {dest}" if dest else "")
    else:
        title = f"{_BATCH_VERBS.get(op, str(op).capitalize())} {noun}" + (
            f" to {dest}" if dest else ""
        )
    reg = registry.TOOLS.get(tool)
    return Row(
        ts=ts,
        n=n,
        when=when,
        tool=tool,
        adapter="mail",
        tier=reg.tier if reg else "destructive",
        kind="batch",
        title=title,
        chip=_TIER_CHIP.get(reg.tier, "changes") if reg else "changes",
        preview=False,
        record=primary,
        records=tuple(rec for _, rec in sorted(g["lines"], key=lambda x: x[0])),
        receipt=rid,
        plan=g.get("plan"),
        done=g.get("done"),
    )


def build_rows(records: list[dict]) -> list[Row]:
    """The rows of the list, newest first. A line that is not a write record (an
    ``error`` entry, no ``tool``, no readable ``ts``) is not a row; a batch's plan,
    done and middleware lines are one row."""
    defaults = registry.dry_run_defaults()
    groups, linked = _batches(records, defaults)
    seen: Counter[str] = Counter()
    rows: list[Row] = []
    for i, rec in enumerate(records):
        tool, ts = rec.get("tool"), rec.get("ts")
        if not isinstance(tool, str) or _when(ts) is None:
            continue
        row: Row | None
        if tool == "mail_recover":
            rid = rec.get("receipt")
            g = groups.get(rid) if isinstance(rid, str) else None
            # one row per batch, at the middleware line when there is one
            if g is None or "mw" in g or rec is not (g.get("plan") or g["done"]):
                continue
            row = _batch_row(g, rec["receipt"], rec, ts, seen[ts])
        elif i in linked:
            row = _batch_row(groups[linked[i]], linked[i], rec, ts, seen[ts])
        else:
            row = _write_row(rec, ts, seen[ts], defaults)
        if row is not None:
            rows.append(row)
            seen[ts] += 1
    undone = {
        a
        for r in rows
        if r.tool == "mail_undo" and not r.preview
        if isinstance(a := _d(r.record.get("args")).get("receipt"), str)
    }
    rows = [replace(r, undone=True) if r.receipt in undone else r for r in rows]
    rows.reverse()
    rows.sort(key=lambda r: r.when, reverse=True)  # stable: ties stay newest-first
    return rows


def _write_row(rec: dict, ts: str, n: int, defaults: dict[str, bool]) -> Row:
    tool = rec["tool"]
    preview = _is_preview(rec, defaults)
    reg = registry.TOOLS.get(tool)
    tier = reg.tier if reg else None
    return Row(
        ts=ts,
        n=n,
        when=_when(ts),
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


def _counts(rows: list[Row]) -> dict:
    real = [r for r in rows if not r.preview]
    return {
        "all": len(real),
        "receipt": sum(r.kind == "batch" for r in real),
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
        '<div class="sub"><span class="mono">{}</span>{}</div></div>{}</a>',
        cls,
        Safe(quote(row.ts, safe=":")),
        row.n,
        qs,
        row.when.strftime("%H:%M"),
        appico(row.adapter),
        row.title,
        row.tool,
        (" · receipt" if row.kind == "batch" else "")
        + (" · undone" if row.undone else ""),
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
    if row.preview or row.kind != "write" or row.tool == "mail_undo":
        return Safe("")
    return h(
        '<div class="banner"><span>ⓘ</span><div><b>No backup for this write.</b> '
        "Recovery covers batch Mail writes — move, trash and dedupe. To reverse this, "
        "open it in {}, or ask Claude to change it back.</div></div>",
        row.adapter.capitalize() if row.adapter else "the app",
    )


def _url(row: Row, qs: str = "") -> str:
    return f"/write/{quote(row.ts, safe=':')}/{row.n}{qs}"


def _undo_row(row: Row, in_order: list[Row]) -> Row | None:
    """The real ``mail_undo`` that named this batch's receipt, if any."""
    return next(
        (
            r
            for r in in_order
            if r.tool == "mail_undo"
            and not r.preview
            and _d(r.record.get("args")).get("receipt") == row.receipt
        ),
        None,
    )


def _undone_banner(row: Row, in_order: list[Row], qs: str) -> Safe:
    undo = _undo_row(row, in_order)
    if undo is None:
        return Safe("")
    day = _day(undo.when.date())
    caller = undo.record.get("caller")
    moved = recovery.outcomes(undo.plan, undo.done) if undo.kind == "batch" else []
    back = Safe("")
    if moved and all(o == "ok" for _, o in moved):
        folders = [str(t["folder"]) for t, _ in recovery.outcomes(row.plan, row.done)]
        back = h(
            " The messages are back in {}.",
            ", ".join(dict.fromkeys(f for f in folders if f)),
        )
    elif moved:
        back = Safe(" Not every message moved back; open the undo to see which.")
    return h(
        '<div class="banner ok"><span>✓</span><div><b>Undone {} at {}{}.</b>{} '
        '<a class="btn link" href="{}">Show the undo</a></div></div>',
        day.lower() if day in ("Today", "Yesterday") else day,
        undo.when.strftime("%H:%M"),
        h(" by {}", caller) if caller else "",
        back,
        _url(undo, qs),
    )


def _undo_record_banner(row: Row, in_order: list[Row], qs: str) -> Safe:
    receipt = _d(row.record.get("args")).get("receipt")
    original = next(
        (r for r in in_order if r.kind == "batch" and r.receipt == receipt), None
    )
    caller = row.record.get("caller")
    return h(
        '<div class="banner ok"><span>↺</span><div>This undo moved the messages of an '
        "earlier batch back to where they came from.{}</div></div>{}",
        h(" Run by <b>{}</b>.", caller) if caller else "",
        h(
            '<div class="actions"><a class="btn" href="{}">Show the original batch</a>'
            "</div>",
            _url(original, qs),
        )
        if original
        else "",
    )


def _detail(row: Row, in_order: list[Row], qs: str, facts: tuple) -> Safe:
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
    undo_record = (
        _undo_record_banner(row, in_order, qs)
        if row.tool == "mail_undo" and not row.preview
        else Safe("")
    )
    if row.kind == "batch":
        files, resolves = facts
        return join(
            [
                head,
                undo_record,
                _undone_banner(row, in_order, qs) if row.undone else Safe(""),
                recovery.render_batch(
                    row,
                    files=files,
                    undo_resolves=resolves,
                    undone=row.undone,
                    reload=_url(row, qs),
                ),
                _raw(row.records),
            ]
        )
    return join(
        [
            head,
            undo_record,
            _preview_banner(row, in_order) if row.preview else Safe(""),
            _changed(row),
            _no_backup(row),
            _asked(row),
            _actions(row),
            _raw(row.records),
        ]
    )


# --- search and filters -----------------------------------------------------------


def _haystack(row: Row) -> str:
    """What ``q`` is matched against: the title, the tool, the argument values, the
    target ids, and for a batch its receipt, destination, folders and Message-IDs."""
    rec = row.record
    parts = [
        row.title,
        row.tool,
        str(rec.get("target_id") or ""),
        _summary(rec.get("before")),
        _summary(rec.get("after")),
        *map(str, _d(rec.get("args")).values()),
    ]
    if row.kind == "batch":
        parts += [row.receipt or "", str((row.plan or {}).get("destination") or "")]
        for t in recovery.targets(row.plan, row.done):
            parts += [str(t.get("id", "")), str(t.get("folder", ""))]
    return fold_text(" ".join(parts))


def _view(request) -> tuple[str, bool, str]:
    """``(q, previews, filter)`` from the query string. Previews are on unless the last
    ``previews`` value is not ``1`` (the hidden ``0`` plus the checked box send both);
    an unknown ``filter`` is ``all``."""
    params = request.query_params
    flag = params.getlist("previews")
    filt = params.get("filter", "all")
    adapters = {r.adapter for r in registry.TOOLS.values() if r.adapter}
    app = filt.startswith("app:") and filt[4:] in adapters
    if filt not in ("all", "receipt", "outbound") and not app:
        filt = "all"
    return params.get("q", ""), not flag or flag[-1] == "1", filt


def _visible(rows: list[Row], q: str, previews: bool, filt: str) -> list[Row]:
    terms = fold_text(q).split()
    out = []
    for r in rows:
        if r.preview and not previews:
            continue
        if filt == "receipt" and r.kind != "batch":
            continue
        if filt == "outbound" and r.tier != "send":
            continue
        if filt.startswith("app:") and r.adapter != filt[4:]:
            continue
        if terms:
            hay = _haystack(r)
            if not all(t in hay for t in terms):
                continue
        out.append(r)
    return out


def _search(q: str, previews: bool, filt: str) -> Safe:
    return h(
        '<form class="search" method="get" action="/">'
        '<input name="q" value="{}" placeholder="Filter" aria-label="Filter writes">'
        '<input type="hidden" name="previews" value="0">'
        '<label><input type="checkbox" name="previews" value="1"{}>Previews</label>'
        '<input type="hidden" name="filter" value="{}">'
        '<button class="btn" type="submit">Filter</button></form>',
        q,
        Safe(" checked") if previews else Safe(""),
        filt,
    )


# --- routes -----------------------------------------------------------------------


def _render(
    request,
    rows: list[Row],
    selected: Row | None,
    errors: list[str],
    facts: tuple = (),
):
    qs = _qs(request)
    q, previews, filt = _view(request)
    shown = _visible(rows, q, previews, filt)
    body = (
        _detail(selected, rows[::-1], qs, facts)
        if selected
        else Safe('<div class="b-empty">Select a write</div>')
    )
    banners = join(
        h(
            '<div class="banner bad"><span>⚠</span><div><b>The audit log could not '
            "be read.</b> {} What follows may be incomplete.</div></div>",
            e,
        )
        for e in errors
    )
    if shown:
        listing = _listing(shown, selected, qs)
    elif rows:
        listing = Safe('<div class="b-empty list-empty">No writes match</div>')
    elif errors:
        listing = Safe("")
    else:
        listing = Safe('<div class="b-empty list-empty">No writes recorded yet</div>')
    return page(
        request,
        title=selected.title if selected else "Writes",
        active=f"writes:{filt}",
        body=body,
        mode="list",
        listing=join([_search(q, previews, filt), banners, listing]),
        selected=selected is not None,
        counts=_counts(rows),
    )


def _recovery_facts(receipt: str) -> tuple[dict[str, int], bool]:
    """The backup files on disk and whether ``mail_undo`` could still replay the
    receipt (``find_receipt`` resolves its plan). Both are reads."""
    try:
        mail_recover.find_receipt(receipt)
        resolves = True
    except NativeError:
        resolves = False
    return recovery.backup_files(receipt), resolves


def _errors(records: list[dict]) -> list[str]:
    return [str(r["error"]) for r in records if "error" in r and "tool" not in r]


async def index(request):
    records = await run_in_threadpool(audit.read_all)
    return _render(request, build_rows(records), None, _errors(records))


async def detail(request):
    ts, n = request.path_params["ts"], request.path_params["n"]
    records = await run_in_threadpool(audit.read_all)
    rows = build_rows(records)
    row = next((r for r in rows if r.ts == ts and r.n == n), None)
    if row is None:
        return PlainTextResponse("Not Found", 404)
    facts = ()
    if row.kind == "batch":
        facts = await run_in_threadpool(_recovery_facts, row.receipt)
    return _render(request, rows, row, _errors(records), facts)
