"""The outgoing-message lifecycle (#160) — the one module that owns "this leaves the
machine".

Four tools dispatch mail off this Mac: ``send_mail``, ``reply_all``, ``forward_mail``
and (#157) ``send_mail(draft_id=…)``. They differ only in how their envelope is
*obtained*; everything after that — the preview shape, the rule about what a preview may
touch, the send, the outbox truth-check — is identical, and before this module each copy
re-derived it (three different ``would_send`` shapes, the quote preamble pasted twice,
the "dry run constructs nothing" rule stated in prose in four docstrings and enforced
nowhere).

**The discipline, stated once.**

1. *A preview NEVER CONSTRUCTS.* Mail autosaves any outgoing message into Drafts
   ~10-15s after it is built — asynchronously, unsuppressably, whether it was sent,
   rolled back or abandoned (#133, device-verified). The autosaved copy's id is minted
   at autosave time, so it cannot be identified in advance and cannot be swept. The only
   way to leave nothing behind is to build nothing. So ``dry_run`` never reaches
   ``make new outgoing message`` / ``reply`` / ``forward``.
2. *A preview MAY READ stored mail.* Reading a message that already exists strands
   nothing, so the rule in (1) does not forbid it — and two previews are worthless
   without it. ``reply_all``'s preview reads the original's ACTUAL to/cc (reply-all is
   exactly the tool whose recipient set surprises you), and ``send_mail(draft_id=…)``'s
   preview reads the draft it is about to send (an id alone tells the approving human
   nothing). This is the exception that used to carry a 9-line justification at
   ``reply_all``'s call site; it lives here now because it is a property of the plane,
   not of one tool.
3. *Never roll back past the ``send`` verb.* ``delete`` after ``send`` is a silent
   no-op — it returns cleanly, removes nothing, and the message delivers anyway (#135).
   Every script here therefore keeps ``send`` OUTSIDE its rollback ``try``, and
   ``tests/test_mail.py`` greps for exactly that.
4. *``sent`` means ACCEPTED, not delivered.* Every real dispatch ends in
   ``with_outbox_pending``, which reports Mail's real queue.

``Outgoing`` is the envelope those four share, and it renders the ONE ``would_send``
shape — same keys every time, so a caller writes one dry-run handler instead of three.
The per-tool spellings it replaced (``reply_to``, ``forwarding``, ``reply_all``) are
gone; ``action`` + ``source`` say the same thing in fixed positions.

Note the builders' shapes: ``forward_of`` **takes no body parameter at all**. Writing
``content`` on a forward destroys its attachments (7 in, 0 out, device-verified by real
send), and that rule is now enforced by the interface rather than by the absence of a
line plus a grep-test. There is nothing to pass, so there is nothing to get wrong.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .. import runtime
from ..errors import NativeError
from ..text import (
    READ_BODY,
    RS,
    STRIP_FRAMING,
    US,
    clean_body,
    sanitize_line,
)
from . import mail_addressing
from .mail_addressing import bare_id

_MISSING_VALUE = "missing value"

# The default-account placeholder a preview reports instead of guessing: Mail's default
# sender is NOT predictable from account order (device-verified), so naming one would be
# a lie a human might approve.
MAIL_DEFAULT_SENDER = "(Mail default account)"


# --- the scripts ---------------------------------------------------------------------
#
# rollback (#135): the ONLY place this adapter deletes a message it just built. A bare
# `delete` reports success whether or not it removed anything, so this verifies the
# outcome instead of assuming it: device-verified 2026-07-26, a successfully deleted
# outgoing message's reference goes DEAD and reading a property off it raises -1728.
# Only -1728 counts as proof. A live reference means the delete did not take; ANY other
# error means the outcome is unknown, and unknown is reported as NOT verified — this
# handler never guesses in the reassuring direction, because a rollback that lies is
# the exact failure #135 is made of.
#
# It carries its OWN `with timeout` (#56): AppleScript's timeout is lexical, so the
# enclosing script's wrapper does not cover a handler body called from inside it — an
# un-bounded Apple Event here could pin a hung Mail exactly when we are cleaning up.
#
# CRITICAL: only ever call this BEFORE handing the message to `send` (rule 3 at the
# module docstring). Once Mail has accepted a message, `delete` is a silent NO-OP:
# device-verified 2026-07-26, both `delete <ref>` and `delete outgoing message i`
# returned cleanly on a sent message and removed nothing, and the message went on to
# deliver normally. So a post-send rollback cannot succeed — it can only report a
# cleanup that did not happen. That is why `send` sits OUTSIDE the rollback `try` in
# every script here: past that verb the honest move is to report the leftover, never to
# pretend it was removed.
#
# The two shared warnings live here as AppleScript handlers rather than as Python
# constants interpolated into the scripts: `_SEND` contains `{visible:false}`, so an
# f-string would need brace escaping, and the no-interpolation rule is easier to keep
# when nothing is interpolated at all. Appended to the ORIGINAL error when rollback()
# could not prove the partial message is gone — the caller gets the real failure plus
# the leftover fact and its recovery (the in-memory outbox zombie clears when Mail is
# quit and reopened; device-verified).
ROLLBACK = """on rollback(msg)
  with timeout of 120 seconds
    try
      tell application "Mail" to delete msg
    end try
    try
      tell application "Mail" to get subject of msg
      return false
    on error number en
      return (en is -1728)
    end try
  end timeout
