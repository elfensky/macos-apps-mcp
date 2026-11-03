# Bundled distribution notices

The build copies these exact upstream texts into `Contents/Resources/THIRD_PARTY_NOTICES/` before signing.
Other licence files remain in each installed `*.dist-info` directory.
`index.json` in the output lists notice locations for both architecture trees and the final site-packages tree.

The build requires nonempty files under `licenses/`, or named `LICENSE*`, `COPYING*`, or `NOTICE*`.
A metadata licence name, empty file, empty directory, or external symlink does not satisfy the check.
The fallback manifest pins distribution versions and SHA256 hashes of every copied file.
The check refuses missing texts, changed bytes, version drift, removed distributions, and redundant fallback groups.

**eli14:** Each dependency is a parcel with a permission slip.
The build checks every parcel and supplies a verified replacement when its slip is missing.
An empty envelope stops the build today. A dependency update needs a new check before a future release.

## Sources

Evidence date: 2026-11-03 UTC. Local date: 2026-11-04 Europe/Brussels.
`manifest.json` records source artifact URLs, archive members, and SHA256 hashes.
Source distributions were downloaded from the exact URLs in `uv.lock` and verified against its hashes.
The build uses these local files without network access.

- **bpylist2 4.1.1:** `LICENSE` is the exact MIT section of the release archive's `README.rst`.
  It retains `Copyright (c) 2017 Marketcircle Inc.`
  The archive has no separate licence file; its README supplies the full text.
  [Release page](https://pypi.org/project/bpylist2/4.1.1/) · [🔖 2026-11-03](https://linkding.lav.ren/bookmarks?details=4687).
  The same README identifies the bundled `_plistlib.py` source as CPython commit
  `90549676e063c2c818cfc14213d3adb7edcc2bd5`. `CPython-LICENSE` preserves that commit's complete licence.
  [CPython licence](https://github.com/python/cpython/blob/90549676e063c2c818cfc14213d3adb7edcc2bd5/LICENSE) · [🔖 2026-11-03](https://linkding.lav.ren/bookmarks?details=4692).
- **dnspython 2.9.0:** the release source archive also lacks `LICENSE`.
  The fallback comes from tag `v2.9.0`, commit `e790c8f20a67ad439c7aafef2321e161c6028eee`.
  It retains the Dnspython Contributors, Nominum, and Google notices.
  [Release licence](https://github.com/rthalley/dnspython/blob/v2.9.0/LICENSE) · [🔖 2026-11-03](https://linkding.lav.ren/bookmarks?details=4688).
- **fastmcp-slim 4.1.6:** the fallback is `LICENSE` from the matching `fastmcp-4.1.6` release archive.
  Slim contains the framework code. The `fastmcp` distribution supplies its dependencies and Apache-2.0 licence.
  The complete recursive release tree contains no `NOTICE` file.
  [Release tree](https://github.com/PrefectHQ/fastmcp/tree/1302563111a0e72176174cdb5ac19838cb0687c3) · [🔖 2026-11-03](https://linkding.lav.ren/bookmarks?details=4689).
- **PyObjC 12.2.2:** all 11 affected source archives contain byte-identical `License.txt` files.
  One shared copy retains both copyright lines, including Ronald Oussoren's 2003–2025 notice.
  Each distribution's source artifact is listed separately in the manifest.
  [Release](https://github.com/ronaldoussoren/pyobjc/releases/tag/v12.2.2) · [🔖 2026-11-03](https://linkding.lav.ren/bookmarks?details=4690).
- **pytimeparse2 1.7.1:** `LICENSE.rst` is copied unchanged from its release source archive.
  It retains Sergey Klyuykov's 2021 copyright notice.
  [Release page](https://pypi.org/project/pytimeparse2/1.7.1/) · [🔖 2026-11-03](https://linkding.lav.ren/bookmarks?details=4691).

## Maintenance

1. Build from the updated lock. Inspect missing-notice failures in both architecture trees.
2. Retrieve the matching upstream release artifact. Verify its hash against `uv.lock` where available.
3. Preserve exact licence text, copyright notices, and any required `NOTICE` material.
4. Update the distribution version, source evidence, and file hashes in `manifest.json`.
5. Remove entries for distributions that disappeared or now ship their own notices.
6. Run the packaging tests and the real universal bundle build.

Do not use generic licence templates or inferred copyright holders.
Record unavailable sources as blockers. A test fixture does not prove upstream licence coverage.
