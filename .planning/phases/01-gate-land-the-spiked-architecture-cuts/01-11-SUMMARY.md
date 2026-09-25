---
phase: 01-gate-land-the-spiked-architecture-cuts
plan: 11
subsystem: server-registration
tags: [registry, audit, gate-04, gate-06, tdd, landing]

# Dependency graph
requires:
  - phase: 01-09
    provides: tiers.py (read_only/allow_send/admit_send provisional outbound ledger) and notices.py — the gates this plan's _tool() calls into unchanged
  - phase: 01-10
    provides: origin/develop @ bd6fe53 proven live on the installed dev-build daemon — the lane's cut point
provides:
  - macos_apps_mcp/registry.py — Tier, ToolRecord (name/tier/adapter/permission/audit_verb/notice/backup_notice/snapshot/open_world/registered/fn), TOOLS, add, derive_audit_verb (raises, no "write" fallback), write_tools, snapshot_sources, audit_verbs, no_notice, backup_notice_tools, by_adapter
  - macos_apps_mcp/server.py::_tool(...) — the one registration decorator every tool goes through; _read_tool/_write_tool/_additive_tool/_send_tool are now thin aliases over it (CLAUDE.md's decorator vocabulary stays true)
  - macos_apps_mcp/audit.py::AuditMiddleware(audit_verbs, snapshot_sources) — the verb comes from the registry record, not a name-prefix guess; _audit_op deleted
  - Branch refactor/gate-card-2-registration-record pushed to origin, 3 commits ahead of bd6fe53 — lane stays open for plans 01-12/01-13
affects: [Phase 1 plan 01-12 (card 2 part B: outbound ledger moves from tiers.py into registry.py, delete the provisional block), Phase 1 plan 01-13 (the one card-2 PR + code review + merge)]

# Actuals (#2632)
actuals:
  tokens: 9783
  tasks: 2
  commits: 3
  plan_head_before: bd6fe5357c3ff02b4db2268f8289c82d48cfab8d
confidence_note: "estimate was 90000 tokens (low confidence); actual realized diff for this plan's 3 commits was ~9783 (chars/4 over the bd6fe53..HEAD diff, 39133 chars across 490 insertions/137 deletions in 8 files) — the estimate anticipated more churn than the mechanical per-tool audit= additions and the thin-alias rewrite actually required"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "One registration decorator (_tool) builds one frozen dataclass record (registry.ToolRecord) per tool, stored in registry.TOOLS BEFORE the registered-or-not gate decision runs — a gated-off tool still gets a record with registered=False, never simply absent. Every hand-maintained name set (_WRITE_TOOLS, _SNAPSHOT_SOURCES) becomes a *view* function over that one dict."
    - "A write's audit verb is a per-tool FACT stated once at registration (registry.derive_audit_verb: explicit override > tier==\"send\" -> \"send\" > create/update/delete/complete prefix > TypeError) — never re-derived from the tool name at audit time. No silent generic \"write\" fallback; an unprefixed write that forgets its audit= kwarg fails at import, not silently at runtime."
    - "AuditMiddleware's write-tool set and its audit-verb map are now the SAME dict (audit_verbs): a tool is a write IFF it is a key of that map, so a write can never be tracked without a verb by construction."
    - "Thin decorator aliases over one implementation (_read_tool/_write_tool/_additive_tool/_send_tool as functools-style wrappers around _tool(tier, **kw)) let every existing call site keep its exact shape — only the twelve tools with no create/update/delete/complete prefix needed a one-keyword addition (audit=\"...\")."

key-files:
  created:
    - macos_apps_mcp/registry.py
    - tests/test_registry.py
  modified:
    - macos_apps_mcp/server.py
    - macos_apps_mcp/audit.py
    - tests/test_tool_annotations.py
    - tests/test_mail_cleanup.py
    - tests/test_audit_middleware.py
    - tests/test_audit.py

key-decisions:
  - "GATE-04's registration half only, per the plan's own success_criteria wording: the outbound ledger (_SEND_ADAPTERS/_SEND_REGISTERED/admit_send/outbound_status) stays in tiers.py, provisionally, exactly as plan 01-09 left it and this plan's context explicitly instructed (\"The outbound ledger stays in tiers.py until plan 01-12 moves it into the registry\") — _tool()'s send branch calls tiers.admit_send(adapter) unchanged. GATE-04 is not fully closed until plan 01-12 consolidates that ledger into registry.py."
  - "GATE-06 is fully closed by this plan: audit._audit_op (the create/update/delete prefix table with a silent \"write\" fallback) is deleted outright, not superseded or kept as a comparison oracle — CONTEXT.md's discretion note was explicit that the spike (which keeps _audit_op) is NOT the recipe to follow here."
  - "Kept the four module-level annotation-dict constants (_READ_ANNOTATIONS/_ADDITIVE_ANNOTATIONS/_DESTRUCTIVE_ANNOTATIONS/_SEND_ANNOTATIONS) in server.py even though no decorator body reads them anymore — tests/test_server.py's pre-existing test_send_annotations_are_destructive_and_open_world (a file NOT in this plan's declared <files> list) asserts srv._SEND_ANNOTATIONS's literal shape; registry.py owns its own equivalent _ANNOTATIONS dict (it cannot import server.py, which imports registry — that would be circular), so the two are parallel literals by design rather than one shared source. Verified no drift between them via the byte-identical tool-list diff below (annotations are part of what that diff compares)."
  - "TDD investigation (tdd.md \"If test passes: feature exists or test is wrong. Investigate\"): the plan's action text named test_create_contact_is_logged_with_its_verb as the RED driver (\"watch it fail on the old signature\"), but empirically it already PASSED before any Task 2 implementation change — create_contact's audit verb was already correct even under the OLD audit._audit_op (its create/update/delete prefix match already returned \"create\" for create_contact, and create_contact was already a member of the old _WRITE_TOOLS/new registry.write_tools()). The actual RED driver was test_audit_op_is_gone (assertion failure: _audit_op still present) and the new AuditMiddleware(audit_verbs=...) constructor call sites (TypeError: unexpected keyword argument) — both genuine, intentional failures on the exact planned behavior. test_create_contact_is_logged_with_its_verb was kept as regression coverage for the rewrite (it must keep passing across the _audit_op deletion, which it does) rather than dropped for not RED-failing on its own."

requirements-completed: [GATE-04, GATE-06]

coverage:
  - id: D1
    description: "registry.ToolRecord + one _tool(...) decorator: every tool (read/additive/destructive/send, plus the meta tools ping/now/usage/doctor) is registered through registry.add(ToolRecord(...)) before the registered-or-not gate decision, including gated-off tools (registered=False, never simply absent)"
    requirement: "GATE-04"
    verification:
      - kind: unit
        ref: "tests/test_registry.py#test_fastmcp_lists_exactly_the_registered_records (default in-process + subprocess MACOS_APPS_ALLOW_SEND=mail + subprocess MACOS_APPS_READ_ONLY=1)"
        status: pass
      - kind: unit
        ref: "tests/test_registry.py#test_duplicate_registration_raises"
        status: pass
      - kind: manual_procedural
        ref: "grep -nE \"^_WRITE_TOOLS|^_SNAPSHOT_SOURCES\" macos_apps_mcp/server.py -> no output; grep -c \"registry.add(\" macos_apps_mcp/server.py -> 1; grep -c \"@mcp.tool\" macos_apps_mcp/server.py -> 0"
        status: pass
    human_judgment: false
  - id: D2
    description: "The published FastMCP tool list (names in order, descriptions, annotations, input schemas) is byte-identical before and after this plan's full refactor, in both default and MACOS_APPS_ALLOW_SEND=mail modes — GATE-04's ordering/tampering edge"
    requirement: "GATE-04"
    verification:
      - kind: other
        ref: "scratch snapshot_tools.py (fastmcp Client.list_tools(), JSON, sorted keys) run against origin/develop@bd6fe53 (detached worktree) and against this lane's final HEAD, both modes; diff empty in all four comparisons (2 BASE captures x 2 lane captures)"
        status: pass
    human_judgment: false
  - id: D3
    description: "Every registered write carries its own explicit-or-derived audit verb; no record carries the generic \"write\" bucket; the twelve unprefixed writes (export_mail, save_mail_attachment, mail_reply, move_mail, trash_mail, mail_undo, run_shortcut, safari_open, music_control, play_playlist, set_volume, set_mode) carry the exact verbs CONTEXT.md's discretion note specifies"
    requirement: "GATE-06"
    verification:
      - kind: unit
        ref: "tests/test_registry.py#test_gate06_verbs, #test_no_record_carries_a_generic_write_verb, #test_every_registered_write_has_its_own_verb, #test_unprefixed_write_without_verb_raises"
        status: pass
    human_judgment: false
  - id: D4
    description: "audit._audit_op is gone; AuditMiddleware.__init__(audit_verbs, snapshot_sources) reads the verb from the registry-derived map; a write is trackable only if it is a key of that map (no way for a registered write to exist with a missing verb, since registry.derive_audit_verb raises at import)"
    requirement: "GATE-06"
    verification:
      - kind: unit
        ref: "tests/test_registry.py#test_audit_op_is_gone; tests/test_audit_middleware.py#test_op_comes_from_the_verb_map; tests/test_audit.py#test_audit_op_labels_send_tools_distinctly_from_write (rewritten against registry.TOOLS/audit_verbs())"
        status: pass
      - kind: manual_procedural
        ref: "grep -n \"def _audit_op\" macos_apps_mcp/audit.py -> no output"
        status: pass
    human_judgment: false
  - id: D5
    description: "Calling create_contact through the live MCP client (fake adapter) writes an audit record with tool create_contact and op create"
    requirement: "GATE-06"
    verification:
      - kind: unit
        ref: "tests/test_registry.py#test_create_contact_is_logged_with_its_verb"
        status: pass
    human_judgment: false
  - id: D6
    description: "TDD gate compliance for Task 2: a genuine RED commit (9 real failures against the exact planned behavior — new AuditMiddleware constructor kwarg, _audit_op removal) precedes the GREEN commit that makes them pass, no REFACTOR commit needed (implementation was already minimal)"
    verification:
      - kind: other
        ref: "git log --oneline bd6fe53..HEAD: 32af203 feat (Task 1, tracer), 44bb96b test (RED), 9bf35f6 feat (GREEN); RED-phase pytest output pasted into Task Commits below (9 failed/19 passed) confirmed BEFORE audit.py/server.py wiring changed"
        status: pass
    human_judgment: false
  - id: D7
    description: "uv run pytest, ruff check, ruff format --check all green in default AND MACOS_APPS_ALLOW_SEND=mail modes on the final lane HEAD; lane branch pushed to origin (no PR — plan 01-13 owns the one card-2 PR)"
    requirement: "GATE-13"
    verification:
      - kind: other
        ref: "uv run pytest -q -> 1449 passed; MACOS_APPS_ALLOW_SEND=mail uv run pytest -q -> 1445 passed, 4 skipped; uv run ruff check . -> []; uv run ruff format --check . -> 143 files already formatted (both modes); git ls-remote --heads origin refactor/gate-card-2-registration-record -> one line (9bf35f69...)"
        status: pass
    human_judgment: false

duration: ~70min
completed: 2026-09-25
status: complete
---

# Phase 01 Plan 11: Card 2 Part A — One registration record per tool, audit verbs from the record (GATE-04 registration half, GATE-06) Summary

**A single `registry.ToolRecord` per tool (including gated-off ones) replaces five hand-maintained `server.py` sets, and `AuditMiddleware` now reads a write's audit verb from that record instead of guessing it from the tool name at call time — `audit._audit_op`'s silent `"write"` fallback is gone, landed via a genuine RED→GREEN TDD cycle for the audit rewrite, with the published FastMCP tool list byte-identical to `origin/develop@bd6fe53` throughout.**

## Performance

- **Duration:** ~70 min
- **Started:** 2026-09-25 (lane cut from origin/develop@bd6fe53)
- **Completed:** 2026-09-25
- **Tasks:** 2 completed (Task 1 tracer, Task 2 tdd)
- **Files modified:** 8 (2 new, 6 modified) across 3 commits

## Accomplishments

- **`macos_apps_mcp/registry.py`** (new): `Tier = Literal["read","additive","destructive","send"]`; `ToolRecord` (frozen dataclass: `name, tier, adapter, permission, audit_verb, notice, backup_notice, snapshot, open_world, registered, fn`, properties `is_write`/`annotations`); `TOOLS: dict[str, ToolRecord]`; `add(rec)` (raises `TypeError` on a duplicate name — GATE-04 adjacency edge); `derive_audit_verb(name, tier, explicit)` (read → `None`, explicit wins, send → `"send"`, else the create/update/delete/complete prefix, else `TypeError` — no `"write"` fallback, per CONTEXT.md's explicit departure from the spike recipe); derived views `write_tools()`, `snapshot_sources()`, `audit_verbs()` (all filtered to `registered=True`, per the plan text — a deliberate difference from the spike's unfiltered `audit_verbs()`), `no_notice()`, `backup_notice_tools()`, `by_adapter()`.
- **`macos_apps_mcp/server.py`**: one `_tool(tier, *, adapter=None, permission=(), audit=None, notice=True, backup_notice=False, snapshot=None, open_world=False, guard=True)` decorator computes `registered` (read → always; additive/destructive → `not tiers.read_only()`; send → `tiers.admit_send(adapter)`, after composing the #179 mail autosave doc exactly as before), calls `registry.add(ToolRecord(...))` **before** deciding registration, then registers with FastMCP only when `registered` — a gated-off tool returns the plain function, still recorded. `_read_tool`, `_write_tool`, `_additive_tool`, `_send_tool(adapter, ...)` are now thin aliases over `_tool(...)` (usable bare or with keywords) — every existing call site keeps its exact shape. Twelve writes with no create/update/delete/complete prefix now carry an explicit `audit=` verb: `export_mail`→`export`, `save_mail_attachment`→`save`, `mail_reply`→`reply`, `move_mail`→`move`, `trash_mail`→`trash`, `mail_undo`→`undo`, `run_shortcut`→`action`, `safari_open`→`open`, `music_control`→`control`, `play_playlist`→`play`, `set_volume`→`set`, `set_mode`→`set`. `ping`/`now`/`usage` now go through `@_read_tool(guard=False, notice=False)` (no native call); `doctor` keeps its guard, adds `notice=False`. `_WRITE_TOOLS`/`_SNAPSHOT_SOURCES` deleted; the `AuditMiddleware` wiring reads `registry.audit_verbs()`/`registry.snapshot_sources()`.
- **`macos_apps_mcp/audit.py`**: `_audit_op` (the create/update/delete prefix table + hand-listed extras + silent `"write"` fallback) deleted outright. `AuditMiddleware.__init__(audit_verbs: Mapping[str, str], snapshot_sources)` replaces `write_tools: set[str]`; `on_call_tool` checks `tool in self._audit_verbs` and writes `"op": self._audit_verbs[tool]` — a tool is a write IFF it is a key of the verb map, so a write can never exist without a verb by construction (GATE-06).
- **Test files repointed at the registry** (per the plan's exact mapping): `tests/test_tool_annotations.py` (`test_every_write_tool_is_audit_classified` now asserts `registry.snapshot_sources()`/`registry.write_tools()`), `tests/test_mail_cleanup.py` (`test_mail_duplicates_is_registered_read_only` now asserts `registry.write_tools()`), `tests/test_audit_middleware.py` (`test_server_snapshot_sources_are_derived_and_satisfy_the_protocol` now asserts `registry.snapshot_sources()`), `tests/test_audit.py` (`test_audit_op_labels_send_tools_distinctly_from_write` rewritten against `registry.TOOLS`/`registry.audit_verbs()` instead of the now-deleted `au._audit_op`).
- **`tests/test_registry.py`** (new, 8 tests): `test_fastmcp_lists_exactly_the_registered_records` (in-process default check + two subprocess checks — `MACOS_APPS_ALLOW_SEND=mail` and `MACOS_APPS_READ_ONLY=1` — asserting the live FastMCP list equals exactly the registered records in every mode, and that gated-off tools are still recorded with `registered=False`); `test_duplicate_registration_raises`; `test_unprefixed_write_without_verb_raises`; `test_no_record_carries_a_generic_write_verb`; `test_gate06_verbs` (the twelve explicit-verb tools); `test_every_registered_write_has_its_own_verb`; `test_audit_op_is_gone`; `test_create_contact_is_logged_with_its_verb` (through the live MCP `Client`, with `srv._contacts` faked and `au.audit_write` captured).
- **GATE-04 ordering check**: a scratch `snapshot_tools.py` (outside the repo, per the lane protocol) captured the FastMCP tool list — name, description, annotations, input schema, in order — via `Client(srv.mcp).list_tools()`, run against `origin/develop@bd6fe53` in a detached worktree (BASE) and against this lane's final `HEAD`, in both default and `MACOS_APPS_ALLOW_SEND=mail` modes. Command and output:
  ```
  diff base_default.json lane_default_final.json   ->  identical (exit 0)
  diff base_send.json    lane_send_final.json      ->  identical (exit 0)
  ```
- **TDD Gate Compliance (Task 2)**: RED commit `44bb96b` added/rewrote `test_op_comes_from_the_verb_map` (`tests/test_audit_middleware.py`), `test_audit_op_is_gone`/`test_every_registered_write_has_its_own_verb`/`test_create_contact_is_logged_with_its_verb` (`tests/test_registry.py`), and `test_audit_op_labels_send_tools_distinctly_from_write` (`tests/test_audit.py`) — verified failing with `uv run pytest tests/test_registry.py tests/test_audit_middleware.py tests/test_audit.py -q` → **9 failed, 19 passed** (8× `TypeError: AuditMiddleware.__init__() got an unexpected keyword argument 'audit_verbs'` + 1× `AssertionError` on `test_audit_op_is_gone`) BEFORE any implementation change. GREEN commit `9bf35f6` then rewrote `audit.py`'s `AuditMiddleware` and `server.py`'s wiring; the same command reported **28 passed, 0 failed**. No REFACTOR commit — the GREEN implementation needed no cleanup pass.
- **Verify triple green throughout, both tiers modes**: `uv run pytest -q` → 1449 passed; `MACOS_APPS_ALLOW_SEND=mail uv run pytest -q` → 1445 passed, 0 failed, 4 skipped; `uv run ruff check .` → `[]`; `uv run ruff format --check .` → 143 files already formatted (all four checks re-run and confirmed clean under `MACOS_APPS_ALLOW_SEND=mail` too).
- Lane pushed: `git push -u origin HEAD` succeeded; `git ls-remote --heads origin refactor/gate-card-2-registration-record` → one line (`9bf35f6900313bba29c958966dc2daa710a3b4e4`). No PR opened — plan 01-13 owns the one card-2 PR. Lane left in place and locked for plans 01-12/01-13.

## Task Commits

1. **Task 1: registry.ToolRecord + one `_tool(...)` decorator with thin aliases; hand-kept sets become views** (tracer) — `32af203` (feat)
2. **Task 2 RED: `AuditMiddleware(audit_verbs=...)` + `_audit_op` removal, test-only** — `44bb96b` (test) — 9 failed / 19 passed, confirmed before any implementation edit
3. **Task 2 GREEN: `AuditMiddleware` reads its verb from `registry.audit_verbs()`** — `9bf35f6` (feat) — 28 passed, 0 failed

_No plan-metadata commit in the lane — per lane_protocol, this SUMMARY is written to the main checkout, uncommitted; the orchestrator commits it. Base recorded via the ledger: `plan_head_before: bd6fe5357c3ff02b4db2268f8289c82d48cfab8d`; `commits: 3` measured via `git rev-list --count bd6fe53..HEAD`._

## Files Created/Modified

- `macos_apps_mcp/registry.py` (new) — `Tier`, `ToolRecord`, `TOOLS`, `add`, `derive_audit_verb`, `write_tools`, `snapshot_sources`, `audit_verbs`, `no_notice`, `backup_notice_tools`, `by_adapter`
- `macos_apps_mcp/server.py` — `_tool(...)` decorator (new); `_read_tool`/`_write_tool`/`_additive_tool`/`_send_tool` (now thin aliases); twelve `audit=` additions; `ping`/`now`/`usage`/`doctor` registration kwargs; `_WRITE_TOOLS`/`_SNAPSHOT_SOURCES` deleted; `AuditMiddleware` wiring reads the registry
- `macos_apps_mcp/audit.py` — `_audit_op` deleted; `AuditMiddleware.__init__(audit_verbs, snapshot_sources)`; `on_call_tool` reads `self._audit_verbs[tool]`
- `tests/test_registry.py` (new) — 8 tests, see Accomplishments
- `tests/test_tool_annotations.py`, `tests/test_mail_cleanup.py`, `tests/test_audit_middleware.py`, `tests/test_audit.py` — repointed at the registry views / rewritten against the new `AuditMiddleware` signature

## Decisions Made

See `key-decisions` in the frontmatter — the outbound-ledger sequencing (unchanged, deferred to 01-12 exactly as the plan's own context specified), the `_audit_op` removal (not superseded, per CONTEXT.md), keeping the four annotation-dict constants in `server.py` for an existing out-of-scope test rather than editing it, and the TDD investigation into why `test_create_contact_is_logged_with_its_verb` did not itself drive RED (it already held true under the old `_audit_op` prefix fallback — kept as regression coverage instead of dropped).

## Deviations from Plan

None — plan executed exactly as written. The one notable divergence from the plan's literal action text (see key-decisions) is a TDD investigation outcome, not a deviation: the plan named `test_create_contact_is_logged_with_its_verb` as the test that should RED-fail, but it already passed under the pre-Task-2 code (a pre-existing correct behavior, verified empirically before touching `audit.py`); the actual RED evidence came from `test_audit_op_is_gone` and the `AuditMiddleware(audit_verbs=...)` constructor call sites, which is the behavior Task 2 genuinely changes. This is documented, not silently substituted.

## Issues Encountered

None. No auth gates (no external service in scope). No node-repair needed — every acceptance criterion and `<verify>` command passed on first or second attempt (the send-mode `test_fastmcp_lists_exactly_the_registered_records` assertion needed one fix to be robust to `MACOS_APPS_ALLOW_SEND=mail` already being set in-process, matching `test_tool_annotations.py`'s existing convention — caught by running the plan-mandated `MACOS_APPS_ALLOW_SEND=mail uv run pytest -q` check myself before considering the task done, not left for a later gate).

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- GATE-06 is fully closed by this plan. GATE-04 is closed for its **registration half** only, per the plan's own success_criteria wording — the outbound ledger (`_SEND_ADAPTERS`/`_SEND_REGISTERED`/`admit_send`/`outbound_status`) is still in `tiers.py`, provisionally, exactly as this plan's context specified it should remain until plan 01-12.
- Plan 01-12 (card 2 part B) has explicit, concrete work already named by the prior plan chain: move the outbound ledger from `tiers.py` into `registry.py`, delete the provisional block, and repoint `_tool()`'s `tier == "send"` branch and `doctor`'s outbound read at the registry instead of `tiers.admit_send`/`tiers.outbound_status`.
- The lane `.worktrees/gate-card-2-registration-record` and branch `refactor/gate-card-2-registration-record` are both still in place, locked, and now pushed to `origin` (3 commits ahead of `bd6fe53`) — plans 01-12 and 01-13 continue in this exact lane, per the dispatch's lane_protocol. No PR opened yet; plan 01-13 owns the one card-2 PR + code review + merge.
- No changes were made to `.planning/state.json`, `.planning/milestone.lock`, `.gsd/`, `.planning/phases/02.1-*`, or `pyproject.toml`, per the dispatch's explicit constraints.

## Self-Check: PASSED

- `macos_apps_mcp/registry.py`, `tests/test_registry.py`: FOUND in the lane (`.worktrees/gate-card-2-registration-record`) — `[ -f ... ]` confirmed for both.
- Commits `32af203`, `44bb96b`, `9bf35f6`: FOUND — `git log --oneline bd6fe53..HEAD` in the lane lists all three, in that order.
- `git ls-remote --heads origin refactor/gate-card-2-registration-record` re-confirmed: one line, `9bf35f6900313bba29c958966dc2daa710a3b4e4`.
- All Task 1 and Task 2 acceptance criteria re-verified passing (see Accomplishments and the coverage block above): the four `server.py` greps, the `test_registry.py` full run and the two `-k` filters, `grep -n "def _audit_op"` (empty), the two `test_registry.py -k` filters for Task 2, and both tool-list diffs (default + `MACOS_APPS_ALLOW_SEND=mail`) against BASE all returned exactly what the plan specified.
- `uv run pytest -q` and `MACOS_APPS_ALLOW_SEND=mail uv run pytest -q` both exit 0 on the final lane HEAD; `uv run ruff check .` and `uv run ruff format --check .` both clean in both modes.
- `commits: 3` measured via `git rev-list --count bd6fe5357c3ff02b4db2268f8289c82d48cfab8d..HEAD` in the lane → `3`, matching the frontmatter. `plan_head_before` recorded as `bd6fe5357c3ff02b4db2268f8289c82d48cfab8d` (the lane's cut point from `origin/develop`, confirmed equal to `git rev-parse origin/develop` at lane-creation time).

---
*Phase: 01-gate-land-the-spiked-architecture-cuts*
*Completed: 2026-09-25*
