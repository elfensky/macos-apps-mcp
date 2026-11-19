---
phase: quick-261025-vuv
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - pyproject.toml
  - uv.lock
  - tests/test_packaging.py
  - macos_apps_mcp/errors.py
  - macos_apps_mcp/runtime.py
  - macos_apps_mcp/eventkit.py
  - macos_apps_mcp/doctor.py
  - macos_apps_mcp/adapters/calendar.py
  - macos_apps_mcp/adapters/reminders.py
  - macos_apps_mcp/server.py
  - tests/test_runtime.py
  - tests/test_off_macos.py
  - tests/test_tools_list_anywhere.py
  - .github/workflows/ci.yml
  - CHANGELOG.md
  - AGENTS.md
autonomous: true
requirements: [OWNER-LINUX-DEPS, OWNER-LINUX-SEAM, OWNER-LINUX-CI]

estimate:
  tokens: 100000
  raw_tokens: 100000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "In a python:3.12-slim Linux container, installing the built wheel with its dependencies installs no pyobjc-* package and no osxphotos, `python -c \"import macos_apps_mcp.server\"` exits 0, and a stdio client of `macos-apps-mcp` gets a tools/list equal to the registered records of `registry.TOOLS` (68 with sends off at v0.15.1)"
    - "Off macOS, every tool call that needs a Mac returns an isError result whose text says `macos-apps-mcp runs only on macOS` (typed `UnsupportedPlatform`, kind `unsupported_platform`) — never an AttributeError, an import failure, or a store-not-found message; ping, now and usage still answer"
    - "Off macOS, runtime.run_native, runtime.run_osascript, runtime.tracked_run, runtime.mac_region and doctor.diagnose raise UnsupportedPlatform before any native work, and eventkit.bootstrap returns without a native call, so the stdio server starts"
    - "On macOS nothing changes: the six PyObjC imports stay eager at module load under `if sys.platform == \"darwin\":`, the synced environment (`uv pip freeze`) is byte-identical to the base, and a broken PyObjC install still fails at import (the guard is the platform, never a try/except around the import)"
    - "uv.lock changes only by the darwin markers: no package that stays in the lock changes version, and the only removed entries are the four that only non-macOS platforms reached (ansicon 1.89.0, jinxed 2.1.0, tenacity 9.2.1, tzlocal 5.4.4); `uv lock --check` passes"
    - "CI has a `linux-tools-list` job on ubuntu-latest that runs `uv sync --locked`, the import smoke and tests/test_tools_list_anywhere.py; the macOS `check` job is unchanged"
  artifacts:
    - path: pyproject.toml
      provides: "darwin markers on every macOS-only dependency"
      contains: "sys_platform == 'darwin'"
    - path: macos_apps_mcp/errors.py
      provides: "UnsupportedPlatform typed error"
      contains: "unsupported_platform"
    - path: macos_apps_mcp/runtime.py
      provides: "require_macos(), called first by run_native, tracked_run and mac_region"
      contains: "def require_macos"
    - path: macos_apps_mcp/server.py
      provides: "_guard refuses off macOS before the tool body runs"
      contains: "runtime.require_macos()"
    - path: tests/test_off_macos.py
      provides: "unit tests for every off-macOS refusal and the bootstrap skip"
      contains: "UnsupportedPlatform"
    - path: tests/test_tools_list_anywhere.py
      provides: "in-process tools/list equals the registry; the one test the Linux CI job runs"
      contains: "list_tools"
    - path: .github/workflows/ci.yml
      provides: "linux-tools-list job"
      contains: "linux-tools-list"
  key_links:
    - from: pyproject.toml
      to: "ci.yml linux-tools-list `uv sync --locked`"
      via: "darwin markers -> uv.lock resolves no PyObjC/osxphotos on Linux"
      pattern: "sys_platform == 'darwin'"
    - from: macos_apps_mcp/runtime.py require_macos
      to: "run_native / tracked_run / mac_region"
      via: "first statement of each door; run_osascript, read_via_sqlite and photos_db reach it through run_native"
      pattern: "require_macos()"
    - from: macos_apps_mcp/server.py _guard
      to: macos_apps_mcp/runtime.py require_macos
      via: "inside the existing try, so UnsupportedPlatform becomes the ToolError text"
      pattern: "runtime.require_macos()"
    - from: macos_apps_mcp/eventkit.py bootstrap
      to: macos_apps_mcp/server.py main
      via: "returns early off macOS, so mcp.run() is reached and tools/list answers"
      pattern: "sys.platform != \"darwin\""
    - from: .github/workflows/ci.yml
      to: tests/test_tools_list_anywhere.py
      via: "linux-tools-list runs only this test file plus the import smoke"
      pattern: "tests/test_tools_list_anywhere.py"
---

