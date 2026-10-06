---
status: complete
phase: quick-261006-wa0
plan: 01
subsystem: mail
tags: [gmail, labels, write-safety, envelope-index]
requirements: [ISSUE-287]
commits: 3
plan_head_before: d66e8ad
plan_head_after: 10be175b0ff4e71c6f9f5cc17c281b1cd2b9c2ff
actuals:
  tasks: 3
  commits: 3
---

# Quick 261006-wa0: Gmail follow-ups to #251 (issue #287) Summary

A Gmail label folder is now refused as the source of `move_mail` and `trash_mail`
before any native call. Thread, sent triage and stats now follow Gmail label membership.
An on-device parity guard compares overview totals with Mail's own counters.

Branch `fix/287-gmail-followups` in the code lane. Three commits, nothing pushed.

## Commits

| Task | SHA | Subject |
| ---- | --- | ------- |
| 1 | 3c8beda | fix(mail): refuse a Gmail label folder as a move or trash source (#287) |
| 2 | a637b9d | fix(mail): Gmail label membership in thread, sent triage and stats (#287) |
| 3 | 10be175 | test(mail): overview parity guard; docs for Gmail follow-ups (#287) |

Each commit ends with the `Co-Authored-By: Claude Opus 5.5` trailer. No `.planning/`
file changed in the code lane.

## Tests

- Unit tests: 1851 at baseline, 1875 at HEAD (`rtk proxy uv run pytest --collect-only -q`:
  1875/1972 collected, 97 integration deselected; the integration count rose by one).
- `uv run pytest -q`: 1875 passed. `uv run ruff check .`, `uv run ruff format --check .`
  and `uv lock --check`: all clean (`uv lock` never run).
- Empty-HOME run of the four mail test files (as on CI): 246 passed.
- `tests/mail_recover_dry_run_baseline.json` untouched.

### RED evidence

- Task 1 (`tests/test_mail_membership.py`): 10 failed, 24 passed. The 10 failures were
  `is_label_mailbox` (missing function) and the two refusal tests, each in both
  `envelope_mode` params and, for the refusal tests, dry and wet. The two "physical source
  still previews" tests passed at RED by design: they pin behaviour that must not change.
  The failures reached the real write path, e.g. `trash_mail` raised
  `NativeError: no Trash mailbox found` instead of `WriteRefused`.
- Task 2: 10 failed, 34 passed. All five new behaviours (sent triage one row, answered,
  reply under another label stays unanswered, thread folder, stats attribution) failed on
  the old queries in both param modes.
- GREEN after each implementation: Task 1 246 passed; Task 2 full suite 1875 passed.

## Live read-only check (real Envelope Index, sqlite `mode=ro`, no AppleScript)

Script ran from the session scratchpad. `mail_index.__file__` proof: AFTER run printed a
path under the code lane; BEFORE run (develop, `PYTHONPATH` = main checkout) printed a path
under the main checkout, so the before numbers are valid.

| Measure | Before (develop) | After |
| ------- | ---------------- | ----- |
| `query_sent_triage(100000)` total rows | 9,819 | 10,848 |
| Gmail-account rows | 0 | 1,029 |
| Gmail rows `answered` | 0 | 17 |
| Full scan time | 0.09 s | 0.67 s |
| Median of 5, `SENT_SCAN` (100) | 0.057 s | 0.167 s |

1,029 matches the device fact (1,029 Gmail Sent Mail messages). One Gmail account.
The added cost is the membership CTE; the awaiting-reply scan stays well under a second.

## Parity guard

`uv run pytest -m integration -k parity -q`: 1 passed in 1.6 s. It checked 126 mailboxes
where Mail's `total_count` is above 0. None reads empty in `query_overview_rows()`.

## Deviations from Plan

**1. [Rule 3 - Blocking] A fourth stub site for `is_label_mailbox`.**
`tests/test_mail_recover_dry_run_identity.py` has a second fixture, `wired` (module-level
pytest fixture), next to `capture()`. The plan listed three sites. Under an empty HOME the
first run failed 4 tests (`no Mail data found`); stubbing `is_label_mailbox` in `wired`
fixed it. Commit 3c8beda.

**2. [Plan instruction] #251 CHANGELOG sentence removed.**
The last sentence of the #251 bullet ("A move or trash from a Gmail label folder now backs
up the target account's own copy.") was deleted, as the plan ordered. Both entries ship in
the same release, and the new #287 bullet states the end state. Commit 10be175.

**3. [Judgment] Line wraps.** Two lines (one docstring line, one test comment rule) were
shortened to satisfy ruff E501. No behaviour change.

The refusal names no other folder or route, per the orchestrator ruling.

## Known Stubs

None.

## Follow-up candidates (out of scope, not implemented)

- `mail_undo` of a move whose destination was a Gmail label replays FROM that label. This
  is the same copy-not-move route the plan now refuses. Undo is untouched by ruling.
- A move INTO a Gmail label from a physical folder (the add-a-label route) is not
  device-verified. Only sources are refused.

## Threat Flags

None. No new endpoint, auth path or file access. `is_label_mailbox` is one read-only
sqlite query with a bound parameter.

## Self-Check: PASSED

- Commits 3c8beda, a637b9d and 10be175 exist on `fix/287-gmail-followups`
  (`git log origin/develop..HEAD` shows exactly three).
- `git diff --name-only origin/develop..HEAD | grep -c '^\.planning/'` = 0.
- Trailer count over the three commits = 3.
- Added text contains no account names, UUIDs, addresses or custom label names.
