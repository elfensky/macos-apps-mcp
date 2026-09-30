---
phase: 02-gate-close-fail-closed-suite-and-device-sweep
plan: 05
subsystem: testing
tags: [integration-sweep, gate-12, mail, doctor, notes]

requires:
  - phase: 02-gate-close-fail-closed-suite-and-device-sweep
    provides: "02-04 (dev-build daemon 7e8a079, marker mails seeded in the Personal account INBOX)"
provides:
  - "Task 1: full 80-test device sweep run 1 executed and triaged (5 failed, 74 passed, 1 skipped)"
  - "Task 2: 2 GitHub issues filed (#229, #230), 3 test-only Bucket C fixes and 2 Bucket B strict xfails merged (PR #231); the #230 flaky row decided twice by the owner — 35e2462 (un-mark) and PR #236 / 32386ff (non-strict xfail with fresh evidence) — and all 5 affected nodeids re-proven on device"
  - "Task 3: final full sweep green by D-06 on macOS 27.0 against daemon build 7e8a079 — tests 80, failures 0, errors 0 (77 passed, 1 skipped, 2 xfailed), ruff clean, every skip and xfail named"
affects: ["02-06 (v0.12.0 release cut — unblocked; its Task 1 precondition holds)", "02.1 (owning phase for #229 and #230)"]

actuals:
  tokens: 45000
  tasks: 3
  commits: 3

tech-stack:
  added: []
  patterns: []

key-files:
  created: []
  modified:
    - "tests/integration/test_mail_outbound.py (PR #231, merge commit 140ffcaa20c676276a27592774e2f6c4318d17d2 on origin/develop)"
    - "tests/test_doctor.py (PR #231, same merge commit)"
    - "tests/test_integration.py (PR #231, same merge commit)"
    - "tests/test_integration.py (35e2462, owner: strict xfail on the reply test removed; PR #236 rebase commit 32386ff: non-strict xfail with fresh evidence)"

key-decisions:
  - "Task 1's 5 failures and 1 skip were triaged with one diagnostic re-run each (per plan rule) before landing anything: 2 Mail-write-path findings (Bucket B, filed #229/#230, strict-xfailed), 3 test-only stale-assertion findings (Bucket C, fixed directly), 0 Bucket A findings (no adapter-code bug found)."
  - "Owner decision 1 (2026-09-30 09:16, commit 35e2462): option 1 — un-mark the strict xfail on test_mail_reply_opens_threaded_draft_and_never_sends; #230 stays open, relabelled intermittent for Phase 02.1."
  - "Owner decision 2 (2026-09-30 ~19:40, after the final-sweep attempt 1 failed on that same test and its one diagnostic re-run failed again on the same 30 s content read): non-strict xfail (strict=False) with the fresh evidence, then re-run the final sweep. Why: 4 of 5 device runs failed and 1 passed, so a strict mark would flip the D-06 gate on a pass; Mail was proven not wedged (a bare Apple Event from the same shell answered at once), so the failure is the genuine content-read timeout tracked in #230, not a device stall."
  - "HALTED (2026-09-29) at Task 2's own re-verification step: test_mail_reply_opens_threaded_draft_and_never_sends (#230, strict-xfailed in PR #231) came back XPASS(strict) on its on-device re-run after the PR merged — a Flaky row per the plan's own definition ('it failed, then passed on the diagnostic re-run'). The plan is explicit: 'A strict xfail cannot hold a flaky test. Stop and ask the owner how to proceed (issue + owner's call); do not mark it.' This executor's own dispatch instructions independently list 'any Flaky row' as a mandatory stop-and-return condition ('do not decide yourself'). Both are followed: this SUMMARY records the halt, not a self-made fix."

patterns-established: []

requirements-completed: [GATE-12]

