"""Mail adapter — Mail.app via osascript (Automation TCC): inbox search, body-by-id, a
draft-and-open write, and a gated outbound send path.

Mail has a rich AppleScript dictionary. ``Pointer.id`` is the RFC822 ``message id``
(stable across relaunch — the citation contract), NOT the AppleScript object ``id`` (a
session-local integer that rots across relaunch, so never a durable citation). Actions
resolve a message BY that RFC id. ``deeplink`` is a ``message://`` URL built from the
same RFC id. Search matches subject OR sender over the inbox; ``mail_body`` hydrates one
message's plaintext by id (hygiene-budgeted). ``create_draft``/``mail_reply`` open a
draft for HUMAN review and never send on their own. ``send``/``reply_all``/``forward``
DO send — but only when the operator opts in via ``MACOS_APPS_ALLOW_SEND`` (unset by
default, so absent unless explicitly enabled) and ``dry_run`` still defaults to True
even then (the surveyed-consensus safe shape: a wrong-recipient/address-leak send is
the ecosystem's most dangerous mail tool, so it's gated + previewed, not eliminated).
``sent: True`` from any of them means Mail ACCEPTED the message, NOT that it was
delivered — device-verified: an accepted send can sit in Mail's Outbox undelivered for
minutes, so every send/reply_all/forward result also reports ``outbox_pending`` (Mail's
outbox count) and a ``note`` when it's non-zero.
Mail also autosaves EVERY outgoing message this module builds into the Drafts mailbox
~10-15s after creation (#133) — asynchronously, unsuppressably, and whether the message
was sent, rolled back, or abandoned. So a successful send leaves a stray Drafts copy;
``drafts()`` + ``delete_draft()`` are the only recovery, and a dry run (which constructs
nothing) is the only way to leave nothing.
Mail's AppleScript is slow on large mailboxes, so reads are capped and the osascript
timeout bounds a pathological search. User input goes via argv / a tempfile — not
interpolated.

Three modules, one adapter (#155). ``mail_index`` is the read-at-rest sqlite plane,
``mail_addressing`` is the ONE home for "which message/mailbox/account does this token
mean?" — the two id forms, the mailbox resolvers plus their AppleScript handler, the
account map, and ``resolve(id, folder=None, account=None) -> ResolvedMessage``, which
answers with exactly one target or raises. This file keeps the AppleScript, the
parsing, and the policy. A new mail capability adds a script + a method HERE and calls
``mail_addressing`` to name its target: #159's recoverable destructive plane and #78's
``move_mail`` both need the exactly-one-target rule, and they inherit it instead of
building an eleventh copy of the addressing concept (there were ten before this).

Every bounded read answers ``contracts.read_result`` — ``{results, truncated?, plane?,
coverage?}`` (#156) — so "the call succeeded" and "the answer is complete" stop being
the same statement.
"""

from __future__ import annotations

import email
import re
from urllib.parse import unquote

from ..contracts import Pointer, deletion_result, read_result
from ..errors import NativeError
from ..runtime import body_file, log, run_osascript
from ..text import (
    READ_BODY,
    RS,
    STRIP_FRAMING,
    US,
    Field,
    addr_list,
    blank_if_missing,
    bool_or_none,
    bool_strict,
    clean_body,
    clean_summary,
    int_or_none,
    int_or_zero,
    parse_framed,
    sanitize_line,
    split_framed,
)
from . import mail_addressing, mail_index
from .mail_addressing import bare_id, stored_id
from .mail_index import _deeplink  # re-export: tests + Pointer builders use it here

MAX_MAILS = 25
MAX_THREAD = 100  # largest thread seen on a real Mac is 154 rows (~144 distinct)
NEEDS_SCAN = 100  # inbox messages scanned newest-first for needs-response
SENT_SCAN = 100  # recent sent messages scanned for awaiting-reply candidates
REFS_SCAN = 150  # inbox reply-headers scanned in the correlation window

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
# orphaned osascript can't pin Mail. US/RS-framed; subject and sender pass through the
# shared STRIP_FRAMING handler — on the old tab wire an unstripped tab in a subject
# shifted the sender into the subject slot.
_SEARCH = (
    STRIP_FRAMING
    + """

on run argv
  set q to item 1 of argv
  set maxN to (item 2 of argv) as integer
  set us to character id 31
  set rs to character id 30
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
        set out to out & (my stripFraming(mid)) & us & ¬
          (my stripFraming(subject of m)) & us & (my stripFraming(sender of m)) & rs
      end if
    end repeat
  end tell
  end timeout
  return out
end run"""
)


# mail_body: hydrate ONE message's plaintext by its RFC822 message-id (the citation from
# a read), in the mailbox the citation came from. NOT inbox-scoped (#146): the original
# rationale — "the inbox is the same source the reads cite" — was true at #62 and was
# falsified by #70/#75, which widened search to every mailbox and every account, so the
# guard started rejecting ids this project's own search had just produced. The scope is
# now whatever mailbox the caller names, and an id absent THERE still raises loudly (the
# guard's real intent). id and mailbox via argv (no injection).
_BODY = (
    mail_addressing.MAILBOX_REF
    + """

on run argv
  set mid to item 1 of argv
  set mb to my mailboxFor(item 2 of argv, item 3 of argv)
  with timeout of 120 seconds
  tell application "Mail"
    set matches to (messages of mb whose message id is mid)
    if (count of matches) is 0 then error ¬
      "no message with that message id in " & (item 3 of argv)
    set c to content of (item 1 of matches)
    if c is missing value then error "message body is not available locally"
    return c
  end tell
  end timeout
end run"""
)

