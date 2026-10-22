---
phase: 04-notes-photos-settle-the-mechanism-then-ship-the-read-plane
plan: 05
subsystem: photos
tags: [photos, osxphotos, export, files, additive-tool, integration-test]

requires:
  - phase: 04-notes-photos-settle-the-mechanism-then-ship-the-read-plane
    provides: "04-02 files module (per-caller cap); 04-04 photos_db seam, _uuid, _live"
provides:
  - "PhotosAdapter.export and PHOTO_MAX_BYTES (250 MiB)"
  - "export_photo additive tool (audit verb export, Full Disk Access, no dry_run, no snapshotter)"
  - "tests/integration/test_photos_integration.py: on-device read and export test that reuses a test photo"
affects: [04-06 photos device sitting]

actuals:
  tokens: 16000
  tasks: 3
  commits: 5
plan_head_before: a98caba
plan_head_after: 31136ac

tech-stack:
  added: []
  patterns: ["absent decided from the source file before the export, never from an empty result", "osxphotos call pinned by a keyword-set test"]

key-files:
  created: [tests/integration/test_photos_integration.py]
  modified: [macos_apps_mcp/adapters/photos.py, macos_apps_mcp/server.py, tests/test_photos.py, tests/test_registry.py, tests/test_tool_annotations.py, README.md, CHANGELOG.md]

key-decisions:
  - "status written with skipped 'live photo motion' is the agreed form of D-08's refusal of the motion part"
  - "An edited photo whose render is not on disk yet is absent with its own reason, not the iCloud text"

requirements-completed: [PHO-04]

coverage:
  - id: D1
    description: "export_photo writes the edited still, or the original when there is no edit, through files.target_path, check_size and confirm_written"
    requirement: PHO-04
    verification:
      - kind: unit
        ref: "tests/test_photos.py#test_export_photo_end_to_end_writes_the_original_into_the_root"
        status: pass
      - kind: unit
        ref: "tests/test_photos.py#test_export_photo_writes_the_edited_still_when_there_are_adjustments"
        status: pass
    human_judgment: false
  - id: D2
    description: "No download option reaches osxphotos; absent, video, overwrite, outside-root, cap, hidden and trashed cases refuse before any write"
    requirement: PHO-04
    verification:
      - kind: unit
        ref: "tests/test_photos.py#test_export_never_passes_a_download_option"
        status: pass
      - kind: unit
        ref: "tests/test_photos.py#test_export_photo_absent_when_path_set_but_file_missing"
        status: pass
    human_judgment: false
  - id: D3
    description: "Registry: additive, verb export, Full Disk Access, no snapshot, no dry_run, absent under READ_ONLY"
    requirement: PHO-04
    verification:
      - kind: unit
        ref: "tests/test_registry.py#test_gate06_verbs"
        status: pass
    human_judgment: false
  - id: D4
    description: "Real-library export through the installed daemon opens as the expected image"
    requirement: PHO-04
    human_judgment: true
    rationale: "Unit tests fake osxphotos; the integration file is only collected here; plan 04-06 runs it and proves the tool through the daemon"

completed: 2026-10-18
status: complete
---

# Phase 4 Plan 05: Photos export Summary

export_photo writes the edited still by id — PR #379, on develop at 31136ac.

**`export_photo(id, dest_dir)` writes one photo as a still image into the allowed root: the edited render when Photos holds an edit, the original otherwise. It does no network work, refuses before it writes, and verifies after.**

## Accomplishments

