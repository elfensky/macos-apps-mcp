---
kind: component
title: Audit and recovery
component: audit-and-recovery
status: implemented
source_revision: 67a668c39484ebc2017c092d008f1dd705ccff73
source_evidence_date: 2026-11-09
---

# Audit and recovery

[Architecture overview](macos-apps-mcp-architecture.md)

## What it does

`AuditMiddleware` records usage, attempts configured before-state snapshots, and awaits the tool action.
Only after a successful result does it append the write audit record.
`audit_write()` catches storage errors and returns `False`; the middleware does not turn that failure into a failed action.
A native action can therefore finish without a persisted audit record.

Records contain the operation, the arguments (strings cut at 200 characters), resolved preview flag, advisory caller labels, and available before/after pointers.
A Mail result can also supply a receipt identifier.
Client names and shim identifiers are not authenticated and never authorize an operation.
Audit storage rotates JSONL files. Every reader covers both retained files, `audit.jsonl.1` and `audit.jsonl`. Retention and read limits make this a bounded operational record, not a complete transaction ledger.

**eli14:** The workshop keeps receipts beside its completed jobs.
The receipt printer can fail after a job finishes.
Mail moves, Trash and dedupe jobs write a work order first and can keep a spare copy. Such a job with no work order does not start. A missing final receipt still leaves uncertainty.
Future recovery depends on the copies and records that actually survived.

### Mail recovery

`mail_recover.recoverable()` checks the batch. It locates message bytes only for a backup or a permanent operation.
Where enabled, backup files precede the native action.
The helper writes a plan record, does the action, then attempts an outcome record.
A failed plan write raises `WriteRefused`, and nothing moves. The outcome record stays best-effort.

Backup fidelity uses `full`, `partial`, `absent`, and `unknown`. `unknown` means the source has not been inspected.
A partial local copy can lack attachments.
A lossy-backup gate exists for permanent operations, but `PERMANENT_OPS` is empty. Mail has no targeted permanent-delete operation.
No current tool exposes the `allow_lossy` override.
Selected deduplication paths use log-only recovery because a verified surviving copy provides the preserved content.
Missing per-target results become `unknown`. A caught native timeout also leaves uncertain targets.

`mail_undo` reads the plan and outcome records from both retained audit files.
It moves back each target whose `left_source` is not `stayed`, also a target that moved in part.
An older receipt without `left_source` keeps the status rule.
It cannot recall sent mail or automatically reverse permanent deletion.
Available `.eml` backups can support manual import. A returned receipt proves that its plan record was written. Its outcome record can be missing. Undo then treats every planned target as possibly moved.
The [dashboard recovery view](macos-apps-mcp-operator-controls.md) provides inspection, not automatic replay.

## Rules it keeps

### Private storage (#552)

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

## Code paths

- [audit.py](../../macos_apps_mcp/audit.py): `AuditMiddleware`, `audit_write`, `read_all`, `private_directory`, and `state_dir`.
- [mail_recover.py](../../macos_apps_mcp/adapters/mail_recover.py): backup, the plan and outcome records, receipts, and undo selection.
- [Rotation tests](../../tests/test_audit_rotation.py) and [partial-undo tests](../../tests/test_mail_undo_partial.py): both retained files, the plan-write refusal, and `left_source`.
- [cli.py](../../macos_apps_mcp/cli.py), [doctor.py](../../macos_apps_mcp/doctor.py), and [privacy tests](../../tests/test_private_storage.py).
- [files.py](../../macos_apps_mcp/files.py): separate export-root validation, staging, and atomic publication without overwriting existing files.

## Sources

- [Installed build evidence](../overnight/2026-11-04-installed-acceptance.md): the state and daemon directories were `0700`. The socket and the dashboard key were `0600`.
- [Mail recovery evidence](../overnight/2026-11-04-mail-recovery-acceptance.md): two new backups were `0600` and kept the test Message-ID and body. Gmail Trash persistence and localized behaviour stay untested.
- [Phase 05.12](../ROADMAP.md), PR #584: #575 and #578 passed their normal path on device build `03c94a3`. A plan-write failure and a partial move were not forced on a device.
- [Phase 02.1 verification](../phases/02.1-mail-fixes-batch-moves-fit-their-timeout-drafts-pick-their-a/02.1-VERIFICATION.md) and [Phase 05.6 private storage summary](../phases/05.6-bug-fixes-notes-write-safety-and-system-folders-in-any-langu/05.6-01-SUMMARY.md).

Notes full-body backups and write guards remain planned in [Phase 05.6](../phases/05.6-bug-fixes-notes-write-safety-and-system-folders-in-any-langu/05.6-CONTEXT.md).
The existing Notes title snapshot is not equivalent to those safeguards.
