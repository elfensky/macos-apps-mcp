---
phase: 01-gate-land-the-spiked-architecture-cuts
plan: 13
subsystem: server-registration
tags: [registry, dry-run, gate-05, gate-13, tdd, landing, pr]

# Dependency graph
requires:
  - phase: 01-11
    provides: macos_apps_mcp/registry.py (ToolRecord, TOOLS, add, derived views) and the one `_tool(...)` registration decorator every tool goes through
  - phase: 01-12
    provides: adapter=/permission=/backup_notice= on every call site; registry.outbound_status() as the one outbound ledger; the fully-verified, pushed 5-commit lane HEAD (db3219c) this plan continued from
provides:
  - registry.ToolRecord.removes_content (GATE-05, D-04) — "removes or replaces content"; _tool(..., removes_content=False) stores removes_content or name.startswith("delete_"), so a delete_*-named tool joins the class even when its own call site forgets the flag
  - registry.removes_content_tools() — the fail-closed view every dry-run-default check walks (all records, registered or not)
  - Published dry_run defaults flip false -> true on delete_event, delete_draft, delete_note (D-01); update_note gains dry_run: bool = True with a read-only current-vs-new preview that makes no Notes write (D-02); move_mail/trash_mail/mail_undo now carry removes_content=True explicitly
  - CHANGELOG.md [Unreleased] -> Changed entry recording the four dry_run contract changes
  - Card 2 (GATE-03/04/05/06, plans 01-11 + 01-12 + this plan) merged to origin/develop as one rebase-merged PR (#219, 8885ad0) — lane and branch removed
affects: [Phase 1 plan 01-14 (post-card-2 daemon check; removal of the .claude/worktrees/ spike worktrees), Phase 2 (GATE-07 — MACOS_APPS_READ_ONLY=1 green — the 12 pre-existing failures this plan proved unchanged, not fixed, are that phase's job)]

# Actuals (#2632)
actuals:
  tokens: 7182
  tasks: 3
  commits: 6
  plan_head_before: db3219c63e795fc46a14284953a37b3955355be2
confidence_note: "estimate was 75000 tokens (low confidence); actual realized diff for this plan's 6 commits was ~7182 (chars/4 over the post-rebase 68fd24d..8885ad0 diff on develop, 28727 chars across 374 insertions/34 deletions in 8 files) — the estimate anticipated more churn than the mechanical removes_content field addition, the three dry_run default flips, and update_note's preview actually required. plan_head_before is the ORIGINAL lane-local hash (db3219c, before gh pr merge --rebase rewrote every commit); the rebase-merge's equivalent base on develop is 68fd24d (same commit content, new hash) — commits: 6 is measured against that post-rebase equivalent (git rev-list --count 68fd24d..8885ad0), since the lane is now deleted and db3219c no longer exists as an ancestor of develop's linear history."

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "A registration-record field can compute a UNION with a structural naming rule at the builder (_tool(..., removes_content=False) stores removes_content or name.startswith('delete_')), and the fail-closed test that walks the class DELIBERATELY re-applies the same naming rule independently rather than trusting the stored field alone — so a bug in the builder's union logic cannot silently hide a delete_*-named tool from the check. Two places state the same rule on purpose; that duplication IS the mitigation, not an oversight to clean up."
    - "A dry-run preview that legitimately needs to READ (not just refuse) states that explicitly in the docstring and in code, distinct from the outbound '#no native call at all' rule: NotesAdapter._update_preview calls _read_title_by_id and get_bodies (both reads) but never runtime.body_file or the _UPDATE_NOTE osascript template (the write). Two tests enforce the distinction with a run_osascript fake that raises ONLY when the write template is named, returning '' harmlessly for any other (read-fallback) call."
    - "Adapters: thin public methods delegate to _private_helpers() (CLAUDE.md convention) — update()'s dry_run branch was extracted into NotesAdapter._update_preview(ident, data) once the inline version grew past ~25 lines, found and fixed in this plan's own Standards-axis code-review pass before the PR was opened."

key-files:
  created: []
  modified:
    - macos_apps_mcp/registry.py
    - macos_apps_mcp/server.py
    - macos_apps_mcp/adapters/notes.py
    - tests/test_registry.py
    - tests/test_server.py
    - tests/test_notes.py
    - tests/test_audit.py
    - CHANGELOG.md

key-decisions:
  - "TDD RED-first via git checkout -- <files> rather than git stash: Task 1 and Task 2 are tdd=\"true\"; git stash is prohibited in worktree mode (shared refs/stash across sibling worktrees). Saved the drafted implementation as a patch file in the scratchpad, ran `git checkout -- <files>` to revert to lane HEAD, wrote and ran the RED tests against the pre-implementation code, committed RED, then `git apply`'d the saved patch for GREEN. This produced genuine RED evidence (6/10 and 9/10 target-test failures respectively, all on the exact planned behavior — missing field/attribute or unflipped default), not narrated RED."
  - "Fixed the EXTRA ITEM (orchestrator-mandated, not in the original PLAN.md task list): under MACOS_APPS_READ_ONLY=1, card 2's own new tests introduced two regressions beyond develop's pre-existing 12 (GATE-07, Phase 2's scope). test_audit.py::test_audit_op_labels_send_tools_distinctly_from_write read three write-tool verbs through registry.audit_verbs(), which filters to registered=True and KeyErrors under READ_ONLY — rewritten to read registry.TOOLS[name].audit_verb directly, since the test's INTENT is verb derivation, not registration gating (a different, already-covered concern). test_registry.py::test_create_contact_is_logged_with_its_verb calls create_contact through a live MCP Client; create_contact is unregistered under READ_ONLY, so the call can't reach it at all — skipped under READ_ONLY with a stated reason, mirroring test_doctor_deploy.py's _gate_off_only convention. Verified byte-identical against the ro-develop.txt baseline afterward: exactly the same 12 failing test names, no more, no fewer."
  - "Standards-axis self-review finding, fixed before opening the PR: NotesAdapter.update()'s dry_run branch (title/body read, truncation check, envelope build) was inlined and had grown to ~50 lines including the docstring — past this file's own established 'thin public method delegates to _private_helpers()' pattern (create(), delete()). Extracted to _update_preview(ident, data); update() is now a two-branch dispatcher. No behavior change, confirmed by the unchanged test suite (1471 passed both before and after)."
  - "Could not spawn parallel sub-agents for the code-review pass (single-agent lane dispatch) — ran the Standards axis and then the Spec axis myself, sequentially, reading the full plan-range diff (bd6fe53..HEAD, 17 files, ~1224/-425 lines) directly rather than delegating to the code-review skill's normal two-sub-agent fan-out."

requirements-completed: [GATE-05, GATE-13]

coverage:
  - id: D1
    description: "registry.ToolRecord.removes_content + registry.removes_content_tools(): the class is a record fact, a delete_*-named tool joins it automatically even when its call site forgets the flag, and a registry test fails closed (sorted offender list) for any tool in the class whose dispatched fn lacks a dry_run=True default"
    requirement: "GATE-05"
    verification:
      - kind: unit
        ref: "tests/test_registry.py#test_content_removing_tools_default_to_dry_run, #test_dry_run_rule_catches_offenders, #test_removes_content_class_is_exactly_the_named_tools, #test_unrelated_write_tools_are_not_in_the_removes_content_class"
        status: pass
      - kind: manual_procedural
        ref: "Manually flipped delete_event's default back to False; test_content_removing_tools_default_to_dry_run failed and named exactly ['delete_event']; reverted and re-ran the full suite green (1464 passed at that point)"
        status: pass
    human_judgment: false
  - id: D2
    description: "delete_event, delete_draft, delete_note default to dry_run=True as published tools (D-01); a bare call previews and changes nothing"
    requirement: "GATE-05"
    verification:
      - kind: unit
        ref: "tests/test_server.py#test_delete_event_bare_call_previews, #test_delete_note_bare_call_previews, #test_delete_draft_bare_call_previews"
        status: pass
      - kind: manual_procedural
        ref: "grep -nE \"def (delete_event|delete_draft|delete_note)\\(\" -A2 macos_apps_mcp/server.py -> all three show dry_run: bool = True"
        status: pass
    human_judgment: false
  - id: D3
    description: "update_note gains dry_run (default True); the preview shows current title/body size against the new ones, reads Notes but makes no Notes write (no _UPDATE_NOTE call, no body_file call), flags a truncated current body, and fails exactly as the real update does for an empty id, a folder argument, or an unknown id"
    requirement: "GATE-05"
    verification:
      - kind: unit
        ref: "tests/test_notes.py#test_update_dry_run_returns_would_update_preview_and_writes_nothing, #test_update_dry_run_flags_a_truncated_current_body, #test_update_dry_run_no_truncation_notice_when_body_fits, #test_update_dry_run_unknown_id_raises_naming_the_id, #test_update_dry_run_refuses_folder_before_any_native_call, #test_update_dry_run_rejects_empty_id"
        status: pass
      - kind: unit
        ref: "tests/test_server.py#test_update_note_bare_call_previews, #test_update_note_tool_dispatches"
        status: pass
    human_judgment: false
  - id: D4
    description: "CHANGELOG [Unreleased] records the dry-run contract change (all four tools named) so the next release notes carry it"
    verification:
      - kind: manual_procedural
        ref: "git diff origin/develop -- CHANGELOG.md (pre-merge) showed one added ### Changed entry under ## [Unreleased] naming delete_event, delete_draft, delete_note and update_note"
        status: pass
    human_judgment: false
  - id: D5
    description: "The published FastMCP tool list differs from BASE (origin/develop@bd6fe53) only by the four intended dry_run schema/docstring changes, in both default and MACOS_APPS_ALLOW_SEND=mail modes"
    requirement: "GATE-05"
    verification:
      - kind: other
        ref: "01-11's snapshot_tools.py re-run against this plan's final lane HEAD (0fa6111) in both modes, diffed against 01-11's BASE captures (origin/develop@bd6fe53, detached worktree): both diffs show only delete_draft/delete_event/delete_note's default+docstring and update_note's new dry_run property+docstring — nothing else"
        status: pass
    human_judgment: false
  - id: D6
    description: "MACOS_APPS_READ_ONLY=1 fails on exactly develop's pre-existing 12 tests — card 2's own new tests introduced no additional READ_ONLY regressions"
    verification:
      - kind: other
        ref: "MACOS_APPS_READ_ONLY=1 uv run pytest -q -p no:randomly -> 12 failed, 1458 passed, 1 skipped, 80 deselected; diffed byte-identical (sorted FAILED names) against the ro-develop.txt baseline captured before this lane"
        status: pass
    human_judgment: false
  - id: D7
    description: "TDD gate compliance: both tdd=\"true\" tasks (Task 1's removes_content/D-01, Task 2's update_note preview/D-02) show a genuine RED commit (failures on the exact planned behavior, produced by reverting the drafted implementation via git checkout -- before writing tests) preceding a GREEN commit that makes them pass; no REFACTOR commit needed for either (a separate, later refactor commit came from the code-review pass, not the TDD cycle itself)"
    verification:
      - kind: other
        ref: "git log --oneline db3219c..0fa6111 (lane, pre-rebase): test(01-13) RED (6/10 target tests failed, AttributeError/AssertionError on the exact planned field+default) -> feat(01-13) GREEN (121 passed) for Task 1; test(01-13) RED (9/10 target tests failed, TypeError on the exact planned dry_run kwarg) -> feat(01-13) GREEN (200 passed) for Task 2; fix(01-13) (READ_ONLY scope guard, orchestrator extra item) -> refactor(01-13) (code-review finding)"
        status: pass
    human_judgment: false
  - id: D8
    description: "Card 2 is on origin/develop by one rebase-merged PR (plans 01-11, 01-12, 01-13); CI green; a code-review pass (Standards then Spec, run sequentially since no sub-agent dispatch was available) found and fixed one Standards-axis issue before merge and no open Spec-axis issue; lane and branch removed"
    requirement: "GATE-13"
    verification:
      - kind: other
        ref: "gh pr view 219 --json state,mergedAt,mergeCommit -> {\"state\":\"MERGED\",\"mergeCommit\":{\"oid\":\"8885ad068791ddcc3f8e7dbb80c793d4188ed747\"}}; gh pr checks 219 green both before and after the review-driven refactor commit; git worktree list / git branch -a show no gate-card-2-registration-record lane or branch remaining"
        status: pass
    human_judgment: false

duration: ~55min (approximate — no persisted start timestamp survives across the per-call fresh-shell Bash environment; estimated from the first RED commit's timestamp back through the required_reading volume, plus the two CI waits, the manual two-axis review and the merge/cleanup/journal steps that followed the last commit)
completed: 2026-09-25
status: complete
---

# Phase 01 Plan 13: Card 2 Part C — Dry-run defaults are correct by construction (GATE-05); card 2 landed (GATE-03/04/05/06, PR #219) Summary

**`delete_event`/`delete_draft`/`delete_note` now default `dry_run=true` and `update_note` gains a read-only current-vs-new preview, both enforced by a registry test that fails closed for any new content-removing tool — landed together with plans 01-11 and 01-12 in one rebase-merged PR (#219, `8885ad0` on `develop`), after fixing two `MACOS_APPS_READ_ONLY` regressions and one Standards-axis code-review finding.**

## Performance

- **Duration:** ~55 min (see frontmatter note on how this was estimated)
- **Completed:** 2026-09-25
- **Tasks:** 3 completed (Task 1 tracer/tdd, Task 2 auto/tdd, Task 3 auto — landing)
- **Files modified:** 8 across 6 commits (this plan's own range); card 2 as a whole (01-11+01-12+01-13) is 17 files across 13 commits, merged as one PR

## Accomplishments

- **`registry.ToolRecord.removes_content: bool`** (GATE-05, D-04) — `_tool(..., removes_content=False)` stores `removes_content or name.startswith("delete_")`, so a `delete_*`-named tool joins the "removes or replaces content" class automatically even when its own call site forgets the flag. New view `registry.removes_content_tools()` walks **every** record (registered or not) — a gated-off `delete_*` tool must still default `dry_run=True` on its underlying function, so it's correct the instant a gate reopens it.
- **`tests/test_registry.py`**: `test_content_removing_tools_default_to_dry_run` (walks the class, asserts `inspect.signature(rec.fn).parameters["dry_run"].default is True`, sorted-offender failure message — GATE-05's ordering edge); `test_dry_run_rule_catches_offenders` (the rule's own fail-closed proof, fed two synthetic records — GATE-05's empty edge: one with no `dry_run` param at all, one with a `False` default, both caught); `test_removes_content_class_is_exactly_the_named_tools` (exactly the 7 tools D-01/D-02/D-03 name — 6 after Task 1, 7 once Task 2 adds `update_note`); `test_unrelated_write_tools_are_not_in_the_removes_content_class` (D-03: `update_event`/`update_reminder`/`complete_reminder`/`update_mail_status`/`run_shortcut` never join).
- **D-01**: `delete_event`, `delete_draft`, `delete_note`'s published `dry_run` default flips `False` → `True`; docstrings state the new default and that `dry_run=false` performs the delete. `move_mail`/`trash_mail`/`mail_undo` (already `True`) now carry `removes_content=True` explicitly.
- **D-02**: `NotesAdapter.update(..., *, dry_run: bool = False)` now returns a `dict` always (matching `delete()`'s pattern — the real path builds a `Pointer` and calls `.as_dict()`). `dry_run=True` delegates to the new `_update_preview(ident, data)` helper (extracted during the code-review pass): reads the current title (`_read_title_by_id`) and body (`get_bodies`), returns `{"dry_run": True, "would_update": {"id", "current": {"title", "body_chars"[, "body_truncated"]}, "new": {"title", "body_chars"}}}` — no `_UPDATE_NOTE` call, no `body_file` call (asserted directly via a `run_osascript` fake that raises only when the write template is named). An unknown id raises `ValueError` naming it; an empty id or a non-`None` folder raise the same `ValueError` the real update does (shared validation, runs before the `dry_run` branch in both paths). `server.py`'s `update_note` gains `dry_run: bool = True`, `removes_content=True`, and forwards `dry_run` through.
- **CHANGELOG.md** `[Unreleased]` → `### Changed`: one entry naming all four dry-run contract changes.
- **Tool-list byte-identity** (GATE-04/05 ordering/tampering edge): 01-11's `snapshot_tools.py` scratch script re-run against this plan's final HEAD in both default and `MACOS_APPS_ALLOW_SEND=mail` modes, diffed against `origin/develop@bd6fe53` — the ONLY differences are the four intended `dry_run` default/schema/docstring changes.
- **Fail-closed proof, done and reverted**: flipping `delete_event`'s default back to `False` made `test_content_removing_tools_default_to_dry_run` fail and name exactly `delete_event`; reverted, full suite re-confirmed green.
- **READ_ONLY scope guard (orchestrator extra item, not fixing GATE-07 — just not growing its debt)**: card 2's own new tests introduced two `MACOS_APPS_READ_ONLY=1` regressions beyond develop's pre-existing 12. `test_audit.py::test_audit_op_labels_send_tools_distinctly_from_write` read three write-tool verbs through `registry.audit_verbs()` (filtered to `registered=True`, so it `KeyError`s under `READ_ONLY`) — rewritten to read `registry.TOOLS[name].audit_verb` directly, since the test's intent is verb *derivation*, not registration *gating*. `test_registry.py::test_create_contact_is_logged_with_its_verb` calls `create_contact` through a live MCP `Client`; the tool is unregistered under `READ_ONLY`, so the call can't reach it — skipped under `READ_ONLY` with a stated reason (mirrors `test_doctor_deploy.py`'s `_gate_off_only` convention). `MACOS_APPS_READ_ONLY=1 uv run pytest -q -p no:randomly` now fails on **exactly** develop's pre-existing 12 — diffed byte-identical (sorted `FAILED` names) against the `ro-develop.txt` baseline.
- **Card 2 landed** (Task 3, D-07): pushed, PR #219 opened against `develop` (title `refactor: one registration record per tool; dry-run defaults and audit verbs from it (gate card 2, GATE-04/05/06)`), `gh pr checks --watch --required` green. A two-axis code review was run **sequentially by this executor** (no sub-agent dispatch available in a single-agent lane): the Standards pass found one finding (see Deviations) and fixed it before merge; the Spec pass (against plans 01-11/01-12/01-13 + GATE-03/04/05/06) found no open issue — two intentional, pre-existing, CONTEXT.md-sanctioned deviations from REQUIREMENTS.md's loose prose (`admit_send` eliminated rather than moved, per RESEARCH Pitfall 3; "every destructive tool" narrowed to the precise "removes or replaces content" class, per D-03) are noted but not defects. Re-verified green (local triple + CI) after the fix, then `gh pr merge --rebase --delete-branch` — `MERGED`, merge commit `8885ad068791ddcc3f8e7dbb80c793d4188ed747`.

## Task Commits

Lane-local hashes (the lane is deleted; these are pre-rebase — see Files Created/Modified for the post-rebase equivalents on `develop`):

1. **Task 1 RED**: `e80b609` (test) — GATE-05 fail-closed dry-run-default rule, three delete tools' bare call must preview — 6 failed / 4 passed, confirmed before any implementation edit
2. **Task 1 GREEN**: `8bb330b` (feat) — `removes_content` on the record, fail-closed D-04 test, D-01 dry-run default flips — 1464 passed
3. **Task 2 RED**: `23f76a3` (test) — `update_note`'s read-only dry-run preview (D-02) — 9 failed / 1 passed, confirmed before any implementation edit
4. **Task 2 GREEN**: `3ee0e9a` (feat) — `update_note`'s read-only dry-run preview (D-02); CHANGELOG records the contract change — 1471 passed
5. **Task 3 fix**: `5e87040` (fix) — keep two GATE-06 tests correct under `MACOS_APPS_READ_ONLY` (GATE-07 scope guard) — 1471 passed, READ_ONLY set byte-identical to develop's 12
6. **Task 3 refactor**: `0fa6111` (refactor) — extract `NotesAdapter._update_preview` — thin public method, per code review — 1471 passed

Post-rebase equivalents on `develop` (same content, `gh pr merge --rebase` hashes): `b8498b9`, `131452c`, `32ba8b7`, `bb82004`, `258c734`, `8885ad0`.

_No separate plan-metadata commit — per lane_protocol, this SUMMARY is written to the main checkout, uncommitted; the orchestrator commits it. `commits: 6` measured via `git rev-list --count 68fd24d..8885ad0` on `develop` post-merge (`68fd24d` is the rebased equivalent of the lane's `plan_head_before`, `db3219c` — the lane no longer exists to re-derive this from its own sentinel file)._

## Files Created/Modified

- `macos_apps_mcp/registry.py` — `ToolRecord.removes_content` (new field); `removes_content_tools()` (new view, all records)
- `macos_apps_mcp/server.py` — `_tool(..., removes_content=False)`; `delete_draft`/`delete_event`/`delete_note` default `dry_run=True`; `move_mail`/`trash_mail`/`mail_undo` carry `removes_content=True`; `update_note` gains `dry_run: bool = True`, `removes_content=True`
- `macos_apps_mcp/adapters/notes.py` — `NotesAdapter.update(..., *, dry_run: bool = False) -> dict`; new private helper `_update_preview(ident, data)`
- `tests/test_registry.py` — `test_content_removing_tools_default_to_dry_run`, `test_dry_run_rule_catches_offenders`, `test_removes_content_class_is_exactly_the_named_tools`, `test_unrelated_write_tools_are_not_in_the_removes_content_class`; `test_duplicate_registration_raises`'s hand-built `ToolRecord` fixed for the new field; `test_create_contact_is_logged_with_its_verb` skipped under `READ_ONLY`
- `tests/test_server.py` — `test_delete_event_bare_call_previews`, `test_delete_note_bare_call_previews`, `test_delete_draft_bare_call_previews`, `test_update_note_bare_call_previews`; existing delete/update dispatch tests updated to pass `dry_run=False` explicitly where they test the mutating path; `_FakeSource.update`/`_FakeWriter` fakes updated for the new `dry_run` kwarg and dict-return contract
- `tests/test_notes.py` — six new `update()` dry-run tests (preview shape, truncation flag on/off, unknown id, folder refusal, empty id)
- `tests/test_audit.py` — `test_audit_op_labels_send_tools_distinctly_from_write` reads verbs off `registry.TOOLS[name].audit_verb` directly (READ_ONLY-safe)
- `CHANGELOG.md` — `[Unreleased]` → `### Changed` entry

## Decisions Made

See `key-decisions` in the frontmatter — the `git checkout --`-based (not `git stash`) TDD RED-first workflow, the orchestrator's extra READ_ONLY-scope-guard item, the Standards-axis `_update_preview` extraction, and running the code-review skill's two axes sequentially myself in the absence of sub-agent dispatch.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `test_duplicate_registration_raises`'s hand-built `ToolRecord` needed the new `removes_content` field**
- **Found during:** Task 1 GREEN verification
- **Issue:** the test constructs a `ToolRecord` directly (not through `_tool`), so adding a new required dataclass field broke it with `TypeError: missing 1 required positional argument`.
- **Fix:** added `removes_content=False` to the hand-built record.
- **Files modified:** `tests/test_registry.py`
- **Verification:** full suite green after (121 passed in `test_registry.py`+`test_server.py`)
- **Committed in:** `8bb330b` (Task 1 GREEN commit)

**2. [Orchestrator extra item, not a plan Rule 1-3 but the same auto-fix shape] Two `MACOS_APPS_READ_ONLY=1` regressions from this card's own new tests**
- **Found during:** Task 3 prep (explicitly required by the dispatch before opening the PR)
- **Issue:** `test_audit_op_labels_send_tools_distinctly_from_write` and `test_create_contact_is_logged_with_its_verb` both assumed write/additive tools are registered — false under `READ_ONLY`.
- **Fix:** see Accomplishments' "READ_ONLY scope guard" bullet.
- **Files modified:** `tests/test_audit.py`, `tests/test_registry.py`
- **Verification:** `MACOS_APPS_READ_ONLY=1 uv run pytest -q -p no:randomly` byte-identical to the `ro-develop.txt` baseline (12 failed, same names)
- **Committed in:** `5e87040`

**3. [Standards-axis code-review finding, Rule 1-shaped] `NotesAdapter.update()`'s inline dry_run branch exceeded the file's established function-length/delegation convention**
- **Found during:** Task 3's Standards-axis review pass (before opening the PR)
- **Issue:** the dry_run branch (title/body read, truncation check, envelope build) was inlined, growing `update()` past ~50 total lines including its docstring — this file's own convention is "thin public methods delegate to `_private_helpers()`" (`create()`, `delete()` both follow it).
- **Fix:** extracted to `_update_preview(ident, data)`; `update()` is now a two-branch dispatcher.
- **Files modified:** `macos_apps_mcp/adapters/notes.py`
- **Verification:** `uv run pytest -q` unchanged at 1471 passed before and after; `uv run ruff check .`/`format --check .` clean
- **Committed in:** `0fa6111`

---

**Total deviations:** 3 auto-fixed (1 blocking test-construction fix, 1 orchestrator-mandated scope guard, 1 self-found Standards-axis refactor).
**Impact on plan:** All three necessary for correctness/consistency/code quality. No scope creep — none touched files outside this plan's declared `<files>` list or the orchestrator's explicit extra item.

## Issues Encountered

None beyond the three deviations above, all resolved within the plan. No auth gates. No node-repair needed — every acceptance criterion and `<verify>` command passed after the deviations above were applied, each caught by re-running the plan's own acceptance criteria/verify commands before moving on, not left for a later gate.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- GATE-05 is fully closed by this plan: every "removes or replaces content" tool defaults `dry_run=True`, enforced by a registry test that fails closed for a new tool (proven manually with a real revert-and-check). GATE-13's landing procedure (D-07) is satisfied for card 2 as a whole: one PR, CI green, local triple green, code review clean, rebase-merged.
- Card 2 (GATE-03/04/05/06) is fully on `develop` at `8885ad0`. `.worktrees/gate-card-2-registration-record` and `refactor/gate-card-2-registration-record` (local and remote) are both gone.
- **Not closed here, deliberately**: GATE-07 (`MACOS_APPS_READ_ONLY=1` green) is Phase 2's scope. This plan only proved card 2 did not grow that 12-test debt — it did not shrink it.
- Plan 01-14 (per the dispatch's own notes) owns the post-card-2 dev-build daemon check and removing the `.claude/worktrees/` spike worktrees (`spike/arch-review-1` through `-9`, none touched by this plan) — both untouched here, as instructed.
- No changes were made to `.planning/state.json`, `.planning/milestone.lock`, `.gsd/`, `.planning/phases/02.1-*`, or `pyproject.toml`. The only git activity in the main checkout was `git fetch`, the post-merge `git worktree unlock`/`remove`, `git branch -D`, and `git fetch --prune` — no commits, no direct edits.

## Self-Check: PASSED

- `macos_apps_mcp/registry.py`, `macos_apps_mcp/server.py`, `macos_apps_mcp/adapters/notes.py`, `tests/test_registry.py`, `tests/test_server.py`, `tests/test_notes.py`, `tests/test_audit.py`, `CHANGELOG.md`: all present on `develop` at `8885ad0` — `git show 8885ad0:<path>` confirmed non-empty for all eight.
- Commits `b8498b9`, `131452c`, `32ba8b7`, `bb82004`, `258c734`, `8885ad0` (post-rebase, on `develop`): `git log --oneline --all` confirms all six, in that order, each with the expected commit-type prefix (test/feat/test/feat/fix/refactor).
- `gh pr view 219 --json state,mergedAt,mergeCommit` → `{"state":"MERGED","mergeCommit":{"oid":"8885ad068791ddcc3f8e7dbb80c793d4188ed747"}}`, matching `git rev-parse origin/develop`.
- All Task 1/2/3 acceptance criteria re-verified passing on the final lane HEAD before push: the `grep` for the three delete defaults, the `-k content_removing_tools_default_to_dry_run or dry_run_rule_catches_offenders` filter, `update_note` present in `removes_content_tools()`, the CHANGELOG diff, both tool-list byte-identity diffs, and the READ_ONLY 12-failure byte-identical comparison.
- `uv run pytest -q` → 1471 passed; `MACOS_APPS_ALLOW_SEND=mail uv run pytest -q` → 1467 passed, 0 failed, 4 skipped; `uv run ruff check .` → clean; `uv run ruff format --check .` → clean — all four re-confirmed on the final lane HEAD immediately before `git push`, and CI (`gh pr checks --required`) green on that same HEAD.
- `commits: 6` measured via `git rev-list --count 68fd24d..8885ad0` on `develop` post-merge → `6`, matching the frontmatter. `plan_head_before` recorded as `db3219c63e795fc46a14284953a37b3955355be2` (the lane-local hash this plan actually started from; its post-rebase equivalent is `68fd24d`, noted in `confidence_note` since the lane no longer exists to re-derive this from its own sentinel file).
- `git worktree list` and `git branch -a` (main checkout) confirm no `gate-card-2-registration-record` worktree or `refactor/gate-card-2-registration-record` branch remains, local or remote.

---
*Phase: 01-gate-land-the-spiked-architecture-cuts*
*Completed: 2026-09-25*
