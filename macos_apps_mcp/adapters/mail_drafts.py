"""Mail drafts (#178) — the draft lifecycle: create, list, resolve, delete, reply.

Everything here opens or removes a draft for the HUMAN; nothing here sends (the send
plane is ``mail_outgoing``, and ``send_mail(draft_id=…)`` lives there because a send is
what it is). The two live at arm's length on purpose: this module composes
``mail_outgoing.ROLLBACK`` (the one verifying delete for a partial outgoing message)
and ``quoted_body`` (the one quote preamble), and exports ``_DELETE_DRAFT`` so the send
path can drop a draft whose content just went out — the constant crosses, the policy
does not.

Bounds are PASSED IN (``limit``) rather than imported: the cap is the adapter's policy
(``mail.MAX_MAILS``), this module is the mechanism — and the parameter is what keeps
the import cycle closed (``mail`` imports this module, never the reverse).

``snapshot``/``delete_draft`` here are the bodies of the MailAdapter methods of the
same names; the methods stay on the class because ``snapshot`` is a Protocol member
(``contracts.Snapshotter`` — ``audit.py`` calls it on the adapter) and
``delete_draft``'s dry-run path resolves through it.
"""

from __future__ import annotations

from collections.abc import Callable

from .. import runtime
from ..contracts import Pointer, deletion_result
from ..text import (
    READ_BODY,
    STRIP_FRAMING,
    Field,
    _summary,
    clean_summary,
    parse_framed,
)
from . import mail_addressing, mail_outgoing
from .mail_addressing import _norm_mid, bare_id
from .mail_index import _deeplink

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
    + mail_outgoing.ROLLBACK
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
    + mail_outgoing.ROLLBACK
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


def _parse_draft_records(raw: str) -> list[dict]:
    """Parse the _DRAFTS payload: US-framed (message id, subject, first recipient)
    records. Records with no stable message-id are skipped — same rule as the inbox
    reads (#61): never emit a non-resolvable id.

    ``folder="drafts"`` (#155) — the canonical name, so a draft pointer round-trips
    into ``mail_attachments`` (confirming an attachment landed) without guessing.

    Each record keeps its ``subject`` and ``to`` as DISCRETE fields alongside the
    Pointer's free-text ``summary`` (#157). Reacquiring "the draft I just made" used to
    mean substring-matching ``"subject — to recipient"``, which is guesswork and
    collides outright whenever two drafts share a subject."""
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
        {
            **Pointer(
                id=r["id"],
                summary=clean_summary(
                    _summary(r["subject"], f"to {r['rcpt']}" if r["rcpt"] else "")
                ),
                deeplink=_deeplink(r["id"]),
                folder="drafts",
            ).as_dict(),
            "subject": r["subject"],
            "to": r["rcpt"],
        }
        for r in recs
    ]


def create_draft(to: str, subject: str, body: str) -> dict:
    """The body of ``MailAdapter.create_draft`` — see that docstring for the
    caller-facing contract."""
    addr = to.strip()
    if not addr:
        raise ValueError("create_draft needs a recipient address (to)")
    with runtime.body_file(body or "") as path:
        runtime.run_osascript(_CREATE_DRAFT, addr, subject or "", path)
    return {
        "created": True,
        "subject": subject or "",
        "mailbox": "Drafts",
        "note": "opened in a Mail compose window for your review; save it to keep "
        "it in Drafts, where it gets a stable message-id — see drafts()/"
        "delete_draft().",
    }


def draft_records(limit: int) -> list[dict]:
    """The Drafts read: Pointer fields plus the discrete ``subject``/``to`` (#157)."""
    return _parse_draft_records(runtime.run_osascript(_DRAFTS, str(limit)))


def snapshot(ident: str, limit: int) -> Pointer | None:
    """Current Pointer for one draft, or None if the id no longer resolves — the body
    of ``MailAdapter.snapshot`` (the ``Snapshotter`` Protocol member). Compares
    bracket-normalized (`_norm_mid`, M1 review): accepts a bracketed or bare ``ident``
    against a bracketed or bare stored id."""
    mid = _norm_mid(ident)
    for r in draft_records(limit):
        if _norm_mid(r["id"]) == mid:
            return Pointer(
                id=r["id"],
                summary=r["summary"],
                deeplink=r["deeplink"],
                folder=r.get("folder"),
            )
    return None


def delete_draft(
    ident: str, dry_run: bool, snapshot: Callable[[str], Pointer | None]
) -> dict:
    """The body of ``MailAdapter.delete_draft``. ``snapshot`` is the ADAPTER's bound
    method, passed in so the dry-run resolve stays a call on the class (the audit
    plane and the Protocol both address the adapter, not this module)."""
    mid = bare_id(ident)
    if not mid:
        raise ValueError("delete_draft needs a draft id (the message-id from drafts)")
    if dry_run:
        found = snapshot(mid)
        if found is None:
            raise ValueError(f"no draft with message id {mid!r}")
        return deletion_result(mid, found)
    runtime.run_osascript(_DELETE_DRAFT, mid)
    return deletion_result(mid, None)


def reply(
    message_id: str, mailbox: str, reply_body: str, include_quote: bool = True
) -> dict:
    """The body of ``MailAdapter.reply`` — see that docstring for the caller-facing
    contract (opens a threaded draft, NEVER sends)."""
    mid = bare_id(message_id)
    if not mid:
        raise ValueError("reply needs the original message's id")
    if not reply_body.strip():
        raise ValueError("reply needs a non-empty reply_body")
    mb = mail_addressing.mailbox_args(mailbox)
    # the quote preamble lives ONCE, in mail_outgoing (#160) — reply and reply_all
    # each carried a copy of the fetch/guard/partition/sanitize/build sequence.
    body = (
        mail_outgoing.quoted_body(reply_body, mid, mb) if include_quote else reply_body
    )
    with runtime.body_file(body) as path:
        runtime.run_osascript(_REPLY, mid, path, *mb)
    return {
        "created": True,
        "subject": "(reply)",
        "mailbox": "Drafts",
        "note": "reply draft opened for review; save it to keep it in Drafts, "
        "where it gets a stable message-id (see drafts())",
    }
