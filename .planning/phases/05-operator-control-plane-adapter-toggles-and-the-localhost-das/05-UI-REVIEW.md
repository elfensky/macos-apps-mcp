# Phase 5 — UI Review

**Audited:** 2026-10-22
**Baseline:** the four sketches (`.planning/sketches/`, 001-004) and the ten rules in the sketch-findings skill. 05-UI-SPEC.md is a pointer only.
**Screenshots:** not captured (static audit by order; no browser, no server)
**Interaction captures:** off (static audit by order)
**Known, not re-reported:** #427 (raw imap:// account UUIDs).

Files read in full or in part: `macos_apps_mcp/dashboard/html.py`, `dashboard.css`, `dashboard.js`, `adapters.py`, `usage.py`, and the grep of `writes.py`, `recovery.py`, `health.py`, `backups.py`. Pages other than Adapters were checked by grep for states, labels and roles, not read line by line.

## Pillar Scores

| Pillar | Score | Key Finding |
|--------|-------|-------------|
| 1. Copywriting | 3/4 | Voice matches the sketches; failure paths return bare plain text |
| 2. Visuals | 3/4 | Frame, groups, chips and switches follow the sketch; decorative glyphs are not hidden from screen readers |
| 3. Color | 2/4 | Tokens copied faithfully, but the faint, success and warning text colors fail contrast |
| 4. Typography | 3/4 | Scale and stack match; many raw px sizes outside the token scale |
| 5. Spacing | 3/4 | 4px grid kept; switch and sidebar targets are small |
| 6. Experience Design | 2/4 | Focus ring nearly invisible; restart bar stays live when locked; plain-text 409/400 dead ends |

**Overall: 16/24**

Rule check (ten hard rules): 1 (two writes only), 5 (Outbound locked, command only, `adapters.py:167-180`), 6 (restart bar text, `adapters.py:108`), 8 (escape-by-default `h()`/`Safe`, `html.py:24-40`) and 10 (no prune control found) hold in the code read. Rules 2, 3, 4, 7 and 9 live in `guard.py` and `writes.py`; rule 4 is visible in `adapters.py:248-261`, rule 9 in the `.preview` / banner code at `writes.py:445-474`. `guard.py` was not audited.

## Top Fixes

