---
status: spike-verified
depends_on: PR #200 (diagnosable floor)
issue: "#201 (tracker); #199 (background)"
created: 2026-09-05
verified_on: Sequoia rig — iMac 2012, macOS 15.7.9 (24G830), Mail 16.0, 36,354-row store
spike: .planning/design/spike_sidecar.py (run 2026-09-05, results below)
---

# Mail on macOS 15: the Message-ID sidecar plane

## The question this answers

"Will making Mail work on Sequoia be a full other code path?" **No.** Sequoia's
Envelope Index is missing exactly ONE thing the sqlite plane needs — the RFC822
Message-ID column (`message_global_data.message_id_header`, a Tahoe migration). Every
other table and column the fingerprint reads is present and identical. The fix is a
**sidecar sqlite file mapping `global_message_id → message_id_header`**, harvested from
the `.emlx` files Mail already keeps on disk, joined into the existing queries in place
of the missing column. The query layer, dedup/ranking, threading, triage, addressing,
recovery plane, and all write tools stay shared between macOS generations. What is new:
one harvest module + one join-line variant + mode detection.

## Device-verified facts (all read-only, this rig, 2026-09-05)

Every load-bearing assumption was tested against the real store before this plan:

1. **`.emlx` filename == `messages.ROWID`.** Spot-verified (ROWID 78955 ↔
   `78955.partial.emlx`, subjects match, account UUID in `mailboxes.url` == account
   directory name), then at scale: across the 8 largest mailboxes, **30,448 of 30,448
   live rows (100.0%)** have a local `.emlx`/`.partial.emlx` named by their ROWID.
