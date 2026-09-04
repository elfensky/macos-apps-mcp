---
status: investigating
trigger: "our mail mcp doesnt seen to work on sequoia (GitHub issue #199)"
created: 2026-08-31
updated: 2026-09-05
---

## Symptoms

Source: GitHub issue #199 — "Mail: Envelope Index schema drift on macOS 15.6.1 (Sequoia) — message_global_data missing message_id_header". Reporter offered to run diagnostic queries on their machine; this dev machine runs Tahoe (Darwin 25.x), where the suite passes.

DATA_START
- expected: sqlite-backed Mail reads (mail_overview, mail_search, mail_stats, mail_awaiting_reply fast path) return results on macOS 15.6.1 (24G90).
- actual: every sqlite-backed Mail read fails with SchemaDrift: "table 'message_global_data' is missing column(s) ['message_id_header'] — macOS likely changed the schema." Pure-AppleScript reads (mail, mail_needs_response) still work. doctor() reports full_disk_access: ok, mail: ok.
- errors: SchemaDrift from mail_index.py fingerprint check.
- timeline: reported 2026-08-31 against macos-apps-mcp 0.10.1 (HEAD d9ac75f); env is macOS 15.6.1 (24G90), Envelope Index at ~/Library/Mail/V10/MailData/Envelope Index.
- repro: call mail_overview / mail_search / mail_stats on macOS 15.6.1. Reporter's `.schema message_global_data` shows message_id INTEGER (internal id) and NO message_id_header column; grep of all CREATE TABLE SQL for %header%/%message_id% finds no replacement — RFC822 Message-ID header text may not live in the Envelope Index at all on this build. New tables present: brand_indicators, data_detection_results, duplicates_unread_count, generated_summaries; new model_* columns on message_global_data (looks like the Mail categorization/summaries schema bump).
- knock-on: mail_index.account_of() cannot resolve without the index, so trash_mail/move_mail reject the canonical "inbox" mailbox ("needs a mailbox that names its account"); mail_search is the only tool emitting per-account folder urls and it is broken — so ALL destructive/move Mail tools are unreachable on affected systems, not just reads. Reporter asks that this be diagnosable via error message or doctor().
DATA_END

## Current Focus

hypothesis: CONFIRMED — see root_cause.
test: compared reporter's Sequoia 15.6.1 schema (issue #199) against local Tahoe Envelope Index (both V10)
expecting: n/a
next_action: handoff checklist 1–8 COMPLETE (root cause verified end-to-end on the rig). Remaining: owner scope decision — Tahoe-only floor with diagnosable failure (doctor + SchemaDrift must state the macOS floor and the destructive-tool consequence) vs an AppleScript/.emlx fallback plane for macOS 15. Evidence favors feasibility of a fallback: AppleScript message id IS the RFC822 Message-ID, and .emlx files carry the header.

## Evidence