end rollback

on outgoingLeftover()
  return " (WARNING: a partial outgoing message may remain; check Mail's " & ¬
    "Outbox before retrying, so a retry cannot send twice)"
end outgoingLeftover

on draftLeftover()
  return " (WARNING: a partial draft may remain in Mail's Drafts; remove it " & ¬
    "with delete_draft)"
end draftLeftover"""

# send (#83): the FIRST tool here that dispatches outside this machine — gated by
# MACOS_APPS_ALLOW_SEND at registration, so it does not exist unless the operator opted
# in. `visible:false` + `send` is device-verified (2026-07-25): the "send needs a
# visible compose window" folklore does not hold. Recipient lists arrive as ONE argv
# item per field, US-joined (an email address cannot contain U+001F). Body via
# tempfile through the shared readBody handler (never a bare `read` — a subject-only
# send leaves an EMPTY body file, which crashes -39, #READ_BODY). Atomic (#44): roll
# back the partial message on any pre-send error.
#
# #133, device-verified 2026-07-26: Mail autosaves any outgoing message to Drafts
# ~10-15s after creation and nothing suppresses it, so a SUCCESSFUL send also leaves a
# stray Drafts copy — not just the error path. This is why the DRY-RUN path builds
# nothing at all: the only way to not litter is to not construct a message.
_SEND = (
    READ_BODY
    + "\n\n"
    + ROLLBACK
    + """

on run argv
  set subj to item 1 of argv
  set bodyText to my readBody(item 2 of argv)
  set isHtml to (item 3 of argv) is "1"
  set fromAddr to item 4 of argv
  set toList to item 5 of argv
  set ccList to item 6 of argv
  set bccList to item 7 of argv
  set us to character id 31
  with timeout of 120 seconds
  tell application "Mail"
    set msg to make new outgoing message with properties {visible:false}
    try
      set subject of msg to subj
      if isHtml then
        set html content of msg to bodyText
      else
        set content of msg to bodyText
      end if
      if fromAddr is not "" then set sender of msg to fromAddr
      set AppleScript's text item delimiters to us
      repeat with a in (text items of toList)
        if (a as text) is not "" then
          tell msg to make new to recipient with properties {address:(a as text)}
        end if
      end repeat
      repeat with a in (text items of ccList)
        if (a as text) is not "" then
          tell msg to make new cc recipient with properties {address:(a as text)}
        end if
      end repeat
      repeat with a in (text items of bccList)
        if (a as text) is not "" then
          tell msg to make new bcc recipient with properties {address:(a as text)}
        end if
      end repeat
      set AppleScript's text item delimiters to ""
    on error errMsg
      set AppleScript's text item delimiters to ""
      if my rollback(msg) then
        error errMsg
      else
        error errMsg & my outgoingLeftover()
      end if
    end try
    send msg
    return "sent"
  end tell
  end timeout
