# Phase 4: Notes & Photos — Settle the Mechanism, Then Ship the Read Plane - Discussion Log (Assumptions Mode)

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the analysis.

**Date:** 2026-10-09
**Phase:** 04-notes-photos-settle-the-mechanism-then-ship-the-read-plane
**Mode:** assumptions
**Areas analyzed:** Photos mechanism and dependency boundary; Photos read plane; Photos export; Notes

## Device probe (orchestrator, before the questions)

| Probe | Result |
|-------|--------|
| `uv add osxphotos` in a throwaway worktree | exit 0; osxphotos 0.77.2; 66 new packages; no existing pin moved; forked resolution (Python 3.11 + macOS 12 → 0.65.0 and pyobjc 10.3.2) |
| `.app` install gate, emulated (export + wheels-only install per arch, Python 3.14, target 15.0) | both arches exit 0; same distributions and non-binary files; every Mach-O minos ≤ 11.0 |
| `import osxphotos`; `PhotosDB()` on the system library | 8.2 s first import; 0.1 s open; model 270010300 (osxphotos tests up to 13999); 12 albums, 32 persons, 57 assets, all trashed |
| Upstream (GitHub API) | MIT, 2019-06, 3.9k stars, 0.77.2 on 2026-09-27; open #2003 (shared albums, macOS 26), #2175 (AMFI signature issue, uv install, macOS 26.5.2); closed #2221 (macOS 27) |

## Assumptions Presented

### Photos mechanism and dependency boundary
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Two gates: the resolve, then the `.app` build | Likely | `scripts/build_app.sh` 79-126; 0.14.2 cryptography prune |
| A clean resolve does not prove the macOS 27 schema | Likely | `.planning/research/PITFALLS.md` 177-193 (osxphotos#1651) |
| Base dependency, not an extra | Unclear | `server.py` 115-186 (no import gate); `pyproject.toml` 43 |
| PhotoKit fallback costs a new TCC grant; persons become a gap | Likely | `packaging/Info.plist`, `entitlements.plist`, `eventkit.py` 98-146 |

### Photos read plane
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| One id across search, info and export | Likely | `adapters/photos.py` 36-39 |
| `read_result` envelope, capped; fixed metadata whitelist; no bytes | Confident | `contracts.py` 123-153; `REQUIREMENTS.md` 134 |
| Reads on the single worker; library load per call vs cached | Unclear | `runtime.py` 433-492 |

### Photos export
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| `@_additive_tool(audit="export")`, `envelope_only` | Confident | `server.py` 601-624; `tests/test_tool_annotations.py` 111-140 |
| Shared write-to-disk module, per-caller cap | Likely | `adapters/mail_files.py`; CLAUDE.md one-adapter rule |
| Edited still vs original | Unclear | PHO-04, criterion 3 |
| iCloud-only original reported `absent` | Likely | `adapters/mail.py` 2475-2477 |

### Notes
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| NOTE-01 closes "not adopted"; NOTE-02 not applicable | Confident | spike 004, owner 2026-09-28 |
| FTS5 body search has not shipped; it ships in Phase 4 | Likely | `adapters/notes.py` 528-576 |
| In-memory FTS per call, no sidecar | Likely | spike 004 (21 KiB, 17 notes); notes hold secrets |
| Keep title matches; envelope with `plane`/`coverage` | Likely | `notes.py` 556-568; `contracts.py` 136-139 |

## Corrections Made

### Photos mechanism
- **Original assumption:** osxphotos, with a first task that proves the macOS 27 schema (recommended); alternatives own `Photos.sqlite` reader, PhotoKit.
- **Owner's first reply:** leaning towards PhotoKit; asked what osxphotos is, whether it is mature, and whether it supplements or replaces PhotoKit.
- **Answer given:** osxphotos is a third-party reader of `Photos.sqlite` (maturity facts above) that uses PhotoKit internally for some exports, so it replaces our own PhotoKit code. A third shape was offered: PhotoKit plus a read-only store read for persons and EXIF (the Reminders pattern).
- **Owner correction:** osxphotos for everything — one surface, fewer chances for bugs, one CLI (paraphrased).

### Dependency boundary
- **Owner:** base dependency.

### Export
- **Owner:** edited still.

## External Research
- osxphotos upstream facts were read through the GitHub API (repository, releases, issue search). PhotoKit person/EXIF access was stated from knowledge, not re-verified, because PhotoKit was not chosen.
