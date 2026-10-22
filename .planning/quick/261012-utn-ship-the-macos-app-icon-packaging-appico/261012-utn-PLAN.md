---
phase: quick-261012-utn
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - packaging/AppIcon.icon/icon.json
  - packaging/AppIcon.icon/Assets/
  - packaging/Info.plist
  - scripts/build_app.sh
  - tests/test_packaging.py
  - docs/DAEMON.md
  - CHANGELOG.md
autonomous: true
requirements: [QUICK-261012-utn]

estimate:
  tokens: 35000
  raw_tokens: 35000
  tasks: 2
  confidence: low

must_haves:
  truths:
    - "`packaging/AppIcon.icon` is a verbatim copy of the owner's Icon Composer file: `diff -r /Users/andrei/Downloads/AppIcon.icon packaging/AppIcon.icon` exits 0, and the commit tracks `icon.json` plus the 16 SVG files under `Assets/`"
    - "`packaging/Info.plist` has `CFBundleIconFile` = `AppIcon` and `CFBundleIconName` = `AppIcon`; `test_info_plist_names_the_icon` pins both"
    - "`test_icon_composer_package_is_consistent` proves `icon.json` parses, the set of `image-name` values across every group's `layers` equals the set of files in `Assets/`, and `supported-platforms.squares` contains `macOS`"
    - "`scripts/build_app.sh` resolves `ACTOOL` once in the preflight block, before any download: `xcrun -f actool`, else the same with `DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer`, else exit 2 with a message that names `packaging/AppIcon.icon` and says the Command Line Tools have no actool"
    - "`scripts/build_app.sh` compiles `packaging/AppIcon.icon` into `$APP/Contents/Resources` with `--minimum-deployment-target \"$MACOS_MIN\"` and `--app-icon AppIcon`, after the bundle reset (`rm -rf \"$APP\"; mkdir -p`) and before the `cp \"$REPO/packaging/Info.plist\"` line and the signing block, and fails the build if `AppIcon.icns` or `Assets.car` is missing or empty afterwards; `test_build_script_compiles_the_icon` pins the call, the message and the order"
    - "The committed icon compiles: Xcode's actool run on `packaging/AppIcon.icon` writes a non-empty `AppIcon.icns` and `Assets.car`, and its partial plist's `CFBundleIconFile` and `CFBundleIconName` equal the values in `packaging/Info.plist`"
    - "`docs/DAEMON.md` build section says the build compiles `packaging/AppIcon.icon` with Xcode's actool, so it needs full Xcode (the Command Line Tools have no actool), and that `DEVELOPER_DIR` points the build at Xcode; `CHANGELOG.md` `[Unreleased]` has an `### Added` bullet for the icon"
    - "`uv run pytest`, `uv run ruff check .` and `uv run ruff format --check .` pass; one commit on `feat/app-icon` holds the code change, no `.planning/` file is in it, nothing is pushed"
  artifacts:
    - path: "packaging/AppIcon.icon/icon.json"
      provides: "the Icon Composer document (groups, layers, Liquid Glass properties), unchanged from the owner's file"
      contains: "supported-platforms"
    - path: "packaging/Info.plist"
      provides: "the two static icon keys copied verbatim into the bundle"
      contains: "CFBundleIconName"
    - path: "scripts/build_app.sh"
      provides: "the actool preflight and the icon compile step"
      contains: "--app-icon AppIcon"
    - path: "tests/test_packaging.py"
      provides: "three contract tests: plist icon keys, icon package consistency, build-script compile step and order"
      contains: "test_build_script_compiles_the_icon"
    - path: "docs/DAEMON.md"
      provides: "the full-Xcode build requirement and the DEVELOPER_DIR route"
      contains: "AppIcon.icon"
    - path: "CHANGELOG.md"
      provides: "[Unreleased] / ### Added bullet"
      contains: "Icon Composer"
  key_links:
    - from: "scripts/build_app.sh `--app-icon AppIcon`"
      to: "packaging/Info.plist `CFBundleIconName` = `AppIcon`"
      via: "macOS 26 looks up the icon in Assets.car by CFBundleIconName; a name mismatch shows the generic icon"
      pattern: "--app-icon AppIcon"
    - from: "scripts/build_app.sh `$APP/Contents/Resources/AppIcon.icns`"
      to: "packaging/Info.plist `CFBundleIconFile` = `AppIcon`"
      via: "macOS before 26 loads the legacy icns named by CFBundleIconFile"
      pattern: "AppIcon.icns"
    - from: "packaging/Info.plist `LSMinimumSystemVersion`"
      to: "actool `--minimum-deployment-target`"
      via: "`MACOS_MIN` read by `plutil -extract` at the top of the build"
      pattern: "--minimum-deployment-target \"\\$MACOS_MIN\""
    - from: "icon compile step"
      to: "codesign (`if [[ -n \"$SIGN\" ]]`)"
      via: "codesign seals Contents/Resources; a file written after signing breaks `codesign --verify --strict`"
      pattern: "if \\[\\[ -n \"\\$SIGN\" \\]\\]"
