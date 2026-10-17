---
status: complete
phase: quick-261018-1sb
plan: 01
requirements: [ISSUE-359]
commits: 2
plan_head_before: 8c2e34a
plan_head_after: 3fbc3d0
actuals:
  tasks: 2
  commits: 2
---

# Quick 261018-1sb: #359 account map re-read Summary

`mail_overview` now re-reads the account map once (at most once per 60 s) when a non-empty map omits a non-local uuid. A failed or empty re-read keeps the previous non-empty map.

## Commits

- `08bbb5f` test(mail): mail_overview re-reads the account map once for an unknown id (#359) — RED
- `3fbc3d0` fix(mail): re-read the account map once before labelling an unknown account (#359) — GREEN

## RED (Task 1)

All 8 ids failed on assertions, none on errors:
- `test_overview_label_rereads_once_and_names_an_added_account[native|sidecar]`: `'(account not in Mail)' == 'Work'`.
- `..._rereads_a_removed_account_once_and_keeps_the_label`, `..._rereads_at_most_once_per_ttl`, `..._rereads_keep_the_names_when_mail_does_not_answer` (each x2): `assert 0 == 1` (no osascript call, today `overview()` never re-reads).
- The other 180 tests in `tests/test_mail_search.py` passed.

## Changes

- `mail_addressing.py`: `_ACCOUNT_MAP_REFRESHED_AT` and `refresh_account_map()`; `account_map()` docstring updated.
- `mail.py` `overview()`: rows parsed once before the loop; one `refresh_account_map()` call when `names` is non-empty and any row has `scheme != "local"`, a non-empty uuid, and `uuid not in names`.
- `tests/conftest.py`: resets `_ACCOUNT_MAP_REFRESHED_AT`; docstring updated.
- `CHANGELOG.md`: `[Unreleased]` / `Fixed` bullet for #359.

## Existing tests that received `_mail_lists(monkeypatch, {ACCT_A: "Personal"})`

Five, not the four predicted. The fifth has the same shape (seeds `{ACCT_A: "Personal"}`, ACCT_B absent) and failed on the conftest refusal only:
1. `test_overview_reports_counts_and_decodes_names`
2. `test_overview_names_the_on_my_mac_store`
3. `test_overview_label_tracer_over_the_in_memory_client`
4. `test_overview_reports_the_account_id_search_pointers_carry`
5. `test_on_my_mac_name_round_trips_from_overview_into_search` (not predicted)

`test_overview_label_is_not_shown_for_an_empty_map` and `test_overview_label_replaces_an_empty_name` pass unchanged, with no fake.

## Verification (lane, after the GREEN commit)

| Command | Exit | Summary line |
| --- | --- | --- |
| `uv run pytest -q` | 0 | 2031 passed, 97 deselected |
| `MACOS_APPS_READ_ONLY=1 uv run pytest -q` | 0 | 2019 passed, 12 skipped, 97 deselected |
| `MACOS_APPS_ALLOW_SEND=mail uv run pytest -q` | 0 | 2027 passed, 4 skipped, 97 deselected |
| `uv run ruff check .` | 0 | All checks passed! |
| `uv run ruff format --check .` | 0 | 109 files already formatted |

Collected: 2031 unit tests (baseline 2023 + 8). `uv.lock` unchanged. Nothing pushed.

## Deviations from Plan

**[Rule 3 - Blocking] Fifth test needed the fake.** `test_on_my_mac_name_round_trips_from_overview_into_search` also reached osascript. Same fix as the other four; no other test changed.

## Out-of-scope follow-ups

- Empty-name account (#359 "Decide separately"): still reads `(account not in Mail)`, pinned by `test_overview_label_replaces_an_empty_name`.
- Cost with a removed account: one `_ACCOUNTS` osascript run per minute at most, and it launches Mail if the user quit it. A later change can skip the re-read when Mail is not running.
- Device proof (operator): after the next daemon rebuild, add an account in Mail while the daemon runs, then call `mail_overview` once. Its rows must show the account name.

## Known Stubs

None.
