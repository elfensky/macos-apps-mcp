"""Mail adapter — Mail.app via osascript (Automation TCC): inbox search, body-by-id, and
a draft-and-open write.

Mail has a rich AppleScript dictionary. ``Pointer.id`` is the RFC822 ``message id``
(stable across relaunch — the citation contract), NOT the AppleScript object ``id`` (a
session-local integer that rots across relaunch, so never a durable citation). Actions
resolve a message BY that RFC id. ``deeplink`` is a ``message://`` URL built from the
same RFC id. Search matches subject OR sender over the inbox; ``mail_body`` hydrates one
message's plaintext by id (hygiene-budgeted). ``create_draft`` opens a draft for HUMAN
review — there is NO send path anywhere (the surveyed-consensus safe shape: a wrong-
recipient/address-leak send is the ecosystem's most dangerous mail tool). Mail's
AppleScript is slow on large mailboxes, so reads are capped and the osascript timeout
bounds a pathological search. User input goes via argv / a tempfile — not interpolated.
"""

from __future__ import annotations

import email
import re
from urllib.parse import quote

from ..contracts import Pointer
from ..errors import NativeError
from ..runtime import body_file, run_osascript
from ..text import (
    RS,
    STRIP_FRAMING,
    US,
    clean_body,
    clean_summary,
    sanitize_line,
    split_framed,
)

MAX_MAILS = 25
NEEDS_SCAN = 100  # inbox messages scanned newest-first for needs-response
SENT_SCAN = 100  # recent sent messages scanned for awaiting-reply candidates
REFS_SCAN = 150  # inbox reply-headers scanned in the correlation window

# Localized system-mailbox name tables (#61): Mail names these per-locale, so a
# a US-hardcoded "Inbox" gives "mailbox not found" on a non-English Mac. Static data
# used by any mailbox-scoped operation (#45 / the reply-draft issues) to try each
# candidate name. Canonical → localized names; en/nl/ru at least (the acceptance floor).
# ponytail: extend per locale as needed — the exact Mail.app strings want on-device
# confirmation, but a miss only means that mailbox isn't found there, never a crash.
_SYSTEM_MAILBOXES = {
    "inbox": ("Inbox", "Postvak IN", "Входящие"),
    "sent": ("Sent", "Verzonden", "Отправленные"),
    "drafts": ("Drafts", "Concepten", "Черновики"),
    "trash": ("Trash", "Prullenmand", "Корзина"),
    "junk": ("Junk", "Ongewenste reclame", "Спам"),
}


def system_mailbox_names(canonical: str) -> tuple[str, ...]:
    """Localized name candidates for a canonical system mailbox (inbox/sent/drafts/
    trash/junk) — a mailbox-scoped op tries each until Mail resolves one. Raises on an
    unknown canonical name so a typo fails loudly rather than silently matching none."""
    key = canonical.strip().lower()
    if key not in _SYSTEM_MAILBOXES:
        raise ValueError(
            f"unknown system mailbox {canonical!r}; expected one of "
            f"{sorted(_SYSTEM_MAILBOXES)}"
        )
    return _SYSTEM_MAILBOXES[key]


# US/RS framing contract (#68): separators, the shared stripFraming AppleScript
# handler, and the split_framed splitter all live in text.py — the protocol's single
# home (the a6ce7fd subject-framing bug came from per-file re-declarations). Nothing
# in this file may hard-code \x1f/\x1e or re-declare the handler; every free-text
# field (subject, sender, date, attachment name) passes through stripFraming FIRST so
# a payload containing those bytes can't desync parsing.