---

<objective>
Ship the owner's Liquid Glass app icon in `macos-apps-mcp.app`. The Icon Composer file
goes into `packaging/AppIcon.icon`; `scripts/build_app.sh` compiles it with Xcode's
`actool` into `Contents/Resources` (`Assets.car` for macOS 26+, `AppIcon.icns` as the
legacy fallback); `packaging/Info.plist` names it; `tests/test_packaging.py` pins the
contract; `docs/DAEMON.md` and `CHANGELOG.md` state the end state.

Purpose: the `.app` shows its own icon in place of the generic one. The build gains one
toolchain need (full Xcode for actool), and that need must fail fast and say how to fix it.

Output: one commit on `feat/app-icon` in the lane, not pushed.
</objective>

<execution_context>
@~/.claude/gsd-core/workflows/execute-plan.md
@~/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
Lane: every path below is repo-root-relative; every command runs with cwd = the lane root
(`/Users/andrei/Developer/macos-apps-mcp/.worktrees/app-icon`, branch `feat/app-icon`).
Do not touch the main checkout, `.planning/ROADMAP.md`, or the contents of the icon package.

Input (read-only, outside the repo): `/Users/andrei/Downloads/AppIcon.icon` — a directory
with `icon.json` and `Assets/` (16 SVG files, no hidden files). Planner check: no script,
no private path, no external reference in any of its files.

@CLAUDE.md
@scripts/build_app.sh
@packaging/Info.plist
@tests/test_packaging.py
@docs/DAEMON.md
@CHANGELOG.md

Facts the planner verified on this Mac (do not re-derive):
- `xcode-select -p` is the Command Line Tools, so `xcrun -f actool` fails;
  `DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcrun -f actool` prints
  `/Applications/Xcode.app/Contents/Developer/usr/bin/actool`.
- That absolute actool path, run WITHOUT `DEVELOPER_DIR` set, compiles the icon:
  `<actool> <icon> --compile <dir> --platform macosx --minimum-deployment-target 15.0 --app-icon AppIcon --output-partial-info-plist <file> --output-format human-readable-text`
  exits 0 and writes `<dir>/AppIcon.icns` and `<dir>/Assets.car`. The partial plist holds
  exactly `CFBundleIconFile` = `AppIcon` and `CFBundleIconName` = `AppIcon`. So the build
  resolves `ACTOOL` to an absolute path once and calls `"$ACTOOL"`; it never exports
  `DEVELOPER_DIR`.
- `icon.json` top-level keys: `fill-specializations`, `groups`, `supported-platforms`
  (`{"squares": ["macOS"]}`). Three groups; the first has an empty `layers` list; the other
  two reference 11 and 5 `image-name` values, 16 in all, one per SVG file.
- `packaging/AppIcon.icon` is not git-ignored. `packaging/` has no `__init__.py`, so the
  `from packaging.requirements import Requirement` import in the tests is unaffected.
- The existing vtool preflight message already contains "Command Line Tools", so a test
  needle of just "Command Line Tools" passes without the new message. The new test pins the
  longer phrase `the Command Line Tools have no actool`.
