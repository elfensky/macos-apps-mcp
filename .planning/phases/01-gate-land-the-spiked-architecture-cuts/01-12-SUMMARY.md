---
phase: 01-gate-land-the-spiked-architecture-cuts
plan: 12
subsystem: server-registration
tags: [registry, notices, tiers, gate-03, gate-04, tdd, landing]

# Dependency graph
requires:
  - phase: 01-11
    provides: macos_apps_mcp/registry.py (ToolRecord, TOOLS, add, derived views) and the one `_tool(...)` registration decorator every tool goes through — this plan's adapter=/permission=/backup_notice= additions land on that decorator
provides:
  - Every non-meta tool call site in server.py carries adapter= and permission= (GATE-04); ping/now/doctor/usage/audit stay bare (meta tools)
  - tests/test_tool_annotations.py's three hand tables (_ADDITIVE_TOOLS/_DESTRUCTIVE_TOOLS/_PERMISSION) are views over registry.TOOLS; _mail_tools() asserts agreement with registry.by_adapter("mail")
  - tests/test_registry.py freezes the develop-era hand tables as literals and pins the registry-derived views against them; adds test_meta_tools_have_no_adapter_permission_or_notice and test_every_other_tool_names_its_adapter
  - notices.py::UntrustedDataNotice reads notice/backup_notice from registry.TOOLS per call (fail-safe: no record -> notice); NO_NOTICE_TOOLS/_BACKUP_NOTICE_TOOLS deleted; move_mail/trash_mail/mail_undo carry backup_notice=True
  - registry.py::outbound_status() — the ONE outbound ledger (registered vs configured send adapters), a view over send-tier records
  - tiers.py reduced to the pure gate predicates (read_only, allow_send) — _SEND_ADAPTERS/_SEND_REGISTERED/admit_send/outbound_status deleted
  - doctor.py imports registry (not tiers) for _outbound_state(); server.py's _tool send branch calls tiers.allow_send(adapter) directly
  - Branch refactor/gate-card-2-registration-record pushed to origin, 5 commits ahead of 01-11's HEAD (9bf35f6) — lane stays open for plan 01-13
affects: [Phase 1 plan 01-13 (the one card-2 PR + code review + merge)]

# Actuals (#2632)
actuals:
  tokens: 14393
  tasks: 3
  commits: 5
  plan_head_before: 9bf35f6900313bba29c958966dc2daa710a3b4e4
confidence_note: "estimate was 80000 tokens (low confidence); actual realized diff for this plan's 5 commits was ~14393 (chars/4 over the 9bf35f6..HEAD diff, 57573 chars across 389 insertions/277 deletions in 10 files) — the estimate anticipated more churn than the mechanical per-tool adapter=/permission= additions, the notices.py registry lookup, and the tiers.py→registry.py ledger move actually required. One extra fixup commit (db3219c) corrected two docstrings whose prose restated a literal grep target, caught by re-running the plan's own acceptance-criteria greps before considering the plan done."

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Every per-tool fact the rest of the system used to read from a hand-maintained table is now a call-site kwarg on server.py's one _tool(...) decorator, landing in registry.ToolRecord: adapter= and permission= (this plan, GATE-04), backup_notice= (this plan, #163), on top of 01-11's audit=/snapshot=/notice=. A tool that dispatches to an adapter but forgets to name it now fails a registry test (test_every_other_tool_names_its_adapter), not silently."
    - "A middleware that used to hold its own hand-maintained exemption set now looks up the called tool's record per call (registry.TOOLS.get(name)) instead of computing a set once at import — notices.UntrustedDataNotice reads notice/backup_notice live off the record, with a fail-safe default (no record -> notice) rather than a fail-open one, so an unregistered/typo'd tool name can never silently lose the prompt-injection mitigation."
    - "One ledger, one owner (RESEARCH Pitfall 3): registry.outbound_status() derives registered/configured send adapters from the send-tier records already sitting in registry.TOOLS, instead of a second capability-tracking set card 5 (01-09) had provisionally parked in tiers.py. tiers.py is now the pure gate-predicate module the phase's architecture rule always intended (read_only(), allow_send()) — server.py's send branch calls allow_send(adapter) directly, no intermediate admit_send() ledger-writer in between."

