---
phase: 04-notes-photos-settle-the-mechanism-then-ship-the-read-plane
plan: 06
subsystem: photos
tags: [photos, osxphotos, daemon, device-proof, signed-bundle, cleanup]

requires:
  - phase: 04-notes-photos-settle-the-mechanism-then-ship-the-read-plane
    provides: "04-01 signed bundle with osxphotos and the test photo; 04-04 read plane; 04-05 export_photo and the integration test"
provides:
  - "Device proof of PHO-01..PHO-04 through the installed daemon (develop build f877989)"
  - "Zero-residue cleanup: the D-15 residue deviation of 04-01 and 04-05 is closed"
affects: [phase-04 verification, release cut]

actuals:
  tokens: 0
  tasks: 4
  commits: 0
plan_head_before: f877989
plan_head_after: f877989

tech-stack:
  added: []
  patterns: ["device proof through the bundle shim (fastmcp StdioTransport), results stored as booleans and sizes only"]

key-files:
  created: []
  modified: []

key-decisions:
  - "COVERAGE.md stays unchanged: every INTEGRATE row has evidence"
  - "The develop build stays installed; the previous bundle stays in app-backup for a rollback"

requirements-completed: [PHO-01, PHO-02, PHO-03, PHO-04]

coverage:
  - id: D1
    description: "Photos read plane (photos, photo_albums, photo_info by old id) works under the installed daemon's own Full Disk Access"
    requirement: PHO-02
    verification:
      - kind: other
        ref: ".worktrees/p04-client.py through the bundle shim: doctor, photo_info, photos, photo_albums (p04-device.json)"
        status: pass
    human_judgment: false
  - id: D2
    description: "export_photo writes the edited still (240x320), refuses a second identical export, and is audited as export"
    requirement: PHO-04
    verification:
      - kind: other
        ref: ".worktrees/p04-client.py export_photo, sips, audit (p04-device.json)"
        status: pass
      - kind: integration
        ref: "tests/integration/test_photos_integration.py (5 tests, 0 failures, 0 errors, 0 skipped)"
        status: pass
    human_judgment: false
  - id: D3
    description: "No test photo, trash item, album or export directory is left in the owner's library"
    verification:
      - kind: other
        ref: "photos search empty; osxphotos live+trash count 0; photo_albums without the test album; no Downloads directory (p04-device.json)"
        status: pass
    human_judgment: false

duration: 2 sessions
completed: 2026-10-19
status: complete
---

# Phase 4 Plan 06: Photos device proof Summary

**Photos proven through the installed signed daemon (develop build f877989): search, albums, metadata by old id, edited-still export 240x320, refusal and audit; the owner emptied the test photos and the script deleted the album, so zero residue is left.**

## Performance

- **Tasks:** 4 of 4
- **Commits:** 0 (no code lane; the build used a detached worktree, now removed)
- **Files modified in the repo:** 0

## Accomplishments

- Signed build of `origin/develop` (f877989): smokes and signed smokes passed on arm64 and x86_64. `codesign --verify --strict` passed before the kickstart and again after the run.
- Installed as the daemon. The previous bundle is at `~/.local/state/macos-apps-mcp/app-backup/macos-apps-mcp-0.14.3-85a3baf.app`.
- `doctor` through the daemon: build `f877989 2026-10-18T16:30:48Z`, mode daemon, 11 surfaces, no Photos Automation surface (D-07), Full Disk Access ok.
- `photo_info` by the old `<UUID>/L0/001` id: kind photo, edited true, 240x320, camera make, taken date and latitude as written.
- `photos` search found the test photo. `photo_albums` listed the test album.
- `export_photo` wrote the edited still, `sips` read it as 240x320, a second identical call was refused (`already exists`), and the newest `audit` entry was `export_photo` with op `export`.
- Integration test on this Mac: 5 tests, 0 failures, 0 errors, 0 skipped. It printed `REUSED TEST PHOTO`, so the ledger did not grow.

## Device results (p04-device.json)

| key | result |
|---|---|
| build_sha / installed_build | f877989 / f877989 2026-10-18T16:30:48Z |
| doctor | mode daemon, 11 surfaces, photos_surface false, fda_ok true |
| photo_info_via_daemon | all 8 checks true |
| search_finds_gate_photo | true |
| album_listed | true |
| export_edited_wh | 240 x 320 |
| second_export_refused | true |
| export_audited | true |
| integration | 5 tests, 0 failures, 0 errors, 0 skipped |
| cleanup_search_empty | true |
| cleanup_trash_empty | true (live 0, in trash 0, prefix `macos-apps-mcp-test-`) |
| album_deleted | true (`osascript`, no Automation prompt, exit 0) |
| seal_after_run | true (codesign strict, satisfies its Designated Requirement) |

## Owner sitting

- Install decision: answer "install", 2026-10-19 before 11:32 CEST. Shown: built 0.14.3 / f877989 against installed 0.14.3 / 85a3baf, the daemon replacement and kickstart, and the rollback.
- Cleanup decision: answer "deleted", 2026-10-19 13:54 CEST. 1 photo was shown to the owner. One clarification: a plain album delete leaves the photo in Recently Deleted. The orchestrator measured 1 item left in Recently Deleted and asked once more. The owner emptied it, and the count then read live 0, in trash 0.

D-15 residue deviation closed: zero `macos-apps-mcp-test-` items (search, trash included, album and export directories all empty).

## COVERAGE outcome

Unchanged. Every INTEGRATE row has evidence: library-open, albums-list, photo-search, photo-by-id, dates, location, EXIF subset, edited flag and export-edited-still are proven by the daemon checks above. Persons and the remaining kind flags (video, Live Photo, in trash, file on disk) are proven by the 04-04 and 04-05 unit tests (22-key whitelist, trashed id refused, Live Photo motion skipped, absent decided before export). No row was edited to OPT-OUT.

## Task Commits

None. No repo change in this plan.

## Decisions Made

None beyond the plan. The develop build stays installed.

## Deviations from Plan

### Auto-fixed Issues

None - plan executed as written, with two notes.

- Task 3 needed a second owner step. The first pass moved the photo out of the album only. The Recently Deleted step ran after the measurement of 1 left item. This follows the plan's rule for a non-zero trash count (return to the owner once, then repeat).
- Issue #96 was already CLOSED when this plan ran (closed 2026-10-18T01:58:05Z, before the device proof). `gh issue close` therefore added no comment. The close comment was posted with `gh issue comment`: https://github.com/elfensky/macos-apps-mcp/issues/96#issuecomment-6266628446

## Issues Encountered

None.

## #96 comment

Posted: https://github.com/elfensky/macos-apps-mcp/issues/96#issuecomment-6266628446. It lists plan PRs #370, #364, #365, #374, #379; review fixes #369, #375, #378, #381; decisions #368 (D-16) and #377 (D-17); and the device results as booleans and sizes.

## Known Stubs

None.

## User Setup Required

None.

## Next Phase Readiness

All four Phase 4 plans' device claims are observed on the installed daemon. Phase 4 can go to verification. A release cut stays the operator's call.

---
*Phase: 04-notes-photos-settle-the-mechanism-then-ship-the-read-plane*
*Completed: 2026-10-19*

## Self-Check: PASSED