- `PhotosAdapter.export` runs on the native worker. Order: id check, library lookup (`_live`: trashed is unknown, hidden is refused), video refusal, `absent` decision from the source file, size check from `os.stat`, `files.target_path` (containment and no-overwrite refusal), the one osxphotos call, path verification, `files.confirm_written`.
- The osxphotos call receives `filename`, `edited`, `overwrite=False`, `increment=False` and nothing else. A test fails if `use_photos_export`, `use_photokit` or `download_missing` ever appears.
- `export_photo` is `@_additive_tool(audit="export", adapter="photos", permission="Full Disk Access")`, with no `dry_run` and no snapshotter. It is in `envelope_only`, `_DEVELOP_ADDITIVE`, `_DEVELOP_PERMISSION` and `test_gate06_verbs`, and it is absent under `MACOS_APPS_READ_ONLY=1`.
- The on-device test file collects 5 tests. Its fixture reuses a non-trashed photo in the album `macos-apps-mcp-test` whose original filename starts `macos-apps-mcp-test-`; it imports a new one only when none exists.

## Refusal texts (as shipped)

- Video (`WriteRefused`): `<uuid> is a video — export_photo writes still images only. Export videos from Photos. Do not retry.`
- Hidden id (`ValueError`, from `_live`, D-17): `photo <uuid> is in the Hidden album, which Photos keeps locked. Unhide it in Photos to use it here. Do not retry.`
- Trashed or unknown id (`ValueError`): `no photo with id <uuid> (unknown, or in Recently Deleted)`.
- Source file missing, result `status: absent`, reason: `the file is not on this Mac (iCloud only); nothing was downloaded`.
- Edited photo, render missing, original on disk, `status: absent`, reason: `the edited version is not on this Mac yet: Photos may still be rendering the edit (try again in a minute), or the edit is only in iCloud. Nothing was exported or downloaded`.
- Over the cap (`ValueError`, from `files.check_size`): `'<name>' is <n> bytes, larger than the 262144000-byte cap. Export it from Photos directly. Do not retry.`
- Wrong or empty osxphotos result (`VerificationFailed`): `osxphotos reported no file at <dest> for <uuid> — nothing was exported. [It wrote <path> instead.] Do not retry; check that Photos still holds the file.` The unexpected file is left alone.

## Task Commits

On develop after the rebase-merge of PR #379 (develop before: a98caba, after: 31136ac; `commits: 5` measured with `git rev-list --count a98caba..31136ac`):

1. **Task 1 RED:** `9054b95` test(photos): export_photo writes one photo through the shared files rules
2. **Task 1 GREEN (tracer):** `717d9d7` feat(photos): export_photo writes the edited still by id
3. **Task 2 tests:** `214eca7` test(photos): export_photo edges
4. **Task 3:** `e484173` test(photos): on-device read and export test; docs for export_photo
5. **Review follow-up:** `31136ac` refactor(photos): reason texts beside the cap; clean the filename in the cap refusal

## Verification

- Tracer gate (Task 1): the end-to-end test through FastMCP passed, the registry and annotation tables passed, and the full suite was green before Task 2 started.
- Final lane HEAD, local: `uv run pytest -q` 2175 passed, 102 deselected; `MACOS_APPS_READ_ONLY=1` 2162 passed, 13 skipped; `MACOS_APPS_ALLOW_SEND=mail` 2171 passed, 4 skipped; `ruff check` clean; `ruff format --check` 110 files formatted.
- `uv run pytest tests/integration/test_photos_integration.py -q` reports 5 deselected; `--collect-only -m integration` collects 5.
- Acceptance greps: `def export_photo` 1; `PHOTO_MAX_BYTES` 262144000; registry line `additive export None False`; READ_ONLY registered `False`; integration marker 1, `macos-apps-mcp-test` 3, `REUSED TEST PHOTO` 2, `NEW TEST PHOTO` 2.
- Task 2 selectors: `download_option` 1 passed; `absent_when_path_set_but_file_missing` 1 passed; `export and hostile` 1 passed; the absent/video/overwrite/outside/cap selector 9 passed; `-k export` 26 passed.
- CI: PR #379, required `check` job passed in 1m3s, then rebase-merged. `origin/develop:macos_apps_mcp/server.py` holds `def export_photo` (count 1). Lane unlocked and removed, branch deleted, main checkout fast-forwarded.
- T-04-SC: `git diff --name-only origin/develop` listed neither `pyproject.toml` nor `uv.lock`.
- Mutation check on the unit tests (not committed): changing `increment=False` to True, dropping the file-on-disk test, adding `use_photokit=True`, dropping the video refusal and forcing `edited=False` each made at least one export test fail.

