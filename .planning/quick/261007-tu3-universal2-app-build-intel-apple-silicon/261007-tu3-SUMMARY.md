---
phase: quick-261007-tu3
plan: 01
subsystem: packaging
tags: [build, universal2, intel, macos-floor, cryptography]
status: complete
requires: []
provides:
  - universal2 daemon .app build (arm64 + x86_64) with a universal2/minos gate before signing
  - LSMinimumSystemVersion 15.0 as the single floor source in packaging/Info.plist
affects: [scripts/build_app.sh, packaging/Info.plist, release checklist]
tech-stack:
  added: [pinned python-build-standalone CPython 3.14.5 (20260510), sha256-checked]
  patterns: [per-arch locked wheel trees merged with lipo, per-slice smokes under arch(1)]
key-files:
  created: []
  modified:
    - scripts/build_app.sh
    - packaging/Info.plist
    - tests/test_packaging.py
    - docs/DAEMON.md
    - docs/RELEASING.md
    - CHANGELOG.md
decisions:
  - "D-01: LSMinimumSystemVersion 15.0 (device-verified 15.6.1 / 15.7.9); code needs 14"
  - "D-02: cryptography, cffi, pycparser pruned from the .app; uv.lock unchanged"
  - "D-03: no --src option, no pkg= stamp suffix; universal builds start at 0.14.2"
  - "D-04: build_app.sh reads the floor from Info.plist with plutil into MACOS_MIN"
requirements: [ISSUE-205]
metrics:
  duration: 383s
  completed: 2026-10-07
commits: 2
plan_head_before: 0c60f439381c8f44f373adfdc7f68b780cf91451
plan_head_after: f7cbd3c21a68af5916d28ed2f033f5d801287fa5
actuals:
  tokens: 3829
  tasks: 2
  commits: 2
---

# Quick 261007-tu3: universal2 .app build (Intel + Apple silicon) Summary

`scripts/build_app.sh` builds one universal2 `.app` from a sha256-pinned python-build-standalone
interpreter and per-arch locked wheels. It reads the macOS 15.0 floor from
`packaging/Info.plist`, prunes cryptography, and gates every Mach-O on `x86_64 arm64` and
minos <= floor before signing.

## Commits

| Task | Commit | Subject |
|------|--------|---------|
| 1 | a66d980 | build: universal2 .app (arm64 + x86_64), macOS 15 floor, no cryptography (#205) |
| 2 | f7cbd3c | docs: universal2 build, macOS 15 floor, cryptography-free .app (#205) |

## TDD gate compliance

- RED (tests only, before the script and plist edits): `uv run pytest -q tests/test_packaging.py`
  gave `2 failed, 4 passed` — `test_info_plist_contract` (KeyError `LSMinimumSystemVersion`)
  and `test_build_script_gates_universal2` (AssertionError
  `plutil -extract LSMinimumSystemVersion raw`).
- GREEN: `6 passed`. ruff check and ruff format --check on the test file are clean.
- The RED and GREEN states share one commit (a66d980), as the plan specifies one commit per task.

## Build evidence (unsigned, Apple-silicon host, `PBS_CACHE` = scratch cache)

- Command: `PBS_CACHE=<cache> bash scripts/build_app.sh --out <scratch>/universal/exec-build`
- Exit code 0, wall time 72 s.
- Log lines:
  - `stream smoke ok` (twice)
  - `smokes ok: arm64`
  - `smokes ok: x86_64`
  - `universal2 gate ok: every Mach-O is x86_64 arm64, minos <= 15.0`
- Mach-O files: 158. Highest minos: arm64 11.0, x86_64 10.15.
- Main executable `lipo -archs`: `x86_64 arm64`. Built Info.plist `LSMinimumSystemVersion`: 15.0.
- site-packages has no cryptography, cffi or pycparser. `uv.lock` equals origin/develop.
- Bundle size: 194M. Build stamp: `0c60f43-dirty 2026-10-07T19:37:31Z` (dirty is expected:
  the build ran before the commit).
- The built `.app` was deleted; the log is kept at `<scratch>/universal/exec-build.log`.

## Full verification

| Check | Exit | Result |
|-------|------|--------|
| `uv run pytest -q` | 0 | 1937 passed, 97 deselected |
| `MACOS_APPS_ALLOW_SEND=mail uv run pytest -q` | 0 | 1933 passed, 4 skipped, 97 deselected |
| `uv run ruff check .` | 0 | All checks passed |
| `uv run ruff format --check .` | 0 | 109 files already formatted |

## Deviations from Plan

None in code or docs; the plan was executed as written.

Long lines: seven lines in `scripts/build_app.sh` exceed 88 columns. All seven come from the
draft unchanged, which the plan allows. No new line exceeds 88 columns.

## Deferred Issues

- `scripts/smoke_stream.py` sometimes logs `asyncio.exceptions.InvalidStateError` from a
  `Future.set_result()` callback during teardown. The build log shows it once on the arm64
  slice. Five repeat runs per slice gave it 2/5 on arm64 and 0/5 on x86_64, and 1/3 in the dev
  venv (`uv run python scripts/smoke_stream.py`). Every run exits 0 and prints `stream smoke ok`.
  The trace also occurs in the dev venv, so this change did not cause it. It is a pre-existing
  teardown race in the smoke client and is out of scope.

## Threat Flags

None. The new download (the PBS interpreter) is sha256-pinned per T-tu3-01. Wheels install
with `--require-hashes --no-deps --no-build` per T-tu3-02.

## Known Stubs

None.

## Self-Check: PASSED

- scripts/build_app.sh, packaging/Info.plist, tests/test_packaging.py, docs/DAEMON.md,
  docs/RELEASING.md, CHANGELOG.md: present and modified in the commits.
- a66d980 and f7cbd3c: ancestors of HEAD. Both subjects end `(#205)` and both carry the trailer.
- No `.planning/` path in the commits. Nothing pushed.

## Orchestrator close-out (2026-10-08)

- Operator decisions: floor macOS 15 (code needs 14); cryptography left out; universal from 0.14.2 (0.14.1 not rebuilt, so no --src/pkg=); Intel signing exception on the x86_64 slice ONLY.
- Signed x86_64 slice hung under the hardened runtime: libffi has no x86_64 trampoline pages. Verified (2-agent workflow + independent verifier) that the python.org and BeeWare Pythons (Apple's libffi; same binary) hang the same way, and that PyObjC itself needs W+X on x86_64; a per-slice signed bundle ran both slices.
- Build: sign the bundle once per entitlement set, `lipo` the matching main-executable slices; gate = exact per-slice entitlement sets (x86_64 = strict + one key) + runtime flag; signed smoke loads the server and allocates a ctypes closure on both slices.
- `plutil -insert` failed on the dotted key (key path) — PlistBuddy instead; caught before any signing.
- Developer ID + notarization of d134479: Accepted, no issues; stapled; spctl "Notarized Developer ID". Final head 66800f9 signed: all gates green, clean stamp.
- Two adversarial reviews applied (exact entitlement gate; sha256 before caching; preflight; NUL-separated gate; non-vacuous tests). PR #308. Verification: 1938 passed; 1934 / 4 skipped with send; ruff clean.
- Not verified: an Intel CPU; macOS 15 on a device for this build. Rosetta 2 installed on the build Mac 2026-10-07 (operator OK).
