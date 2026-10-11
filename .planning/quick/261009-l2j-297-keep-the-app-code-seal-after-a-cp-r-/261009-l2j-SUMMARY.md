---
phase: quick-261009-l2j
plan: 01
status: complete
commits: 2
plan_head_before: 241db7f
plan_head_after: c87a8ab
---

# Quick 261009-l2j: the .app keeps its code seal after a cp -R install (#297)

Branch `fix/297-pyc-seal`, base 241db7f, two commits, nothing pushed. (origin/develop has moved ahead since the base; the branch needs a rebase at PR time.)

- eaaaa6b `fix(build): hash-based .pyc so a cp -R install keeps the code seal (#297)`: `scripts/build_app.sh`, `tests/test_packaging.py`
- c87a8ab `docs: install the .app with ditto; changelog for the cp -R seal fix (#297)`: `docs/DAEMON.md`, `CHANGELOG.md`

## Timing (arm64, bundle interpreter, 16 rounds interleaved: first run + 15 warm, ms)

| mode | first | warm median | warm p90 | delta vs timestamp |
|---|---|---|---|---|
| timestamp | 1087.8 | 679.5 | 743.5 | +0.0 (0.0%) |
| checked-hash | 795.5 | 726.8 | 792.5 | +47.4 (+7.0%) |
| unchecked-hash | 760.6 | 676.2 | 725.4 | -3.2 (-0.5%) |

`REWRITES timestamp=0 checked-hash=0 unchecked-hash=0`. Rule (fixed before measuring): checked-hash if its warm median is at most 10% above unchecked-hash. `RULE delta_ms=50.6 pct=7.5`, `CHOICE checked-hash`.
Trade-off: checked-hash hashes each imported source at start but honours an edited source; unchecked-hash would silently ignore an edited .py (in a signed bundle any edit already breaks the seal).
Not measured: x86_64 under Rosetta, a true cold start (no `sudo purge`).

## Deviation: a second .pyc family (Rule 3, approved by the orchestrator)

The plan said only `*.cpython-314.pyc` is loaded. Wrong: fastmcp's `key_value` calls `beartype.claw.beartype_this_package()`, and beartype's hook writes its own `*.cpython-314.opt-beartype0v22v9.pyc` (31 files) as timestamp .pyc during the unsigned smokes. compileall never touches them. First build B (compileall only) failed: `RESULT B pre=0 ping=0 post=1 newer_pyc=31 newer_files=31`.
Fix: a generic step in `build_app.sh` after compileall, before signing, on the bundle interpreter. It converts every timestamp-based `.pyc` that has a source to checked-hash (`_code_to_hash_pyc` layout), refuses a stale one or an unreadable source (`HASH PYC CONVERSION FAILED`), and keeps sourceless ones. It does not name beartype. Build log: `hash pyc ok: 31 converted, 0 timestamp left (0 sourceless kept)`.
Why not `-B` in the daemon argv: the client-spawned shim runs the same bundle and would still write, and the LaunchAgent argv is a pinned contract.

## Proofs (plain `cp -R`, private socket, first daemon run, `ping` answered)

- A (control, unedited script): `RESULT A pre=0 ping=0 post=1 newer_pyc=1333 newer_files=1333`; `a sealed resource is missing or invalid`.
- B (fixed, eaaaa6b): `RESULT B pre=0 ping=0 post=0 newer_pyc=0 newer_files=0`; post-run `valid on disk` / `satisfies its Designated Requirement`.
- `MODES dist-new/macos-apps-mcp.app total=3980 timestamp=0 unchecked-hash=0 checked-hash=3980 other=0` (every `*.pyc`, including the 31 opt-* files).

## Checks

RED: `tests/test_packaging.py::test_build_script_compiles_hash_pyc` failed on the unedited script (7 others passed), then passed. It now also pins the conversion step: after `-m compileall`, before signing, gate message present.
Final: `uv run pytest -q` rc=0; `MACOS_APPS_ALLOW_SEND=mail uv run pytest -q` rc=0; `ruff check .` rc=0; `ruff format --check .` rc=0. Unit tests: 1939 (97 integration deselected).

## Safety

Live socket and `/Applications` CodeResources: `live-before.txt` equals `live-after.txt`. No scratch daemon left, scratch builds and `/tmp/m297` removed, logs and scripts kept in the scratchpad `297/`.

## Follow-ups (not done)

- `ditto` merges into an existing bundle; a reinstall should remove the old bundle first (DAEMON.md now says to move it away).
- Finder-drag and `ditto` installs of build B were not re-run (hash .pyc do not depend on file times).
- The conversion step's stale-pyc gate path has no unit test (it is a build-time gate).

## PR text

Title: `fix(build): keep the .app code seal after a cp -R install (#297)`

Cause: `cp -R` gives every file a new mtime, so timestamp .pyc read as stale and the daemon rewrote them inside the signed bundle on its first run, breaking `codesign --verify --strict`.

Fix: the build compiles hash-based .pyc (`compileall -f --invalidation-mode checked-hash`, `-f` because the smokes already wrote timestamp .pyc) and converts every remaining timestamp .pyc that has a source, including the `opt-*` caches that beartype's claw hook writes under fastmcp's key_value, then fails the build if any is left. DAEMON.md installs with `ditto`; CHANGELOG narrows the 0.14.0 seal claim to ditto, Finder-drag and zip installs.

Numbers (arm64, 15 warm runs, interleaved): timestamp 679.5 ms, checked-hash 726.8 ms (+7.0%, +47 ms), unchecked-hash 676.2 ms warm median. Rule set before measuring: checked-hash if within 10% of unchecked-hash; result +7.5%. Trade-off: checked-hash hashes each imported source per start but honours edits; unchecked-hash would ignore an edited .py.

Proof: unedited build, plain `cp -R`, first daemon run: seal valid before, broken after (1333 .pyc rewritten). Fixed build, same procedure: valid before and after, 0 files written, `ping` answered.

Closes #297

Merge only after v0.14.3 is cut.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
