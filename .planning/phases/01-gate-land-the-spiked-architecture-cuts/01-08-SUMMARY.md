---
phase: 01-gate-land-the-spiked-architecture-cuts
plan: 08
subsystem: mail
tags: [eventkit, mail, applescript, device-verification, gate-02, gate-09, gate-13, landing]

requires:
  - phase: 01-gate-land-the-spiked-architecture-cuts
    provides: "01-06's card 7 (runtime.py split, EventKit plane isolated in eventkit.py) merged to origin/develop"
  - phase: 01-gate-land-the-spiked-architecture-cuts
    provides: "01-05's card 4 (recoverable() owns its dry-run preflight), PR #215 open, CI-green, review-clean, merge held for this plan's device verification"
provides:
  - "Card 7's EventKit runtime split proven on real EventKit/TCC (GATE-02 device proof) — 7/7 green on origin/develop@26550d3, no leftovers"
  - "Card 4's recoverable() plane proven on the real scratch mailbox with the Mail watchdog running (GATE-09 device verification) — real move+undo round trip, plus a device dry-run identity diff against the v0.11.0 baseline"
  - "PR #215 merged via rebase (799355c on origin/develop) — card 4 landed"
affects: ["01-09 (card 5 — GATE-10 requirement tick), 01-14 (final branch/worktree cleanup, GATE-13)"]

actuals:
  tokens: 1800
  tasks: 2
  commits: 0
  plan_head_before: 162ef92
confidence_note: "This plan produced no repo diff of its own (files_modified: [] in frontmatter, as declared) — it verified card 7 and card 4 on real EventKit/Mail and merged a pre-existing PR (#215) via GitHub's rebase-merge, which replayed plan 01-05's own 3 commits onto origin/develop unchanged. commits: 0 reflects no NEW commit authored by this plan in the main checkout, matching the main-checkout rule that only fetch/worktree/branch-delete run here; the ~1800-token actuals figure is the scratch identity-probe script (outside the repo) plus this SUMMARY, not a code change."

tech-stack:
  added: []
  patterns:
    - "Device dry-run identity check: a recording pass-through installed directly on runtime.run_osascript (module-attribute patch, works because mail.py calls runtime.run_osascript(...) by qualified reference per #176) that still calls the REAL function — proves a dry run's actual native-call shape on live Mail, not a mocked shape, run once per tree via `uv run --project <tree> python <script>`."

key-files:
  created: []
  modified: []

key-decisions:
  - "Task 2's selector deviation (orchestrator-decided, pre-recorded in the dispatch): the plan's literal `-k \"request_access or create_event or create_reminder\"` collects only 1 test because the tests are named `event_create`/`reminder_create`, not `create_event`/`create_reminder`. Ran `-k \"request_access or event_create or reminder_create\"` instead, which collected exactly 7 tests as predicted."
  - "The `rtk` dev-CLI proxy hook summarized pytest's -k collection output as a bare 'Pytest: No tests collected' with exit 0 on the first collect-only attempt (a filtering artifact, not a real zero-collection) — resolved by using `rtk proxy <cmd>` to bypass filtering for every pytest/ruff/uv invocation in this plan, per CLAUDE.md's rtk note. Real collection was never zero; this is noted so a future session does not misread the summarized form as a failure."
  - "Task 3(b)'s identity script (outside the repo, per plan instruction) built its own script-identity map fresh in each of the two separate `uv run --project <tree> python` invocations, from that invocation's own `import macos_apps_mcp.adapters.mail` — `id(mail._PRESENT)` etc. are per-process values and cannot be compared across the two processes directly; only the JSON `script` label (`_PRESENT`/`_MOVE`/`_TRASH`/`_DEDUPE`/`?`) and the recorded args/kwargs are diffed, which is what the plan's acceptance criterion asks for."

requirements-completed: [GATE-02, GATE-09]

