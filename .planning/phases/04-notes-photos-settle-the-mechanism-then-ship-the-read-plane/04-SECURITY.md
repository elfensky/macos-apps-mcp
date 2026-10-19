---
phase: "04"
slug: "notes-photos-settle-the-mechanism-then-ship-the-read-plane"
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on severity (the blocking gate)
threats_open: 0
asvs_level: 1
block_on: high
register_authored_at_plan_time: true
threats_total: 34
threats_closed: 34
created: "2026-10-19"
audited_at: "6e54c05"
---

# Phase 04 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
> Requirements: NOTE-01, NOTE-02, PHO-01, PHO-02, PHO-03, PHO-04.
> Audited source: `git diff cb36415 6e54c05 -- . ':!.planning'` (plan PRs #370, #364, #365,
> #374, #379; review-fix PRs #369, #375, #378, #381; decisions #368 D-16, #377 D-17).
> ASVS Level 1, block on high. Evidence is a `file:line` on develop at 6e54c05, a named unit
> test (all pass on a scratch copy of 6e54c05), or a recorded device result in a plan SUMMARY.

---

## Plain-language summary

**Technical.** All 34 threats are closed: 31 by a mitigation found in the merged code or in
recorded device evidence, and 3 by a documented accepted risk (T-04-11, T-04-15, T-04-R5;
T-04-R5 is also below the `high` block threshold). No `high` threat is open.
`threats_open: 0`.

**eli14.** Think of the server as a librarian who may read the owner's notebooks and photo
albums aloud, and may copy one photo into one tray. Each threat is a way the librarian could
read too much, copy into the wrong place, or be fooled. For every way, a lock was found on
the door, a test that rattles the lock, or a written note that a small risk is accepted.
Today nothing serious is unlocked. In the future, the one known gap (T-04-R5, the tool that
builds the app package is fetched unpinned) stays small, and an issue tracks it.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| PyPI → uv.lock → signed bundle | osxphotos and 67 new locked packages enter the daemon's code | third-party code (supply chain) |
| signed bundle → AMFI / hardened runtime | every new `.so` must load under the Developer ID signature | executable code |
| NoteStore.sqlite → process memory → FTS5 | the body pass decodes every live note body | note text, may hold credentials (high) |
| model query → FTS5 MATCH expression | the query string becomes FTS5 syntax | untrusted input |
| Photos library → model context | metadata (dates, places, persons, EXIF) crosses into the model | personal data (high) |
| photo text set by others → model | titles, descriptions, keywords, person and place names, labels | untrusted text (prompt injection) |
| untrusted original filename / model `dest_dir` → filesystem | a name or directory becomes a write path | untrusted input → disk write |
| osxphotos export → network (iCloud) / Photos.app | an export option could download or launch Photos | network side effect |
| plan scripts / device output → SUMMARY, PR, issue (public repo) | anything a probe prints can be published | ids, library facts, addresses |
| this phase → the owner's running daemon | the device install replaces the bundle every client uses | availability |

---

## Threat Register

### Plan-time register (04-01 … 04-06)

| Threat ID | Category | Component | Severity | Disposition | Mitigation / Evidence | Status |
|-----------|----------|-----------|----------|-------------|------------------------|--------|
| T-04-01 | Tampering | osxphotos dependency tree | high | mitigate | `pyproject.toml:41` `osxphotos>=0.77.2,<0.78`; `scripts/build_app.sh:105` `uv export --frozen`, `:117` `--no-build --no-deps --require-hashes`; `:109-113` export guard exits 1 on a `platform_release` line; `tests/test_packaging.py::test_osxphotos_is_a_capped_base_dependency`, `::test_build_script_gates_universal2`; 04-01 SUMMARY "Pin result": the lock lost only the five D-16 pairs | closed |
| T-04-02 | Denial of service | thin dylib / AMFI refusing a `.so` | high | mitigate | `scripts/build_app.sh:121` drops the thin `libdisclaim_*.dylib` before the arch diff (`:123-125`); universal2 gate `:155`; unsigned smokes import osxphotos `:160`; signed smokes `:272`; 04-01 SUMMARY gate table (7 build lines, exit 0, `codesign --verify --strict`, `amfi_lines` 0); 04-06 SUMMARY `seal_after_run` true | closed |
| T-04-03 | Information disclosure | photo ids / library facts in gate ledger or SUMMARY | medium | mitigate | ledger kept git-ignored under `.worktrees/` (04-01 SUMMARY "Kept for 04-06"); UUID and e-mail regex over every phase SUMMARY: 0 matches (re-run in this audit) | closed |
| T-04-04 | Tampering | residue in the owner's Photos library (04-01) | medium | mitigate | throwaway photo with the `macos-apps-mcp-test-` prefix in album `macos-apps-mcp-test`; residue closed in 04-06 SUMMARY (`cleanup_search_empty`, `cleanup_trash_empty` live 0 / trash 0, `album_deleted` true) | closed |
| T-04-SC | Tampering | package installs (all six plans) | high | mitigate | only `c051934` (04-01, PR #370) changed `pyproject.toml`/`uv.lock` dependencies; `b8f0125` (#375) changed a comment only; 04-02…04-05 SUMMARYs record `git diff --name-only origin/develop` without either file; 04-06 builds `--frozen --require-hashes` (`scripts/build_app.sh:105,117`); package legitimacy: owner D-01/D-02, 04-RESEARCH "Packages removed due to SLOP verdict: none"; resolver output quoted in 04-01 SUMMARY | closed |
| T-04-05 | Tampering | `files` move weakens basename or containment rules | high | mitigate | `git mv` of module and suite (PR #364); `macos_apps_mcp/files.py:64-82` `safe_basename` (NFC, Cc/Cf/Cs/Co/Cn stripped, last component under `/`, `\`, `:`, dotfile prefix); `:99-121` `resolve_dest` checks containment after `resolve()`; same 37-test count before and after (04-02 SUMMARY); `tests/test_files.py::test_a_symlink_pointing_out_of_the_root_is_refused` | closed |
| T-04-06 | Tampering | overwrite of an existing file | medium | mitigate | `macos_apps_mcp/files.py:133-137` `FileExistsError` before any write; refusal tests moved unchanged; `tests/test_photos.py::test_export_photo_never_overwrites` | closed |
| T-04-07 | Denial of service | oversized write after the cap moved to the caller | medium | mitigate | `macos_apps_mcp/files.py:141` `check_size(..., *, max_bytes: int, ...)` keyword-only, no default; `tests/test_files.py::test_the_cap_is_the_callers_and_keyword_only` (TypeError); Mail passes `MAIL_MAX_BYTES` 25 MiB | closed |
| T-04-28 | Information disclosure | 04-02 device run leaks mail details | low | mitigate | 04-02 SUMMARY "Device run": statuses, sizes and booleans only; scratch root and script removed (`test ! -e`) | closed |
| T-04-08 | Information disclosure | second copy of note text on disk | high | mitigate | `macos_apps_mcp/adapters/notes.py:563` `sqlite3.connect(":memory:")`, closed in `finally` `:576-577`; `tests/test_notes.py::test_body_search_touches_no_disk_but_the_store` (only the read-only store URI and `:memory:`) | closed |
| T-04-09 | Information disclosure | locked note body indexed and surfaced | high | mitigate | `macos_apps_mcp/adapters/notes.py:556-561` selects `ZISPASSWORDPROTECTED` and drops `locked` rows before decode; `tests/test_notes.py::test_locked_note_body_is_never_indexed` | closed |
| T-04-10 | Tampering | FTS5 syntax injected through the query | medium | mitigate | `macos_apps_mcp/adapters/notes.py:539-540` only `\w+` words, each a double-quoted phrase with `"` doubled; `tests/test_notes.py::test_body_query_is_never_fts_syntax` (`tax" OR "x`, `NEAR(a b)`, asserts no `coverage` and the expected ids, #369) | closed |
| T-04-11 | Denial of service | O(library) decode and index per call | low | accept | `shortcut:` comment `macos_apps_mcp/adapters/notes.py:550-551` names the upgrade trigger; output capped by `MAX_NOTES`; Accepted Risks Log AR-04-01 | closed (accepted) |
| T-04-12 | Information disclosure | library dump, image bytes or thumbnails in a result | high | mitigate | `macos_apps_mcp/adapters/photos.py:116-147` fixed 22-key `_info` (no path, bytes, thumbnail); `:26-27` `MAX_PHOTOS = 25`, `MAX_ALBUMS = 100` with `read_result(..., cap=)` `:174,191`; `tests/test_photos.py::test_photo_info_end_to_end_returns_the_whitelist` (`set(got) == INFO_KEYS`), `::test_photo_info_holds_no_bytes_or_path`, `::test_photos_search_caps_at_max_photos`, `::test_photo_albums_cap` | closed |
| T-04-13 | Spoofing | prompt injection in photo text | medium | mitigate | every string through `clean_summary` (`photos.py:76,100,110,112,122`); photo read tools keep the default untrusted-data notice (`server.py:121` `notice: bool = True`; `photos`, `photo_albums`, `photo_info` at `server.py:1067,1080,1091` pass no `notice=False`); `tests/test_photos.py::test_photo_info_strings_are_one_clean_line`, `::test_photo_albums_strings_are_clean_one_liners` | closed |
| T-04-14 | Information disclosure | GPS location in search results | medium | mitigate | search Pointer holds id, summary, deeplink only (`photos.py:95-102`); latitude/longitude only in `_info`; `tests/test_photos.py::test_photos_search_pointer_shape_holds_no_location_or_person` | closed |
| T-04-15 | Information disclosure | temporary Photos DB copy in `$TMPDIR` | low | accept | osxphotos removes its copy when the object is freed; `PhotosDB()` is built per call (`runtime.py:534-538`), so no long-lived copy; Accepted Risks Log AR-04-02 | closed (accepted) |
| T-04-16 | Denial of service | osxphotos used off the native worker | medium | mitigate | `runtime.py:559` `photos_db` runs on the worker; adapter wraps every access in `runtime.run_native` (`photos.py:170,191,196,274`); executor stays `max_workers=1` (`runtime.py:50`); seam `photos_db` fail-closed in `tests/test_native_seam.py:30`; `tests/test_photos.py::test_photo_info_reads_the_library_on_the_native_worker`, `::test_photos_search_runs_on_the_native_worker`, `::test_photo_albums_reads_the_library_on_the_native_worker`, `::test_export_photo_runs_on_the_native_worker` | closed |
| T-04-17 | Tampering | malformed id reaching the library | medium | mitigate | `photos.py:42-50` `_uuid` full-match against the UUID pattern before any seam call (`:195`, `:203`); `tests/test_photos.py::test_photo_info_malformed_id_raises_before_the_seam`, `::test_export_photo_unknown_and_malformed_ids_raise` | closed |
| T-04-18 | Tampering | hostile original filename | high | mitigate | `photos.py:234-237` name goes through `files.target_path` → `safe_basename`; `tests/test_photos.py::test_export_photo_hostile_original_filename_stays_inside_the_destination` | closed |
| T-04-19 | Elevation of privilege | `dest_dir` traversal or symlink out of the root | high | mitigate | `files.py:108-121` containment after `resolve()`, `mkdir` only after the check; `tests/test_photos.py::test_export_photo_outside_the_root_is_refused_and_creates_nothing`; `tests/test_files.py::test_a_symlink_pointing_out_of_the_root_is_refused` | closed |
| T-04-20 | Tampering | overwrite, or osxphotos renaming on a clash | high | mitigate | `files.target_path` refuses in Python before export (`files.py:133-137`); `photos.py:244-245` `overwrite=False, increment=False`; `tests/test_photos.py::test_export_photo_never_overwrites` (export never called); 04-06 device `second_export_refused` true. Residual check-to-write window accepted in `files.py:33-36` (pre-existing, milliseconds, user's own root) | closed |
| T-04-21 | Information disclosure | silent iCloud download or Photos.app launch on export (D-09) | high | mitigate | `photos.py:216-223` `absent` decided from `path`/`path_edited` with `os.path.isfile` before export; `:240-246` export receives only `filename`, `edited`, `overwrite`, `increment`; `tests/test_photos.py::test_export_never_passes_a_download_option`, `::test_export_photo_absent_when_path_set_but_file_missing`, `::test_export_photo_absent_when_the_source_path_is_unset`; `<0.78` pin (T-04-01); `doctor` probes no Photos Automation (`doctor.py:37-39`) | closed |
| T-04-22 | Denial of service | huge file written to disk | medium | mitigate | `photos.py:29` `PHOTO_MAX_BYTES` 250 MiB; `:224-233` `os.stat` then `files.check_size` before export; `tests/test_photos.py::test_export_photo_cap_refuses_before_the_export` | closed |
| T-04-23 | Repudiation | export leaves no audit trace | low | mitigate | `server.py:1104` `@_additive_tool(audit="export", ...)`; `tests/test_registry.py::test_gate06_verbs` (`"export_photo": "export"`); 04-06 device `export_audited` true | closed |
| T-04-24 | Information disclosure | ids, library facts or e-mail in device ledger, SUMMARY or #96 comment | high | mitigate | 04-06 SUMMARY results are booleans and sizes; UUID and e-mail regex over every phase SUMMARY and the #96 close comment: 0 matches (re-run in this audit) | closed |
| T-04-25 | Tampering | residue in the library or `~/Downloads` | medium | mitigate | 04-06 SUMMARY: search empty, live 0 / trash 0 for prefix `macos-apps-mcp-test-`, album deleted, no Downloads export directory left | closed |
| T-04-26 | Spoofing | checks measure a stale or dev daemon | medium | mitigate | 04-06 SUMMARY: `doctor` build `f877989`, `mode: daemon` before any Photos call; `installed_build` equals `build_sha` | closed |
| T-04-27 | Denial of service | failed install leaves no working daemon | medium | mitigate | 04-06 SUMMARY: owner answer "install" at the decision checkpoint; previous bundle kept in app-backup for rollback; install and proof passed | closed |

### Threats found by the independent reviews (added in this audit)

| Threat ID | Category | Component | Severity | Disposition | Mitigation / Evidence | Status |
|-----------|----------|-----------|----------|-------------|------------------------|--------|
| T-04-R1 | Information disclosure | Hidden-album photos exposed by search, `photo_info`, `export_photo` and album counts (D-17, PR #378, decision #377) | medium | mitigate | `photos.py:59-63` `_live` refuses a hidden id (shared by `info` and `export`); `:165` search skips `p.hidden`; `:106` album count excludes hidden and trashed; `tests/test_photos.py::test_photos_search_never_matches_hidden_photos`, `::test_photo_info_hidden_photo_refuses_with_the_unhide_directive`, `::test_export_photo_hidden_id_is_refused_with_the_unhide_directive`, `::test_photo_albums_count_only_live_photos` | closed |
| T-04-R2 | Tampering / Information disclosure | Failing export leaves a partial file, blocks retries, and leaks the library path in an untyped error (PR #381) | low | mitigate | `photos.py:239-254` any export exception removes the target (`dest.unlink(missing_ok=True)`) and raises a typed `NativeError` that names only the id and file name, cause kept; `tests/test_photos.py::test_export_photo_a_failing_export_leaves_no_file_and_raises_typed`, `::test_export_photo_source_evicted_after_the_isfile_check_is_absent` | closed |
| T-04-R3 | Tampering (result integrity) | Notes body search silently misses non-Latin words and reports a complete search (issue #367, PR #369) | medium | mitigate | `notes.py:530-540` query words from the NFC query (`norm_text`), not `fold_text`; `:558-559` bodies indexed as NFC; quoting kept; 28-case parametrized body-search test in `tests/test_notes.py` (marked #367 at `:1089`) | closed |
| T-04-R4 | Spoofing | Unsigned bundle smoke could import the checkout instead of the bundle; gate test needles matched comments, not commands (PR #375) | low | mitigate | `scripts/build_app.sh:160` unsigned smoke runs `-E -s -P`; `tests/test_packaging.py:153` needle carries the flags; the libdisclaim and export-guard needles pin the commands and their order (`test_build_script_gates_universal2`) | closed |
| T-04-R5 | Tampering (supply chain) | Project install builds with an unpinned, unhashed `hatchling` from PyPI (issue #373, pre-existing) | low | accept | `pyproject.toml:77` `requires = ["hatchling"]` unversioned; `scripts/build_app.sh:132` installs the project with `--no-deps` and no `--require-hashes`. Runtime dependencies stay hash-locked. Below the `high` block threshold; tracked in #373 (open). Accepted Risks Log AR-04-03 | closed (accepted) |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above workflow.security_block_on count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Unregistered Flags

None. Every plan SUMMARY `## Threat Flags` section is "None", with each named mitigation mapped
to a register entry above (04-02 → T-04-05/06/07/28; 04-03 → T-04-08/09/10; 04-04 →
T-04-12…17; 04-05 → T-04-18…23). 04-01 and 04-06 carry no Threat Flags section. The attack
surface the reviews found is registered as T-04-R1…R5.

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-04-01 | T-04-11 | Per-call decode and in-memory index of every live note is instant at the current library size; output is capped by `MAX_NOTES`; the `shortcut:` comment names the upgrade (persisted sidecar index past a few thousand notes). | 04-03 plan threat model (disposition accept) | 2026-10-18 |
| AR-04-02 | T-04-15 | osxphotos may copy the Photos database to `$TMPDIR` while Photos holds its lock; the copy is per call and removed when the object is freed, and `PhotosDB` is never cached. The copy stays in the user's own per-user temporary directory. | 04-04 plan threat model (disposition accept) | 2026-10-18 |
| AR-04-03 | T-04-R5 | The unpinned build backend is pre-existing (same line before Phase 4), affects only the backend that packages this repo's own code, and is low severity; every runtime dependency is hash-locked. The fix needs a design choice (hashed build constraints or a hash-locked build venv) and is tracked in #373. | Phase 4 security audit, low and below the block threshold; owner review via #373 | 2026-10-19 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-10-19 | 34 | 34 | 0 | gsd-security-auditor (ASVS L1, block on high; source at 6e54c05; targeted unit tests pass on a scratch copy; no device, Photos or Mail access) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-10-19