2. **Message-ID is in every sampled file** (320/320, including `.partial.emlx` —
   a partial is missing attachments, not headers), and subjects cross-check against
   the index (319/320; the 1 miss was the test's fuzzy matcher, not the data).
3. **Harvest is cheap.** Headers-only parse (16 KB read/file): 673 files/s on this
   2012 spinning disk → the full 36,354-row store harvests in **under a minute**;
   Apple-Silicon SSDs will be an order of magnitude faster.
4. **The join swap works against the real index.** Prototype: harvested the Travel
   mailbox (4,427/4,427 ids, 6.9 s) into a sidecar, `ATTACH`ed it read-only to the
   read-only index connection, ran the repo's actual `_BASE_SQL` with ONLY the
   `gd` join line changed — deduped, ranked hits with per-account `folder` urls in
   **21 ms**. The `folder` url is the token that un-strands `trash_mail`/`move_mail`.
5. **Store shape:** 36,354 live rows → 22,682 distinct `global_message_id`s, zero
   NULL gids. Copies share a gid, so the sidecar needs one row per gid, ~2–3 MB.
6. **Spotlight is not a shortcut.** `mdls` on a real `.emlx` returns null for
   `com_apple_mail_messageID`/subject on this rig — rejected as a source.

## Design

### The sidecar store

`<state_dir>/mail_ids.sqlite` (next to the FTS body sidecar):

```sql
CREATE TABLE global_ids(
    global_message_id INTEGER PRIMARY KEY,   -- messages.global_message_id
    message_id_header TEXT NOT NULL          -- exact bracketed RFC822 Message-ID
);
CREATE TABLE meta(key TEXT PRIMARY KEY, value);  -- max_rowid_harvested, built_at
```

Keyed on `global_message_id`, NOT `ROWID`: copies of one message share the gid (that
is what dedup partitions on), a move gives a message a new ROWID but the same gid, and
`INSERT OR REPLACE` on re-harvest self-heals. Rows for since-deleted messages are
harmless — every query joins FROM live index rows.

### The harvester

For each index row lacking a sidecar entry: resolve the mailbox directory from
`mailboxes.url` (`V10/<account-uuid>/<name>.mbox/<store-uuid>/Data/`, nested mailboxes
appending `.mbox` per segment — verified), find `<ROWID>.emlx` or
`<ROWID>.partial.emlx`, read the byte-count line + first 16 KB, extract `Message-ID:`.
Reuses the body indexer's walker/parse patterns (`parse_emlx` already extracts mids).
Per-mailbox filename walks are cheap; the observed `Data/8/7/Messages/78955…` nesting
looks like reversed leading ROWID digits, but the plan does NOT depend on deriving it —
a filename walk per mailbox is the contract. High-water mark (`max_rowid_harvested`)
makes increments O(new mail).

- **Initial build: explicit**, via a `mail_index_ids` tool + CLI (the
  `mail_index_bodies` / `dedupe-mail` precedent — a potentially minutes-long job is
  started by a human, not smuggled into a read). Same registration tier as
  `mail_index_bodies`.
- **Top-up: automatic and bounded.** At read time in sidecar mode, if
  `max(messages.ROWID) − max_rowid_harvested` ≤ ~200, harvest inline (≈0.3 s here)
  before answering; above the cap, answer from what exists and carry a staleness
  note naming `mail_index_ids` (the #156 honesty pattern — never silently stale).
- A row whose file is absent (not yet downloaded) is skipped and retried next pass;
  it stays uncitable meanwhile — the SAME rule Tahoe itself imposes, where the native
  column is lazily backfilled and sat at ~73% populated on the dev machine. Sequoia
  with sidecar at 100% local coverage is *better* than native Tahoe, not worse.

### The query-layer swap — SUPERSEDED by the spike: shadow, don't swap

The spike found something better than the mode-parameterized join this section first
proposed. In sidecar mode, connection setup runs:

```sql
ATTACH DATABASE 'file:<state>/mail_ids.sqlite?mode=ro' AS mid;
CREATE TEMP VIEW message_global_data AS
  SELECT global_message_id AS ROWID, message_id_header FROM mid.global_ids;
```

SQLite resolves unqualified names temp-first, so the view **shadows** Sequoia's real
(column-less) `message_global_data` for every existing query — the join
`gd.ROWID = m.global_message_id` lands on the view's aliased gid. Spike-verified
bonus: `pragma_table_info('message_global_data')` ALSO resolves the view, so the
native `HEADER_FINGERPRINT` passes untouched. Net production delta: **zero SQL-builder
changes, zero fingerprint variants** — one setup hook.

Plumbing: `runtime.read_via_sqlite` gains a generic optional `setup:
Callable[[Connection], None]` (runtime stays Mail-agnostic); `mail_index` passes the
attach-and-shadow hook in sidecar mode. Mode detection stays EXPLICIT (a
schema-qualified `pragma main.table_info` probe, cached) — doctor, coverage
reporting, and the floor message must know which mode they are in even though the
queries no longer care. (The join-swap variant remains a fallback if shadowing is
ever judged too implicit; it was also prototyped and works.)

**Implementation deviation (2026-09-05, PR-B): the view JOINS BACK to the real
table** instead of projecting the sidecar alone. The spike's simple view shadowed
the WHOLE table, and `build_sent_triage_query` (#192, `mail_awaiting_reply`'s fast
path) joins on `message_global_data.message_id` — a column Sequoia DOES have (its
17-column table is missing only `message_id_header`). Under the simple view that
query would raise "no such column" and silently degrade to the slow AppleScript
scan. The shipped view:

```sql
CREATE TEMP VIEW message_global_data AS
SELECT g.ROWID AS ROWID, i.message_id_header, g.message_id
FROM main.message_global_data AS g
LEFT JOIN mid.global_ids AS i ON i.global_message_id = g.ROWID
```

Same semantics for every dedup/search/overview query (an unmapped gid yields a NULL
header exactly like Tahoe's lazy backfill), a superset for the fingerprint, and
`mail_awaiting_reply`'s index plane works on Sequoia too — rig-verified.

### Mode detection

`_read_index` (from PR #200) grows a cached mode resolver riding the fingerprint
check it already performs per read:

- native column present → **native** (Tahoe: zero behavior change, zero new risk);
- column absent, pre-26 macOS, sidecar file present → **sidecar**
  (fingerprint variant: `HEADER_FINGERPRINT` minus the `message_global_data` entry);
- column absent, sidecar absent → the #200 floor message, extended with
  "run `mail_index_ids` to build the Message-ID sidecar and enable the sqlite plane
  on this macOS".

### Doctor + coverage honesty

The `mail_index` surface (from #200) gains a third state: `ok=True,
status="sidecar"` with coverage in the remediation-free detail — "22,682 of 22,682
ids mapped (100%), high-water ROWID …, built …". Coverage below ~99% or a stale
high-water mark degrades the message, never the answer. `body_coverage()` (currently
reads the native column) moves onto the same mode switch.

## Spike results (2026-09-05, this rig — `spike_sidecar.py`)

Full-store harvest + the attach-and-shadow injection at the `_open_sqlite_ro` seam,
then the REAL adapters ran **unmodified**:

- Harvest: 36,346 files parsed in 52 s (695/s); **22,679 of 22,688 distinct global
  ids (99.96%)**. Gaps: 14 rows whose account directory does not exist under V10 at
  all (an account with no local store — the skip-and-report case), 9 messages with
  no Message-ID header (uncitable on every macOS, same rule as Tahoe).
- `pragma_table_info` on the shadowed name → `{ROWID, message_id_header}` — native
  fingerprint satisfied: True.
- Battery (all previously broken on Sequoia, all through untouched adapter code):
  `mail_overview` 376 ms / 47 mailboxes · `mail_search(subject+unread)` 8 ms, no
  fallback plane flag · `mail_search(from_)` 61 ms · `mail_stats(365d)` 141 ms,
  `plane: envelope-index`, real numbers (4,903 messages, read_ratio 0.971) ·
  `mail_thread` 30 ms · `mail_addressing.resolve(id)` 29 ms → per-account folder url
  · `mail_duplicates` 450 ms / 24 mailbox rows.
- **The knock-on is closed**: `trash_mail(<real id>, <real folder url>,
  dry_run=True)` → 351 ms, full preview with `would_affect` — account gate passed,
  Trash resolved, presence probe ran. The destructive plane is reachable end-to-end.

## What stays untouched

The AppleScript fallback lane (subject/from-only search), all write tools' own logic,
`mail_addressing` resolution (same queries, swapped join), `mail_recover` receipts,
dedupe CLI, `runtime.py`, `daemon.py`, the tool layer. On Tahoe the sidecar never
activates and no new code runs.

## Delivery plan

- **PR-A — sidecar infrastructure** (~250 LOC + tests): store, harvester,
  `mail_index_ids` tool/CLI role, doctor coverage state, high-water increments.
  Unit tests over a fake Mail tree (existing `_write_emlx` helpers); no query changes
  yet — lands inert on every machine.
- **PR-B — activation** (~150 LOC + tests): mode resolver, the `setup` hook on
  `read_via_sqlite`, the attach-and-shadow hook, bounded auto top-up,
  staleness/coverage notes, floor-message update. Key test move: parameterize the
  existing `_fake_envelope` battery to run the WHOLE existing
  search/thread/overview/triage suite in both modes — the proof this is one code
  path, not two.
- **Rig verification pass** (this machine, before release): full build, real
  searches/threads/overview, then the write plane per docs/mail-applescript-facts.md
  — `trash_mail`/`move_mail`/`update_mail_status`/`mail_undo` run for real against a
  sacrificial message and inspected in Mail.app, not just green-suited (the facts doc
  exists because reviews pass what devices fail).

## Risks

1. **Coverage on other machines.** This rig stores every message locally; a Mac with
   "Remove unedited downloads"-style settings or a huge server-side store may not.
   Mitigated by per-row skip + retry, coverage reporting, and the Tahoe-is-also-lazy
   precedent. An AppleScript gap-filler (bulk `message id of every message of mailbox`)
   is a possible later add for stubborn gaps — noted, not planned.
2. **ROWID reuse** after vacuum/rebuild of Mail's index: sidecar keys on gid and
   re-harvests with `INSERT OR REPLACE`; a full `Mailbox → Rebuild` also bumps the
   high-water logic's assumptions — detect `max(ROWID)` regression and trigger a
   fresh full harvest.
3. **emlx variants** (encrypted/S-MIME bodies, odd encodings): headers are what we
   parse and they are plain RFC822; `parse_emlx` has handled the store's corpus for
   the body index already.
4. **A future macOS 15.x point release adding the column**: mode detection is
   column-presence, not version — it would flip to native automatically.
