---
phase: 05-operator-control-plane-adapter-toggles-and-the-localhost-das
reviewed: 2026-10-22T20:56:14Z
depth: standard
files_reviewed: 41
files_reviewed_list:
  - CHANGELOG.md
  - README.md
  - docs/DAEMON.md
  - macos_apps_mcp/audit.py
  - macos_apps_mcp/cli.py
  - macos_apps_mcp/daemon.py
  - macos_apps_mcp/dashboard/__init__.py
  - macos_apps_mcp/dashboard/adapters.py
  - macos_apps_mcp/dashboard/backups.py
  - macos_apps_mcp/dashboard/dashboard.css
  - macos_apps_mcp/dashboard/dashboard.js
  - macos_apps_mcp/dashboard/grants.py
  - macos_apps_mcp/dashboard/guard.py
  - macos_apps_mcp/dashboard/health.py
  - macos_apps_mcp/dashboard/html.py
  - macos_apps_mcp/dashboard/recovery.py
  - macos_apps_mcp/dashboard/usage.py
  - macos_apps_mcp/dashboard/writes.py
  - macos_apps_mcp/deploy.py
  - macos_apps_mcp/doctor.py
  - macos_apps_mcp/eventkit.py
  - macos_apps_mcp/registry.py
  - macos_apps_mcp/server.py
  - macos_apps_mcp/tiers.py
  - packaging/Info.plist
  - pyproject.toml
  - scripts/build_app.sh
  - tests/_dashboard.py
  - tests/conftest.py
  - tests/test_adapters_off.py
  - tests/test_audit.py
  - tests/test_daemon.py
  - tests/test_daemon_dispatch.py
  - tests/test_dashboard_adapters.py
  - tests/test_dashboard_guard.py
  - tests/test_dashboard_key.py
  - tests/test_dashboard_system.py
  - tests/test_dashboard_writes.py
  - tests/test_doctor.py
  - tests/test_doctor_deploy.py
  - tests/test_packaging.py
  - tests/test_registry.py
  - uv.lock
findings:
  critical: 1
  warning: 6
  info: 5
  total: 12
status: issues_found
---

# Phase 05: Code Review Report

**Reviewed:** 2026-10-22T20:56:14Z
**Depth:** standard
**Files Reviewed:** 41
**Status:** issues_found

## Summary

Scope: the merged source diff `d053ec1..3cab97e` (code equals origin/develop at 3cab97e). The
per-PR reviews (PM-01..PM-41) covered the single modules well. This review looked at what they
could not see: record shapes across `audit.py`, `writes.py` and `adapters.py`; the page key, the
form token and the restart flow together; the test suite against the developer's real state.

The request layer (`guard.py`, the dispatcher in `daemon.py`) holds. No dashboard module imports
the FastMCP server. No page runs a native call on the event loop except through `run_in_threadpool`
or the single-flight `doctor` thread. The page-escape helper is used consistently; no `Safe(...)`
wraps request or audit data. I re-checked these earlier fixes and they hold: PM-21 and PM-22
(`_read_small`, `O_NOFOLLOW`), PM-25 and PM-40 (`RECEIPT_RE`), PM-35 (the absent-user-TCC note),
PM-13 and PM-14 (badge, lock re-read). PM-37 is only half fixed (WR-04).

One BLOCKER: the audit reader silently drops any record whose text contains U+2028, U+2029 or
U+0085, and that text is chosen by strangers (mail subjects, note titles). The dashboard's audit
list then omits the write. Six WARNINGs and five INFO items follow. I ran the suite (all green) with
an open/bind spy: no test opens the real `adapters_off`, the real key file or port 47632, but 38
tests open the real TCC databases (WR-01).

Not read in depth: `dashboard.css`, `uv.lock`, `packaging/Info.plist` (version line only), and the
bodies of the test files beyond the isolation fixtures and the cases cited below.

## Critical Issues

### CR-01: The audit reader splits on `str.splitlines()`, so a write whose text holds U+2028, U+2029 or U+0085 vanishes from the dashboard

**File:** `macos_apps_mcp/audit.py:141` (`read_all`, new in this phase); same defect at `:103` (`audit_read`) and `:187` (`usage_read`)
**Issue:** `audit_write` writes records with `json.dumps(..., ensure_ascii=False)`. That call escapes
every control character below U+0020 but not U+0085, U+2028 or U+2029. `str.splitlines()` splits on
all three. A record whose `after.summary` (or `before`, `args`, a mailbox name in a plan target)
contains one of them is cut into two fragments. Both fail `json.loads`, and the `except ValueError:
continue` skips them without a trace. I reproduced it on this checkout with a scratch state dir:
two records written, `audit.read_all()` returned one.

