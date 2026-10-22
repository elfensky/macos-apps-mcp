---
phase: 05-operator-control-plane-adapter-toggles-and-the-localhost-das
plan: 06
subsystem: release
tags: [release, v0.15.0, notarization, pypi, daemon-install]
requires: [05-05, 05-08]
provides: [v0.15.0 tag, GitHub release, PyPI 0.15.0, installed notarized daemon]
affects: [/Applications/macos-apps-mcp.app, app-backup]
requirements: [PLAT-01, PLAT-02]
key-files:
  created: []
  modified: [CHANGELOG.md]
decisions:
  - "D-18 cut approved by the owner as cut-and-pypi"
status: complete
commits: 1
plan_head_before: f84897d
plan_head_after: 7b26e22c6fbeabf5d510cbe2dba70e1988cb1e6c
---

# Phase 5 Plan 06: v0.15.0 — Photos and the dashboard Summary

v0.15.0 is tagged on the `main` merge commit, released with a stapled zip, published to production PyPI, and installed as the notarized daemon. The probe proves the build.

## Task 1: release notes on develop

- PR #424 rebase-merged. Commit `f84897d` is on origin/develop.
- CHANGELOG has `## [0.15.0] - 2026-10-22 — Photos and the dashboard` below an empty `## [Unreleased]`.
- Local verify: test_packaging 16 passed; pytest 2460 passed; `MACOS_APPS_ALLOW_SEND=mail` 2454 passed, 6 skipped; `MACOS_APPS_READ_ONLY=1` 2445 passed, 15 skipped; ruff check clean; ruff format 128 files formatted.
- Lane removed.

## Task 2: owner approval

The owner answered "cut-and-pypi". The production PyPI dispatch was approved.

## Task 3: cut, build, release, install

Pre-probe (running daemon before the swap; a develop build installed for the 04.1 UAT, not the v0.14.3 tag build):

```
version: 0.14.3
build: 106ffb6 2026-10-20T11:13:52Z
build token resolves to: 106ffb64e27bb293f01bbeaa38a91b98f3e7d5be
PROBE PASSED
```

Cut:
- Release PR https://github.com/elfensky/macos-apps-mcp/pull/425 (develop to main). Both required checks passed. Merged with `--merge`, no branch deleted.
- origin/main `7b26e22c6fbeabf5d510cbe2dba70e1988cb1e6c` has two parents (`85a3baf` and `f84897d`).
- Tag `v0.15.0` (annotated) points at `7b26e22`, which equals origin/main.

Build (detached worktree at the tag, since removed):
- Log shows `universal2 gate ok`, `smokes ok: arm64`, `smokes ok: x86_64`, `entitlements ok: x86_64 has the exception, arm64 is strict`, `signed smoke ok: arm64`, `signed smoke ok: x86_64`.
- Notarization status: Accepted. `xcrun stapler validate`: the validate action worked.
- `spctl -a -vv -t install`:

```
dist/macos-apps-mcp.app: accepted
source=Notarized Developer ID
origin=Developer ID Application: Andrei M. Lavrenov (VUMUR696L9)
```

- Zip made after stapling: `macos-apps-mcp-0.15.0.zip`, 90.7M.

Publish:
- Release: https://github.com/elfensky/macos-apps-mcp/releases/tag/v0.15.0. Asset `macos-apps-mcp-0.15.0.zip` attached. Notes are the CHANGELOG 0.15.0 section; the body contains `photo_info`, `PLAT-01` and `PLAT-02` (9 matching lines).
- PyPI: `publish.yml` dispatched with `target=pypi` at ref v0.15.0 (run 39839964724, workflow_dispatch). `gh run watch --exit-status` exited 0. `curl -sf https://pypi.org/pypi/macos-apps-mcp/0.15.0/json` exited 0.
- No GitHub milestone was closed.

Install:
- Old bundle moved to `~/.local/state/macos-apps-mcp/app-backup/macos-apps-mcp-0.14.3-106ffb6.app`. The older backups (0.14.2, 0.14.3-85a3baf, 0.14.3-f877989) are untouched.
- `ditto` into the empty slot. `codesign --verify --strict /Applications/macos-apps-mcp.app` exit 0. Kickstart exit 0. Socket present within 30 s.
- Post-probe (`.daemon_probe.py 0.15.0 <v0.15.0 sha>`, `$?` = 0):

```
version: 0.15.0
build: 7b26e22 2026-10-22T19:19:28Z
build token resolves to: 7b26e22c6fbeabf5d510cbe2dba70e1988cb1e6c
PROBE PASSED
```

- `lsof -nP -iTCP:47632 -sTCP:LISTEN`:

```
macos-app 84285 andrei    4u  IPv4 0x553be518f5c8f530      0t0  TCP 127.0.0.1:47632 (LISTEN)
```

- `git worktree list` no longer lists `.worktrees/build-v0.15.0`.
- Vault journal bullet landed (vault MR 1745).

## Deviations from Plan

None in the steps. One note: the running daemon before the swap was build `106ffb6`, not the v0.14.3 tag build. The backup name uses that token, as the orchestrator directed.

## Not checked

- `doctor().deployment.dashboard` equal to `http://127.0.0.1:47632` was not read here. The probe does not print it, and this session's MCP client dropped with the daemon swap. The `lsof` line proves the listener. The reconnect and browser sitting belong to 05-07.
- The dashboard page key was never printed or read.

## Owner follow-up

Reconnect every MCP client with `/mcp`. Each client dropped once at the kickstart.

## Self-Check: PASSED

Tag, release asset, PyPI 0.15.0, probe and `lsof` were each verified by command output above.