key-files:
  created: []
  modified:
    - macos_apps_mcp/server.py
    - macos_apps_mcp/registry.py
    - macos_apps_mcp/notices.py
    - macos_apps_mcp/tiers.py
    - macos_apps_mcp/doctor.py
    - tests/test_tool_annotations.py
    - tests/test_registry.py
    - tests/test_server.py
    - tests/test_doctor_deploy.py
    - tests/test_gate_on_dispatch.py

key-decisions:
  - "Copied every adapter=/permission= value verbatim from the CURRENT (pre-refactor) tests/test_tool_annotations.py hand table, per the plan's explicit instruction and cross-checked against the spike recipe (git show d9926c9) — 61 tool call sites classified, zero re-derived from scratch, zero disagreements with the spike's own mapping."
  - "Task 2's RED phase produced 2 genuine failures (backup_notice_tools() empty; NO_NOTICE_TOOLS/_BACKUP_NOTICE_TOOLS still present) out of 10 written assertions — the other 8 (fail-safe-for-unknown-name, backup-advisory-rides-the-three-writes, per-tool notice coverage) already held true under the PRE-refactor hand-set implementation, because the refactor's observable behavior is nearly behavior-preserving for already-classified tool names. Kept as regression coverage rather than dropped, following the same TDD-investigation precedent 01-11 documented for test_create_contact_is_logged_with_its_verb."
  - "Two docstrings (tiers.py's module docstring, doctor.py's _outbound_state()) initially restated the exact literal names the plan's own acceptance-criteria greps search for (_SEND_ADAPTERS/_SEND_REGISTERED/admit_send/outbound_status; registry.outbound_status()) in explanatory prose, which made those strict greps fail even though the underlying code was correct. Reworded both to describe the behavior without repeating the literal grep target — caught by re-running the plan's own acceptance criteria before declaring Task 3 done, fixed in a small follow-up commit (db3219c) rather than amending the landed Task 3 commit."

requirements-completed: [GATE-03, GATE-04]

