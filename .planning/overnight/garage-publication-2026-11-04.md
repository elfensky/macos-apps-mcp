# Garage publication evidence — 2026-11-04

The repository owns the current roadmap and architecture. Garage serves their home-only display copies.
The vault enrollment uses repository mode, so scheduled vault refreshes retain the overview card and skip this project's uploads.

| Evidence | Recorded result |
|---|---|
| First publication | `2026-11-04T01:34:18Z` |
| Published source | `93c7f0928d2534ddae2392e78ec722f55491a2ae` |
| Full `.planning/` source hash | `3ab08b8cea583f0fc7017eddc46e596b38b6f3e307c6d29fcbc446a581074e03` |
| Project identity | `personal-macos-apps-mcp` |
| Vault cutover | MR !2394, head `818baad0`; merged before the upload |
| Local bundle | 15 self-contained HTML pages; 122 internal paths and fragments validated |
| Live copy | All 15 paths returned HTML with status 200 and matched the local bytes |
| Metadata | `page.json` matched the project identity, repository source and full-folder hash |
| Display assets | No external assets or scripts |

## Published paths

- [Current roadmap](https://projects.static.lav.ren/macos-apps-mcp/).
- [Architecture overview](https://projects.static.lav.ren/macos-apps-mcp/architecture/).
- Seven component pages under `architecture/`: `transport`, `tools-and-policy`, `native-access`, `adapters`, `audit-and-recovery`, `operator-controls`, and `packaging-and-release`.
- Six compatibility paths retain the old phase URLs and link to the corresponding current roadmap sections.

The first source contains 20 phases, nine historical closures, 93 plan files and 92 summary files.
The historical verification fingerprints are stale. These counts establish neither current-build acceptance nor release readiness.
The page footer identifies its source commit and the last planning commit date. Neither date is a user-review date.
Later publication replaces the same project folder; this record retains the first verified snapshot.

## Source and acceptance

The local sources are [ROADMAP.md](../ROADMAP.md), [STATE.md](../STATE.md), and the eight curated [architecture notes](../architecture/macos-apps-mcp-architecture.md).
The generated HTML is a display copy. It is not a second roadmap source or a new build framework.
The full project folder is uploaded together so architecture and compatibility paths remain present.

The latest published software release remains `v0.15.1`. The installed build is unverified against this source.
Publication does not establish native acceptance, physical Intel acceptance, signing, notarization, installation, or release.
Architecture user review remains pending. The source-evidence and review qualifications remain unchanged.

**eli14:** The repository is the logbook, and Garage is its noticeboard.
The board now copies that logbook. A correct notice does not prove that the installed machine passed its tests.