## Code review

The `code-review` skill needs a sub-agent tool that this executor did not have. The diff `origin/develop...HEAD` was reviewed inline against the plan, PHO-04 and D-08..D-11, D-17. Two findings were fixed in `31136ac`: the original filename went uncleaned into the cap refusal text, and the two reason constants sat below the class. No open finding. The orchestrator runs an independent review.

## Deviations from Plan

### Recorded, not hidden

**1. [D-08 form] Live Photo.** `status: written` with `skipped: "live photo motion"` is the agreed form of D-08's refusal of the motion part: the still is exported, the motion is refused by omission and named in an explicit field.

**2. [Orchestrator note] Edit render not on disk yet.** 04-01 found that Photos sets `hasadjustments` first and writes the edited render up to a minute later. The plan pins one `absent` reason ("the file is not on this Mac (iCloud only)"). That text is wrong when the original is on disk. So when the photo has adjustments, `path_edited` is not a file and `path` is a file, the reason is the render-pending text above. In every other absent case the plan's text is unchanged. The rule still decides from the source, never from an empty result. A test covers it.

**3. [D-17] Hidden photos.** The orchestrator note added one export test for a hidden id (`test_export_photo_hidden_id_is_refused_with_the_unhide_directive`). The refusal comes from `_live`; `export_photo` goes through it.

**4. [D-15 residue]** Photos AppleScript cannot delete media items (Photos.sdef: `delete` applies to albums and folders only), so throwaway photos persist until the single owner sitting in 04-06 removes them and empties Recently Deleted — a bounded, owner-visible deviation from D-15's "removed after the test", closed when 04-06 Task 4's residue check reports zero `macos-apps-mcp-test-` items. The integration test reuses an existing test photo, so a repeated run adds none; it imports a new one only when the album holds none.

### Process notes

- **[TDD order] Task 2 has no separate fix commit.** Task 1's implementation already covered every flow the plan assigns to Task 2, so the 26 export tests passed on their first run and no source change followed. The tests were committed as one `test(...)` commit. Their value was shown by the mutation check above.
- **[Test defect, own tests]** The first kwargs-pin test read `filename` from the fake's named parameter instead of its keywords, so it failed once; the fake was changed to record `*args, **kw`.
- **[Style]** The Task 1 RED commit left one E501 in a test docstring; it is fixed in the next commit, so the PR tip is clean.
- **[Process] Project root pin.** The verbatim guard ran from a uniquely named scratchpad copy before the first write and before every commit; it printed `pin ok` each time.
- **[Process]** The `gsd-plan-head-before` ledger was not created; `plan_head_before` is `origin/develop` at lane creation (`a98caba`) and `commits: 5` was measured on merged develop.
- **[Process]** The integration test was only collected. Its Photos import script (`import ... into album ... skip check duplicates true`) was not compiled or run, by the rule never to open the real Photos library. 04-06 is its first run.

## Known Stubs

None.

## Threat Flags

None. T-04-18 to T-04-21 are mitigated and tested: the hostile-name test, the outside-root tests, the no-overwrite test (export never called), and the kwargs pin plus the absent-from-source tests. T-04-22 by the cap test; T-04-23 by the registry verb test.

## Self-Check: PASSED

PR #379 state MERGED; `origin/develop` holds `def export_photo` (count 1); commits 9054b95, 717d9d7, 214eca7, e484173 and 31136ac are on develop; lane directory absent; local branch deleted. Vault journal bullet logged (MR 1613 in the vault repo).

---
*Phase: 04-notes-photos-settle-the-mechanism-then-ship-the-read-plane*
*Completed: 2026-10-18*
