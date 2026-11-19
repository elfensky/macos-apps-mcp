---
phase: 04-notes-photos-settle-the-mechanism-then-ship-the-read-plane
plan: 02
subsystem: files
tags: [files, mail, security, refactor, D-11]
requires: []
provides:
  - "macos_apps_mcp/files.py: shared write-to-disk rules (root, safe_basename, resolve_dest, target_path, check_size, confirm_written)"
  - "mail_attachments.MAIL_MAX_BYTES: Mail's own 25 MiB cap"
affects: [04-05]
tech-stack:
  added: []
  patterns: ["per-caller cap, keyword-only, no module default", "neutral shared module; caller wording through fallback= and hint="]
key-files:
  created: []
  modified:
    - macos_apps_mcp/files.py
    - macos_apps_mcp/adapters/mail.py
    - macos_apps_mcp/adapters/mail_attachments.py
    - tests/test_files.py
    - tests/test_mail_extras.py
    - docs/mail-applescript-facts.md
decisions:
  - "D-11 landed: write-to-disk rules live in macos_apps_mcp/files.py; the size cap is the caller's"
metrics:
  tasks: 3
  duration: "about 1 hour"
  completed: 2026-10-18
status: complete
commits: 4
plan_head_before: cb36415af39880bb2de1e5c4b898ded4abaa1fbf
plan_head_after: e8db94dd72d4b1585b841ddcbcb256ac46148554
actuals:
  tokens: 8200
  tasks: 3
  commits: 4
---

Write-to-disk rules shared as macos_apps_mcp.files, per-caller size cap, Mail unchanged — PR #364

# Phase 04 Plan 02: Shared files module Summary

**One-liner:** `adapters/mail_files.py` moved with `git mv` to `macos_apps_mcp/files.py`; `check_size` and `confirm_written` take the cap and the wording from the caller, so Photos (04-05) can reuse the audited rules.

## What changed

- `git mv` of the module and of its test suite (history follows: `git log --follow` lists 3 commits for `files.py` after the rebase-merge).
- `files.check_size(size, name, *, max_bytes, hint="")`: the cap is keyword-only with no default. `files` has no module-level byte cap.
- `files.confirm_written(path, *, hint="")`: the 0-byte refusal takes the caller's explanation. The fallback literal is now `file`. The outside-root refusal says "files can only be written under it".
- `mail_attachments.MAIL_MAX_BYTES = 25 * 1024 * 1024` (same value as before, same argv value). Mail passes `fallback="attachment"`, `hint="Save it from Mail directly."` and its old "not available locally" sentence. `mail.py` export keeps `fallback="message"`.
- `docs/mail-applescript-facts.md` names `files` and `tests/test_files.py`. `docs/landscape.md` line 46 stays as written (historical).
- The module docstring no longer holds a literal U+202E character; it names the code point in words.

## Commits (on origin/develop after the rebase merge)

| Task | Commit | Message |
| ---- | ------ | ------- |
| 1 (tracer) | 6bf6e0e | refactor(files): the write-to-disk rules move to a package-level files module (D-11) |
| 2 RED | fa5edfe | test(files): per-caller cap and neutral refusals (D-11) |
| 2 GREEN | a2774e1 | refactor(files): the size cap is per caller; refusals no longer say mail (D-11) |
| 3 | e8db94d | docs(mail): the facts doc names the shared files module (D-11) |

PR: https://github.com/elfensky/macos-apps-mcp/pull/364 (rebase-merged, required `check` job green in 1m34s). Feature-branch SHAs before the rebase: aa119d6, 07d84ec, d5624c8, 59a29c9.

## Tracer gate (Task 1)

Behaviour identical. `tests/test_files.py` reported 37 passed, the same count as the baseline recorded from `tests/test_mail_files.py` before the move. `find_spec('macos_apps_mcp.adapters.mail_files')` is `None`. `git log --follow` on `files.py` listed more than 1 commit. `pytest tests/test_mail_extras.py -k export` reported 6 passed. Full suite and ruff were green before the next task started.

## TDD record (Task 2)

