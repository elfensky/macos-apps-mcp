---
phase: 01-gate-land-the-spiked-architecture-cuts
plan: 01
subsystem: infra
tags: [release, codesign, notarization, launchd, daemon, github-releases]

# Dependency graph
requires: []
provides:
  - "v0.11.0 tagged on origin/main, the byte-identity baseline for card 4 (plan 01-05) and the pre-cut develop tree for success criterion 5"
  - "Installed, notarized daemon running v0.11.0 (build f52e9d5) — every gate card now builds against an installed baseline that already carries the Sequoia mail plane"
affects: [01-05, 01-10, 01-14]

actuals:
  tokens: 6000
  tasks: 3
  commits: 2

tech-stack:
  added: []
  patterns:
    - "Release cut: PR develop→main merged with --merge (never rebase, never --delete-branch since head=develop), tag the merge commit, build only in a detached tag worktree, re-zip after stapling"
    - "Daemon proof: .worktrees/.daemon_probe.py (git-ignored) connects over the unix socket the same way deploy._request_grants_via_daemon does, and reads doctor()'s version/build/deployment/surfaces fields"

key-files:
  created:
    - ".worktrees/.daemon_probe.py (git-ignored, reused by plans 01-10 and 01-14)"
  modified: []

key-decisions:
  - "Ledger baseline (gsd-plan-head-before-01-01) set to 20a1a6a (develop tip before Task 1's version-bump commit) so the plan's commit count covers both the version-bump commit and this metadata commit."
  - "Release notes body extracted verbatim from CHANGELOG.md's ## [0.11.0] section via awk range-match, passed to gh release create --notes-file (no rewriting)."

patterns-established:
  - "One-off device probes for daemon proofs live at .worktrees/.daemon_probe.py, git-ignored, kept across plans that need the same proof (01-10, 01-14)."

requirements-completed: [GATE-13]

coverage:
  - id: D1
    description: "Release PR develop→main merged with a merge commit; tag v0.11.0 pushed pointing at it"
    requirement: "GATE-13"
    verification:
      - kind: other
        ref: "git log -1 --format=%P origin/main (two parents, second=8682676); git rev-parse v0.11.0^{commit} == git rev-parse origin/main"
        status: pass
    human_judgment: false
  - id: D2
    description: "Notarized, stapled .app built from the tag in a detached worktree, re-zipped after stapling, uploaded as a GitHub release asset"
    requirement: "GATE-13"
    verification:
      - kind: other
        ref: "xcrun stapler validate + spctl -a -vv -t install (source=Notarized Developer ID); gh release view v0.11.0 --json assets"
        status: pass
    human_judgment: false
  - id: D3
    description: "Daemon reinstalled at /Applications, kickstarted, and proven to serve v0.11.0 build f52e9d5 with no -dirty"
    requirement: "GATE-13"
    verification:
      - kind: other
        ref: "uv run python .worktrees/.daemon_probe.py"
        status: pass
    human_judgment: true
    rationale: "The plan's own <verify> requires an owner-run doctor() from a reconnected client as a human-check, in addition to the automated probe."

duration: 11min
completed: 2026-09-25
status: complete
---

# Phase 1 Plan 1: Cut and Install v0.11.0 Summary

**v0.11.0 released and installed — build f52e9d5**

## Performance

