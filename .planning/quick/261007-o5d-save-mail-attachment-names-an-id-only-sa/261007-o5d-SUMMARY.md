---
phase: quick-261007-o5d
plan: 01
subsystem: mail
tags: [mail, attachments, filesystem, "#296"]
status: complete
requires: []
provides:
  - id-only save_mail_attachment named after the listed attachment name
affects: [save_mail_attachment]
tech-stack:
  added: []
  patterns: [listing read before the write path is computed]
key-files:
  created: []
  modified:
    - macos_apps_mcp/adapters/mail_attachments.py
    - tests/test_mail_extras.py
    - CHANGELOG.md
decisions:
  - The id-only path reads the attachment list through the module's own records(target.folder, "", target.id, 1); name and name+id paths make no listing call.
metrics:
  completed: 2026-10-07
actuals:
  tasks: 2
  commits: 2
plan_head_before: f7967f4
plan_head_after: 0dc5a9d
---

# Quick 261007-o5d: An id-only attachment save is named after the attachment (#296)

`save_mail_attachment(message_id, dest_dir, attachment_id=X)` reads the message's
attachment list first, matches the row by id, checks the listed size against the cap,
and names the file after the listed name. `original_name` reports that name.

## Commits

| Task | Commit | Subject |
|------|--------|---------|
| 1 | 6848af2 | fix(mail): name an id-only attachment save after the attachment (#296) |
| 2 | 0dc5a9d | docs(changelog): an id-only attachment save is named after the attachment (#296) |

## Changes

- `mail_attachments._listed_attachment(target, wanted_id)`: calls
  `records(target.folder, "", target.id, 1)` and returns the row whose `id` matches.
  An unknown id raises `ValueError` that lists the message's non-empty ids (or `none`)
  and states that nothing was saved.
- `mail_attachments.save_attachment`: on the id-only path, the order is listing,
  `mail_files.check_size(row["size"], row["name"])`, then `mail_files.target_path`,
  then the save script. The save argv is unchanged (the name slot stays `""`).
  `original_name` is the file name used.
- `tests/test_mail_extras.py`: `test_save_by_attachment_id_leaves_the_name_slot_empty`
  is replaced. New tests cover id-only naming, unknown id, overwrite refusal, size cap,
  hostile listed name, and the unchanged name paths (parametrized over `""` / `"1.12"`).
- `CHANGELOG.md`: `[Unreleased]` / `### Fixed` bullet for #296.

## TDD Gate Compliance

RED (before the fix), `uv run pytest -q tests/test_mail_extras.py`: 5 failed, 26 passed.
Failing tests:

- `test_save_by_attachment_id_alone_is_named_after_the_attachment`
- `test_save_by_an_unknown_attachment_id_lists_the_real_ids`
- `test_save_by_attachment_id_refuses_an_existing_file`
- `test_save_by_attachment_id_refuses_an_oversized_attachment`
- `test_save_by_attachment_id_derives_a_hostile_listed_name`

`test_save_by_name_makes_one_apple_event[""]` and `["1.12"]` passed at RED, as planned.
GREEN: all pass. The RED tests and the fix are in one commit, as the plan specifies.

## Verification

- `uv run pytest -q`: 1924 passed, 97 deselected.
- `MACOS_APPS_ALLOW_SEND=mail uv run pytest -q`: 1920 passed, 4 skipped, 97 deselected.
- `uv run ruff check .`: no issues.
- `uv run ruff format --check .`: 109 files already formatted.
- Unit count: 1924 (baseline 1918).
- `server.py`, `mail.py`, `mail_files.py`: unchanged against `origin/develop`.
- No `.planning/` file in either commit. Nothing pushed.
- Device check: open, for the orchestrator.

## Deviations from Plan

**1. [Rule 3 - Blocking] Branch file-list check uses the merge base**
- **Issue:** `origin/develop` gained `c319051` (`.planning/` files only) after the
  branch was cut. `git diff --name-only origin/develop..HEAD` therefore lists those
  `.planning/` files, although no commit on this branch touches them.
- **Fix:** the check ran as `git diff --name-only origin/develop...HEAD`. It lists only
  `CHANGELOG.md`, `macos_apps_mcp/adapters/mail_attachments.py` and
  `tests/test_mail_extras.py`. The branch was not rebased.

## Follow-up candidates (out of scope)

- `clean_summary` caps a listed name at 200 characters and adds a `[truncated N chars]`
  marker. An id-only save of an attachment with a longer name gets a file name without
  its real extension. The name path has the same ceiling.

## Self-Check: PASSED

- Files modified exist; commits 6848af2 and 0dc5a9d are ancestors of HEAD.

## Orchestrator close-out (2026-10-07)

- Review (2 lenses, no blocking): fixed the vacuous unknown-id assertion; an empty listing now raises a "no message in this folder" NativeError; the listing host cap is 120 s (`_LIST_TIMEOUT`, equal to the script backstop); stale comments updated; four older fakes accept `**kw`.
- Device (watchdog running): id-only save from the Gmail INBOX label wrote `5711648514.pdf` (79,229 bytes, valid PDF); unknown id and wrong folder gave the two errors, nothing saved; probe file removed.
- PR #304. Verification: 1926 passed; 1922 passed / 4 skipped with send; ruff clean.
