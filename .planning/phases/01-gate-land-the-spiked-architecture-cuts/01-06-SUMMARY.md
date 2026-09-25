---
phase: 01-gate-land-the-spiked-architecture-cuts
plan: 06
subsystem: runtime
tags: [eventkit, threading, runtime-split, gate-02, byte-identity, code-review, landing]

# Dependency graph
requires:
  - phase: 01-04
    provides: the qualified native-seam pattern and a develop tip (7a3194b) with card 1's static tripwire already widened to every adapter + doctor.py
provides:
  - macos_apps_mcp/eventkit.py — the EventKit plane (store, request_access/request_access_each/bootstrap, NSDate/RRULE coercion, run_native_async), byte-identical bodies moved from runtime.py
  - macos_apps_mcp/runtime.py trimmed to the native door — an 11-name public surface (run_native, on_worker, app_process_info, terminate_children, tracked_run, run_osascript, body_file, verify_sqlite_schema, read_via_sqlite, mac_region, log), pinned by a test
  - tests/test_eventkit.py — every EventKit-typed unit test moved out of test_runtime.py, plus two new GATE-02 pin tests (public surface, no second executor)
  - Card 7 merged to origin/develop by one rebase-merged PR (#216, merge commit 8627aa8)
affects: [Phase 1 plan 01-08 (card 7's device proof: `-m integration -k "request_access or create_event or create_reminder"`), Phase 1 plan 01-09 (card 5, which must sequence doctor.py's import-block edit starting from this lane's post-card-7 shape, not the pre-card-7 spike diff)]

# Actuals (#2632)
actuals:
  tokens: 12630
  tasks: 3
  commits: 3
  plan_head_before: 7a3194bdfcea578f7bb9b54b00aa8b6e9c66536f
confidence_note: "estimate was 90000 tokens (low confidence); actual realized diff for this plan's 3 commits was ~12630 (chars/4 over the develop..merge-commit diff) — the estimate did not anticipate how mechanical the split was once the moved-name list was settled from the spike recipe"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "EventKit-typed native code lives in its own module (eventkit.py), imported
      by name from adapters (from ..eventkit import store, to_nsdate, ...) —
      run_native stays a separate ..runtime import. Adapter tests keep patching
      cal.store/rem.store unchanged since the import is still by-name."
    - "runtime.on_worker() is the public thread-affinity fence eventkit's
      store() calls without eventkit owning the worker — runtime owns the
      executor and the fence predicate; eventkit only asks it a question."
    - "A public-surface pin test (vars(module) introspection, filtered by
      __module__) catches any future name drift between runtime.py's ~10-name
      door and what actually lives there; it must call monkeypatch.undo() first
      to see past the autouse native-seam lock (conftest.py) that fakes
      run_osascript/body_file/tracked_run for every non-integration test."

key-files:
  created:
    - macos_apps_mcp/eventkit.py
    - tests/test_eventkit.py
  modified:
    - macos_apps_mcp/runtime.py
    - macos_apps_mcp/adapters/calendar.py
    - macos_apps_mcp/adapters/reminders.py
    - macos_apps_mcp/doctor.py
    - macos_apps_mcp/server.py
    - tests/test_runtime.py
    - tests/test_integration.py
    - macos_apps_mcp/contracts.py
    - macos_apps_mcp/lifecycle.py
    - DESIGN.md

key-decisions:
  - "Byte-identity check run as a one-off scratch AST script (not a permanent test), comparing BASE (7a3194b, origin/develop at lane creation) against this lane's eventkit.py: all 23 moved names OK, the sole documented diff is store()'s fence call _on_worker() -> on_worker()."
  - "test_runtime_public_surface_is_the_native_door calls monkeypatch.undo() before introspecting vars(runtime) — the autouse conftest fixture patches run_osascript/body_file/tracked_run to a _refuse fake for every unit test, which would otherwise make those three names invisible to a __module__-based introspection check."
  - "Code-review pass (Standards + Spec, run sequentially myself — no sub-agent tool available) over origin/develop...HEAD found one Standards finding: DESIGN.md's EventKit-worker prose bullet still named only runtime.py after the store moved to eventkit.py in the same PR. Fixed and folded into the landing commit. A second stale docstring (adapters/messages.py's `_apple_date_to_dt`, referencing `runtime.from_nsdate`) was found but reverted from this PR — messages.py is outside this plan's declared files_modified list, so the fix stays deferred rather than expanding this PR's scope."
  - "Lane was already rebased on origin/develop at merge time (merge-base == origin/develop tip, 7a3194b, before and after the code-review commit) — no rebase/force-push/CI-rewatch cycle was needed."
  - "PR #216 merged via `gh pr merge 216 --rebase --delete-branch` — merge commit 8627aa8b29d39c22f74e902e36a970b73fa932e2 on origin/develop. Task 3's verify command (grep request_access_each count in origin/develop's eventkit.py) returned 1."
  - "Lane cleanup ran from the main checkout only: worktree unlock/remove, local branch delete, fetch --prune. No pull/commit/stash/reset/checkout touched the main checkout's own git state. Parallel lanes (.worktrees/gate-card-3-envelope-fixture, .worktrees/gate-card-4-recoverable-preflight) were left untouched throughout."

requirements-completed: []

coverage:
  - id: D1
    description: "The EventKit cluster (store, request_access/request_access_each/bootstrap, NSDate/RRULE coercion, run_native_async, container_id) moved to macos_apps_mcp/eventkit.py with bodies byte-identical to this lane's pre-cut runtime.py, except store()'s documented fence-call edit"
    requirement: "GATE-02"
    verification:
      - kind: manual_procedural
        ref: "one-off scratch AST byte-identity script comparing BASE (origin/develop@7a3194b) runtime.py defs against eventkit.py defs — 22/23 OK, 1 OK-with-documented-fence-diff, 0 DIFF"
        status: pass
      - kind: unit
        ref: "tests/test_eventkit.py (full file, 20 test functions covering store/request_access/nsdate/recurrence/run_native_async/bootstrap)"
        status: pass
    human_judgment: false
  - id: D2
    description: "runtime.py's public surface is exactly the 11-name native door (run_native, on_worker, app_process_info, terminate_children, tracked_run, run_osascript, body_file, verify_sqlite_schema, read_via_sqlite, mac_region, log); runtime imports no EventKit"
    requirement: "GATE-02"
    verification:
      - kind: unit
        ref: "tests/test_runtime.py#test_runtime_public_surface_is_the_native_door"
        status: pass
    human_judgment: false
  - id: D3
    description: "eventkit.py defines no executor of its own; runtime._executor stays a single ThreadPoolExecutor(max_workers=1); eventkit dispatches only through runtime.run_native/on_worker"
    requirement: "GATE-02"
    verification:
      - kind: unit
        ref: "tests/test_eventkit.py#test_eventkit_owns_no_executor"
        status: pass
    human_judgment: false
  - id: D4
    description: "Calendar and Reminders import the EventKit cluster from the one module eventkit (by-name imports), keeping run_native as a separate runtime import — their existing tests still patch cal.store/rem.store unchanged"
    requirement: "GATE-02"
    verification:
      - kind: unit
        ref: "tests/test_calendar.py, tests/test_reminders.py, tests/test_free_busy.py (all pass unmodified against the new import shape)"
        status: pass
    human_judgment: false
  - id: D5
    description: "Card 7 is on origin/develop by one rebase-merged PR, CI green, local verify triple clean, code-review pass (Standards + Spec) found no open issue after one folded-in fix"
    requirement: "GATE-13"
    verification:
      - kind: other
        ref: "gh pr view 216 --json state,mergeCommit,mergedAt -> state=MERGED, mergeCommit=8627aa8b29d39c22f74e902e36a970b73fa932e2; git show origin/develop:macos_apps_mcp/eventkit.py | grep -c request_access_each -> 1"
        status: pass
    human_judgment: false
  - id: D6
    description: "eventkit.bootstrap() stays non-fatal when EventKit access is denied; the moved test that pins this passes unchanged"
    requirement: "GATE-02"
    verification:
      - kind: unit
        ref: "tests/test_eventkit.py#test_bootstrap_is_nonfatal_on_denied_surface"
        status: pass
    human_judgment: false

duration: ~50min
completed: 2026-09-25
status: complete
---

# Phase 01 Plan 06: Card 7 — runtime.py split, EventKit plane isolated in eventkit.py (GATE-02) Summary

**runtime.py's EventKit cluster (store, TCC request/bootstrap, NSDate/RRULE coercion, run_native_async) moved byte-identically into a new eventkit.py; runtime.py now exposes only an 11-name native door pinned by a test — PR #216 merged via rebase (8627aa8), device proof queued for plan 01-08.**

## Performance

- **Duration:** ~50 min (reading required context through PR merge + lane cleanup + journal)
- **Tasks:** 3 completed
- **Files modified:** 10 (9 in Task 1's commit, 5 more touched across Tasks 2–3; see Files Created/Modified)

## Accomplishments

- **Moved names** (23 total, all byte-identical except one documented edit): `_FULL_ACCESS`, `_ACCESS_TIMEOUT`, `container_id`, `_require_full_access`, `_store`, `store`, `_ASYNC_TIMEOUT`, `run_native_async`, `to_nsdate`, `epoch_nsdate`, `from_nsdate`, `due_components`, `_FREQUENCIES`, `to_recurrence_rule`, `recurrence_signature`, `persisted_recurrence_signature`, `_FREQUENCY_NAMES`, `rrule_text`, `_request_one`, `_ENTITIES`, `request_access`, `request_access_each`, `bootstrap` — copied from this lane's `runtime.py` (develop after card 1, `7a3194b`), never from the spike. `store()`'s fence call `_on_worker()` → `on_worker()` is the one documented body edit.
- **runtime.py's public surface, pinned by a test** (11 names): `run_native, on_worker, app_process_info, terminate_children, tracked_run, run_osascript, body_file, verify_sqlite_schema, read_via_sqlite, mac_region, log`. `_on_worker` renamed public `on_worker` (eventkit's `store()` fences through it without owning the worker); `classify_stuck_app` → `_classify_stuck_app` and `track_child` → `_track_child` (runtime-internal only, now private). `runtime` no longer imports `EventKit`, `Foundation`'s `Recurrence`/`CLEAR_RECURRENCE`, or `datetime`.
- **Byte-identity check** (one-off scratch AST script, not a permanent test) confirmed every moved name's body unchanged from `BASE` (`7a3194b`) except the fence edit:

  ```
  OK         _FULL_ACCESS
  OK         _ACCESS_TIMEOUT
  OK         container_id
  OK         _require_full_access
  OK         _store
  OK (fence: _on_worker() -> on_worker()) store
  OK         _ASYNC_TIMEOUT
  OK         run_native_async
  OK         to_nsdate
  OK         epoch_nsdate
  OK         from_nsdate
  OK         due_components
  OK         _FREQUENCIES
  OK         to_recurrence_rule
  OK         recurrence_signature
  OK         persisted_recurrence_signature
  OK         _FREQUENCY_NAMES
  OK         rrule_text
  OK         _request_one
  OK         _ENTITIES
  OK         request_access
  OK         request_access_each
  OK         bootstrap
  ```

- **Importers re-pointed:** `calendar.py`/`reminders.py` import the moved names from `..eventkit` by name (`run_native` stays a separate `..runtime` import) — `tests/test_calendar.py`/`tests/test_reminders.py`/`tests/test_free_busy.py` needed zero changes, since they patch `cal.store`/`rem.store` (module attributes), unaffected by which module the name was imported from. `doctor.py` imports `request_access_each` from `.eventkit` (keeps `app_process_info`, `run_native` from `.runtime`). `server.py` imports `bootstrap` from `.eventkit`.
- **Tests split:** `tests/test_eventkit.py` (new) holds every EventKit-typed case moved out of `test_runtime.py` (store/access, nsdate/recurrence conversions, `run_native_async`, `bootstrap`), plus two new GATE-02 pin tests added in Task 2 (`test_eventkit_owns_no_executor`, and `test_runtime_public_surface_is_the_native_door` in `test_runtime.py`). `test_runtime.py` keeps the non-EventKit runtime tests (osascript dispatch/error classification, the sqlite dual-backend plane, batch/container helpers, child tracking, `body_file`) and its `_classify_stuck_app` call site was updated. `tests/test_integration.py` imports `request_access`/`store`/`to_nsdate` from `macos_apps_mcp.eventkit` at all 4 sites; `run_native`/`run_osascript` stay from `macos_apps_mcp.runtime`.
- **Docstring updates:** `contracts.py`'s `Recurrence` docstring and `lifecycle.py`'s module docstring now say `eventkit.to_recurrence_rule`/`eventkit.bootstrap()`; `DESIGN.md`'s module map gained an `eventkit.py` line and `runtime.py`'s description was corrected to "the single serialized native worker thread + osascript/sqlite dispatch".
- **Verify triple green throughout:** `uv run pytest -q` → 1405 passed (after Task 2); `uv run ruff check .` → `[]`; `uv run ruff format --check .` → 136 files already formatted.
- **Code-review pass** (Standards + Spec, run myself sequentially — no sub-agent tool available) over `origin/develop...HEAD` (3 commits at review time, 12 files, +540/-443): **one Standards finding** — `DESIGN.md`'s "EventKit on one dedicated, serialized worker thread" bullet still named only `runtime.py` after the store moved to `eventkit.py` in this same PR; fixed and folded into a third commit. A second candidate finding (`adapters/messages.py`'s docstring referencing `runtime.from_nsdate`) was identified but **reverted** — that file is outside this plan's declared `files_modified`, so the fix is deferred rather than expanding this PR's scope. Spec axis: every Task 1–3 acceptance criterion and the plan's `must_haves.truths`/`artifacts`/`key_links`/`prohibitions` are satisfied by the diff; no scope creep found.
- The lane was already rebased on `origin/develop` at merge time (merge-base equalled `origin/develop`'s tip, `7a3194b`, unchanged by the parallel card-3 lane) — no rebase, force-push, or CI re-watch cycle was needed.
- `gh pr merge 216 --rebase --delete-branch` succeeded — merge commit `8627aa8b29d39c22f74e902e36a970b73fa932e2` on `origin/develop`; `gh pr view 216` confirms `state: MERGED`.
- Task 3's `<verify>` command confirmed card 7 live on `develop`: `git show origin/develop:macos_apps_mcp/eventkit.py | grep -c "def request_access_each"` → `1`.
- Lane cleanup from the main checkout: `git worktree unlock` + `git worktree remove .worktrees/gate-card-7-runtime-split` + `git branch -D refactor/gate-card-7-runtime-split` + `git fetch -q --prune origin` — all succeeded; `git worktree list` confirms the lane is gone. The parallel card-3 (`.worktrees/gate-card-3-envelope-fixture`) and card-4 (`.worktrees/gate-card-4-recoverable-preflight`) lanes were left untouched.
- Vault journal bullet landed: `elfensky/obsidian` MR !801, merged — one line noting card 7's landing (PR #216, merge commit 8627aa8, GATE-02).

## Task Commits

This plan's own 3 task commits, authored in the lane as `3c6cb11`, `c60865d`, `75d58cc`. GitHub's rebase-merge for PR #216 replayed every commit onto `origin/develop` with new SHAs — the hashes below are the ones that actually exist on `origin/develop` today; the lane-local hashes no longer resolve anywhere once the branch was deleted post-merge:

1. **Task 1: Move the EventKit cluster to eventkit.py and re-point every importer (tracer)** — `32d0f20` on `origin/develop` (lane-local: `3c6cb11`) (feat)
2. **Task 2: Pin the runtime public surface and the single worker; prove byte-identical bodies; fix stale docstrings** — `0603bb5` on `origin/develop` (lane-local: `c60865d`) (test)
3. **Task 3 landing fix: DESIGN.md prose correction found by code review** — `8627aa8` on `origin/develop` (lane-local: `75d58cc`) (docs)

**Merge / PR tip commit:** `8627aa8b29d39c22f74e902e36a970b73fa932e2` on `origin/develop` (PR #216's final replayed commit — `gh pr view 216` reports this as `mergeCommit`).

## Files Created/Modified

- `macos_apps_mcp/eventkit.py` (new) — the EventKit plane: store, TCC request/bootstrap, NSDate/RRULE coercion, `run_native_async`, `container_id`
- `tests/test_eventkit.py` (new) — every EventKit-typed test moved from `test_runtime.py`, plus `test_eventkit_owns_no_executor`
- `macos_apps_mcp/runtime.py` — trimmed to the 11-name native door; `on_worker` public, `_classify_stuck_app`/`_track_child` private; module docstring corrected
- `macos_apps_mcp/adapters/calendar.py`, `macos_apps_mcp/adapters/reminders.py` — import the moved names from `..eventkit`, keep `run_native` from `..runtime`
- `macos_apps_mcp/doctor.py` — `from .eventkit import request_access_each`
- `macos_apps_mcp/server.py` — `from .eventkit import bootstrap`
- `tests/test_runtime.py` — trimmed to non-EventKit tests; `_classify_stuck_app` call site updated; `test_runtime_public_surface_is_the_native_door` added (uses `monkeypatch.undo()` to see past the autouse native-seam lock)
- `tests/test_integration.py` — 4 import sites re-pointed to `macos_apps_mcp.eventkit`
- `macos_apps_mcp/contracts.py` — `Recurrence` docstring points at `eventkit.to_recurrence_rule`
- `macos_apps_mcp/lifecycle.py` — module docstring points at `eventkit.bootstrap()`
- `DESIGN.md` — module map gained an `eventkit.py` line; `runtime.py`'s description and the EventKit-worker prose bullet corrected

## Decisions Made

See `key-decisions` in the frontmatter — byte-identity check methodology, the `monkeypatch.undo()` fix for the public-surface test, the code-review finding folded in vs. the one deferred (out of this PR's declared files), and the clean rebase/merge/cleanup sequence.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `test_runtime_public_surface_is_the_native_door` initially failed under the autouse native-seam lock**
- **Found during:** Task 2 verification
- **Issue:** `tests/conftest.py`'s autouse `_no_real_osascript` fixture monkeypatches `runtime.run_osascript`/`body_file`/`tracked_run` to a `_refuse` fake for every non-integration test — including this new test itself — so `vars(runtime)` saw the fakes (whose `__module__` is `tests.conftest`, not `macos_apps_mcp.runtime`) instead of the real functions, and the introspection undercounted the public surface by 3 names.
- **Fix:** Added a `monkeypatch` parameter to the test and called `monkeypatch.undo()` first — pytest's `monkeypatch` fixture is function-scoped and shared across every fixture requesting it within one test, so this undoes the autouse fixture's patches too, restoring the real bindings before introspecting.
- **Files modified:** tests/test_runtime.py
- **Verification:** `uv run pytest tests/test_runtime.py tests/test_eventkit.py -q -k "public_surface or owns_no_executor"` → 2 passed
- **Committed in:** `0603bb5` (Task 2 commit)

**2. [Rule 1 - Doc drift] DESIGN.md's EventKit-worker prose bullet still named only runtime.py**
- **Found during:** Task 3 code-review pass (Standards axis)
- **Issue:** After the store moved to `eventkit.py` in this same PR, `DESIGN.md`'s bullet "EventKit on one dedicated, serialized worker thread (`runtime.py`)" implied the store still lived in `runtime.py`.
- **Fix:** Corrected the bullet to name both modules' actual roles (`runtime.py` owns the worker, `eventkit.py` owns the store and every EventKit-typed call).
- **Files modified:** DESIGN.md
- **Verification:** `uv run pytest -q` (1405 passed), `uv run ruff check .`/`ruff format --check .` clean, re-confirmed before push
- **Committed in:** `8627aa8` (Task 3 landing commit)

---

**Total deviations:** 2 auto-fixed (1 test bug, 1 doc drift). A third candidate finding (`adapters/messages.py`'s stale `runtime.from_nsdate` docstring reference) was identified during code review but reverted — that file is outside this plan's declared `files_modified`, so it is left as a deferred, out-of-scope cleanup rather than expanding this PR.
**Impact on plan:** Both auto-fixes are necessary for correctness (a mis-scoped pin test would have been a false negative forever) and documentation accuracy. No scope creep beyond the plan's declared files.

## Issues Encountered

None beyond the deviations above. The plan's file-by-file recipe (from `01-PATTERNS.md`/`01-RESEARCH.md`, verified against this lane's actual `runtime.py`/`calendar.py`/`reminders.py`/`doctor.py`/`server.py`/test files before editing) matched the codebase exactly — no additional collisions with the parallel card-3 lane (`.worktrees/gate-card-3-envelope-fixture`, no shared files) were found.

## User Setup Required

None — no external service configuration required. The device proof (`uv run pytest -m integration -k "request_access or create_event or create_reminder"`) is explicitly deferred to plan 01-08 per this plan's objective and D-08.

## Next Phase Readiness

- GATE-02's code half is landed: `runtime.py` is the native door, EventKit is its own module, bodies are unchanged. Requirement ticking (`requirements-completed: []` in this SUMMARY's frontmatter, per the shared-ID gate) is deferred — GATE-02 ticks only at plan 01-08 (the device proof), GATE-13 only at plan 01-14 (final branch/worktree cleanup across all cards).
- `origin/develop` now carries card 7 at merge commit `8627aa8`. Plan 01-09 (card 5) must sequence `doctor.py`'s import-block edit starting from what card 7 left behind (`from .eventkit import request_access_each` / `from .runtime import app_process_info, run_native`), not the pre-card-7 shape the spike's own diff was authored against — this is `01-PATTERNS.md`'s Pitfall 6, now concretely the state on `develop`.
- Plan 01-08 owns the device proof (`-m integration -k "request_access or create_event or create_reminder"`) and card 5's dev-build daemon check; both wait on this plan's merge, which is now satisfied.
- The lane `.worktrees/gate-card-7-runtime-split` and branch `refactor/gate-card-7-runtime-split` are both gone (locally and on the remote). No stale worktree or branch remains for card 7.
- Parallel lanes `.worktrees/gate-card-3-envelope-fixture` (plan 01-07) and `.worktrees/gate-card-4-recoverable-preflight` (plan 01-05) were left untouched throughout — no shared files, no interference.

## Self-Check: PASSED

- `macos_apps_mcp/eventkit.py`, `tests/test_eventkit.py`: FOUND on `origin/develop` (`git cat-file -e origin/develop:<path>` for both) — expected MISSING in the main checkout's own working tree, since the main checkout stays on its own `develop` ref per the orchestrator-owned sync contract and was not pulled by this executor.
- Task commits: `3c6cb11`/`c60865d`/`75d58cc` (this plan's lane-local hashes) no longer resolve after the lane branch was deleted post-merge — expected, since GitHub's rebase-merge for PR #216 replayed every commit onto `origin/develop` with new SHAs. The replayed hashes all verify: `32d0f20`, `0603bb5`, `8627aa8` — all FOUND in `git log --oneline --all` from the main checkout.
- Task 3's `<verify>` command re-confirmed: `git show origin/develop:macos_apps_mcp/eventkit.py | grep -c "def request_access_each"` → `1`.
- All Task 1–3 acceptance criteria re-verified passing (see Accomplishments above): runtime.py has no `import EventKit`/`.contracts` import, no moved `def`s remain in runtime.py (all present in eventkit.py instead), both adapters import from `..eventkit`, no test imports the moved names from `macos_apps_mcp.runtime`, `uv run pytest -q` exits 0 (1405 passed), the public-surface test passes 1/1, the byte-identity output lists OK for every moved name with the one documented `store()` diff, the two docstring greps print nothing, `DESIGN.md` names `eventkit.py` once in its module map.
- `commits: 3` measured via `git rev-list --count 7a3194bdfcea578f7bb9b54b00aa8b6e9c66536f..8627aa8b29d39c22f74e902e36a970b73fa932e2` on the main checkout (fetched from origin) → `3`, matching the frontmatter.

---
*Phase: 01-gate-land-the-spiked-architecture-cuts*
*Completed: 2026-09-25*
