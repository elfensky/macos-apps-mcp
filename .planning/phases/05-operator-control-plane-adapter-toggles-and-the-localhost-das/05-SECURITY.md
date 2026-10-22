---
phase: "05"
slug: "operator-control-plane-adapter-toggles-and-the-localhost-das"
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on severity (the blocking gate)
threats_open: 0
asvs_level: 1
block_on: high
register_authored_at_plan_time: true
threats_total: 58
threats_closed: 58
created: "2026-10-22"
audited_at: "4ceb433"
---

# Phase 05 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
> Requirements: PLAT-01, PLAT-02.
> Audited source: `git diff d053ec1 4ceb433 -- . ':!.planning'` (43 files; plan PRs #406, #407,
> #408, #412, #415, #418, #421, #424, #425; review-fix PRs #409, #410, #413, #416, #419, #422,
> and #431 from the phase-close review).
> ASVS Level 1, block on high. Evidence is a plan SUMMARY (each plan landed by PR with the full
> suite green: at the code head f84897d, 2460 passed; read-only 2445 passed, 15 skipped; send
> 2454 passed, 6 skipped), the per-PR independent probe review in `05-POSTMERGE-REVIEW.md`
> (PM-01..PM-41, with the fix PR for every should-fix), or the device proof in 05-07-SUMMARY.md.

---

## Plain-language summary

**Technical.** All 58 register rows are closed: 51 by a mitigation that landed with its
plan and was probed by an independent review after the merge, 7 by a documented accepted
risk (all `low` or `medium`, below the `high` block threshold; the one `medium`, T-05-44, is
the owner's decision of 2026-10-22). Every `high` row is mitigated. The six should-fix findings
of the post-merge reviews (PM-01, PM-02, PM-09, PM-13, PM-25, PM-26, PM-34..36) are fixed on
develop. `threats_open: 0`.

**eli14.** The daemon got a front door for the operator: a small website that only this Mac
can reach. The risks are the usual ones for a door: someone else on the Mac opening it, a web
page tricking the browser into pushing its buttons, a form half-sent, and what the pages show.
The door has a key (the page key), a second check on every button press (Origin and a form
token), it shows only escaped text, and a request that breaks off does nothing. The deny-list
file fails closed. Today the blast radius is one Mac and one account; a sandboxed app on the same
account could still obtain the key by opening a page in the browser (T-05-44, accepted, visible
when it happens, and the key can be rotated).

## Trust Boundaries

| Boundary | Trusted side | Untrusted side | Control |
|----------|--------------|----------------|---------|
| Loopback TCP 127.0.0.1:47632 | the daemon | every process on this Mac, every website in the operator's browser | Host allow-list, page-key cookie, Origin or Sec-Fetch-Site + form token on non-GET, 8 KiB body cap, security headers (D-08, D-19) |
| Unix socket (MCP) | the daemon | the shim | 0700 dir / 0600 socket; MCP is never routed from TCP (D-06) |
| State files (`adapters_off`, `allow_send`, `dashboard_key`) | the daemon | other local processes, operator mistakes | home-pinned, 0600/0700, non-blocking regular-file reads, fail closed (D-20, #416) |
| Audit log and backups | the daemon | content written by strangers (mail subjects, args) | escape-by-default rendering, receipt ids validated before any path, read-only recovery (D-09, D-13) |
| Release artefacts | the owner | GitHub, PyPI, launchd | owner-approved one-way cut, notarized build from the tag, old bundle kept (D-18) |

## Threat Register

### Plan-time register (05-01 … 05-09)

| Threat ID | Category | Component | Severity | Disposition | Mitigation / Evidence | Status |
|-----------|----------|-----------|----------|-------------|-----------------------|--------|
| T-05-01 | Elevation of privilege | `server._tool` (an OFF adapter's tool reachable) | high | mitigate | Task 1: the gate is ANDed in every tier at registration; the subprocess test proves the listed tools equal the registered records and no photos tool is listed — landed by 05-01 (#407); see 05-01-SUMMARY.md | closed |
| T-05-02 | Tampering | `deploy._ADAPTERS_OFF_FILE` path (a path under XDG_STATE_HOME would let the daemon and the operator read two files, failing open) | high | mitigate | Task 1: home-pinned constant beside `_ALLOW_SEND_FILE`; tests patch the constant, never HOME in-process; the file is read only in the daemon role — landed by 05-01 (#407); see 05-01-SUMMARY.md | closed |
| T-05-03 | Information disclosure | `doctor` Automation probe / EventKit request for an OFF app | medium | mitigate | Task 3: OFF surfaces return `adapter_off` before any `run_osascript`, `_process_line` or EventKit call; tests record the calls — landed by 05-01 (#407); see 05-01-SUMMARY.md | closed |
| T-05-04 | Elevation of privilege | `registry.outbound_status` / send tier (allow_send=mail re-enables Mail's send tools while Mail is OFF) | high | mitigate | Task 1 ANDs the adapter gate into the send tier; Task 2 ANDs it into `outbound_status()["configured"]`; subprocess and unit tests cover allow_send=mail with mail OFF — landed by 05-01 (#407); see 05-01-SUMMARY.md | closed |
| T-05-05 | Repudiation | operator cannot tell configured from running state | low | mitigate | Task 2: `adapters_pending` plus the restart directive, the `outbound_pending` shape — landed by 05-01 (#407); see 05-01-SUMMARY.md | closed |
| T-05-SC | Tampering | npm/pip/cargo installs | high | mitigate | no package is added, upgraded or locked in this plan: `git diff --name-only origin/develop...HEAD` lists neither `pyproject.toml` nor `uv.lock` (Task 4 full checks; the PR file list is the `files_modified` list; 05-08 owns both files) — landed by 05-01 (#407); see 05-01-SUMMARY.md | closed |
| T-05-06 | Information disclosure | Guard Host check (DNS rebinding reads the pages) | high | mitigate | Task 1 strict Host allow-list `{127.0.0.1:<port>, localhost:<port>}` on every request; Task 3 tests 400 on GET, static and POST — landed by 05-02 (#408); see 05-02-SUMMARY.md | closed |
| T-05-07 | Tampering | Guard POST checks (CSRF from a website) | high | mitigate | Task 1 Origin allow-list, `Origin: null` refused, `Sec-Fetch-Site: same-origin` only when Origin is absent, constant-time token, 8 KiB cap; `Referrer-Policy: same-origin` so real posts carry an Origin (C1); Task 3 tests every refusal — landed by 05-02 (#408); see 05-02-SUMMARY.md | closed |
| T-05-08 | Tampering | framing (click-jacking a valid form) | high | mitigate | CSP `frame-ancestors 'none'` and `X-Frame-Options: DENY` on every response; Task 3 asserts the headers on 200/400/403/404 — landed by 05-02 (#408); see 05-02-SUMMARY.md | closed |
| T-05-09 | Elevation of privilege | stored XSS through tool names and record strings | high | mitigate | Task 1 `esc`/`h`/`Safe` escape every value; no inline style or script; CSP `default-src 'self'` as backstop; Task 3 renders `<script>` and an attribute breakout escaped — landed by 05-02 (#408); see 05-02-SUMMARY.md | closed |
| T-05-10 | Elevation of privilege | MCP reachable over TCP | high | mitigate | Task 1 dispatcher routes only lifespan and `server[1] is None` to MCP, everything else to the dashboard or 404 (C4), `proxy_headers=False`; Task 3 fake-scope tests and the guarded `POST /mcp` → 404; Task 1 real-bind test: unsigned `POST /mcp` → 403 from the Guard, `GET /mcp` → 404, no `jsonrpc` body — landed by 05-02 (#408); see 05-02-SUMMARY.md | closed |
| T-05-11 | Information disclosure | a non-loopback bind | high | mitigate | Task 1 `assert_loopback` in `bind_dashboard`, constant host; Task 3 refuses `0.0.0.0`, LAN, `localhost`, `::` — landed by 05-02 (#408); see 05-02-SUMMARY.md | closed |
| T-05-12 | Information disclosure | static route path traversal | high | mitigate | Task 2 two-entry dict, no path from the URL; Task 3 traversal tests — landed by 05-02 (#408); see 05-02-SUMMARY.md | closed |
| T-05-13 | Denial of service | a taken port stops the daemon | medium | mitigate | Task 1 catches `OSError` from the TCP bind only, logs it, MCP keeps serving; Task 3 test — landed by 05-02 (#408); see 05-02-SUMMARY.md | closed |
| T-05-SC | Tampering | npm/pip/cargo installs | high | mitigate | no package is added or locked in this plan: Task 4 checks that `git diff --name-only origin/develop...HEAD` lists none of `pyproject.toml`, `uv.lock`, `packaging/Info.plist`; the starlette declaration and its legitimacy evidence are 05-08's (T-05-SC there) — landed by 05-02 (#408); see 05-02-SUMMARY.md | closed |
| T-05-14 | Tampering | POST /adapters, POST /restart (CSRF) | high | mitigate | both routes sit behind 05-02's Guard (Host, Origin, token); Task 2 tests 403 without a token and 405 for GET /restart; Task 1 tests that GET is side-effect free — landed by 05-03 (#412); see 05-03-SUMMARY.md | closed |
| T-05-15 | Elevation of privilege | `adapters_off` written with an unknown or crafted name | high | mitigate | Task 1: `adapter` must be in the registry's names and `on` in {0,1}, else 400 with no write; the file is rewritten from known names only — landed by 05-03 (#412); see 05-03-SUMMARY.md | closed |
| T-05-16 | Tampering | a truncated `adapters_off` after a kill mid-write (reads as all on) | medium | mitigate | Task 1: temp file in the same directory, fsync, `os.replace`; failure test — landed by 05-03 (#412); see 05-03-SUMMARY.md | closed |
| T-05-17 | Denial of service | repeated restarts | medium | mitigate | Task 2: token + Origin required; one watchdog per process (`_restart_armed`); launchd `ThrottleInterval` 10 s bounds the relaunch rate; the restart bar names the consequence — landed by 05-03 (#412); see 05-03-SUMMARY.md | closed |
| T-05-18 | Elevation of privilege | the Outbound gate changed from the page | high | mitigate | Task 3: the Outbound group holds no form and no input; no route writes `allow_send`; test asserts the group markup — landed by 05-03 (#412); see 05-03-SUMMARY.md | closed |
| T-05-19 | Repudiation | a dashboard change with no trace | medium | mitigate | Tasks 1-2: one audit record per toggle, Discard and restart with caller `dashboard`, outside the middleware and the usage tally — landed by 05-03 (#412); see 05-03-SUMMARY.md | closed |
| T-05-20 | Information disclosure | grant chips leak TCC data to another site | low | accept | the page is readable only through the Host check (DNS rebinding refused, 05-02); the data is the operator's own grants — landed by 05-03 (#412); see 05-03-SUMMARY.md | accepted (AR-05-01) |
| T-05-SC | Tampering | npm/pip/cargo installs | high | mitigate | no package is added or locked: `pyproject.toml` and `uv.lock` are not in this plan's `files_modified`, and `git diff --name-only origin/develop` at landing lists neither — landed by 05-03 (#412); see 05-03-SUMMARY.md | closed |
| T-05-21 | Elevation of privilege | stored XSS through summaries, args, tool names, folders, target ids, raw JSON | high | mitigate | Task 1: every value through `esc`/`h`; the raw JSON tokens escaped one by one; `safe_href` scheme allow-list; CSP backstop from 05-02; tests render `<script>`, an attribute breakout and `javascript:` — landed by 05-04 (#418); see 05-04-SUMMARY.md | closed |
| T-05-22 | Information disclosure | receipt-driven file listing (path traversal) | high | mitigate | Task 2: `RECEIPT_RE` checked before any filesystem call; real directory, not a symlink, parent is the backup root; names and sizes only; test with `../../etc` — landed by 05-04 (#418); see 05-04-SUMMARY.md | closed |
| T-05-23 | Tampering | a recovery write from the page | medium | mitigate | Task 2: no route writes or acts on backups or mail; the undo is a copied prompt for Claude's gated `mail_undo`; tests show `_backup_dir`, `purge_backup` and `backup_usage` are never called — landed by 05-04 (#418); see 05-04-SUMMARY.md | closed |
| T-05-24 | Information disclosure | message content on the page | medium | mitigate | rows show Pointer summaries already in the audit log and Message-IDs; no `.eml` content or subject is read; no file endpoint — landed by 05-04 (#418); see 05-04-SUMMARY.md | closed |
| T-05-25 | Repudiation | a preview mistaken for a real write | medium | mitigate | Task 1: `dry_run` resolved from the tool default for legacy records; dimmed row, `preview` chip and banner; tests on a legacy `trash_mail` record — landed by 05-04 (#418); see 05-04-SUMMARY.md | closed |
| T-05-26 | Denial of service | a large log slows every page | low | mitigate | Task 3: a 3000-record render bound in the tests; two plain file reads per request (about 40 ms measured) — landed by 05-04 (#418); see 05-04-SUMMARY.md | closed |
| T-05-SC | Tampering | npm/pip/cargo installs | high | mitigate | no package is added or locked: `pyproject.toml` and `uv.lock` are not in this plan's `files_modified`, and `git diff --name-only origin/develop` at landing lists neither — landed by 05-04 (#418); see 05-04-SUMMARY.md | closed |
| T-05-27 | Information disclosure | `/backups/<receipt>` path traversal and symlink escape | high | mitigate | Task 3: `RECEIPT_RE` before any filesystem call; `receipt_dir` requires a real directory whose parent is the backup root; names and sizes only, no file contents; tests with `..%2f`, a non-receipt name, a symlink and a bad op — landed by 05-05 (#421); see 05-05-SUMMARY.md | closed |
| T-05-28 | Denial of service | Health reloads pile threads behind a busy worker | medium | mitigate | Task 1: non-blocking single-flight lock, `abandon_on_cancel=True` inside a 10 s bound; at most one diagnose thread; test with a blocked fake — landed by 05-05 (#421); see 05-05-SUMMARY.md | closed |
| T-05-29 | Information disclosure | a TCC prompt or an Apple Event from a page | medium | mitigate | Task 1: `diagnose(request=False)` only; the fake asserts the argument; grep shows no `request=True` — landed by 05-05 (#421); see 05-05-SUMMARY.md | closed |
| T-05-30 | Tampering | a page deletes or prunes a backup | medium | mitigate | Task 3: no route writes; `purge_backup` and `_backup_dir` never called (tests); an absent root stays absent — landed by 05-05 (#421); see 05-05-SUMMARY.md | closed |
| T-05-31 | Information disclosure / Elevation of privilege | another local macOS user reads or toggles over loopback (RESEARCH A5) | low | mitigate | D-19: 05-09's page key refuses every request without the key cookie (05-09 T-05-40); Task 4 documents the key, the CLI link, the key rotation and the cross-port cookie residual in docs/DAEMON.md — landed by 05-05 (#421); see 05-05-SUMMARY.md | closed |
| T-05-SC | Tampering | npm/pip/cargo installs | high | mitigate | no package is added or locked: `pyproject.toml` and `uv.lock` are not in this plan's `files_modified`, and `git diff --name-only origin/develop` at landing lists neither — landed by 05-05 (#421); see 05-05-SUMMARY.md | closed |
| T-05-32 | Repudiation | one-way push of `main`, tag, release or PyPI without consent | high | mitigate | Task 2 blocking-human decision (D-18); Task 3 precondition on its answer; PyPI only on "cut-and-pypi" — landed by 05-06 (#424, #425); see 05-06-SUMMARY.md | closed |
| T-05-33 | Tampering | release bundle built from a dirty or wrong tree | high | mitigate | Task 3 builds only in `.worktrees/build-v0.15.0` detached at the tag; the probe requires the build token to resolve to v0.15.0's commit, no `-dirty` — landed by 05-06 (#424, #425); see 05-06-SUMMARY.md | closed |
| T-05-34 | Spoofing | unsigned or un-notarized bundle shipped | medium | mitigate | `stapler validate` and `spctl` must report Notarized Developer ID; zip made after stapling — landed by 05-06 (#424, #425); see 05-06-SUMMARY.md | closed |
| T-05-35 | Information disclosure | notary credentials | medium | mitigate | keychain profile `notary` only; no credential printed, written or passed on the command line — landed by 05-06 (#424, #425); see 05-06-SUMMARY.md | closed |
| T-05-36 | Denial of service | a failed install leaves the Mac without a working daemon | medium | mitigate | the 0.14.3 bundle moves to `app-backup` first; a failed probe restores it and kickstarts — landed by 05-06 (#424, #425); see 05-06-SUMMARY.md | closed |
| T-05-SC | Tampering | package installs | low | accept | no package is added or upgraded in this plan; Task 1 changes `CHANGELOG.md` only (checked) — landed by 05-06 (#424, #425); see 05-06-SUMMARY.md | accepted (AR-05-02) |
| T-05-37 | Denial of service | the proof leaves Photos off or the daemon down | medium | mitigate | Task 3 always runs `restore` (with the D-05 file + kickstart fallback) and the final `on` check must pass — landed by 05-07 (device proof, no PR); see 05-07-SUMMARY.md | closed |
| T-05-38 | Tampering | a baseline probe restarts the daemon by accident | low | mitigate | Task 1 never sends the token in `baseline`; only `restore` uses it, after the owner's step — landed by 05-07 (device proof, no PR); see 05-07-SUMMARY.md | closed |
| T-05-39 | Elevation of privilege | a local process drives the dashboard with the page token | low | accept | per D-19 a process needs the page key, which only the operator's account can read (05-09: 0600 file, 0700 folder); a process of that account is trusted; the proof script is one and never prints the key (prohibition; Task 3 greps the SUMMARY) — landed by 05-07 (device proof, no PR); see 05-07-SUMMARY.md | accepted (AR-05-03) |
| T-05-SC | Tampering | package installs | low | accept | no package is added, installed or locked; no tracked file changes — landed by 05-07 (device proof, no PR); see 05-07-SUMMARY.md | accepted (AR-05-04) |
| T-05-SC | Tampering | npm/pip/cargo installs (starlette flagged [SUS] for recency) | high | mitigate | Task 1: starlette 1.6.0 is already locked and installed via mcp/fastmcp; `uv lock --offline` adds four lines in three hunks and leaves the starlette entry and `revision` unchanged; `uv sync --locked --offline` passes; nothing is downloaded; the evidence is in the SUMMARY and the PR body — landed by 05-08 (#406); see 05-08-SUMMARY.md | closed |
| T-05-40 | Information disclosure / Elevation of privilege | another account or a sandboxed app reads the audit trail or posts with the page's form token (PM-12) | high | mitigate | Tasks 1-2: every request but `/key` needs the cookie equal to the key, checked in the Guard after Host and before routing; `/static` included; the form token stays for writes; tests cover every route, HEAD, and the token-without-cookie POST — landed by 05-09 (#415); see 05-09-SUMMARY.md | closed |
| T-05-41 | Information disclosure | the key file read by another account | high | mitigate | Tasks 1-2: mkstemp file 0600, `os.replace`, folder 0700 set again at every daemon start; tests assert both modes, including a folder that existed as 0755 — landed by 05-09 (#415); see 05-09-SUMMARY.md | closed |
| T-05-42 | Information disclosure | the key in a log, `doctor`, the audit trail, the usage tally or a page | medium | mitigate | Tasks 1-3: uvicorn `access_log=False`; refusals are constant text; the key lives in the Guard only, never on `app.state`; the `doctor` note is constant and never reads the file; tests assert the key is absent from captured output, the `doctor` JSON, `audit.jsonl`, `usage.jsonl` and page bodies — landed by 05-09 (#415); see 05-09-SUMMARY.md | closed |
| T-05-43 | Information disclosure | the key in the URL: the address bar, browser history, the process list | medium | mitigate | Tasks 1 and 3: `/key` answers 303 to `/`, so the address bar ends on `/`; `Referrer-Policy: same-origin` keeps the URL off other sites; the CLI opens it with `webbrowser.MacOSXOSAScript("default").open` (stdin to `osascript`; `BROWSER` cannot redirect it), never as a process argument, tested by `subprocess` refusals. Residual, accepted: the history entry stays in the operator's own browser profile; the remedy is to remove the key file and restart the daemon — landed by 05-09 (#415); see 05-09-SUMMARY.md | closed |
| T-05-44 | Information disclosure | the cookie sent to another program's 127.0.0.1 port (RFC 6265 section 8.5) | medium | accept | `SameSite=Strict` keeps the cookie off cross-site requests, so the attack needs the operator's browser to open a page served by the other program's own loopback listener; plain-http loopback has no port-bound cookie; HttpOnly keeps it from scripts; 05-05 documents the risk and the rotation; accepted by the owner, 2026-10-22 — landed by 05-09 (#415); see 05-09-SUMMARY.md | accepted (AR-05-05) |
| T-05-45 | Spoofing | cookie fixation or tossing from another 127.0.0.1 port | low | mitigate | Task 2: the cookie value is the key itself, never a server-issued id that a login promotes, so a planted value grants nothing; any matching cookie of the name passes, so a tossed duplicate cannot shadow the real one (test); an overwrite only refuses the operator until the CLI link sets it again — landed by 05-09 (#415); see 05-09-SUMMARY.md | closed |
| T-05-46 | Tampering | script injection through a refusal | medium | mitigate | Task 2: refusals are `text/plain` constants with `nosniff` and the CSP; no request value is echoed; test with `<script>` in the path and the query — landed by 05-09 (#415); see 05-09-SUMMARY.md | closed |
| T-05-47 | Elevation of privilege / Denial of service | an empty, garbled or unreadable key file | high | mitigate | Task 2: only a urlsafe token of 32 or more characters is a key, so an empty key never matches an empty cookie; an existing file is never rewritten; every request answers 503 with the remedy; MCP keeps serving; tests for empty, short, bad characters, mode 000, a directory and a failed write — landed by 05-09 (#415); see 05-09-SUMMARY.md | closed |
| T-05-48 | Spoofing | guessing the key through `/key` | low | accept | 256 random bits (`secrets.token_urlsafe(32)`), constant-time comparison; no rate limit at ASVS L1 — landed by 05-09 (#415); see 05-09-SUMMARY.md | accepted (AR-05-06) |
| T-05-49 | Information disclosure | the model's shell, running as the same account, reads the key file or runs the CLI | low | accept | the boundary is the account (05-07 T-05-39): the key stays out of `doctor`, logs, pages and SUMMARYs so it never reaches a transcript by accident; the CLI is the operator's — landed by 05-09 (#415); see 05-09-SUMMARY.md | accepted (AR-05-07) |
| T-05-SC | Tampering | npm/pip/cargo installs | high | mitigate | no package is added or locked: `pyproject.toml` and `uv.lock` are not in `files_modified`; `webbrowser`, `hmac`, `secrets` and `re` are standard library; Task 4 checks the PR's file list — landed by 05-09 (#415); see 05-09-SUMMARY.md | closed |

### Review-time register (per-PR independent probe reviews; ids as in 05-POSTMERGE-REVIEW.md)

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
| PM-09 | should-fix | `Guard._read_body` read `http.disconnect` as the end of the body and replayed a cut-short form to the handler as complete | fixed by #409 |
| PM-10 | advisory | A duplicate `Origin` header resolves to the last value | accepted: browsers send one Origin; a non-browser local client is D-19's concern |
| PM-11 | advisory | uvicorn's own 400 responses (malformed request line, duplicate Host) carry none of the five security headers | accepted: constant text, never reaches the Guard |
| PM-12 | should-fix | Loopback TCP is reachable by other macOS accounts and sandboxed apps; from 05-03/05-04 pages carry the token and the audit trail | D-19: page key, plan 05-09 |
| PM-13 | should-fix | The sidebar badge divided by `registered \| configured`, so an adapter OFF at start and in the file read `9/9` | fixed by #413 |
| PM-14 | advisory | The D-20 lock was checked outside the write lock; a file that turned unreadable in between was replaced by a guess | fixed by #413 (re-read under the lock, 409) |
| PM-15 | advisory | A second Restart while one was armed logged a second restart for one exit | fixed by #413 |
| PM-16 | advisory | `force_exit` skips the lifespan shutdown, so every restart writes a `CancelledError` traceback to the daemon log | accepted: log noise only |
| PM-17 | advisory | A TCC row with a `status` (`limited`, `unknown`) showed the red `denied` chip | fixed by #413 (no chip) |
| PM-18 | advisory | The row counted tool records, not registered tools (an OFF adapter showed its full count) | fixed by #413 |
| PM-19 | advisory (test gap) | No test pins the restart hook after the body, the write lock, or write-before-log | write-before-log tested by #413; the other two accepted (concurrency, ASGI ordering) |
| PM-20 | open item | This Mac's user TCC database reads as absent from the sessions' shells, so grant chips and the AppleEvents target ids in `grants.py` are not confirmed against live rows | 05-05 Health and 05-07 device proof confirm the target ids |
| PM-21 | advisory | A FIFO at the key path blocked `read_bytes()` in `serve()` after the socket bind, so MCP never served (a `/dev/zero` symlink would grow memory); `adapters_off` and `allow_send` were read the same way | fixed by #416 (`_read_small`: non-blocking, regular file only, 4 KiB) |
| PM-22 | advisory | A symlink at the key path was followed: accepted, `chmod` changed its target, a dangling one was replaced with a new key | fixed by #416 (`O_NOFOLLOW` on the key file; config files still follow) |
| PM-23 | advisory | Key creation is check-then-replace, not exclusive (8 racing threads disagree) | accepted: unreachable after the single-instance socket bind and the exclusive TCP bind |
| PM-24 | advisory (test gap) | No test pinned the 0644 → 0600 tightening; `access_log=False` is invisible behind `log_level="warning"` | tightening tested by #416; the log flag accepted as a second guard |
| PM-25 | should-fix | `RECEIPT_RE` took exactly 3 counter digits; `mail_recover` pads to a minimum of 3, so from the 1001st batch of one run recovery read "no file" | fixed by #419 (`\d{3,}`) |
| PM-26 | should-fix | One corrupt record gave a 500 on every page via the sidebar counts (out-of-range `ts`, non-list `targets`, a lone surrogate) | fixed by #419 |
| PM-27 | advisory | `audit_read` returned non-dict JSON lines, so `find_receipt` and `mail_undo` crashed on one (older than the dashboard); an undone target without `folder` raised `KeyError` | fixed by #419 |
| PM-28 | advisory | A corrupt middleware line naming a receipt hides its whole batch | accepted: corruption only |
| PM-29 | advisory | The adjacency fallback can mislink after a timed-out batch | accepted: the plan names the limit |
| PM-30 | advisory | Page rendering reads the log on the event loop shared with MCP (+0.3–0.7 s MCP latency during page loads on a 25k-record log); no pagination | accepted: the real log parses in about 40 ms (D-12) |
| PM-31 | advisory | `shortcuts://` was an allowed deeplink, and following `run-shortcut` runs it; http(s) links come from model-chosen Safari URLs | `shortcuts` removed by #419; http(s) accepted |
| PM-32 | advisory (test gap) | 9 of 20 mutants survived (the reflected search value, the word diff's unchanged run, folder, `backup_dir`, outcome, error banner, `RECEIPT_RE` before the disk, symlinked files) | tests added by #419; two mutants re-applied and caught |
| PM-33 | advisory | A GET can create the state folder through `audit.state_dir`'s `mkdir` | accepted: older than the dashboard; the folder exists on a deployed Mac |
| PM-34 | should-fix (test gap) | No test held the in-thread single-flight refusal; with it removed a 50-request burst started 6 hung `doctor` calls | test added by #422; the mutant fails |
| PM-35 | should-fix | An absent user TCC database (macOS 27, #261) showed a permanent "did not answer" warning | fixed by #422 (a note). The review's proposal to count it as a complete read was rejected on device evidence: the installed daemon's `doctor` (FDA) sees only FDA rows, so it would make every Automation and EventKit row claim "not asked" |
| PM-36 | should-fix | `docs/DAEMON.md` § 7: removing an unreadable key file was said to be enough; the daemon must also restart | fixed by #422 |
| PM-37 | advisory | `doctor`'s daemon-role report passed its 7000-char budget (7302 with long deny-list input) | fixed by #422 (unknown names capped, shorter notes, a daemon-role budget test); closes PM-05 |
| PM-38 | advisory | Backups says "no files" for a chmod-000 receipt folder and "rotated out" when the log is unreadable | accepted: corruption only |
| PM-39 | advisory | A symlinked backup root is followed (names and sizes only) | accepted: the daemon's own folder |
| PM-40 | advisory | `RECEIPT_RE` matched Arabic-Indic and fullwidth digits | fixed by #422 (`re.ASCII`) |
| PM-41 | advisory | `_last` is unused; a `doctor` run over 10 s never shows a report; `grant_report` runs twice per load | accepted |

## Unregistered Flags

None: every should-fix finding of the post-merge reviews maps to a fix PR or an owner decision
(D-19, D-20), and the owner's UAT finding is issue #427 (display, not a threat).

## Accepted Risks Log

| Id | Threat | Severity | Why accepted | Revisit when |
|----|--------|----------|--------------|--------------|
| AR-05-01 | T-05-20 (05-03): grant chips leak TCC data to another site | low | the page is readable only through the Host check (DNS rebinding refused, 05-02); the data is the operator's own grants | a later ASVS level, or a multi-user Mac |
| AR-05-02 | T-05-SC (05-06): package installs | low | no package is added or upgraded in this plan; Task 1 changes `CHANGELOG.md` only (checked) | a later ASVS level, or a multi-user Mac |
| AR-05-03 | T-05-39 (05-07): a local process drives the dashboard with the page token | low | per D-19 a process needs the page key, which only the operator's account can read (05-09: 0600 file, 0700 folder); a process of that account is trusted; the proof script is one and never prints the key (prohibition; Task 3 greps the SUMMARY) | a later ASVS level, or a multi-user Mac |
| AR-05-04 | T-05-SC (05-07): package installs | low | no package is added, installed or locked; no tracked file changes | a later ASVS level, or a multi-user Mac |
| AR-05-05 | T-05-44 (05-09): the cookie sent to another program's 127.0.0.1 port (RFC 6265 section 8.5) | medium | `SameSite=Strict` keeps the cookie off cross-site requests, so the attack needs the operator's browser to open a page served by the other program's own loopback listener; plain-http loopback has no port-bound cookie; HttpOnly keeps it from scripts; 05-05 documents the risk and the rotation; accepted by the owner, 2026-10-22 | a later ASVS level, or a multi-user Mac |
| AR-05-06 | T-05-48 (05-09): guessing the key through `/key` | low | 256 random bits (`secrets.token_urlsafe(32)`), constant-time comparison; no rate limit at ASVS L1 | a later ASVS level, or a multi-user Mac |
| AR-05-07 | T-05-49 (05-09): the model's shell, running as the same account, reads the key file or runs the CLI | low | the boundary is the account (05-07 T-05-39): the key stays out of `doctor`, logs, pages and SUMMARYs so it never reaches a transcript by accident; the CLI is the operator's | a later ASVS level, or a multi-user Mac |
| AR-05-08 | WR-02 (phase-close review): the `dashboard` CLI link and the restart page's auto-refresh send the key to whatever listens on 47632 if another process took the port while the daemon was down | medium | a variant of T-05-44 (owner, 2026-10-22): plain-http loopback has no port-bound credential; the key rotates by removing the file and restarting; visible when it happens (a foreign page opens) | with T-05-44: a later ASVS level, or a port-bound credential |

Review-time acceptances: PM-03, PM-06, PM-07, PM-08, PM-10, PM-11, PM-16, PM-19 (two of three),
PM-23, PM-28, PM-29, PM-30, PM-33, PM-38, PM-39, PM-41 (each `advisory`; the reason is in the
table above).

## Security Audit Trail

| Date | Scope | Method | Result |
|------|-------|--------|--------|
| 2026-10-22 | #406, #407 | orchestrator diff read; mutation review of #407 (15 mutants, audit hook on open()) | PM-01..PM-08 → #410 |
| 2026-10-22 | #408 | raw-HTTP probe of a real daemon.serve() (Host, Origin, token, body cap, traversal, MCP over TCP) | PM-09..PM-12 → #409, D-19 |
| 2026-10-22 | #412 | probe of the toggle, Discard and restart paths; 7 killing mutants | PM-13..PM-20 → #413 |
| 2026-10-22 | #415 | bypass, order, leak, key-file and cookie probes of a real daemon with the page key | PM-21..PM-24 → #416 |
| 2026-10-22 | #418 | XSS/traversal/robustness probes of the write list and recovery; 20 mutants | PM-25..PM-33 → #419 |
| 2026-10-22 | #421 | hung/raising doctor under 50 concurrent requests, prompt-path grep, backups edge cases | PM-34..PM-41 → #422 |
| 2026-10-22 | installed 0.15.0 | 05-07 device proof: refusals over HTTP, page-key refusal, Photos off/on through the dashboard | PASS (05-07-SUMMARY.md) |
| 2026-10-22 | dashboard CSS and templates | static UI audit (gsd-ui-auditor, no browser) | 05-UI-REVIEW.md 16/24; accessibility items → #428 |
| 2026-10-22 | the whole phase diff (41 files) | phase-close code review (gsd-code-reviewer) | 05-REVIEW.md: CR-01 (audit readers split a record on U+2028/U+2029/U+0085) and WR-04 fixed at the close; WR-02 accepted (AR-05-08); WR-01, WR-03, WR-05, WR-06, IN-02..05 → #430 |

## Sign-Off

- [x] Every plan carries a `<threat_model>`; the register above is their union plus the review-time findings
- [x] No `high` threat open; `threats_open: 0`
- [x] Accepted risks are logged with a reason and a revisit condition
- [x] The audit trail names the method and result per PR

**Approval:** closed 2026-10-22 at develop 4ceb433 (orchestrator; the owner decided D-19, D-20 and T-05-44).
