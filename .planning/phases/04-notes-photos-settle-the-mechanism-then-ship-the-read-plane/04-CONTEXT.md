# Phase 4: Notes & Photos — Settle the Mechanism, Then Ship the Read Plane - Context

**Gathered:** 2026-10-09 (assumptions mode)
**Status:** Ready for planning

<domain>
## Phase Boundary

The two adapters whose mechanism was open are settled on device before feature code. Photos
gets a bounded read plane and an export by id. Notes gets its written semantic-search decision
and the body search that replaces semantic search.

Open requirements: NOTE-01, NOTE-02, PHO-01, PHO-02, PHO-03, PHO-04 (#93, #96).

Not in this phase: any Photos write other than the export (no album create, no import, no
delete, no keyword or person edit); shared albums (osxphotos #2003 on macOS 26); Live Photo
motion and video export; Notes semantic search or any ML dependency; adapter toggles (Phase 5).

The Photos mechanism probe ran before this context was written (2026-10-09, this Mac, macOS
27.0.1, results in D-02). Those results are locked; the planner does not re-probe them, but
the first plan proves what the probe could not (D-03).
</domain>

<decisions>
## Implementation Decisions

### Photos mechanism (PHO-01)
- **D-01:** **osxphotos for everything Photos** (owner, 2026-10-09, paraphrased: osxphotos
  for everything — one surface, fewer chances for bugs, one CLI). Search, albums, per-photo
  metadata and export all go through osxphotos. No PhotoKit code of our own, no AppleScript
  in the Photos adapter, no direct `Photos.sqlite` read of our own. osxphotos is a **base
  dependency** in `[project] dependencies`, not an extra (owner, 2026-10-09). The stale
  pyproject comment ("Photos extra deferred: osxphotos pins pyobjc-core<10 …") is replaced by
  the probe result. PhotoKit-plus-store-read and PhotoKit-only were presented and not chosen
  (see Deferred).
- **D-02:** Probe results (2026-10-09, this Mac, macOS 27.0.1 26A434), locked:
  - `uv add osxphotos` exits 0: osxphotos **0.77.2**, 66 new packages, **no existing pin
    moved**. uv forks the resolution: Python 3.11 on macOS 12 (`platform_release < '22'`) gets
    osxphotos 0.65.0 and moves pyobjc (EventKit included) to 10.3.2; every other macOS,
    including the shipped `.app` (Python 3.14, macOS 15+), gets 0.77.2 with pyobjc 12.2.2,
    the version the project already locks.
  - The `.app` install gate, emulated (not a full build): `uv export --frozen --no-dev
    --no-emit-project --prune cryptography`, then `uv pip install --no-build --no-deps
    --require-hashes` for `aarch64-apple-darwin` and `x86_64-apple-darwin`, Python 3.14,
    `MACOSX_DEPLOYMENT_TARGET=15.0`: both exit 0, the two trees hold the same distributions
    and the same non-binary files, every Mach-O needs macOS 11.0 or older.
  - Runtime: `import osxphotos` 8.2 s (first import, cold `.pyc`). `PhotosDB()` opens the
    system library in 0.1 s; `db_version 5001`, `photos_version 12`, model version
    **270010300**. osxphotos's tested model range ends at 13999, so this macOS 27 model is
    newer than any model its authors test. It read 12 albums, 32 persons and 57 assets.
  - **This Mac's library has 0 live photos** (57 assets, all trashed). Device tests import
    throwaway photos and remove them afterwards.
  - osxphotos upstream: MIT, since 2019-06, 3.9k stars, 0.77.0–0.77.2 in 2026-09, 435 open
    issues; a macOS 27 issue is already closed (#2221). Open and relevant: #2003 (shared
    albums on macOS 26), #2175 (AMFI "Unrecoverable CT signature issue" importing
    pyobjc/photoscript on macOS 26.5.2 when installed via uv).
- **D-03:** **The first plan proves osxphotos inside the signed daemon before any feature
  code.** A real `scripts/build_app.sh` build with osxphotos in the tree (both smokes, the
  signed smoke, the universal2 gate). Then, in that signed bundle: `PhotosDB()` opens; one
  throwaway photo imported into Photos reads back its date, location, persons (none is fine)
  and EXIF subset by id; its edited still exports and opens as an image. If the signed bundle
  cannot import osxphotos (#2175) or the macOS 27 model misreads, the plan stops and returns
  to the owner with the output; it does not fall back on its own.

### Photos read plane (PHO-02, PHO-03)
- **D-04:** One id for every Photos tool: the osxphotos `uuid`. `photos()` moves from the
  Photos.app AppleScript `search` to an osxphotos query (owner D-01: one surface), so the id
  it returns goes straight into `photo_info(id)` and `export_photo(id)`. An id in the old
  AppleScript form (`<UUID>/L0/001`, already cited in notes) is accepted and reduced to its
  UUID. The search fields the query covers (filename, title, description, keywords, place,
  persons, labels from `search_info`) are named in the docstring.
- **D-05:** Albums list as Pointers in the `read_result` envelope (`contracts.read_result`),
  capped, with `truncated` at the cap. `photo_info(id)` returns one dict with a fixed field
  whitelist: dates (taken, added, modified), location (lat/lon and place name), person names,
  and an EXIF subset (camera make and model, lens, focal length, aperture, shutter speed, ISO,
  pixel size). Free text (title, description, place, person names) passes through the text
  hygiene helpers. No thumbnails, no image bytes, no library-wide dump. An unknown id raises
  `ValueError`.
- **D-06:** Photos reads run on the single `run_native` worker (`max_workers=1`, never
  widened) through the adapter.
- **D-07:** Permissions: osxphotos reads the library at rest, so the Photos tools need **Full
  Disk Access**, which the daemon already holds. Docstrings name Full Disk Access, not
  Automation. Whether `Photos` stays in `doctor._AUTOMATION_APPS` follows from what the
  adapter still sends to Photos.app (after D-04 and D-09: nothing) — the planner checks and
  removes it if nothing uses it.

### Photos export (PHO-04)
- **D-08:** `export_photo(id, dest_dir)` writes the **edited still** — the image as Photos
  shows it, crop and edits applied; the original when there is no edit (owner, 2026-10-09).
  Video and the motion part of a Live Photo are refused with a typed, agent-directed message.
- **D-09:** No silent network work: an asset whose file is not on disk (iCloud "Optimize Mac
  Storage") is reported as `absent` for that id, like `export_mail`. No osxphotos option that
  asks Photos.app or PhotoKit to download it (`use_photos_export`, `use_photokit`) is used.
- **D-10:** `export_photo` is `@_additive_tool(audit="export", adapter="photos", …)`, has no
  `dry_run` and no snapshotter, and joins `envelope_only` in `tests/test_tool_annotations.py`
  — the `export_mail` / `save_mail_attachment` shape.
- **D-11:** The write-to-disk rules are shared, not copied: `adapters/mail_files.py` moves to
  a package-level module (`macos_apps_mcp/files.py`, beside `text.py` and `errors.py`). Its
  root, env override, derived basename, containment check after `resolve()`, overwrite refusal
  and empty-file check stay the same; the size cap becomes a per-caller value; refusal texts
  stop saying "mail". The two Mail importers and `tests/test_mail_files.py` follow. The
  overwrite refusal runs in Python before osxphotos writes anything.

### Notes (NOTE-01, NOTE-02)
- **D-12:** NOTE-01 closes as **not adopted** on the owner's decision of 2026-09-28 (spike 004:
  17 notes are too small for an index; native macOS embeddings score below today's matcher;
  MiniLM-L6 via ONNX if ever adopted). The written decision already exists; the phase records
  it and cites the spike, and #93 is closed with it. NOTE-02 is not applicable: no
  `[semantic]` extra, no `notes_semantic`, no ML dependency.
- **D-13:** The owner's replacement ships in this phase: `notes()` searches note **bodies**
  with SQLite FTS5 (spike 004: hit@1 0.31 → 0.54, no new dependency). The index is built in
  memory per call from the bodies the adapter already decodes, through `read_via_sqlite`; no
  sidecar file, so no second copy of note text (notes hold credentials) lands on disk.
  Locked notes stay excluded.
- **D-14:** No lost results: today's folded title/snippet substring match stays, and body hits
  are added (FTS alone drops short words such as "tax"). `notes()` returns the `read_result`
  envelope; without Full Disk Access the AppleScript fallback searches titles only, and the
  result says so in `plane` / `coverage`. The return-shape change gets a CHANGELOG note.

### Probes and tests
- **D-15:** Every device write uses throwaway items: imported test photos and an export
  directory under scratch, all removed after the test. Device tests are
  `@pytest.mark.integration`, run manually, never in CI. Unit tests mock at the adapter
  boundary; osxphotos is faked there, and the conftest fail-closed native seam extends to it.

### Claude's Discretion
- `PhotosDB` lifetime: load per call or cache with an mtime-based reload — decide from the load
  time measured in D-03 on a library with photos, and state the trade-off.
- Album cap and search cap values (`MAX_PHOTOS = 25` today), and the export size cap.
- Exact module split inside `adapters/photos.py`.

### Folded Todos
None.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

- `.planning/ROADMAP.md` — Phase 4 (goal, success criteria 1–5)
- `.planning/REQUIREMENTS.md` — NOTE-01, NOTE-02, PHO-01..04; out-of-scope list (no inline binary)
- `.planning/PROJECT.md` — core value (safe writes), pointers-not-payload
- `.planning/spikes/004-notes-semantic-cost/README.md`, `.planning/spikes/MANIFEST.md`,
  `.planning/spikes/WRAP-UP-SUMMARY.md` — the NOTE-01 decision and the FTS5 measurement
- `.claude/skills/spike-findings-macos-apps-mcp/references/notes-search.md` — FTS5 recipe
  (local, git-ignored copy of the spike findings)
- `.planning/research/STACK.md`, `ARCHITECTURE.md`, `FEATURES.md`, `PITFALLS.md` (osxphotos#1651
  schema break, write-to-disk discipline, inline-thumbnail anti-pattern)
- Prior contexts: `01-CONTEXT.md`, `02-CONTEXT.md`, `02.1-CONTEXT.md`, `03-CONTEXT.md`
  (tiers, audit, `read_result`, store-plane fingerprints, throwaway device writes)
- Code: `macos_apps_mcp/adapters/photos.py`, `adapters/notes.py`, `adapters/mail_files.py`,
  `adapters/mail.py` (`export_mail`, ~2444-2498), `adapters/mail_index.py` (FTS5 use),
  `server.py` (tool tiers, `export_mail` registration, `notes()`/`photos()` tools),
  `registry.py`, `contracts.py` (`read_result`), `runtime.py` (`run_native`,
  `read_via_sqlite`), `doctor.py` (`_AUTOMATION_APPS`, Full Disk Access probe)
- Build: `pyproject.toml`, `scripts/build_app.sh` (install, universal2 and `.pyc` gates),
  `packaging/Info.plist`, `packaging/entitlements.plist`, `CREDITS.md`
- Tests: `tests/test_tool_annotations.py` (`envelope_only`), `tests/test_native_seam.py`,
  `tests/conftest.py`, `tests/test_photos.py`, `tests/test_notes.py`, `tests/test_mail_files.py`
- Issues: #93 (NOTE-01/02), #96 (PHO-01..04); upstream osxphotos #2003, #2175, #2221
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `contracts.read_result` — the one bounded-read envelope (`results`, `truncated`, `plane`,
  `coverage`); `reminders()` adopted it in Phase 3.
- `adapters/mail_files.py` — the untrusted-to-disk discipline D-11 lifts into a shared module.
- `runtime.read_via_sqlite` + a `_FINGERPRINT` — the Notes body read already uses it;
  `notes._decode_note_data` and the body join exist (FTS5 builds on them).
- `export_mail` — the `absent`-per-id and envelope shape `export_photo` follows.

### Established Patterns
- Tools are thin dispatch; tiers gate at registration; a write declares its audit verb.
- Every native call runs on the one serialized worker.
- Device writes use throwaway items, removed in teardown; integration tests never run in CI.

### Integration Points
- `server.py`: `photos()` (rewired), new `photo_albums`/`photo_info` reads and the
  `export_photo` additive tool; `notes()` return shape.
- `pyproject.toml` dependencies; the `.app` build picks osxphotos up through `uv export`.
- `CREDITS.md` gains osxphotos (MIT).
</code_context>

<specifics>
## Specific Ideas

- Owner, 2026-10-09 (paraphrased): osxphotos for everything — one surface, fewer chances
  for bugs, one CLI. The osxphotos CLI is part of the reason: one tool the owner can also use
  by hand.
- The library on this Mac is empty (0 live photos); every device proof imports its own
  throwaway photo.
</specifics>

<deferred>
## Deferred Ideas

- PhotoKit for the core plus a read-only `Photos.sqlite` read for persons and EXIF (the
  Reminders pattern) — presented 2026-10-09, not chosen.
- PhotoKit only (persons and EXIF as gaps) — presented, not chosen.
- Shared albums (osxphotos #2003 on macOS 26).
- Export of the original file, video and Live Photo motion.
- iCloud download on export (osxphotos `use_photokit` / `use_photos_export`).
- Notes semantic search behind a `[semantic]` extra — not adopted (D-12); revisit only if the
  library grows far past 17 notes.

### Reviewed Todos (not folded)
None — no pending todo matched Phase 4.
</deferred>
