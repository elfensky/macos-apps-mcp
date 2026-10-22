---
phase: 05-operator-control-plane-adapter-toggles-and-the-localhost-das
plan: 04
subsystem: dashboard-writes
tags: [dashboard, audit, recovery, mail, receipts, escaping, read-only]
requires:
  - phase: 05-operator-control-plane-adapter-toggles-and-the-localhost-das
    provides: "05-03 dashboard audit records, html.page, SIDEBAR; 05-09 page key Guard and tests/_dashboard.py"
provides:
  - "audit.read_all(): the two-file reader (audit.jsonl.1 then audit.jsonl), explicit unreadable entry"
  - "GET / (write list) and GET /write/<ts>/<n> (write detail), 404 for a bad ts or ordinal"
  - "AuditMiddleware records carry the batch receipt when the tool result has one"
  - "dashboard.recovery: RECEIPT_RE, receipt_dir, backup_files, targets, outcomes, render_batch (reused by 05-05)"
  - "html.safe_href, html._DEEPLINK_SCHEMES, html.appico, page(mode=list), Writes and Apps sidebar groups"
affects: [05-05, 05-06, 05-07]
key-files:
  created:
    - macos_apps_mcp/dashboard/writes.py
    - macos_apps_mcp/dashboard/recovery.py
    - tests/test_dashboard_writes.py
  modified:
    - macos_apps_mcp/audit.py
    - macos_apps_mcp/dashboard/__init__.py
    - macos_apps_mcp/dashboard/html.py
    - macos_apps_mcp/dashboard/dashboard.css
    - tests/test_audit.py
    - CHANGELOG.md
key-decisions:
  - "D-12: a batch is one row; outcomes come from done.results, never the plan status; the middleware line links by its receipt key, else by adjacency"
  - "D-13: recovery is read-only; a receipt must match RECEIPT_RE before any path is built; the undo is a copyable prompt"
  - "Recovery rows show the Message-ID, not the subject (flagged assumption kept: no Envelope Index or .eml read)"
requirements: [PLAT-02]
requirements-completed: [PLAT-02]
status: complete
commits: 8
plan_head_before: 37485f98e0137ffe82056c5c21c12b8a3c8616f8
plan_head_after: a9ad8e43021dd1bc7fdf5ebfcfb14272884f59cd
pr: 418
merge_sha: a9ad8e43021dd1bc7fdf5ebfcfb14272884f59cd
actuals:
  tokens: 120000
  tasks: 4
  commits: 8
