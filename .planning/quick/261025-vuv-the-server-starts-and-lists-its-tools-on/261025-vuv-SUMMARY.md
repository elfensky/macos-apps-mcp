---
phase: quick-261025-vuv
plan: 01
subsystem: platform / packaging / ci
tags: [linux, glama, darwin-markers, unsupported-platform, ci]
requires: []
provides:
  - "PyObjC and osxphotos install only on macOS"
  - "the server imports, starts and lists its tools off macOS"
  - "UnsupportedPlatform at every native door"
  - "linux-tools-list CI job"
affects: [pyproject.toml, uv.lock, runtime, eventkit, doctor, cli, server, ci]
key-files:
  created: [tests/test_off_macos.py, tests/test_tools_list_anywhere.py]
  modified:
    - pyproject.toml
    - uv.lock
    - tests/test_packaging.py
    - tests/test_runtime.py
    - macos_apps_mcp/errors.py
    - macos_apps_mcp/runtime.py
    - macos_apps_mcp/eventkit.py
    - macos_apps_mcp/doctor.py
    - macos_apps_mcp/cli.py
    - macos_apps_mcp/server.py
    - macos_apps_mcp/adapters/calendar.py
    - macos_apps_mcp/adapters/reminders.py
    - .github/workflows/ci.yml
    - CHANGELOG.md
    - AGENTS.md
decisions:
  - "Guard is sys.platform == 'darwin', never try/except: a broken PyObjC on a Mac still fails at import."
  - "The unit test skips the EventKit bootstrap on darwin (a TCC prompt can block); off macOS it is the unmodified start."
metrics:
  tasks: 3
  commits: 6
  duration: "n/a (orchestrator-run)"
status: complete
commits: 6
plan_head_before: 3bf281b143e95295c39d107444c5c811ca087317
plan_head_after: ee2163c9bbc0448211b28758ab924f8446e60e86
actuals:
  tasks: 3
  commits: 5
---

# Phase quick-261025-vuv Plan 01: The server starts and lists its tools on Linux Summary

PyObjC/osxphotos are darwin-only dependencies, every macOS import is platform-guarded, every native door refuses with `UnsupportedPlatform`, and a Linux CI job plus a Docker proof show the server lists its 68 tools over stdio in python:3.12-slim.

## Commits

| Task | Hash | Message |
| ---- | ---- | ------- |
| 1 | dd8644a | build(deps): PyObjC and osxphotos are macOS-only dependencies |
| 1 (review) | 20b7265 | test(packaging): every macOS-only dependency carries the darwin marker |
| 2 | ce04e71 | feat(runtime): the server imports and refuses cleanly off macOS |
| 2 (review) | b434b56 | fix(cli): every role refuses off macOS with the platform reason |
| 3 | 426205c | test(ci): a Linux job proves the server starts and lists its tools |

## Review fixes

- Task 1: the marker test now evaluates all five markers for both darwin and linux.
- Task 2: `cli.main` refuses all ten roles off macOS with exit 1; the platform test pins "Use it on a Mac." and "Do not retry."
- Not taken: un-guarding audit, and a worker fast path.

## Task 3

- `tests/test_tools_list_anywhere.py`: a REAL start. It launches `python -m macos_apps_mcp` as a stdio subprocess (whole parent environment passed, so the READ_ONLY / ALLOW_SEND gates match), runs MCP initialize + tools/list, and asserts the names equal the registered records of `registry.TOOLS`. On darwin the child is `python -c` with `server.bootstrap` stubbed, so a unit test never triggers a TCC prompt; off macOS bootstrap is already a no-op and the start is the plain `-m` entry. Passes default, `MACOS_APPS_READ_ONLY=1` and `MACOS_APPS_ALLOW_SEND=mail`.
- `ci.yml`: new `linux-tools-list` job on ubuntu-latest (checkout@v7, setup-uv@v10.3.2, `uv sync --locked`, import smoke, the test). `check` is unchanged (verified equal to 3bf281b). Header rewritten.
- CHANGELOG `[Unreleased]` Added bullet; AGENTS.md "Architecture" bullet naming `require_macos` and `linux-tools-list`.

## Device check (orchestrator, darwin)

In-process `doctor` read EventKit `full_access`, and a real `events today` read returned 7 items. The Mac behaves as before.

## Docker evidence (python:3.12-slim, linux/aarch64)

Route (a), built wheel with pip:

```
aarch64
pyobjc/osxphotos packages: 0
import ok
tools: 68
equal to registry: True
calendars error: macos-apps-mcp runs only on macOS: this server is running on linux, where Mail, Calendar, Reminders and the other Mac apps do not exist. Use it on a Mac. Do not retry.
```

Route (b), source checkout (git archive of HEAD, copied to /app) with uv:

```
pyobjc/osxphotos packages: 0
import ok
tools: 68
equal to registry: True
calendars error: macos-apps-mcp runs only on macOS: this server is running on linux, ...
```

The same three results came from starting `/app/.venv/bin/macos-apps-mcp` directly.

## Glama build spec

Glama builds from the GitHub default branch (`develop`), so the fix is live for Glama when this PR merges. Run from the repo root in python:3.12-slim.

Build / install steps:

```
pip install uv
uv sync --locked --no-dev
```

Start command (stdio):

```
uv run --no-sync macos-apps-mcp
```

(equivalent: `.venv/bin/macos-apps-mcp`). A PyPI-based spec (`pip install macos-apps-mcp`, `uvx macos-apps-mcp`) works only after the next release publishes to PyPI.

## Verification

- `uv run pytest -q`: 2638 passed, 1 failed. The failure is the known flake `tests/test_doctor.py::test_report_stays_under_token_budget[daemon-not-built-worst-escape]` (#464, report only).
- `MACOS_APPS_ALLOW_SEND=mail uv run pytest -q`: 2633 passed, 6 skipped, 0 failed.
- `MACOS_APPS_READ_ONLY=1 uv run pytest -q`: 2624 passed, 15 skipped, 0 failed.
- `uv run ruff check .` clean; `uv run ruff format --check .` 132 files already formatted.
- CI-structure check, CHANGELOG and AGENTS.md greps all pass.

## Deviations from Plan

- [Rule 2 - Safety] The plan said the test opens the server "in-process"; the owner asked for a real subprocess start. Implemented as a stdio subprocess, with the darwin bootstrap stub described above so the unit suite never reaches EventKit. The commit message is `test(ci): ...` as instructed by the orchestrator, not the plan's `ci:` wording.

## Deferred

- Review of task 3 (ee2163c): the stdio start times out after 60 s; the docstring says the darwin child skips only the EventKit bootstrap; AGENTS.md says tools that need the Mac refuse and the Linux job covers the server's import path. Not taken: a narrower child environment.

- #464 flake (test_report_stays_under_token_budget).
- `.github/workflows/publish.yml` header comment still says PyObjC is macOS-only so no Linux (planner surprise 9).

## Known Stubs

None.

## Self-Check: PASSED

All five commits are ancestors of HEAD; tests/test_tools_list_anywhere.py, ci.yml job, CHANGELOG and AGENTS.md entries exist.