- `test_build_script_gates_universal2` asserts `src.count("for a in arm64 x86_64; do") == 3`.
  The new existence loop iterates file names (`for f in ...`), so that count stays 3.
- The universal2 gate checks only Mach-O files; `AppIcon.icns` and `Assets.car` are not
  Mach-O, so the gate is unaffected.
</context>

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1: Icon package, plist keys, actool preflight and compile step, with their contract tests</name>
  <files>packaging/AppIcon.icon/icon.json, packaging/AppIcon.icon/Assets/, packaging/Info.plist, scripts/build_app.sh, tests/test_packaging.py</files>
  <precondition>`/Users/andrei/Downloads/AppIcon.icon/icon.json` exists, and `DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcrun -f actool` exits 0 (full Xcode is installed).</precondition>
  <behavior>
    - `test_info_plist_names_the_icon`: `plistlib` loads `packaging/Info.plist`; `CFBundleIconFile == "AppIcon"` and `CFBundleIconName == "AppIcon"`. Docstring (the why): macOS 26 finds the Liquid Glass icon in `Assets.car` by `CFBundleIconName`, and older macOS loads `AppIcon.icns` by `CFBundleIconFile`; both names must match the build's `--app-icon AppIcon`.
    - `test_icon_composer_package_is_consistent`: `json.loads` of `packaging/AppIcon.icon/icon.json` succeeds; the set of every `image-name` across `groups[*]["layers"]` (use `.get("layers", [])`) equals the set of file names in `packaging/AppIcon.icon/Assets`, and is not empty; `"macOS" in doc["supported-platforms"]["squares"]`. Docstring: actool fails, or drops a layer, when a name in `icon.json` has no file; a stray file is an asset no layer uses.
    - `test_build_script_compiles_the_icon`: reads `scripts/build_app.sh` the way the sibling tests do (`(ROOT / "scripts" / "build_app.sh").read_text()`). Needles: `DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcrun -f actool`, `the Command Line Tools have no actool`, `"$ACTOOL" "$REPO/packaging/AppIcon.icon"`, `--compile "$APP/Contents/Resources"`, `--platform macosx`, `--minimum-deployment-target "$MACOS_MIN"`, `--app-icon AppIcon`, `--output-partial-info-plist "$WORK/`, `for f in AppIcon.icns Assets.car`, `ICON COMPILE FAILED`. Order asserts: `src.index("the Command Line Tools have no actool") < src.index("curl -fsSL")` (fails before any download); `src.index('rm -rf "$APP"; mkdir -p') < src.index('"$ACTOOL" "$REPO/packaging/AppIcon.icon"') < src.index('cp "$REPO/packaging/Info.plist"')`; and the compile index `< src.index('if [[ -n "$SIGN" ]]')`. Docstring: the bundle reset would delete an earlier compile, and codesign seals `Contents/Resources`, so an icon written after signing breaks the seal.
    - All three tests fail before the change (missing keys, missing directory, missing needles), and pass after it.
  </behavior>
  <action>
    Write the three tests in `<behavior>` first, in `tests/test_packaging.py`, in the style of the existing tests (module-level `ROOT` / `PKG`, plain `assert`, a short docstring that says why). Add `import json` in isort order (before `import plistlib`). Place `test_info_plist_names_the_icon` after `test_info_plist_contract`, `test_icon_composer_package_is_consistent` after it, and `test_build_script_compiles_the_icon` after `test_build_script_gates_universal2`. Run `uv run pytest tests/test_packaging.py -q` and confirm the three new tests fail and the old ones pass.

    Copy the icon package verbatim: `cp -R /Users/andrei/Downloads/AppIcon.icon packaging/AppIcon.icon`. Do not edit, rename, reformat or regenerate any file in it. Confirm with `diff -r /Users/andrei/Downloads/AppIcon.icon packaging/AppIcon.icon` (exit 0).

    In `packaging/Info.plist`, add `CFBundleIconFile` = `AppIcon` and `CFBundleIconName` = `AppIcon` as two `<key>…</key><string>AppIcon</string>` lines in the existing one-line-per-key style, directly after the `CFBundleName` line. The keys are static: the build copies this file verbatim, so the build does not merge actool's partial plist.

    In `scripts/build_app.sh`, two edits:

    (a) Preflight. Directly after the vtool check (the `xcrun -f vtool` block), add a check that sets `ACTOOL` once: the command substitution tries `xcrun -f actool 2>/dev/null`, and if that fails, `DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcrun -f actool 2>/dev/null` (exactly this text: the test pins it). If both fail, print to stderr, in the style of the neighbouring preflight messages, a message that contains `packaging/AppIcon.icon` and the phrase `the Command Line Tools have no actool`, and tells the operator to install Xcode or set `DEVELOPER_DIR` to an Xcode's `Contents/Developer`; then `exit 2`. Use the `VAR="$(…)" || { echo … >&2; exit 2; }` form, which is safe under `set -euo pipefail`. Extend the comment above the preflight by a few words, or add one line: actool comes with full Xcode only, and the absolute path from `xcrun -f` runs without `DEVELOPER_DIR`. Do not export `DEVELOPER_DIR`: the vtool, lipo, codesign and notarytool calls keep the selected toolchain.

    (b) Compile step. Directly after the line `SITE="$APP/Contents/lib/python${PYVER}/site-packages"` and before the `# 2. Locked deps` comment, add a short block. One comment line says why it is here: the icon goes into Resources after the bundle reset and before signing, because codesign seals Resources. Then run `"$ACTOOL" "$REPO/packaging/AppIcon.icon" --compile "$APP/Contents/Resources" --platform macosx --minimum-deployment-target "$MACOS_MIN" --app-icon AppIcon --output-partial-info-plist "$WORK/icon-partial.plist" --output-format human-readable-text`, with `|| { echo "ICON COMPILE FAILED: actool rejected packaging/AppIcon.icon" >&2; exit 1; }`. Then `for f in AppIcon.icns Assets.car; do` check `[[ -s "$APP/Contents/Resources/$f" ]]`, else print `ICON COMPILE FAILED: no Contents/Resources/$f` to stderr and `exit 1`. `$MACOS_MIN` is already read from `packaging/Info.plist` at the top of the script; reuse it, do not read the plist again. The partial plist goes to `$WORK`, which the existing `trap` deletes. Do not change any other line of the script.

    Run `bash -n scripts/build_app.sh`, then the packaging tests (all pass now), then the actool probe in `<verify>`, which compiles the committed copy of the icon with the same flags into a temporary directory and compares the partial plist with `packaging/Info.plist`. Do NOT run `scripts/build_app.sh` itself: it downloads two interpreters and takes minutes, and the string tests cover the script.
  </action>
  <verify>
    <automated>diff -r /Users/andrei/Downloads/AppIcon.icon packaging/AppIcon.icon && bash -n scripts/build_app.sh && uv run pytest tests/test_packaging.py -q && A="$(xcrun -f actool 2>/dev/null || DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcrun -f actool)" && D="$(mktemp -d)" && "$A" packaging/AppIcon.icon --compile "$D" --platform macosx --minimum-deployment-target "$(plutil -extract LSMinimumSystemVersion raw packaging/Info.plist)" --app-icon AppIcon --output-partial-info-plist "$D/partial.plist" --output-format human-readable-text >/dev/null && test -s "$D/AppIcon.icns" && test -s "$D/Assets.car" && test "$(plutil -extract CFBundleIconFile raw "$D/partial.plist")" = "$(plutil -extract CFBundleIconFile raw packaging/Info.plist)" && test "$(plutil -extract CFBundleIconName raw "$D/partial.plist")" = "$(plutil -extract CFBundleIconName raw packaging/Info.plist)" && rm -rf "$D" && echo ICON-PROBE-OK</automated>
  </verify>
  <done>The three new tests failed before the change and pass after it; the whole of `tests/test_packaging.py` passes; `bash -n` passes; the actool probe prints `ICON-PROBE-OK` (non-empty `AppIcon.icns` and `Assets.car`; the partial plist's two icon keys equal `packaging/Info.plist`'s); `diff -r` shows the copy is verbatim.</done>
