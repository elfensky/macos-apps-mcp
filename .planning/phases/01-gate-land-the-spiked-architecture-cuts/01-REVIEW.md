---
phase: 01-gate-land-the-spiked-architecture-cuts
reviewed: 2026-09-26T00:00:00Z
depth: standard
files_reviewed: 63
files_reviewed_list:
  - .worktrees/.daemon_probe.py
  - CHANGELOG.md
  - DESIGN.md
  - macos_apps_mcp/adapters/calendar.py
  - macos_apps_mcp/adapters/contacts.py
  - macos_apps_mcp/adapters/mail.py
  - macos_apps_mcp/adapters/mail_index.py
  - macos_apps_mcp/adapters/mail_recover.py
  - macos_apps_mcp/adapters/messages.py
  - macos_apps_mcp/adapters/music.py
  - macos_apps_mcp/adapters/notes.py
  - macos_apps_mcp/adapters/photos.py
  - macos_apps_mcp/adapters/reminders.py
  - macos_apps_mcp/adapters/safari.py
  - macos_apps_mcp/adapters/shortcuts.py
  - macos_apps_mcp/audit.py
  - macos_apps_mcp/contracts.py
  - macos_apps_mcp/daemon.py
  - macos_apps_mcp/deploy.py
  - macos_apps_mcp/doctor.py
  - macos_apps_mcp/eventkit.py
  - macos_apps_mcp/lifecycle.py
  - macos_apps_mcp/notices.py
  - macos_apps_mcp/registry.py
  - macos_apps_mcp/runtime.py
  - macos_apps_mcp/server.py
  - macos_apps_mcp/tiers.py
  - packaging/Info.plist
  - pyproject.toml
  - tests/conftest.py
  - tests/envelope.py
  - tests/mail_recover_dry_run_baseline.json
  - tests/test_applescript_timeout.py
  - tests/test_audit.py
  - tests/test_audit_middleware.py
  - tests/test_contacts.py
  - tests/test_deploy.py
  - tests/test_doctor.py
  - tests/test_doctor_deploy.py
  - tests/test_eventkit.py
  - tests/test_gate_on_dispatch.py
  - tests/test_import_layers.py
  - tests/test_integration.py
  - tests/test_mail.py
  - tests/test_mail_addressing.py
  - tests/test_mail_cleanup.py
  - tests/test_mail_drafts.py
  - tests/test_mail_extras.py
  - tests/test_mail_ids.py
  - tests/test_mail_index.py
  - tests/test_mail_recover.py
  - tests/test_mail_recover_dry_run_identity.py
  - tests/test_mail_search.py
  - tests/test_mail_triage.py
  - tests/test_music.py
  - tests/test_native_seam.py
  - tests/test_notes.py
  - tests/test_registry.py
  - tests/test_runtime.py
  - tests/test_safari.py
  - tests/test_server.py
  - tests/test_shortcuts.py
  - tests/test_tool_annotations.py
findings:
  critical: 0
  warning: 1
  info: 1
  total: 2
status: issues_found
---

# Phase 01: Code Review Report

**Reviewed:** 2026-09-26T00:00:00Z
**Depth:** standard
**Files Reviewed:** 63
**Status:** issues_found

## Summary

This phase extracts `eventkit.py` from `runtime.py`, replaces four hand-maintained
name/permission tables (`_WRITE_TOOLS`, `_SNAPSHOT_SOURCES`, `_audit_op`, the
`test_tool_annotations.py` literals) with one registration record
(`registry.ToolRecord`/`registry.TOOLS`) built by a single `server.py` decorator, moves
tier gating into `tiers.py`, and folds a caller-owned dry-run gap in `mail_recover.py`
(GATE-09: `dedupe_batch`'s dry run used to preview "planned" for ids nobody had
checked) into one `present=` contract shared by `move_mail`/`trash_mail`/`dedupe_batch`.
It also closes a real host-timeout-vs-script-timeout ordering bug for the dedupe
AppleScript (GATE-10) and backs the invariant with a codebase-wide static test
(`test_applescript_timeout.py`) instead of a single fixed case.

Traced end to end: every destructive/send tool's dry-run default (`registry`'s
`removes_content_tools()` + `test_registry.py`'s fail-closed signature check), the
tier-gate → FastMCP-registration path (`_tool` in `server.py`), the audit-verb
derivation (no silent `"write"` fallback, GATE-06), the untrusted-data notice exemption
list, and the layering rule ("nothing below `server.py` imports `server.py`",
`test_import_layers.py`). All hold. `uv run pytest` (1471 tests) and
`uv run ruff check .` are clean against the current tree.

