"""Spike 005 — what does Mail do with a sender that no account owns?

Part `sender`: builds outgoing messages with a chosen `sender` (the `send_mail` verb),
windowless and visible, waits past the autosave window (facts §2), reads the autosaved
draft's From header, then deletes the outgoing messages and the drafts. Nothing is sent.
Part `reply`: runs Mail's `reply` verb (the `mail_reply` shape) on INBOX messages of
non-default accounts, reads the reply's sender, and deletes it before send.

    uv run python .planning/spikes/005-mail-unowned-from/probe_sender.py sender
    uv run python .planning/spikes/005-mail-unowned-from/probe_sender.py controls
    uv run python .planning/spikes/005-mail-unowned-from/probe_sender.py reply

Prints and writes roles, never addresses.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import uuid
from email.utils import parseaddr
from pathlib import Path

from macos_apps_mcp import runtime
from macos_apps_mcp.adapters import mail_index
from macos_apps_mcp.adapters.mail_addressing import MAILBOX_REF, bare_id

HERE = Path(__file__).parent
US, RS = "\x1f", "\x1e"
WAIT = 25  # facts §2: autosave lands ~10-15 s late; assert no earlier than 20 s
EXCLUDED = {"Grandma", "Mama"}  # family members' mail: never a probe target
NONDEFAULT = "Business"  # the #208 scenario
UNOWNED = "gsd-spike-005@example.invalid"  # RFC 2606: never deliverable
UNOWNED_OWNED_DOMAIN = "spike005-nobody@lav.ren"  # a domain two accounts share
UNOWNED_BIZ_DOMAIN = "spike005-nobody@drunik.be"  # a non-default account's domain
PREFIX = "gsd-spike-005"


def osa(script: str, *args: str, timeout: int = 240) -> str:
    """Raw osascript, not runtime.run_osascript: its 30 s cap is too short here."""
    p = subprocess.run(
        ["osascript", "-", *args],
        input=script,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if p.returncode:
        raise RuntimeError(p.stderr.strip())
    return p.stdout.rstrip("\n")


def records(raw: str) -> list[list[str]]:
    return [r.split(US) for r in raw.split(RS) if r]


ACCOUNTS = """on run argv
  set out to ""
  tell application "Mail"
    repeat with a in every account
      set addrs to email addresses of a
      repeat with e in addrs
        set out to out & (id of a) & (character id 31) & (name of a) & ¬
          (character id 31) & (contents of e) & (character id 30)
      end repeat
    end repeat
  end tell
  return out
end run"""


def accounts() -> tuple[dict[str, str], dict[str, str]]:
    """(address -> account name, account id -> account name)."""
    by_addr, by_id = {}, {}
    for aid, name, addr in records(osa(ACCOUNTS)):
        by_addr[addr.lower()] = name
        by_id[aid] = name
    return by_addr, by_id


def role(value: str, by_addr: dict[str, str]) -> str:
    """Map a sender string ("Name <addr>" or bare) to a role; never the address."""
    if value.startswith("ERR") or value in ("", "(missing)"):
        return value or "(empty)"
    addr = parseaddr(value)[1].lower()
    if addr in by_addr:
        return f"account:{by_addr[addr]}"
    if addr == UNOWNED:
        return "kept:unowned"
    if addr == UNOWNED_OWNED_DOMAIN:
        return "kept:unowned-owned-domain"
    if addr == UNOWNED_BIZ_DOMAIN:
        return "kept:unowned-biz-domain"
    return "other:" + mask(value)


def mask(value: str) -> str:
    """The shape of a string without its letters: 'Ab <a@a.a>' for 'Jo <x@y.be>'."""
    out = []
    for ch in value:
        k = (
            "A"
            if ch.isupper()
            else "a"
            if ch.isalpha()
            else "9"
            if ch.isdigit()
            else ch
        )
        if not (out and out[-1] == k and k in "Aa9"):
            out.append(k)
    return "".join(out)


CREATE = """on run argv
  set us to character id 31
  set rs to character id 30
  set out to ""
  with timeout of 120 seconds
  tell application "Mail"
    repeat with k from 2 to (count of argv)
      set AppleScript's text item delimiters to us
      set parts to text items of (item k of argv)
      set AppleScript's text item delimiters to ""
      set caseName to item 1 of parts
      set snd to item 3 of parts
      set msg to make new outgoing message with properties ¬
        {visible:((item 2 of parts) is "1")}
      set subject of msg to (item 1 of argv) & " " & caseName
      tell msg to make new to recipient with properties {address:"andrei@lav.ren"}
      if (item 4 of parts) is not "" then set content of msg to item 4 of parts
      set setErr to ""
      if snd is not "" then
        try
          set sender of msg to snd
        on error e number n
          set setErr to (n as text) & " " & e
        end try
      end if
      try
        set rb to sender of msg
        if rb is missing value then set rb to "(missing)"
      on error e number n
        set rb to "ERR " & (n as text)
      end try
      set out to out & caseName & us & setErr & us & rb & rs
    end repeat
  end tell
  end timeout
  return out
