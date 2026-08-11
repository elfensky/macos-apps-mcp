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

## 3b. You cannot script-send a stored draft

Verified 2026-08-05 (#157), against a real draft in the Drafts mailbox. This killed the
obvious implementation and shaped the one that shipped.

| Fact | Detail |
|---|---|
| **`send <message in the Drafts mailbox>` raises -1708** — *"message id 41611 of mailbox \"Drafts\" of account id … doesn't understand the “send” message"*. | `Mail.sdef` declares `send` with a `direct-parameter type="outgoing message"` and means it; a stored draft is a `message`. This is the rare case where the dictionary is honest. |
| **`open <draft>` DOES open a real compose window — and AppleScript never sees it.** `count of outgoing messages` stays 0 before and after, while `name of every window` shows the compose window plainly. | So there is no object to hand to `send`. A window Mail opens itself is not a scripting object; the compose window `make new outgoing message` creates IS one. That asymmetry is the whole reason the `open`-then-send route is dead. |
| Everything a rebuild needs IS readable off a stored draft: `subject`, `content` (unlike an outgoing message, whose content is permanently unreadable — §4), `sender` as `"Name <addr>"`, `to`/`cc`/`bcc recipients`, `count of mail attachments`, and `all headers`. | So the only mechanic left is **rebuild from the draft's own stored bytes and send that**, which is what `send_mail(draft_id=…)` does. `set sender of msg to "Andrei Lavrenov <andrei@lav.ren>"` — the display form Mail itself reports — is accepted. |
| A rebuild silently loses **attachments** and **In-Reply-To/References**. | `make new outgoing message` carries no attachments and cannot set headers (§6), so a reply draft would arrive detached from its thread. Both are detectable before sending (`mail attachments` count, `all headers contains "In-Reply-To:"`), so `send_mail(draft_id=…)` **refuses** those two cases instead of degrading them. |

## 3c. The autosave litter is real but NOT universal

Measured 2026-08-05 across four real sends through the outbound plane, counting the
Drafts mailbox before and 45–60 s after each (well past the ~10–15 s autosave window):

| Send | Drafts delta |
|---|---|
| `send_mail(draft_id=…)` — `_SEND` with plain `content` | **-1** (its source draft removed; no copy left) |
| `reply_all` — Mail's native `reply` verb | **0** |
| `forward` — Mail's native `forward` verb | **0** |
| `send_mail(html=True)` — `_SEND` writing `html content` | **+1** |

So #133's "a successful send litters too" is **not** something to count on in either
direction — it happened on one of four. Nothing here changes the posture: a dry run
still constructs nothing (that is the only guarantee), and `drafts()` + `delete_draft()`
are still the sweep. Do not "optimise away" the sweep on the strength of three clean
runs.

## 3d. Send Later has NO scripting surface (#84)

Verified 2026-08-11. The feature is real in the app and its mailbox is real on this Mac —
`local://A2025935-…/SendLater`, with an `Info.plist` and an entry in the Envelope Index —
which is what makes this look reachable. It is not.

| Fact | Detail |
|---|---|
| `Mail.sdef` contains **zero** occurrences of "send later", "deferred" or "schedul". The `outgoing message` class has **no date property at all** — its entire surface is `sender`, `subject`, `content`, `visible`, `message signature`, read-only `id`, and the two deprecated no-ops. | The only `type="date"` properties in the whole dictionary are `date received` and `date sent`, both `access="r"`, and both on `message`, not `outgoing message`. |
| **`send` takes no date.** `<command name="send"><direct-parameter type="outgoing message"/><result type="boolean"/></command>` — one parameter, no optional arguments. | So there is no place to put a time even if one were accepted. |
| Runtime, against a real outgoing message, all three spellings refused: `set sendLaterDate of m` → **-1700** *"Can't make sendLaterDate of outgoing message into type specifier"*; `set send date of m` → **-10006**; the raw four-char form `set «class sndL» of m` → **-10006**. | This is the case where the dictionary is HONEST. Compare `html content` (§4), which lies — but note that one is **declared** in the sdef and merely mis-described. An UNDECLARED Cocoa key has no four-char code, so AppleScript cannot build a specifier for it and no Apple Event can carry it. Declared-but-lying and undeclared are different failure classes; only the first can surprise you. |
| The mechanic exists entirely inside the compose back-end. `strings` on Mail: `_sendLaterDate` (`T@"NSDate",&,N,V_sendLaterDate`), `deliverMessageWithSendLaterDate:completionHandler:`, `generateAndSendMessageWithSendLaterDate:sendingProgress:completionHandler:`, `appendMessageToSendLaterQueue:sendLaterDate:`, `_initializeSendLaterStore`, `_presentSendLaterDatePicker`. | The date is a **parameter of the send/deliver call**, held by a separate send-later store. It is not a property of any object AppleScript can reach. |
| **The mailbox is a MIRROR, not the queue.** Mail's own log line: *"Appending **placeholder** message with ID:%@ to the sendLater mailbox for send later date:%@"*. | So a message you put in `SendLater` yourself has no entry in the send-later store and carries no date. The mailbox contents are a display of the schedule, not its cause. |
| `move`ing a real draft into `SendLater` **succeeds** and then does nothing. Device-probed with a draft addressed to the operator: the move verified (source empty, destination 1), and the message simply sat there — Outbox stayed 0 and nothing was sent. | The back door is reachable and inert — watched for 11 minutes (14:53→15:04), Outbox 0 throughout, no crash reports. It was never going to be more than that: even a mailbox that Mail *did* act on gives no channel to say **when**, and "when" is the entire feature. |
| Moving back **out** of `SendLater` works, but only to a CONCRETE mailbox url. `move … to "drafts"` — the unified accessor — returned cleanly and moved nothing, twice; the same move to `imap://<uuid>/Drafts` succeeded first try. | Not a `SendLater` property: the unified accessor is the part that failed. `move_mail`'s post-verify caught it and reported `status: ERROR`, so it was loud rather than silent — the #135 discipline working. On My Mac has no `Trash` mailbox at all, so `trash_mail` on a `local://` message correctly refuses (#80). |

**Consequence for #84.** Both branches of its sketch are closed. Native Send Later via
AppleScript does not exist, and the fallback ("create a draft now, send it later") inherits
§3b's two refusals — a draft carrying **attachments** and a **reply/forward** draft — because
a scheduled send would have to go through the same rebuild `send_mail(draft_id=…)` does.
A scheduled send that cannot carry an attachment and cannot stay in a thread is a different
product from the one the issue imagines, and must not be shipped under that name.

## 4. Content and attachments

- **`content` of an outgoing/forwarded message is permanently unreadable** (empty at 0s/1s/4s). Mail
  assembles the quoted original only in its compose UI, at send time.
- **Writing `content` on a forward destroys the attachments.** Verified by real send and real
  inspection: 7 attachments in, **0** out. Untouched, all 7 arrive intact with the full original
  body. This is why `forward_mail` carries no covering-note parameter — there is no way to add one
  without destroying the thing being forwarded.
- `html content` is **write-only** on an outgoing message, and is not a property of a stored message
  at all. **It also WORKS**, despite `Mail.sdef` declaring it `hidden="yes"` with the description
  *"Does nothing at all (deprecated)"* — verified 2026-08-05 by a real `send_mail(html=True)` to
  `andrei@lav.ren`: the HTML body arrived and rendered. So the dictionary lies in the *pessimistic*
  direction too, and a "the sdef says it's a no-op, let's rip it out" cleanup would have broken a
  working feature. Prove it either way before acting on that file.
- `to recipients` / `cc recipients` / `sender` **are** readable on a stored inbox message.
- Never `read` a body file directly — `read … as «class utf8»` raises **-39** on a zero-byte file, so
  a subject-only send crashes the script. Use the shared `READ_BODY` handler in `text.py` (empty
  body → empty text).

### 4b. Saving an attachment (#81)

Verified 2026-08-05 against real messages. `mail attachment` is entirely read-only in
`Mail.sdef` but declares `<responds-to command="save">` — and unlike most of that file, **this one
is true**. Three of the four things probing found are not in the dictionary at all.

| Fact | Detail |
|---|---|
| `save <mail attachment> in (path as POSIX file)` **works**, writing to the exact path given (it is a FILE, not a target directory). The saved bytes are the real thing — a 192,250-byte PDF opened as *"PDF document, version 1.5, 2 pages"*. | It does **not** need the message open, or a window, or Mail in the foreground. |
| **It OVERWRITES SILENTLY.** A 0-byte placeholder at the destination came back holding the full 192 KB, with no error. | So "never overwrite" cannot be enforced in AppleScript — `mail_files.target_path` refuses in Python, before the Apple Event. |
| **Saving a NOT-downloaded attachment makes Mail FETCH the whole message**, synchronously. It does not fail and it does not write an empty file. | All seven attachments on one `.partial` message flipped to `downloaded=true` in the same call. So this is a network operation, not a read — hence `_SAVE_TIMEOUT = 300`, not the 30 s default. |
| **`file size` on a not-yet-downloaded attachment is the ENCODED estimate, not the byte count.** The same attachment reported 14,509 before the fetch and 8,755 after. | A size cap therefore over-refuses by roughly 4/3 on undownloaded attachments. That is the safe direction, and it is why the written file is `stat`ed afterwards rather than trusted. |
| A missing destination DIRECTORY raises **-10000** and writes nothing. | `mail_files.resolve_dest` creates it first, inside the allowlisted root. |
| `id of <mail attachment>` is a **MIME part path** — `"2"`, `"1.12"`, `"1.14"` — unique within its message and derived from the message's own structure. | The NAME is not unique (`image001.jpg`…`image005.png` on one real message), so the id is what addresses an attachment when a name is ambiguous. |

Not provable on device, so handled defensively regardless: whether Mail's `name` can carry `/`,
`..`, a NUL or a bidi override. Crafting such an attachment needs hand-rolled MIME, and the
Python-side sanitiser is correct whatever Mail does — an attachment name arrives from whoever sent
the mail, so it is treated as hostile unconditionally. See `mail_files` and
`tests/test_mail_files.py`.

### 4c. `.partial.emlx` means NO ATTACHMENTS, not "no body" (#119)

Verified 2026-08-06, by classifying **all 22,748 `.partial.emlx` on this Mac** and by comparing
on-disk bytes against what Mail returns after a full fetch. This killed #119's entire premise:
the "63% of bodies are not local, download them" story was wrong, and the feature it specified
would have spent hours and GB to gain 99 messages.

| Fact | Detail |
|---|---|
| **A `.partial.emlx` carries a complete, extractable body 99.47% of the time.** Full-store census: 22,627 body_ok · 99 genuinely body-stubbed (0.44%) · 13 attachment-only with no text part · 9 with no `Message-ID` (unindexable by our citation contract, not by Mail's). | So the ~62% "coverage gap" `body_coverage()` used to report was **the indexer's own filename filter**, not missing bytes. `build_body_index` skipped `*.partial.emlx` and hid two thirds of the store from `mail_search(body=…)`. |
| **The body in the partial is BYTE-IDENTICAL to the body after a full fetch.** Not inferred — measured: extract body from the on-disk partial, read `source` of the same message over IMAP, extract again, compare. 7 of 7 identical, including a **27 MB** message whose 2,131-char body was already complete in its 17 KB partial. | What the partial omits is the attachment parts, which sit there as empty MIME parts carrying `X-Apple-Content-Length: <n>`. That header is the tell: the *shape* of the message is local, the attachment *payload* is not. |
| **Reading `content` does NOT fetch and does NOT fill the file.** Returned 5,795 chars in 1.0 s off a partial and the file was still `.partial.emlx` at the same size 30 s later. | #119's specified mechanism ("reading `content of message` forces Mail to fetch from IMAP; the `.emlx` then fills in") is simply false. |
| **Reading `source` DOES fetch the whole message** — 130,092 chars off a 50 KB partial, and 27 MB in 2.9 s off a 17 KB one — but it persists **unreliably**. Controlled probe on `Legal` (10 fetched vs 10 untouched control, re-checked at 120 s): **treatment 2/10 converted `.partial`→full, control 0/10.** | So `source` is a real trigger but a ~20%-per-2-min one, and Mail *also* converts partials on its own in the background (the store-wide partial count drifts down while nothing is running). Never attribute a conversion to your own script without a control group. |
| When a partial does fill in, the **ROWID is unchanged** — `4566.partial.emlx` → `4566.emlx`. And the size barely moves (22,477 → 22,514 bytes; one went *down*, 7,348 → 7,313). | Confirms the flip is bookkeeping plus attachment bytes, not a body arriving. It also means `indexed_files` (keyed by path) re-reads the filled-in file for free, and the `DELETE FROM bodies WHERE message_id` before insert stops it double-counting. |
| `messages.ROWID` in the Envelope Index **is** the `<n>` in `<n>.emlx` / `<n>.partial.emlx`, and the path encodes account UUID + mailbox. | So partial-vs-full is a pure filesystem question and scoping needs no Mail launch — confirmed, and still true. |

Cheap and safe by comparison: **`message id of every message of mb` is one Apple Event and O(mailbox)** — 161 ids in 0.7 s — and returns ids **without** angle brackets, while the Envelope Index stores them **with**. Normalise before joining. This is the fast way to map index-position → message without ever touching `whose` (§8b, and the ~56 s/set scan cost in `dedupe.py`).

## 5. Addressing a mailbox by name

Verified 2026-07-31 (#146), probing every branch against real accounts.

| Fact | Detail |
|---|---|
| `mailbox "<path>" of account` takes the mailboxes.url path **DECODED**, with `/` separators. | `mailbox "[Gmail]/Spam" of acct` → 80 messages. The encoded spelling `"%5BGmail%5D/Spam"` does **not** resolve — this is the same decoded-vs-encoded split as #144, from the other side. |
| `name of <mailbox>` returns the **LEAF ONLY**, never the path. | Spam's name is `"Spam"`, and `mailbox "Spam" of acct` then **fails** — the nesting lives in `container`, so a name read back from Mail is not a usable address. Round-trip the url, never a name. |
| `mailboxes of <account>` returns the account's mailboxes **flat**, nesting erased. | So "find the mailbox named X" cannot distinguish `[Gmail]/Drafts` from a user folder `Drafts`. |
| An account is addressable by `first account whose id is "<uuid>"` — the uuid is exactly the segment in mailboxes.url. | Unknown uuid raises `Can't get account 1 whose id = …`, unknown folder raises `Can't get mailbox "Nope" of account …`. Both fail loudly; neither silently falls back to another mailbox. |
| **On My Mac mailboxes hang off the APPLICATION, not an account** — `mailbox "Outbox"` inside `tell application "Mail"`. | `every account` never lists that store, so its `local://` uuid would never resolve through the account path. It needs its own branch. |
| A mailbox reference **returned from a handler survives the `tell` boundary** and is usable in the caller's own `tell` block. | Verified against a real filed message: `set mb to my mailboxFor(…)` outside, `messages of mb whose message id is mid` inside. This is what lets one shared resolver serve every id-addressed script. |

## 5b. Creating, moving and deleting mailboxes

Verified 2026-08-03 (#78/#159), probing every branch against real accounts. **Three of
these contradict what `Mail.sdef` reads like** — the dictionary is not the device.

| Fact | Detail |
|---|---|
| **`move {a, b, c} to mb` — an AppleScript LIST — raises -1700 and moves NOTHING.** | `Can't make {…} into type specifier`. The `list="yes"` direct parameter that makes a batch look like one Apple Event is inside a **commented-out block** of `Mail.sdef`; the live definition is a singular `type="specifier"`. `whose message id is in {…}` fails identically. So a batch is **N events in one script**, never one event — which is what the 25 cap and the raised host-side timeout exist for. The failure was atomic: 0 of 3 moved. |
| `move <one ref> to dst` and `move (messages of src whose message id is "…") to dst` both work. | The `whose` form re-evaluates per iteration, so it is immune to the moved-out-of-the-collection reference rot in §6. |
| **A cross-account `move` is a TRUE move: source 0, destination 1, stable after 45s and in the Envelope Index.** | Mail.app's own UI **drag** copies — that is where #140/#153's ~3.9k duplicates came from — but the `move` verb does not. So there is no copy → verify → delete-source dance to build. Verify anyway: `move` on a 0-match `whose` is a silent no-op. |
| `make new mailbox with properties {name:"a/b"}` **auto-creates the missing parent**, at application level and via `at end of mailboxes of <account>`. | So nesting needs no per-level loop. |
| It returns **`missing value`** — there is nothing to read the new mailbox's address back from. | Combined with "the `mailbox` class has no url property" and "the Envelope Index does not know it exists until Mail syncs", all three possible sources are blind. The address must be **synthesised** (`<scheme>://<uuid>/<name>`), which works because the path is percent-DECODED before use. |
| **`make new mailbox at <account> …` (the bare `at acct` form) raises a coercion error AND CREATES THE MAILBOX ANYWAY.** | Reports failure, leaves a folder behind. Only the `at end of mailboxes of <account>` form is safe. |
| `mailboxes of <account>` omits container-only parents. | Creating `a/b` over IMAP makes `a` a `\Noselect` folder; `mailboxes of acct` then lists `b` (with `container` → `a`) and never `a`. Refines §5's "returns flat": it is **leaves plus selectable top-level**, not everything. |
| **`delete <mailbox>` is NOT scriptable — -10000 (`AppleEvent handler failed`) in every form**, by name, by `first mailbox whose name is …`, on a local or an account mailbox. | So `create_mailbox` has no scripted undo; removing a mailbox is a Mail.app UI action. Do not build a delete_mailbox tool against this. |
| Opening a backup `.eml` whose Message-ID is **still in the store** is a silent no-op — no window, no error. | Mail dedupes by Message-ID. So "the backup won't open" reads as a corrupt-file failure when the file is perfect. Verify a backup by rewriting its Message-ID first; with a fresh id both a full and a `.partial`-derived `.eml` open normally. |

## 5c. Deleting a message — and why there is no permanent delete

Verified 2026-08-05 (#80), against real messages in `Personal/macos-apps-mcp-test`. **Four of
these contradict `Mail.sdef`**, and together they cut a scoped feature: a targeted permanent
delete cannot be built.

| Fact | Detail |
|---|---|
| `delete <message>` in an ordinary mailbox is a **MOVE TO THAT ACCOUNT'S TRASH**, and the message stays addressable there. | Source 1→0, Trash 0→1, and `messages of trash mailbox whose message id is …` finds it afterwards. This — not any erase verb — is what `trash_mail` is built on. |
| **`delete` is ASYNCHRONOUS on the source side.** At t0 the source still counts the message; it clears by t3. The Trash side is populated immediately. | Measured t0/t3/t10 in one script: `t0 src=1 trash=1`, `t3 src=0 trash=1`. So a delete must be verified by **present-in-Trash** (immediate and reliable), never by absent-from-source at t0 — the opposite of `move`, which verifies synchronously on both sides. Verifying a delete the way `move_mail` verifies a move reports a clean failure on a delete that worked. |
| **`delete` on a message ALREADY IN TRASH is a silent no-op.** | Both `delete (first message of mb whose …)` and the collection form `delete (messages of mb whose …)` return cleanly and remove nothing; the message is still in Trash 5s later. Re-verified on a freshly restarted, healthy Mail after the first run overlapped a crash window. **Trash is terminal for AppleScript.** |
| **`set deleted status of <message> to true` raises -609 (`Connection is invalid`)** — on a healthy Mail, in a mailbox whose store is open, where READING the same property on the same message succeeds. | `Mail.sdef` line 577 declares `deleted status` with no `access="r"`, i.e. writable. It is not. The read/write asymmetry is the tell: `read deleted status=false` then `write ERROR -609` in consecutive statements. |
| **`delete` returning cleanly and removing NOTHING is a symptom of a SICK Mail, not a property of the verb** (#164, resolved 2026-08-06). The 2026-08-05 evidence — 2 of 10 sets dropped, ~56 s per set — was collected in a session that took **19 crashes** and spent time in the §8b crash-loop. Re-measured on a freshly restarted Mail: **0 failures in 232 delete-observations**, and ~50x faster. | Two arms, both on 2026-08-06. FAST: 200 deletes in a 10-message mailbox, 0 reported failures and **0 silent drops** against an independent post-count, 0.57 s each. SLOW: 32 sets in `Personal/Gaming` — the very mailbox #164 was found in, 3,454 messages — 32/32, **0.98 s per set against the 56 s baseline**. The clincher: the one message that had failed TWICE (`1bc5d9cb…`, still 2 copies a day later) collapsed in ~1 s in that run. Nothing about the message, the mailbox or the batch size ever predicted it; Mail's process health did. |
| So the mitigation is **restart Mail, then re-run** — not a code change, and above all not a retry loop. | **Never "fix" this with a retry loop inside the script** (facts §8: bounded waits only) — retrying belongs at the CLI, where re-running IS the retry and a human is watching. What earns the trust is the VERIFICATION, which was never the weak part: all 3 historical drops were caught and reported as `ERROR expected 1 copy to survive but 2 remain`, and the 2026-08-06 arms add 232 observations with zero silent drops. A dropped delete is loud and is a no-op — never a wrong delete. |
| `Mail.sdef` has **no `erase` and no `expunge` command** at all. The full verb list is GetURL, bounce, check for new mail, delete, duplicate, extract address/name from, forward, import Mail mailbox, mailto, move, perform mail action with messages, redirect, reply, send, synchronize. | With `delete`-in-Trash a no-op, `deleted status` unwritable and no erase verb, **there is no scriptable targeted permanent delete.** Emptying Trash stays a human act in Mail.app — which is also why `empty_trash` was cut from #80. Do not build a permanent-delete tool against this; prove it changed before trying again. |
| **`trash mailbox of <account>` raises -1728 for EVERY account**, although `Mail.sdef` declares it on the account class (line 406) exactly like `drafts mailbox`/`sent mailbox`/`junk mailbox`. | Only the APPLICATION-level `trash mailbox` works, and it is the unified **"All Trash"** across accounts. So an account's own Trash cannot be read from Mail; get it from the Envelope Index (`mailboxes.url`), whose per-account spellings differ — `…/Trash` (IMAP), `…/Deleted%20Messages` (iCloud), `…/%5BGmail%5D/Trash` (Gmail). |
| **`move` OUT of the unified `trash mailbox` accessor does the move and then CRASHES Mail** — and the caller hangs, host-side timeout and all. | The messages did land in the destination (verified in the index afterwards), then Mail died with the §10 assertion and the `run_osascript` call never returned — an MCP client aborted it at **1800s**, far past `_MOVE_TIMEOUT=300`. A dead Mail mid-Apple-Event does not surface as a timeout. So an undo must move back **from the message's own account Trash url**, read out of the index, never from the unified accessor. Counting through the unified accessor is fine; moving through it is not. |

## 5d. Cross-account copies are the SAME message with DIFFERENT bytes (#153)

Verified 2026-08-06 over all 3,948 cross-account duplicate sets on this Mac, plus a
400-set body comparison and a negative control. This killed #153's inherited identity
rule.

| Fact | Detail |
|---|---|
| **`size + date_sent` — #140's byte-identity gate — agrees on only 1.2% of cross-account sets.** 1.1% of the 3,926 Google+Personal ones. | `date_sent` matches essentially always (it is a header); `size` almost never does. Gmail rewrites headers in transit (`X-GM-*`, extra `Received:`) without touching a word of the content. #140's gate is right *within* one mailbox, where every copy came off one server — it does not survive the crossing. Gating #153 on it would have shipped a cleanup that declines 99% of the garbage it exists to remove. |
| **The extracted BODY matches on ~100%** — 397/397 Google+Personal sets in a 400-set sample, every copy readable. | And it is local, thanks to #119: a `.partial.emlx` holds a complete body 99.47% of the time, so this needs no IMAP. Sets where the bodies genuinely differ are real (33 of 3,948) and are exactly the forwarded/edited copies #153 said must never be collapsed. |
| **A body hash is NOT an identity on its own.** Negative control over 792 distinct Message-IDs: 784 distinct hashes, i.e. **6 real collisions** — all bulk-sender templates (the same newsletter sent twice). | So Message-ID stays the key and the hash is only ever the CONFIRMATION on copies that already share one. Run the control before trusting a 100%: a broken extractor returning a constant looks identical to a perfect match rate. |
| A cross-account delete lands the loser in **its own account's Trash**, and does not perturb the keeper. Verified per message on two accounts, and **re-checked after an IMAP round and a full Mail quit+relaunch**. | Google: loser left `[Gmail]/All Mail` for `[Gmail]/Trash`, keeper untouched in Personal — so the archive-vs-trash suspicion is answered, deleting a Gmail label copy did NOT remove the message elsewhere. iCloud: loser left `Sent Messages` for `Deleted Messages`, its own spelling. |
| A loser **already in a Trash mailbox must not be targeted at all**. | §5c: `delete` on a message already in Trash returns cleanly and removes nothing. Targeting them manufactures guaranteed failures that read exactly like #164's dropped deletes — and the copy is already where a delete would put it. The first cross-account dry run turned up 6 of these. |
| The two planes disagree on Message-ID spelling and **the mismatch fails SILENTLY**: sqlite stores `<a@b>`, AppleScript's `message id` reports `a@b`. | Feeding index ids straight to the delete/verify scripts matched nothing and reported every keeper missing — no error, just a pass that did nothing and a verification that cried wolf. Normalise with `mail_addressing.bare_id` at the boundary. Caught on device; a green suite did not. |

## 6. Addressing and iteration

- **`whose` is unreliable on the Drafts mailbox** — raised -1728 on a draft that demonstrably
  existed. Address drafts by iterating `message i of dm` and comparing `message id`.
- **Deleting while iterating forward invalidates the reference** (-1728). Always iterate in reverse
  by index: `repeat with i from n to 1 by -1`.
- Mail's default sender is **not** predictable from account order (with 4 accounts, the first is
  `andrei@lavrenov.io` but Mail picks `andrei@lav.ren`). `set sender` **does** work — which is why
  `send_mail` takes `from_address` and the preview never guesses.

## 7. AppleScript language traps

- **`st` is a reserved word** — the ordinal suffix, as in "1st". `set st to "x"` fails with
  *"Expected expression but found “st”"* (-2741) at a character offset that points at the
  assignment and explains nothing. Caught 2026-08-03 by running `move_mail` for the first time,
  after a green 1,024-test suite had passed the script; a scratch variable named `st` in three
  new scripts was the whole bug. Add it to the list below and use `outcome`.
- **`after`, `before`, `at`, and `me` are reserved words.** Using them as variable names breaks
  scripts in ways whose error messages point somewhere else entirely — `set mE to …` fails with
  *"Can't set me to …"* (-10003), naming a line you never wrote, and `repeat with at in (mail
  attachments of m)` fails with *"Expected variable name or property but found parameter name"*
  (-2741), naming nothing useful (`at`, 2026-07-31).
- **`with timeout` is lexical.** It does **not** cover a handler body called from inside it. Every
  handler that talks to Mail needs its own `with timeout` (#56), or a hung Mail can pin an Apple
  Event indefinitely.

## 8. TCC and background agents

- `sample <pid>` works **without** TCC — safe from a launchd agent.
- **Apple Events from a launchd agent do not work.** Background agents get no Automation grant and
  fail instantly, which reads as a false "Mail is hung". Never probe Mail with AppleScript from a
  daemon; the watchdog is deliberately passive (CPU/RSS only).
- Never leave a polling loop pointed at Mail. One orphaned `until … osascript … sleep 4` loop was
  found still hammering Mail after a force quit. Bounded waits only, or let launchd own the cadence
  — one probe per invocation, never `while true`.

## 8b. Walking every mailbox crashes Mail

Verified 2026-08-05 (#80), 19 crashes in one probing session. A script shaped like

```applescript
repeat with a in accounts
  repeat with mb in (mailboxes of a)
    count of (messages of mb whose message id is mid)   -- "where does this message live?"
```

forces Mail to open a message **store** per mailbox, and on a store it cannot open it aborts:
`+[MFLibrary defaultLibrary]` → `NSAssertionHandler` → `objc_exception_throw` → `abort()`,
**SIGABRT on the `MFMailbox.storeCreationQueue`** (`-[MFIMAPAccount storeForMailbox:]` →
`-[MFLibraryStore initWithMailbox:readOnly:]`). Wrapping each count in `try` does not help — the
abort is on Mail's own queue, not in the Apple Event.

Two consequences, both bought the hard way:

- **Mail then CRASH-LOOPS.** Once it has aborted, every later store access re-aborts: reading
  `name of every account` still works while `count of messages of inbox` raises -609, and
  `first account whose id is …` raises -10000. It reads exactly like broken permissions or a
  corrupt index — the Envelope Index passed `PRAGMA integrity_check` throughout. Only a **full
  quit + relaunch** clears it; relaunching into the same state does not.
- **This is why "sqlite locates, AppleScript acts" is a rule and not a preference.** Answering
  "which mailboxes hold this Message-ID?" is an Envelope Index query
  (`query_message_locations`), and it costs one read with no Mail launch. The AppleScript
  spelling of the same question is what took Mail down.

Corollary for probes: address the **specific** mailboxes an operation touches, by account id and
path through `mailboxFor`. Never enumerate `mailboxes of <account>` to find something.

## 9. When Mail freezes

Mail **hangs** rather than crashes, so macOS writes no crash report and a force quit destroys the
only evidence.

**Run `~/mail-watchdog/capture.sh` BEFORE force-quitting.** It samples Mail's main-thread stack,
which names the blocking call.
