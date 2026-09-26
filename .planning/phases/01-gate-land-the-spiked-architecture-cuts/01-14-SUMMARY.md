---
phase: 01-gate-land-the-spiked-architecture-cuts
plan: 14
subsystem: infra
tags: [daemon, codesign, launchd, dev-build, gate-check, git-cleanup]

# Dependency graph
requires: ["01-13", "01-08", "01-07", "01-03"]
provides:
  - "Installed daemon runs a signed dev build of develop 8885ad0 (card 2 landed); the four D-01/D-02 dry-run defaults, the outbound ledger, and mail_index are proven live"
  - "D-09 complete: every spike/arch-review-* branch and worktree removed; GATE-13's landing-order edge (1 -> 7 -> 5 -> 2) confirmed on origin/develop"
affects: []

actuals:
  tokens: 850
  tasks: 3
  commits: 0

tech-stack:
  added: []
  patterns:
    - "Same dev-build swap pattern as 01-10: detached worktree at origin/develop, build_app.sh --sign (no notarize), ditto backup + diff -rq, rm + cp -R, launchctl kickstart -k, extended probe over the unix socket"

key-files:
  created: []
  modified: []

key-decisions:
  - "Task 1 (blocking-human) was answered by the owner on 2026-09-26 as 'swap-and-clean', before this executor was dispatched (recorded in .continue-here.md and STATE.md). This SUMMARY records that answer; the executor did not re-ask."
  - "Per orchestrator instruction, the vault-journal step at the end of Task 3 was skipped — the orchestrator journals the phase close itself after its own tooling finishes, to avoid a vault touch locking the orchestrator session out of gsd-tools. See Deviations."

patterns-established: []

requirements-completed: [GATE-13]

coverage:
  - id: D1
    description: "Dev build of develop 8885ad0 (card 2) installed and kickstarted; probe proves version 0.11.0, build token 8885ad0 without -dirty, all four dry_run defaults true, outbound ledger agrees with the tool list, and a dry-run-only send_mail preview"
    requirement: "GATE-13"
    verification:
      - kind: other
        ref: "uv run python .worktrees/.daemon_probe.py (extended for 01-14)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Landing order (1 -> 7 -> 5 -> 2) confirmed on origin/develop since v0.11.0; every spike/arch-review-* branch (11) and worktree (9) removed, none with uncommitted changes, no remote spike branches"
    requirement: "GATE-13"
    verification:
      - kind: other
        ref: "git log --oneline --reverse v0.11.0..origin/develop; Task 3 <automated> verify command"
        status: pass
    human_judgment: false

duration: 25min
completed: 2026-09-26
status: complete
---

# Phase 1 Plan 14: Post-card-2 Dev-build Daemon Swap and Spike Cleanup Summary

**Daemon rebuilt from develop 8885ad0 (card 2) with every D-01/D-02/D-06 gate proven live; all 11 spike branches and their 9 worktrees deleted, GATE-13's landing order confirmed.**

## Owner go (Task 1) — already answered

The owner answered **"swap-and-clean"** on 2026-09-26 (recorded in `.continue-here.md` and
`STATE.md` before this executor was dispatched). This executor started at Task 2 and did not
re-ask the question.

## Task 2: Dev build, install, probe

### Build

- `BUILT` = `8885ad068791ddcc3f8e7dbb80c793d4188ed747` (origin/develop tip; card 2 / PR #219,
  the last of cards 1 -> 7 -> 5 -> 2)
- Worktree: `git worktree add --detach .worktrees/devbuild-card-2 origin/develop`, clean
  (`git status --porcelain` empty), `git describe --always --dirty --exclude '*'` = `8885ad0`
- `codesign -v -p codesigning` confirmed identity `5801DB97C1ABD1CDB6B122213E77F86536D32F3B
  "Developer ID Application: Andrei M. Lavrenov (VUMUR696L9)"` before building
- `scripts/build_app.sh --sign "Developer ID Application: Andrei M. Lavrenov (VUMUR696L9)" --out dist`
  run from inside the worktree, exit 0. Tail:

```
dist/macos-apps-mcp.app/Contents/MacOS/macos-apps-mcp: replacing existing signature
dist/macos-apps-mcp.app: replacing existing signature
dist/macos-apps-mcp.app: valid on disk
dist/macos-apps-mcp.app: satisfies its Designated Requirement
built: dist/macos-apps-mcp.app
```

