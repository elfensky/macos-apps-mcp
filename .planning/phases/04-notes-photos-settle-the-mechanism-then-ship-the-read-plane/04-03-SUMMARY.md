---
phase: 04-notes-photos-settle-the-mechanism-then-ship-the-read-plane
plan: 03
subsystem: notes
tags: [notes, fts5, sqlite, search, envelope, decision-record]
requires: []
provides:
  - "NotesAdapter.read(query) -> {results, truncated?, plane?, coverage?}"
  - "in-memory FTS5 body search for notes() (locked notes excluded, nothing on disk)"
  - "docs/notes-semantic-search.md (NOTE-01 decision: not adopted)"
affects: [04-04 (edits server.py, README.md, CHANGELOG.md, tests/test_server.py after this PR)]
tech-stack:
  added: []
  patterns: ["per-call :memory: FTS5 index inside the existing read_via_sqlite read", "(pointers, plane, coverage) tuple from the search closure, envelope built after"]
key-files:
  created: [docs/notes-semantic-search.md]
  modified: [macos_apps_mcp/adapters/notes.py, macos_apps_mcp/server.py, tests/test_notes.py, tests/test_server.py, README.md, CHANGELOG.md]
key-decisions:
  - "NOTE-01 closes as not adopted (owner, 2026-09-28, spike 004); NOTE-02 not applicable"
  - "Body pass runs inside the sqlite closure and catches SchemaDrift/sqlite3.Error itself, so a body failure keeps the title/snippet plane instead of falling back to AppleScript"
  - "Query words of 4+ characters drive the body pass; all words when none is that long (fixes the 'tax' gap, which came from the spike's own filter, not FTS5)"
requirements-completed: [NOTE-01, NOTE-02]
duration: "about 45 min"
completed: 2026-10-18
status: complete
commits: 5
plan_head_before: cb36415af39880bb2de1e5c4b898ded4abaa1fbf
plan_head_after: 4c90f9756db1d1759b106252ea43a75e032175f0
actuals:
  tokens: 28000
  tasks: 3
  commits: 5
---

# Phase 4 Plan 03: Notes body search and the NOTE-01 decision Summary

notes() searches bodies; semantic search not adopted — PR #365, closes #93

## What shipped

- `docs/notes-semantic-search.md`, the first commit of the PR: decision (not adopted, owner, 2026-09-28), spike 004 numbers, and the five items ROADMAP criterion 4 names (model, chunking, index build and refresh, size cap, optional-extra boundary).
- `notes()` returns the bounded-read envelope. It also finds a word that sits only in a note body, through an FTS5 table built per call in a `:memory:` connection (porter, diacritics removed, `bm25(f), id desc`).
- Title and snippet hits keep today's order and come first. Body-only hits follow, without duplicates, up to `MAX_NOTES`.
- Locked notes are dropped before decode. Only two `sqlite3.connect` targets exist per call: the read-only store URI and `:memory:`.
- Degraded paths: AppleScript fallback gives `plane: applescript` and a "titles only" coverage. A body-pass failure keeps the sqlite results and gives "body search unavailable" coverage.
- README `notes` row and CHANGELOG `[Unreleased]` `### Changed` entry. `test_no_semantic_extra_and_no_ml_dependency` pins NOTE-02.

## Commits (on develop, rebase-merged)

| Hash | Subject |
|------|---------|
| d7c5195 | docs(notes): the NOTE-01 decision — semantic search not adopted (#93) |
| 3745023 | test(notes): notes() finds a word only in a note body (#93) |
| e750fa3 | feat(notes): notes() searches note bodies (FTS5, in memory) and returns the read envelope (#93) |
| 6d2adf8 | test(notes): body search merge, locked, boundary and degraded paths (#93) |
| 4c90f97 | docs(notes): the NOTE-02 guard and the notes() envelope in README and CHANGELOG (#93) |

PR: elfensky/macos-apps-mcp#365, merged (rebase). Required `check` job: pass (1m25s). Issue #93: CLOSED. Lane `.worktrees/notes-fts-body` removed, branch deleted.

## Verification

- Local, in the lane before the push: `uv run pytest` 2049 passed; `MACOS_APPS_READ_ONLY=1 uv run pytest` 2037 passed, 12 skipped; `MACOS_APPS_ALLOW_SEND=mail uv run pytest` 2045 passed, 4 skipped; `ruff check` clean; `ruff format --check` clean.
- Task 2 selection (`-k "body or merge or locked or short or cap or tie or coverage or fallback or disk"`): 29 passed. `-k locked` 1, `-k disk` 1, `-k cap` 6 (24, 25, 26 among them).
- Commit order: the decision commit is first in `git log --reverse origin/develop..HEAD` and touches only the doc.
- `git show origin/develop:docs/notes-semantic-search.md | grep -c …` printed 8 (at least 6 needed).
- Code review (`code-review` skill, run inline because this session had no sub-agent tool): no open finding. Standards: qualified `sqlite3.connect`, typed errors, `read_result`, thin dispatch, `shortcut:` comment, ruff clean. Spec: every plan truth maps to a test.
- Mutation checks (dropping the locked filter, flipping the tie order, removing the 4-character rule, narrowing the `sqlite3.Error` catch) each fail one test.
- No device run (plan says none needed). The installed daemon picks this up at the 04-06 rebuild.

## Deviations from Plan

**1. [Process] Task 2 had no separate GREEN commit.** The Task 1 GREEN code already held the body-pass `try/except (SchemaDrift, sqlite3.Error)` and the titles-only fallback coverage, so the Task 2 tests passed on arrival. They ship as one `test(...)` commit, with the reason in its message and the mutation checks above as proof the tests are not vacuous. The plan's `feat(notes): body search keeps the title plane…` commit does not exist.

**2. [Rule 1 - lint] Two E501 line-length slips in new test and adapter comments** were fixed before the push (one amended into the Task 2 test commit, one in the final docs commit).

**3. [Test shape] The tracer test expects the pointer dict with `folder`** (`iCloud / Groceries`); the plan text listed only id, summary and deeplink.

**4. [Test shape] The fallback test drives a drifted store** (as the existing fallback tests do) rather than an unreadable path; an absent path raises a plain `NativeError`, which does not fall back.

**Total deviations:** 4 (1 process, 1 lint, 2 test shape). **Impact:** none on behavior or scope.

## Known Stubs

None.

## Threat Flags

None. T-04-08 and T-04-09 (high, mitigate) are covered by `test_body_search_touches_no_disk_but_the_store` and `test_locked_note_body_is_never_indexed`; T-04-10 by `test_body_query_is_never_fts_syntax`.

## Notes for later plans

- 04-04 edits `server.py`, `README.md`, `CHANGELOG.md` and `tests/test_server.py` after this PR: develop now holds the `### Changed` section and the new `notes` README row.
- `_EmptySource` in `tests/test_server.py` now has a `read`; `test_read_tool_empty_result_is_not_an_error` points its list case at `srv.contacts`.

## Self-Check: PASSED

PR merged, issue closed, lane removed, decision doc on origin/develop, vault journal bullet landed.
