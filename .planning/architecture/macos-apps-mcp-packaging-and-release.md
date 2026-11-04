---
kind: component
title: Packaging and release
component: packaging-and-release
status: implemented
source_revision: 18dcbf6594bbd62330f71c89376a54155dda1d63
source_evidence_date: 2026-11-04
review_status: independent-review-complete
publication_status: published
first_published_at: "2026-11-04T01:34:18Z"
first_published_revision: 93c7f0928d2534ddae2392e78ec722f55491a2ae
---

# Packaging and release

[Architecture overview](macos-apps-mcp-architecture.md)

## Implemented build boundary

`scripts/build_app.sh` builds a self-contained universal2 app for arm64 and x86_64.
It combines matching Python 3.14.5 standalone interpreter trees and compatible native dependency slices.
The Python package retains its `>=3.12` floor.
`uv.lock` supplies hash-checked runtime dependencies and build constraints. The project wheel installs without dependency resolution.
All locked runtime dependencies needed by the bundle remain included.

The build checks every Mach-O architecture and minimum macOS version, then exercises imports and actual-shim transport on both slices.
Bytecode is prepared before signing to avoid modifying sealed bundle contents during ordinary imports.
The bundle records its Git build identity separately from the package version.

The app bundle and SMAppService launchd agent provide the deployment identity used for macOS privacy grants.
Signed builds and installed grants remain distinct from ordinary repository execution.
Source merges do not replace the installed app. A new deployment requires installation, daemon restart, and client reconnection.

**eli14:** Packaging puts the workshop's tools into one labelled crate.
Checking both compartments proves that both sets of tools are present and can start in the tested environment.
It does not prove that the crate was delivered, installed, or tested on a physical Intel Mac.
A new crate label also cannot change the crate already in use.

## Cryptography compatibility exception

The lock selects cryptography 48.0.1. The Intel dependency declaration retains the `<49` cap.
MCP 2 imports cryptography for request-state encryption even when authentication is disabled, so the bundle cannot prune it.
The recorded exception is limited to the reviewed local configuration and AES-GCM/HKDF request-state path.
It is not a general claim that the retained version is safe.

The [2026-11-03 security assessment](../phases/05.4-mcp-2-fastmcp-4-migration/05.4-SECURITY.md) records affected APIs and the reachability evidence.
Dependency alerts remain open under that decision.
Authentication, certificate-chain verification, PKCS#7 processing, or relevant dependency changes require reassessment.
This source overview does not claim a new advisory review.

## Distribution notices — #553

The build inspects installed `*.dist-info` metadata in both architecture trees and the final site-packages tree.
It requires nonempty licence material and copies version-pinned, hash-checked fallback texts before signing.
`Contents/Resources/THIRD_PARTY_NOTICES/index.json` records notice locations and fallback use.
Other shipped notices remain in their distribution metadata directories.

Missing material, changed hashes, version drift, obsolete mappings, redundant fallbacks, and legacy `.egg-info` metadata stop the check.
The inventory covers site-packages distributions, not the Python interpreter or every native Python library.
Material presence does not by itself establish complete legal compliance.

## Acceptance and release states

The [migration implementation record](../phases/05.4-mcp-2-fastmcp-4-migration/05.4-IMPLEMENTATION.md) reports an unsigned universal bundle and successful slice tests.
The x86_64 execution used Rosetta on an Apple-silicon host.
That evidence is not signing, notarization, installation, physical Intel acceptance, or native application acceptance.
The installed daemon's current version and build require separate fresh evidence.

The latest published release remains `v0.15.1`, verified on 2026-11-04.
The GSD `v0.11.0` label describes a planning milestone, not the current software release.
The [release procedure](../../docs/RELEASING.md) separates integration into `develop`, release cuts into `main`, distribution, and installed-daemon proof.
`doctor().version` and `doctor().build` identify what actually serves a deployed request.

## Sources and planned work

- [build_app.sh](../../scripts/build_app.sh), [pyproject.toml](../../pyproject.toml), [uv.lock](../../uv.lock), and [Info.plist](../../packaging/Info.plist).
- [bundle_licenses.py](../../scripts/bundle_licenses.py), [notice evidence](../../packaging/licenses/README.md), and [licence tests](../../tests/test_bundle_licenses.py).
- [Deployment implementation](../../macos_apps_mcp/deploy.py) and [daemon runbook](../../docs/DAEMON.md).
- [Phase 05.4 decisions](../phases/05.4-mcp-2-fastmcp-4-migration/05.4-DECISIONS.md) and [Phase 6 distribution scope](../ROADMAP.md).

The universal build and notice inventory are implemented.
Remaining distribution work includes release bundles, the Homebrew cask, and companion guidance/plugin delivery as specified in Phase 6.
Current-source installed-device acceptance remains pending.