</task>

<task type="auto">
  <name>Task 2: DAEMON.md and CHANGELOG end state, full verification, one commit</name>
  <files>docs/DAEMON.md, CHANGELOG.md</files>
  <action>
    `docs/DAEMON.md`, section "### 1. Build the signed `.app`": add one short paragraph directly after the paragraph that starts "This produces `dist/macos-apps-mcp.app`" and before the paragraph that starts "The build installs the exact versions". Content, in Simplified Technical English and in the end-state register (no "now", no history): the build compiles `packaging/AppIcon.icon`, an Icon Composer file, with Xcode's `actool` into `Contents/Resources` (`Assets.car` for macOS 26 and later, `AppIcon.icns` for older macOS); the build therefore needs full Xcode, because the Command Line Tools have no `actool`; when `xcode-select` points at the Command Line Tools, the build uses `/Applications/Xcode.app`, and for an Xcode at a different path, set `DEVELOPER_DIR` to its `Contents/Developer`. Keep it to two or three sentences. Change no other line of the file.

    `CHANGELOG.md`, `## [Unreleased]`: add a `### Added` section above the existing `### Fixed` (Keep a Changelog order) with one bullet in the style of the existing bullets (bold lead, then the detail): the `.app` carries an app icon, a Liquid Glass icon compiled from an Icon Composer file (`packaging/AppIcon.icon`), with a standard icon for macOS before 26; building the `.app` needs full Xcode for `actool` (see docs/DAEMON.md). No issue number exists for this change, so the bullet carries none. Make no claim about where macOS shows the icon beyond the app's own icon in Finder.

    Run the full verification (cwd = lane root): `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`. If any fails, report its actual output; do not weaken a test or skip a check. If `ruff format --check` fails on `tests/test_packaging.py`, run `uv run ruff format tests/test_packaging.py` and re-run all three.

    Commit once, on `feat/app-icon`, staging by explicit path only: `git add packaging/AppIcon.icon packaging/Info.plist scripts/build_app.sh tests/test_packaging.py docs/DAEMON.md CHANGELOG.md`. Before committing, confirm `git diff --cached --name-only` lists exactly those paths (the icon package as 17 files: `icon.json` and 16 `Assets/*.svg`) and no `.planning/` path. Subject: `feat(packaging): Liquid Glass app icon compiled from an Icon Composer file`. Body: two or three plain lines (what the build does with the file, the full-Xcode need and its fail-fast preflight, the tests). End the body with the `Co-Authored-By:` trailer that the executing session's commit attribution names. Do not push and do not open a PR: the orchestrator does that.
  </action>
  <verify>
    <automated>uv run pytest -q && uv run ruff check . && uv run ruff format --check . && grep -n "AppIcon.icon" docs/DAEMON.md && grep -n "DEVELOPER_DIR" docs/DAEMON.md && sed -n '/^## \[Unreleased\]/,/^## \[0/p' CHANGELOG.md | grep -n "### Added" && T="$(git ls-tree -r --name-only HEAD packaging/AppIcon.icon)" && SRC="$(cd /Users/andrei/Downloads/AppIcon.icon && find . -type f)" && diff <(printf '%s\n' "$T" | sed 's|^packaging/AppIcon.icon/||' | sort) <(printf '%s\n' "$SRC" | sed 's|^\./||' | sort) && F="$(git show --name-only --format= HEAD)" && ! printf '%s\n' "$F" | grep -q '^\.planning/' && SUBJ="$(git log -1 --format=%s)" && printf '%s\n' "$SUBJ" | grep -q '^feat(packaging): Liquid Glass app icon' && S="$(git status --porcelain --untracked-files=no -- packaging scripts tests docs CHANGELOG.md)" && test -z "$S" && echo COMMIT-OK</automated>
  </verify>
  <done>`uv run pytest`, `uv run ruff check .` and `uv run ruff format --check .` pass; `docs/DAEMON.md` names `packaging/AppIcon.icon`, the full-Xcode need and `DEVELOPER_DIR`; `CHANGELOG.md` `[Unreleased]` has the `### Added` bullet; HEAD on `feat/app-icon` is the one `feat(packaging)` commit with the 17 icon files, the plist, the script, the test, the doc and the changelog, and no `.planning/` path; nothing pushed.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| `~/Downloads` -> repo | The owner's Icon Composer file enters the public repo as data (JSON + SVG) |
