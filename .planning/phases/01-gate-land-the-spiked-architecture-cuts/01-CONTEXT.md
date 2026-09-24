# Phase 1: Gate — Land the Spiked Architecture Cuts - Context

**Gathered:** 2026-09-25
**Status:** Ready for planning

<domain>
## Phase Boundary

Land seven cards from the 2026-08-28 spiked architecture review on current `develop`, in the
order 1 → 7 → 5 → 2, with the Mail-scoped cards 3, 4 and 9 in parallel:

- **Card 1**: the native seam fails closed for every adapter, `doctor` and `shortcuts`' `tracked_run`.
- **Card 7**: `runtime.py` split — the EventKit cluster moves to its own module.
- **Card 5**: tier policy and the untrusted-data notice leave `server.py`; the `doctor → server` import cycle is removed.
- **Card 2**: one registration record per tool; dry-run defaults and audit verbs come from it.
- **Card 3**: shared envelope fixture with the native and the Sequoia shape.
- **Card 4**: `recoverable()` owns its preflight.
- **Card 9**: script-timeout tripwire only, plus the `_DEDUPE` fix.

Requirements: GATE-01, 02, 03, 04, 05, 06, 08, 09, 10, 13. The phase adds no tool features. The one
behaviour change for callers is the dry-run defaults (D-01, D-02).

Not in this phase: `MACOS_APPS_READ_ONLY=1` green (GATE-07), doctor tests off live `pgrep`
(GATE-11) and the full device sweep (GATE-12). They are Phase 2. Card 6 (MailFilter) and card 8
(MailAdapter pass-throughs) do not land.

</domain>

<decisions>
## Implementation Decisions

### Dry-run defaults (GATE-05)
- **D-01:** `delete_event`, `delete_draft` and `delete_note` default to `dry_run=True`. Today all
  three default to `False`. PROJECT.md says `delete_note` "has none". That is stale: it has
  `dry_run: bool = False` today. — **Reversibility:** costly — this changes the published tool
  contract. A caller that calls `delete_event(id)` gets a preview instead of a delete. The change
  goes into the release notes of the next release.
- **D-02:** `update_note` gets `dry_run: bool = True`. The preview shows the current title and body
  size against the new ones, and makes no Notes write. A read is allowed in this preview. (The
  "no native call" rule applies to outbound dry runs only.) Reason: `update_note` replaces the
  full title and body. Its audit before-state is the title only (`notes.snapshot`,
  `macos_apps_mcp/adapters/notes.py:681`), so an overwritten body cannot be restored from the
  audit log. — **Reversibility:** costly — this is the same contract change as D-01.
- **D-03:** No other write tool changes its default. `update_event`, `update_reminder` and
  `complete_reminder` keep one-call semantics (no dry run). Their before-state Pointer is enough to
  restore them by hand. `update_mail_status` and `run_shortcut` stay `False`. `move_mail`,
  `trash_mail`, `mail_undo` and the send tools stay `True`.