# Bounded host-side (#52): stop emitting after maxN matches instead of streaming the
# whole match set back and slicing in Python. The `whose` filter still scans the inbox
# (AppleScript has no LIMIT), but the *output* is capped at the source, so a common
# subject can't return thousands of records and blow the buffer (FradSer #66/#69).
# Matches subject OR sender (#61). with timeout (#56): bound the Apple Events so an
# orphaned osascript can't pin Mail.
_SEARCH = """on run argv
  set q to item 1 of argv
  set maxN to (item 2 of argv) as integer
  set out to ""
  set c to 0
  with timeout of 120 seconds
  tell application "Mail"
    repeat with m in (messages of inbox whose (subject contains q or sender contains q))
      set mid to message id of m
      -- RFC 5322 message-id is only SHOULD: a header-less message yields `missing
      -- value`. Skip it — it has no stable citation (never emit a garbage id). #61
      if mid is not missing value and mid is not "" then
        set c to c + 1
        if c > maxN then exit repeat
        set out to out & mid & tab & (subject of m) & tab & (sender of m) & linefeed
      end if
    end repeat
  end tell
  end timeout
  return out
end run"""


# mail_body: hydrate ONE message's plaintext by its RFC822 message-id (the citation from
# a read). Scoped to the inbox — the same source the reads cite; a message-id from
# elsewhere raises loudly rather than scanning every mailbox. id via argv (no injection)
_BODY = """on run argv
  set mid to item 1 of argv
  with timeout of 120 seconds
  tell application "Mail"
    set matches to (messages of inbox whose message id is mid)
    if (count of matches) is 0 then error "no inbox message with that message id"
    set c to content of (item 1 of matches)
    if c is missing value then error "message body is not available locally"
    return c
  end tell
  end timeout
end run"""

# AppleScript coerces an unset property to this literal string on stdout; guard the body
# path against it exactly as the id paths do (#61/#62 review) — never hand back a
# "missing value" body as if it were the email's contents.
_MISSING_VALUE = "missing value"

# create_draft: draft-and-open, NEVER send. `make new outgoing message … visible:true`
# opens a compose window for the HUMAN to review/send; there is deliberately no `send`
# verb here (the two-tier safe gate — joshrutkowski/orchard/patrickfreyer). The body is
# READ from a tempfile as «class utf8» (never interpolated into the script — the
# supermemoryai pattern), so a long/multiline/unicode body can't break or inject the
# script. to/subject/tempfile-path all arrive via argv. Atomic (#44): everything after
# `make new outgoing message` is wrapped in a try; on any failure the partial outgoing
# message is deleted before re-raising, so a retry can't strand a duplicate draft.
_CREATE_DRAFT = """on run argv
  set recipientAddr to item 1 of argv
  set subj to item 2 of argv
  set bodyText to (read (POSIX file (item 3 of argv)) as «class utf8»)
  with timeout of 120 seconds
  tell application "Mail"
    set msg to make new outgoing message with properties {visible:true}
    try
      set subject of msg to subj
      set content of msg to bodyText
      tell msg to make new to recipient with properties {address:recipientAddr}
      activate
    on error errMsg
      delete msg
      error errMsg
    end try
  end tell
  end timeout
end run"""


# reply (#42/#46): fetch the original's sender/date/plaintext by message-id (US-framed),
# so Python can build the quoted block deterministically (Mail's auto-quote is NOT
# visible via the content property — spike 2026-07-11). Scoped to inbox, like _BODY.
# sender/date are stripped of raw framing bytes (the shared STRIP_FRAMING handler)
# before being joined, so a sender display name that happens to contain a literal
# US/RS char can't desync reply()'s raw.partition(US) parsing. The body `c` is the
# LAST field and needs no stripping for parse-safety (clean_body strips control
# chars from it in _build_quote).
_ORIGINAL = (
    STRIP_FRAMING
    + """

on run argv
  set mid to item 1 of argv
  set us to character id 31
  with timeout of 120 seconds
  tell application "Mail"
    set matches to (messages of inbox whose message id is mid)
    if (count of matches) is 0 then error "no inbox message with that message id"
    set m to item 1 of matches
    set snd to sender of m
    set dt to (date received of m) as text
    set c to content of m
    if c is missing value then set c to ""
    return (my stripFraming(snd)) & us & (my stripFraming(dt)) & us & c
  end tell
  end timeout
end run"""
)

