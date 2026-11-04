# Installed Mail recovery acceptance — 2026-11-04

The installed signed build `7bc8607 2026-11-04T11:41:03Z`, version `0.15.1`, completed one authorized self-addressed Mail test.
Its runtime reports MCP `2.3.0`, FastMCP `4.1.6`, and daemon mode.
One received Inbox copy was moved to Trash and restored. Its body remained intact.
The restored message, both receipts, and both backups remain available.

## Verified outcome

| Check | Result |
|---|---|
| Send | One send, after a preview; 4.934 seconds; Outbox empty; received test body matched |
| Fixture | One exact Inbox copy and one distinct candidate Trash path; English Trash title |
| Trash | Preview reported present; one target succeeded; source absent and Trash present afterward |
| Longer call | The actual installed Trash call completed in 6.087 seconds |
| Undo | Preview reported present; one target succeeded in 3.530 seconds; source body matched |
| Delayed observations | At two and fifteen minutes after undo: one exact source copy and no exact Trash copy |
| Backups | One new backup for Trash and one for undo; each contained the test Message-ID and body |
| File modes | Both new backup files were `0600`; every directory component through the state directory was `0700` |
| Ownership | All checked directory components belonged to the current account; none was a symlink |
| Receipts | The audit linked undo to the original Trash receipt |
| Notice | The scoped search returned exactly one leading untrusted-content notice |
| Leftovers | One restored Inbox message; two receipts retained; no matching draft index row |
| Signature | Strict verification passed after the native write and restore |

Send began at `2026-11-04T12:45:22Z`, Trash at `12:47:59Z`, and undo at `12:49:05Z`.
The final delayed index check ran at `13:04:18Z`.
Operation durations measure complete installed tool calls, including transport and verification. They are not isolated Apple Event timings.
The sender and recipient were the explicitly authorized owner address. No third-party recipient was used.

The primary send, search, body read, Trash, and undo calls used the installed stdio shim and daemon.
Additional verification used read-only SQLite checks, file metadata/content checks on the new backups, and read-only account/Outbox AppleScript probes.
Those supplemental probes do not establish the daemon's permission identity.
The existing periodic Mail watchdog was loaded; it was not changed.

## Limits

- The account uses a custom IMAP host. Gmail backing is unverified.
- Trash was undone before its two-minute and fifteen-minute observations. The later checks measured the restored state only.
- The Gmail Trash persistence gate remains untested. This is not localized-folder acceptance.
- PR #559 was not installed. Its ambiguity refusal, dedupe preflight, and undo guards remain outside this test.
- No failure injection, interrupted destructive call, replay measurement, or real Claude frontend acceptance occurred.
- Notarization, the updated Intel installation, and release remain pending.

**eli14:** One marked test letter went to the bin and returned to its original drawer.
Two locked safety copies preserved its text. Later checks found the restored letter in place.
This proves that route worked on this Mac; it does not prove every mail provider or translated bin label.

## Evidence

The private acceptance directory contains `outcome.json`, `verification.json`, `finalcheck.json`, `parent-modes.json`, and the executed harnesses.
Message IDs, receipt IDs, account details, bodies, and absolute evidence paths remain outside this public repository.
The evidence directory is `0700`; its private JSON records are `0600`.

Repository checks passed: 3,475 tests, 105 integration tests deselected, seven upstream warnings, Ruff lint, formatting, and diff checks.
The documentation adds no runtime change. All 85 checked relative links resolve.

[Installation evidence](2026-11-04-installed-acceptance.md) covers build identity, protocols, licences, storage, and normal restart recovery.
[Working notes](2026-11-04-installed-working-notes.md) record the acceptance boundaries.