<objective>
The server starts and lists its tools on Linux, for Glama's build test; every native call fails loud there with one typed error.

Purpose: Glama (an MCP directory) scores a server only after a build test in a Linux container: it installs the server, starts it over stdio and reads tools/list. A scored Glama listing is required by the awesome-mcp-servers list. Today the test fails twice (measured in Docker, python:3.12-slim, linux/aarch64): (1) `pip install macos-apps-mcp` cannot install the unconditional PyObjC dependencies; (2) with the pure dependencies only, `import macos_apps_mcp.server` fails at `runtime.py` `import Foundation`. The product stays macOS-only: on Linux the goal is only "start + list tools", and any tool call returns a clear, typed error.

Output: darwin-only dependency markers and a refreshed lock (Task 1); platform-guarded imports, the `UnsupportedPlatform` refusal at every native door and at `_guard` (Task 2); a cross-platform tools/list test, a Linux CI job, a Docker proof and the Glama build spec (Task 3).

**Execution protocol (owner, binding):** run ONE task per executor turn, in order. Each task ends with its own atomic commit; then stop and return, because the owner runs a multi-AI review after every task. Work only in the lane `/Users/andrei/Developer/macos-apps-mcp/.worktrees/linux-tools-list` (branch `feat/linux-tools-list`, from origin/develop 3bf281b = v0.15.1). Never edit the main checkout. All paths below are repo-root-relative; every `<automated>` command assumes cwd = the lane root. Set `SCRATCH` to the session scratchpad directory before the first command of each task (`export SCRATCH=<scratchpad>`); temp files go there, never in the repo.