Failure scenario: a stranger sends a mail, or a shared note, whose subject contains U+2028. The
model creates a reminder or note from it. The middleware record for that write carries the subject
in `after.summary`. The `/` list, the sidebar counts and the detail page never show the write, and
no banner says a line was dropped (`_errors` only reports an unreadable file). The page's job is to
let the operator see what the model wrote ("Safe writes", audit review), and text the sender
controls decides whether the write is visible. A batch plan record (mailbox names in `targets[].folder`)
that is dropped removes the whole batch row, and `find_receipt` (also `audit_read`) then answers
"no recoverable-mail receipt", so `mail_undo` and the "To undo, ask Claude" prompt are gone for a
batch whose backups are on disk. PM-26 made corrupt lines skip safely; this is the case where a
valid line is misclassified as corrupt.
**Fix:** Split on `"\n"` only, in all three readers, and keep the skip for genuinely bad lines:
```python
for line in text.split("\n"):
    if not line:
        continue
    try:
        rec = json.loads(line)
    except ValueError:
        continue
```
Add a test in `tests/test_audit.py` that writes a record with `"\u2028"`, `"\u2029"` and `"\x85"` in
`after.summary` and asserts `read_all()`, `audit_read()` and `usage_read()` still return it.

## Warnings

### WR-01: 38 tests open the developer's real TCC databases

**File:** `tests/conftest.py:36-40`; unfaked callers in `tests/test_dashboard_adapters.py:28-35`, `tests/test_dashboard_key.py:42-48`, `tests/test_adapters_off.py`
**Issue:** `_isolated_state` patches `_ALLOW_SEND_FILE`, `_ADAPTERS_OFF_FILE` and `_DASHBOARD_KEY_FILE`,
but not `deploy._TCC_DB` or `deploy._TCC_SYSTEM_DB`. `GET /adapters` and `POST /restart` render
through `deploy.grant_report()`, and `doctor.diagnose()` calls it too. Only some tests fake it
(`test_dashboard_adapters.py:356`, `tests/test_dashboard_system.py:121`). I wrapped `_tcc_rows` and
`open()` with a spy and ran the full suite: the user and the system `TCC.db` were opened by 38 tests
(`test_adapters_off`, `test_dashboard_adapters`, `test_dashboard_key`, plus the older
`test_doctor` and `test_doctor_deploy`). No test opened the real `adapters_off`, the real key file or
bound 47632.

Failure scenario: on a Mac whose test runner has Full Disk Access, the Adapters page shows the
developer's real grant state. A test that asserts a row has no chip fails or passes depending on the
machine's grants (CI has no TCC database, so it never sees it). The read is read-only, but the
project rule is that no test reaches the developer's real state, and PM-04's audit hook covered only
the deny-list file.
**Fix:** Add two lines to the session fixture in `tests/conftest.py`:
```python
mp.setattr(deploy, "_TCC_DB", state_home / "absent-user" / "TCC.db")
mp.setattr(deploy, "_TCC_SYSTEM_DB", state_home / "absent-system" / "TCC.db")
```
Tests that need rows keep patching them locally (`test_doctor.py:480` already does).

### WR-02: The CLI sends the page key to whatever listens on port 47632, and the restart flow hands the cookie to a port squatter

**File:** `macos_apps_mcp/deploy.py:440-465` (`dashboard`), `macos_apps_mcp/daemon.py:322-326` (single bind attempt), `macos_apps_mcp/dashboard/adapters.py:240` (restart page refresh)
**Issue:** T-05-44 accepts that the cookie reaches every 127.0.0.1 port when an app opens a URL
visibly. Two paths need no such action by the operator:

1. `macos-apps-mcp dashboard` opens `http://127.0.0.1:47632/key?k=<key>` without checking who owns
   the port. The port is fixed and well known. If a hostile loopback listener (another account, a
   sandboxed app with network access, which is the PM-12 threat model) binds it before the daemon
   starts at login, the daemon logs `not bound: ...` and MCP keeps serving (D-07). The operator's
   own CLI then delivers the key in the URL to the squatter.
