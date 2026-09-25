# Contributing to macos-apps-mcp

## Setup
```sh
uv sync
```

## Tests
```sh
uv run pytest                 # unit tests — no macOS access needed; this is what CI runs
uv run pytest -m integration  # real EventKit / TCC — this Mac only, grant access when prompted; NEVER in CI
```

## Run the server
```sh
uv run macos-apps-mcp          # stdio transport
```

## Lint & format
```sh
uv run ruff check .          # lint
uv run ruff check . --fix    # lint with autofix
uv run ruff format .         # format
uv run ruff format --check . # check formatting, no writes — what CI runs
```
ruff config lives in `pyproject.toml` (line-length 88; rules `E, F, I, UP, B, SIM`) — the same setup
as the sibling repos. Before committing, run the full chain and report real output rather than
suppressing failures:
```sh
uv run pytest && uv run ruff check . && uv run ruff format --check .
```
Commits follow conventional-commit prefixes (`feat:`, `fix:`, `docs:`, `test:`, `chore:`, `refactor:`).

## Branching & releases

- **`develop`** is the trunk — all history lives here. Branch features off it
  (`feature/<desc>`, `refactor/<desc>`) in a worktree under `.worktrees/` — never in
  the main checkout, see [AGENTS.md](AGENTS.md) ("Worktrees — one lane, always") —
  and PR back with **rebase-and-merge** so `develop` stays linear.
- **`main`** is release-only: one merge commit per release, its tree equal to
  `develop`'s release-point tree and its second parent the `develop` commit it was
  cut from. Never commit directly to `main`. `git log --first-parent main` shows the
  release timeline. Releases are annotated tags on `main`.
- **Cut a release:** bump the version + dated `CHANGELOG.md` section by PR to
  `develop`, then merge a PR `develop` → `main` with a merge commit, tag that commit
  `vX.Y.Z` and push the tag. The merge to `main` triggers the TestPyPI publish.
  Promote to PyPI via the `publish.yml` `workflow_dispatch` (`target=pypi`). Full
  procedure: [docs/RELEASING.md](docs/RELEASING.md).

## Non-negotiable invariants
- **All EventKit / native access goes through `runtime.run_native`** (one serialized worker, `max_workers=1`). Never widen the executor; never touch `EKEventStore` from another thread.
- **The `EKEventStore` is owned by `runtime`, not by an adapter.** One adapter must never import or reach into another.
- **Reads return `Pointer`s** (`get_pointers(query) -> list[Pointer]`); **writes take typed dataclasses** (`ReminderData`, `CalendarEventData`). Tools in `server.py` are thin dispatch only.
- **Pointers, not payload** — `id` + one-line `summary` + `deeplink`, never full bodies.
- One adapter module per app under `macos_apps_mcp/adapters/`. Adding an app = add a module + mount its tools in `server.py`.

## Compatibility
Latest stable macOS only (rolling). We use the macOS 14+ full-access APIs; we do not carry back-compat shims.