coverage:
  - id: D1
    description: "read_all returns both files oldest first, skips corrupt lines, and yields one explicit error entry for an unreadable file"
    requirement: PLAT-02
    verification:
      - kind: unit
        ref: "tests/test_audit.py#test_read_all_returns_both_files_oldest_first"
        status: pass
      - kind: unit
        ref: "tests/test_audit.py#test_read_all_unreadable_file_is_one_explicit_error_entry"
        status: pass
    human_judgment: false
  - id: D2
    description: "A write is a list row and a detail with word diff, resolved dry_run, preview banner (legacy trash_mail) and raw lines; ordinals address same-second rows; bad ts or ordinal is 404"
    requirement: PLAT-02
    verification:
      - kind: unit
        ref: "tests/test_dashboard_writes.py#test_detail_word_diff_resolved_dry_run_and_raw_line"
        status: pass
      - kind: unit
        ref: "tests/test_dashboard_writes.py#test_preview_a_legacy_record_reads_as_a_preview_not_a_write"
        status: pass
      - kind: unit
        ref: "tests/test_dashboard_writes.py#test_ordinal_counts_rows_sharing_a_timestamp_and_bad_ones_are_404"
        status: pass
    human_judgment: false
  - id: D3
    description: "Plan, done and the move line are one batch row; the receipt key beats adjacency; a dedupe CLI pair is a batch; the undo prompt shows only when find_receipt resolves; undone and undo-record banners"
    requirement: PLAT-02
    verification:
      - kind: unit
        ref: "tests/test_dashboard_writes.py#test_batch_plan_done_and_move_read_as_one_row"
        status: pass
      - kind: unit
        ref: "tests/test_dashboard_writes.py#test_the_receipt_key_links_exactly_and_beats_adjacency"
        status: pass
      - kind: unit
        ref: "tests/test_dashboard_writes.py#test_undo_prompt_only_when_the_plan_resolves"
        status: pass
      - kind: unit
        ref: "tests/test_audit.py#test_middleware_record_carries_the_batch_receipt"
        status: pass
    human_judgment: false
  - id: D4
    description: "Recovery never touches the filesystem on a bad receipt or a symlinked folder, never calls _backup_dir, purge_backup or backup_usage, and never creates the backup tree"
    requirement: PLAT-02
    verification:
      - kind: unit
        ref: "tests/test_dashboard_writes.py#test_receipt_path_tricks_never_reach_the_filesystem"
        status: pass
      - kind: unit
        ref: "tests/test_dashboard_writes.py#test_rendering_never_creates_the_backup_tree"
        status: pass
    human_judgment: false
  - id: D5
    description: "Every audit string renders escaped; a javascript:, data: or file: deeplink gives no href"
    requirement: PLAT-02
    verification:
      - kind: unit
        ref: "tests/test_dashboard_writes.py#test_escape_every_audit_string_and_the_deeplink_scheme"
        status: pass
      - kind: unit
        ref: "tests/test_dashboard_writes.py#test_escape_batch_fields"
        status: pass
    human_judgment: false
  - id: D6
    description: "Search, previews switch, filters, sidebar counts without previews, day headers, empty and unreadable states, kept query, 3000-record render under 3 s"
    requirement: PLAT-02
    verification:
      - kind: unit
        ref: "tests/test_dashboard_writes.py#test_search_matches_words_ids_and_folds_case_and_diacritics"
        status: pass
      - kind: unit
        ref: "tests/test_dashboard_writes.py#test_filter_narrows_to_batches_outbound_or_one_app"
        status: pass
      - kind: unit
        ref: "tests/test_dashboard_writes.py#test_a_large_log_renders_fast"
        status: pass
    human_judgment: false
  - id: D7
    description: "Dashboard audit records (toggle, discard, restart) render truthfully: no fake diff, no undo prompt, no backup banner, caller dashboard"
    requirement: PLAT-02
    verification:
      - kind: unit
        ref: "tests/test_dashboard_writes.py#test_dashboard_records_render_truthfully"
        status: pass
    human_judgment: false
  - id: D8
    description: "The pages look like sketches 001, 002 and 003 in a real browser, light and dark, and on a phone width"
    verification: []
    human_judgment: true
    rationale: "No browser was driven; 05-07 compares the pages with the sketches"
duration: 55min
completed: 2026-10-22
---

# Phase 5 Plan 04: Write list, write detail and read-only recovery — PR #418

The dashboard's home page now lists every write in the audit log, shows what each one changed, and shows each Mail batch with its backups and a prompt to copy for Claude's `mail_undo`. PR #418 was rebase-merged into develop with the required `check` green.

## Performance

- **Tasks:** 4 of 4. **Commits:** 8 (RED before GREEN for Tasks 1 to 3, one self-review fix, one CHANGELOG).
- **Files:** 9 changed (3 new), +1954 / -24.
- **Tests:** 2422 passed (full); 2407 passed and 15 skipped under `MACOS_APPS_READ_ONLY=1`; 2416 passed and 6 skipped under `MACOS_APPS_ALLOW_SEND=mail`. `ruff check` and `ruff format --check` clean. Baseline before the plan: 2387 passed.
- After the suite, the real `~/.local/state/macos-apps-mcp/daemon/dashboard_key` and `adapters_off` were still absent. The real daemon was not touched.

## Accomplishments

- **Reader (D-12).** `audit.read_all()` reads `audit.jsonl.1` then `audit.jsonl`, no cache, no limit; a corrupt line is skipped; an unreadable file adds one `{"error": …}` entry that the list shows as a `banner bad`. `audit_read` and the `audit` tool are unchanged.
- **List and detail (D-11).** `GET /` and `GET /write/<ts>/<n>` follow sketches 001 and 002 variant D: day headers, time, app icon, mono tool name, chip, dimmed previews; the detail has the word diff, the args with `dry_run` resolved, the preview banner and the raw lines collapsed. Legacy records without `dry_run` use `registry.dry_run_defaults()` through `audit._resolve_dry_run`.
- **Batches (D-12, D-13).** `build_rows` groups `mail_recover` plan and done records by receipt into one row. The middleware line joins by its new `receipt` key, else by adjacency. `recovery.render_batch` shows per message: Message-ID, file name and size or `no file`, a fidelity chip and the outcome from the done record. The undo prompt and the collapsed exact call appear only when `mail_recover.find_receipt` resolves the plan and the batch is not undone.
- **Safety.** `RECEIPT_RE` runs before any path is built; the folder must be a real directory, not a symlink, directly under the backup root; only names and sizes of regular files are read. No route writes. `safe_href` allow-lists deeplink schemes.
- **Finding (D-11).** Search folds case and diacritics (`text.fold_text`), all terms must match; previews switch, `receipt` / `outbound` / `app:<adapter>` filters, sidebar counts without previews, phone layout with a Back link.

