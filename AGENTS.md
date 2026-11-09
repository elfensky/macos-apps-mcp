# AGENTS.md — macos-apps-mcp

One consolidated MCP server for native macOS apps, worked on by Andrei, shipped as a signed `.app` daemon, on PyPI and
in the MCP Registry.

Shared standards: the developer handbook, `~/vault/knowledge/developer/developer.md` (layout 1.0.0).
This file holds only what is true of this repo. Personal project: commits as `andrei@lav.ren`, `gh` user `elfensky`
(identity per project: `~/vault/meta/registry.md`).

## Stack

| Layer | Choice | Notes |
|---|---|---|
| Framework | FastMCP 4 on MCP 2 | Pins and the reason for each in `pyproject.toml` (#470) |
| Language | Python, `uv` | `requires-python >=3.12`; `ruff` config in `pyproject.toml`. No mypy (2026-06-24: the Protocol seam keeps the tool layer testable without it) |
| Runtime | Python 3.14 (`.python-version`) | The daemon `.app` declares macOS 15 |
| Deploy | Signed, notarized `.app` with a launchd agent; PyPI; the MCP Registry | `docs/DAEMON.md`, `docs/RELEASING.md` |

## Commands

| Command | Purpose |
|---|---|
| `uv sync` | Install the locked environment |
| `uv run ruff check . && uv run ruff format --check . && uv run pytest && MACOS_APPS_READ_ONLY=1 uv run pytest` | **Verification gate**: lint, format, tests, then the read-only tier, in CI's order. Run it before calling work done |
| `uv run ruff format .` | Format |
| `uv run pytest -m integration` | Real macOS, EventKit and TCC. Run by hand on this Mac, never in CI (2026-06-23: it needs real grants) |
| `uv run pytest -m device` | The installed daemon over its socket. Run by hand after a deploy (`docs/RELEASING.md`), never in CI |
| `uv run macos-apps-mcp` | Run the server (stdio) |
| `scripts/build_app.sh` | Build the `.app` (`docs/DAEMON.md`) |

## Branches

`develop` integrates. `main` releases: only `--no-ff` release cuts from `develop`, each tagged `vX.Y.Z`; the merge to
`main` publishes to TestPyPI, and PyPI is a manual dispatch (`docs/RELEASING.md`). Merge with `gh pr merge --rebase`,
then `git push origin --delete <branch>`. Rulesets: `develop` takes PRs with rebase only and requires `check`; `main`
takes PRs with a merge commit only and requires `check` and `bumped`.

## This repo's own rules

- **Touching Mail? Read [docs/mail-applescript-facts.md](docs/mail-applescript-facts.md) FIRST** (2026-07-26).
  Device-verified traps that code review cannot catch — `delete` after `send` is a silent no-op, a
  compose window is a recipient-less `outgoing message`, writing `content` on a forward destroys the
  attachments, and Mail's Drafts autosave lands ~15s late so a 3-second check reports a clean
  mailbox and lies — and a move out of a Gmail label reads `ok`, then the copy is back ~2 min later
  (observe Gmail writes at +2 and +15 min). Verify every Mail write **by running it and inspecting
  the resulting message**; three reviews and a green suite once passed a forward that delivered
  empty mail and ate 7 attachments.
- **Our count disagrees with Mail's own counter? Our query is wrong until proven otherwise** (2026-10-06).
  Compare against `mailboxes.total_count` / `unread_count` (#251, #287): a Gmail INBOX
  mismatch was once filed as stale counters, and Mail's counter was right. Exception: a Gmail
  label made by `create_mailbox` has no `source`, and its counter stays 0 — compare against an
  AppleScript count there (#291).
- **Hermetic tests** (2026-11-05). A test never touches a real home path. `tests/conftest.py` (`_isolated_state`)
  patches every home-anchored constant and sets `MACOS_APPS_MCP_SOCKET`; add a new one there. A test
  that reached `uninstall_agent()` once unlinked the live daemon's socket.
- **The repo is not the daemon** (2026-07-29). Merging changes nothing about what Claude Code sees until the `.app`
  is rebuilt and reinstalled. A release includes the three-file version bump and the mandatory `doctor().version`
  proof (`docs/RELEASING.md`).
- **Notarization** (2026-11-04). Before requesting notarization credentials, check the existing `notary` profile with
  `notarytool history`; an account email is not its profile name. See
  [docs/DAEMON.md](docs/DAEMON.md#notarization-profile).
- **Bugs before features** (owner, 2026-10-11): an open bug or error goes on the GSD roadmap in an
  inserted phase ahead of the next feature phase (precedent: Phase 03.1).
- **Public repo** (2026-11-04). Public notes omit private client identifiers and absolute home-directory links;
  local evidence addresses stay outside Git.

## Architecture invariants

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
  `doctor._AUTOMATION_APPS` and its bundle id to `doctor._AUTOMATION_BUNDLES` so `doctor`
  checks it (a pin test fails when they disagree); it must not reach into another adapter. This is
  what lets a module later harden into a `lyfe` native data-plane adapter unchanged.
- **The shim↔daemon hop has NO read deadline** (`daemon._uds_client_factory`, `Timeout(None,
  connect=10.0)`). A call's duration is the daemon's business — a bulk Mail pass runs HOURS —
  and it is a local socket with no network to time out on. Per-operation limits belong in the
  adapter, which knows what it asked for. Never "fix" a hang by adding a timeout here: that is
  #170, where httpx's own 5s default silently killed every destructive Mail call over ~5s. A
  dead stream must ANSWER: MCP 2 reports abandoned streams, and the shim middleware adds
  the uncertain-outcome warning. Never replay a destructive request.
- **MCP 2 / FastMCP 4 public interfaces only.** Use httpx2 on the local transport, unlimited
  SSE event size, and public protocol-era mirroring. The upstream HTTP request-body limit
  is 4 MiB including its envelope. Shim IDs travel in an advisory header, never model extras.
- **Bundle all locked runtime dependencies.** MCP 2 imports cryptography for request-state encryption even without auth; do not prune it.
- **Three capability tiers, all gated at registration** (a gated-off tool is *absent*, never
  registered-and-erroring): read → write (`@_write_tool`/`@_additive_tool`, skipped by
  `MACOS_APPS_READ_ONLY`) → **outbound** (`@_send_tool("<adapter>")`, registered only when
  `MACOS_APPS_ALLOW_SEND` names that adapter; `READ_ONLY` wins unconditionally). Outbound acts off
  this machine, so it carries `openWorldHint` and defaults `dry_run=True` — and its dry-run path must
  make **no native call at all** (building a Mail `outgoing message` can strand an autosaved draft).
  A new send tool goes through `_send_tool` or `tests/test_tool_annotations.py` fails.
- **Off macOS the server loads and lists its tools; every tool that needs the Mac refuses.** A
  macOS-only import at module load sits under `if sys.platform == "darwin":` (else the name is
  `None`), never a try/except, and a native door refuses through `runtime.require_macos()`. The
  `linux-tools-list` CI job fails on a load-time macOS import on the server's import path, and
  Glama lists the server only after a Linux build test reads tools/list.

## Docs

| Code path | Doc path | What drifts |
|---|---|---|
| The whole design | [DESIGN.md](DESIGN.md) | The design and its rationale |
| `macos_apps_mcp/adapters/` (Mail) | [docs/mail-applescript-facts.md](docs/mail-applescript-facts.md) | Device-verified Mail behaviour |
| `macos_apps_mcp/daemon.py`, `packaging/`, `scripts/build_app.sh` | [docs/DAEMON.md](docs/DAEMON.md) | Install modes, signing, notarization, the launchd agent |
| `pyproject.toml` version, `server.json`, `CHANGELOG.md`, `.github/workflows/publish.yml` | [docs/RELEASING.md](docs/RELEASING.md) | The release procedure and the device suite after a deploy |
| `macos_apps_mcp/server.py` tools | [README.md](README.md) § Tools | The tool list and its tiers |
| The modules and their seams | `.planning/architecture/` | The architecture notes, written by the handbook-align-pages skill |
| Listings and launch | [docs/PROMOTION.md](docs/PROMOTION.md) | A session on promotion work starts at its "Next steps — start here" section (2026-10-26) |
| — | [docs/landscape.md](docs/landscape.md) | The prior-art survey and shipped history, not a plan |

## Life cockpit

Tracked in the life-cockpit vault under `#personal` (tracker: `elfensky/macos-apps-mcp`). The cockpit is the
control plane (what to work on); this repo is where the work happens. Report progress by
opening/closing issues and PRs as usual — the cockpit pulls from the tracker on its next
`/sync`. Nothing to update in the vault; don't mirror cockpit state (milestones, due dates) here.
GSD projects: after `/gsd-new-project`, run `/cockpit-gsd-profile` once in this repo before planning the first slice.
Roadmap: this repo owns its roadmap. `.planning/ROADMAP.md` (GSD) is the one roadmap file here; no second
roadmap file lives in this repo.
Pages: /handbook-align-pages in this repo updates the architecture notes and publishes the roadmap and architecture pages (~/vault/knowledge/developer/stack/page-kit.md).

Display: the roadmap at https://projects.lav.ren/macos-apps-mcp/roadmap/ and the architecture at
https://projects.lav.ren/macos-apps-mcp/architecture/. Republish only on request, through the handbook-align-pages
skill.

<!-- A new convention for this repo goes here in the same session, never into per-machine agent memory. -->
