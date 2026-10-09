---
phase: quick-261009-tqc
plan: 01
subsystem: mail
tags: [mail, gmail, labels, "#291", device]
status: complete
key-files:
  modified:
    - docs/mail-applescript-facts.md
metrics:
  completed: 2026-10-09
actuals:
  tasks: 1
  commits: 1
---

# Quick 261009-tqc: facts §5f — the #291 label undo on a healthy Mail; reply/forward from a label

Docs-only record of two owner-approved device runs (item 6, 2026-10-09). PR #320, commit `a2d6334`.

## Results

- **#291 T3 rerun, healthy Mail** (health 1.35/0.65/1.62/1.56 s, cap 2.0 s; code 70186a1 in a
  scratch worktree with a scratch state dir; new label `mcp-291-rerun`): T1 was a move. T3 read
  `ok` at +20 s; at +2 min a new Gmail All Mail row with the label was back; held at +5 and
  +15 min. Decided: not a slow-Mail drop. The #291 refusals stay.
- **Reply/forward from a label** (daemon 0.14.2): `mail_reply` gives a threaded draft;
  `reply_all` and `forward_mail` deliver correctly (headers and bodies checked on the
  delivered messages, sends to andrei@lav.ren only); no draft litter.
- **Cleanup:** 7 copies trashed by `trash_mail` (receipts `…-450-trash`, `…-451-trash`,
  `…-452-trash`); held at +2 and +15 min. Two throwaway drafts deleted. Left for the owner:
  the empty label `mcp-291-rerun` (not scriptable, §5b) and one compose window (⌘W, §5e).

## Checks

`uv run pytest -q` 1947 passed (exit 0); `MACOS_APPS_ALLOW_SEND=mail uv run pytest -q` 1943 passed,
4 skipped (exit 0); `ruff check` exit 0; `ruff format --check` exit 0.
