# Notes.app AppleScript: device-verified facts

Each entry here was run against real Notes, on scratch notes only. Each entry has its date, its
macOS build and its Notes build. A fact that was not run is not here: see `## Not verified`.

Probe: `notes_probe.py` in the Phase 05.6 `05.6-proto/` folder, run as the installed bundle
(release 0.16.1). Every result was read back from the note and from NoteStore, never from a
return value.

## 1. What a note body holds, and what a body replace destroys (#500)

Run on 2026-11-21 (macOS 27.2.1, build 26B131; Notes bundle version 3195.42.3).
The scratch note was typed into Notes with key events: a title line, a plain line, a bold line,
a checklist with two items, a bullet list with one item and a table with one filled cell. It
held no picture, no drawing and no link.

| Item | Counted by `count of attachments` | How `body` holds it | In `plaintext` | NoteStore signal |
|---|---|---|---|---|
| Title line | no | `<h1>` | yes | none |
| Bold text | no | `<b>` | yes | `ZHASEMPHASIS` stayed 0 |
| Checklist item | no | `<ul><li>`, the same path as a bullet item; no class, no attribute | yes | `ZHASCHECKLIST` = 1 |
| Bullet item | no | `<ul><li>` | yes | none |
| Table | yes (1) | `<object>` with a `<table>` inside | no | one attachment row, type `com.apple.notes.table` |

- **A checklist has no marker in the HTML.** The tag path of a checklist item equals the path of
  a bullet item, and the body has no class value at all. Only the store column `ZHASCHECKLIST`
  shows it.
- **`count of attachments` counts a table.** It read 1 for one table, equal to the count of
  attachment rows in the store.
- **The text of a table cell is not in `plaintext`.**

**`set body` of a note to its own HTML (the same HTML that `body` returned):**

| Item | Result |
|---|---|
| Checklist | **Lost.** `ZHASCHECKLIST` went from 1 to 0. The items stay as a plain bullet list. |
| Title line | Changed: the `<h1>` became a bold line (`<b>`, `<font>`, `<span>`). The note kept its name. |
| Table | Kept as a table. The store then held 2 table attachment rows for the note (1 before). |
| Bold text, bullet list, plain text | Kept. |

The write answered with no error. Only the store showed the loss.

**A new note made from the saved HTML (`make new note` with that body):** the checklist is not
restored (`ZHASCHECKLIST` = 0, a plain bullet list), the table is restored (1 attachment row),
bold, bullet list and plain text are restored, and the title line is a bold line, not `<h1>`.
So a saved HTML body is not a complete backup of a note with a checklist.

Two more readings from the same run:

- `shared of container of n` raised -1700 on a note in a folder that is not shared; `shared of
  n` read `false`. A guard that reads the folder must take an error as "unknown".
- A key event that is sent to the process of Notes applies a format command (checklist, bold,
  table) only while Notes is the active app. With Notes in the background the text arrived and
  every format command was ignored.

## Not verified

- A picture, a drawing and a link in a note: not run (no such scratch fixture).
- Locked notes (`password protected`, and `body`, `set body`, `delete` on a locked note): not
  run. Owner decision of 2026-11-21: the guard reads the property and the store flag, refuses on
  any error, and is held by unit tests.
- Shared notes and notes in a shared folder (`shared`, `shared of container`,
  `ZSERVERSHAREDATA`): not run, by the same decision.
- Recently Deleted in another language (the AppleScript name, `ZTITLE2`): not run, by the same
  decision. The merged read rule uses `ZFOLDERTYPE`.
- A ticked checklist item: not run (both items were open).
