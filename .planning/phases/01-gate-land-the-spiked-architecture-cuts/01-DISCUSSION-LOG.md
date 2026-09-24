# Phase 1: Gate — Land the Spiked Architecture Cuts - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-25
**Phase:** 01-gate-land-the-spiked-architecture-cuts
**Areas discussed:** Which tools default to dry run, Release and daemon rebuilds, PR landing and who merges

---

## Which tools default to dry run

| Option | Description | Selected |
|--------|-------------|----------|
| Deletes + update_note | `delete_event`, `delete_draft`, `delete_note` change to True. `update_note` gets `dry_run=True` because it replaces the full body and the audit keeps only the title. Other updates stay one call. Trade-off: `update_note` needs a small new preview path. | ✓ |
| Deletes only | Only the three deletes change to True. Trade-off: `update_note` can still overwrite a body in one call, and no copy is kept. | |
| All 12 destructive tools | Every update, `complete_reminder`, `update_mail_status` and `run_shortcut` also default to True. Trade-off: every edit takes two calls, and four tools need new preview code. The gate gets larger. | |

**User's choice:** Deletes + update_note (recommended)
**Notes:** It was checked during the discussion that `notes.snapshot` keeps the title only, so an overwritten note body is lost.

---

## Release and daemon rebuilds

| Option | Description | Selected |
|--------|-------------|----------|
| Release now, dev builds in the gate | Release `develop` before card 1, so the daemon gets the Sequoia plane now. The checks after cards 5 and 2 use dev builds, proved by the `doctor().build` sha. The next release comes after Phase 2. Trade-off: one extra release now, and SC6 reads "new build sha". | ✓ |
| No release until Phase 2 ends | Dev builds only. Trade-off: the running daemon stays on 0.10.1 without the Sequoia plane for the whole gate. | |
| Release after cards 5 and 2 | Two releases during the gate, as SC6 says now. Trade-off: two public versions of a half-finished architecture. | |

**User's choice:** Release now, dev builds in the gate (recommended)
**Notes:** `doctor()` showed the installed daemon is 0.10.1, build `5f2cfb1` (2026-08-23).

---

## PR landing and who merges

| Option | Description | Selected |
|--------|-------------|----------|
| Claude merges; owner does device steps | One PR per card. It is rebase-merged when CI is green and a code review finds no open issue. The work stops for the owner only at device steps (card 4 scratch mailbox, card 7 EventKit run, daemon rebuilds). Trade-off: the owner reviews after the merge. | ✓ |
| Owner merges every PR | Each PR stops for the owner. Trade-off: 7 stops, and the chain waits on each merge. | |
| One stacked PR at the end | All cards on one branch with one commit per card, reviewed once. Trade-off: one big review, and the daemon checks run on the branch. | |

**User's choice:** Claude merges; owner does device steps (recommended)
**Notes:** None.

---

## Claude's Discretion

- Re-land method: redo each change on current `develop`, with the spike as the recipe. No cherry-pick.
- Audit verb names: short effect verbs in the style of `send` / `open` / `reply`.
- Card 2 keeps the four decorator names as thin aliases.
- Card 3 fixture runs every `query_*` test against both the native and the Sequoia shape.
- Card 4 byte-identity baseline is generated again from the pre-cut release tag.
- `_DEDUPE`: raise the script backstop to at least 900 s.
- Release version number: 0.11.0.

## Deferred Ideas

- Full-body snapshot for `update_note`, so an edit is recoverable. Backlog.
- Card 6 (MailFilter): only when a 13th Mail filter is added.
- Card 8 (MailAdapter pass-throughs): withdrawn.