end run"""
)

# reply_all (#83): Mail's NATIVE reply verb with `reply to all yes`, so In-Reply-To /
# References are set by Mail (the only mechanism that threads — make-new-outgoing
# cannot set headers). `opening window no` keeps it headless; device-verified
# 2026-07-25, returns an outgoing message with the Re: subject already applied. The
# body (reply text + our quote, built in Python exactly as `reply` does) is read
# through the shared readBody handler, never a bare `read` (an empty body — no quote,
# no reply text — would otherwise crash -39, #READ_BODY). Atomic (#44), with #133's
# limit: a successful reply-all still leaves an autosaved Drafts copy behind.
_REPLY_ALL = (
    READ_BODY
    + "\n\n"
    + ROLLBACK
    + "\n\n"
    + mail_addressing.MAILBOX_REF
    + """

on run argv
  set mid to item 1 of argv
  set bodyText to my readBody(item 2 of argv)
  set mb to my mailboxFor(item 3 of argv, item 4 of argv)
  with timeout of 120 seconds
  tell application "Mail"
    set matches to (messages of mb whose message id is mid)
    if (count of matches) is 0 then error ¬
      "no message with that message id in " & (item 4 of argv)
    set r to reply (item 1 of matches) opening window no reply to all yes
    try
      set content of r to bodyText
    on error errMsg
      if my rollback(r) then
        error errMsg
      else
        error errMsg & my outgoingLeftover()
      end if
    end try
    send r
    return "sent"
  end tell
  end timeout
end run"""
)

# forward (#83): Mail's NATIVE forward verb (device-verified: returns an outgoing
# message with the Fwd: subject and the original content + attachments already in
# place). This script NEVER touches `content` of the forwarded message: `content` of a
# forward is permanently unreadable (reads empty at 0s/1s/4s — Mail renders the quoted
# original only in its compose UI and assembles it at send time, never exposing it to
# scripting), so a note prepended via `set content of f to noteText & ... & (content of
# f)` was actually just OVERWRITING the body with the note — the "original" half was
# always empty. Worse, device-verified end to end (real send, real inspection of what
# arrived): writing `content` at all — even once — destroys the attachments. A forward
# of a message with 7 attachments, body replaced, delivered with 0 attachments; the same
# forward with `content` never touched delivered all 7 attachments intact plus the full
# 1915-char original body. So there is no way to add a covering note to a forward
# without destroying the very thing being forwarded — this script forwards the
# original unchanged and carries no note, and `forward_of` has no body parameter to
# tempt anyone into re-adding one. Recipients arrive US-joined in one argv item.
_FORWARD = (
    ROLLBACK
    + "\n\n"
    + mail_addressing.MAILBOX_REF
    + """

on run argv
  set mid to item 1 of argv
  set toList to item 2 of argv
  set mb to my mailboxFor(item 3 of argv, item 4 of argv)
  set us to character id 31
  with timeout of 120 seconds
  tell application "Mail"
    set matches to (messages of mb whose message id is mid)
    if (count of matches) is 0 then error ¬
      "no message with that message id in " & (item 4 of argv)
    set f to forward (item 1 of matches) opening window no
    try
      set AppleScript's text item delimiters to us
      repeat with a in (text items of toList)
        if (a as text) is not "" then
          tell f to make new to recipient with properties {address:(a as text)}
        end if
      end repeat
      set AppleScript's text item delimiters to ""
    on error errMsg
      set AppleScript's text item delimiters to ""
      if my rollback(f) then
        error errMsg
      else
        error errMsg & my outgoingLeftover()
      end if
    end try
    send f
    return "sent"
  end tell
  end timeout
