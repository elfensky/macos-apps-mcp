---
sketch: 004
name: toggles-and-health
question: "How do adapter toggles show 'restart needed', how does Health reflect the active set — and may the dashboard write the toggle at all?"
winner: "A"
tags: [adapters, health, toggles, safety, phase-5, dashboard]
---

# Sketch 004: Toggles and health

## Design Question
Phase 5 criterion 3 says the dashboard exposes the adapter toggles, and a change shows in
`doctor` and in tool presence after the daemon restarts. How does the page show the gap between
"configured" and "running", and should the toggle be a write from the page at all?

## How to View
open .planning/sketches/004-toggles-and-health/index.html

## Variants
- **A: Switch + restart here** — System Settings switches; a changed row reads "off after restart"; a sticky bar collects pending changes with Discard and "Restart daemon"; the page shows "Restarting…" and reconnects.
- **B: Switch saves, you restart** — the switch writes the config only. Each row shows both states (running / not loaded, and "config: on" when they differ), like `doctor`'s outbound configured vs registered. A banner gives the `launchctl kickstart` command; the operator picks the moment, because a restart drops every MCP client's connection.
- **C: Read-only + CLI command** — no switches. Each row shows On/Off and "Change…" reveals a Terminal command (`macos-apps-mcp adapters off photos`) that writes the config and restarts, like `allow-send`. The dashboard has no write endpoint at all.

## Decision
**A — switch + restart on the page** (keeps Phase 5 criterion 3 as written). The toggles and the
restart are the dashboard's only two write actions; recovery stays read-only (sketch 003).
Conditions carried into Phase 5:
- both actions check `Host` and `Origin` and require a per-session token;
- each toggle and each restart writes an audit record with caller `dashboard`;
- the restart bar says that a restart drops open MCP connections;
- the Outbound gate is shown locked and changes only through `allow-send`.

All variants: the Outbound gate is shown locked, with its `allow-send` command. Health lists the
active adapter set, links a pending change to the Adapters page, and raises a banner only when an
**active** adapter's grant is denied (turn Photos on and restart in A to see it).

## What to Look For
- A: toggle Photos and Music, then Restart; open Health afterwards.
- B: toggle, then read the row states before and after "simulate a restart".
- C: "Change…" on any row.
- Does the pending state read clearly without a restart button (B), or at all without a switch (C)?

## Findings From the Code
- **Consent gates are not MCP tools on purpose.** `deploy.allow_send`: "Deliberately NOT an MCP
  tool: the gate is the operator's consent, so the model must not be able to grant itself
  sending (and the restart would drop the caller's own connection)." Adapter toggles are the
  same kind of gate, so "ask Claude" (sketch 003's answer) does not apply here.
- **A web toggle is reachable from any website.** A switch is a POST to 127.0.0.1; without a
  Host/Origin check and a per-session token, any page the operator visits could flip it. The
  Outbound gate must never be on the page.
- **Even a read-only dashboard needs a Host check.** DNS rebinding lets a remote page read
  loopback responses — the audit trail and message subjects — unless the server rejects an
  unexpected `Host` header.
- **Registration is fixed at import.** The daemon reads adapter config once at start, so every
  variant has a "configured but not running" state to show; `doctor` already models it for
  outbound (`outbound_pending`).
