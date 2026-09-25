# Phase 1: Gate — Land the Spiked Architecture Cuts - Research

**Researched:** 2026-09-25
**Domain:** In-repo Python architecture refactor (module boundaries, test seams, tool
registration) — no new external dependencies, no new libraries, no network calls.
**Confidence:** HIGH (every finding below is grounded in a `git diff`/`git show` against
the actual spike branches and the actual `develop` HEAD, or a `Read` of the current file,
performed this session — not training-data recall of what a "typical" refactor looks like)

## Summary

This phase re-lands seven throwaway spike branches (`spike/arch-review-{1,7,5,2,3,4,9}-*`,
all 20 commits behind `develop` as of this research — not the 17 CONTEXT.md states;
`git rev-list --count d9ac75f..develop` returns 20 `[VERIFIED: git rev-list --count
d9ac75f01eab732509324c0f91087bd587ee6242..develop → 20]`) as real PRs on current
`develop`, in the order 1 → 7 → 5 → 2 with Mail-scoped 3/4/9 in parallel. None of the
spikes touch a package dependency; this is pure module-boundary surgery plus test-seam
hardening. The primary risk is not "what library to use" — there is none — it is
**collision between the spike's diff and the #199/#201 Sequoia-plane work that landed on
`develop` after the spike's merge-base**, and **three places where the spike's own diff
does not fully satisfy the phase's success criteria**, verified by reading the spike
source directly rather than assuming the recipe is complete.

**Primary recommendation:** redo each card by diffing spike vs. merge-base
(`d9ac75f01eab732509324c0f91087bd587ee6242`) to see the *shape* of the change, then apply
that shape by hand against current `develop`, using the collision map in this document
file-by-file. Do not `git cherry-pick` or rebase a spike commit (CONTEXT.md discretion
rule; also directly borne out by the collisions found below). Three items — the
`_no_real_osascript` fixture, `HEADER_FINGERPRINT` coverage, and the outbound-ledger
duplication between `tiers.py` and `registry.py` — require going beyond the spike diff
to actually satisfy the stated success criteria; see **Common Pitfalls**.

## Project Constraints (from CLAUDE.md)

- FastMCP standalone; tools in `server.py` are thin dispatch, no business logic in the
  tool layer.
- Adapters are typed `Protocol`s; reads uniform (`get_pointers -> list[Pointer]`), writes
  per-adapter typed. No ABC, no plugin registry.
- All EventKit/osascript access goes through `runtime.run_native()` — one serialized
  worker thread, `max_workers=1`, never widen it.