end run"""
)

# outbox_pending (#134): a successful `send`/`reply`/`forward` verb means Mail ACCEPTED
# the message — NOT that it left this machine. Device-verified 2026-07-25: a
# perfectly-formed message (correct subject, recipient, sender) was accepted by `send`,
# this code returned `sent: True`, and the message then sat undelivered for minutes.
#
# Counts `messages of outbox` — Mail's REAL send queue. It must NOT count `outgoing
# messages`, which is what this shipped as in #134 and is a different thing entirely:
# that is the set of script-created message OBJECTS alive in Mail's current session, and
# it includes messages already delivered. Device-verified 2026-07-26, sampling both
# counters across one real send: the object count read 2 before the send and 2 for ten
# seconds after it, never moving, while `messages of outbox` went 0 -> 1 as the message
# queued and back to 0 within ~10s as it went out. Counting objects therefore reports a
# permanent non-zero after the session's first send, firing the "delivery is NOT
# confirmed" note on every subsequent send forever — a false alarm that trains the
# caller to ignore the one signal that matters.
#
# Called after every send script runs, never before — this reports the WHOLE queue, not
# specifically the message this call just sent: once the native verb consumes our
# outgoing message there is no stable id left to re-identify it by, so we cannot scope
# the count to just ours. A non-zero count therefore only means "something is queued",
# not "our message is queued" — but that's still the actionable signal: delivery is NOT
# confirmed and Mail's Outbox needs a look. Do not invent subject-matching or other
# heuristics to attribute the count to one message.
_OUTBOX_COUNT = """on run argv
  with timeout of 120 seconds
  tell application "Mail"
    return (count of (messages of outbox)) as text
  end tell
  end timeout
end run"""

# reply_all dry-run preview (#129): resolve an inbox message's to/cc recipients — the
# set reply-all would ACTUALLY reach — plus its sender and subject, by message-id.
# Reply-all is exactly the tool whose recipient set is surprising (a long cc list), and
# the whole justification for dry_run defaulting to True is that a wrong recipient
# becomes visible before anything leaves; a preview that echoes back only what the
# caller typed is decorative. This is rule 2 at the module docstring: a preview may
# READ. Device-verified 2026-07-26: `to recipients`, `cc recipients`, `sender` and
# `subject` are all readable on a stored message. Errors when the id has no match. One
# RS-framed record per recipient — (kind, address), kind in to/cc — plus final
# (sender, …) and (subject, …) records: the _DRAFTS/_ATTACHMENTS idiom, so a
# variable-length to/cc list parses with split_framed instead of a fixed-arity
# US-partition. Every free-text field passes through the shared stripFraming handler.
_REPLY_ALL_RECIPIENTS = (
    STRIP_FRAMING
    + "\n\n"
    + mail_addressing.MAILBOX_REF
    + """

on run argv
  set mid to item 1 of argv
  set mb to my mailboxFor(item 2 of argv, item 3 of argv)
  set us to character id 31
  set rs to character id 30
  set out to ""
  with timeout of 120 seconds
  tell application "Mail"
    set matches to (messages of mb whose message id is mid)
    if (count of matches) is 0 then error ¬
      "no message with that message id in " & (item 3 of argv)
    set m to item 1 of matches
    repeat with r in (to recipients of m)
      set out to out & "to" & us & (my stripFraming(address of r)) & rs
    end repeat
    repeat with r in (cc recipients of m)
      set out to out & "cc" & us & (my stripFraming(address of r)) & rs
    end repeat
    set out to out & "sender" & us & (my stripFraming(sender of m)) & rs
    set subj to subject of m
    if subj is missing value then set subj to ""
    set out to out & "subject" & us & (my stripFraming(subj)) & rs
  end tell
  end timeout
  return out
end run"""
)

# reply (#42/#46): fetch the original's sender/date/plaintext by message-id (US-framed),
# so Python can build the quoted block deterministically (Mail's auto-quote is NOT
# visible via the content property — spike 2026-07-11). sender/date are stripped of raw
# framing bytes (the shared STRIP_FRAMING handler) before being joined, so a sender
# display name that happens to contain a literal US/RS char can't desync the two
# partitions below. The body `c` is the LAST field and needs no stripping for
# parse-safety (clean_body strips control chars from it in build_quote).
_ORIGINAL = (
    STRIP_FRAMING
    + "\n\n"
    + mail_addressing.MAILBOX_REF
    + """

on run argv
  set mid to item 1 of argv
  set mb to my mailboxFor(item 2 of argv, item 3 of argv)
  set us to character id 31
  with timeout of 120 seconds
  tell application "Mail"
    set matches to (messages of mb whose message id is mid)
    if (count of matches) is 0 then error ¬
      "no message with that message id in " & (item 3 of argv)
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

