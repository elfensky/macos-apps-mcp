---
phase: "04"
slug: "notes-photos-settle-the-mechanism-then-ship-the-read-plane"
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: validated
nyquist_compliant: true
wave_0_complete: true
created: "2026-10-18"
validated: "2026-10-19"
validated_at: "origin/develop 6e54c05"
---

# Phase 04 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 (pytest-cov), FastMCP in-process `Client` for tool-level tests |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]`: `testpaths = ["tests"]`, `addopts = "-m 'not integration'"`; fail-closed native seams in `tests/conftest.py` (`run_osascript`, `body_file`, `tracked_run`, `photos_db`) |
| **Quick run command** | `uv run pytest -q tests/test_photos.py tests/test_notes.py tests/test_files.py tests/test_packaging.py tests/test_native_seam.py tests/test_registry.py tests/test_tool_annotations.py tests/test_doctor.py` |
| **Full suite command** | `uv run pytest -q && MACOS_APPS_READ_ONLY=1 uv run pytest -q && MACOS_APPS_ALLOW_SEND=mail uv run pytest -q && uv run ruff check . && uv run ruff format --check .` |
| **Device command (manual, never CI)** | `uv run pytest -m integration tests/integration/test_photos_integration.py` (Full Disk Access, real Photos library, throwaway photo) |
| **Estimated runtime** | quick ~9 s; full suite ~21 s per tier |

---

## Sampling Rate

- **After every task commit:** Run the quick run command.
- **After every plan wave:** Run the full suite command (all three tiers and both ruff checks).
- **Before `/gsd-verify-work`:** Full suite must be green.
- **Max feedback latency:** 25 seconds.

---

## Per-Task Verification Map

