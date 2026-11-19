# Phase 5: Operator Control Plane — Adapter Toggles and the Localhost Dashboard - Discussion Log (Assumptions Mode)

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the analysis.

**Date:** 2026-10-21
**Phase:** 05-operator-control-plane-adapter-toggles-and-the-localhost-dashboard
**Mode:** assumptions
**Areas analyzed:** Adapter toggle setting and gate; Dashboard transport and security; Rendering and data sources; Writes, restart, tests and device proof

## Method

The orchestrator scouted `daemon.py`, `tiers.py`, `cli.py`, `deploy.py`, `doctor.py`, `audit.py`,
`mail_recover.py`, `server.py`, `pyproject.toml`, the launchd plist, issue #126 and the sketch skill,
then spawned `gsd-assumptions-analyzer` (opus) with six working hypotheses to verify. The analyzer
read 5-15 files, probed the installed uvicorn 0.52.4, built a test wheel, read `man launchd.plist`
and `man launchctl`, and measured this Mac's audit log and backup tree. Calibration: standard.

## Assumptions Presented

### Adapter toggle setting and gate
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Deny-list file `adapters_off` beside `allow_send`; env `MACOS_APPS_ADAPTERS_OFF` wins; file read in the daemon role only; absent = all on | Likely | `tiers.py:61-69`, `deploy.py:290-301` |
| `tiers.adapter_enabled` ANDed into `registered` for every record with an adapter, send tier too; meta tools never gated; adapter instances stay | Confident | `server.py:161-183`, `registry.py:106-130`; 66 adapter tools, 5 meta tools; no adapter `__init__` |
| `registry.adapter_status()` mirrors `outbound_status()`; `outbound_status()["configured"]` ANDs `adapter_enabled`; doctor adds `adapters` and `adapters_pending` | Confident | `registry.py:177-196`, `doctor.py:413-419`, `test_doctor_deploy.py:136-171` |
| doctor makes no prompt and no Apple Event for an OFF adapter; surface kept with `status: "adapter_off"`, left out of counts | Likely | `doctor.py:39-46,167`, `eventkit.py:107-124` |
| No CLI twin this phase | Likely | `cli.py:9-19,50-53`; sketch 004 variant C rejected a CLI as the only path |

### Dashboard transport and security
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| One uvicorn `Server.run(sockets=[uds, tcp])` behind an ASGI dispatcher; `/mcp` never on TCP; UDS scope has `server == (path, None)`, `client is None` | Confident | `uvicorn/protocols/utils.py:36-37`, `uvicorn/server.py:106-147,323-347`; live probe |
| Fixed port 47632 on 127.0.0.1 behind a loopback guard; a failed bind keeps MCP serving | Likely | `daemon.py:54-80,202-224`; `.planning/sketches/_shared/data.js:6` |
| Host on every request; token + Origin (or `Sec-Fetch-Site`) on POST; CSP with `frame-ancestors 'none'` | Likely | `starlette/middleware/trustedhost.py:40`; sketch rules 2, 3, 8 |

### Rendering and data sources
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Starlette + hand-rolled HTML through an escape-by-default helper; no jinja2; `starlette` listed, version bump forced | Likely | jinja2 absent from `uv.lock` and the venv; `.github/workflows/version.yml` |
| One `dashboard.py` + css + js as package files; recovery read-only (path + Copy); no live watch | Likely | wheel build with a dummy css; sketch CSS 14,319 B; sketch rules 1 and 10 |
| Reader over `audit.jsonl.1` + `audit.jsonl`; legacy `dry_run` resolved from defaults; outcomes from `done.results`; adjacency link | Likely | `audit.py:46,67-68,84-118,202-208`; `mail_recover.py:479-517`; 369/369 adjacency |
| Backups page from the disk tree; never `_backup_dir()`; undo prompt only when `find_receipt` resolves | Likely | `mail_recover.py:316-322,559-594`; 935 receipts, 188 MB, 562 ms |
| Health and Usage in the thread pool; Health bounds its wait | Likely | `doctor.py:113-116,332`, `runtime.py:47-57`, `starlette/concurrency.py:32` |

### Writes, restart, tests and device proof
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Toggle POST rewrites the file and appends a `tool: "dashboard"` record with `dry_run: false`, `caller: "dashboard"` | Confident | `audit.py:61-72`, `deploy.py:345-346`, `mail_recover.py:582` |
| Restart via the daemon's own exit (`should_exit` + `force_exit`), launchd relaunches; no `launchctl` from inside the job | Likely | `uvicorn/server.py:301-317`; plist `KeepAlive`/`ThrottleInterval`; `man launchd.plist` |
| Tests: per-gate subprocess harness + `httpx.ASGITransport`; conftest patches the file constant | Confident | `tests/test_registry.py:155-205`, `tests/conftest.py:30-37`, `starlette/testclient.py:33-45` |
| Phase close is a device proof; release 0.15.0 is the owner's call | Unclear | `pyproject.toml:3` 0.14.3, `CHANGELOG.md:7` `[Unreleased]`, `docs/RELEASING.md` |

## Orchestrator Adjustments Before Presentation

- **Restart mechanism.** The analyzer's first pick was `launchctl kickstart -k` from a background
  task inside the daemon, with an open question whether a `launchctl` child of the job survives
  the kill. The orchestrator replaced it with the analyzer's alternative (1): set uvicorn's
  `should_exit` and `force_exit` and let `KeepAlive` relaunch. Verified in the installed uvicorn
  that `force_exit` skips the wait for connections and tasks. No device research needed.
- **Research items dropped.** (a) `launchctl` from inside the job: moot. (b) Browser `Origin` on a
  same-origin POST and loopback as a secure context: settled by accepting `Sec-Fetch-Site:
  same-origin` when `Origin` is absent, with the token as the real guard; loopback is a secure
  context by specification. (c) Starlette's `TestClient` httpx fallback: avoided by using
  `httpx.ASGITransport` directly.
- **Added decisions the analyzer did not raise:** `Open Settings` as a plain
  `x-apple.systempreferences:` link; `deployment.dashboard` in doctor; `adapters_unknown`; the
  dated amendment to `docs/landscape.md`'s floating note.

## Corrections Made

No corrections — all assumptions confirmed ("Yes, proceed").

## Owner Decisions

### Release at phase close
| Option | Description | Selected |
|--------|-------------|----------|
| Cut 0.15.0 at phase close | Last plan: owner approves, `--no-ff` cut, tag, build, notarize, install, `doctor().version` proof; device proof on the installed release | ✓ |
| Dev-build proof only | Device proof on a dev-stamped `.app`; the version still bumps to 0.15.0 in the pyproject PR; release later | |

**User's choice:** Cut 0.15.0 at phase close.
**Notes:** The installed daemon is 0.14.3; Photos (Phase 4) and the 04.1 fixes are unreleased. The
`starlette` line in `pyproject.toml` forces a version bump in any case (`version.yml`).

## Auto-Resolved

Not applicable (interactive run).

## External Research

None performed — see "Orchestrator Adjustments" for why the three flagged items were settled by design.

---

*Phase: 05-operator-control-plane-adapter-toggles-and-the-localhost-das*
*Discussion log generated: 2026-10-21*
