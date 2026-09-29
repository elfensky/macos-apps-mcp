---
spike: 005
idea: mail-fixes
name: mail-unowned-from
type: standard
validates: "Given 8 Mail accounts, when outgoing messages get owned, non-default and unowned senders (windowless and visible) and replies are built in non-default accounts, then the autosaved draft's From shows whether Mail rejects, falls back or keeps it, and which account a reply uses"
verdict: VALIDATED
related: []
tags: [mail, sender, drafts, reply, accounts, autosave]
---

# Spike 005: What Mail does with a sender no account owns

## What This Validates

Given Mail on macOS 27.0 with 8 accounts (default sender: Personal), when outgoing messages
get an owned non-default sender, an unowned sender and variants of both, windowless
(`send_mail`'s shape) and visible (`create_draft`'s shape), and when Mail's `reply` verb runs
on INBOX messages (`mail_reply`'s shape), then the autosaved draft's From header shows what
Mail does with each sender, and the reply's sender shows which account a reply uses.

**Answer (MAIL-04): Mail falls back to the default account, silently.** `set sender` to an
address that no account owns raises no error. The readback right after it already names the
default account, and the autosaved draft carries the default From and is filed in the default
account's Drafts. Mail does not match by domain. So `send_mail(from_address=<unowned>)` today
sends from the default account and reports success.

**Answer (MAIL-03):** an owned non-default address sticks, windowless and visible. A reply
comes from the receiving account, **except** when the original message is FROM an address of a
configured account: then the reply is from that account and to that account.

## Research

- `Mail.sdef`: `sender` on `outgoing message` is writable `text` (cocoa key
  `appleScriptSender`), with no validation described. On `message` it is read-only.
- `docs/mail-applescript-facts.md`: §2 autosave lands ~10–15 s late, so wait ≥ 20 s; §3 `delete`
  before `send` works; §3c a windowless `delete` can silently no-op; §6 `set sender` works and
  the default sender is not predictable from account order; `whose` is unreliable on Drafts.
- `defaults read com.apple.mail` holds no default-account key.

| Approach | Mechanism | Verdict |
|---|---|---|
| `set sender` on an outgoing message, read the autosaved draft | the `send_mail` verb; the draft shows the stored From | **chosen** |
| Send to `andrei@lav.ren`, read the delivered From | real send | rejected: the owner approved no send |
| Read Mail preferences for the rule | `defaults` | no such key |

## How to Run

```sh
cd .planning/spikes/005-mail-unowned-from
uv run python probe_sender.py sender    # 9-case matrix, ~90 s
uv run python probe_sender.py controls  # 4 visible controls, 60 s autosave wait
uv run python probe_sender.py autosave  # 1 bare visible message, 60 s wait
uv run python probe_sender.py reply     # 4 replies, each deleted before send
```

Run it with the Mail watchdog on. Visible cases open compose windows; after the delete an
empty window frame can stay open (facts §5e): close it with ⌘W. Output and `results-*.json`
carry roles (`account:Business`, `kept:unowned`) and masked shapes, never addresses.

## What to Expect

One line per case: `set_error`, the immediate `sender` readback, then the autosaved draft's
sender, From header and the account whose Drafts holds it. Cleanup lines end with `left=0`.
Deleted drafts go to their account's Trash (facts §5c: Trash is terminal for AppleScript).

## Investigation Trail

1. **Inventory (read-only).** 8 accounts, 1 address each. Grandma and Mama hold family
   members' mail and are excluded as targets. Default sender: Personal.
2. **Matrix, 9 cases.** Owned non-default (Business) exact, display form and uppercase: all
   Business. Unowned `example.invalid`: Personal, windowless and visible. Unowned `lav.ren`:
   Personal. No `set sender` raised an error.
3. **Confound: domain or default?** Personal is both the default and the `lav.ren` domain.
   Control with an unowned `drunik.be` address (Business's domain): Personal. Mail ignores the
   domain.
4. **Uppercase oddity.** The From header resolved to Business, but the stored draft's `sender`
   read `ANDREI@drunik.be <ANDREI@DRUNIK.BE>` in shape: a display name with an `@` and no
   quotes. `email.utils.parseaddr` returns `('', '')` for it. The probe's own parser missed
   it the first time.
5. **Autosave did not fire for bare messages.** 3 of 3 messages with only a subject and a
   recipient never autosaved (25 s twice, then 60 s). 12 of 12 with a sender or a body
   autosaved. This refines facts §3 ("any outgoing message").
6. **Windowless `delete` no-op (facts §3c) reproduced.** 6 of 6 windowless messages survived
   `delete`, twice; 8 of 8 visible ones were deleted (-1728). The controls and the replies used
   visible messages only for that reason. The 6 survivors were never sent; facts §3c says they
   vanish on the next Mail restart. They autosaved once before the delete (5 of 6; the bare one
   did not), and those drafts were deleted.
7. **Replies, direct.** Business INBOX and iCloud INBOX, third-party sender, addressed to the
   holding account: reply from that account, to the third party. 4 of 4 over two runs.
8. **Surprise: a reply to mail from a configured account.** A Personal INBOX message from
   Grandma's address to the Google address: the reply is FROM Grandma's account and TO
   Grandma's address. Confirmed with a Mama message (2 of 2). Mail treats mail from any
   configured account as the user's own and answers it from that identity. Every reply was
   deleted before `send`; Drafts stayed at its baseline.
9. **Census.** In the newest 500 INBOX messages per non-excluded account, every third-party
   message is addressed to the account that holds it. "Receiving account ≠ addressed account"
   for third-party mail does not occur on this Mac, so that case is untested.

## Results

**Verdict: VALIDATED.**

| Case | `set sender` error | Readback | Autosaved From | Filed in |
|---|---|---|---|---|
| no sender (default) | — | Personal | Personal (with body; none when bare) | Personal |
| owned non-default, exact / display form | none | Business | Business | Business |
| owned non-default, UPPERCASE | none | Business | Business (`sender` echoes the case) | Business |
| unowned `example.invalid` | none | **Personal** | **Personal** | Personal |
| unowned in the default's domain | none | **Personal** | **Personal** | Personal |
| unowned in a non-default account's domain | none | **Personal** | **Personal** | Personal |

Windowless and visible gave the same sender in every case tested in both.

| Reply target (INBOX of) | Original From → To | Reply From → To |
|---|---|---|
| Business | third party → Business | Business → third party |
| iCloud | third party → iCloud | iCloud → third party |
| Personal | Grandma → Google | **Grandma → Grandma** |
| Personal | Mama → Google | **Mama → Mama** |

**Signal for the build (Phase 02.1)**

- **Refuse an unowned `from_address` before any native write** (MAIL-04). Mail never
  refuses it and never errors. The check needs the accounts' `email addresses`, which is an
  Automation read. The outbound dry run makes no native call, so it cannot check ownership
  unless the address list is cached from an earlier real call. The plan must decide this.
- **Compare case-insensitively and pass the account's own spelling.** Mail matches the case,
  but keeps the caller's spelling in the stored `sender`.
- **The `sender` readback is a valid verify-after-write.** It matched the autosaved From in
  every case. But a readback-then-rollback is not a safe refusal: in the facts §3c state the
  windowless rollback no-ops and the message autosaves into Drafts.
- **A reply is not always from the receiving account.** For mail from a configured account,
  Mail answers as that account. On this Mac that means family members' identities. `reply_all`
  sends with no review, so it needs a guard: read the reply's `sender` and refuse when it is
  not the account the original was addressed to. `mail_reply` should report the reply's
  `from`.
- **A parser of Mail's `sender` must accept `x@y <X@Y>`** (an unquoted display name with `@`).
  `parseaddr` does not.
- **Autosave needs content or a sender change.** A check that waits for an autosaved draft
  must set a body (`create_draft` always does).

**Not tested**

- Threading headers of a reply: each reply was deleted before autosave. `reply_all` threading
  was device-verified in #83 with the same verb.
- Receiving account ≠ addressed account for third-party mail: no such message exists here.
- What a recipient sees: nothing was sent.