# read a saved draft's envelope (#157). Mail CANNOT script-send a stored draft — `send`
# is declared on `outgoing message` only and a `message` in the Drafts mailbox raises
# -1708 ("doesn't understand the send message"); `open`ing the draft does produce a real
# compose window but AppleScript never sees it as an `outgoing message` (count stays 0),
# so there is nothing to hand `send`. Both device-verified 2026-08-05. The only
# mechanic left is to REBUILD the draft as a fresh outgoing message from its own stored
# bytes — which is why this script exists, and why it also reports the two things that
# rebuild would silently destroy:
#
#   * `attachments` — a rebuilt message carries none, so a draft with attachments is
#     REFUSED rather than sent stripped.
#   * `threaded` — In-Reply-To/References are set by Mail's native `reply` verb and
#     CANNOT be set on a make-new-outgoing message, so a reply draft would arrive
#     un-threaded. Refused too, pointing at reply_all.
#
# Drafts are addressed by iterating IN REVERSE BY INDEX, never `whose`: a `whose`
# equality filter is unreliable on the Drafts mailbox (-1728 on a draft that
# demonstrably existed). Fields are US-partitioned from the LEFT with `content` LAST —
# the _ORIGINAL idiom — so a body containing framing bytes cannot desync the parse;
# the recipient lists are RS-joined inside their own US field (an address can contain
# neither byte, and every free-text field passes stripFraming first).
_DRAFT_ENVELOPE = (
    STRIP_FRAMING
    + """

on run argv
  set mid to item 1 of argv
  set us to character id 31
  set rs to character id 30
  with timeout of 120 seconds
  tell application "Mail"
    set dm to drafts mailbox
    set n to count of (messages of dm)
    set found to missing value
    repeat with i from n to 1 by -1
      set m to message i of dm
      set thisId to message id of m
      if thisId is not missing value and (thisId as text) is mid then
        set found to m
        exit repeat
      end if
    end repeat
    if found is missing value then error "no draft with that message id"
    set subj to subject of found
    if subj is missing value then set subj to ""
    set snd to sender of found
    if snd is missing value then set snd to ""
    set toOut to ""
    repeat with r in (to recipients of found)
      set toOut to toOut & (my stripFraming(address of r)) & rs
    end repeat
    set ccOut to ""
    repeat with r in (cc recipients of found)
      set ccOut to ccOut & (my stripFraming(address of r)) & rs
    end repeat
    set bccOut to ""
    try
      repeat with r in (bcc recipients of found)
        set bccOut to bccOut & (my stripFraming(address of r)) & rs
      end repeat
    end try
    set nAtt to (count of (mail attachments of found)) as text
    set threaded to "0"
    try
      set hdrs to (all headers of found)
      if hdrs contains "In-Reply-To:" or hdrs contains "References:" then
        set threaded to "1"
      end if
    end try
    set c to content of found
    if c is missing value then set c to ""
    return (my stripFraming(subj)) & us & (my stripFraming(snd)) & us & toOut & us & ¬
      ccOut & us & bccOut & us & nAtt & us & threaded & us & c
  end tell
  end timeout
end run"""
)


# --- the envelope --------------------------------------------------------------------


@dataclass(frozen=True)
class Outgoing:
    """One message about to leave this machine, plus the closure that dispatches it.

    ``action`` names which of the four builders produced it and ``source`` the stored
    message it derives from (the original being replied to / forwarded, or the draft
    being sent) — together they replace the per-tool ``reply_to`` / ``forwarding`` /
    ``reply_all`` keys that made three previews three different shapes.
    """

    action: str
    to: list[str]
    cc: list[str] = field(default_factory=list)
    bcc: list[str] = field(default_factory=list)
    sender: str = ""
    subject: str = ""
    body: str = ""
    html: bool = False
    source: str = ""
    dispatch: Callable[[], None] = lambda: None

    def _envelope(self) -> dict:
        return {
            "action": self.action,
            "to": self.to,
            "cc": self.cc,
            "bcc": self.bcc,
            "from": self.sender or MAIL_DEFAULT_SENDER,
            "subject": self.subject,
            "source": self.source,
        }

    def preview(self) -> dict:
        """The ONE ``would_send`` shape. Same keys for every action, so a caller writes
        one dry-run handler — and the two size/format facts a human approving a send
        wants (how much text, is it HTML) ride along in fixed positions."""
        return {
            "dry_run": True,
            "would_send": {
                **self._envelope(),
                "body_chars": len(self.body),
                "html": self.html,
            },
        }

    def accepted(self) -> dict:
        """The result after Mail took the message. ``sent: True`` means ACCEPTED, not
        delivered — ``with_outbox_pending`` adds the queue truth on top."""
        return {"sent": True, **self._envelope()}