- 2026-08-31: `grep message_id_header macos_apps_mcp/adapters/*.py` — ~30 call sites, all in mail_index.py; it is the id backbone (dedup partition key, id-IN filters, duplicate key, HEADER_FINGERPRINT requires `message_global_data: {ROWID, message_id_header}` at mail_index.py:42).
- 2026-08-31: local Tahoe (Darwin 25.6.0) `pragma_table_info('message_global_data')` — identical base columns to the reporter's Sequoia dump (incl. model_category/generated_summary etc.), PLUS `message_id_header` as the LAST column → added by ALTER TABLE migration, not part of the original CREATE TABLE.
- 2026-08-31: reporter (Sequoia 15.6.1 / 24G90): no `%header%` column in ANY table of their Envelope Index; RFC822 Message-ID text absent from the index entirely. Both machines use `~/Library/Mail/V10/` — the V-directory number does not discriminate; only column presence does (which the fingerprint already checks).
- 2026-08-31: local Tahoe: `messages.global_message_id` is typeof INTEGER (not the RFC822 string) — not an alternate route. Coverage wrinkle: only 47073 of 64574 messages have message_id_header populated (~73%) even on Tahoe — the migration backfills lazily.
- 2026-08-31: verification rig chosen: iMac 2012 running Sequoia via OpenCore. Handoff prompt posted on issue #199.
- 2026-09-04 (rig, all sqlite opens mode=ro): environment — macOS 15.7.9 (24G830), Mail.app 16.0, only `~/Library/Mail/V10` exists. This is a NEWER Sequoia point release than the reporter's 15.6.1 (24G90).
- 2026-09-04 (rig): `pragma_table_info('message_global_data')` → 17 columns, NO `message_id_header`. Answers the open point-release question: 15.7.9 does not add or backfill the column either — it is genuinely Tahoe-only, not a lagging 15.x migration.
- 2026-09-04 (rig): no `%header%` column in ANY table; every `%message_id%`/`%global%` column is an internal id; `messages.global_message_id` typeof integer. All four tables the reporter flagged as new (brand_indicators, data_detection_results, duplicates_unread_count, generated_summaries) exist here too → 15.6.1 and 15.7.9 index schemas agree. `PRAGMA user_version` = 0 — useless for floor detection; the column fingerprint stays the only discriminator.
- 2026-09-04 (rig): .emlx format verified (first line = byte count, then raw RFC822); 200/200 sampled files in one mailbox — including `.partial.emlx` — carry a `Message-ID:` header. Sample is one mailbox, but supports .emlx as the fallback source for id-addressing.
- 2026-09-04 (rig): live repro in-process (thin-dispatch adapter calls): `MailAdapter().stats()` and `.overview()` both raise verbatim: `SchemaDrift: table 'message_global_data' is missing column(s) ['message_id_header'] — macOS likely changed the schema. Do not trust a sqlite result until the fingerprint is updated.` `overview()` reads sqlite BEFORE contacting Mail, so it fails fast with no Mail launch and no Automation prompt.
- 2026-09-04 (rig): CORRECTION to the knock-on mechanism: `account_of()` is a pure string parse (`mailbox_url.account`) — it never touches the index. `trash_mail(..., mailbox="inbox", dry_run=True)` raises ValueError ("needs a mailbox that names its account") on EVERY macOS by design. The Sequoia-specific breakage is upstream: every emitter of per-account `folder` urls (mail_search sqlite plane, mail_overview) is SchemaDrift-broken, and the AppleScript `_SEARCH` payload is only (message id, subject, sender) — no folder — so no reachable read can produce the token the destructive tools require. Same conclusion (all destructive/move tools unreachable), more precise mechanism.
- 2026-09-04 (rig): mail_search nuance: a bare subject/from substring query with NO other filters falls back to the AppleScript inbox scan (mail.py `_run_fallback` gating) instead of raising — so on Sequoia that one shape still answers, inbox-only, with the `plane` flag. Every other filter shape raises SchemaDrift. Also useful for the fix design: AppleScript `message id` IS the RFC822 Message-ID, so Sequoia can mint stable citations via the AppleScript plane; only the index lacks them.
- 2026-09-04 (rig): unit suite 1193 passed / 3 failed — all three are `time.tzset` missing from uv's cross-compiled x86_64 python-build-standalone CPython 3.14 (rig quirk, unrelated to #199). Rig setup notes: brew has no Intel-Sequoia bottles (Tier 3) — install uv via the astral.sh standalone installer; cryptography 50.0.0 ships arm64-only macOS wheels, so `uv sync --no-install-package cryptography` (transitive via mcp→pyjwt[crypto], unused on the stdio path).
- 2026-09-04 (rig): server-level doctor/mail_overview over stdio NOT yet captured: `server.main()` → `bootstrap()` requests Calendar+Reminders TCC at startup, and this rig has no grants for the host process (user TCC.db has no Calendar/Reminders/AppleEvents rows for it), so the consent prompt blocks the MCP handshake. Automation → Mail is also ungranted, so the AppleScript-plane checks (`mail`, `mail_needs_response`, the search fallback) are pending the same screen-side clicks.
- 2026-09-05 (rig): TCC granted at the screen (responsible app = com.apple.Terminal): Calendar 2, Reminders 2; AppleEvents→Mail was first DENIED (auth_value 0 — an earlier prompt got Don't Allow) then flipped to 2 mid-session. With Calendar+Reminders granted, `bootstrap()` no longer blocks and the stdio handshake completes — confirms the earlier hang diagnosis.
- 2026-09-05 (rig, server-level over stdio, checklist item 6 CLOSED): `doctor()` → version 0.10.1, full_disk_access ok, calendar+reminders full_access, automation surfaces unprobed (request=False is prompt-free by design); `deployment.grant_identities` faithfully mirrored TCC, including the then-denied Terminal→Mail AppleEvents row. NOTE for the fix: doctor's summary reads "no denied surfaces" on a machine where EVERY sqlite mail read is broken — nothing in doctor probes the Envelope Index schema, which is exactly the reporter's diagnosability complaint. `mail_overview` → isError=True with the verbatim SchemaDrift message.
- 2026-09-05 (rig, checklist item 7 CLOSED, after the Mail Automation grant): `mail(query="invoice")` → real inbox Pointers (RFC822 ids, `folder:"inbox"`); `mail_needs_response()` → works (flagged + unread-direct reasons); `mail_search(subject="invoice")` → answers via the fallback with `"plane":"applescript-inbox"` honestly set; `mail_search(subject="invoice", unread=True)` → verbatim SchemaDrift (the dropped-filter rule). All four match the 2026-09-04 code-path analysis exactly.
- 2026-09-05 (rig): knock-on confirmed END-TO-END, not just by code reading: every working AppleScript read emits `folder:"inbox"` — the unified accessor trash_mail/move_mail reject by design — and no Sequoia-reachable read emits a per-account url. Destructive/move tools are unreachable on macOS 15 in practice.

## Eliminated

- hypothesis: Sequoia changed/renamed the schema ("drift") — NO: Tahoe ADDED the column; Sequoia never had it. The code was built against a Tahoe-only column.
- hypothesis: permissions/TCC — NO: doctor() reports full_disk_access ok, mail ok on the reporter's machine.

## Resolution

root_cause: mail_index.py depends on `message_global_data.message_id_header`, a column Apple introduced in Tahoe (macOS 26) via migration. On Sequoia (macOS 15) the RFC822 Message-ID is not stored in the Envelope Index at all — device-verified on 15.6.1 (reporter) and 15.7.9 (rig) — so every sqlite-backed read trips SchemaDrift. Knock-on: no Sequoia-reachable read can emit the per-account `folder` url (sqlite emitters broken, AppleScript pointers carry no folder), so all destructive/move mail tools are unreachable (issue #199).
fix: null
verification: null
files_changed: []
