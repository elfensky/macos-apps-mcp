"""Mail triage (#178) — "what needs my attention?", answered from headers alone.

Two questions, one plane: ``needs_response`` ranks inbound messages that likely need
the user's reply, ``awaiting_reply`` finds sent messages nobody answered. Both read
through Mail's UNIFIED accessors (``inbox`` / ``sent mailbox``) — no per-account
addressing, no Envelope Index, no body scan — and both classify in pure Python over
US/RS-framed header records, which is what makes the classifiers testable without a
Mac. Deliberately zero coupling to ``mail_index`` / ``mail_addressing``'s resolvers /
``mail_recover``: triage names nothing and mutates nothing.

The result bound is PASSED IN (``limit``) rather than imported: the cap is the
adapter's policy (``mail.MAX_MAILS``), this module is the mechanism — and taking it as
a parameter is also what keeps the import cycle closed (``mail`` imports this module,
never the reverse).
"""

from __future__ import annotations

import email
import re

from .. import runtime
from ..contracts import Pointer
from ..text import (
    RS,
    STRIP_FRAMING,
    US,
    Field,
    _summary,
    addr_list,
    bool_strict,
    clean_summary,
    int_or_zero,
    parse_framed,
)
from .mail_addressing import _norm_mid
from .mail_index import _deeplink

NEEDS_SCAN = 100  # inbox messages scanned newest-first for needs-response
SENT_SCAN = 100  # recent sent messages scanned for awaiting-reply candidates
REFS_SCAN = 150  # inbox reply-headers scanned in the correlation window

# All four scan scripts declare `with timeout of 120 seconds` themselves; the host
# cap must match that budget, not undercut it (#188 — the 30s default killed every
# scan whenever Mail was in the §3c degraded-throughput state). Same pattern as
# _MOVE_TIMEOUT/_SAVE_TIMEOUT: raised host-side ceiling, with the AppleScript-level
# `with timeout` as the second line of defense.
_TRIAGE_TIMEOUT = 120.0

# _INBOX_TRIAGE: newest-first inbox records, US/RS framed. Fields INLINED into the
# concat (a `set x to (read status of m)` statement mis-parses — `read`/`was` lead
# like commands; booleans coerce inside `&`). Subject passes through the shared
# STRIP_FRAMING handler before being joined, so a subject that happens to contain
# those control chars can't desync the parser.
# Addresses bare (extract address from / address of every to recipient, TID-joined)
# — these can't carry framing bytes. Date as seconds-ago. maxN via argv.
# Verified on-device.
_INBOX_TRIAGE = (
    STRIP_FRAMING
    + """

on run argv
  set maxN to (item 1 of argv) as integer
  set us to character id 31
  set rs to character id 30
  set out to ""
  with timeout of 120 seconds
  tell application "Mail"
    set n to (count of messages of inbox)
    if n > maxN then set n to maxN
    repeat with i from 1 to n
      set m to message i of inbox
      set mid to message id of m
      if mid is not missing value and mid is not "" then
        set AppleScript's text item delimiters to ","
        set toJoined to ((address of every to recipient of m) as text)
        set AppleScript's text item delimiters to ""
        set out to out & mid & us & (my stripFraming(subject of m)) & us & ¬
          (extract address from (sender of m)) & us & toJoined & us & ¬
          (((current date) - (date received of m)) as integer) & us & ¬
          (was replied to of m) & us & (read status of m) & us & ¬
          (flagged status of m) & rs
      end if
    end repeat
  end tell
  end timeout
  return out
end run"""
)

# _SENT_TRIAGE: recent sent records from the unified `sent mailbox` (All Sent),
# newest-first. Subject passes through the shared STRIP_FRAMING handler before
# being joined, same rationale as _INBOX_TRIAGE.
_SENT_TRIAGE = (
    STRIP_FRAMING
    + """

on run argv
  set maxN to (item 1 of argv) as integer
  set us to character id 31
  set rs to character id 30
  set out to ""
  with timeout of 120 seconds
  tell application "Mail"
    set sm to sent mailbox
    set n to (count of messages of sm)
    if n > maxN then set n to maxN
    repeat with i from 1 to n
      set m to message i of sm
      set mid to message id of m
      if mid is not missing value and mid is not "" then
        set AppleScript's text item delimiters to ","
        set toJoined to ((address of every to recipient of m) as text)
        set AppleScript's text item delimiters to ""
        set out to out & mid & us & (my stripFraming(subject of m)) & us & ¬
          toJoined & us & (((current date) - (date sent of m)) as integer) & rs
      end if
    end repeat
  end tell
  end timeout
  return out
end run"""
)

