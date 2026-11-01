"""The outgoing-message lifecycle (#160) — the one module that owns "this leaves the
machine".

Four tools dispatch mail off this Mac: ``send_mail``, ``reply_all``, ``forward_mail``
and (#157) ``send_mail(draft_id=…)``. They differ only in how their envelope is
*obtained*; everything after that — the preview shape, the rule about what a preview may
touch, the send, the outbox truth-check — is identical, and before this module each copy
re-derived it (three different ``would_send`` shapes, the "dry run constructs nothing"
rule stated in prose in four docstrings and enforced nowhere).

**The discipline, stated once.**

1. *A preview NEVER CONSTRUCTS.* Mail autosaves any outgoing message into Drafts
   ~10-15s after it is built — asynchronously, unsuppressably, whether it was sent,
   rolled back or abandoned (#133, device-verified). The autosaved copy's id is minted
   at autosave time, so it cannot be identified in advance and cannot be swept. The only
   way to leave nothing behind is to build nothing. So ``dry_run`` never reaches
   ``make new outgoing message`` / ``reply`` / ``forward``.
2. *A preview MAY READ stored mail.* Reading a message that already exists strands
   nothing, so the rule in (1) does not forbid it — and two previews are worthless
   without it. ``reply_all``'s preview reads the original (its to/cc, Reply-To, sender
   and the holding account's addresses) to resolve the reply's OWN recipients (reply-all
   is exactly the tool whose recipient set surprises you, #516), and
   ``send_mail(draft_id=…)``'s preview reads the draft it is about to send (an id
   alone tells the approving human nothing). This is the exception that used to carry
   a 9-line justification at ``reply_all``'s call site; it lives here now because it is
   a property of the plane, not of one tool.
3. *Never roll back past the ``send`` verb.* ``delete`` after ``send`` is a silent
   no-op — it returns cleanly, removes nothing, and the message delivers anyway (#135).
   Every script here therefore keeps ``send`` OUTSIDE its rollback ``try`` (the reply
   send, ``_SEND_OUTGOING``, has no rollback at all), and ``tests/test_mail.py`` greps
   for exactly that. What a sent ``reply_all`` leaves in Drafts is swept afterwards by
   the stored row's own message id (``_ReplyFlow.after_send``), never by the outgoing
   message.
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

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from .. import runtime
from ..errors import (
    ACCESSIBILITY_PANE,
    AccessibilityDenied,
    ComposeRefused,
    NativeError,
)
from ..text import (
    READ_BODY,
    RS,
    STRIP_FRAMING,
    US,
    sanitize_block,
    sanitize_line,
    squash_text,
)
from . import mail_addressing, mail_reply_cleanup, mailbox_url
from .mail_addressing import bare_id

# The default-account placeholder a preview reports instead of guessing: Mail's default
# sender is NOT predictable from account order (device-verified), so naming one would be
# a lie a human might approve.
MAIL_DEFAULT_SENDER = "(Mail default account)"

# What a reply_all preview reports as `from`: Mail answers from the account that holds
# the original and picks the address itself, so naming one would be a guess (#516).
REPLY_SENDER = "(the account that holds the original)"


def _bare_address(value: str) -> str:
    """The address inside the LAST ``<...>`` when the stripped value ends with ``>``,
    else the whole stripped value (the rule ``owned_sender`` documents)."""
    addr = value.strip()
    if addr.endswith(">") and "<" in addr:
        addr = addr.rsplit("<", 1)[1][:-1].strip()
    return addr


def owned_sender(from_address: str) -> str:
    """The caller's ``from_address``, verified against an owned Mail account and
    returned in MAIL's OWN spelling — the form ``set sender of msg to ...`` must
    receive (#208, MAIL-04, D-09).

    Mail does not reject a ``from_address`` no account owns — it silently sends from
    its default account instead (spike 005, device-verified). So this refuses it
    first, in Python, before any native write: an unowned address raises a typed
    ``ValueError`` naming the refused address, why (Mail would otherwise substitute
    its default silently), and the fix (one of the owned addresses, or omit
    ``from_address`` for Mail's default).

    Extraction is the address inside the LAST ``<...>`` when the stripped value ends
    with ``>``, else the whole stripped value — matched case-insensitively against
    ``mail_addressing.owned_addresses()``. Deliberately NOT ``email.utils.parseaddr``:
    it returns ``('', '')`` on Mail's own ``x@y <X@Y>`` shape, a display name
    containing an ``@`` with no quoting (device-verified, facts doc). Taking the LAST
    pair is also the deliberately-safe choice, not merely the Mail-compatible one: a
    display name that itself contains a ``<...>`` pair cannot smuggle a second address
    past this ownership check, since the real address Mail will send from is always
    the final bracketed pair.
    """
    addr = _bare_address(from_address)
    owned = mail_addressing.owned_addresses()
    spelling = owned.get(addr.lower())
    if spelling is None:
        raise ValueError(
            f"{from_address!r} is not an address any Mail account owns — Mail would "
            "silently send from its default account instead of refusing, so this "
            "call refuses first. Owned addresses: "
            f"{', '.join(sorted(owned.values()))}. Use one of them, or omit "
            "from_address for Mail's default."
        )
    return spelling


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
    "Outbox before retrying, so a retry cannot send twice. Quitting and " & ¬
    "reopening Mail clears it.)"
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
# set reply-all would ACTUALLY reach — plus its sender, Reply-To and subject, by
# message-id, and the addresses of the account that holds the message (#516: Python
# resolves the reply's own to/cc from them; the original's header is not the reply).
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
    set rt to reply to of m
    if rt is missing value then set rt to ""
    set out to out & "replyto" & us & (my stripFraming(rt)) & rs
    set subj to subject of m
    if subj is missing value then set subj to ""
    set out to out & "subject" & us & (my stripFraming(subj)) & rs
    try
      repeat with ea in (email addresses of (account of (mailbox of m)))
        set out to out & "self" & us & (my stripFraming(ea as text)) & rs
      end repeat
    end try
  end tell
  end timeout
  return out
end run"""
)

# the native reply (#42/#46, #348): fetch the original's Mail-internal id, sender,
# received date and plaintext by message-id (US-framed, eight fields). The flow takes
# the original's last words from it (what must follow the reply text for Mail's own
# quote to count as confirmed) and Mail's attribution line (which the Drafts sweep
# allows after the call's text); nothing is quoted from it any more: Mail builds the
# quote itself. The internal id is what `_REPLY_OPEN` opens the reply by (`«class
# mssg» id n`, 4-12 ms on any mailbox size, spike 006), so the O(mailbox) `whose
# message id` scan happens HERE, before the sweep's baseline, and never between the
# baseline and the `reply` verb. A fourth argument "0" skips the body
# (`include_quote=False` needs only the id). The date travels as five integers (#348):
# Mail's attribution line wants the Mac's own date and time format, which only
# Foundation gives (runtime.mail_attribution_stamp), and a locale string cannot be
# parsed back. The sender is stripped of raw framing bytes (the shared STRIP_FRAMING
# handler) before being joined, so a display name that happens to contain a literal
# US/RS char can't desync the split in _quote_facts. The body `c` is the LAST field
# and needs no stripping for parse-safety (sanitize_block strips control chars from it
# in _quote_facts). A missing date leaves its five fields empty; the attribution line
# is then written without a date.
_ORIGINAL = (
    STRIP_FRAMING
    + "\n\n"
    + mail_addressing.MAILBOX_REF
    + """

on run argv
  set mid to item 1 of argv
  set mb to my mailboxFor(item 2 of argv, item 3 of argv)
  set wantText to ((count of argv) < 4) or ((item 4 of argv) is not "0")
  set us to character id 31
  with timeout of 120 seconds
  tell application "Mail"
    set matches to (messages of mb whose message id is mid)
    if (count of matches) is 0 then error ¬
      "no message with that message id in " & (item 3 of argv)
    set m to item 1 of matches
    set snd to sender of m
    set d to date received of m
    if d is missing value then
      set dp to us & us & us & us
    else
      set dp to "" & (year of d) & us & ((month of d) as integer) & us & (day of d) ¬
        & us & (hours of d) & us & (minutes of d)
    end if
    set c to ""
    if wantText then
      set c to content of m
      if c is missing value then set c to ""
    end if
    return "" & (id of m) & us & (my stripFraming(snd)) & us & dp & us & c
  end tell
  end timeout
end run"""
)

# --- the native reply (FIX-16, #348; facts section 4e) -------------------------------
#
# `mail_reply` lets Mail build its own reply (`reply … opening window yes`, NO write to
# `content`: any scripted body loses the native quote, facts 4d) and puts the reply text
# on top through `runtime.compose_insert`. These four scripts are that flow's Mail side.
# Each wraps its Mail block in `with timeout of 120 seconds` and every call passes
# `timeout=ORIGINAL_TIMEOUT`, so the host never gives up on a step Mail is still doing.
_JOIN_IDS = """on joinIds(xs)
  set tid to AppleScript's text item delimiters
  set AppleScript's text item delimiters to ","
  set s to (xs as text)
  set AppleScript's text item delimiters to tid
  return s
end joinIds"""

# The ids of every outgoing message BEFORE the reply opens: the baseline `_DISCARD_NEW_
# REPLY` needs when a failure leaves the reply's own id unknown. Reads ids only; it does
# not touch the original.
_OUTGOING_IDS = (
    _JOIN_IDS
    + """

on run argv
  with timeout of 120 seconds
    tell application "Mail"
      set xs to id of every outgoing message
    end tell
  end timeout
  return my joinIds(xs)
end run"""
)

# Open Mail's native reply and bind its window by the id set that is NEW across the
# `reply` verb (facts 4e `Window identity`, B1). Only CLOSEABLE new windows count: a
# tiled Mail viewer adds a non-closeable 13-pixel divider window beside the compose
# window. Never `window 1`, never a title. An unreadable `closeable` keeps the id (more
# candidates fail, never mis-bind). Zero or several candidates is an error, and the
# error path rolls the reply back (verified, only -1728 counts). There is NO retry on
# zero: the device listed the reply window at once in all 43 opens, and a second read
# after a delay could bind a window the OWNER opened in that second (a hand reply, with
# focus in its body) and paste into it. The original is addressed by its Mail-internal
# id from `_ORIGINAL` (`«class mssg» id n of mb`, no `whose` scan: the Drafts sweep's
# claim window starts at the `reply` verb, so nothing slow may run before it), and its
# `message id` is re-read and compared first: a mismatch (the id names another message
# now) is an error BEFORE any reply exists. Returns `outgoing-id US window-id US
# sender US signature`; the sender (the From address of the reply, read while the reply
# exists) is "" when Mail does not answer it, and the sweep then proves nothing. The
# signature (the `content` of the reply's `message signature`, read into a variable
# first: FIX-16 gap G4) is "" when Mail has none or does not answer; it is the LAST
# field so a US character inside it cannot shift the others, and it is only compared.
_REPLY_OPEN = (
    ROLLBACK
    + "\n\n"
    + mail_addressing.MAILBOX_REF
    + """

on newWindowIds(idsBefore, idsAfter)
  set found to {}
  repeat with w in idsAfter
    set wi to contents of w
    if wi is not in idsBefore then
      set cl to true
      try
        tell application "Mail" to set cl to closeable of window id wi
      end try
      if cl then set end of found to wi
    end if
  end repeat
  return found
end newWindowIds

on run argv
  set n to (item 1 of argv) as integer
  set mb to my mailboxFor(item 2 of argv, item 3 of argv)
  set doAll to ((item 4 of argv) is "1")
  set expected to item 5 of argv
  set us to character id 31
  with timeout of 120 seconds
  tell application "Mail"
    set m to «class mssg» id n of mb
    set gotId to "<<unreadable>>"
    try
      set gotId to message id of m
    end try
    if gotId is not expected then error ¬
      "the original is no longer the message at Mail's id " & n & " in " & ¬
      (item 3 of argv)
    set idsBefore to id of every window
    set r to reply m opening window yes reply to all doAll
    try
      set found to my newWindowIds(idsBefore, id of every window)
      if (count of found) is not 1 then error ¬
        "could not tell which window is the reply (" & (count of found) & ¬
        " new windows)"
      set snd to ""
      try
        set snd to (sender of r) as text
      end try
      set sig to ""
      try
        set sg to message signature of r
        if sg is not missing value then set sig to (content of sg) as text
      end try
      return ((id of r) as text) & us & ((item 1 of found) as text) & us & snd & ¬
        us & sig
    on error errMsg
      if my rollback(r) then
        error errMsg
      else
        error errMsg & my draftLeftover()
      end if
    end try
  end tell
  end timeout
end run"""
)

# Discard the reply by its outgoing message id: `dead` only when the verifying rollback
# got -1728; `alive` otherwise. Addressing by id works from a later osascript process
# than the one that opened the reply (facts 4e `Refusal cleanup`). Safe to run twice: a
# dead reference answers -1728 again.
_DISCARD_OUTGOING = (
    ROLLBACK
    + """

on run argv
  set oid to (item 1 of argv) as integer
  with timeout of 120 seconds
    tell application "Mail"
      if my rollback(outgoing message id oid) then return "dead"
      return "alive"
    end tell
  end timeout
end run"""
)

# The id-free discard (facts 4e `Id-free discard`): the reply's own id is unknown (the
# open timed out, say). Candidates are the outgoing messages that are NEW since the
# baseline and whose subject ends with the original's subject; an empty subject matches
# nothing. Exactly one candidate is discarded; zero is `none`, several is `several` and
# deletes nothing. A Cmd-N window or a hand reply is not a scripting object, and a hand
# reply scripted in the meantime makes two candidates, so neither is ever deleted.
_DISCARD_NEW_REPLY = (
    ROLLBACK
    + "\n\n"
    + mail_addressing.MAILBOX_REF
    + """

on run argv
  set known to "," & (item 1 of argv) & ","
  set mid to item 2 of argv
  set mb to my mailboxFor(item 3 of argv, item 4 of argv)
  with timeout of 120 seconds
    tell application "Mail"
      set matches to (messages of mb whose message id is mid)
      if (count of matches) is 0 then return "original-missing"
      set subj to subject of (item 1 of matches)
      if subj is "" then return "none"
      set cands to {}
      repeat with om in outgoing messages
        try
          set oi to id of om
          if known does not contain ("," & oi & ",") then
            if (subject of om) ends with subj then set end of cands to oi
          end if
        end try
      end repeat
      if (count of cands) is 0 then return "none"
      if (count of cands) > 1 then return "several"
      if my rollback(outgoing message id (item 1 of cands)) then return "dead"
      return "alive"
    end tell
  end timeout
end run"""
)


# Which account SENDS the reply (facts 4e `Refusal cleanup` (3)): every account's id
# (the UUID that mailboxes.url embeds) with its email addresses, US-framed, one
# RS-ended record per account: `id US address US address RS`. Reads account properties
# only, never a message; the sweep matches the reply's From address against it in
# Python (case insensitive) and claims a Drafts row only in the one account that holds
# it.
_ACCOUNT_ADDRESSES = """on run argv
  set us to character id 31
  set rs to character id 30
  set out to ""
  with timeout of 120 seconds
  tell application "Mail"
    repeat with acc in accounts
      set AppleScript's text item delimiters to us
      set out to out & (id of acc) & us & ((email addresses of acc) as text) & rs
    end repeat
  end tell
  end timeout
  set AppleScript's text item delimiters to ""
  return out
end run"""

# Does an earlier scripted compose window rule the sweep out? (facts 4e `Refusal
# cleanup` (2)). Reads the subject of the original (by its Mail-internal id) and of
# every outgoing message that was open at the start (`known`, comma-joined ids):
# "clear" only when every one has a readable, non-empty subject that does NOT end with
# the original's, the `_DISCARD_NEW_REPLY` predicate (a window that can autosave a
# reply to THIS original carries "Re: <its subject>"). An empty original subject, and
# a window that is gone or unreadable by now, answer "block": stricter, never looser.
_BASELINE_CLEAR = (
    mail_addressing.MAILBOX_REF
    + """

on run argv
  set AppleScript's text item delimiters to ","
  set ids to text items of (item 1 of argv)
  set AppleScript's text item delimiters to ""
  set n to (item 2 of argv) as integer
  set mb to my mailboxFor(item 3 of argv, item 4 of argv)
  with timeout of 120 seconds
    tell application "Mail"
      set subj to subject of («class mssg» id n of mb)
      if subj is missing value or subj is "" then return "block"
      repeat with oi in ids
        set blocked to true
        try
          set s to subject of (outgoing message id ((contents of oi) as integer))
          if s is not missing value and s is not "" then
            if not (s ends with subj) then set blocked to false
          end if
        end try
        if blocked then return "block"
      end repeat
      return "clear"
    end tell
  end timeout
end run"""
)


# Send the reply that `_REPLY_OPEN` built and `compose_insert` filled, by its outgoing
# message id (facts 4e `Send after insert`: works from a later osascript). It runs only
# after the insert is CONFIRMED and sits outside every rollback: `delete` after the
# `send` verb is a silent no-op (facts 3), so there is no handler here and nothing after
# `send`. The autosave copy this leaves in Drafts is the sweep's business, by the stored
# row's own message id, never by this outgoing message.
_SEND_OUTGOING = """on run argv
  with timeout of 120 seconds
    tell application "Mail"
      set r to outgoing message id ((item 1 of argv) as integer)
      send r
      return "sent"
    end tell
  end timeout
end run"""


# Delete the call's own autosaved Drafts copy (facts 4e `Refusal cleanup`). Addressed
# in the REPLY ACCOUNT'S Drafts by Message-ID, a `whose` query (0.3 s on a store of 287
# drafts), never `delete_draft`'s walk of the unified Drafts mailbox (#521). Exactly one
# match is deleted. `delete` is ASYNCHRONOUS on the source side (facts 5c: the source
# still counts the message at t0 and has cleared it by t3), so absence is read once,
# after one bounded `delay 3` (a single wait, never a loop on Mail). `deleted` only when
# that re-query finds nothing; any other answer is `alive`, which the caller reports as
# "may be left". Whether Drafts clears within 3 s is checked on device in 05.2-13.
_SWEEP_DELETE = (
    mail_addressing.MAILBOX_REF
    + """

on run argv
  set mid to item 1 of argv
  set mb to my mailboxFor(item 2 of argv, item 3 of argv)
  with timeout of 120 seconds
    tell application "Mail"
      set matches to (messages of mb whose message id is mid)
      if (count of matches) is 0 then return "gone"
      if (count of matches) > 1 then return "several"
      delete (item 1 of matches)
      delay 3
      if (count of (messages of mb whose message id is mid)) is 0 then return "deleted"
      return "alive"
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
    recipients_note: str = ""
    # what the builder's send leaves to report beside `sent` (reply_all's Drafts copy)
    dispatch: Callable[[], dict | None] = lambda: None

    def _envelope(self) -> dict:
        envelope = {
            "action": self.action,
            "to": self.to,
            "cc": self.cc,
            "bcc": self.bcc,
            "from": self.sender or MAIL_DEFAULT_SENDER,
            "subject": self.subject,
            "source": self.source,
        }
        if self.recipients_note:  # own key: with_outbox_pending owns `note`
            envelope["recipients_note"] = self.recipients_note
        return envelope

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
    "make the preview cheap by moving the reads here". A builder's ``dispatch`` may
    return extra keys to report beside ``sent`` (``reply_all``'s ``drafts_copy``)."""
    if dry_run:
        return outgoing.preview()
    extra = outgoing.dispatch()
    result = with_outbox_pending(outgoing.accepted())
    if extra:  # its own keys, so the outbox note stays
        result.update(extra)
    return result


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


def build_attribution(sender: str, stamp: tuple[str, str] | None) -> str:
    """Mail's attribution line (#348): `On <date>, at <time>, <sender> wrote:`
    (`<sender> wrote:` when the date is unknown)."""
    when = f"On {stamp[0]}, at {stamp[1]}, " if stamp else ""
    return f"{when}{sender} wrote:"


# #230: every script that acts on the ORIGINAL message (read it, reply to it, forward
# it) finds it with a `whose message id is` scan and can run past the 30s default on
# device, with Mail mostly idle in the watchdog samples: `_ORIGINAL` did (02.1), then
# `_REPLY` once `_ORIGINAL` had its 120s (2026-10-05). With every such call at 120s, a
# reply to the newest inbox message took 52-72s end to end, 5 of 5. 120.0 equals each
# script's own `with timeout of 120 seconds` backstop (GATE-10 is >=, so equality
# passes).
ORIGINAL_TIMEOUT = 120.0


def _stamp(date_parts: list[str]) -> tuple[str, str] | None:
    """The attribution's ``(date, time)`` from ``_ORIGINAL``'s five date fields; None
    when the date cannot be read (the line is then written without one)."""
    try:
        return runtime.mail_attribution_stamp(datetime(*map(int, date_parts)))
    except (ValueError, OverflowError, OSError):
        return None


# --- the native reply flow (FIX-16, #348) --------------------------------------------

# How many of the original's last words must follow the reply text (facts 4e `Confirm`:
# the tail comes from the original's own text, folded and squashed the same way).
_TAIL_WORDS = 6


def _quote_facts(
    message_id: str,
    mailbox_args: tuple[str, str],
    tool: str = "mail_reply",
    *,
    quote: bool = True,
) -> tuple[str | None, str | None, int]:
    """``(tail, attribution, internal id)`` of the original. The tail is its last words,
    squashed: what must follow the reply text for Mail's quote to count as confirmed. An
    original with no readable text has no tail, and the flow refuses before it creates
    anything. The attribution is Mail's line for this original, which the Drafts sweep
    allows after the call's text (facts 4e `Refusal cleanup`). The internal id is what
    the reply is opened by (``_REPLY_OPEN``). ``quote=False`` (no quote) reads the id
    alone: tail and attribution are None."""
    raw = runtime.run_osascript(
        _ORIGINAL,
        message_id,
        *mailbox_args,
        *(() if quote else ("0",)),
        timeout=ORIGINAL_TIMEOUT,
    )
    parts = raw.split(US, 7)
    tail = attribution = None
    if quote:
        original = parts[7] if len(parts) == 8 else ""
        words = squash_text(sanitize_block(original).replace("\ufffc", "")).split()
        tail = " ".join(words[-_TAIL_WORDS:])
        # the confirm compares letters and digits: a tail of marks only matches anything
        if not any(c.isalnum() for c in tail):
            raise ComposeRefused(
                f"{tool} cannot confirm Mail's quote: the original has no readable "
                "text, so there is nothing to check the quote against. Nothing was "
                "created and nothing was sent. To reply without the quote, call "
                f"{tool} with include_quote=False."
            )
        attribution = build_attribution(sanitize_line(parts[1]), _stamp(parts[2:7]))
    if len(parts) != 8 or not parts[0].strip().isdigit():
        raise ComposeRefused(
            f"{tool} could not read the original message from Mail. Nothing was "
            "created and nothing was sent."
        )
    return tail, attribution, int(parts[0])


def _parse_open(raw: str) -> tuple[int, int, str, str]:
    """``(outgoing id, window id, sender, signature)`` from ``_REPLY_OPEN``; ValueError
    otherwise. The sender (the reply's From) and the signature (the one Mail put into
    this reply) are "" when Mail did not answer them. The signature is the last field,
    so a US character inside it stays whole."""
    # strip() eats a trailing US (Python counts it as whitespace): an empty last field
    # is an absent field, not an error
    outgoing, window, *rest = raw.strip().split(US, 3)
    sender, signature = (rest + ["", ""])[:2]
    return int(outgoing), int(window), sender.strip(), signature.strip()


_LEFT_OVER = (
    " The reply may NOT be fully removed: a reply window or a Drafts copy may be "
    "left. Look for the open reply window to that message and in the Drafts mailbox "
    "of the account the reply is sent from (usually the account that holds the "
    "original; delete_draft removes a draft). Mail saves the copy up to about a "
    "minute after the window opened, so look again after that. Nothing was sent."
)

# The same, after a PROVEN discard: the window is gone, only a Drafts copy may be left.
_DRAFTS_LEFT = (
    " The reply window was discarded, but the reply may NOT be fully removed: a "
    "Drafts copy may be left. Look in the Drafts mailbox of the account the reply is "
    "sent from (usually the account that holds the original; delete_draft removes a "
    "draft). Mail saves the copy up to about a minute after the window opened, so "
    "look again after that. Nothing was sent."
)

# After an unproven discard that still found and deleted the autosaved copy.
_DELETED_WINDOW_LEFT = (
    " A Drafts copy that Mail autosaved was found and deleted. The reply may NOT be "
    "fully removed: the discard of the reply window was not proven, so look for the "
    "open reply window to that message. Nothing was sent."
)

# Said when the discard ran so late that the Drafts read followed it too closely to
# prove anything (facts 4e `Refusal cleanup`: only a read long after the discard is
# proven).
_STILL_LAND = (
    " The reply was discarded, but the discard ran too long after the window opened to "
    "rule out a Drafts copy that may still land: look in the Drafts mailbox of the "
    "account the reply is sent from (usually the account that holds the original) "
    "again in a minute. Nothing was sent."
)

# What the call says about the Drafts copy of a reply that WAS sent, beside `sent` (the
# send itself is never reported as failed because of this check, and nothing outside the
# one proven Drafts row is ever deleted).
_LOOK_IN_DRAFTS = (
    "Look in the Drafts mailbox of the account the reply was sent from (usually the "
    "account that holds the original; delete_draft removes a draft)."
)
_SENT_COPY = {
    "removed": (
        "The reply was sent. A Drafts copy that Mail autosaved was found and deleted."
    ),
    "none": (
        "The reply was sent. No Drafts copy was there 45 s after the window opened."
    ),
    "late": (
        "The reply was sent. The check for a Drafts copy ran too soon after the send "
        "to rule out one that has not landed yet. " + _LOOK_IN_DRAFTS + " Look "
        "again in a minute."
    ),
    "unproven": (
        "The reply was sent. A Drafts copy may be left: the check found a message it "
        "could not prove to be this reply's own copy, or could not confirm a delete. "
        + _LOOK_IN_DRAFTS
    ),
    "unavailable": (
        "The reply was sent. A Drafts copy may be left: the check could not read "
        "Mail's index (no Full Disk Access, for example). Mail saves the copy up to "
        "about a minute after the window opened. " + _LOOK_IN_DRAFTS
    ),
}

# Said when the send call fails: Mail may have accepted it all the same (a timeout), so
# a retry could send twice. The reply is NOT discarded after a send started (facts 3).
_SEND_UNSURE = (
    " (WARNING: the reply may have been sent. Check Mail's Outbox and Sent before "
    "retrying, so a retry cannot send twice. A reply window may still be open; close "
    "it without sending. A Drafts copy of the reply may also be left, in the Drafts "
    "mailbox of the account the reply is sent from; nothing was swept.)"
)

# Owner decision 2026-11-01 (rollback-sweep): a refusal after the window opened waits
# until this long after it opened, because Mail's autosave copy of a scripted reply
# landed 5 s after the open in the sitting and was only ever looked for at +45 s or
# later. One bounded wait; the Envelope Index read is not a Mail call.
SWEEP_AFTER_S = 45.0

# The Drafts read counts as "no copy" only when it follows the discard by at least this
# long. The sitting proved reads 35 s or more after the discard (discards at 1.9 to
# 10 s, reads at +45 s); a read right after a late discard is the case it never tested.
SWEEP_GAP_S = 30.0

# The longest span from the baseline read (just before the `reply` verb) to the moment
# the window went (the discard, or the send, answered) in which a Drafts row may still
# be claimed: the open's own timeout. A longer span means Mail stalled, and the
# owner's own hand draft could have landed in it (facts 4e `Refusal cleanup` (3)).
CLAIM_SPAN_S = ORIGINAL_TIMEOUT


def _wait_until(deadline: float) -> None:
    time.sleep(max(0.0, deadline - time.monotonic()))


class _ReplyFlow:
    """What one native reply has created, and how to take it away (THE DISCARD RULE).

    By the outgoing id when the flow knows it; when it does not (the open itself failed
    or timed out), the id-free discard against the baseline taken before the open. Only
    a ``dead`` answer (the -1728 proof) lets the refusal say nothing was created."""

    def __init__(
        self,
        message_id: str,
        mailbox_args: tuple[str, str],
        text: str,
        baseline: str,
        index_top: int | None,
        attribution: str | None,
        tail: str | None,
        tool: str = "mail_reply",
        original_id: int = 0,
    ):
        self.tool = tool  # the tool whose errors these are
        self.message_id, self.mailbox_args = message_id, mailbox_args
        # Mail's internal id of the original (the reply is opened by it)
        self.original_id = original_id
        self.text, self.baseline = text, baseline
        # the highest message row before the window opened (None: index unreadable),
        # Mail's attribution line and the last words of the original (None: a reply
        # without a quote)
        self.index_top, self.attribution, self.tail = index_top, attribution, tail
        # the highest message row right after the window went (the discard, or the
        # send, answered): a Drafts row above it landed after the window was gone, so it
        # is not proven the window's own
        self.landed_by: int | None = None
        self.outgoing_id: int | None = None
        self.sender = ""  # the reply's From, read while the reply exists
        # the signature Mail put into this reply, read while it exists: compared by the
        # Drafts sweep, never reported
        self.signature = ""
        # the baseline read was just taken: no reply window exists yet
        self.started_at = time.monotonic()
        self.opened_at: float | None = None
        self.discarded_at: float | None = None
        self.stage = "open"
        self._discarded: str | None = None

    def discard(self) -> str:
        """Run the discard once; later calls return the first answer. Never raises:
        a failing discard script is an ``unknown`` answer, reported loudly."""
        if self._discarded is None:
            try:
                if self.outgoing_id is not None:
                    raw = runtime.run_osascript(
                        _DISCARD_OUTGOING,
                        str(self.outgoing_id),
                        timeout=ORIGINAL_TIMEOUT,
                    )
                else:
                    raw = runtime.run_osascript(
                        _DISCARD_NEW_REPLY,
                        self.baseline,
                        self.message_id,
                        *self.mailbox_args,
                        timeout=ORIGINAL_TIMEOUT,
                    )
                answer = raw.strip()
            except Exception:  # noqa: BLE001 - reported as unproven, never raised
                answer = "unknown"
            self._discarded = answer
            self.window_gone()
        return self._discarded

    def window_gone(self) -> None:
        """The window is gone (the discard answered, or the send did): note when, and
        the index top right then. Never raises; an unreadable top proves nothing."""
        self.discarded_at = time.monotonic()
        try:
            self.landed_by = mail_reply_cleanup.index_top()
        except Exception:  # noqa: BLE001 - None: nothing can be proven the window's
            self.landed_by = None

    def _may_claim(self, url: str) -> bool:
        """The flow's own conditions for deleting the one row ``find_own_draft`` proved
        (the selector cannot know them). Cheapest first; any doubt is False."""
        return (
            self.discarded_at is not None
            and self.discarded_at - self.started_at <= CLAIM_SPAN_S
            and self._sent_from(url)
            and self._baseline_clear()
        )

    def _sent_from(self, url: str) -> bool:
        """The row sits in the account whose email addresses hold the reply's From
        address: one account, read once (a claim is made once per call, so there is
        nothing to cache). An unreadable From, an unknown or shared address, or a failed
        read is False: a family account's Drafts is never a candidate."""
        addr = _bare_address(self.sender).lower()
        account = mailbox_url.account(url)
        if not addr or not account:
            return False
        try:
            raw = runtime.run_osascript(_ACCOUNT_ADDRESSES, timeout=ORIGINAL_TIMEOUT)
        except Exception:  # noqa: BLE001 - nothing proven
            return False
        owners = []
        for record in raw.split(RS):
            uuid, *held = record.split(US)
            if addr in {a.strip().lower() for a in held}:
                owners.append(uuid.strip().casefold())
        return owners == [account.casefold()]

    def _baseline_clear(self) -> bool:
        """No scripted compose window that was open at the start can autosave a reply
        to THIS original (``_BASELINE_CLEAR``: its subject does not end with the
        original's). Nothing open at the start is clear without a read."""
        if not self.baseline:
            return True
        try:
            raw = runtime.run_osascript(
                _BASELINE_CLEAR,
                self.baseline,
                str(self.original_id),
                *self.mailbox_args,
                timeout=ORIGINAL_TIMEOUT,
            )
        except Exception:  # noqa: BLE001 - nothing proven
            return False
        return raw.strip() == "clear"

    def sweep(self, *, sent: bool = False) -> str:
        """The Drafts sweep (rollback-sweep): ``removed`` (the call's own autosave copy
        was found and deleted), ``none`` (no copy 45 s after the window opened),
        ``late`` (no copy, but the discard ended too close to the read to rule out one
        that has not landed), ``unproven`` (a copy is there that cannot be proven the
        call's own, the delete was not confirmed, or the read failed) or
        ``unavailable`` (the index cannot be read). Every new message row is read, in
        any mailbox. A copy is deleted only when ``_may_claim`` holds (facts 4e
        `Refusal cleanup` (2), (3)): the window went within ``CLAIM_SPAN_S`` of the
        baseline read, the row sits in the account the reply is SENT FROM, and no
        other scripted compose window for this original was open at the start
        (``baseline``). ``sent``: the reply was sent, so its own Sent copies are set
        aside (``find_own_draft``)."""
        if self.index_top is None:
            return "unavailable"
        _wait_until((self.opened_at or time.monotonic()) + SWEEP_AFTER_S)
        read_at = time.monotonic()  # no later than the index snapshot of the read
        try:
            found = mail_reply_cleanup.find_own_draft(
                self.index_top,
                bare_id(self.message_id),
                self.text,
                self.attribution,
                tail=self.tail,
                landed_by=self.landed_by,
                **({"sent_twins": True} if sent else {}),
                **({"signature": self.signature} if self.signature else {}),
            )
        except NativeError:
            return "unavailable"
        except Exception:  # noqa: BLE001 - a malformed draft must not hide the refusal
            return "unproven"
        if found.kind == "none":
            discarded = self.discarded_at
            late = discarded is None or read_at - discarded < SWEEP_GAP_S
            return "late" if late else "none"
        if found.kind != "one" or not self._may_claim(found.url):
            return "unproven"
        try:
            answer = runtime.run_osascript(
                _SWEEP_DELETE,
                bare_id(found.mid),
                *mail_addressing.mailbox_args(found.url),
                timeout=ORIGINAL_TIMEOUT,
            )
        except Exception:  # noqa: BLE001 - reported as unproven, never raised
            return "unproven"
        return "removed" if answer.strip() == "deleted" else "unproven"

    def refusal(self, cause: Exception) -> ComposeRefused:
        """The error for a failure after the flow started: discard, sweep, then word
        it. "Nothing was created" is said only when the discard answered ``dead`` AND
        the sweep left no Drafts copy behind."""
        discarded = self.discard()
        swept = self.sweep()
        if isinstance(cause, ComposeRefused):
            said = str(cause)
        elif isinstance(cause, NativeError):  # agent-directed text, no reply text in it
            said = f"{self.stage}: {cause}"
        else:  # never echo a foreign exception's text: it could carry the reply text
            said = f"{self.stage}: {type(cause).__name__}"
        if discarded == "dead" and swept in ("none", "removed"):
            looked = (
                "a Drafts copy that Mail autosaved was found and deleted"
                if swept == "removed"
                else "no Drafts copy was there 45 s after the window opened"
            )
            end = (
                f" The reply was discarded and {looked}: nothing was created and "
                "nothing was sent."
            )
        elif discarded == "dead" and swept == "late":
            end = _STILL_LAND
        elif discarded == "dead":
            end = _DRAFTS_LEFT
        elif swept == "removed":
            end = _DELETED_WINDOW_LEFT
        else:
            end = _LEFT_OVER
        return ComposeRefused(f"{self.tool} did not complete ({said}).{end}")

    def after_send(self) -> dict:
        """The sweep after a SENT reply (owner decision 2026-11-01): the autosave copy
        survives a send (facts 4e `Send after insert`), so wait until 45 s after the
        window opened and sweep as a refusal does. Nothing here can fail the send or
        delete anything but the one Drafts row it proved: the result rides beside
        ``sent`` as ``drafts_copy`` plus a plain-language note."""
        self.window_gone()
        try:
            outcome = self.sweep(sent=True)
        except Exception:  # noqa: BLE001 - the send happened; the sweep never raises
            outcome = "unproven"
        return {"drafts_copy": outcome, "drafts_copy_note": _SENT_COPY[outcome]}


def open_reply_with_text(
    message_id: str,
    mailbox_args: tuple[str, str],
    text: str,
    *,
    reply_all: bool,
    replace_all: bool = False,
    send: bool = False,
    report: dict | None = None,
) -> int:
    """Open Mail's native reply to ``message_id`` and put ``text`` on top of it; return
    the reply's outgoing message id. Shared by ``reply`` and ``reply_all``.

    The whole flow runs in ONE ``run_native`` closure, so no other native call
    interleaves. Accessibility is checked before any Mail call. Every failure after the
    flow started applies THE DISCARD RULE (``_ReplyFlow``), then raises
    ``ComposeRefused``; the reply text never reaches a script, an argv or a file.
    ``replace_all`` is the no-quote reply: the whole body is replaced by ``text``.

    ``send`` (``reply_all``): after the insert is CONFIRMED, send the reply by its
    outgoing message id, outside every rollback (facts 3: ``delete`` after ``send`` is a
    silent no-op). A failing send is re-raised as it is, with the wording that the reply
    may have been sent, and is never followed by a discard or a sweep. After a send that
    answered, the flow waits until 45 s after the window opened and sweeps its own
    Drafts copy (``_ReplyFlow.after_send``); the outcome goes into ``report``
    (``drafts_copy``, ``drafts_copy_note``) and can never fail the call.
    """
    tool = "reply_all" if reply_all else "mail_reply"

    def work() -> int:
        if not runtime.accessibility_trusted():
            raise AccessibilityDenied(
                f"{tool} needs Accessibility for macos-apps-mcp, to put your text "
                "above Mail's own quote, and it is off. Tell the user to switch it on "
                f"in {ACCESSIBILITY_PANE}. Nothing was created and nothing was sent. "
                "Do not retry until the next user message."
            )
        # the one O(mailbox) scan runs here, before the sweep's baseline
        tail, attribution, original_id = _quote_facts(
            message_id, mailbox_args, tool, quote=not replace_all
        )
        baseline = runtime.run_osascript(_OUTGOING_IDS, timeout=ORIGINAL_TIMEOUT)
        flow = _ReplyFlow(
            message_id,
            mailbox_args,
            text,
            baseline.strip(),
            mail_reply_cleanup.index_top(),
            attribution,
            tail,
            tool,
            original_id,
        )
        try:
            try:
                raw = runtime.run_osascript(
                    _REPLY_OPEN,
                    str(original_id),
                    *mailbox_args,
                    "1" if reply_all else "0",
                    message_id,
                    timeout=ORIGINAL_TIMEOUT,
                )
            finally:
                # the window may have opened at any time before the call returned or
                # failed: this is the latest it can have been (the sweep waits from it)
                flow.opened_at = time.monotonic()
            outgoing_id, window_id, flow.sender, flow.signature = _parse_open(raw)
            flow.outgoing_id, flow.stage = outgoing_id, "insert"
            runtime.compose_insert(
                window_id,
                text,
                replace_all=replace_all,
                quote_tail=tail,
                rollback=flow.discard,
                tool=tool,
            )
        except Exception as exc:
            raise flow.refusal(exc) from exc
        if send:
            _send_reply(outgoing_id)
            result = flow.after_send()
            if report is not None:
                report.update(result)
        return outgoing_id

    return work() if runtime.on_worker() else runtime.run_native(work)


def _send_reply(outgoing_id: int) -> None:
    """Send the confirmed reply. Outside every rollback and every discard: a failure
    here (a timeout included) may mean Mail accepted the send, so it is re-raised with
    the warning that a retry could send twice, and nothing is deleted."""
    try:
        runtime.run_osascript(
            _SEND_OUTGOING, str(outgoing_id), timeout=ORIGINAL_TIMEOUT
        )
    except NativeError as exc:
        raise type(exc)(f"{exc}{_SEND_UNSURE}") from exc
    except Exception as exc:  # never echo a foreign text: it could carry the reply
        raise NativeError(f"send: {type(exc).__name__}{_SEND_UNSURE}") from exc


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
        # D-09/D-10: resolve Mail's own spelling (or refuse) BEFORE any native write.
        # This only runs here — deliver() calls dispatch() only when dry_run=False —
        # so a dry run never reaches the ownership read and never constructs anything.
        spelling = owned_sender(sender) if sender else ""
        with runtime.body_file(text) as path:
            runtime.run_osascript(
                _SEND,
                subj,
                path,
                "1" if html else "0",
                spelling,
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
    "to"/"cc"/"sender"/"replyto"/"subject"/"self". Malformed/partial trailing records
    are skipped — same defensive rule as every other parser here."""
    to: list[str] = []
    cc: list[str] = []
    mine: list[str] = []
    sender = ""
    replyto = ""
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
        elif kind == "replyto":
            replyto = value
        elif kind == "subject":
            subject = value
        elif kind == "self":
            mine.append(value)
    return {
        "to": to,
        "cc": cc,
        "sender": sender,
        "replyto": replyto,
        "subject": subject,
        "self": mine,
    }


def _reply_recipients(seen: dict) -> tuple[list[str], list[str], str | None]:
    """The reply's OWN ``(to, cc, warning)``, by Mail's reply-all rule (#516): ``to`` is
    the original's Reply-To addresses, else its sender; ``cc`` is the original's to + cc
    minus every address of the holding account and minus ``to``. Addresses compare
    lower-cased by their bare form and the first occurrence wins; the lists keep the
    spelling the original carried. A self-sent original keeps its sender in ``to``
    (facts 5f). When the account's addresses could not be read nothing is subtracted —
    show more, never less — and the warning says so."""
    to: list[str] = []
    for part in seen["replyto"].split(","):
        addr = _bare_address(part)
        if "@" in addr and addr.lower() not in {a.lower() for a in to}:
            to.append(addr)
    if not to:
        addr = _bare_address(seen["sender"])
        if "@" in addr:
            to.append(addr)
    if not to:
        raise ValueError(
            "the original has no sender or Reply-To address to reply to; "
            "nothing was built"
        )
    skip = {_bare_address(a).lower() for a in seen["self"]} | {a.lower() for a in to}
    cc: list[str] = []
    for raw in seen["to"] + seen["cc"]:
        addr = _bare_address(raw)
        if addr and addr.lower() not in skip:
            skip.add(addr.lower())
            cc.append(addr)
    warning = None
    if not seen["self"]:
        warning = (
            "The addresses of the account that holds the original could not be read, "
            "so none were removed from cc: it may list this account's own address."
        )
    return to, cc, warning


def reply_all_to(
    message_id: str, mailbox: str, body: str, include_quote: bool = True
) -> Outgoing:
    """A reply-all. Its preview READS the original — rule 2 at the module docstring, and
    the reason ``dry_run`` defaults to True on this tool at all — and reports the
    reply's own ``to`` (the sender, or its Reply-To) and ``cc`` (everyone else on the
    original minus this account's addresses), the set Mail's reply-all reaches (#516).
    ``from`` is a label: Mail answers from the account that holds the original.

    The send (``dry_run=False``) is Mail's own reply-all with the text put on top of its
    quote through Accessibility (``open_reply_with_text(..., send=True)``): nothing is
    written to ``content``, no plain quote is built, and the message goes out only after
    the insert is confirmed."""
    mid = bare_id(message_id)
    if not mid:
        raise ValueError("reply_all needs the original message's id")
    if not body.strip():
        raise ValueError("reply_all needs a non-empty body")
    mb = mail_addressing.mailbox_args(mailbox)
    seen = _parse_reply_all_recipients(
        runtime.run_osascript(_REPLY_ALL_RECIPIENTS, mid, *mb, timeout=ORIGINAL_TIMEOUT)
    )
    to, cc, warning = _reply_recipients(seen)
    note = (
        "to and cc are computed from the original by Mail's reply-all rule; "
        "Mail's own reply-all decides who receives the message."
    )

    def dispatch() -> dict:
        # Mail's own reply-all, the text put on top through Accessibility, sent only
        # after the insert is confirmed (FIX-16, #348; facts 4e). `include_quote=False`
        # replaces the whole body (gap-no-quote: gui-replace), never `set content`.
        report: dict = {}
        open_reply_with_text(
            mid,
            mb,
            body,
            reply_all=True,
            replace_all=not include_quote,
            send=True,
            report=report,
        )
        return report

    return Outgoing(
        action="reply_all",
        to=to,
        cc=cc,
        sender=REPLY_SENDER,
        subject=seen["subject"],
        body=body,
        source=message_id.strip(),
        recipients_note=f"{note} {warning}" if warning else note,
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
        runtime.run_osascript(
            _FORWARD, mid, US.join(to_list), *mb, timeout=ORIGINAL_TIMEOUT
        )

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
