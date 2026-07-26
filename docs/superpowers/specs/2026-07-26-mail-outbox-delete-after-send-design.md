# `delete` after `send`, and what `outbox_pending` really counts (#135) — design

**Milestone:** 0.9.0 — Mail depth & outbound. Follows #104/#82/#83 (merged as #134).
**Status:** approved (brainstorming, 2026-07-26).
**Covers:** #135 (`delete` on an outgoing message doesn't remove it) and the `outbox_pending`
counter it exposed as wrong.
**Out of scope:** #133 (the same rollback stranding an autosaved *draft* — different symptom, not
addressed by this change), outbox list/delete tools, `doctor()` changes.

## Why

#135 was filed as "our rollback fails to clean up." Device verification on 2026-07-26 found two
real defects, neither of them quite that.

1. **A post-`send` rollback cannot work, so it can only lie.** `delete` on an outgoing message Mail
   has already accepted returns cleanly and removes nothing; the message delivers anyway. Every
   send path wrapped `send` inside a `try` whose handler called `delete`, so a failure at the send
   step ran a cleanup that silently did nothing and reported success.
2. **`outbox_pending` has been measuring the wrong thing since #134.** It counts `outgoing
   messages`, which is the set of script-created message *objects* alive in Mail's session —
   including already-delivered ones — not Mail's send queue. It therefore reads non-zero forever
   after the session's first send, firing "delivery is NOT confirmed" on every later send.

The original report's "a stranded message jams the outbox" is **not** supported by anything
observed here, and the recipient-less-message theory is disproved outright (finding 7). What the
reporter saw as a stuck count of 3 was almost certainly the session-object counter of finding 5.

## Device findings (2026-07-26, macOS 25.5) — do not re-derive

Each line was run as raw osascript against the live Mail on this machine.

1. **A compose window IS an `outgoing message` with 0 recipients.** `make new outgoing message
   {visible:true}` took the count 0 → 1 with `count of (to recipients of m)` = 0. So any sweep of
   the form "delete every recipient-less outgoing message" would destroy a human's half-written
   email. That whole class of fix is off the table.
2. **Pre-`send` `delete` works, every time tried.** A freshly made outgoing message: 1 → 0. A
   `forward … opening window no`-derived message (the exact shape #135 suspected): 1 → 0. Neither
   left a residue in the Drafts mailbox.
3. **A deleted reference goes detectably dead.** Reading a property off a successfully deleted
   outgoing message raises **-1728**. This makes "verify the delete" precise and race-free — no
   counting, so a human opening a compose window mid-call cannot produce a false verdict.
4. **`delete` on a QUEUED message is a silent no-op.** After `send msg`, both
   `delete outgoing message i` and `delete <ref>` returned cleanly and the count stayed 1 → 1.
   This is #135's "3 → 3" observation, reproduced.
5. **`outgoing messages` is not Mail's outbox.** The probe message from (4) *arrived in the inbox* —
   delivered — yet still counted as an outgoing message. Sampling both counters across one real
   send settled it: `count of outgoing messages` read 2 before the send and 2 for ten seconds
   after, never moving, while `count of (messages of outbox)` went 0 → 1 as the message queued and
   back to 0 within ~10s as it went out. The first counts script-session message objects (they
   outlive delivery); the second is the real queue. An earlier reading of finding 5 — that
   deleting in flight *breaks* Mail's outbox cleanup — was **wrong**, and was disproved by a send
   that left an entry behind with no `delete` involved at all.
6. **The session-object list clears on a Mail restart.** Quitting and relaunching took the object
   count 1 → 0. This is *not* a recovery for a genuinely stuck outbox — it only discards dead
   scripting objects — so nothing in this design tells a user to restart Mail to unjam mail.
7. **Recipient-less sends are not the cause.** `send_mail` and `forward` both already `raise` in
   Python on an empty `to`, so the shipped paths cannot queue a recipient-less message. The
   recipient-less leftovers in the original report came from ad-hoc spike scripts, not from us.

## The change

### 1. `send` moves out of the delete-protected `try`

`_SEND`, `_REPLY_ALL`, and `_FORWARD` today wrap population *and* `send` in one `try` whose handler
calls `delete`. Split them:

```applescript
set msg to make new outgoing message with properties {visible:false}
try
  -- populate: subject, body, sender, recipients
