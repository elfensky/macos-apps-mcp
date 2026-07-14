# mac-mcp → macos-apps-mcp Rename Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the project `mac-mcp → macos-apps-mcp` end-to-end (package, distribution, repo, server name, env var, docs) and release `0.6.0` under the new name.

**Architecture:** Two rename commits on the existing feature branch — (1) the Python package + packaging, (2) targeted docs + workflows — then a PR into `develop`, then post-merge ops: GitHub repo rename, trusted-publisher re-registration, and the standard commit-tree release onto `main` (push → TestPyPI, dispatch → PyPI). Rename is behavior-preserving: the existing test suite plus grep gates are the tests. Spec: [2026-07-14-rename-macos-apps-mcp-design.md](../specs/2026-07-14-rename-macos-apps-mcp-design.md).

**Tech Stack:** Python ≥3.11, FastMCP 2.0, PyObjC/EventKit (macOS-only), `uv`, hatchling, ruff, pytest, GitHub Actions, PyPI Trusted Publishing (OIDC).

## Global Constraints

- Work on branch `feature/rename-macos-apps-mcp` (exists, off `develop`, carries the spec commit). PR back into `develop` with **rebase-and-merge**. `main` is release-only — touched only via the Task 4 release push, never committed to directly.
- Token map, applied everywhere ours: `mac_mcp` → `macos_apps_mcp`, `mac-mcp` → `macos-apps-mcp`, `MAC_MCP` → `MACOS_APPS`. (The new strings contain none of the old tokens as substrings, so post-rename greps for old tokens are sound.)
- The only env var is `MAC_MCP_READ_ONLY` → **`MACOS_APPS_READ_ONLY`**. No backward-compat alias (never published to production PyPI — zero public users).
- Version: `0.5.0` → `0.6.0`.
- **Protected — NEVER rename** (frozen history / third-party):
  - Every dated `## [x.y.z]` entry in `CHANGELOG.md` (incl. the 0.2.0 entry documenting `apple-mcp → mac-mcp`). Only the intro line changes; the rename is recorded as a NEW `0.6.0` entry.
  - Everything under `docs/superpowers/` except checkbox ticks in THIS plan file.
  - Third-party names `supermemoryai/apple-mcp`, `griches/apple-mcp`, `Dhravya/apple-mcp`, `patrickfreyer/apple-mail-mcp` in `CREDITS.md`/`DESIGN.md` — note these contain none of our three tokens, so the seds below cannot touch them; the verify steps prove it.