def deliver(outgoing: Outgoing, *, dry_run: bool) -> dict:
    """The one outbound path. ``dry_run`` returns the preview and CONSTRUCTS NOTHING
    (rule 1 at the module docstring); otherwise dispatch, then report the outbox truth.

    Whatever native READS a builder needed to fill the envelope have already happened by
    the time this is called — that is rule 2, and it is why this function cannot be
    "make the preview cheap by moving the reads here"."""
    if dry_run:
        return outgoing.preview()
    outgoing.dispatch()
    return with_outbox_pending(outgoing.accepted())


def _outbox_pending() -> int:
    """Run _OUTBOX_COUNT and parse the result. The script always returns a plain
    integer coerced `as text`, so a parse failure means something is structurally
    wrong — let it raise rather than silently reporting 0 (which would itself be the
    dishonest-success failure this whole feature exists to prevent)."""
    return int(runtime.run_osascript(_OUTBOX_COUNT).strip())


def with_outbox_pending(result: dict) -> dict:
    """Merge the outbox truth into a send result dict. When Mail's outbox is non-empty,
    add a `note` a model can relay to the human verbatim — the caller must not treat
    `sent: True` alone as delivery confirmation.

    A FAILURE of this follow-up read degrades to ``outbox_pending: None`` + note,
    never an exception: the send already happened, and raising here reports a
    COMPLETED send as a failed call — a model that retries that "failure" sends the
    mail twice. Same principle as never rolling back past the `send` verb, applied
    to the reporting side. None is "unknown", which is honest; 0 would be a fake
    clean queue."""
    try:
        pending = _outbox_pending()
    except (NativeError, OSError, ValueError):
        result["outbox_pending"] = None
        result["note"] = (
            "Mail accepted the message but its Outbox could not be read — delivery "
            "is NOT confirmed. Tell the user to open Mail ▸ Outbox to check before "
            "assuming this was delivered. Do NOT retry the send."
        )
        return result
    result["outbox_pending"] = pending
    if pending > 0:
        result["note"] = (
            f"Mail still has {pending} message(s) queued in its Outbox — delivery is "
            "NOT confirmed. Tell the user to open Mail ▸ Outbox to check before "
            "assuming this was delivered."
        )
    return result


def split_addrs(value) -> list[str]:
    """Normalize a recipient argument to a list of addresses. Accepts a comma-separated
    string (what a model usually produces) or a list; blanks are dropped. None → [].

    Every entry is run through ``sanitize_line`` (F1 review): callers US-join the
    result and _SEND/_FORWARD re-split on US (`text items of`), so an address string
    containing a literal U+001F would otherwise yield ONE entry in a dry-run preview
    but split into TWO recipients on the wire once joined — the preview and the wire
    must describe the same recipient set by construction. sanitize_line strips
    C0/C1/DEL controls (which includes U+001F) and collapses whitespace; an entry that
    sanitizes to empty is dropped."""
    if value is None:
        return []
    items = value if isinstance(value, list) else str(value).split(",")
    return [s for a in items if (s := sanitize_line(a))]


def build_quote(sender: str, date_str: str, original_body: str) -> str:
    """Standard reply quote: `On <date>, <sender> wrote:` then the original body, each
    line `> `-prefixed. Bounded via clean_body (hard=None: always truncate, never raise
    — the quote is supplementary text, not the primary deliverable, so a huge original
    must not abort the whole reply)."""
    bounded = clean_body(original_body, hard=None)
    quoted = "\n".join("> " + line for line in bounded.splitlines())
    return f"On {date_str}, {sender} wrote:\n{quoted}"


