---
phase: 01-gate-land-the-spiked-architecture-cuts
plan: 09
subsystem: server-registration
tags: [tiers, notices, middleware, import-cycle, gate-03, gate-10, byte-identity, code-review, landing]

# Dependency graph
requires:
  - phase: 01-08
    provides: card 7 merged to origin/develop (PR #216, 8627aa8) — doctor.py's import block as this plan had to start from (`from .eventkit import request_access_each` / `from .runtime import app_process_info, run_native`), and the device proof clearing the way for this lane to cut from origin/develop
provides:
  - macos_apps_mcp/tiers.py — read_only()/allow_send(adapter), bodies byte-identical to server.py's former _read_only/_allow_send; a PROVISIONAL outbound ledger (_SEND_ADAPTERS, _SEND_REGISTERED, admit_send, outbound_status) that card 2 (plan 01-12) consolidates into registry.py and deletes from here
  - macos_apps_mcp/notices.py — UntrustedDataNotice middleware, UNTRUSTED_NOTICE, NO_NOTICE_TOOLS, _BACKUP_NOTICE_TOOLS, moved verbatim from server.py, sibling of audit.py (not folded in, to avoid an audit->mail_recover->audit cycle)
  - tests/test_import_layers.py — a general layering test (AST-based import-closure walk) pinning "nothing below server.py imports server.py", not just the one removed call site
  - doctor.py no longer imports server anywhere — the package's only import cycle is gone
affects: [Phase 1 plan 01-10 (dev-build daemon check, D-06), Phase 1 plan 01-12 (card 2 must delete tiers.py's provisional ledger once registry.py exists and repoint doctor's outbound read), Phase 1 plan 01-14 (final spike-branch/worktree cleanup)]

# Actuals (#2632)
actuals:
  tokens: 10395
  tasks: 3
  commits: 3
  plan_head_before: 799355c44fe4691159f8efc95b9a4e24ddbf9f52
confidence_note: "estimate was 80000 tokens (low confidence); actual realized diff for this plan's 3 commits was ~10395 (chars/4 over the develop..merge-commit diff, 41578 chars across 398 insertions/185 deletions in 12 files) — the estimate did not anticipate how mechanical the two moves were once the five test-file call sites were enumerated in the plan itself"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Tier policy lives in its own module (tiers.py), imported DOWN by server.py
      and doctor.py — neither of those two callers imports the other's module
      anymore. A gate predicate module has no business importing the thing it
      gates."
    - "A provisional ledger can live in a policy module before its permanent home
      exists, as long as the move is marked in both the module docstring and the
      plan record for the card that consolidates it — tiers.py's docstring names
      card 2 by number so an implementer three plans later isn't guessing."
    - "A middleware that would create an import cycle if folded into its closest
      analog gets a sibling module instead (notices.py next to audit.py) — the
      cycle test (test_import_layers.py) would have caught it immediately if
      this had been done wrong."
    - "The general form of an anti-cycle test (walk the whole import closure,
      assert no back-edge) outlives the specific bug it was written to catch —
      test_import_layers.py doesn't reference _outbound_state or doctor.py by
      name; it would catch ANY future module reaching back into server.py."

key-files:
  created:
    - macos_apps_mcp/tiers.py
    - macos_apps_mcp/notices.py
    - tests/test_import_layers.py
  modified:
    - macos_apps_mcp/server.py
    - macos_apps_mcp/doctor.py
    - macos_apps_mcp/daemon.py
    - macos_apps_mcp/deploy.py
    - tests/test_deploy.py
    - tests/test_doctor_deploy.py
    - tests/test_gate_on_dispatch.py
    - tests/test_server.py
    - tests/test_tool_annotations.py