end run"""

# Drafts by index, never `whose` (facts §6); all subjects in one Apple Event. The
# account comes from the concrete mailbox the draft sits in, so a draft filed under
# another account shows up.
INSPECT = """on run argv
  set us to character id 31
  set rs to character id 30
  set out to ""
  with timeout of 120 seconds
  tell application "Mail"
    set dm to drafts mailbox
    set subs to subject of every message of dm
    set out to "count" & us & ((count of subs) as text) & rs
    repeat with i from 1 to (count of subs)
      set subj to item i of subs
      if subj is missing value then set subj to ""
      if subj contains (item 1 of argv) then
        set m to message i of dm
        set acct to "?"
        try
          set acct to id of account of mailbox of m
        end try
        set snd to ""
        try
          set snd to sender of m
        end try
        set out to out & subj & us & snd & us & acct & us & ¬
          (all headers of m) & rs
      end if
    end repeat
  end tell
  end timeout
  return out
end run"""

DELETE_OUTGOING = """on run argv
  set gone to 0
  set kept to 0
  with timeout of 120 seconds
  tell application "Mail"
    repeat with i from (count of outgoing messages) to 1 by -1
      set m to outgoing message i
      set subj to ""
      try
        set subj to subject of m
      end try
      if subj starts with (item 1 of argv) then
        delete m
        try
          get subject of m
          set kept to kept + 1
        on error number en
          if en is -1728 then
            set gone to gone + 1
          else
            set kept to kept + 1
          end if
        end try
      end if
    end repeat
  end tell
  end timeout
  return (gone as text) & " " & (kept as text)
end run"""

DELETE_DRAFTS = """on run argv
  set c to 0
  with timeout of 120 seconds
  tell application "Mail"
    set dm to drafts mailbox
    set subs to subject of every message of dm
    repeat with i from (count of subs) to 1 by -1
      set subj to item i of subs
      if subj is not missing value and subj contains (item 1 of argv) then
        delete (message i of dm)
        set c to c + 1
      end if
    end repeat
  end tell
  end timeout
  return c as text
