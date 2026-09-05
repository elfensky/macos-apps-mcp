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

Nine modules, one adapter. ``mail_index`` is the read-at-rest sqlite plane;
``mail_addressing`` (#155) is the ONE home for "which message/mailbox/account does this
token mean?" — the two id forms, the mailbox resolvers plus their AppleScript handler,
the account map, and ``resolve(id, folder=None, account=None) -> ResolvedMessage``,
which answers with exactly one target or raises; ``mailbox_url`` (#175) parses and
synthesises the ``<scheme>://<uuid>/<path>`` tokens that addressing trades in;
``mail_recover`` (#159) is the recoverable destructive plane — **backup → log → act**
— which owns the batch cap, the per-target action log and undo for every write that
mutates stored mail; ``mail_outgoing`` (#160) is the OUTBOUND lifecycle — envelope
build → the one ``would_send`` preview shape → construct → send → outbox truth-check —
which ``send``/``reply_all``/``forward``/``send(draft_id=…)`` are four
parametrizations of, and which states once (and enforces) the rules a dry run must
obey; ``mail_files`` (#81) is the filesystem boundary (allowlisted root, derived
names, never-overwrite); ``mail_triage`` (#178) owns the needs-response /
awaiting-reply scans and their pure classifiers; ``mail_drafts`` (#178) owns the draft
lifecycle — create/list/resolve/delete plus the threaded ``reply`` draft;
``mail_attachments`` (#178) lists and saves attachments. This file keeps the rest of
the AppleScript, the parsing, and the policy — the caps, ``search``'s plane choice,
and the recoverable writes' refusal rules.

So a new mail capability adds a script + a method HERE, calls ``mail_addressing`` to
name its target, hands anything that LEAVES THIS MACHINE to ``mail_outgoing`` rather
than re-deriving the send discipline, and — if it is destructive — hands its script to
``mail_recover.recoverable`` as the ``act`` callable rather than running it itself.
``move_mail`` (#78) is the worked example and the plane's first consumer;
``tests/test_tool_annotations.py`` fails if a new destructive mail write is neither
declared recoverable nor exempted with a reason, the same registration-guard pattern
``_send_tool`` uses.

Everything under "organize" MUTATES stored mail, and every claim it makes is VERIFIED
by re-reading rather than inferred from a verb returning cleanly — the discipline #135
forced when a bare ``delete`` reported success having removed nothing.

Every bounded read answers ``contracts.read_result`` — ``{results, truncated?, plane?,
coverage?}`` (#156) — so "the call succeeded" and "the answer is complete" stop being
the same statement.
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import replace
from datetime import datetime

from .. import runtime
from ..contracts import Pointer, read_result
from ..errors import BatchTooLarge, NativeError, OutputOverflow
from ..runtime import log
from ..text import (
    BODY_HARD_MAX,
    RS,  # noqa: F401  (re-export, #178: tests build framed fixtures off mail.RS)
    STRIP_FRAMING,
    US,
    Field,
    _summary,  # re-export (#178): tests import it here; the parsers below use it
    blank_if_missing,
    clean_body,
    clean_summary,
    parse_framed,
    sanitize_line,
    split_framed,
)
from . import (
    mail_addressing,
    mail_attachments,
    mail_drafts,
    mail_files,
    mail_ids,
    mail_index,
    mail_outgoing,
    mail_recover,
    mail_triage,
    mailbox_url,
)
from .mail_addressing import bare_id, stored_id
from .mail_index import _deeplink  # re-export: tests + Pointer builders use it here

MAX_MAILS = 25
MAX_THREAD = 100  # largest thread seen on a real Mac is 154 rows (~144 distinct)
# mail_bodies is deliberately smaller than note_bodies' 50: a mail body carries quoted
# history, signatures and disclaimers, so 50 of them is a context dump, not a read. The
# total budget (BODY_HARD_MAX) usually bites first anyway — this cap just fails fast.
MAX_BODIES = 20
_TOP_N = 10  # mail_stats top-sender/top-mailbox lists (#85): token-bounded

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

# --- organize: mailboxes, moves, status (#78/#79) ------------------------------------
# Everything below MUTATES stored mail. The destructive half (`_MOVE`) never runs on its
# own — it is the `act` callable #159's recoverable plane invokes after it has copied
# each target's bytes to disk and logged the plan. See mail_recover.

# create_mailbox (#78). Device-verified 2026-08-03, every branch:
#
# - `make new mailbox with properties {name:"a/b"}` AUTO-CREATES the missing parent —
#   both at application level (the On My Mac store) and via `at end of mailboxes of
#   <account>`. So nesting needs no per-level loop.
# - It returns `missing value`. There is nothing to read the new mailbox's address back
#   from — and the `mailbox` class has no `url` property at all (Mail.sdef) while the
#   Envelope Index will not know the mailbox exists until Mail syncs. That is why the
#   caller synthesises the address instead of asking; see MailAdapter.create_mailbox.
# - `make new mailbox at <account> …` (the bare `at acct` form) raises a coercion error
#   AND CREATES THE MAILBOX ANYWAY — a trap that leaves a folder behind while reporting
#   failure. Only the `at end of mailboxes of <account>` form is used here.
# - So the create is verified by ADDRESS: resolve the path through the shared
#   `mailboxFor` and read its name. Same discipline as every other write in this file —
#   a Mail verb that returns cleanly having done nothing is the recurring bug (#135).
_CREATE_MAILBOX = (
    mail_addressing.MAILBOX_REF
    + """

on run argv
  set acctId to item 1 of argv
  set mbName to item 2 of argv
  with timeout of 120 seconds
  tell application "Mail"
    if acctId is "local" then
      make new mailbox with properties {name:mbName}
    else
      make new mailbox at end of mailboxes of ¬
        (first account whose id is acctId) with properties {name:mbName}
    end if
  end tell
  end timeout
  set mb to my mailboxFor(acctId, mbName)
  with timeout of 120 seconds
  tell application "Mail"
    return name of mb
  end tell
  end timeout
end run"""
)

# move_mail's dry-run preview (#78). Reads STORED messages through AppleScript rather
# than sqlite ON PURPOSE: the Envelope Index lags Mail, and a preview reporting 25 ids
# present when they are not is worse than no preview at all. A read of stored messages
# strands nothing — the same justification #129's reply-all preview stands on, and the
# reason this is not a violation of "a dry run makes no native call" (that rule exists
# to stop CONSTRUCTING an outgoing message, which can strand an autosaved draft).
_PRESENT = (
    STRIP_FRAMING
    + "\n\n"
    + mail_addressing.MAILBOX_REF
    + """

on run argv
  set mb to my mailboxFor(item 1 of argv, item 2 of argv)
  set us to character id 31
  set rs to character id 30
  set AppleScript's text item delimiters to us
  set ids to text items of (item 3 of argv)
  set AppleScript's text item delimiters to ""
  set out to ""
  with timeout of 300 seconds
  tell application "Mail"
    repeat with rawId in ids
      set mid to rawId as text
      if mid is not "" then
        set outcome to "missing"
        try
          if (count of (messages of mb whose message id is mid)) > 0 then
            set outcome to "present"
          end if
        on error errMsg
          set outcome to "ERROR " & errMsg
        end try
        set out to out & mid & us & (my stripFraming(outcome)) & rs
      end if
    end repeat
  end tell
  end timeout
  return out
end run"""
)

# _MOVE (#78) — the first DESTRUCTIVE mail write, and the shape the rest of 0.9.2/0.9.3
# copies. Device-verified 2026-08-03, and two of the three answers contradict what the
# dictionary reads like:
#
# 1. `move {a, b, c} to mb` — an AppleScript LIST of specifiers — raises -1700 ("Can't
#    make {…} into type specifier") and moves NOTHING. The `list="yes"` direct parameter
#    that makes a batch look like one Apple Event is inside a COMMENTED-OUT block of
#    Mail.sdef; the live definition is a singular `type="specifier"`. `whose message id
#    is in {…}` fails the same way. So a batch is N events in ONE script, not one event
#    — which is exactly why the cap is 25 and why the timeout is raised below.
#    The failure was atomic (0 of 3 moved), so nothing half-applied.
# 2. `move <one ref> to dst` and `move (messages of src whose message id is "…") to dst`
#    both work. The `whose` form is used here so the reference is re-evaluated per
#    iteration — moving a message OUT of the source collection is the same mutation
#    class that invalidates a forward-iterated reference (-1728, facts doc §6).
# 3. A CROSS-ACCOUNT move is a true move: source 0, destination 1, stable across sync
#    (re-checked after 45s and against the Envelope Index). Mail.app's own UI *drag*
#    copies — that is where #140/#153's duplicates came from — but the `move` verb does
#    not, so there is no copy → verify → delete-source dance to perform here.
#
# It VERIFIES rather than asserting: a 0-match `whose` makes `move` a silent no-op, so
# each id is checked present-in-source first, then absent-from-source AND
# present-in-destination after. `moved: 25` is never assumed (#135). Both mailboxes and
# the US-joined id list arrive via argv; nothing is interpolated.
#
# The still-in-source branch RE-CHECKS once after a bounded 2s wait before it reports,
# and what it reports is the OBSERVATION, not an inference (#174). That branch has two
# device-verified ways to fire on a move that did nothing wrong: a self-move (a unified
# destination whose container already includes the source — a genuine no-op, facts §5e)
# and, once on 2026-08-11 under a full-suite run, a cross-account move that a re-locate
# immediately after proved was a clean TRUE move. The old text ("so this was a COPY,
# not a move") sent callers hunting for a duplicate that did not exist. Measured
# 2026-08-13 before choosing the 2s window: 17/17 cross-account moves (quiet AND under
# a read-load that tripled verb latency to ~3.7s) read source=0 in the SAME script
# statement after the verb — unlike `delete`, which measurably lags (§5c t0/t3). So
# the source side of `move` is synchronous on this device and the re-check is a cheap
# guard on the accusing path only, never a poll on the happy path. A real copy still
# reads present in both after 2s and still gets a loud ERROR.
_MOVE = (
    STRIP_FRAMING
    + "\n\n"
    + mail_addressing.MAILBOX_REF
    + """

on run argv
  set src to my mailboxFor(item 1 of argv, item 2 of argv)
  set dst to my mailboxFor(item 3 of argv, item 4 of argv)
  set us to character id 31
  set rs to character id 30
  set AppleScript's text item delimiters to us
  set ids to text items of (item 5 of argv)
  set AppleScript's text item delimiters to ""
  set out to ""
  with timeout of 600 seconds
  tell application "Mail"
    repeat with rawId in ids
      set mid to rawId as text
      if mid is not "" then
        set outcome to "unknown"
        try
          if (count of (messages of src whose message id is mid)) is 0 then
            set outcome to "not-in-source"
          else
            move (messages of src whose message id is mid) to dst
            if (count of (messages of dst whose message id is mid)) is 0 then
              set outcome to "ERROR move returned cleanly but the message is " & ¬
                "not in the destination"
            else
              set srcLeft to (count of (messages of src whose message id is mid))
              if srcLeft > 0 then
                delay 2
                set srcLeft to (count of (messages of src whose message id is mid))
              end if
              if srcLeft is 0 then
                set outcome to "ok"
              else
                set outcome to "ERROR the message reads present in BOTH " & ¬
                  "mailboxes after a 2s re-check — either the source copy " & ¬
                  "survived, or the destination resolves to the source itself " & ¬
                  "(a self-move, which changes nothing). Nothing was deleted; " & ¬
                  "re-locate the message before acting on either reading"
              end if
            end if
          end if
        on error errMsg
          set outcome to "ERROR " & errMsg
        end try
        set out to out & mid & us & (my stripFraming(outcome)) & rs
      end if
    end repeat
  end tell
  end timeout
  return out
end run"""
)

# A batch of up to MAX_MAILS moves is N Apple Events against a possibly-remote IMAP
# store, plus two verifying counts each — genuinely not a 30-second job, so this one
# script gets a raised host-side timeout (the AppleScript-level `with timeout` above is
# the second line of defense, never the first).
_MOVE_TIMEOUT = 300.0

# _TRASH (#80) — soft delete. Device-verified 2026-08-05, and the verification differs
# from _MOVE's in a way that matters:
#
# 1. `delete <message>` in an ordinary mailbox is a MOVE TO THAT ACCOUNT'S TRASH. It is
#    not an erase, and the message stays addressable in Trash afterwards. There is no
#    permanent delete to reach for: `delete` on a message already in Trash is a silent
#    no-op, `deleted status` raises -609 on write, and Mail.sdef has no erase verb
#    (facts doc §5c). Emptying Trash is a Mail.app UI act.
# 2. **`delete` is ASYNCHRONOUS on the source side.** Measured t0/t3/t10: the source
#    still counts the message immediately after the verb returns and only clears by t3,
#    while Trash is populated at once. So this must NOT copy _MOVE's "gone from source"
#    assertion — that reports a clean failure on a delete that worked. The reliable
#    signal is the DESTINATION, and it is checked as an INCREASE (before vs after), not
#    as presence: a message whose duplicate already sat in Trash would otherwise read as
#    "ok" no matter what the delete did.
# 3. The Trash mailbox is passed IN, resolved from the Envelope Index by the caller —
#    `trash mailbox of <account>` raises -1728 for every account despite Mail.sdef
#    declaring it, and the application-level unified accessor must not be used here: a
#    `move` out of it moved the mail and then crashed Mail (§5c).
_TRASH = (
    STRIP_FRAMING
    + "\n\n"
    + mail_addressing.MAILBOX_REF
    + """

on run argv
  set src to my mailboxFor(item 1 of argv, item 2 of argv)
  set tb to my mailboxFor(item 3 of argv, item 4 of argv)
  set us to character id 31
  set rs to character id 30
  set AppleScript's text item delimiters to us
  set ids to text items of (item 5 of argv)
  set AppleScript's text item delimiters to ""
  set out to ""
  with timeout of 600 seconds
  tell application "Mail"
    repeat with rawId in ids
      set mid to rawId as text
      if mid is not "" then
        set outcome to "unknown"
        try
          if (count of (messages of src whose message id is mid)) is 0 then
            set outcome to "not-in-source"
          else
            set beforeTrash to (count of (messages of tb whose message id is mid))
            delete (messages of src whose message id is mid)
            set landed to false
            repeat 12 times
              if (count of (messages of tb whose message id is mid)) > beforeTrash then
                set landed to true
                exit repeat
              end if
              delay 0.5
            end repeat
            if landed then
              set outcome to "ok"
            else if (count of (messages of src whose message id is mid)) is 0 then
              set outcome to "ok"
            else
              set outcome to "ERROR delete returned cleanly but the message is " & ¬
                "still in the source and never reached Trash"
            end if
          end if
        on error errMsg
          set outcome to "ERROR " & errMsg
        end try
        set out to out & mid & us & (my stripFraming(outcome)) & rs
      end if
    end repeat
  end tell
  end timeout
  return out
end run"""
)

# Same reasoning as _MOVE_TIMEOUT: N Apple Events against a possibly-remote IMAP store,
# two verifying counts each, not a 30-second job.
_TRASH_TIMEOUT = 300.0

# Dedupe gets its own, longer ceiling. Measured 2026-08-05 against a real IMAP account:
# the deletes are SERVER-bound, not CPU-bound (Mail idles at ~3% while they run), and a
# 25-set batch can be several copies per set. 300s is right for `trash_mail`, which runs
# on the daemon's single serialized worker where a long hold starves every other tool —
# but the dedupe CLI is its OWN process, so nothing is starved by waiting, and a batch
# cut short by the host timeout is strictly worse: the plan record is written, the
# deletes are half-applied, and the receipt never gets its outcome record.
_DEDUPE_TIMEOUT = 900.0

# _DEDUPE (#140) — collapse N same-mailbox copies of one Message-ID down to 1.
#
# It cannot be spelled as "delete the losers", because AppleScript has no way to name
# one of them. sqlite identifies a specific row by `messages.ROWID`; Mail's scripting
# layer only understands `messages of mb whose message id is X`, which matches ALL the
# copies at once — so `delete` on that collection (what `_TRASH` does, correctly, for a
# single-copy target) would take the survivor with them. There is no ROWID in the
# dictionary and no other per-copy handle.
#
# So the winner is not CHOSEN here, it is what is LEFT: the collection is captured once,
# then items n..2 are deleted in REVERSE index order (the §6 rule — forward iteration
# invalidates the reference with -1728) and item 1 survives. That is why the caller
# refuses to run unless every copy in the set is byte-identical on size AND date_sent:
# with identical bytes the survivor's identity is immaterial, which is exactly what
# makes an unaddressable winner acceptable. #140's "keep the lowest ROWID" is a sqlite
# statement; it has no AppleScript spelling, and acting through sqlite is forbidden.
#
# Verification is a SECOND PASS over the whole batch, not a check after each delete, and
# it asserts the thing actually wanted: **exactly one copy survives in the source**. Two
# reasons, both measured 2026-08-05:
#
# - `delete` is asynchronous on BOTH sides (§5c), so an immediate per-message check
#   reports a false failure on a delete that worked — and a false failure is not
#   cosmetic, it drops the message from the receipt's undo plan. Waiting per message
#   instead made a 25-set batch take minutes, because nearly every message spent the
#   full ceiling; by the second pass the earlier deletes have long since settled and the
#   common case waits not at all.
# - "one survivor" catches OVER-deletion (0 left) as well as under-deletion, which the
#   Trash-growth count this replaced could not distinguish.
_DEDUPE = (
    STRIP_FRAMING
    + "\n\n"
    + mail_addressing.MAILBOX_REF
    + """

on run argv
  set src to my mailboxFor(item 1 of argv, item 2 of argv)
  set tb to my mailboxFor(item 3 of argv, item 4 of argv)
  set us to character id 31
  set rs to character id 30
  set AppleScript's text item delimiters to us
  set ids to text items of (item 5 of argv)
  set AppleScript's text item delimiters to ""
  set out to ""
  set acted to {}
  with timeout of 600 seconds
  tell application "Mail"
    -- FIRST PASS: delete. Verification is a SECOND pass below, deliberately — `delete`
    -- is asynchronous on both sides (§5c), so checking each message right after its own
    -- delete either reports a false failure or burns a per-message wait.
    repeat with rawId in ids
      set mid to rawId as text
      if mid is not "" then
        set outcome to "unknown"
        set wanted to 0
        try
          set matches to (messages of src whose message id is mid)
          set n to (count of matches)
          if n < 2 then
            set outcome to "not-duplicated"
          else
            set wanted to n - 1
            repeat with i from n to 2 by -1
              delete (item i of matches)
            end repeat
          end if
        on error errMsg
          set outcome to "ERROR " & errMsg
        end try
        set acted to acted & {{mid, outcome, wanted}}
      end if
    end repeat
    -- SECOND PASS: verify only now. Every delete above has had the whole rest of the
    -- batch to settle, so the common case needs no wait at all — where a per-message
    -- wait inside the first loop spent its full ceiling on nearly every message and
    -- made a 25-set batch take minutes.
    repeat with rec in acted
      set mid to item 1 of rec
      set outcome to item 2 of rec
      set wanted to item 3 of rec
      if outcome is "unknown" then
        try
          set survivors to (count of (messages of src whose message id is mid))
          if survivors is 1 then
            set outcome to "ok " & wanted
          else
            set landed to false
            repeat 12 times
              if (count of (messages of src whose message id is mid)) is 1 then
                set landed to true
                exit repeat
              end if
              delay 0.5
            end repeat
            if landed then
              set outcome to "ok " & wanted
            else
              set outcome to "ERROR expected 1 copy to survive but " & ¬
                (count of (messages of src whose message id is mid)) & " remain"
            end if
          end if
        on error errMsg
          set outcome to "ERROR " & errMsg
        end try
      end if
      set out to out & mid & us & (my stripFraming(outcome)) & rs
    end repeat
  end tell
  end timeout
  return out
end run"""
)

# update_mail_status (#79): read/unread and flag/unflag+colour on stored messages.
# Purely reversible and destroys nothing, so it does NOT ride #159's recoverable plane —
# there is no byte to preserve and no undo to synthesize; re-issuing the tool with the
# opposite value IS the undo. It still verifies, for the same reason everything here
# does. "" means "leave this property alone" — the tri-state has to survive argv, which
# carries only text.
# `flag index` (Mail.sdef: integer, read/write) is the colour; `flagged status` is the
# on/off. Setting a colour implies flagged, or the index would be set on a message that
# shows no flag at all.
_SET_STATUS = (
    STRIP_FRAMING
    + "\n\n"
    + mail_addressing.MAILBOX_REF
    + """

on run argv
  set mb to my mailboxFor(item 1 of argv, item 2 of argv)
  set wantRead to item 3 of argv
  set wantFlag to item 4 of argv
  set wantColor to item 5 of argv
  set us to character id 31
  set rs to character id 30
  set AppleScript's text item delimiters to us
  set ids to text items of (item 6 of argv)
  set AppleScript's text item delimiters to ""
  set out to ""
  with timeout of 300 seconds
  tell application "Mail"
    repeat with rawId in ids
      set mid to rawId as text
      if mid is not "" then
        set outcome to "unknown"
        try
          set matches to (messages of mb whose message id is mid)
          if (count of matches) is 0 then
            set outcome to "not-found"
          else
            set m to item 1 of matches
            if wantRead is not "" then set read status of m to (wantRead is "1")
            if wantFlag is not "" then set flagged status of m to (wantFlag is "1")
            if wantColor is not "" then
              set flagged status of m to true
              set flag index of m to (wantColor as integer)
            end if
            set outcome to "ok"
            if wantRead is not "" and (read status of m) is not (wantRead is "1") then ¬
              set outcome to "ERROR read status did not persist"
            if wantFlag is not "" and ¬
              (flagged status of m) is not (wantFlag is "1") then ¬
              set outcome to "ERROR flagged status did not persist"
          end if
        on error errMsg
          set outcome to "ERROR " & errMsg
        end try
        set out to out & mid & us & (my stripFraming(outcome)) & rs
      end if
    end repeat
  end tell
  end timeout
  return out
end run"""
)


def _tri(value: bool | None) -> str:
    """A tri-state boolean as the scripts read it off argv: ``""`` leaves the property
    alone, ``"1"``/``"0"`` set it. argv carries only text, so the absent case needs a
    spelling of its own — ``"0"`` would silently mark everything unread."""
    return "" if value is None else ("1" if value else "0")


def _parse_statuses(raw: str) -> dict[str, str]:
    """Parse the ``id US status RS`` payload every per-target script here emits into
    ``{id: status}``. Malformed/partial trailing records are skipped — the same
    defensive rule as every other parser in this file. Ids are compared in the bare
    form the scripts echo back, which is the form they were sent in."""
    out: dict[str, str] = {}
    for fields in split_framed(raw):
        if len(fields) < 2:
            continue
        out[bare_id(fields[0])] = fields[1].strip()
    return out


def _split_ids(value) -> list[str]:
    """Normalize an ids argument to bare Message-IDs. Accepts a comma-separated string
    (what a model usually produces) or a list; blanks are dropped, duplicates collapse
    (acting on the same message twice would double-count the receipt).

    Every entry goes through ``sanitize_line`` for the reason ``_split_addrs``
    documents: callers US-join the result and the scripts re-split on US, so an id
    carrying a literal U+001F would be ONE target in the preview and TWO on the wire.
    """
    if value is None:
        return []
    items = value if isinstance(value, list) else str(value).split(",")
    out: list[str] = []
    for a in items:
        mid = bare_id(sanitize_line(a))
        if mid and mid not in out:
            out.append(mid)
    return out


# Mail's `flag index` values, in Mail's own menu order. Exposed as NAMES because an
# integer flag colour is exactly the kind of magic number a caller gets wrong silently;
# an unknown name raises instead.
FLAG_COLORS = {
    "red": 0,
    "orange": 1,
    "yellow": 2,
    "green": 3,
    "blue": 4,
    "purple": 5,
    "grey": 6,
    "gray": 6,
}


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
        return _parse_search_results(runtime.run_osascript(_SEARCH, q, str(MAX_MAILS)))[
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
        body = runtime.run_osascript(_BODY, mid, *target.mailbox_args)
        # defense in depth: the _BODY script already errors on a missing-value content,
        # but a Mail version that returns the coerced literal instead of erroring must
        # not surface it as the body (#62 review).
        if body.strip() == _MISSING_VALUE:
            raise NativeError(
                "the message body is not available locally (HTML-only, or not yet "
                "downloaded) — open it in Mail to view it. Do not retry."
            )
        return clean_body(body)

    def get_bodies(self, ids: list[str]) -> dict:
        """Plaintext bodies for up to ``MAX_BODIES`` message-ids in ONE call (#158).

        Reads ``.emlx`` AT REST (``mail_index.body_texts``) — one walk of the store for
        the whole batch, no Mail launch, no osascript, and no FTS sidecar. That is the
        actual fix the issue was after: the old cost was N osascript round-trips, and
        batching them would only have hidden it.

        ``{"results": [{"id", "body"}], "missing": [...]}`` — an id whose copy has no
        readable file or no text part lands in ``missing``, NEVER in ``results`` with an
        empty body. "we could not read it" and "the author wrote nothing" are different
        answers, and conflating them is how a model concludes a message was blank.

        Budgets are the same ones ``mail_body`` uses (#52): each body truncates at
        ``BODY_MAX`` with an explicit marker, and the batch TOTAL raises
        ``OutputOverflow`` past ``BODY_HARD_MAX`` rather than dumping. Per body the cap
        is soft on purpose (``hard=None``) — one pasted-dump message must truncate, not
        fail the other nineteen; it is the total that is allowed to refuse.
        """
        wanted = [i for i in dict.fromkeys(ids) if i.strip()]
        if not wanted:
            raise ValueError("mail_bodies needs at least one message id")
        if len(wanted) > MAX_BODIES:
            raise BatchTooLarge(
                f"mail_bodies takes at most {MAX_BODIES} ids at a time (got "
                f"{len(wanted)}) — read the thread's pointers first and hydrate the "
                "few that matter."
            )
        texts = self._bodies_at_rest(wanted)
        results, total = [], 0
        for i in wanted:
            text = texts.get(stored_id(i))
            if text is None:
                continue
            body = clean_body(text, hard=None)
            total += len(body)
            if total > BODY_HARD_MAX:
                raise OutputOverflow(
                    f"these bodies total more than {BODY_HARD_MAX} chars — ask for "
                    f"fewer ids ({len(results)} fit so far), or read them one at a "
                    "time with mail_body."
                )
            results.append({"id": i, "body": body})
        return {
            "results": results,
            "missing": [i for i in wanted if stored_id(i) not in texts],
        }

    def _bodies_at_rest(self, ids: list[str]) -> dict[str, str]:
        """``{stored (bracketed) id: body text}`` for the ids whose ``.emlx`` is
        readable — the shared resolution behind ``get_bodies`` and thread snippets.

        A Message-ID has SEVERAL rows (a Gmail label plus All Mail, a cross-account
        copy), so every copy's rowid is offered to the one at-rest walk and the first
        that yields text wins. Which copy answers does not matter: they are the same
        message, which is exactly what #153's body-identity gate measured (397/397).
        """
        rows = mail_index.query_message_locations([stored_id(i) for i in ids])
        if not rows:
            return {}
        texts = mail_index.body_texts([r["rowid"] for r in rows])
        out: dict[str, str] = {}
        for r in rows:
            text = texts.get(r["rowid"])
            if text and r["message_id"] not in out:
                out[r["message_id"]] = text
        return out

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
        return mail_drafts.create_draft(to, subject, body)

    def _draft_records(self) -> list[dict]:
        """The Drafts read: Pointer fields plus the discrete ``subject``/``to`` (#157).
        ``list_drafts`` is the same read in the bounded-read envelope."""
        return mail_drafts.draft_records(MAX_MAILS)

    def list_drafts(self) -> dict:
        """List the Drafts mailbox: each record is a citable Pointer (id, summary,
        deeplink, folder) PLUS discrete ``subject`` and ``to`` fields (#157), so
        reacquiring a specific draft — to send it, or to delete it — is a field
        comparison rather than substring-matching the summary. A read — never mutates.
        Bounded to MAX_MAILS (#156: `truncated` says when that bound bit). Unlike the
        inbox reads this is NOT scoped to one account: `drafts mailbox` is Mail's
        unified, locale-independent accessor.

        A draft Mail has not autosaved yet (~10-15s after ``create_draft``/
        ``mail_reply``, asynchronously, unhurryable) is simply ABSENT here. Wait for
        the window; do NOT retry the create."""
        return read_result(self._draft_records(), cap=MAX_MAILS)

    def snapshot(self, ident: str) -> Pointer | None:
        """Current Pointer for one draft, or None if the id no longer resolves — the
        before-state an id-addressed write needs for the audit trail (#67). Satisfies
        the Snapshotter Protocol. Compares bracket-normalized (`_norm_mid`, M1 review):
        accepts a bracketed or bare ``ident`` against a bracketed or bare stored id."""
        return mail_drafts.snapshot(ident, MAX_MAILS)

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
        # self.snapshot passed in, not re-derived: the dry-run resolve stays a call on
        # the class (the Snapshotter Protocol / audit plane address the adapter).
        return mail_drafts.delete_draft(ident, dry_run, self.snapshot)

    def send(
        self,
        to=None,
        subject: str = "",
        body: str = "",
        cc=None,
        bcc=None,
        html: bool = False,
        from_address: str | None = None,
        draft_id: str = "",
        dry_run: bool = True,
    ) -> dict:
        """Send mail — the one path here that leaves this machine. Two mutually
        exclusive modes, and passing both RAISES rather than guessing which was meant:

        * **fresh** — ``to`` + ``subject``/``body``: compose and send now.
        * **approved draft** (#157) — ``draft_id`` alone: send a draft the human
          already reviewed, by the stable Message-ID ``drafts()`` reports. The body is
          taken from the draft's own stored bytes, so the text that was approved and
          the text that goes out are the same text. Mail cannot script-send a stored
          draft (device-verified: ``send`` on a Drafts message raises -1708), so this
          REBUILDS it — and therefore REFUSES a draft carrying attachments or one that
          is a reply/forward, because a rebuild would silently drop the attachments or
          the threading headers. Both refusals name what to use instead.

        A draft is only addressable once **Mail has autosaved it, ~10-15 seconds after
        ``create_draft``/``mail_reply`` returns** — asynchronously, and nothing can
        hurry it. ``drafts()`` resolves the id after that window. **Do NOT retry the
        create** because the draft has not appeared yet: retrying makes a second draft,
        and the first one still arrives.

        ``dry_run=True`` (the default, deliberately inverted from the id-addressed
        deletes) previews and CONSTRUCTS NOTHING in Mail: a send constructs its
        recipient, so a wrong recipient is the failure that matters, and building an
        outgoing message strands an autosaved copy in Drafts ~15s later that cannot be
        identified in advance. The ``draft_id`` preview does READ the draft it would
        send — reading a stored message strands nothing, and an id alone tells an
        approving human nothing (see ``mail_outgoing``, rule 2).

        ``from_address`` sets the sending account. Omitted, Mail picks its default —
        which is NOT predictable from account order (device-verified), so the preview
        reports "(Mail default account)" rather than a guess. Addresses accept a
        comma-separated string or a list; ``html=True`` sends the body as HTML.

        A successful return (``sent: True``) means Mail ACCEPTED the message — NOT
        that it was delivered (device-verified: an accepted send can sit undelivered
        in Mail's Outbox for minutes). Check ``outbox_pending``: non-zero means
        something is still queued and delivery is not confirmed.
        """
        if draft_id.strip():
            if to or subject or body or cc or bcc or from_address or html:
                raise ValueError(
                    "send_mail takes EITHER draft_id OR to/subject/body — not both. "
                    "A draft already carries its own recipients and text; passing "
                    "fresh content alongside it would make it ambiguous which one "
                    "gets sent, so this raises instead of guessing."
                )
            outgoing = mail_outgoing.stored_draft(draft_id)
            result = mail_outgoing.deliver(outgoing, dry_run=dry_run)
            if not dry_run:
                result["draft_removed"] = self._drop_sent_draft(outgoing.source)
            return result
        return mail_outgoing.deliver(
            mail_outgoing.new_message(
                to,
                subject=subject,
                body=body,
                cc=cc,
                bcc=bcc,
                html=html,
                from_address=from_address,
            ),
            dry_run=dry_run,
        )

    def _drop_sent_draft(self, mid: str) -> bool:
        """Remove the source draft after its content has been sent, so the approved
        copy does not sit in Drafts waiting to be sent a second time — the duplicate
        #157 exists to prevent.

        NEVER raises. The send already happened; surfacing a cleanup failure as an
        exception would report a COMPLETED send as a failed call, and a model that
        retries that "failure" sends the mail twice — the same rule that keeps
        ``with_outbox_pending`` from raising. False means "still in Drafts, remove it
        with delete_draft"."""
        try:
            runtime.run_osascript(mail_drafts._DELETE_DRAFT, mid)
        except (NativeError, OSError, ValueError):
            return False
        return True

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

        ``dry_run=True`` (default) reads the original's ACTUAL to/cc recipients and
        reports them — not merely what the caller typed — because reply-all's recipient
        set is exactly the surprising one (a long cc list). That read is safe where
        CONSTRUCTING a message is not; the rule and its rationale live once at
        ``mail_outgoing``'s module docstring (rule 2), not here.

        ``mailbox`` is required (#146): the ``folder`` value from the search result that
        produced ``message_id``, verbatim.

        A successful return (``sent: True``) means Mail ACCEPTED the reply — NOT
        that it was delivered (device-verified: an accepted send can sit undelivered
        in Mail's Outbox for minutes). Check ``outbox_pending``: non-zero means
        something is still queued and delivery is not confirmed.
        """
        return mail_outgoing.deliver(
            mail_outgoing.reply_all_to(
                message_id, mailbox, body, include_quote=include_quote
            ),
            dry_run=dry_run,
        )

    def forward(self, message_id: str, mailbox: str, to, dry_run: bool = True) -> dict:
        """Forward a message and SEND it. The original message and its attachments are
        forwarded UNCHANGED — there is no way to attach a covering note, and no
        parameter that would let you try: writing `content` on a forward destroys the
        attachments (a real 7-attachment forward delivered 0 once `content` was
        touched; untouched, all 7 arrived intact with the full original body), and
        `content` of a forward is permanently unreadable anyway, so a "prepend a note"
        was really "replace the body with the note". Use ``send`` for a fresh message
        with your own text.

        ``dry_run=True`` (default) makes no call into Mail. It still VALIDATES
        ``mailbox`` — that is pure string work, and a preview that accepts a token the
        real send would reject is the kind of preview that teaches nothing. The
        preview's ``subject`` is empty: Mail composes the "Fwd: …" subject itself at
        send time.

        ``mailbox`` is required (#146): the ``folder`` value from the search result that
        produced ``message_id``, verbatim.

        A successful return (``sent: True``) means Mail ACCEPTED the forward — NOT
        that it was delivered (device-verified: an accepted send can sit undelivered
        in Mail's Outbox for minutes). Check ``outbox_pending``: non-zero means
        something is still queued and delivery is not confirmed."""
        return mail_outgoing.deliver(
            mail_outgoing.forward_of(message_id, mailbox, to), dry_run=dry_run
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
        return mail_drafts.reply(
            message_id, mailbox, reply_body, include_quote=include_quote
        )

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
        recs = mail_attachments.records(mailbox, query, message_id, MAX_MAILS)
        # An id names one message, so the cap cannot have hidden anything.
        return read_result(recs, cap=None if message_id else MAX_MAILS)

    def save_attachment(
        self,
        message_id: str,
        dest_dir: str,
        name: str = "",
        attachment_id: str = "",
        mailbox: str = "",
    ) -> dict:
        """Write ONE attachment to disk (#81) and answer where it landed.

        Address the attachment by ``name`` (what ``mail_attachments`` shows) or, when
        several on the same message share one — four ``image00N.jpg`` is an ordinary
        real message — by its ``attachment_id``. An ambiguous name RAISES and lists the
        ids rather than picking one.

        ``dest_dir`` is a path under the allowlisted root (``~/Downloads``, moved with
        ``MACOS_APPS_FILE_ROOT``). The saved filename is DERIVED from the attachment's
        name, never concatenated: an attachment name arrives in inbound mail from
        anyone, so ``../../.ssh/authorized_keys`` reduces to ``authorized_keys`` inside
        ``dest_dir`` — see ``mail_files`` for the whole rule set. An existing file is
        never overwritten (Mail's own ``save`` verb overwrites silently; the refusal is
        in Python, before the Apple Event) and the write is size-capped.

        Device-verified 2026-08-05: saving an attachment whose message was never
        downloaded makes Mail **fetch the whole message first** — it does not fail and
        it does not write an empty file — so this can take much longer than a read, and
        its timeout is raised accordingly. An offline account cannot fetch, so a file
        that lands at 0 bytes is deleted and reported as a failure.
        """
        return mail_attachments.save_attachment(
            message_id,
            dest_dir,
            name=name,
            attachment_id=attachment_id,
            mailbox=mailbox,
        )

    # --- organize (#78/#79) ----------------------------------------------------------

    def create_mailbox(self, name: str, account: str) -> dict:
        """Create a mailbox (folder) under one account; ``name`` may contain ``/`` to
        nest. Additive — it creates a container, it never touches a message.

        ``account`` takes a display name, a UUID, or "On My Mac", through the same
        ``resolve_account`` every read speaks, so this shares ``mail_search``'s
        vocabulary. It is REQUIRED: a folder has to land somewhere specific, and
        picking an account for the caller is the auto-pick the disambiguation rule
        forbids.

        The returned ``folder`` is SYNTHESISED, not read back. Three sources could
        answer "what is this mailbox's address?" and none of them can: the ``mailbox``
        class has no url property (Mail.sdef), ``make new mailbox`` returns ``missing
        value`` (device-verified 2026-08-03), and the Envelope Index will not know the
        mailbox exists until Mail syncs. So this composes ``<scheme>://<uuid>/<name>``,
        which works IMMEDIATELY because ``mailbox_args`` DECODES a path before use — a
        plain name passes through untouched. Two accepted consequences:

        - A name containing a literal ``%`` would mis-decode, so ``%`` is REJECTED with
          a typed error. Silent corruption is the only alternative.
        - The synthesised token is not byte-identical to the one Mail eventually stores
          (Mail encodes a space as ``%20``). Both DECODE to the same mailbox, so both
          work, and ``mail_overview`` reports the canonical one after the sync. Nothing
          in this project compares mailbox tokens by string equality.

        There is deliberately no ``dry_run``: creating a folder adds nothing to undo.
        There is also no delete — device-verified 2026-08-03, ``delete <mailbox>``
        raises -10000 in every form, so removing a mailbox is a Mail.app UI action.
        """
        mb = name.strip().strip("/")
        if not mb:
            raise ValueError("create_mailbox needs a mailbox name")
        if "%" in mb:
            raise ValueError(
                f"mailbox name {name!r} contains '%', which cannot be addressed: a "
                "mailbox path is percent-DECODED before use, so a literal '%' would "
                "silently resolve to a different mailbox. Rename it without '%'."
            )
        if "//" in mb:
            raise ValueError(
                f"mailbox name {name!r} has an empty path segment — use single '/' "
                "separators to nest (e.g. 'Projects/2026')."
            )
        uuid = mail_addressing.resolve_account(account)
        # mailboxFor's "local" sentinel, not a UUID: Mail's `every account` never lists
        # the On My Mac store, so its mailboxes hang off the application itself (#146).
        local = mail_addressing.local_account_id()
        acct_arg = "local" if local and uuid == local else uuid
        scheme = "local" if acct_arg == "local" else "imap"
        leaf = runtime.run_osascript(_CREATE_MAILBOX, acct_arg, mb).strip()
        if not leaf or leaf == _MISSING_VALUE:
            raise NativeError(
                f"Mail reported no mailbox at {mb!r} after creating it — the create "
                "did not take. Check Mail for a partially created folder before "
                "retrying."
            )
        return {
            "created": True,
            "mailbox": mb,
            "account": uuid,
            "folder": mailbox_url.make(scheme, uuid, mb),
            "note": "pass `folder` back verbatim to move_mail/mail_search. Mail will "
            "report its own equivalent spelling of this token in mail_overview once "
            "the account syncs; both address the same mailbox.",
        }

    def move_mail(
        self,
        ids,
        from_mailbox: str,
        to_mailbox: str,
        dry_run: bool = True,
    ) -> dict:
        """Move messages between mailboxes — the first DESTRUCTIVE mail write, and the
        first consumer of #159's recoverable plane.

        TWO mailboxes are required, not one: #146 established that a message id alone
        does not locate a message, so the source is part of the address. Both are
        address tokens — a ``folder`` value from a read passed back VERBATIM, or one of
        the five canonical names.

        Batch-capped at 25 and ``dry_run=True`` by DEFAULT (unlike ``delete_draft``): a
        move is reversible in principle, but reversing 200 misfiled messages by hand is
        not a real remedy. ``mail_undo`` is the real one, and it exists because every
        target's source mailbox and preserved bytes are recorded before anything moves.

        Archiving is not a separate tool — it is a move into a mailbox named Archive.

        Cross-account moves are ordinary moves here. Device-verified 2026-08-03: the
        `move` verb leaves exactly ONE copy across accounts, source gone, stable after
        sync — Mail.app's own UI *drag* is what copies, and what produced the ~3.9k
        duplicates #153 cleans up. This still verifies both sides per message, so a
        server that behaved otherwise would be reported (``status`` says the message
        reads present in BOTH mailboxes), never silently duplicated.

        A canonical name as ``to_mailbox`` is a UNIFIED accessor ("All Drafts" — a
        container spanning every account, with no ``account`` of its own), and Mail
        files into the mailbox of that role belonging to the **source message's own
        account**. Census, device-verified 2026-08-11 on one throwaway draft with every
        leg reversed: from an imap source all five work and land in that account's
        concrete mailbox (Drafts→inbox/sent/junk/trash, INBOX→drafts, all
        ``succeeded: 1``). Two cases do not, and only the first is refusable here:

        - **On My Mac source** — the local store has NO inbox/sent/drafts/trash/junk, so
          there is nothing for the unified name to resolve to and all five are a
          no-op ("not in the destination", message untouched). Refused below. This is
          the same asymmetry that makes ``trash_mail`` refuse a ``local://`` message
          (#80) — one store, no system mailboxes — not a second rule.
        - **self-move** — the unified container already includes the source (e.g.
          ``imap://X/INBOX`` → ``"inbox"``). A no-op the post-verify reports as
          present-in-both (after a bounded re-check, naming self-move as one of the two
          readings — #174). Deliberately NOT refused: telling a concrete url's ROLE
          requires a per-account five-role url map, and the leaf-name shortcut that
          would avoid it ("Sent Messages"/"Deleted Messages"/"[Gmail]/Trash") is
          exactly the per-locale name table #61 deleted. Nothing moves and nothing is
          lost, and the status is loud and factual.
        """
        mids = _split_ids(ids)
        # The cap and the empty-batch refusal come from the plane, and BEFORE any
        # native call — that is the whole point of enforcing them in one place.
        mail_recover.check_batch(mids)
        src = mail_addressing.mailbox_args(from_mailbox)
        dst = mail_addressing.mailbox_args(to_mailbox)
        if src == dst:
            raise ValueError(
                "from_mailbox and to_mailbox address the same mailbox — nothing to "
                "move. Do not retry with the same pair."
            )
        # An empty account id is mailbox_args' unified-accessor marker; "local" is the
        # On My Mac sentinel. Refused HERE rather than left to the post-verify (#171):
        # the address is one the docstring offers, so it must fail at the boundary with
        # the fix in hand, not as a per-id verification failure after N Apple Events.
        if not dst[0] and src[0] == "local":
            raise ValueError(
                f"to_mailbox {to_mailbox!r} is a unified accessor, which files into "
                "the SOURCE message's own account — and the On My Mac store has no "
                "inbox/sent/drafts/trash/junk, so this move cannot land anywhere. Pass "
                "the destination's `folder` url instead (mail_overview lists them). Do "
                "not retry with a canonical name."
            )
        targets = [
            mail_recover.Target(
                id=mid,
                folder=from_mailbox,
                account=mail_index.account_of(from_mailbox),
            )
            for mid in mids
        ]
        if dry_run:
            present = _parse_statuses(
                runtime.run_osascript(_PRESENT, *src, US.join(mids))
            )
            targets = [replace(t, status=present.get(t.id, "missing")) for t in targets]
            return mail_recover.preview("move", targets, destination=to_mailbox)

        def act(located):
            return _parse_statuses(
                runtime.run_osascript(
                    _MOVE,
                    *src,
                    *dst,
                    US.join(t.id for t in located),
                    timeout=_MOVE_TIMEOUT,
                )
            )

        return mail_recover.recoverable("move", targets, act, destination=to_mailbox)

    def trash_mail(self, ids, mailbox: str, dry_run: bool = True) -> dict:
        """Move messages to Trash — soft delete (#80), on #159's recoverable plane.

        SOFT is the only delete there is. Device-verified 2026-08-05: Mail's ``delete``
        verb moves a message to its account's Trash and nothing in Mail's scripting
        dictionary erases it from there — ``delete`` on a message already in Trash is a
        silent no-op, ``deleted status`` is unwritable (-609), and there is no erase or
        expunge command. So this tool cannot destroy mail, and there is no permanent
        counterpart to gate; emptying Trash is a human act in Mail.app. See the facts
        doc §5c before trying to build one.

        Rides the plane exactly like ``move_mail``, which is the point of the plane —
        every target's bytes are copied out and its source mailbox logged BEFORE the
        first Apple Event, so ``mail_undo`` replays it as a move back OUT of Trash. The
        backup is kept even though the server copy survives a soft delete: Trash is a
        30-day-ish staging area, not a guarantee, and the receipt is what makes the
        operation reconstructible after Mail's own expiry.

        ``mailbox`` is required and is one address token for the whole batch — the same
        rule ``move_mail`` follows, and it is what makes the destination knowable: the
        account owns the Trash, so one source mailbox means one Trash mailbox and one
        replayable receipt.
        """
        mids = _split_ids(ids)
        mail_recover.check_batch(mids)
        src = mail_addressing.mailbox_args(mailbox)
        account = mail_index.account_of(mailbox)
        if account is None:
            raise ValueError(
                f"trash_mail needs a mailbox that names its account — {mailbox!r} is a "
                "unified accessor, and Mail files a deleted message in the OWNING "
                "account's Trash, which a unified name cannot identify. Pass the "
                "`folder` url from the read that produced these ids."
            )
        trash = mail_index.query_trash_url(account)
        if trash is None:
            raise NativeError(
                f"no Trash mailbox found for account {account} in Mail's index, so a "
                "soft delete could not be verified or undone. Open Mail and confirm "
                "account is set up, then retry. Do not retry unchanged."
            )
        if src == mail_addressing.mailbox_args(trash):
            raise ValueError(
                "these messages are already in Trash. Mail cannot delete them any "
                "further from a script — emptying Trash is a Mail.app action. Do not "
                "retry."
            )
        targets = [
            mail_recover.Target(id=mid, folder=mailbox, account=account) for mid in mids
        ]
        if dry_run:
            present = _parse_statuses(
                runtime.run_osascript(_PRESENT, *src, US.join(mids))
            )
            targets = [replace(t, status=present.get(t.id, "missing")) for t in targets]
            return mail_recover.preview("trash", targets, destination=trash)

        dst = mail_addressing.mailbox_args(trash)

        def act(located):
            return _parse_statuses(
                runtime.run_osascript(
                    _TRASH,
                    *src,
                    *dst,
                    US.join(t.id for t in located),
                    timeout=_TRASH_TIMEOUT,
                )
            )

        return mail_recover.recoverable("trash", targets, act, destination=trash)

    def duplicates(self, limit: int = MAX_MAILS) -> dict:
        """Where the redundant copies are (#140/#153) — READ-ONLY, sqlite only.

        Diagnoses; it cannot clean anything up. The cleanup is
        ``macos-apps-mcp dedupe-mail``, a CLI command, because the scale does not fit
        the MCP surface: ~9.9k redundant rows at roughly a tenth of a second per
        AppleScript delete against a 30-second-capped, single serialized worker is
        hours of work a human starts, not a model-mediated round trip (the #119 shape).

        Two halves, because they answer different questions: ``mailboxes`` is the
        per-mailbox table (total rows vs distinct messages), and ``worst`` names the
        individual messages doing the most damage. ``cross_account`` counts rows whose
        Message-ID also lives under a different account — reported per account and
        never ranked, since #153 settled that which account wins is a human decision.

        Header-less messages are excluded from every count: a message with no RFC822
        Message-ID keys on its own ROWID and can never be a duplicate of anything,
        which is also true operationally — AppleScript addresses a message BY
        Message-ID, so a row without one cannot be targeted at all.
        """
        mailboxes = mail_index.query_duplicate_summary()
        worst = mail_index.query_duplicate_offenders(limit)
        for row in worst:
            row["subject"] = clean_summary(row.get("subject") or "") or "(no subject)"
            row["id"] = bare_id(str(row.get("message_id") or ""))
            row.pop("message_id", None)
        redundant = sum(r["redundant"] for r in mailboxes)
        out = {
            "redundant": redundant,
            "mailboxes": mailboxes,
            "worst": worst,
            "cross_account": mail_index.query_cross_account_summary(),
            "note": (
                f"{redundant} redundant same-mailbox rows. This tool only reports — "
                "run `macos-apps-mcp dedupe-mail` in a terminal to clean up (it "
                "previews by "
                "default; --execute acts). Counts come from Mail's index at rest and "
                "may lag Mail by a few minutes."
            ),
        }
        staleness = mail_index.take_staleness_note()
        if staleness:
            out["staleness"] = staleness
        return out

    def presence(self, ids, mailbox: str) -> dict:
        """``{message_id: "present" | "missing" | "ERROR …"}`` for one mailbox (#153).

        A read, through AppleScript rather than sqlite for the reason ``_PRESENT``
        already states: the Envelope Index lags Mail, and this is used to prove a
        KEEPER's copy is still there after deleting its siblings in other accounts.
        An answer that lags is not a proof, and reporting a keeper safe when it is gone
        is the exact failure #153 is built to prevent.
        """
        mids = _split_ids(ids)
        if not mids:
            return {}
        src = mail_addressing.mailbox_args(mailbox)
        return _parse_statuses(runtime.run_osascript(_PRESENT, *src, US.join(mids)))

    def dedupe_batch(self, ids, mailbox: str, dry_run: bool = True) -> dict:
        """Collapse each named Message-ID's same-mailbox copies down to one (#140).

        The engine behind the ``dedupe-mail`` CLI, and NOT an MCP tool — the model must
        not be able to start thousands of deletes. Each id must already be known
        (by the caller, from sqlite) to have several byte-identical copies in
        ``mailbox``; this deletes all but one of each.

        Rides the recoverable plane in LOG-ONLY mode (``backup=False``): both dedupe
        issues require byte-identity before a copy is touched, so the surviving copy IS
        the backup and writing per-loser files would be pure cost at this scale. The
        un-truncated action log still records every id, its mailbox and its receipt,
        which is what makes the pass auditable and undoable while Trash holds the
        losers.
        """
        mids = _split_ids(ids)
        mail_recover.check_batch(mids)
        src = mail_addressing.mailbox_args(mailbox)
        account = mail_index.account_of(mailbox)
        if account is None:
            raise ValueError(
                f"dedupe needs a mailbox url that names its account — got {mailbox!r}"
            )
        trash = mail_index.query_trash_url(account)
        if trash is None:
            raise NativeError(
                f"no Trash mailbox found for account {account}; cannot verify a dedupe "
                "pass. Do not retry unchanged."
            )
        targets = [
            mail_recover.Target(id=mid, folder=mailbox, account=account) for mid in mids
        ]
        if dry_run:
            return mail_recover.preview("dedupe", targets, destination=trash)
        dst = mail_addressing.mailbox_args(trash)

        def act(located):
            statuses = _parse_statuses(
                runtime.run_osascript(
                    _DEDUPE,
                    *src,
                    *dst,
                    US.join(t.id for t in located),
                    timeout=_DEDUPE_TIMEOUT,
                )
            )
            # "ok 3" carries how many copies went to Trash; the plane's success test is
            # the bare "ok", so normalise while keeping the count in the log line.
            return {
                mid: ("ok" if status.startswith("ok") else status)
                for mid, status in statuses.items()
            }

        return mail_recover.recoverable(
            "dedupe", targets, act, destination=trash, backup=False
        )

    def undo(self, receipt_id: str, dry_run: bool = True) -> dict:
        """Replay one recoverable-plane receipt in reverse (#159).

        A move undoes as a move BACK: the receipt records where every message came
        from, so this is a lookup plus an ordinary ``move_mail`` — which means the undo
        is itself backed up, logged, verified and undoable, with no second code path to
        keep in step. A receipt with no destination (a permanent delete) cannot be
        replayed at all; ``undo_plan`` raises and names the preserved bytes instead.

        ponytail: every receipt today comes from ``move_mail``, which takes ONE source
        mailbox, so a receipt has exactly one source and the undo is one move. Group by
        ``Target.folder`` here if an op ever gathers targets from several mailboxes.
        """
        rec, targets = mail_recover.undo_plan(receipt_id)
        folders = {t.folder for t in targets}
        if len(folders) != 1:
            raise NativeError(
                f"receipt {receipt_id!r} spans {len(folders)} source mailboxes, which "
                "this undo cannot replay as one move. Restore them by hand from "
                f"{rec.get('backup_dir')}. Do not retry."
            )
        return self.move_mail(
            [t.id for t in targets],
            rec["destination"],
            folders.pop(),
            dry_run=dry_run,
        )

    def update_status(
        self,
        ids,
        mailbox: str = "",
        read: bool | None = None,
        flagged: bool | None = None,
        flag_color: str = "",
        dry_run: bool = False,
    ) -> dict:
        """Mark messages read/unread and flag/unflag them, optionally with a colour
        (#79). Batch-capped like every id-addressed write here.

        Deliberately NOT on #159's recoverable plane: this changes two booleans and an
        integer on a stored message. Nothing is destroyed, there are no bytes to
        preserve, and re-issuing this tool with the opposite value IS the undo — a
        backup directory per flag flip would be ceremony, not safety. ``dry_run``
        therefore defaults to FALSE, matching ``delete_draft`` rather than
        ``move_mail``.

        ``mailbox`` is optional and is the disambiguator: given, it is trusted verbatim
        for every id (one Apple Event batch). Omitted, each id resolves ON ITS OWN
        through ``mail_addressing.resolve`` — which reads the Envelope Index, so it
        needs Full Disk Access — and the batch is grouped by the mailbox each id
        actually lives in.

        At least one of ``read``/``flagged``/``flag_color`` must be given; a call that
        changes nothing is a caller bug, not a no-op success.
        """
        mids = _split_ids(ids)
        mail_recover.check_batch(mids)
        color = (flag_color or "").strip().lower()
        if color and color not in FLAG_COLORS:
            raise ValueError(
                f"unknown flag colour {flag_color!r} — one of "
                f"{sorted(set(FLAG_COLORS))}"
            )
        if read is None and flagged is None and not color:
            raise ValueError(
                "update_mail_status needs at least one of read, flagged or flag_color"
            )
        # Group by the mailbox each id actually lives in: one script per mailbox, so a
        # batch spanning two folders is still two Apple Event runs, not 25.
        groups: dict[tuple[str, str], list[str]] = {}
        homes: dict[str, str] = {}
        for mid in mids:
            target = mail_addressing.resolve(mid, folder=mailbox or None)
            groups.setdefault(target.mailbox_args, []).append(target.id)
            # the ROUND-TRIP token, not mailbox_args' decoded path: what a preview row
            # reports has to be what the caller can hand back to the next call
            homes[target.id] = target.folder
        want = {
            "read": read,
            "flagged": True if color and flagged is None else flagged,
            "flag_color": color or None,
        }
        if dry_run:
            return {
                "dry_run": True,
                "op": "status",
                "count": len(mids),
                "would_set": {k: v for k, v in want.items() if v is not None},
                "would_affect": [{"id": mid, "folder": homes[mid]} for mid in mids],
            }
        statuses: dict[str, str] = {}
        for mb, group in groups.items():
            statuses.update(
                _parse_statuses(
                    runtime.run_osascript(
                        _SET_STATUS,
                        *mb,
                        _tri(read),
                        _tri(want["flagged"]),
                        str(FLAG_COLORS[color]) if color else "",
                        US.join(group),
                    )
                )
            )
        results = {mid: statuses.get(mid, "unknown") for mid in mids}
        ok = [m for m, s in results.items() if s == "ok"]
        out = {
            "op": "status",
            "count": len(mids),
            "succeeded": len(ok),
            "set": {k: v for k, v in want.items() if v is not None},
            "results": results,
        }
        if len(ok) != len(mids):
            out["note"] = (
                f"{len(mids) - len(ok)} of {len(mids)} messages were NOT updated — see "
                "`results`. Tell the user; do not retry the whole batch blindly."
            )
        return out

    def get_needs_response(self) -> dict:
        """Inbox messages that likely need the user's response, ranked with a reason
        (flagged / unread-direct / unanswered-direct). Heuristic over headers/
        properties — no body scan; direct-addressed + not-yet-replied. Bounded to
        MAX_MAILS, and #156's `truncated` says when that bound bit."""
        return read_result(mail_triage.needs_response(MAX_MAILS), cap=MAX_MAILS)

    def get_awaiting_reply(self, days: int = 3) -> dict:
        """Sent messages older than `days` with no reply, ranked oldest-first (reason
        'awaiting-reply'). Real In-Reply-To/References threading. Bounded to
        MAX_MAILS."""
        return read_result(mail_triage.awaiting_reply(days, MAX_MAILS), cap=MAX_MAILS)

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
            mail_index.require_index_path()
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
            staleness=mail_index.take_staleness_note(),
        )

    def thread(
        self, message_id: str, limit: int = MAX_THREAD, snippets: bool = False
    ) -> dict:
        """Every message in the conversation containing ``message_id``, deduped and
        oldest-first — including the ones YOU sent, which is what makes it a transcript.
        Bodies stay behind ``mail_body``/``mail_bodies``: a thread is Pointers, so
        quoted-text duplication never arises. Unknown id -> empty (a no-match read, not
        an error); `truncated` marks a thread that hit `limit`, where the OLDEST were
        dropped.

        ``snippets=True`` adds a ``SUMMARY_MAX``-bounded first extract of each body,
        read AT REST on one walk (#158) — no Mail launch, no extra call per message. It
        answers "who spoke last, and about what" without hydrating a single body, which
        is the read that used to cost one ``mail_body`` per message. Opt-in, not
        default: at ``limit=100`` a snippet per pointer is itself the payload dump that
        pointers-not-payload exists to prevent. A message whose file is unreadable
        simply carries no ``snippet`` key — an absent extract, never an empty one.

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
        pointers = mail_index.query_thread(stored_id(message_id), limit)
        if snippets and pointers:
            texts = self._bodies_at_rest([p.id for p in pointers])
            pointers = [
                replace(p, snippet=clean_summary(texts[stored_id(p.id)]))
                if stored_id(p.id) in texts
                else p
                for p in pointers
            ]
        return read_result(
            pointers, cap=limit, staleness=mail_index.take_staleness_note()
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
            scheme, uuid, box = mailbox_url.parse(url) or ("", "", "")
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
                    "mailbox": box,
                    "folder": url,
                    "total": r["total"],
                    "unread": r["unread"],
                }
            )
        return out

    def stats(self, days: int = 30, account: str = "") -> dict:
        """Volume / read-ratio / top-sender statistics over a window (#85).

        Pure Envelope Index — never launches Mail, so it costs one sqlite read and a
        Full Disk Access grant. Counted per DISTINCT message, not per row: raw rows
        overcount by up to 3.6x on a real store (Travel 4,423 rows against 1,252
        distinct), so stats over rows would be wrong by exactly the margin
        ``mail_overview`` was fixed for.

        Deliberately token-bounded — this is a read that rides in a model's context, so
        the top-N lists are capped at ten and there is no per-day series. ``mailbox``
        values are the DECODED url path plus the owning account's uuid; mapping a uuid
        to a display name is one ``mail_overview`` call, and doing it here would make a
        pure-sqlite read launch Mail.

        ``account`` takes a raw account UUID (the ``account`` field every mail Pointer
        carries), not a display name — a name would have to be resolved through Mail.
        """
        if days < 1:
            raise ValueError("mail_stats needs a positive window in days")
        since = int(time.time()) - days * 86400
        rows = mail_index.query_stats_rows(since, account.strip() or None)
        total = len(rows)
        unread = sum(1 for r in rows if not r["is_read"])
        senders: Counter[str] = Counter()
        mailboxes: Counter[str] = Counter()
        days_seen: Counter[str] = Counter()
        for r in rows:
            senders[r["sender"] or "(no sender)"] += 1
            mailboxes[r["mailbox_url"]] += 1
            days_seen[
                datetime.fromtimestamp(r["date_received"]).strftime("%Y-%m-%d")
            ] += 1
        busiest = days_seen.most_common(1)
        out = {
            "window_days": days,
            "since": since,
            "messages": total,
            "unread": unread,
            # round, don't truncate: "0.0" for 1 unread in 10,000 reads as a bug.
            "read_ratio": round((total - unread) / total, 3) if total else None,
            "flagged": sum(1 for r in rows if r["flagged"]),
            "with_attachments": sum(1 for r in rows if r["has_document"]),
            "per_day": round(total / days, 1),
            "busiest_day": (
                {"date": busiest[0][0], "messages": busiest[0][1]} if busiest else None
            ),
            "top_senders": [
                {"address": a, "messages": n} for a, n in senders.most_common(_TOP_N)
            ],
            "top_mailboxes": [
                {
                    "mailbox": mailbox_url.path(url),
                    "account": mailbox_url.account(url) or "",
                    "folder": url,
                    "messages": n,
                }
                for url, n in mailboxes.most_common(_TOP_N)
            ],
            "plane": "envelope-index",
        }
        staleness = mail_index.take_staleness_note()
        if staleness:
            out["staleness"] = staleness
        return out

    def export(self, ids, dest_dir: str) -> dict:
        """Write messages out as importable ``.eml`` files (#85).

        Read AT REST — the same ``.emlx`` payload #159's backups copy, with Mail's
        length prefix and trailing plist stripped — so this launches no Mail, needs no
        Automation, and cannot report a different message than a backup would.

        ``.eml`` is the ONLY format. TXT/HTML renderers were cut in review: ``.eml`` is
        lossless and opens in Mail and everything else, while a model that wants the
        text already has ``mail_body``. Add a format when someone actually needs one.

        Each file is named ``<sanitized-subject-or-id>.eml`` under ``dest_dir`` — inside
        the allowlisted root, derived not concatenated, never overwriting (see
        ``mail_files``). A message that cannot be located is reported per-id as
        ``absent`` rather than failing the batch: 62% of local messages are
        ``.partial``, and a message with no local file has no bytes here to write.
        """
        mids = _split_ids(ids)
        if not mids:
            raise ValueError("export_mail needs at least one message id")
        if len(mids) > MAX_MAILS:
            raise BatchTooLarge(
                f"export_mail takes at most {MAX_MAILS} ids at a time (got "
                f"{len(mids)}). Split the batch and re-issue."
            )
        located = mail_recover.locate(
            [mail_recover.Target(id=m, folder="") for m in mids]
        )
        payloads = mail_recover.read_payloads(located)
        out = []
        for t in located:
            payload = payloads.get(t.id)
            if payload is None:
                out.append({"id": t.id, "status": "absent", "fidelity": t.fidelity})
                continue
            path = mail_files.target_path(dest_dir, f"{t.id}.eml", fallback="message")
            path.write_bytes(payload)
            out.append(
                {
                    "id": t.id,
                    "status": "written",
                    "path": str(path),
                    "bytes": len(payload),
                    # `partial` means Mail never downloaded the ATTACHMENTS (#119) —
                    # the body is there and complete. A real file, missing its
                    # attachment payloads. Say so.
                    "fidelity": t.fidelity,
                }
            )
        return {
            "results": out,
            "written": sum(1 for r in out if r["status"] == "written"),
            "dest_dir": str(mail_files.resolve_dest(dest_dir)),
            "plane": "at-rest",
        }

    def index_bodies(self, rebuild: bool = False) -> dict:
        """Opt-in build/refresh of the best-effort FTS body index over EVERY .emlx on
        disk, ``.partial`` included (read-at-rest). Resumable, size-capped. Returns
        counts + coverage. Never launches Mail, never writes in Mail's data.

        Indexing partials is #119's whole finding: a ``.partial.emlx`` is missing its
        ATTACHMENTS, not its body — 99.47% of them hold a complete one — so the old
        skip hid ~62% of the store from ``mail_search(body=…)``."""
        root = mail_index.mail_root()
        if root is None:
            raise NativeError("no Mail data found; open Mail once. Do not retry.")
        res = mail_index.build_body_index(
            mail_root=root, fts_db=mail_index.fts_path(), rebuild=rebuild
        )
        # NOT a coverage figure, and it used to be named one (#168 review). `indexed` is
        # THIS RUN's newly-indexed count; over `total_emlx` it reads as "14/36476 of the
        # store is searchable" on a store that is already fully indexed — the exact
        # opposite of the truth, on the one field a caller reads to judge the feature.
        # A resumable indexer cannot answer "is body search usable?" from its own run
        # counters; only the sidecar-vs-store intersection can, and `body_coverage()`
        # already does that (~1.9s) on the one path that needs it — an empty `body=`
        # search. So report the run honestly and name where the real answer lives.
        res["indexed_this_run"] = (
            f"{res['indexed']} newly indexed, {res['skipped']} already current, of "
            f"{res['total_emlx']} .emlx on disk. This is THIS RUN's progress, not "
            "coverage — mail_search(body=…) reports coverage when it finds nothing."
        )
        return res

    def index_ids(self, rebuild: bool = False) -> dict:
        """Build/refresh the Message-ID sidecar (#201) — the map that gives a
        pre-Tahoe Envelope Index the RFC822 Message-IDs it never stored (#199).
        Harvested headers-only off the ``.emlx`` files at rest; resumable (a row
        whose file is absent is retried next run), self-healing on a Mail index
        rebuild. Never launches Mail, never writes in Mail's data.

        ``rebuild=True`` starts from an empty sidecar — the recovery move when the
        sidecar itself is suspect; a plain re-run already re-harvests everything
        unmapped and self-heals via INSERT OR REPLACE."""
        path = mail_index.require_index_path()
        if rebuild:
            mail_ids.sidecar_path().unlink(missing_ok=True)
        return mail_ids.build(path)