| repo -> build Mac toolchain | `actool` (Xcode) parses `icon.json` and the SVGs at build time, as the build user |
| build -> signed bundle | Files in `Contents/Resources` are sealed by codesign; anything written after signing breaks the seal |
| lane -> public repo | Code, tests, docs, CHANGELOG and commit text become public after the PR |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-utn-01 | Tampering (foreign content enters the repo) | `packaging/AppIcon.icon` copied from `~/Downloads` | low | mitigate | The owner's own file, copied verbatim (`diff -r` gate in Task 1); the planner scan found only `icon.json` and 16 SVG files, no script, no hidden file, no external reference. The daemon never reads it: only `actool` parses it, at build time |
| T-utn-02 | Tampering (bundle seal broken) | icon compile step vs codesign in `scripts/build_app.sh` | medium | mitigate | The step sits after the bundle reset and before the `cp` of `Info.plist` and the signing block; `test_build_script_compiles_the_icon` pins that order; the build's existing `codesign --verify --strict` runs fail on any later write |
| T-utn-03 | Denial of service (build breaks on a Command-Line-Tools-only Mac) | actool resolution | medium | mitigate | The preflight resolves `ACTOOL` before any download and exits 2 with a message that names `packaging/AppIcon.icon`, says the Command Line Tools have no actool, and names `DEVELOPER_DIR`; `docs/DAEMON.md` states the need; the test pins the message and its position before `curl` |
| T-utn-04 | Denial of service (generic icon ships silently) | `--app-icon` name vs `CFBundleIconName` / `CFBundleIconFile` | low | mitigate | The build fails if `AppIcon.icns` or `Assets.car` is missing or empty; the tests pin `--app-icon AppIcon` and both plist keys equal to `AppIcon`; the Task 1 probe proves actool's partial plist matches `packaging/Info.plist` |
| T-utn-05 | Elevation of privilege (toolchain substitution) | `DEVELOPER_DIR` / `/Applications/Xcode.app` fallback | low | accept | The build runs on the owner's Mac with the owner's Xcode, as the build user; an attacker who can replace Xcode already controls the build. `DEVELOPER_DIR` is not exported, so codesign and notarytool keep the selected toolchain |
| T-utn-06 | Information disclosure | icon metadata, docs, CHANGELOG, commit | low | mitigate | The planner scan found no user name, home path or `file://` reference in the icon package; the docs name only the public Xcode default path |
| T-utn-SC | Tampering | npm/pip/cargo installs | high | mitigate | No package install in this plan: `actool` is part of the Xcode already installed, and `uv.lock` / `pyproject.toml` do not change |
</threat_model>

