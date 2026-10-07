---
phase: quick-261007-o5a
plan: 01
subsystem: mail-reads
tags: [mail, gmail, labels, envelope-index, "#299"]
requires: ["#291 label guard (is_label_mailbox)"]
provides: ["third membership arm: Gmail label without source"]
affects: [mail_overview, mail_search, mail_thread, mail_awaiting_reply, mail_stats]
key-files:
  modified:
    - macos_apps_mcp/adapters/mail_index.py
    - tests/test_mail_membership.py
    - tests/integration/test_mail_reads_integration.py
    - docs/mail-applescript-facts.md
    - CHANGELOG.md
decisions:
  - "Arm 3 of _MAILBOX_MEMBERSHIP_CTE uses the write guard's rule: source IS NULL, no stored messages row, same-account labelled message"
  - "Parity integration test keeps its one-direction logic; comment only (orchestrator decision)"
metrics:
  completed: 2026-10-07
status: complete
commits: 3
plan_head_before: f7967f479c76e42703f600a8aaf6832667e9ebe8
plan_head_after: 4c313dd086188d6148dbac6ff1d283e42c7bf9d5
actuals:
  tasks: 3
  commits: 3
---

# Quick 261007-o5a: Reads count a Gmail label without source (#299) Summary

A third `UNION ALL` arm in `_MAILBOX_MEMBERSHIP_CTE` counts the `labels` rows of a
source-less mailbox that stores no message row, when the labelled message lives in the
same account. Every logical read (overview, search, thread, sent triage, stats) follows,
with no read-builder change.

## Commits

| Task | Commit | Subject |
|------|--------|---------|
| 1 | a0909a3 | fix(mail): reads count a Gmail label that has no source (#299) |
| 2 | 4c8b768 | test(mail): note the source-less label case in the parity check (#299) |
| 3 | 4c313dd | docs(mail): reads count a Gmail label without source (#299) |

No `.planning/` path in any commit. Nothing pushed.

## Task 1: RED, GREEN, mutation check

RED (before the CTE edit), `-k "without_source or sourceless"`:

- `test_overview_and_search_count_a_label_without_source[native|sidecar]`: FAILED,
  `assert (0, 0) == (1, 1)`.
- `test_thread_triage_and_stats_follow_a_label_without_source[native|sidecar]`: FAILED,
  the thread cited All Mail instead of the source-less Sent label.
- `test_a_sourceless_mailbox_with_stored_rows_counts_only_its_rows[native|sidecar]`:
  PASSED (guard, by design).

GREEN: membership, index, extras and triage test files: 195 passed. Arms 1-2 are
byte-identical to origin/develop (plan verify script printed `ok`); location, duplicate
and trash queries are unchanged; `tests/envelope.py` is unchanged.

Mutation check: with the same-account predicate removed,
`test_membership_obeys_the_mailbox_source` FAILED in both modes with
`assert (1, 1) == (0, 0)` on the ACCT_B mailbox. With the predicate restored it passed.

## Measurement (real Envelope Index, read-only, median of 5)

| Metric | Before | After |
|--------|--------|-------|
| Overview rows | 156 | 156 |
| Sum of totals | 102648 | 102648 |
| Rows with total > 0 | 126 | 126 |
| URLs whose total changed | - | 0 |
| `query_search(limit=25)` results | 25 | 25 |
| Membership rows | 132471 | 132471 |
| Median overview | 143.5 ms | 156.8 ms (+9 %) |
| Median search | 381.5 ms | 446.8 ms (+17 %) |

The membership delta is 0: this store holds no source-less label today. The timing
delta is the cost of arm 3 alone. Both medians are below the 50 % threshold.

## Verification (final, worktree root)

- `uv run pytest -q`: 1924 passed, 97 deselected.
- `MACOS_APPS_ALLOW_SEND=mail uv run pytest -q`: 1920 passed, 4 skipped, 97 deselected.
- `uv run ruff check .`: All checks passed.
- `uv run ruff format --check .`: 109 files already formatted.
- Unit count: 1924 (baseline 1918).
- The integration parity test was not run (device-only).

## Deviations from Plan

None in code. Task 2 follows the ORCHESTRATOR DECISION (comment only); the comment
contains `source IS NULL`, so the artifact `contains` check also holds.

Note: `git diff --name-only origin/develop..HEAD` lists `.planning/` files because
origin/develop is one records commit (c319051) ahead of this branch's base. The
three-dot diff (`origin/develop...HEAD`) shows only the five planned files.

## Follow-up candidates (out of scope)

- Whether Mail sets `source` later (for example after a relaunch) needs a device run
  with a new label. The orchestrator decides whether the PR closes #299.
- The new read has no device run yet. A check needs a fresh `create_mailbox` label with
  one message: `mail_overview` and a scoped `mail_search` against an AppleScript count.

## Self-Check: PASSED

All five files exist; commits a0909a3, 4c8b768 and 4c313dd are ancestors of HEAD.

## Orchestrator close-out (2026-10-07)

- Review (2 lenses, no blocking; should-fix: id lookup +47–50 %). Arm 3 rewritten to drive from a `bare_label` CTE (source-less, labelled, no LIVE row); real-index medians, old → new: id lookup ~100 → ~125 ms, search 400 → 445 ms, overview/thread/sent triage +5 to +15 ms, identical results. Tried and rejected: CROSS JOIN order (search 5.4 s), MATERIALIZED bare_label (sent triage 58 s).
- Deleted rows no longer make a mailbox look physical (reads and the write guard); account compared on `url || '/'`; test fixture `messages.deleted` is `NOT NULL DEFAULT 0` as in Mail's schema; two tests pin the deleted-row and pathless-url cases (both fail on the pre-review code).
- Device: `test_overview_count_parity_with_mails_own_counters` passes on the real index with the new CTE (read-only). The new arm itself has no device case: this store holds no source-less label today.
- Verification: 1928 passed; 1924 passed / 4 skipped with send; ruff clean; empty-HOME mail tests 364 passed.