1. **BLOCKER — keyboard focus is almost invisible.** `dashboard.css:115` and `:311` draw the focus ring with `--color-selection`, which is `rgba(0,122,255,.12)` (light) or `.24` (dark). A 3px ring at 12% alpha on white is below any visible contrast. Every link, switch, Copy and Restart button depends on it. Fix: use a solid `--color-primary` outline (2px) for `:focus-visible`.
2. **WARNING — text colors fail WCAG contrast.**
   - `--color-text-faint` (#aeaeb2 on white, about 2.2:1) carries the sidebar group headings (`dashboard.css:192`, on #e8e8ed, about 1.8:1) and the empty states "Select a write" / "No writes recorded yet" (`:248`, used at `writes.py:765,778,782`).
   - `.chip.additive`, `.chip.ok`, `ins.w` and `.chip.outbound` put `--color-success` (#34c759) or purple on a 14% tint of the same hue (about 2:1) (`:125-129`, `:343`). The "adds" tier chip and the `ins` word diff are the core review signal.
   - `#c77700` on the orange tint (`:125`, `:322`, `:366`) is about 3:1 at 11px.
   Fix: a darker text token per hue for light mode (as already done once for orange), and `--color-text-muted` for empty states and group headings.
3. **WARNING — failure and locked states dead-end or mislead.**
   - `adapters.py:294,298,302,304`: a rejected toggle (env override, unreadable file, bad token, stale form) answers a bare `PlainTextResponse` 409/400 with no frame, no sidebar and no way back. Fix: render the Adapters page with the `banner warn` and the same status code.
   - `adapters.py:103-126`: when `locked` is true the Discard form is hidden but the "Restart daemon" form stays. Restart is still allowed while the file is unreadable, and the bar claims changes "wait" that the operator cannot change or discard. Decide per D-20 and either hide the bar or explain.
   - `adapters.py:240` plus `dashboard.css:328`: the restarting state sets `pointer-events:none` on the group only, but the page reloads every 12 s by meta refresh with no `prefers-reduced-motion` guard for the `.spin` animation (`:325`). Low risk; note only.

## More Findings

### Pillar 1: Copywriting (3/4)
- Voice follows the sketch: short sentences with a next step ("Fix the file's permissions, then reload this page.", `adapters.py:33-36`). The restart bar names the dropped connections (rule 6).
- Singular/plural handled (`adapters.py:114-116`, `:59`).
- Generic strings remain: the filter submit is "Filter" next to a placeholder "Filter" (`writes.py:738-742`); two controls with one word.
- The sub line "Automation · Full Disk Access · 27 tools · 3 calls" can be cut by `white-space:nowrap; text-overflow:ellipsis` on phone (`dashboard.css:176-177`), hiding the grant text it exists to show.

### Pillar 2: Visuals (3/4)
- Structure matches sketch 001 D: sidebar, list, detail, system pages (`html.py:201-237`). Appico placeholders, grouped rows and the locked Outbound row follow sketch 004.
- Banner icons (`ⓘ ✓ ⚠ ● ↺ ↩`, `writes.py:474,558,602,619`, `health.py:265,315`) and the lock glyph (`dashboard.css:329`) are plain text. Screen readers read "circled latin small letter i". Mark them `aria-hidden="true"`.
- The state is carried by background tint alone in places (`.banner.warn`, `.banner.bad`), with a glyph that is the only non-color cue; add a word (the bold lead already does so in most banners).
- Preview rows dim to opacity .6 (`dashboard.css:244`), which pushes muted sub text (6.0:1 normal) below 4.5:1. Rule 9 is met (chip plus banner) but the dimming costs legibility.

### Pillar 3: Color (2/4)
- Tokens match `themes/default.css` one to one; dark mode overrides present (`dashboard.css:56-94`).
- Hardcoded colors outside the token set: `#c77700` (6 uses), `#b3541e`, `#ff9f6b`, appico gradients, `#fff`. The sketch allows the app icons; the rest should be tokens.
- Accent use is restrained: primary on the active nav row, the switch and Restart only. The 60/30/10 split is respected.
- Contrast failures listed under Top Fixes, item 2.
- Dark mode: the `.chip.additive/.ok` text uses the brighter dark success on a 14% tint (about 5:1), so dark is acceptable; the defect is light mode.

### Pillar 4: Typography (3/4)
- Scale and stack match the findings (13px base; `--text-*` tokens used).
- Raw sizes bypass the tokens: 11px (`:207,329`), 11.5px (`:379`), 12px (`:349,361`), `0.92em` (`:111`). Four different near-11/12 values exist. Map them to `--text-xs/sm`.
- Weights stay at 500/600/700 only. Fine.

### Pillar 5: Spacing (3/4)
- Spacing tokens are used throughout; a few raw values (9px, 6px, 3px, 5px, 7px) are in sketch components and carried over unchanged.
- Switch is 32x18 and the sidebar nav row is about 26px high (`:197`); both are under the 44px touch target on the phone layout. The switch can be enlarged with padding on the `button` (the span is absolutely positioned).
- Phone: the sidebar becomes a horizontal strip (`:287-300`) with group headings hidden, so "Writes" filters and "System" pages run together in one scroll row, with the Apps filters (up to ten) pushing System pages off screen. The sketch accepts the strip; the cost is that Adapters, Health and Backups may be several swipes away.

### Pillar 6: Experience Design (2/4)
- States covered: empty list, no match, unreadable audit log (`writes.py:767-782`), unreadable adapters file, env override, unreadable grants, doctor failure (`health.py:337`), no receipts (`backups.py:105`), no calls (`usage.py:35`). This is broad and good.
- Gaps: focus ring; plain-text error pages; locked-but-restartable bar (Top Fixes 1 and 3).
- The switch is a `button aria-pressed` with an `aria-label` of the app name only (`adapters.py:137`). The label does not say what pressing does, and a screen reader hears "Mail, toggle button, pressed" with no word "adapter". Prefer `aria-label="Mail adapter"`.
- The pending chip, sticky bar and Discard follow sketch 004 A.
- No `role="status"` / `aria-live` on the restarting bar or banners; the state change arrives by full page load, so this is minor.
- `<nav>` landmark missing: the sidebar is an `<aside>` of plain links (`html.py:165`); wrap the links in `<nav aria-label="Dashboard">`. No skip link; the sidebar holds up to 20 links before the content.
- Writes list is a set of `a.row` links, usable by keyboard. The Copy button changes its own text to "Copied" (`dashboard.js:28`) with no live region.

## Files Audited
- `macos_apps_mcp/dashboard/html.py`, `dashboard.css`, `dashboard.js`, `adapters.py`, `usage.py`
- `macos_apps_mcp/dashboard/writes.py`, `recovery.py`, `health.py`, `backups.py` (grep and excerpts)
- `.planning/sketches/MANIFEST.md`, `001`-`004` READMEs, `themes/default.css`
- `.claude/skills/sketch-findings-macos-apps-mcp/SKILL.md`
