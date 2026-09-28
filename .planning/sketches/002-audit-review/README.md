---
sketch: 002
name: audit-review
question: "How does one write read in the detail pane — before → after, what was asked, the receipt — so the operator can judge it in seconds?"
winner: "D"
tags: [audit, detail, phase-5, dashboard]
---

# Sketch 002: Audit review

## Design Question
Inside frame D (sketch 001), how does the detail pane present one write so the operator can
judge it quickly: what changed, what the model asked for, and whether it was only a preview?

## How to View
open .planning/sketches/002-audit-review/index.html

## Variants
- **A: Word diff + what was asked** — the before and after summaries as one word-level diff line, then the call's `args` as a table, with `dry_run` resolved ("not passed — defaulted to true").
- **B: History of the target** — a GitHub-style timeline of every logged write on the same `target_id` (created → updated → now). A batch shows its receipt lifecycle: backed up → acted → undone.
- **C: Sentence + raw record** — one plain sentence ("The model changed Dentist from 14:00–14:30 to 15:00–15:30"), then the exact `audit.jsonl` lines. A batch shows all three lines: the `mail_recover` plan, the done record and the middleware record. Path of least resistance: the server dumps JSON.
- **D: A + C's raw lines** ★ — synthesis. A's word diff and resolved `args`, then the exact `audit.jsonl` lines in a collapsed section at the bottom.

## Decision
**D.** The word diff is the fastest way to judge a write; the raw log lines stay one click away
for when the summary is in doubt. B's per-item history was dropped: most items are touched
once, so the timeline is usually one step.

## What to Look For
- Select the Dentist update (default), the 09:40 trash batch, the 10:03 dedupe that was undone, and the two dimmed previews.
- Can you tell a preview from a real write in under a second, in the list and in the detail?
- Which variant makes a wrong write obvious — the diff (A), the history (B) or the sentence (C)?

## Findings From the Code
- **Previews are logged in the same shape as real writes (#222).** `AuditMiddleware` logs every
  successful write call, including dry runs. Most destructive tools default to
  `dry_run=True`; a caller that omits the flag leaves no `dry_run` key in `args`, so a
  preview `delete_event` looks like a real delete (`before` set, `after` null). The
  dashboard can only tell them apart by knowing each tool's default. A resolved `dry_run`
  field on the audit record would remove that guess.
- **Pointers carry summaries, not fields.** `before` and `after` are `Pointer` dicts, so a
  field-level diff is not possible; A diffs the summary strings word by word, and the
  `args` show the requested values.
- **The caller is not recorded (#222).** No record says which session or client made the write
  (C shows this as "Caller: not recorded").