Measured at origin/develop 6e54c05 in a scratch copy on 2026-10-19:
`uv run pytest -q` 2178 passed, 102 deselected; `MACOS_APPS_READ_ONLY=1` 2165 passed, 13 skipped;
`MACOS_APPS_ALLOW_SEND=mail` 2174 passed, 4 skipped; `ruff check` clean; `ruff format --check` 111 files formatted.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 04-01-01 | 01 | 1 | PHO-01 | T-04-01, T-04-02, T-04-SC | osxphotos is a capped base dependency (`>=0.77.2,<0.78`), Python 3.12 floor, no 3.11 classifier, UTI dependency without a marker; the build drops the thin libdisclaim dylibs inside the install loop and refuses a `platform_release` export before install | unit | `uv run pytest -q tests/test_packaging.py -k "osxphotos_is_a_capped_base_dependency or build_script_gates_universal2"` | ✅ | ✅ green |
| 04-01-01 | 01 | 1 | PHO-01 | T-04-02 | Signed universal2 build logs all 7 gate lines and exits 0; the bundle imports osxphotos and opens the library on arm64 and x86_64 | device | `grep -c -e "universal2 gate ok" … .worktrees/p04-gate-build.log` (7) and the gate t1 assert on `.worktrees/p04-gate.json` | ✅ | ✅ green (evidence re-checked) |
| 04-01-02 | 01 | 1 | PHO-01 | T-04-03, T-04-04 | Throwaway photo reads back by id exactly as written; original exports 320x240 on both slices; no uuid in the gate JSON | device | gate t2 assert on `.worktrees/p04-gate.json` | ✅ | ✅ green (evidence re-checked) |
| 04-01-03 | 01 | 1 | PHO-01 | — | Owner rotates the throwaway photo once | manual | — (checkpoint: human-action) | n/a | ✅ done (owner "Rotated", 2026-10-18) |
| 04-01-04 | 01 | 1 | PHO-01 | T-04-03 | Edited still exports 240x320 on both slices; DAEMON.md and CREDITS.md drop the stale "deferred" note | device + grep | gate t4 assert on `.worktrees/p04-gate.json`; `git show origin/develop:pyproject.toml \| grep -c "osxphotos>=0.77.2,<0.78"` (1) | ✅ | ✅ green |
| 04-02-01 | 02 | 1 | PHO-04 | T-04-05, T-04-06 | `files.py` keeps basename derivation, containment after `resolve()`, overwrite refusal and empty-file check unchanged (37 moved tests) | unit | `uv run pytest -q tests/test_files.py tests/test_mail_extras.py tests/test_mail_attachments.py` | ✅ | ✅ green |
| 04-02-02 | 02 | 1 | PHO-04 | T-04-07 | Size cap is a keyword-only per-caller value; Mail keeps 25 MiB and its own wording; refusal texts are neutral | unit | `uv run pytest -q tests/test_files.py tests/test_mail_extras.py tests/test_mail_attachments.py tests/test_mail.py` (245 passed) | ✅ | ✅ green |
| 04-02-03 | 02 | 1 | PHO-04 | T-04-28 | One device save and one device export of real Mail with the watchdog loaded; second save refused | full suite + device | full suite command; device run recorded in 04-02-SUMMARY | ✅ | ✅ green (device: Manual-Only row) |
| 04-03-01 | 03 | 1 | NOTE-01 | T-04-08, T-04-10 | Decision record committed before any indexing code; `notes()` finds a word only in a body through FastMCP and returns the `read_result` envelope | unit + git | `git log --reverse --format=%s cb36415..origin/develop -- docs/notes-semantic-search.md macos_apps_mcp/adapters/notes.py \| head -1` (the docs commit); `uv run pytest -q tests/test_notes.py tests/test_server.py -k "notes or body or read_tool_empty"` (127 passed) | ✅ | ✅ green |
| 04-03-02 | 03 | 1 | NOTE-01 | T-04-08, T-04-09, T-04-10, T-04-11 | Title hits stay first without duplicates; locked bodies never indexed; FTS5 syntax in the query stays literal; no disk write but the store; NFC/NFD in every script finds the body (#367); drift and no-FTS5 report `coverage`; fallback says titles only | unit | `uv run pytest -q tests/test_notes.py -k "body or merge or locked or short or cap or tie or coverage or fallback or disk"` (57 passed) | ✅ | ✅ green |
| 04-03-03 | 03 | 1 | NOTE-01, NOTE-02 | T-04-SC | No `[semantic]` extra, no `notes_semantic` tool, no ML package in `uv.lock`; the decision doc names model, chunking, refresh, size cap and extra boundary | unit + grep | `uv run pytest -q tests/test_notes.py -k no_semantic_extra_and_no_ml_dependency`; `git show origin/develop:docs/notes-semantic-search.md \| grep -c -e "not adopted" -e "all-MiniLM-L6-v2" -e "1,000-character" -e "ZMODIFICATIONDATE1" -e "10,000 notes" -e "\[semantic\]"` (8) | ✅ | ✅ green |
| 04-04-01 | 04 | 2 | PHO-03 | T-04-12, T-04-13, T-04-16, T-04-17 | `photo_info` returns the 22-key whitelist, no bytes and no path; uuid, lower-case and `<UUID>/L0/001` aliases resolve to one record; malformed id raises before the seam; trashed is unknown; hidden refuses with the unhide directive; strings are one clean line; persons drop the unknown-face placeholder; `photos_db` runs on the native worker and maps TCC denial to Full Disk Access | unit | `uv run pytest -q tests/test_photos.py tests/test_native_seam.py -k "photo_info or photos_db or seam"` (76 passed) | ✅ | ✅ green |
| 04-04-01 | 04 | 2 | PHO-01 | T-04-16 | osxphotos is imported lazily inside `runtime.photos_db`, never at server import | smoke | `uv run python -c "import sys, macos_apps_mcp.server; print('osxphotos' in sys.modules)"` (False) | ✅ | ✅ green (see W-03) |
| 04-04-02 | 04 | 2 | PHO-02 | T-04-12, T-04-13, T-04-14 | `photos()` searches eight folded fields, skips trashed and hidden, newest first, capped with `truncated`, pointers hold no location or person; `photo_albums()` lists albums as Pointers in the envelope, same-title albums stay apart, counts only live photos, capped; adapter holds no AppleScript | unit | `uv run pytest -q tests/test_photos.py tests/test_server.py tests/test_registry.py tests/test_tool_annotations.py` (238 passed); `MACOS_APPS_READ_ONLY=1 uv run pytest -q tests/test_photos.py tests/test_registry.py` (116 passed, 2 skipped) | ✅ | ✅ green |
| 04-04-03 | 04 | 2 | PHO-02 | — | Photos leaves the Automation probe list; doctor reports 11 surfaces | unit | `uv run pytest -q tests/test_doctor.py` (37 passed) | ✅ | ✅ green |
| 04-05-01 | 05 | 3 | PHO-04 | T-04-23 | `export_photo` end to end through FastMCP writes into the allowed root; additive, verb `export`, Full Disk Access, no `dry_run`, no snapshotter; absent under READ_ONLY | unit | `uv run pytest -q tests/test_photos.py tests/test_registry.py tests/test_tool_annotations.py -k "export_photo or gate06 or develop_era or audit_classified"` (32 passed) | ✅ | ✅ green |
| 04-05-02 | 05 | 3 | PHO-04 | T-04-18, T-04-19, T-04-20, T-04-21, T-04-22 | Edited still when adjusted; `absent` from the source (unset, missing, directory, evicted, render pending) without a download; video refused before file work; Live Photo motion skipped by name; never overwrites; outside-root refused and creates nothing; cap refuses before export; wrong, empty, zero-byte or failing osxphotos result is a typed failure that leaves no file; no download option reaches osxphotos; hostile filename stays inside | unit | `uv run pytest -q tests/test_photos.py -k export` (29 passed) | ✅ | ✅ green |
| 04-05-03 | 05 | 3 | PHO-04 | T-04-25 | Device test file is marked `integration`, collects 5 tests and is deselected by default | collect | `uv run pytest tests/integration/test_photos_integration.py --collect-only -q -m integration` (5 collected); `uv run pytest -q tests/integration/test_photos_integration.py` (5 deselected) | ✅ | ✅ green |
| 04-06-01 | 06 | 4 | PHO-01..PHO-03 | T-04-24, T-04-26, T-04-27 | Installed daemon is the develop build; doctor: mode daemon, 11 surfaces, no Photos Automation surface, Full Disk Access ok; `photo_info` by old id correct through the daemon; bundle seal valid | device | daemon t1 assert on `.worktrees/p04-device.json`; `codesign --verify --strict --verbose=2 /Applications/macos-apps-mcp.app` | ✅ | ✅ green (evidence re-checked) |
| 04-06-02 | 06 | 4 | PHO-02, PHO-04 | T-04-24, T-04-25 | Search and albums through the daemon; edited still exports 240x320; second export refused; export audited; integration suite 5/0/0/0 on this Mac | device | daemon t2 assert on `.worktrees/p04-device.json`; JUnit read of `.worktrees/p04-integration.xml` (5 tests, 0 failures, 0 errors, 0 skipped) | ✅ | ✅ green (evidence re-checked) |
| 04-06-03 | 06 | 4 | — | T-04-25 | Owner deletes the test photos and empties Recently Deleted | manual | — (checkpoint: human-action) | n/a | ✅ done (owner "deleted", 2026-10-19) |
| 04-06-04 | 06 | 4 | PHO-01..PHO-04 | T-04-24, T-04-25 | Zero residue (search, trash, album, export dir); seal intact after the run; no uuid or e-mail address in the SUMMARY or device JSON | device | cleanup assert on `.worktrees/p04-device.json`; privacy regex over 04-06-SUMMARY.md and the device JSON | ✅ | ✅ green (evidence re-checked) |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

### Requirement coverage

| Requirement | Automated (CI) | Device / manual proof | Status |
|-------------|----------------|-----------------------|--------|
| NOTE-01 | `test_notes.py` body-search suite; decision doc grep and commit-order check | — (decision record; owner decision 2026-09-28) | COVERED |
| NOTE-02 | `test_no_semantic_extra_and_no_ml_dependency` (not adopted ⇒ the guard is the whole requirement) | — | COVERED |
| PHO-01 | `test_osxphotos_is_a_capped_base_dependency`, `test_build_script_gates_universal2`, the lazy-import smoke, `test_photos_db_*` | signed bundle gate on both slices (04-01), installed daemon (04-06) | COVERED |
| PHO-02 | `test_photos_search_*`, `test_photo_albums_*`, `test_photo_albums_tool_dispatches`, `test_doctor.py` | daemon search and albums (04-06) | COVERED |
| PHO-03 | `test_photo_info_*` (22-key whitelist, no bytes or path, aliases, trashed, hidden, persons) | daemon `photo_info` by old id (04-06); integration date and location test | COVERED |
| PHO-04 | `test_files.py`, `test_export_photo_*`, `test_export_never_passes_a_download_option`, `test_gate06_verbs` | edited still opens 240x320 via `sips` (04-01, 04-06); integration export test | COVERED |

Review-fix PRs are pinned by tests in the same suite: #369 / #367 by `test_body_search_finds_a_word_in_any_script` (a mutation of `_fts_expr` back to `fold_text` fails 24 of its 28 cases); #375 by `test_build_script_gates_universal2`; #378 by `test_photo_info_hidden_photo_refuses_with_the_unhide_directive`, `test_photos_search_never_matches_hidden_photos`, `test_photos_db_tcc_denial_is_full_disk_access`, `test_photos_db_permission_error_that_escapes_is_full_disk_access`, `test_photos_search_skips_the_unknown_face_placeholder`; #381 by `test_export_photo_a_failing_export_leaves_no_file_and_raises_typed`.

---

## Wave 0 Requirements

Existing infrastructure covers all phase requirements. pytest, the fail-closed seam guard and the FastMCP client harness existed before the phase; 04-04 added `photos_db` to the conftest seam set in its own RED commit.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| osxphotos imports and `PhotosDB()` opens inside the signed Developer ID bundle on arm64 and x86_64; read back by id; original and edited stills export | PHO-01 | Needs the Developer ID identity, a signed universal2 build and the real Photos library under Full Disk Access | `scripts/build_app.sh --sign`, then the gate probe inside the bundle per 04-01-PLAN Tasks 1, 2, 4. Evidence: 7 gate lines, exit 0; `p04-gate.json` t1, t2, t4 asserts pass; `codesign_ok` true, `amfi_lines` 0 |
| The owner rotates a throwaway photo so that an edited render exists | PHO-01, PHO-04 | Photos AppleScript cannot make an edit; owner action in Photos | 04-01 Task 3. Evidence: owner answer "Rotated", 2026-10-18 |
| Real Mail attachment save and message export through `files.py` | PHO-04 (shared write-to-disk rules) | Touches real Mail; the watchdog must run | 04-02 Task 3. Evidence: save bytes equal disk bytes, second save refused with "already exists", `.eml` size equals `bytes`, scratch root removed |
| Read plane and export through the installed daemon's own Full Disk Access | PHO-01..PHO-04 | Needs the installed signed daemon and the real library; owner install decision | 04-06 Tasks 1, 2. Evidence: build f877989 installed; doctor 11 surfaces, no Photos Automation surface, FDA ok; `photo_info` 8 of 8 checks; search and albums found the test photo; export 240x320, second export refused, audited as `export` |
| On-device integration suite | PHO-02..PHO-04 | `-m integration` touches the real Photos library; never in CI | `uv run pytest -m integration tests/integration/test_photos_integration.py`. Evidence: 5 tests, 0 failures, 0 errors, 0 skipped; printed `REUSED TEST PHOTO` |
| Owner removes the throwaway photos and empties Recently Deleted | — (D-15 residue) | Photos AppleScript cannot delete media items | 04-06 Task 3. Evidence: owner answer "deleted", 2026-10-19; live 0, in trash 0; test album deleted; no export directory left; seal intact after the run |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies (the two `checkpoint:human-action` tasks are owner actions with recorded answers)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (none missing)
- [x] No watch-mode flags
- [x] Feedback latency < 60s
- [x] `nyquist_compliant: true` set in frontmatter

### Warnings (do not block compliance)

- **W-01:** The NOTE-01 decision doc content and its commit order are checked by a grep and a `git log` command, not by a pytest test. A later edit that deletes or empties `docs/notes-semantic-search.md` keeps CI green.
- **W-02:** The Notes body search (D-13) has no device run. The real NoteStore schema is fingerprinted by the pre-existing integration tests, and the installed 04-06 build holds the code, but no `notes()` body query through the daemon is recorded.
- **W-03:** The lazy import of osxphotos (04-04 must-have) is checked by a one-off smoke command, not by a pytest test. A top-level `import osxphotos` keeps CI green, because osxphotos is a base dependency.
- **W-04:** The comment above `_SCRIPT_WORDS` in `tests/test_notes.py` says "Escaped on purpose", but the list holds literal glyphs. The test generates NFC and NFD forms itself, so it stays sound; an editor that applies NFKC would turn the full-width case into ASCII without a failure.

**Approval:** approved 2026-10-19

## Validation Audit 2026-10-19

| Metric | Count |
|---|---|
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 |
