# Mail indexed search — Envelope Index read plane + best-effort body FTS — design

**Issue:** [#70](https://github.com/elfensky/macos-apps-mcp/issues/70) · **Milestone:** 0.8.0 — New adapters & expansion · **Date:** 2026-07-23

## Why

AppleScript whose-clauses can't match body content and iterate per-message — "slow searches"
is the top documented Mail-server complaint (patrickfreyer). Nobody ships an **indexed** Mail
read plane with **Pointer** output (survey gap; imdinu/apple-mail-mcp's FTS5 experiment shows
the appetite). Apple already maintains the index we need: `Envelope Index`, a normalized
sqlite store listing every message's subject/sender/date/folder. Reading it directly gives
instant search across **all** mailboxes — today's `mail()` is inbox-only, subject/sender
substring, AppleScript-slow.

## On-device reality (verified 2026-07-23, this Mac, `~/Library/Mail/V10`)

- `Envelope Index` holds **36,009** messages, normalized: `messages` → `subjects.subject`,
  `addresses.address` + `addresses.comment` (sender email + display name),
  `date_sent`/`date_received` (epoch), `mailboxes.url` (folder), and the **RFC822
  Message-ID** in `message_global_data.message_id_header` (join
  `messages.global_message_id → message_global_data.ROWID`). Every `Pointer` field the
  AppleScript path builds today is present and joinable.
- **Body coverage is structurally partial**: **13,453 full `.emlx`** vs **22,702
  `.partial.emlx`** (headers only, body not downloaded from IMAP). The downloaded set is
  outside our control — it shifts with Mail's account settings and grows as messages are
  opened. **No body source can be complete.** Stability therefore comes from *architecture*
  (a best-effort layer that never affects the header core), not from the source.

## Architecture

Two planes, hard-separated by trust:

```
mail_search(...)  ──┬─ header plane  (Envelope Index sqlite)   ALWAYS WORKS, all 36k
                    └─ body= filter  (FTS5 sidecar over .emlx)  BEST-EFFORT, indexed subset
mail_index_bodies() ─ builds/resumes the sidecar (opt-in, size-capped)
```

### A. Header read plane — the stable core

New sqlite reader in `adapters/mail.py`, built on the **existing**
`runtime.read_via_sqlite(path, fingerprint, query, *, fallback=<applescript>,
immutable=False)` — the same dual-backend plumbing Messages (chat.db) and Notes
(NoteStore.sqlite) use. No new plumbing.

- **Path:** newest `~/Library/Mail/V*/MailData/Envelope Index` (glob `V*`, pick highest).
- **`immutable=False`** (`mode=ro`, reads the `-wal` for live state) — same lesson as Notes;
  `immutable=1` would pin a stale snapshot.
- **Query:** one parameterized SELECT joining `messages` → `subjects`, `addresses` (sender),
  `mailboxes`, `message_global_data`, mapping each row → `Pointer(id=message_id_header,
  summary=subject, deeplink=_deeplink(message_id_header), folder=mailbox url)`. Reuses the
  existing `_deeplink`. Rows with a NULL/empty `message_id_header` are skipped (no stable
  citation — same "header-less message → missing" rule the adapter already documents).
- **Filters** (all optional, ANDed; SQL params, never interpolated): `subject`, `from_`
  (sender address/name substring), `to` (via `recipients`/`addresses`), `mailbox` (folder
  substring), `since`/`until` (epoch range on `date_received`), `unread`, `flagged`. Bounded
  by `limit` (host maxN backstop, same `MAX_MAILS` budget).
- **Fingerprint** (notes-style enumeration): the tables + columns actually read
  (`messages`: the joined/filter columns; `subjects.subject`; `addresses.address,comment`;
  `mailboxes.url`; `message_global_data.message_id_header`). A macOS schema move that
  renames/drops any → `SchemaDrift` → **AppleScript fallback** (`get_pointers`-style reader),
  never a mis-parsed Pointer. Missing FDA → same fallback.

### B. Body FTS sidecar — best-effort layer

- **Location:** `runtime.state_dir()/mail_fts.sqlite` — **our** state dir, **never** inside
  Mail's data.
- **Schema:** FTS5 virtual table `bodies(message_id UNINDEXED, body)` + a plain
  `indexed_files(path TEXT PRIMARY KEY, mtime INTEGER, size INTEGER)` meta table for
  resume/staleness bookkeeping.
- **Source:** full `.emlx` files under `~/Library/Mail/V*/`, **skipping `.partial.emlx`**
  (no body). `.emlx` = a decimal byte-length first line, then that many bytes of RFC822, then
  a trailing XML plist. Parse the RFC822 slice with stdlib `email.parser.BytesParser`; extract
  `text/plain` (else `text/html` → tag-stripped text via stdlib `html.parser`); key the FTS
  row by the parsed **Message-ID** (same id as the header plane → clean join). Read-at-rest:
  no Mail.app, no automation TCC, no lock contention — the same model as the sqlite core.
- **Build tool `mail_index_bodies(rebuild=False)`** — **opt-in**:
  - **Resumable:** for each `.emlx`, skip if `(path, mtime, size)` already in
    `indexed_files` unchanged; else parse + upsert + record. A re-run continues after a stop.
  - **Size-capped:** stop when `mail_fts.sqlite` exceeds a cap (default ~200 MB, env-override
    `MACOS_APPS_MCP_FTS_MAX_BYTES`); record progress so a later run resumes. `ponytail:` cap
    is a hard byte ceiling, not a row estimate — the upgrade path is incremental/background
    indexing if the cap bites.
  - `rebuild=True` truncates the sidecar and re-walks from scratch.
  - Returns `{indexed, skipped, total_emlx, capped: bool, coverage: "N/36009"}`.
- **Unparseable / header-less / partial** messages are skipped gracefully and counted —
  never fatal.

### C. Tool surface — thin dispatch in `server.py`

- **`mail_search(subject=None, from_=None, to=None, mailbox=None, since=None, until=None,
  unread=None, flagged=None, body=None, limit=…) -> list[dict]`** — the single search tool,
  backend chosen under the hood (header sqlite always; FTS when `body=` set; AppleScript
  fallback when sqlite unavailable). `body=` ANDs an FTS constraint onto the header filters
  (FTS → candidate Message-IDs → intersect header query). When `body=` is used, the result is
  accompanied by a **coverage note** (indexed/total) so partial body coverage is never
  presented as complete. At least one filter required (empty call → `ValueError`, same spirit
  as today's empty-query guard).
- **`mail_index_bodies(rebuild=False) -> dict`** — build/resume the sidecar.
- Both **read-classified** (`tests/test_tool_annotations.py` self-enforces). `mail()`,
  `mail_body`, triage tools **unchanged**. Reads are audit-exempt and ride the untrusted-data
  notice.

## Contract

**No `contracts.py` change.** Reads return `list[Pointer]`; `Pointer` already carries
`id/summary/deeplink/folder`. The `body=` coverage note travels as an adapter-emitted
sibling in the tool result (a trailing note dict / logged string), not a new Pointer field —
YAGNI on the contract.

## Testing

Pure-function cores unit-tested at the Protocol boundary (mock the adapter seam; no live
Mail/TCC):

- SQL row-tuple → `Pointer` mapping, incl. NULL `message_id_header` skip and folder/deeplink.
- Filter → WHERE/param construction (each filter, ANDing, epoch range, injection-safety:
  values are bound params).
- Fingerprint drift → fallback invoked (fake conn missing a column).
- `.emlx` parse: length-prefix strip + trailing-plist strip + MIME `text/plain` vs
  `text/html`→text extraction + Message-ID key; malformed/partial → skipped, counted.
- FTS query → Message-IDs → header-join intersection.
- Resume/size-cap bookkeeping: unchanged file skipped; cap → `capped=True` + progress
  recorded; `rebuild` truncates.

Integration (`-m integration`, **on-device, never CI**):

- Real `Envelope Index` subject search on the 36k mailbox **<1s** (acceptance).
- Fingerprint-mismatch path falls back to AppleScript.
- `mail_index_bodies` over a bounded `.emlx` sample; `body=` search returns matching Pointers
  with a coverage note; re-run skips already-indexed files.

## Acceptance (from #70)

- [ ] Subject search on the 10k+ mailbox **<1s**.
- [ ] Fingerprint mismatch → AppleScript fallback.
- [ ] Body sidecar **opt-in**, **resumable**, **size-capped**.

## Out of scope (split out)

- **`mail_download_bodies`** — forcing Mail to fetch the ~22k un-downloaded IMAP bodies (so
  the FTS index reaches near-full coverage). It is a distinct, side-effectful subsystem:
  requires Mail.app running + automation TCC + IMAP network, is long-running (hours) and
  GB-scale, and must be explicit/resumable/progress-tracked. It breaks the read-at-rest
  property every other read tool preserves, so it earns its **own issue + on-device spec**.
- Generalizing `.emlx`-style read-at-rest to other apps — already the DESIGN.md direction and
  mostly realized per-app (EventKit/Contacts frameworks, chat.db, NoteStore.sqlite); `.emlx`
  is Mail-specific, not a shared abstraction (YAGNI). Roadmap, not this issue.
