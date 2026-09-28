# Sketch Wrap-Up Summary

**Date:** 2026-09-28
**Sketches processed:** 4
**Design areas:** Layout and navigation, Audit review, Recovery, Adapters and health
**Skill output:** `./.claude/skills/sketch-findings-macos-apps-mcp/` (local; `.claude/` is git-ignored)

## Included Sketches

| # | Name | Winner | Design Area |
|---|------|--------|-------------|
| 001 | dashboard-shell | D — B's list + detail; Health, Adapters, Usage as pages | Layout and navigation |
| 002 | audit-review | D — word diff + resolved args; raw audit.jsonl collapsed | Audit review |
| 003 | recovery-flow | D — read-only: per-message backups + ask-Claude undo prompt | Recovery |
| 004 | toggles-and-health | A — switch + pending chip + restart bar; Outbound locked | Adapters and health |

## Excluded Sketches

| # | Name | Reason |
|---|------|--------|
| — | — | None excluded. |

## Design Direction

The Phase 5 operator dashboard (PLAT-01, PLAT-02) is calm and native to macOS, like System
Settings: grouped inset rows, the system font, automatic light and dark. Review of what the
model wrote is the home screen. Health, adapters, usage and backups are secondary pages.
The daemon serves every page on loopback only, server-rendered, with no SPA framework.

## Key Decisions

- **Layout:** sidebar (Writes, Apps, System) | list of writes | detail of one write. System
  items open as full pages at plain URLs. Phone: one column, list → detail with Back.
- **Review:** a preview is dimmed and chipped in the list and bannered in the detail. The
  detail shows a word diff of the before → after summaries, the args with `dry_run`
  resolved, and the raw `audit.jsonl` lines collapsed.
- **Recovery:** read-only. Each batch shows its messages with backup fidelity (`full`,
  `partial`, `no backup`), a copyable "Undo mail receipt …" prompt, and the exact
  `mail_undo` call. A Backups page shows size against the advisory limit and never deletes.
- **Adapters:** System Settings switches, an "off after restart" chip, and a sticky restart
  bar with Discard and Restart daemon. The Outbound gate is locked and changes only through
  `allow-send`. Health raises a banner only for an active adapter whose grant is denied.
- **Write boundary:** the toggle and the restart are the only write actions. Both check
  `Host` and `Origin`, require a per-session token, and write an audit record with caller
  `dashboard`. Every read checks `Host` against DNS rebinding. Every audit and receipt string
  is escaped, because mail subjects are untrusted.
- **Palette and type:** macOS system colours, SF and SF Mono, 13px base, 4px grid, hairline
  separators, tier chips as verbs (`adds` green, `changes` orange, `sends` purple).

## Open for the Build

- The audit record has no resolved `dry_run` and no caller (#222). Previews and dashboard
  writes depend on it.
- `Open` and `Reveal` on a backup file are server actions with a side effect. They need the
  same Host/Origin + token check, or they become a path with a Copy button.
- The phone layout hides the sidebar, so filters and System pages have no route there.
- Watching `audit.jsonl` for a finished undo needs a refresh strategy without an SPA (reload,
  poll or server-sent events).