- **Duration:** 11 min (Task 3 continuation; Task 1's version bump landed in a prior session)
- **Started:** 2026-09-25T11:29:00Z
- **Completed:** 2026-09-25T11:40:29Z
- **Tasks:** 3 (1: version bump PR — prior session; 2: owner go — prior session; 3: cut, build, install, prove — this session)
- **Files modified:** 0 in this repo's tracked tree (Task 3 touches git refs, a GitHub release, and `/Applications/macos-apps-mcp.app` only)

## Accomplishments

- Release PR `develop` → `main` (#212) merged with a merge commit (`f52e9d5`, two parents: `5f2cfb1` v0.10.1 and `8682676` the 0.11.0 version-bump commit); tag `v0.11.0` created and pushed pointing at it.
- `.app` built from a detached worktree at the `v0.11.0` tag, signed inside-out with the Developer ID identity, notarized (`xcrun notarytool submit --wait` → Accepted) and stapled; `xcrun stapler validate` and `spctl -a -vv -t install` both confirm `source=Notarized Developer ID`.
- Re-zipped after stapling (`ditto -c -k --keepParent`) and uploaded to the GitHub release `v0.11.0` (asset `macos-apps-mcp-0.11.0.zip`), with release notes taken verbatim from `CHANGELOG.md`'s `## [0.11.0]` section.
- Old daemon bundle (0.10.1, build `5f2cfb1`) replaced in `/Applications`, `launchctl kickstart -k` fired, socket back up in 1s.
- `.worktrees/.daemon_probe.py` (git-ignored) proves the daemon over the unix socket: `version: 0.11.0`, `build: f52e9d5` (resolves to `v0.11.0`'s commit, no `-dirty`), `deployment.outbound: ['mail']`, `mail_index` surface `ok`, `send_mail` present in the tool list.
- Build worktree `.worktrees/build-v0.11.0` removed; vault journal bullet landed (`elfensky/obsidian` MR !796).

## Evidence pasted from the plan's acceptance criteria

- `git log -1 --format=%P origin/main` → `5f2cfb126a90e78cae38370279c7d9de3d5f4ea9 8682676079a6a70e283e52d04baa7f41d9636dcb` (two parents; second is the develop tip carrying the 0.11.0 bump).
- `git rev-parse v0.11.0^{commit}` == `git rev-parse origin/main` == `f52e9d51fdd2729d108113a262aabcdd956dee9b`.
- `spctl -a -vv -t install dist/macos-apps-mcp.app`:
  ```
  dist/macos-apps-mcp.app: accepted
  source=Notarized Developer ID
  origin=Developer ID Application: Andrei M. Lavrenov (VUMUR696L9)
  ```
- `gh release view v0.11.0 --json assets --jq '.assets[].name'` → `macos-apps-mcp-0.11.0.zip`.
- Daemon probe output:
  ```
  version: 0.11.0
  build: f52e9d5 2026-09-25T11:33:07Z
  deployment.outbound: ['mail']
  mail_index surface: {'surface': 'mail_index', 'kind': 'sqlite', 'ok': True, 'status': 'ok'}
  send_mail in tool list: True
  ```
  `git rev-parse f52e9d5` == `git rev-parse v0.11.0^{commit}` — confirmed match, no `-dirty`.
- `git worktree list` no longer lists `.worktrees/build-v0.11.0` or `.worktrees/release-0.11.0`.

## Task Commits

1. **Task 1: Land the 0.11.0 version bump on develop by PR** — `8682676` (chore) — landed in a prior session via PR #211 (rebase-merged, lane commit `10130a1`).
2. **Task 2: Owner go for the one-way release cut** — checkpoint, no commit (owner answered "cut-now").
3. **Task 3: Cut v0.11.0, build the notarized .app, install, kickstart and prove it** — no repo-tracked file changes; produced git ref `v0.11.0`, PR #212 merge commit `f52e9d5` on `origin/main`, and a GitHub release. Nothing to commit in this repo's tree for this task.

**Plan metadata:** committed together with this SUMMARY (see below).

## Files Created/Modified

- `.worktrees/.daemon_probe.py` — git-ignored one-off daemon proof script, kept for plans 01-10 and 01-14 to reuse.
- No tracked repository files were modified by Task 3.

## Decisions Made

- Release notes for `gh release create` were extracted verbatim from `CHANGELOG.md`'s `## [0.11.0]` section (awk range match stopping before the next `## [` heading) rather than hand-written, so the release body matches the changelog exactly.
- The commit ledger baseline for this plan (`gsd-plan-head-before-01-01`) was set to `20a1a6a` (develop tip immediately before Task 1's version-bump commit), since Task 1's commit landed in a separate worktree/session before this continuation's ledger file existed. This lets the measured commit count include both the version-bump commit and this metadata commit.

## Deviations from Plan

None - plan executed exactly as written. Both of Task 3's preconditions (codesigning identity present, `notarytool history` reachable) were verified before the first one-way step, per the resume instructions, and passed without incident.

## Issues Encountered

None. The `gh pr checks --watch --required` call for PR #212 returned promptly with all required checks green; no auth gates or retries were needed.

## User Setup Required

None - no external service configuration required. However, this replaces the daemon transport: **every connected MCP client must reconnect (`/mcp` in each Claude Code session) to pick up the new build** — a client that stays connected keeps talking to the old shim process until it respawns.

## Next Phase Readiness

- `v0.11.0` exists on `origin` as the pre-cut baseline for the gate cards (success criterion 5) and the byte-identity baseline for card 4 (plan 01-05).
- The installed daemon now serves the Sequoia mail plane (#199/#201/#204) that was previously only on `develop`.
- `.worktrees/.daemon_probe.py` is in place for plans 01-10 and 01-14 to reuse without rewriting the probe.
- No blockers. Card 1 (native seam) can start.

---
*Phase: 01-gate-land-the-spiked-architecture-cuts*
*Completed: 2026-09-25*