coverage:
  - id: D1
    description: "Card 7's EventKit device proof: uv run pytest -m integration -k \"request_access or event_create or reminder_create\" green on develop with card 7 merged, no macos-apps-mcp-test: leftovers"
    requirement: GATE-02
    verification:
      - kind: integration
        ref: "tests/test_integration.py -m integration -k \"request_access or event_create or reminder_create\" (run from a detached worktree at origin/develop@26550d3)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Card 4's scratch-mailbox verification: a real move -> undo round trip on Personal/macos-apps-mcp-test, with the Mail watchdog running, independently read back (not just the test's own return value)"
    requirement: GATE-09
    verification:
      - kind: integration
        ref: "tests/test_integration.py::test_move_mail_dry_run_reads_mail_and_moves_nothing, tests/test_integration.py::test_move_then_undo_returns_every_message_to_its_source"
        status: pass
      - kind: manual_procedural
        ref: "post-run python read-back via MailAdapter().search(): scratch mailbox empty, both round-tripped ids present-in-source (dry-run presence read, no write)"
        status: pass
    human_judgment: false
  - id: D3
    description: "Device dry-run identity diff: move_mail/trash_mail dry-run envelopes and osascript argv byte-identical between v0.11.0 baseline and the card-4 tree on real INBOX ids; dedupe_batch's dry run differs only by the added _PRESENT call and the statuses it produces"
    requirement: GATE-09
    verification:
      - kind: manual_procedural
        ref: "scratchpad/dry_run_identity_probe.py — recording pass-through around runtime.run_osascript, run once per tree, diffed"
        status: pass
    human_judgment: false
  - id: D4
    description: "Card 4 merged only after (a) and (b) both passed, by one rebase-merged PR; both worktrees and the lane branch cleaned up"
    requirement: GATE-13
    verification:
      - kind: other
        ref: "gh pr view 215 -> state=MERGED, mergeCommit=799355c44fe4691159f8efc95b9a4e24ddbf9f52; git log --oneline -1 origin/develop -> 799355c"
        status: pass
    human_judgment: false

duration: 35min
completed: 2026-09-25
status: complete
---

# Phase 01 Plan 08: Owner Device Session — Card 7 EventKit Proof, Card 4 Mail Verification and Merge Summary

