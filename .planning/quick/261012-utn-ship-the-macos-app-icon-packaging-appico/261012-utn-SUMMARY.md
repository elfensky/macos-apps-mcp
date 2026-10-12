---
phase: quick-261012-utn
plan: 01
subsystem: packaging
tags: [app-icon, actool, icon-composer, build]
status: complete
requirements: [QUICK-261012-utn]
key-files:
  created:
    - packaging/AppIcon.icon/icon.json
    - packaging/AppIcon.icon/Assets/ (16 SVG files)
  modified:
    - packaging/Info.plist
    - scripts/build_app.sh
    - tests/test_packaging.py
    - docs/DAEMON.md
    - CHANGELOG.md
commits: 1
plan_head_before: 72f9ff1
plan_head_after: 22870dcd984ec26892d04f6d9dd84093b4c338c1
actuals:
  tokens: 9000
  tasks: 2
  commits: 1
completed: 2026-10-12
---

# Quick 261012-utn: App icon in the .app Summary

The build compiles `packaging/AppIcon.icon` (Icon Composer, copied verbatim) with Xcode's actool into `Contents/Resources`, and a preflight fails fast without actool.

## What changed

- `packaging/AppIcon.icon`: 17 files, `diff -r` identical to the owner's file.
- `packaging/Info.plist`: `CFBundleIconFile` and `CFBundleIconName` are `AppIcon`.
- `scripts/build_app.sh`: preflight sets `ACTOOL` (selected toolchain, else `/Applications/Xcode.app`, else exit 2) before any download. The compile step runs after the bundle reset and before the `Info.plist` copy and signing. It fails the build if `AppIcon.icns` or `Assets.car` is missing or empty.
- `tests/test_packaging.py`: three new tests (plist keys, icon package consistency, build step and order). Each failed before the change and passes after it.
- `docs/DAEMON.md` and `CHANGELOG.md`: end-state text for the full-Xcode need and the icon.

## Verification

- `uv run pytest`: 2010 passed, 97 deselected.
- `uv run ruff check .`: all checks passed.
- `uv run ruff format --check .`: 109 files already formatted.
- actool probe on the committed icon: `ICON-PROBE-OK` (non-empty `AppIcon.icns` and `Assets.car`; partial plist keys equal `packaging/Info.plist`).
- Commit gate: tracked icon files equal the source set; no `.planning/` path in the commit.

## Deviations from Plan

None - plan executed exactly as written. One wording adjustment: the preflight message was re-wrapped so the pinned phrase `the Command Line Tools have no actool` sits on one string fragment.

## Not run

`scripts/build_app.sh` end to end (downloads two interpreters). The icon showing in Finder after a real build is not checked.

## Known Stubs

None.

## Self-Check: PASSED

Commit 22870dc is on `feat/app-icon`; all listed files exist.