on error errMsg
  my rollback(msg)      -- pre-send only; finding (2): this actually works
  error errMsg
end try
send msg                -- past this line `delete` is a no-op that only lies (finding 4)
```

If `send` itself raises, the message is **left alone** and the error propagates. Nothing is lost
by not deleting: the delete there never removed anything anyway (finding 4). What changes is that
the caller is told a message may remain, instead of being told it was cleaned up.

Whether `send` failed before or after Mail took ownership is unknowable from AppleScript, so the
rule is unconditional: **never `delete` after `send` has been attempted.**

### 2. The pre-send rollback verifies itself

A shared handler in the Mail script preamble, alongside `READ_BODY`/`STRIP_FRAMING`:

```applescript
on rollback(msg)
  try
    tell application "Mail" to delete msg
  end try
  try
    tell application "Mail" to get subject of msg
    return false          -- still readable => the delete did not take
  on error number en
    return (en is -1728)  -- -1728 => reference dead => really gone (finding 3)
  end try
end rollback
```

Only -1728 counts as proof. Any other error (a timeout, say) means the outcome is unknown, and
unknown is reported as **not** verified — the handler never guesses in the reassuring direction.

A `false` return is folded into the re-raised error so the caller learns a partial message survived,
rather than being told a clean lie. It does not change control flow — the original error is still
what propagates.

### 3. `_OUTBOX_COUNT` counts the real queue

One line: `count of (messages of outbox)` instead of `count of outgoing messages` (finding 5).
Without this the signal is a permanent false alarm and the caller learns to ignore it. The note's
wording is unchanged — it was already correct; it just now fires on the right condition.

## Testing

Unit (mocked at the adapter boundary, per the repo's convention):

- **The invariant that keeps this fixed:** for each of `_SEND`, `_REPLY_ALL`, `_FORWARD`, no
  `delete` appears anywhere after the `send` verb in the script text. This is the test that fails if
  someone later re-nests `send` back inside the rollback `try`.
- The `rollback` handler is present in each script that can roll back, and the scripts still carry
  their existing argv/framing contracts (existing tests cover these — they must stay green).
- `_OUTBOX_COUNT` reads `messages of outbox` and never `outgoing messages`; `_with_outbox_pending`
  emits its note when pending > 0 and stays silent at 0.

On-device (`-m integration`, manual, never CI) — per the standing rule, sends go **only** to
andrei@lav.ren, and each write is judged by the resulting message, not the return value:

- A real `send_mail` delivers, and the outbox drains to 0 afterwards.
- A `forward_mail` of a message with attachments delivers with its attachments intact.
- The `rollback` handler, run against live Mail, deletes a real outgoing message and returns
  `true` — the delete is proven, not assumed.
- `outbox_pending` moves 0 → non-zero → 0 across a real send. The old counter could not: it reads
  non-zero forever once the session has sent anything.

## Risks

- **A failed `send` now leaves a message behind.** Accepted deliberately: the delete that used to
  "clean up" there never removed anything (finding 4), so this changes what is *reported*, not what
  survives. The error points at Mail ▸ Outbox so a retry cannot silently send twice.
- **#133 is untouched.** Mail's autosaved Drafts copy is a separate mechanism; nothing here
  suppresses it. `drafts()` + `delete_draft()` remain the recovery.
- **`messages of outbox` is verified on this machine only.** It resolved cleanly and tracked one
  real send end to end (finding 5). If a future macOS drops the accessor, `_outbox_pending` raises
  rather than silently reporting 0 — the existing parse-strictly-or-raise behaviour, which is the
  right failure direction for a delivery-confidence signal.
- **Whether a genuinely stuck outbox jams later sends is still unverified.** Nothing observed here
  reproduced it, and no claim about it survives in the code.
