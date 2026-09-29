"""Spike 006 Part B — real moves, Fiction INBOX → Fiction Archive (owner-approved).

Every batch runs through `mail_recover.recoverable()`: backup, receipt, verify.

- `shipped`: `MailAdapter.move_mail` on 1 and 3 messages (the per-id `whose` `_MOVE`),
  its host timeout raised for measurement only; then `MailAdapter.undo` of the 1-message
  receipt, timed.
- `proto`: a by-ID act on 5 and 25 messages. Two bulk reads map Message-ID → Mail's
  internal id; each move addresses `«class mssg» id n` (O(1)); the source reference
  must die (-1728); the destination is checked as a count INCREASE from one bulk read
  before and one after the batch. Then the undone message is re-moved, so the owner's
  end state is "all 34 archived".

Targets: the oldest questionablequesting.com alerts with exactly one copy in INBOX and
none in Archive. Prints and writes timings and statuses, never ids.

    uv run python .planning/spikes/006-mail-move-budget/probe_move.py
"""

from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path

from macos_apps_mcp import runtime
from macos_apps_mcp.adapters import mail, mail_index, mail_recover
from macos_apps_mcp.adapters.mail_addressing import MAILBOX_REF, bare_id, mailbox_args

HERE = Path(__file__).parent
US, RS = "\x1f", "\x1e"
FICTION = "imap://BDA93031-756E-4487-BEDD-F2768006926A"
SRC, DST = f"{FICTION}/INBOX", f"{FICTION}/Archive"
SENDER = "questionablequesting.com"

BULK = (
    MAILBOX_REF
    + """

on run argv
  set mb to my mailboxFor(item 1 of argv, item 2 of argv)
  set us to character id 31
  set rs to character id 30
  with timeout of 900 seconds
  tell application "Mail"
    set mids to message id of every message of mb
    if (item 3 of argv) is "1" then
      set nids to id of every message of mb
    else
      set nids to {}
    end if
  end tell
  end timeout
  set AppleScript's text item delimiters to us
  set a to mids as text
  set b to nids as text
  set AppleScript's text item delimiters to ""
  return a & rs & b
end run"""
)

ACT = (
    MAILBOX_REF
    + """

on run argv
  set src to my mailboxFor(item 1 of argv, item 2 of argv)
  set dst to my mailboxFor(item 3 of argv, item 4 of argv)
  set us to character id 31
  set rs to character id 30
  set AppleScript's text item delimiters to us
  set mids to text items of (item 5 of argv)
  set nids to text items of (item 6 of argv)
  set AppleScript's text item delimiters to ""
  set out to ""
  with timeout of 600 seconds
  tell application "Mail"
    repeat with k from 1 to (count of mids)
      set mid to item k of mids
      set n to (item k of nids) as integer
      set outcome to "unknown"
      try
        set m to «class mssg» id n of src
        set got to ""
        try
          set got to message id of m
        end try
        if got is "" then
          set outcome to "not-in-source"
        else if got is not mid then
          set outcome to "ERROR internal id resolved to another message"
        else
          move m to dst
          set outcome to "moved"
          try
            get message id of («class mssg» id n of src)
            delay 2
            get message id of («class mssg» id n of src)
            set outcome to "ERROR still in source after a 2s re-check"
          end try
        end if
      on error errMsg
        set outcome to "ERROR " & errMsg
      end try
      set out to out & mid & us & outcome & rs
    end repeat
  end tell
  end timeout
  return out
end run"""
)


def bulk(url: str, with_ids: bool) -> tuple[list[str], list[str]]:
    raw = runtime.run_osascript(
        BULK, *mailbox_args(url), "1" if with_ids else "0", timeout=1800
    )
    a, b = raw.split(RS)
    return a.split(US), (b.split(US) if b else [])


