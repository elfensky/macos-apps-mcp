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
scriptable properties only, within existing bounds (`MAX_MAILS = 25`).

### Extraction (AppleScript, bounded, argv-safe)

- `_INBOX_TRIAGE` → inbox records, framed with US/RS control chars like `_ATTACHMENTS`:
  `{id (message-id), subject, sender, to_addrs (list), date_received (epoch), was_replied_to
  (bool), read (bool), flagged (bool)}`. Messages with no stable message-id are skipped
  (same rule as `_SEARCH`). Bounded to a scan cap.
- `_SENT_TRIAGE` → recent sent records: `{id, subject, recipient_addrs (list), date_sent
  (epoch)}` from Mail's unified `sent mailbox` accessor. Bounded.
- `_MY_ADDRESSES` → the user's own addresses: the flattened `email addresses of every
  account`. Used to detect direct-addressing and outbound identity. Empty on failure (the
  classifiers degrade, see below) — never raises the whole tool.

Dates cross as epoch seconds (fold-proof, like the rest of the codebase). Addresses are
lowercased for comparison. All inputs via argv; `with timeout`.

### Tool 1 — `mail_needs_response() -> list[dict]`

Pure `_classify_needs_response(records, my_addrs) -> list[Pointer]`:

- Drop any record whose `was_replied_to` is true (already handled).
- **Directly addressed** = one of `my_addrs` is in `to_addrs`. If `my_addrs` is non-empty,
  keep only direct records; if `my_addrs` is empty (extraction failed), skip the direct
  filter rather than return nothing.
- Assign one **reason** (stable vocabulary) and a tier, highest first:
  1. `flagged` — the message is flagged.
  2. `direct-question` — unread and the subject contains `?`.
  3. `unread-direct` — unread.
  4. `unanswered-direct` — read but still unreplied.
- Sort by tier, then most-recent `date_received` first. Bounded to `MAX_MAILS`.
- Pointer: `id` = message-id, `summary` = `subject — sender`, `deeplink` = `message://…`,
  `reason` = the tier string.

### Tool 2 — `mail_awaiting_reply(days: int = 3) -> list[dict]`

Pure `_classify_awaiting_reply(sent, inbox, days, now) -> list[Pointer]`:

- `days` must be a positive int (validated at the tool boundary).
- Consider each sent record whose age (`now - date_sent`) is at least `days`.
- Normalize a subject: strip leading `re:`/`fwd:`/`fw:` (repeatably), trim, lowercase.
- A sent message is **replied** if some inbox record has: same normalized subject **AND**
  its `sender` ∈ the sent message's `recipient_addrs` **AND** `date_received > date_sent`.
  Otherwise it is **awaiting-reply**.
- Pointer: `id` = the **sent** message-id (open it to follow up), `summary` =
  `subject — to <first recipient>`, `deeplink` = `message://…`, `reason` = stable
  **`awaiting-reply`**. Sorted **oldest-sent-first** (most overdue). Bounded to `MAX_MAILS`.
- Approximate by construction (fuzzy subject correlation, English Re:/Fwd: prefixes) —
  documented in the tool docstring; the Envelope Index plane (#70) is the accurate upgrade.

## Reason vocabulary (stable)

`flagged`, `direct-question`, `unread-direct`, `unanswered-direct`, `awaiting-reply`. Fixed
strings — a caller can switch on them. New reasons are additive, never renamed.

## Server tools

Both `@_read_tool` (read-only; Automation for Mail), returning `[_emit(p) for p in …]`.
Classified in the annotation map (`"Automation"`). Both are read tools → they ride the
untrusted-data notice (subjects/senders are attacker-writable) and are audit-exempt (reads).

## Tests

Unit (fixture, no TCC) — the pure classifiers over hand-built record lists:
- `_classify_needs_response`: was-replied dropped; direct filter (in-To kept, cc-only
  dropped); each reason tier assigned correctly; tier ordering + recency tiebreak; empty
  `my_addrs` falls back to no-direct-filter; bounded to `MAX_MAILS`.
- `_classify_awaiting_reply`: a matching inbox reply (subject+sender+date) suppresses the
  item; a same-subject message from a non-recipient does NOT suppress; subject
  normalization (`Re:`/`Fwd:` folded); the `days` threshold excludes too-recent sends;
  oldest-first ordering; bounded.
- `Pointer.reason` round-trips through `_emit` (present when set, absent when None).
- Server dispatch: `mail_needs_response` / `mail_awaiting_reply` forward and emit reason;
  correctly permission-classified.

Integration (`-m integration`, manual only): `_INBOX_TRIAGE` / `_SENT_TRIAGE` /
`_MY_ADDRESSES` extract real records on-device (structure + bounds), and each tool returns
well-formed reason-carrying Pointers against the real mailbox.

## Out of scope (YAGNI)

Body-content sentiment/urgency scanning; cc-based triage; per-account scoping; a combined
`mail_triage(kind)` tool; non-English `Re:`/`Fwd:` prefix folding (add when a locale needs
it — the fold list is one constant).