coverage:
  - id: D1
    description: "Every tool record states its adapter and the macOS permission(s) its docstring must name; test_tool_annotations.py derives its permission table, additive/destructive sets and _mail_tools() oracle agreement from registry.TOOLS instead of hand tables"
    requirement: "GATE-04"
    verification:
      - kind: unit
        ref: "tests/test_tool_annotations.py (19 tests, default + MACOS_APPS_ALLOW_SEND=mail modes)"
        status: pass
      - kind: unit
        ref: "tests/test_registry.py#test_tier_reproduces_the_develop_era_additive_and_destructive_sets, #test_permission_reproduces_the_develop_era_hand_map, #test_every_other_tool_names_its_adapter"
        status: pass
      - kind: manual_procedural
        ref: "grep for a hand-written permission literal in tests/test_tool_annotations.py -> no output (only the develop-era pin literal remains, in test_registry.py)"
        status: pass
    human_judgment: false
  - id: D2
    description: "The meta tools ping/now/doctor/usage carry adapter=None, permission=(), notice=False; audit carries adapter=None, permission=() but keeps the notice; every other tool carries an adapter (GATE-04 empty edge)"
    requirement: "GATE-04"
    verification:
      - kind: unit
        ref: "tests/test_registry.py#test_meta_tools_have_no_adapter_permission_or_notice"
        status: pass
    human_judgment: false
  - id: D3
    description: "The untrusted-data notice and the #163 backup advisory are decided per call from the tool's registry record; a tool with no record gets the notice (fail safe); notices.py's NO_NOTICE_TOOLS/_BACKUP_NOTICE_TOOLS are gone"
    requirement: "GATE-04"
    verification:
      - kind: unit
        ref: "tests/test_server.py#test_no_notice_exempts_exactly_the_meta_tools, #test_hand_maintained_notice_sets_are_gone, #test_untrusted_notice_covers_every_registered_tool_except_meta, #test_unregistered_tool_name_gets_the_notice_fail_safe, #test_backup_advisory_rides_the_three_recoverable_writes"
        status: pass
      - kind: unit
        ref: "tests/test_registry.py#test_no_notice_and_backup_notice_reproduce_the_hand_sets"
        status: pass
      - kind: other
        ref: "TDD gate: test(01-12) RED commit 1df35ae (8 passed, 2 failed on the exact planned behavior) -> feat(01-12) GREEN commit 5fd28ae (114 passed, 0 failed)"
        status: pass
      - kind: manual_procedural
        ref: "grep -nE \"^(NO_NOTICE_TOOLS|_BACKUP_NOTICE_TOOLS)\" macos_apps_mcp/notices.py -> no output"
        status: pass
    human_judgment: false
  - id: D4
    description: "The outbound ledger has ONE owner: registry.outbound_status() derives registered and configured adapters from send records; tiers.py holds only read_only() and allow_send()"
    requirement: "GATE-03"
    verification:
      - kind: unit
        ref: "tests/test_doctor_deploy.py#test_outbound_status_splits_registered_from_configured, #test_deployment_section_outbound_pending_when_configured_not_registered (pre-existing, still green through the registry.outbound_status() path); tests/test_gate_on_dispatch.py#test_gate_on_registers_the_three_send_tools (gate-on subprocess pins registry.outbound_status()['registered'])"
        status: pass
      - kind: unit
        ref: "tests/test_import_layers.py (2 tests, unchanged, still green)"
        status: pass
      - kind: manual_procedural
        ref: "grep -nE \"_SEND_ADAPTERS|_SEND_REGISTERED|def admit_send|def outbound_status\" macos_apps_mcp/tiers.py -> no output; grep -n \"def outbound_status\" macos_apps_mcp/registry.py -> one line; grep -n \"registry.outbound_status()\" macos_apps_mcp/doctor.py -> one line"
        status: pass
    human_judgment: false
  - id: D5
    description: "doctor reports outbound registered/configured/outbound_pending from registry.outbound_status(); after a toggle flip without restart the two lists still disagree and doctor reports outbound_pending"
    requirement: "GATE-03"
    verification:
      - kind: unit
        ref: "tests/test_doctor_deploy.py#test_deployment_section_outbound_pending_when_configured_not_registered, #test_deployment_section_outbound_off_when_read_only"
        status: pass
    human_judgment: false
  - id: D6
    description: "The published FastMCP tool list (names, descriptions, annotations, input schemas) stays byte-identical to origin/develop@bd6fe53 through this plan's full refactor, in both default and MACOS_APPS_ALLOW_SEND=mail modes — none of adapter=/permission=/backup_notice=/the ledger move leak into what a client sees"
    verification:
      - kind: other
        ref: "01-11's snapshot_tools.py re-run against this plan's final lane HEAD (scratch, outside the repo), diffed against 01-11's BASE captures (origin/develop@bd6fe53, detached worktree): diff base_default.json lane_default_final2.json -> identical; diff base_send.json lane_send_final.json -> identical"
        status: pass
    human_judgment: false
  - id: D7
    description: "uv run pytest, ruff check, ruff format --check all green in default AND MACOS_APPS_ALLOW_SEND=mail modes on the final lane HEAD; lane branch pushed to origin (no PR — plan 01-13 owns the one card-2 PR)"
    requirement: "GATE-13"
    verification:
      - kind: other
        ref: "uv run pytest -q -> 1457 passed; MACOS_APPS_ALLOW_SEND=mail uv run pytest -q -> 1453 passed, 0 failed, 4 skipped; uv run ruff check . -> []; uv run ruff format --check . -> 143 files already formatted; git push -> 60d953c..db3219c refactor/gate-card-2-registration-record -> refactor/gate-card-2-registration-record"
        status: pass
    human_judgment: false

