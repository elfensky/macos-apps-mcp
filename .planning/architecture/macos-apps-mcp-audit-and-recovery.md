---
kind: component
title: Audit and recovery
component: audit-and-recovery
status: implemented
source_revision: 18dcbf6594bbd62330f71c89376a54155dda1d63
source_evidence_date: 2026-11-04
review_status: independent-review-complete
publication_status: pending
---

# Audit and recovery

[Architecture overview](macos-apps-mcp-architecture.md)

## Best-effort audit contract

`AuditMiddleware` records usage, attempts configured before-state snapshots, and awaits the tool action.
Only after a successful result does it append the write audit record.
`audit_write()` catches storage errors and returns `False`; the middleware does not turn that failure into a failed action.
A native action can therefore finish without a persisted audit record.

Records contain the operation, bounded arguments, resolved preview flag, advisory caller labels, and available before/after pointers.
A Mail result can also supply a receipt identifier.
Client names and shim identifiers are not authenticated and never authorize an operation.
Audit storage rotates JSONL files; retention and read limits make this a bounded operational record, not a complete transaction ledger.

**eli14:** The workshop keeps receipts beside its completed jobs.
The receipt printer can fail after a job finishes.
Some Mail jobs also keep a spare copy before work starts, but a missing receipt still leaves uncertainty.
Future recovery depends on the copies and records that actually survived.

## Implemented Mail recovery

`mail_recover.recoverable()` checks the batch and locates available message bytes.
Where enabled, backup files precede the native action.
The helper attempts a plan record, performs the action, then attempts an outcome record.
Both audit attempts remain best-effort; failure to append the plan does not itself prevent the action.

Backup fidelity uses `full`, `partial`, `absent`, and `unknown`. `unknown` means the source has not been inspected.
A partial local copy can lack attachments.
A lossy-backup gate exists for permanent operations, but `PERMANENT_OPS` is empty. Mail has no targeted permanent-delete operation.
No current tool exposes the `allow_lossy` override.
Selected deduplication paths use log-only recovery because a verified surviving copy provides the preserved content.
Missing per-target results become `unknown`. A caught native timeout also leaves uncertain targets.

`mail_undo` uses retained plan data to move eligible messages to their source mailboxes.
It cannot recall sent mail or automatically reverse permanent deletion.
Available `.eml` backups can support manual import. A returned receipt identifier does not prove its log record persisted.
The [dashboard recovery view](macos-apps-mcp-operator-controls.md) provides inspection, not automatic replay.

## Implemented storage protection — #552

`state_dir()` creates private state at `0700` and narrows existing group/other permissions.
It preserves narrower owner-only modes and existing file modes.
Directory checks reject symlinks and foreign ownership before descriptor-based permission changes.
CLI startup attempts repair and warns on failure; tool listing and diagnostics remain available.
Private file write paths recheck directory safety.

Mail backup directories receive `0700` checks at each owned component.
Backup files use exclusive `0600` creation. A backup destination failure aborts before the Mail action.
An unreadable source retains the existing absent-backup behavior.
Completed-action results reuse the checked backup path, preserving the receipt if storage state changes later.
These checks do not constitute a global storage gate for all native writes.

Doctor reports observed exposure and repairs remembered by the current process.
The implementation checks POSIX modes, not macOS ACL permissions.
Installed-device state-directory acceptance remains pending.

## Sources and planned work

- [audit.py](../../macos_apps_mcp/audit.py): `AuditMiddleware`, `audit_write`, `private_directory`, and `state_dir`.
- [mail_recover.py](../../macos_apps_mcp/adapters/mail_recover.py): backup, plan/outcome attempts, receipts, and undo selection.
- [cli.py](../../macos_apps_mcp/cli.py), [doctor.py](../../macos_apps_mcp/doctor.py), and [privacy tests](../../tests/test_private_storage.py).
- [files.py](../../macos_apps_mcp/files.py): separate export-root validation, staging, and atomic publication without overwriting existing files.
- [Phase 02.1 verification](../phases/02.1-mail-fixes-batch-moves-fit-their-timeout-drafts-pick-their-a/02.1-VERIFICATION.md) and [Phase 05.6 private storage summary](../phases/05.6-bug-fixes-notes-write-safety-and-system-folders-in-any-langu/05.6-01-SUMMARY.md).

Notes full-body backups and write guards remain planned in [Phase 05.6](../phases/05.6-bug-fixes-notes-write-safety-and-system-folders-in-any-langu/05.6-CONTEXT.md).
The existing Notes title snapshot is not equivalent to those safeguards.