end run"""


def header(headers: str, name: str) -> str:
    for line in headers.splitlines():
        if line.lower().startswith(name.lower() + ":"):
            return line.split(":", 1)[1].strip()
    return ""


def inspect(tag: str, by_addr, by_id) -> dict:
    out = {"drafts_total": None, "drafts": {}}
    for rec in records(osa(INSPECT, tag)):
        if rec[0] == "count":
            out["drafts_total"] = int(rec[1])
            continue
        subj, snd, acct, headers = rec[0], rec[1], rec[2], US.join(rec[3:])
        case = subj.split(tag, 1)[1].strip()
        out["drafts"].setdefault(case, []).append(
            {
                "sender": role(snd, by_addr),
                "from_header": role(header(headers, "From"), by_addr),
                "filed_in": by_id.get(acct, acct),
                "in_reply_to": bool(header(headers, "In-Reply-To")),
            }
        )
    return out


def index_hits(tag: str) -> list[str]:
    """Where the Envelope Index sees the tag, in any mailbox (catches On My Mac)."""
    c = runtime._open_sqlite_ro(mail_index.envelope_index_path())
    rows = c.execute(
        "select mb.url from messages m join subjects s on s.ROWID = m.subject "
        "join mailboxes mb on mb.ROWID = m.mailbox where s.subject like ? "
        "and m.deleted = 0",
        (f"%{tag}%",),
    ).fetchall()
    return sorted(u.split("/", 3)[-1] for (u,) in rows)


def sender_cases(part: str, nondefault: str) -> list[tuple[str, str, str, str]]:
    """(case, visible, sender, content). `controls` is visible-only: in the facts §3c
    state a windowless message survives `delete`, a visible one does not."""
    if part == "autosave":  # separates "no content" from "short wait" (round 1)
        return [("visible-default-bare", "1", "", "")]
    if part == "controls":
        return [
            ("visible-unowned-biz-domain", "1", UNOWNED_BIZ_DOMAIN, ""),
            ("visible-owned-upper", "1", nondefault.upper(), ""),
            ("visible-default-content", "1", "", "gsd-spike-005 body"),
            ("visible-owned-content", "1", nondefault, "gsd-spike-005 body"),
        ]
    return [
        ("hidden-default", "0", "", ""),
        ("hidden-owned", "0", nondefault, ""),
        ("hidden-owned-display", "0", f"Andrei Lavrenov <{nondefault}>", ""),
        ("hidden-owned-upper", "0", nondefault.upper(), ""),
        ("hidden-unowned", "0", UNOWNED, ""),
        ("hidden-unowned-owned-domain", "0", UNOWNED_OWNED_DOMAIN, ""),
        ("visible-default", "1", "", ""),
        ("visible-owned", "1", nondefault, ""),
        ("visible-unowned", "1", UNOWNED, ""),
    ]


def run_sender(part: str) -> dict:
    by_addr, by_id = accounts()
    nondefault = next(a for a, n in by_addr.items() if n == NONDEFAULT)
    tag = f"{PREFIX} {uuid.uuid4().hex[:8]}"
    cases = sender_cases(part, nondefault)
    wait = WAIT if part == "sender" else 60
    before = inspect(tag, by_addr, by_id)["drafts_total"]
    t0 = time.monotonic()
    created = {}
    for case, set_err, rb in records(osa(CREATE, tag, *(US.join(c) for c in cases))):
        created[case] = {"set_error": set_err, "readback": role(rb, by_addr)}
    print(f"created {len(created)} in {time.monotonic() - t0:.1f}s")
    for case, r in created.items():
        print(
            f"  {case:30} set_error={r['set_error'] or '-':6} readback={r['readback']}"
        )
    time.sleep(wait)
    autosaved = inspect(tag, by_addr, by_id)
    print(f"after {wait}s: drafts {before} -> {autosaved['drafts_total']}")
    for case, ds in sorted(autosaved["drafts"].items()):
        for d in ds:
            print(f"  {case:30} {d}")
    gone_kept = osa(DELETE_OUTGOING, tag)
    print(f"outgoing deleted (gone kept): {gone_kept}")
    time.sleep(WAIT)
    after_del = inspect(tag, by_addr, by_id)
    print(f"after outgoing delete + {WAIT}s: tagged drafts {len(after_del['drafts'])}")
    removed = osa(DELETE_DRAFTS, tag)
    time.sleep(WAIT)
    final = inspect(tag, by_addr, by_id)
    left = sum(len(v) for v in final["drafts"].values())
    print(f"drafts deleted: {removed}; left={left}; total {final['drafts_total']}")
    print(f"index hits (not deleted): {index_hits(tag)}")
    return {
        "tag": tag,
        "created": created,
        "autosaved": autosaved["drafts"],
        "drafts_before": before,
        "drafts_after_autosave": autosaved["drafts_total"],
        "outgoing_gone_kept": gone_kept,
        "tagged_drafts_after_outgoing_delete": len(after_del["drafts"]),
        "drafts_deleted": int(removed),
        "left": left,
        "drafts_final": final["drafts_total"],
    }


REPLY = (
    MAILBOX_REF
    + """

