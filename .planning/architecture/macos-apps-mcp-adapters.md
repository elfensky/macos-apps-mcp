---
kind: component
title: App adapters
component: adapters
status: implemented
source_revision: 67a668c39484ebc2017c092d008f1dd705ccff73
source_evidence_date: 2026-11-09
---

# App adapters

[Architecture overview](macos-apps-mcp-architecture.md)

## What it does

Adapters translate [typed tool requests](macos-apps-mcp-tools-and-policy.md) into app-specific reads and actions.
Shared [native access](macos-apps-mcp-native-access.md) supplies framework, process, and database primitives.
Mail and Reminders have internal helper modules. These stay inside their own family.

| Family and source | Implemented access and limits |
|---|---|
| [Calendar](../../macos_apps_mcp/adapters/calendar.py) | EventKit reads, free/busy, create/update/delete, alarms, and supported recurrence rules. Unsupported recurrence shapes are refused. An update refuses `recurrence='none'` on a repeating event. An update without a calendar keeps the event's calendar. Omitted location and notes are cleared (#572). |
| [Reminders](../../macos_apps_mcp/adapters/reminders.py) | EventKit item/list actions; the read-only Reminders store adds tags and parent links. No public tag or subtask writes. An update without a list keeps the reminder's list. Omitted notes, priority, due and start are cleared (#572). |
| [Mail](../../macos_apps_mcp/adapters/mail.py) | Envelope Index, local message files, and optional indexes serve reads. AppleScript performs app actions; reply composition also uses Accessibility. |
| [Notes](../../macos_apps_mcp/adapters/notes.py) | NoteStore reads, body decoding, and in-memory FTS5 search. AppleScript supplies fallbacks and writes. |
| [Contacts](../../macos_apps_mcp/adapters/contacts.py) | AppleScript search and creation with typed `ContactData`; no direct Contacts framework access. |
| [Messages](../../macos_apps_mcp/adapters/messages.py) | Read-only `chat.db` content; AppleScript chat listing. Search and snippets use the decoded `attributedBody` when `text` is empty. No send implementation. |
| [Photos](../../macos_apps_mcp/adapters/photos.py) | osxphotos library reads, albums, metadata, and local still-image export. Requires Full Disk Access, rather than Automation. |
| [Safari](../../macos_apps_mcp/adapters/safari.py) | AppleScript tab reads and URL opening. |
| [Music](../../macos_apps_mcp/adapters/music.py) | AppleScript library search, current playback, playlists, and playback controls. |
| [Shortcuts](../../macos_apps_mcp/adapters/shortcuts.py) | Tracked CLI listing and execution; arbitrary shortcuts can have external effects. No Automation prompt for this CLI route. |

**eli14:** Each workshop bench handles one kind of item.
Some benches read a catalogue; others ask the app to change an item.
A catalogue can be incomplete, and permission to use one bench does not grant permission to use every bench.
Each bench therefore reports its own limits.

## Rules it keeps

### Read and action boundaries

The [Mail index](../../macos_apps_mcp/adapters/mail_index.py) separates indexed reads from AppleScript actions.
The [Message-ID sidecar](../../macos_apps_mcp/adapters/mail_ids.py) supports stores without the needed header column and reports stale coverage.
Mail body reads and exports are explicit operations. Mail's [recovery component](macos-apps-mcp-audit-and-recovery.md) preserves available bytes for supported destructive operations.

Notes body hydration decodes local data and attempts AppleScript for missing bodies.
Missing Full Disk Access or schema drift can trigger the full AppleScript fallback.
Messages content has no equivalent AppleScript fallback.
Photos excludes Hidden and Recently Deleted items. Export uses an available local still image and does not download missing iCloud content.

Mail sending remains behind the outbound gate.
An accepted send does not prove delivery; Outbox status and post-action warnings remain material.
Mail writes require resulting-message inspection during acceptance, as recorded in the [device facts](../../docs/mail-applescript-facts.md).

### Notes and localization limits

Notes currently supports create, full replacement, and deletion, with previews on content-removing tools.
Its snapshots are title pointers, not full-content backups.
Notes has no backup browsing and no undo tool.

Notes excludes folder type 1 and passes 48 translated names to its AppleScript fallback.
Mail supports explicit translated system-folder names and preserves the original mailbox address.
Names remain heuristics; SQLite ASCII case matching differs from Python Unicode casefolding.
Mail refuses a Trash write when more than one distinct Trash path matches (#556). Undo of a trash receipt needs one current Trash at the recorded path.

## Sources

- [Phase 3 verification](../phases/03-eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub/03-VERIFICATION.md): EventKit depth.
- [Phase 4 verification](../phases/04-notes-photos-settle-the-mechanism-then-ship-the-read-plane/04-VERIFICATION.md): Notes search and Photos.
- [Localized-folder implementation and limits](../phases/05.6-bug-fixes-notes-write-safety-and-system-folders-in-any-langu/05.6-02-SUMMARY.md).
- [Phase 05.6 context](../phases/05.6-bug-fixes-notes-write-safety-and-system-folders-in-any-langu/05.6-CONTEXT.md): planned Notes safety and localization.
- [Ambiguous Trash selection](../phases/05.6-bug-fixes-notes-write-safety-and-system-folders-in-any-langu/05.6-05-SUMMARY.md): implemented; device acceptance pending.

Locked and shared-note guards, non-text preservation checks and full HTML before-state backups are planned under #500.
The read-only device suite passed on build `3dd93b2`. Localized Mail write acceptance (#556), real-index timing, Notes probes and draft probes remain open.