duration: ~95min
completed: 2026-09-25
status: complete
---

# Phase 01 Plan 12: Card 2 Part B — Adapter/permission on every record, notice decided per call, registry becomes the one outbound ledger (GATE-03, GATE-04) Summary

**Every non-meta tool now names its adapter and macOS permission at the registration call site, `notices.UntrustedDataNotice` decides the untrusted-data notice and the #163 backup advisory from that same record per call (fail-safe on an unrecognized name), and `registry.outbound_status()` replaces `tiers.py`'s provisional outbound-capability tracking as the single source doctor reads — resolving RESEARCH Pitfall 3, landed via a genuine RED→GREEN TDD cycle for the notice rewrite, with the published FastMCP tool list byte-identical to `origin/develop@bd6fe53` throughout.**

## Performance

- **Duration:** ~95 min
- **Started:** 2026-09-25 (continuing the lane from 01-11's HEAD, `9bf35f6`)
- **Completed:** 2026-09-25
- **Tasks:** 3 completed (Task 1 tracer, Task 2 tdd, Task 3 auto)
- **Files modified:** 10 across 5 commits

## Accomplishments

- **Task 1 (tracer, GATE-04):** every `@_read_tool`/`@_write_tool`/`@_additive_tool`/`@_send_tool` call site in `server.py` except the five meta tools (`ping`, `now`, `doctor`, `usage`, `audit`) now carries `adapter="<name>"` and `permission=` — 61 tool call sites, values copied verbatim from the pre-refactor `tests/test_tool_annotations.py` hand table (cross-checked against the spike recipe `git show d9926c9`). `tests/test_tool_annotations.py`'s `_ADDITIVE_TOOLS`/`_DESTRUCTIVE_TOOLS`/`_PERMISSION` are now views over `registry.TOOLS` (`{n: r.permission for n, r in registry.TOOLS.items()}`, etc.); `_mail_tools()`'s independent AST oracle now asserts agreement with `registry.by_adapter("mail")`. `tests/test_registry.py` freezes the develop-era literals as `_DEVELOP_ADDITIVE`/`_DEVELOP_DESTRUCTIVE`/`_DEVELOP_PERMISSION` and pins the registry-derived views against them (`test_tier_reproduces_the_develop_era_additive_and_destructive_sets`, `test_permission_reproduces_the_develop_era_hand_map`), plus two new tests: `test_meta_tools_have_no_adapter_permission_or_notice` (ping/now/doctor/usage: adapter `None`, permission `()`, notice `False`; audit: adapter `None`, permission `()`, notice `True`) and `test_every_other_tool_names_its_adapter`.
- **Task 2 (tdd, GATE-04 notice half):** `notices.py::UntrustedDataNotice.on_call_tool` now looks up `registry.TOOLS.get(name)` per call — notice rides unless the record says `notice=False`; the #163 backup advisory rides when the record says `backup_notice=True`; a name absent from the registry (`rec is None`) gets the notice — **fail safe**. `NO_NOTICE_TOOLS` and `_BACKUP_NOTICE_TOOLS` deleted from `notices.py`; the middleware still holds no constructor state, so its `mcp.add_middleware(notices.UntrustedDataNotice())` wiring position in `server.py` is unchanged. `server.py`: `backup_notice=True` added to `move_mail`, `trash_mail`, `mail_undo`'s `_write_tool(...)` calls. `tests/test_server.py`: notice-set references repointed at `registry.no_notice()`; five tests updated/added (`test_no_notice_exempts_exactly_the_meta_tools`, `test_hand_maintained_notice_sets_are_gone`, `test_untrusted_notice_covers_every_registered_tool_except_meta`, `test_unregistered_tool_name_gets_the_notice_fail_safe`, `test_backup_advisory_rides_the_three_recoverable_writes`). `tests/test_registry.py`: `test_no_notice_and_backup_notice_reproduce_the_hand_sets` pins `registry.no_notice() == {"ping","now","doctor","usage"}` and `registry.backup_notice_tools() == {"move_mail","trash_mail","mail_undo"}`.
- **Task 3 (auto, GATE-03 + GATE-04, RESEARCH Pitfall 3):** `registry.py` gains `outbound_status()` — `{"registered": sorted send-tier adapters with `registered=True`, "configured": sorted send-tier adapters for which `tiers.allow_send(adapter)` is true right now}`, a pure view over the send records already sitting in `registry.TOOLS`. `tiers.py` loses `_SEND_ADAPTERS`, `_SEND_REGISTERED`, `admit_send`, `outbound_status` — it is now exactly the pure gate predicates (`read_only()`, `allow_send())` the phase's architecture rule always intended, and its module docstring says so without restating the deleted names literally (to stay clean under the plan's own strict grep). `server.py`'s `_tool` send branch calls `tiers.allow_send(adapter)` directly — no intermediate ledger-writer. `doctor.py`: `from . import deploy, registry, runtime` (dropped `tiers`, unused elsewhere); `_outbound_state()` returns `registry.outbound_status()`. Tests repointed at `registry`: `test_doctor_deploy.py`'s `_gate_off_only` skipif and `test_outbound_status_splits_registered_from_configured`; `test_gate_on_dispatch.py`'s gate-on subprocess snippet imports `registry` instead of `tiers`. `tests/test_import_layers.py` stayed green **unchanged** (no edits needed — `registry.py` importing `tiers.py` introduces no back-edge to `server.py`).
- **Byte-identity re-check (D6):** 01-11's scratch `snapshot_tools.py` (outside the repo) re-run against this plan's final lane HEAD in both default and `MACOS_APPS_ALLOW_SEND=mail` modes, diffed against 01-11's `BASE` captures (`origin/develop@bd6fe53`, detached worktree). Both diffs empty:
  ```
  diff base_default.json lane_default_final2.json  ->  identical (exit 0)
  diff base_send.json    lane_send_final.json       ->  identical (exit 0)
  ```
- **TDD Gate Compliance (Task 2)**: RED commit `1df35ae` added `test_hand_maintained_notice_sets_are_gone` (`tests/test_server.py`) and `test_no_notice_and_backup_notice_reproduce_the_hand_sets` (`tests/test_registry.py`), plus three regression-coverage tests (`test_unregistered_tool_name_gets_the_notice_fail_safe`, `test_backup_advisory_rides_the_three_recoverable_writes`, and the repointed `test_no_notice_exempts_exactly_the_meta_tools`) — verified failing with `uv run pytest tests/test_server.py tests/test_registry.py -q -k "notice or backup_advisory"` → **8 passed, 2 failed** (`test_hand_maintained_notice_sets_are_gone`: `NO_NOTICE_TOOLS`/`_BACKUP_NOTICE_TOOLS` still present; `test_no_notice_and_backup_notice_reproduce_the_hand_sets`: `backup_notice_tools()` empty) BEFORE any implementation change — both failures are exactly the planned behavior. GREEN commit `5fd28ae` rewrote `notices.py` and added `backup_notice=True` to the three `server.py` call sites; the same targeted command plus the full `tests/test_server.py tests/test_registry.py` suite reported **114 passed, 0 failed**. No REFACTOR commit — the GREEN implementation needed no cleanup pass.
- **Verify triple green throughout, both tiers modes** (final lane HEAD, after the db3219c fixup): `uv run pytest -q` → 1457 passed; `MACOS_APPS_ALLOW_SEND=mail uv run pytest -q` → 1453 passed, 0 failed, 4 skipped; `uv run ruff check .` → `[]`; `uv run ruff format --check .` → 143 files already formatted (all four re-confirmed in both modes). `MACOS_APPS_READ_ONLY=1 uv run pytest tests/test_registry.py -q` → 12 passed, 1 pre-existing failure (see Issues Encountered — not caused by this plan).
- Lane pushed twice: `9bf35f6..60d953c` (Tasks 1–3) then `60d953c..db3219c` (the docstring fixup). `git ls-remote --heads origin refactor/gate-card-2-registration-record` confirms one head at `db3219c`. No PR opened — plan 01-13 owns the one card-2 PR. Lane left in place and locked for plan 01-13.

## Task Commits

1. **Task 1: adapter= and permission= on every call site; test_tool_annotations reads the registry** (tracer) — `4d2bd87` (feat)
2. **Task 2 RED: `test_hand_maintained_notice_sets_are_gone` + `backup_notice_tools()` pin, test-only** — `1df35ae` (test) — 8 passed / 2 failed, confirmed before any implementation edit
3. **Task 2 GREEN: `UntrustedDataNotice` reads `notice`/`backup_notice` from `registry.TOOLS`** — `5fd28ae` (feat) — 114 passed, 0 failed
4. **Task 3: `registry.outbound_status()` is the one outbound ledger; `tiers.py` keeps only the gate predicates** — `60d953c` (feat)
5. **Fixup: doctor.py docstring no longer restates the literal `registry.outbound_status()` call** — `db3219c` (fix)

_No plan-metadata commit in the lane — per lane_protocol, this SUMMARY is written to the main checkout, uncommitted; the orchestrator commits it. Base recorded via the ledger: `plan_head_before: 9bf35f6900313bba29c958966dc2daa710a3b4e4`; `commits: 5` measured via `git rev-list --count 9bf35f6..HEAD`._

## Files Created/Modified

- `macos_apps_mcp/server.py` — `adapter=`/`permission=` on 61 non-meta tool call sites; `backup_notice=True` on `move_mail`/`trash_mail`/`mail_undo`; `_tool`'s send branch calls `tiers.allow_send(adapter)` (was `tiers.admit_send`)
- `macos_apps_mcp/registry.py` — new `outbound_status()` view; module docstring unchanged (already accurate)
- `macos_apps_mcp/notices.py` — `UntrustedDataNotice.on_call_tool` reads `registry.TOOLS.get(name)` per call; `NO_NOTICE_TOOLS`/`_BACKUP_NOTICE_TOOLS` deleted
- `macos_apps_mcp/tiers.py` — `_SEND_ADAPTERS`/`_SEND_REGISTERED`/`admit_send`/`outbound_status` deleted; module docstring rewritten
- `macos_apps_mcp/doctor.py` — imports `registry` instead of `tiers`; `_outbound_state()` reads `registry.outbound_status()`
- `tests/test_tool_annotations.py` — three hand tables become registry views; `_mail_tools()` asserts agreement with `registry.by_adapter("mail")`
- `tests/test_registry.py` — develop-era literal pins; `test_meta_tools_have_no_adapter_permission_or_notice`; `test_every_other_tool_names_its_adapter`; `test_no_notice_and_backup_notice_reproduce_the_hand_sets`
- `tests/test_server.py` — notice tests repointed at `registry.no_notice()`; fail-safe and backup-advisory regression tests added
- `tests/test_doctor_deploy.py`, `tests/test_gate_on_dispatch.py` — every outbound-ledger reference repointed at `registry`

## Decisions Made

See `key-decisions` in the frontmatter — copying permission/adapter values verbatim rather than re-deriving them, the TDD investigation into which of Task 2's written tests genuinely drove RED (2 of 10 — the other 8 were already true under the pre-refactor hand-set implementation and are kept as regression coverage, mirroring 01-11's precedent), and the docstring-literal-vs-grep-target fixup caught by re-running the plan's own acceptance criteria before declaring the plan done.

