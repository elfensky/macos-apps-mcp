# Packaging and release

## What it does

`scripts/build_app.sh` builds a self-contained universal2 app for arm64 and x86_64.
It combines matching Python 3.14.5 standalone interpreter trees and compatible native dependency slices.
The Python package retains its `>=3.12` floor.
`uv.lock` supplies hash-checked runtime dependencies and build constraints. The project wheel installs without dependency resolution.
All locked runtime dependencies needed by the bundle remain included.

The build checks every Mach-O architecture and minimum macOS version, then exercises imports and actual-shim transport on both slices.
Bytecode is prepared before signing to avoid modifying sealed bundle contents during ordinary imports.
The bundle records its Git build identity separately from the package version.
The build copies `packaging/sitecustomize.py` into the bundle's site-packages, so a start with no arguments runs the `launch` role.
It installs `packaging/cli.sh` as `Contents/Resources/bin/macos-apps-mcp`. The wheel ships neither file.

The app bundle and SMAppService launchd agent provide the deployment identity used for macOS privacy grants.
Signed builds and installed grants remain distinct from ordinary repository execution.
Source merges do not replace the installed app. A new deployment requires installation, daemon restart, and client reconnection.



### Distribution notices — #553

The build inspects installed `*.dist-info` metadata in both architecture trees and the final site-packages tree.
It requires nonempty licence material and copies version-pinned, hash-checked fallback texts before signing.
`Contents/Resources/THIRD_PARTY_NOTICES/index.json` records notice locations and fallback use.
Other shipped notices remain in their distribution metadata directories.

Missing material, changed hashes, version drift, obsolete mappings, redundant fallbacks, and legacy `.egg-info` metadata stop the check.
The inventory covers installed distribution metadata. It does not cover the bundled Python interpreter or its native libraries.
Material presence does not by itself establish complete legal compliance.

## Rules it keeps

### Cryptography compatibility exception

The lock selects cryptography 48.0.1. The Intel dependency declaration retains the `<49` cap.
MCP 2 imports cryptography for request-state encryption even when authentication is disabled, so the bundle cannot prune it.
The recorded exception is limited to the reviewed local configuration and AES-GCM/HKDF request-state path.
It is not a general claim that the retained version is safe.