key-decisions:
  - "Ledger ownership (RESEARCH Pitfall 3 / Assumption A2, decided at plan time and executed here as written): the outbound ledger moved into tiers.py PROVISIONALLY rather than staying split or waiting for registry.py — doctor.py had to stop importing server NOW, and registry.py doesn't exist until card 2 (plan 01-12). tiers.py's module docstring and the ledger block's own comment both name card 2 as the consolidation point."
  - "doctor.py's import-block edit started from what card 7 (plan 01-08, merged PR #216) actually left on origin/develop — confirmed by reading the file before editing, not from spike 5's diff — avoiding RESEARCH's Pitfall 6 (the pre-card-7 import line collision)."
  - "The layering test is general, not a regression test for one call site: it computes server.py's own module-level import closure via ast, then walks every module in that closure (function bodies included, since a lazy local import is exactly how the old cycle hid) asserting no import anywhere resolves back to macos_apps_mcp.server. Verified live: re-adding a lazy `from . import server` inside doctor.py's _outbound_state() made the test fail with the exact module and line number, then was reverted before committing."
  - "A code-review finding (not a plan deviation, an in-flight fix before landing): tiers.py's read_only() docstring had lost the word \"below\" relative to server.py's original _read_only() when first drafted — a normalized-AST byte-identity check against origin/develop's server.py caught it, one word restored, re-verified byte-identical, folded into a small dedicated commit before the PR merged."
  - "A second, more consequential bug caught in the same pass (Rule 1 — bug, not a plan deviation, since it was introduced and fixed within this plan's own edit): tests/test_server.py's test_untrusted_notice_is_one_block_not_per_item had a local variable literally named `notices`, which after adding `import macos_apps_mcp.notices as notices` at module scope would have shadowed the module for the WHOLE function body (Python's static per-function scoping, not just after the assignment line) — the list comprehension on the same line that builds it would have raised AttributeError on a list object. Renamed the local to notice_blocks; verified the test still passes and still asserts the same thing."

requirements-completed: [GATE-10]

coverage:
  - id: D1
    description: "Tier policy (read_only, allow_send) moved to macos_apps_mcp/tiers.py, bodies byte-identical to server.py's pre-cut _read_only/_allow_send (confirmed by a normalized-AST comparison against origin/develop@799355c); server.py's write/additive/send gates now call tiers.read_only()/tiers.admit_send()"
    requirement: "GATE-03"
    verification:
      - kind: manual_procedural
        ref: "scratch AST byte-identity script comparing origin/develop@799355c's server.py _read_only/_allow_send defs against tiers.py's read_only/allow_send defs, normalized for the rename and the one internal call-site rename — 2/2 OK"
        status: pass
      - kind: unit
        ref: "tests/test_server.py (tiers.read_only/tiers.allow_send parametrized cases, unchanged assertions), tests/test_doctor_deploy.py, tests/test_deploy.py, tests/test_gate_on_dispatch.py, tests/test_tool_annotations.py — all pass in default AND MACOS_APPS_ALLOW_SEND=mail modes"
        status: pass
    human_judgment: false
  - id: D2
    description: "doctor.py no longer imports server anywhere (the package's only import cycle removed); _outbound_state() calls tiers.outbound_status() directly; the import block is otherwise exactly what card 7 left"
    requirement: "GATE-03"
    verification:
      - kind: unit
        ref: "tests/test_import_layers.py#test_nothing_below_server_imports_server, #test_layering_closure_is_not_vacuous"
        status: pass
      - kind: manual_procedural
        ref: "grep -nE \"from \\. import server|import server\" macos_apps_mcp/doctor.py -> no output; grep confirms card 1/7 import lines (eventkit.request_access_each, runtime.app_process_info+run_native, deploy+runtime+tiers) all survive unchanged"
        status: pass
    human_judgment: false
  - id: D3
    description: "Untrusted-data notice middleware (UntrustedDataNotice, UNTRUSTED_NOTICE, NO_NOTICE_TOOLS, _BACKUP_NOTICE_TOOLS) moved to macos_apps_mcp/notices.py, a sibling of audit.py; server.py wires notices.UntrustedDataNotice() at the same registration point; the notice tests assert the identical behavior as before the move"
    requirement: "GATE-03"
    verification:
      - kind: unit
        ref: "tests/test_server.py -k notice (5 tests, unchanged assertions, only the module reference changed)"
        status: pass
    human_judgment: false
  - id: D4
    description: "GATE-10 small fix: daemon.py's stale comment on the MACOS_APPS_MCP_ROLE assignment (claiming doctor reads it before the server import) replaced with the accurate explanation; deploy.py's allow_send_file() docstring repointed at tiers.allow_send"
    requirement: "GATE-10"
    verification:
      - kind: manual_procedural
        ref: "grep -n \"doctor reads it\" macos_apps_mcp/daemon.py -> no output; grep -n \"server._allow_send\" macos_apps_mcp/deploy.py -> no output"
        status: pass
    human_judgment: false
  - id: D5
    description: "Card 5 is on origin/develop by one rebase-merged PR (#218), CI green, local verify triple clean in both default and MACOS_APPS_ALLOW_SEND=mail modes, code-review pass (Standards + Spec) found and fixed two issues before merge, no open issue remained"
    requirement: "GATE-13"
    verification:
      - kind: other
        ref: "gh pr view 218 --json state,mergeCommit,mergedAt -> state=MERGED, mergeCommit=bd6fe5357c3ff02b4db2268f8289c82d48cfab8d; git show origin/develop:macos_apps_mcp/tiers.py | grep -c \"def allow_send\" -> 1"
        status: pass
    human_judgment: false

