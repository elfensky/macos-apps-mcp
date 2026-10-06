---
phase: quick-261006-uff
plan: 01
subsystem: mail
tags: [mail, gmail, pr-251, recover-plane, envelope-index]
status: complete
requirements: [PR-251-HARDEN]
commits: 3
plan_head_before: 096cccf
plan_head_after: 4afe4f4
actuals:
  tasks: 3
  commits: 3
---

# Quick 261006-uff: Harden PR #251 (Gmail label membership) Summary

Three commits on `pr-251` in the code lane, on top of the contributor commit `096cccf` (unmodified, still an ancestor). Nothing pushed.

## Commits

| Task | SHA | Message |
| ---- | --- | ------- |
| 1 | 17fe8bf | fix(mail): back up the target account's copy for a Gmail label folder (#251) |
| 2 | 78252b6 | fix(mail): deterministic label citation and UNION ALL membership (#251) |
| 3 | 4afe4f4 | docs(mail): changelog and device-verified facts for Gmail labels (#251) |

## What changed

- **T1** `mail_recover.locate` picks, in order: the row whose `mailbox_url == t.folder`; else (only when `t.account` is set) the first row whose `mail_index.account_of(url) == t.account`; else `candidates[0]`. Docstring extended. No change to `query_message_locations`.
- **T2** `_BASE_SQL` window ends with `mb.ROWID`; `_MAILBOX_MEMBERSHIP_CTE` uses `UNION ALL` with a disjointness comment; fingerprint comment added; `build_overview_query` docstring corrected (false stale-counter reason removed, outer-join warning restored); `build_duplicate_summary_query` docstring qualified to direct mailboxes; comments in `tests/test_mail_index.py` and `tests/envelope.py` corrected.
- **T3** CHANGELOG: one house-form `(#251)` entry replaces the contributor's four-line entry. Facts §5f: dated 2026-10-06 device-verification block with the three facts.

## RED then GREEN evidence

- **T1:** the new test `test_locate_prefers_the_targets_own_account_for_a_gmail_label_folder` failed before the fix (`99 != 10`, the other account's row) and passes after (35 passed in `tests/test_mail_recover.py`).
- **T2:** `test_unscoped_search_breaks_an_equal_rank_label_tie_by_mailbox_rowid` failed in both `[native]` and `[sidecar]` on the SQL-shape assertion (`m.ROWID, mb.ROWID) AS rn` absent from `_BASE_SQL`) and passes after the fix. The behavioural half passed throughout, as the plan predicted.

## Test counts

- Before (at `096cccf`): 1848 passed, 96 deselected.
- After T1: 1849 passed. After T2 and T3: 1851 passed, 96 deselected (T1 +1, T2 +2 for native and sidecar).
- Final: `uv run pytest -q` 1851 passed; `uv run ruff check .` All checks passed; `uv run ruff format --check .` 108 files already formatted.

## Gates

- `git log --oneline 096cccf..HEAD`: exactly 3 commits, each subject ends `(#251)`, each body ends with the Co-Authored-By trailer.
- `git diff --name-only 096cccf..HEAD`: 8 files (CHANGELOG.md, docs/mail-applescript-facts.md, mail_index.py, mail_recover.py, tests/envelope.py, tests/test_mail_index.py, tests/test_mail_membership.py, tests/test_mail_recover.py). No `.planning/` path. `git status --porcelain` is clean.
- Contributor commit author is still the contributor.
- The T3 grep gate (no UUID or email in added CHANGELOG/facts lines) passed.

## Deviations from Plan

None. Notes only:

- Added test lines contain synthetic placeholders required by the plan's own test spec: a second-account UUID in the same all-letters style as the existing test constants, and an `example.test` reserved-domain Message-ID header. Neither is a real account, address or label. They are the only added-line matches of a broad UUID/`@domain` grep across the whole diff.
- The `locate` fix was written as three sequential `if`/`next` steps instead of one expression, for readability. Behaviour is as specified.

## Known Stubs

None.

## Threat Flags

None. No new network, auth, file-access or schema surface.

## Self-Check: PASSED

All three commits exist in `096cccf..HEAD`; all 8 touched files exist.