# reply builds a real reply via Mail's NATIVE reply verb (Mail owns In-Reply-To/
# References threading — the only mechanism that threads; make-new-outgoing can't set
# headers, spike 2026-07-11). The body (reply text + our quote) is set on the returned
# outgoing message — keystroke-free (#46; no .eml). A window opens for the HUMAN to
# review/send. NEVER sends. Atomic (#44): delete the draft on any post-creation
# failure. body via tempfile as «class utf8»; message-id via argv.
_REPLY = """on run argv
  set mid to item 1 of argv
  set bodyText to (read (POSIX file (item 2 of argv)) as «class utf8»)
  with timeout of 120 seconds
  tell application "Mail"
    set matches to (messages of inbox whose message id is mid)
    if (count of matches) is 0 then error "no inbox message with that message id"
    set r to reply (item 1 of matches) opening window yes
    try
      set content of r to bodyText
    on error errMsg
      delete r
      error errMsg
    end try
  end tell
  end timeout
end run"""


def _build_quote(sender: str, date_str: str, original_body: str) -> str:
    """Standard reply quote: `On <date>, <sender> wrote:` then the original body, each
    line `> `-prefixed. Bounded via clean_body (hard=None: always truncate, never raise
    — the quote is supplementary text, not the primary deliverable, so a huge original
    must not abort the whole reply)."""
    bounded = clean_body(original_body, hard=None)
    quoted = "\n".join("> " + line for line in bounded.splitlines())
    return f"On {date_str}, {sender} wrote:\n{quoted}"


# list_attachments (#45): attachments of messages in a mailbox matching a subject query.
# Mailbox addressing uses Mail's UNIFIED, cross-account, locale-independent accessors
# (verified on-device: `drafts mailbox`->"All Drafts", `sent mailbox`->"All Sent",
# `trash mailbox`->"All Trash", `junk mailbox`->"All Junk", `inbox`->unified inbox) — no
# per-account name search, so this can't pick the wrong (often empty) same-named mailbox
# on a multi-account Mac the way a "first account with a matching mailbox name" loop
# would. Since these accessors are locale-independent, only the canonical name travels
# via argv — no localized candidate list needed. An empty query lists ALL messages in
# the mailbox (bounded by maxN) rather than none — AppleScript's `contains ""` is
# false, so that case is branched explicitly. Fields framed per the US/RS contract:
# per record = subject, then (name, size, downloaded) TRIPLES per attachment; the
# subject and each attachment name pass through the shared STRIP_FRAMING handler
# before being joined, so a message that happens to contain those control chars can't
# desync the parser. Output capped at maxN records. with timeout (#56). All inputs via
# argv (no interpolation).
_ATTACHMENTS = (
    STRIP_FRAMING
    + """

on run argv
  set q to item 1 of argv
  set maxN to (item 2 of argv) as integer
  set canon to item 3 of argv
  set us to character id 31
  set rs to character id 30
  set out to ""
  set c to 0
  with timeout of 120 seconds
  tell application "Mail"
    if canon is "inbox" then
      set mb to inbox
    else if canon is "sent" then
      set mb to sent mailbox
    else if canon is "drafts" then
      set mb to drafts mailbox
    else if canon is "trash" then
      set mb to trash mailbox
    else if canon is "junk" then
      set mb to junk mailbox
    else
      error "unknown mailbox " & canon
    end if
    if q is "" then
      set msgs to messages of mb
    else
      set msgs to (messages of mb whose subject contains q)
    end if
    repeat with m in msgs
      set c to c + 1
      if c > maxN then exit repeat
      set out to out & my stripFraming(subject of m)
      repeat with a in (mail attachments of m)
        set aSize to ""
        try
          set aSize to (file size of a) as text
        end try
        set aDown to ""
        try
          set aDown to (downloaded of a) as text
        end try
        set out to out & us & my stripFraming(name of a) & us & aSize & us & aDown
      end repeat
      set out to out & rs
    end repeat
  end tell
  end timeout
  return out
end run"""
)