# _MY_ADDRESSES: the user's own addresses, US-framed (list-join with TID — element
# iteration raises -1700). Verified on-device.
_MY_ADDRESSES = """on run argv
  set us to character id 31
  set AppleScript's text item delimiters to us
  set out to ""
  with timeout of 120 seconds
  tell application "Mail"
    repeat with acc in accounts
      set out to out & ((email addresses of acc) as text) & us
    end repeat
  end tell
  end timeout
  set AppleScript's text item delimiters to ""
  return out
end run"""

# _INBOX_REFS: for inbox messages received within `cutoffSecs` ago (the correlation
# window), emit the RAW HEADERS (RS-framed) of only those that ARE replies (carry
# In-Reply-To / References) — Python parses referenced ids (stdlib email handles
# folding). Capped at maxN.
_INBOX_REFS = """on run argv
  set cutoffSecs to (item 1 of argv) as integer
  set maxN to (item 2 of argv) as integer
  set rs to character id 30
  set out to ""
  set c to 0
  with timeout of 120 seconds
  tell application "Mail"
    set cutoff to (current date) - cutoffSecs
    repeat with m in (messages of inbox whose date received > cutoff)
      set h to all headers of m
      if (h contains "In-Reply-To:") or (h contains "References:") then
        set c to c + 1
        if c > maxN then exit repeat
        set out to out & h & rs
      end if
    end repeat
  end tell
  end timeout
  return out
end run"""


def _parse_triage_records(raw: str) -> list[dict]:
    """Parse _INBOX_TRIAGE: RS-separated records, US-separated fields (id, subject,
    sender, to_addrs (comma-joined), secs_ago, was_replied_to, read, flagged).
    Malformed/partial records are skipped; addresses lowercased."""
    return parse_framed(
        raw,
        [
            Field("id"),
            Field("subject"),
            Field("sender", lambda s: s.strip().lower()),
            Field("to_addrs", addr_list),
            Field("secs_ago", int_or_zero),
            Field("was_replied_to", bool_strict),
            Field("read", bool_strict),
            Field("flagged", bool_strict),
        ],
    )


def _parse_sent_records(raw: str) -> list[dict]:
    """Parse _SENT_TRIAGE: RS records, US fields (id, subject, recipients, secs_ago)."""
    return parse_framed(
        raw,
        [
            Field("id"),
            Field("subject"),
            Field("recipient_addrs", addr_list),
            Field("secs_ago", int_or_zero),
        ],
    )


def _parse_my_addrs(raw: str) -> set[str]:
    return {a.strip().lower() for a in raw.split(US) if a.strip()}


def _classify_needs_response(
    records: list[dict], my_addrs: set[str], limit: int
) -> list[Pointer]:
    """Rank inbound messages that likely need the user's response. Drops already-replied
    messages; keeps those directly addressed to the user (my_addrs ∩ to_addrs). If
    my_addrs is empty (extraction failed) it degrades to FLAGGED-ONLY rather than
    flooding the inbox. Reasons (stable): flagged > unread-direct > unanswered-direct;
    recency (smallest secs_ago) breaks ties within a tier. Bounded to ``limit``.

    ``folder="inbox"`` (#155): the triage scan runs against Mail's unified `inbox`, so
    "inbox" is both the truth and one of the five canonical names the id-taking tools
    accept. Without it this tool — the documented triage ENTRY POINT — handed back ids
    that ``mail_body``/``mail_reply`` could not take, since both require a mailbox they
    said would come from the read. ``account`` stays unset: a unified accessor spans
    every account, and guessing one would be worse than admitting we don't know."""
    out: list[tuple[int, int, Pointer]] = []
    for r in records:
        if r["was_replied_to"]:
            continue
        direct = bool(my_addrs & set(r["to_addrs"]))
        if my_addrs and not direct:
            continue
        if not my_addrs and not r["flagged"]:
            continue  # can't confirm direct → flagged-only, no flood
        if r["flagged"]:
            tier, reason = 0, "flagged"
        elif not r["read"]:
            tier, reason = 1, "unread-direct"
        else:
            tier, reason = 2, "unanswered-direct"
        p = Pointer(
            id=r["id"],
            summary=clean_summary(_summary(r["subject"], r["sender"])),
            deeplink=_deeplink(r["id"]),
            folder="inbox",
            reason=reason,
        )
        out.append((tier, r["secs_ago"], p))
    out.sort(key=lambda t: (t[0], t[1]))  # tier asc, then most-recent (secs_ago) first
    return [p for _, _, p in out[:limit]]