- **D-04:** The registration record declares the class "removes or replaces content". The
  registry test fails when a tool in that class does not default to `dry_run=True`. The test must
  fail closed for a new tool: any tool named `delete_*` is in the class even when its record
  forgets the flag. (Phase 3's `delete_reminder`, REM-01, must be caught.) The mechanism belongs to
  the planner.

### Release and daemon rebuilds (GATE-13, success criterion 6)
- **D-05:** Cut a release from current `develop` before card 1 starts, per `docs/RELEASING.md`.
  This ships the Sequoia plane (#199/#201/#204) to the installed daemon. Today the daemon runs
  0.10.1 (build `5f2cfb1`, 2026-08-23) without it. This release is the first plan of the phase.
  It includes the two-file bump, the `--no-ff` cut to `main`, the tag, then build → sign →
  notarize → staple → install → kickstart, and the `doctor().version` + `doctor().build` proof.
  The release tag is also the byte-identity baseline for success criterion 5 ("`develop` before
  the cut").
- **D-06:** During the gate, the daemon checks after card 5 and after card 2 use **dev builds**
  from `develop`. They get no version bump and no tag. A check passes when `doctor().build`
  reports the built sha and one outbound dry run still reports gated correctly. Success criterion
  6 says "the new version". That phrase means "the new build sha" here. The next release comes
  after Phase 2 closes (GATE-12 device sweep green).

### Landing flow (GATE-13)
- **D-07:** Each card gets one PR against `develop`, and the PR is rebase-merged. Claude merges its
  own PR when all of these are true:
  - CI is green.
  - `uv run pytest`, `uv run ruff check .` and `uv run ruff format --check .` pass locally.
  - A code-review pass finds no open issue.

  The owner reviews after the merge. Each merge gets a one-line summary to the owner. The next
  sequential card branches from `develop` after the previous merge.
- **D-08:** The work stops for the owner at device steps only:
  1. The pre-gate release and daemon install (D-05). This step also pushes `main` and a tag.
  2. Card 7's `uv run pytest -m integration -k "request_access or create_event or create_reminder"`.
  3. Card 4's verification on the scratch mailbox `Personal/macos-apps-mcp-test` with the Mail
     watchdog running.
  4. The dev-build daemon checks after card 5 and after card 2 (D-06).
- **D-09:** After the last card merges, delete every `spike/arch-review-*` branch, including the
  non-landing 6, 6-baseline, 8 and 8-alt. Also remove their worktrees under `.claude/worktrees/`
  (`git worktree remove`). New lanes for this phase use `.worktrees/` (PR #209 convention).

### Claude's Discretion
- **Re-land method:** Redo each card's change on current `develop` and use the spike diff as the
  recipe. Do not cherry-pick or rebase the spike commit. A moved function body is copied from
  current `develop`, never from the spike. The spikes are 17 commits behind, and the Sequoia plane
  changed `doctor.py`, `server.py`, `runtime.py`, `contracts.py`, `mail.py`, `mail_index.py` and
  `tests/conftest.py`. Check "bodies byte-identical" against `develop`.
- **Audit verbs (GATE-06):** Use short effect verbs in the style of the existing `send`, `open` and
  `reply`. Examples: `move_mail`→`move`, `trash_mail`→`trash`, `mail_undo`→`undo`,
  `export_mail`→`export`, `save_mail_attachment`→`save`, music/volume/mode tools→`play`/`set`.
  `create_contact` must be logged at all. The verb comes from the registration record and is
  required for every write. Spike 2's `audit="write"` placeholder is replaced, and the
  `_audit_op` fallback to `"write"` is removed. The audit record already carries `tool`
  (`audit.py:273`), so the verb is a filter category.
- **Card 2 decorator names:** Keep `@_read_tool`, `@_write_tool`, `@_additive_tool` and
  `@_send_tool` as thin aliases over one `_tool(...)` record, as spike 2 did. Then CLAUDE.md,
  `.claude/CLAUDE.md` and `tests/test_tool_annotations.py` stay true.
- **Card 3 Sequoia coverage:** The shared `fake_envelope` fixture runs every `query_*` executor test
  against both shapes: native, and Sequoia (`sequoiaify_envelope` + the #201 sidecar).
  `HEADER_FINGERPRINT` covers every column an executor reads, and a test asserts that coverage.
- **Card 4 baseline:** Generate the dry-run envelope and osascript argv baseline again from the
  pre-cut `develop` (the D-05 release tag). Do not reuse the spike's
  `tests/spike_arch4_old_dry_run.json`: it was taken at d9ac75f, and #201 changed `mail.py` after
  it. Rename the `test_spike_arch4_*` files to names without "spike".
- **`_DEDUPE` (card 9):** Raise the script `with timeout` backstop to at least the host cap (900 s).
  Do not lower the host cap.
- **Release version number (D-05):** Use 0.11.0, because there are `feat` commits since v0.10.1.
- Small fixes: rewrite `check_batch`'s refusal text so it does not claim a backup for
  `update_status`, and remove the stale `daemon.py` comment.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Scope and requirements
- `.planning/ROADMAP.md` §"Phase 1: Gate" — goal and six success criteria. Read criterion 6 with D-06.
- `.planning/REQUIREMENTS.md` — GATE-01…06, 08, 09, 10, 13 (Phase 1). GATE-07/11/12 are Phase 2.
- `.planning/PROJECT.md` §Key Decisions, §Context — the spiked review, the gate-first rule, and #180 (new `mail_index` reads written single, tested through the envelope fixture).
- `.planning/codebase/CONCERNS.md` — each card's finding with file:line evidence and the spike's fix approach.

### Architecture rules
- `CLAUDE.md` §"Architecture (don't drift)" — thin dispatch, one module per adapter, `run_native()` on one worker, three registration-time tiers, no deadline on the shim↔daemon hop.
- `DESIGN.md` — design rationale. Card 7's spike edits it.
- `.planning/codebase/ARCHITECTURE.md`, `.planning/codebase/TESTING.md` — module map and test seams.

### Mail (cards 3, 4, 9)
- `docs/mail-applescript-facts.md` — read FIRST before any Mail change. Device-verified traps. The scratch mailbox is `Personal/macos-apps-mcp-test` (line ~231).
- `.planning/debug/mail-index-schema-sequoia.md`, `.planning/design/mail-sequoia-id-sidecar.md` — the Sequoia shape and the #201 sidecar that card 3's fixture must carry.

### Release and daemon (D-05, D-06)
- `docs/RELEASING.md` — two-file version bump, `--no-ff` cut, `doctor().version` + `doctor().build` proof.
- `docs/DAEMON.md` — build → sign → notarize → staple → install → kickstart.

### Primary sources (recipes, never merged as-is)
- `spike/arch-review-1-native-seam` @ 6d50996
- `spike/arch-review-7-runtime-split` @ 5db5fc5
- `spike/arch-review-5-tier-policy` @ f442d49
- `spike/arch-review-2-registration-record` @ afd7f34 + d9926c9
- `spike/arch-review-3-fake-envelope-fixture` @ 1bc0ed0
- `spike/arch-review-4-recoverable-preflight` @ f7186d5
- `spike/arch-review-9-script-preamble` @ 38e149f. The wrapper was withdrawn; only the tripwire lands.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `tests/test_native_seam.py`: it globs `adapters/` for Mail modules only today (`_MAIL_MODULES`, asserts ≥ 3). Card 1 widens it to every `adapters/*.py` + `doctor.py` with `tracked_run`.
- `tests/conftest.py:70` `sequoiaify_envelope`: the Sequoia-shape converter for card 3's fixture.
- `tests/test_mail_search.py:30` `_fake_envelope`: the private fixture that card 3 moves to `tests/envelope.py`.
- `macos_apps_mcp/adapters/mail_index.py:26` `HEADER_FINGERPRINT`: extend it to every column a `query_*` reads.
- `macos_apps_mcp/audit.py:185` `_audit_op`: the prefix map with a silent `"write"` fallback that card 2 replaces.
- `contracts.deletion_result()`: the existing dry-run envelope (`{"dry_run": True, "would_delete": …}`). D-01 reuses it. D-02's `update_note` preview follows the same shape.
- `doctor().build` (#143): the build-sha proof that D-06 relies on.

### Established Patterns
- Capability gating happens at registration. A gated-off tool is absent. Card 2's record must include gated-off tools before the gate runs.
- Seam calls are qualified (`from .. import runtime`, then `runtime.run_osascript(...)`, #176). Card 1 applies this to every adapter.
- Every Mail write is verified by running it on device and inspecting the result. A green suite has passed a broken forward before.

### Integration Points
- `macos_apps_mcp/server.py` (1380 lines): cards 2 and 5, and card 7's imports.
- `macos_apps_mcp/runtime.py` (744 lines): card 7.
- `macos_apps_mcp/doctor.py:302` `from . import server`: the package's only import cycle, which card 5 removes.
- `macos_apps_mcp/adapters/mail.py`, `mail_recover.py`: cards 4 and 9. Both touch `mail.py`, so the card that merges second rebases.

</code_context>

<specifics>
## Specific Ideas

- The installed daemon is 0.10.1, build `5f2cfb1` from 2026-08-23. It does not have #199/#201/#204 until the D-05 release is installed.
- The spikes are **17** commits behind `develop` today. ROADMAP.md and STATE.md still say 16.
- The D-05 release tag does two jobs: it ships the Sequoia plane, and it fixes the pre-cut byte-identity baseline.

</specifics>

<deferred>
## Deferred Ideas

- **Full-body snapshot for `update_note`**: this makes a note edit recoverable, not only
  previewable. The `notes.snapshot` docstring calls it "a non-breaking later enhancement".
  Backlog, not this phase.
- **Card 6, MailFilter**: land it only when a 13th Mail search filter is added (CONCERNS.md).
- **Card 8, MailAdapter pass-throughs**: withdrawn at the review. Not revisited.

</deferred>

---

*Phase: 01-gate-land-the-spiked-architecture-cuts*
*Context gathered: 2026-09-25*
