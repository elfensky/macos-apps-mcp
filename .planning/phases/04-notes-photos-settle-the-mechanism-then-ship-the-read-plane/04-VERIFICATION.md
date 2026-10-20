---
phase: 04-notes-photos-settle-the-mechanism-then-ship-the-read-plane
verified: 2026-10-20T11:09:40Z
status: passed
score: 66/66 must-haves verified
covered_files:
  - ".planning/phases/04-notes-photos-settle-the-mechanism-then-ship-the-read-plane/04-01-PLAN.md"
  - ".planning/phases/04-notes-photos-settle-the-mechanism-then-ship-the-read-plane/04-01-SUMMARY.md"
  - ".planning/phases/04-notes-photos-settle-the-mechanism-then-ship-the-read-plane/04-02-PLAN.md"
  - ".planning/phases/04-notes-photos-settle-the-mechanism-then-ship-the-read-plane/04-02-SUMMARY.md"
  - ".planning/phases/04-notes-photos-settle-the-mechanism-then-ship-the-read-plane/04-03-PLAN.md"
  - ".planning/phases/04-notes-photos-settle-the-mechanism-then-ship-the-read-plane/04-03-SUMMARY.md"
  - ".planning/phases/04-notes-photos-settle-the-mechanism-then-ship-the-read-plane/04-04-PLAN.md"
  - ".planning/phases/04-notes-photos-settle-the-mechanism-then-ship-the-read-plane/04-04-SUMMARY.md"
  - ".planning/phases/04-notes-photos-settle-the-mechanism-then-ship-the-read-plane/04-05-PLAN.md"
  - ".planning/phases/04-notes-photos-settle-the-mechanism-then-ship-the-read-plane/04-05-SUMMARY.md"
  - ".planning/phases/04-notes-photos-settle-the-mechanism-then-ship-the-read-plane/04-06-PLAN.md"
  - ".planning/phases/04-notes-photos-settle-the-mechanism-then-ship-the-read-plane/04-06-SUMMARY.md"
  - ".planning/phases/04-notes-photos-settle-the-mechanism-then-ship-the-read-plane/04-CONTEXT.md"
  - ".planning/phases/04-notes-photos-settle-the-mechanism-then-ship-the-read-plane/04-UAT.md"
  - ".planning/phases/04-notes-photos-settle-the-mechanism-then-ship-the-read-plane/COVERAGE.md"
  - "CHANGELOG.md"
  - "README.md"
  - "docs/notes-semantic-search.md"
  - "macos_apps_mcp/adapters/mail.py"
  - "macos_apps_mcp/adapters/mail_attachments.py"
  - "macos_apps_mcp/adapters/notes.py"
  - "macos_apps_mcp/adapters/photos.py"
  - "macos_apps_mcp/doctor.py"
  - "macos_apps_mcp/files.py"
  - "macos_apps_mcp/runtime.py"
  - "macos_apps_mcp/server.py"
  - "pyproject.toml"
  - "scripts/build_app.sh"
  - "tests/conftest.py"
  - "tests/integration/test_photos_integration.py"
  - "tests/test_files.py"
  - "tests/test_native_seam.py"
  - "tests/test_notes.py"
  - "tests/test_packaging.py"
  - "tests/test_photos.py"
  - "tests/test_registry.py"
  - "tests/test_tool_annotations.py"
  - "uv.lock"
covered_digest: "v3:sha256:385fe06c0d49780ded59b503dd8495b4ffb3a2051d4ecc4f1c5c3e778ca02925"
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: human_needed
  previous_score: 66/66
  gaps_closed: []
  gaps_remaining: []
  regressions: []
  human_verification_resolved:
    - "HV-1 (04-01/P1): pass, owner, 04-UAT.md test 1"
    - "HV-2 (04-01/P2): pass, owner, 04-UAT.md test 2"
    - "HV-3 (04-06/P1): pass, owner, 04-UAT.md test 3"
    - "HV-4 (04-06/P2, P3): pass, owner, 04-UAT.md test 4"
