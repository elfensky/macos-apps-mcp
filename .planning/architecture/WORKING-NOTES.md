# Architecture working notes — 2026-11-04

This is a working record, not display-page content. It deliberately has no `kind` frontmatter.
Only the eight `macos-apps-mcp-*.md` files belong in the architecture publication input.

## Scope and evidence

- Worktree: `t3-d09dce7f`; branch: `docs/current-architecture`.
- Baseline: `f91dbed988745ff2d7847907a53d8927b7b2809f`.
- Source claims were checked against the current Python modules, lock, build scripts, tests, and relevant phase records.
- The parent publication audit was read at its supplied worktree path. Its #553 status is superseded by the merged baseline.
- An initial GitHub snapshot on 2026-11-04 observed #554 OPEN at `67cfb879407baac3ec12a39d4a0099f17cc1725c`, with no merge date.
- The same read confirmed the latest release is `v0.15.1`, published `2026-10-25T21:04:13Z`.
- These API reads retrieved repository metadata, not personal app data or web-page bodies.
- User review remains pending. No `as_of` or publication date was invented.
- Global planning files, generated maps, DESIGN.md, application code, and publisher code remain outside this change.

## Findings for parent integration

- `AuditMiddleware` appends after the action. `audit_write()` returns false on failure, and native actions can complete without persisted records.
- Mail recovery also ignores the boolean result of its plan/outcome audit attempts. Its backup-before-action ordering does not guarantee a durable plan.
- #552 preserves diagnostics after startup repair failure and preserves completed-action receipts after later directory changes.
- #553 inventories site-packages distribution notices. It does not inventory the interpreter or all native libraries.
- The repository instruction's native-free outbound preview rule is broader than current source behavior.
  `stored_draft()` and `reply_all_to()` read Mail data before `deliver()` returns a preview.
  `tests/test_mail_outgoing.py` explicitly expects a stored-draft read. New-message and forward previews remain native-free.
  Architecture prose records this distinction; no behavior or global instruction was changed.
- PROJECT.md contains aspirational blanket audit/recovery claims. The architecture states the implemented limits without widening this worker's ownership.
- The source contract requires no renderer dependency. Stable component filenames map manually to the proposed nested HTML paths.

## Validation and exploratory limits

- Initial sandbox GitHub metadata reads failed: `error connecting to api.github.com`.
  The same read-only commands succeeded with approved network access.
- Initial `uv sync --locked` failed: `Could not acquire lock`; `Operation not permitted (os error 1)` under the shared uv cache.
  The approved retry created this worktree's environment successfully with Python 3.14.5 and the existing lock.
- Markdown validation passed: eight curated notes, 114 relative links, and seven diagram components matching the component metadata.
  All source links resolve inside this checkout. Each note has an eli14 paragraph and pending review/publication metadata.
  Descriptive prose passed a 25-word sentence check. This temporary validation added no repository script or dependency.
- Source spot checks passed for the five locked SDK/library versions, ten app families, transport limits, native worker, dashboard controls,
  startup warning, bundle gates, and action-before-audit order. This is static source evidence, not device acceptance.
- `uv run pytest`: `3167 passed, 105 deselected, 7 warnings in 65.40s (0:01:05)` on Python 3.14.5.
  The seven warnings are upstream `MCPDeprecationWarning` messages for the logging capability deprecated by SEP-2577.
- `uv run ruff check .`: `All checks passed!`
- `uv run ruff format --check .`: `141 files already formatted`.
- `git diff --check`: passed. No runtime or dependency files changed.
- No native integration tests, device probes, app installation, restart, signing, release, or publication are part of this task.

## Journal handoff

The vault-journal skill's helper creates another worktree. The task prohibits that action and live-vault edits.
The parent receives the journal bullet instead of an executed helper call.

- Prepared current architecture sources with explicit audit and deployment limits — elfensky/macos-apps-mcp#555 #personal.
- Architecture evidence distinguishes native-free new-message previews from existing-draft and reply-all reads — architecture working notes #personal.

## Independent review corrections

- Claude reviewed `e1a979c` against `f91dbed`. It found no blocking defect, one factual error, and minor metadata/wording issues.
- The permanent-operation fidelity gate is inactive: `PERMANENT_OPS` is empty and no tool exposes `allow_lossy`. The architecture now states this.
- Backup fidelity uses the exact `unknown` value, with its inspection meaning stated separately from per-target outcome status.
- Component diagram IDs now match the hyphenated component metadata. No renderer or build behavior is claimed.
- The earlier localization snapshot is historical. #554 merged as `18dcbf6594bbd62330f71c89376a54155dda1d63` on 2026-11-04.
  The architecture branch is rebased onto that revision and describes the merged read behavior, with #556 and device limitations explicit.
- `source_revision` is the inspected code baseline. Publication must derive its own page commit from Git; the two must not be confused.
- The parent journal entry already landed through vault MR !2388. No duplicate entry is needed.
- Corrected combined-baseline validation: 3340 passed, 105 integration tests deselected, seven upstream warnings, 58.36 seconds.
  Ruff lint and 142-file formatting passed. Eight notes, 115 relative links, seven exact component IDs and frontmatter checks passed.


## Grant-chip source integration

- #557 merged as `4a7c26287b108c9c81f42db0bdf5280ed537e986` after independent review and its requested refusal correction.
  The reviewed correction passed 211 focused tests and 3461 full-suite tests; corrected-head CI passed all six checks.
- Overview and operator-controls notes now describe the completed Health snapshot, time, TCC fallback and explicit probe-refusal precedence.
  Their source revision identifies the merged implementation. Their metadata distinguishes the earlier architecture review from this source-checked wording update.
  Real macOS 27 acceptance remains pending. No installed-build or publication claim is added.

## First publication — 2026-11-04

- MR !2394 moved the vault enrollment to repository mode and removed its duplicate roadmap notes. The live vault was fast-forwarded before upload.
- The strict source gate passed in the ordinary checkout at `93c7f09`, before fact collection and again under the publication lock.
- Four untracked planning files were preserved outside the checkout: a dead-process lock, two generated bytecode files, and a redundant newline-only placeholder.
  The gate and full-folder hash were not weakened. No tracked source was removed for publication.
- The plain HTML bundle contains the roadmap, eight architecture pages and six old-path redirects. Local validation checked 122 internal paths and fragments.
- The folder upload completed at `2026-11-04T01:34:18Z`. All 15 live HTML paths matched the local bytes; project identity and the source hash matched metadata.
- The archive helper excludes this home-only service by policy. No browser, external asset, framework or server was needed.
- Publication metadata records this event separately from source review and installed-device acceptance. The published commit remains derived from Git.
- The publication-record branch passed 3461 tests, with 105 integration tests deselected and seven upstream warnings. Ruff lint and formatting passed.
  Twelve changed Markdown files passed frontmatter, private-path and relative-link checks; 156 relative links resolved.
- GSD reported two directories for phase 05.4. The older directory held only a tracked newline placeholder, with no evidence or inbound links.
  Removing it cleared the warning. Analysis still reported 20 phases, nine historical closures, 93 plans and 92 summaries.