2. A dashboard Restart frees the port for the 0.3 to 10 s the daemon is down (launchd
   `ThrottleInterval` 10). The restart page meta-refreshes the browser to `/adapters` after 12 s. If a
   squatter took the port in that gap, the browser sends the `macos_apps_mcp_key` cookie to it
   automatically, with no link clicked and nothing visible. The relaunched daemon makes one bind
   attempt and gives up.

The squatter holds a key that works against the real dashboard as soon as the next daemon start
binds the port again. `doctor` says `not bound: ...`, but no page or CLI warns the operator.
**Fix:** (a) In `deploy.dashboard`, before printing the link, prove the listener is the daemon with a
keyed challenge that does not reveal the key: `GET /key?c=<nonce>` answers
`hmac(key, nonce)`; the CLI verifies it, and only then opens `/key?k=<key>`. (b) In `daemon.serve`,
retry the dashboard bind for a few seconds (the old process is gone, so the port frees at once)
before logging `not bound`. (c) Make the CLI print the `deployment.dashboard` state when the
challenge fails ("port 47632 is not the dashboard; check `doctor`").

### WR-03: Dashboard toggles and restarts are shown as "What the model asked for", with an invented `dry_run` row and a `changes` chip

**File:** `macos_apps_mcp/dashboard/writes.py:506-528` (`_asked`), `:665-676` (`_detail`), `:312` (`_write_row` chip)
**Issue:** A dashboard record (`tool: "dashboard"`, `caller: "dashboard"`) is the operator's own
click, but `_detail` renders it with the same blocks as a model write. I rendered a toggle record:
the detail reads `What changed / Turned Photos off / What the model asked for / tool dashboard /
adapter photos / on false / dry_run: not passed — not a dry-run tool / caller dashboard`, and the
list chip is `changes` (tier lookup misses, so `_TIER_CHIP.get(None, "changes")`). In an audit view,
attributing the operator's action to the model is misleading, and the `dry_run` row is made up
because the record has `dry_run: false` set explicitly.
**Fix:** For `row.kind == "dashboard"` skip `_asked` (or title it "What you did"), show `caller` only,
and use a neutral chip such as `dashboard`; add the class to `_CHIP_CLASS`. In `_asked`, read
`dry_run` from the record when `"dry_run"` is in `rec` rather than from the args.

### WR-04: PM-37's cap bounds the count of unknown adapter names, not their length: one long name still blows the `doctor` budget

**File:** `macos_apps_mcp/doctor.py:432-438` (`adapters_unknown`); `macos_apps_mcp/deploy.py:344-358` (4096-byte read); `tests/test_doctor.py:427-491`
**Issue:** PM-37 limited `adapters_unknown` to three names. The names are still unbounded in length
(the env var has no limit; the file read allows 4096 bytes). PM-08 accepted that a newline-separated
file reads as one unknown name, which makes a long single name easy to produce. I ran the
budget test with one 4000-character name: the daemon-role report is 10867 characters against the
7000 limit. The budget test uses ten short names (`no-such-adapter-N`), so it cannot see this.
`doctor` is a tool the model calls, so the extra 4 KB goes into the model's context on every call
until the file is fixed.
**Fix:** Clip each name: `names = sorted(n[:40] + ("…" if len(n) > 40 else "") for n in unknown_adapters)`.
Change the budget test's `junk` to include one 4000-character name.

### WR-05: A failure while building the dashboard takes MCP down; only a failed port bind is isolated

**File:** `macos_apps_mcp/daemon.py:327-337`
**Issue:** D-07 and T-05-13 say the dashboard must never take MCP down. `serve()` catches `OSError`
from `bind_dashboard`, but the next block (`from . import dashboard, deploy` and `dashboard.build_app(...)`)
is outside that `try`. An exception there (a missing `dashboard.css` read by `_STATIC` at import, a
starlette API change on a later `uv sync`, a corrupt package file) propagates out of `serve()`. launchd
(`KeepAlive`) relaunches the daemon into the same crash, every 10 s, and no MCP tool works. This is
the PM-02 class (a crash loop from an optional input). The build smoke imports `macos_apps_mcp.dashboard`,
which covers a broken bundle, but not a runtime failure in `build_app`.
**Fix:**
```python
try:
    from . import dashboard, deploy
    dash_app = dashboard.build_app(...)
except Exception as e:  # noqa: BLE001 - the dashboard must never take MCP down
    log.exception("dashboard not started")
    dashboard_state = f"not bound: {type(e).__name__}: {e}"
    tcp.close()
    tcp, dash_app = None, None
```