def _referenced_ids(header_blobs: list[str]) -> set[str]:
    """Message-ids cited by inbox messages via In-Reply-To / References. Each blob is
    one message's raw headers; stdlib email parses folded headers robustly."""
    ids: set[str] = set()
    for blob in header_blobs:
        msg = email.message_from_string(blob)
        refs = f"{msg.get('In-Reply-To', '')} {msg.get('References', '')}"
        for tok in re.findall(r"<[^>]+>", refs):
            ids.add(_norm_mid(tok))
    return ids


def _classify_awaiting_reply(
    sent: list[dict], referenced_ids: set[str], days: int, limit: int
) -> list[Pointer]:
    """Sent messages older than `days` whose Message-ID no inbox message references
    (real In-Reply-To/References threading — accurate, no fuzzy subject matching).
    Reason: stable 'awaiting-reply'. Sorted oldest-sent-first (most overdue). Bounded
    to ``limit``. A group-thread send is cleared if ANY recipient's reply cites it
    (documented).

    ``folder="sent"`` (#155): the scan runs through Mail's unified `sent mailbox`
    accessor, so "sent" is the literal truth AND one of the five canonical names the
    id-taking tools accept — a pointer from here now reaches ``mail_body`` unaided.
    ``account`` stays unset: a unified accessor spans every account, so there is nothing
    honest to put there."""
    cutoff = days * 86400
    out: list[tuple[int, Pointer]] = []
    for r in sent:
        if r["secs_ago"] < cutoff:
            continue
        if _norm_mid(r["id"]) in referenced_ids:
            continue
        to = ", ".join(r["recipient_addrs"]) or "(no recipients)"
        p = Pointer(
            id=r["id"],
            summary=clean_summary(f"{r['subject']} — to {to}"),
            deeplink=_deeplink(r["id"]),
            folder="sent",
            reason="awaiting-reply",
        )
        out.append((r["secs_ago"], p))
    out.sort(key=lambda t: t[0], reverse=True)  # most overdue (largest secs_ago) first
    return [p for _, p in out[:limit]]


def needs_response(limit: int) -> list[Pointer]:
    """The scan behind ``mail_needs_response``: run the inbox triage, learn the user's
    own addresses, classify. ``mail.MailAdapter.get_needs_response`` supplies the
    bound and wraps the answer in the bounded-read envelope."""
    records = _parse_triage_records(
        runtime.run_osascript(_INBOX_TRIAGE, str(NEEDS_SCAN), timeout=_TRIAGE_TIMEOUT)
    )
    my = _parse_my_addrs(runtime.run_osascript(_MY_ADDRESSES, timeout=_TRIAGE_TIMEOUT))
    return _classify_needs_response(records, my, limit)


def awaiting_reply(days: int, limit: int) -> list[Pointer]:
    """The scan behind ``mail_awaiting_reply``: recent sent records, correlated against
    the inbox's In-Reply-To/References headers."""
    if not 1 <= days <= 365:
        raise ValueError("days must be between 1 and 365")
    sent = _parse_sent_records(
        runtime.run_osascript(_SENT_TRIAGE, str(SENT_SCAN), timeout=_TRIAGE_TIMEOUT)
    )
    # The per-record age cutoff is applied in ONE place —
    # _classify_awaiting_reply. Here only the correlation window is sized:
    # scan inbox back to the oldest send; if even that is younger than the
    # cutoff, no send can qualify, so skip the inbox scan entirely.
    window = max((r["secs_ago"] for r in sent), default=0)
    if window < days * 86400:
        return []
    blobs = [
        b
        for b in runtime.run_osascript(
            _INBOX_REFS, str(window), str(REFS_SCAN), timeout=_TRIAGE_TIMEOUT
        ).split(RS)
        if b.strip()
    ]
    return _classify_awaiting_reply(sent, _referenced_ids(blobs), days, limit)
