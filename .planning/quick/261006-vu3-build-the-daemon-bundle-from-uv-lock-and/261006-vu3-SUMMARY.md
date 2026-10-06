---
phase: quick-261006-vu3
plan: 01
status: complete
requirements: [ISSUE-286]
commits: 3
plan_head_before: 85af3c7
plan_head_after: c263131b10dbdb66b5a052d6825d9b5c35787c89
actuals:
  tasks: 3
  commits: 3
---

# Quick 261006-vu3: Build the daemon bundle from uv.lock (#286) Summary

The `.app` build now installs the hashed `uv.lock` pins, caps mcp<2 and fastmcp<4, and
fails the build unless one streamed tool call returns through the bundled shim transport.

Code lane: `/Users/andrei/Developer/macos-apps-mcp/.worktrees/fix-286`, branch
`fix/286-bundle-from-lockfile`. Nothing pushed.

## Commits

| Task | SHA | Subject |
| ---- | --- | ------- |
| 1 | aa38ffa | build: smoke-test a streamed call on the bundle's interpreter (#286) |
| 2 | b93570c | fix(build): install the daemon bundle from uv.lock; cap mcp<2, fastmcp<4 (#286) |
| 3 | c263131 | docs: changelog and build notes for the lockfile bundle (#286) |

## Tests

Before: 1830 passed, 96 deselected. After each task and at the end: 1830 passed, 96
deselected. `ruff check`, `ruff format --check` and `uv lock --check` green throughout.

## RED / GREEN (Task 1)

RED: `scripts/smoke_stream.py` on the old mcp-2.3.0 bundle exited 1 (`/tmp/mam-286-red.log`):

```
  File ".../site-packages/macos_apps_mcp/daemon.py", line 128, in _handle_sse_response
    await original(
          ~~~~~~~~^
TypeError: StreamableHTTPTransport._handle_sse_response() takes 3 positional arguments but 4 were given
```

GREEN: `uv run python scripts/smoke_stream.py` (lockfile mcp 1.29.0) printed `stream smoke ok`, exit 0.

## Real build (Task 2)

`bash scripts/build_app.sh --out /tmp/mam-286-build` exited 0. Log tail:

```
 + macos-apps-mcp==0.13.1 (from file:///Users/andrei/Developer/macos-apps-mcp/.worktrees/fix-286)
[10/06/26 23:03:42] DEBUG    Sending INFO to client: working     context.py:1446
                    INFO     Received INFO from server: {'msg': 'working', 'extra': None}
stream smoke ok
built: /tmp/mam-286-build/macos-apps-mcp.app
```

Bundle site-packages held `mcp-1.29.0.dist-info` and `fastmcp-3.4.7.dist-info`, equal to the
`uv.lock` versions. CPython 3.14.5; every locked wheel was available. `/tmp/mam-286-build`
removed afterwards.

## Final checks

- `git diff --numstat origin/develop -- uv.lock` is `2 2 uv.lock`; only the two `specifier`
  lines differ.
- No `.planning/` change in the code lane. Three subjects end `(#286)`; three
  `Co-Authored-By: Claude Opus 5.5` trailers. Branch not on origin.

## Deviations from Plan

None. Plan executed as written. Note: the commit-attribution trailer follows the plan and
lane instruction (`Claude Opus 5.5`), not the harness default.

Small choices inside the plan's allowance: the smoke tool uses `await asyncio.sleep(1)`
instead of the validated `time.sleep(1)`; the bare `assert` became `sys.exit(...)`.

## Known Stubs

None.

## Self-Check: PASSED

Commits aa38ffa, b93570c and c263131 exist on the branch; `scripts/smoke_stream.py` exists.
