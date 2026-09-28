# Sketch Manifest

## Design Direction
The Phase 5 operator dashboard (PLAT-01, PLAT-02), served by the daemon on loopback only and
rendered without an SPA framework. It feels calm and native to macOS, like System Settings:
grouped inset rows, the system font, automatic light and dark. The core action is to review
what the model wrote — before-state, after-state, the receipt — and to undo it or recover mail
from the recoverable-plane backup. Health, `doctor` output, adapter toggles and usage are
secondary and must not crowd the review. All sketch data is invented (the repo is public) but
follows the real `audit.py` and `mail_recover` record shapes.

## Reference Points
- Little Snitch and Console.app — a list of events beside the detail of one event
- Tailscale admin console — sidebar sections, a table with a toggle per row
- GitHub and Sentry audit logs — a timeline of actor, action, target

## Shared Files
- `themes/default.css` — tokens only (macOS system colours, SF font stack, light + dark)
- `_shared/base.css` — shared components (grouped rows, chips, switch, buttons, app icons)
- `_shared/sketch.js` — sketch chrome: variant tabs, theme / viewport / annotate toolbar, toast
- `_shared/data.js` — invented audit records, receipts, adapters in the real shapes

## Sketches

| # | Name | Design Question | Winner | Tags |
|---|------|----------------|--------|------|
| 001 | dashboard-shell | What frame holds the dashboard when review + recovery is the core action? | **D** B's list + detail; Health, Adapters, Usage as pages | layout, navigation |
| 002 | audit-review | How does one write read, with before → after, deeplink and receipt? | **D** word diff + resolved args; raw audit.jsonl collapsed | audit, detail |
| 003 | recovery-flow | How do you restore a batch — and does the dashboard act, or only show? | **D** read-only: per-message backups + ask-Claude undo prompt | recovery, safety |
| 004 | toggles-and-health | How do grants, `doctor` and adapter toggles show "restart needed"? | **A** switch + pending chip + restart bar; outbound locked | adapters, health |