- One adapter module per app under `macos_apps_mcp/adapters/`; no cross-adapter imports.
- Seam calls are qualified (`from .. import runtime`, then `runtime.<name>(...)`) — never
  `from ..runtime import <name>` for a seam function (#176). This is the literal
  mechanism GATE-01 enforces and widens.
- Three capability tiers gated at registration (read → write → outbound); a gated-off
  tool is *absent*, never registered-and-erroring.
- `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .` must pass before
  reporting success; mock at the adapter boundary, integration tests never run in CI.
- `develop` is the trunk (rebase-merge only); `main` is release-only (`--no-ff` cuts,
  tagged `vX.Y.Z`).
- No mypy; ruff rules `E, F, I, UP, B, SIM`, line-length 88, Python 3.11+.
- `docs/mail-applescript-facts.md` must be read before any Mail change (cards 3/4/9) —
  done this session; relevant facts folded into Common Pitfalls below.

## User Constraints (from CONTEXT.md)

<user_constraints>
### Locked Decisions

- **D-01:** `delete_event`, `delete_draft` and `delete_note` default to `dry_run=True`.
  Today all three default to `False`. PROJECT.md says `delete_note` "has none" — stale;
  it has `dry_run: bool = False` today.
- **D-02:** `update_note` gets `dry_run: bool = True`. The preview shows the current
  title and body size against the new ones, and makes no Notes write. A read is allowed
  in this preview (the "no native call" rule applies to outbound dry runs only). Reason:
  `update_note` replaces the full title and body; its audit before-state is the title
  only (`notes.snapshot`, `macos_apps_mcp/adapters/notes.py:681`), so an overwritten body
  cannot be restored from the audit log.
- **D-03:** No other write tool changes its default. `update_event`, `update_reminder`
  and `complete_reminder` keep one-call semantics. `update_mail_status` and
  `run_shortcut` stay `False`. `move_mail`, `trash_mail`, `mail_undo` and the send tools
  stay `True`.
- **D-04:** The registration record declares the class "removes or replaces content".
  The registry test fails when a tool in that class does not default to `dry_run=True`.
  The test must fail closed for a new tool: any tool named `delete_*` is in the class
  even when its record forgets the flag (Phase 3's `delete_reminder`, REM-01, must be
  caught). The mechanism belongs to the planner.
- **D-05:** Cut a release from current `develop` before card 1 starts, per
  `docs/RELEASING.md`. This ships the Sequoia plane (#199/#201/#204) to the installed
  daemon. Today the daemon runs 0.10.1 (build `5f2cfb1`, 2026-08-23) without it. Includes
  the two-file bump, `--no-ff` cut to `main`, tag, then build → sign → notarize → staple
  → install → kickstart, and the `doctor().version` + `doctor().build` proof. The release
  tag is also the byte-identity baseline for success criterion 5.
- **D-06:** During the gate, the daemon checks after card 5 and after card 2 use **dev
  builds** from `develop` — no version bump, no tag. A check passes when `doctor().build`
  reports the built sha and one outbound dry run still reports gated correctly. "The new
  version" in success criterion 6 means "the new build sha" here.
- **D-07:** Each card gets one PR against `develop`, rebase-merged. Claude merges its own
  PR when CI is green, local `pytest`/`ruff check`/`ruff format --check` pass, and a
  code-review pass finds no open issue. The owner reviews after merge; each merge gets a
  one-line summary. The next sequential card branches from `develop` after the previous
  merge.
- **D-08:** Work stops for the owner at device steps only: (1) the pre-gate release +
  daemon install; (2) card 7's `-m integration -k "request_access or create_event or
  create_reminder"`; (3) card 4's scratch-mailbox verification with the watchdog running;
  (4) the dev-build daemon checks after cards 5 and 2.
- **D-09:** After the last card merges, delete every `spike/arch-review-*` branch
  (including non-landing 6, 6-baseline, 8, 8-alt) and their worktrees under
  `.claude/worktrees/`. New lanes for this phase use `.worktrees/` (PR #209 convention).

### Claude's Discretion

- **Re-land method:** redo each card's change on current `develop` using the spike diff
  as the recipe. Never cherry-pick or rebase the spike commit. A moved function body is
  copied from current `develop`, never from the spike. Check "bodies byte-identical"
  against `develop`.
- **Audit verbs (GATE-06):** short effect verbs in the style of `send`/`open`/`reply`.
  `move_mail`→`move`, `trash_mail`→`trash`, `mail_undo`→`undo`, `export_mail`→`export`,
  `save_mail_attachment`→`save`, music/volume/mode tools→`play`/`set`. `create_contact`
  must be logged. The verb comes from the registration record and is required for every
  write. Spike 2's `audit="write"` placeholder is replaced, and the `_audit_op` fallback
  to `"write"` is **removed** (the spike's own diff keeps it as a fallback — see Common
  Pitfalls, this must be gone, not merely superseded).
- **Card 2 decorator names:** keep `@_read_tool`, `@_write_tool`, `@_additive_tool`,
  `@_send_tool` as thin aliases over one `_tool(...)` record, as spike 2 did.
- **Card 3 Sequoia coverage:** the shared `fake_envelope` fixture runs every `query_*`
  executor test against both shapes (native, Sequoia); `HEADER_FINGERPRINT` covers every
  column an executor reads, and a test asserts that coverage.
- **Card 4 baseline:** regenerate the dry-run envelope / osascript argv baseline from the
  pre-cut `develop` (the D-05 release tag), not the spike's `tests/spike_arch4_old_dry_run.json`
  (taken at d9ac75f, before #201 changed `mail.py`). Rename `test_spike_arch4_*` files to
  drop "spike".
- **`_DEDUPE` (card 9):** raise the script `with timeout` backstop to at least the host
  cap (900s). Do not lower the host cap.
- **Release version (D-05):** 0.11.0 (feat commits since v0.10.1).
- **Small fixes:** rewrite `check_batch`'s refusal text so it does not claim a backup for
  `update_status`; remove the stale `daemon.py` comment.

### Deferred Ideas (OUT OF SCOPE)

- **Full-body snapshot for `update_note`** — backlog, not this phase.
- **Card 6, MailFilter** — land only when a 13th Mail search filter is added.
- **Card 8, MailAdapter pass-throughs** — withdrawn at review, not revisited.
- `MACOS_APPS_READ_ONLY=1` green (GATE-07), doctor off live `pgrep` (GATE-11), full
  device sweep (GATE-12) — all Phase 2.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| GATE-01 | Native seam fails closed for every adapter/doctor/shortcuts | `test_native_seam.py` widening confirmed against spike 1; **gap found**: spike's `_no_real_osascript` fixture is NOT extended to lock `body_file`/`tracked_run` — see Common Pitfalls |
| GATE-02 | `runtime.py` ~10 public names; EventKit cluster in its own module | Full target `runtime.py`/`eventkit.py` public-name lists extracted from spike 7; doctor.py/server.py import collisions mapped |
| GATE-03 | Tier policy + notice middleware out of `server.py`; no `doctor↔server` cycle | `tiers.py`/`notices.py` content extracted from spike 5; exact cycle line identified (`doctor.py:302`) |
| GATE-04 | One registration record per tool | `registry.py` extracted from spike 2; integration collision with card 5's `tiers.py` outbound ledger identified — not called out by CONTEXT.md |
| GATE-05 | Every destructive tool defaults `dry_run=True` | Current signatures of `delete_event`/`delete_draft`/`delete_note`/`update_note` read directly; D-04's fail-closed mechanism options laid out |
| GATE-06 | Writes audit under their own verb | Current `_audit_op` fallback read at `audit.py:185`; spike 2 keeps it as fallback — CONTEXT.md requires removal, a divergence from the spike recipe |
| GATE-08 | Shared envelope fixture covers every `query_*`-read column | `HEADER_FINGERPRINT` gap for `size`/`message_references` confirmed by the spike's own docstring; `envelope_mode` fixture already exists on `develop` (post-Sequoia), simplifying the redo |
| GATE-09 | `recoverable()` runs its own preflight | Current `dedupe_batch` dry-run bug (`preview()` called with no presence check) confirmed directly in `mail.py`; spike 4's `_presence()` helper extracted |
| GATE-10 | Script-timeout tripwire; `_DEDUPE` fix | `_DEDUPE_TIMEOUT=900` vs. script `with timeout of 600 seconds` bug confirmed at `mail.py:468`/`515`; full timeout inventory across adapters given |
| GATE-13 | Landing flow, daemon rebuilds, branch cleanup | `docs/RELEASING.md`/`docs/DAEMON.md` steps read in full; bundle id / kickstart mechanism confirmed |
</phase_requirements>

## Architectural Responsibility Map

This is a single-process local MCP server, not a multi-tier web app — "tiers" here are
internal module layers, not browser/CDN/backend.

| Capability | Owning module (post-gate) | Today | Rationale |
|------------|---------------------------|-------|-----------|
| Tool dispatch + registration record | `server.py` (via `registry.py`) | `server.py` hand-maintained sets | GATE-04: one record, not five parallel name sets |
| Capability-tier gate (read/write/send) | `tiers.py` (new) | `server.py` (`_read_only`/`_allow_send`) | GATE-03: `doctor`/`deploy` must read it without reaching into `server` |
| Untrusted-data notice middleware | `notices.py` (new) | `server.py` | GATE-03: not dispatch logic, belongs beside audit-adjacent concerns |
| Native worker + osascript/sqlite door | `runtime.py` (trimmed) | `runtime.py` (mixed with EventKit) | GATE-02: the door every adapter imports must stay small |
| EventKit store, NSDate/RRULE, TCC request | `eventkit.py` (new) | `runtime.py` | GATE-02: EventKit-typed code isolated so `runtime` has no `EventKit` import |
| Health/consent diagnostics | `doctor.py` | `doctor.py` (imports `server` locally) | GATE-03: must import `tiers`/`eventkit`, never `server` |
| Write audit trail + verb taxonomy | `audit.py` (verbs sourced from `registry.py`) | `audit.py` (`_audit_op` prefix table) | GATE-06: verb is a per-tool fact, not inferred from the name at audit time |
| Recoverable destructive plane (Mail) | `mail_recover.py` | `mail_recover.py` (`recoverable()` has no `dry_run`) | GATE-09: preflight belongs where every caller (`move_mail`/`trash_mail`/`dedupe_batch`) shares it |
| Mail sqlite read plane | `mail_index.py` + `tests/envelope.py` | `mail_index.py` + private `_fake_envelope` in one test file | GATE-08: fixture must be shared, schema must match what executors read |

## Standard Stack

No new libraries. This phase touches only in-repo modules with dependencies already
declared in `pyproject.toml` (fastmcp, PyObjC EventKit/Foundation, pytest, ruff). No
`npm view`/`pip index versions` verification applies — nothing is being added.

## Package Legitimacy Audit

**N/A for this phase.** No external packages are installed, upgraded, or newly imported
by any of the seven cards. All new modules (`eventkit.py`, `tiers.py`, `notices.py`,
`registry.py`, `tests/envelope.py`) are pure in-repo Python using only stdlib and
already-vendored dependencies (`EventKit`, `Foundation` from PyObjC, `fastmcp`). Skip the
Package Legitimacy Gate protocol.

## Architecture Patterns

### System Architecture Diagram (post-gate import graph)

```
                     ┌──────────────┐
   CLI / launchd ──▶ │ __init__.py  │──▶ imports server.py at process start
                     └──────┬───────┘        (runs every @_tool registration)
                            │
                            ▼
   ┌───────────────────────────────────────────────────────────────┐
   │ server.py  (thin dispatch only)                                │
   │   registers via registry._tool(tier, adapter, audit=, ...)    │
   │   reads gate state from  tiers.read_only() / tiers.allow_send()│
   │   wires  notices.UntrustedDataNotice  as FastMCP middleware    │
   └───────┬───────────────────────────────────┬───────────────────┘
           │ dispatch                            │ diagnostics
           ▼                                      ▼
   ┌───────────────┐                     ┌────────────────┐
   │ adapters/*.py │                     │ doctor.py       │
   │ (Protocol)    │                     │ imports:        │
   │ import ONLY:  │                     │  eventkit.request_access_each │
   │  runtime      │◀──native door───────│  runtime.{app_process_info,  │
   │  eventkit     │   (qualified, no    │    run_native, run_osascript}│
   │  errors/text  │    by-name import)  │  tiers.outbound_status (or   │
   └───────┬───────┘                     │   registry view, see pitfall)│
           │                             │  NEVER imports server.py     │
           ▼                             └────────────────┘
   ┌────────────────────────────┐
   │ runtime.py (~10 public names)│──▶ ThreadPoolExecutor(max_workers=1)
   │  run_native, on_worker,       │      "mac-native" worker thread
   │  run_osascript, tracked_run,  │
   │  body_file, terminate_children,│
   │  app_process_info,             │
   │  read_via_sqlite,               │
   │  verify_sqlite_schema, mac_region│
   └──────────┬─────────────────┘
              │ EventKit-typed calls only from
              ▼
   ┌────────────────────┐
   │ eventkit.py (new)   │──▶ EKEventStore, NSDate/RRULE coercion, TCC request,
   │  calendar/reminders │     run_native_async, bootstrap()
   │  import THIS, not   │
   │  runtime, for EK    │
   └─────────────────────┘
```

### Recommended Project Structure (new files this phase)

```
macos_apps_mcp/
├── eventkit.py          # card 7 — EventKit cluster split out of runtime.py
├── tiers.py             # card 5 — read_only/allow_send/admit_send/outbound ledger
├── notices.py           # card 5 — UntrustedDataNotice middleware
├── registry.py          # card 2 — ToolRecord + registry.TOOLS + derived views
tests/
├── envelope.py           # card 3 — promoted _fake_envelope, widened schema
```

### Pattern 1: Qualified native-seam import (card 1)

**What:** every adapter and `doctor.py` reaches the native seam as
`runtime.run_osascript(...)` / `runtime.tracked_run(...)` / `runtime.body_file(...)`,
never `from ..runtime import run_osascript`.
**When to use:** any new module that needs osascript, the shortcuts CLI, or the tempfile
body-transport helper.
**Example (verified against current develop + the spike's fix):**
```python
# WRONG — a copy in this module's namespace escapes the conftest lock
from ..runtime import tracked_run
proc = tracked_run(["shortcuts", "list"], timeout=10.0)

# RIGHT — qualified, one patch point for every test
from .. import runtime
proc = runtime.tracked_run(["shortcuts", "list"], timeout=10.0)
```
`[VERIFIED: macos_apps_mcp/adapters/shortcuts.py:21]` current develop still has
`from ..runtime import tracked_run` — this file has NOT been fixed yet and is squarely
in scope for card 1, per the widened glob (`adapters/*.py`, not just `mail*.py`).
`[VERIFIED: macos_apps_mcp/adapters/notes.py:30]` current develop still has
`from ..runtime import body_file, read_via_sqlite, run_osascript` — same fix needed.

### Pattern 2: Registration record replaces hand-maintained name sets (card 2)

**What:** one `_tool(tier, *, adapter=, permission=, audit=, notice=True,
backup_notice=False, snapshot=None, open_world=False, guard=True)` decorator builds a
`registry.ToolRecord` and stores it in `registry.TOOLS`, even for a gated-off tool
(`registered=False`). `write_tools()`, `snapshot_sources()`, `audit_verbs()`,
`no_notice()`, `backup_notice_tools()`, `send_adapters()`, `send_registered()` become
views over that dict instead of five separately-maintained sets.
**When to use:** every `@mcp.tool` registration in `server.py`.
**Example (from spike 2, `macos_apps_mcp/registry.py`, adapted — the derive-verb rule
that replaces `_audit_op`'s silent fallback):**
```python
def derive_audit_verb(name: str, tier: Tier, explicit: str | None) -> str | None:
    if tier == "read":
        if explicit is not None:
            raise TypeError(f"{name}: a read tool carries no audit verb")
        return None
    if explicit is not None:
        return explicit
    if tier == "send":
        return "send"
    for prefix in ("create", "update", "delete", "complete"):
        if name.startswith(prefix):
            return prefix
    raise TypeError(f"{name}: write tool needs an explicit audit= verb")
```
This RAISES instead of falling back to `"write"` — which is what CONTEXT.md's discretion
note requires and the spike diff does *not* fully deliver (see Common Pitfalls).

### Pattern 3: Recoverable-plane preflight (card 4)

**What:** `recoverable(op, targets, act, *, dry_run=False, present=_NO_READ, ...)` runs
the presence check itself when `dry_run=True`; a caller must pass a `present` callable
or an explicit `present=None` (meaning "this op has no read, preview `planned`
honestly") — leaving it unstated raises `TypeError`.
**When to use:** every caller of `mail_recover.recoverable` that supports a dry run
(`move_mail`, `trash_mail`, `dedupe_batch`).
**Example (spike 4, `macos_apps_mcp/adapters/mail_recover.py`, confirmed against
`d9ac75f..spike/arch-review-4-recoverable-preflight`):**
```python
def _presence(src: tuple[str, str]):
    """The plane's `present` read for one source mailbox."""
    return lambda targets: _present_ids(src, [t.id for t in targets])

# move_mail / trash_mail — same 6-line dry-run branch DELETED from each caller,
# folded into recoverable() itself:
return mail_recover.recoverable(
    "move", targets, act, dry_run=dry_run, present=_presence(src),
    destination=to_mailbox,
)

# dedupe_batch — present=None is DELIBERATE and visible: the CLI verifies via
# sqlite before calling this with dry_run=False only, so a dry run here answers
# "planned" per target and says nobody looked (no Apple Event) — this is the
# explicit-None escape hatch, not a silent gap.
return mail_recover.recoverable(
    "dedupe", targets, act, dry_run=dry_run, present=None,
    destination=trash, backup=False,
)
```
`[VERIFIED: macos_apps_mcp/adapters/mail.py:1478-1479]` current develop's `dedupe_batch`
dry-run branch is `if dry_run: return mail_recover.preview("dedupe", targets,
destination=trash)` — calling `preview()` directly with **no presence check at all**.
This is the exact GATE-09 bug ("`dedupe_batch(dry_run=True)` can no longer report
'planned' for targets it never checked") reproduced in the current codebase, not just a
hypothetical.

### Anti-Patterns to Avoid

- **Cherry-picking or rebasing a spike commit onto `develop`.** The spike branches are 20
  commits stale and every one of them touches at least one file the #199/#201 Sequoia
  plane also changed (`doctor.py`, `server.py`, `runtime.py`, `contracts.py`, `mail.py`,
  `mail_index.py`, `tests/conftest.py`). A cherry-pick either conflicts loudly or — worse
  — silently reintroduces pre-Sequoia code shape. Redo by hand from the diff.
- **Treating the spike diff as feature-complete.** Three of the seven cards' spike diffs
  do not fully satisfy their own success criterion when read literally (see Common
  Pitfalls) — they were throwaway spikes, not PRs, and were explicitly filed as "not a
  PR" in their own commit messages (e.g. `38e149f` card 9: *"Throwaway spike for
  architecture-review finding 9 ... Not a PR."*).
- **Keeping `_audit_op`'s `"write"` fallback "just in case."** CONTEXT.md is explicit:
  remove it. A silent fallback is exactly the bug GATE-06 exists to close, and keeping it
  (as spike 2 literally does) reopens the same hole with an extra layer on top.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|--------------|-----|
| Per-tool metadata (tier/verb/permission/snapshot) tracking | A sixth hand-maintained name set alongside `_WRITE_TOOLS`/`_SNAPSHOT_SOURCES`/etc. | `registry.ToolRecord` (card 2) | GATE-04's whole point: one record, no second edit to forget |
| AppleScript timeout auditing | A per-adapter ad-hoc check | One tripwire test that pairs every `with timeout of N seconds` template with its call-site `timeout=` kwarg (card 9) | Manual review already missed the `_DEDUPE` 600<900 bug once; a test catches it forever |
| Dry-run presence verification | Each mail write re-implementing its own "check presence before preview" block | `recoverable(dry_run=True, present=...)` (card 4) | `dedupe_batch` already shipped without it — the exact bug the phase exists to close |

**Key insight:** every "don't hand-roll" item in this phase is really the same lesson
applied three times: a fact needed in five places (dry-run default, audit verb, presence
check, timeout backstop, notice exemption) must be stated once and read back, not
re-derived per call site — because re-derivation is exactly how `dedupe_batch` and
`_DEDUPE` drifted.

## Runtime State Inventory

> This phase is a code-structure refactor, not a rename/rebrand/migration of user-facing
> identifiers. No stored data, live-service config, OS-registered state, secret/env-var
> names, or user-facing build artifacts change name or shape as a result of this phase.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — no database, collection, or user_id keys change | None |
| Live service config | None — no n8n/Datadog/Tailscale/Cloudflare config touched | None |
| OS-registered state | The **daemon itself** is rebuilt and re-kickstarted twice (after card 5, after card 2) plus once released (D-05) — this is a *build* action, not a rename; the LaunchAgent identity (`ren.lav.macos-apps-mcp`) is unchanged `[VERIFIED: CLAUDE.md "macOS bundle metadata" reference confirms bundle id is stable across this phase — no file in the diff touches packaging/Info.plist's CFBundleIdentifier]` | Rebuild + reinstall + `launchctl kickstart -k gui/$UID/ren.lav.macos-apps-mcp` per D-06; no re-registration needed |
| Secrets/env vars | None — `MACOS_APPS_READ_ONLY`/`MACOS_APPS_ALLOW_SEND` env var *names* are unchanged; only which module reads them moves (`server.py` → `tiers.py`) | Code edit only (import path), the env var contract for callers is unchanged |
| Build artifacts | `spike/arch-review-*` branches and `.claude/worktrees/` are deleted post-landing (D-09); this is repo hygiene, not a build artifact needing a data migration | `git branch -D` + `git worktree remove` per card, after the last card merges |

## Common Pitfalls

### Pitfall 1: The spike's `_no_real_osascript` fixture does not lock `body_file`/`tracked_run`

**What goes wrong:** GATE-01's success criterion explicitly names three seam names that
must be "locked once in conftest": `run_osascript`, `body_file`, `tracked_run`. The
actual conftest.py diff in `spike/arch-review-1-native-seam` touches only the
**docstring** of the existing `_no_real_osascript` fixture — it still only
`monkeypatch.setattr(runtime, "run_osascript", _refuse)`.
`[VERIFIED: git diff d9ac75f01eab732509324c0f91087bd587ee6242..spike/arch-review-1-native-seam
-- tests/conftest.py]` shows a 7-line diff, all in the docstring; no new
`monkeypatch.setattr` line for `body_file` or `tracked_run` was added.
**Why it happens:** the spike widened the *static* AST check (`test_native_seam.py`'s
`_SEAM` set now includes `body_file`/`tracked_run`, confirmed at
`[VERIFIED: git show spike/arch-review-1-native-seam:tests/test_native_seam.py]`
`_SEAM = frozenset({"run_osascript", "body_file", "tracked_run"})`), which catches a
by-name **import**. It does not add the runtime **fail-closed lock** for the two newly
qualified calls, which catches a test that forgets to `monkeypatch` a qualified call.
Both are needed: the static check stops a regression to by-name imports; the fixture
stops a *new* test (e.g. in `test_shortcuts.py` or `test_notes.py`) that calls
`runtime.tracked_run`/`runtime.body_file` for real without faking it.
**How to avoid:** extend `_no_real_osascript` (or add two sibling autouse fixtures) in
`tests/conftest.py` to also refuse `runtime.body_file` and `runtime.tracked_run` unless
faked, exactly mirroring the existing `run_osascript` refusal. This is beyond the spike
diff — plan it as an explicit task, not "port the spike."
**Warning signs:** a new adapter test spawns a real subprocess or writes a real tempfile
during `uv run pytest` and the test suite still passes (silently) because nothing failed
closed.

### Pitfall 2: `HEADER_FINGERPRINT` still won't cover what card 3's own fixture needs

**What goes wrong:** GATE-08 requires `HEADER_FINGERPRINT` to cover every column a
`query_*` executor reads, "so a real store missing them surfaces as drift, not a
query-time error." The spike's own `tests/envelope.py` docstring says the opposite is
still true after the spike lands:
`[VERIFIED: git show spike/arch-review-3-fake-envelope-fixture:tests/envelope.py]`
*"Neither of those columns is in `HEADER_FINGERPRINT`, so the fingerprint would not
catch a real store lacking them either (out of scope here; noted for the reviewer)."*
— referring to `messages.size` (read by `query_duplicate_rows`) and the whole
`message_references` table plus `recipients.type`/`position` (read by
`query_sent_triage`).
**Why it happens:** the spike's job was to prove the fixture *could* serve these reads;
extending the drift-detection fingerprint to match was explicitly deferred.
**How to avoid:** this phase's card 3 must add `size`, `message_id`, `subject_prefix` to
`HEADER_FINGERPRINT["messages"]`, add a `message_references` entry
(`{"ROWID", "message", "reference"}`), and extend `recipients` to `{"message",
"address", "type", "position"}` — then write the test CONTEXT.md's discretion note
requires ("a test asserts that coverage"), e.g. a test that statically extracts every
`m.<col>`/`table.<col>` reference from each `query_*` function body via `ast` and asserts
it's a subset of `HEADER_FINGERPRINT`.
`[VERIFIED: macos_apps_mcp/adapters/mail_index.py:26-45]` current `HEADER_FINGERPRINT`
has `"messages": {"ROWID", "subject", "sender", "global_message_id", "mailbox",
"date_received", "date_sent", "read", "flagged", "deleted", "conversation_id"}` — no
`size`, no `message_id`, no `subject_prefix`.
**Warning signs:** `query_duplicate_rows`/`query_sent_triage` work fine against the test
fixture but silently mis-parse (rather than typed-`SchemaDrift`-fail) on a real Mac whose
Envelope Index schema has drifted on those specific columns.

### Pitfall 3: Card 5's outbound ledger and card 2's registry duplicate each other

**What goes wrong:** neither CONTEXT.md nor the phase description calls this out, and it
only becomes visible by reading both spike diffs side by side. Spike 5 (`tiers.py`)
introduces `_SEND_ADAPTERS`/`_SEND_REGISTERED`/`admit_send()`/`outbound_status()` as the
outbound capability ledger. Spike 2 (`registry.py`) — built *before* `tiers.py` existed
(both spikes share merge-base `d9ac75f`, and card 2's `_tool()` decorator still calls a
local, pre-`tiers` `_allow_send()` — confirmed at
`[VERIFIED: git show spike/arch-review-2-registration-record:macos_apps_mcp/server.py]`,
the `_tool()` function body reads `registered = _allow_send(adapter)` for the send tier)
— *also* derives `send_adapters()`/`send_registered()` as views over `registry.TOOLS`.
Landed sequentially (5 then 2, per D-07's rebase-onto-previous rule), these are two
sources of truth for the same fact.
**Why it happens:** the spikes were built in parallel off one merge-base, each solving
its own finding independently; neither anticipated the other landing first.
**How to avoid:** when card 2 rebases onto card 5, `_tool()`'s `tier == "send"` branch
must call `tiers.admit_send(adapter)` (not a duplicated `_allow_send`), and `doctor`'s
`outbound_status()` should come from **one** of the two ledgers, not both — the
registration record (GATE-04's "one record" principle) is the more defensible owner
since `registry.TOOLS` already knows `tier`, `adapter`, and `registered` per tool; `tiers.py`
should keep only the pure gate predicates (`read_only()`, `allow_send()`) and drop its own
`_SEND_ADAPTERS`/`_SEND_REGISTERED`/`admit_send`/`outbound_status` once `registry.py`
lands. Plan this as an explicit integration task on card 2, not an assumption that the
two spikes compose for free.
**Warning signs:** `doctor().deployment.outbound` and a `registry`-derived outbound view
disagree after a toggle flip, because one ledger updates and the other doesn't.

### Pitfall 4: `check_batch`'s refusal text is already wrong for `update_status`

**What goes wrong:** `BatchTooLarge`'s message says "every target is backed up to disk
before anything moves" — but `update_mail_status` calls `check_batch` too, and never
backs anything up (it only flips `read`/`flagged` booleans; server.py's docstring says
`dry_run defaults to FALSE: this changes two booleans, destroys nothing`).
`[VERIFIED: macos_apps_mcp/adapters/mail_recover.py:141-158]`
`[VERIFIED: macos_apps_mcp/adapters/mail.py:1560]` — `mail_recover.check_batch(mids)`
is called from `update_status` at this line, which never reaches `recoverable()`/backup.
**How to avoid:** make the refusal text conditional (or generic — "the safety cap is
N" without the backup claim), per CONTEXT.md's small-fix instruction.

### Pitfall 5: the `_DEDUPE` timeout bug is real and reproducible today

**What goes wrong:** `_DEDUPE_TIMEOUT = 900.0` (the host-side `timeout=` passed to
`runtime.run_osascript`) but the AppleScript template's own backstop is `with timeout of
600 seconds` — the script can self-abort via its own `with timeout` block **before** the
host-side 900s cap would ever fire, which defeats the purpose of the host cap (a batch
that legitimately needs 700s never gets there).
`[VERIFIED: macos_apps_mcp/adapters/mail.py:468]` `_DEDUPE_TIMEOUT = 900.0`
`[VERIFIED: macos_apps_mcp/adapters/mail.py:515]` `  with timeout of 600 seconds`
(inside the `_DEDUPE` template starting at `mail.py:499`)
**How to avoid:** raise line 515's `600` to `900` (or higher) — do not lower
`_DEDUPE_TIMEOUT`. Then write the general tripwire (GATE-10) so this class of bug can't
recur: parse every `with timeout of N seconds` occurrence per template constant, resolve
which `timeout=` kwarg value is passed at each `run_osascript(TEMPLATE, ..., timeout=X)`
call site (via `ast`, matching the template constant as the positional callee arg), and
assert `N >= X` everywhere. A hand-maintained mapping table is an acceptable simpler
implementation if the AST cross-reference proves too fragile — the *test asserting the
invariant* is what GATE-10 requires, not a specific implementation strategy.

### Pitfall 6: the doctor.py↔server.py import-cycle removal collides with card 7's import edit on the SAME line

**What goes wrong:** both card 5 and card 7 touch
`macos_apps_mcp/doctor.py`'s import block, and card 5 also removes the
`_outbound_state()` local-import-of-server function
(`[VERIFIED: macos_apps_mcp/doctor.py:297-306]`, currently `from . import server` inside
`_outbound_state()`, with the docstring *"Imported LOCALLY ... a module-level `import
server` here would be circular — this is the one place doctor.py reaches into server.py"*).
**Why it happens:** landing order is 1 → 7 → 5 → 2, sequential — this is not a
simultaneous edit conflict, but the planner must sequence card 5's doctor.py edit to
start from the **post-card-7** import line (`from .eventkit import request_access_each` /
`from .runtime import app_process_info, run_native, run_osascript`), not from the
pre-card-7 line the spike 5 diff was authored against (which still reads `from .runtime
import app_process_info, request_access_each, run_native, run_osascript`).
**How to avoid:** when planning card 5, its recipe step must say "starting from
doctor.py's import block as card 7 left it," not "as the spike diff shows it" — the raw
spike diff for card 5 is authored against the pre-card-7 shape and would silently
reintroduce the `runtime.request_access_each` import if applied literally after card 7.

## Code Examples

### The redo procedure for every card (verified against this session's `git diff`)

```bash
# 1. See the shape of the change (never apply this literally — read it as a recipe)
git diff d9ac75f01eab732509324c0f91087bd587ee6242..spike/arch-review-<N>-<slug> -- <files>

# 2. See what develop changed in the same files since that merge-base (the collision set)
git diff d9ac75f01eab732509324c0f91087bd587ee6242..develop -- <same files>

# 3. Apply the spike's shape by hand onto current develop's version of each file,
#    reconciling with what step 2 shows changed independently.
```

### Runtime's target public surface after card 7 (verified: `git show
spike/arch-review-7-runtime-split:macos_apps_mcp/runtime.py | grep -n "^def \|^log ="`)

```
run_native, on_worker, app_process_info, terminate_children, tracked_run,
run_osascript, body_file, verify_sqlite_schema, read_via_sqlite, mac_region, log
```
11 names (10 callables + the module logger) — matches GATE-02's "~10 public names."
`_open_sqlite_ro` stays private (leading underscore) but is imported by name from
`deploy.py` today (`[VERIFIED: macos_apps_mcp/deploy.py:97]`
`from .runtime import _open_sqlite_ro, verify_sqlite_schema`) — a private-name cross-module
import that predates this phase and is out of scope to fix here, but the planner should
note it doesn't shrink the "public names" count since it's already underscore-prefixed.

### `eventkit.py`'s target public surface (same source)

```
store, request_access, request_access_each, bootstrap, run_native_async,
to_nsdate, epoch_nsdate, from_nsdate, due_components, to_recurrence_rule,
recurrence_signature, persisted_recurrence_signature, rrule_text, container_id
```
`calendar.py`/`reminders.py` import these from `.eventkit` instead of `.runtime`
(verified diff, `git diff d9ac75f..spike/arch-review-7-runtime-split -- macos_apps_mcp/adapters/calendar.py macos_apps_mcp/adapters/reminders.py`) — both keep importing
`run_native` from `.runtime` separately, since that stays runtime's job.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|-------------------|---------------|--------|
| `server.py` holds tier gates, notice middleware, and five hand-maintained tool-name sets | `tiers.py`/`notices.py`/`registry.py` each own one concern; `server.py` is thin dispatch + registration calls | This phase (cards 2, 5) | `doctor`/`deploy` stop needing a lazy circular import into `server` |
| Each mail write's dry-run branch re-implements its own presence check | `recoverable()` owns the preflight; callers pass `present=` | This phase (card 4) | `dedupe_batch`'s unverified-preview bug becomes structurally impossible for any *future* caller |
| `_fake_envelope` lives privately in `test_mail_search.py` | `tests/envelope.py` shared fixture, already running through the post-Sequoia `envelope_mode` fixture on `develop` | This phase (card 3), building on #199/#201 which already landed `envelope_mode` | Other mail test files stop stubbing `query_*` and start testing against real sqlite shapes |

**Note on timing:** the `envelope_mode`/`sequoiaify_envelope` fixture infrastructure
CONTEXT.md's "Card 3 Sequoia coverage" note asks for **already exists on `develop`**
(landed by #201, independent of this phase) — `[VERIFIED: tests/test_mail_search.py:18]`
`pytestmark = pytest.mark.usefixtures("envelope_mode")` is already active. Card 3's job
is narrower than "add Sequoia coverage": it is "promote the fixture to a shared file
with a wider schema, and route more test files through the fixture that already covers
both shapes."

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The GATE-10 tripwire's exact implementation strategy (AST cross-reference vs. hand-maintained mapping table) is left to the planner/implementer, since neither CONTEXT.md nor any spike specifies one (card 9's spike bundled the tripwire with a `framed_script` wrapper that CONTEXT.md says was withdrawn) | Common Pitfalls #5 | If the planner picks the AST route and it proves too fragile against real template strings, mid-phase replanning costs a wave; the hand-maintained-table fallback should be pre-agreed |
| A2 | Card 2's registry vs. card 5's tiers outbound-ledger duplication (Pitfall 3) is resolved by making `registry.py` the sole ledger owner and trimming `tiers.py` back to pure gate predicates — this is this researcher's architectural read of GATE-04's "one record" principle, not a decision either spike or CONTEXT.md states explicitly | Common Pitfalls #3 | If the planner instead keeps both ledgers "for now," `doctor().deployment.outbound` can silently drift from the registry's own view after a toggle flip — exactly the class of bug this phase exists to prevent |

## Open Questions

1. **Does the D-05 pre-gate release block on Phase 02.1's Mail fixes, or proceed with
   0.10.1's `recoverable()`/`_DEDUPE` bugs intact until this phase's cards 4/9 land?**
   - What we know: D-05 says cut the release "before card 1 starts," to ship the Sequoia
     plane. STATE.md says Phase 02.1 (Mail fixes, #206/#208) is scheduled right after
     this gate phase, specifically because "card 4 rewrites `recoverable()`."
   - What's unclear: whether the 0.11.0 release cut for D-05 happens *before* or *after*
     cards 4/9 land within this same phase (the phase's landing order is 1 → 7 → 5 → 2
     sequential with 3/4/9 in parallel — D-05's release is described as "the first plan
     of the phase," i.e., before any card, so it ships pre-card-4 bugs to the daemon).
   - Recommendation: confirm with the operator whether the D-05 release should be recut
     (or a second release cut) after cards 4/9 merge, since D-06 only mentions dev builds
     (no tag) after cards 5 and 2 — cards 3/4/9 get no daemon-rebuild checkpoint at all
     per D-08's device-step list. This may be intentional (Mail fixes ship formally in
     Phase 02.1's own release) — worth a one-line confirmation, not a blocker.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|--------------|-----------|---------|----------|
| `uv` | all dev commands | ✓ (per CLAUDE.md conventions; not independently re-probed this session — command availability is process-standard for this repo, not phase-specific) | — | — |
| macOS 12+ / EventKit / TCC | card 7's device proof (`-m integration -k "request_access or..."`) | Device-only step, owner-run per D-08 | — | none — this is a hard device checkpoint, not automatable |
| `codesign`/`notarytool` | D-05 release build | Device-only step, owner-run per D-08 | — | none |

No new external service or tool dependency is introduced by this phase; all of the above
are already required by the project's existing release/dev workflow.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.x (`[VERIFIED: pyproject.toml]` `pytest 8.x, <10`) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` — `testpaths = ["tests"]`, `markers = ["integration: ..."]`, `addopts = "-m 'not integration'"` `[VERIFIED: pyproject.toml:77-80]` |
| Quick run command | `uv run pytest` |
| Full suite command | `uv run pytest && uv run ruff check . && uv run ruff format --check .` |
| Device/integration command | `uv run pytest -m integration -k "<selector>"` (never in CI; run manually) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|---------------------|-------------|
| GATE-01 | Every `adapters/*.py` + `doctor.py` (incl. `shortcuts.tracked_run`) fails closed on a forgotten native-seam fake | unit | `uv run pytest tests/test_native_seam.py -v` | ✅ exists, needs widening (43 lines today) |
| GATE-01 | `body_file`/`tracked_run` also fail-closed at runtime, not just statically | unit | new test in `tests/test_native_seam.py` or `tests/conftest.py` exercising the new autouse lock | ❌ Wave 0 — must be written fresh (Pitfall 1) |
| GATE-02 | `runtime.py` ~10 public names, EventKit isolated | unit | `uv run pytest tests/test_runtime.py tests/test_eventkit.py -v` | ⚠️ `test_runtime.py` exists (needs trimming per spike, -150 lines), `test_eventkit.py` is new (spike has 184 lines to adapt) |
| GATE-02 | Device proof: EventKit still works post-split | integration (device, D-08 step 2) | `uv run pytest -m integration -k "request_access or create_event or create_reminder"` | ✅ command confirmed against `pyproject.toml` marker config |
| GATE-03 | `doctor` imports no `server` symbol; no import cycle | unit | new/updated `tests/test_doctor.py`, `tests/test_doctor_deploy.py`; a static test (e.g. `ast`-grep `doctor.py` for `import server`) is the most direct fail-closed check | ⚠️ existing files need updates; a NEW static-cycle test is not in any spike — Wave 0 |
| GATE-03 | Tier policy behaves identically after the move | unit | `uv run pytest tests/test_server.py tests/test_deploy.py tests/test_gate_on_dispatch.py -v` | ✅ all exist |
| GATE-04 | One registration record drives annotations/gates/guard/snapshot/notice/verb | unit | `uv run pytest tests/test_registry.py tests/test_tool_annotations.py -v` | ⚠️ `test_registry.py` is new (spike has 269 lines); `test_tool_annotations.py` shrinks drastically (spike: 290→~141 lines) |
| GATE-05 | Every destructive tool defaults `dry_run=True`, fail-closed on `delete_*` prefix | unit | new registry test asserting the "removes or replaces content" class default | ❌ Wave 0 — mechanism is the planner's call (D-04) |
| GATE-06 | Every write logs its own verb, no bare `"write"`, `_audit_op` fallback removed | unit | `uv run pytest tests/test_audit.py tests/test_audit_middleware.py -v` | ✅ files exist, need new assertions per the removed fallback |
| GATE-08 | `HEADER_FINGERPRINT` covers every `query_*`-read column; shared fixture across both shapes | unit | `uv run pytest tests/test_mail_search.py tests/test_mail_cleanup.py tests/test_mail_index.py -v` | ⚠️ needs the fingerprint-coverage test written fresh (Pitfall 2) |
| GATE-09 | `recoverable()` preflight; `dedupe_batch` can't report "planned" unchecked | unit | `uv run pytest tests/test_mail_recover.py tests/test_mail.py -v` (rename `test_spike_arch4_*` per Claude's Discretion) | ⚠️ new assertions needed on `dedupe_batch`'s dry-run path |
| GATE-09 | Device proof: scratch mailbox, byte-identical dry-run envelopes/argv | manual (device, D-08 step 3) | run against `Personal/macos-apps-mcp-test` with `~/mail-watchdog/capture.sh` running first `[CITED: docs/mail-applescript-facts.md §9]` | manual-only, justified — Mail writes cannot be verified by reading code (`docs/mail-applescript-facts.md` §1) |
| GATE-10 | Timeout tripwire; `_DEDUPE` 600→900 fix | unit | new test, e.g. `tests/test_timeout_tripwire.py` | ❌ Wave 0 — no spike delivers this cleanly (card 9's wrapper was withdrawn) |
| GATE-13 | Two-file version bump matches | unit | `uv run pytest tests/test_packaging.py` | ✅ exists (`[CITED: docs/RELEASING.md]` "a mismatch ships an `.app` that lies about itself") |
| GATE-13 | `doctor().version` / `doctor().build` after each daemon rebuild | manual (device, D-08 steps 1 & 4) | `doctor()` tool call post-kickstart | manual-only, justified — daemon identity cannot be verified from the repo |

### Sampling Rate

- **Per task commit:** `uv run pytest` (fast, excludes integration by default per
  `addopts`)
- **Per card PR merge:** `uv run pytest && uv run ruff check . && uv run ruff format
  --check .` (D-07's explicit merge gate)
- **Phase gate:** the D-08 device checkpoints, each at its named point in the landing
  sequence — not deferred to phase end, since GATE-12's full device sweep is explicitly
  Phase 2's job, not this phase's.

### Wave 0 Gaps

- [ ] `tests/conftest.py` — extend `_no_real_osascript` (or add sibling fixtures) to lock
      `body_file` and `tracked_run`, not just `run_osascript` (Pitfall 1)
- [ ] A `HEADER_FINGERPRINT` coverage test in `tests/test_mail_index.py` or
      `tests/envelope.py` asserting every `query_*` executor's read columns are a subset
      of the fingerprint (Pitfall 2)
- [ ] A registry test for D-04's fail-closed `delete_*`-prefix dry-run-default rule
      (mechanism is the planner's/implementer's design choice)
- [ ] A static import-cycle test for `doctor.py` (no spike delivers one; GATE-03's "no
      import cycle in the package" needs an explicit assertion, not just passing tests)
- [ ] `tests/test_timeout_tripwire.py` (or equivalent) — GATE-10's tripwire, built fresh
      per Pitfall 5 since card 9's spike wrapper was withdrawn

## Security Domain

`security_enforcement` is enabled (`security_asvs_level: 1`, `security_block_on: high`
per `.planning/config.json`). This phase adds no new external input surface, no new
network listener, and no new cryptography — it moves existing code between modules and
adds one new dry-run default. The relevant ASVS surface is therefore narrow.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-------------------|
| V2 Authentication | No | No new auth surface this phase (daemon TCC/socket auth model unchanged) |
| V3 Session Management | No | Unchanged |
| V4 Access Control | Yes (narrowly) | The capability-tier gate itself (`tiers.read_only()`/`allow_send()`) is being moved, not redesigned — regression risk is "the gate stops being consulted at the same point," not a new access-control mechanism. Test coverage: `tests/test_gate_on_dispatch.py`, `tests/test_deploy.py` |
| V5 Input Validation | Yes (preserved, not added) | `run_osascript`'s existing `--` argv-separator injection guard (`[VERIFIED: macos_apps_mcp/runtime.py:305-333]`) is untouched by this phase — no adapter changes its argument-passing shape |
| V6 Cryptography | No | No cryptography touched (code-signing/notarization for the D-05 release is an existing, unchanged process, not new crypto code) |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|-----------------------|
| A test that forgets to fake the native seam spawns a real Apple Event / subprocess against the user's real Mail/Calendar/Reminders during `uv run pytest` | Tampering (unintended write against live user data during a test run) | The `_no_real_osascript`-style autouse fixture (GATE-01) — this IS the mitigation this phase installs; Pitfall 1 identifies where the mitigation is currently incomplete |
| A gated-off tool (READ_ONLY or send-disabled) is silently registered anyway due to a registration-order bug | Elevation of Privilege (a write/send tool reachable when the deploy config says it shouldn't be) | GATE-04's "gated-off tools are still recorded pre-gate, never derived from FastMCP `Tool` objects" — the registry records `registered=False` explicitly rather than inferring absence from FastMCP's own tool list |
| A dry-run preview reports "planned"/"present" for a target that was never actually checked, giving a false sense of safety before a destructive batch op | Repudiation / Tampering (the user acts on a preview that lied) | GATE-09's `recoverable()` preflight — the exact bug already present in `dedupe_batch` (see Common Pitfall 2 in the Architecture Patterns section / Pitfall 4 above referring to `check_batch`, and the GATE-09 finding referring to `recoverable`) |

## Sources

### Primary (HIGH confidence — read/executed this session)

- `git diff`/`git show` against all seven spike branches vs. merge-base
  `d9ac75f01eab732509324c0f91087bd587ee6242` and vs. current `develop` HEAD (`59f4558`)
- `Read` of current `macos_apps_mcp/runtime.py`, `doctor.py`, `audit.py`,
  `contracts.py`, `adapters/mail.py`, `adapters/mail_recover.py`,
  `adapters/mail_index.py`, `adapters/notes.py`, `server.py` (targeted sections),
  `tests/conftest.py`, `tests/test_native_seam.py`, `tests/test_tool_annotations.py`,
  `tests/test_mail_search.py`, `tests/test_mail_cleanup.py`
- `docs/mail-applescript-facts.md` — read in full this session
- `docs/RELEASING.md` — read in full this session
- `docs/DAEMON.md` §Install (daemon mode) — read this session
- `.planning/phases/01-.../01-CONTEXT.md`, `.planning/REQUIREMENTS.md`,
  `.planning/STATE.md` — read this session

### Secondary (MEDIUM confidence)

- None — this phase required no external documentation lookup (no library/framework
  questions; pure in-repo architecture).

### Tertiary (LOW confidence)

- None.

## Metadata

**Confidence breakdown:**
- Standard stack: N/A — no new dependencies this phase
- Architecture: HIGH — every module-boundary claim is grounded in a `git diff`/`git show`
  against the actual spike source and current `develop`, performed this session
- Pitfalls: HIGH — all six pitfalls are reproduced or directly quoted from current
  source or the spike's own docstrings, not inferred

**Research date:** 2026-09-25
**Valid until:** this research is tied to `develop @ 59f4558` and the seven spike SHAs
listed in CONTEXT.md's canonical refs; it goes stale the moment any card lands (each
landed card changes the collision map for the next one) — re-diff before planning the
next sequential card if more than a few days elapse between planning and execution.