### WR-06: A toggle returns 303 even when its audit record was not written

**File:** `macos_apps_mcp/dashboard/adapters.py:248-273` (`_log`, `_apply_toggle`, `_apply_discard`); `macos_apps_mcp/audit.py:61-72`
**Issue:** Sketch rule 4 and D-15: every toggle and restart writes an audit record. `audit_write`
never raises (disk full, a read-only state folder, a permission change), so the file is already
rewritten when the log fails, and the handler redirects as if all went well. The operator's only
trace of the change is then missing, and the Writes page cannot show it. PM-19 pins write-before-log
order but not this silent failure. (The same applies to the restart record, which `go()` writes after
arming the exit.)
**Fix:** Let `audit_write` return `True` or `False`, make `_log` return it, and have the toggle
handler answer 500 with a short text ("changed, but the audit log could not be written") when it is
false. Keep the "audit never breaks a write" rule for the MCP middleware, which does not need the result.

## Info

### IN-01: The 0.15.0 changelog still says "This release adds the Usage page"

**File:** `CHANGELOG.md:34`
**Issue:** The dashboard bullet was written for the Usage-page PR. In the final 0.15.0 entry the next
five bullets add the Adapters, Writes, Health and Backups pages, so the sentence reads as if only
Usage ships.
**Fix:** Delete the sentence, or reword it ("The pages are listed below.").

### IN-02: The adapter-name set and the version lookup are written five times

**File:** `macos_apps_mcp/dashboard/adapters.py:50`, `macos_apps_mcp/dashboard/html.py:112`, `macos_apps_mcp/dashboard/writes.py:708`, `macos_apps_mcp/doctor.py:424`, `macos_apps_mcp/registry.py:200`; `macos_apps_mcp/dashboard/html.py:89-93` vs `macos_apps_mcp/doctor.py:290-300`
**Issue:** `{r.adapter for r in registry.TOOLS.values() if r.adapter}` appears in five modules, and
`html._version` duplicates `doctor._version` with a different fallback (`"dev"` against `"unknown"`),
so the sidebar footer and the Health page can name different versions for the same install.
**Fix:** Add `registry.adapter_names()` and use it everywhere; make `html._version` call
`doctor._version()` (Health already does).

### IN-03: Private cross-module reach and a shadowed parameter

**File:** `macos_apps_mcp/dashboard/writes.py:154` (`audit._resolve_dry_run`), `macos_apps_mcp/dashboard/health.py:106,280-281,288` (`deploy._BUNDLE_ID`, `doctor._version`, `doctor._build_stamp`), `macos_apps_mcp/dashboard/grants.py:50` (loop variable `service` shadows the `service` parameter)
**Issue:** Underscore names are used across modules, so a rename in `audit`, `doctor` or `deploy` breaks
the dashboard without a lint error. In `grant_state` the loop `for service, target in needs` rebinds
the parameter after it was used once; it works today and misleads the next edit.
**Fix:** Drop the underscore on the three shared helpers (or add public wrappers) and rename the loop
variable to `svc`.

### IN-04: `doctor` reports the dashboard URL even when every page answers 503

**File:** `macos_apps_mcp/daemon.py:329`, `macos_apps_mcp/doctor.py:446-455`
**Issue:** `dashboard_state` is set from the TCP bind alone. When the key file is unreadable,
`deploy.dashboard_key(create=True)` returns `None` and the Guard refuses everything with 503, yet
`deployment.dashboard` still says `http://127.0.0.1:47632`. The note only says the pages need the key.
**Fix:** After `key = deploy.dashboard_key(create=True)`, set
`dashboard_state = f"{url} (page key unusable: every page answers 503)"` when `key is None`.

### IN-05: The adapter gate re-reads the deny-list for every tool during import

**File:** `macos_apps_mcp/server.py:160-166`, `macos_apps_mcp/tiers.py:84-96`
**Issue:** `server._tool` calls `tiers.adapter_enabled` for each of about a hundred tools, and under
the daemon each call reads `adapters_off` again. A file change during the roughly one-second import
registers part of an adapter (for example the read tools but not the writes). The documented order
(write the file, then kickstart) avoids it; the reverse order does not. `doctor` then shows
`adapters_pending`, but the tool list is already inconsistent.
**Fix:** Take one snapshot per import: compute `_OFF = tiers.adapters_off()` once at the top of
`server.py` (or memoize it for the import) and have `_tool` test that set.

---

_Reviewed: 2026-10-22T20:56:14Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
