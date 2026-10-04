---
phase: 02-gate-close-fail-closed-suite-and-device-sweep
plan: 06
subsystem: infra
tags: [release, codesign, notarization, launchd, daemon, github-releases]

requires:
  - phase: 02-gate-close-fail-closed-suite-and-device-sweep
    provides: "02-05 (final device sweep green by D-06: .worktrees/sweep-02-final.xml failures 0, errors 0)"
provides:
  - "v0.12.0 tagged on origin/main (merge commit 5ce98ab), released on GitHub with the stapled zip and the CHANGELOG notes"
  - "Installed, notarized daemon running v0.12.0 (build 5ce98ab, no -dirty) — Phase 2 closes with a tagged release under the daemon instead of the dev build 7e8a079"
affects: ["02.1 (builds on a released, installed 0.12.0 daemon)", "docs/RELEASING.md (procedure re-proven unchanged)"]

actuals:
  tokens: 15000
  tasks: 3
  commits: 1

tech-stack:
  added: []
  patterns:
    - "Release cut as in 01-01: PR develop→main merged with --merge, tag the merge commit, build only in a detached tag worktree, zip after stapling, probe the installed daemon"

key-files:
  created: []
  modified:
    - "pyproject.toml, packaging/Info.plist, uv.lock, CHANGELOG.md (PR #238, rebase commit 50b9def on origin/develop)"

key-decisions:
  - "D-09 executed as decided: version 0.12.0 (feat commits and a contract change since 0.11.0), cut only after the owner's 'cut-now' at Task 2."
  - "The old bundle was moved aside (mv) as the backup instead of ditto-then-rm: one step, same outcome, the backup is the original bytes."

patterns-established: []

requirements-completed: [GATE-12]

coverage:
  - id: D1
    description: "0.12.0 bump landed on develop by a rebase-merged PR; uv.lock changed only the root version line; CHANGELOG has the dated 0.12.0 section and a fresh empty Unreleased"
    requirement: GATE-12
    verification:
      - kind: other
        ref: "git show origin/develop:pyproject.toml | grep -c '^version = \"0.12.0\"' → 1; Info.plist → 1; git diff --stat 50b9def^ 50b9def -- uv.lock → 1 insertion(+), 1 deletion(-)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Owner approved the one-way cut before main, the tag or the release was pushed"
    requirement: GATE-12
    verification:
      - kind: other
        ref: "Task 2 blocking-human checkpoint answered 'cut-now' (2026-10-01); nothing was pushed to main before it"
        status: pass
    human_judgment: true
    rationale: "A checkpoint answer is the owner's act, recorded here."
  - id: D3
    description: "develop→main merge commit 'Release v0.12.0 — Architecture gate', tag v0.12.0 on it, GitHub release with macos-apps-mcp-0.12.0.zip made after stapling, notes naming the dry-run contract change"
    requirement: GATE-12
    verification:
      - kind: other
        ref: "git log -1 --format=%P origin/main → f52e9d5 50b9def; git rev-parse v0.12.0^{commit} == origin/main == 5ce98ab; gh release view v0.12.0 assets → macos-apps-mcp-0.12.0.zip; body names delete_event, delete_draft, delete_note, update_note"
        status: pass
    human_judgment: false
  - id: D4
    description: "Installed daemon answers doctor() with version 0.12.0 and a build token resolving to v0.12.0's commit, no -dirty"
    requirement: GATE-12
    verification:
      - kind: other
        ref: "uv run python .worktrees/.daemon_probe.py 0.12.0 5ce98ab… → PROBE PASSED; doctor() from a reconnected Claude Code session → version 0.12.0, build 5ce98ab 2026-10-01T05:33:30Z"
        status: pass
    human_judgment: true
    rationale: "The plan's human-check (doctor() from a reconnected client) was run from the orchestrating session after the daemon swap."

duration: "Task 1 ~10 min (2026-09-30 evening); Task 3 ~12 min (2026-10-01 07:25–07:38, notarization ~3 min)"
completed: 2026-10-01
status: complete
---

# Phase 2 Plan 6: Cut and Install v0.12.0 Summary

**v0.12.0 released and installed — build 5ce98ab**

## Performance

- **Duration:** Task 1 ~10 min; Task 3 ~12 min (notarization wait ~3 min). Task 2 was an owner checkpoint.
- **Started:** 2026-09-30T22:05+02:00 (Task 1 lane); Task 3 2026-10-01T07:25+02:00
- **Completed:** 2026-10-01T07:38+02:00
- **Tasks:** 3 of 3
- **Files modified:** 4 tracked files in PR #238 (Task 1); Task 3 touches git refs, a GitHub release and `/Applications/macos-apps-mcp.app` only

## Accomplishments

