"""Shared test fakes — plain SimpleNamespace stand-ins for EventKit objects,
used by the calendar and reminders adapter tests (no native calls)."""

from __future__ import annotations

from itertools import count as _counter
from types import SimpleNamespace

from macos_apps_mcp.text import RS, US


def fake_rule(freq=0, interval=1, count=None):
    # freq is the EKRecurrenceFrequency int (daily=0, weekly=1, monthly=2, yearly=3).
    end = None if count is None else SimpleNamespace(occurrenceCount=lambda: count)
    return SimpleNamespace(
        frequency=lambda: freq, interval=lambda: interval, recurrenceEnd=lambda: end
    )


class FakeMail:
    """A tiny in-memory Mail store answering ``mail._BULK``, ``mail._MOVE`` and
    ``mail._PRESENT`` by SCRIPT IDENTITY (``is``, not source-text equality) — install
    with ``monkeypatch.setattr(runtime, "run_osascript", fake)``.

    State: ``{(account, path): [(internal_id, message_id), ...]}``, one entry per
    stored copy, in insertion ("bulk read") order — the same key shape
    ``mail_addressing.mailbox_args`` returns (a unified accessor is ``("", "drafts")``).
    Every call is recorded in ``.calls`` as ``(script, args, kwargs)``.

    Knobs for the by-ID move's failure paths (#206, D-01/D-03):
    - ``lands_nowhere``: internal ids whose move reports ``"moved"`` but the copy is
      removed from the source and never actually inserted at the destination — this is
      what makes the Python-side act closure's own count-increase check fail and fold
      to the "not in the destination" ERROR, so the fake must NOT pre-empt that by
      answering the ERROR text itself.
    - ``survives``: internal ids whose source copy "survives" the move (the post-move
      probe would still read it) — the fake answers the exact self-move ERROR text
      ``_MOVE`` itself would emit, and leaves the copy present in BOTH mailboxes.

    Knobs for the by-ID trash's three verification outcomes (#206, D-01, facts §5c —
    delete is ASYNCHRONOUS on the source side, so the script's own per-copy status and
    whether the copy actually lands at the destination are independent):
    - ``trash_rise_only``: the copy lands at the destination (its count rises) but the
      script still reports ``"deleted"`` (the source reference has not died yet) —
      verified ``ok`` by the destination rise alone.
    - ``trash_gone_only``: the source reference dies (reported ``"gone"``) but the copy
      never lands at the destination — verified ``ok`` because every copy is ``"gone"``,
      never because of a rise that didn't happen.
    - ``trash_neither``: the copy neither lands at the destination nor is reported
      gone — the one case that must fold to an ``ERROR``, never a silent ``ok``.
    - ``raise_for``: ``{script: exception}`` — raise instead of answering, for a given
      script object.

    Any script this fake doesn't recognize raises ``AssertionError`` (fail closed).
    """

    SURVIVES_ERROR = (
        "ERROR the message reads present in BOTH mailboxes after a 2s re-check — "
        "either the source copy survived, or the destination resolves to the source "
        "itself (a self-move, which changes nothing). Nothing was deleted; re-locate "
        "the message before acting on either reading"
    )

    def __init__(self) -> None:
        self._ids = _counter(1)
        self.boxes: dict[tuple[str, str], list[tuple[int, str]]] = {}
        self.calls: list[tuple[object, tuple, dict]] = []
        self.lands_nowhere: set[int] = set()
        self.survives: set[int] = set()
        self.trash_rise_only: set[int] = set()
        self.trash_gone_only: set[int] = set()
        self.trash_neither: set[int] = set()
        self.raise_for: dict[object, Exception] = {}

    def seed(self, box: tuple[str, str], *message_ids: str) -> list[int]:
        """Add copies to ``box``, each minted a fresh, globally-unique internal id.
        Returns the minted ids in the same order as ``message_ids``."""
        out = []
        for mid in message_ids:
            nid = next(self._ids)
            self.boxes.setdefault(box, []).append((nid, mid))
            out.append(nid)
        return out

    def __call__(self, script, *args, **kwargs):
        self.calls.append((script, args, kwargs))
        if script in self.raise_for:
            raise self.raise_for[script]
        from macos_apps_mcp.adapters import mail as _mail

        if script is _mail._BULK:
            return self._bulk(args)
        if script is _mail._MOVE:
            return self._move(args)
        if script is _mail._TRASH:
            return self._trash(args)
        if script is _mail._PRESENT:
            return self._present(args)
        raise AssertionError(f"FakeMail has no answer for this script: {script!r}")

    def _bulk(self, args):
        account, path, want_internal = args[0], args[1], args[2]
        copies = self.boxes.get((account, path), [])
        mids = US.join(mid for _, mid in copies)
        nids = US.join(str(nid) for nid, _ in copies) if want_internal == "1" else ""
        return mids + RS + nids

    def _move(self, args):
        src_acct, src_path, dst_acct, dst_path, mids_joined, nids_joined = args
        src = (src_acct, src_path)
        dst = (dst_acct, dst_path)
        mids = mids_joined.split(US) if mids_joined else []
        nids = [int(n) for n in nids_joined.split(US)] if nids_joined else []
        out: list[tuple[int, str]] = []
        for mid, nid in zip(mids, nids, strict=True):
            copies = self.boxes.setdefault(src, [])
            idx = next((i for i, (n, _m) in enumerate(copies) if n == nid), None)
            if idx is None:
                out.append((nid, "not-in-source"))
                continue
            _, stored_mid = copies[idx]
            if stored_mid != mid:
                out.append((nid, "ERROR internal id resolved to another message"))
                continue
            del copies[idx]
            if nid in self.lands_nowhere:
                # the script reports "moved" — nothing actually lands at dst, so the
                # PYTHON-side count-increase check is what must catch this, not us.
                out.append((nid, "moved"))
                continue
            self.boxes.setdefault(dst, []).append((nid, mid))
            if nid in self.survives:
                copies.append((nid, mid))  # the source copy "survives"
                out.append((nid, self.SURVIVES_ERROR))
                continue
            out.append((nid, "moved"))
        return "".join(f"{nid}{US}{status}{RS}" for nid, status in out)

    def _trash(self, args):
        src_acct, src_path, dst_acct, dst_path, mids_joined, nids_joined = args
        src = (src_acct, src_path)
        dst = (dst_acct, dst_path)
        mids = mids_joined.split(US) if mids_joined else []
        nids = [int(n) for n in nids_joined.split(US)] if nids_joined else []
        out: list[tuple[int, str]] = []
        for mid, nid in zip(mids, nids, strict=True):
            copies = self.boxes.setdefault(src, [])
            idx = next((i for i, (n, _m) in enumerate(copies) if n == nid), None)
            if idx is None:
                out.append((nid, "not-in-source"))
                continue
            _, stored_mid = copies[idx]
            if stored_mid != mid:
                out.append((nid, "ERROR internal id resolved to another message"))
                continue
            if nid in self.trash_neither:
                # the delete call returns cleanly but nothing actually happened — the
                # source copy stays and the destination never grows. The one case the
                # Python fold must turn into an ERROR, never a silent "ok".
                out.append((nid, "deleted"))
                continue
            del copies[idx]
            if nid in self.trash_gone_only:
                # the source reference died (reported "gone"), but the copy never
                # lands at the destination — source absence alone must be enough here
                # (facts §5c: delete clears the source asynchronously).
                out.append((nid, "gone"))
                continue
            self.boxes.setdefault(dst, []).append((nid, mid))
            if nid in self.trash_rise_only:
                # lands at the destination (its count rises) but the script still
                # reports the copy as readable — the asynchronous source side hasn't
                # caught up yet.
                out.append((nid, "deleted"))
                continue
            out.append((nid, "gone"))
        return "".join(f"{nid}{US}{status}{RS}" for nid, status in out)

    def _present(self, args):
        box = (args[0], args[1])
        ids = args[2].split(US) if args[2] else []
        stored = {mid for _, mid in self.boxes.get(box, [])}
        return "".join(
            f"{mid}{US}{'present' if mid in stored else 'missing'}{RS}"
            for mid in ids
            if mid
        )