duration: ~50min
completed: 2026-09-25
status: complete
---

# Phase 01 Plan 09: Card 5 — Tier policy in tiers.py, notices in notices.py, doctor no longer imports server (GATE-03, GATE-10) Summary

**`read_only`/`allow_send` and their (provisional) outbound ledger left server.py for a new `tiers.py`, the untrusted-data notice middleware left for a new `notices.py`, and doctor.py's only reach into server.py is gone — pinned by a general AST-based layering test — landed via PR #218 (rebase-merged, bd6fe53) with one docstring byte-identity fix and one real test bug caught by code review before merge.**

## Performance

- **Duration:** ~50 min
- **Completed:** 2026-09-25
- **Tasks:** 3 completed
- **Files modified:** 12 (across all 3 commits: 5 in Task 1, 5 in Task 2, 1 in Task 3's fix commit)

## Accomplishments

- **`macos_apps_mcp/tiers.py`** (new): `read_only()` and `allow_send(adapter)` — bodies copied from `origin/develop@799355c`'s `server.py` `_read_only`/`_allow_send`, renamed public, the one internal `_read_only()` call inside `allow_send` renamed to `read_only()`. A normalized-AST byte-identity script (paste below) confirmed both bodies match exactly except that rename.
- **Provisional outbound ledger, moved into `tiers.py`** (per the plan's explicit ledger-ownership decision, RESEARCH Pitfall 3 / Assumption A2): `_SEND_ADAPTERS`, `_SEND_REGISTERED`, `admit_send(adapter) -> bool` (replaces the two inline set updates `_send_tool` used to do itself), `outbound_status()`. The module docstring and the ledger block's own comment both state that card 2 (plan 01-12) deletes this block once `registry.py` becomes the one registration record — `registry.py` doesn't exist yet, and `doctor.py` had to stop importing `server` immediately, so this is the sequencing this plan was told to use.
- **`server.py`**: `from . import tiers`; `_write_tool`/`_additive_tool` gate on `tiers.read_only()`; `_send_tool` calls `tiers.admit_send(adapter)` for the registered-or-not decision (the #179 autosave doc composition still runs before the gate, unchanged); `_read_only`, `_allow_send`, `_SEND_ADAPTERS`, `_SEND_REGISTERED`, `outbound_status` deleted; the now-unused `os` import removed.
- **`doctor.py`**: `_outbound_state()` calls `tiers.outbound_status()` directly — the lazy `from . import server` reach-in (the package's only import cycle) is gone. The import block edit was made starting from what card 7 (plan 01-08, PR #216) actually left on `origin/develop` (`from . import deploy, runtime` -> `from . import deploy, runtime, tiers`) — verified by reading the file before editing, not applied from spike 5's diff (RESEARCH Pitfall 6, concretely avoided).
- **`tests/test_import_layers.py`** (new): `test_nothing_below_server_imports_server` parses every `macos_apps_mcp/**/*.py` with `ast`, resolves relative imports (import-level-aware) to fully-qualified module names, computes `server.py`'s own module-level (top-level-statement-only) import closure, then walks EVERY module in that closure — whole tree, function bodies included — asserting no import anywhere resolves back to `macos_apps_mcp.server`; a failure names the module and line. `test_layering_closure_is_not_vacuous` pins the closure actually contains `doctor`, `deploy`, `audit`, `runtime`, `tiers` (32 modules total, confirmed by a scratch run). **Verified live** (per the plan's acceptance criterion): re-added a lazy `from . import server` inside `doctor.py`'s `_outbound_state()`, ran the test — it failed naming `macos_apps_mcp.doctor:300` — then reverted before committing.
  - The resolution logic deliberately does NOT count a bare `from . import X`'s base package (e.g. `macos_apps_mcp` alone) as a resolved import target — every relative import in the package trivially resolves to its own parent package, which would otherwise pull the package's `__init__.py` (which imports server to build the app) and `cli.py` (which imports server to dispatch it) into the "closure", producing false positives on the two legitimate entry-point edges the plan's objective explicitly calls out (`__init__.py` and `daemon.serve()` importing the program they run). Only `base+alias` forms (`from . import server` -> `macos_apps_mcp.server`) and named-submodule forms (`from .server import mcp` -> `macos_apps_mcp.server`) count.
- **`macos_apps_mcp/notices.py`** (new): `UNTRUSTED_NOTICE`, `NO_NOTICE_TOOLS` (renamed from `_NO_NOTICE`, made public since it now lives in its own module), `_BACKUP_NOTICE_TOOLS`, `class UntrustedDataNotice(Middleware)` — bodies and comments moved verbatim from `server.py`. Module docstring states why this is a sibling of `audit.py` rather than folded into it: `audit.py` is a leaf `adapters.mail_recover` imports, while this module imports `mail_recover` itself (for `backup_advisory()`) — folding the notice into `audit.py` would create `audit -> mail_recover -> audit`.
- **`server.py` wiring**: `from . import notices`; `mcp.add_middleware(notices.UntrustedDataNotice())` at the exact same registration point the old class definition + `mcp.add_middleware(UntrustedDataNotice())` occupied; the moved block and its now-unused imports (`Middleware`, `TextContent`, `mail_recover`) deleted.
- **GATE-10 small fix**: `daemon.py`'s `serve()` had a stale comment on the `MACOS_APPS_MCP_ROLE` assignment claiming doctor reads the variable before the server import — replaced with the accurate explanation (registration already ran at package import; the gate reads argv via `deploy.is_daemon_role()`; this assignment is for embedders/tests only). `deploy.py`'s `allow_send_file()` docstring cross-reference repointed at `tiers.allow_send`.
- **Five test files repointed** (per the plan's exact mapping): `tests/test_deploy.py` (`server._allow_send` x3 -> `tiers.allow_send`), `tests/test_doctor_deploy.py` (`server._SEND_REGISTERED` -> `tiers._SEND_REGISTERED`, `server.outbound_status`/`srv._allow_send` x5 -> `tiers.outbound_status`/`tiers.allow_send`), `tests/test_gate_on_dispatch.py` (`srv.outbound_status()` inside the gate-on subprocess string -> `tiers.outbound_status()`, with a second `import macos_apps_mcp.tiers as tiers` added to the subprocess code to keep the line under ruff's 88-char cap), `tests/test_server.py` (`srv._read_only`/`srv._allow_send` -> `tiers.read_only`/`tiers.allow_send`, `srv.UNTRUSTED_NOTICE`/`srv.UntrustedDataNotice`/`srv._NO_NOTICE` -> `notices.UNTRUSTED_NOTICE`/`notices.UntrustedDataNotice`/`notices.NO_NOTICE_TOOLS`), `tests/test_tool_annotations.py` (`srv._allow_send` x2 -> `tiers.allow_send`).
- **Byte-identity check, pasted per Task 3's instruction** (normalized-AST comparison, `origin/develop@799355c` vs. this lane's `tiers.py`):
  ```
  OK     _read_only -> read_only
  OK     _allow_send -> allow_send
  ```
  (The `read_only` docstring initially dropped the word "below" during drafting — caught by this exact check before landing, fixed, re-verified OK; see Deviations.)
- **Verify triple green throughout, both tiers modes:** `uv run pytest -q` -> 1440 passed; `MACOS_APPS_ALLOW_SEND=mail uv run pytest -q` -> 1436 passed, 4 skipped (the four `_gate_off_only`-marked tests, correctly skipped when the gate is actually on); `uv run ruff check .` -> `[]`; `uv run ruff format --check .` -> 141 files already formatted.
- **Code-review pass** (Standards + Spec, run myself sequentially — no sub-agent tool available) over `origin/develop...HEAD` (3 commits, 12 files, +398/-185 at review time): Standards axis found nothing outstanding against CLAUDE.md's architecture rules (thin-dispatch, qualified imports, ruff config, tier-gating-at-registration all preserved) — checked `DESIGN.md`'s module-map for staleness but it was already missing several existing modules (`daemon.py`, `deploy.py`, etc.) before this plan, so adding just `tiers.py`/`notices.py` there would be inconsistent scope-creep rather than a genuine regression this diff introduced (unlike card 7's DESIGN.md fix, which corrected a bullet this exact PR made newly wrong); left untouched, out of scope. Grepped the whole repo (excluding `.planning/` and the historical `docs/superpowers/plans/` design doc) for any remaining `server._allow_send`/`srv._allow_send`/`server.outbound_status`/etc. — none found outside the intentionally-historical planning artifacts. Spec axis: every Task 1-3 acceptance criterion and the plan's `must_haves.truths`/`artifacts`/`key_links`/`prohibitions` verified against the actual diff and passing test output — no scope creep found. Two real findings, both fixed before merge (see Deviations).
- Lane was already rebased on `origin/develop` at merge time (merge-base equalled `origin/develop`'s tip, `799355c`, unchanged throughout this plan's execution) — no rebase, force-push, or CI re-watch cycle was needed.
- `gh pr merge 218 --rebase --delete-branch` merged (remote branch delete succeeded; local branch delete was skipped by `gh` because the branch was still checked out in the lane, cleaned up manually in the next step, matching the plan's lane-cleanup instructions) — merge commit `bd6fe5357c3ff02b4db2268f8289c82d48cfab8d` on `origin/develop`; `gh pr view 218` confirms `state: MERGED`.
- Task 3's `<verify>` command confirmed card 5 live on `develop`: `git show origin/develop:macos_apps_mcp/tiers.py | grep -c "def allow_send"` -> `1`.
- Lane cleanup from the main checkout only: `git worktree unlock` + `git worktree remove .worktrees/gate-card-5-tier-policy` + `git branch -D refactor/gate-card-5-tier-policy` + `git fetch -q --prune origin` — all succeeded; `git worktree list` confirms the lane is gone. No `git pull`/`commit`/`stash`/`checkout`/`reset` ran in the main checkout at any point.
- Vault journal bullet landed: `elfensky/obsidian` MR !815, merged — one line noting card 5's landing (PR #218, merge commit bd6fe53, GATE-03).

## Task Commits

Each task was committed atomically in the lane. GitHub's rebase-merge for PR #218 replayed every commit onto `origin/develop` with new SHAs — the hashes below are the ones that actually exist on `origin/develop` today; the lane-local hashes no longer resolve anywhere once the branch was deleted post-merge:

1. **Task 1: Tier policy + provisional outbound ledger into tiers.py; doctor's server reach-in removed; layering test** - `c7a9e88` on `origin/develop` (lane-local: `6749c43`) (feat)
2. **Task 2: Untrusted-data notice middleware into notices.py; stale daemon comment removed** - `a978551` on `origin/develop` (lane-local: `b2cac3c`) (feat)
3. **Task 3 landing fix: byte-identity check caught a dropped docstring word** - `bd6fe53` on `origin/develop` (lane-local: `6e5ac29`) (fix)

**Merge / PR tip commit:** `bd6fe5357c3ff02b4db2268f8289c82d48cfab8d` on `origin/develop` (PR #218's final replayed commit — `gh pr view 218` reports this as `mergeCommit`).

## Files Created/Modified

- `macos_apps_mcp/tiers.py` (new) — tier policy: `read_only()`, `allow_send(adapter)`, provisional outbound ledger (`_SEND_ADAPTERS`, `_SEND_REGISTERED`, `admit_send`, `outbound_status`)
- `macos_apps_mcp/notices.py` (new) — the untrusted-data notice middleware: `UNTRUSTED_NOTICE`, `NO_NOTICE_TOOLS`, `_BACKUP_NOTICE_TOOLS`, `UntrustedDataNotice`
- `tests/test_import_layers.py` (new) — `test_nothing_below_server_imports_server`, `test_layering_closure_is_not_vacuous`
- `macos_apps_mcp/server.py` — imports `tiers` and `notices`; write/additive/send gates call into `tiers`; the notice middleware instantiation calls into `notices`; five names and the notice class deleted; `os` import removed
- `macos_apps_mcp/doctor.py` — import block gains `tiers` (alongside the unchanged `deploy, runtime` and the card-7 `eventkit`/`runtime` lines); `_outbound_state()` calls `tiers.outbound_status()`, no more local `import server`
- `macos_apps_mcp/daemon.py` — `serve()`'s stale role-assignment comment corrected
- `macos_apps_mcp/deploy.py` — `allow_send_file()` docstring repointed at `tiers.allow_send`
- `tests/test_deploy.py`, `tests/test_doctor_deploy.py`, `tests/test_gate_on_dispatch.py`, `tests/test_server.py`, `tests/test_tool_annotations.py` — repointed at `tiers`/`notices` per the plan's exact mapping (see Accomplishments)

## Decisions Made

See `key-decisions` in the frontmatter — the provisional-ledger sequencing (executed exactly as the plan's objective specified), the doctor.py import-block starting point (verified against the actual post-card-7 file rather than the spike diff), the general (not call-site-specific) shape of the layering test, and the two code-review fixes (a byte-identity docstring word, a real test-shadowing bug).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `tiers.read_only()`'s docstring dropped the word "below" relative to server.py's original**
- **Found during:** Task 3's byte-identity verification (normalized-AST comparison against `origin/develop@799355c`)
- **Issue:** When first drafting `tiers.py`, `read_only()`'s docstring read "The write decorators consult it at registration time" instead of the original "The write decorators **below** consult it at registration time" — a one-word drift from the plan's must_haves requirement that the moved bodies be byte-identical.
- **Fix:** Restored the exact original wording. Re-ran the byte-identity script: both `read_only`/`allow_send` now report `OK`.
- **Files modified:** macos_apps_mcp/tiers.py
- **Verification:** Byte-identity script output pasted above; full verify triple re-run green after the fix.
- **Committed in:** `bd6fe53` (Task 3 landing fix commit)

**2. [Rule 1 - Bug] `tests/test_server.py`'s notice test had a local variable that would have shadowed the new `notices` module import**
- **Found during:** Task 2 implementation, while mechanically repointing `srv.UNTRUSTED_NOTICE` references to `notices.UNTRUSTED_NOTICE`
- **Issue:** `test_untrusted_notice_is_one_block_not_per_item` built a local list named `notices` (`notices = [b for b in res.content if ...]`) on the SAME lines the mechanical rename had just turned into `notices.UNTRUSTED_NOTICE`. Because Python decides a name is function-local for the WHOLE function body the instant it's assigned anywhere in that function (not just after the assignment line executes), the list-comprehension itself — which reads `notices.UNTRUSTED_NOTICE` on its own right-hand side before the assignment completes — would have raised `UnboundLocalError`/`AttributeError` the moment this test ran, not a silent behavior change.
- **Fix:** Renamed the local variable to `notice_blocks`; the two `notices.UNTRUSTED_NOTICE` reads elsewhere in the function correctly resolve to the module.
- **Files modified:** tests/test_server.py
- **Verification:** `uv run pytest tests/test_server.py -q -k notice` -> 5 passed (same 5 tests, same assertions, this one now actually runnable)
- **Committed in:** `a978551` (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (1 documentation byte-identity drift, 1 real test bug this plan's own mechanical edit would have introduced). **Impact on plan:** Neither auto-fix touches production behavior outside test/doc accuracy; the second one is exactly the kind of self-inflicted bug the plan's own verification loop (running the five test files, then the full suite, before landing) exists to catch before it reaches `develop`. No scope creep.

## Issues Encountered

None beyond the deviations above. Everything else in the plan's file-by-file recipe (from the PLAN.md action text plus `01-PATTERNS.md`/`01-RESEARCH.md`, verified against this lane's actual `server.py`/`doctor.py`/five test files before editing) matched what was actually on `origin/develop` after card 7 — no additional collisions or surprises. No auth gates encountered (no external service in scope for this plan).

## User Setup Required

None — no external service configuration required. The dev-build daemon check (D-06) is explicitly deferred to plan 01-10 per this plan's objective; this plan did not build, install, or restart the daemon, and did not touch `/Applications/macos-apps-mcp.app` or launchd, per the orchestrator's explicit instruction.

## Next Phase Readiness

- GATE-03's code half is landed: tier policy and the untrusted-data notice are out of `server.py`, `doctor.py` imports no server symbol at any nesting level, and a general layering test (not a narrow regression test) pins "nothing below server imports server" going forward. GATE-03 itself is NOT ticked by this plan — per the orchestrator's explicit instruction, it ticks at plan 01-12 (card 2), since GATE-03's full text also covers the registration-record consolidation that hasn't happened yet. GATE-10 IS ticked here (`requirements-completed: [GATE-10]`) — this is GATE-10's last outstanding plan (the script-timeout tripwire half landed already via card 9, PR #213); the remaining stale-comment half landed in this plan's Task 2.
- `origin/develop` now carries card 5 at merge commit `bd6fe53`. Plan 01-10 owns the dev-build daemon check (D-06): rebuild + reinstall the `.app`, restart the daemon, confirm `doctor().build` reports the new sha and one outbound dry run still reports gated correctly.
- Plan 01-12 (card 2) has explicit, concrete work already named by this plan: delete `tiers.py`'s provisional ledger block (`_SEND_ADAPTERS`, `_SEND_REGISTERED`, `admit_send`, `outbound_status`) once `registry.py` exists, repoint `_tool()`'s `tier == "send"` branch and `doctor`'s outbound read at the registry instead, and leave `tiers.py` holding only `read_only()`/`allow_send()`.
- The lane `.worktrees/gate-card-5-tier-policy` and branch `refactor/gate-card-5-tier-policy` are both gone (locally and on the remote). No stale worktree or branch remains for card 5.
- The parallel `spike/arch-review-*` branches and their `.claude/worktrees/` checkouts (including `spike/arch-review-5-tier-policy` itself, read-only throughout this plan via `git show`/`git diff`, never checked out or landed) are untouched — plan 01-14 owns their removal (D-09).

## Self-Check: PASSED

- `macos_apps_mcp/tiers.py`, `macos_apps_mcp/notices.py`, `tests/test_import_layers.py`: FOUND on `origin/develop` (`git show origin/develop:<path> | head -1` for each returns real content) — expected MISSING in the main checkout's own working tree, since the main checkout stays on its own `develop` ref per the orchestrator-owned sync contract and was not pulled by this executor.
- Task commits `6749c43`/`b2cac3c`/`6e5ac29` (lane-local hashes) no longer resolve after the lane branch was deleted post-merge — expected, since GitHub's rebase-merge for PR #218 replayed every commit onto `origin/develop` with new SHAs. The replayed hashes all verify: `c7a9e88`, `a978551`, `bd6fe53` — all FOUND in `git log --oneline --all` from the main checkout after `git fetch`.
- Task 3's `<verify>` command re-confirmed: `git show origin/develop:macos_apps_mcp/tiers.py | grep -c "def allow_send"` -> `1`.
- All Task 1-3 acceptance criteria re-verified passing (see Accomplishments above): the four greps (doctor no server import, card-1/7 imports survive, server.py has no tier defs, tiers.py has four defs) all returned exactly what the plan specified; `test_import_layers.py` passes and was verified live to catch a reintroduced back-edge; `uv run pytest -q` and `MACOS_APPS_ALLOW_SEND=mail uv run pytest -q` both exit 0; the notice-class/comment/docstring greps in Task 2's acceptance criteria all printed nothing (as required) or one line (as required); `uv run ruff check .` and `uv run ruff format --check .` both clean.
- `commits: 3` measured via `git rev-list --count 799355c44fe4691159f8efc95b9a4e24ddbf9f52..bd6fe5357c3ff02b4db2268f8289c82d48cfab8d` on the main checkout (fetched from origin) -> `3`, matching the frontmatter.

---
*Phase: 01-gate-land-the-spiked-architecture-cuts*
*Completed: 2026-09-25*
