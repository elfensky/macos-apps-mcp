---
phase: 04-notes-photos-settle-the-mechanism-then-ship-the-read-plane
plan: 01
subsystem: packaging
tags: [osxphotos, photos, uv, python-3.12, signed-bundle, universal2, pyobjc]

requires:
  - phase: 03-calendar-reminders-depth
    provides: signed universal2 build pipeline and the Developer ID bundle gates
provides:
  - osxphotos 0.77.2 as a locked base dependency (>=0.77.2,<0.78)
  - Python 3.12 floor (D-16) and pyobjc-framework-UniformTypeIdentifiers as a base dependency
  - build_app.sh drops osxphotos's thin libdisclaim dylibs and refuses a platform_release export
  - proof inside the signed bundle, on both slices, that PhotosDB opens, a photo reads back by id, and original and edited stills export
affects: [04-04 photos read plane, 04-05 photos export, 04-06 photos device sitting]

actuals:
  tokens: 14000
  tasks: 4
  commits: 2
plan_head_before: 3d2682c
plan_head_after: 52ac5a5

tech-stack:
  added: [osxphotos 0.77.2, pyobjc-framework-UniformTypeIdentifiers, cffi and pycparser now ship in the bundle]
  patterns: [signed-bundle gate before feature code, export guard against silently dropped platform_release markers]

key-files:
  created: []
  modified: [pyproject.toml, uv.lock, scripts/build_app.sh, tests/test_packaging.py, README.md, CHANGELOG.md, docs/DAEMON.md, CREDITS.md]

key-decisions:
  - "D-16 (owner, 2026-10-18): Python 3.12 floor; Python 3.11 support ends, 0.14.3 stays installable there"
  - "ruff target-version stays py311: py312 raises 5 UP047 findings that need code edits"
  - "AMFI count is taken from the start of a task's own bundle runs, not the plan's literal 15-minute window"

requirements-completed: [PHO-01]

coverage:
  - id: D1
    description: "osxphotos 0.77.x is a capped base dependency; no pin outside the five D-16 pairs moved"
    requirement: PHO-01
    verification:
      - kind: unit
        ref: "tests/test_packaging.py#test_osxphotos_is_a_capped_base_dependency"
        status: pass
    human_judgment: false
  - id: D2
    description: "The build drops the thin libdisclaim dylibs, refuses a platform_release export, and both smokes import osxphotos"
    requirement: PHO-01
    verification:
      - kind: unit
        ref: "tests/test_packaging.py#test_build_script_gates_universal2"
        status: pass
      - kind: integration
        ref: "scripts/build_app.sh --sign (7 log lines, exit 0)"
        status: pass
    human_judgment: false
  - id: D3
    description: "Inside the signed bundle on arm64 and x86_64: PhotosDB opens, a throwaway photo reads back by id exactly as written, original exports 320x240, edited exports 240x320"
    requirement: PHO-01
    verification:
      - kind: integration
        ref: ".worktrees/p04-gate.json (gate t1, t2, t4 ok)"
        status: pass
    human_judgment: false

duration: ~15min (Task 4 and landing; Tasks 1-3 ran in an earlier agent)
completed: 2026-10-18
status: complete
---

# Phase 4 Plan 01: osxphotos signed-bundle gate Summary

**osxphotos 0.77.2 is proven inside the signed Developer ID bundle on arm64 and x86_64 (import, PhotosDB open, read by id, original and edited export) and is a base dependency on develop through PR #370, bought with a Python 3.12 floor.**

## Performance

- **Duration:** about 15 min for this continuation (Task 4 and landing); Tasks 1-3 ran in an earlier agent
- **Completed:** 2026-10-18
- **Tasks:** 4 of 4
- **Files modified:** 8 in the PR (CHANGELOG.md, CREDITS.md, README.md, docs/DAEMON.md, pyproject.toml, scripts/build_app.sh, tests/test_packaging.py, uv.lock)

## Accomplishments

- osxphotos `>=0.77.2,<0.78` is a locked base dependency; the lock lost only the five D-16 pairs and gained 67.
- A real signed build logged all seven gate lines; the bundle imports osxphotos and opens the Photos library on both slices.
- One throwaway photo read back by id with every written field intact; its edited still (after one owner rotate) exports at 240x320.
- PHO-01 is on develop: PR #370 rebase-merged with the required `check` job green.

