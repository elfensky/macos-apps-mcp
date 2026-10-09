---
phase: quick-261009-l1d
plan: 01
subsystem: docs
tags: [readme, uvx, install, changelog]
status: complete
requirements: [ISSUE-113]
key-files:
  modified: [README.md, DESIGN.md, CHANGELOG.md]
actuals:
  tokens: 2000
  tasks: 2
  commits: 2
plan_head_before: 241db7f9ba38576d448c7f5fd3b230517ac4da8d
plan_head_after: 31d337ef2dc862f435c7391771b8ab4d15596049
commits: 2
completed: 2026-10-09
---

# Quick 261009-l1d: README recommends uvx (#113)

The README `## Install` now leads with `uvx macos-apps-mcp` (client JSON plus the `claude mcp add` line); clone + `uv sync` stays as the development path.

## Commits (branch docs/113-readme-uvx, not pushed)

- 8c89b58 docs(readme): recommend uvx macos-apps-mcp as the install (#113) — README.md, DESIGN.md
- 31d337e docs(changelog): the README recommends uvx as the install (#113) — CHANGELOG.md

## Checks

| Check | Exit |
|-------|------|
| Task 1 automated verify (JSON blocks, strings, DESIGN amendment, DAEMON.md unchanged, file set) | 0 |
| `uv run pytest -q` | 0 (1938 passed, 97 deselected) |
| `MACOS_APPS_ALLOW_SEND=mail uv run pytest -q` | 0 (1934 passed, 4 skipped, 97 deselected) |
| `uv run ruff check .` | 0 |
| `uv run ruff format --check .` | 0 |
| CHANGELOG `[Unreleased]` / `### Changed` cites (#113) | 0 |
| Two commits, subjects end `(#113)`, both carry the trailer, files = CHANGELOG.md DESIGN.md README.md | pass |

## Deviations from Plan

None - plan executed as written. The plan's own verification text says the diff lists only CHANGELOG.md and README.md; the task checks and Task 1 step 8 add DESIGN.md, which is the file set committed.

## Follow-up candidates

- docs/DAEMON.md mode table and step 3 do not name the uvx form (`uvx macos-apps-mcp install-agent` dispatches the same role). Not changed here.

## Known Stubs

None.

## Self-Check: PASSED