- Verification gate after every code/packaging change: `uv run pytest && uv run ruff check . && uv run ruff format --check .` (macOS host — PyObjC won't sync on Linux).
- This environment routes shell commands through the `rtk` proxy, which can serve condensed or cached output. When a gate depends on byte-exact output (greps, diffs, status), prefix the command with `rtk proxy ` (e.g. `rtk proxy git status --short`). A cached `rg` served stale results once during planning — trust `exit=` codes and re-run suspicious-looking empty results through `rtk proxy`.

---

### Task 1: Rename the Python package, code identifiers, and distribution

**Files:**
- Rename: `mac_mcp/` → `macos_apps_mcp/` (directory, via `git mv`)
- Modify: every `*.py` under `macos_apps_mcp/` and `tests/`; `pyproject.toml`
- Regenerate: `uv.lock`

**Interfaces:**
- Consumes: current names (`mac_mcp` package, `mac-mcp` script/server, `MAC_MCP_READ_ONLY`).
- Produces: import root `macos_apps_mcp`; console script `macos-apps-mcp` (target `macos_apps_mcp:main`); `FastMCP("macos-apps-mcp")`; env var `MACOS_APPS_READ_ONLY`; distribution `macos-apps-mcp` v`0.6.0`. Tasks 2–4 and all docs reference exactly these.

Every `mac_mcp`/`mac-mcp`/`MAC_MCP` token in `.py` files and `pyproject.toml` is **ours** (no third-party dependency uses those names), so a blanket replace is safe there. Protected strings live only in Markdown (Task 2) — and contain none of our tokens anyway.

- [ ] **Step 1: Preflight — right branch, clean tree, green baseline**

```bash
rtk proxy git rev-parse --abbrev-ref HEAD   # expect: feature/rename-macos-apps-mcp
rtk proxy git status --short                # expect: only untracked NAMING.md
uv run pytest && uv run ruff check . && uv run ruff format --check .
```
Expected: all pass — the green state the rename must preserve.

- [ ] **Step 2: Rename the package directory**

```bash
git mv mac_mcp macos_apps_mcp
```

- [ ] **Step 3: Replace identifiers in all Python sources + pyproject**

```bash
grep -rIl --include='*.py' -E 'mac_mcp|mac-mcp|MAC_MCP' macos_apps_mcp tests \
  | xargs sed -i '' -e 's/mac_mcp/macos_apps_mcp/g' -e 's/mac-mcp/macos-apps-mcp/g' -e 's/MAC_MCP/MACOS_APPS/g'
sed -i '' -e 's/mac_mcp/macos_apps_mcp/g' -e 's/mac-mcp/macos-apps-mcp/g' pyproject.toml
```

This updates, among others:
- `macos_apps_mcp/server.py:42` → `mcp = FastMCP("macos-apps-mcp")`
- `server.py:63-64` → `MACOS_APPS_READ_ONLY` lookup (+ docstring at line 3)
- `server.py:162-163` → ping tool returns `"macos-apps-mcp ok"` (test_server asserts this string — the same sed updates the test)
- `runtime.py:806` → `logging.getLogger("macos_apps_mcp")` (+ TCC/consent error prose at lines 183, 200, 378-380, 431-434, 587-589)
- `doctor.py:106,163,228-229` → "restart macos-apps-mcp" prose
- `adapters/mail.py:404,448` → tempfile prefixes `macos-apps-mcp-draft-` / `macos-apps-mcp-reply-`
- `adapters/shortcuts.py:141` → tempfile prefix `macos-apps-mcp-shortcut-`
- `__init__.py` / `__main__.py` docstrings (`python -m macos_apps_mcp`)
- all `from macos_apps_mcp... import` lines across 17 `tests/*.py` files, and `MACOS_APPS_READ_ONLY` in `test_server.py` (3×) / `test_tool_annotations.py` (1×)
- `pyproject.toml:2` name, `:41` script line, `:57` wheel packages, `:60` comment

- [ ] **Step 4: Verify nothing in Python or pyproject still says the old name**

```bash
rtk proxy grep -rIn --include='*.py' -E 'mac_mcp|mac-mcp|MAC_MCP' macos_apps_mcp tests pyproject.toml; echo "exit=$?"
```
Expected: no matches, `exit=1`.

- [ ] **Step 5: Set the new version**

In `pyproject.toml`, change:

```toml
version = "0.5.0"
```
to
```toml
version = "0.6.0"
```

(The name/script/wheel lines were already rewritten by Step 3; confirm they read `name = "macos-apps-mcp"`, `macos-apps-mcp = "macos_apps_mcp:main"`, `packages = ["macos_apps_mcp"]`.)

- [ ] **Step 6: Re-sync to regenerate the lockfile and editable install**

```bash
uv sync
rtk proxy grep -n 'name = "macos-apps-mcp"' uv.lock | head -2
ls .venv/bin/ | grep macos-apps-mcp
```
Expected: sync succeeds; `uv.lock` lists `name = "macos-apps-mcp"`; console script `macos-apps-mcp` exists in the venv.

- [ ] **Step 7: Build and verify renamed artifacts**

```bash
uv build && ls dist/ | grep macos_apps_mcp-0.6.0
```
Expected: `macos_apps_mcp-0.6.0-py3-none-any.whl` and `macos_apps_mcp-0.6.0.tar.gz`.

- [ ] **Step 8: Run the full gate + import smoke**

```bash
uv run pytest && uv run ruff check . && uv run ruff format --check .
uv run python -c "from macos_apps_mcp import main; print('entry ok')"
uv run python -c "import importlib.util as u; print('module -m ok' if u.find_spec('macos_apps_mcp.__main__') else 'MISSING __main__')"
```
Expected: all pass; `entry ok`; `module -m ok` (covers the README's `python -m macos_apps_mcp` launch path without booting the blocking stdio server — booting is smoke-tested from TestPyPI in Task 4.)

- [ ] **Step 9: Commit**

```bash
git add -A -- ':!NAMING.md'
git commit -m "refactor: rename package mac_mcp -> macos_apps_mcp; distribution macos-apps-mcp 0.6.0

Server name, console script, MACOS_APPS_READ_ONLY env var, imports, lockfile.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Targeted documentation + workflow rename

**Files:**
- Modify: `README.md`, `CLAUDE.md`, `DESIGN.md`, `CONTRIBUTING.md`, `CREDITS.md`, `docs/parity-checklist.md`, `docs/projection-contract.md`, `.github/workflows/publish.yml`, `.github/workflows/ci.yml`, `CHANGELOG.md` (intro line + new entry only)
- Delete: `NAMING.md` (untracked brainstorm scratch — plain `rm`, no git involvement)

**Interfaces:**
- Consumes: names produced by Task 1 (`macos_apps_mcp`, `macos-apps-mcp`, `MACOS_APPS_READ_ONLY`), and the design's MCP config key **`"macos-apps"`**.
- Produces: docs that a fresh reader can follow end-to-end under the new name.

The 9 sed-safe files contain only our-project references; the protected third-party `apple-*` strings (in `CREDITS.md`, `DESIGN.md`) contain none of our three tokens, so the sed cannot corrupt them. `CHANGELOG.md` is the one file where our tokens appear in protected dated history — hand-edit only.

- [ ] **Step 1: Blanket-rename the safe files**

```bash
for f in README.md CONTRIBUTING.md CLAUDE.md DESIGN.md CREDITS.md \
         docs/parity-checklist.md docs/projection-contract.md \
         .github/workflows/publish.yml .github/workflows/ci.yml; do
  sed -i '' -e 's/mac_mcp/macos_apps_mcp/g' -e 's/mac-mcp/macos-apps-mcp/g' -e 's/MAC_MCP/MACOS_APPS/g' "$f"
done
```

Notable results: README title/clone URL/env-var docs; `CLAUDE.md` paths + `uv run macos-apps-mcp` + tracker line `elfensky/macos-apps-mcp`; `DESIGN.md:24-25` config + `:44` tree diagram + `:118` env var + `:178` tracker; `publish.yml:35` both project URLs; `ci.yml:6` comment; `docs/parity-checklist.md:1` title becomes "apple-events → macos-apps-mcp parity checklist" (correct — `apple-events` is the third-party predecessor, untouched by our tokens).

- [ ] **Step 2: Hand-fix the README MCP config blocks to use the `"macos-apps"` key**

Step 1's sed leaves the config key as `"macos-apps-mcp"`; the design locks the key to `"macos-apps"` (ecosystem standard: name minus `-mcp`). In `README.md`, make the from-source block read exactly:

```json
{
  "mcpServers": {
    "macos-apps": {
      "command": "/absolute/path/to/macos-apps-mcp/.venv/bin/python",
      "args": ["-m", "macos_apps_mcp"]
    }
  }
}
```

and the PyPI line read: `` `uvx macos-apps-mcp` runs the server with no clone, and the MCP config becomes `"command": "uvx", "args": ["macos-apps-mcp"]` (same `"macos-apps"` key). ``

- [ ] **Step 3: Hand-edit CHANGELOG.md — intro line + new 0.6.0 entry, history untouched**

Change the intro sentence (line ~3):
`All notable changes to mac-mcp are documented here.` → `All notable changes to macos-apps-mcp are documented here.`

Prepend this entry below the intro, above `## [0.5.0]`:

```markdown
## [0.6.0] - 2026-07-14

### Changed

- **Renamed `mac-mcp` → `macos-apps-mcp`** across the board: the PyPI distribution,
  the GitHub repo (`elfensky/macos-apps-mcp`), the import package (`macos_apps_mcp`),
  the console script (`macos-apps-mcp`), and the FastMCP server name. Two reasons:
  `mac-mcp` collides with unrelated projects on GitHub, and `mac(os)-mcp`-shaped
  names read as macOS *control* (mouse/keyboard automation) — this server is native
  *apps* data. The read-only guard env var is now **`MACOS_APPS_READ_ONLY`** (was
  `MAC_MCP_READ_ONLY`) — no backward-compat alias; `mac-mcp` was never published to
  production PyPI, so there are no public installs to migrate. Suggested MCP config
  key: `"macos-apps"`. Decision record:
  `docs/superpowers/specs/2026-07-14-rename-macos-apps-mcp-design.md`.
```

Every existing dated `## [x.y.z]` entry stays byte-identical — including the 0.2.0 entry that documents the `apple-mcp → mac-mcp` rename.

- [ ] **Step 4: Remove the brainstorm scratch file**

```bash
rm NAMING.md
```

- [ ] **Step 5: Verify protected strings survived and nothing else remains**

```bash
rtk proxy grep -c -E 'supermemoryai/apple-mcp|griches/apple-mcp|Dhravya/apple-mcp|patrickfreyer/apple-mail-mcp' CREDITS.md   # expect >= 3
rtk proxy grep -n 'Renamed .apple-mcp. → .mac-mcp.' CHANGELOG.md | head -2   # the 0.2.0 history entry, byte-intact
rtk proxy rg -n 'mac_mcp|mac-mcp|MAC_MCP' --glob '!docs/superpowers/**' --glob '!CHANGELOG.md'; echo "exit=$?"
```
Expected: last command prints nothing, `exit=1`. Old tokens survive **only** in `CHANGELOG.md` dated entries (incl. the new 0.6.0 entry's own backticked `mac-mcp` mentions) and the frozen `docs/superpowers/` records. Then confirm those docs really are untouched:

```bash
rtk proxy git status --short docs/superpowers/   # expect: only this plan file modified (checkboxes), nothing else
```

- [ ] **Step 6: Run the gate (cheap insurance — docs shouldn't affect it)**

```bash
uv run pytest && uv run ruff check . && uv run ruff format --check .
```
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add README.md CONTRIBUTING.md CLAUDE.md DESIGN.md CREDITS.md CHANGELOG.md \
        docs/parity-checklist.md docs/projection-contract.md .github/workflows/
git commit -m "docs: rename mac-mcp -> macos-apps-mcp (targeted; history and third-party refs preserved)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: PR into develop

**Files:** none (git/GitHub only)

**Interfaces:**
- Consumes: the two rename commits + the spec commit on `feature/rename-macos-apps-mcp`.
- Produces: rename merged into `develop` (rebase-and-merge, linear history).

- [ ] **Step 1: Push the branch and open the PR**

```bash
git push -u origin feature/rename-macos-apps-mcp
gh pr create --base develop --title "Rename mac-mcp → macos-apps-mcp (0.6.0)" --body "$(cat <<'EOF'
## Why

`mac-mcp` collides with several unrelated servers on GitHub, and `mac(os)-mcp`-shaped names read as macOS *control* (mouse/keyboard automation) — the MCP registry's existing `macos-mcp` entries are exactly that. This server is native *apps* data; the name now says so. Decision record: `docs/superpowers/specs/2026-07-14-rename-macos-apps-mcp-design.md`.

## What

- Package `mac_mcp/` → `macos_apps_mcp/`, console script + distribution `macos-apps-mcp` **0.6.0**, `FastMCP("macos-apps-mcp")`
- Env var `MAC_MCP_READ_ONLY` → `MACOS_APPS_READ_ONLY` (no compat alias — never published to prod PyPI)
- Docs renamed **targeted, not global**: CHANGELOG dated entries, `docs/superpowers/` records, and third-party `apple-*` attributions stay byte-identical
- Suggested MCP config key: `"macos-apps"`

Post-merge ops (repo rename, trusted publishers, 0.6.0 release) follow the plan in `docs/superpowers/plans/2026-07-14-rename-macos-apps-mcp.md`.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 2: Wait for CI green**

```bash
gh pr checks --watch
```
Expected: CI (macos-latest, `uv sync --locked` + gate) passes — the Task 1 relock keeps `--locked` honest.

- [ ] **Step 3: STOP — user merges**

Ask the user to approve, then:

```bash
gh pr merge --rebase --delete-branch
```

---

### Task 4: Post-merge ops — repo rename, publishers, 0.6.0 release

**Files:** none (GitHub/PyPI/web UI + release plumbing)

**Interfaces:**
- Consumes: renamed code on `develop`; `publish.yml` (push-to-main → TestPyPI, dispatch → PyPI); the `pypi` environment.
- Produces: repo `elfensky/macos-apps-mcp`; `macos-apps-mcp` claimed on TestPyPI + PyPI; `v0.6.0` released; operator configs updated.

**Order matters:** the repo rename must precede the publisher registrations (Trusted Publishing matches the OIDC token's `repository` claim), and both must precede the `main` push (which auto-publishes to TestPyPI).

- [ ] **Step 1: Rename the GitHub repo and repoint the remote**

```bash
gh repo rename macos-apps-mcp --repo elfensky/mac-mcp --yes
git remote set-url origin https://github.com/elfensky/macos-apps-mcp.git
rtk proxy git remote -v   # confirm origin -> elfensky/macos-apps-mcp
```
(GitHub auto-redirects the old URL. Renaming the local folder `~/Developer/mac-mcp` is optional and the operator's call — nothing in the toolchain depends on it.)

- [ ] **Step 2: MANUAL (web UI) — register pending publishers under the new identity**

1. **TestPyPI** — test.pypi.org → Account → Publishing → *Add a pending publisher*: project `macos-apps-mcp`, owner `elfensky`, repository `macos-apps-mcp`, workflow `publish.yml`, environment `pypi`. (The old TestPyPI `mac-mcp` project orphans harmlessly; its publisher binding is dead after the repo rename.)
2. **PyPI** — pypi.org → same fields exactly. Also delete the stale pending publisher for `mac-mcp` if one is still registered (it was never consumed).

Without these, the publish steps fail with an OIDC trust error.

- [ ] **Step 3: Cut the release commit onto `main` (commit-tree, per the house release flow)**

```bash
git checkout develop && git pull
PREV_MAIN=$(git rev-parse origin/main)
DEV_TIP=$(git rev-parse develop)
TREE=$(git rev-parse develop^{tree})
COMMIT=$(git commit-tree "$TREE" -p "$PREV_MAIN" -p "$DEV_TIP" -m "Release v0.6.0")
[ "$(git rev-parse ${COMMIT}^{tree})" = "$TREE" ] && echo "tree ok" || echo "tree mismatch — ABORT"
git push origin "$COMMIT":main
```
Expected: `tree ok`; push triggers the `Publish` workflow (TestPyPI leg).

- [ ] **Step 4: Watch the TestPyPI publish, then smoke-test the artifact**

```bash
gh run watch
timeout 6 uvx --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ --from macos-apps-mcp macos-apps-mcp; \
  [ $? -eq 124 ] && echo "booted ok (timed out as expected)" || echo "CHECK: exited early — inspect output above"
```
Expected: workflow green; `booted ok` — the server is a blocking stdio process, so a clean 6-second timeout means it imported and started. (If `timeout` is missing on this Mac, use `gtimeout` from coreutils.)

- [ ] **Step 5: Promote to production PyPI — this is the claim on the name**

```bash
gh workflow run publish.yml --ref main -f target=pypi
gh run watch
timeout 6 uvx macos-apps-mcp@0.6.0; [ $? -eq 124 ] && echo "prod boot ok" || echo "CHECK output above"
```
Expected: `Publish to PyPI` step green; https://pypi.org/project/macos-apps-mcp/ exists; prod boot ok.

- [ ] **Step 6: Tag + GitHub release + local hygiene**

```bash
COMMIT=${COMMIT:-$(git fetch -q origin && git rev-parse origin/main)}   # re-derive if running in a fresh shell
git tag -a v0.6.0 "$COMMIT" -m "Release v0.6.0"
git push origin v0.6.0
gh release create v0.6.0 --title "v0.6.0 — macos-apps-mcp" --notes "Renamed mac-mcp → macos-apps-mcp (collision + control-vs-apps misread). New env var MACOS_APPS_READ_ONLY, config key \"macos-apps\". First production PyPI release under the new name: \`uvx macos-apps-mcp\`. See CHANGELOG."
git fetch origin && git branch -f main origin/main
```

- [ ] **Step 7: Update operator configs (the human's own machines)**

Point every MCP client config at the new identity — key `macos-apps`, new command/args, new env var name:

```json
{
  "mcpServers": {
    "macos-apps": {
      "command": "/absolute/path/to/macos-apps-mcp/.venv/bin/python",
      "args": ["-m", "macos_apps_mcp"]
    }
  }
}
```

- Any `MAC_MCP_READ_ONLY` in configs → `MACOS_APPS_READ_ONLY` (the old var is silently ignored after the rename — this is the one step that can't be skipped safely).
- macOS TCC permissions survive: they're granted to the *launching* app (Terminal/Claude/etc.), not the venv path. If anything looks off, run the server's `doctor` tool.
- life-cockpit: the tracker id is now `elfensky/macos-apps-mcp`; the vault picks it up on its next `/sync` — nothing to do in this repo.