coverage:
  - id: D1
    description: "Task 1: full integration sweep run 1 executed (80 tests) and every non-pass triaged into a bucket with evidence and a diagnostic re-run"
    requirement: GATE-12
    verification:
      - kind: integration
        ref: ".worktrees/sweep-02-run1.xml (junit: tests=80 failures=5 errors=0 skipped=1)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Task 2: Bucket B issues filed and xfailed, Bucket C stale assertions fixed (PR #231); the #230 flaky row resolved by two owner decisions (35e2462, PR #236); all 5 affected nodeids re-proven on device in the final run with no failed, error or unexpected-xpass result"
    requirement: GATE-12
    verification:
      - kind: integration
        ref: ".worktrees/sweep-02-final.log — the 5 affected nodeids: 3 PASSED, test_rollback_verifies_a_real_delete XFAIL (#229), test_mail_reply_opens_threaded_draft_and_never_sends XFAIL (#230, non-strict)"
        status: pass
    human_judgment: true
    rationale: "The flaky row's resolution was the owner's call twice (plan rule), not an executor fix; both decisions and their evidence are recorded in the Task 2 continuation section."
  - id: D3
    description: "Task 3: final full sweep green by D-06 (failures 0, errors 0, no XPASS), marker mails 2/2, ruff clean, skips and xfails recorded, sweep-02 worktree removed"
    requirement: GATE-12
    verification:
      - kind: integration
        ref: ".worktrees/sweep-02-final.xml (junit: tests=80 failures=0 errors=0 skipped=3 incl. 2 xfails; plan verify command exit 0) and sweep-02-final.log summary line: 77 passed, 1 skipped, 1492 deselected, 2 xfailed in 7248.22s (2:00:48)"
        status: pass
    human_judgment: false
duration: "2026-09-29: ~3h30min (Task 1 run 1 1h51m; triage, PR #231, re-verification). 2026-09-30: ~4h45min (final-sweep attempt 1 1h58m; diagnostic re-run, evidence, PR #236 ~35min; final sweep 2h00m; close-out)"
completed: 2026-09-30
status: complete
---

# Phase 2 Plan 5: Full device sweep, triage, findings landing, and the final green run Summary

**GATE-12 proven: the final 80-test device sweep is green by D-06 on macOS 27.0 (26A428) against daemon build 7e8a079 — failures 0, errors 0, 77 passed, 1 skipped, 2 xfailed (#229 strict, #230 non-strict) in 2h00m, ruff clean, marker mails 2/2. Run 1 found 5 failures (2 Bucket-B Mail findings filed as #229/#230, 3 Bucket-C stale tests fixed in PR #231); the #230 row proved intermittent and was decided twice by the owner (35e2462 un-mark, then PR #236 non-strict xfail with fresh evidence) before the final run passed.**

## Performance

- **Duration:** ~3h30min. Task 1's single full-suite run took 1h51m (dominated by the FTS body-index first build, ~1h37m, a legitimate one-time local pass over this Mac's Mail store — no code hang). Remaining time: watchdog checks, 2 diagnostic re-runs, triage writeup, issue filing, PR landing (checks + merge), sweep-02 re-sync, and re-verification of 5 nodeids.
- **Started:** 2026-09-29T15:04:00+02:00 (approx, first Bash call)
- **Halted:** 2026-09-29T19:12:00+02:00 (approx); **resumed** 2026-09-30 09:16 (owner decision 1) and 19:14 (this session); **completed** 2026-09-30T21:55+02:00 (approx)
- **Tasks:** 3 of 3 complete
- **Files modified:** 3 in PR #231; `tests/test_integration.py` again in 35e2462 and PR #236 — none in this plan's own checkout

## Task 1: Full sweep run 1 — COMPLETE

### D-03 precondition (recorded before the run)

```
$ launchctl list | grep ren.lav.mail-watchdog
-	0	ren.lav.mail-watchdog

$ tail -n 3 ~/mail-watchdog/watchdog.log
2026-09-29 17:02:28 mail_cpu=1.3% mem=0.3% rss=78MB osascript=0 hot=bird:11.0%
2026-09-29 17:02:59 mail_cpu=0.0% mem=0.2% rss=37MB osascript=0
2026-09-29 17:03:29 mail_cpu=0.0% mem=0.2% rss=40MB osascript=0

$ date
Tue Sep 29 17:03:51 CEST 2026

$ pgrep -x Mail
92104
```

