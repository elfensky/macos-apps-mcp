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

## Shipped

- **v1** — Calendar + Reminders read/write (EventKit), RRULE subset · [milestone](https://github.com/elfensky/macos-apps-mcp/milestone/1)
- **0.3.0 — Trust core** — typed errors, `doctor`, verify-after-write, `now`, EKSpan · [milestone](https://github.com/elfensky/macos-apps-mcp/milestone/2)
- **0.4.0 — Safety rails** — output hygiene, dry-run + batch caps, untrusted-data notice, id-only writes, tool annotations · [milestone](https://github.com/elfensky/macos-apps-mcp/milestone/3)
- **0.5.0 — Native data planes** — Messages via chat.db, Notes via NoteStore.sqlite, id-first Mail + draft-and-open · [milestone](https://github.com/elfensky/macos-apps-mcp/milestone/4)
- **0.7.0 — Differentiators** — `free_busy` availability, Notes create/update with stable ids, JSONL write audit trail + `audit()`, Mail triage (needs-response / awaiting-reply as ranked Pointers) · [milestone](https://github.com/elfensky/macos-apps-mcp/milestone/5)

## 0.8.0 — New adapters & expansion ([milestone](https://github.com/elfensky/macos-apps-mcp/milestone/6))

Infrastructure that later milestones sit on, plus the first new adapter.

| Issue | What | Prior art |
|---|---|---|
| [#70](https://github.com/elfensky/macos-apps-mcp/issues/70) | Envelope Index read plane — indexed Mail search engine | imdinu, che-apple-mail-mcp, rusty_apple_mail_mcp |
| [#71](https://github.com/elfensky/macos-apps-mcp/issues/71) | launchd daemon + TCC-to-binary attachment (one grant, every client) | FradSer scoped binary; iMCP app as the ceiling |
| [#69](https://github.com/elfensky/macos-apps-mcp/issues/69) | Music adapter | apple-mcp-pro |

## 0.9.0 — Mail depth & outbound ([milestone](https://github.com/elfensky/macos-apps-mcp/milestone/7))

Close the gap to the deepest specialist ([patrickfreyer/apple-mail-mcp](https://github.com/patrickfreyer/apple-mail-mcp),
22 tools) and introduce **gated** outbound. "Never sends" stays the default; send becomes an
explicit opt-in tier (`MACOS_APPS_ALLOW_SEND`, see [#104](https://github.com/elfensky/macos-apps-mcp/issues/104)),
not a ceiling.

**Mail reads:** [#75](https://github.com/elfensky/macos-apps-mcp/issues/75) rich search (body/dates/flags/attachments/accounts) ·
[#76](https://github.com/elfensky/macos-apps-mcp/issues/76) inbox overview + unread counts ·
[#77](https://github.com/elfensky/macos-apps-mcp/issues/77) thread view

**Mail organization:** [#78](https://github.com/elfensky/macos-apps-mcp/issues/78) mailboxes: list/create/move/archive ·
[#79](https://github.com/elfensky/macos-apps-mcp/issues/79) mark read / flag ·
[#80](https://github.com/elfensky/macos-apps-mcp/issues/80) trash management ·
[#81](https://github.com/elfensky/macos-apps-mcp/issues/81) save attachments to disk

**Mail outbound (gated):** [#82](https://github.com/elfensky/macos-apps-mcp/issues/82) drafts lifecycle ·
[#83](https://github.com/elfensky/macos-apps-mcp/issues/83) direct send / reply-all / forward ·
[#84](https://github.com/elfensky/macos-apps-mcp/issues/84) scheduled send ·
[#85](https://github.com/elfensky/macos-apps-mcp/issues/85) statistics + export

**Messages:** [#86](https://github.com/elfensky/macos-apps-mcp/issues/86) send — iMessage/SMS auto-routing, group chats (gated) ·
[#87](https://github.com/elfensky/macos-apps-mcp/issues/87) attachments via progressive disclosure ·
[#88](https://github.com/elfensky/macos-apps-mcp/issues/88) unread + date-range read filters

## 0.10.0 — Adapter depth parity ([milestone](https://github.com/elfensky/macos-apps-mcp/milestone/8))

Depth for adapters we already ship, stealing the best single feature from each specialist.

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

## 0.11.0 — New domains ([milestone](https://github.com/elfensky/macos-apps-mcp/milestone/9))

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
([#104](https://github.com/elfensky/macos-apps-mcp/issues/104) gates 0.9.0's sends).

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