The [2026-11-03 security assessment](https://github.com/elfensky/macos-apps-mcp/blob/834691b4ab771698a09d63e7546a0781caf4b548/.planning/phases/05.4-mcp-2-fastmcp-4-migration/05.4-SECURITY.md) records affected APIs and the reachability evidence.
Authentication, certificate-chain verification, PKCS#7 processing, or relevant dependency changes require reassessment.
This source overview does not claim a new advisory review.

### Signing and release

`--notarize` submits a zip made before stapling. Re-create the distribution zip after stapling, so that the zip carries the ticket.
The GSD `v0.11.0` label describes a planning milestone, not the current software release.
The [release procedure](https://github.com/elfensky/macos-apps-mcp/blob/834691b4ab771698a09d63e7546a0781caf4b548/docs/RELEASING.md) separates integration into `develop`, release cuts into `main`, distribution, and installed-daemon proof.
`doctor().version` and `doctor().build` identify what actually serves a deployed request.
After a deploy, `uv run pytest -m device` tests the installed daemon through its socket. The release checklist requires its reads and writes to pass.

## Code paths

- [build_app.sh](https://github.com/elfensky/macos-apps-mcp/blob/834691b4ab771698a09d63e7546a0781caf4b548/scripts/build_app.sh), [pyproject.toml](https://github.com/elfensky/macos-apps-mcp/blob/834691b4ab771698a09d63e7546a0781caf4b548/pyproject.toml), [uv.lock](https://github.com/elfensky/macos-apps-mcp/blob/834691b4ab771698a09d63e7546a0781caf4b548/uv.lock), and [Info.plist](https://github.com/elfensky/macos-apps-mcp/blob/834691b4ab771698a09d63e7546a0781caf4b548/packaging/Info.plist).
- [bundle_licenses.py](https://github.com/elfensky/macos-apps-mcp/blob/834691b4ab771698a09d63e7546a0781caf4b548/scripts/bundle_licenses.py), [notice evidence](https://github.com/elfensky/macos-apps-mcp/blob/834691b4ab771698a09d63e7546a0781caf4b548/packaging/licenses/README.md), and [licence tests](https://github.com/elfensky/macos-apps-mcp/blob/834691b4ab771698a09d63e7546a0781caf4b548/tests/test_bundle_licenses.py).
- [Deployment implementation](https://github.com/elfensky/macos-apps-mcp/blob/834691b4ab771698a09d63e7546a0781caf4b548/macos_apps_mcp/deploy.py) and [daemon runbook](https://github.com/elfensky/macos-apps-mcp/blob/834691b4ab771698a09d63e7546a0781caf4b548/docs/DAEMON.md).
- [sitecustomize.py](https://github.com/elfensky/macos-apps-mcp/blob/834691b4ab771698a09d63e7546a0781caf4b548/packaging/sitecustomize.py), [cli.sh](https://github.com/elfensky/macos-apps-mcp/blob/834691b4ab771698a09d63e7546a0781caf4b548/packaging/cli.sh), and [packaging tests](https://github.com/elfensky/macos-apps-mcp/blob/834691b4ab771698a09d63e7546a0781caf4b548/tests/test_packaging.py).

## Sources

- [Phase 05.4 decisions](https://github.com/elfensky/macos-apps-mcp/blob/834691b4ab771698a09d63e7546a0781caf4b548/.planning/phases/05.4-mcp-2-fastmcp-4-migration/05.4-DECISIONS.md) and [Phase 6 distribution scope](https://github.com/elfensky/macos-apps-mcp/blob/834691b4ab771698a09d63e7546a0781caf4b548/.planning/ROADMAP.md).

The latest published release is `v0.15.1`, checked on 2026-11-09.
Dependabot alerts 2, 17 and 18 for cryptography are dismissed as `not_used` since 2026-10-25. MCP 2 now imports cryptography, so that dismissal reason is out of date.

The [migration implementation record](https://github.com/elfensky/macos-apps-mcp/blob/834691b4ab771698a09d63e7546a0781caf4b548/.planning/phases/05.4-mcp-2-fastmcp-4-migration/05.4-IMPLEMENTATION.md) reports an unsigned universal bundle and successful slice tests.
The x86_64 execution used Rosetta on an Apple-silicon host.
That evidence is not signing, notarization, installation, physical Intel acceptance, or native application acceptance.
The [2026-11-04 installed evidence](https://github.com/elfensky/macos-apps-mcp/blob/834691b4ab771698a09d63e7546a0781caf4b548/.planning/overnight/2026-11-04-installed-acceptance.md) establishes signed arm64 build 7bc8607, version 0.15.1, native reads, and normal restart recovery.
Strict signature verification and all 133 distribution notice records passed after installation.
The [Mail recovery test](https://github.com/elfensky/macos-apps-mcp/blob/834691b4ab771698a09d63e7546a0781caf4b548/.planning/overnight/2026-11-04-mail-recovery-acceptance.md) also passed on this installed build; strict signature verification still passed afterward.
[Notarization and physical Intel installation](https://github.com/elfensky/macos-apps-mcp/blob/834691b4ab771698a09d63e7546a0781caf4b548/.planning/overnight/2026-11-04-notarization-intel-acceptance.md) passed for the same build.
Both protocol eras and bounded native reads passed on Intel; its final signature, staple, and Gatekeeper checks passed.
On build `3dd93b2`, the read-only device suite passed with 19 tests and 0 failures. A real frontend survived a daemon restart and an outage.
Phase 05.4 verification passed on 2026-11-06. The release stays open.

The universal build and notice inventory are implemented.
Remaining distribution work includes release bundles, the Homebrew cask, and companion guidance/plugin delivery as specified in Phase 6.
The Phase 05.2 reply acceptance and the localized Mail writes stay open. Other phases own them.
