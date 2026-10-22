"""The read-only recovery view of a batch Mail write (PLAT-02, D-13, sketch 003 D).

A batch (move, trash or dedupe) leaves a plan record, a done record and, for a move, a
backup folder of one ``.eml`` per message. This module shows them and nothing more: no
route here moves, deletes, prunes, opens or serves a backup. The undo runs through
Claude and ``mail_undo``, where writes are gated, dry-run first and audited, so the page
offers a prompt to copy.

Receipt ids come from the audit log, which strangers can write into, so a receipt is
checked against ``RECEIPT_RE`` before any filesystem call, and only the names and sizes
of regular files directly inside a real receipt folder are ever read. Nothing here calls
``mail_recover._backup_dir`` (it runs ``mkdir``), ``purge_backup`` or ``backup_usage``.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path, PurePosixPath

from .. import audit
from ..adapters import mail_recover
from .html import Safe, h, join

RECEIPT_RE = re.compile(
    # the counter is padded to a MINIMUM of 3 digits (mail_recover._receipt_id)
    r"^\d{8}-\d{6}-\d{6}-\d{3,}-(" + "|".join(sorted(mail_recover.OPS)) + r")$",
    re.ASCII,  # \d is ASCII digits only: no Arabic-Indic or fullwidth look-alikes
)
_EML = re.compile(r"\d+\.eml")

FIDELITY = {
    "full": "Full copy, attachments included.",
    "partial": "Body complete, attachments missing — Mail had not downloaded them.",
    "absent": "No local copy — only the server copy exists.",
}
_NO_COPY = "No file copy was taken for this batch."
_VERBS = {"move": "moved", "trash": "trashed", "dedupe": "deduplicated"}


def backup_root() -> Path:
    """``<state>/backup/mail``, only computed: ``mail_recover._backup_dir`` creates the
    folder it names, and a page must not."""
    return audit.state_dir() / "backup" / "mail"


def receipt_dir(receipt) -> Path | None:
    """The receipt's backup folder, or None. The id must match ``RECEIPT_RE`` (checked
    before any filesystem call, so ``../`` never reaches a path), and the folder must be
    a real directory, not a symlink, directly inside the backup root."""
    if not isinstance(receipt, str) or not RECEIPT_RE.fullmatch(receipt):
        return None
    root = backup_root()
    folder = root / receipt
    try:
        if folder.is_symlink() or not folder.is_dir():
            return None
        if folder.resolve().parent != root.resolve():
            return None
    except OSError:
        return None
    return folder


def backup_files(receipt) -> dict[str, int]:
    """Name -> size of the regular files directly inside the receipt folder. Empty for
    a receipt that is malformed, absent or unreadable."""
    folder = receipt_dir(receipt)
    if folder is None:
        return {}
    out: dict[str, int] = {}
    try:
        for p in folder.iterdir():
            if p.is_symlink() or not p.is_file():
                continue
            out[p.name] = p.stat().st_size
    except OSError:
        return {}
    return out


def targets(plan: dict | None, done: dict | None) -> list[dict]:
    """A batch's targets: the plan's, else (a done record alone) one per result."""
    if plan is not None:
        ts = plan.get("targets")
        return [t for t in ts if isinstance(t, dict)] if isinstance(ts, list) else []
    results = (done or {}).get("results")
    return [{"id": i} for i in results] if isinstance(results, dict) else []


def outcomes(plan: dict | None, done: dict | None) -> list[tuple[dict, str]]:
    """Each target with its outcome. The outcome comes from the done record's
    ``results``, never from the plan target's ``status`` (always "planned"); with no
    done record every target reads ``unknown``."""
    results = (done or {}).get("results")
    results = results if isinstance(results, dict) else {}
    return [
        (t, str(results.get(str(t.get("id")), "unknown"))) for t in targets(plan, done)
    ]


def _size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    return f"{n / 1024:.0f} KB" if n < 1024 * 1024 else f"{n / 1048576:.1f} MB"


def _fid_chip(fidelity) -> Safe:
    if fidelity in FIDELITY:
        return h(
            '<span class="chip fid {}" title="{}">{}</span>',
            fidelity,
            FIDELITY[fidelity],
            "no backup" if fidelity == "absent" else fidelity,
        )
    return h('<span class="chip fid none" title="{}">no file copy</span>', _NO_COPY)


def _file_line(t: dict, files: dict[str, int]) -> Safe:
    """The backup's file name and size, from the folder listing; the name comes from the
    record but is only believed when the listing holds a file of that name."""
    name = PurePosixPath(str(t.get("backup") or "")).name
    if _EML.fullmatch(name) and name in files:
        return h('<div class="faint mono">{} · {}</div>', name, _size(files[name]))
    return Safe('<div class="faint mono">no file</div>')


def _target_row(t: dict, outcome: str, files: dict[str, int]) -> Safe:
    state = (
        Safe('<span class="chip ok">ok</span>')
        if outcome == "ok"
        else h('<span class="chip danger">{}</span>', outcome)
    )
    folder = (
        h('<div class="faint">from {}</div>', t["folder"]) if t.get("folder") else ""
    )
    return h(
        '<tr{}><td class="main"><span class="mono">{}</span>{}{}</td>'
        "<td>{}</td><td>{}</td></tr>",
        Safe(' class="left-out"') if outcome != "ok" else Safe(""),
        t.get("id", ""),
        folder,
        _file_line(t, files),
        _fid_chip(t.get("fidelity")),
        state,
    )


def _note(status: str, n: int) -> Safe:
    it, were = ("it", "was") if n == 1 else ("they", "were")
    noun = "message" if n == 1 else "messages"
    why = {
        "not-in-source": f"{were} missing when the batch ran, so {it} never moved",
        "unknown": f"the batch was stopped and {it} may or may not have moved",
    }.get(status)
    if why is None:
        return h(
            '<p class="muted note">{} {} left out: status “{}”.</p>', n, noun, status
        )
    lead = f"{n} {noun} left out: "
    if status == "not-in-source":
        lead += f"{it} "
    return h('<p class="muted note">{}{}.</p>', lead, why)


def render_batch(
    row, *, files: dict[str, int], undo_resolves: bool, undone: bool, reload: str
) -> Safe:
    """The batch card, the copyable undo prompt, the fidelity legend and the backup
    folder (sketch 003, variant D). ``undo_resolves`` is true only when
    ``mail_recover.find_receipt`` found the plan; ``undone`` hides the prompt."""
    plan = row.plan or {}
    op = str(plan.get("op"))
    rows = outcomes(row.plan, row.done)
    ok = sum(o == "ok" for _, o in rows)
    full = sum(t.get("fidelity") == "full" for t, _ in rows)
    sources = ", ".join(
        dict.fromkeys(str(t["folder"]) for t, _ in rows if t.get("folder"))
    )
    dest = plan.get("destination")
    backup_dir = plan.get("backup_dir")
    kept = (
        f"{full} full backup{'' if full == 1 else 's'}, "
        f"{len(rows) - full} partial or none"
        if backup_dir
        else "log only, no file backups"
    )
    summary = h(
        "<p><b>{} of {}</b> {}{}{} · {}</p>",
        ok,
        len(rows),
        _VERBS.get(op, "handled"),
        h(" from {}", sources) if sources else "",
        h(" to <b>{}</b>", dest) if dest else "",
        kept,
    )
    left = Counter(o for _, o in rows if o != "ok")
    card = h(
        '<div class="card">{}<table class="targets">{}</table>{}</div>',
        summary,
        join(_target_row(t, o, files) for t, o in rows),
        join(_note(status, n) for status, n in left.items()),
    )
    prompt = f"Undo mail receipt {row.receipt}"
    if undone:
        undo = Safe("")
    elif undo_resolves:
        undo = h(
            '<div class="section-label">To undo, ask Claude</div>'
            '<div class="prompt"><span class="grow">{}</span>'
            '<button class="btn" type="button" data-copy="{}">Copy</button></div>'
            '<p class="muted note">Claude runs <code class="call">mail_undo</code> '
            "as a preview first, then moves the messages back after you confirm. "
            "This page only reads — writes stay in the MCP path, where they are "
            'gated and audited. <a href="{}">Reload</a> once it has run.</p>'
            '<details class="raw"><summary>Exact tool call</summary>'
            '<p><code class="call">mail_undo(receipt="{}", dry_run=false)</code></p>'
            "</details>",
            prompt,
            prompt,
            reload,
            row.receipt,
        )
    else:
        undo = Safe(
            '<p class="muted note">The plan for this receipt has rotated out of the '
            "recent audit log, so mail_undo cannot replay it. The backup files "
            "remain.</p>"
        )
    legend = h(
        '<div class="legend">{}</div>',
        join(
            join([_fid_chip(f), h("<span>{}</span>", text)])
            for f, text in FIDELITY.items()
        ),
    )
    folder = (
        h(
            '<div class="actions"><span class="mono muted">{}</span>'
            '<button class="btn" type="button" data-copy="{}">Copy</button></div>',
            backup_dir,
            backup_dir,
        )
        if backup_dir
        else Safe(
            '<p class="muted note">No backup folder: this batch was logged without '
            "file copies.</p>"
        )
    )
    return join([card, undo, legend, folder])
