---
sketch: 003
name: recovery-flow
question: "How does the operator get a batch of mail back — and does the dashboard act itself, or only show what to ask Claude?"
winner: "D"
tags: [recovery, undo, safety, phase-5, dashboard]
---

# Sketch 003: Recovery flow

## Design Question
Inside frame D, a batch Mail write (move, trash, dedupe) carries a receipt and a backup. How does
the operator get those messages back, and is the dashboard allowed to perform the undo itself?

## How to View
open .planning/sketches/003-recovery-flow/index.html

## Variants
- **A: Undo here — preview, then confirm** — the dashboard acts. "Undo…" opens a preview (every message: Trash → INBOX, left-out messages named), then "Move 6 back" runs `mail_undo(dry_run=false)` with live per-message progress. Logged with caller `dashboard`.
- **B: Read-only — ask Claude to undo** — the dashboard never writes. It shows the batch, a copyable prompt ("Undo mail receipt …") and the exact tool call, then watches `audit.jsonl` and flips to "Undone" when the undo lands.
- **C: Backup files — manual recovery** — the per-message `.eml` backups with fidelity (`full` / `partial` / `no backup`), Open and Reveal buttons, a fidelity legend, and a System → Backups page (size, advisory limit, receipt folders). For when the server copy is gone.
- **D: B + C — read-only** ★ — synthesis. The batch with each message's `.eml` backup and fidelity, then B's "ask Claude" prompt and audit watch, then the fidelity legend and the receipt folder. System → Backups page from C.

## Decision
**D — the dashboard stays read-only.** It shows the batch, each message's backup and the undo
prompt; the undo itself runs through Claude and `mail_undo`, where writes are gated,
dry-run-first and audited. The backup files cover the case where the server copy is gone.
Cost accepted: one copy and paste per undo. No write endpoint means no token, Origin check or
second audit path for recovery.

## What to Look For
- Type `coffee` or `pharmacy` in the filter: search reaches the messages inside a batch.
- A: run the undo end to end. B: copy the prompt, then "simulate Claude running it".
- Does a write button on a web page feel as safe as the MCP path with its dry-run default?

## Safety Notes (from the code and the Phase 5 scope)
- **Phase 5 scope says browse.** PLAT-02 asks for "browsable recoverable-plane backups
  (recovery/history)"; the only dashboard write it names is the adapter toggle. Variant A
  widens the scope.
- **A loopback write endpoint is reachable from any web page.** Binding to 127.0.0.1 stops
  other machines, not the browser: a page on any site can POST a form to
  `http://127.0.0.1:<port>/undo`, and DNS rebinding can read responses. An acting dashboard
  needs a Host/Origin check and a per-session token on every write, not only a loopback bind.
- **A dashboard write goes around `AuditMiddleware`.** It must write its own audit record
  (with a caller field, which the log does not have today — see sketch 002).
- **Undo scope is the whole receipt.** `mail_undo` takes a receipt; `undo_plan` keeps only
  targets whose outcome was `ok`, so a missing message is left out, never "moved back".