def quoted_body(body: str, message_id: str, mailbox_args: tuple[str, str]) -> str:
    """``body`` plus the quoted original — the 10-line preamble ``reply`` and
    ``reply_all`` each carried their own copy of (fetch, guard missing value, partition
    on US twice, sanitize both halves, build the quote).

    Defense in depth: the script already strips raw framing bytes from sender/date, but
    ``sanitize_line`` ALSO strips any other control char a display name or date could
    carry, so the quote header stays clean even when the script side is bypassed (a
    mocked ``_ORIGINAL`` in tests). An original that cannot be read degrades to an
    unquoted body — the reply is the deliverable, the quote is decoration."""
    raw = runtime.run_osascript(_ORIGINAL, message_id, *mailbox_args)
    if not raw.strip() or raw.strip() == _MISSING_VALUE:
        return body
    sender, _, rest = raw.partition(US)
    date_str, _, original = rest.partition(US)
    quote = build_quote(sanitize_line(sender), sanitize_line(date_str), original)
    return body + "\n\n" + quote


# --- the four builders ---------------------------------------------------------------


def new_message(
    to,
    subject: str = "",
    body: str = "",
    cc=None,
    bcc=None,
    html: bool = False,
    from_address: str | None = None,
) -> Outgoing:
    """A fresh message. The only builder whose envelope is fully known from its
    arguments, so its preview reads nothing at all."""
    to_list = split_addrs(to)
    if not to_list:
        raise ValueError("send_mail needs at least one recipient address (to)")
    if not (subject or "").strip() and not (body or "").strip():
        raise ValueError("send_mail needs a subject or a body (both were empty)")
    cc_list, bcc_list = split_addrs(cc), split_addrs(bcc)
    sender = (from_address or "").strip()
    text = body or ""
    subj = subject or ""

    def dispatch() -> None:
        with runtime.body_file(text) as path:
            runtime.run_osascript(
                _SEND,
                subj,
                path,
                "1" if html else "0",
                sender,
                US.join(to_list),
                US.join(cc_list),
                US.join(bcc_list),
            )

    return Outgoing(
        action="send",
        to=to_list,
        cc=cc_list,
        bcc=bcc_list,
        sender=sender,
        subject=subj,
        body=text,
        html=bool(html),
        dispatch=dispatch,
    )


def _parse_reply_all_recipients(raw: str) -> dict:
    """Parse the _REPLY_ALL_RECIPIENTS payload: RS-framed (kind, value) records, kind in
    "to"/"cc"/"sender"/"subject". Malformed/partial trailing records are skipped — same
    defensive rule as every other parser here."""
    to: list[str] = []
    cc: list[str] = []
    sender = ""
    subject = ""
    for rec in raw.split(RS):
        fields = rec.split(US)
        if len(fields) < 2:
            continue
        kind, value = fields[0], fields[1]
        if kind == "to":
            to.append(value)
        elif kind == "cc":
            cc.append(value)
        elif kind == "sender":
            sender = value
        elif kind == "subject":
            subject = value
    return {"to": to, "cc": cc, "sender": sender, "subject": subject}


def reply_all_to(
    message_id: str, mailbox: str, body: str, include_quote: bool = True
) -> Outgoing:
    """A reply-all. Its preview READS the original's actual to/cc — rule 2 at the module
    docstring, and the reason ``dry_run`` defaults to True on this tool at all."""
    mid = bare_id(message_id)
    if not mid:
        raise ValueError("reply_all needs the original message's id")
    if not body.strip():
        raise ValueError("reply_all needs a non-empty body")
    mb = mail_addressing.mailbox_args(mailbox)
    seen = _parse_reply_all_recipients(
        runtime.run_osascript(_REPLY_ALL_RECIPIENTS, mid, *mb)
    )

    def dispatch() -> None:
        text = quoted_body(body, mid, mb) if include_quote else body
        with runtime.body_file(text) as path:
            runtime.run_osascript(_REPLY_ALL, mid, path, *mb)

    return Outgoing(
        action="reply_all",
        to=seen["to"],
        cc=seen["cc"],
        sender=seen["sender"],
        subject=seen["subject"],
        body=body,
        source=message_id.strip(),
        dispatch=dispatch,
    )


