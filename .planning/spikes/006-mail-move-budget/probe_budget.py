"""Spike 006 — what does one `whose message id is` scan cost, by mailbox size?

Part `scan` (read-only): per mailbox, one `count of messages`, then a timed
`count of (messages of mb whose message id is mid)` for the oldest, median and newest
message and one missing id, 3 reps each, then one bulk `message id of every message`.
Part `present` (read-only): the shipped `_PRESENT` script (the move/trash dry run) on
1, 5 and 25 ids of the 9k+ INBOX.

    uv run python .planning/spikes/006-mail-move-budget/probe_budget.py scan
    uv run python .planning/spikes/006-mail-move-budget/probe_budget.py present

Prints and writes position labels and timings, never message ids.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

from macos_apps_mcp import runtime
from macos_apps_mcp.adapters import mail, mail_index
from macos_apps_mcp.adapters.mail_addressing import MAILBOX_REF, bare_id, mailbox_args

HERE = Path(__file__).parent
US = "\x1f"
MISSING = "gsd-spike-006-missing@example.invalid"
ACCOUNTS = {  # name -> uuid; Grandma and Mama are never probe targets
    "Business": "02B406D0-99D4-4E9A-9A7C-0DB912FD1D93",
    "Personal": "AE0EAE3D-449A-4B33-A923-FBFDB3DD13A1",
    "Fiction": "BDA93031-756E-4487-BEDD-F2768006926A",
}
MAILBOXES = [  # smallest first, so the first store load is not blamed on size
    ("Business", "INBOX"),
    ("Personal", "INBOX"),
    ("Personal", "Travel"),
    ("Fiction", "Trash"),
    ("Fiction", "FanfictionNet"),
    ("Fiction", "INBOX"),
    ("Fiction", "Archive"),
]
BIG = ("Fiction", "INBOX")

SCAN = (
    'use framework "Foundation"\nuse scripting additions\n\n'
    + MAILBOX_REF
    + """

on now()
  return (current application's NSDate's timeIntervalSinceReferenceDate()) as real
end now

on run argv
  set mb to my mailboxFor(item 1 of argv, item 2 of argv)
  set us to character id 31
  set AppleScript's text item delimiters to us
  set ids to text items of (item 3 of argv)
  set AppleScript's text item delimiters to ""
  set reps to (item 4 of argv) as integer
  set out to ""
  with timeout of 900 seconds
  tell application "Mail"
    set t0 to my now()
    set n to count of messages of mb
    set out to out & "count" & us & n & us & ((my now()) - t0) & linefeed
    repeat with r from 1 to reps
      repeat with k from 1 to (count of ids)
        set mid to item k of ids
        set t0 to my now()
        set c to count of (messages of mb whose message id is mid)
        set out to out & "scan" & us & k & us & c & us & ((my now()) - t0) & linefeed
      end repeat
    end repeat
    set t0 to my now()
    set allIds to message id of every message of mb
    set out to out & "bulk" & us & (count of allIds) & us & ((my now()) - t0) & linefeed
  end tell
  end timeout
  return out
