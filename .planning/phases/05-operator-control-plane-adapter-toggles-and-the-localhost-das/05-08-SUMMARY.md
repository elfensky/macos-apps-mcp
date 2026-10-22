---
phase: 05-operator-control-plane-adapter-toggles-and-the-localhost-das
plan: 08
subsystem: packaging
tags: [packaging, release, dependency, starlette, uv-lock]
requires: []
provides:
  - "starlette>=0.48 declared as a direct dependency"
  - "version 0.15.0 in pyproject.toml, packaging/Info.plist and the uv.lock root line"
affects: [05-02, 05-06]
tech-stack:
  added: []
  patterns: ["offline lock refresh (uv lock --offline)"]
key-files:
  created: []
  modified: [pyproject.toml, uv.lock, packaging/Info.plist]
decisions:
  - "D-09: the one PR that edits pyproject.toml carries the 0.15.0 bump and the starlette declaration"
requirements: [PLAT-02]
status: complete
commits: 1
plan_head_before: d053ec151ed176c03cc27c13a27965370b3a5483
plan_head_after: 0d70f8f (pre-merge lane commit; rebase-merged onto develop as ce8bb3b)
actuals:
  tokens: 1500
  tasks: 2
  commits: 1
---

# Phase 5 Plan 08: starlette declared and 0.15.0 on develop — PR #406

Declared `starlette>=0.48` and bumped to 0.15.0 in the three version places; PR #406 rebase-merged into develop as `ce8bb3b`. The 05-02 merge gate is open.

## What changed

- `pyproject.toml`: `"starlette>=0.48",  # imported directly (dashboard/)` after the `httpx` line; `version = "0.15.0"`.
- `packaging/Info.plist`: `CFBundleShortVersionString` 0.15.0.
- `uv.lock`: exactly four lines in three hunks (`uv lock --offline`):
  - `-version = "0.14.3"` / `+version = "0.15.0"` (root package)
  - `+    { name = "starlette" },` (root `dependencies`)
  - `+    { name = "starlette", specifier = ">=0.48" },` (`requires-dist`)
  - `revision = 5` and the starlette 1.6.0 package entry are unchanged.

## Landing

- PR: #406 (`Part of #126`, no closing keyword), merge SHA on develop: `ce8bb3b`.
- Required `check` green (1m4s); `bumped`, CodeQL also green.
- Proof on origin/develop: the `"starlette>=0.48",` and `version = "0.15.0"` grep prints 2; the Info.plist grep prints 1.
- Lane `.worktrees/packaging-0.15.0` and branch `chore/packaging-0.15.0` removed; main checkout fast-forwarded to `ce8bb3b`.

## Local check summaries (before push)

- `uv run pytest -q`: 2229 passed, 102 deselected
- `MACOS_APPS_READ_ONLY=1 uv run pytest -q`: 2214 passed, 15 skipped, 102 deselected
- `MACOS_APPS_ALLOW_SEND=mail uv run pytest -q`: 2225 passed, 4 skipped, 102 deselected
- `uv run ruff check .`: All checks passed
- `uv run ruff format --check .`: 110 files already formatted
- `uv run pytest -q tests/test_packaging.py`: 16 passed

## Package legitimacy evidence (T-05-SC)

starlette 1.6.0 was already locked (and installed) as a dependency of `mcp` and `fastmcp`. The lock diff adds no package. Nothing was downloaded (`uv lock --offline`, `uv sync --locked --offline`, `uv lock --check --offline` all pass). Source repository: github.com/Kludex/starlette. The [SUS] verdict came from release recency only. Owner override recorded in the plan (no human check).

## Inline self-review (origin/develop...HEAD)

Diff is three files, +6/-3. It matches the plan spec: the dependency line sits with the "imported directly" group, the version appears in all three places, the lock diff is the expected four lines, and no other file changed. No findings. The orchestrator runs the independent review.

## Deviations from Plan

None - plan executed exactly as written. Two notes:
- The `vault-journal` step was skipped on orchestrator instruction (parallel executors); the orchestrator records the landing from the PR number and merge SHA above.
- The tracer gate: `<verify>` ran end to end and passed before the PR was opened.

## Known Stubs

None.

## Threat Flags

None.

## Self-Check: PASSED

- `ce8bb3b` is on origin/develop; PR #406 state MERGED; lane directory absent.