def forward_of(message_id: str, mailbox: str, to) -> Outgoing:
    """A forward. **No body parameter exists** — writing ``content`` on a forward
    destroys its attachments (device-verified: 7 in, 0 out), so the rule is the
    interface, not an omitted line. ``subject`` stays empty: Mail composes the "Fwd: …"
    subject itself at send time, and reading the original just to guess at it would
    launch Mail for a preview that otherwise needs no native call at all."""
    mid = bare_id(message_id)
    if not mid:
        raise ValueError("forward needs the original message's id")
    to_list = split_addrs(to)
    if not to_list:
        raise ValueError("forward needs at least one recipient address (to)")
    mb = mail_addressing.mailbox_args(mailbox)

    def dispatch() -> None:
        runtime.run_osascript(_FORWARD, mid, US.join(to_list), *mb)

    return Outgoing(
        action="forward",
        to=to_list,
        source=message_id.strip(),
        dispatch=dispatch,
    )


def _parse_draft_envelope(raw: str) -> dict:
    """Parse the _DRAFT_ENVELOPE payload: seven US-partitions from the LEFT, then the
    body. Recipient lists are RS-joined inside their own field."""
    subject, _, rest = raw.partition(US)
    sender, _, rest = rest.partition(US)
    to_raw, _, rest = rest.partition(US)
    cc_raw, _, rest = rest.partition(US)
    bcc_raw, _, rest = rest.partition(US)
    n_att, _, rest = rest.partition(US)
    threaded, _, body = rest.partition(US)

    def addrs(value: str) -> list[str]:
        return [s for part in value.split(RS) if (s := sanitize_line(part))]

    return {
        "subject": sanitize_line(subject),
        "sender": sanitize_line(sender),
        "to": addrs(to_raw),
        "cc": addrs(cc_raw),
        "bcc": addrs(bcc_raw),
        "attachments": int(n_att) if n_att.strip().isdigit() else 0,
        "threaded": threaded.strip() == "1",
        "body": body,
    }


def stored_draft(draft_id: str) -> Outgoing:
    """#157: send a draft the human already approved, by its stable Message-ID.

    Mail cannot script-send a stored draft (``send`` is declared on ``outgoing
    message``; a Drafts ``message`` raises -1708, and ``open``ing it yields a compose
    window AppleScript never sees). So this REBUILDS the draft as a fresh outgoing
    message from the draft's own stored bytes — the model never re-types the body, so
    what the human approved and what goes out are the same text — and REFUSES the two
    cases where rebuilding would silently lose something:

    * **attachments** — a rebuilt message carries none;
    * **a reply/forward draft** (In-Reply-To/References present) — those headers can
      only be set by Mail's native ``reply``/``forward`` verbs, so the rebuilt message
      would arrive detached from its thread. ``reply_all``/``forward_mail`` do that job.

    Both refusals are ValueErrors naming the alternative. Silently degrading a send is
    the one thing this plane must never do.
    """
    mid = bare_id(draft_id)
    if not mid:
        raise ValueError("send_mail(draft_id=…) needs the draft's message-id")
    d = _parse_draft_envelope(runtime.run_osascript(_DRAFT_ENVELOPE, mid))
    if not d["to"]:
        raise ValueError(
            f"draft {mid!r} has no recipient — open it in Mail and address it first"
        )
    if d["attachments"]:
        raise ValueError(
            f"draft {mid!r} carries {d['attachments']} attachment(s). Mail cannot "
            "script-send a stored draft, so this rebuilds it — and a rebuilt message "
            "carries no attachments. Send this one from Mail's own compose window."
        )
    if d["threaded"]:
        raise ValueError(
            f"draft {mid!r} is a reply or forward (it carries In-Reply-To/References). "
            "Rebuilding it would drop those headers and the message would arrive "
            "detached from its thread. Use reply_all(dry_run=False) or "
            "forward_mail(dry_run=False) against the ORIGINAL message instead."
        )

    def dispatch() -> None:
        with runtime.body_file(d["body"]) as path:
            runtime.run_osascript(
                _SEND,
                d["subject"],
                path,
                "0",
                d["sender"],
                US.join(d["to"]),
                US.join(d["cc"]),
                US.join(d["bcc"]),
            )

    return Outgoing(
        action="send_draft",
        to=d["to"],
        cc=d["cc"],
        bcc=d["bcc"],
        sender=d["sender"],
        subject=d["subject"],
        body=d["body"],
        source=mid,
        dispatch=dispatch,
    )
