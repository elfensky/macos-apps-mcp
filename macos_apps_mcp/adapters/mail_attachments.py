"""Mail attachments (#178) — list what a message carries, save ONE attachment to disk.

Reads address any mailbox through ``mail_addressing`` (the shared ``MAILBOX_REF``
resolver / ``resolve`` for a bare id); the filesystem boundary — allowlisted root,
derived filenames, never-overwrite, size cap — is ``mail_files``', enforced in Python
BEFORE any Apple Event. Nothing here mutates a message: ``save`` writes a file out,
and the one side effect it can have (Mail fetching a not-yet-downloaded message) is
documented on the script below.

The result bound is PASSED IN (``limit``) rather than imported: the cap is the
adapter's policy (``mail.MAX_MAILS``), this module is the mechanism — and the
parameter is what keeps the import cycle closed (``mail`` imports this module, never
the reverse).
"""

from __future__ import annotations

from .. import runtime
from ..text import (
    STRIP_FRAMING,
    US,
    Field,
    bool_or_none,
    clean_summary,
    int_or_none,
    parse_framed,
)
from . import mail_addressing, mail_files
from .mail_index import _deeplink

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
        -- #81: the attachment's own id (a MIME part path, e.g. "1.12"). Four
        -- attachments named image001.jpg on one message is normal, so the NAME is not
        -- an address; this is. Guarded because it is the one property Mail.sdef
        -- declares that has never been exercised on every message shape.
        set aId to ""
        try
          set aId to (id of a) as text
        end try
        set out to out & us & my stripFraming(name of a) & us & aSize & us & aDown & ¬
          us & my stripFraming(aId)
      end repeat
      set out to out & rs
    end repeat
  end tell
  end timeout
  return out
end run"""
)


# save_mail_attachment (#81): write ONE attachment out. `mail attachment` is entirely
# read-only in Mail.sdef but declares `<responds-to command="save">` — device-verified
# 2026-08-05, and unlike most of that dictionary this one is TRUE. What the probing
# added, and what shapes this script:
#
# * `save a in <file>` writes to the EXACT path given (it is not a directory), and
#   OVERWRITES SILENTLY — a 0-byte placeholder came back holding 192 KB. So the
#   never-overwrite rule cannot live here; `mail_files.target_path` refuses in Python
#   before this script is ever reached.
# * Saving an attachment on a NOT-downloaded message makes Mail FETCH the whole message
#   synchronously — all seven attachments on a `.partial` message flipped to
#   downloaded=true and `file size` changed from the base64 estimate (14509) to the real
#   byte count (8755). So this call is not a read: it can hit the network, and it gets
#   _SAVE_TIMEOUT rather than the 30s default.
# * A missing destination DIRECTORY raises -10000 and writes nothing (`mail_files`
#   creates it first, inside the allowlisted root).
# * The size cap is enforced HERE, before `save`, because `file size` is only knowable
#   from Mail — checking it in Python would cost a second Apple Event on every call,
#   and the fetch above means "look, then save" is not free.
#
# Addressing: `attachment id` (a MIME part path like "1.12") when given, else the name.
# The name is NOT unique — four `image00N.jpg` on one real message — so an ambiguous
# name errors with the ids rather than silently saving the first match. Returns
# `<size>US<downloaded>` as the attachment's own report of what it wrote.
_SAVE_ATTACHMENT = (
    mail_addressing.MAILBOX_REF
    + """

on run argv
  set mid to item 1 of argv
  set mb to my mailboxFor(item 2 of argv, item 3 of argv)
  set wantName to item 4 of argv
  set wantId to item 5 of argv
  set destPath to item 6 of argv
  set maxBytes to (item 7 of argv) as integer
  set us to character id 31
  with timeout of 600 seconds
  tell application "Mail"
    set matches to (messages of mb whose message id is mid)
    if (count of matches) is 0 then error ¬
      "no message with that message id in " & (item 3 of argv)
    set m to item 1 of matches
    set found to missing value
    set nMatch to 0
    set seenIds to ""
    repeat with a in (mail attachments of m)
      set thisId to ""
      try
        set thisId to (id of a) as text
      end try
      if wantId is not "" then
        if thisId is wantId then
          set found to a
          set nMatch to 1
          exit repeat
        end if
      else if (name of a) is wantName then
        set nMatch to nMatch + 1
        set found to a
        set seenIds to seenIds & thisId & " "
      end if
    end repeat
    if found is missing value then error ¬
      "no attachment on that message matches — list them with mail_attachments"
    if nMatch > 1 then error ¬
      "that name is on " & (nMatch as text) & " attachments of this message (ids: " & ¬
      seenIds & ") — pass attachment_id instead"
    set aSize to -1
    try
      set aSize to (file size of found) as integer
    end try
    if aSize > maxBytes then error ¬
      "attachment is " & (aSize as text) & " bytes, over the cap"
    set aDown to ""
    try
      set aDown to (downloaded of found) as text
    end try
    save found in (destPath as POSIX file)
    return (aSize as text) & us & aDown
  end tell
  end timeout
