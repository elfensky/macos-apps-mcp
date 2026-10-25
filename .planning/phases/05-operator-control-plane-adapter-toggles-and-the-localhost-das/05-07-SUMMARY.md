---
phase: 05-operator-control-plane-adapter-toggles-and-the-localhost-das
plan: 07
subsystem: device-proof
tags: [device-proof, dashboard, adapter-toggle, restart, launchd, v0.15.0]
requires: [05-06, 05-09]
provides: [device evidence that the dashboard toggle and restart work on the installed 0.15.0 in the owner's browser]
affects: []
requirements: [PLAT-01, PLAT-02]
key-files:
  created: []
  modified: []
decisions:
  - "No tracked file changed: the proof script .worktrees/.p05_dashboard_proof.py is git-ignored and stays for the next release"
status: complete
commits: 0
plan_head_before: 3cab97e59012aba368b24b7ed3ef2e7a3df30dd2
plan_head_after: 3cab97e59012aba368b24b7ed3ef2e7a3df30dd2
---

# Phase 5 Plan 07: Device proof on the installed 0.15.0 Summary

The installed 0.15.0 daemon accepted a Photos switch-off from the owner's browser, was relaunched by launchd, and served without Photos. A scripted run then switched Photos back on through the dashboard's own endpoints. The daemon came back with all 10 adapters and the four Photos tools. The `off`, `restore` and `on` modes each exited 0.

## Task 1: proof script and baseline (tracer)

Script: `.worktrees/.p05_dashboard_proof.py` (git-ignored). It reads the page key from its file, sends it as a cookie, and prints no key. Baseline exited 0 with 17 PASS lines: version 0.15.0; 10 adapters; photos on; `adapters_off` []; four Photos tools listed; dashboard `http://127.0.0.1:47632`; `GET /usage` 200 with a CSP header and `Referrer-Policy: same-origin`; foreign Host 400; POST without token 403; `POST /mcp` 403 `Forbidden origin`; `GET /mcp` 404; GET without cookie 403 naming the `macos-apps-mcp dashboard` command. State: baseline pid 84285, baseline timestamp 2026-10-22T21:32:54. The key grep printed 0 on the output, the JSON and the script.

## Task 2: owner's browser sitting (human-verify, blocking)

The owner answered "photos off" on 2026-10-22. The browser was not named; it was the owner's everyday browser. The owner switched Photos off, the restart bar appeared, and the daemon restarted from the page. It came back with Photos off and no pending chip. No `Forbidden origin` and no `Forbidden token` appeared.

Page difference reported by the owner: the write detail and recovery pages show mailbox folders and accounts as raw `imap://<account-UUID>/<percent-encoded folder>` URLs. The owner wants the account NAME shown (Business / Personal, the account's address, or both) and the UUID kept internal. Filed as GitHub issue #427 (elfensky/macos-apps-mcp, labelled bug). Per "bugs before features", it becomes an inserted phase ahead of the next feature phase; it is not patched here.

During the sitting the owner also switched Safari off and back on (two more dashboard toggles and restarts, see the audit records below). Safari ended on.

## Task 3: Photos gone, back on through the dashboard, proven

### `off` (exit 0, 2026-10-22 22:40 local)

```
PASS: version 0.15.0
PASS: 9 adapters (want 9)
PASS: photos adapter off
PASS: adapters_off ['photos']
PASS: no adapters_pending (None)
PASS: photos tools listed: []
PASS: pid 8281 != baseline 84285
PASS: audit: dashboard toggle photos off
PASS: audit: dashboard restart
```

The shim `doctor` showed dashboard `http://127.0.0.1:47632` and `adapters_pending` null. The dashboard audit records (caller `dashboard`, newest first):

| ts (local) | op | args |
| --- | --- | --- |
| 2026-10-22T22:38:24 | restart | {} |
| 2026-10-22T22:38:22 | toggle | {adapter: safari, on: true} |
| 2026-10-22T22:28:13 | restart | {} |
| 2026-10-22T22:28:09 | toggle | {adapter: safari, on: false} |
| 2026-10-22T22:26:25 | restart | {} |
| 2026-10-22T22:26:23 | toggle | {adapter: photos, on: false} |

The key grep on the captured output printed 0.

### `restore` (exit 0, ending 2026-10-22 22:40 local)

```
PASS: GET /adapters yields a token
PASS: toggle photos on -> 303
PASS: restart -> 200
PASS: version 0.15.0
PASS: 10 adapters (want 10)
PASS: photos adapter on
PASS: adapters_off []
PASS: no adapters_pending (None)
PASS: photos tools listed: ['export_photo', 'photo_albums', 'photo_info', 'photos']
PASS: pid 13771 != 8281
PASS: adapters_off file empty
```

The script used the page-key cookie, an `Origin` header and the form token for `POST /adapters` and `POST /restart`. The restart answer contained `Restarting the daemon`. The relaunch finished inside the 40 s bound. The key grep printed 0.

### `on` (exit 0, 2026-10-22 22:40 local)

```
PASS: version 0.15.0
PASS: 10 adapters (want 10)
PASS: photos adapter on
PASS: adapters_off []
PASS: no adapters_pending (None)
PASS: photos tools listed: ['export_photo', 'photo_albums', 'photo_info', 'photos']
PASS: pid 13771 != 8281
PASS: adapters_off file empty
```

The key grep printed 0. The `adapters_off` file is 0 bytes.

### Daemon pids

| Point | pid |
| --- | --- |
| Baseline (before the owner's sitting) | 84285 |
| After the Photos-off restart (`off`) | 8281 |
| After the dashboard restore restart (`restore`, `on`) | 13771 |

(The owner's two Safari restarts at 22:28 and 22:38 happened between the baseline and the `off` run; 8281 is the pid `off` observed.)

### Final end state

One read-only shim `doctor(request=False)`: version 0.15.0, 10 adapters, `adapters_off` [], `adapters_pending` null, four Photos tools listed. `launchctl print` shows pid 13771. `.worktrees/p05-proof.json` was removed; the script was kept.

## Device evidence

Confirmed on device:
- D-16: launchd relaunches the daemon after the dashboard's `POST /restart`, both after the owner's switch-off and after the scripted restore. New pids each time. The daemon came back within the bound without a manual kickstart.
- RESEARCH C1/A1: the `Origin` header is accepted by the owner's everyday browser under `Referrer-Policy: same-origin`. No `Forbidden origin` for the toggle or the restart. The Safari toggles went through the same path.
- D-15: the toggle and restart audit records exist with caller `dashboard`.
- D-19: the foreign Host, missing-token, missing-Origin and missing-cookie probes all refuse as designed (baseline).

Unverified:
- The browser was not named. Safari, Firefox and Chrome are therefore not confirmed by name; only "the owner's everyday browser" is.
- The "Copy result" button and the sketch-comparison notes were not reported by the owner beyond the account-UUID difference above.

## Deviations from Plan

None in execution. The owner switched Safari off and on during the sitting, which added two toggles and two restarts to the audit log; the end state is unaffected.

## Known Stubs

None. No file was created or changed in the repo.

## Threat Flags

None.

## Follow-ups

- Issue #427: show account names instead of raw `imap://<UUID>/...` URLs on the write detail and recovery pages (inserted phase ahead of the next feature phase).
- The two restarts dropped every MCP client once each. Run `/mcp` to reconnect.

## Self-Check: PASSED

- `off`, `restore` and `on` exited 0; every line above was printed by the script.
- Key grep on all three captured outputs printed 0.
- `git status --short` in the main checkout shows no tracked change; no commit made.