end run"""
)


def secs(s: str) -> float:
    return float(s.replace(",", "."))


def url_for(acct: str, path: str) -> str:
    url = f"imap://{ACCOUNTS[acct]}/{path}"
    c = runtime._open_sqlite_ro(mail_index.envelope_index_path())
    assert c.execute("select 1 from mailboxes where url = ?", (url,)).fetchone(), url
    return url


def samples(url: str, n: int = 3) -> list[str]:
    """Bare ids spread over the mailbox by date: oldest, ..., newest."""
    c = runtime._open_sqlite_ro(mail_index.envelope_index_path())
    ids = [
        bare_id(mid)
        for (mid,) in c.execute(
            "select gd.message_id_header from messages m "
            "join mailboxes mb on mb.ROWID = m.mailbox "
            "join message_global_data gd on gd.ROWID = m.global_message_id "
            "where mb.url = ? and m.deleted = 0 and gd.message_id_header != '' "
            "order by m.date_received",
            (url,),
        )
    ]
    if not ids:
        return []
    if n == 1:
        return [ids[len(ids) // 2]]
    return [ids[round(i * (len(ids) - 1) / (n - 1))] for i in range(n)]


def run_scan() -> dict:
    out = {}
    for acct, path in MAILBOXES:
        url = url_for(acct, path)
        ids = samples(url) + [MISSING]
        labels = ["oldest", "median", "newest"][: len(ids) - 1] + ["missing"]
        t0 = time.monotonic()
        raw = runtime.run_osascript(
            SCAN, *mailbox_args(url), US.join(ids), "3", timeout=1800
        )
        wall = time.monotonic() - t0
        scans: dict[str, list[float]] = {k: [] for k in labels}
        hits: dict[str, int] = {}
        for line in raw.splitlines():
            f = line.split(US)
            if f[0] == "count":
                n, t_count = int(f[1]), secs(f[2])
            elif f[0] == "scan":
                label = labels[int(f[1]) - 1]
                scans[label].append(secs(f[3]))
                hits[label] = int(f[2])
            elif f[0] == "bulk":
                bulk_n, t_bulk = int(f[1]), secs(f[2])
        scans = {k: v for k, v in scans.items() if v}
        allscans = [t for ts in scans.values() for t in ts]
        row = {
            "messages": n,
            "count_s": round(t_count, 3),
            "scan_median_s": round(statistics.median(allscans), 3),
            "scan_max_s": round(max(allscans), 3),
            "scan_by_position_s": {
                k: [round(t, 3) for t in v] for k, v in scans.items()
            },
            "hits": hits,
            "bulk_ids": bulk_n,
            "bulk_s": round(t_bulk, 3),
            "wall_s": round(wall, 1),
        }
        out[f"{acct}/{path}"] = row
        print(
            f"{acct + '/' + path:18} n={n:6} scan med={row['scan_median_s']:.3f}s "
            f"max={row['scan_max_s']:.3f}s bulk={t_bulk:.2f}s ({bulk_n}) "
            f"wall={wall:.1f}s hits={hits}"
        )
        for k, v in row["scan_by_position_s"].items():
            print(f"    {k:8} {v}")
    return out


def run_present() -> dict:
    """The shipped dry-run read, `_PRESENT`, timed end to end from the host."""
    url = url_for(*BIG)
    ids = samples(url, 25)
    out = {}
    for n in (1, 5, 25, 25):
        chosen = ids[:: max(1, 25 // n)][:n]
        t0 = time.monotonic()
        raw = runtime.run_osascript(
            mail._PRESENT, *mailbox_args(url), US.join(chosen), timeout=1800
        )
        wall = time.monotonic() - t0
        present = raw.count("present")
        key = f"n={n}" if f"n={n}" not in out else f"n={n} (repeat)"
        out[key] = {
            "wall_s": round(wall, 1),
            "per_id_s": round(wall / n, 2),
            "present": present,
        }
        print(f"_PRESENT {key:14} {wall:6.1f}s  {wall / n:5.2f}s/id  present={present}")
    return out


# Every way to reach one message, timed on a healthy Mail. `«class mssg» id n` is the
# by-ID reference form Mail itself prints (facts §3b); the English `message id n`
# would parse as the `message id` property.
PRIMITIVES = (
    'use framework "Foundation"\nuse scripting additions\n\n'
    + MAILBOX_REF
    + """

on now()
  return (current application's NSDate's timeIntervalSinceReferenceDate()) as real
end now

on run argv
  set mb to my mailboxFor(item 1 of argv, item 2 of argv)
  set mid to item 3 of argv
  set us to character id 31
  set out to ""
  with timeout of 900 seconds
  tell application "Mail"
    repeat 2 times
      set t0 to my now()
      set c to count of (messages of mb whose message id is mid)
      set out to out & "whose-mid" & us & c & us & ((my now()) - t0) & linefeed
    end repeat
    set t0 to my now()
    set mids to message id of every message of mb
    set out to out & "bulk-mid" & us & (count of mids) & us & ¬
      ((my now()) - t0) & linefeed
    set t0 to my now()
    set nids to id of every message of mb
    set out to out & "bulk-id" & us & (count of nids) & us & ¬
      ((my now()) - t0) & linefeed
  end tell
  set t0 to my now()
  set k to 0
  repeat with i from 1 to count of mids
    if item i of mids is mid then
      set k to i
      exit repeat
    end if
  end repeat
  set out to out & "find-in-list" & us & k & us & ((my now()) - t0) & linefeed
  set n to item k of nids
  tell application "Mail"
    set t0 to my now()
    set got to message id of message k of mb
    set out to out & "by-index" & us & (got is mid) & us & ((my now()) - t0) & linefeed
    set t0 to my now()
    try
      set got to message id of («class mssg» id n of mb)
      set out to out & "by-id" & us & (got is mid) & us & ((my now()) - t0) & linefeed
    on error e number en
      set out to out & "by-id" & us & "ERR " & en & us & ((my now()) - t0) & linefeed
    end try
    set t0 to my now()
    set got to message id of (first message of mb whose id is n)
    set out to out & "whose-id" & us & (got is mid) & us & ((my now()) - t0) & linefeed
  end tell
  end timeout
  return out
end run"""
)


def run_rescan() -> dict:
    out = {}
    for acct, path in (BIG, ("Fiction", "Archive")):
        url = url_for(acct, path)
        (mid,) = samples(url, 1)
        raw = runtime.run_osascript(PRIMITIVES, *mailbox_args(url), mid, timeout=1800)
        rows = [line.split(US) for line in raw.splitlines()]
        res = {}
        for name, val, t in rows:
            res.setdefault(name, []).append({"result": val, "s": round(secs(t), 3)})
        out[f"{acct}/{path}"] = res
        print(f"{acct}/{path}")
        for name, v in res.items():
            print(f"    {name:12} {v}")
    return out


def main() -> None:
    part = sys.argv[1] if len(sys.argv) > 1 else "scan"
    res = {"scan": run_scan, "present": run_present, "rescan": run_rescan}[part]()
    (HERE / f"results-{part}.json").write_text(json.dumps(res, indent=2) + "\n")


if __name__ == "__main__":
    main()