def _parse_attachments(raw: str) -> list[dict]:
    """Parse the _ATTACHMENTS payload: RS-separated records, each US-separated as
    subject then (name, size, downloaded) triples. Malformed/partial trailing records
    are skipped."""
    out = []
    for parts in split_framed(raw):
        summary = clean_summary(parts[0])
        atts = []
        rest = parts[1:]
        for i in range(0, len(rest) - 2, 3):
            name = rest[i].strip()
            if not name:
                continue
            size_s = rest[i + 1].strip()
            down_s = rest[i + 2].strip().lower()
            atts.append(
                {
                    "name": clean_summary(name),
                    "size": int(size_s) if size_s.isdigit() else None,
                    "downloaded": (down_s == "true")
                    if down_s in ("true", "false")
                    else None,
                }
            )
        out.append({"summary": summary or "(no subject)", "attachments": atts})
    return out


def _parse_triage_records(raw: str) -> list[dict]:
    """Parse _INBOX_TRIAGE: RS-separated records, US-separated fields (id, subject,
    sender, to_addrs (comma-joined), secs_ago, was_replied_to, read, flagged).
    Malformed/partial records are skipped; addresses lowercased."""
    out = []
    for f in split_framed(raw):
        if len(f) < 8:
            continue
        out.append(
            {
                "id": f[0],
                "subject": f[1],
                "sender": f[2].strip().lower(),
                "to_addrs": [a.strip().lower() for a in f[3].split(",") if a.strip()],
                "secs_ago": int(f[4]) if f[4].strip().lstrip("-").isdigit() else 0,
                "was_replied_to": f[5].strip().lower() == "true",
                "read": f[6].strip().lower() == "true",
                "flagged": f[7].strip().lower() == "true",
            }
        )
    return out


def _parse_sent_records(raw: str) -> list[dict]:
    """Parse _SENT_TRIAGE: RS records, US fields (id, subject, recipients, secs_ago)."""
    out = []
    for f in split_framed(raw):
        if len(f) < 4:
            continue
        out.append(
            {
                "id": f[0],
                "subject": f[1],
                "recipient_addrs": [
                    a.strip().lower() for a in f[2].split(",") if a.strip()
                ],
                "secs_ago": int(f[3]) if f[3].strip().lstrip("-").isdigit() else 0,
            }
        )
    return out


def _parse_my_addrs(raw: str) -> set[str]:
    return {a.strip().lower() for a in raw.split(US) if a.strip()}


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
  with timeout of 60 seconds
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


def _summary(subject: str, sender: str) -> str:
    subject, sender = subject.strip(), sender.strip()
    if subject and sender:
        return f"{subject} — {sender}"
    return subject or sender or "(no subject)"


def _deeplink(message_id: str) -> str:
    # message://%3C<id>%3E opens the message in Mail. The angle brackets are percent-
    # encoded (%3C/%3E) and the id itself is percent-encoded with safe='@' (an RFC822
    # message-id is local@domain, so '@' stays literal; spaces/other chars escaped) —
    # the patrickfreyer recipe (#61). Best-effort; verified on-device (integration).
    mid = message_id.strip().lstrip("<").rstrip(">")
    return f"message://%3C{quote(mid, safe='@')}%3E"


def _classify_needs_response(records: list[dict], my_addrs: set[str]) -> list[Pointer]:
    """Rank inbound messages that likely need the user's response. Drops already-replied
    messages; keeps those directly addressed to the user (my_addrs ∩ to_addrs). If
    my_addrs is empty (extraction failed) it degrades to FLAGGED-ONLY rather than
    flooding the inbox. Reasons (stable): flagged > unread-direct > unanswered-direct;
    recency (smallest secs_ago) breaks ties within a tier. Bounded to MAX_MAILS."""
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
            reason=reason,
        )
        out.append((tier, r["secs_ago"], p))
    out.sort(key=lambda t: (t[0], t[1]))  # tier asc, then most-recent (secs_ago) first
    return [p for _, _, p in out[:MAX_MAILS]]