# AppleScript coerces an unset property to this literal string on stdout; guard the body
# path against it exactly as the id paths do (#61/#62 review) — never hand back a
# "missing value" body as if it were the email's contents.
_MISSING_VALUE = "missing value"

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
# CRITICAL: only ever call this BEFORE handing the message to `send`. Once Mail has
# accepted a message, `delete` is a silent NO-OP: device-verified 2026-07-26, both
# `delete <ref>` and `delete outgoing message i` returned cleanly on a sent message and
# removed nothing, and the message went on to deliver normally. So a post-send rollback
# cannot succeed — it can only report a cleanup that did not happen. That is why `send`
# sits OUTSIDE the rollback `try` in every script here: past that verb the honest move
# is to report the leftover, never to pretend it was removed.
#
# The two leftover warnings live here as AppleScript handlers rather than as Python
# constants interpolated into the scripts: `_SEND` contains `{visible:false}`, so an
# f-string would need brace escaping, and the no-interpolation rule is easier to keep
# when nothing is interpolated at all. Appended to the ORIGINAL error when rollback()
# could not prove the partial message is gone — the caller gets the real failure plus
# the leftover fact and its recovery (the in-memory outbox zombie clears when Mail is
# quit and reopened; device-verified).
_ROLLBACK = """on rollback(msg)
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

# create_draft: draft-and-open, NEVER send. `make new outgoing message … visible:true`
# opens a compose window for the HUMAN to review/send; there is deliberately no `send`
# verb here (the two-tier safe gate — joshrutkowski/orchard/patrickfreyer). The body is
# READ from a tempfile via the shared readBody handler (never interpolated into the
# script — the supermemoryai pattern), so a long/multiline/unicode/EMPTY body can't
# break, inject, or crash (-39 on a zero-byte file, #READ_BODY) the script. to/subject/
# tempfile-path all arrive via argv. Atomic (#44), with a HARD LIMIT (#133): everything
# after `make new outgoing message` is wrapped in a try and the partial outgoing message
# is rolled back before re-raising — but that does NOT stop a duplicate appearing in
# Drafts. Device-verified 2026-07-26: Mail autosaves ANY outgoing message to the Drafts
# mailbox ~10-15 seconds after creation, asynchronously, and nothing cancels it. The
# rollback removes the outgoing-message OBJECT (proven, -1728) and the autosave still
# lands afterwards. Five suppression attempts all failed — one-shot `with properties`,
# post-creation writes, visible:true, visible:false, and `close … saving no`. So a
# failed create_draft CAN leave a stray draft; `drafts()` + `delete_draft()` are the
# recovery, and the #44 comment must not be read as promising otherwise.
_CREATE_DRAFT = (
    READ_BODY
    + "\n\n"
    + _ROLLBACK
    + """

on run argv
  set recipientAddr to item 1 of argv
  set subj to item 2 of argv
  set bodyText to my readBody(item 3 of argv)
  with timeout of 120 seconds
  tell application "Mail"
    set msg to make new outgoing message with properties {visible:true}
    try
      set subject of msg to subj
      set content of msg to bodyText
      tell msg to make new to recipient with properties {address:recipientAddr}
      activate
    on error errMsg
      if my rollback(msg) then
        error errMsg
      else
        error errMsg & my draftLeftover()
      end if
    end try
  end tell
  end timeout
end run"""
)

# drafts (#82): list the Drafts mailbox as US/RS-framed (message id, subject, first
# recipient) records. Iterates BY INDEX rather than with a `whose` filter — on device,
# `messages of drafts mailbox whose subject is X` raised -1728 for a draft that
# demonstrably existed, while index access is reliable (spike 2026-07-25). Output is
# capped host-side at maxN, the _SEARCH idiom (#52). The first recipient is enough for a
# pointer summary; a draft's own sender is the user, so it carries no signal.
_DRAFTS = (
    STRIP_FRAMING
    + """

on run argv
  set maxN to (item 1 of argv) as integer
  set us to character id 31
  set rs to character id 30
  set out to ""
  set c to 0
  with timeout of 120 seconds
  tell application "Mail"
    set dm to drafts mailbox
    set n to count of (messages of dm)
    repeat with i from 1 to n
      set m to message i of dm
      set mid to message id of m
      if mid is not missing value and mid is not "" then
        set c to c + 1
        if c > maxN then exit repeat
        set subj to subject of m
        if subj is missing value then set subj to ""
        set rcpt to ""
        try
          set rcpt to (address of item 1 of (to recipients of m)) as text
        end try
        set out to out & (my stripFraming(mid)) & us & (my stripFraming(subj)) & ¬
          us & (my stripFraming(rcpt)) & rs
      end if
    end repeat
  end tell
  end timeout
  return out
end run"""
)

# delete_draft (#82): resolve one draft by RFC822 message-id and delete it. Iterates
# IN REVERSE BY INDEX: deleting while iterating a forward collection invalidates the
# reference (-1728, device-verified), and a `whose` equality filter is unreliable on the
# Drafts mailbox. Returns immediately after the delete, so at most one is removed.
_DELETE_DRAFT = """on run argv
  set mid to item 1 of argv
  with timeout of 120 seconds
  tell application "Mail"
    set dm to drafts mailbox
    set n to count of (messages of dm)
    repeat with i from n to 1 by -1
      set m to message i of dm
      set thisId to message id of m
      if thisId is not missing value and (thisId as text) is mid then
        delete m
        return "deleted"
      end if
    end repeat
    error "no draft with that message id"
  end tell
  end timeout
end run"""

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
    + _ROLLBACK
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
    + _ROLLBACK
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
# original unchanged and carries no note. Recipients arrive US-joined in one argv item.
_FORWARD = (
    _ROLLBACK
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
# Called after every send script runs (send/reply_all/forward), never before — this
# reports the WHOLE queue, not specifically the message this call just sent: once the
# native verb consumes our outgoing message there is no stable id left to re-identify it
# by, so we cannot scope the count to just ours. A non-zero count therefore only means
# "something is queued", not "our message is queued" — but that's still the actionable
# signal: delivery is NOT confirmed and Mail's Outbox needs a look. Do not invent
# subject-matching or other heuristics to attribute the count to one message.
_OUTBOX_COUNT = """on run argv
  with timeout of 120 seconds
  tell application "Mail"
    return (count of (messages of outbox)) as text
  end tell
  end timeout
end run"""


def _outbox_pending() -> int:
    """Run _OUTBOX_COUNT and parse the result. The script always returns a plain
    integer coerced `as text`, so a parse failure means something is structurally
    wrong — let it raise rather than silently reporting 0 (which would itself be the
    dishonest-success failure this whole feature exists to prevent)."""
    return int(run_osascript(_OUTBOX_COUNT).strip())


def _with_outbox_pending(result: dict) -> dict:
    """Merge the outbox truth into a send/reply_all/forward result dict. When Mail's
    outbox is non-empty, add a `note` a model can relay to the human verbatim — the
    caller must not treat `sent: True` alone as delivery confirmation.

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