## Deviations from Plan

None — plan executed exactly as written. The one notable addition beyond the plan's literal task list is the `db3219c` fixup commit: two docstrings (in `tiers.py` and `doctor.py`) initially restated, in explanatory prose, the exact literal strings the plan's own acceptance-criteria greps search for — this made the greps fail even though the underlying code change was correct. This is documented as a deviation under Rule 1 (auto-fix bug: a self-inflicted test/grep failure caused by my own docstring wording), caught before finishing the plan, fixed in a small follow-up commit rather than amending the already-landed Task 3 commit.

### Auto-fixed Issues

**1. [Rule 1 - Bug] Docstring prose tripped the plan's own acceptance-criteria greps**
- **Found during:** Task 3, final acceptance-criteria re-verification
- **Issue:** `tiers.py`'s module docstring and `doctor.py`'s `_outbound_state()` docstring explained the change by naming the deleted symbols (`_SEND_ADAPTERS`, `_SEND_REGISTERED`, `admit_send`, `outbound_status`) and the new call (`registry.outbound_status()`) verbatim in prose — which is exactly what the plan's `grep -nE "_SEND_ADAPTERS|_SEND_REGISTERED|def admit_send|def outbound_status" macos_apps_mcp/tiers.py` and `grep -n "registry.outbound_status()" macos_apps_mcp/doctor.py` checks for, so both greps returned unintended matches (a docstring line, not a `def`/call site) even though the actual code was already correct.
- **Fix:** reworded both docstrings to describe the same facts without repeating the literal grep targets.
- **Files modified:** `macos_apps_mcp/tiers.py` (already part of the `60d953c` commit body being reworded before its own commit), `macos_apps_mcp/doctor.py` (separate fixup)
- **Verification:** both greps now return exactly the acceptance criterion's expected line count; full suite re-run green in both modes; tool-list diff re-confirmed empty.
- **Committed in:** `60d953c` (tiers.py, caught before that commit landed) and `db3219c` (doctor.py, caught after)