**Card 7's EventKit runtime split went 7/7 green against real EventKit/TCC with zero leftovers, and card 4's `recoverable()` plane was verified on the real scratch mailbox with the Mail watchdog running (move+undo round trip, plus a device dry-run identity diff showing move/trash byte-identical and dedupe now correctly reading presence) — PR #215 merged via rebase (799355c) after both passed.**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-09-25T14:29:00Z (16:29 CEST)
- **Completed:** 2026-09-25T15:04:00Z (17:04 CEST)
- **Tasks:** 2 executed this session (Task 1's checkpoint:decision was answered by the owner before dispatch — see below); Task 3 also completed the card-4 merge and cleanup
- **Files modified:** 0 in the repo (device verification + merge plan, no `files_modified` declared)

## Task 1: Owner go (pre-answered)

The owner replied **"run-now"** on 2026-09-25 at approximately 16:28 CEST, confirming they were at the Mac for TCC prompts and to watch Mail during the scratch-mailbox verification. This plan started directly at Task 2 per the dispatch instructions; no checkpoint was re-presented.

## Deviations from Plan

### Auto-fixed / Orchestrator-directed

**1. [Pre-recorded orchestrator decision] Task 2 selector correction**
- **Found during:** Dispatch (pre-recorded by the orchestrator, confirmed on execution)
- **Issue:** The plan's literal selector `-k "request_access or create_event or create_reminder"` collects only 1 test (`test_request_access_grants_full`) because the actual test names are `test_event_create_*` / `test_reminder_create_*`, not `test_create_event`/`test_create_reminder`.
- **Fix:** Used `-k "request_access or event_create or reminder_create"` instead, per the dispatch's pre-recorded correction.
- **Verification:** Collected exactly 7 tests (`test_request_access_grants_full`, `test_reminder_create_update_complete`, `test_event_create_update_delete`, `test_event_create_all_day`, `test_reminder_create_with_priority`, `test_event_create_recurring_series`, `test_reminder_create_recurring`), matching the predicted count and names exactly.
- **Impact:** None on scope — same tests the plan intended, correct selector syntax only.

**2. [Tooling artifact, no code change] `rtk` proxy filtering summarized pytest's collect-only output**
- **Found during:** Task 2, initial `--collect-only` run
- **Issue:** The first `-k`-filtered `--collect-only` invocation (without `rtk proxy`) printed only `Pytest: No tests collected` with exit 0 — a summarization artifact from the `rtk` dev-CLI proxy hook, not a real zero-collection (re-running the identical command through `rtk proxy` showed the full, correct 7/1511 collection).
- **Fix:** Used `rtk proxy <cmd>` for every pytest/ruff/uv command for the rest of this plan, per CLAUDE.md's "`rtk proxy <cmd>` bypasses filtering when debugging" note.
- **Impact:** None — purely a local terminal-output artifact; no test behavior or code was affected.

---

**Total deviations:** 1 pre-recorded selector correction (no scope change), 1 tooling-output artifact (no code change).
**Impact on plan:** None beyond the intended, pre-recorded selector fix.

## Task 2: Card 7 EventKit device proof on develop (GATE-02)

**Develop sha tested:** `26550d3bdee0476fcaa1e4f4a6117f176bbde85e` (verified: `git rev-parse origin/develop` and `git worktree add --detach .worktrees/proof-card-7 origin/develop` both resolved to this sha).

Ran from a detached worktree (`.worktrees/proof-card-7`, `uv sync` first):

```
uv run pytest -m integration -k "request_access or event_create or reminder_create" -v
```

```
collected 1511 items / 1504 deselected / 7 selected

tests/test_integration.py::test_request_access_grants_full PASSED        [ 14%]
tests/test_integration.py::test_reminder_create_update_complete PASSED   [ 28%]
tests/test_integration.py::test_event_create_update_delete PASSED        [ 42%]
tests/test_integration.py::test_event_create_all_day PASSED              [ 57%]
tests/test_integration.py::test_reminder_create_with_priority PASSED     [ 71%]
tests/test_integration.py::test_event_create_recurring_series PASSED     [ 85%]
tests/test_integration.py::test_reminder_create_recurring PASSED         [100%]

7 passed, 1504 deselected in 1.20s
```

**Leftover read-back** (`CalendarAdapter().get_pointers("today")` / `RemindersAdapter().get_pointers("today")`, filtered for the `macos-apps-mcp-test:` prefix):

```
calendar leftovers: []
reminder leftovers: []
```

Worktree `.worktrees/proof-card-7` removed afterwards. GATE-02's device proof passes: 7/7 green, no leftovers.

## Watchdog precondition (re-checked immediately before Task 3)

```
$ launchctl list | grep ren.lav.mail-watchdog
-	0	ren.lav.mail-watchdog

$ tail -n 3 ~/mail-watchdog/watchdog.log
2026-09-25 16:32:25 mail_cpu=0.0% mem=0.1% rss=21MB osascript=0
2026-09-25 16:32:55 mail_cpu=0.0% mem=0.1% rss=21MB osascript=0 hot=bird:12.9%
2026-09-25 16:33:27 mail_cpu=0.2% mem=0.4% rss=108MB osascript=0 hot=bird:14.7%

$ date
Fri Sep 25 16:33:35 CEST 2026

$ pgrep -x Mail
49418   # Mail running
```

Watchdog loaded (exit 0), log line fresh (8 s old), Mail running and idle (mail_cpu ~0%). Precondition satisfied.

## Task 3: Card 4 scratch-mailbox verification, device dry-run identity, merge (GATE-09 / GATE-13)

### Rebase and verify triple

The card-4 lane (`.worktrees/gate-card-4-recoverable-preflight`, PR #215) was 15 commits behind `origin/develop`. Rebased cleanly (no conflicts), re-ran the triple, and pushed:

```
uv run pytest -q          -> 1438 passed, 80 deselected in 14.07s
uv run ruff check .       -> All checks passed!
uv run ruff format --check . -> 138 files already formatted

git push --force-with-lease  -> 9cc4fe5...67a401c (forced update, ok)
gh pr checks --watch --required -> check: pass (45s)
```

### (a) Real round trip on the scratch mailbox

```
uv run pytest -m integration -k "move_mail_dry_run or move_then_undo" -v
```

```
collected 1518 items / 1516 deselected / 2 selected

tests/test_integration.py::test_move_mail_dry_run_reads_mail_and_moves_nothing PASSED [ 50%]
tests/test_integration.py::test_move_then_undo_returns_every_message_to_its_source PASSED [100%]

2 passed, 1516 deselected in 19.18s
```

**Independent read-back** (not the test's own return value — a fresh `MailAdapter()` call against real Mail, after the test run completed):

```
scratch mailbox: imap://02B406D0-99D4-4E9A-9A7C-0DB912FD1D93/macos-apps-mcp-test
inbox folder:    imap://BDA93031-756E-4487-BEDD-F2768006926A/INBOX

reconstructed test ids (top-2 of the same deterministic INBOX):
  ['<17b7f489636173f49fed83c9ab699d76@forum.questionablequesting.com>',
   '<6ab67a2ced449_1dfbafdc097f6@ao3-app26.mail>']

presence of these ids in their source folder (dry-run read, no write):
  [('17b7f489636173f49fed83c9ab699d76@forum.questionablequesting.com', 'present'),
   ('6ab67a2ced449_1dfbafdc097f6@ao3-app26.mail', 'present')]

scratch mailbox holds (should be empty): []
```

Every round-tripped id is back in its source mailbox; `macos-apps-mcp-test` holds none of them. GATE-09's scratch-mailbox verification passes.

### (b) Device dry-run identity

Wrote a scratch script outside the repo (`scratchpad/dry_run_identity_probe.py`) that installs a recording pass-through directly on the `runtime.run_osascript` module attribute — records each call's script identity (matched against that process's own `mail._PRESENT`/`_MOVE`/`_TRASH`/`_DEDUPE` by object identity), args and kwargs, then calls the REAL `run_osascript` (so the actual `_PRESENT` presence read still happens against live Mail; move/trash/dedupe's `act()` branches are never reached on a dry run). Ran two real INBOX message ids and the scratch mailbox through `move_mail(..., dry_run=True)`, `trash_mail(..., dry_run=True)` and `dedupe_batch(..., dry_run=True)`, once per tree:

```
uv run --project .worktrees/baseline-v0.11.0 python <script>              # v0.11.0, pre-cut
uv run --project .worktrees/gate-card-4-recoverable-preflight python <script>  # card-4, rebased
```

**Diff (baseline -> card-4):**

```diff
<     "status": "planned"
---
>     "status": "present"
<     "status": "planned"
---
>     "status": "present"
<  "dedupe_dry_calls": [],
---
>  "dedupe_dry_calls": [
>   {
>    "args": [
>     "BDA93031-756E-4487-BEDD-F2768006926A",
>     "INBOX",
>     "17b7f489636173f49fed83c9ab699d76@forum.questionablequesting.com\u001f6ab67a2ced449_1dfbafdc097f6@ao3-app26.mail"
>    ],
>    "kwargs": {},
>    "script": "_PRESENT"
>   }
>  ],
```

`move_dry` / `move_dry_calls` and `trash_dry` / `trash_dry_calls` show **no diff at all** — byte-identical between the v0.11.0 baseline and the card-4 tree, both envelope and osascript argv. `dedupe_dry` differs **only** by the added `_PRESENT` call and the two statuses it produced (`"planned"` -> `"present"`), exactly the GATE-09 fix card 4 makes. No message was moved by either run (dry runs only ever reach the `_PRESENT` branch). Acceptance criterion satisfied exactly as specified.

### Merge

Both (a) and (b) passed, so the merge proceeded:

```
gh pr view 215 -> state=OPEN, mergeStateStatus=CLEAN, mergeable=MERGEABLE
statusCheckRollup: check / SUCCESS (completed 2026-09-25T14:35:22Z)

gh pr merge 215 --rebase --delete-branch
gh pr view 215 -> state=MERGED, mergedAt=2026-09-25T14:39:28Z, mergeCommit=799355c44fe4691159f8efc95b9a4e24ddbf9f52
git log --oneline -1 origin/develop -> 799355c fix(01-05): recoverable() docstring/error no longer suggests an unusable present=None opt-out
```

### Cleanup (from the main checkout only)

```
git worktree unlock .worktrees/gate-card-4-recoverable-preflight   -> ok
git worktree remove .worktrees/gate-card-4-recoverable-preflight   -> ok
git branch -D refactor/gate-card-4-recoverable-preflight           -> ok (deleted)
git worktree remove .worktrees/baseline-v0.11.0                    -> ok
git fetch -q --prune origin                                       -> ok
```

`git worktree list` afterwards confirms both worktrees are gone; `git branch --list refactor/gate-card-4-recoverable-preflight` returns nothing.

### Vault journal

Landed via `vault-journal` (MR !811, merged): one bullet at 16:40 covering both the card 4 merge (PR #215, 799355c, GATE-09) and card 7's device proof (GATE-02, 7/7 green on `origin/develop@26550d3`, no leftovers).

## Files Created/Modified

None in the repo. One scratch file outside the repo: `scratchpad/dry_run_identity_probe.py` (session scratchpad, not committed — per plan instruction, lives outside the repo).

## Decisions Made

See `key-decisions` in the frontmatter: the pre-recorded Task 2 selector correction, the `rtk` proxy filtering note, and the per-process identity-map construction in the Task 3(b) script.

## Issues Encountered

None beyond the two items logged under "Deviations from Plan" above (a pre-recorded selector fix and a local tooling-output artifact, neither a real problem).

## Authentication Gates

None. TCC access for Calendar/Reminders was already granted from prior integration runs; no prompt appeared this session.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- **GATE-02's device proof is done.** Card 7's EventKit runtime split is proven on real EventKit/TCC.
- **GATE-09's device verification (success criterion 5's device clause) is done.** Card 4's `recoverable()` plane is proven on the real scratch mailbox, with the watchdog running, plus a device dry-run identity check against the v0.11.0 baseline.
- **PR #215 is MERGED** (799355c) — card 4 is landed on `origin/develop`.
- Both worktrees this plan used (`.worktrees/gate-card-4-recoverable-preflight`, `.worktrees/baseline-v0.11.0`) and the lane branch (`refactor/gate-card-4-recoverable-preflight`) are gone.
- Per this plan's main-checkout rules, `STATE.md`/`ROADMAP.md`/`REQUIREMENTS.md`/`HANDOFF.json` are untouched here — the orchestrator ticks GATE-02 and GATE-09 and advances the phase position. This SUMMARY is left **uncommitted** in the main checkout, per instruction.
- No blockers for plan 01-09 (card 5) or the rest of the phase — this plan touched no shared files.

## Self-Check: PASSED

- `.planning/phases/01-gate-land-the-spiked-architecture-cuts/01-08-SUMMARY.md`: FOUND (this file).
- Merge commit `799355c44fe4691159f8efc95b9a4e24ddbf9f52`: FOUND in `git log --oneline -1 origin/develop`.
- `git worktree list` (re-run after cleanup): confirms `.worktrees/gate-card-4-recoverable-preflight` and `.worktrees/baseline-v0.11.0` are both absent.
- `git branch --list refactor/gate-card-4-recoverable-preflight`: empty (branch deleted).
- Watchdog + Mail-running precondition output pasted above, captured immediately before Task 3 as required.
- Both acceptance-criteria read-backs (Task 2 leftover check, Task 3(a) round-trip read-back) re-shown above with their actual command output, not narrated.

---
*Phase: 01-gate-land-the-spiked-architecture-cuts*
*Completed: 2026-09-25*
