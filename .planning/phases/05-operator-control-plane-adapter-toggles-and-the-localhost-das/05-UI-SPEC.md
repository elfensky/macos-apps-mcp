---
phase: "05"
slug: "operator-control-plane-adapter-toggles-and-the-localhost-das"
status: approved
shadcn_initialized: false
preset: none
created: "2026-10-22"
---

# Phase 05 — UI Design Contract

> This file points at the contract; it adds no design of its own. The four sketches of
> 2026-09-28 are the UI contract (05-CONTEXT.md, Claude's Discretion: "the references win").
> The owner chose this pointer form on 2026-10-22 to satisfy the `ui.safety-gate` without a
> second design source that could drift from the sketches.

---

## Design System

| Property | Value |
|----------|-------|
| Tool | none (no SPA framework, no template engine) |
| Preset | not applicable |
| Component library | none: the sketches' own components, ported to `macos_apps_mcp/dashboard/dashboard.css` |
| Icon library | none: the sketches' app tiles |
| Font | the system font stack of `.planning/sketches/themes/default.css` |

Tokens, spacing, type scale and colours: `.planning/sketches/themes/default.css` (light and dark).
Components: `.planning/sketches/_shared/base.css`. Frame: `.planning/sketches/_shared/shell.css`.

---

## Contract Sources

| Source | What it fixes |
|--------|---------------|
| `.planning/sketches/MANIFEST.md` | design direction, the four winners |
| `.planning/sketches/001-dashboard-shell/README.md` | frame D: Console list + detail; System pages |
| `.planning/sketches/002-audit-review/README.md` | variant D: word diff, resolved `dry_run` row, raw lines collapsed |
| `.planning/sketches/003-recovery-flow/README.md` | variant D: read-only recovery, ask-Claude undo prompt |
| `.planning/sketches/004-toggles-and-health/README.md` | variant A: switch, pending chip, restart bar; Outbound locked |
| `.claude/skills/sketch-findings-macos-apps-mcp/` (git-ignored, local) | the ten hard rules, CSS patterns, HTML structures, what to avoid |
| `05-CONTEXT.md` D-08 to D-11, D-19 | security headers and Guard, escaping, static allow-list, routes, page key |

---

## Pages

| Route (D-11) | Sketch | Plan |
|--------------|--------|------|
| `/` and `/write/<ts>` | 001 frame D + 002 variant D | 05-04 |
| `/backups`, `/backups/<receipt>` | 003 variant D | 05-04, 05-05 |
| `/adapters` (GET; POST toggle; POST discard), `/restart` (POST) | 004 variant A | 05-03 |
| `/health` | 004 variant A | 05-05 |
| `/usage` | 001 System page | 05-02 |

Every page works without JS; JS exists only for Copy (D-11). No inline style and no inline
script (D-08 CSP).

---

## Copywriting Contract

The sketch texts are the copy, word for word: page texts, chips (`adds` / `changes` / `sends` /
`preview`), day headers, the preview banner, the word diff and the resolved `dry_run` row
(D-11; 05-CONTEXT.md, Specific Ideas).

---

## Registry Safety

No component registry and no third-party UI code. The only new runtime dependency is
`starlette` (05-08, D-09), already locked as a dependency of `mcp` and `fastmcp`.

---

## Checker Sign-Off

Not run: the contract is the sketches, which the owner approved on 2026-09-28. A conflict
between this file and a sketch reference is resolved in favour of the sketch.
