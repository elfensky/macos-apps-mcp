# mac-mcp → macos-apps-mcp — project rename

**Status:** approved (design) · **Date:** 2026-07-14 · **Owner:** elfensky

Rename the project `mac-mcp → macos-apps-mcp` end-to-end. Two problems force it: the name
**collides** (multiple unrelated `mac-mcp` repos exist on GitHub), and it **misreads** — a
`mac(os)-mcp`-shaped name signals macOS *control* (mouse/keyboard/UI automation), not native
*apps* data. The MCP registry confirms the misread in the wild: `io.github.Jeomon/macos-mcp` is
"desktop automation via the Accessibility API" and `io.github.cyanheads/macos-mcp-server` is
"control settings, windows, screenshots". The `apps` token is the differentiator.

This is the second application of the rebrand playbook from
[2026-06-29-mac-mcp-rebrand-release-design.md](2026-06-29-mac-mcp-rebrand-release-design.md)
(`apple-mcp → mac-mcp`); its principles are inherited unchanged.

## How the name was chosen

34 candidates across four directions (Mac-wordplay, Apple-lore, role-metaphor, plain
descriptive), each checked for exact-name availability on PyPI and GitHub. Apple-lore was
eliminated (collisions, needs insider knowledge, not googleable); role-metaphor parked;
descriptive won over wordplay because MCP servers are conventionally descriptive-named —
the name should *be* the registry search query. Runners-up, all verified free on
2026-07-14: `macsuite-mcp`, `mackit-mcp`, `macos-native-mcp` (descriptive);
`macaw-mcp` (wordplay track winner, recorded here in case a brandable name is ever wanted).

**Availability of `macos-apps-mcp`, verified 2026-07-14:**

- PyPI: 404 (free). TestPyPI: 404 (free). PyPI treats `-`/`_` as equivalent, so the wheel
  name `macos_apps_mcp` is the same claim.
- GitHub: no exact-name repo (search API, `in:name`, case-insensitive).
- Official MCP registry: no similar entry; registry names are owner-namespaced
  (`io.github.elfensky/macos-apps-mcp`) so the slot cannot be squatted.
- Old name status: `mac-mcp` was **never published to production PyPI** (404) — zero public
  install-base to migrate. TestPyPI has `mac-mcp` artifacts (200); they orphan harmlessly.

## Decisions (locked)

| Axis | Decision |
|------|----------|
| New name | `macos-apps-mcp` everywhere: PyPI distribution, GitHub repo, console script |
| GitHub repo | `elfensky/mac-mcp` → `elfensky/macos-apps-mcp` (`gh repo rename`; old URLs and remotes auto-redirect) |
| Code rename depth | **Full** (same as June): package `mac_mcp/` → `macos_apps_mcp/`, every import, the console script, `FastMCP("mac-mcp")` → `FastMCP("macos-apps-mcp")` |
| Env var | `MAC_MCP_READ_ONLY` → `MACOS_APPS_READ_ONLY` (the only env var in the tree); **no** backward-compat alias (zero public users pre-PyPI — same YAGNI as June) |
| README config key | `"macos-apps"` — ecosystem standard is name-minus-`-mcp` (`playwright-mcp`→`"playwright"`, `chrome-devtools-mcp`→`"chrome-devtools"`, GitHub→`"github"`); tools read `mcp__macos-apps__events` |
| Version | `0.5.0` → `0.6.0` (rename is notable; pre-1.0 minor bump — same rule as June) |
| PyPI claim | Names are claimed by **first actual upload**, not by pending publishers — so release `0.6.0` promptly after the rename lands |
| Behavior | **None changes.** No tool renames (tools are already unprefixed: `events`, `mail`, …), no adapter changes |

## The inherited hazard rule: targeted rename, not global

Same rule as June, same reason. `CREDITS.md` and `CHANGELOG.md` reference third-party
projects (`supermemoryai/apple-mcp`, `griches/apple-mcp`, …) and our own past names; a
global replace would corrupt attribution and rewrite history.

