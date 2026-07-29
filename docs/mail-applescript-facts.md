# Mail.app AppleScript: device-verified facts

Everything here was verified by **running it against real Mail on macOS 25.5**, not read in a
dictionary or inferred from code. Each entry says what was observed and when.

**Do not re-derive these, and do not "improve" a workaround into something more elegant** — most of
them exist because the elegant version was tried first and lost. Add to this file whenever a device
probe teaches something new; that is cheaper than the next person paying for it again.

The costliest lesson of the 0.9.0 milestone frames the rest: three rounds of code review and a green
test suite all passed a `forward_mail` that delivered **completely empty emails and destroyed
attachments**. Reading code did not catch it. Sending one email caught it instantly.

---

## 1. Reading code cannot verify a Mail write

Mail's scripting layer lies in ways that only sending reveals. Every write/outbound path must be
exercised on device, and judged by **the resulting message** — its body, its attachment count — not
by the tool's return value.

- Send **only** to `andrei@lav.ren`. Never a third party, in any test, ever.
- Assert the outbox actually **drains** (`count of (messages of outbox)` → 0). `sent: True` proves
  nothing.
- Watch for **passing-count drops**: a fix wave once silently deleted five tests while the suite
  total stayed flat because new tests landed in the same commit. Check `grep -c "^def test_"`.

## 2. Timing: the trap that hid a bug for two days

**Mail's autosave is asynchronous, ~10–15 seconds after the message is created** (#133,
2026-07-26). A check that runs 3 seconds after a delete sees a clean Drafts mailbox and concludes
"no residue" — wrongly. Wait **at least 20 seconds** before asserting a draft is absent.

This single mis-timing produced repeated "cannot reproduce" verdicts on a bug that reproduces 100%
of the time when you wait long enough.

Corollary: `run_osascript` caps a script at **30 seconds**, so a probe that needs a long `delay`
must be run as raw `osascript` from a shell, not through the runtime.

## 3. Outgoing messages

| Fact | Verified |
|---|---|
| Mail autosaves **any** outgoing message into Drafts ~10–15s after creation. Asynchronous, and **unsuppressable** — one-shot `with properties`, post-creation writes, `visible:true`, `visible:false`, and `close … saving no` all still leave a copy. A **successful send litters too**; the copies persist indefinitely (12h+ observed). | #133, 2026-07-26 |
| An outgoing message has **no readable `message id`** — raises **-1700**. The autosaved draft's id is minted at autosave time, so our litter cannot be identified in advance, and any cleanup would have to guess by subject (and could delete a real draft). | #133, 2026-07-26 |
| **A compose window IS an `outgoing message` with 0 recipients.** So "delete every recipient-less outgoing message" would destroy a human's half-written email. Never sweep on that predicate. | #135, 2026-07-26 |
| `delete` **before** `send` works reliably — fresh messages and `forward`-derived alike, leaving no immediate residue. | #135, 2026-07-26 |
| `delete` **after** `send` is a **silent no-op**. Both `delete <ref>` and `delete outgoing message i` return cleanly, remove nothing, and the message delivers anyway. **Never roll back past the `send` verb** — report the leftover instead. | #135, 2026-07-26 |
| A successfully deleted message's reference goes **dead with -1728**. This is the only reliable way to *prove* a delete took; treat any other error as "unknown", never as success. | #135, 2026-07-26 |
| `count of outgoing messages` counts script-session message **objects**, including already-delivered ones — it does not fall back to 0 and is **not** the outbox. Use `count of (messages of outbox)` for the real queue. | #135, 2026-07-26 |
| `send` returning means Mail **ACCEPTED** the message, not that it was delivered. An accepted send can sit in the Outbox for minutes. | 2026-07-25 |
| A message stuck in the Outbox clears when Mail is **quit and reopened** — the stranded entry is in-memory, not on disk. | #135, 2026-07-26 |

## 4. Content and attachments

- **`content` of an outgoing/forwarded message is permanently unreadable** (empty at 0s/1s/4s). Mail
  assembles the quoted original only in its compose UI, at send time.
- **Writing `content` on a forward destroys the attachments.** Verified by real send and real
  inspection: 7 attachments in, **0** out. Untouched, all 7 arrive intact with the full original
  body. This is why `forward_mail` carries no covering-note parameter — there is no way to add one
  without destroying the thing being forwarded.
- `html content` is **write-only** on an outgoing message, and is not a property of a stored message
  at all.
- `to recipients` / `cc recipients` / `sender` **are** readable on a stored inbox message.
- Never `read` a body file directly — `read … as «class utf8»` raises **-39** on a zero-byte file, so
  a subject-only send crashes the script. Use the shared `READ_BODY` handler in `text.py` (empty
  body → empty text).

## 5. Addressing and iteration

- **`whose` is unreliable on the Drafts mailbox** — raised -1728 on a draft that demonstrably
  existed. Address drafts by iterating `message i of dm` and comparing `message id`.
- **Deleting while iterating forward invalidates the reference** (-1728). Always iterate in reverse
  by index: `repeat with i from n to 1 by -1`.
- Mail's default sender is **not** predictable from account order (with 4 accounts, the first is
  `andrei@lavrenov.io` but Mail picks `andrei@lav.ren`). `set sender` **does** work — which is why
  `send_mail` takes `from_address` and the preview never guesses.

## 6. AppleScript language traps

- **`after`, `before`, and `me` are reserved words.** Using them as variable names breaks scripts in
  ways whose error messages point somewhere else entirely — `set mE to …` fails with *"Can't set me
  to …"* (-10003), naming a line you never wrote.
- **`with timeout` is lexical.** It does **not** cover a handler body called from inside it. Every
  handler that talks to Mail needs its own `with timeout` (#56), or a hung Mail can pin an Apple
  Event indefinitely.

## 7. TCC and background agents

- `sample <pid>` works **without** TCC — safe from a launchd agent.
- **Apple Events from a launchd agent do not work.** Background agents get no Automation grant and
  fail instantly, which reads as a false "Mail is hung". Never probe Mail with AppleScript from a
  daemon; the watchdog is deliberately passive (CPU/RSS only).
- Never leave a polling loop pointed at Mail. One orphaned `until … osascript … sleep 4` loop was
  found still hammering Mail after a force quit. Bounded waits only, or let launchd own the cadence
  — one probe per invocation, never `while true`.

## 8. When Mail freezes

Mail **hangs** rather than crashes, so macOS writes no crash report and a force quit destroys the
only evidence.

**Run `~/mail-watchdog/capture.sh` BEFORE force-quitting.** It samples Mail's main-thread stack,
which names the blocking call.