- Bundle checks: `build_stamp` = `8885ad0 2026-09-26T08:48:01Z` (matches `$BUILT`, no `-dirty`);
  `CFBundleShortVersionString` `0.11.0`; `CFBundleIdentifier` `ren.lav.macos-apps-mcp`;
  `TeamIdentifier` `VUMUR696L9`; `codesign -dvv` shows `flags=0x10000(runtime)`.

### Backup, install, kickstart

Backup taken before touching the installed app (safety rule 1 — the plan removes the
installed app outright):

```
ditto /Applications/macos-apps-mcp.app <scratchpad>/backup-pre-card2-0.11.0-bd6fe53/macos-apps-mcp.app
diff -rq /Applications/macos-apps-mcp.app <backup>        # no output — byte-identical
```

**Backup path:**
`/private/tmp/claude-501/-Users-andrei-Developer-macos-apps-mcp/2a5c7475-ba00-4d64-a52f-62f3abc1a712/scratchpad/backup-pre-card2-0.11.0-bd6fe53/macos-apps-mcp.app`
(session scratchpad; the previous v0.11.0/bd6fe53 backup from 01-10 is a separate directory in
the same scratchpad tree).

```
rm -rf /Applications/macos-apps-mcp.app
cp -R dist/macos-apps-mcp.app /Applications/
codesign --verify --strict /Applications/macos-apps-mcp.app   # ok, before first launch
launchctl kickstart -k gui/$(id -u)/ren.lav.macos-apps-mcp
```

The daemon came back as a new process (pid 77762). The unix socket
(`~/.local/state/macos-apps-mcp/daemon/mcp.sock`) answered within 1 second of the kickstart.
No probe failure occurred, so the rollback path (restore backup, kickstart, confirm old build
answers doctor) was never needed.

### Probe

`.worktrees/.daemon_probe.py` was extended in place (git-ignored, per the plan) to also check:
the `inputSchema` `dry_run` default of `delete_event`/`delete_draft`/`delete_note`/`update_note`
from `list_tools`; agreement between `deployment.outbound` and `send_mail`'s presence in the
tool list; and to run the dry-run-only `send_mail` probe itself instead of requiring a second
scratch script. It now exits non-zero on any failed criterion, so it doubles as the plan's
`<automated>` verify command.

Full output of `uv run python .worktrees/.daemon_probe.py` (exit 0):

```
version: 0.11.0
build: 8885ad0 2026-09-26T08:48:01Z
deployment.outbound: ['mail']
mail_index surface: {'surface': 'mail_index', 'kind': 'sqlite', 'ok': True, 'status': 'ok'}
send_mail in tool list: True
--- dry_run defaults ---
delete_event.dry_run default: True
delete_draft.dry_run default: True
delete_note.dry_run default: True
update_note.dry_run default: True
--- outbound dry-run probe ---
send_mail result: {'dry_run': True, 'would_send': {'action': 'send', 'to': ['andrei@lav.ren'], 'cc': [], 'bcc': [], 'from': '(Mail default account)', 'subject': 'gate check (01-14)', 'source': '', 'body_chars': 7, 'html': False}}
--- summary ---
PROBE PASSED
```

(A benign `asyncio.exceptions.InvalidStateError` traceback from `Future.set_result()` printed
after "PROBE PASSED", during interpreter shutdown — a known FastMCP/anyio cleanup artifact, not
a probe failure. Process exit code was confirmed 0 separately.)

Every plan criterion is met: version 0.11.0; build token `8885ad0` equals `$BUILT` with no
`-dirty`; all four `dry_run` defaults are `True`; `deployment.outbound` (`['mail']`) agrees with
`send_mail` being present in the tool list; the send result carries `dry_run: true`; mail_index
status is `ok`.

### Cleanup

`git worktree remove --force .worktrees/devbuild-card-2` removed the build worktree (`--force`
only for the ignored `dist/` inside it). `git worktree list` afterward shows only the main
checkout. `.worktrees/` now holds only `.daemon_probe.py`, as before.

### Pending human check

