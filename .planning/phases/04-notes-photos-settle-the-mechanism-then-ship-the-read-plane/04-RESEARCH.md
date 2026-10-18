# Phase 4: Notes & Photos — Settle the Mechanism, Then Ship the Read Plane - Research

**Researched:** 2026-10-18
**Domain:** osxphotos 0.77.2 as the Photos read/export plane inside a signed universal2 `.app` daemon; SQLite FTS5 body search for Notes; shared write-to-disk module
**Confidence:** MEDIUM-HIGH (osxphotos API and Notes/FTS5 facts read from the released wheel or run this session; signed-bundle behaviour and the Photos device writes are still unproven — that is D-03's job)

> Method note. `uv add` was NOT run (D-03 reserves it for the executor). osxphotos 0.77.2 and photoscript 0.6.1 were
> read from their released wheels (unzipped into the session scratchpad, read only) and exercised once in a
> **scratch venv outside the repo** (`uv pip install osxphotos==0.77.2`, Python 3.14.5, macOS 27.0.1 arm64). Nothing in the repo changed.
> Library facts below are counts and types only; no photo content, titles, names or UUIDs are recorded.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

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

### Deferred Ideas (OUT OF SCOPE)
- PhotoKit for the core plus a read-only `Photos.sqlite` read for persons and EXIF (the
  Reminders pattern) — presented 2026-10-09, not chosen.
- PhotoKit only (persons and EXIF as gaps) — presented, not chosen.
- Shared albums (osxphotos #2003 on macOS 26).
- Export of the original file, video and Live Photo motion.
- iCloud download on export (osxphotos `use_photokit` / `use_photos_export`).
- Notes semantic search behind a `[semantic]` extra — not adopted (D-12); revisit only if the
  library grows far past 17 notes.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PHO-01 | Photos mechanism settled by `uv add osxphotos` on the deployment target (#96) | D-02 is locked. This research adds three gate findings D-02 did not cover: two **thin** `libdisclaim_*.dylib` files fail the universal2 gate (Pitfall 1); cffi and pycparser re-enter the bundle (Pitfall 2); the unsigned-vs-signed AMFI risk (#2175) and the exact gate commands (Environment, Validation). |
| PHO-02 | List albums as Pointers (#96) | `PhotosDB.album_info` → `AlbumInfo.title/.uuid/.folder_names/.photos` (Architecture Pattern 3). Wrapped in `read_result`, capped. |
| PHO-03 | Bounded metadata by id: dates, location, persons, EXIF subset (#96) | `PhotosDB.get_photo(uuid)` + the `PhotoInfo` attributes listed with types in Pattern 4. Fixed whitelist, `ValueError` on unknown id. |
| PHO-04 | Export a photo by id to a destination directory, write-to-disk discipline (#96) | `PhotoInfo.export(dest, filename, edited=<hasadjustments>, overwrite=False, increment=False)`: no network by default in 0.77.2 (Pattern 5, Pitfall 4); shared `files.py` (Pattern 6). |
| NOTE-01 | Written decision on semantic search before any index code (#93) | Already written (spike 004). The phase records it and closes #93. |
| NOTE-02 | If adopted: `notes_semantic` behind `[semantic]` (#93) | Not applicable (D-12). The FTS5 replacement is D-13/D-14; recipe and the real cause of the "tax" gap in Pattern 7. |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- Tools in `server.py` are thin dispatch; no business logic in the tool layer. Reads uniform (`get_pointers -> list[Pointer]`), writes per-adapter typed. One adapter module per app; no cross-adapter reach.
- All native access runs through `runtime.run_native()` (single worker, `max_workers=1`, never widened). Adapters call the seam **qualified** (`from .. import runtime`; `runtime.x()`), never `from ..runtime import x` (`tests/test_native_seam.py` enforces).
- Three tiers gated at registration; a gated-off tool is absent. Outbound is not touched by this phase. A new write tool goes through `_additive_tool`/`_write_tool` with an explicit `audit=` verb.
- The shim↔daemon hop has no read deadline. Never add a timeout there to "fix" a slow first `import osxphotos`.
- Free text passes through `text.py` hygiene (`clean_summary`, `clean_body`, `fold_text`, `norm_text`). Docstrings must name the macOS permission(s) (`tests/test_tool_annotations.py`).
- Typed errors only (`errors.py`); never return `[]` for a failure.
- Verification before reporting success: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`. CI also runs `MACOS_APPS_READ_ONLY=1 uv run pytest`.
- Every session works in its own worktree under `.worktrees/`; `develop` is the trunk (rebase-merge). The repo is not the daemon: the `.app` must be rebuilt and reinstalled before any device claim.
- Bugs before features; Mail traps are not touched here.
- Project skill `spike-findings-macos-apps-mcp` (Notes search reference) was read; its FTS5 recipe is adopted with one correction (Pattern 7).

## Summary

The phase is two independent halves. **Photos** replaces the AppleScript `search` with osxphotos 0.77.2 reading `Photos.sqlite` at rest (Full Disk Access) on the single native worker, adds `photo_albums`, `photo_info` and an additive `export_photo`, and lifts the write-to-disk rules out of `mail_files.py` into a shared `files.py`. **Notes** adds in-memory FTS5 body search per call and an envelope return shape; semantic search is closed as not adopted. Everything needed for the Notes half already exists in the repo (decoder, body join, `read_via_sqlite`, `read_result`) and FTS5 is compiled into the shipped Python.

The Photos half has one real build risk that D-02 did not see: **`osxphotos/lib/` ships two thin dylibs** (`libdisclaim_arm64.dylib`, `libdisclaim_x86_64.dylib`), and `scripts/build_app.sh`'s universal2 gate will stop on them. They are used only by the osxphotos CLI, so the build must delete them from both per-arch trees before the diff step. The second gate finding is that `xattr` (via `osxmetadata`) brings **cffi and pycparser** back into the bundle, so the "no cryptography/cffi/pycparser in the `.app`" comments and `docs/DAEMON.md` text become stale. The #2175 AMFI risk is real but unconfirmed upstream (reporter: uv-installed venv, no signature detail); the bundle signs every `.so` with Developer ID, and `import osxphotos` plus `PhotosDB()` ran cleanly in an ordinary uv venv on this macOS 27.0.1 Mac.

Two behaviours need design care. (1) `PhotoInfo.export()` returns only the list of exported paths, so a missing file **and** an error both look like an empty list; the adapter must decide `absent` from `path`/`path_edited` before exporting and treat an empty result after a pre-checked export as a failure. (2) Photos AppleScript **cannot delete media items** ("Only albums and folders can be deleted"), so D-15's "removed afterwards" cannot be met by script for an imported photo (Open Question 1).

**Primary recommendation:** Plan 1 = `uv add 'osxphotos>=0.77.2,<0.78'` + build-script fix for the thin dylibs + `import osxphotos` added to the unsigned and signed smokes + the signed-bundle `PhotosDB()` gate on both slices; then `files.py` rename; then the Photos plane behind a new `runtime.photos_db()` seam; then Notes FTS5 + envelope; then docs, CHANGELOG, CREDITS, `_AUTOMATION_APPS`.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Tool registration, tier gate, docstring permissions | Tool layer (`server.py`) | `registry.py` | Thin dispatch; one record per tool |
| Photos query / metadata / export orchestration | Adapter (`adapters/photos.py`) | `files.py` | Business logic lives in the adapter; disk rules are shared |
| osxphotos import + `PhotosDB` construction (lazy, FDA preflight, typed errors) | Native door (`runtime.py`, new `photos_db()`) | — | The conftest/AST tripwires fail closed on this one patch point |
| Write-to-disk safety (root, basename, containment, no overwrite, size cap, empty-file) | Shared module (`files.py`) | adapters call it | One audited copy; Mail and Photos both route through it |
| Notes body decode + FTS5 index | Adapter (`adapters/notes.py`) | `runtime.read_via_sqlite` | Reuses the decoder; index lives only in a per-call `:memory:` connection |
| Bounded-read wire shape | `contracts.read_result` | — | The one envelope (`results`, `truncated`, `plane`, `coverage`) |
| Dependency / signing / universal2 | Build (`scripts/build_app.sh`, `pyproject.toml`, `uv.lock`) | `tests/test_packaging.py` | Only the build gate sees thin or too-new binaries |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| osxphotos | 0.77.2 (published 2026-09-27) | Read Photos library at rest; export a file | Owner decision D-01. Pure-Python wheel `py3-none-any`, MIT, `requires_python >=3.10`. [CITED: pypi.org/pypi/osxphotos/0.77.2/json] |
| sqlite3 (stdlib) FTS5 | SQLite 3.50.4 in the shipped Python 3.14.5 | Notes in-memory body index | No new dependency. [VERIFIED: ran `pragma compile_options` under `uv run python` 3.14.5 (PBS build dated May 10 2026, the build's pin): output list contained `'ENABLE_FTS5'`] |

### Supporting (new transitive packages the bundle must carry)
`import osxphotos` loads these (measured: 52 third-party top-level modules, **41 extension modules**):
pyobjc frameworks `Photos, Vision, Metal, Quartz, AVFoundation, AVFAudio, CoreML, CoreMedia, CoreAudio, CoreServices, ScriptingBridge, FSEvents, UniformTypeIdentifiers` (all 12.2.2, same version the project locks), plus `_cffi_backend` (via `xattr`), `wrapt` (2.5.1), `bitarray`, `charset_normalizer`, `markupsafe`, `yaml`, and pure-Python `photoscript`, `py-applescript`, `requests`, `rich`, `mako`, `textx`, `bpylist2`, `osxmetadata`, `makelive`, `cgmetadata`, `utitools`. Not imported at `import osxphotos` but installed: `psutil`, `whenever` (Rust extension), `pip`, `ptpython`, `click`. [VERIFIED: ran `-I -c "import osxphotos"` and listed `sys.modules`; `requires_dist` from PyPI JSON]
Size: the packages not already in the app add about 67 MB on one arch tree (arm64 measured); universal2 roughly doubles the `.so` part. Estimate only: +60 to +100 MB on the 201 MB app. [ASSUMED: arithmetic from one arch]

### Alternatives Considered
Locked by D-01; PhotoKit variants are in Deferred. Not re-opened.

**Installation (plan 1, task 1):**
```bash
uv add 'osxphotos>=0.77.2,<0.78'   # read the resolver output; quote any fork in the decision (SC-1)
```
Pin reason: osxphotos is 0.x, its model range is a moving target, and the repo already caps `fastmcp`/`mcp` at the tested major (`pyproject.toml` comment). The cap `<0.78` is a recommendation. Caveat: the Python 3.11 + macOS 12 fork resolves to 0.65.0 today (D-02); `>=0.77.2` may make that fork unresolvable. If `uv` errors, add `[tool.uv] environments = [...]` rather than loosening the pin. [ASSUMED: uv behaviour not run; Open Question 4]

**Version verification:** `uvx --from pip pip index versions osxphotos` → `osxphotos (0.77.2)`, `photoscript (0.6.1)` on 2026-10-18. [VERIFIED: pip index, this session]

## Package Legitimacy Audit

`gsd_run query package-legitimacy check --ecosystem pypi …` returned **SUS for every package**. Reasons were only `unknown-downloads` (the seam has no PyPI download data) plus `too-new` for packages whose *latest release* is under 30 days old (`osxphotos`, `photoscript`, `whenever`) and `no-repository` for `cffi`/`whenever` (no `repoUrl` in the registry metadata). None was `SLOP`; all exist; none has a `postinstall` signal (PyPI wheels run no install scripts). osxphotos is not a new package: since 2019-06, MIT, 3.9k stars (D-02, GitHub API).

| Package | Registry | Latest release | Source Repo | Verdict | Disposition |
|---------|----------|----------------|-------------|---------|-------------|
| osxphotos | PyPI | 2026-09-27 | github.com/RhetTbull/osxphotos | SUS (too-new, unknown-downloads) | Owner-approved D-01/D-02; planner adds `checkpoint:human-verify` before the install task |
| photoscript | PyPI | 2026-09-27 | github.com/RhetTbull/photoscript | SUS (too-new, unknown-downloads) | Transitive; same checkpoint covers it |
| py-applescript | PyPI | 2022-01-23 | github.com/rdhyee/py-applescript | SUS (unknown-downloads) | Transitive |
| wurlitzer | PyPI | 2024-06-12 | github.com/minrk/wurlitzer | SUS (unknown-downloads) | Transitive |
| xattr | PyPI | 2025-10-13 | github.com/xattr/xattr | SUS (unknown-downloads) | Transitive |
| cffi | PyPI | 2026-08-03 | none in registry metadata | SUS (unknown-downloads, no-repository) | Transitive; two arch wheels exist for cp314: `macosx_10_15_x86_64`, `macosx_11_0_arm64` [CITED: pypi.org/pypi/cffi/2.1.1/json] |
| makelive / cgmetadata / osxmetadata / utitools | PyPI | 2024–2026 | github.com/RhetTbull/* | SUS (unknown-downloads) | Transitive, same author as osxphotos |
| mac-alias | PyPI | 2025-12-04 | github.com/dmgbuild/mac_alias | SUS (unknown-downloads) | Transitive |
| whenever | PyPI | 2026-10-02 | none in registry metadata | SUS (too-new, unknown-downloads, no-repository) | Transitive; Rust extension — D-02's emulated install gate passed for both arches |

**Packages removed due to SLOP verdict:** none.
**Packages flagged SUS:** all of the above. The owner already approved osxphotos on 2026-10-09 with the probe in front of them; the `checkpoint:human-verify` therefore needs one line ("resolver output reviewed, 66+ new packages, no pin moved") and not a design discussion. Tag for all package names: `[CITED: pypi.org]`, not `[VERIFIED]`, because the seam verdict is SUS.
Postinstall check (npm-only step) is not applicable to PyPI.

## Architecture Patterns

### System Architecture Diagram

```
MCP client ──► shim ──► unix socket ──► daemon (signed .app, FDA granted)
                                          │
                  server.py tools (thin) ─┤
   photos(q) / photo_albums() / photo_info(id)        export_photo(id, dest_dir)
                         │  read tier                     │ additive tier, audit="export"
                         ▼                                ▼
                 adapters/photos.py  ─────────────► files.py (root, basename, resolve+contain,
                         │                                     no-overwrite, size cap, confirm_written)
                         ▼
            runtime.photos_db()   [NEW seam: lazy import osxphotos, FDA preflight,
                         │         typed errors, optional mtime-keyed cache]
                         ▼ (runs inside run_native → the one worker thread)
          osxphotos.PhotosDB()  ── reads ~/Pictures/…photoslibrary/database/Photos.sqlite
                         │          (+ -wal; temp copy of all three if Photos holds the lock)
                         ▼
        PhotoInfo / AlbumInfo  ──► whitelist ► text hygiene ► Pointer / dict ► read_result
                         │
                         └─ export: pre-check path_edited|path on disk → absent | PhotoInfo.export(...)
                                    (never download_missing / use_photos_export / use_photokit)

Notes:  notes(q) ► NotesAdapter.read(q) ► runtime.read_via_sqlite(NOTESTORE, fingerprint)
          ├─ pass 1: folded substring on title/snippet (unchanged, newest first)
          ├─ pass 2: decode bodies (_decode_note_data) → :memory: FTS5 → bm25 → body-only hits
          └─ merge, dedupe by Z_PK, cap MAX_NOTES ► read_result(plane?, coverage?)
          fallback (no FDA / drift): AppleScript title search ► plane="applescript", coverage="titles only"
```

### Recommended Project Structure
```
macos_apps_mcp/
├── files.py                  # NEW — moved from adapters/mail_files.py (git mv); per-caller size cap
├── runtime.py                # + photos_db()  (lazy osxphotos import; the fail-closed seam)
├── adapters/
│   ├── photos.py             # rewritten: osxphotos plane; no AppleScript, no STRIP_FRAMING
│   ├── notes.py              # + read(query) envelope, body FTS pass
│   ├── mail.py, mail_attachments.py   # import `files` instead of `mail_files`
tests/
├── test_files.py             # RENAMED from test_mail_files.py
├── test_photos.py            # rewritten (fakes)
├── _fakes.py                 # + FakePhotosDB / FakePhoto
└── integration/test_photos_integration.py   # NEW, @pytest.mark.integration
```

### Pattern 1: Lazy import on the worker, one seam
**What:** `import osxphotos` takes 0.65 s warm and 5.5 s on the first import in a fresh venv (measured; D-02 saw 8.2 s). It pulls PyObjC Photos/Vision/Metal/Quartz. Import it inside a function, never at module top, so `import macos_apps_mcp.server` (and every unit test) stays fast and never touches the Photos frameworks.
**Why a `runtime` function:** the fail-closed test lock patches names on `runtime`. A module-level `_load()` inside `adapters/photos.py` would have no lock and a unit test that forgot to fake it would open the developer's real library.
**Example:**
```python
# runtime.py — new. Skeleton only; names are the planner's.
def photos_db():
    """osxphotos PhotosDB for the system library. Call inside run_native only."""
    def work():
        import osxphotos  # lazy: 0.65 s warm, ~5-8 s cold; pulls PyObjC Photos/Vision/Metal
        try:
            return osxphotos.PhotosDB()
        except PermissionError as e:
            raise FullDiskAccessDenied(...) from e
        except (sqlite3.Error, KeyError, AttributeError, ValueError) as e:
            raise SchemaDrift(f"osxphotos could not read the Photos library ({e}) ...") from e
    return work() if on_worker() else run_native(work)
```
Seam registration (three places, all verified by reading): `tests/conftest.py:215` `for seam in ("run_osascript", "body_file", "tracked_run"):` and `tests/test_native_seam.py:30` `_SEAM = frozenset({"run_osascript", "body_file", "tracked_run"})` plus the `test_unit_tests_cannot_reach_a_seam_unfaked` parametrize list gain `"photos_db"`.
[VERIFIED: tests/conftest.py:215, tests/test_native_seam.py:30]

### Pattern 2: `PhotosDB` lifetime — recommend a cache keyed on file stat
**Facts (measured/read):**
- `PhotosDB()` reads the whole database into Python dicts at construction (`_dbphotos`, `_dbalbums_*`, `_dbfaces_*`) [VERIFIED: photosdb.py in the 0.77.2 wheel]. Cost is O(library). This Mac: open 0.05–0.08 s for 57 assets; `db.photos()` after load: 0.0 s.
- When Photos.app (or `photolibraryd`/`photoanalysisd`) holds the exclusive lock, osxphotos copies `Photos.sqlite`, `-wal` and `-shm` into a `TemporaryDirectory` and reads the copy [VERIFIED: photosdb.py `_copy_db_file`, `sqlite_db_is_locked`]. That is a **second copy of the whole Photos database (faces, places, titles) in `$TMPDIR`** for the life of the `PhotosDB` object.
- This Mac at rest: `Photos.sqlite` 13.4 MB, `Photos.sqlite-wal` 2.2 MB, `-shm` present. [VERIFIED: stat, this session]
- A cached `PhotosDB` is safe on the single worker: `db.execute()` lazily opens a thread-bound sqlite connection, and D-06 guarantees one thread.
**Recommendation:** cache the object in `runtime.photos_db()`, key = `(st_mtime_ns, st_size)` of `<library>/database/Photos.sqlite` **and** `Photos.sqlite-wal`; reload when the key changes. Do not include `-shm` (readers touch it). Photos writes land in the `-wal` first, so the main file's mtime alone lags. [CITED: sqlite.org/wal.html — general WAL behaviour; the `-wal` mtime claim is [ASSUMED] until D-03 changes a keyword and watches both mtimes]. The path comes from the public `db.db_path` (ends `database/Photos.sqlite`) [VERIFIED].
**Trade-off to state in the decision:** per-call load is simplest and always fresh but repeats an O(library) parse and, while Photos is open, a full database copy per call; the cache pays one stat of two files per call and holds the parsed library in memory between calls. If D-03's measured open time on a real library is under about 1 s, per-call is acceptable and the cache can wait; otherwise cache. [ASSUMED: threshold is a judgment call]

### Pattern 3: Albums
```python
albums = db.album_info          # non-shared albums only (shared: db.album_info_shared, out of scope)
for a in albums:
    a.uuid                      # str, uppercase UUID
    a.title                     # str
    a.folder_names              # list[str], [] at top level  -> Pointer.folder = " / ".join(...) or None
    len(a.photos)               # builds PhotoInfo objects for the album; count only
```
Observed on this Mac: 12 albums, every `len(a.photos) == 0` while the library holds 57 trashed assets, so album membership excludes trashed assets. [VERIFIED: ran probe2.py] Pointer: `id=a.uuid`, `summary=clean_summary(f"{title} ({n} photos)")`, `deeplink=""`. osxphotos has no deeplink helper (grep of the wheel: no `photos://`); keep `deeplink=""` as today. Wrap in `read_result(pointers, cap=MAX_ALBUMS)`.

### Pattern 4: Metadata by id (D-05 whitelist) — attribute map
All read from the 0.77.2 wheel source and exercised on a real `PhotoInfo`: [VERIFIED: photoinfo.py, exifinfo.py in the wheel; probe2.py types]

| Whitelist field | osxphotos attribute | Type / note |
|---|---|---|
| dates | `p.date` (taken), `p.date_added`, `p.date_modified` | tz-aware `datetime`; `date_modified` can be `None` (observed `NoneType`); `isoformat()` |
| location | `p.latitude`, `p.longitude` | `float | None`; `p.location` is a tuple |
| place name | `p.place.name` | `str`; `p.place` is `None` when no reverse geocode (`PlaceInfo5`); `p.place.names` is a `PlaceNames` object (city, country, …) |
| persons | `p.persons` | `list[str]` |
| camera / lens / lens | `p.exif_info.camera_make`, `.camera_model`, `.lens_model` | `str | None`; `exif_info` is a frozen `ExifInfo` dataclass with all-`None` fields when absent |
| focal / aperture / shutter / ISO | `.focal_length`, `.aperture`, `.shutter_speed`, `.iso` | floats/int; observed `shutter_speed=0.03125` (seconds), `aperture=1.6` (f-number), `focal_length=5.96` (mm) |
| pixel size | `p.width`, `p.height` | `int` (edited/current); `p.original_width/original_height` exist |
| kind flags (for refusal) | `p.ismovie`, `p.live_photo`, `p.hasadjustments`, `p.intrash`, `p.ismissing`, `p.iscloudasset` | `bool` |
| file presence | `p.path`, `p.path_edited` | `str | None`; both `None` when the asset is not on disk |
| search text | `p.original_filename`, `p.filename`, `p.title`, `p.description`, `p.keywords`, `p.labels` | `title`/`description` can be `None`; `labels` comes from Photos' search index (`search_info`) |

Lookup: `db.get_photo(uuid)` returns the `PhotoInfo` **regardless of trash** or `None`. It is case-sensitive: uppercase UUID found, lowercase returned `None` [VERIFIED]. So: normalise (`strip().split("/")[0].upper()`), validate against `UUID_PATTERN` (`[0-9a-fA-F]{8}-…`, `osxphotos/_constants.py:737`), call `get_photo`, then decide whether `intrash` counts as "unknown" (Open Question 3). The old AppleScript id suffix is `/L0/001` for photos [VERIFIED: photoscript 0.6.1 `UUID_SUFFIX_PHOTO = "/L0/001"`].

### Pattern 5: Search — QueryOptions is AND-only, so write one predicate
`PhotosDB.query(QueryOptions(...))` combines every set field with AND (`photoquery.py` filters `photos` successively). There is **no "any field" option**. D-04 wants one query string over filename, title, description, keywords, place, persons, labels. Two ways:
- 7 separate `query()` calls and a union (each call re-lists photos), or
- **one** `db.photos()` (non-trashed by default) and a single Python predicate over those seven attributes using `text.fold_text` (the repo's existing diacritic/smart-punctuation fold). Recommended: one pass, same fold as Notes, trivially fakeable. Cap with `MAX_PHOTOS` and `truncated`. `db.photos()` signature: `(keywords, uuid, persons, albums, images=True, movies=True, from_date, to_date, intrash=False)`. [VERIFIED: inspect.signature]
Filename match: both `original_filename` (what the user sees as `IMG_xxxx`) and `filename` (the mangled on-disk name).

### Pattern 6: Export — what to call and how it behaves
Call `PhotoInfo.export(dest, filename=..., edited=<bool>, overwrite=False, increment=False)`. In 0.77.2 its signature has **no** `use_photokit`/`download_missing`, and `use_photos_export=False` is the default; `ExportOptions` defaults are `download_missing=False, use_photokit=False, use_photos_export=False, exiftool=False, convert_to_jpeg=False, live_photo=False, raw_photo=False`. [VERIFIED: ran `inspect.signature` and `dataclasses.fields` on the installed 0.77.2]
Observed behaviour (probe3.py, library assets that are trashed iCloud assets):
- File on disk, not edited: `exported` = 1 path, 0.03 s, file named as passed, nothing else written beside it.
- File **not on disk** (`ismissing`): `ExportResults.missing` = 1, `exported` = `[]`, `error` = `[]`, nothing written, **Photos.app did not launch** (`pgrep -x Photos` before and after). So the no-network path is the default.
- `edited=True` on an asset without adjustments: `ValueError("Photo does not have adjustments, cannot export edited version")`. So set `edited = p.hasadjustments`.
- Destination exists with `increment=False, overwrite=False`: `FileExistsError`. (With `increment=True`, the default, osxphotos silently renames to `name (1).ext` — never use the default.)
**Design consequences:**
1. Decide `absent` yourself from `src = p.path_edited if p.hasadjustments else p.path`; `src is None` → `{"id", "status": "absent"}`. Do not infer absence from an empty export result.
2. `PhotoInfo.export()` returns only `results.exported` and drops `results.error`. After a pre-checked export, an empty list is a failure → raise `VerificationFailed`; then `files.confirm_written(path)`.
3. Name the file from the **actual source suffix** (`Path(src).suffix`): a HEIC original can have a JPEG edit, and osxphotos warns when the extension is wrong. Recommended name: `safe_basename(f"{stem}_{uuid[:8]}{suffix}")` so two photos called `IMG_0001.HEIC` do not collide (Open Question 5; discretion).
4. Refuse before any file work: `ismovie` → typed refusal; `live_photo` → export the still only and say the motion part was skipped (D-08 says Live Photo motion is refused: pick "refuse the motion, export the still" and state it in the result).
5. Size check from `os.stat(src).st_size` **before** export (`files.check_size`). No reported-size dependency.
6. The docs page (`rhettbull.github.io/osxphotos/API_README.html`) shows `use_photokit=True` as a default in a `PhotoInfo.export` signature; the 0.77.2 wheel does not. **Trust the wheel; pin `<0.78` and add a unit test that fails if the export call ever passes or defaults a download option** (Pitfall 4).

### Pattern 7: Notes — FTS5 body search, with the real cause of the short-word gap
**The "tax" gap is not an FTS5 property.** FTS5 matches short tokens: in a `:memory:` table with `tokenize='porter unicode61 remove_diacritics 2'`, `MATCH '"tax"'` returned the note containing "Tax", and `"cafe"` matched "Café". [VERIFIED: ran, SQLite 3.50.4] The loss comes from the spike's own query tokenizer, `tokens()` in `.planning/spikes/004-notes-semantic-cost/measure.py`: `[t for t in re.findall(r"\w+", fold_text(q)) if len(t) >= 4]`. [VERIFIED: measure.py read; the skill reference says the same: "The `len >= 4` filter is the spike's heuristic; it drops short words such as 'tax'"]. D-14's rationale ("FTS alone drops short words") should be read as "the measured configuration drops them".
**Recommended policy:** build the OR expression from tokens of length ≥ 4 (the measured configuration, hit@1 0.54), and **if no token is that long, use all tokens** so a one-word query like "tax" still reaches the bodies. The existing folded substring pass (title/snippet) is kept as is, so no result that exists today disappears (D-14). Each token is a double-quoted FTS5 phrase, so query text is never FTS5 syntax; double any embedded `"`. Keep the existing post-fold empty-query guard (`ValueError`). [Open Question 6 for the ordering]
**Corpus read** (verbatim source: `_FROM` in `adapters/notes.py:344-352`, `_decode_note_data` at `:437`):
```python
head = "FROM ZICCLOUDSYNCINGOBJECT o"
frm = _FROM.replace(head, f"{head} JOIN ZICNOTEDATA d ON d.Z_PK = o.ZNOTEDATA", 1)
rows = conn.execute(
    "SELECT o.Z_PK, o.ZTITLE1, d.ZDATA, o.ZISPASSWORDPROTECTED " + frm
).fetchall()
live = [(pk, title or "", text) for pk, title, blob, locked in rows
        if not locked and (text := _decode_note_data(blob)) is not None]
db = sqlite3.connect(":memory:")
db.execute("create virtual table f using fts5(id unindexed, body, "
           "tokenize='porter unicode61 remove_diacritics 2')")
db.executemany("insert into f values (?, ?)", [(pk, f"{t}\n{x}") for pk, t, x in live])
hits = [r[0] for r in db.execute("select id from f where f match ? order by bm25(f)", (expr,))]
```
[Source: skill reference `notes-search.md` lines 21-48, adapted; the join text was checked against `_FROM`.]
**Fingerprints.** `_FINGERPRINT` (notes.py:58) does not cover `ZICNOTEDATA`; `_BODY_FINGERPRINT` (notes.py:78) does. The body pass must call `runtime.verify_sqlite_schema(conn, _BODY_FINGERPRINT)` itself and, on `SchemaDrift` or `sqlite3.OperationalError` (e.g. "no such module: fts5"), keep the substring results and say so in `coverage` — not fall back to AppleScript, which would lose the title/snippet plane that still works.
**Envelope.** Mirror Reminders: keep `get_pointers(query) -> list[Pointer]` unchanged (tests at `tests/test_notes.py:397-455` and the `PointerSource` contract rely on it) and add `NotesAdapter.read(query) -> dict` returning `read_result(...)`; `server.notes()` calls `read()`. `read_via_sqlite` returns whatever `query`/`fallback` return, so let both closures return `(pointers, plane, coverage)` and build the envelope after. Fallback → `plane="applescript"`, `coverage="titles only — body search needs Full Disk Access"`. Body-pass skipped → `coverage="body search unavailable: <reason>"`. `truncated` comes free from `read_result(cap=MAX_NOTES)`.
**Cost.** Every call gunzips and protobuf-decodes every live note: instant at 17 notes (spike: 21 KiB index). It is O(library) per call; note this in a `shortcut:` comment with the upgrade trigger (a few thousand notes).
**Locked notes.** The substring pass still lists locked notes (🔒 prefix, `tests/test_notes.py:399` pins `get_pointers("secret")` matching the locked note's title). The body pass excludes `ZISPASSWORDPROTECTED = 1`. Test the exclusion by the flag, not by decode failure (the synthetic store at `tests/test_notes.py` `_make_notestore` gives the locked note a decodable body).

### Pattern 8: `mail_files.py` → `files.py` (D-11) — exact rename inventory
Public names today: `root()`, `safe_basename(name, fallback)`, `resolve_dest(dest_dir)`, `target_path(dest_dir, name, fallback)`, `check_size(size, name)`, `confirm_written(path)`, constant `MAX_BYTES = 25 * 1024 * 1024` (`mail_files.py:46`), `_FALLBACK = "attachment"` (`:42`), `_MAX_NAME_BYTES = 200` (`:50`), `_DEFAULT_ROOT = "~/Downloads"` (`:52`). Env var `MACOS_APPS_FILE_ROOT` (`:62`). [VERIFIED: grep -n and read]
Importers (grep of `macos_apps_mcp tests scripts docs`):
- `macos_apps_mcp/adapters/mail.py`: docstring refs at `:40`, `:1442`, `:2474`; import list `:96` (`mail_files,`); uses `mail_files.target_path` (`:2496`) and `mail_files.resolve_dest` (`:2513`).
- `macos_apps_mcp/adapters/mail_attachments.py`: docstring `:5`; `from . import mail_addressing, mail_files` (`:30`); comments `:127`, `:134`; `check_size` (`:326`), `target_path` (`:328`), `MAX_BYTES` passed into the AppleScript argv (`:336`), `confirm_written` (`:344`).
- `tests/test_mail_files.py` (21 tests, imports `from macos_apps_mcp.adapters import mail_files`) → rename to `tests/test_files.py`.
- `tests/test_mail_extras.py`: docstring `:3`; `str(mail.mail_files.MAX_BYTES)` at `:72` (an exact argv assertion) and `mail.mail_files.MAX_BYTES + 1` at `:240`.
- `docs/mail-applescript-facts.md` `:161-171` (prose names `mail_files`), `docs/ROADMAP.md:46`.
- `server.py:614` and `:647` docstrings mention `MACOS_APPS_FILE_ROOT` only (no import).
Refusal texts that say "mail" or "attachment": `resolve_dest` ("mail can only be written under it"), `check_size` ("Save it from Mail directly"), `confirm_written` ("the attachment is not available locally (the account may be offline, or the message not downloaded)"), module docstring, `_FALLBACK = "attachment"`. Tests match on the substrings `"outside"`, `"already exists"`, `"larger than"`, `"0 bytes"` (`tests/test_mail_files.py:120,125,135,162,177,197`) and `"cap"` (`tests/test_mail_extras.py:242`): keep those substrings.
Suggested shape: `check_size(size, name, *, max_bytes)` and `confirm_written(path, *, hint="")`; Mail keeps its 25 MiB as `MAIL_MAX_BYTES` in `mail_attachments.py` (the value also feeds the AppleScript argv at `:336`), Photos defines its own. `tests/test_import_layers.py` only forbids imports back to `server`; a package-level `files.py` is allowed. `tests/test_native_seam.py` globs `adapters/*.py` and asserts `len(_NATIVE_MODULES) >= 10` — moving one file out leaves the count above that.

### Anti-Patterns to Avoid
- **Top-level `import osxphotos`** anywhere in the package: slows import, drags PyObjC Photos/Vision into every test and shim, and defeats the fail-closed seam.
- **Letting osxphotos pick the filename or increment on collision** (`increment=True` default, `filename=None`): the overwrite refusal must run in Python first.
- **Deciding `absent` from an empty `export()` result.**
- **Inline thumbnails or bytes** (REQUIREMENTS out-of-scope; `exif_info`/`place` whitelist only).
- **`PhotosDB(...)` per call while Photos is open and the library is large** without a measurement (temp database copy per call).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Reading `Photos.sqlite` | Own SQL against Z-tables | osxphotos `PhotosDB` | D-01; the schema moves each macOS release (PITFALLS #9, osxphotos#1651) |
| Hostile-filename → path | New sanitiser for photo names | `files.safe_basename` / `target_path` | Already hostile-input tested (bidi override, NUL, traversal, 4 KB names); a shared copy is the whole point of D-11 |
| Diacritic/smart-punct fold | New normaliser | `text.fold_text` | Same fold Notes and Mail use |
| Bounded-read wire shape | New dict | `contracts.read_result` | One envelope, one test |
| Body ranking | Custom TF-IDF | SQLite FTS5 `bm25()` | Already in the shipped Python |
| Locked-note handling | New crypto/decoder | Skip `ZISPASSWORDPROTECTED` rows | Locked bodies are encrypted; never attempt |
| Photo test JPEG with EXIF | Pillow (not a dependency) | ImageIO via PyObjC `Quartz` (already a transitive dependency once osxphotos lands) | See Environment / Pattern 9 |

## Runtime State Inventory

Rename/refactor items in this phase: `mail_files` → `files`; `photos` tool changes mechanism and id semantics.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | Vault notes cite old Photos ids in the AppleScript form `<UUID>/L0/001` (CONTEXT: "already cited in notes"). The audit log records tool names and verbs, not module names. No datastore keys the module name `mail_files`. | Code edit only: `photo_info`/`export_photo` accept and reduce the old form. No data migration. |
| Live service config | None — verified by grep: no launchd plist, config file or dashboard references `mail_files` or a Photos tool name. | None |
| OS-registered state | The TCC Automation grant for `com.apple.Photos` stays in `TCC.db` after `"Photos"` leaves `_AUTOMATION_APPS`; harmless. launchd label unchanged. | Optional doc note: the grant can be removed by hand; no code. |
| Secrets/env vars | `MACOS_APPS_FILE_ROOT` keeps its name and meaning (D-11). | None |
| Build artifacts | The installed `/Applications/macos-apps-mcp.app` runs the old code until rebuilt and reinstalled (`CLAUDE.md`: "The repo is not the daemon"). The scratch venv in this session's scratchpad is not part of the repo. | Rebuild + `ditto` + restart daemon, then prove `doctor().build` changed before any device claim. |

## Common Pitfalls

### Pitfall 1: Thin `libdisclaim_*.dylib` files fail the universal2 gate (NEW — not in D-02)
**What goes wrong:** `osxphotos/lib/libdisclaim_arm64.dylib` is arm64-only and `libdisclaim_x86_64.dylib` is x86_64-only (`file` and `lipo -archs` output: arm64 / x86_64, `minos 11.0`). In `scripts/build_app.sh` the two per-arch trees both contain both files, `cmp -s` says identical so no `lipo` runs, and the gate `[[ "$(lipo -archs "$f")" == "x86_64 arm64" ]]` fails with `NOT UNIVERSAL2: …/osxphotos/lib/libdisclaim_arm64.dylib`. D-02's emulation checked `minos` only. [VERIFIED: ran `file`/`vtool` on the unzipped wheel; read `scripts/build_app.sh`]
**Why it happens:** the dylibs exist for the osxphotos CLI (`cli/cli.py:12` is the only importer of `osxphotos.disclaim`, and only when running under PyInstaller/pyapp). The library never loads them. [VERIFIED: grep of the wheel]
**How to avoid:** delete them from **both** trees right after the `uv pip install` loop (`rm -f "$WORK/site-$a/osxphotos/lib/"libdisclaim_*.dylib`). Deleting from `$SITE` after `ditto` is wrong: the later `find . -type f` loop walks the aarch64 tree, `cmp -s` then fails on the missing file, and the script exits `ARCH-SPECIFIC NON-BINARY`. Add a `tests/test_packaging.py` needle for `libdisclaim` beside `"ARCH-SPECIFIC NON-BINARY"` (`test_build_script_gates_universal2`).
**Warning signs:** build log line `NOT UNIVERSAL2: … libdisclaim_…`.

### Pitfall 2: cffi and pycparser re-enter the bundle
**What goes wrong:** `xattr` (`Requires-Dist: cffi>=1.16.0`) ← `osxmetadata` ← `osxphotos`. `uv export --prune cryptography` drops cffi/pycparser only while nothing else needs them. After this phase the bundle carries `_cffi_backend` (loaded at `import osxphotos`). `docs/DAEMON.md` says "The build leaves out cryptography, cffi and pycparser" and the build script comment says the same. [VERIFIED: read both; `Requires-Dist` from the installed `xattr` metadata]
**Impact:** documentation and a comment go stale; cryptography stays out (its Intel-wheel problem, #205/#322, is unchanged). cffi has per-arch cp314 wheels (above), so the build's `lipo` path handles it. The Intel slice already carries `allow-unsigned-executable-memory`, which covers libffi closures.
**How to avoid:** update the comment and the DAEMON.md paragraph to say cryptography only; keep `--prune cryptography`. Do not "fix" it by pruning cffi (xattr would fail at import).

### Pitfall 3: First `import osxphotos` is slow and runs inside a tool call
**What goes wrong:** 5.5 s cold / 0.65 s warm here (fresh venv); D-02 measured 8.2 s. In the bundle `.pyc` are precompiled, but the first load of ~40 new signed `.so` can still cost seconds. A client with its own tool timeout may report failure on the first Photos call.
**How to avoid:** lazy import on the worker (Pattern 1); never add a deadline on the shim↔daemon hop (CLAUDE.md, #170). Optionally warm the import when the daemon starts, off the request path — Open Question, not required. Record the cold first-call time in the D-03 output.

### Pitfall 4: A docs/source mismatch could silently enable a network download
**What goes wrong:** the published API docs show `use_photokit=True` as the default of `PhotoInfo.export`; the 0.77.2 source has no such parameter and `ExportOptions.use_photokit` defaults to `False`. A future osxphotos minor could change that default, and a download would start Photos.app or PhotoKit, breaking D-09.
**How to avoid:** pin `<0.78`; call `PhotoInfo.export` with explicit keyword arguments only; add a unit test with a fake `PhotoInfo.export` that records its kwargs and asserts `use_photos_export` is absent or `False` and no `download_missing`/`use_photokit` key exists; keep the pre-check for `path`/`path_edited`.

### Pitfall 5: Empty or failed export looks like absence (or success)
`PhotoInfo.export` hides `results.error`. See Pattern 6 points 1-2. Also `files.confirm_written` removes a 0-byte file and raises.

### Pitfall 6: AppleScript cannot delete imported test photos (D-15)
Photos' scripting dictionary: `delete` — "Delete an object. Only albums and folders can be deleted." [VERIFIED: `/System/Applications/Photos.app/Contents/Resources/Photos.sdef` line 118]. `import` exists (`IPXSimpo`, optional `into` album, `skip check duplicates`). So a script can import a throwaway photo and delete a throwaway **album**, but not the photo. photoscript 0.6.1 has no photo delete either (it deletes albums and folders only). See Open Question 1.

### Pitfall 7: A second Photos database copy in `$TMPDIR` while Photos is open
See Pattern 2. Mention in the security section; the cache reduces the number of copies; nothing in this phase deletes osxphotos's temp directory early.

### Pitfall 8: `get_photo` is case-sensitive
Lowercase UUID → `None` (verified). Uppercase after validation.

### Pitfall 9: No schema fingerprint of our own for `Photos.sqlite` (D-01)
D-01 forbids our own read, so the Mail/Reminders-style `*_FINGERPRINT` is not available. The canary is functional: the D-03 device check reads a known imported photo back by id and compares date/EXIF; `doctor` or the tool `coverage` can report `db.photos_version` and the model version so a drift report names the version. osxphotos's tested model range ends at 13999 and this Mac is 270010300. [VERIFIED: `_constants.py:56` `_PHOTOS_5_MODEL_VERSION = [13000, 13999]`; D-02]

### Pitfall 10: Real library is empty of live photos
57 assets, all trashed, 45 of them not on disk, 12 on disk (3 movies), none with adjustments, none live. [VERIFIED: probe2.py counts] Any "reads back by id" proof needs an imported photo. Trashed assets are readable by uuid, which matters for Open Question 3.

## Code Examples

### The Photos search predicate (one pass, existing fold)
```python
# adapters/photos.py (shape only)
from ..text import fold_text, clean_summary

def _haystack(p) -> list[str]:
    place = p.place.name if p.place else ""
    return [p.original_filename, p.filename, p.title or "", p.description or "",
            *p.keywords, place, *p.persons, *p.labels]

def _matches(p, needle: str) -> bool:
    return any(needle in fold_text(s or "") for s in _haystack(p))
```
[Attributes verified in Pattern 4; `fold_text` and `clean_summary` are existing `text.py` helpers (imported today in `adapters/photos.py` and `adapters/notes.py`).]

### Export orchestration (shape only)
```python
src = p.path_edited if p.hasadjustments else p.path
if src is None:
    return {"id": uuid, "status": "absent"}          # iCloud copy only; nothing downloaded
files.check_size(os.stat(src).st_size, name, max_bytes=PHOTO_MAX_BYTES)
dest = files.target_path(dest_dir, f"{stem}_{uuid[:8]}{Path(src).suffix}", fallback="photo")
done = p.export(str(dest.parent), filename=dest.name, edited=bool(p.hasadjustments),
                overwrite=False, increment=False)
if not done:
    raise VerificationFailed("osxphotos reported no file written …")
size = files.confirm_written(dest)
```
`PhotoInfo.export(dest, filename=None, edited=False, live_photo=False, raw_photo=False, export_as_hardlink=False, overwrite=False, increment=True, sidecar_json=False, sidecar_exiftool=False, sidecar_xmp=False, use_photos_export=False, timeout=120, exiftool=False, …) -> list[str]` [VERIFIED: signature printed from 0.77.2].

### Throwaway test JPEG with EXIF-style metadata, no new dependency
Quartz ImageIO from PyObjC wrote a 16×12 JPEG (1,032 bytes); `sips -g make -g model` read back `TestMake` / `TestModel`; `CGImageDestinationFinalize` returned `True` with Exif (DateTimeOriginal, ISO, FocalLength, FNumber, LensModel) and GPS dictionaries supplied. `sips` does not print the Exif or GPS keys, so whether Photos ingests them is a device check, not proven. [VERIFIED: ran; Exif/GPS ingestion by Photos is UNPROVEN]
```python
from Quartz import (CGColorSpaceCreateDeviceRGB, CGBitmapContextCreate, CGBitmapContextCreateImage,
    kCGImageAlphaNoneSkipLast, CGImageDestinationCreateWithURL, CGImageDestinationAddImage,
    CGImageDestinationFinalize, kCGImagePropertyExifDictionary, kCGImagePropertyTIFFDictionary,
    kCGImagePropertyGPSDictionary)  # + the Exif/TIFF/GPS key constants
```
`exiftool` is installed on this Mac (`/opt/homebrew/bin/exiftool`) and can verify Exif/GPS in the file before import; it is not needed by osxphotos here (`exiftool=False`). Tag the helper as test-only.

### Importing a throwaway photo (device tests only; not product code)
Photos AppleScript `import` (needs Automation for Photos in the test host): `tell application "Photos" to import {POSIX file "…"} into album "…" skip check duplicates true`. photoscript `PhotosLibrary().import_photos(paths, album=, skip_duplicate_check=True)` wraps the same call (it first launches Photos and waits). `osxphotos import` CLI also exists. All three go through Photos.app. [VERIFIED: Photos.sdef lines 53-67 for the verb and parameters; photoscript 0.6.1 `import_photos` source]. Residue: the photo stays in the library (Pitfall 6).

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| Photos.app AppleScript `search` (20 s cold, `<UUID>/L0/001` ids) | osxphotos at-rest read (open 0.05–0.1 s on this library), plain UUID ids | Faster, no Automation needed for Photos, id changes form (accept both) |
| pyproject note "osxphotos pins pyobjc-core<10" | osxphotos 0.77.2 requires `pyobjc-core>=10.0` for `platform_release >= 22 or python >= 3.12`; the `<10` pin applies only to Python <3.12 on macOS <13 [CITED: PyPI `requires_dist`] | The note is stale; replace it with the probe result |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Universal2 `.so` doubling makes the app grow by roughly +60 to +100 MB | Standard Stack | Only a size expectation; build log shows the real number |
| A2 | `Photos.sqlite-wal` mtime moves on Photos writes before a checkpoint; main-file mtime alone lags | Pattern 2 | Cache would serve stale data; D-03 must change a keyword and watch both mtimes |
| A3 | A 1 s open-time threshold is the right line between per-call load and the cache | Pattern 2 | Wrong choice costs latency or staleness, not correctness |
| A4 | `osxphotos>=0.77.2,<0.78` makes uv fork resolution fail or stay quiet in the py3.11/macOS 12 fork | Standard Stack | The first task has to adjust `[tool.uv] environments`; read resolver output |
| A5 | FDA granted to `ren.lav.macos-apps-mcp` is enough to read `~/Pictures/…photoslibrary` (no separate Photos TCC row) | Summary / Validation | `PhotosDB()` raises `PermissionError` in the daemon; D-03 and the read-plane device test must run **as the daemon**, not only from a terminal |
| A6 | FTS5 `bm25()` gives ~zero weight to stopwords so OR-ing short tokens is harmless for ranking | Pattern 7 | Noisy ranking when the fallback "all tokens" branch fires; mitigated because that branch only fires for queries with no token ≥ 4 chars |
| A7 | `photos://asset?uuid=` is not used as a deeplink | Pattern 3 | None — `deeplink=""` stays |
| A8 | A PhotoKit `deleteAssets` call shows a user-confirmation prompt on macOS | Open Question 1 | Only matters if the owner wants scripted cleanup; web search was inconclusive |
| A9 | Export file naming `stem_uuid8.ext` is acceptable | Pattern 6 | Cosmetic; planner's discretion |

## Open Questions (RESOLVED)

1. **D-15 says imported test photos are "removed afterwards", but Photos AppleScript cannot delete media items.**
   - What we know: `delete` accepts albums and folders only (Photos.sdef:118); photoscript has no photo delete; PhotoKit `deleteAssets` likely needs a user confirmation (unverified, A8); the library on this Mac currently holds 0 live photos.
   - What's unclear: whether the owner accepts residue.
   - Recommendation (default): the device test imports into a uniquely named throwaway **album** with a unique filename marker, records the uuid, deletes the **album** in teardown, and the integration test prints the leftover uuid plus a one-line manual cleanup ("select, Delete, then Recently Deleted"). Treat as a contradiction with D-15: "removed" is met for the album, the export directory and the file, not for the library asset.
   - RESOLVED: every throwaway photo is named `macos-apps-mcp-test-<purpose>-<stamp>.jpg` and goes into the one album `macos-apps-mcp-test`; scripts remove export directories at once; the photos are deleted (and emptied from Recently Deleted) in ONE owner sitting at the end of the phase, then a read through the daemon proves none is left and the album is deleted by script → plan 04-01 Task 2 (first import), 04-05 Task 3 (integration test), 04-06 Tasks 3–4 (sitting and proof).
2. **Does the Intel iMac (macOS 15) get the same signed-bundle import gate?** It is the other deployment target and has hardened-runtime history (#205). Default: yes, run the D-03 import + `PhotosDB()` check there through the remote session after the arm64 pass, read-only.
   - RESOLVED: deferred, not a task. This Mac's build smokes and reads both slices (x86_64 under Rosetta); the iMac run happens only if the owner asks, and 04-01's SUMMARY lists it under "Deferred" → plan 04-01 Task 1 (both slices on this Mac).
3. **Are trashed assets visible to `photo_info`/`export_photo`?** `get_photo` returns them. Default: treat `intrash` as unknown id (`ValueError`), consistent with `photos()` (`intrash=False` default) and with what the user sees in Photos.
   - RESOLVED: a trashed photo is an unknown id (`ValueError`) for `photo_info` and `export_photo` → plan 04-04 Task 1 (`photo_info`), 04-05 Task 2 (`export_photo`).
4. **`uv add` pin and fork.** Default `osxphotos>=0.77.2,<0.78`. If uv rejects the macOS-12 fork, add `[tool.uv] environments` excluding it instead of loosening. The planner records the resolver output in the decision (SC-1).
   - RESOLVED: run `uv add 'osxphotos>=0.77.2,<0.78'` first and quote its output. If it fails only on the Python 3.11 + macOS 12 split, put the marker on the dependency itself (`; python_version >= "3.12" or platform_release >= "22"`) rather than `[tool.uv] environments`: the marker leaves only Photos missing on that platform, while an environments list would also stop `uv sync` there, and `uvx` (which ignores the lock) would still fail to resolve. The pin is never loosened → plan 04-01 Task 1.
5. **Export file name.** Default `<original stem>_<first 8 of uuid><source suffix>`. Alternative `<stem>_edited<suffix>` (osxphotos's own) collides across photos.
   - RESOLVED: `<original stem>_<first 8 of uuid><source suffix>`, passed through `files.target_path` → plan 04-05 Task 1.
6. **Notes merge order.** Default: substring hits first (today's order), then body-only hits by bm25, deduped by `Z_PK`, capped at `MAX_NOTES`. Alternative: rank everything by bm25 with substring hits as a boost. Spike 004's 0.54 hit@1 measures the pure bm25 ranking, not this merge; the first implementation should re-measure on the 17-note corpus with `$SPIKE_PRIVATE_DIR` queries before the choice is final.
   - RESOLVED: substring hits first in today's order, then body-only hits by `bm25` (ties: higher `Z_PK` first), deduped by `Z_PK`, capped at `MAX_NOTES`. No re-measure: this merge cannot move any result that today's matcher returns, which is what D-14 protects; the private query set stays out of the repo → plan 04-03 Tasks 1–2.
7. **Export size cap.** Default 250 MiB (ProRAW DNG is about 75 MB; [ASSUMED]); `MAX_ALBUMS = 100`; `MAX_PHOTOS = 25` kept.
   - RESOLVED: `PHOTO_MAX_BYTES = 250 * 1024 * 1024`, `MAX_ALBUMS = 100`, `MAX_PHOTOS = 25` → plan 04-04 Tasks 1–2 (caps), 04-05 Task 1 (export cap).
8. **Live Photo.** D-08 says the motion part is refused. Default: export the still, return `status: "written"` plus `skipped: "live photo motion"`; refuse movies outright.
   - RESOLVED: a Live Photo exports its still with `skipped: "live photo motion"`; a video raises `WriteRefused` before any file work → plan 04-05 Task 2.
9. **Contradiction check against locked decisions:** none found. One tension: D-03 says the gate runs "in that signed bundle", but the bundle's identity (TCC) is only in force when the daemon itself runs; a terminal-launched run is attributed to the terminal's grants (A5). Proposed resolution: plan 1 proves import + open from the signed binary on both slices; the first read-plane device test proves FDA as the daemon.
   - RESOLVED: as proposed. 04-01 proves `import osxphotos`, `PhotosDB()`, read-back and export from the signed binary on both slices; 04-06 Task 1 makes the first Photos read through the installed daemon (the bundle shim), which proves Full Disk Access under the daemon's own identity → plan 04-01 Tasks 1–4, 04-06 Task 1.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| uv | `uv add`, build | ✓ | 0.13.0 | — |
| Python (uv-managed PBS) | tests, scratch | ✓ | 3.14.5 | — |
| Rosetta 2 | x86_64 smokes in the build | ✓ | `arch -x86_64 /usr/bin/true` exits 0 | — |
| `vtool`, `lipo` | universal2 gate | ✓ | CLT | — |
| `actool` (full Xcode) | icon compile in the build | ✓ via `DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer` | Xcode present | `xcrun -f actool` fails without DEVELOPER_DIR; the script handles it |
| Developer ID Application identity | signed build | ✓ | 1 identity found | unsigned dev build cannot prove #2175 |
| PBS tarballs cache | build | ✓ | both arches, 3.14.5+20260510 | script downloads and checks sha256 |
| notarytool | optional notarize | ✓ | 1.1.3 | — |
| Photos library (system) | device tests | ✓ | model 270010300, 57 assets all trashed | import throwaway photos |
| exiftool | optional EXIF verification of the test JPEG | ✓ | `/opt/homebrew/bin/exiftool` | `sips` shows make/model only |
| Installed daemon | device tests | ✓ running | `/Applications/macos-apps-mcp.app` | — |
| Intel iMac (REMOTE imac2012) | Open Question 2 | not probed | — | skip, note as a gap |

**Missing dependencies with no fallback:** none.
**The signed-bundle gate commands** (for the planner to name):
```sh
scripts/build_app.sh --sign "<Developer ID Application identity>" --out dist
# log must show, in order: universal2 gate ok … ; smokes ok: arm64 ; smokes ok: x86_64 ;
# entitlements ok … ; signed smoke ok: arm64 ; signed smoke ok: x86_64
for a in arm64 x86_64; do
  /usr/bin/arch -$a dist/macos-apps-mcp.app/Contents/MacOS/macos-apps-mcp -E -s -P -B -c \
   "import osxphotos; db = osxphotos.PhotosDB(); print(osxphotos.__version__, db.db_version, db.photos_version, len(db.photos()))"
done
codesign --verify --strict --verbose=2 dist/macos-apps-mcp.app     # seal intact (-B writes no .pyc)
/usr/bin/log show --last 3m --predicate 'sender == "AppleMobileFileIntegrity"' | grep -ci "CT signature\|CMS blob"   # expect 0
```
Edit the two build smokes so they import osxphotos (the unsigned `-c "import macos_apps_mcp"` and the signed `-c "import ctypes, macos_apps_mcp.server …"`): `import macos_apps_mcp.server` will not import osxphotos once the import is lazy. Keep `PhotosDB()` out of the build smokes (needs a library and FDA). `tests/test_packaging.py::test_build_script_gates_universal2` asserts `src.count("for a in arm64 x86_64; do") == 3`; edit the `-c` strings, do not add a loop.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x (`>=8,<10`), `addopts = "-m 'not integration'"` |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]`; `tests/conftest.py` (autouse `_no_real_osascript`, `_isolated_state`) |
| Quick run command | `uv run pytest tests/test_files.py tests/test_photos.py tests/test_notes.py tests/test_native_seam.py tests/test_tool_annotations.py tests/test_registry.py tests/test_packaging.py tests/test_mail_extras.py tests/test_doctor.py -x -q` |
| Full suite command | `uv run pytest && MACOS_APPS_READ_ONLY=1 uv run pytest && uv run ruff check . && uv run ruff format --check .` (unit suite about 19 s; CI runs both pytest forms on `macos-latest` after `uv sync --locked`) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PHO-01 | osxphotos in `dependencies`, stale comment gone; thin dylibs removed by the build; smokes import osxphotos | unit (text assertions) | `uv run pytest tests/test_packaging.py -x` | ✅ extend |
| PHO-01 | Signed bundle imports osxphotos, opens `PhotosDB()`, no AMFI lines, both slices | device-only (build + commands above) | manual | ❌ record in plan SUMMARY |
| PHO-02 | `photo_albums` → Pointers in `read_result`, capped, `truncated` at cap, folder label | unit with fakes | `uv run pytest tests/test_photos.py -k albums -x` | ❌ Wave 0 |
| PHO-03 | `photo_info` whitelist only, hygiene applied, unknown/malformed id → `ValueError`, old `/L0/001` id reduced, lowercase uppercased, trashed → unknown | unit | `uv run pytest tests/test_photos.py -k info -x` | ❌ Wave 0 |
| PHO-03 | `photos(query)` searches the seven fields, folded, capped | unit | `uv run pytest tests/test_photos.py -k search -x` | ❌ Wave 0 |
| PHO-04 | export: absent when no file; refuses movie; edited iff `hasadjustments`; never overwrites; size cap; empty export → `VerificationFailed`; kwargs carry no download option | unit | `uv run pytest tests/test_photos.py -k export -x` | ❌ Wave 0 |
| PHO-04 | `export_photo` registered additive, audit verb `export`, in `envelope_only`, docstring names Full Disk Access | unit | `uv run pytest tests/test_tool_annotations.py tests/test_registry.py -x` | ✅ extend tables |
| PHO-04 | exported file opens as an image (`sips -g pixelWidth`) | device-only | `uv run pytest -m integration tests/integration/test_photos_integration.py` | ❌ Wave 0 |
| D-11 | `files.py` behaves as `mail_files` did; Mail callers unchanged | unit | `uv run pytest tests/test_files.py tests/test_mail_extras.py tests/test_mail_attachments.py -x` | ✅ rename |
| D-15 | A unit test that forgets to fake `photos_db` raises, does not open a library | unit | `uv run pytest tests/test_native_seam.py -x` | ✅ extend |
| NOTE-01/02 | Decision recorded; no `[semantic]` extra, no ML dependency in `pyproject.toml` | unit (text) | `uv run pytest tests/test_packaging.py -x` | ✅ extend (assert no `fastembed`/`onnxruntime`/`numpy` in dependencies) |
| D-13/D-14 | body-only hit found; substring hit kept; locked excluded by flag; short single word finds body; envelope `plane`/`coverage` in fallback; fts5-missing and body-schema-drift keep substring results with `coverage` | unit (synthetic NoteStore from `tests/test_notes.py::_make_notestore`) | `uv run pytest tests/test_notes.py -k "body or fts or envelope" -x` | ✅ extend |
| D-07 | `Photos` out of `_AUTOMATION_APPS`; doctor surface count and lists updated | unit | `uv run pytest tests/test_doctor.py -x` | ✅ edit |

### Sampling Rate
- **Per task commit:** the quick command for the files the task touched.
- **Per wave merge:** full suite (both pytest forms) plus ruff.
- **Phase gate:** full suite green; device tests run manually on a rebuilt, reinstalled daemon; `doctor().build` shows the new build.

### Wave 0 Gaps
- [ ] `tests/_fakes.py` — `FakePhoto` (SimpleNamespace with the Pattern 4 attributes, an `export()` that records kwargs and writes bytes) and `FakePhotosDB` (`album_info`, `photos(**kw)`, `get_photo(uuid)`, `db_path`)
- [ ] `tests/test_photos.py` — rewrite (the old tests parse AppleScript output and go away with `_parse`)
- [ ] `tests/integration/test_photos_integration.py` — `@pytest.mark.integration`, throwaway album/JPEG helper (ImageIO), teardown deletes album + export dir, prints leftover uuid
- [ ] `tests/conftest.py:215` and `tests/test_native_seam.py:30` plus its parametrize list — add `photos_db`
- [ ] `tests/test_files.py` — `git mv tests/test_mail_files.py`, import `from macos_apps_mcp import files`
- [ ] Edits to frozen tables: `tests/test_registry.py` — `_DEVELOP_ADDITIVE` (+`export_photo`, list near line 32), `_DEVELOP_PERMISSION` (`"photos": "Full Disk Access"` at the `"photos"` entry; + `photo_albums`, `photo_info`, `export_photo`), the verbs table (`"export_mail": "export"` at line 242 → + `"export_photo": "export"`); `test_permission_reproduces_the_develop_era_hand_map` compares with `==`, so a missing entry fails. `tests/test_tool_annotations.py:111-135` `envelope_only` + `"export_photo"`.
- [ ] `tests/test_doctor.py`: lines 101 (surface name list), 373 and 496 (`== 12` → 11), comment 492-493; `tests/test_integration.py:585` `test_photos_search_runs` (AppleScript era).
- [ ] No framework install needed.

Device-only (never CI): signed-bundle gate; `PhotosDB()` under the daemon identity; import-by-script, read-by-id, export, `sips` open check; Rosetta and Intel slices; measuring the cold first-call time and the open time on a library with photos (feeds the Pattern 2 decision).

## Security Domain

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | — (local daemon; TCC grants are the access control) |
| V3 Session Management | no | — |
| V4 Access Control | yes | Tier gates at registration (`_additive_tool` skipped under `MACOS_APPS_READ_ONLY`); export confined to the allowlisted root |
| V5 Input Validation | yes | UUID pattern check before lookup; `fold_text` guard for empty queries; `files.safe_basename`/`resolve_dest`; FTS5 tokens quoted |
| V6 Cryptography | no | none added; locked notes stay unread (never decrypt) |
| V8 Data Protection | yes | No second copy of note text on disk (in-memory FTS); document the Photos temp database copy; no image bytes or thumbnails in results |
| V12 Files and Resources | yes | `files.py` rules: derived basename, containment after `resolve()`, no overwrite, size cap, empty-file removal |
| V14 Configuration / supply chain | yes | `osxphotos<0.78` cap; 66+ new transitive packages; package audit above; signed bundle with every `.so` signed |

### Known Threat Patterns
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Hostile original filename on a photo shared by someone else (`../../x`, bidi override, dotfile) | Tampering | `files.safe_basename`; name is derived from the stem and source suffix, never concatenated |
| `dest_dir` traversal or symlink out of the root | Tampering / EoP | `resolve_dest` checks containment after `resolve()`; nothing created before the check |
| Overwriting an existing file | Tampering | Python-side refusal before osxphotos writes; `increment=False, overwrite=False` as the second line |
| Prompt injection in photo titles, descriptions, keywords, person names, place names, labels | Spoofing / Tampering | `clean_summary`/`clean_body` hygiene; the `UntrustedDataNotice` middleware stays on (do not set `notice=False`) |
| Silent network or Photos.app launch on export | Information disclosure | Pre-check `path`/`path_edited`; no `download_missing`/`use_photos_export`/`use_photokit`; test pins the kwargs |
| Whole-library dump or large result | DoS / Information disclosure | Caps (`MAX_PHOTOS`, `MAX_ALBUMS`, `MAX_NOTES`), `truncated` flag, whitelist-only `photo_info` |
| Location (GPS) disclosure to the model | Information disclosure | Intentional per PHO-03; keep it in `photo_info` only, not in search Pointers |
| Photos database copy in `$TMPDIR` while Photos is open | Information disclosure | Cache to limit copies; note in docs; osxphotos cleans its `TemporaryDirectory` when the object is freed |
| Notes holding credentials copied into an index | Information disclosure | No sidecar; per-call `:memory:` connection closed after the read; locked notes excluded |
| Unsigned/ad-hoc `.so` rejected by AMFI (#2175) | DoS | Build signs every `.so`/`.dylib` with Developer ID; signed smoke on both slices; AMFI log check |
| Malicious or compromised new dependency | Tampering | Locked, hashed install (`--require-hashes`); version cap; owner-approved checkpoint |

## Sources

### Primary (HIGH confidence — read or run this session)
- osxphotos 0.77.2 wheel contents (`photosdb/photosdb.py`, `photoinfo.py`, `photoquery.py`, `photoexporter.py`, `exportoptions.py`, `exifinfo.py`, `albuminfo.py`, `utils.py`, `disclaim.py`, `lib/README.md`, `_constants.py`) — unzipped from the PyPI wheel and read; plus runs in a scratch venv.
- photoscript 0.6.1 and py-applescript 1.0.3 wheels (import-time behaviour: no Apple event at import; `import_photos`; `UUID_SUFFIX_PHOTO`).
- `/System/Applications/Photos.app/Contents/Resources/Photos.sdef` (verbs `import`, `delete`, `export`, `search`).
- In-repo files read: `scripts/build_app.sh`, `pyproject.toml`, `macos_apps_mcp/{server,runtime,contracts,doctor,errors,notices,registry}.py`, `adapters/{photos,notes,mail_files,mail_attachments,mail_index}.py`, `adapters/mail.py` (export section), `tests/{conftest,test_native_seam,test_tool_annotations,test_registry,test_packaging,test_notes,test_photos,test_mail_files,test_import_layers}.py`, `docs/DAEMON.md`, `CHANGELOG.md`, `CREDITS.md`, spike 004 README, `measure.py`, `results-retrieval.json`, skill reference `notes-search.md`.

### Secondary (MEDIUM — external pages fetched)
- [osxphotos 0.77.2 on PyPI (JSON)](https://pypi.org/pypi/osxphotos/0.77.2/json) · [🔖 2026-10-18](https://linkding.lav.ren/bookmarks?details=2028) — `requires_dist`, MIT, wheel `py3-none-any`, upload 2026-09-27.
- [osxphotos issue #2175](https://github.com/RhetTbull/osxphotos/issues/2175) · [🔖 2026-10-18](https://linkding.lav.ren/bookmarks?details=2029) — open since 2026-07-18; macOS 26.5.2, uv tool install, Python 3.12/3.13, osxphotos 0.75.9/0.76.1; AMFI "no CMS blob … Unrecoverable CT signature issue" on wrapt and pyobjc `.so`; root cause unconfirmed; no workaround.
- [cffi 2.1.1 on PyPI (JSON)](https://pypi.org/pypi/cffi/2.1.1/json) · [🔖 2026-10-18](https://linkding.lav.ren/bookmarks?details=2030) — cp314 macOS wheels for x86_64 and arm64.
- [osxphotos API reference](https://rhettbull.github.io/osxphotos/API_README.html) · [🔖 2026-10-18](https://linkding.lav.ren/bookmarks?details=2033) — documents `PhotosDB`, `photos()`, `query()`, `PhotoInfo.export()`; its export signature differs from the 0.77.2 source (Pitfall 4); no Full Disk Access statement found in the first 100,000 characters.

### Tertiary (LOW)
- Web search for PhotoKit `deleteAssets` confirmation on macOS: inconclusive (A8).

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH for osxphotos facts (source read and run); MEDIUM for pin/fork behaviour (uv not run).
- Architecture: HIGH for seam, registry, Notes and `files.py` (read in the repo); MEDIUM for the cache policy (needs a measured library).
- Pitfalls: HIGH for thin dylibs, cffi, `get_photo` case, export behaviours (reproduced); MEDIUM for #2175 (upstream unconfirmed) and FDA-in-daemon (A5).

**Research date:** 2026-10-18
**Valid until:** 2026-11-01 (osxphotos releases every few weeks; re-check the version and the `export` signature before the pin)