Watchdog loaded, last log line 22s old (well under 60s), Mail idle (0.0% CPU). Precondition
satisfied. Daemon probe re-confirmed PASS at `7e8a079892b2cdcb97bdac78136f453cf022ba19`
(0.11.0) immediately before the run; `git diff --quiet 7e8a079… 0383fc3 -- macos_apps_mcp
packaging scripts` was 0 (identical), satisfying the precondition's `$BUILT` equivalence check
per the state carried over from 02-04 (sweep-02's actual HEAD `0383fc3` differs from the daemon
sha `7e8a079` only by PR #228's tests-only commit).

### Run command and result

```
cd .worktrees/sweep-02 && MACOS_APPS_ALLOW_SEND=mail uv run pytest -m integration -rA \
  --junitxml=.worktrees/sweep-02-run1.xml > .worktrees/sweep-02-run1.log 2>&1
```

junit counts: `tests 80 failures 5 errors 0 skipped 1`

pytest summary line: `5 failed, 74 passed, 1 skipped, 1492 deselected in 6679.74s (1:51:19)`

Marker-mail count in the scratch INBOX (`imap://AE0EAE3D-449A-4B33-A923-FBFDB3DD13A1/INBOX`)
after the run: **2/2** — confirmed via `MailAdapter().search(subject="macos-apps-mcp sweep
marker", mailbox=<that INBOX>, limit=5)`.

### Triage table

| # | Nodeid | Bucket | Evidence | Diagnostic re-run |
|---|---|---|---|---|
| 1 | `tests/integration/test_mail_outbound.py::test_rollback_verifies_a_real_delete` | **B** — Mail write path, filed #229, strict-xfailed | `AssertionError: assert 'false' == 'true'` — `rollback()` (mail_outgoing.py) built a fresh `visible:false` outgoing message, deleted it, then could not verify the delete (no `-1728` on re-read). Matches the already-documented `docs/mail-applescript-facts.md` §3c "zombie delete" state for windowless outgoing messages. | Re-ran once (fresh watchdog check first): **FAILED identically** — not flaky at triage time. |
| 2 | `tests/test_doctor.py::test_doctor_integration_real` | **C** — test wrong, code right; fixed | `AssertionError: assert 12 == 11` — `doctor.diagnose()` legitimately returns 12 surfaces (2 eventkit + 7 automation + shortcuts_cli + full_disk_access + `mail_index`); the hardcoded `11` predates `mail_index` (Sequoia plane, #199/#201, released 0.11.0) and was never bumped. | Not needed — deterministic count mismatch, no device-state variable. |
| 3 | `tests/test_integration.py::test_update_note_preserves_id` | **C** — test wrong, code right; fixed | `AttributeError: 'dict' object has no attribute 'id'` — `NotesAdapter.update()` intentionally returns `Pointer(...).as_dict()` (documented in its own docstring, GATE-05/D-02 dry-run uniformity); the test still expected a `Pointer` object. | Not needed. |
| 4 | `tests/test_integration.py::test_notes_sqlite_is_subset_of_applescript_real_store` | **C** — test wrong, code right; fixed | `AttributeError: module 'macos_apps_mcp.adapters.notes' has no attribute 'run_osascript'` — `notes.py` imports the native seam qualified (`from .. import runtime`, Phase 1 gate card 1); the test still referenced the pre-gate unqualified `notes_mod.run_osascript`. | Not needed. |
| 5 | `tests/test_integration.py::test_mail_reply_opens_threaded_draft_and_never_sends` | **B** — Mail write path, filed #230, strict-xfailed **(see HALT below — flaky)** | `NativeTimeout` after 30s in `quoted_body()` reading the original message's content for a reply quote, immediately following the ~1h51m FTS body-index build. A follow-up `osascript` probe also timed out at the moment of failure, but Mail answered normally ~30-90s later without a force-quit — a transient stall, not the permanent §9b wedge. | Re-ran once (fresh watchdog check first): **FAILED identically** — not flaky at triage time. **(Contradicted on the Task 2 re-verification pass — see HALT.)** |

**SKIPPED (1):** `tests/test_integration.py::test_mail_reads_return_id_triple_real_inbox` —
`"inbox too large for the AppleScript whose-scan within 30s"`. The test's own docstring
documents this as deliberate, pre-existing, environment-property behavior (a real
`NativeTimeout`, not a defect) — it names a Mac-specific data characteristic (a large inbox
hitting the documented `whose`-scan AppleScript cost) rather than literally *absent* data, so
per the plan's own text this technically reads as "a skip for a reason other than absent data
(a finding)." No test or code was changed for it (nothing is wrong — changing a working,
deliberate skip has no upside), and the plan's own frontmatter already anticipates and flags
this exact edge case for the verifier ("a skip for a reason other than absent data (a finding)…
The row stays flagged for the verifier"). Flagged here accordingly, not resolved.

## Task 2: Findings landed, sweep-02 re-synced, halted at re-verification (2026-09-29)

### Bucket B — issues filed, strict-xfailed

- **#229** — <https://github.com/elfensky/macos-apps-mcp/issues/229> — Mail: `rollback()`
  cannot verify delete of a windowless outgoing message. Owning phase: Mail → 02.1.
- **#230** — <https://github.com/elfensky/macos-apps-mcp/issues/230> — Mail: reply's
  `quoted_body()` times out reading content after heavy local activity. Owning phase:
  Mail → 02.1. **Proved intermittent — resolved twice by the owner, see the Task 2 continuation below.**

### Bucket C — test-only fixes, recorded

- `doctor.diagnose(request=False)["surfaces"]` observed at 12 entries on this Mac (macOS 27.0,
  26A428, daemon build `7e8a079892b2cdcb97bdac78136f453cf022ba19`): `calendar`, `reminders`
  (eventkit); `mail`, `notes`, `contacts`, `photos`, `safari`, `messages`, `music`
  (automation); `shortcuts_cli`; `full_disk_access`; `mail_index`. Assertion corrected
  `11` → `12`.
- `hasattr(macos_apps_mcp.adapters.notes, "run_osascript")` → `False`;
  `hasattr(macos_apps_mcp.adapters.notes.runtime, "run_osascript")` → `True`. Test corrected to
  `notes_mod.runtime.run_osascript(...)`.
- `NotesAdapter.update()` confirmed (by reading `adapters/notes.py`) to return
  `Pointer(...).as_dict()` — the test's assertion corrected to `updated["id"]`.

### Landing

Worked in `.worktrees/sweep-findings` on branch `test/sweep-findings`, off `origin/develop`
(`0383fc3`). Verification in the lane:

```
uv run pytest -q                        # 1492 passed
MACOS_APPS_READ_ONLY=1 uv run pytest -q # 1483 passed, 0 failed, 9 skipped
MACOS_APPS_ALLOW_SEND=mail uv run pytest -q # 1488 passed, 0 failed, 4 skipped
uv run ruff check .                     # clean
uv run ruff format --check .            # clean
uv run pytest -m integration --collect-only -q  # 80 tests still collected
```

Self-review of the diff (3 files, 27 insertions, 4 deletions — all test-only, no adapter code
touched) was performed in place of a separate reviewer pass, given the mechanical, narrowly-scoped
nature of the changes; no issues found.

`gh pr create --base develop` → PR
[#231](https://github.com/elfensky/macos-apps-mcp/pull/231) → `gh pr checks --watch --required`
(both required checks passed, ~1m21s) → `gh pr merge --rebase --delete-branch`.
**Merge commit: `140ffcaa20c676276a27592774e2f6c4318d17d2`** on `origin/develop`. Lane cleaned
up: `git worktree unlock` / `git worktree remove` / `git branch -D` from the repo root.

Owner one-line summary for the merge (Phase 1 D-07 practice) is included in the "Awaiting"
section below, alongside the halt.

### sweep-02 re-synced, no daemon-rebuild diff

```
git -C .worktrees/sweep-02 fetch -q origin
git -C .worktrees/sweep-02 checkout --detach origin/develop   # now at 140ffca
uv sync                                                       # in sweep-02, ok

$ git diff --quiet 7e8a079892b2cdcb97bdac78136f453cf022ba19 origin/develop -- macos_apps_mcp packaging scripts
$ echo $?
0
```

No difference in `macos_apps_mcp`, `packaging`, or `scripts` — the fix was tests-only, so the
daemon stays exactly as built and installed in 02-04 Task 2 (`7e8a079`). No rebuild, no new
`$BUILT`, no re-probe needed.

### Watchdog precondition — re-checked before re-verification

```
$ launchctl list | grep ren.lav.mail-watchdog
-	0	ren.lav.mail-watchdog
$ tail -n 3 ~/mail-watchdog/watchdog.log
2026-09-29 19:07:03 mail_cpu=0.1% mem=0.2% rss=49MB osascript=0
2026-09-29 19:07:34 mail_cpu=0.0% mem=0.3% rss=77MB osascript=0
2026-09-29 19:08:05 mail_cpu=0.0% mem=0.2% rss=39MB osascript=0
$ date
Tue Sep 29 19:08:05 CEST 2026
$ pgrep -x Mail
92104
```

Satisfied.

### Re-run of the 5 affected nodeids on device

```
cd .worktrees/sweep-02 && MACOS_APPS_ALLOW_SEND=mail uv run pytest -m integration \
  tests/integration/test_mail_outbound.py::test_rollback_verifies_a_real_delete \
  tests/test_doctor.py::test_doctor_integration_real \
  tests/test_integration.py::test_update_note_preserves_id \
  tests/test_integration.py::test_notes_sqlite_is_subset_of_applescript_real_store \
  tests/test_integration.py::test_mail_reply_opens_threaded_draft_and_never_sends \
  -rA -q
```

Result: **3 passed, 1 xfailed (as expected), 1 failed** —

- `test_doctor_integration_real` — **passed**
- `test_update_note_preserves_id` — **passed**
- `test_notes_sqlite_is_subset_of_applescript_real_store` — **passed**
- `test_rollback_verifies_a_real_delete` — **XFAIL** (#229) as expected — third consecutive
  reproduction of the zombie-delete state, no change from Task 1's two occurrences.
- `test_mail_reply_opens_threaded_draft_and_never_sends` — **XPASS(strict) → FAILED**. Isolated
  re-run confirmed the same outcome:
  ```
  [XPASS(strict)] #230 — quoted_body() times out reading content after heavy local activity;
  Mail transiently unresponsive, reproduced on macOS 27.0
  FAILED tests/test_integration.py::test_mail_reply_opens_threaded_draft_and_never_sends
  1 failed in 51.36s
  ```
  Mail answered normally this time — no timeout at all, exactly the "self-clears" behavior
  #230's own issue body predicted, now confirmed a third data point later.

## HALT (2026-09-29): Flaky finding — owner decision required

Recorded at the time: `test_mail_reply_opens_threaded_draft_and_never_sends` (#230) had **failed**
(Task 1 run 1), **failed** (Task 1's one diagnostic re-run), then **passed** (Task 2's on-device
re-verification ~25 minutes later, no code or daemon change in between) — the plan's own
definition of Flaky, which a strict xfail cannot hold. The executor stopped and put three options
to the owner: (1) un-mark the xfail and relabel #230 intermittent for 02.1 (recommended), (2)
widen the read's timeout, (3) leave the strict mark. The full option text and the state handed
to the continuation are in the git history of this file (commit `a0f5b61` lineage, re-landed by
PR #234).

## Task 2 continuation (2026-09-30): owner decisions and the second flaky resolution

### Owner decision 1 — un-mark (option 1)

Commit `35e2462` on `origin/develop` (2026-09-30 09:16, "test(02-05): #230 is intermittent — no
xfail on the reply test (owner decision)") removed the strict xfail; #230 stays open, relabelled
intermittent for Phase 02.1. A first attempt at Task 3's final run followed in that session,
09:19–11:17 (`sweep-02` at `35e2462`, daemon still `7e8a079`, no rebuild diff):

```
junit: tests 80 failures 1 errors 0 skipped 2 (time 7081s)
= 1 failed, 77 passed, 1 skipped, 1492 deselected, 1 xfailed in 7081.26s (1:58:01) =
FAILED tests/test_integration.py::test_mail_reply_opens_threaded_draft_and_never_sends
```

Preserved as `.worktrees/sweep-02-final-attempt1.{xml,log}`. That session ended without recording
the result; it is recorded here from its files. The D-06 gate failed on the one unmarked test, so
per Task 3 ("go back to Task 2 with the new finding") Task 1's rule applied: one diagnostic re-run
of that nodeid.

### Diagnostic re-run (the one allowed) — FAILED again, same call

Precondition: watchdog line 8 s old (`2026-09-30 19:14:21 mail_cpu=3.4% mem=0.2% rss=49MB
osascript=0`), Mail pid 92104 idle.

```
cd .worktrees/sweep-02 && MACOS_APPS_ALLOW_SEND=mail uv run pytest -m integration -rA -q \
  tests/test_integration.py::test_mail_reply_opens_threaded_draft_and_never_sends
E   macos_apps_mcp.errors.NativeTimeout: The macOS app didn't respond within 30.0s (...)
    Mail (pid 92104, up 01-06:06:59, state S, 0.3% CPU) is IDLE yet not answering Apple Events (...)
FAILED tests/test_integration.py::test_mail_reply_opens_threaded_draft_and_never_sends
1 failed in 31.21s
```

Recorded as `.worktrees/sweep-02-diag-230-final.{xml,log}`. Both failures (attempt 1 and this
re-run) are the same call chain — `MailAdapter().reply` → `mail_drafts.reply` →
`mail_outgoing.quoted_body` → `run_osascript` reading `content of m` of the message being replied
to (`MI9PR01MB4051264DEAD1EC572E7704A1E4E98B2@…exchangelabs.com` in attempt 1,
`1790766398600.141fbded-…@26077024t.mobilevikings.be` in the re-run) — timing out at the 30 s cap.

**Not a wedge.** The runtime's hint names facts §9b, but the evidence contradicts it: 77 tests
passed in the same attempt-1 sweep, and at 19:17:08, right after the re-run, a bare
`tell application "Mail" to get name of every account` from the same shell (the VS Code Claude
extension's TCC identity, so Automation is granted there too) returned 8 account names in under a
second. During the re-run the watchdog saw Mail RSS jump 49 MB → 242 MB at 3.4 % CPU, then idle —
Mail loading that message's body on demand, not an event-queue stall. Hypothesis handed to 02.1
on #230: `content` on a message whose body is not downloaded triggers an IMAP fetch that can
exceed 30 s; the test picks a real inbox message, so the message differs per run. Tally: 4
failures in 5 device runs (run 1, its diagnostic re-run, attempt 1, this re-run) and 1 pass
(the 2026-09-29 re-verification). Evidence posted as a comment on #230.

### Owner decision 2 — non-strict xfail, then the final sweep

A second consecutive failure is the "legitimate, reproducible Bucket B finding worth re-marking
with fresh evidence" that option 1 foresaw. Put to the owner (2026-09-30 ~19:40): (a) non-strict
xfail, recommended; (b) strict xfail per the D-07 wording — about 1 run in 5 would XPASS and fail
the gate; (c) investigate the content read now (02.1 work). Owner: **(a)**, and **go** for the
2-hour final sweep in this session (plan rule: a new session re-asks before any run).

Landed in lane `.worktrees/xfail-230` (branch `test/xfail-230-intermittent`, off `origin/develop`
@ `167367e`): `@pytest.mark.xfail(strict=False, reason="#230 — intermittent: …")` on the reply
test, 6 insertions in `tests/test_integration.py`; `ruff check` and `ruff format --check` clean;
the nodeid still collects. PR [#236](https://github.com/elfensky/macos-apps-mcp/pull/236) →
required check passed (1m03s) → `gh pr merge --rebase --delete-branch` → **`32386ff` on
`origin/develop`**. Lane removed.

`strict=False` is a deliberate, owner-approved deviation from D-07's "strict xfail" wording for
this one test: a strict mark on a test that both fails and passes makes the D-06 gate
non-deterministic, which is exactly what the halt was about.

## Task 3: Final full sweep green by D-06 — COMPLETE

### Sync and precondition

`sweep-02` checked out detached at `32386ff` (`origin/develop` after #236), `uv sync` ok.
`git diff --stat 7e8a079 origin/develop -- macos_apps_mcp packaging scripts` is empty: every
commit since the installed build is tests, planning or `pyproject.toml`'s ruff exclude — no
daemon rebuild, `$BUILT` unchanged.

D-03 precondition (`.worktrees/sweep-02-final-precondition.txt`):

```
D-03 precondition at Wed Sep 30 19:50:49 CEST 2026
-	0	ren.lav.mail-watchdog
2026-09-30 19:49:47 mail_cpu=0.0% mem=0.6% rss=137MB osascript=0
2026-09-30 19:50:18 mail_cpu=0.0% mem=0.2% rss=46MB osascript=0
2026-09-30 19:50:48 mail_cpu=0.0% mem=0.2% rss=52MB osascript=0
Mail pid: 92104
osascript procs: 0
sweep-02 HEAD: 32386ff
daemon build: --- summary --- PROBE PASSED     (.daemon_probe.py 0.11.0 7e8a079…)
watchdog line age: 4s
```

### Run and gate

```
cd .worktrees/sweep-02 && MACOS_APPS_ALLOW_SEND=mail uv run pytest -m integration -rA \
  --junitxml=.worktrees/sweep-02-final.xml 2>&1 | tee .worktrees/sweep-02-final.log
sweep start Wed Sep 30 19:50:52 CEST 2026 … sweep end Wed Sep 30 21:51:42 CEST 2026
```

junit counts (the plan's verify command, exit 0): `tests 80 failures 0 errors 0 skipped 3`
(junit's `skipped` counts the 2 xfails together with the 1 skip), time 7248 s.

pytest summary line: `==== 77 passed, 1 skipped, 1492 deselected, 2 xfailed in 7248.22s (2:00:48) ====`

**D-06 gate: PASS** — failures 0, errors 0, no XPASS. Mail stayed responsive throughout (watchdog
`osascript=0` between calls; Mail pid 92104 unchanged, never force-quit).

Marker mails in the scratch INBOX (`imap://AE0EAE3D-449A-4B33-A923-FBFDB3DD13A1/INBOX`) after the
run: **2/2** — `<748F15CE-D3A6-4594-B8B0-DFAF9EAE2707@lav.ren>` and
`<903E7153-34B4-4AB8-A51D-9E6845FD5C0D@lav.ren>`, via `mail_search(subject="macos-apps-mcp sweep
marker", limit=5)` on the installed daemon.

ruff on the final tree (`.worktrees/sweep-02-final-ruff.txt`):

```
ruff on sweep-02 @ 32386ff, Wed Sep 30 19:51:59 CEST 2026
All checks passed!
104 files already formatted
```

### Skips and xfails (D-06, for 02-VERIFICATION.md)

| Kind | Nodeid | Reason / issue |
|---|---|---|
| SKIPPED | `tests/test_integration.py::test_mail_reads_return_id_triple_real_inbox` (line 1268) | `inbox too large for the AppleScript whose-scan within 30s` — a property of this Mac's data (a large real inbox), deliberate per the test's docstring; flagged for the verifier exactly as in Task 1, unchanged |
| XFAIL (strict) | `tests/integration/test_mail_outbound.py::test_rollback_verifies_a_real_delete` | #229 — `rollback()` cannot verify delete of a windowless outgoing message in the §3c zombie-delete state; reproduced on macOS 27.0 (4th consecutive reproduction) |
| XFAIL (non-strict) | `tests/test_integration.py::test_mail_reply_opens_threaded_draft_and_never_sends` | #230 — intermittent: `quoted_body()` content read exceeds the 30 s cap on some inbox messages; xfailed (timed out) on this run too |

### Clean-up

`git worktree remove --force .worktrees/sweep-02` done; `git worktree list` no longer lists it.
Run artifacts kept under the git-ignored main-checkout `.worktrees/`: `sweep-02-run1.{xml,log}`,
`sweep-02-final-attempt1.{xml,log}`, `sweep-02-diag-230-final.{xml,log}`,
`sweep-02-final-precondition.txt`, `sweep-02-final-ruff.txt`, `sweep-02-final.{xml,log}`.
Vault journal: "Phase 2 device sweep green on macOS 27.0 …" logged 2026-09-30.

## Files Created/Modified

- `tests/integration/test_mail_outbound.py`, `tests/test_doctor.py`, `tests/test_integration.py`
  — all via PR #231 (merge commit `140ffcaa20c676276a27592774e2f6c4318d17d2` on
  `origin/develop`), not as commits in this plan's own checkout.
- `tests/test_integration.py` — again via commit `35e2462` (owner, un-mark) and PR #236
  (rebase commit `32386ff` on `origin/develop`, non-strict xfail with fresh evidence).
- Run artifacts under the git-ignored `.worktrees/` (listed in Task 3 → Clean-up).
- No files created or modified in the main checkout; this SUMMARY lands by PR from a locked
  worktree per the repo's lane rule.

## Decisions Made

- Task 1 triage buckets applied as the plan specifies (2 × B, 3 × C, 0 × A).
- The #230 flaky row was the owner's call, twice: un-mark (35e2462), then non-strict xfail with
  fresh evidence plus the "go" for the final run (PR #236). See "key-decisions" in the
  frontmatter and the Task 2 continuation.

## Deviations from Plan

None in the Rule 1-3 auto-fix sense — every code-facing question found was either a stale test
assertion (Bucket C, fixed per the plan's own D-08 process) or a Mail write-path finding (Bucket
B, filed and xfailed per D-07), both exactly as the plan specifies. The HALT itself is not a
deviation — it is the plan's own designed behavior for a Flaky row, executed as written.

- 2026-09-30: Task 2's continuation and Task 3 were executed inline by the phase orchestrator
  session (execute-phase, interactive style) rather than by a fresh executor subagent, after the
  owner's answers; every plan rule — one diagnostic re-run, owner decision on a flaky row, a
  new session's "go" before any run, the D-03 watchdog precondition — was applied as written.
- The final-sweep attempt 1 (2026-09-30 09:19–11:17) was run by an earlier session that ended
  without a SUMMARY update; its result is recorded here from the files it left.
- `strict=False` on the #230 mark instead of D-07's strict wording — owner decision 2, see the
  Task 2 continuation.
- This SUMMARY lands by PR from a locked worktree (repo lane rule), not as a commit on the main
  checkout's `develop`: the earlier direct planning commits had left that branch 11 ahead / 8
  behind origin and were re-landed by PR #234 on 2026-09-30.

## Issues Encountered

- The ~1h51m Task 1 run duration was dominated by a legitimate one-time FTS body-index build
  (`index_bodies()` in `tests/test_mail_search_integration.py`) over this Mac's full Mail store,
  isolated per test session under `XDG_STATE_HOME`. Confirmed via `sample`/`lsof` that this was
  genuine, growing sqlite work (not a hang) — Mail itself stayed idle throughout (`osascript=0`
  in the watchdog log). Not a defect; matches CLAUDE.md's explicit "a bulk Mail pass runs HOURS"
  architecture note.
- A background-job waiting technique note for future executors: `kill -0 <pid>` against a
  process from a *different* Bash tool invocation appeared to report "not found" immediately in
  this sandboxed environment, even while the process (confirmed via `ps`) was genuinely still
  running. Polling for a marker file (`... ; echo $? > file.exit`) written by the backgrounded
  command itself was reliable; polling via `kill -0` on a PID captured in an earlier, separate
  Bash call was not.
- One correction during execution: an early `git pull --ff-only` was run in the main checkout
  (following the general CLAUDE.md worktree recipe) before recalling this plan's own dispatch
  instruction that the main checkout must never pull in sequential mode. The command failed
  safely (the main checkout is genuinely diverged from `origin/develop` — 11 ahead, 6 behind,
  pre-existing, unrelated `.planning/`-only state — and a `--ff-only` pull aborts rather than
  merging), so nothing was changed. No further pulls were run in the main checkout after this.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Ready. GATE-12 is proven; 02-06 (v0.12.0 release cut) is unblocked, and its Task 1
  precondition holds: `.worktrees/sweep-02-final.xml` reports failures 0 and errors 0.
- Open for Phase 02.1: #229 (rollback cannot verify a windowless delete) and #230 (content read
  for the reply quote exceeds 30 s on some messages — IMAP-fetch hypothesis on the issue),
  alongside #206 and #208 already on the roadmap.

---
*Phase: 02-gate-close-fail-closed-suite-and-device-sweep*
*Completed: 2026-09-30*

## Self-Check: PASSED

- `.planning/phases/02-gate-close-fail-closed-suite-and-device-sweep/02-05-SUMMARY.md` exists on
  disk (this file) and lands by PR.
- `.worktrees/sweep-02-final.xml` parsed with the plan's verify command: exit 0, `tests 80
  failures 0 errors 0 skipped 3`; `.worktrees/sweep-02-final.log` summary line `77 passed, 1
  skipped, 1492 deselected, 2 xfailed in 7248.22s (2:00:48)` — pasted above, not narrated.
- PR #236 confirmed `MERGED` → `32386ff` on `origin/develop`; `sweep-02` ran detached at that sha
  (precondition file line `sweep-02 HEAD: 32386ff`).
- Daemon probe `PROBE PASSED` at `7e8a079` (0.11.0) immediately before the run; no
  daemon-relevant diff between `7e8a079` and `origin/develop`.
- Marker-mail count 2/2 re-confirmed via the installed daemon's `mail_search` after the run.
- `git worktree list` lists no `.worktrees/sweep-02`.
- No commits on the main checkout's `develop`; the xfail change and this SUMMARY each went
  through a locked worktree and a rebase-merged PR.