advisory:
  - finding: "The installed daemon (build stamp f877989) predates PR #385 and PR #386. The staged export (files.staging, files.publish) and the #385 fixes are on develop 106ffb6 but are not live until the .app is rebuilt and reinstalled."
    category: other
    reason: "Not a Phase 4 must-have: the 04-06 install truth names the build with 04-01 to 04-05 merged, and that build is installed and sealed. The owner decided on 2026-10-20 to rebuild and reinstall after this fix."
    evidence_status: "observed: installed build_stamp f877989; the installed files.py has no staging function; codesign --verify --strict ok"
  - finding: "The staged export path of #386 and the IN-07 integration fixture of #385 have not run on device. The hard-link publish depends on the root volume (APFS or HFS+)."
    category: other
    reason: "Unit tests cover the race, symlink, case-variant, failure-cleanup and no-hard-link cases, and each fails when its fix is removed. A device run after the rebuild closes the advisory."
    evidence_status: "none provided (verification hard rule: no -m integration, no Photos access)"
---

# Phase 4: Notes & Photos — Settle the Mechanism, Then Ship the Read Plane Verification Report

**Phase Goal:** The two adapters whose mechanism is still open are settled on device before any feature code; what survives the probe ships as a bounded read plane, what does not ships as a documented gap.
**Verified:** 2026-10-20T11:09:40Z
**Status:** passed
**Re-verification:** Yes (after #386)

## Verdict summary

The phase goal is achieved in the merged code on `origin/develop` (106ffb6). PR #386
(580182c, 46ca884, 106ffb6) changes `export_photo`: osxphotos now writes into a private
staging directory beside the destination (`files.staging`), and the result is published
with `os.link` (`files.publish`). The link fails on any entry at the destination, so the
export never overwrites and never writes through a symlink. Cleanup deletes only inside the
staging directory. The generic `dest.unlink` and the WR-02 before-listing cleanup are gone.
New limit: the allowed root must support hard links; otherwise the call raises a typed
`NativeError` and writes nothing at the destination.

#386 causes no regression. The full unit suite passes in a scratch copy of develop 106ffb6
(2199 passed, 102 deselected). Lint and format are clean. Three mutation checks confirm that
the new tests bite (see Behavioral Spot-Checks).

All 66 must-haves (5 ROADMAP success criteria and 61 PLAN truths) remain verified. There are
0 gaps and 0 debt markers. The 4 human-verification items of the previous report (5
judgment-tier process prohibitions) are resolved: the owner confirmed all 4 in
`04-UAT.md` (status `complete`, 4/4 pass, 2026-10-20 13:05 CEST). The human-verification
section is therefore empty, and the status is `passed`.

The owner also decided on 2026-10-20: D-17 (hidden photos stay locked) is kept, and the
daemon is rebuilt and reinstalled after this fix. The installed daemon is still f877989; that
is an advisory, not a must-have.

**eli14.** Before, the export crew carried the photo straight to its spot on the shelf. If
another crew put something on that spot in the same second, our crew could crush it, or
follow a sign on the spot that pointed off the shelf. Now our crew builds the delivery in its
own locked back room and then hangs it on the shelf with one hook that only fits an empty
spot. If the spot is taken, the hook does not fit, and the crew says so. It only ever tidies
its own back room, never the shelf. One new limit: the hook needs a shelf that takes hooks
(APFS or HFS+ disks do; exFAT and FAT sticks do not), and on other shelves the crew refuses
clearly. Today, nothing changes for the installed app: it is still the old build until the
owner rebuilds and reinstalls it, which is already decided.

## Re-verification: what PR #386 changed

| Covered must-have | Code (develop 106ffb6) | Named test (passes; fails with the fix removed) | Status |
|---|---|---|---|
| D-08 edited still, original otherwise; name `<stem>_<id8><suffix>` | `edited = bool(p.hasadjustments)`, `src = path_edited or path`, `edited=edited` to osxphotos; name built and checked by `files.target_path` as before | `test_export_photo_writes_the_edited_still_when_there_are_adjustments`, long-name test | ✓ VERIFIED |
| D-08 video refused, Live Photo still plus `skipped` | unchanged; refusal before any file work, `skipped: live photo motion` | video and Live Photo tests | ✓ VERIFIED |
| D-09 absent, no download; exactly 4 export kwargs | source checks unchanged; the call still gets only `filename`, `edited`, `overwrite=False`, `increment=False`; only the directory argument changes (the staging directory) | `test_export_never_passes_a_download_option` (now also asserts the directory is a `.macos-apps-mcp-export-` directory beside dest) | ✓ VERIFIED |
| D-10 additive, audit `export`, no `dry_run`, no snapshotter | `server.export_photo` unchanged: `@_additive_tool(audit="export", adapter="photos", permission="Full Disk Access")`, signature `(id, dest_dir)` | `test_export_photo_is_an_additive_audited_export_without_dry_run_or_snapshot`, `test_gate06_verbs`, registry and annotation tests | ✓ VERIFIED |
| D-11 shared files rules (outside root, existing target before osxphotos, size cap, 0-byte removal, hostile name) | `files.target_path`, `files.check_size`, `files.confirm_written` still used; two new shared helpers `files.staging` and `files.publish` live in `files.py`, not in the adapter | `tests/test_files.py`; `test_export_photo_a_zero_byte_result_is_removed_and_reported` (nothing published, staging gone) | ✓ VERIFIED |
| Never overwrite (prohibition "osxphotos never names, increments or overwrites") | `files.publish` uses `os.link`; `FileExistsError` becomes `files.exists_refusal(dest)` | `test_export_photo_a_file_another_writer_lands_at_dest_is_never_overwritten`, `..._a_symlink_at_dest_is_never_written_through`, `..._a_case_variant_at_dest_is_never_overwritten` | ✓ VERIFIED (behavioral) |
| Failure cleanup removes only this call's file | the generic `except` raises `NativeError` without any unlink; `staging` removes its own directory on exit | `test_export_photo_a_failing_export_never_deletes_another_writer_s_file` (export-error, enospc); `..._a_failing_export_leaves_no_file_and_raises_typed` | ✓ VERIFIED (behavioral) |
| A written path other than the target raises `VerificationFailed` | `got != staged` raises; a file in the staging directory goes with it ("removed"), a path elsewhere stays ("that file stays") | `test_export_photo_a_different_written_path_is_a_verification_failure` (private, dest-dir, dest-dir-case-variant, outside) | ✓ VERIFIED |
| Audit shape `{id, status: written, path, bytes, edited, dest_dir}` (+ `skipped`) | same 6 keys; `bytes` comes from `confirm_written(staged)`, which is the same inode as dest after the link | `test_export_photo_end_to_end_writes_the_original_into_the_root` (exact dict, one file in dest, `st_nlink == 1`, staging gone) | ✓ VERIFIED |
| Runs on the native worker (D-06) | the whole `work()` still runs inside `runtime.run_native` | `*_on_the_native_worker` tests | ✓ VERIFIED |
| New limit: no hard links, or the directory refuses a new entry | `publish` maps `OSError` to `NativeError` naming hard links; `staging` maps a `mkdtemp` failure to `NativeError` ("cannot write in") | `test_export_photo_a_volume_that_refuses_the_write_is_typed` (no-hard-links, unwritable-dir) | ✓ VERIFIED |

`shutil.rmtree(..., onexc=...)` needs Python 3.12 or later. `requires-python` is `>=3.12`
(D-16), and the bundle builds on Python 3.14 (`scripts/build_app.sh`, `PYVER=3.14`).

The #386 change replaces the CR-01 and WR-02 code of #385 with one mechanism. The CR-01
test is renamed and widened (the fake export now copies with `shutil.copy`, like osxphotos
0.77.2), and the WR-02 test cases now include a case variant. The previous Info finding
("`dest.unlink` after a non-`FileExistsError` osxphotos failure") is closed.

## Goal Achievement

### ROADMAP Success Criteria

| # | Success criterion | Status | Evidence |
|---|---|---|---|
| SC1 | `uv add osxphotos` runs first; the resolver output decides the plane; osxphotos adopted and the stale pyproject note corrected | ✓ VERIFIED | Unchanged by #385 and #386 (`pyproject.toml`, `uv.lock` not in either diff). `osxphotos>=0.77.2,<0.78` in `[project] dependencies`; 04-01 SUMMARY quotes the resolver runs and the D-16 run. |
| SC2 | Albums list as Pointers; a photo's metadata reads back bounded by id; no thumbnails, no inline bytes, no library dump | ✓ VERIFIED | Read paths unchanged by #386. `albums` capped at 100, `_info` a fixed 22-key whitelist, `photos()` capped at 25. Device record: `photo_info` by the old id, `album_listed` true. |
| SC3 | Export by id writes to an allowlisted directory under the write-to-disk discipline; the file opens as the expected image | ✓ VERIFIED | `PhotosAdapter.export` uses `files.target_path`, `check_size`, `confirm_written`, and now `staging` and `publish` (#386). Device record (build f877989): 240×320 per `sips`, a second call refused, audit op `export`. The #386 path is not yet on device (advisory). |
| SC4 | A written Notes semantic-search decision lands before any indexing code, and "not adopted" closes it | ✓ VERIFIED | `docs/notes-semantic-search.md` ("not adopted", five items, CJK limit); pinned by `test_the_note01_decision_record_is_kept`. #93 closed. |
| SC5 | If adopted, `notes_semantic` from a sidecar behind `[semantic]`; plain `uv sync` pulls no ML dependency | ✓ VERIFIED (not applicable by decision) | Not adopted (SC4). `test_no_semantic_extra_and_no_ml_dependency` passes on 106ffb6. |

### PLAN must-have truths

| Plan | Truths | Status | Evidence |
|---|---|---|---|
| 04-01 (PHO-01) | 11 | ✓ 11/11 | Not touched by #386. `test_packaging.py` passes in the full suite. |
| 04-02 (PHO-04) | 7 | ✓ 7/7 | `files.py` gains `staging` and `publish`; `target_path`, `exists_refusal`, `check_size` and `confirm_written` are unchanged. No module-level cap added; `MAIL_MAX_BYTES` still passed by `mail_attachments`. Mail writers still accept the documented TOCTOU window (module docstring). |
| 04-03 (NOTE-01, NOTE-02) | 12 | ✓ 12/12 | Not touched by #386; suite green. |
| 04-04 (PHO-02, PHO-03) | 14 | ✓ 14/14 | Not touched by #386; D-17 (`_live` refuses hidden photos) unchanged and kept by the owner. |
| 04-05 (PHO-04) | 9 | ✓ 9/9 | See the #386 table above: D-08, D-09, D-10, D-11, VerificationFailed, the result shape and the worker all hold. |
| 04-06 (PHO-01..04) | 8 | ✓ 8/8 | Historical device truths; the installed build is f877989 (stamp read here), `codesign --verify --strict` ok. The truth names the build with 04-01 to 04-05 merged, which f877989 is. |

**Score:** 66/66 truths verified (0 present, behavior-unverified)

The never-overwrite and failure-cleanup truths are behavior-dependent. Each is VERIFIED on a
passing named test that a mutation check turns red, not on presence.

### Superseding decisions honoured

- **D-16 (Python 3.12 floor, owner, PR #368).** Unchanged; `onexc` relies on it.
- **D-17 (hidden photos stay locked).** Kept by the owner on 2026-10-20; unchanged in code.

### Prohibitions

| Plan | Prohibition | Tier | Disposition | Evidence |
|---|---|---|---|---|
| 04-01 | No own fallback to PhotoKit/AppleScript/sqlite at a gate failure | judgment | ✓ resolved by the owner | `04-UAT.md` test 1 pass; no fallback code exists |
| 04-01 | No other photo touched; installed daemon not replaced | judgment | ✓ resolved by the owner | `04-UAT.md` test 2 pass |
| 04-02 | Write-to-disk rules not weakened | test | ✓ enforced | `tests/test_files.py`; #386 strengthens the photo path |
| 04-03 | No note text on disk | test | ✓ enforced | `test_body_search_touches_no_disk_but_the_store` |
| 04-03 | No ML dependency, `[semantic]` extra or `notes_semantic` | test | ✓ enforced | `test_no_semantic_extra_and_no_ml_dependency` |
| 04-03 | No locked note indexed | test | ✓ enforced | `test_locked_note_body_is_never_indexed` |
| 04-04 | No bytes, thumbnails, paths or library dump | test | ✓ enforced | exact-key whitelist test; caps tests |
| 04-04 | Executor not widened; osxphotos only on the worker | test | ✓ enforced | `max_workers=1`; `*_on_the_native_worker` tests |
| 04-04 | No Apple Event to Photos | test | ✓ enforced | `test_the_photos_adapter_has_no_applescript` |
| 04-05 | No iCloud download option or Photos.app/PhotoKit drive | test | ✓ enforced | `test_export_never_passes_a_download_option` |
| 04-05 | osxphotos never names, increments or overwrites | test | ✓ enforced | kwargs pin; the three #386 race tests (file, symlink, case variant) |
| 04-05 | No video or Live Photo motion export | test | ✓ enforced | video refusal and Live Photo tests |
| 04-06 | Only test-album / test-prefix items touched | judgment | ✓ resolved by the owner | `04-UAT.md` test 3 pass |
| 04-06 | No `ditto` over a bundle still in place | judgment | ✓ resolved by the owner | `04-UAT.md` test 4 pass; previous bundle in app-backup |
| 04-06 | No install before the owner answered `install` | judgment | ✓ resolved by the owner | `04-UAT.md` test 4 pass |

Complete with 0 flagged prohibitions: the 5 judgment-tier items carry explicit owner
resolution, and the 10 test-tier items have wired enforcement.

### Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `pyproject.toml` | osxphotos base dependency, capped | ✓ VERIFIED | `osxphotos>=0.77.2,<0.78`, `requires-python >=3.12` |
| `scripts/build_app.sh` | dylib drop, export guard, smoke imports | ✓ VERIFIED | unchanged by #386 |
| `tests/test_packaging.py` | needles for the build gates | ✓ VERIFIED | passes in the full suite |
| `macos_apps_mcp/files.py` | shared write-to-disk rules | ✓ VERIFIED | adds `staging`, `publish`; used by `photos.export` |
| `macos_apps_mcp/adapters/mail_attachments.py` | `MAIL_MAX_BYTES` | ✓ VERIFIED | passed as `max_bytes=` |
| `macos_apps_mcp/adapters/notes.py` | `read` envelope, FTS5 body pass | ✓ VERIFIED | wired from `server.notes` |
| `docs/notes-semantic-search.md` | NOTE-01 decision | ✓ VERIFIED | pinned by a test |
| `macos_apps_mcp/runtime.py` | `photos_db` seam | ✓ VERIFIED | used only qualified, inside the worker |
| `macos_apps_mcp/adapters/photos.py` | search, albums, info, export | ✓ VERIFIED | no AppleScript; export staged and published by link |
| `macos_apps_mcp/server.py` | `photos`, `photo_albums`, `photo_info`, `export_photo` | ✓ VERIFIED | one-line dispatch each; unchanged by #386 |
| `tests/test_photos.py` | fakes and read/export tests | ✓ VERIFIED | #386 adds 4 tests and widens the race, wrong-path, end-to-end and kwargs tests |
| `tests/integration/test_photos_integration.py` | device test | ✓ VERIFIED | `pytestmark = pytest.mark.integration`; not re-run here (advisory) |
| `/Applications/macos-apps-mcp.app` | the 04-01..04-05 develop build installed | ✓ VERIFIED | stamp f877989; seal ok; does not carry #385/#386 (advisory) |

### Key Link Verification

| From | To | Via | Status |
|---|---|---|---|
| `build_app.sh` install loop | `ARCH TREES DIFFER` diff | dylib drop inside the loop, before the diff | ✓ WIRED |
| `uv.lock` | bundle site-packages | `uv export --frozen --no-dev --no-emit-project --prune cryptography` | ✓ WIRED |
| `mail.py` export | `files.target_path` / `files.resolve_dest` | `from .. import files` | ✓ WIRED |
| `mail_attachments.py` save | `files.check_size(..., max_bytes=MAIL_MAX_BYTES)` | per-caller cap | ✓ WIRED |
| `server.notes` | `NotesAdapter.read` | `_notes.read(title)` | ✓ WIRED |
| `_body_hits` | `runtime.verify_sqlite_schema(conn, _BODY_FINGERPRINT)` | body pass checks its own fingerprint | ✓ WIRED |
| `server.photo_info` / `photos` / `photo_albums` | `PhotosAdapter.info` / `read` / `albums` | one-line dispatch | ✓ WIRED |
| `PhotosAdapter` methods | `runtime.photos_db()` | qualified, inside `run_native` | ✓ WIRED |
| `conftest._no_real_osascript` | `runtime.photos_db` | seam tuple | ✓ WIRED |
| `server.export_photo` | `PhotosAdapter.export` | `_additive_tool(audit="export")` | ✓ WIRED |
| `PhotosAdapter.export` | `files.target_path` / `check_size` / `confirm_written` / `staging` / `publish` | `from .. import files` | ✓ WIRED |
| device client | installed daemon | bundle shim (`-m macos_apps_mcp shim`) | ✓ WIRED (device record) |

### Data-Flow Trace (Level 4)

| Artifact | Data | Source | Real data | Status |
|---|---|---|---|---|
| `photos` / `photo_albums` / `photo_info` | Pointers, metadata dict | `osxphotos.PhotosDB()` on the system library | yes (device read through the daemon) | ✓ FLOWING |
| `export_photo` | written file | `PhotoInfo.export` into the staging directory, then `os.link` to dest | yes on the earlier path (240×320 per `sips`); the staged path is unit-proven only | ✓ FLOWING |
| `notes` | Pointers | NoteStore read-only URI + in-memory FTS5 | yes (unit fixtures; same read path as before the phase) | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| Unit suite on develop 106ffb6 (scratch copy, run once) | `uv run pytest -q` | 2199 passed, 102 deselected | ✓ PASS |
| Lint | `ruff check macos_apps_mcp tests scripts` | All checks passed | ✓ PASS |
| Format | `ruff format --check macos_apps_mcp tests scripts` | 103 files already formatted | ✓ PASS |
| Never-overwrite tests bite | scratch copy: `os.link` in `publish` replaced by `os.replace` | 4 named tests fail (file, symlink, case variant, no-hard-links) | ✓ PASS |
| Staging tests bite | scratch copy: export straight into `dest.parent`, no `publish` | 11 tests fail, the failure-cleanup and race tests included | ✓ PASS |
| Failure cleanup test bites | scratch copy: the old `dest.unlink` restored in the generic `except` | `test_export_photo_a_failing_export_never_deletes_another_writer_s_file` fails (2 cases) | ✓ PASS |
| D-08..D-11 named tests | `pytest -k "edited_still or additive_audited_export or gate06_verbs or download_option or ..."` | 35 passed | ✓ PASS |
| Scratch copy restored | `pytest tests/test_photos.py tests/test_files.py` after the mutations | 155 passed | ✓ PASS |
| Records lane code equals develop | `git diff origin/develop HEAD --name-only` | `.planning/` files only | ✓ PASS |
| Installed bundle seal | `codesign --verify --strict` | ok | ✓ PASS |
| Installed bundle build | build stamp read | f877989; no `staging` in the installed `files.py` | ℹ️ INFO (advisory) |
| Device integration test | not re-run (hard rule: no `-m integration`) | 5/0/0/0 in the 04-06 device record on the earlier code | ? SKIP (device record accepted; advisory) |

### Probe Execution

No `scripts/*/tests/probe-*.sh` is declared by any Phase 4 plan. The phase's device gates ran
as plan tasks (04-01 signed-bundle gate, 04-06 daemon proof) and were not re-run, by the
verification hard rules (no Photos library access, no daemon call).

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|---|---|---|---|---|
| NOTE-01 | 04-03 | Written semantic-search decision before indexing code | ✓ SATISFIED | decision doc, first commit of #365, #93 closed, record pinned by a test |
| NOTE-02 | 04-03 | If adopted, `notes_semantic` behind `[semantic]` | ✓ SATISFIED (not applicable) | not adopted; guard test pins the absence |
| PHO-01 | 04-01, 04-06 | Mechanism settled by `uv add osxphotos` | ✓ SATISFIED | resolver output quoted; osxphotos base dependency; signed-bundle gate |
| PHO-02 | 04-04, 04-06 | Albums as Pointers | ✓ SATISFIED | `photo_albums`; device album listed |
| PHO-03 | 04-04, 04-06 | Bounded metadata by id | ✓ SATISFIED | `photo_info` whitelist; device read by old id |
| PHO-04 | 04-02, 04-05, 04-06 | Export by id, write-to-disk discipline | ✓ SATISFIED | `export_photo` via `files`; #386 publishes atomically and never overwrites or deletes another writer's file |

Every requirement ID declared in the PLAN frontmatter is in REQUIREMENTS.md, and REQUIREMENTS.md
maps no other ID to Phase 4. No orphaned requirement.

### Advisory (New Scope, Unevidenced)

| # | Finding | Category | Why Advisory |
|---|---|---|---|
| 1 | The installed daemon (f877989) does not carry #385 or #386 | other | Not a Phase 4 must-have; the owner decided to rebuild and reinstall after this fix |
| 2 | The #386 staged export and the IN-07 fixture have not run on device; the hard-link publish depends on the root volume | other | Manual-only device proof; unit tests and mutation checks agree; a device run after the rebuild closes it |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|---|---|---|---|---|
| `photos.py`, `files.py`, `test_photos.py`, `CHANGELOG.md` (#386) and the phase-modified files | — | TBD / FIXME / XXX / TODO / HACK | — | none found |
| `macos_apps_mcp/files.py` | `staging` | a `.macos-apps-mcp-export-*` directory stays in the destination when the process dies between `mkdtemp` and the `finally` | ℹ️ Info | needs a killed daemon mid-export; the directory is hidden and holds at most one partial file |
| `macos_apps_mcp/server.py` | `export_photo` docstring | does not state the hard-link volume requirement | ℹ️ Info | the error text and the CHANGELOG state it; the default root (~/Downloads) is on APFS |
| `macos_apps_mcp/runtime.py` | `photos_db` | `shortcut:` PhotosDB per call is O(library) | ℹ️ Info | measured 0.03 s open; upgrade path stated in the comment |
| `macos_apps_mcp/adapters/notes.py` | `_body_hits` | `shortcut:` index rebuilt per call | ℹ️ Info | instant at the measured library size; sidecar path stated |
| `pyproject.toml` | ruff config | `target-version = "py311"` beside `requires-python >=3.12` | ℹ️ Info | deferred to #384 |
| `macos_apps_mcp/server.py` | `_guard` | `FileExistsError` / `OSError` not typed | ℹ️ Info | deferred to #383 (IN-01, pre-existing for Mail) |
| `.planning/REQUIREMENTS.md` | NOTE-01..PHO-04 rows | still `[ ]` / `Pending` | ℹ️ Info | tracking state; the phase-close step updates it |
| issue #373 | — | unpinned hatchling build backend | ℹ️ Info | pre-existing, low, open follow-up |

### Known item: #96 closed at planning time

The Phase 4 plan PR #363 closed issue #96 at planning time through a closing keyword
(before the device proof). The work is complete, and #96 carries the full closing comment.
The early close is a process note, not a gap. Planning PRs should reference an issue without
a closing keyword.

### Human Verification Required

None open. The 4 checks of the previous report (HV-1..HV-4, covering the 5 judgment-tier
process prohibitions 04-01/P1, 04-01/P2, 04-06/P1, 04-06/P2, 04-06/P3) are resolved by the
owner in `04-UAT.md`: status `complete`, 4 passed, 0 issues, 0 pending, confirmed in the
Phase 4 close session on 2026-10-20 13:05 CEST. #386 changes none of them.

### Gaps Summary

No gaps. PR #386 replaces the #385 race and wrong-path cleanup with one mechanism: a private
staging directory and an atomic hard-link publish. It causes no regression: the full suite is
green on develop 106ffb6, and the new never-overwrite and failure-cleanup tests fail when the
fix is removed. Every ROADMAP success criterion and every PLAN truth holds, and every
human-verification item is confirmed in a completed UAT. Two advisories stay open: the
installed daemon predates #385 and #386 (rebuild and reinstall decided by the owner), and the
staged export has not run on device.

---

_Verified: 2026-10-20T11:09:40Z_
_Verifier: Claude (gsd-verifier)_