- **Task 1.** Lane `.worktrees/release-0.12.0` off `origin/develop` @ `f6e7342`: `pyproject.toml` and
  `packaging/Info.plist` 0.11.0 → 0.12.0; `uv lock` (no `--upgrade`) changed only the root version
  line; `CHANGELOG.md` `## [Unreleased]` → `## [0.12.0] - 2026-09-30 — Architecture gate` with a new
  empty `## [Unreleased]` above and the entry text untouched (it names `delete_event`, `delete_draft`,
  `delete_note` and `update_note`). PR [#238](https://github.com/elfensky/macos-apps-mcp/pull/238),
  required check 50 s, rebase-merged → **`50b9def`**. Lane removed.
- **Task 2.** Owner checkpoint (D-09) answered **cut-now**; the identity
  `Developer ID Application: Andrei M. Lavrenov (VUMUR696L9)` was listed by
  `security find-identity -v -p codesigning` and `xcrun notarytool history --keychain-profile notary`
  returned history before the first one-way step.
- **Task 3.** PR [#240](https://github.com/elfensky/macos-apps-mcp/pull/240) `develop` → `main`,
  required check 47 s, merged with `--merge --subject "Release v0.12.0 — Architecture gate"` →
  **`5ce98ab`** (parents `f52e9d5` = v0.11.0, `50b9def` = the bump). Tag `v0.12.0` created on
  `origin/main` and pushed. Built in `.worktrees/build-v0.12.0` detached at the tag (`git describe
  --always --dirty` → `v0.12.0`), signed, notarized (submission `7116cf3e-9bed-4b08-9991-abb9a00a5c8a`,
  Accepted), stapled; `xcrun stapler validate` ok; `spctl` accepted; zipped after stapling
  (`macos-apps-mcp-0.12.0.zip`, 46.5 MB). GitHub release
  [v0.12.0](https://github.com/elfensky/macos-apps-mcp/releases/tag/v0.12.0) created from the
  CHANGELOG section (scratchpad notes file, verbatim) and the zip uploaded. Old bundle (0.11.0, dev
  build `7e8a079`) moved to the session scratchpad as the backup; new bundle copied to
  `/Applications`, `codesign --verify --strict` ok, `launchctl kickstart -k` at 07:37:26, socket up
  in 6 s, probe PASSED. Build worktree removed; vault journal bullet landed 2026-10-01.

## Evidence pasted from the plan's acceptance criteria

- Task 1 verify: `git show origin/develop:pyproject.toml | grep -c '^version = "0.12.0"'` → `1`;
  `… packaging/Info.plist | grep -c '<string>0.12.0</string>'` → `1`;
  `git diff --stat 50b9def^ 50b9def -- uv.lock` → ` 1 file changed, 1 insertion(+), 1 deletion(-)`;
  `git show origin/develop:CHANGELOG.md | grep -n '^## \['` → `7:## [Unreleased]`,
  `9:## [0.12.0] - 2026-09-30 — Architecture gate`, `22:## [0.11.0] - 2026-09-25 — Sequoia mail plane`.
- The six local checks in the lane (pasted):
  ```
  uv run pytest tests/test_packaging.py      5 passed in 0.67s
  uv run pytest                              1492 passed, 80 deselected in 15.52s
  MACOS_APPS_ALLOW_SEND=mail uv run pytest   1488 passed, 4 skipped, 80 deselected in 14.90s
  MACOS_APPS_READ_ONLY=1 uv run pytest       1483 passed, 9 skipped, 80 deselected in 14.31s
  uv run ruff check .                        All checks passed!
  uv run ruff format --check .               104 files already formatted
  ```
- `git log -1 --format=%P origin/main` → `f52e9d51fdd2729d108113a262aabcdd956dee9b 50b9def2be86f65f23c37a025b8bf23cc42dcb8b`
  (two parents; the second is the develop commit carrying the 0.12.0 bump).
- `git rev-parse v0.12.0^{commit}` == `git rev-parse origin/main` == `5ce98abf99dfe5c3d7d1f8eecc02325f71de926e`.
- `spctl -a -vv -t install dist/macos-apps-mcp.app`:
  ```
  dist/macos-apps-mcp.app: accepted
  source=Notarized Developer ID
  origin=Developer ID Application: Andrei M. Lavrenov (VUMUR696L9)
  ```
- `gh release view v0.12.0 --json assets --jq '.assets[].name' | grep -c macos-apps-mcp-0.12.0.zip` → `1`;
  `gh release view v0.12.0 --json body --jq .body` names `delete_event`, `delete_draft`, `delete_note`, `update_note`.
- Daemon probe (`uv run python .worktrees/.daemon_probe.py 0.12.0 5ce98abf99dfe5c3d7d1f8eecc02325f71de926e`):
  ```
  version: 0.12.0
  build: 5ce98ab 2026-10-01T05:33:30Z
  build token resolves to: 5ce98abf99dfe5c3d7d1f8eecc02325f71de926e
  deployment.outbound: ['mail']
  mail_index surface: {'surface': 'mail_index', 'kind': 'sqlite', 'ok': True, 'status': 'ok'}
  send_mail in tool list: True
  --- dry_run defaults ---
  delete_event.dry_run default: True
  delete_draft.dry_run default: True
  delete_note.dry_run default: True
  update_note.dry_run default: True
  --- outbound dry-run probe ---
  send_mail result: {'dry_run': True, 'would_send': {... 'subject': 'gate check (02-04)' ...}}
  --- summary ---
  PROBE PASSED
  ```
  No `-dirty`.
- Human-check: `doctor()` from the reconnected Claude Code session → `"version":"0.12.0","build":"5ce98ab 2026-10-01T05:33:30Z"`, responsible process `/Applications/macos-apps-mcp.app/Contents/MacOS/macos-apps-mcp`, launched by launchd — the same token as the probe.
- `git worktree list` lists neither `.worktrees/release-0.12.0` nor `.worktrees/build-v0.12.0`.

## Task Commits

1. **Task 1: Land the 0.12.0 version bump on develop by PR** — `50b9def` (chore) via PR #238, rebase-merged.
2. **Task 2: Owner approval for the one-way cut** — checkpoint, no commit (owner answered "cut-now").
3. **Task 3: Cut v0.12.0, build, release, install, prove** — no repo-tracked file changes; produced the merge commit `5ce98ab` on `origin/main`, tag `v0.12.0`, GitHub release `v0.12.0`, and the installed bundle.

## Files Created/Modified

- `pyproject.toml`, `packaging/Info.plist`, `uv.lock`, `CHANGELOG.md` — PR #238.
- `/Applications/macos-apps-mcp.app` — replaced (0.11.0 dev build `7e8a079` → 0.12.0 build `5ce98ab`); the previous bundle is kept in the session scratchpad under `backup-pre-0.12.0/`.
- No other tracked repository files.

## Decisions Made

- D-09 as decided; see key-decisions.
- Release notes extracted verbatim from `CHANGELOG.md`'s `## [0.12.0]` section (awk range match), as in 01-01.

## Deviations from Plan

- All three tasks were executed inline by the phase orchestrator session (execute-phase, interactive style) rather than by an executor subagent; every gate was honoured: Task 1 landed by PR with the six local checks, Task 2 was a real owner answer, Task 3's preconditions were checked before the first one-way step.
- The old bundle was backed up by `mv` into the scratchpad instead of `ditto` + remove — same outcome, one step.
- This SUMMARY lands by PR from a locked worktree (repo lane rule), not as a commit on the main checkout.

## Issues Encountered

- **The first install attempt restored the backup although the probe had passed.** The install script captured the probe's exit through `${PIPESTATUS[0]}`, which is bash; under zsh it is empty, so the `!= 0` branch ran: the 0.11.0 backup was moved back and the daemon kickstarted (07:36:48 → restore). The probe output itself read `PROBE PASSED`. The install was redone with the probe's exit read directly (`$?`), passed at 07:37:26, and the 0.12.0 bundle stayed. Net effect: connected MCP sessions dropped twice instead of once. Lesson for `docs/RELEASING.md` readers and future executors: in zsh use `$pipestatus[1]` or avoid the pipe.
- `gh pr merge` right after `gh pr create` can run before CI registers and is refused by the base-branch policy (seen on PR #236 earlier in this phase); a short pause before `gh pr checks --watch` avoids it.

## User Setup Required

Reconnect each Claude Code session's MCP client (`/mcp`) once; the daemon swap dropped the transport. This session's shim reconnected on its own.

## Next Phase Readiness

- Phase 2 is complete pending verification: GATE-07 and GATE-11 landed in wave 1, GATE-12 proven by 02-05, v0.12.0 released and installed by this plan.
- Next: Phase 02.1 (Mail fixes — #206 batch moves and the timeout, #208 draft account; plus #229 and #230 from the sweep).

---
*Phase: 02-gate-close-fail-closed-suite-and-device-sweep*
*Completed: 2026-10-01*

## Self-Check: PASSED

- `.planning/phases/02-gate-close-fail-closed-suite-and-device-sweep/02-06-SUMMARY.md` exists (this file), landed by PR.
- `git rev-parse v0.12.0^{commit}` == `git rev-parse origin/main` == `5ce98ab…`; `origin/main` has two parents, the second `50b9def`.
- GitHub release `v0.12.0` exists with asset `macos-apps-mcp-0.12.0.zip`; body names the four dry-run tools.
- Probe output and `spctl` output pasted verbatim above; `doctor()` from this session reports the same version and build token.
- `git worktree list` lists no `release-0.12.0` or `build-v0.12.0` worktree.