on run argv
  set us to character id 31
  set rs to character id 30
  set out to ""
  repeat with k from 2 to (count of argv)
    set AppleScript's text item delimiters to us
    set parts to text items of (item k of argv)
    set AppleScript's text item delimiters to ""
    set mb to my mailboxFor(item 2 of parts, "INBOX")
    with timeout of 120 seconds
    tell application "Mail"
      set matches to (messages of mb whose message id is (item 3 of parts))
      if (count of matches) is 0 then
        set out to out & (item 1 of parts) & us & "NOT FOUND" & us & "" & us & "" & rs
      else
        set r to reply (item 1 of matches) opening window yes
        set subject of r to (item 1 of argv) & " " & (item 1 of parts)
        set rb to sender of r
        set tos to ""
        try
          repeat with t in (to recipients of r)
            set tos to tos & (address of t) & ","
          end repeat
        end try
        delete r
        set gone to "kept"
        try
          get subject of r
        on error number en
          if en is -1728 then set gone to "gone"
        end try
        set out to out & (item 1 of parts) & us & rb & us & gone & us & tos & rs
      end if
    end tell
    end timeout
  end repeat
  return out
end run"""
)


def reply_targets(by_addr: dict[str, str], by_id: dict[str, str]) -> list[tuple]:
    """Newest INBOX message per case: (label, account id, bare id, from, addressed).

    A message FROM a configured account is Mail's "my own message" case. The target
    sits in Personal's INBOX; the excluded accounts are never touched."""
    c = runtime._open_sqlite_ro(mail_index.envelope_index_path())
    ids = {n: i for i, n in by_id.items()}
    out = []
    for label, acct, sender in (
        ("business-direct", "Business", None),
        ("icloud-direct", "iCloud", None),
        ("personal-from-grandma", "Personal", "Grandma"),
        ("personal-from-mama", "Personal", "Mama"),
    ):
        rows = c.execute(
            "select gd.message_id_header, lower(fa.address), "
            "group_concat(lower(ra.address)) "
            "from messages m join mailboxes mb on mb.ROWID = m.mailbox "
            "join message_global_data gd on gd.ROWID = m.global_message_id "
            "left join addresses fa on fa.ROWID = m.sender "
            "left join recipients r on r.message = m.ROWID "
            "left join addresses ra on ra.ROWID = r.address "
            "where mb.url = ? and m.deleted = 0 group by m.ROWID "
            "order by m.date_received desc limit 200",
            (f"imap://{ids[acct]}/INBOX",),
        ).fetchall()
        for mid, frm, rcpts in rows:
            to = sorted({by_addr[a] for a in (rcpts or "").split(",") if a in by_addr})
            if mid and by_addr.get(frm) == sender and (sender or acct in to):
                out.append((label, ids[acct], bare_id(mid), sender or "other", to))
                break
    return out


def run_reply() -> dict:
    by_addr, by_id = accounts()
    tag = f"{PREFIX} {uuid.uuid4().hex[:8]}"
    targets = reply_targets(by_addr, by_id)
    before = inspect(tag, by_addr, by_id)["drafts_total"]
    raw = osa(REPLY, tag, *(US.join(t[:3]) for t in targets))
    result = {}
    for (label, _, _, frm, to), (lab, rb, gone, tos) in zip(
        targets, records(raw), strict=True
    ):
        assert label == lab
        result[label] = {
            "receiving": label.split("-")[0],
            "original_from": frm,
            "original_to": to,
            "reply_sender": role(rb, by_addr),
            "reply_to": [role(a, by_addr) for a in tos.split(",") if a],
            "outgoing": gone,
        }
        print(f"  {label:18} {result[label]}")
    time.sleep(WAIT)
    litter = inspect(tag, by_addr, by_id)
    print(
        f"after {WAIT}s: drafts {before} -> {litter['drafts_total']}, "
        f"tagged {len(litter['drafts'])}"
    )
    removed = osa(DELETE_DRAFTS, tag) if litter["drafts"] else "0"
    return {
        "tag": tag,
        "replies": result,
        "drafts_before": before,
        "drafts_after": litter["drafts_total"],
        "tagged_litter": litter["drafts"],
        "litter_deleted": int(removed),
    }


def main() -> None:
    part = sys.argv[1] if len(sys.argv) > 1 else "sender"
    res = run_reply() if part == "reply" else run_sender(part)
    (HERE / f"results-{part}.json").write_text(json.dumps(res, indent=2) + "\n")


if __name__ == "__main__":
    main()