# reply_all dry-run preview (#129): resolve an inbox message's to/cc recipients — the
# set reply-all would ACTUALLY reach — plus its sender, by message-id. Reply-all is
# exactly the tool whose recipient set is surprising (a long cc list), and the whole
# justification for dry_run defaulting to True is that a wrong recipient becomes
# visible before anything leaves; a preview that echoes back only what the caller typed
# is decorative. Device-verified 2026-07-26: `to recipients`, `cc recipients`, and
# `sender` are all readable on a stored inbox message. Scoped to inbox (the same source
# _BODY/_ORIGINAL read from); errors when the id has no match, matching that pair. One
# RS-framed record per recipient — (kind, address), kind in to/cc — plus a final
# (sender, address) record: the _DRAFTS/_ATTACHMENTS idiom, so a variable-length to/cc
# list parses with split_framed instead of a fixed-arity US-partition. Every free-text
# field (address, sender) passes through the shared stripFraming handler first.
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
  end tell
  end timeout
  return out
end run"""
)

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

# reply builds a real reply via Mail's NATIVE reply verb (Mail owns In-Reply-To/
# References threading — the only mechanism that threads; make-new-outgoing can't set
# headers, spike 2026-07-11). The body (reply text + our quote) is set on the returned
# outgoing message — keystroke-free (#46; no .eml). A window opens for the HUMAN to
# review/send. NEVER sends. Atomic (#44): roll back the draft on any post-creation
# failure — subject to #133's limit, i.e. Mail's async autosave can still leave a stray
# Drafts copy. body via tempfile through the shared readBody handler, never a bare
# `read` (an empty reply_body would otherwise crash -39, #READ_BODY); id via argv.
_REPLY = (
    READ_BODY
    + "\n\n"
    + _ROLLBACK
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
    set r to reply (item 1 of matches) opening window yes
    try
      set content of r to bodyText
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


def _build_quote(sender: str, date_str: str, original_body: str) -> str:
    """Standard reply quote: `On <date>, <sender> wrote:` then the original body, each
    line `> `-prefixed. Bounded via clean_body (hard=None: always truncate, never raise
    — the quote is supplementary text, not the primary deliverable, so a huge original
    must not abort the whole reply)."""
    bounded = clean_body(original_body, hard=None)
    quoted = "\n".join("> " + line for line in bounded.splitlines())
    return f"On {date_str}, {sender} wrote:\n{quoted}"


# list_attachments (#45): attachments of messages in a mailbox matching a subject query.
# Mailbox addressing goes through the shared mailboxFor resolver, so this reaches ANY
# mailbox (#146) — #45 shipped it with the five special names only, which left a filed
# message's attachments as unreachable as its body. A special name still resolves
# through Mail's UNIFIED, cross-account, locale-independent accessors (verified
# on-device: `drafts mailbox`->"All Drafts", `sent mailbox`->"All Sent", `trash
# mailbox`->"All Trash", `junk mailbox`->"All Junk", `inbox`->unified inbox), so that
# case still can't pick the wrong (often empty) same-named mailbox on a multi-account
# Mac; a url names its account outright, so neither can that one. An empty query lists
# ALL messages in the mailbox (bounded by maxN) rather than none — `contains ""` is
# false, so that case is branched explicitly. A non-empty `mid` (#155/#81) addresses ONE
# message by RFC822 message-id instead, the same `whose message id is` predicate _BODY
# uses; it wins over `q` because an id already names exactly one message. Caveat from
# the facts doc: `whose` is unreliable on the Drafts mailbox — but an unsaved draft has
# no message-id to pass in the first place, so the id branch is not the Drafts path (an
# empty `mid` + empty `q` still lists the whole mailbox, which is).
# Fields framed per the US/RS contract:
# per record = subject, then (name, size, downloaded) TRIPLES per attachment; the
# subject and each attachment name pass through the shared STRIP_FRAMING handler
# before being joined, so a message that happens to contain those control chars can't
# desync the parser. Output capped at maxN records. with timeout (#56). All inputs via
# argv (no interpolation).
_ATTACHMENTS = (
    STRIP_FRAMING
    + "\n\n"
    + mail_addressing.MAILBOX_REF
    + """

