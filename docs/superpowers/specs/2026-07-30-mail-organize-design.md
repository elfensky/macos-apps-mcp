# Mail organize — one mailbox vocabulary, mailbox writes, status writes — design

**Issues:** [#144](https://github.com/elfensky/macos-apps-mcp/issues/144) ·
[#78](https://github.com/elfensky/macos-apps-mcp/issues/78) ·
[#79](https://github.com/elfensky/macos-apps-mcp/issues/79) ·
**Release:** 0.9.1 — Mail organize · **Date:** 2026-07-30

## Why

0.9.0 shipped the reads. Triage without "file this" and "mark this read" is half a triage, so
0.9.1 adds the three write verbs that make the read plane actionable.

#144 leads, and it was not on the roadmap. It came out of a multi-AI debate over whether #78's
*read* half needed its own tool. It does not — `mail_overview` already enumerates all 51
mailboxes with account, path and counts, and the hierarchy is one slash-delimited path string.
But settling that surfaced a live bug in the shipped 0.9.0 daemon: **`mail_overview` prints a
mailbox name `mail_search` cannot match.** Since both new write tools need a mailbox vocabulary,
and the obvious one is the one that is broken, #144 goes first.

`mailboxes()` from #78's sketch is **not built** — see [Out of scope](#out-of-scope).

## On-device reality (verified 2026-07-29 / 07-30, this Mac, `~/Library/Mail/V10`)

Every number below came from querying the live `Envelope Index`.

### The #144 bug, reproduced

`MailAdapter.overview()` returns `unquote(box)` — percent-**decoded**. `build_header_query`'s
mailbox filter is `mb.url LIKE ?` against the raw, still-**encoded** `mailboxes.url`.

```
mail_search(mailbox="Planet Group")     -> 0 hits
mail_search(mailbox="Planet%20Group")   -> 5 hits
mail_search(mailbox="[Gmail]/All Mail") -> 0 hits
mail_search(mailbox="Travel")           -> 5 hits
```

**10 of 51 mailboxes are affected** — every name containing a space, `&`, or brackets:

```
Planet%20Group          Social%20&%20SEO        AI%20&%20ML
Deleted%20Messages      Sent%20Messages
%5BGmail%5D/All%20Mail  %5BGmail%5D/Drafts      %5BGmail%5D/Sent%20Mail
%5BGmail%5D/Spam        %5BGmail%5D/Trash
```

Note the encoding is **not** a Python `quote()` round-trip: space and brackets are encoded,
`&` is not. So the fix cannot be "re-encode the user's value and compare" — see the design.

The **account** half already round-trips correctly. `_resolve_account` ([mail.py:213](../../../macos_apps_mcp/adapters/mail.py))
accepts a display name, a bare UUID, **and** `"On My Mac"` — all three of the values `overview()`
can print. Only the mailbox half is broken. That seam exists because of the same class of bug
(#N1), and it is the model the fix follows.

### Copy fan-out — what a write is actually addressing

22,296 distinct Message-IDs over 36k non-deleted rows.

| Distinct mailboxes holding one Message-ID | Message-IDs |
| --- | --- |
| 1 | 18,320 |
| 2 | 3,969 |
| 3 | 7 |

**3,976 Message-IDs live in more than one mailbox, and essentially all of them are
cross-account** — one filed copy on the lav.ren account plus an `[Gmail]/All Mail` copy on the
retired Gmail account:

```
 997  Gaming @AE0E + [Gmail]/All Mail @5936      373  Travel @AE0E + [Gmail]/All Mail @5936
 419  Expense @AE0E + [Gmail]/All Mail @5936     369  Income @AE0E + [Gmail]/All Mail @5936
 401  Cloud @AE0E + [Gmail]/All Mail @5936       327  Investing @AE0E + [Gmail]/All Mail @5936
```

Same-mailbox exact duplicates (9,881 redundant rows over 3,457 messages) do **not** appear here —
they are extra rows in *one* mailbox, and they are #140's problem, not this slice's.

### The writes cannot be inbox-scoped

The three inboxes hold **16 messages, 0 unread**. All **200 unread** messages live in filed
folders and Junk. `_SEARCH` and `_BODY` are scoped to `inbox`; these write tools must not be, or
they would refuse to act on 100% of the unread mail on this machine.

### A negative result, stated so nobody re-derives it

Whether marking one copy read propagates to its siblings **cannot be answered from the index**:
all 200 unread messages are single-copy, so there is no specimen. Any claim either way today
would be vacuous — the kind of green-but-empty check that cost the 0.9.0 milestone. It is
settled by a device write probe, listed in [Verification](#verification).

## Design

### Tool surface — three new tools, one query builder fixed

```python
update_mail_status(ids: list[str], read: bool | None = None,
                   flagged: bool | None = None) -> dict          # #79, @_write_tool
create_mailbox(name: str, account: str) -> dict                  # #78, @_additive_tool
move_mail(ids: list[str], mailbox: str, account: str | None = None,
          dry_run: bool = False) -> dict                         # #78, @_write_tool
```

`flag_color` is **dropped**, for the same reason the 0.9.0 spec dropped it from `mail_search`:
it is only useful to someone who colour-flags mail, and nothing has asked for it twice. #79's
"(+colour)" is noted as declined, not forgotten.

### #144: `_resolve_mailbox` — the single mailbox vocabulary

A new adapter helper, not a query-builder change, because the decoding cannot happen in SQL
(SQLite has no urldecode, and Mail's encoding is not reproducible by `quote()`).

```python
def _resolve_mailbox(name: str, account: str | None = None) -> list[str]:
    """Raw mailboxes.url values whose DECODED path matches `name`."""
```

- Reads `mailboxes.url` (already in `HEADER_FINGERPRINT` — no fingerprint change).
- `unquote`s each path, then matches with **today's semantics**: case-insensitive substring.
  This is a pure bug fix — identical behaviour for the 41 mailboxes that work now, correct for
  the 10 that do not.
- `account`, when given, goes through `_resolve_account` first and restricts to that UUID.

`build_header_query` gains `mailbox_urls: list[str] | None` filtering `mb.url IN (?, ?, …)` and
loses the `LIKE` on the encoded url. The builder stays pure — `(sql, params)`, no connection.
Exact `IN` also fixes a second latent trap the `account` clause already documents: `LIKE
'%Trash%'` matched a folder named `Trash Archive`.

The write tools reuse the same helper to resolve the **source** side — which account's copy of a
message they are acting on — but demand **exactly one** match, raising a typed error listing the
candidates when ambiguous. One vocabulary, two strictness levels. `move_mail`'s **destination** is
resolved through Mail instead, never through the index; see its section for why.

### Addressing a message for a write: sqlite locates, AppleScript acts

1. Query the index for the ids → `(message_id, mailbox_url, account_uuid, read, flagged)`.
2. Reverse `_account_map()` (UUID → display name) for the account name AppleScript needs.
3. Pass account name + mailbox name + message id as **argv** to a script that scopes to that one
   mailbox and acts.

No store-wide `whose` scan, no interpolation ([runtime.run_osascript](../../../macos_apps_mcp/runtime.py)
argv-only), `with timeout` on every handler including nested ones — AppleScript's timeout is
lexical ([mail-applescript-facts.md](../../mail-applescript-facts.md) §6).

Two unknowns the implementation plan must **probe before writing code**:

- How AppleScript addresses `[Gmail]/All Mail` — a nested `mailbox "All Mail" of mailbox
  "[Gmail]"`, or a flat name?
- Whether `whose message id is X` is reliable outside Drafts. §5 indicts Drafts only, which is
  not proof it is safe elsewhere. Fallback is index-iteration in reverse, per §5.

### `update_mail_status` — fan out to every copy

Marks **all** non-deleted copies of each Message-ID, across mailboxes and accounts.

Rationale: "mark this read" means the message is read, not that one of its three rows is. The
alternative (write only the ranked copy the read plane cited) leaves the `[Gmail]/All Mail` copy
unread, so `mail_overview` keeps counting it — a write that reports success and leaves the
symptom on screen.

Returns per id `{copies_touched: 2, mailboxes: [...]}`. A write that touched 1 of 3 must say so;
a bare `true` is the lie class this repo keeps paying for.

**No `dry_run`.** Status is trivially reversible — mark it unread again — so a preview call is
ceremony. Batch cap 25 ids.

### `create_mailbox` — account required

`account` is **required**, not inferred. There are 5 accounts; guessing which one a new folder
belongs to is exactly the #N1 failure mode. `/` nests, which Gmail needs.

Additive, so `@_additive_tool` (not-read-only, not destructive) and no `dry_run`.

Returns the decoded name plus an explicit note that the folder **will not appear in
`mail_overview` until Mail writes its `mailboxes` row**. This is not cosmetic: a sqlite "does the
target exist?" precheck in `move_mail` must not hard-fail on a folder we ourselves just created.
`move_mail` therefore resolves its destination through Mail, not through the index.

### `move_mail` — one account, ranked copy, the rest reported

Moves the copy the read plane cites (`_MAILBOX_RANK`: INBOX > filed > All Mail/Archive/Trash/Junk),
within one account. **Never moves mail across an account boundary** — on IMAP that is a
copy-plus-delete, not a move, and it would silently reorganise an archive that may be better
retired wholesale.

Returns per id:

```python
{"id": "<…>", "from_mailbox": "Travel", "to_mailbox": "Expense",
 "other_copies": ["Gmail/[Gmail]/All Mail"]}
```

`other_copies` makes the retired-Gmail copy **visible rather than silent**, which is the input
#140 needs later.

`dry_run: bool = False` — available for a preview, not mandatory, matching `delete_draft`. Batch
cap 25.

## Testing

Unit tests mock at the adapter boundary (Protocol fakes) as usual, plus:

- `_resolve_mailbox` against a fixture `mailboxes` table containing all 10 real encoded names.
  The regression test is literally `mailbox="Planet Group"` → 5 rows.
- **Encoded names must be written as explicit `%20` / `%5B` strings in the fixture**, and the
  test must assert the decoded form differs from the raw — the `fold_text` lesson: a fixture that
  normalises makes the test vacuous.
- `test_tool_annotations.py` `_PERMISSION` entries for all three new tools (self-enforcing).
- `test_applescript_timeout.py` is introspective and will fail any new template lacking
  `with timeout` — including nested handlers.
- Test-count guard: `grep -c "^def test_" tests/test_mail.py` — currently 99.

## Verification

**Judged by re-reading the Envelope Index, never by a return value.**
[mail-applescript-facts.md](../../mail-applescript-facts.md) §1: three review rounds and a green
suite passed a `forward_mail` that delivered empty mail and destroyed 7 attachments.

Watchdog confirmed alive (`launchctl list | grep mail-watchdog`) before any Mail contact;
`~/mail-watchdog/capture.sh` **before** any force-quit.

On-device sequence, on the lav.ren account only:

1. `create_mailbox("MCP Test", account="…")` → confirm it appears in Mail.
2. `move_mail([known_id], "MCP Test")` → re-read the index, confirm the row's mailbox changed and
   the id still resolves.
3. `update_mail_status([known_id], read=False)` → confirm `messages.read = 0` at rest, then
   `read=True`, then `flagged=True`.
4. Move it back to its original folder; delete `MCP Test`.

**The fan-out probe, which earns its own step:** pick a real 2-copy Message-ID, mark it read,
re-read the index, and count how many copies flipped. This answers what the 200 single-copy
unread messages could not. If one write flips both copies, the fan-out is a no-op that IMAP
already does and the design simplifies to a single write — record the finding in
`mail-applescript-facts.md` either way.

No probe touches a message on the retired Gmail account.

## Out of scope

- **`mailboxes()` from #78's sketch.** `mail_overview` already returns
  `{account, mailbox, total, unread}` for all 51 mailboxes; the hierarchy is the slash path. A
  debate (codex, sonnet, opus — 3/3) found no gap worth a 53rd tool. Nesting, account filter,
  the 16 ms count cost and Junk/Trash noise were all examined and dismissed.
- **`flag_color`** — declined above.
- **#140 dedupe** and **#80 trash** — 0.9.2. #140 deletes mail; it should inherit an addressing
  mechanism already proven on reversible verbs, not ship alongside it.
- **Cross-account moves** — a copy-plus-delete masquerading as a move.

## Known limitations

- Account **names** come from AppleScript, which launches Mail. `_resolve_mailbox(account=…)`
  inherits `_resolve_account`'s UUID path, so it still works when Mail is unreachable.
- A mailbox created by `create_mailbox` is invisible to every sqlite-backed read until Mail
  writes its index row. Latency unmeasured; `move_mail` resolves destinations through Mail for
  exactly this reason.
- `move_mail` picks the ranked copy. For the 3,976 multi-copy ids that means "the filed copy on
  the live account", which is right, but it is a rule, not a reading of intent.
