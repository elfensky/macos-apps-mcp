---
phase: 01-gate-land-the-spiked-architecture-cuts
plan: 10
subsystem: infra
tags: [daemon, codesign, launchd, dev-build, gate-check]

# Dependency graph
requires: ["01-09", "01-07"]
provides:
  - "Installed daemon runs a signed dev build of develop bd6fe53 (cards 1, 3, 4, 5, 7, 9); its gates and the widened mail_index fingerprint are proven live"
affects: [01-11, 01-14]

actuals:
  tokens: 30000
  tasks: 2
  commits: 0

tech-stack:
  added: []
  patterns:
    - "Dev-build swap: detached worktree at origin/develop, build_app.sh --sign (no notarize), ditto the installed app to a scratch backup, rm + cp -R, launchctl kickstart -k, probe over the unix socket"

key-files:
  created: []
  modified: []

key-decisions:
  - "Task 2 ran in the orchestrator session, not in a gsd-executor. The owner chose this route ('1') after two dispatch routes were blocked: a session hook blocked the GSD tool that renews the isolation sentinel, and a worktree-isolated executor cannot run git or write files in the main repository."
  - "The installed app was copied to a scratch backup before removal. The backup check is a byte comparison (diff -rq), not codesign --verify --strict: a running daemon writes __pycache__ files into its own bundle, so an installed app never passes a strict seal check."

patterns-established:
  - "Back up /Applications/macos-apps-mcp.app with ditto before every swap; roll back by copying the backup into place and kickstarting."

requirements-completed: []

coverage:
  - id: D1
    description: "Signed dev build from origin/develop in a detached worktree; build stamp equals the built commit without -dirty"
    requirement: "GATE-13"
    verification:
      - kind: other
        ref: "build_stamp 'bd6fe53 2026-09-25T19:39:50Z'; codesign --verify --strict on dist/ and on the installed copy before first launch"
        status: pass
    human_judgment: false
  - id: D2
    description: "Daemon reinstalled, kickstarted, and answering with version 0.11.0 and build bd6fe53"
    requirement: "GATE-13"
    verification:
      - kind: other
        ref: "uv run python .worktrees/.daemon_probe.py"
        status: pass
    human_judgment: true
    rationale: "The plan's human-check: the owner reconnects one Claude Code session and its doctor() shows the same build token."
  - id: D3
    description: "Outbound gated correctly: outbound lists mail, and send_mail answers a dry_run preview only"
    requirement: "GATE-13"
    verification:
      - kind: other
        ref: "scratch outbound_dry_run_probe.py: send_mail {dry_run: true} returned dry_run true + would_send"
        status: pass
    human_judgment: false
  - id: D4
    description: "mail_index surface ok on the real Envelope Index (card 3's widened HEADER_FINGERPRINT holds)"
    requirement: "GATE-08"
    verification:
      - kind: other
        ref: ".daemon_probe.py mail_index surface status"
        status: pass
    human_judgment: false

duration: 15min
completed: 2026-09-25
status: complete
---

# Phase 1 Plan 10: Post-card-5 Dev-build Daemon Swap Summary

**The daemon runs develop's build bd6fe53: version 0.11.0, outbound gated to a dry-run preview, mail_index ok.**

## Owner go (Task 1)

The owner answered "swap-now" on 2026-09-25 at about 17:30 CEST. After two blocked dispatch routes,
the owner chose on 2026-09-25 to run Task 2 in the orchestrator session ("1").

## Build

- BUILT = `bd6fe5357c3ff02b4db2268f8289c82d48cfab8d` (origin/develop; cards 1, 3, 4, 5, 7, 9 landed)
- Worktree: `git worktree add --detach .worktrees/devbuild-card-5 origin/develop`, clean, `git describe --always --dirty` = `bd6fe53`
- `scripts/build_app.sh --sign "Developer ID Application: Andrei M. Lavrenov (VUMUR696L9)" --out dist`, exit 0. Output tail:

```
dist/macos-apps-mcp.app/Contents/MacOS/macos-apps-mcp: replacing existing signature
dist/macos-apps-mcp.app: replacing existing signature
dist/macos-apps-mcp.app: valid on disk
dist/macos-apps-mcp.app: satisfies its Designated Requirement
built: dist/macos-apps-mcp.app
```

- Bundle checks: build_stamp `bd6fe53 2026-09-25T19:39:50Z`; CFBundleShortVersionString `0.11.0`; Identifier `ren.lav.macos-apps-mcp`; TeamIdentifier `VUMUR696L9`, the same team as the replaced app, so the TCC grants carry over.

## Install and kickstart

```
ditto /Applications/macos-apps-mcp.app <scratchpad>/backup-v0.11.0-f52e9d5/macos-apps-mcp.app
diff -rq /Applications/macos-apps-mcp.app <backup>        # identical
rm -rf /Applications/macos-apps-mcp.app
cp -R dist/macos-apps-mcp.app /Applications/
codesign --verify --strict /Applications/macos-apps-mcp.app   # ok, before first launch
launchctl kickstart -k gui/$(id -u)/ren.lav.macos-apps-mcp
```

The daemon came back as a new process (pid 87760, was 36661). The socket answered at once.

## Probe

`uv run python .worktrees/.daemon_probe.py`:

```
version: 0.11.0
build: bd6fe53 2026-09-25T19:39:50Z
deployment.outbound: ['mail']
mail_index surface: {'surface': 'mail_index', 'kind': 'sqlite', 'ok': True, 'status': 'ok'}
send_mail in tool list: True
```

- Build token: `bd6fe53` equals BUILT, and it carries no `-dirty`.
- Outbound branch: `deployment.outbound` lists `mail`, so `send_mail` was called once with `{"to": "andrei@lav.ren", "subject": "gate check", "body": "dry run", "dry_run": true}`. The result:

```json
{
  "dry_run": true,
  "would_send": {
    "action": "send", "to": ["andrei@lav.ren"], "cc": [], "bcc": [],
    "from": "(Mail default account)", "subject": "gate check", "source": "",
    "body_chars": 7, "html": false
  }
}
```

No mail was sent.
- mail_index: `ok` on the real Envelope Index. Card 3's widened `HEADER_FINGERPRINT` holds on this Mac.

## Cleanup

`git worktree remove --force .worktrees/devbuild-card-5` removed the worktree; `--force` was needed only for the ignored `dist/` and `__pycache__/`. `.worktrees/.daemon_probe.py` is kept for plan 01-14. The v0.11.0 backup stays in the session scratchpad.

## Deviations from Plan

1. **Route.** Task 2 ran in the orchestrator session, by owner choice, instead of in a dispatched executor (see key-decisions). Before that, a worktree-isolated executor stopped at its first git command without building anything.
2. **Backup before removal.** The plan removes the installed app outright. A byte-identical backup was taken first to give a rollback path.

## Issues Encountered

- **The installed bundle's seal breaks after first launch.** `codesign --verify --strict` fails on a running install ("a sealed resource is missing or invalid") because the daemon's Python writes `__pycache__/*.pyc` into `Contents/lib/python3.14/site-packages` after signing. The v0.11.0 install showed it too. The daemon still launches and keeps its TCC grants, so nothing is broken today. A fix is to precompile the `.pyc` files before signing, or to run the interpreter with `-B`. Recorded as a pending todo in STATE.md.

## Next

Owner: reconnect every Claude Code session with `/mcp`; doctor() should show build `bd6fe53 2026-09-25T19:39:50Z`. Card 2 (plan 01-11) may start.

## Self-Check: PASSED