- RED: 16 tests failed before the implementation. Failures were `TypeError: check_size() got an unexpected keyword argument 'max_bytes'`, `AssertionError` on `hasattr(files, "MAX_BYTES")` and `AttributeError` on `mail_attachments.MAIL_MAX_BYTES`. The fallback table failed on the `file` literal. Semantic assessment: every failure is on the planned API change, none is an import, collection or fixture fault; the Mail regression tests that already passed (hostile name, 0-byte wording) were kept as guards. The `gsd_run check tdd-red-evidence` classifier has no pytest adapter, so no machine verdict exists; the assessment above is the manual one.
- GREEN: same 16 tests pass; 245 tests across the four Mail and files suites pass.
- REFACTOR: none needed.

## Local checks (final HEAD of the lane)

- `uv run pytest -q`: 2035 passed, 97 deselected
- `MACOS_APPS_READ_ONLY=1 uv run pytest -q`: 2023 passed, 12 skipped, 97 deselected
- `MACOS_APPS_ALLOW_SEND=mail uv run pytest -q`: 2031 passed, 4 skipped, 97 deselected
- `uv run ruff check .`: All checks passed
- `uv run ruff format --check .`: 109 files already formatted
- `git diff --name-only origin/develop` listed neither `pyproject.toml` nor `uv.lock` (T-04-SC)

## Code review (`code-review` skill, inline, `origin/develop...HEAD`)

The review ran both axes in this session because no sub-agent tool was available to the executor.

- Standards: no breach of the documented repo style; no baseline smell worth a finding.
- Spec (D-11): all must-have truths covered. One plan-sanctioned wording change for Mail callers: the outside-root refusal says "files" instead of "mail".
- Result: 0 open findings, so no fix commit.

## Device run (lane code, scratch root, Mail watchdog loaded)

- Watchdog: `launchctl list` listed `ren.lav.mail-watchdog`; `watchdog.log` was modified within the last 2 minutes before the run and again after it. No Mail hang occurred, so `capture.sh` was not needed.
- `save_attachment` on an existing downloaded attachment: `bytes` 321, file on disk 321, above 0, path inside the root. True.
- Second save of the same attachment: refused with `FileExistsError` whose text holds `already exists`, before Mail writes. True.
- `export` of the same message: 1 result, status `written`; `.eml` size 36648 equals its `bytes`; file holds a `Message-ID:` header line; path inside the root. True.
- Cleanup: the scratch root and the device script were removed (checked with `test ! -e`).
- The script printed statuses, sizes and booleans only. No message id, subject, attachment name, address or path appears here.

## Changelog line

Internal: the write-to-disk rules moved from `adapters/mail_files.py` to `macos_apps_mcp/files.py` with a per-caller size cap; Mail behaviour is unchanged.

## Deviations from Plan

None to the code. Process notes:

- **[Process] Pre-commit allow-list.** The executor boilerplate wants worktree HEADs in the `agent-*` namespace. This plan owns the lane `refactor/files-module` by design, so that check was not applied; the supplied-root pin ran before each write and commit instead.
- **[Process] Shared scratchpad.** A parallel executor overwrote a shared `pin.sh` in the session scratchpad once (the pin printed another lane's root). The pin failed closed, no commit was made. A uniquely named pin file was used from then on.
- **[Process] Plan commit ledger.** The `gsd-plan-head-before` ledger was not created. `plan_head_before` is the lane's fork point `cb36415` (`origin/develop` at lane creation) and `commits: 4` was measured with `git rev-list --count cb36415..e8db94d` on the merged `develop`.
- **[Process] Code review** was done inline (see above).

## Known Stubs

None.

## Threat Flags

None. T-04-05 and T-04-06 mitigated by the unchanged hostile-name and overwrite suite moving with the module (same passed count); T-04-07 by the keyword-only `max_bytes` (TypeError tests); T-04-28 by the statuses-only device script.

## Self-Check: PASSED

- `macos_apps_mcp/files.py` and `tests/test_files.py` exist on `origin/develop`; the `grep -c` of the four function names on `origin/develop:macos_apps_mcp/files.py` prints 4.
- Commits 6bf6e0e, fa5edfe, a2774e1, e8db94d are ancestors of `origin/develop`.
- PR #364 state `MERGED`; lane `.worktrees/files-module` and the device script removed; `refactor/files-module` branch deleted.
- Vault journal bullet logged (journal-add, MR 1598 merged).
