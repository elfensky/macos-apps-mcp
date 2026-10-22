---
phase: "05"
scope: wave 1 (PRs #406, #407, #408)
reviewed: 2026-10-22
---

# Phase 05 — Wave 1 Post-Merge Review

Independent reviews of each merged wave-1 PR: an orchestrator read of every source diff, a
mutation-and-probe review of #407, and a running-server security probe of #408 (raw HTTP on an
ephemeral loopback port, scratch `HOME`). The phase-close code review keeps these ids.

## #406 — starlette declared, 0.15.0 (05-08)

No finding. Three files, +6/−3; the `uv.lock` diff is the four named lines.

## #407 — adapter deny-list (05-01)

| Id | Severity | Finding | Disposition |
|----|----------|---------|-------------|
| PM-01 | should-fix | An `adapters_off` file that exists but cannot be read read as empty: every adapter registered, `doctor` silent (fail open) | fixed by #410 (D-20: fail closed, `doctor` says so) |
| PM-02 | should-fix | A non-UTF-8 byte in the file raised `UnicodeDecodeError` at server import: daemon crash loop under launchd; `allow_send` file had the same gap | fixed by #410 (bytes replaced) |
| PM-03 | advisory | `doctor` gates its probes on the live config while tools register at import, so a file change without a restart can skip a live adapter's probe | accepted: `adapters_pending` and the restart note report the delta |
| PM-04 | advisory | No test checks `deployment.adapters_off` while an adapter is off at registration | open, test gap |
| PM-05 | advisory | The token-budget test does not cover the new keys in their worst case (6997 of 7000 with pending deltas and 10 unknown names); `adapters_unknown` has no length cap | open |
| PM-06 | advisory | D-17's daemon role is set by env var in `test_registry.py`, not argv; "meta tools stay when every adapter is off" is tested with `photos` only | accepted: the argv branch is shared with `allow_send` and tested there |
| PM-07 | advisory | `request_access_each` creates the `EKEventStore` even when calendar and reminders are both off (no request, no prompt) | accepted |
| PM-08 | advisory | A newline-separated file reads as one unknown name (nothing turned off; `doctor` lists it) | accepted: the file is a comma list (docs/DAEMON.md § 6) |

Mutation result: 14 of 15 mutants failed the suite; the survivor is PM-04. No test reads the
developer's real `adapters_off` file (audit hook on `open()`: 0 opens; 11 without the conftest patch).

## #408 — loopback transport, Guard, Usage page (05-02)

| Id | Severity | Finding | Disposition |
|----|----------|---------|-------------|
| PM-09 | should-fix | `Guard._read_body` read `http.disconnect` as the end of the body and replayed a cut-short form to the handler as complete | fixed by #409 |
| PM-10 | advisory | A duplicate `Origin` header resolves to the last value | accepted: browsers send one Origin; a non-browser local client is D-19's concern |
| PM-11 | advisory | uvicorn's own 400 responses (malformed request line, duplicate Host) carry none of the five security headers | accepted: constant text, never reaches the Guard |
| PM-12 | should-fix | Loopback TCP is reachable by other macOS accounts and sandboxed apps; from 05-03/05-04 pages carry the token and the audit trail | D-19: page key, plan 05-09 |

Held under probe: no request reached MCP over TCP (121 TCP scopes, all to the dashboard); the
Host, Origin, token and 8 KiB checks; static traversal; escaping of hostile tool names; all five
headers on Guard responses; MCP over the UDS with the port taken. Mutations of the dispatcher,
Origin, body-cap and Host checks each failed the suite.

Not covered: real-browser headers (Safari, Firefox; RESEARCH A1, A2) — 05-07's device proof.

## #412 — Adapters page, toggle, Discard, restart (05-03, wave 2)

| Id | Severity | Finding | Disposition |
|----|----------|---------|-------------|
| PM-13 | should-fix | The sidebar badge divided by `registered \| configured`, so an adapter OFF at start and in the file read `9/9` | fixed by #413 |
| PM-14 | advisory | The D-20 lock was checked outside the write lock; a file that turned unreadable in between was replaced by a guess | fixed by #413 (re-read under the lock, 409) |
| PM-15 | advisory | A second Restart while one was armed logged a second restart for one exit | fixed by #413 |
| PM-16 | advisory | `force_exit` skips the lifespan shutdown, so every restart writes a `CancelledError` traceback to the daemon log | accepted: log noise only |
| PM-17 | advisory | A TCC row with a `status` (`limited`, `unknown`) showed the red `denied` chip | fixed by #413 (no chip) |
| PM-18 | advisory | The row counted tool records, not registered tools (an OFF adapter showed its full count) | fixed by #413 |
| PM-19 | advisory (test gap) | No test pins the restart hook after the body, the write lock, or write-before-log | write-before-log tested by #413; the other two accepted (concurrency, ASGI ordering) |
| PM-20 | open item | This Mac's user TCC database reads as absent from the sessions' shells, so grant chips and the AppleEvents target ids in `grants.py` are not confirmed against live rows | 05-05 Health and 05-07 device proof confirm the target ids |

Held under probe: every refusal (method, token, Origin, bad action or value, lock states) left the
file and the audit log unchanged; 10 concurrent toggles kept all 10 names with no temp file; known
names kept, unknown dropped (D-01); a real restart exits 0 in 0.3 s idle and 3.06 s with the native
worker blocked; a cut-short restart body logs nothing; no test arms a real timer or exits.

## T-05-44 — the page-key cookie reaches every 127.0.0.1 port (05-09 planning)

Raised by the 05-09 planner and widened at review: an app that listens on loopback and opens a URL
in the browser (sandboxed apps included) can obtain the key, visibly. Accepted and documented with
the key rotation (owner, 2026-10-22; D-19).
