# Roadmap

High-level direction for macos-apps-mcp, grounded in a full landscape survey of Apple-apps MCP servers
(2026-07-14; findings embedded in the linked issues). Detail lives in the issues — this file is the
map, not the territory. Issues here are **candidates**: filing ≠ commitment; refinement happens per
milestone.

**Where we sit.** The 3.1k★ category leader ([supermemoryai/apple-mcp](https://github.com/supermemoryai/apple-mcp))
is archived; [mattt/iMCP](https://github.com/mattt/iMCP) is the only maintained multi-app suite with
traction and ships **no Mail, no Notes, no Photos, no Safari** (its two most-requested issues). No
surveyed server combines uniform bounded reads across Mail + Messages + Notes + Calendar + Reminders.
That combination is this repo — the roadmap deepens it rather than chasing breadth for its own sake.

**Ordering principles** (from [DESIGN.md](../DESIGN.md), unchanged): pointers-not-payload on every
read; writes gated, id-addressed, dry-runnable; native stores (EventKit / sqlite) over AppleScript
where they exist; one adapter per app.

**Release cadence.** Ship in small cuts. A release is one coherent slice that works on its own —
`0.9.1`, `0.9.2`, `0.9.3` — not a milestone waiting to be complete. Minor bumps (`0.10.0`) mark a
change of theme, not a bigger pile of work. **Milestones and releases are different things and do
not have to line up:** `0.9.0` shipped with its milestone still open, and the rest of that
milestone lands across `0.9.x`. Procedure in [RELEASING.md](RELEASING.md).

Small cuts also keep the deploy honest — every release is a rebuild of the `.app`, and the daemon
serves its old build until you do it.

## Shipped

- **v1** — Calendar + Reminders read/write (EventKit), RRULE subset · [milestone](https://github.com/elfensky/macos-apps-mcp/milestone/1)
- **0.3.0 — Trust core** — typed errors, `doctor`, verify-after-write, `now`, EKSpan · [milestone](https://github.com/elfensky/macos-apps-mcp/milestone/2)
- **0.4.0 — Safety rails** — output hygiene, dry-run + batch caps, untrusted-data notice, id-only writes, tool annotations · [milestone](https://github.com/elfensky/macos-apps-mcp/milestone/3)
- **0.5.0 — Native data planes** — Messages via chat.db, Notes via NoteStore.sqlite, id-first Mail + draft-and-open · [milestone](https://github.com/elfensky/macos-apps-mcp/milestone/4)
- **0.7.0 — Differentiators** — `free_busy` availability, Notes create/update with stable ids, JSONL write audit trail + `audit()`, Mail triage (needs-response / awaiting-reply as ranked Pointers) · [milestone](https://github.com/elfensky/macos-apps-mcp/milestone/5)
- **0.8.0 — New adapters & expansion** — indexed Mail search (Envelope Index + FTS body sidecar, #70), launchd daemon + TCC-to-bundle so one grant serves every client (#71), Full-Disk-Access visibility (#123), and the **Music** adapter — search / now-playing / additive playback (#69) · [milestone](https://github.com/elfensky/macos-apps-mcp/milestone/6)
- **0.9.0 — Mail depth & outbound** — **gated** outbound (#82 drafts lifecycle, #83 send / reply-all / forward, #104 the tier), flipped by the `allow-send` **CLI** command so the model cannot grant itself sending; and the Mail read plane completed — #75 rich search, #76 inbox overview, #77 thread view, all deduped by RFC822 Message-ID · [milestone](https://github.com/elfensky/macos-apps-mcp/milestone/7) (**stays open** — the rest lands across 0.9.x)

## 0.9.x — the rest of Mail depth

Candidate cuts, smallest coherent slice each. Ordering is a proposal, not a commitment.

| Cut | Contents | Note |
|---|---|---|
| **0.9.1 — Mail addressing** ✅ | [#155](https://github.com/elfensky/macos-apps-mcp/issues/155) the addressing triple + id-only resolution · [#156](https://github.com/elfensky/macos-apps-mcp/issues/156) stop under-answering silently | **Landed on `develop`.** Both shipped as the modules the 2026-08-03 review asked for rather than per-read patches: `adapters/mail_addressing.py` gathers the ~10 homes of "what addresses a message" behind two id conversions and one `resolve(id, folder=None, account=None)` that answers with exactly one target or raises — the rule #159/#78/#80/#140/#153/#81 all need — and `contracts.read_result` is the ONE bounded-read envelope `{results, truncated?, plane?, coverage?}`, so "the call succeeded" and "the answer is complete" stop being the same statement. Breaking: every bounded mail read changed shape. #155 closes #154. |
| **0.9.2 — Mail organize** ✅ | [#159](https://github.com/elfensky/macos-apps-mcp/issues/159) the recoverable destructive plane · [#78](https://github.com/elfensky/macos-apps-mcp/issues/78) mailbox hierarchy: list/create/move/archive · [#79](https://github.com/elfensky/macos-apps-mcp/issues/79) mark read/unread, flag (+colour) | **Landed on `develop`.** #159 went first and #78's `move_mail` is its first consumer — the pairing was the cut's proof, and it held: `move_mail`/`mail_undo` are locate → `recoverable(…)` and hand-roll no safety of their own. #78's **read** half was already free — #155 had put the raw `folder` url on every `mail_overview` row, so the proposed `mailboxes()` tool stayed dead. **Three device probes overturned the design settled on the issue**, which is the whole argument for probing: a *list* of specifiers to `move` raises -1700 and moves nothing (the `list="yes"` parameter is in a commented-out block of `Mail.sdef`), so a batch is N events in one script, not one event; a **cross-account `move` is a true move** — Mail.app's UI *drag* is what copies, so the planned copy → verify → delete-source dance was never needed; and `delete <mailbox>` is not scriptable at all, so `create_mailbox` ships with no counterpart. A green 1,024-test suite also passed a script that could not compile, because `st` turns out to be an AppleScript reserved word — [the facts doc](mail-applescript-facts.md) has all of it. Fixed on the way: a live `folder` url passed to `mail_search(mailbox=…)` matched zero rows, so the documented round trip silently returned nothing. |
| **0.9.3 — Mail cleanup** | [#80](https://github.com/elfensky/macos-apps-mcp/issues/80) trash: soft/permanent/empty · [#140](https://github.com/elfensky/macos-apps-mcp/issues/140) same-mailbox dedupe · [#153](https://github.com/elfensky/macos-apps-mcp/issues/153) cross-account dedupe | Same verb, same dry-run discipline — build together rather than doing trash three times. Both dedupes are measured on the dev machine (re-verified 2026-08-03): 9,879 redundant rows same-mailbox (#140), ~3.9k cross-account copies from a migration (#153). They are separate tools because the winner differs — #140 keeps the lowest ROWID, #153 cannot infer which *account* should survive and makes the caller say. Both act through **AppleScript, never sqlite** — `mail_index` is a read-only reader ("sqlite locates, AppleScript acts"). **Two decisions settled by the 2026-08-03 review:** the dedupes ship as a **CLI command** (`dedupe-mail`), not MCP tools — thousands of ~0.1s AppleScript deletes against a 30s-capped serialized worker is the #119 shape, human-started; the MCP surface keeps a read-only duplicate report. And "move to Trash = reversible" only holds until `empty_trash` (or Mail's own 30-day erase) — recovery rides #159's backup + action log, not Trash retention. Permanent/empty needs its gate decided *before* the cut — cheapest is the `allow-send` pattern, a CLI-set `allow-destructive`. |
| **0.9.4 — Mail extras** | [#81](https://github.com/elfensky/macos-apps-mcp/issues/81) save attachments to disk · [#85](https://github.com/elfensky/macos-apps-mcp/issues/85) statistics + export | #81 is UNBLOCKED by #155: `mail_attachments` rows now carry id + deeplink + folder, and `mail_attachments(message_id=…)` addresses one message directly, so the file to save has a name and an owner. #85 rides the query plane `mail_overview` established, and depends on the dedup fix — stats over raw rows would be wrong by the same margin `mail_overview` was. |
| **0.9.5 — Body download** | [#119](https://github.com/elfensky/macos-apps-mcp/issues/119) `download-bodies` | A **CLI command** mirroring `allow-send`, never an MCP tool: hours of IMAP and GB of disk, so a human starts it. Unblocked by 0.9.0. |
| **0.9.6 — Messages depth** | [#86](https://github.com/elfensky/macos-apps-mcp/issues/86) gated send · [#87](https://github.com/elfensky/macos-apps-mcp/issues/87) attachments · [#88](https://github.com/elfensky/macos-apps-mcp/issues/88) unread + date filters | #86 reuses the existing gate — `allow-send messages`; the second-adapter plumbing already exists. |

Floating: [#84](https://github.com/elfensky/macos-apps-mcp/issues/84) scheduled send · [#157](https://github.com/elfensky/macos-apps-mcp/issues/157) send an approved draft by id · [#158](https://github.com/elfensky/macos-apps-mcp/issues/158) bulk body read (evaluate a Pointer `snippet` first — it may remove the need). All three are outbound/read-tier and small; attach to whichever cut is light. [#160](https://github.com/elfensky/macos-apps-mcp/issues/160) (one outgoing-message lifecycle) lands **with #157** — same plane, and #157 is otherwise a fourth hand-rolled copy of the send discipline. [#161](https://github.com/elfensky/macos-apps-mcp/issues/161) is the hygiene sweep — fits any cut.

### The 2026-08-03 architecture review

The mail subsystem was walked module-by-module against the 0.9.x plan (deep-module lens; findings
validated on-device). Three issues filed: [#159](https://github.com/elfensky/macos-apps-mcp/issues/159)
recoverable destructive plane — the roadmap's four destructive tools each re-specified dry-run/
Trash-not-delete/caps with no module owning them, `empty_trash` (#80) would have erased the
dedupes' only undo path, and the audit trail (200-char truncation, one snapshot source) cannot
reconstruct a bulk operation; [#160](https://github.com/elfensky/macos-apps-mcp/issues/160)
outgoing lifecycle; [#161](https://github.com/elfensky/macos-apps-mcp/issues/161) hygiene.
Measured while validating: a message's `.emlx` is named by its Envelope Index ROWID (backup is a
file copy, no Mail launch), and **62.5% of local messages are `.partial.emlx`** — so backup
fidelity is bounded by #119 until `download-bodies` runs, and a permanent delete of an
undownloaded message must demand `allow_lossy`. Killed in review: per-loser file backups for the
dedupes (byte-identity means the surviving copy *is* the backup — the un-truncated action log
suffices).

### The mail-vs-vault debate

2026-08-02. The Mail surface was walked against its actual caller — a Claude Code session rooted in
the life-cockpit Obsidian vault — across four workflows: *link this email to that note*, *check
inbox X for the mail from Y*, *draft a reply to X*, *update the project from mail Y*. Two rounds,
four models (Codex, Antigravity, OpenCode, Opus), 23 findings, 4 filed (#155–#158).

The verdict: **complete as a mail-client API, incomplete as a citation source.** Citation
*rendering* was never the gap — the vault has been writing `[📧](message://%3C<id>%3E)` since 2022,
byte-identical to what `_deeplink()` emits. The gap is that a reply about a message must carry
`id + folder + account` and most reads carry only the id.

Killed in cross-critique, recorded so they don't get re-filed: the dedupe issues do **not** write
rows in Mail's Envelope Index; `send_mail` must **not** sleep to sweep its own Drafts litter (it
would block the single serialized `run_native` worker and still race an unsuppressable async
autosave); and "`sent: True` ≠ delivered" is already handled by `_with_outbox_pending`.

## 0.10.x — Adapter depth parity ([milestone](https://github.com/elfensky/macos-apps-mcp/milestone/8))

Depth for adapters we already ship, stealing the best single feature from each specialist. Cut per
adapter — Calendar (#89, #90) as `0.10.0`, Reminders (#91, #92) as `0.10.1`, and so on — rather
than one release waiting on all nine.

| Issue | What | Prior art |
|---|---|---|
| [#89](https://github.com/elfensky/macos-apps-mcp/issues/89) | Calendar alarms | mcp-ical |
| [#90](https://github.com/elfensky/macos-apps-mcp/issues/90) | Extended recurrence (`BYDAY`, …) | mcp-ical |
| [#91](https://github.com/elfensky/macos-apps-mcp/issues/91) | Reminders tags + subtasks | FradSer |
| [#92](https://github.com/elfensky/macos-apps-mcp/issues/92) | Reminders delete + list management | FradSer |
| [#93](https://github.com/elfensky/macos-apps-mcp/issues/93) | Notes semantic search sidecar (evaluate) | RafalWilinski (dead — niche is open) |
| [#94](https://github.com/elfensky/macos-apps-mcp/issues/94) | Contacts full cards, `contacts_me`, update | iMCP |
| [#95](https://github.com/elfensky/macos-apps-mcp/issues/95) | Contacts sqlite fast search | apple-mcp-pro |
| [#96](https://github.com/elfensky/macos-apps-mcp/issues/96) | Photos albums, metadata, export | sweetrb, osxphotos |
| [#97](https://github.com/elfensky/macos-apps-mcp/issues/97) | Safari bookmarks, reading list, history | apple-mcp-pro; history = survey gap |

## 0.11.x — New domains ([milestone](https://github.com/elfensky/macos-apps-mcp/milestone/9))

Domains we don't cover; iMCP parity is the anchor. Each is a new adapter module per the
one-adapter-per-app rule.

| Issue | What | Prior art / caveat |
|---|---|---|
| [#98](https://github.com/elfensky/macos-apps-mcp/issues/98) | Maps — search, directions, ETA | iMCP (MapKit) |
| [#99](https://github.com/elfensky/macos-apps-mcp/issues/99) | Location — current, geocode | iMCP; headless CoreLocation TCC is the spike |
| [#100](https://github.com/elfensky/macos-apps-mcp/issues/100) | Weather | iMCP uses WeatherKit — **entitlement-blocked for us**; decide keyless HTTP vs Shortcuts first |
| [#101](https://github.com/elfensky/macos-apps-mcp/issues/101) | Capture — screenshot (camera/audio maybe) | iMCP, apple-mcp-pro |
| [#102](https://github.com/elfensky/macos-apps-mcp/issues/102) | System utilities cluster — cherry-pick | apple-mcp-pro (12 tools; most are skips) |
| [#103](https://github.com/elfensky/macos-apps-mcp/issues/103) | Generic AppleScript escape hatch — **likely wontfix** | steipete, peakmojo; bypasses our typed-safety design |

## Platform & DX ([milestone](https://github.com/elfensky/macos-apps-mcp/milestone/10))

Cross-cutting, unversioned — pulled into whichever release needs them first
([#104](https://github.com/elfensky/macos-apps-mcp/issues/104) gated 0.9.0's sends; [#143](https://github.com/elfensky/macos-apps-mcp/issues/143) is the daemon-drift guard's blind spot).

| Issue | What | Prior art |
|---|---|---|
| [#104](https://github.com/elfensky/macos-apps-mcp/issues/104) | Granular capability gating (read < draft < send/destructive) | patrickfreyer `--read-only`; iMCP#161 demand |
| [#105](https://github.com/elfensky/macos-apps-mcp/issues/105) | User-preferences env context | patrickfreyer |
| [#106](https://github.com/elfensky/macos-apps-mcp/issues/106) | Companion skill + Claude Code plugin packaging | patrickfreyer |
| [#107](https://github.com/elfensky/macos-apps-mcp/issues/107) | Distribution polish — .mcpb, brew tap | iMCP, patrickfreyer |

## Not planned

- **Journal** — no API at all (settled in [DESIGN.md](../DESIGN.md)).
- **Raw script execution by default** — see [#103](https://github.com/elfensky/macos-apps-mcp/issues/103);
  run [steipete/macos-automator-mcp](https://github.com/steipete/macos-automator-mcp) alongside if needed.
- **Becoming a GUI app (iMCP-shaped)** — the stdio server stays; a signed helper *binary* ([#71](https://github.com/elfensky/macos-apps-mcp/issues/71))
  is as far as we go. Run iMCP alongside for anything only an app can do.
- **Contributing Mail support to iMCP** — evaluated 2026-07-14: would be a from-scratch Swift rewrite
  into a sandbox that structurally resists Mail access, against a bursty review queue. Declined.
