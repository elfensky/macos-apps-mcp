---
phase: quick-261007-1bq
plan: 01
subsystem: mail, doctor
tags: [gmail, labels, move_mail, mail_undo, doctor, "#291", "#285"]
requires: []
provides:
  - "mail_index.account_has_labels, spelling-proof is_label_mailbox (one _label_keys read)"
  - "move_mail: canonical source ValueError; label / canonical-into-labelled-account destination WriteRefused"
  - "mail_undo: undo-specific WriteRefused for label or canonical receipt destination"
  - "doctor().libs = {mcp, fastmcp}"
key-files:
  modified:
    - macos_apps_mcp/adapters/mail_index.py
    - macos_apps_mcp/adapters/mail.py
    - macos_apps_mcp/server.py
    - macos_apps_mcp/doctor.py
    - tests/test_mail_membership.py
    - tests/test_mail.py
    - tests/test_mail_cleanup.py
    - tests/test_mail_recover_dry_run_identity.py
    - tests/test_doctor.py
    - docs/mail-applescript-facts.md
    - docs/DAEMON.md
    - CHANGELOG.md
decisions:
  - "_refuse_label_source generalised to _refuse_label_route(source, destination=None); no parallel function"
  - "Test stubs now patch mail_index._label_keys (one stub covers both helpers)"
metrics:
  tasks: 3
  files: 12
status: complete
commits: 5
plan_head_before: 70186a1f5e609cd3d8b1b6b12552726a8fda37a1
plan_head_after: a05f966cfeb09bd9bc9451ccbf829592fd99e0a6
actuals:
  tasks: 3
  commits: 5
---

# Phase quick-261007-1bq Plan 01: Gmail write gaps (#291) and doctor libs (#285) Summary

Every `move_mail` route that touches a Gmail label folder, or a unified name that could resolve to one, now fails before any native call (dry runs included); `mail_undo` explains the receipts it cannot replay; `doctor()` reports the bundled `mcp` and `fastmcp` versions.

## Commits

