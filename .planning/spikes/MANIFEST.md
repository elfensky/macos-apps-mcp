# Spike Manifest

## Ideas

### eventkit-depth
Phase 3 of milestone v0.11.0 takes Calendar and Reminders to Mail-level depth: alarms and real
recurrence on events, deletion, lists, subtasks and tags on reminders. Two parts of that scope
must be proven on device before any code: whether Reminders tags have a public write route, and
whether EventKit stores all-day events and RRULE shapes exactly as asked.

**Requirements:**

- No private-API write, in any outcome (REM-04, owner decision in REQUIREMENTS.md).
- A recurrence shape EventKit cannot express is rejected loudly with a typed error, never saved
  in a changed form (Phase 3 success criterion 2).
- Subtasks ship read-only, the same as tags: read from the Reminders sqlite store, with the
  write gap named in the tool docstring (owner, 2026-09-28, after spike 002).
- A DTSTART that does not match its rule is accepted with RFC 5545 semantics; the extra first
  occurrence is stated in the Pointer summary (owner, 2026-09-28, after spike 003).
- RRULE fidelity is proven on Google CalDAV too, because Google holds the default calendar for
  new events (owner, 2026-09-28).

### notes-semantic-search
NOTE-01: a written decision on Notes semantic search (embedding model, chunking, index build and
refresh policy, size cap, optional-extra boundary) before any indexing code. The spike measures
the real corpus so the decision rests on numbers, not guesses.

**Requirements:**

- The base install gains no ML dependency; semantic search lives behind a `[semantic]` extra.
- The index is a sidecar in the server's own state dir, the same shape as the Mail FTS sidecar.
- NOTE-01 closes as "not adopted": `notes()` gains FTS5 full-body search instead, with no new
  dependency (owner, 2026-09-28, after spike 004).

### mail-fixes
Phase 02.1: Mail's existing write tools keep their promises on a large, real mailbox. A batch
move or trash within the cap finishes inside its timeout and always leaves a receipt, and a
draft carries the sender the caller chose. Two facts must be measured on device before code:
what Mail does with a From address that no account owns (MAIL-04, with the MAIL-03 sender and
reply checks), and the per-message cost of `_PRESENT`, `_MOVE` and `_TRASH` on the 9k+ IMAP
mailbox (MAIL-01).

**Requirements:**

- If Mail does not reject an unowned `from_address`, `send_mail` and `create_draft` refuse it
  before any native write, and the outbound dry run still makes no native call (MAIL-04).
- Nothing is sent by a spike. Mail probes are draft-only or move-only, with the watchdog
  running (owner, 2026-09-28).
- The Grandma and Mama accounts hold family members' mail and are never probe targets.

### dashboard-loader
#483: the operator dashboard opens at a domain. A static loader page on a public https
origin fetches the daemon's pages from `127.0.0.1:47632` and shows them: the app.plex.tv
pattern, local only. The spikes prove whether browsers let a public page reach a loopback
server with a Bearer header, a CORS preflight and a POST, and what the daemon sees.

**Requirements:**

- Local only: the browser runs on the Mac that runs the daemon. No relay, no LAN bind, no
  per-install certificates (owner, 2026-10-25).
- Read and write: the loader carries the adapter switches and the restart. Sending mail stays
  a Terminal command (owner, 2026-10-25).
- The loader is public, on own infrastructure behind cloudflared, and anyone can self-host
  the same file on their own domain (owner, 2026-10-25).
- A hash check of the hosted loader by the daemon is later hardening, a tripwire and not a
  lock; it is not in the first version (owner, 2026-10-25).
- Safari is not supported by the loader: when a loopback fetch fails before the network, the
  loader says so and links to `http://127.0.0.1:47632` (owner, 2026-10-25, after spike 010).

## Spikes