## Decisions Made

- Recovery rows show the Message-ID, not the subject. The plan record holds no subject and the dashboard reads neither the Envelope Index nor the `.eml` files. Search finds a batch by Message-ID, folder, destination or receipt id. (Flagged assumption of the plan, kept; named in the PR body.)
- `_BATCH_TOOLS` = `{"move_mail": "move", "trash_mail": "trash", "mail_undo": "move"}`: tool to the plan op it writes. These are the tools whose adapter methods call `mail_recover.recoverable` (`mail_undo` replays through `move_mail`). Adjacency also requires the plan op to match and the line to be a real call.
- Deeplink scheme set (`_DEEPLINK_SCHEMES`), from the adapters' Pointer builders: `addressbook`, `calshow`, `http`, `https`, `imessage`, `message`, `shortcuts`, `x-apple-reminderkit`. (`http` for Safari tab URLs; `imessage` and `calshow` found by the grep beyond the plan's expected list.)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] A corrupt record's `op` crashed a page**
- **Found during:** Task 4 self-review
- **Issue:** an `op` that is a list is unhashable and raised in the verb tables.
- **Fix:** `_op()` reads `op` as a string or not at all; a test feeds odd records (list op, int ts, non-dict args, receipt as list).
- **Files modified:** macos_apps_mcp/dashboard/writes.py, tests/test_dashboard_writes.py
- **Commit:** e125007

### Plan text corrected

- The plan's day-header example `Mon 22 Sep` is a 2025 date; 22 Sep 2026 is a Tuesday. The weekday is computed from the date, and the test expects `Tue 22 Sep`.
- `html.page(mode="list")` takes `listing`, `selected` and `counts` arguments (the plan named only the mode). The existing `mode="console"` is unchanged.
- Added beyond the plan, all small: a `Filter` submit button in the search form (the CSP forbids the inline script a checkbox would need, so the form works without JS); a distinct `No writes recorded yet` state for an empty log; build_rows sorts by time, newest first, with ties in reverse file order; a done record without a plan still forms a batch row.

## Code review (inline, no sub-agent tool)

Reviewed `origin/develop...HEAD` against the plan, D-09, D-11, D-12, D-13 and sketch rules 8 to 10.

- **Escaping:** every `Safe(` in writes.py and recovery.py wraps a constant or an already-escaped assembly (word diff and JSON tokens escape each part). Tests render `<script>`, an attribute breakout and hostile `javascript:` / `data:` deeplinks, a hostile target id and destination, and hostile dashboard args. No finding open.
- **Paths:** receipt checked by regex first; symlinked receipt folder and `../../etc` both list nothing (test with a decoy file). The file name shown must match `\d+\.eml` and exist in the folder listing. No finding open.
- **GET side effects:** the pages read `audit.read_all`, `find_receipt` and a directory listing. `audit.state_dir()` creates only the state dir that the audit log already needs; the backup tree stays absent (test). `_backup_dir`, `purge_backup` and `backup_usage` are patched to fail in a test and are never called.
- **Robustness:** one finding (the unhashable `op`), fixed in e125007.
- **Residual, not fixed:** the sidebar counts read and parse the log on every dashboard page, including Usage and Adapters, so each request costs two file reads (the plan accepts about 40 ms). `find_receipt` scans the last 2000 lines only, so an old batch can read "rotated out" while its plan is still in `audit.jsonl.1`; the page states this truthfully.

## Known Stubs

None.

## Threat Flags

None. No new network endpoint or write path; the new routes are two GETs behind the Guard.

## Issues Encountered

None blocking.

## Self-Check: PASSED

Files found: writes.py, recovery.py, tests/test_dashboard_writes.py, audit.py (`read_all`, `_audit_receipt`). The PR is MERGED; `origin/develop` holds `read_all` and `_audit_receipt`. The lane and branch are removed; the vault journal bullet is logged.