## Resolver output (D-01, D-02, D-16)

First run, plain `uv add 'osxphotos>=0.77.2,<0.78'` on `requires-python >=3.11`, stopped at the gate:

```
error: Failed to add dependencies
  cause: No solution found when resolving dependencies for split (markers: python_full_version == '3.11.*' and platform_release < '22' and sys_platform == 'darwin')
  cause: Because osxphotos>=0.77.2 depends on pyobjc-framework-cocoa{python_full_version < '3.12' and platform_release < '22' and sys_platform == 'darwin'}>=9.0,<10.0 and your project depends on osxphotos>=0.77.2, ...
         And because your project depends on pyobjc-framework-cocoa>=10.0, we can conclude that your project's requirements are unsatisfiable.
```

Second try, the marker route (`osxphotos{python_full_version >= '3.12' or platform_release >= '22'}`): the same split, the same error. uv cannot prove `platform_release >= 22` disjoint from `platform_release < 22`, so the `or` marker does not remove osxphotos from the fork.

Owner decision D-16, 2026-10-18: raise the floor to Python 3.12. D-16 run (`requires-python >=3.12`, 2026-10-18T13:40:39Z):

```
## uv add osxphotos
Resolved 151 packages in 439ms
 Installed 64 packages in 173ms
 + osxphotos==0.77.2
 + osxmetadata==1.4.1
 + photoscript==0.6.1
## uv add UniformTypeIdentifiers
Resolved 151 packages in 32ms
```

`uv_add_route`: `requires-python-3.12`. `uv.lock` revision stays 5.

## Pin result

The old lock minus the new lock is exactly the five D-16 pairs: backports-tarfile 1.2.0, importlib-metadata 9.0.0, tomli 2.4.1, zipp 4.1.0, cryptography 50.0.0 (`removed_pairs`). 67 pairs were added. No other pin moved. The export holds 0 `platform_release` lines.

## Gate table

| Check | arm64 | x86_64 |
|---|---|---|
| `import osxphotos` in the signed bundle | ok | ok |
| `import_osxphotos_cold_s` | 0.54 | 0.70 |
| `PhotosDB()` open (`photosdb_open_s`, median of 3) | 0.03 | 0.053 |
| db_version / photos_version | 5001 / 12 | 5001 / 12 |
| Read-back by id of the original (date, GPS, persons, camera, lens, exposure, ISO, size, flags) | match | match |
| Original export (`edited` false) | 320x240 | 320x240 |
| Edited read (width 240, height 320, `hasadjustments` true, `path_edited` set) | match | match |
| Edited export (`edited` true) | 240x320 | 240x320 |

Build: `universal2 gate ok`, `smokes ok: arm64`, `smokes ok: x86_64`, `entitlements ok`, `signed smoke ok: arm64`, `signed smoke ok: x86_64`, `built:`; exit 0; build stamp = 3561502, clean tree. `codesign --verify --strict` passed after every bundle run (`codesign_ok` true). `amfi_lines` 0.

Key numbers for later plans: `photosdb_open_s` 0.03 (arm64; 04-04 reads this), `import_osxphotos_cold_s` 0.54, `wal_mtime_moved_import` true, `wal_mtime_moved_edit` true.

**Race for 04-05.** Photos sets the edit flag first and writes `resources/renders/<X>/<uuid>_1_201_a.jpeg` after. The first read after the rotate (16:56) gave `hasadjustments` true and `path_edited` not set; a minute later `path_edited` was set. 04-05 must expect an edited photo whose render is not on disk yet.

## Owner sitting

Task 3: the owner answered "Rotated" on 2026-10-18, before 16:56 CEST. Nothing else was asked of the owner except the D-16 decision after the first gate stop.

## Task Commits