| # | Idea | Name | Type | Validates | Verdict | Tags |
|---|------|------|------|-----------|---------|------|
| 002 | eventkit-depth | reminders-tags-route | standard | Given macOS 27, when every public surface is checked for a tag write and sqlite for a tag read, then REM-04 resolves | ✓ VALIDATED — read-only from sqlite; `parentReminder` is not public (REM-03 premise false) | reminders, tags, subtasks, sqlite, app-intents |
| 003 | eventkit-depth | eventkit-allday-rrule | standard | Given a scratch calendar in a non-UTC zone, when all-day and RRULE events are created, then each reads back on the correct days, or EventKit rejects it | ✓ VALIDATED — all-day correct in every zone; 21/22 RRULE shapes exact; BYWEEKNO saved but never expanded (must be rejected); identical on Google CalDAV | calendar, rrule, all-day, timezone, dst |
| 004 | notes-semantic-search | notes-semantic-cost | standard | Given the real Notes corpus, when lexical and embedding retrievers index it, then size, build time, index size, dependency weight and quality are measured | ✓ VALIDATED — 17 notes (too small to need an index); native macOS embeddings below lexical; FTS5 over bodies is the zero-dep win; MiniLM-L6 (ONNX) if ever adopted | notes, embeddings, fts5, onnx |
| 005 | mail-fixes | mail-unowned-from | standard | Given 8 Mail accounts, when outgoing messages get owned, non-default and unowned senders (windowless and visible) and replies are built in non-default accounts, then the autosaved draft's From shows whether Mail rejects, falls back or keeps it, and which account a reply uses | ✓ VALIDATED — unowned From silently falls back to the default account (no error, no domain match); owned non-default sticks; a reply to mail FROM a configured account is sent as that account (Grandma → Grandma) | mail, sender, drafts, reply, accounts |
| 006 | mail-fixes | mail-move-budget | standard | Given the 9k+ IMAP mailbox, when `_PRESENT`, `_MOVE` and `_TRASH` run on 1, 5 and 25 ids, then seconds per message (median, p95) are measured for the MAIL-01 timeout formula | ✓ VALIDATED — cost is the per-id `whose` scan (~0.1–0.25 ms per stored message, 5–9× in the §3c state): shipped 25-move ≈ 460 s; a by-ID act (`«class mssg» id n`, O(1)) moved 25 in 63 s | mail, move, trash, timeout, imap |
| 007 | eventkit-depth | reminder-delete-subtasks | standard | Given a scratch list with a parent and 2 subtasks, when EventKit removes the parent, then the sqlite store shows whether the subtasks are deleted, orphaned or promoted, and how fast | ✓ VALIDATED — removing a parent deletes its subtasks at once (EventKit cannot see them); completing a parent leaves them open | reminders, subtasks, delete, sqlite |
| 008 | eventkit-depth | eventkit-alarms | standard | Given iCloud and Google/Personal, when timed, all-day and recurring all-day events get alarm lists from 3 zones, then each alarm reads back exactly after sync and falls on the correct local day | ✓ VALIDATED — relative alarms exact on iCloud and Google, right local day in 4 zones; Google silently keeps 5 of 6 (random drop) and converts absolute to relative 10–30 s after save; DST days fire at 08:00/10:00 like Calendar's own alerts | calendar, alarms, all-day, timezone, google-caldav |
| 009 | dashboard-loader | loader-chrome-lna | standard | Given a public https page in Chrome 156, when it fetches a loopback mock with a Bearer header and POSTs a form, then Chrome asks once, the mock sees the page Origin and a loopback Host, the page reads the answers, and an unpaired mock stays unreadable | ✓ VALIDATED — 10/10 in Chrome 156, Zen (Firefox 158) the same; one `loopback-network` prompt per site, persistent after "Allow while visiting the site"; plain CORS, no LNA header reaches the server; key in `localStorage`, not the fragment alone | dashboard, loader, chrome, firefox, local-network-access, cors |
| 010 | dashboard-loader | loader-safari-loopback | standard | Given the same page in Safari 27.0.1, when it fetches the loopback mocks, loads loopback images and navigates to a loopback URL, then each is allowed or blocked | ✗ INVALIDATED — every `fetch` to `127.0.0.1` and `localhost` fails before the network (`Load failed`), no LNA in Safari; images load and a top-level navigation works, so Safari needs approach A (a link) or C (https on loopback) | dashboard, loader, safari, webkit, mixed-content |
| 011 | dashboard-loader | live-daemon-baseline | standard | Given the live daemon, when the public page sends a no-cors GET and a CORS GET without a key, then the requests arrive but the page reads nothing | ✓ VALIDATED — the no-cors GET arrives after the loopback prompt and reads opaque; the CORS GET gets no CORS answer (`TypeError`); no POST sent to the live daemon | dashboard, guard, cors, baseline |