end run"""
)

# Saving can FETCH the message off the server (see above), so 30s is not enough — a
# large attachment on a slow IMAP account is an ordinary case, not a hang. Same
# reasoning as _MOVE_TIMEOUT.
_SAVE_TIMEOUT = 300.0


def _parse_attachments(raw: str) -> list[dict]:
    """Parse the _ATTACHMENTS payload: RS-separated records, each US-separated as
    message-id, subject, then (name, size, downloaded) triples. Malformed/partial
    trailing records are skipped.

    The id (#155) makes a row addressable — #81 (save an attachment to disk) has nothing
    to name a file by without it, and "the attachment on THIS message" used to cost a
    whole-mailbox scan. Each attachment carries its OWN ``id`` too (#81): a MIME part
    path like ``1.12``, which is what ``save_mail_attachment`` addresses when several
    attachments on one message share a name — device-verified, four ``image00N.jpg``
    on one real message. A blank id is kept, not dropped: an unsaved draft has no
    Message-ID yet, and listing its attachments is this tool's documented job. `folder`
    is filled in by the caller, which knows the mailbox it was asked about."""
    recs = parse_framed(
        raw,
        [Field("id", str.strip), Field("summary", clean_summary)],
        repeat=[
            Field("name", clean_summary, required=True),
            Field("size", int_or_none),
            Field("downloaded", bool_or_none),
            Field("id", str.strip),
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


def records(mailbox: str, query: str, message_id: str, limit: int) -> list[dict]:
    """The body of ``MailAdapter.list_attachments`` — see that docstring for the
    caller-facing contract. Returns the records; the adapter wraps them in the
    bounded-read envelope (an id names one message, so its cap cannot bite)."""
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
    raw = runtime.run_osascript(_ATTACHMENTS, query.strip(), str(limit), *mb, mid)
    recs = _parse_attachments(raw)[:limit]
    # #155: hand back the mailbox this actually read, VERBATIM. It is already the
    # round-trip token every id-taking tool wants, and echoing it means a row from
    # here is complete on its own — id + deeplink + folder — instead of only being
    # usable by a caller who still remembers what it asked for.
    for r in recs:
        r["folder"] = folder
    return recs


def save_attachment(
    message_id: str,
    dest_dir: str,
    name: str = "",
    attachment_id: str = "",
    mailbox: str = "",
) -> dict:
    """The body of ``MailAdapter.save_attachment`` — see that docstring for the
    caller-facing contract."""
    target = mail_addressing.resolve(message_id, folder=mailbox or None)
    wanted_name, wanted_id = name.strip(), attachment_id.strip()
    if not wanted_name and not wanted_id:
        raise ValueError(
            "save_mail_attachment needs the attachment's name or its id — list "
            "them with mail_attachments first"
        )
    path = mail_files.target_path(dest_dir, wanted_name or wanted_id)
    raw = runtime.run_osascript(
        _SAVE_ATTACHMENT,
        target.id,
        *target.mailbox_args,
        wanted_name,
        wanted_id,
        str(path),
        str(mail_files.MAX_BYTES),
        timeout=_SAVE_TIMEOUT,
    )
    size, _, downloaded = raw.strip().partition(US)
    return {
        "saved": str(path),
        "name": path.name,
        "original_name": wanted_name or wanted_id,
        "bytes": mail_files.confirm_written(path),
        "reported_size": int_or_none(size),
        "was_downloaded": bool_or_none(downloaded),
        "id": target.id,
        "folder": target.folder,
    }
