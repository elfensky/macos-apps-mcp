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

import contextlib
import os
import tempfile
from urllib.parse import quote

from ..contracts import Pointer
from ..runtime import NativeError, clean_body, clean_summary, run_osascript

MAX_MAILS = 25

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
# script. to/subject/tempfile-path all arrive via argv.
_CREATE_DRAFT = """on run argv
  set recipientAddr to item 1 of argv
  set subj to item 2 of argv
  set bodyText to (read (POSIX file (item 3 of argv)) as «class utf8»)
  with timeout of 120 seconds
  tell application "Mail"
    set msg to make new outgoing message with properties {visible:true}
    set subject of msg to subj
    set content of msg to bodyText
    tell msg to make new to recipient with properties {address:recipientAddr}
    activate
  end tell
  end timeout
end run"""


# list_attachments (#45): attachments of messages in a mailbox matching a subject query.
# Mailbox addressing uses Mail's UNIFIED, cross-account, locale-independent accessors
# (verified on-device: `drafts mailbox`->"All Drafts", `sent mailbox`->"All Sent",
# `trash mailbox`->"All Trash", `junk mailbox`->"All Junk", `inbox`->unified inbox) — no
# per-account name search, so this can't pick the wrong (often empty) same-named mailbox
# on a multi-account Mac the way a "first account with a matching mailbox name" loop
# would. Since these accessors are locale-independent, only the canonical name travels
# via argv — no localized candidate list needed. An empty query lists ALL messages in
# the mailbox (bounded by maxN) rather than none — AppleScript's `contains ""` is
# false, so that case is branched explicitly. Fields framed with US (\x1f)/RS (\x1e):
# per record = subject, then (name, size, downloaded) TRIPLES per attachment; the
# subject and each attachment name are stripped of any raw framing bytes (stripFraming)
# before being joined, so a message that happens to contain those control chars can't
# desync the parser. Output capped at maxN records. with timeout (#56). All inputs via
# argv (no interpolation).
_ATTACHMENTS = """on stripFraming(t)
  set t to t as text
  set AppleScript's text item delimiters to (character id 30)
  set t to text items of t
  set AppleScript's text item delimiters to ""
  set t to t as text
  set AppleScript's text item delimiters to (character id 31)
  set t to text items of t
  set AppleScript's text item delimiters to ""
  set t to t as text
  return t
end stripFraming

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


def _parse_attachments(raw: str) -> list[dict]:
    """Parse the _ATTACHMENTS payload: RS-separated records, each US-separated as
    subject then (name, size, downloaded) triples. Malformed/partial trailing records
    are skipped."""
    out = []
    for record in raw.split("\x1e"):
        if not record.strip():
            continue
        parts = record.split("\x1f")
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

    def create_draft(self, to: str, subject: str, body: str) -> None:
        """Create a Mail draft and OPEN it for the human to review/send — NEVER sends.
        The body is written to a 0600 tempfile and read by the script as «class utf8»
        (never interpolated); to/subject go via argv. The tempfile is deleted after the
        (synchronous) script has read its content into the draft."""
        addr = to.strip()
        if not addr:
            raise ValueError("create_draft needs a recipient address (to)")
        fd, path = tempfile.mkstemp(prefix="mac-mcp-draft-", suffix=".txt")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(body or "")
            run_osascript(_CREATE_DRAFT, addr, subject or "", path)
        finally:
            with contextlib.suppress(OSError):
                os.unlink(path)

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