One real edge case was found in new code: `NotesAdapter._update_preview` (the D-02
`update_note` dry-run preview) can under-report the CURRENT body size for a note whose
body fails to hydrate, which is exactly the kind of confidently-wrong preview this
project's own Mail lessons (`docs/mail-applescript-facts.md` §1) warn against — see
WR-01. A second, low-impact prefix-matching inconsistency in `registry.py` is filed as
IN-01 for awareness; it cannot fire against any tool registered today.

## Warnings

### WR-01: `update_note`'s dry-run preview can silently under-report the current body

**File:** `macos_apps_mcp/adapters/notes.py:764-782`
**Issue:** `_update_preview` (new in this phase, backing `update_note(dry_run=True)`)
computes `current_body` from `self.get_bodies([ident])` and reports `body_chars:
len(current_body)`:

```python
title = self._read_title_by_id(ident)
if title is None:
    raise ValueError(f"update_note: unknown note id {ident!r}")
bodies = self.get_bodies([ident])
current_body = bodies[0]["body"] if bodies else ""
```

`get_bodies`'s own docstring (notes.py:601-615) says an id it can't decode/hydrate
(sqlite decode failure *and* the AppleScript gap-fill both come up empty for that id)
is **silently skipped** — "the caller diffs returned vs requested". `_update_preview`
does not diff; it treats an empty `bodies` list identically to a note whose body is
genuinely empty, defaulting to `""` and reporting `body_chars: 0`. Because
`_read_title_by_id` already proved the id exists, a human or agent reading the preview
sees "current body: 0 chars" and can reasonably conclude there is nothing to lose by
overwriting it with `dry_run=False` — when the real body may be non-trivial and simply
failed to hydrate. This is a narrow edge case (both the sqlite and AppleScript body
paths have to come up empty for an id whose title read succeeded), but it sits directly
on the safety-critical path GATE-05/D-04 exists to protect (a full-replace update whose
own preview is the only before-state a human gets, per this method's own docstring:
"`notes.snapshot` is title-only ... this is the only before-state a full-replace update
gets"). No existing test (`tests/test_notes.py`) exercises "title resolves, body fails
to hydrate".
**Fix:** Distinguish "hydration failed" from "genuinely empty" the same way
`mail_bodies`/`mail_recover.Target` do elsewhere in this codebase (an explicit sentinel,
not a bare `""`), e.g.:

```python
bodies = self.get_bodies([ident])
if bodies:
    current_body = bodies[0]["body"]
    body_known = True
else:
    current_body = ""
    body_known = False
...
current: dict[str, object] = {
    "title": clean_summary(title) or "(untitled note)",
    "body_chars": len(current_body) if body_known else None,
}
if not body_known:
    current["body_unreadable"] = True
```
and add a test that fakes `get_bodies` returning `[]` for a title-resolvable id, asserting
the preview flags it rather than reporting `body_chars: 0`.

## Info

### IN-01: `derive_audit_verb`'s "delete" prefix is looser than the GATE-05 "delete_" class

**File:** `macos_apps_mcp/registry.py:87-89` vs `macos_apps_mcp/registry.py:146-148`
**Issue:** `derive_audit_verb` picks an audit-log verb by
`name.startswith(prefix)` for `prefix in ("create", "update", "delete", "complete")`
(no underscore required), while the GATE-05 safety classification —
`removes_content_tools()` and the identical check inlined in `server.py`'s `_tool`
decorator (`name.startswith("delete_")`) — requires the underscore. Every tool
registered today follows the `delete_<noun>` convention, so the two rules currently
agree, but they are two different string tests protecting two different things (one
labels the audit-log `op` field, the other forces a `dry_run=True` default), and
nothing ties them together. A future tool named without the underscore (e.g.
`deleteme_something` is fine, but a hypothetical `deleteAllDrafts`-style name would
not be) would get `op: "delete"` in the audit log from the first rule while silently
failing to join the `removes_content` safety class from the second — an audit-log
mislabeling risk, not a dry-run bypass (the project's snake_case convention makes this
unlikely in practice, and `test_registry.py`'s pinned literal sets would still force a
manual review of any newly classified tool).
**Fix:** Have `derive_audit_verb` reuse the same `"delete_"` (with underscore) test as
`removes_content_tools`, or extract one shared `_DELETE_PREFIX = "delete_"` constant
both read, so a future rename can't silently diverge the two checks again.

---

_Reviewed: 2026-09-26T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
