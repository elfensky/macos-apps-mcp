# Mail triage reads — awaiting-reply / needs-response as ranked Pointers — design

**Issue:** [#68](https://github.com/elfensky/macos-apps-mcp/issues/68) · **Milestone:** 0.7.0 — Differentiators · **Date:** 2026-07-22

## Why

patrickfreyer's `get_awaiting_reply`/`get_needs_response` prove demand for smart-inbox
heuristics, but they return emoji-decorated prose the agent must regex. The same heuristics
emitting **ranked Pointers with a machine-readable `reason`** are novel and far more
agent-usable (survey gap). Two read tools; never write, never scan bodies.

## Contract change

`contracts.Pointer` gains an optional field, mirroring the existing optional `folder`:

```python
    reason: str | None = None  # triage reads only: a stable machine-readable why-string
```

`server._emit` includes it when set:

```python
    if p.reason is not None:
        d["reason"] = p.reason
```

Ranking is conveyed by **list order** (most urgent first) — no separate score field.

## Architecture

Pure, fixture-tested classifier functions over message **records** (dicts); AppleScript only
extracts the records (integration-tested). No message *body* content is read — headers and
scriptable properties only.

> **Adversarial-review corrections (2026-07-22, verified on-device).** The multi-provider
> debate + on-device probes fixed feasibility/heuristic errors in the first draft: (a) Mail's
> `sender` is a display string (`"Jane Doe <jane@x.com>"`), NOT an address — a
> sender∈recipient_addrs join would be **always false**, so addresses MUST be extracted with
> `extract address from`; (b) `was replied to`, `read status`, `flagged status`, `date sent`,
> `to recipients`/`address`, `email addresses of every account`, `sent mailbox` all exist and
> work (a critic's "was_replied_to doesn't exist" was refuted on-device); (c) awaiting-reply's
> fuzzy subject correlation is unreliable (aliases, lists, subject drift, group threads) — so
> it is redesigned to **real header threading** via `all headers` (Message-ID ↔
> In-Reply-To/References, confirmed accessible).

### Extraction (AppleScript, bounded, argv-safe)

Exact AppleScript property → record-key mapping (get the names right — `read status` not
`read`, `flagged status` not `flagged`):

- `_INBOX_TRIAGE` → inbox records, US/RS-framed like `_ATTACHMENTS`, iterating deterministically
  **newest-first** (`message 1 through N of inbox` — `message 1` is newest in current Mail; NOT
  unordered `messages of inbox`), each:
  `{id ← message id, subject, sender ← extract address from (sender of m) (lowercased),
  to_addrs ← address of every to recipient of m (ONE batched Apple Event, lowercased),
  date_received ← epoch (see below), was_replied_to ← was replied to, read ← read status,
  flagged ← flagged status}`. Messages with no stable `message id` are skipped (same rule as
  `_SEARCH`). Bounded to a scan cap (`MAX_MAILS`).
- `_SENT_TRIAGE` → recent sent records from Mail's unified `sent mailbox` (verified "All Sent"),
  newest-first, bounded: `{id ← message id, subject, recipient_addrs ← address of every to
  recipient (batched, lowercased), date_sent ← epoch}`.
- `_INBOX_REFS` (awaiting-reply only) → the set of message-ids the inbox **references**: for
  inbox messages with `date received` **after the oldest candidate sent date** (a date-gated
  window, NOT the 25-item output cap — that cap can't prove "no reply came back"), parse each
  message's `all headers` for the `In-Reply-To` and `References` header values and emit the
  `<message-id>` tokens found. Hard-capped (e.g. 300 messages scanned) with a logged truncation.
- `_MY_ADDRESSES` → the user's own addresses: iterate `email addresses of every account` as a
  framed list (NOT `as string`, which concatenates them). Lowercased.

**Epoch dates:** extracted AppleScript-side as integer seconds via date arithmetic against a
fixed reference date, used **only for comparison/age** (never display), so it's monotonic and
comparison-correct; a DST-boundary case is covered in a unit test. `days` for awaiting-reply is
validated `1 ≤ days ≤ 365` at the tool boundary. All inputs via argv; `with timeout`.

### Tool 1 — `mail_needs_response() -> list[dict]`

Pure `_classify_needs_response(records, my_addrs) -> list[Pointer]`:

- Drop any record whose `was_replied_to` is true (already handled).
- **Directly addressed** = one of `my_addrs` (lowercased) is in `to_addrs`. If `my_addrs` is
  non-empty, keep only direct records. If `my_addrs` is **empty** (extraction failed), do NOT
  flood the inbox — fall back to **flagged-only** (an explicit user signal that needs no
  addressing), so the tool degrades to a small high-confidence set, never "everything".
- Assign one **reason** (stable vocabulary) and a tier, highest first. The direct-To +
  not-replied prefilter already removes bulk/marketing (rarely sent to your exact address as an
  unreplied direct), so these tiers rank an already-relevant set:
  1. `flagged` — the message is flagged.
  2. `unread-direct` — unread.
  3. `unanswered-direct` — read but still unreplied.
- Sort by tier, then most-recent `date_received` first. Bounded to `MAX_MAILS`. (The `?`-in-
  subject "direct-question" tier from the draft is dropped — the debate showed it adds marketing
  noise for little gain over `unread-direct`.)
- Pointer: `id` = message-id, `summary` = `subject — sender`, `deeplink` = `message://…`,
  `reason` = the tier string.

### Tool 2 — `mail_awaiting_reply(days: int = 3) -> list[dict]`

Real header threading — accurate, no fuzzy subject/sender/alias pathologies. Pure
`_classify_awaiting_reply(sent, referenced_ids, days, now) -> list[Pointer]`:

- `days` validated `1 ≤ days ≤ 365`.
- Consider each sent record whose age (`now - date_sent`) is at least `days`.
- A sent message is **replied** iff its `message id` is in `referenced_ids` (the set of
  Message-IDs that inbox messages cite via In-Reply-To/References, from `_INBOX_REFS`).
  Otherwise it is **awaiting-reply**. Message-ids are normalized (strip `<>`, lowercase) on both
  sides before set membership.
- Pointer: `id` = the **sent** message-id (open it to follow up), `summary` = `subject — to
  <recipients>`, `deeplink` = `message://…`, `reason` = stable **`awaiting-reply`**. Sorted
  **oldest-sent-first** (most overdue). Bounded to `MAX_MAILS`.
- Group-thread nuance (documented): a sent message is cleared if **any** recipient's reply
  cites it; per-recipient outstanding tracking is out of scope (the Envelope Index plane, #70,
  is the place for it). The `message://<sent-id>` deeplink resolving from All Sent is verified
  in the integration pass (may need adjustment if it only resolves inbox-scoped).

## Reason vocabulary (stable)

`flagged`, `unread-direct`, `unanswered-direct`, `awaiting-reply`. Fixed strings — a caller can
switch on them. New reasons are additive, never renamed.

## Server tools

Both `@_read_tool` (read-only; Automation for Mail), returning `[_emit(p) for p in …]`.
Classified in the annotation map (`"Automation"`). Both are read tools → they ride the
untrusted-data notice (subjects/senders are attacker-writable) and are audit-exempt (reads).

## Tests

Unit (fixture, no TCC) — the pure classifiers over hand-built record lists. **Fixtures must
reflect the real AppleScript shapes** the debate exposed (else green tests hide a dead feature):

- `_classify_needs_response`: was-replied dropped; direct filter keeps in-`to_addrs`, drops
  not-in-`to_addrs` (cc-only); the three tiers assigned + ordered, recency tiebreak; **empty
  `my_addrs` degrades to flagged-only (NOT everything)**; bounded to `MAX_MAILS`.
- `_classify_awaiting_reply` (header-threaded): a sent message whose `message id` IS in
  `referenced_ids` is suppressed; one whose id is absent is emitted; **message-id normalization**
  (`<Id@x>` vs `id@x`, case) matches on both sides; the `days` threshold excludes too-recent
  sends; oldest-sent-first ordering; bounded. Include a fixture where a same-subject inbox
  message that does NOT reference the sent id does **not** suppress it (proves we're threading on
  ids, not subjects).
- **Address-extraction fixture guard:** a record whose raw `sender` would be a display string
  must never appear in a classifier input — the pure functions consume already-extracted bare
  addresses; add a test asserting the record schema is address-shaped (the display→address
  extraction is AppleScript-side, integration-verified).
- Epoch/date: an age/`date_received > date_sent` comparison across a DST boundary.
- `Pointer.reason` round-trips through `_emit` (present when set, absent when None).
- Server dispatch: `mail_needs_response` / `mail_awaiting_reply` forward and emit reason;
  `days` out-of-range rejected; correctly permission-classified.

Integration (`-m integration`, manual, on-device) — the AppleScript is where the real risk lives
(per the debate): `_INBOX_TRIAGE`/`_SENT_TRIAGE`/`_MY_ADDRESSES`/`_INBOX_REFS` extract
well-formed records against the real mailbox (addresses are bare + lowercased, dates comparable,
newest-first ordering holds); a real sent message with a known inbox reply is correctly
suppressed by `mail_awaiting_reply`; the `message://<sent-id>` deeplink is checked for
resolution from All Sent.

## Out of scope (YAGNI)

Body-content sentiment/urgency scanning; cc-based triage; per-account scoping; a combined
`mail_triage(kind)` tool; per-recipient outstanding tracking on group threads (the Envelope
Index plane #70 is the place for it); a `?`-in-subject "question" tier (debate: marketing
noise). Header threading via `all headers` supersedes the draft's fuzzy subject correlation, so
`Re:`/`Fwd:` prefix folding is no longer needed at all.
