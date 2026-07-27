# Mail reads — rich search, inbox overview, thread view — design

**Issues:** [#75](https://github.com/elfensky/macos-apps-mcp/issues/75) ·
[#76](https://github.com/elfensky/macos-apps-mcp/issues/76) ·
[#77](https://github.com/elfensky/macos-apps-mcp/issues/77) ·
**Milestone:** 0.9.0 — Mail depth & outbound · **Date:** 2026-07-27

## Why

`mail_search` (#70) landed the Envelope Index read plane but stopped at header filters.
Three gaps remain on the same plane, and doing them separately means three passes over the
same SQL: attachment/account filters (#75), "what's unread where" (#76), and conversation
fetch (#77). All three are one indexed query each against an index that already exists.

#119 (force IMAP body download) was scoped into this slice originally and is **split out** —
see [Out of scope](#out-of-scope).

## On-device reality (verified 2026-07-27, this Mac, `~/Library/Mail/V10`)

Every number below came from querying the live `Envelope Index`, not from documentation.

- **36,113 message rows (36,112 non-deleted), 51 mailboxes, 23,445 conversations, 10,969
  attachment rows**, across 4 IMAP accounts plus the local *On My Mac* store. Every count
  below is over non-deleted rows.
- `messages.conversation_id` exists and carries **five dedicated indexes** (incl.
  `messages_conversation_id_mailbox_date_received_deleted_index`). Mail already does the
  threading — matching References/In-Reply-To by hand, as #77 sketches, is redundant work.
- `attachments(ROWID, message, name)` with `attachments_message_name_index` → `has_attachments`
  is an indexed `EXISTS`, not a per-message AppleScript probe. **But the table counts inline
  signature and newsletter images as attachments** — see below.
- `mailboxes.url` embeds the account UUID: `imap://<UUID>/<percent-encoded-path>`.
- AppleScript `id of every account of application "Mail"` returns **exactly those UUIDs**,
  alongside `name` and `email addresses` — verified, sub-second:
  `iCloud=B88CA30E…, Personal=AE0EAE3D…, Business=02B406D0…, Google=5936B2CE…`.

### Duplicates: the finding that shapes all three features

**36,112 non-deleted message rows resolve to only 22,223 distinct RFC822 Message-IDs.** 6,089
Message-IDs appear in two or more mailboxes. Confirmed not a NULL-grouping artefact: only 26 of
those rows (16 empty, 10 NULL) have no `message_id_header`.

Three distinct causes, which must not be conflated:

1. **Exact copies in the *same* mailbox** — **9,881 redundant rows over 3,457 messages**
   (Travel 3,171, Expense 2,410, Investing 2,201). Verbatim example — identical Message-ID,
   date, subject and byte size, three rows in one folder:

   ```
   <##PP35084829$…@tatv.be>  Travel  rowid 17518  1552566909  6231 bytes
   <##PP35084829$…@tatv.be>  Travel  rowid 18943  1552566909  6231 bytes
   <##PP35084829$…@tatv.be>  Travel  rowid 20364  1552566909  6231 bytes
   ```

   A migration copy that ran three times. Real garbage on the IMAP server; deletable.
2. **Cross-account copies — 3,945 messages.** The same mail on Google's server *and* on
   lav.ren, from the gmail→lav.ren migration. Two real messages on two real servers.
3. **Gmail's label view — 6 rows.** One server-side message Gmail *displays* under both
   All Mail and a label. Not a duplicate; deleting one deletes both.

Cleaning up (1) and (2) would improve the mailbox but **cannot fix the code**: (3) regenerates
forever, (2) reappears on any new account or copied thread, every reply creates a Sent-plus-folder
pair, and the read plane must be correct on a mailbox nobody has cleaned. Apple hit this too —
the schema carries a `mailboxes.unread_count_adjusted_for_duplicates` column.

**Therefore: dedupe in the read plane, unconditionally.** Cleanup is filed separately.

### `has_attachments` cannot be a naive EXISTS

Mail records inline images as attachment rows. The most common `attachments.name` values on this
Mac are email furniture, not attachments anyone means:

```
Mail Attachment.png  498 · image001.png 426 · image002.png 385 · embed0.png 285
icon-headerbar-logo.png 131 · megekko_header_bars_full.png 131
```

| Predicate | Messages matched |
| --- | --- |
| any attachment row (naive `EXISTS`) | 4,474 |
| anything that is not an image | 2,566 |
| **the shipped rule (below)** | **2,562** |

A naive `has_attachments=True` would return a mailbox-worth of newsletters. **The filter means
"carries a real document"**: an attachment whose name does not end in a known image extension.
Names with no extension count as documents (43 rows — could be anything; better a false positive
than a silently dropped attachment). There are no NULL names in this store, but the predicate
tolerates them for the same reason.

```python
_IMAGE_EXTS = ("png", "jpg", "jpeg", "gif", "webp", "heic",
               "bmp", "tiff", "tif", "svg", "ico")
```

Cost, stated plainly: a photo someone genuinely emailed you is missed. `mail_attachments` still
lists every attachment of a message, images included, so nothing becomes unreachable.

### Stored counts are stale

`mailboxes.unread_count` is a trigger-maintained column, and on this Mac it **lies**: the Gmail
`INBOX` row reports `unread_count = 1` while a live `COUNT(*)` over its non-deleted unread
messages returns `0`. `unread_count_adjusted_for_duplicates` matches the stale value, so it
buys nothing. Counts are computed live — 16 ms over 36k rows, backed by
`messages_read_deleted_…_index` (a partial index on `read = 0 AND deleted = 0`).

### Account names are not resolvable at rest

`~/Library/Mail/V10/MailData/` holds no accounts plist. `~/Library/Accounts/Accounts4.sqlite`
maps `ZIDENTIFIER` → `ZACCOUNTDESCRIPTION` (`AE0EAE3D… → "Personal"` ✓) but is **incomplete** —
the iCloud account's description is blank — and would need its own FDA grant, schema
fingerprint and fallback for a cosmetic label. Rejected. The one-shot AppleScript is
authoritative, sub-second, and uses plumbing the adapter already has.

## Design

### Tool surface — two new tools, one extended

```python
mail_search(..., has_attachments: bool = False, account: str = "")   # #75, extended
mail_overview() -> list[dict]                                        # #76
mail_thread(id: str, limit: int = 100) -> list[dict]                 # #77
```

#76 ships as **one** tool, not the `mail_accounts()` + `mail_unread()` pair its issue sketches:
the account name is a column of the same rows, so a second tool would be a second round-trip
for a field already in hand.

Only the two filters Andrei selected are added to `mail_search`. `flag_color` and sort-order
control were considered and dropped (YAGNI — `flag_color` is only useful to someone who
colour-flags mail; newest-first is the right default and nothing has asked for another).

`account` accepts **either** a display name (`"Personal"`) **or** the raw account UUID. The name
path needs the AppleScript lookup; the UUID path is pure sqlite and always works. Without that,
a filter would be unusable exactly when Mail is unreachable — see [Known limitations](#known-limitations).

### The dedup rule — one CTE, shared by all three

```sql
ROW_NUMBER() OVER (PARTITION BY gd.message_id_header ORDER BY
  CASE WHEN mb.url LIKE '%/INBOX'                              THEN 0
       WHEN mb.url LIKE '%All%Mail' OR mb.url LIKE '%/Archive'
         OR mb.url LIKE '%/Trash'   OR mb.url LIKE '%Junk'     THEN 2
       ELSE 1 END,
  m.date_received DESC, m.ROWID) = 1
```

Preference: a live INBOX copy beats a filed copy, which beats an All Mail / Archive / Trash /
Junk copy. Ties break newest-first, then by ROWID so the result is deterministic.

Applied **in SQL, not in Python**, so `LIMIT 25` returns 25 distinct messages rather than 25 rows
that collapse to 16. Measured on the live index: a `subject LIKE '%contract%'` search returns
**171 rows undeduped, 111 deduped**, in 134 ms.

Rows with a NULL or empty `message_id_header` are excluded, as they already are — no
Message-ID means no stable citation, which is the rule `row_to_pointer` documents today.

### `mail_thread(id, limit=100)` — #77

Resolve the Message-ID to its `conversation_id`, return every non-deleted message in that
conversation, deduped, **oldest-first**.

Verified against a real 25-message exchange on this Mac — an insurance thread spanning the
`Insurance` folder and `Sent Messages` across two accounts, correctly interleaved:

```
lukas.joosen@verz.kbc.be   Insurance       2025-08-19 12:03
lukas.joosen@verz.kbc.be   Insurance       2025-09-11 11:58
andrei@lavrenov.io         Sent Messages   2025-09-11 12:24
lukas.joosen@verz.kbc.be   Insurance       2025-09-11 13:33
…                                          (25 messages, 98 ms)
```

- **Sent messages are included.** The transcript above is unreadable without them.
- **Quoted-text dedup is not applicable.** Threads return Pointers; bodies stay behind
  `mail_body`. Pointers-not-payload gets this for free.
- **Truncation keeps the newest `limit` messages, returned oldest-first.** The largest thread
  on this Mac is 154 rows (~144 distinct); when the point of reading a thread is to reply to it,
  the old end is the end to drop. `MAX_THREAD = 100` clamps a caller-supplied `limit`, mirroring
  how `MAX_MAILS` clamps `mail_search`.
- An unknown Message-ID returns `[]`, not an error — the same contract a no-match search has.

### `mail_overview()` — #76

One row per mailbox: `{account, mailbox, total, unread}`, unread-first, then account then
mailbox name. Mailbox names are URL-decoded via `urllib.parse.unquote`
(`%5BGmail%5D/Spam` → `[Gmail]/Spam`).

- **All 51 mailboxes**, not just those with unread. ~800 tokens for the complete picture, and
  Spam-with-7-unread stays visible *as Spam* rather than being silently filtered — no triage
  policy baked into a read tool.
- **Counts computed live**, per the staleness finding above.
- Account names come from a best-effort AppleScript lookup, **cached per process**. If Mail is
  unreachable or Automation is denied, the UUID is used as the account label and the counts —
  which never needed Mail — are returned regardless. The tool never fails for want of a label.

This is an enumeration read, so it returns typed dicts rather than Pointers, matching the
`safari_tabs` / `messages_chats` precedent in DESIGN.md. There is nothing to cite here: a count
is not a message.

### Code placement

| File | Change |
| --- | --- |
| `adapters/mail_index.py` | `_DEDUP_RANK` CTE fragment; `build_thread_query`, `build_overview_query`; `has_attachments` + `account` clauses in `build_header_query` |
| `adapters/mail_index.py` (`HEADER_FINGERPRINT`) | `messages` gains `conversation_id`; new `attachments: {ROWID, message, name}` entry |
| `adapters/mail.py` | `MailAdapter.thread()`, `.overview()` — same `read_via_sqlite` path as `.search()`; `MAX_THREAD` constant |
| `server.py` | `mail_thread`, `mail_overview` as thin `@_read_tool`s; two new params threaded onto `mail_search` |

No new dependency. No `run_native` work beyond the existing osascript account lookup. Query
construction stays pure functions in `mail_index.py` so it is unit-testable without a Mac.

### Capability tier

All three are **reads** — `@_read_tool`, no `MACOS_APPS_READ_ONLY` interaction, no send gate.
`tests/test_tool_annotations.py` enforces the classification automatically.

### Failure modes

| Condition | Behaviour |
| --- | --- |
| Schema drift (renamed/dropped column) | `read_via_sqlite` fingerprint mismatch → existing AppleScript fallback for `mail_search`; `mail_thread`/`mail_overview` raise the typed `NativeError` (AppleScript has no equivalent, and inventing a degraded answer would be dishonest) |
| No Mail data (`Envelope Index` absent) | Existing `NativeError` with "open Mail once" remediation |
| Mail unreachable during account lookup | `mail_overview` falls back to UUID labels; counts unaffected |
| Unknown Message-ID in `mail_thread` | `[]` |
| Message with no RFC822 Message-ID | Excluded, as today |

## Known limitations

Accepted, not overlooked. Each is a consequence of a decision above, documented so nobody
rediscovers it as a bug.

**No AppleScript fallback for `mail_thread` / `mail_overview`.** `mail_search` degrades to an
AppleScript inbox search on schema drift; these two cannot, because AppleScript has no way to
express "fetch this conversation" or "count unread across all mailboxes". A macOS release that
renames `conversation_id` or the `mailboxes` columns takes both tools offline until the
fingerprint is updated — they raise the typed `NativeError` rather than inventing a degraded
answer. This is strictly more fragile than `mail_search` and is the main upgrade risk in the
slice.

**Dedup discards the other locations.** A message in both INBOX and a filed folder is reported
as INBOX; the filed copy does not appear. Correct for triage, occasionally lossy when the
question was "where did I file this". Reversing it means putting a folder *list* on `Pointer`,
which changes a contract shared by every adapter — deliberately not done here.

**`mail_overview` labels depend on machine state.** Counts never need Mail; account names do. The
same call returns `Personal` with Mail running and `AE0EAE3D-449A-4B33-A923-FBFDB3DD13A1` without
it. Same data, different labels. Preferred over failing the whole call for a cosmetic field.

**Thread truncation drops the oldest messages.** A thread beyond `MAX_THREAD` loses its opening,
so "how did this start" is unanswerable there. Exactly one thread on this Mac (154 rows) is
affected.

**`has_attachments` misses emailed photos.** Per the rule above.

## Testing

**Unit** — a fixture sqlite built with this schema subset, asserting:
dedup preference order (INBOX wins over Archive; same-mailbox triplicate collapses to one);
`LIMIT` applies *after* dedup; thread chronology and that truncation drops the **old** end;
overview counts computed live and unaffected by a deliberately wrong stored `unread_count`;
`has_attachments` matching a `.pdf` and an extensionless name while rejecting a message whose
only attachment is `image001.png`; `account` resolving by both display name and raw UUID;
URL-decoding of mailbox names.

**Integration** (`-m integration`, on-device only, never CI) — all three tools against the real
Envelope Index.

**Regression guard** — `grep -c "^def test_" tests/test_mail.py` must not drop (currently 88);
a fix wave once silently deleted five tests while the suite total stayed flat.

Reads only — no Mail writes — so the forward-mail lesson in
[docs/mail-applescript-facts.md](../../mail-applescript-facts.md) does not bite here. Each tool
is still run on device and its output eyeballed before merge.

## Out of scope

- **#119 body download** — split to its own slice, shaped as a **CLI command**
  (`macos-apps-mcp download-bodies [--mailbox X] [--since D] [--limit N]`) mirroring
  `allow-send`, not an MCP tool. 22,715 of 36,297 `.emlx` are `.partial.emlx` (37% of bodies
  local); forcing the rest means hours of IMAP and GB of disk. The model may *report* the
  coverage gap; it must not be able to start the job.
- **Duplicate cleanup** — the 9,881 redundant same-mailbox rows. A destructive IMAP write with
  dry-run, filed against #80's trash-management area.
- **Smart mailboxes** — saved searches in `SmartMailboxes.plist`, absent from the Envelope
  Index entirely. Documented as a known gap rather than silently missing.
- **`flag_color` filter, sort-order control** — dropped, per above.