- Rename only references to **our** project as it exists now (package, binary, server name,
  repo URL, prose self-references).
- Third-party project names and their GitHub URLs stay **verbatim**.
- `CHANGELOG.md` past entries are immutable — they were accurate when written. The rename is
  a **new** `0.6.0` entry, not an edit of the past.
- Dated documents under `docs/superpowers/` (specs, plans) are historical records — untouched.
- `NAMING.md` (untracked brainstorm scratch) is removed; this spec is the decision record.

Every touched file is reviewed by hand against this rule — no unattended global replace.

## Migration surface (measured 2026-07-14)

`mac-mcp|mac_mcp|MAC_MCP` appears in **41 files** (including untracked `NAMING.md` and the
historical docs that stay untouched). The live surface:

- **Package:** `mac_mcp/` — `__init__.py`, `__main__.py`, `server.py`, `runtime.py`,
  `contracts.py`, `doctor.py`, `adapters/` modules.
- **Tests:** 17 `tests/test_*.py` files import `mac_mcp` (heaviest: `test_integration.py` 85,
  `test_mail.py` 28, `test_notes.py` 17).
- **Docs:** `README.md`, `CLAUDE.md`, `DESIGN.md`, `CONTRIBUTING.md`, `CREDITS.md`,
  `docs/parity-checklist.md`, `docs/projection-contract.md`, plus a new
  `CHANGELOG.md` entry. `CLAUDE.md`'s life-cockpit tracker line flips to
  `elfensky/macos-apps-mcp`.
- **Build/CI:** `pyproject.toml` (`[project] name`, `[project.scripts]`,
  `[tool.hatch.build.targets.wheel]`), `.github/workflows/publish.yml:35` (project URLs),
  `.github/workflows/ci.yml:6` (comment only).
- **Known anchors:** `mac_mcp/server.py:42` `mcp = FastMCP("mac-mcp")`; the
  `MAC_MCP_READ_ONLY` lookup at `server.py:63-64`; `uv.lock` regenerates via `uv sync`
  (project name is in it).

## Ops checklist (ordered, after the PR merges to `develop`)

1. `gh repo rename macos-apps-mcp` — GitHub redirects the old URL and remotes.
2. Update the local remote URL (redirect works, but be explicit) and optionally rename the
   local folder `~/Developer/mac-mcp` — operator's choice, nothing depends on it.
3. **TestPyPI trusted publisher** — re-register for project `macos-apps-mcp` +
   repo `elfensky/macos-apps-mcp` + `publish.yml` + environment `pypi` (the binding names all
   three; the old `mac-mcp` TestPyPI project orphans harmlessly).
4. **Production PyPI** — add a pending publisher for `macos-apps-mcp`, then release `0.6.0`
   (tag → `workflow_dispatch` target `pypi`, per the June release design) to actually claim
   the name.
5. Update operator MCP client configs: server key `macos-apps`, new command/args, new env var
   names. (The old `MAC_MCP_*` vars are simply ignored after the rename — configs must move.)
6. life-cockpit: tracker id changes to `elfensky/macos-apps-mcp`; the vault picks it up on its
   next `/sync` — nothing to do in this repo.

## Verification

- `uv sync && uv run pytest && uv run ruff check . && uv run ruff format --check .`
- `uv run macos-apps-mcp` starts; `python -m macos_apps_mcp` starts.
- Grep gate: `rg -l 'mac_mcp|mac-mcp|MAC_MCP'` returns **only** the historical
  `docs/superpowers/` documents, `CHANGELOG.md`/`CREDITS.md` third-party/history mentions,
  and this spec.

## Not in scope

Behavior changes of any kind; MCP registry publication (`io.github.elfensky/macos-apps-mcp`
— a separate later decision); back-compat env aliases; rewriting historical docs.