def proto_act(timing: dict):
    """An `act` for recoverable(): by-ID moves, constant-cost verification."""

    def act(located) -> dict[str, str]:
        want = [t.id for t in located]
        t0 = time.monotonic()
        mids, nids = bulk(SRC, True)
        timing["bulk_src_s"] = round(time.monotonic() - t0, 2)
        where = {}
        for m, n in zip(mids, nids, strict=True):
            where.setdefault(m, []).append(n)
        t0 = time.monotonic()
        before = Counter(bulk(DST, False)[0])
        timing["bulk_dst_before_s"] = round(time.monotonic() - t0, 2)
        out = {m: "not-in-source" for m in want if len(where.get(m, [])) == 0}
        out |= {
            m: "ERROR more than one copy in source; the by-ID act moves one"
            for m in want
            if len(where.get(m, [])) > 1
        }
        todo = [m for m in want if m not in out]
        t0 = time.monotonic()
        raw = runtime.run_osascript(
            ACT,
            *mailbox_args(SRC),
            *mailbox_args(DST),
            US.join(todo),
            US.join(where[m][0] for m in todo),
            timeout=1800,
        )
        timing["act_s"] = round(time.monotonic() - t0, 2)
        acted = mail._parse_statuses(raw)
        t0 = time.monotonic()
        after = Counter(bulk(DST, False)[0])
        timing["bulk_dst_after_s"] = round(time.monotonic() - t0, 2)
        for m in todo:
            st = acted.get(m, "unknown")
            if st == "moved":
                st = "ok" if after[m] > before[m] else "ERROR not in destination"
            out[m] = st
        return out

    return act


def targets(n: int) -> list[str]:
    c = runtime._open_sqlite_ro(mail_index.envelope_index_path())
    rows = c.execute(
        "select gd.message_id_header, "
        "(select count(*) from messages m2 join mailboxes b2 on b2.ROWID = m2.mailbox "
        " where m2.global_message_id = m.global_message_id and b2.url = ? "
        " and m2.deleted = 0), "
        "(select count(*) from messages m3 join mailboxes b3 on b3.ROWID = m3.mailbox "
        " where m3.global_message_id = m.global_message_id and b3.url = ? "
        " and m3.deleted = 0) "
        "from messages m join mailboxes mb on mb.ROWID = m.mailbox "
        "join addresses a on a.ROWID = m.sender "
        "join message_global_data gd on gd.ROWID = m.global_message_id "
        "where mb.url = ? and m.deleted = 0 and lower(a.address) like ? "
        "order by m.date_received limit ?",
        (SRC, DST, SRC, f"%@{SENDER}", n * 3),
    ).fetchall()
    ids = [bare_id(mid) for mid, in_src, in_dst in rows if in_src == 1 and not in_dst]
    assert len(ids) >= n, f"only {len(ids)} clean targets"
    return ids[:n]


def summary(res: dict) -> dict:
    return dict(Counter(t["status"] for t in res.get("targets", [])))


def main() -> None:
    mail._MOVE_TIMEOUT = 1800.0  # measurement only: the shipped cap is #206's bug
    adapter = mail.MailAdapter()
    ids = targets(34)
    batches = {"shipped-1": ids[:1], "shipped-3": ids[1:4], "proto-5": ids[4:9]}
    batches["proto-25"] = ids[9:34]
    out = {}
    for name, batch in batches.items():
        timing: dict = {}
        t0 = time.monotonic()
        if name.startswith("shipped"):
            res = adapter.move_mail(batch, SRC, DST, dry_run=False)
        else:
            src = mailbox_args(SRC)
            targets_ = [
                mail_recover.Target(
                    id=m, folder=SRC, account=mail_index.account_of(SRC)
                )
                for m in batch
            ]
            res = mail_recover.recoverable(
                "move",
                targets_,
                proto_act(timing),
                present=mail._presence(src),
                destination=DST,
            )
        wall = time.monotonic() - t0
        out[name] = {
            "n": len(batch),
            "wall_s": round(wall, 1),
            "per_msg_s": round(wall / len(batch), 2),
            "statuses": summary(res),
            "phases_s": timing,
            "receipt": res.get("receipt"),
        }
        print(f"{name:10} {json.dumps(out[name])}")
    t0 = time.monotonic()
    res = adapter.undo(out["shipped-1"]["receipt"], dry_run=False)
    out["undo-shipped-1"] = {
        "wall_s": round(time.monotonic() - t0, 1),
        "statuses": summary(res),
        "receipt": res.get("receipt"),
    }
    print(f"undo-1     {json.dumps(out['undo-shipped-1'])}")
    timing = {}
    t0 = time.monotonic()
    res = mail_recover.recoverable(
        "move",
        [
            mail_recover.Target(
                id=ids[0], folder=SRC, account=mail_index.account_of(SRC)
            )
        ],
        proto_act(timing),
        present=mail._presence(mailbox_args(SRC)),
        destination=DST,
    )
    out["re-archive-1"] = {
        "wall_s": round(time.monotonic() - t0, 1),
        "statuses": summary(res),
        "phases_s": timing,
        "receipt": res.get("receipt"),
    }
    print(f"re-arch-1  {json.dumps(out['re-archive-1'])}")
    (HERE / "results-move.json").write_text(json.dumps(out, indent=2) + "\n")


if __name__ == "__main__":
    main()