| SHA | Subject |
| --- | ------- |
| fa816b6 | fix(mail): match a Gmail label url decoded or re-cased (#291) |
| 87da036 | fix(mail): refuse a canonical move source and a move into a Gmail label (#291) |
| 1b6fdf9 | fix(mail): mail_undo explains a move into a Gmail label or a unified name (#291) |
| 0a76913 | fix(doctor): report the bundled mcp and fastmcp versions (#285) |
| a05f966 | docs(mail): record the #291 refusals around Gmail label folders (#291) |

## RED output (recorded)

Task 1, lookup half (before `mail_index` change): 4 failed (`test_is_label_mailbox_matches_any_spelling` and `test_account_has_labels`, native + sidecar); `AttributeError: module 'macos_apps_mcp.adapters.mail_index' has no attribute 'account_has_labels'`, and the spelling test failed on the decoded / re-cased urls.

Task 1, route half (before `mail.py` change): `10 failed, 6 passed`. Failing: `test_move_mail_refuses_a_label_destination` (4), `test_move_mail_refuses_a_canonical_destination_into_a_labelled_account` (4), `test_move_mail_refuses_a_canonical_source` (2; the fake run_osascript raised "must refuse before Mail is touched"). The label-source-in-any-spelling test and the "still allowed" test were already green, because commit A had landed.

Task 2 (before `undo` change): `8 failed, 2 passed`. The label cases failed because move_mail's #287 wording has neither "by hand" nor the backup dir; the canonical cases failed on move_mail's canonical-source `ValueError`. The physical-destination replay stayed green.

Task 3 (before `doctor` change): `test_diagnose_shape` failed (no `libs` key); `test_version_reads_any_distribution` failed with `TypeError` (no `dist` parameter).

## Verification (real output, from the worktree root)

- `uv run pytest -q`: `1906 passed, 97 deselected` (baseline 1875, +31).
- `MACOS_APPS_ALLOW_SEND=mail uv run pytest -q`: `1902 passed, 4 skipped, 97 deselected`.
- `uv run ruff check .`: `All checks passed!`
- `uv run ruff format --check .`: `109 files already formatted`
- Empty-HOME runs (`HOME=$(mktemp -d) .venv/bin/python -m pytest -q -p no:cacheprovider` on the mail test files): before the stub change, `test_move_mail_allows_a_unified_destination_from_an_imap_source` failed (the unstubbed `account_has_labels` read hit the missing store). After the `_label_keys` stubs: `276 passed` (Task 1 files) and `245 passed` (Task 2 files).
- `tests/mail_recover_dry_run_baseline.json` byte-identical to `70186a1`.
- `git diff --name-only 70186a1..HEAD | grep -c '^\.planning/'` = 0; 5 commits, 5 with the `Co-Authored-By: Claude Opus 5.5` trailer; nothing pushed.

## Deviations from Plan

- **Co-author trailer / branch allow-list:** the executor's generic pre-commit check that a worktree HEAD be in the `agent-*` namespace was not applied; the orchestrator's named lane `fix/gmail-write-gaps` is the required branch. HEAD was never a protected branch.
- **Plan-file note:** the plan says the 4 stub sites patch `is_label_mailbox`; they were replaced as specified by a `_label_keys` stub (`lambda: frozenset()`).
- No other deviation. No deviation rules 1-4 triggered.

## Notes and out-of-scope flags

- AGENTS.md deliberately not changed (no Mail write-rules list there).
- #291 item 5 (device check of `update_mail_status`, `mail_body`, `mail_attachments`, `save_mail_attachment`, reply/reply-all/forward on label folders) is left to the orchestrator; facts §5f ends with the "Decided 2026-10-07, not device-verified (#291)" block, ready for those results.
- A pre-#287 `trash_mail` receipt whose source was a Gmail label replays as a move INTO that label, so `undo` answers with move_mail's label-destination wording (Task 1), not the Task 2 undo wording. Safe; reword only if it appears in practice.
- The full unit suite passes on this machine with a real Envelope Index present; the empty-HOME runs prove no unstubbed call site reaches it.

## Known Stubs

None.

## Threat Flags

None. No new network endpoint, auth path or file access; mitigations T-1bq-01 to T-1bq-04 and T-1bq-07 applied (fixture UUIDs only in added text).

## Self-Check: PASSED

All five commits are ancestors of HEAD (`git rev-list --count 70186a1..HEAD` = 5); modified files exist; unit and lint checks green as listed above.

## Orchestrator close-out (2026-10-07)

- Rebased onto develop after the v0.14.0 cut; CHANGELOG entries moved into the new `[Unreleased]` / `### Fixed`.
- #291 item 5 run on device and recorded in facts §5f (commit `docs(mail): device results for the other Mail tools on a Gmail label (#291)`): `mail_body`, `mail_attachments`, `update_mail_status`, `save_mail_attachment` work from label folders; `mail_reply`, `reply_all`, `forward_mail` not run.
- New guards checked against the real Envelope Index with `osascript` blocked: 7/7 refusals, no native call; a non-Gmail move still passes.
- Found on device, not fixed: a stale Mail store row (facts §5f); `save_mail_attachment` names an id-only save after the id (#296).
- PR #295 (Fixes #291, #285), base develop. Verification after rebase: 1906 passed; 1902 passed / 4 skipped with send; ruff clean.

## Addendum — item 4 device run (2026-10-07)

- Protocol reviewed by a 3-lens workflow before the run; results reviewed by a second 3-lens workflow. Probe ran the develop 70186a1 copy from the scratchpad; Mail slow (health 5.9–10.8 s, memory paging), pid unchanged throughout.
- T1 (Personal INBOX → new Gmail label): `ok`, a move. T3 (`mail_undo` of T1): `ok`, but the Gmail copy was back by +2 min. T2 (All Mail → INBOX): present in BOTH. Cleanup: three `trash_mail` from physical folders, held to +15 min; empty label `mcp-291-probe` left for removal by hand.
- New finding: a label made by `create_mailbox` keeps `source IS NULL` (38 min), so the label guard missed it. `_label_keys` was replaced by `_label_state` (sourced keys, same-account label accounts, physical keys); a folder with no stored row or an unknown url in a label account is a label.
- Commits on top: `fix(mail): recognise a new Gmail label that has no source (#291)`, `fix(mail): refusal texts state what the device run showed (#291)`, `docs(mail): device results for a move into a Gmail label (#291)`. Verification: 1918 passed; 1914 passed / 4 skipped with send; ruff clean; empty-HOME mail tests 298 passed.
- Filed: #299 (reads see a source-less label as empty), #296 (attachment id naming).