---

**Total deviations:** 1 auto-fixed (1 self-caught test/grep-compliance bug, no functional code change).
**Impact on plan:** Zero behavioral impact — both fixes were docstring wording only, re-verified with the full test suite and the tool-list byte-identity diff after each.

## Issues Encountered

**Pre-existing test gap, NOT caused by this plan (out of scope, documented, not fixed):** `MACOS_APPS_READ_ONLY=1 uv run pytest tests/test_registry.py -q` reports 12 passed, 1 failed — `test_create_contact_is_logged_with_its_verb` fails with `fastmcp.exceptions.ToolError: Unknown tool: 'create_contact'`. `create_contact` is an additive tool, unregistered under `MACOS_APPS_READ_ONLY=1` (true since 01-09/01-11, unrelated to this plan's adapter=/permission=/notice/backup_notice/outbound-ledger changes); the test was written in 01-11 without a `READ_ONLY`-mode guard. Verified pre-existing by checking out `9bf35f6` (01-11's HEAD, this plan's `plan_head_before`) into a throwaway detached worktree (`/tmp/gsd-01-12-preexisting-check`, removed after the check) and re-running the identical command: same failure, same traceback, at that commit — confirming none of this plan's three tasks introduced or worsened it. Per the executor's scope-boundary rule ("only auto-fix issues DIRECTLY caused by the current task's changes"), this is out of scope for 01-12 and was left untouched. Flagging it here for the phase owner / plan 01-13's code review rather than a separate `deferred-items.md` write, since the lane_protocol's SUMMARY write is the one permitted write outside the lane for this dispatch.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- GATE-04 is now fully closed (both the registration half from 01-11 and the annotation/notice/ledger half from this plan). GATE-03 is closed: `doctor` reads the outbound ledger from below `server.py`, with no import cycle (`tests/test_import_layers.py` unchanged and green).
- Plan 01-13 (card 2's code review + the one PR + merge) has a clean, fully-verified 5-commit branch to review: `refactor/gate-card-2-registration-record`, `9bf35f6..db3219c` ahead of `origin/develop@bd6fe53`. Every task's acceptance criteria and the plan-level `<verification>` re-checked passing on the final HEAD.
- The lane `.worktrees/gate-card-2-registration-record` and branch `refactor/gate-card-2-registration-record` are both still in place, locked, and pushed to `origin`. No PR opened yet; plan 01-13 owns the one card-2 PR + code review + merge.
- The one open, out-of-scope item (`test_create_contact_is_logged_with_its_verb` under `MACOS_APPS_READ_ONLY=1`, see Issues Encountered) is worth a one-line fix in 01-13's code review pass (skip or gate the test under `READ_ONLY`) — it predates this plan and does not block the PR on its own merits, but a reviewer running the exact `MACOS_APPS_READ_ONLY=1 uv run pytest tests/test_registry.py -q` command will see it.
- No changes were made to `.planning/state.json`, `.planning/milestone.lock`, `.gsd/`, `.planning/phases/02.1-*`, or `pyproject.toml`, per the dispatch's explicit constraints. The only git activity in the main checkout was `git fetch`, and one throwaway `git worktree add`/`git worktree remove` pair (at `/tmp/gsd-01-12-preexisting-check`, outside `.planning` and outside the lane) used solely to verify the pre-existing test gap above — no commits, no branch changes, no state files touched in the main checkout.

## Self-Check: PASSED

- `macos_apps_mcp/server.py`, `macos_apps_mcp/registry.py`, `macos_apps_mcp/notices.py`, `macos_apps_mcp/tiers.py`, `macos_apps_mcp/doctor.py`, `tests/test_tool_annotations.py`, `tests/test_registry.py`, `tests/test_server.py`, `tests/test_doctor_deploy.py`, `tests/test_gate_on_dispatch.py`: FOUND in the lane (`.worktrees/gate-card-2-registration-record`) — `[ -f ... ]` confirmed for all ten.
- Commits `4d2bd87`, `1df35ae`, `5fd28ae`, `60d953c`, `db3219c`: FOUND — `git log --oneline --all` in the lane lists all five, in that order.
- `git push` output confirmed: `60d953c..db3219c refactor/gate-card-2-registration-record -> refactor/gate-card-2-registration-record`.
- All Task 1, 2 and 3 acceptance criteria re-verified passing after the fixup (see Accomplishments and the `coverage` block above): the adapter-declared grep, the no-hand-dict grep, the `-k notice` filter, the `NO_NOTICE_TOOLS`/`_BACKUP_NOTICE_TOOLS` grep, the three tiers.py/registry.py/doctor.py greps (each now returning exactly the criterion's expected line count), and both tool-list diffs (default + `MACOS_APPS_ALLOW_SEND=mail`) against `BASE` all returned exactly what the plan specified.
- `uv run pytest -q` and `MACOS_APPS_ALLOW_SEND=mail uv run pytest -q` both exit 0 on the final lane HEAD (`db3219c`); `uv run ruff check .` and `uv run ruff format --check .` both clean in both modes.
- `commits: 5` measured via `git rev-list --count 9bf35f6900313bba29c958966dc2daa710a3b4e4..HEAD` in the lane → `5`, matching the frontmatter. `plan_head_before` recorded as `9bf35f6900313bba29c958966dc2daa710a3b4e4` (01-11's final HEAD, confirmed equal to the lane's own prior-plan commit).

---
*Phase: 01-gate-land-the-spiked-architecture-cuts*
*Completed: 2026-09-25*
