"""The recoverable destructive plane (#159) — **backup → log → act, in that order**.

One module every destructive mail write passes through, so the safety invariants are
stated ONCE instead of re-derived per call site. 0.9.2/0.9.3 file four of those writes
(``move_mail`` #78, ``trash_mail`` #80, same-mailbox dedupe #140, cross-account dedupe
#153) and each issue independently re-specified dry-run-default, batch cap,
Trash-not-delete and verify-then-act. That is the autosave-fact pattern again: an
invariant with no module owning it.

It extends the repo's own seam one step — **sqlite locates, Python preserves,
AppleScript acts**:

- **locate** ``mail_index.query_message_locations`` answers which ``messages.ROWID``
  backs each target, and the ROWID names the ``.emlx`` file on disk (device-verified
  2026-08-03: 36,417 files under ``~/Library/Mail/V10``, zero ROWID collisions).
- **preserve** the RFC822 bytes are copied out as a plain ``.eml`` — a file copy, no
  Mail launch, fast even at dedupe scale — BEFORE any Apple Event is sent.
- **act** the caller's AppleScript runs last, and reports per-target truth that this
  module records. It never assumes; #135 burned that lesson in when a bare ``delete``
  reported success having removed nothing.

**Fidelity is bounded by download state.** Measured on this Mac: 13,642 full ``.emlx``
against 22,733 ``.partial.emlx`` — 62.5% of local messages are headers-only, so a
backup is often honest but LOSSY. Every target is therefore stamped ``full`` |
``partial`` | ``absent``, and a PERMANENT delete refuses a non-full target without an
explicit ``allow_lossy``. A move or a soft delete needs no such gate: the server copy
survives either way.

**The action log is the existing audit JSONL**, not a second log — but written straight
through ``audit_write`` rather than via ``AuditMiddleware``, whose ``_audit_args``
truncates every string at 200 chars (``audit.py``) and so could never carry a
thousand-target set. Two records per operation: the PLAN (before acting — that is what
makes undo survive a crash mid-act) and the OUTCOME.

**Undo** is a move-back: the plan records where each target came from, so
``find_receipt`` + the caller's move script return a batch to its source mailboxes. A
permanent delete cannot be replayed — the receipt says so, and points at the ``.eml``
bytes for manual re-import.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, replace
from datetime import datetime
from itertools import count
from pathlib import Path

from ..audit import audit_read, audit_write, state_dir
from ..errors import BatchTooLarge, NativeError
from . import mail_addressing, mail_index

# Hard cap on one destructive batch, rejected BEFORE any native call. Inbox-zero needs
# batch; the cap is what stops a batch becoming an incident. Deliberately NOT
# overridable (unlike errors.require_batch_within's override_param): a caller who can
# raise the ceiling on request is a caller who will, and the recovery path is bounded by
# how many files we are willing to copy first.
MAX_TARGETS = 25

# The ops this plane knows. A whitelist, so a typo can't mint a receipt that
# ``mail_undo`` will later fail to interpret. 0.9.3 adds "trash" (#80) and "dedupe"
# (#140/#153).
OPS = frozenset({"move", "trash", "dedupe"})

# Ops that destroy the last copy — the only ones the lossy gate applies to.
#
# STILL EMPTY, and now for a device reason rather than a sequencing one: 0.9.3 probed
# for a targeted permanent delete and proved there is none (facts doc §5c). Mail's
# `delete` on a message already in Trash is a silent no-op, `deleted status` raises -609
# on write although Mail.sdef declares it writable, and the dictionary carries no erase
# or expunge verb at all. Emptying Trash is a Mail.app UI act, so nothing this project
# can call destroys a last copy.
#
# The gate below (and ``allow_lossy``) is kept rather than deleted: it is the enforced
# statement of the rule for whoever finds an erase verb on a later macOS — add the op
# here and the refusal is already written and tested. Do not build a permanent delete
# against today's Mail; prove §5c changed first.
PERMANENT_OPS = frozenset()

# Backup fidelity. `unknown` is the DEFAULT and is not the same claim as `absent`: a
# dry run never looks at disk, and reporting "absent" for a message nobody searched for
# would be a confidently wrong answer of exactly the kind this project refuses. Only
# `locate` may stamp the other three.
_FULL, _PARTIAL, _ABSENT, _UNKNOWN = "full", "partial", "absent", "unknown"


@dataclass(frozen=True, slots=True)
class Target:
    """One message a destructive op is about to touch, and everything undo needs.

    ``id``       bare Message-ID (``mail_addressing.bare_id``).
    ``folder``   the SOURCE mailbox token — a round-trip ``mailboxes.url`` or one of the
                 five canonical names. This is the field undo moves back TO, so it is
                 recorded per target and not per batch: a batch may be gathered from
                 several mailboxes.
    ``account``  owning account uuid, or None for a unified accessor.
    ``rowid``    ``messages.ROWID`` — the ``.emlx`` filename. None when unlocated.
    ``fidelity`` ``unknown`` (nobody has looked — a dry run) or, once ``locate`` has
                 run, ``full`` | ``partial`` | ``absent``: how much of the message the
                 backup could actually preserve.
    ``backup``   path of the written ``.eml``, or None (dry run, or nothing to copy).
    ``status``   what the act reported for this target: ``planned`` until it runs.
    """

    id: str
    folder: str
    account: str | None = None
    rowid: int | None = None
    fidelity: str = _UNKNOWN
    backup: str | None = None
    status: str = "planned"

    def as_dict(self) -> dict:
        d: dict = {"id": self.id, "folder": self.folder}
        # Omitted while unknown, like Pointer's optional fields: a preview row is about
        # WHERE a message is, and an unasked question deserves silence, not a guess.
        if self.fidelity != _UNKNOWN:
            d["fidelity"] = self.fidelity
        if self.account is not None:
            d["account"] = self.account
        if self.rowid is not None:
            d["rowid"] = self.rowid
        if self.backup is not None:
            d["backup"] = self.backup
        d["status"] = self.status
        return d


def check_batch(targets) -> list[Target]:
    """The cap, enforced once. Raises ``BatchTooLarge`` past ``MAX_TARGETS``; raises on
    an empty batch too — a destructive call that names nothing is a caller bug, and
    answering "0 affected, all good" is the reassuring-direction lie this module
    exists to refuse. Returns the list so a caller can inline it."""
    items = list(targets)
    if not items:
        raise ValueError(
            "this operation needs at least one message id (none were given)"
        )
    if len(items) > MAX_TARGETS:
        raise BatchTooLarge(
            f"this operation would affect {len(items)} messages but the safety cap is "
            f"{MAX_TARGETS}, and it is not overridable — every target is backed up to "
            "disk before anything moves. Split the batch and re-issue. Do not retry "
            "the same oversized batch unchanged."
        )
    return items


def _rowid_paths(root: Path) -> dict[int, Path]:
    """``messages.ROWID`` -> its ``.emlx`` path, from ONE rglob.

    Device-verified 2026-08-03 against ``~/Library/Mail/V10``: every ``.emlx`` is named
    by the Envelope Index ROWID of the message it holds, and across 36,417 files no two
    rows shared a ROWID — so a flat dict is a complete, unambiguous index. Same walk
    ``build_body_index`` already does.

    ponytail: one full-tree rglob (~2s on a 36k-message store) per destructive call,
    for a batch capped at 25. Scope the glob to the target's ``<acct-uuid>/<name>.mbox``
    subtree if that ever bites — the mailbox url already carries both halves.
    """
    out: dict[int, Path] = {}
    for f in root.rglob("*.emlx"):
        stem = f.name.split(".", 1)[0]
        if stem.isdigit():
            out[int(stem)] = f
    return out


def locate(targets) -> list[Target]:
    """Fill ``rowid`` and ``fidelity`` on each target from the index + disk.

    A target whose folder is a mailbox url is matched to the row in THAT mailbox — a
    Message-ID has several rows and only one of them is the copy about to be acted on.
    A canonical-name folder (a unified accessor) has no url to match, so the first row
    wins; that is the honest best available, and the fidelity stamp still describes
    whatever file was actually copied.

    Never raises on a miss: a target we cannot locate is stamped ``absent`` and carries
    on. Refusing the whole batch because one message was never downloaded would make
    the common case (62.5% partial on this Mac) unusable, and ``absent`` is exactly the
    signal the permanent-delete gate reads.
    """
    items = list(targets)
    if not items:
        return []
    rows = mail_index.query_message_locations(
        {mail_addressing.stored_id(t.id) for t in items}
    )
    by_id: dict[str, list[dict]] = {}
    for r in rows:
        by_id.setdefault(mail_addressing.bare_id(str(r["message_id"])), []).append(r)
    root = mail_index.mail_root()
    paths = _rowid_paths(root) if root is not None and rows else {}
    out = []
    for t in items:
        candidates = by_id.get(mail_addressing.bare_id(t.id), [])
        row = next(
            (c for c in candidates if c["mailbox_url"] == t.folder),
            candidates[0] if candidates else None,
        )
        if row is None:
            out.append(replace(t, fidelity=_ABSENT))
            continue
        path = paths.get(int(row["rowid"]))
        fidelity = (
            _ABSENT
            if path is None
            else (_PARTIAL if path.name.endswith(".partial.emlx") else _FULL)
        )
        out.append(replace(t, rowid=int(row["rowid"]), fidelity=fidelity))
    return out


def _backup(op: str, receipt_id: str, targets: list[Target]) -> list[Target]:
    """Copy each located target's RFC822 bytes out as a plain ``.eml``, before anything
    acts. Returns the targets stamped with their backup paths.

    Plain ``.eml`` (not a copy of the ``.emlx``) so the file is importable by Mail.app
    and by anything else — ``emlx_payload`` drops Mail's byte-count line and trailing
    plist, which are the two things that make an ``.emlx`` un-openable elsewhere.

    A per-file failure downgrades that target to ``absent`` rather than aborting: the
    op's own safety does not depend on the copy (a move leaves the message intact), and
    a batch that refuses to run because one file was expunged mid-flight is worse than
    one that runs and says which target it could not preserve.
    """
    root = mail_index.mail_root()
    if root is None:
        return targets
    paths = _rowid_paths(root)
    out = []
    for t in targets:
        path = paths.get(t.rowid) if t.rowid is not None else None
        if path is None:
            out.append(replace(t, fidelity=_ABSENT))
            continue
        try:
            payload = mail_index.emlx_payload(path.read_bytes())
            if not payload:
                out.append(replace(t, fidelity=_ABSENT))
                continue
            dest = _backup_dir(receipt_id) / f"{t.rowid}.eml"
            dest.write_bytes(payload)
        except OSError:
            # Mail can expunge/rename a file between the rglob and the read — same
            # race build_body_index documents. Record the miss, keep going.
            out.append(replace(t, fidelity=_ABSENT))
            continue
        out.append(replace(t, backup=str(dest)))
    return out


def _backup_dir(receipt_id: str) -> Path:
    """``state_dir()/backup/mail/<receipt-id>/`` — the existing convention
    (``audit.jsonl``, ``allow_send`` and the FTS sidecar already live under
    ``state_dir()``), never a new dot-dir."""
    d = state_dir() / "backup" / "mail" / receipt_id
    d.mkdir(parents=True, exist_ok=True)
    return d


# Receipt ids must be unique per OPERATION, not per clock tick: an undo issued straight
# after its move is the normal case, and a shared id would make the two receipts share a
# backup directory — so `purge_backup` on one would destroy the other's preserved bytes.
# A wall-clock stamp alone collided in practice (two ops inside one millisecond), so the
# stamp is paired with a process-local counter: the clock keeps ids sortable and
# readable across restarts, the counter makes them unique within a run.
_MINTED = count()


def _receipt_id(op: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    return f"{stamp}-{next(_MINTED):03d}-{op}"


def _check_op(op: str) -> str:
    if op not in OPS:
        raise ValueError(f"unknown destructive op {op!r} — known: {sorted(OPS)}")
    return op


def preview(op: str, targets, *, destination: str | None = None) -> dict:
    """The ONE dry-run envelope every destructive mail write answers with.

    Shaped like ``deletion_result``/``read_result``: a single wire shape, so "what does
    a dry run MEAN" is one contracts fact with one test rather than four tool-level
    behaviours that drift. It reports what WOULD be touched and where each target
    currently is — no backup written, no Apple Event sent, nothing on disk.

    The caller is expected to have refreshed ``status`` through a READ of stored
    messages first (AppleScript, not sqlite: the index lags, and a preview claiming 25
    ids are present when they are not is worse than no preview). Reading stored
    messages strands nothing — the same justification #129's reply-all preview stands
    on.
    """
    _check_op(op)
    items = check_batch(targets)
    out: dict = {
        "dry_run": True,
        "op": op,
        "count": len(items),
        "would_affect": [t.as_dict() for t in items],
    }
    if destination is not None:
        out["destination"] = destination
    return out


def is_preview(result) -> bool:
    """True for the envelope ``preview`` builds — the shape the plane-bypass guard test
    checks, so a destructive tool that hand-rolls its own dry run fails loudly."""
    return isinstance(result, dict) and result.get("dry_run") is True and "op" in result


def recoverable(
    op: str,
    targets,
    act,
    *,
    destination: str | None = None,
    backup: bool = True,
    allow_lossy: bool = False,
) -> dict:
    """**backup → log → act**, then report what actually happened.

    ``act(targets) -> dict[id, status]`` is the caller's AppleScript, and its returned
    status per id is taken as the truth of record — callers are expected to VERIFY
    (re-read the destination and the source), never to assume, because a Mail verb that
    returns cleanly having done nothing is this project's most expensive recurring bug.
    An id missing from that map is recorded as ``unknown``, which is honest; defaulting
    it to ``ok`` would be the reassuring-direction lie.

    ``destination`` is what undo needs to move a batch back FROM. Without it a receipt
    is not replayable, and says so.

    ``backup=False`` is the LOG-ONLY mode #140/#153 need: both dedupes require
    byte-identity before deleting a loser, so the surviving copy IS the backup and
    copying files would be pure cost. The action record is still written in full.

    ``allow_lossy`` only matters for a ``PERMANENT_OPS`` op: without it, a target whose
    local bytes are ``partial`` or ``absent`` cannot be permanently destroyed, because
    the backup would not be a recovery. Checked AFTER locating (fidelity is not knowable
    before) and BEFORE any Apple Event, so a refusal costs nothing but a file read.
    """
    _check_op(op)
    items = check_batch(targets)
    # Locating exists to serve exactly two consumers — the file backup, and the lossy
    # gate on a PERMANENT op. With neither in play it is pure cost, and not a small one:
    # `_rowid_paths` rglobs a 36k-file tree (~2s) per call, and the dedupe CLI (#140)
    # drives thousands of messages through here 25 at a time with backup=False. Skipping
    # it leaves every target stamped `unknown` fidelity, which is the honest answer —
    # nobody looked — and is exactly what that stamp is for.
    located = (
        locate(items) if backup or op in PERMANENT_OPS else [replace(t) for t in items]
    )
    if op in PERMANENT_OPS and not allow_lossy:
        lossy = [t for t in located if t.fidelity != _FULL]
        if lossy:
            raise NativeError(
                f"{len(lossy)} of {len(located)} messages have no full local copy "
                f"({', '.join(t.id for t in lossy[:3])}…), so a permanent delete could "
                "not be undone from the backup — most local mail is headers-only until "
                "its body is downloaded. Move them to Trash instead, or pass "
                "allow_lossy=True to destroy them knowing the bodies are unrecoverable."
            )
    receipt_id = _receipt_id(op)
    if backup:
        located = _backup(op, receipt_id, located)
    plan = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "tool": "mail_recover",
        "op": op,
        "phase": "plan",
        "receipt": receipt_id,
        "destination": destination,
        "backup_dir": str(_backup_dir(receipt_id)) if backup else None,
        "targets": [t.as_dict() for t in located],
    }
    # Logged BEFORE acting, deliberately: if the process dies mid-act, the log still
    # holds every source mailbox undo needs. The outcome record below completes it.
    audit_write(plan)
    statuses = act(located) or {}
    done = [replace(t, status=statuses.get(t.id, "unknown")) for t in located]
    audit_write(
        {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "tool": "mail_recover",
            "op": op,
            "phase": "done",
            "receipt": receipt_id,
            "results": {t.id: t.status for t in done},
        }
    )
    ok = [t for t in done if t.status == "ok"]
    out: dict = {
        "op": op,
        "receipt": receipt_id,
        "count": len(done),
        "succeeded": len(ok),
        "targets": [t.as_dict() for t in done],
    }
    if destination is not None:
        out["destination"] = destination
    if backup:
        out["backup_dir"] = str(_backup_dir(receipt_id))
    lossy = [t.id for t in done if t.fidelity != _FULL]
    if lossy:
        out["partial_backups"] = lossy
    if len(ok) != len(done):
        out["note"] = (
            f"{len(done) - len(ok)} of {len(done)} messages were NOT affected — see "
            "each target's `status`. Tell the user; do not retry the whole batch "
            "blindly."
        )
    if destination is not None:
        out["undo"] = f'mail_undo("{receipt_id}")'
    return out


# How many audit lines back ``find_receipt`` looks. A receipt is undone within minutes
# of being minted in every workflow this serves, and the log is append-only with two
# lines per destructive op — 2000 covers far more history than that while keeping the
# read bounded.
_RECEIPT_SCAN = 2000


def find_receipt(receipt_id: str) -> tuple[dict, dict[str, str]]:
    """``(plan record, per-id outcomes)`` for ``receipt_id``.

    Two records, because they are written at two different moments and both matter: the
    PLAN carries every target and its source mailbox (written before acting, so it
    survives a crash mid-act), and the DONE record carries what each target's status
    ended up being. A plan with no matching done record — the crash case — yields ``{}``
    outcomes, and the caller treats every planned target as possibly-acted, which is the
    conservative reading.

    Raises when the plan is not in the recent log, naming the reason rather than
    answering an empty batch: an unresolvable receipt is exactly the thing a caller must
    be told about."""
    rid = receipt_id.strip()
    plan = None
    outcomes: dict[str, str] = {}
    for rec in audit_read(limit=_RECEIPT_SCAN):
        if rec.get("receipt") != rid:
            continue
        if rec.get("phase") == "plan" and plan is None:
            plan = rec
        elif rec.get("phase") == "done" and not outcomes:
            outcomes = rec.get("results") or {}
    if plan is None:
        raise NativeError(
            f"no recoverable-mail receipt {rid!r} in the recent audit log — check the "
            "receipt id from the operation's result, or read `audit` to list them. Do "
            "not retry with a guessed id."
        )
    return plan, outcomes


def undo_plan(receipt_id: str) -> tuple[dict, list[Target]]:
    """``(record, targets)`` for replaying a receipt in reverse: each target keeps the
    SOURCE folder it came from, and the record's ``destination`` says where the batch
    is now. Raises when the receipt names no destination — a permanent delete cannot be
    replayed, and the honest answer points at the preserved bytes instead of pretending
    otherwise."""
    rec, outcomes = find_receipt(receipt_id)
    destination = rec.get("destination")
    if not destination:
        where = rec.get("backup_dir") or "(no backup was taken)"
        raise NativeError(
            f"receipt {receipt_id!r} is a {rec.get('op')!r} with no destination "
            "mailbox, so there is nothing to move the messages back FROM — it cannot "
            f"be replayed. The preserved message bytes are in {where}; import them "
            "into Mail by hand. Do not retry."
        )
    targets = [
        Target(
            id=t["id"],
            folder=t["folder"],
            account=t.get("account"),
            rowid=t.get("rowid"),
            fidelity=t.get("fidelity", _UNKNOWN),
            backup=t.get("backup"),
        )
        for t in rec.get("targets", [])
        # Only replay what actually moved. A target the op reported as not-in-source or
        # failed is already where undo would put it, and "moving" it back would report a
        # fake success. An outcome we never recorded (the crash case) IS replayed: the
        # conservative reading of "we do not know" is that it moved.
        if outcomes.get(t["id"], "ok") == "ok"
    ]
    if not targets:
        raise NativeError(
            f"receipt {receipt_id!r} recorded no messages to restore. Do not retry."
        )
    return rec, targets


# --- storage visibility (#163) -------------------------------------------------------
# Retention is KEEP FOREVER, and there is deliberately no pruning code anywhere in this
# module. Batches are capped at 25 messages, so growth is MB-scale, and an auto-expiry
# would mean the safety layer silently destroying its own safety net — the one failure
# this plane cannot be allowed to have. The accepted trade-off is that "deleted" mail
# lingers on disk until a human sweeps it, so what ships instead of pruning is
# VISIBILITY: a doctor() line, and an advisory past a size threshold.

# Past this, mail writes carry a one-line advisory. Env-overridable because "too big"
# is a judgement about someone else's disk, not a constant we get to pick for them.
_DEFAULT_BACKUP_LIMIT = 1024**3  # 1 GiB


def backup_limit() -> int:
    """The advisory threshold in bytes (``MACOS_APPS_BACKUP_LIMIT``). A non-numeric or
    negative value falls back to the default rather than raising: this is a nicety on
    the side of a mail write, and it must never be the reason one fails."""
    raw = os.environ.get("MACOS_APPS_BACKUP_LIMIT", "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    return _DEFAULT_BACKUP_LIMIT


def backup_usage() -> dict:
    """``{bytes, receipts, oldest, path}`` for the backup tree — what doctor() reports.

    Cheap by construction (one walk of a directory holding at most 25 small ``.eml``
    per receipt) and NEVER raises: an unreadable or absent tree answers zeroes, because
    this rides in every doctor() report and a storage read must not be able to fail a
    diagnostic. ``oldest`` is read from the receipt id, which is a sortable timestamp by
    design — no stat call, and it survives a copy that rewrote mtimes.
    """
    root = state_dir() / "backup" / "mail"
    out = {"path": str(root), "bytes": 0, "receipts": 0, "oldest": None}
    try:
        receipts = sorted(d.name for d in root.iterdir() if d.is_dir())
    except OSError:
        return out
    total = 0
    for name in receipts:
        try:
            for f in (root / name).iterdir():
                if f.is_file():
                    total += f.stat().st_size
        except OSError:
            continue
    out["bytes"] = total
    out["receipts"] = len(receipts)
    # "20260805-001122-123456-000-move" -> the date half is enough to act on.
    out["oldest"] = receipts[0][:8] if receipts else None
    return out


def backup_advisory() -> str | None:
    """The one-line notice a mail write carries once the tree passes ``backup_limit()``,
    or None. Cleanup is a HUMAN act — this names the directory and says to delete it,
    rather than offering to do it: a tool that can erase the backups is a tool that can
    erase the only copy of something it deleted earlier."""
    usage = backup_usage()
    limit = backup_limit()
    if usage["bytes"] < limit:
        return None
    gb = usage["bytes"] / 1024**3
    return (
        f"Mail backup storage is {gb:.1f} GB across {usage['receipts']} receipts "
        f"(oldest {usage['oldest']}), past the {limit / 1024**3:.1f} GB advisory "
        f"threshold. These are undo copies kept forever on purpose; nothing prunes "
        f"them. Tell the user they can delete old ones with `rm -r {usage['path']}` "
        "(this destroys the ability to undo those operations). Do not delete them "
        "yourself."
    )


def purge_backup(receipt_id: str) -> int:
    """Delete one receipt's backup directory; returns the number of files removed.

    Not wired to a tool — the backups are small, plain ``.eml``, and a user who wants
    them gone can delete the directory. It exists so a test can clean up after itself
    without re-implementing the path convention.
    """
    d = state_dir() / "backup" / "mail" / receipt_id.strip()
    if not d.is_dir():
        return 0
    n = len(list(d.glob("*.eml")))
    shutil.rmtree(d)
    return n