**Planner decisions (Claude's discretion, each with its evidence):**
- Guard shape per owner: `if sys.platform == "darwin":` + the import, `else:` + the name bound to `None`. That alone does not import: six module-level constants read EventKit attributes at load (`eventkit._FULL_ACCESS`, `_ENTITIES`, `_ENTITY_ADAPTERS`, `_FREQUENCIES`; `calendar._SPANS`; `doctor._EK_ENTITIES`). Each gets `if EK is not None else <empty>`, so the darwin expression is evaluated exactly as today.
- `server.main()` calls `eventkit.bootstrap()`, which calls `run_native` at startup. With the seam refusing, the server would die before `mcp.run()`. So `bootstrap()` returns early off macOS.
- Native doors outside `run_native` also refuse: `runtime.tracked_run` (the Shortcuts CLI calls it directly, never through run_native; also pgrep/ps), `runtime.mac_region` (a direct Foundation read in `messages_with`), and `doctor.diagnose` (EventKit status, TCC.db, launchd; off macOS its EventKit loop is empty, so it needs its own check).
- `server._guard` also calls `runtime.require_macos()`. Reason: several tools answer from a store-path lookup before they reach the seam. Off macOS, Mail answers `no Mail data found ... Open Mail once` (`mail_index._NO_MAIL_DATA`) and Reminders answers `Reminders store not found` (`reminders_store.store_paths`). These errors are typed but name the wrong cause. One call in `_guard` gives every native tool the platform reason; ping, now and usage (`guard=False`) still answer.
- New error class `UnsupportedPlatform` (kind `unsupported_platform`): no existing kind means "this OS has no Mac apps".
- Task order is fixed by the owner (dependencies → imports + seam → proof + CI), so the plan has no tracer task; the Docker run in Task 3 is the end-to-end proof. Task 2 touches 9 files and the plan 16 files; the owner's single-plan, three-task constraint forces this.
</objective>

<execution_context>
@~/.claude/gsd-core/workflows/execute-plan.md
@~/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@AGENTS.md
@pyproject.toml
@macos_apps_mcp/runtime.py
@macos_apps_mcp/eventkit.py
@macos_apps_mcp/errors.py
@tests/conftest.py

Measured baselines at 3bf281b (planner, 2026-10-25, macOS 27 arm64, uv 0.13.5):
- `uv run pytest -q`: 2615 passed, 1 failed, 102 deselected. The failure is the known flake `tests/test_doctor.py::test_report_stays_under_token_budget[daemon-not-built-worst-escape]` (5-digit PIDs, open issue #464). Report it if it fails; do not fix it.
- Registry: 71 records (39 read, 16 additive, 13 destructive, 3 send); 68 registered with sends off. The owner's "71 with sends off" counts records; tests compute the set, they never hard-code it.
- Linux resolution of the lock: `pyobjc|osxphotos` lines = 6 at HEAD (target 0). Darwin resolution = 21 (must stay 21).
- Trial run of the Task 1 + Task 2 import changes (guards, the six constants, the bootstrap skip): wheel in python:3.12-slim aarch64 installed 0 PyObjC packages, imported, and answered stdio tools/list with 68 tools.
- The simulated-Linux import smoke (Task 2 verify) fails at HEAD with `import of Foundation halted; None in sys.modules`.
- `ruff check` passes on a module whose imports follow an `if sys.platform` block (no E402).
- Faking `sys.platform` BEFORE third-party imports breaks `sysconfig` (`_sysconfigdata__linux_darwin`); the smoke preloads the dependencies first.
</context>

<tasks>

<task type="auto">
  <name>Task 1: Install the macOS-only dependencies only on macOS (pyproject markers + lock refresh)</name>
  <files>pyproject.toml, uv.lock, tests/test_packaging.py</files>
  <precondition>`git merge-base --is-ancestor 3bf281b HEAD` exits 0 in the lane, and `uv sync --locked` exits 0 there (a new worktree has no dependencies installed).</precondition>
  <read_first>pyproject.toml (the `dependencies` list and the comment blocks around it), tests/test_packaging.py (`test_only_intel_macs_cap_cryptography`, `test_osxphotos_is_a_capped_base_dependency`), scripts/build_app.sh lines 97-120 (the bundle export: `uv pip install --python-platform <arch>-apple-darwin` evaluates `sys_platform` as darwin; only `platform_release` markers are dropped, and the export already refuses those)</read_first>
  <action>
Requirement OWNER-LINUX-DEPS.

Step 0 (before any edit): run `uv sync --locked`, then write the darwin environment baseline with `uv pip freeze > "$SCRATCH/freeze-before.txt"`.

Step 1, pyproject.toml: append the marker `; sys_platform == 'darwin'` inside the string of exactly these five runtime dependencies, keeping their specifiers and inline comments: `pyobjc-framework-EventKit>=10.0`, `pyobjc-framework-Cocoa>=10.0`, `pyobjc-framework-ServiceManagement>=10.0`, `osxphotos>=0.77.2,<0.78`, `pyobjc-framework-uniformtypeidentifiers>=10.0`. Every other runtime dependency (fastmcp, anyio, mcp, uvicorn, httpx, starlette) is cross-platform and stays unmarked; the cryptography line already carries its own darwin + x86_64 marker and stays byte-identical. The dev and build groups stay unchanged (pytest, pytest-cov, python-dateutil, ruff, hatchling are cross-platform). Add one comment line above the first marked dependency saying why: Linux installs only the pure dependencies, so the server starts and lists its tools there (Glama's build test), and the bundle install evaluates `sys_platform` as darwin. Never use a `platform_release` marker (D-16: the bundle install drops it in silence).

Step 2: run `uv lock` with no upgrade flag. The planner's trial (same uv 0.13.5) gave exactly this diff: the marker lines change, wheel lists of osxphotos-only transitive packages lose their non-macOS wheels, and four entries go: ansicon 1.89.0, jinxed 2.1.0, tzlocal 5.4.4 and the win32-only tenacity 9.2.1 fork. All four were reachable only on platforms that now install no osxphotos at all, so removing them is the marker itself, not an upgrade. No other package may be added, removed or change version (the repo has a 3-day Dependabot cooldown and a release just shipped). If the diff differs, stop and report it; do not hand-edit the lock.

Step 3, tests/test_packaging.py, minimal: in `test_osxphotos_is_a_capped_base_dependency`, the line asserting that the UniformTypeIdentifiers requirement has no marker becomes an assertion that its marker string equals `sys_platform == "darwin"` (packaging normalizes the quotes). Update the docstring sentence to match: the line's only marker is the darwin platform, never `platform_release`, which the bundle install drops in silence. No other test changes.

Step 4: `uv sync --locked`, then confirm `uv pip freeze` is identical to the Step 0 baseline (the Mac environment does not move). Run the full verification, then commit atomically: `build(deps): install the PyObjC and osxphotos dependencies only on macOS`.
  </action>
  <verify>
    <automated>uv lock --check && uv run python -c "import tomllib; from packaging.requirements import Requirement; deps = [Requirement(d) for d in tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']]; mac = [r for r in deps if r.name.startswith('pyobjc') or r.name == 'osxphotos']; bad = [r.name for r in mac if r.marker is None or 'platform_release' in str(r.marker) or r.marker.evaluate({'sys_platform': 'linux'}) or not r.marker.evaluate({'sys_platform': 'darwin'})]; print(len(mac), bad); raise SystemExit(1 if bad or len(mac) != 5 else 0)" && uv run python -c "import subprocess, tomllib; old = tomllib.loads(subprocess.run(['git', 'show', '3bf281b:uv.lock'], capture_output=True, text=True, check=True).stdout); new = tomllib.load(open('uv.lock', 'rb')); pv = lambda d: {(p['name'], p['version']) for p in d['package'] if 'version' in p}; added, removed = pv(new) - pv(old), pv(old) - pv(new); allowed = {('ansicon', '1.89.0'), ('jinxed', '2.1.0'), ('tenacity', '9.2.1'), ('tzlocal', '5.4.4')}; print('added', sorted(added), 'removed', sorted(removed)); raise SystemExit(0 if not added and removed <= allowed else 1)" && uv export --frozen --no-hashes --no-emit-project --all-groups > "$SCRATCH/reqs.txt" && test "$(uv pip compile "$SCRATCH/reqs.txt" --python-platform x86_64-manylinux_2_28 --python-version 3.12 --no-header --no-annotate -q | grep -ciE '^(pyobjc|osxphotos)')" = 0 && test "$(uv pip compile "$SCRATCH/reqs.txt" --python-platform aarch64-apple-darwin --python-version 3.12 --no-header --no-annotate -q | grep -ciE '^(pyobjc|osxphotos)')" -ge 1 && uv sync --locked && uv pip freeze | diff "$SCRATCH/freeze-before.txt" - && uv run pytest tests/test_packaging.py -q && uv run pytest -q && MACOS_APPS_ALLOW_SEND=mail uv run pytest -q && MACOS_APPS_READ_ONLY=1 uv run pytest -q && uv run ruff check . && uv run ruff format --check .</automated>
  </verify>
  <done>All five macOS-only dependencies carry `sys_platform == 'darwin'` (the marker gate fails at HEAD with 5 unmarked, passes after); `uv lock --check` passes; the lock adds nothing and removes at most the four non-macOS-only entries; Linux resolution has 0 pyobjc/osxphotos lines (HEAD: 6), darwin still resolves them (21 lines at HEAD and in the planner's trial); the Mac `uv pip freeze` is identical to the baseline, which is the proof that the darwin set did not move; the three suite runs are green except the known #464 flake; ruff is clean; one commit.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Load on Linux, refuse at every native door (guarded imports, UnsupportedPlatform, require_macos)</name>
  <files>macos_apps_mcp/errors.py, macos_apps_mcp/runtime.py, macos_apps_mcp/eventkit.py, macos_apps_mcp/doctor.py, macos_apps_mcp/adapters/calendar.py, macos_apps_mcp/adapters/reminders.py, macos_apps_mcp/server.py, tests/test_runtime.py, tests/test_off_macos.py</files>
  <precondition>Task 1's commit is HEAD (`git log -1 --format=%s` starts with `build(deps)`), and the owner's review of Task 1 is done.</precondition>
  <read_first>macos_apps_mcp/runtime.py (run_native, run_osascript, tracked_run, read_via_sqlite, photos_db, mac_region), macos_apps_mcp/eventkit.py (imports, the four module-level EK constants, bootstrap), macos_apps_mcp/doctor.py lines 1-160 and diagnose(), macos_apps_mcp/adapters/calendar.py lines 1-45 and the `_SPANS` dict, macos_apps_mcp/adapters/reminders.py lines 1-45, macos_apps_mcp/server.py lines 1-80 (`_guard`) and main(), macos_apps_mcp/errors.py, tests/conftest.py `_no_real_osascript` (a seam self-test binds the real function at test-module import), tests/test_runtime.py lines 1-110 (the two taxonomy tuples), tests/test_native_seam.py (doctor and adapters must call seams qualified)</read_first>
  <behavior>
    - With `sys.platform` monkeypatched to "linux": `runtime.run_native(fn)` raises `UnsupportedPlatform` and `fn` never runs (pass a callable that raises AssertionError if called).
    - `run_osascript('return "x"')` and `tracked_run(["true"], timeout=5.0)`, both bound from `macos_apps_mcp.runtime` at test-module import (the real functions, before conftest's autouse fake), raise `UnsupportedPlatform`.
    - `runtime.mac_region()` raises `UnsupportedPlatform`.
    - `doctor.diagnose()` raises `UnsupportedPlatform`, with `doctor._EK_ENTITIES` monkeypatched to `()` to mirror Linux (without the check, diagnose would reach `app_process_info`, whose `tracked_run` is conftest's AssertionError fake, so the test is not vacuous on a Mac).
    - `eventkit.bootstrap()` returns None and never calls `eventkit.run_native` (monkeypatched to a recorder).
    - `server._guard(recorder)()` raises `fastmcp.exceptions.ToolError` whose text contains `runs only on macOS`, and the recorder is never called.
    - Every refusal message contains `runs only on macOS` and names the current `sys.platform` value; `UnsupportedPlatform` is a `NativeError` with kind `unsupported_platform`.
    - With the real `sys.platform` (darwin, no patch), `runtime.require_macos()` returns None.
  </behavior>
  <action>
Requirement OWNER-LINUX-SEAM. Write tests/test_off_macos.py first from the behavior list (RED: it fails on the missing name), then implement until it passes (GREEN). The test file has one module docstring stating why it exists: Glama's Linux build check needs the server to load and list tools, and every native call must refuse there with one typed error.

errors.py: add `class UnsupportedPlatform(NativeError)` in the existing style: a one-sentence docstring (the server runs off macOS, where no Mac app exists, so every native call refuses) and `kind = "unsupported_platform"`.

runtime.py: add `import sys` to the stdlib block (sorted). Replace the top-level `import Foundation as F` with the owner's guard: `if sys.platform == "darwin":` with the unchanged import indented under it, and `else:` binding `F = None`, carrying one comment line that says why (off macOS the server must still import and list its tools; `require_macos()` refuses every native call). Never wrap the import in a try/except: a broken PyObjC on a Mac must still fail loudly at import, as today. Import `UnsupportedPlatform` from `.errors` in the existing sorted list. Define `require_macos() -> None` directly above `run_native`: when `sys.platform != "darwin"` (read at call time, so tests can monkeypatch it) it raises `UnsupportedPlatform` with exactly this agent-directed text, formatted with the current platform value: `macos-apps-mcp runs only on macOS: this server is running on {sys.platform}, where Mail, Calendar, Reminders and the other Mac apps do not exist. Use it on a Mac. Do not retry.` Its docstring names the doors that call it. Make `require_macos()` the first statement of `run_native`, `tracked_run` and `mac_region`, and add one sentence to each docstring. `run_osascript`, `read_via_sqlite` and `photos_db` get no own call: off the worker they dispatch through `run_native`, and off macOS no code ever runs on the worker. Say this in one sentence in the `run_native` docstring.

eventkit.py: add `import sys`; put `import EventKit as EK` and `import Foundation as F` under one `if sys.platform == "darwin":` block, with `else:` binding `EK = F = None` and the same one-line why. Append `if EK is not None else None` to `_FULL_ACCESS`, and `if EK is not None else ()` to `_ENTITIES` and `_ENTITY_ADAPTERS`, and `if EK is not None else {}` to `_FREQUENCIES`; `_FREQUENCY_NAMES` then derives `{}` with no edit. In `bootstrap()`, after the docstring, return early when `sys.platform != "darwin"`, with one comment line: there is nothing to request off macOS, and the server must still reach `mcp.run()` so tools/list answers.

doctor.py: add `import sys`; guard `import EventKit as EK` the same way (`else: EK = None`); append `if EK is not None else ()` to `_EK_ENTITIES`. Make `runtime.require_macos()` the first statement of `diagnose()` (qualified, as test_native_seam requires; doctor already imports `runtime`).

adapters/calendar.py and adapters/reminders.py: add `import sys`; guard `import EventKit as EK` the same way. In calendar.py append `if EK is not None else {}` to `_SPANS`. reminders.py has no module-level EventKit read.

server.py: change `from . import notices, registry, tiers` to also import `runtime` (sorted). In `_guard`'s wrapper, inside the existing `try`, call `runtime.require_macos()` before the tool body, with one comment line: off macOS every native tool answers the platform reason first, because Mail and Reminders would otherwise answer from a store-path lookup ("no Mail data found", "Reminders store not found"). Add one sentence to the `_guard` docstring. Tools registered with `guard=False` (ping, now, usage) are not wrapped and keep answering on Linux.

tests/test_runtime.py: import `UnsupportedPlatform` and add it to both taxonomy tuples (the `issubclass` loop and `test_taxonomy_kinds_are_distinct_machine_codes`).

On darwin every change is either a string comparison that passes or an expression evaluated exactly as before. Run `uv run ruff format` on the touched files (the ternaries over multi-line literals get parenthesized), then the full verification, then commit atomically: `feat: load on Linux and refuse every native call there with UnsupportedPlatform`.
  </action>
  <verify>
    <automated>uv run python -c "import asyncio, platform, sqlite3, sysconfig, anyio, fastmcp, httpx, mcp, starlette, sys; sys.platform = 'linux'; sys.modules.update(dict.fromkeys(['EventKit', 'Foundation', 'objc', 'AppKit', 'ServiceManagement', 'UniformTypeIdentifiers', 'osxphotos'])); import macos_apps_mcp.server as srv, macos_apps_mcp.registry as reg; print('simulated-linux import ok', sum(r.registered for r in reg.TOOLS.values()))" && ! grep -nE '^(import|from) (EventKit|Foundation|AppKit|objc|ServiceManagement|UniformTypeIdentifiers|osxphotos)( |$)' macos_apps_mcp/*.py macos_apps_mcp/adapters/*.py macos_apps_mcp/dashboard/*.py && ( for f in eventkit runtime doctor adapters/calendar adapters/reminders; do grep -q 'if sys.platform == "darwin":' "macos_apps_mcp/$f.py" || exit 1; done ) && ( for f in eventkit doctor adapters/calendar adapters/reminders; do grep -q '^    import EventKit as EK$' "macos_apps_mcp/$f.py" || exit 1; done ) && grep -q '^    import Foundation as F$' macos_apps_mcp/eventkit.py && grep -q '^    import Foundation as F$' macos_apps_mcp/runtime.py && ! grep -nE '^(try:|except ImportError)' macos_apps_mcp/eventkit.py macos_apps_mcp/runtime.py macos_apps_mcp/doctor.py macos_apps_mcp/adapters/calendar.py macos_apps_mcp/adapters/reminders.py && grep -q '^def require_macos' macos_apps_mcp/runtime.py && grep -v '^\s*#' macos_apps_mcp/server.py | grep -q 'runtime.require_macos()' && grep -v '^\s*#' macos_apps_mcp/doctor.py | grep -q 'runtime.require_macos()' && uv run python -c "import macos_apps_mcp.eventkit as e, macos_apps_mcp.runtime as r, macos_apps_mcp.doctor as d, macos_apps_mcp.adapters.calendar as c, macos_apps_mcp.adapters.reminders as m; assert all(x.EK is not None for x in (e, d, c, m)) and e.F is not None and r.F is not None and e._ENTITIES and c._SPANS and d._EK_ENTITIES and e._FREQUENCY_NAMES; print('darwin eager imports intact')" && uv run pytest tests/test_off_macos.py tests/test_runtime.py tests/test_native_seam.py tests/test_import_layers.py -q && uv run pytest -q && MACOS_APPS_ALLOW_SEND=mail uv run pytest -q && MACOS_APPS_READ_ONLY=1 uv run pytest -q && uv run ruff check . && uv run ruff format --check .</automated>
  </verify>
  <done>The simulated-Linux import prints `simulated-linux import ok 68` (fails at HEAD); no column-0 import of a PyObjC/osxphotos module is left in the package (HEAD: exactly six — eventkit.py twice, runtime.py, doctor.py, adapters/calendar.py, adapters/reminders.py); the five modules each hold a darwin guard with the original import indented under it; no module-level try/except appears in them; `require_macos()` opens run_native, tracked_run, mac_region and diagnose and runs inside `_guard` (proven by tests/test_off_macos.py); on the Mac every EK/F name and EK-derived constant is populated as before; tests/test_off_macos.py covers every behavior line; the three suite runs are green except the known #464 flake; ruff is clean; one commit.</done>
</task>

<task type="auto">
  <name>Task 3: Prove it on Linux — tools/list test, linux-tools-list CI job, Docker run, Glama spec</name>
  <files>tests/test_tools_list_anywhere.py, .github/workflows/ci.yml, CHANGELOG.md, AGENTS.md</files>
  <precondition>Task 2's commit is HEAD (`git log -1 --format=%s` starts with `feat: load on Linux`), the owner's review of Task 2 is done, and `docker version --format '{{.Server.Os}}'` prints `linux`.</precondition>
  <read_first>tests/test_registry.py lines 147-153 (`_live()`: the existing in-process `Client(srv.mcp)` + `asyncio.run` pattern), .github/workflows/ci.yml (whole file), CHANGELOG.md lines 1-20 (the `[Unreleased]` heading and the house bullet style), AGENTS.md "Architecture (don't drift)" bullets</read_first>
  <action>
Requirement OWNER-LINUX-CI.

tests/test_tools_list_anywhere.py (new): a module docstring saying it is the one test the Linux CI job runs, because Glama's build test starts the server in a Linux container and reads tools/list. One test, `test_tools_list_matches_the_registry`, following the `_live()` pattern of tests/test_registry.py: open `fastmcp.Client(macos_apps_mcp.server.mcp)` in-process under `asyncio.run`, collect the names from `list_tools()`, and assert they equal the set of `registry.TOOLS` names whose record is `registered`, and that the set is not empty. Compute the set; never hard-code 68 or 71. It must pass on macOS and on Linux unchanged.

.github/workflows/ci.yml: keep the `check` job byte-identical. Add a second job `linux-tools-list` with `runs-on: ubuntu-latest` and these steps in order: the same `actions/checkout@v7` and `astral-sh/setup-uv@v10.3.2` lines as `check`, then `run: uv sync --locked`, then `run: uv run python -c "import macos_apps_mcp.server"`, then `run: uv run pytest tests/test_tools_list_anywhere.py`. Rewrite the header comment, which says `uv sync` cannot run on Linux: the macOS `check` job runs lint and the whole suite twice (default and read-only), and the `linux-tools-list` job proves the server installs, imports and lists its tools on Linux (Glama's build test), so a future load-time macOS import breaks CI. The workflow-level `permissions: contents: read` stays.

CHANGELOG.md: under `## [Unreleased]`, add `### Added` with one bullet in the house style, bold lead `**The server starts and lists its tools on Linux.**`, then the why in short sentences: Glama scores an MCP server only after a build test in a Linux container that starts it and reads tools/list, and the awesome-mcp-servers list requires a scored Glama listing; the PyObjC and osxphotos dependencies now install only on macOS; on any other system every tool that needs a Mac answers `unsupported_platform` ("macos-apps-mcp runs only on macOS"); nothing changes on a Mac; a Linux CI job keeps it that way.

AGENTS.md: add one bullet at the end of "Architecture (don't drift)": off macOS the server loads but never acts. A macOS-only import at module load sits under `if sys.platform == "darwin":` (else the name is `None`), never a try/except, and a native door refuses through `runtime.require_macos()`. The `linux-tools-list` CI job fails on a load-time macOS import, and Glama lists the server only after a Linux build test reads tools/list.

Docker proof (nothing of it is committed; all files in `$SCRATCH`):
(a) Wheel route, per owner: `uv build --wheel -o "$SCRATCH/dist"`. Write `$SCRATCH/client/list_tools.py`, a short script that takes the server start command from argv (command = argv[1], args = argv[2:]), connects with `fastmcp.Client(fastmcp.client.transports.StdioTransport(command=..., args=...))`, compares the tools/list names with the registered set it computes by importing `macos_apps_mcp.server` and `macos_apps_mcp.registry` in its own process, calls the `calendars` tool and catches the ToolError, then prints the tool count, whether the two sets are equal, and the error text. Run `docker run --rm -v "$SCRATCH/dist":/w:ro -v "$SCRATCH/client":/c:ro python:3.12-slim sh -c '...'` where the shell string runs `pip install -q --root-user-action=ignore /w/macos_apps_mcp-0.15.1-py3-none-any.whl`, then `pip list | grep -ciE "pyobjc|osxphotos"` (expect 0), then `python -c "import macos_apps_mcp.server"`, then `python /c/list_tools.py macos-apps-mcp`. Expect 68 tools, sets equal, and the error text starting `macos-apps-mcp runs only on macOS: this server is running on linux`.
(b) Source route, which is what Glama builds (it clones the GitHub default branch, develop): export the committed tree with `git archive --format=tar HEAD` into `$SCRATCH/src` (the Task 2 commit carries every runtime change), mount it read-only, copy it to `/app` in python:3.12-slim, run `pip install -q uv` then `uv sync --locked --no-dev`, then `.venv/bin/python /c/list_tools.py uv run --no-sync macos-apps-mcp` from `/app`. Expect the same three results. If it fails, also try `pip install .` + `macos-apps-mcp` and record which route worked.

Run the full verification, then commit atomically: `ci: prove the server starts and lists its tools on Linux`. In the SUMMARY notes, give the exact Glama build spec that worked in (b): the install command(s) and the stdio start command, plus two facts. First, Glama builds from develop, so the fix reaches Glama when this PR merges. Second, a PyPI-based spec (`pip install macos-apps-mcp`, `uvx macos-apps-mcp`) works only after the next release publishes to PyPI. Paste the Docker output lines (the counts, the set check, the error text) as evidence.
  </action>
  <verify>
    <automated>uv run pytest tests/test_tools_list_anywhere.py -q && uv run python -c "import subprocess, yaml; w = yaml.safe_load(open('.github/workflows/ci.yml')); old = yaml.safe_load(subprocess.run(['git', 'show', '3bf281b:.github/workflows/ci.yml'], capture_output=True, text=True, check=True).stdout); j = w['jobs']['linux-tools-list']; runs = [s.get('run') for s in j['steps']]; assert w['jobs']['check'] == old['jobs']['check'], 'check job changed'; assert j['runs-on'] == 'ubuntu-latest'; assert runs[-3:] == ['uv sync --locked', 'uv run python -c \"import macos_apps_mcp.server\"', 'uv run pytest tests/test_tools_list_anywhere.py'], runs; print('ci ok')" && sed -n '/^## \[Unreleased\]/,/^## \[0\.15\.1\]/p' CHANGELOG.md | grep -q 'starts and lists its tools on Linux' && grep -q 'require_macos' AGENTS.md && grep -q 'linux-tools-list' AGENTS.md && uv run pytest -q && MACOS_APPS_ALLOW_SEND=mail uv run pytest -q && MACOS_APPS_READ_ONLY=1 uv run pytest -q && uv run ruff check . && uv run ruff format --check .</automated>
    <human-check>Docker evidence in the SUMMARY: route (a) prints 0 PyObjC/osxphotos packages; both routes print a tools/list count equal to the registry set and the `calendars` error text `macos-apps-mcp runs only on macOS: this server is running on linux ...`.</human-check>
  </verify>
  <done>tests/test_tools_list_anywhere.py passes on the Mac; ci.yml has the `linux-tools-list` job with exactly the three run steps and an unchanged `check` job; CHANGELOG `[Unreleased]` has the Added bullet (baseline 0 matches) and AGENTS.md names `require_macos` (baseline 0); both Docker routes list the registered tools over stdio on linux/aarch64 and answer `calendars` with the platform error; the three suite runs are green except the known #464 flake; ruff is clean; one commit; the SUMMARY carries the Glama build spec and the Docker evidence.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| MCP client → tool layer (`_guard`) | Untrusted tool calls arrive; off macOS they must not reach any native code path |
| pyproject/uv.lock → installers (CI, bundle, Glama) | The markers decide which packages install on which platform |
| CI workflow → GitHub runners | A new job runs repository code on ubuntu-latest |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-vuv-01 | Tampering | eventkit/runtime/doctor/calendar/reminders import guards | high | mitigate | The guard is `sys.platform == "darwin"`, never a try/except: a broken PyObjC on a Mac still fails at import instead of loading with `EK = None` and answering wrong or empty reads. Task 2 gates: no module-level try/except in the five modules, and the darwin eager-import assertion passes. |
| T-vuv-02 | Elevation of privilege | off-macOS tool calls | medium | mitigate | `runtime.require_macos()` is the first statement of run_native, tracked_run, mac_region and diagnose, and runs inside `_guard` before any tool body, so no native or pre-seam path executes off macOS (tests/test_off_macos.py). |
| T-vuv-03 | Information disclosure | UnsupportedPlatform message | low | accept | The text names only `sys.platform` (e.g. `linux`), no path, user or host detail. |
| T-vuv-04 | Tampering | uv.lock refresh | medium | mitigate | `uv lock` without upgrade; Task 1 gates that no remaining package changes version, nothing is added, removals are limited to the four non-macOS-only entries, darwin resolution stays at 21 pyobjc/osxphotos lines, and the Mac `uv pip freeze` is identical. |
| T-vuv-05 | Tampering | bundle build (scripts/build_app.sh) | medium | mitigate | The new marker is `sys_platform` only; the bundle install (`--python-platform <arch>-apple-darwin`) evaluates it as darwin, and the existing export refusal of `platform_release` markers stays untouched. |
| T-vuv-06 | Elevation of privilege | ci.yml linux-tools-list | low | mitigate | Same pinned actions as `check` (`actions/checkout@v7`, `astral-sh/setup-uv@v10.3.2`), workflow-level `permissions: contents: read`, no secrets, `uv sync --locked` only. |
| T-vuv-SC | Tampering | npm/pip/cargo installs | high | mitigate | No new dependency enters pyproject or the lock (markers only). The Docker proof installs only names already in uv.lock plus uv itself, inside a throwaway `--rm` container with read-only mounts; nothing it installs ships. |
</threat_model>

<verification>
After each task (the owner reviews between tasks):
- `uv run pytest -q`, `MACOS_APPS_ALLOW_SEND=mail uv run pytest -q`, `MACOS_APPS_READ_ONLY=1 uv run pytest -q` — green except the known flake `tests/test_doctor.py::test_report_stays_under_token_budget` (#464, 5-digit PIDs): report it, do not fix it.
- `uv run ruff check .` and `uv run ruff format --check .` — clean.
- Report actual output for any failure; never suppress or simplify it.

Whole plan:
- Linux: the wheel and the source checkout both install, import and answer stdio tools/list in python:3.12-slim; `calendars` answers the platform error.
- macOS: environment identical to the base; every PyObjC import eager as before.
- CI: `linux-tools-list` added; `check` unchanged.
</verification>

<success_criteria>
- Glama's build test can pass from develop: install with uv (or pip), start `macos-apps-mcp` over stdio, read tools/list.
- Every Mac-needing tool call off macOS returns `unsupported_platform` with `macos-apps-mcp runs only on macOS`.
- Zero behaviour change on macOS, proven by the freeze diff, the eager-import assertion and three green suite runs.
- Three atomic commits, one per task, each reviewed by the owner before the next.
</success_criteria>

<output>
Create `.planning/quick/261025-vuv-the-server-starts-and-lists-its-tools-on/261025-vuv-SUMMARY.md` when done. Its notes carry the exact Glama build spec (install command(s) + stdio start command) that worked in Docker route (b), the Docker evidence lines, the fact that Glama builds from develop (live on merge) while a PyPI-based spec needs the next release, and the #464 flake status. The PR to develop and the vault-journal bullet belong to the orchestrator (/gsd-quick) after the owner's last review, not to the executor.
</output>
