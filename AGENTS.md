# CLAUDE.md — macos-apps-mcp

One consolidated MCP server for native macOS apps. Python + **FastMCP**, managed with **`uv`**.
Full design and rationale: [DESIGN.md](DESIGN.md).

**Touching Mail? Read [docs/mail-applescript-facts.md](docs/mail-applescript-facts.md) FIRST.**
Device-verified traps that code review cannot catch — `delete` after `send` is a silent no-op, a
compose window is a recipient-less `outgoing message`, writing `content` on a forward destroys the
attachments, and Mail's Drafts autosave lands ~15s late so a 3-second check reports a clean
mailbox and lies. Verify every Mail write **by running it and inspecting the resulting message**;
three reviews and a green suite once passed a forward that delivered empty mail and ate 7
attachments.

## Architecture (don't drift)

- **FastMCP standalone.** Tools in `macos_apps_mcp/server.py` are *thin dispatch* to adapters — no
  business logic in the tool layer.
- **Adapters = typed `Protocol`** (`macos_apps_mcp/contracts.py`): **reads uniform**
  (`get_pointers -> list[Pointer]`), **writes per-adapter typed** (`create_reminder(ReminderData)`,
  `create_event(CalendarEventData)`). No ABC, no plugin registry (YAGNI). `Pointer(id, summary,
  deeplink)` is the citation contract — **pointers, not payload** (no full bodies by default).
- **All EventKit / native access goes through `macos_apps_mcp/runtime.run_native()`** — a single
  serialized worker thread (EKEventStore thread-affinity + TCC). Never call EventKit off arbitrary
  threads, and never widen the executor past `max_workers=1`.
- **One adapter module per app** under `macos_apps_mcp/adapters/`. Adding an app = add a module + mount its
  tools in `server.py` + (if the app is reached via osascript/Automation) add its name to
  `doctor._AUTOMATION_APPS` so `doctor` probes it; it must not reach into another adapter. This is
  what lets a module later harden into a `lyfe` native data-plane adapter unchanged.
- **The shim↔daemon hop has NO read deadline** (`daemon._uds_client_factory`, `Timeout(None,
  connect=10.0)`). A call's duration is the daemon's business — a bulk Mail pass runs HOURS —
  and it is a local socket with no network to time out on. Per-operation limits belong in the
  adapter, which knows what it asked for. Never "fix" a hang by adding a timeout here: that is
  #170, where httpx's own 5s default silently killed every destructive Mail call over ~5s. A
  dead stream must ANSWER (`fail_loud_on_dead_stream`) — silence is what a model misreads as
  failure, then retries a destructive call that already succeeded.
- **Three capability tiers, all gated at registration** (a gated-off tool is *absent*, never
  registered-and-erroring): read → write (`@_write_tool`/`@_additive_tool`, skipped by
  `MACOS_APPS_READ_ONLY`) → **outbound** (`@_send_tool("<adapter>")`, registered only when
  `MACOS_APPS_ALLOW_SEND` names that adapter; `READ_ONLY` wins unconditionally). Outbound acts off
  this machine, so it carries `openWorldHint` and defaults `dry_run=True` — and its dry-run path must
  make **no native call at all** (building a Mail `outgoing message` can strand an autosaved draft).
  A new send tool goes through `_send_tool` or `tests/test_tool_annotations.py` fails.

## Dev

```sh
uv sync
uv run pytest                   # unit tests — mock at the adapter boundary (Protocol fakes)
uv run pytest -m integration    # real macOS / EventKit / TCC — run manually, NEVER in CI
uv run ruff check .             # lint
uv run ruff format .            # format
uv run macos-apps-mcp            # run the server (stdio)
```

**Code style.** `ruff` for lint + format (config in `pyproject.toml`): line-length 88, rules
`E, F, I, UP, B, SIM` — same setup as the sibling repos (`lintle`, `descent-engine`). No mypy
(neither sibling uses one); the Protocol seam keeps the tool layer testable without it.

**Branches & releases.** `develop` is the trunk — every PR **rebase-merged**, so it stays linear.
`main` is release-only: nothing but `--no-ff` release cuts, each tagged `vX.Y.Z`. Full procedure,
including the two-file version bump and the mandatory `doctor().version` proof, is in
[docs/RELEASING.md](docs/RELEASING.md). **The repo is not the daemon** — merging changes nothing
about what Claude Code sees until the `.app` is rebuilt and reinstalled.

**Verification.** After completing edits, run these before reporting success — if any fail, report
the actual output, do not suppress or simplify failures:

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

## Life cockpit

Tracked in the life-cockpit vault under `#personal` (tracker: `elfensky/macos-apps-mcp`). The cockpit is
the control plane (what to work on); this repo is where the work happens. Report progress by
opening/closing issues and PRs as usual — the cockpit pulls from the tracker on its next `/sync`.
Nothing to update in the vault; don't mirror cockpit state (milestones, due dates) here.