<verification>
cwd = lane root (`/Users/andrei/Developer/macos-apps-mcp/.worktrees/app-icon`):
- `uv run pytest`
- `uv run ruff check .`
- `uv run ruff format --check .`
- Task 1 actool probe prints `ICON-PROBE-OK`
- Task 2 commit gate prints `COMMIT-OK`

Not run: `scripts/build_app.sh` (it downloads two interpreters and takes minutes). The
string tests and the actool probe cover the new step; the next real build shows the icon
in Finder.
</verification>

<success_criteria>
- `packaging/AppIcon.icon` is tracked and byte-identical to the owner's file
- `packaging/Info.plist` names `AppIcon` in `CFBundleIconFile` and `CFBundleIconName`
- `scripts/build_app.sh` fails fast without actool, and compiles the icon into `Contents/Resources` at the pinned position with the plist's floor
- Three new tests in `tests/test_packaging.py` pass; the full suite, ruff check and ruff format check pass
- `docs/DAEMON.md` and `CHANGELOG.md` state the end state
- One `feat(packaging)` commit on `feat/app-icon`, no `.planning/` file in it, not pushed
</success_criteria>

<output>
Create `.planning/quick/261012-utn-ship-the-macos-app-icon-packaging-appico/261012-utn-SUMMARY.md` when done.
</output>
