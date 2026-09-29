---
spike: 006
idea: mail-fixes
name: mail-move-budget
type: standard
validates: "Given the 9k+ IMAP mailbox, when `_PRESENT`, `_MOVE` and `_TRASH` run on 1, 5 and 25 ids, then seconds per message (median, p95) are measured for the MAIL-01 timeout formula"
verdict: VALIDATED
related: [005]
tags: [mail, move, trash, timeout, imap, by-id, bulk-read]
---

# Spike 006: What a batch move costs on a large mailbox

## What This Validates

Given Fiction INBOX (9.5k messages, IMAP) and its move destination Fiction Archive (49.5k),
when the scripts behind `move_mail`, `trash_mail` and their dry runs address messages, then
the cost of each Apple Event primitive and of a real batch is measured, so MAIL-01's timeout
rests on numbers.

**Answer: the per-id `whose message id is` scan is the whole cost.** It reads the whole
mailbox every time: about 0.1–0.25 ms per stored message on a healthy Mail, and 5–9× more
in the facts §3c state. The shipped `_MOVE` runs 3 source scans and 1 destination scan per
message, so its cost is `n × (3 × scan(src) + scan(dst))`. For INBOX → Archive that is about
18 s per message, so 25 messages take about 460 s, over the 300 s cap (#206).

**A by-ID act makes the batch almost constant.** Two bulk reads map Message-ID → Mail's
internal id. Each message is then addressed as `«class mssg» id n of mb`, which resolves in
4–12 ms regardless of mailbox size. 25 messages moved and verified in 63 s through the
recoverable plane.

## Research

- #206: audit-log evidence of 10–34 s per message on this mailbox pair, a 25-message move
  lost at 300 s, and a 25-id dry run lost at 30 s. Option 5 there asks whether per-message
  verification can become one batched read.
- `docs/mail-applescript-facts.md` §4c: `message id of every message of mb` is one Apple
  Event and O(mailbox). §3b: Mail's own error text prints the by-ID form
  `message id 41611 of mailbox …`. §3c: in the windowless-delete-no-op state, scripts run
  about 2× slower. §5b: `move <one ref> to dst` works.

| Approach | Primitive | Verdict |
|---|---|---|
| Scale the host timeout with n (MAIL-01 as written) | per-id `whose` scans | works, but 25 messages need ~8 min on a healthy Mail and much more on a sick one |
| Bulk read, then act by index | `message k of mb` | rejected: index access is O(mailbox) too (1.8 s on Archive), and new mail shifts indexes |
| **Bulk read, then act by internal id** | `«class mssg» id n of mb` | **chosen for the prototype**: O(1), and ids do not shift |
| Answer the dry run from the Envelope Index (#206 option 3) | sqlite | not measured here; the index lags Mail (#174) |

## How to Run

```sh
cd .planning/spikes/006-mail-move-budget
uv run python probe_budget.py scan     # read-only: whose/bulk cost on 7 mailboxes
uv run python probe_budget.py rescan   # read-only: every primitive, INBOX + Archive
uv run python probe_budget.py present  # read-only: shipped _PRESENT on 1/5/25 ids
uv run python probe_move.py            # WRITES: 34 real moves, owner-approved
```

`probe_move.py` moves the oldest questionablequesting.com alerts from Fiction INBOX to Fiction
Archive: shipped `_MOVE` on 1 and 3, the by-ID prototype on 5 and 25, then `undo` of the
1-message receipt and a by-ID re-archive of it. Every batch goes through `recoverable()`
(backup, receipt, verify). Run it with the Mail watchdog on.

## What to Expect

Timings per primitive and per batch. Every batch line ends `"statuses": {"ok": n}` and
carries a receipt that `mail_undo` accepts.

## Investigation Trail

1. **Found the mailboxes.** #206's 9,122-message inbox is Fiction INBOX (now 9,458); its
   destination is Fiction Archive (49,531). Fiction Trash is empty.
2. **Scan cost by size (first pass).** One `whose message id is` count: 0.02 s at 8 messages,
   4.6 s at 4.4k, 8.7 s at 9.5k, 60 s at 49.5k. Linear. Hit and miss cost the same, and the
   message's position does not matter: every scan reads the whole mailbox. One bulk
   `message id of every message` cost the same as one scan.
3. **The model disagreed with #206.** It predicted ~86 s per message for INBOX → Archive;
   #206 logged 10–15 s. Mail had been in the facts §3c state since spike 005 (6 windowless
   messages that survived `delete`).
4. **Restarted Mail (owner-approved) and re-measured.** Every timing fell 5–9×, not the 2×
   facts §3c reports: INBOX scan 0.9–2.5 s, Archive 10.9–14.4 s. Healthy numbers fit #206.
5. **Looked for an O(1) primitive.** Bulk internal ids (`id of every message`) cost 6–7× less
   than bulk Message-IDs. Access by index is still O(mailbox) (0.17 s / 1.8 s). `whose id is
   n` is O(mailbox) too. The by-ID reference `«class mssg» id n of mb` resolved in 0.012 s on
   INBOX and 0.004 s on Archive, and returned the right message both times. (The English
   `message id n` parses as the `message id` property; the raw class code avoids that.)
6. **Duplicates exist.** The Archive's median sample had 3 copies of one Message-ID. A by-ID
   act moves one copy, so the prototype refuses a target with more than one copy in the
   source; the destination is checked as a count increase, not presence.
7. **Real moves (owner-approved), healthy Mail.** 34 messages, all `ok`, receipts complete
   (`plan` + `done`). End state checked in the Envelope Index: 34 in Archive, 0 in INBOX.
8. **Dry run.** Shipped `_PRESENT` on 25 ids: 22.8 s, under the 30 s default host timeout
   with ~7 s to spare. At the §3c slowdown it needs minutes, which is #206's dry-run failure.
9. **Memory.** Mail's RSS rose to about 1.5 GB during the Archive bulk reads and stayed near
   1.4–1.6 GB while idle afterwards.

## Results

**Verdict: VALIDATED.**

Primitive cost (healthy Mail, `results-rescan.json`):

| Primitive | Fiction INBOX 9.5k | Fiction Archive 49.5k |
|---|---:|---:|
| `whose message id is` count | 0.9–2.5 s | 10.9–14.4 s |
| bulk `message id of every message` | 0.9 s | 11.2 s |
| bulk `id of every message` | 0.17 s | 1.5 s |
| `message k of mb` (index) | 0.17 s | 1.8 s |
| `first message whose id is n` | 0.18 s | 2.0 s |
| **`«class mssg» id n of mb` (by-ID)** | **0.012 s** | **0.004 s** |

The §3c-state first pass (`results-scan.json`) is kept as the slow-state reference: the same
scans cost 8.7 s and 60 s.

Batches, INBOX → Archive (healthy Mail, `results-move.json`):

| Batch | Path | Wall | Per message |
|---|---|---:|---:|
| 1 | shipped `_MOVE` | 35.3 s | 35.3 s |
| 3 | shipped `_MOVE` | 53.5 s | 17.8 s |
| 25 | shipped `_MOVE` (extrapolated, not run) | ~460 s | ~18 s |
| 5 | by-ID prototype | 32.4 s | 6.5 s |
| 25 | by-ID prototype | 62.8 s | 2.5 s |
| 1 | `undo` (shipped, Archive → INBOX) | 35.4 s | — |
| 1 | by-ID re-archive | 14.6 s | — |

By-ID batch of 25, by phase: source bulk read 2.8 s, Archive bulk read before 11.5 s, the 25
moves 30.4 s (about 1.2 s each: the IMAP move itself), Archive bulk read after 17.0 s.

Shipped `_PRESENT` (dry run), Fiction INBOX: 1 id 2.2 s, 5 ids 5.0 s, 25 ids 22.8 s.

**Signal for the build (Phase 02.1, MAIL-01)**

- **A timeout that scales with n is a patch, not a fix.** The per-message cost is set by the
  mailbox sizes (source × 3 + destination), not by the batch, and by Mail's health (5–9×).
  If the scripts keep the per-id `whose`, the budget must be computed from both mailbox
  sizes (the Envelope Index has the counts) with a health margin, and it still reaches
  minutes.
- **The by-ID act removes the scaling.** Bulk-read the source (Message-ID + internal id),
  act on `«class mssg» id n`, prove each source reference dead (-1728), and check the
  destination as a count increase from one bulk read before and after. Cost ≈ 2 bulk reads
  of the destination + 1 of the source + ~1.2 s per move.
- **Duplicates need a rule.** A by-ID act moves one copy; `whose` moved every copy. Decide
  per op (move all copies, or refuse), and keep the destination check as an increase.
- **The dry run can use the same bulk read.** One source bulk read answers presence for all
  25 ids at once (0.9 s on INBOX), instead of 25 scans (22.8 s).
- **Record in `docs/mail-applescript-facts.md`:** the by-ID form and its raw-class spelling;
  scan cost ≈ 0.1–0.25 ms per stored message on a healthy Mail; the §3c slowdown measured at
  5–9×; index access is not O(1).
- **Undo inherits the cost** of whichever act `move_mail` uses, because `undo` replays through
  `move_mail`. With the by-ID act, a 25-message undo from Archive needs one 11 s bulk read of
  Archive, not 75 scans of it.

**Not tested**

- `_TRASH` with real messages: its source cost is the same scan; its destination (Fiction
  Trash) is empty, so the model predicts ~3 source scans per message. Not run.
- The by-ID act on a cross-account move, and on a Gmail label mailbox.
- A shipped 25-message move and a 25-message shipped undo: predicted at ~8 min and
  ~25 × (3 × 12 s + 1 s) ≈ 15 min; not run by agreement.
- Whether Mail's 1.5 GB RSS after the Archive bulk reads is released later, or grows with
  repeated reads.
