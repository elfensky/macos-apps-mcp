# CLAUDE.md — macos-apps-mcp

One consolidated MCP server for native macOS apps. Python + **FastMCP 2.0**, managed with **`uv`**.
Full design and rationale: [DESIGN.md](DESIGN.md).

## Architecture (don't drift)

- **FastMCP 2.0 standalone.** Tools in `macos_apps_mcp/server.py` are *thin dispatch* to adapters — no
  business logic in the tool layer.
- **Adapters = typed `Protocol`** (`macos_apps_mcp/contracts.py`): **reads uniform**
  (`get_pointers -> list[Pointer]`), **writes per-adapter typed** (`create_reminder(ReminderData)`,
  `create_event(CalendarEventData)`). No ABC, no plugin registry (YAGNI). `Pointer(id, summary,
  deeplink)` is the citation contract — **pointers, not payload** (no full bodies by default).
- **All EventKit / native access goes through `macos_apps_mcp/runtime.run_native()`** — a single
  serialized worker thread (EKEventStore thread-affinity + TCC). Never call EventKit off arbitrary
  threads, and never widen the executor past `max_workers=1`.
- **One adapter module per app** under `macos_apps_mcp/adapters/`. Adding an app = add a module + mount its
  tools in `server.py`; it must not reach into another adapter. This is what lets a module later
  harden into a `lyfe` native data-plane adapter unchanged.

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
