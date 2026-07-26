# The outbox zombie: `delete` after `send` (#135) — design

**Milestone:** 0.9.0 — Mail depth & outbound. Follows #104/#82/#83 (merged as #134).
**Status:** approved (brainstorming, 2026-07-26).
**Covers:** #135 (`delete` on an outgoing message doesn't remove it; a stranded one jams the outbox).
**Out of scope:** #133 (the same rollback stranding an autosaved *draft* — different symptom, not
addressed by this change), outbox list/delete tools, `doctor()` changes.

## Why

#135 was filed as "our rollback fails to clean up." Device verification on 2026-07-26 shows the
opposite and worse: **our rollback is what creates the jam.**

`delete` on an outgoing message that Mail has already accepted via `send` does not remove it. It
returns cleanly, the count does not drop, and the message is left stranded at the head of the send
queue — where later, valid sends pile up behind it and never leave.

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
5. **The stranded entry is a delivered zombie.** The probe message from (4) *arrived in the inbox* —
   it was delivered — yet its outbox entry persisted. Mail removes an accepted message from the
   outbox once it goes out; calling `delete` on it in flight breaks that cleanup and leaves the
   object behind.
6. **The zombie is in-memory, not on disk.** Quitting and relaunching Mail took the count 1 → 0.
   That is the recovery a jammed user needs, and it is why "clearing the outbox restored delivery"
   worked in the original report.
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
send msg                -- past this line, deleting strands a zombie (findings 4 + 5)
```

If `send` itself raises, the message is **left alone** and the error propagates. That leaves an
unsent message behind in the worst case, which is strictly better than a zombie that jams every
subsequent send. The raised error names the leftover and the recovery.

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

### 3. The `outbox_pending` note gains the recovery

`_with_outbox_pending`'s note already tells the caller delivery is unconfirmed. It gains one
sentence: a message stuck in the Outbox clears when Mail is quit and reopened (finding 6). That is
the actionable half a jammed user is missing.

## Testing

Unit (mocked at the adapter boundary, per the repo's convention):

- **The invariant that keeps this fixed:** for each of `_SEND`, `_REPLY_ALL`, `_FORWARD`, no
  `delete` appears anywhere after the `send` verb in the script text. This is the test that fails if
  someone later re-nests `send` back inside the rollback `try`.
- The `rollback` handler is present in each script that can roll back, and the scripts still carry
  their existing argv/framing contracts (existing tests cover these — they must stay green).
- `_with_outbox_pending` emits the restart recovery in its note when pending > 0, and no note at 0.

On-device (`-m integration`, manual, never CI) — per the standing rule, sends go **only** to
andrei@lav.ren, and each write is judged by the resulting message, not the return value:

- A real `send_mail` delivers, and the outbox drains to 0 afterwards.
- A `forward_mail` of a message with attachments delivers with its attachments intact.
- A deliberately failing pre-send step rolls back with the outbox count unchanged and no Drafts
  residue.

## Risks

- **A failed `send` now leaves a message behind.** Accepted deliberately: the alternative is the
  zombie this issue exists to remove. The error text points at Mail ▸ Outbox and the restart
  recovery.
- **#133 is untouched.** Mail's autosaved Drafts copy is a separate mechanism from the outbox
  object; nothing here suppresses it. `drafts()` + `delete_draft()` remain the recovery.
- **Finding 5 is inferred, not proven.** That deleting in flight is what *breaks* Mail's own outbox
  cleanup is the best explanation for a delivered message whose entry persisted; the fix does not
  depend on the mechanism being right, only on the observed no-op (finding 4).