on run argv
  set q to item 1 of argv
  set maxN to (item 2 of argv) as integer
  set mb to my mailboxFor(item 3 of argv, item 4 of argv)
  set mid to item 5 of argv
  set us to character id 31
  set rs to character id 30
  set out to ""
  set c to 0
  with timeout of 120 seconds
  tell application "Mail"
    if mid is not "" then
      set msgs to (messages of mb whose message id is mid)
    else if q is "" then
      set msgs to messages of mb
    else
      set msgs to (messages of mb whose subject contains q)
    end if
    repeat with m in msgs
      set c to c + 1
      if c > maxN then exit repeat
      -- #155: the id first, so an attachment row is addressable. A draft that Mail has
      -- not autosaved yet has no message id and raises here — that is expected, not an
      -- error: it degrades to "" and the row still lists its attachments, which is the
      -- documented reason this tool works on Drafts at all.
      set mid to ""
      try
        set mid to (message id of m) as text
      end try
      set out to out & mid & us & my stripFraming(subject of m)
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
    message-id, subject, then (name, size, downloaded) triples. Malformed/partial
    trailing records are skipped.

    The id (#155) makes a row addressable — #81 (save an attachment to disk) has nothing
    to name a file by without it, and "the attachment on THIS message" used to cost a
    whole-mailbox scan. A blank id is kept, not dropped: an unsaved draft has no
    Message-ID yet, and listing its attachments is this tool's documented job. `folder`
    is filled in by the caller, which knows the mailbox it was asked about."""
    recs = parse_framed(
        raw,
        [Field("id", str.strip), Field("summary", clean_summary)],
        repeat=[
            Field("name", clean_summary, required=True),
            Field("size", int_or_none),
            Field("downloaded", bool_or_none),
        ],
        repeat_key="attachments",
    )
    for r in recs:
        r["summary"] = r["summary"] or "(no subject)"
        # Only a real id yields a deeplink: message://%3C%3E resolves to nothing, and a
        # citation that opens an empty window is worse than an absent one.
        if r["id"]:
            r["deeplink"] = _deeplink(r["id"])
    return recs


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


def _summary(subject: str, sender: str) -> str:
    subject, sender = subject.strip(), sender.strip()
    if subject and sender:
        return f"{subject} — {sender}"
    return subject or sender or "(no subject)"


def _classify_needs_response(records: list[dict], my_addrs: set[str]) -> list[Pointer]:
    """Rank inbound messages that likely need the user's response. Drops already-replied
    messages; keeps those directly addressed to the user (my_addrs ∩ to_addrs). If
    my_addrs is empty (extraction failed) it degrades to FLAGGED-ONLY rather than
    flooding the inbox. Reasons (stable): flagged > unread-direct > unanswered-direct;
    recency (smallest secs_ago) breaks ties within a tier. Bounded to MAX_MAILS.

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
    return [p for _, _, p in out[:MAX_MAILS]]


def _norm_mid(mid: str) -> str:
    """A Message-ID as a COMPARISON key: the bare id, lowercased. Not a third id form
    (``mail_addressing`` owns the only two) — nothing is ever addressed with this, it
    only answers "are these two the same message?" across headers that disagree on
    case."""
    return bare_id(mid).lower()


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
    return [p for _, p in out[:MAX_MAILS]]


def _parse_search_results(raw: str) -> list[Pointer]:
    """Parse the _SEARCH payload: US/RS-framed (message id, subject, sender) records.
    Records with no stable message-id are skipped — a message without a Message-ID
    header has no resolvable citation ("missing value"/"" on the wire). #61 review.

    ``folder="inbox"`` (#155): this script scans the inbox and nothing else, so the
    round-trip token is knowable without asking. Before this, an id from the fallback
    path — or from ``mail()`` — could not be handed to ``mail_body``, whose docstring
    promises the folder comes "from the SAME search result"."""
    recs = parse_framed(
        raw,
        [
            Field("id", str.strip, required=True),
            Field("subject", blank_if_missing),
            Field("sender", blank_if_missing),
        ],
        min_fields=1,
    )
    return [
        Pointer(
            id=r["id"],
            summary=clean_summary(_summary(r["subject"], r["sender"])),
            deeplink=_deeplink(r["id"]),
            folder="inbox",
        )
        for r in recs
    ]


def _parse_draft_records(raw: str) -> list[Pointer]:
    """Parse the _DRAFTS payload: US-framed (message id, subject, first recipient)
    records. Records with no stable message-id are skipped — same rule as the inbox
    reads (#61): never emit a non-resolvable id.

    ``folder="drafts"`` (#155) — the canonical name, so a draft pointer round-trips
    into ``mail_attachments`` (confirming an attachment landed) without guessing."""
    recs = parse_framed(
        raw,
        [
            Field("id", str.strip, required=True),
            Field("subject"),
            Field("rcpt", str.strip),
        ],
        min_fields=1,
    )
    return [
        Pointer(
            id=r["id"],
            summary=clean_summary(
                _summary(r["subject"], f"to {r['rcpt']}" if r["rcpt"] else "")
            ),
            deeplink=_deeplink(r["id"]),
            folder="drafts",
        )
        for r in recs
    ]


def _parse_reply_all_recipients(raw: str) -> dict:
    """Parse the _REPLY_ALL_RECIPIENTS payload: RS-framed (kind, address) records,
    kind in "to"/"cc"/"sender". Malformed/partial trailing records are skipped —
    same defensive rule as every other parser here."""
    to: list[str] = []
    cc: list[str] = []
    sender = ""
    for fields in split_framed(raw):
        if len(fields) < 2:
            continue
        kind, value = fields[0], fields[1]
        if kind == "to":
            to.append(value)
        elif kind == "cc":
            cc.append(value)
        elif kind == "sender":
            sender = value
    return {"to": to, "cc": cc, "sender": sender}


def _split_addrs(value) -> list[str]:
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


class MailAdapter:
    def get_pointers(self, query: str) -> list[Pointer]:
        """query: a substring to match against the inbox subject OR sender (#61).

        The ``PointerSource`` contract, so it stays a bare list — every adapter
        implements this one shape. ``inbox_search`` is the tool-facing wrapper that
        adds #156's bound signal."""
        q = query.strip()
        if not q:
            raise ValueError("mail read needs a search substring (got an empty query)")
        # maxN is enforced host-side; the slice is a cheap backstop on the result.
        return _parse_search_results(run_osascript(_SEARCH, q, str(MAX_MAILS)))[
            :MAX_MAILS
        ]

    def inbox_search(self, query: str) -> dict:
        """``get_pointers`` in the bounded-read envelope (#156) — the legacy `mail`
        tool's read. Separate from ``get_pointers`` only because that name is the
        cross-adapter ``PointerSource`` Protocol and must keep its list shape."""
        return read_result(self.get_pointers(query), cap=MAX_MAILS)

    def get_body(self, message_id: str, mailbox: str = "") -> str:
        """Plaintext body of one message by its RFC822 message-id, budgeted (#52):
        control-stripped, truncated with a marker past BODY_MAX, and OutputOverflow past
        the hard cap (a pasted dump → open it in Mail). Accepts a bracketed or bare id.

        ``mailbox`` is OPTIONAL (#155). Given, it is the ``folder`` value from the
        search result that produced the id, passed back VERBATIM — the cheapest path,
        Automation only, no index read. Omitted, the id resolves ON ITS OWN through
        ``mail_addressing.resolve`` (the Envelope Index, so Full Disk Access), which is
        what lets a vault note that stored only the citation — the correct
        pointers-not-payload thing to store — still reach the message after #78's
        ``move_mail`` invalidated whatever folder token it once had. An id absent from
        an explicitly named mailbox still raises."""
        target = mail_addressing.resolve(message_id, folder=mailbox or None)
        mid = target.id
        body = run_osascript(_BODY, mid, *target.mailbox_args)
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
        Atomic (#44): if any step after creation fails, the script rolls the partial
        draft back before erroring. That rollback is verified but NOT sufficient (#133):
        Mail autosaves any outgoing message to Drafts ~10-15s after creation,
        asynchronously and unsuppressably, so a failed create can still leave a stray
        draft. List it with `drafts()` and remove it with `delete_draft()`. Returns a
        locator
        (#43): a freshly opened compose window has no stable Message-ID YET (Mail
        stamps one once the draft is saved to the Drafts mailbox), so we return where
        to find it rather than guessing an id — once saved, `drafts()`/`delete_draft()`
        address it by that stable id. The body is written to a 0600 tempfile and read
        by the script as «class utf8» (never interpolated); to/subject go via argv.
        The tempfile is deleted after the (synchronous) script has read its content
        into the draft."""
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
            "it in Drafts, where it gets a stable message-id — see drafts()/"
            "delete_draft().",
        }

    def _draft_pointers(self) -> list[Pointer]:
        """The Drafts read as bare Pointers — what ``snapshot`` needs. ``list_drafts``
        is the same read in the bounded-read envelope."""
        return _parse_draft_records(run_osascript(_DRAFTS, str(MAX_MAILS)))

    def list_drafts(self) -> dict:
        """List the Drafts mailbox as pointers (id + "subject — to recipient"). A read
        — never mutates. Bounded to MAX_MAILS (#156: `truncated` says when that bound
        bit). Unlike the inbox reads this is NOT scoped to one account: `drafts mailbox`
        is Mail's unified, locale-independent accessor."""
        return read_result(self._draft_pointers(), cap=MAX_MAILS)

    def snapshot(self, ident: str) -> Pointer | None:
        """Current Pointer for one draft, or None if the id no longer resolves — the
        before-state an id-addressed write needs for the audit trail (#67). Satisfies
        the Snapshotter Protocol. Compares bracket-normalized (`_norm_mid`, M1 review):
        accepts a bracketed or bare ``ident`` against a bracketed or bare stored id."""
        mid = _norm_mid(ident)
        for p in self._draft_pointers():
            if _norm_mid(p.id) == mid:
                return p
        return None

    def delete_draft(self, ident: str, dry_run: bool = False) -> dict:
        """Delete one draft by its RFC822 message-id (from `list_drafts`). Accepts a
        bracketed or bare id — brackets are stripped like every other id-taking mail
        method (`get_body`/`reply`/`reply_all`/`forward`, M1 review), so a caller
        passing `<id>` resolves instead of failing loudly. ``dry_run=True`` resolves
        the target and returns the preview envelope, no mutation. Answers with the
        shared ``deletion_result`` shape (C5d — the real delete used to say
        ``{"deleted": True, "id": mid}``, the one odd envelope out). Raises if the id
        resolves to no draft, so a stale id fails loudly instead of silently deleting
        nothing."""
        mid = bare_id(ident)
        if not mid:
            raise ValueError(
                "delete_draft needs a draft id (the message-id from drafts)"
            )
        if dry_run:
            found = self.snapshot(mid)
            if found is None:
                raise ValueError(f"no draft with message id {mid!r}")
            return deletion_result(mid, found)
        run_osascript(_DELETE_DRAFT, mid)
        return deletion_result(mid, None)

    def send(
        self,
        to,
        subject: str = "",
        body: str = "",
        cc=None,
        bcc=None,
        html: bool = False,
        from_address: str | None = None,
        dry_run: bool = True,
    ) -> dict:
        """Send a NEW mail — the one path here that leaves this machine.

        ``dry_run=True`` (the default, deliberately inverted from the id-addressed
        deletes) returns the resolved envelope and makes NO call into Mail: a send
        CONSTRUCTS its recipient, so a wrong recipient is the failure that matters,
        and a dry run must not strand an autosaved draft in the user's mailbox.

        ``from_address`` sets the sending account. Omitted, Mail picks its default —
        which is NOT predictable from account order (device-verified), so the preview
        reports "(Mail default account)" rather than a guess. Addresses accept a
        comma-separated string or a list; ``html=True`` sends the body as HTML.

        A successful return (``sent: True``) means Mail ACCEPTED the message — NOT
        that it was delivered (device-verified: an accepted send can sit undelivered
        in Mail's Outbox for minutes). Check ``outbox_pending``: non-zero means
        something is still queued and delivery is not confirmed.
        """
        to_list = _split_addrs(to)
        if not to_list:
            raise ValueError("send_mail needs at least one recipient address (to)")
        if not (subject or "").strip() and not (body or "").strip():
            raise ValueError("send_mail needs a subject or a body (both were empty)")
        cc_list, bcc_list = _split_addrs(cc), _split_addrs(bcc)
        sender = (from_address or "").strip()
        envelope = {
            "to": to_list,
            "cc": cc_list,
            "bcc": bcc_list,
            "from": sender or "(Mail default account)",
            "subject": subject or "",
        }
        if dry_run:
            return {
                "dry_run": True,
                "would_send": {
                    **envelope,
                    "body_chars": len(body or ""),
                    "html": bool(html),
                },
            }
        with body_file(body or "") as path:
            run_osascript(
                _SEND,
                subject or "",
                path,
                "1" if html else "0",
                sender,
                US.join(to_list),
                US.join(cc_list),
                US.join(bcc_list),
            )
        return _with_outbox_pending({"sent": True, **envelope})

    def reply_all(
        self,
        message_id: str,
        mailbox: str,
        body: str,
        include_quote: bool = True,
        dry_run: bool = True,
    ) -> dict:
        """Reply-all to a message and SEND it. Mail's native reply verb sets the
        threading headers; ``include_quote`` appends the `On <date>, <sender> wrote:`
        block, built in Python exactly as ``reply`` builds it. The sending account is
        inherited from the original message — the correct identity for a thread.

        ``dry_run=True`` (default) is a deliberate, DOCUMENTED exception to this
        file's "a dry run makes no native call" rule (``send``/``forward`` still make
        none at all): reply-all's recipient set is exactly the surprising one (a long
        cc list), so the preview reads the original message's ACTUAL to/cc recipients
        by message-id and reports them — not merely what the caller typed — before
        anything leaves. That read is safe where a send/forward dry run isn't, because
        the no-native-call rule exists to stop CONSTRUCTING an outgoing message (which
        can strand an autosaved draft in Drafts); reading an already-stored message
        strands nothing.

        ``mailbox`` is required (#146): the ``folder`` value from the search result that
        produced ``message_id``, verbatim.

        A successful return (``sent: True``) means Mail ACCEPTED the reply — NOT
        that it was delivered (device-verified: an accepted send can sit undelivered
        in Mail's Outbox for minutes). Check ``outbox_pending``: non-zero means
        something is still queued and delivery is not confirmed.
        """
        mid = bare_id(message_id)
        if not mid:
            raise ValueError("reply_all needs the original message's id")
        if not body.strip():
            raise ValueError("reply_all needs a non-empty body")
        mb = mail_addressing.mailbox_args(mailbox)
        if dry_run:
            recipients = _parse_reply_all_recipients(
                run_osascript(_REPLY_ALL_RECIPIENTS, mid, *mb)
            )
            return {
                "dry_run": True,
                "would_send": {
                    "to": recipients["to"],
                    "cc": recipients["cc"],
                    "reply_to": message_id.strip(),
                    "reply_all": True,
                    "body_chars": len(body),
                    "include_quote": include_quote,
                },
            }
        full = body
        if include_quote:
            raw = run_osascript(_ORIGINAL, mid, *mb)
            if raw.strip() and raw.strip() != _MISSING_VALUE:
                sender, _, rest = raw.partition(US)
                date_str, _, original = rest.partition(US)
                full = (
                    body
                    + "\n\n"
                    + _build_quote(
                        sanitize_line(sender), sanitize_line(date_str), original
                    )
                )
        with body_file(full) as path:
            run_osascript(_REPLY_ALL, mid, path, *mb)
        return _with_outbox_pending(
            {"sent": True, "reply_to": message_id.strip(), "reply_all": True}
        )

    def forward(self, message_id: str, mailbox: str, to, dry_run: bool = True) -> dict:
        """Forward a message and SEND it. The original message and its
        attachments are forwarded UNCHANGED — there is no way to attach a covering
        note. Device-verified: `content` of a forwarded message is permanently
        unreadable via AppleScript (Mail assembles the quoted original only at send
        time, never exposing it to scripting), so writing `content` to prepend a note
        was actually just replacing the whole body with the note. Worse, writing
        `content` at all — even once — destroys the attachments (a real 7-attachment
        forward was delivered with 0 once `content` was touched; untouched, all 7
        arrived intact with the full original body). So this method carries no
        covering-note parameter; use ``send`` for a fresh message with your own text.
        ``dry_run=True`` (default) makes no call into Mail. It still VALIDATES
        ``mailbox`` — that is pure string work, and a preview that accepts a token the
        real send would reject is the kind of preview that teaches nothing.

        ``mailbox`` is required (#146): the ``folder`` value from the search result that
        produced ``message_id``, verbatim.

        A successful return (``sent: True``) means Mail ACCEPTED the forward — NOT
        that it was delivered (device-verified: an accepted send can sit undelivered
        in Mail's Outbox for minutes). Check ``outbox_pending``: non-zero means
        something is still queued and delivery is not confirmed."""
        mid = bare_id(message_id)
        if not mid:
            raise ValueError("forward needs the original message's id")
        to_list = _split_addrs(to)
        if not to_list:
            raise ValueError("forward needs at least one recipient address (to)")
        mb = mail_addressing.mailbox_args(mailbox)
        if dry_run:
            return {
                "dry_run": True,
                "would_send": {"to": to_list, "forwarding": message_id.strip()},
            }
        run_osascript(_FORWARD, mid, US.join(to_list), *mb)
        return _with_outbox_pending(
            {"sent": True, "to": to_list, "forwarding": message_id.strip()}
        )

    def reply(
        self,
        message_id: str,
        mailbox: str,
        reply_body: str,
        include_quote: bool = True,
    ) -> dict:
        """Reply to a message by its RFC822 message-id: opens a threaded draft
        for the human to review/send — NEVER sends. Uses Mail's native reply verb so
        In-Reply-To/References are set by Mail (real Gmail/Outlook threading).
        include_quote appends `On <date>, <sender> wrote:` + the `> `-quoted original.
        Keystroke-free (#46); atomic (#44). Returns the same locator dict as
        create_draft — save it to Drafts and it gets a stable message-id, addressable
        via drafts()/delete_draft().

        ``mailbox`` is required (#146): the ``folder`` value from the search result that
        produced ``message_id``, verbatim. It scopes BOTH native calls — the quote read
        and the draft build — so a filed original can't reply with an empty quote."""
        mid = bare_id(message_id)
        if not mid:
            raise ValueError("reply needs the original message's id")
        if not reply_body.strip():
            raise ValueError("reply needs a non-empty reply_body")
        mb = mail_addressing.mailbox_args(mailbox)
        body = reply_body
        if include_quote:
            raw = run_osascript(_ORIGINAL, mid, *mb)
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
            run_osascript(_REPLY, mid, path, *mb)
        return {
            "created": True,
            "subject": "(reply)",
            "mailbox": "Drafts",
            "note": "reply draft opened for review; save it to keep it in Drafts, "
            "where it gets a stable message-id (see drafts())",
        }

    def list_attachments(
        self, mailbox: str = "", query: str = "", message_id: str = ""
    ) -> dict:
        """List attachments of messages in `mailbox` whose subject contains `query`, or
        of the ONE message `message_id` names.

        `mailbox` is a search result's `folder` value passed back verbatim, or one of
        the canonical inbox/sent/drafts/trash/junk (#146 — #45 shipped those five
        only, so a filed message's attachments were as unreachable as its body). Works
        for Drafts (no message-id needed); a special name resolves through Mail's
        unified, cross-account accessors (`drafts mailbox`/`sent mailbox`/`trash
        mailbox`/`junk mailbox`/`inbox`), which are locale-independent, and a url names
        its own account. query is optional: an empty/omitted query lists ALL
        messages in the mailbox (bounded by MAX_MAILS) — this deliberately differs from
        `get_pointers`, which rejects an empty query.

        `message_id` (#155/#81) addresses ONE message instead of scanning: with no
        `mailbox` it resolves through ``mail_addressing.resolve``, so an id alone
        reaches its attachments. Scanning a whole mailbox to find one message was never
        a real option here — the scan stops at MAX_MAILS records, so the message a
        caller actually meant is usually past the cap. `query` is ignored when it is
        set: the id already names exactly one message.

        Returns the bounded-read envelope over records
        [{id, deeplink, folder, summary, attachments: [{name, size, downloaded}]}].
        A read — never mutates."""
        if not mailbox and not message_id:
            raise ValueError(
                "mail_attachments needs a mailbox (the `folder` value from a read) "
                "or a message_id"
            )
        if message_id:
            target = mail_addressing.resolve(message_id, folder=mailbox or None)
            folder, mb, mid = target.folder, target.mailbox_args, target.id
        else:
            folder, mb, mid = mailbox, mail_addressing.mailbox_args(mailbox), ""
        raw = run_osascript(_ATTACHMENTS, query.strip(), str(MAX_MAILS), *mb, mid)
        recs = _parse_attachments(raw)[:MAX_MAILS]
        # #155: hand back the mailbox this actually read, VERBATIM. It is already the
        # round-trip token every id-taking tool wants, and echoing it means a row from
        # here is complete on its own — id + deeplink + folder — instead of only being
        # usable by a caller who still remembers what it asked for.
        for r in recs:
            r["folder"] = folder
        # An id names one message, so the cap cannot have hidden anything.
        return read_result(recs, cap=None if mid else MAX_MAILS)

    def get_needs_response(self) -> dict:
        """Inbox messages that likely need the user's response, ranked with a reason
        (flagged / unread-direct / unanswered-direct). Heuristic over headers/
        properties — no body scan; direct-addressed + not-yet-replied. Bounded to
        MAX_MAILS, and #156's `truncated` says when that bound bit."""
        records = _parse_triage_records(run_osascript(_INBOX_TRIAGE, str(NEEDS_SCAN)))
        my = _parse_my_addrs(run_osascript(_MY_ADDRESSES))
        return read_result(_classify_needs_response(records, my), cap=MAX_MAILS)

    def get_awaiting_reply(self, days: int = 3) -> dict:
        """Sent messages older than `days` with no reply, ranked oldest-first (reason
        'awaiting-reply'). Real In-Reply-To/References threading. Bounded to
        MAX_MAILS."""
        if not 1 <= days <= 365:
            raise ValueError("days must be between 1 and 365")
        sent = _parse_sent_records(run_osascript(_SENT_TRIAGE, str(SENT_SCAN)))
        # The per-record age cutoff is applied in ONE place —
        # _classify_awaiting_reply. Here only the correlation window is sized:
        # scan inbox back to the oldest send; if even that is younger than the
        # cutoff, no send can qualify, so skip the inbox scan entirely.
        window = max((r["secs_ago"] for r in sent), default=0)
        if window < days * 86400:
            return read_result([])
        blobs = [
            b
            for b in run_osascript(_INBOX_REFS, str(window), str(REFS_SCAN)).split(RS)
            if b.strip()
        ]
        return read_result(
            _classify_awaiting_reply(sent, _referenced_ids(blobs), days), cap=MAX_MAILS
        )

    def search(
        self,
        *,
        subject=None,
        from_=None,
        to=None,
        mailbox=None,
        since=None,
        until=None,
        unread=None,
        flagged=None,
        has_attachments=None,
        account=None,
        body=None,
        limit=MAX_MAILS,
    ) -> dict:
        """Indexed search over ALL mailboxes via Mail's Envelope Index (read-at-rest).
        All filters optional, ANDed. Falls back to the AppleScript inbox search on
        missing FDA / schema drift. `body` matches against the best-effort FTS body
        sidecar (built by `index_bodies`); the FTS hits are intersected with the header
        query via message-ids. If the sidecar has no matches (absent, empty, or no hit
        for this query) this answers empty rather than raising — a body search is opt-in
        and its absence isn't an error condition — but it reports `coverage` so that
        empty is not read as "nothing exists" (#156 case 4).

        At least one filter is required (an unfiltered search would walk the whole
        store); "" and None are both absent for the text filters, while since/until
        are compared ``is not None`` — epoch 0 is a real filter (#70 review M3).
        This is the adapter's domain rule (C5c), not tool-layer decoration.

        Answers the bounded-read envelope (#156): `truncated` when the answer came back
        at `limit` — 25 is a hard ceiling, so "find every invoice from 2025" would
        otherwise return 25 and read as complete — and `plane` when the AppleScript
        fallback ran, since that scans the INBOX only while being shaped identically to
        a whole-store result."""
        subject, from_, to, mailbox, body, account = (
            v or None for v in (subject, from_, to, mailbox, body, account)
        )
        if (
            not any((subject, from_, to, mailbox, body, account))
            and since is None
            and until is None
            and not unread
            and not flagged
            and not has_attachments
        ):
            raise ValueError("mail_search needs at least one filter")
        # Clamp: an unbounded caller-supplied limit with body= would otherwise build an
        # oversized `message_ids IN (...)` clause (SQLite variable ceiling) and ignore
        # the promised MAX_MAILS backstop (#70 review M1). Clamped on BOTH sides —
        # SQLite reads a negative LIMIT as unlimited, so a one-sided min() let
        # limit=-1 (reachable straight from the MCP schema) return the whole store.
        limit = max(1, min(limit, MAX_MAILS))
        account = mail_addressing.resolve_account(account) if account else None

        mailbox_urls = None
        if mailbox:
            # #144: resolve the DECODED name (what mail_overview reports) to exact
            # urls. No match is a no-match read — the same 0-hit answer the old
            # substring filter gave — and it must not fall through to an
            # unfiltered query. Resolution itself raises on a missing store,
            # preserving the raise-before-anything ordering.
            mailbox_urls = mail_addressing.resolve_mailbox(mailbox, account=account)
            if not mailbox_urls:
                # #156 case 2: a NAME resolving to nothing is a typo or a wrong-account
                # guess — a followable error, not a 0-hit read that reads as "that
                # mailbox is empty". A URL is different: it was a real handle when a
                # read issued it, so one that no longer resolves went stale (#78's
                # move_mail does exactly that) and stays the honest empty answer.
                if mail_addressing.is_mailbox_url(mailbox):
                    return read_result([], cap=limit)
                raise ValueError(
                    f"no mailbox matches {mailbox!r}"
                    + (f" in account {account!r}" if account else "")
                    + " — mail_overview lists every mailbox with the exact name to "
                    "use, or pass a `folder` url from a read result verbatim. Do not "
                    "retry with a guessed name."
                )

        message_ids = None
        if body:
            # The missing-store raise must come BEFORE the FTS sidecar is consulted:
            # body= with no Envelope Index is the followable error, not a silent []
            # (the sidecar alone cannot answer a search honestly).
            mail_index._require_index_path()
            # ponytail: body= caps at `limit` FTS rows BEFORE header filters apply, so
            # a narrow header filter over many body hits can under-return; acceptable
            # for the best-effort body layer — widen limit or add ORDER BY if it bites.
            message_ids = mail_index.fts_search(
                mail_index.fts_path(), body, limit=limit
            )
            if not message_ids:
                log.info(
                    "mail_search body=%r: no FTS matches (run mail_index_bodies to "
                    "build/refresh the body index)",
                    body,
                )
                # #156 case 4: an empty body= answer is usually about the INDEX, not
                # the mailbox — most local messages are headers-only until #119 runs.
                # Say so in the payload, not just in a log the caller never sees.
                return read_result([], coverage=mail_index.body_coverage())

        # Fallback: the AppleScript inbox scan can express a subject/sender substring
        # — NOTHING else. It is offered only when no other filter is set: falling
        # back with unread=/since=/account=/… silently returned unfiltered inbox
        # hits while the caller believed the filters applied, and a to= filter
        # degraded into a SENDER match. body= is the same rule (AppleScript cannot
        # do body FTS). A search that can't reach the sqlite plane with any of those
        # filters set raises the typed remediation instead — honest failure over a
        # confidently wrong answer. since/until compare against None because 0
        # (epoch) is a real filter value.
        needle = subject or from_ or ""
        dropped = (
            bool(to)
            or bool(mailbox)
            or since is not None
            or until is not None
            or bool(unread)
            or bool(flagged)
            or bool(has_attachments)
            or bool(account)
            or bool(body)
        )
        # #156 case 3: the caller must be able to tell an inbox-only scan from a
        # whole-store one. The flag is set INSIDE the callable rather than inferred
        # afterwards because only query_search knows whether it ever reached sqlite.
        used_fallback = False

        def _run_fallback() -> list[Pointer]:
            nonlocal used_fallback
            used_fallback = True
            return self.get_pointers(needle)[:limit]

        fallback = _run_fallback if (needle and not dropped) else None
        result = mail_index.query_search(
            subject=subject,
            from_=from_,
            to=to,
            mailbox_urls=mailbox_urls,
            since=since,
            until=until,
            unread=unread,
            flagged=flagged,
            has_attachments=has_attachments,
            account=account,
            message_ids=message_ids,
            limit=limit,
            fallback=fallback,
        )
        if body:
            log.info(
                "mail_search body=%r: searched %d indexed messages",
                body,
                len(message_ids),
            )
        return read_result(
            result,
            cap=limit,
            plane="applescript-inbox" if used_fallback else None,
        )

    def thread(self, message_id: str, limit: int = MAX_THREAD) -> dict:
        """Every message in the conversation containing ``message_id``, deduped and
        oldest-first — including the ones YOU sent, which is what makes it a transcript.
        Bodies stay behind ``mail_body``: a thread is Pointers, so quoted-text
        duplication never arises. Unknown id -> empty (a no-match read, not an error);
        `truncated` marks a thread that hit `limit`, where the OLDEST were dropped.

        No AppleScript fallback: AppleScript cannot express "fetch this conversation",
        so on schema drift this raises the typed error rather than inventing a
        degraded answer built from a subject-substring match.
        """
        # Both sides: SQLite reads a negative LIMIT as unlimited, so a one-sided min()
        # let limit=-1 return every message in the store.
        limit = max(1, min(limit, MAX_THREAD))
        # The index stores Message-IDs WITH angle brackets; AppleScript's `message id`
        # reports them BARE — `stored_id` is the one sanctioned conversion. Without it
        # every id the AppleScript tools emit matched zero rows, indistinguishable from
        # a genuine miss.
        return read_result(
            mail_index.query_thread(stored_id(message_id), limit), cap=limit
        )

    def overview(self) -> list[dict]:
        """Per-mailbox {account, mailbox, total, unread}, unread-first.

        Every mailbox is listed, including Junk/Trash/All Mail — a read tool reports,
        it does not decide what deserves attention, and Spam-with-7-unread is only
        useful if you can see it IS Spam. Not Pointers: a count is not a citable
        message, so this is an enumeration read like safari_tabs / messages_chats.

        Counts are per DISTINCT message, not per row: the same message filed twice in
        one mailbox is one message.

        Counts come from sqlite alone. Account NAMES come from Mail (osascript, which
        LAUNCHES Mail if it isn't running) and are best-effort: when Mail is unreachable
        the UUID stands in and the counts are returned anyway. The On My Mac store is
        the one account Mail never names — AppleScript's `every account` lists only the
        configured mail accounts, device-verified 2026-07-27 — so its `local://` scheme
        is mapped to the literal "On My Mac" instead of showing a raw UUID. That is
        permanent for that store, not a Mail-unreachable artefact.

        `account_id` and `folder` are the machine-readable halves (#155). Every mail
        Pointer now carries the same `account` uuid and the same `folder` url, so ONE
        call here is the whole uuid → display-name map — which is what lets the other
        reads report an account without ever contacting Mail. `mailbox` stays the
        decoded human name (the one `mail_search(mailbox=…)` matches); `folder` is the
        exact url, so a mailbox chosen here round-trips into a search without going
        back through substring matching.
        """
        rows = mail_index.query_overview_rows()
        names = mail_addressing.account_map()
        out = []
        for r in rows:
            url = r["mailbox_url"]
            # <scheme>://<UUID>/<percent-encoded path> — scheme is imap:// or local://
            scheme, _, rest = url.partition("://")
            uuid = mail_index.account_of(url) or ""
            _, _, box = rest.partition("/")
            # local:// is the On My Mac store; Mail never reports it as an account, so
            # its UUID would otherwise be shown raw forever (see the docstring).
            account = (
                mail_addressing.ON_MY_MAC
                if scheme == "local"
                else names.get(uuid, uuid)
            )
            out.append(
                {
                    "account": account,
                    "account_id": uuid,
                    "mailbox": unquote(box),
                    "folder": url,
                    "total": r["total"],
                    "unread": r["unread"],
                }
            )
        return out

    def index_bodies(self, rebuild: bool = False) -> dict:
        """Opt-in build/refresh of the best-effort FTS body index over downloaded .emlx
        (read-at-rest; skips not-yet-downloaded *.partial.emlx). Resumable, size-capped.
        Returns counts + coverage. Never launches Mail, never writes in Mail's data."""
        root = mail_index.mail_root()
        if root is None:
            raise NativeError("no Mail data found; open Mail once. Do not retry.")
        res = mail_index.build_body_index(
            mail_root=root, fts_db=mail_index.fts_path(), rebuild=rebuild
        )
        res["coverage"] = (
            f"{res['indexed']}/{res['total_emlx']} downloaded .emlx indexed"
        )
        return res