Per the plan's `<verify><human-check>`, the owner should reconnect one Claude Code session
with `/mcp`; its `doctor()` should show build `8885ad0 2026-09-26T08:48:01Z`, and calling
`delete_event` with only an id should return a preview (dry-run, no delete). This is the
owner's own follow-up — not blocking, per the orchestrator's dispatch notes.

## Task 3: Landing order and spike cleanup (D-09)

### Landing order (GATE-13)

`git fetch -q --prune origin` then `git log --oneline --reverse v0.11.0..origin/develop`
(29 commits). First commit of each sequential card, in the order they appear in that log:

| Order | Card | PR | First commit | Last commit |
|-------|------|----|--------------|--------------|
| 1 | Card 9 (script-timeout tripwire) | #213 | `0cfc0f0` | `36624be` |
| 2 | **Card 1** (native seam) | #214 | `dbcb326` | `7a3194b` |
| 3 | Card 4 (recoverable preflight) | #215 | `3ba1c9a` | `799355c` |
| 4 | **Card 7** (runtime split) | #216 | `32d0f20` | `8627aa8` |
| 5 | Card 3 (fake-envelope fixture) | #217 | `1978bdd` | `26550d3` |
| 6 | **Card 5** (tier policy) | #218 | `c7a9e88` | `bd6fe53` |
| 7 | **Card 2** (registration record) | #219 | `43346ed` | `8885ad0` |

The four sequential cards appear in the required order **1 -> 7 -> 5 -> 2** (first-commit
position: card 1 before card 7 before card 5 before card 2). The Mail-scoped cards 3, 4 and 9
interleave among them, as the plan allows. `v0.11.0` resolves to `f9ac7b06c0368e8bdefe2306c3724bdc3489f3ed`.

### Cleanup (D-09)

Each step's list was printed before it ran, per the plan.

**1. Delete set** — `git branch --list 'spike/arch-review-*'` printed exactly these 11
branches (nothing outside this pattern was touched):

```
spike/arch-review-1-native-seam
spike/arch-review-2-registration-record
spike/arch-review-3-fake-envelope-fixture
spike/arch-review-4-recoverable-preflight
spike/arch-review-5-tier-policy
spike/arch-review-6-baseline-13th
spike/arch-review-6-mailfilter
spike/arch-review-7-runtime-split
spike/arch-review-8-mailadapter-passthroughs
spike/arch-review-8-mailadapter-passthroughs-alt
spike/arch-review-9-script-preamble
```

**2. Worktrees** — `git worktree list --porcelain` showed 9 worktrees under
`.claude/worktrees/agent-*`, each checked out on one of the branches above (none locked).
`git -C <path> status --porcelain` was run for every one of the 9 and printed **no output for
any of them** — none had uncommitted changes, so none was skipped and no work was discarded.
All 9 were removed with `git worktree remove` (no `--force` needed):

| Worktree | Branch |
|----------|--------|
| `agent-a26e9f5a499b70861` | spike/arch-review-1-native-seam |
| `agent-a3159da7a809ad81f` | spike/arch-review-3-fake-envelope-fixture |
| `agent-a468a8b0b59471405` | spike/arch-review-4-recoverable-preflight |
| `agent-a78ed6c6c31b24972` | spike/arch-review-8-mailadapter-passthroughs |
| `agent-a8a85a0bb5f46b4c1` | spike/arch-review-2-registration-record |
| `agent-a9472e832c8a978ab` | spike/arch-review-9-script-preamble |
| `agent-a961de51fed09235c` | spike/arch-review-6-mailfilter |
| `agent-acb47f116c41a7bbf` | spike/arch-review-5-tier-policy |
| `agent-ad7965b0d53e87357` | spike/arch-review-7-runtime-split |

(9 removed — `spike/arch-review-6-baseline-13th` and
`spike/arch-review-8-mailadapter-passthroughs-alt` had no worktree, matching the orchestrator's
pre-dispatch inventory.)

**3. Branches** — `git branch -D` deleted all 11 branches listed in step 1. Confirmed
afterward: `git branch --list 'spike/arch-review-*'` prints nothing.

**4. Remote check** — `git ls-remote --heads origin 'spike/arch-review-*'` returned nothing
both before and after cleanup — there were no remote spike branches to delete.