def _norm_mid(mid: str) -> str:
    """Normalize a Message-ID for comparison: strip angle brackets + surrounding space,
    lowercase."""
    return mid.strip().lstrip("<").rstrip(">").strip().lower()


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
    sent: list[dict], referenced_ids: set[str], days: int
) -> list[Pointer]:
    """Sent messages older than `days` whose Message-ID no inbox message references
    (real In-Reply-To/References threading — accurate, no fuzzy subject matching).
    Reason: stable 'awaiting-reply'. Sorted oldest-sent-first (most overdue). Bounded
    to MAX_MAILS. A group-thread send is cleared if ANY recipient's reply cites it
    (documented)."""
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
            reason="awaiting-reply",
        )
        out.append((r["secs_ago"], p))
    out.sort(key=lambda t: t[0], reverse=True)  # most overdue (largest secs_ago) first
    return [p for _, p in out[:MAX_MAILS]]


def _parse(raw: str) -> list[Pointer]:
    out = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        mid = parts[0]
        # a message with no Message-ID header has no stable citation — skip it rather
        # than emit a non-resolvable id ("missing value" is AppleScript's coercion of an
        # unset property; "" is the alternative some Mail versions return). #61 review.
        if mid.strip() in ("", "missing value"):
            continue
        subject = parts[1] if len(parts) > 1 else ""
        sender = parts[2] if len(parts) > 2 else ""
        out.append(
            Pointer(
                id=mid,
                summary=clean_summary(_summary(subject, sender)),
                deeplink=_deeplink(mid),
            )
        )
    return out


