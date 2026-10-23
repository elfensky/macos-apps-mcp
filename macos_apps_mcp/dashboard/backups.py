"""The Backups pages: every Mail backup receipt on disk, read-only (PLAT-02, D-13).

The list comes from the disk tree ``<state>/backup/mail``, not from the audit log, so a
receipt whose plan rotated out of the log is still found. It is joined to the log for
what the log still knows (the operation, the destination, the target count). Nothing
here creates, deletes, prunes, opens or serves a backup (retention is keep-forever,
#163): the folder name comes from the URL, so ``recovery.RECEIPT_RE`` runs before any
path is built, and only the names and sizes of regular files directly inside a real
receipt folder are read. ``backup_usage`` is not used: it counts every directory,
symlinks and strangers included, and this page counts what it lists.
"""

from __future__ import annotations

from starlette.concurrency import run_in_threadpool
from starlette.responses import PlainTextResponse

from .. import audit
from ..adapters import mail_addressing, mail_recover
from . import recovery, writes
from .html import Safe, h, join
from .html import page as render_page


def _not_found():
    return PlainTextResponse("Not Found", 404)


def _scan() -> list[tuple[str, int, int]]:
    """``(receipt, files, bytes)`` for every real receipt folder, newest first. An
    absent or unreadable backup root answers an empty list; it is never created."""
    try:
        names = sorted(
            (e.name for e in recovery.backup_root().iterdir()),
            reverse=True,
        )
    except OSError:
        return []
    out = []
    for name in names:
        if not recovery.RECEIPT_RE.fullmatch(name):
            continue
        if recovery.receipt_dir(name) is None:  # a symlink, or not a directory
            continue
        files = recovery.backup_files(name)
        out.append((name, len(files), sum(files.values())))
    return out


def _plans(records: list[dict]) -> dict[str, dict]:
    """Receipt -> its plan record, for the plans the log still holds."""
    out: dict[str, dict] = {}
    for rec in records:
        rid = rec.get("receipt") if isinstance(rec, dict) else None
        if (
            isinstance(rid, str)
            and rec.get("tool") == "mail_recover"
            and rec.get("phase") == "plan"
        ):
            out.setdefault(rid, rec)
    return out


def _limit(n: int) -> str:
    if n >= 1024**3:
        return f"{n / 1024**3:g} GB"
    return f"{n / 1024**2:.0f} MB"


def _receipt_row(name: str, files: int, size: int, plan: dict | None) -> Safe:
    op = name.rsplit("-", 1)[1]
    k = len(recovery.targets(plan, None)) if plan is not None else files
    title = f"{op} · {k} {'message' if k == 1 else 'messages'}"
    dest = plan.get("destination") if plan else None
    if isinstance(dest, str) and dest:
        title += f" → {mail_addressing.mailbox_label(dest)}"
    return h(
        '<a class="row clickable" href="/backups/{}"><div class="grow">'
        '<div class="title">{}</div><div class="sub mono">{}</div></div>'
        '<span class="muted">{}</span></a>',
        name,
        title,
        name,
        recovery.size_label(size),
    )


def _load_list() -> tuple[list[tuple[str, int, int]], dict[str, dict]]:
    return _scan(), _plans(audit.read_all())


async def page(request):
    items, plans = await run_in_threadpool(_load_list)
    total = sum(size for _, _, size in items)
    n = len(items)
    limit = mail_recover.backup_limit()
    oldest = items[-1][0] if items else None
    sub = f"advisory limit {_limit(limit)} (MACOS_APPS_BACKUP_LIMIT)"
    if oldest:
        sub = f"oldest {oldest[:4]}-{oldest[4:6]}-{oldest[6:8]} · " + sub
    root = recovery.backup_root()
    rows = (
        join(_receipt_row(name, k, size, plans.get(name)) for name, k, size in items)
        if items
        else Safe('<div class="row muted">No receipts on disk.</div>')
    )
    body = h(
        "<h1>Backups</h1>\n"
        '<p class="lede">Every batch Mail write copies its messages to disk first. '
        "Nothing here is ever pruned.</p>\n"
        '<div class="group"><div class="row"><div class="grow">'
        '<div class="title">{} MB in {} {}</div><div class="sub">{}</div>'
        '<meter class="usage-meter" min="0" max="{}" value="{}"></meter></div></div>'
        '<div class="row"><span class="grow mono muted">{}</span>'
        '<button class="btn" type="button" data-copy="{}">Copy</button></div></div>\n'
        '<div class="group-title">Receipts</div>\n<div class="group">{}</div>\n',
        f"{total / 1024**2:.1f}",
        n,
        "receipt" if n == 1 else "receipts",
        sub,
        limit,
        total,
        root,
        root,
        rows,
    )
    return render_page(request, title="Backups", active="backups", body=body)


def _load_receipt(name: str):
    """``(folder, batch row or None, files, plan resolves)``, or None for a receipt that
    is not a real folder under the backup root."""
    folder = recovery.receipt_dir(name)
    if folder is None:
        return None
    row = next(
        (r for r in writes.build_rows(audit.read_all()) if r.receipt == name), None
    )
    return folder, row, *recovery.facts(name)


_BACK = Safe('<a class="btn link" href="/backups">‹ Backups</a>')


def _rotated(name: str, folder, files: dict[str, int]) -> Safe:
    """A receipt whose plan is no longer in the log: its files and nothing to replay."""
    listing = (
        join(
            h(
                '<div class="row"><span class="grow mono">{}</span>'
                '<span class="muted">{}</span></div>',
                n,
                recovery.size_label(files[n]),
            )
            for n in sorted(files)
        )
        if files
        else Safe('<div class="row muted">The folder holds no files.</div>')
    )
    return h(
        '{}<h1>Receipt</h1>\n<p class="lede mono">{}</p>\n'
        '<div class="banner"><div>The plan for this receipt has rotated out of the '
        "audit log; the backup files remain.</div></div>\n"
        '<div class="group">{}</div>\n'
        '<div class="actions"><span class="mono muted">{}</span>'
        '<button class="btn" type="button" data-copy="{}">Copy</button></div>\n',
        _BACK,
        name,
        listing,
        folder,
        folder,
    )


async def receipt(request):
    name = request.path_params["receipt"]
    if not recovery.RECEIPT_RE.fullmatch(name):  # before any filesystem call
        return _not_found()
    found = await run_in_threadpool(_load_receipt, name)
    if found is None:
        return _not_found()
    folder, row, files, resolves = found
    if row is None:
        body = _rotated(name, folder, files)
    else:
        body = h(
            '{}<h1>{}</h1>\n<p class="lede mono">{}</p>\n{}{}',
            _BACK,
            row.title,
            name,
            Safe(
                '<div class="banner ok"><span>↩</span><div>This batch was undone: a '
                "later mail_undo moved the messages back.</div></div>\n"
            )
            if row.undone
            else Safe(""),
            recovery.render_batch(
                row,
                files=files,
                undo_resolves=resolves,
                undone=row.undone,
                reload=f"/backups/{name}",
            ),
        )
    return render_page(request, title="Receipt", active="backups", body=body)