**5. Prune** — `git worktree prune` ran; `git worktree list` shows only the main checkout.

### Task 3 automated verify

```
wt="$(git worktree list --porcelain)" && test -z "$(git branch --list 'spike/arch-review-*')" \
  && test -z "$(git ls-remote --heads origin 'spike/arch-review-*')" \
  && ! printf '%s' "$wt" | grep -q 'refs/heads/spike/arch-review-'
```

Exit code: **0** (pass).

## Files Created/Modified

None in the repository. `.worktrees/.daemon_probe.py` (git-ignored) was extended in place, per
the plan's Artifacts note. `/Applications/macos-apps-mcp.app` was replaced with the new dev
build (not a repo file).

## Decisions Made

- Task 1's owner decision ("swap-and-clean") was pre-answered before this executor's dispatch;
  see key-decisions and STATE.md/`.continue-here.md`.
- The vault-journal step named in Task 3's action was deliberately skipped — see Deviations.

## Deviations from Plan

### Auto-fixed Issues

None — no bugs, missing functionality, or blocking issues were found during execution.

### Other deviations (not auto-fix rules 1-3, but explicitly authorized by the dispatch)

**1. [Dispatch override] Skipped the `vault-journal` call at the end of Task 3's action**
- **Found during:** Task 3 (cleanup action text names `vault-journal: "gate landed — cards
  1/7/5/2 + 3/4/9; spikes deleted"`)
- **Reason:** The orchestrator's dispatch notes explicitly instruct deferring this to the
  orchestrator itself, since a vault touch from this session could lock the orchestrator's own
  session out of `gsd-tools.cjs` (the same Toyota-lock failure mode recorded in
  `.continue-here.md`'s blockers).
- **Impact:** None on this plan's deliverables. The orchestrator is expected to journal the
  phase close after its own tooling finishes.

---

**Total deviations:** 0 auto-fixed; 1 authorized process deviation (vault-journal deferred).
**Impact on plan:** No scope creep, no unresolved issues.

## Issues Encountered

- A benign `asyncio.exceptions.InvalidStateError` traceback printed after `PROBE PASSED` during
  probe script interpreter shutdown (FastMCP/anyio cleanup noise on the async client). Confirmed
  non-fatal — process exit code is 0. No action needed; not a probe result.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Success criterion 6 (D-06 reading) and D-09 are both met: the dev-build daemon proves every
  gate/dry-run/outbound criterion on develop 8885ad0 (card 2), and every spike branch and
  worktree is gone.
- No release was cut in this plan — per D-06, the next release follows Phase 2 (GATE-12 device
  sweep green). The daemon currently serves a signed **dev build** (8885ad0), not a tagged
  release; `main`/tags are unaffected.
- Owner follow-up: reconnect Claude Code sessions with `/mcp` and confirm `doctor()` shows build
  `8885ad0 2026-09-26T08:48:01Z` (the pending human check above).
- The phase's remaining gates (code review, verifier, `update_roadmap`) and ticking GATE-13 are
  the orchestrator's responsibility per the dispatch instructions — not performed by this
  executor.

---
*Phase: 01-gate-land-the-spiked-architecture-cuts*
*Completed: 2026-09-26*

## Self-Check: PASSED

- `.planning/phases/01-gate-land-the-spiked-architecture-cuts/01-14-SUMMARY.md` exists on disk (untracked, per dispatch instructions — orchestrator commits it with tracking).
- No task commits exist for this plan (plan changes no repo files) — `git log` HEAD is unchanged from before this session (`1d1ce63`), matching `commits: 0` in the frontmatter.
- Task 2 acceptance criteria: probe output pasted above meets every plan criterion (version 0.11.0; build `8885ad0` == `$BUILT`, no `-dirty`; all four `dry_run` defaults `True`; outbound/tool-list agreement; dry-run-only send; mail_index `ok`); `.worktrees/devbuild-card-2` confirmed absent from `git worktree list`.
- Task 3 acceptance criteria: landing order 1 -> 7 -> 5 -> 2 confirmed by commit position; 11 branches and 9 worktrees listed and removed, all confirmed clean before removal; `git branch --list 'spike/arch-review-*'` and `git ls-remote --heads origin 'spike/arch-review-*'` both empty; automated verify command exit code 0.