class MailAdapter:
    def get_pointers(self, query: str) -> list[Pointer]:
        """query: a substring to match against the inbox subject OR sender (#61)."""
        q = query.strip()
        if not q:
            raise ValueError("mail read needs a search substring (got an empty query)")
        # maxN is enforced host-side; the slice is a cheap backstop on the result.
        return _parse(run_osascript(_SEARCH, q, str(MAX_MAILS)))[:MAX_MAILS]

    def get_body(self, message_id: str) -> str:
        """Plaintext body of one inbox message by its RFC822 message-id, budgeted (#52):
        control-stripped, truncated with a marker past BODY_MAX, and OutputOverflow past
        the hard cap (a pasted dump → open it in Mail). Raises if the id isn't in the
        inbox (the read source). Accepts a bracketed or bare id."""
        mid = message_id.strip().lstrip("<").rstrip(">")
        if not mid:
            raise ValueError("mail_body needs a message id")
        body = run_osascript(_BODY, mid)
        # defense in depth: the _BODY script already errors on a missing-value content,
        # but a Mail version that returns the coerced literal instead of erroring must
        # not surface it as the body (#62 review).
        if body.strip() == _MISSING_VALUE:
            raise NativeError(
                "the message body is not available locally (HTML-only, or not yet "
                "downloaded) — open it in Mail to view it. Do not retry."
            )
        return clean_body(body)

    def create_draft(self, to: str, subject: str, body: str) -> dict:
        """Create a Mail draft and OPEN it for the human to review/send — NEVER sends.
        Atomic (#44): if any step after creation fails, the script deletes the partial
        draft before erroring, so a retry can't strand a duplicate. Returns a locator
        (#43): an unsent draft has no stable Message-ID (Mail stamps it only on send),
        so we return where to find it, not a fabricated id. The body is written to a
        0600 tempfile and read by the script as «class utf8» (never interpolated);
        to/subject go via argv. The tempfile is deleted after the (synchronous) script
        has read its content into the draft."""
        addr = to.strip()
        if not addr:
            raise ValueError("create_draft needs a recipient address (to)")
        with body_file(body or "") as path:
            run_osascript(_CREATE_DRAFT, addr, subject or "", path)
        return {
            "created": True,
            "subject": subject or "",
            "mailbox": "Drafts",
            "note": "opened in a Mail compose window for your review; save it to keep "
            "it in Drafts. Unsent drafts have no stable id.",
        }

    def reply(
        self, message_id: str, reply_body: str, include_quote: bool = True
    ) -> dict:
        """Reply to an inbox message by its RFC822 message-id: opens a threaded draft
        for the human to review/send — NEVER sends. Uses Mail's native reply verb so
        In-Reply-To/References are set by Mail (real Gmail/Outlook threading).
        include_quote appends `On <date>, <sender> wrote:` + the `> `-quoted original.
        Keystroke-free (#46); atomic (#44). Returns the same locator dict as
        create_draft (an unsent draft has no stable id)."""
        mid = message_id.strip().lstrip("<").rstrip(">")
        if not mid:
            raise ValueError("reply needs the original message's id")
        if not reply_body.strip():
            raise ValueError("reply needs a non-empty reply_body")
        body = reply_body
        if include_quote:
            raw = run_osascript(_ORIGINAL, mid)
            if raw.strip() and raw.strip() != _MISSING_VALUE:
                sender, _, rest = raw.partition(US)
                date_str, _, original = rest.partition(US)
                # defense-in-depth (#42/#46 review): the AppleScript already strips raw
                # framing bytes from sender/date, but sanitize_line ALSO strips any
                # other control chars a display name/date could carry, keeping the
                # quote header clean even if the AppleScript-side strip is bypassed
                # (e.g. a mocked _ORIGINAL in tests).
                sender = sanitize_line(sender)
                date_str = sanitize_line(date_str)
                body = reply_body + "\n\n" + _build_quote(sender, date_str, original)
        with body_file(body) as path:
            run_osascript(_REPLY, mid, path)
        return {
            "created": True,
            "subject": "(reply)",
            "mailbox": "Drafts",
            "note": "reply draft opened for review; unsent drafts have no stable id",
        }

    def list_attachments(self, mailbox: str, query: str = "") -> list[dict]:
        """List attachments of messages in `mailbox` (canonical inbox/sent/drafts/
        trash/junk) whose subject contains `query`. Works for Drafts (no message-id
        needed); mailbox resolution uses Mail's unified, cross-account accessors
        (`drafts mailbox`/`sent mailbox`/`trash mailbox`/`junk mailbox`/`inbox`), which
        are locale-independent. query is optional: an empty/omitted query lists ALL
        messages in the mailbox (bounded by MAX_MAILS) — this deliberately differs from
        `get_pointers`, which rejects an empty query. Returns up to MAX_MAILS records:
        [{"summary", "attachments": [{"name","size","downloaded"}]}]. A read — never
        mutates."""
        # system_mailbox_names raises ValueError on an unknown canonical name; kept
        # purely as validation here since the script no longer needs localized
        # candidates (the unified accessors are locale-independent).
        system_mailbox_names(mailbox)
        canon = mailbox.strip().lower()
        raw = run_osascript(_ATTACHMENTS, query.strip(), str(MAX_MAILS), canon)
        return _parse_attachments(raw)[:MAX_MAILS]

    def get_needs_response(self) -> list[Pointer]:
        """Inbox messages that likely need the user's response, ranked with a reason
        (flagged / unread-direct / unanswered-direct). Heuristic over headers/
        properties — no body scan; direct-addressed + not-yet-replied. Bounded."""
        records = _parse_triage_records(run_osascript(_INBOX_TRIAGE, str(NEEDS_SCAN)))
        my = _parse_my_addrs(run_osascript(_MY_ADDRESSES))
        return _classify_needs_response(records, my)

    def get_awaiting_reply(self, days: int = 3) -> list[Pointer]:
        """Sent messages older than `days` with no reply, ranked oldest-first (reason
        'awaiting-reply'). Real In-Reply-To/References threading. Bounded."""
        if not 1 <= days <= 365:
            raise ValueError("days must be between 1 and 365")
        sent = _parse_sent_records(run_osascript(_SENT_TRIAGE, str(SENT_SCAN)))
        candidates = [r for r in sent if r["secs_ago"] >= days * 86400]
        if not candidates:
            return []
        window = max(  # scan inbox back to the oldest candidate send
            r["secs_ago"] for r in candidates
        )
        blobs = [
            b
            for b in run_osascript(_INBOX_REFS, str(window), str(REFS_SCAN)).split(RS)
            if b.strip()
        ]
        return _classify_awaiting_reply(sent, _referenced_ids(blobs), days)
