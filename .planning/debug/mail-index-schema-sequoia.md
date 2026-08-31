---
status: investigating
trigger: "our mail mcp doesnt seen to work on sequoia (GitHub issue #199)"
created: 2026-08-31
updated: 2026-08-31
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
next_action: on the Sequoia iMac — run the read-only verification checklist from the issue #199 handoff comment, append results to Evidence, then decide scope (Tahoe-only vs AppleScript fallback plane)

## Evidence

- 2026-08-31: `grep message_id_header macos_apps_mcp/adapters/*.py` — ~30 call sites, all in mail_index.py; it is the id backbone (dedup partition key, id-IN filters, duplicate key, HEADER_FINGERPRINT requires `message_global_data: {ROWID, message_id_header}` at mail_index.py:42).
- 2026-08-31: local Tahoe (Darwin 25.6.0) `pragma_table_info('message_global_data')` — identical base columns to the reporter's Sequoia dump (incl. model_category/generated_summary etc.), PLUS `message_id_header` as the LAST column → added by ALTER TABLE migration, not part of the original CREATE TABLE.
- 2026-08-31: reporter (Sequoia 15.6.1 / 24G90): no `%header%` column in ANY table of their Envelope Index; RFC822 Message-ID text absent from the index entirely. Both machines use `~/Library/Mail/V10/` — the V-directory number does not discriminate; only column presence does (which the fingerprint already checks).
- 2026-08-31: local Tahoe: `messages.global_message_id` is typeof INTEGER (not the RFC822 string) — not an alternate route. Coverage wrinkle: only 47073 of 64574 messages have message_id_header populated (~73%) even on Tahoe — the migration backfills lazily.
- 2026-08-31: verification rig chosen: iMac 2012 running Sequoia via OpenCore. Handoff prompt posted on issue #199.

## Eliminated

- hypothesis: Sequoia changed/renamed the schema ("drift") — NO: Tahoe ADDED the column; Sequoia never had it. The code was built against a Tahoe-only column.
- hypothesis: permissions/TCC — NO: doctor() reports full_disk_access ok, mail ok on the reporter's machine.

## Resolution

root_cause: mail_index.py depends on `message_global_data.message_id_header`, a column Apple introduced in Tahoe (macOS 26) via migration. On Sequoia (macOS 15) the RFC822 Message-ID is not stored in the Envelope Index at all, so every sqlite-backed read trips SchemaDrift, and account_of() failing makes all destructive/move mail tools unreachable (issue #199 knock-on).
fix: null
verification: null
files_changed: []
