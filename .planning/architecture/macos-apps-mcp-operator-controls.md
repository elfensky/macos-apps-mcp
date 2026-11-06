---
kind: component
title: Operator controls
component: operator-controls
status: implemented
source_revision: 4a7c26287b108c9c81f42db0bdf5280ed537e986
source_evidence_date: 2026-11-04
review_status: source-checked-update
publication_status: published
first_published_at: "2026-11-04T01:34:18Z"
first_published_revision: 93c7f0928d2534ddae2392e78ec722f55491a2ae
---

# Operator controls

[Architecture overview](macos-apps-mcp-architecture.md)

## Responsibility and interfaces

The daemon serves a Starlette dashboard at literal loopback address `127.0.0.1:47632`.
Its TCP routes remain separate from the [MCP Unix socket](macos-apps-mcp-transport.md).
The dashboard displays audit entries, write diffs, usage, health, adapter settings, and Mail backup receipts.
It reads registration facts from `registry.py` without importing the server layer.

The CLI opens the dashboard through a local page-key link.
Doctor reports permissions, version/build metadata, storage status, and configured versus registered capabilities.
Doctor defaults to diagnostics without permission prompts; `request=True` can request grants.
The current installed build is not inferred from source metadata.

**eli14:** The dashboard is the workshop's control panel behind a local access door.
The door needs a key because another browser page can still reach the same building.
Changing a switch can require a restart, which can interrupt unfinished jobs.
A panel label does not prove that the app has granted permission.

## Implemented dashboard boundary

Every request passes `Guard` before reaching a route.

| Check | Effect |
|---|---|
| Host | Only the configured `127.0.0.1` or `localhost` host and port are accepted. |
| Page key | Every ordinary route requires the key cookie. The `/key` link exchanges a valid key for that cookie. |
| Unusable key | Requests receive 503 after Host validation. |
| Mutation origin | Non-GET/HEAD requests require an allowed Origin, or `Sec-Fetch-Site: same-origin` when Origin is absent. |
| Mutation token | A per-process token uses constant-time comparison; form bodies have an 8 KiB cap. |
| Response policy | CSP, frame denial, content-type protection, same-origin referrers, and no-store headers apply, including refusals. |

The key cookie is HttpOnly and SameSite Strict.
Dashboard CSS and JavaScript are bundled local files.
Proxy headers and access logging are disabled; the latter avoids logging page-key query strings.
Dashboard bind or construction failure does not stop MCP service.

## Settings and recovery

Adapter toggles persist the deny-list. Registration changes after a daemon restart, with pending differences displayed beforehand.
Restart drops MCP connections and can interrupt a Mail batch. Clients must reconnect.
Operator action logging remains [best-effort](macos-apps-mcp-audit-and-recovery.md); the dashboard can report a lost record.

Outbound enablement remains an operator CLI action through `allow-send`, not a dashboard form or MCP tool.
Direct stdio deployments use their process-start environment settings.
The backup and recovery pages are read-only; they neither invoke undo nor purge backups.

## Sources and planned work

- [Dashboard routes](../../macos_apps_mcp/dashboard/__init__.py), [Guard](../../macos_apps_mcp/dashboard/guard.py), and [adapter controls](../../macos_apps_mcp/dashboard/adapters.py).
- [Recovery view](../../macos_apps_mcp/dashboard/recovery.py), [doctor.py](../../macos_apps_mcp/doctor.py), and [deploy.py](../../macos_apps_mcp/deploy.py).
- [Guard tests](../../tests/test_dashboard_guard.py), [key tests](../../tests/test_dashboard_key.py), and [dispatcher tests](../../tests/test_daemon_dispatch.py).
- [Phase 5 verification](../phases/05-operator-control-plane-adapter-toggles-and-the-localhost-das/05-VERIFICATION.md) and [Phase 05.1 verification](../phases/05.1-bug-fixes-dashboard-follow-ups-427-428-430/05.1-VERIFICATION.md).
- [Phase 05.2 acceptance](../phases/05.2-bug-fixes-automation-grants-unreadable-on-macos-27-455/05.2-13-PLAN.md).

Adapters reads the last completed Health report through `health.last_permissions()`.
Automation uses Health's existing live/TCC merge; other permissions use the same report's TCC data.
Explicit Full Disk Access and EventKit probe refusals override those rows.
Before the first completed report, `deploy.grant_report()` supplies the existing TCC-only fallback.
The page identifies the report's completion time and links to Health.
Rendering makes no native call; failed or unfinished checks retain the previous report.

Real macOS 27 acceptance remains pending. The grant-chip additions have source validation after the earlier independent architecture review.
[Implementation and review limits](../phases/05.6-bug-fixes-notes-write-safety-and-system-folders-in-any-langu/05.6-04-SUMMARY.md) and [regression tests](../../tests/test_dashboard_adapter_health.py) record the evidence.
The domain-hosted dashboard loader remains planned in Phase 05.5 of the [roadmap](../ROADMAP.md).
