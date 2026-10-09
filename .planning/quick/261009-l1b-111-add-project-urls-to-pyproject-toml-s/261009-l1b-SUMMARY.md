---
phase: quick-261009-l1b
plan: 01
subsystem: packaging
tags: [pyproject, pypi, project-urls]
requires: []
provides: ["[project.urls] table in pyproject.toml", "CHANGELOG Unreleased/Added entry for #111"]
affects: [pyproject.toml, CHANGELOG.md]
key-files:
  modified: [pyproject.toml, CHANGELOG.md]
decisions: []
status: complete
actuals:
  tokens: 1000
  tasks: 2
  commits: 2
plan_head_before: 241db7f9ba38576d448c7f5fd3b230517ac4da8d
plan_head_after: ce81ff07965a4aab9bd0c4d81f6071d9918cad2b
commits: 2
completed: 2026-10-09
---

# Phase quick-261009-l1b Plan 01: Project URLs for PyPI Summary

`pyproject.toml` now has a `[project.urls]` table (Homepage, Repository, Issues, Changelog), and the built wheel carries the four matching `Project-URL:` lines. Closes #111 once the next PyPI upload happens (Andrei dispatches it; not done here).

## Commits (branch chore/111-project-urls, not pushed)

- 7577172 chore(packaging): add [project.urls] so the PyPI page links to the repo (#111)
- ce81ff0 docs(changelog): the PyPI page links back to the repo (#111)

## Wheel METADATA (built via `uv build` into scratch `dist-111`, exit 0)

```
Project-URL: Homepage, https://github.com/elfensky/macos-apps-mcp
Project-URL: Repository, https://github.com/elfensky/macos-apps-mcp
Project-URL: Issues, https://github.com/elfensky/macos-apps-mcp/issues
Project-URL: Changelog, https://github.com/elfensky/macos-apps-mcp/blob/main/CHANGELOG.md
```

## Checks

| Check | Exit | Last line |
|-------|------|-----------|
| `uv run pytest -q` | 0 | 1938 passed, 97 deselected in 26.69s |
| `MACOS_APPS_ALLOW_SEND=mail uv run pytest -q` | 0 | 1934 passed, 4 skipped, 97 deselected in 25.87s |
| `uv run ruff check .` | 0 | All checks passed! |
| `uv run ruff format --check .` | 0 | 109 files already formatted |
| `rtk proxy uv run pytest --collect-only -q` | 0 | 1938/2035 tests collected (97 deselected) |

`uv.lock` unchanged (`git diff --quiet uv.lock` exit 0 after each task). No `dist/` in the lane. Branch has no upstream. Only `pyproject.toml` and `CHANGELOG.md` differ from 241db7f.

## Deviations from Plan

None - plan executed exactly as written. The agent-branch-namespace allow-list in the generic commit protocol was not applied: the lane is a plan-owned worktree on `chore/111-project-urls`, as the plan's lanes block directs.

## Known Stubs

None.

## Self-Check: PASSED

Both commits exist on the branch; both files changed as planned.
