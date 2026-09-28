---
sketch: 001
name: dashboard-shell
question: "What frame holds the Phase 5 operator dashboard, when reviewing writes and recovering mail is the core action?"
winner: "D"
tags: [layout, navigation, phase-5, dashboard]
---

# Sketch 001: Dashboard shell

## Design Question
What frame holds the Phase 5 localhost dashboard? The core action is to review what the model
wrote and to recover mail from a backup. Health, adapter toggles and usage are secondary.

## How to View
open .planning/sketches/001-dashboard-shell/index.html

## Variants
- **A: Sidebar sections** — Tailscale-style sidebar: Activity, Recovery (review) above Adapters, Health, Usage (system). One section at a time in the main pane.
- **B: Console list + detail** — Console / Little Snitch three columns: filters (by app, by tier, batches with receipts), the list of writes, the detail of one write. Health and Adapters open as a sheet, so the home screen is always the list.
- **C: One status page** — a single scrolling page: a health sentence, "Needs attention", the recent writes as native `<details>` rows, then Recovery, Adapters and Usage. Buildable with no JS (path of least resistance for Starlette + server-rendered HTML).
- **D: B's list + system pages** ★ — synthesis. B's filters, list and detail for review; Health, Adapters and Usage open as full pages in the main area (A's pattern), not as a sheet.

## Decision
**D.** Review stays the home screen as a Console-style list + detail. System items are real
pages, not popups: a sheet is for a quick glance, and health, grants and toggles need room.
Each page is a plain URL, so the server can render it with no JS.

## What to Look For
- How many clicks from opening the page to seeing what changed and its before-state.
- Whether health and adapter toggles feel buried (B) or crowd the review (C).
- Which frame still holds when the audit trail has 500 writes, not 11.
- Phone width: A turns the sidebar into a strip, B pushes the detail as a new view, C just reflows.

## Grounding
Fake data in `../_shared/data.js` uses the real shapes: `audit.py` records (`ts`, `tool`, `op`,
`args`, `target_id`, `before`, `after`) and `mail_recover` receipts (plan + done, per-target
`folder`, `fidelity`, `status`).
