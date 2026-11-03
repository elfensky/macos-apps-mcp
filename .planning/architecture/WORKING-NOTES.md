# Architecture working notes — 2026-11-04

This is a working record, not display-page content. It deliberately has no `kind` frontmatter.
Only the eight `macos-apps-mcp-*.md` files belong in the architecture publication input.

## Scope and evidence

- Worktree: `t3-d09dce7f`; branch: `docs/current-architecture`.
- Baseline: `f91dbed988745ff2d7847907a53d8927b7b2809f`.
- Source claims were checked against the current Python modules, lock, build scripts, tests, and relevant phase records.
- The parent publication audit was read at its supplied worktree path. Its #553 status is superseded by the merged baseline.
- GitHub metadata read on 2026-11-04 confirmed #554 OPEN at `67cfb879407baac3ec12a39d4a0099f17cc1725c`, with no merge date.
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

- Prepared current architecture sources with explicit audit and deployment limits — `elfensky/macos-apps-mcp`, architecture draft PR #personal.
- Architecture evidence distinguishes native-free new-message previews from existing-draft and reply-all reads — architecture working notes #personal.
