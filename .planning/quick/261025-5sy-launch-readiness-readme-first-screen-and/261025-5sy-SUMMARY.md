---
phase: quick-261025-5sy
plan: 01
subsystem: docs
tags: [readme, credits, launch-readiness, provenance]
requires: []
provides:
  - README first screen for new visitors (pitch, What you can ask, Safety and privacy, First 5 minutes, Why not apple-mcp?)
  - CREDITS.md apple-mail-mcp entry corrected to prior art (no code reused)
affects: [README.md, CREDITS.md]
key-files:
  modified: [README.md, CREDITS.md]
decisions:
  - "Provenance Branch A: the Mail adapter was written independently; apple-mail-mcp is prior art, no code reused"
metrics:
  tasks: 2
  files: 2
status: complete
actuals:
  tasks: 2
  commits: 4
plan_head_before: d4769dac5c0fdb570547953f2e0a29562e940aca
plan_head_after: 21434d310a1d64b01b11237ae116066c65243164
completed: 2026-10-25
---

# Phase quick-261025-5sy Plan 01: Launch-readiness README first screen and CREDITS provenance Summary

The README first screen now describes the server for a stranger with mechanism-only safety claims, and CREDITS.md states that apple-mail-mcp is prior art with no code reused.

## Task 1: README first screen (commits 9e17de6, 93ed20b)

- 9e17de6 rewrote everything above `## Tools` (100 lines, ceiling 100). The tail from `## Tools` is byte-identical to the base.
- 93ed20b holds the orchestrator's fixes from the multi-AI review:
  - `run_shortcut`, `safari_open` and the send tools are named as the paths that act past the Mac.
  - Full Disk Access is described as a manual grant.
  - `doctor` shows Automation as unprobed until `request=True`.
  - Audit before-state exists only for updates and deletes by id.
  - Gmail label moves are named as refused routes.
  - The pointer and dry-run overclaims were narrowed.
- Rejected review points: change of `dry_run` defaults, a Python version floor, and the old `mac-mcp` listing tool names.

## Task 2: CREDITS.md (commits 9bb22ee, 21434d3)

Branch A applied: written independently, no code reused (owner decision, see evidence below).

- The apple-mail-mcp entry moved into "Prior art — referenced & learned from (no code reused)".
- The entry names what was learned: the `message://` deeplink encoding, the needs-response and awaiting-reply triage ideas, mailbox creation as a tool, and its issue #58 (orphan watcher and child cleanup). It ends with "No code reused."
- The community contributors keep their links (ahharvey #66, Brendan DeBeasi #51 and #49, elfensky #76), credited for the ideas their pull requests carried. The "credited in the ported files" promise is gone.
- Section heading `## Code we build on / will port` is now `## Code we build on` (holds osxphotos). The intro tense and the License notes paragraph are in present tense: no source is copied from any listed project. The griches no-licence sentence and the FastMCP/PyObjC sentence stay.

### Provenance evidence

A verbatim line comparison of the fork elfensky/apple-mail-mcp (branch `working`, commit 59b1a54, 2,003 distinct non-trivial Python lines) against `macos_apps_mcp/` (7,285 lines) found 5 shared lines, all stock idioms:

- `set AppleScript's text item delimiters to ","` and the `""` form
- `has_attachments=has_attachments,`
- `if (count of matches) is 0 then`
- `ctype = part.get_content_type()`

Three function names are shared (`get_needs_response`, `get_awaiting_reply`, `create_mailbox`) with different implementations. The fork builds one AppleScript per account and ranks by question marks in subjects. macos-apps-mcp reads Mail's unified inbox and the Envelope Index and classifies in pure Python (`adapters/mail_triage.py`). The feature ideas and the `message://` encoding recipe (commit 2ea3c28, "the patrickfreyer recipe") came from the fork. The code did not.

## Verification (Task 2)

- Gate commands from the plan: stale-text grep empty, all four PR links, griches and osxphotos present, only README.md and CREDITS.md differ from the base outside `.planning`.
- `uv run ruff check .`: All checks passed.
- `uv run ruff format --check .`: 129 files already formatted.
- `uv run pytest -q`: 2614 passed, 102 deselected. The flaky `test_report_stays_under_token_budget` (#464) did not fail in this run.

## Deviations from Plan

- Commit message differs from the plan's `docs(quick-261025-5sy): CREDITS apple-mail-mcp provenance`. The orchestrator specified `docs(credits): apple-mail-mcp is prior art — the Mail adapter reuses no code` and the trailer `Co-Authored-By: Claude Opus 5.5`.
- Branch A was applied from the orchestrator's prompt, which also asked for the triage and mailbox-creation ideas to be named in the entry.

## Deferred

- Review of Task 2 (21434d3): fork PR states corrected (#66/#76 merged upstream, #49/#51 closed unmerged); issue #58 linked to patrickfreyer explicitly; the basis of "no copied code" stated; the bundled-licence gap filed as #471 (PyObjC and bpylist2 ship no licence text in the signed .app).

- Issue template: left to Phase 05.3. Issue #465 owns `gh issue create --web`.
- Flaky test `tests/test_doctor.py::test_report_stays_under_token_budget` fails only when PIDs have 5 digits. Tracked as open issue #464 (Phase 05.2). Not caused by this plan.
- An outdated third-party listing of the old name `mac-mcp` exists at mcprepository.com. Claim or update it in the registry week.
- From the plan output spec: joshrutkowski/orchard appear in a `mail_drafts.py` comment as idea sources but not in CREDITS.md. Owner decides whether they belong there. Do a PyPI render check after the next release.

## Known Stubs

None.

## Self-Check: PASSED

- CREDITS.md, README.md, this SUMMARY: found.
- Commits 9e17de6, 93ed20b, 9bb22ee, 21434d3: ancestors of HEAD.
