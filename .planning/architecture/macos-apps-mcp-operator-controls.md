---
kind: component
title: Operator controls
component: operator-controls
status: implemented
source_revision: 67a668c39484ebc2017c092d008f1dd705ccff73
source_evidence_date: 2026-11-09
---

# Operator controls

[Architecture overview](macos-apps-mcp-architecture.md)

## What it does

The daemon serves a Starlette dashboard at literal loopback address `127.0.0.1:47632`.
Its TCP routes remain separate from the [MCP Unix socket](macos-apps-mcp-transport.md).
The dashboard displays audit entries, write diffs, usage, health, adapter settings, and Mail backup receipts.
It reads registration facts from `registry.py` without importing the server layer.

Opening the app runs the `launch` role. The first open registers the agent, asks for the grants once and opens Health.
Later opens show the dashboard home. Each open links the CLI into `~/.local/bin`.
The `dashboard [page]` command prints the page-key link and opens it.
Doctor reports permissions, version/build metadata, storage status, and configured versus registered capabilities.
Doctor defaults to diagnostics without permission prompts; `request=True` can request grants.
Doctor reports the version and build that the serving process read at start. A bundle replaced on disk changes them only after a restart (#574).

**eli14:** The dashboard is the workshop's control panel behind a local access door.
The door needs a key because other accounts and apps on this Mac can reach the same building.
Changing a switch can require a restart, which can interrupt unfinished jobs.
A panel label does not prove that the app has granted permission.

### Adapter permission chips

Adapters reads the last completed Health report through `health.last_permissions()`.
Automation uses Health's existing live/TCC merge; other permissions use the same report's TCC data.
Explicit Full Disk Access and EventKit probe refusals override those rows.
Before the first completed report, `deploy.grant_report()` supplies the existing TCC-only fallback.
The page identifies the report's completion time and links to Health.
Rendering makes no native call; failed or unfinished checks retain the previous report.

## Rules it keeps

### Implemented dashboard boundary

Every request passes `Guard` before reaching a route.

| Check | Effect |
|---|---|
| Host | Only the configured `127.0.0.1` or `localhost` host and port are accepted. |
| Page key | Every route except `/key` requires the key cookie. A valid `/key` link sets the cookie, then redirects to `/` or to the one lowercase page that `to` names. |
| Unusable key | Requests receive 503 after Host validation. |
| Mutation origin | Non-GET/HEAD requests require an allowed Origin, or `Sec-Fetch-Site: same-origin` when Origin is absent. |
| Mutation token | A per-process token uses constant-time comparison; form bodies have an 8 KiB cap. |
| Response policy | CSP, frame denial, content-type protection, same-origin referrers, and no-store headers apply, including refusals. |

The key cookie is HttpOnly and SameSite Strict.
Dashboard CSS and JavaScript are bundled local files.
Proxy headers and access logging are disabled; the latter avoids logging page-key query strings.
Dashboard bind or construction failure does not stop MCP service.

### Settings and recovery

Adapter toggles persist the deny-list. Registration changes after a daemon restart, with pending differences displayed beforehand.
The switches and the restart lock when `MACOS_APPS_ADAPTERS_OFF` is set, or when the `adapters_off` file cannot be read.
Restart drops MCP connections and can interrupt a Mail batch. Clients must reconnect.
Operator action logging remains [best-effort](macos-apps-mcp-audit-and-recovery.md); the dashboard can report a lost record.

Outbound enablement remains an operator CLI action through `allow-send`, not a dashboard form or MCP tool.
Direct stdio deployments use their process-start environment settings.
The backup and recovery pages are read-only; they neither invoke undo nor purge backups.

## Code paths

- [Dashboard routes](../../macos_apps_mcp/dashboard/__init__.py), [Guard](../../macos_apps_mcp/dashboard/guard.py), and [adapter controls](../../macos_apps_mcp/dashboard/adapters.py).
- [Recovery view](../../macos_apps_mcp/dashboard/recovery.py), [Backups](../../macos_apps_mcp/dashboard/backups.py), [Health](../../macos_apps_mcp/dashboard/health.py), and [grants](../../macos_apps_mcp/dashboard/grants.py).
- [doctor.py](../../macos_apps_mcp/doctor.py), and [deploy.py](../../macos_apps_mcp/deploy.py).
- [Guard tests](../../tests/test_dashboard_guard.py), [key tests](../../tests/test_dashboard_key.py), and [dispatcher tests](../../tests/test_daemon_dispatch.py).
- [Deploy tests](../../tests/test_deploy.py), [serving identity tests](../../tests/test_doctor_serving_identity.py), and [permission chip tests](../../tests/test_dashboard_adapter_health.py).

## Sources

- [Phase 5 verification](../phases/05-operator-control-plane-adapter-toggles-and-the-localhost-das/05-VERIFICATION.md) and [Phase 05.1 verification](../phases/05.1-bug-fixes-dashboard-follow-ups-427-428-430/05.1-VERIFICATION.md).
- [Phase 05.2-16 device acceptance](../phases/05.2-bug-fixes-automation-grants-unreadable-on-macos-27-455/05.2-16-SUMMARY.md): failed on build `926ec99`, so Phase 05.2 stays open.
- [Grant-chip implementation and review limits](../phases/05.6-bug-fixes-notes-write-safety-and-system-folders-in-any-langu/05.6-04-SUMMARY.md).
- [Installed evidence](../overnight/2026-11-04-installed-acceptance.md): on 2026-11-04 the installed daemon passed the Health and Adapters checks.

No permission was revoked to force a denial. In-flight report replacement has synthetic tests only. Issue #497 stays open.
Phase 05.5 of the [roadmap](../ROADMAP.md) holds the domain-hosted dashboard loader (#483). The phase is optional and has not started.