1. **Task 1 (tracer): resolver, build fix, signed build, import and PhotosDB on both slices** - `c051934` on develop (lane commit 3561502 before the rebase)
2. **Task 2: throwaway photo imported, read back by id, exported and opened** - no commit (git-ignored outputs)
3. **Task 3: owner rotates the photo** - no commit (owner action)
4. **Task 4: edited still exports; DAEMON.md and CREDITS.md; PR** - `52ac5a5` on develop (lane commit ee000c6 before the rebase)

PR #370 (rebase-merged). develop after the merge: 52ac5a5; before: 3d2682c.

## Decisions Made

- D-16 Python 3.12 floor, with the owner's decision of 2026-10-18; CHANGELOG states that Python 3.11 support ends and 0.14.3 stays installable.
- ruff `target-version` stays `py311`: `py312` raises 5 UP047 findings that need code edits. The setting and the new floor now differ; a later cleanup can move both.
- The export guard in `build_app.sh` refuses a `platform_release` marker, because `uv export` under `--python-platform` drops such a line and still exits 0.

## Deviations from Plan

### Plan defect

**1. [Plan defect] The AMFI window can never print 0.** The plan's literal `log show --last 15m` count always includes the build's own unsigned smokes. Task 1 literal count: 216 lines, all naming unsigned binaries (the unsigned smokes at 15:44:09-15:44:17, before codesign at 15:45:35-15:45:46, plus other unsigned venvs and homebrew tools on this Mac). Independent re-count by the orchestrator: 0 lines since signing finished at 15:45:47, and 90 bundle lines before it, all from the unsigned smokes. Task 4 counted from the start of its own bundle runs (16:59:32 CEST) over every process: 0. `amfi_lines` keeps that definition, with `amfi_note` in `p04-gate.json`.

### Plan amendment, recorded

**2. [Gate stop, resolved by the owner] First run stopped at the resolver.** Both resolver failures are quoted above. The owner decided D-16 on 2026-10-18; the plan was amended and rerun from Task 1.

### D-15 residue

Photos AppleScript cannot delete media items (Photos.sdef: `delete` applies to albums and folders only), so throwaway photos persist until the single owner sitting in 04-06 removes them and empties Recently Deleted — a bounded, owner-visible deviation from D-15's "removed after the test", closed when 04-06 Task 4's residue check reports zero `macos-apps-mcp-test-` items.

### Code review

The `code-review` skill needs a sub-agent tool that this executor did not have. The diff against origin/develop was reviewed inline against the plan and the project standards: no defect found. Test needles pin the dylib drop, the export guard, both smoke imports and the dependency cap. The orchestrator runs an independent review.

## Issues Encountered

- `gh pr merge --delete-branch` skipped the local branch delete because the worktree held it; the worktree and branch were removed by hand per the plan.
- The `bumped` CI job fails on a pyproject edit without a version bump and is not required (#330); no bump was made. The required `check` job passed (1m36s).

## Rebase

origin/develop moved to 3d2682c and later after the lane started. The rebase had no conflict; CHANGELOG.md kept the Notes entries and gained the Python 3.11 line. After the rebase: `uv run pytest -q` 2082 passed; `MACOS_APPS_READ_ONLY=1` 2070 passed, 12 skipped; `MACOS_APPS_ALLOW_SEND=mail` 2078 passed, 4 skipped; ruff check and format clean. The diff against origin/develop was the six code-plan files plus DAEMON.md and CREDITS.md.

## Deferred

The same gate on the Intel iMac runs only if the owner asks (RESEARCH Open Question 2).

## Kept for 04-06

Git-ignored in `.worktrees/`: `p04-gate.json`, `p04-test-photos.json`, `p04-gate-probe.py`. The photo and its album stay in the Photos library until 04-06. `p04-gate-dist` and the lane are removed.

## Next Phase Readiness

04-04 (Photos read plane) can read `photosdb_open_s` and build on the proven mechanism. 04-05 must handle the edit-render race above. No blockers.

## Self-Check: PASSED

PR #370 state MERGED; origin/develop holds `osxphotos>=0.77.2,<0.78`, the osxmetadata text in DAEMON.md, and CREDITS.md without "deferred and unused"; lane and `p04-gate-dist` are gone.

---
*Phase: 04-notes-photos-settle-the-mechanism-then-ship-the-read-plane*
*Completed: 2026-10-18*
