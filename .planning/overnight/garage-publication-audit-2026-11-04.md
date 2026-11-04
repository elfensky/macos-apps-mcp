# Garage publication audit — macos-apps-mcp

Evidence date: 2026-11-04, Europe/Brussels. Final remote snapshot: 2026-11-03T23:32:46Z.
Scope: this project's repository publication and separate vault cutover. No publication or deployment is claimed.

This is a historical working audit. Its PR table records the snapshot above, not current integration state.
[Current roadmap](../ROADMAP.md) and [integration working notes](2026-11-03.md) supersede its PR statuses.
The publication recipe still requires fresh live-source checks.

The existing publisher can deliver the roadmap, architecture overview, and component pages in one project folder.
Publication is blocked by the legacy enrollment, an outdated ordinary checkout, and uncommitted or untracked planning inputs.
No new renderer, Astro project, or keijiban dependency is required.

**eli14:** Garage is a noticeboard. The repository holds the project logbook; the vault keeps its address.
The old copying job must stop replacing this project's notice before the new notice is attached.
Today, the obstacle concerns the noticeboard. Publishing a notice does not replace or verify the installed application.

## 1. Verified state and PR #544

| Item | Verified state |
|---|---|
| Canonical page | <https://projects.static.lav.ren/macos-apps-mcp/> returns 200 HTML. |
| Architecture page | `/macos-apps-mcp/architecture/` returns 404. |
| Published source | `work-personal/projects/macos-apps-mcp/roadmap/macos-apps-mcp-roadmap.md`. |
| Published identity | `personal-macos-apps-mcp`; domain `personal`; slug `macos-apps-mcp`. |
| Evidence versus publication | `page.json.as_of`: `2026-11-01`; `updated`: `2026-11-03T22:36:03Z`. The page cites repository commit `8378ab8`. |
| Live default branch | `refs/heads/develop`, `694275e8bc0dd535d49888d56a5f73ca59fc3f08`. |
| Migration | [PR #550](https://github.com/elfensky/macos-apps-mcp/pull/550) merged as `dce3324195b33ad2afe02d150adc6db786f359e0`. |
| Storage fix | [PR #552](https://github.com/elfensky/macos-apps-mcp/pull/552) merged at `23:30:10Z`, as `694275e8bc0dd535d49888d56a5f73ca59fc3f08`. Reviewed head: `fc37db685cc252bcd6f8bf3ecf09ec65742710f1`. |
| Licence fix | [PR #553](https://github.com/elfensky/macos-apps-mcp/pull/553) remains open at `2f95c814a847ced8dc4962b39bf07b2fc970e17c`. |
| Localized folders | [PR #554](https://github.com/elfensky/macos-apps-mcp/pull/554) remains open at `67cfb879407baac3ec12a39d4a0099f17cc1725c`. |
| Published release | [v0.15.1](https://github.com/elfensky/macos-apps-mcp/releases/tag/v0.15.1), published `2026-10-25T21:04:13Z`. Migration acceptance and release remain pending. |
| Ordinary checkout | the ordinary repository checkout, branch `develop`, observed HEAD `926ec99f42a16c227516b3fd81490fd62a86a935`. |

PR states can change during the parent's work. Publication requires a fresh source check, not these recorded SHAs.

[PR #544](https://github.com/elfensky/macos-apps-mcp/pull/544) remains an open draft on `night/gsd-standard`.
Its head remains `4cc3654cf9b481d2d9ecdebb7b48fdd72b51e1ed`.
GitHub reported `CONFLICTING` against `dce3324`; after #552 merged, its final mergeability response was `UNKNOWN`.
The current head has four successful CodeQL checks. Its body reports older pytest and six-check results; those are not current-head proof.

| Existing #544 scope | Integration consequence |
|---|---|
| Rename `docs/ROADMAP.md` to `docs/landscape.md`; replace forward tables with prior-art requirement references. | Reuse this change. Do not create another landscape rename or duplicate roadmap. |
| Update citations in `PROJECT.md`, codebase maps, phase records, research, the progress guide, and the historical Mail plan. | Preserve these citation changes when adding current architecture links. |
| Untrack `.planning/state.json` and 17 `.planning/research/.cache/` files. Ignore these paths, `.gsd/`, and `.planning/milestone.lock`. | Coordinate with the parent's current state edits. Runtime removal is not permission to lose canonical Markdown evidence. |
| Move `debug/mail-index-schema-sequoia.md` into `research/`; update four citing phase files. | Reuse the move and its citations. The final commit removes the proposed `debug/` ignore rule. |
| Add cockpit-profile and roadmap guidance to `AGENTS.md`. | Replace its obsolete keijiban publication sentence with the current vault page-kit recipe. |
| No profile change in `.planning/config.json`. | Its values already matched the profile. No second profile migration is needed. |

The scopes are compatible, but #544 is not ready for automatic integration.
Its deletion of `state.json` overlaps later changes to that file, including #550 and the parent's unstaged edits.
Its final `.gitignore` also retains an inaccurate comment describing debug records as scratch files.
The existing PR should supply its changes after owner reconciliation, review, and refreshed checks.
This audit does not transfer its ownership or amend it.

The new publication work comprises current roadmap evidence, curated architecture notes, the vault cutover, and the staged HTML.
#544 supplies none of these. It does not modify `.planning/ROADMAP.md` or `.planning/STATE.md` in its diff.
It is not a technical dependency of `publish`; its cleanup must not be silently treated as a completed prerequisite.

## 2. Separate vault cutover MR

Vault project identifier supplied by the parent: `f1f2339d-b088-4e2a-a161-d05ae85dd4a8`.
The following changes belong to a separate vault MR. Other enrollments remain unchanged.

### Decisions and evidence worth preserving

The seven vault roadmap notes contain no unique feature design absent from the repository.
The six milestone notes have empty item lists and placeholder rationale sections.
Their scope and completion dates come from repository commit `8378ab8`, not independent acceptance evidence.

Four qualifications remain useful in the repository's `.planning/PROJECT.md` or architecture overview:

- `active` describes project lifecycle; it does not prove runtime or deployment health.
- Recorded completion dates are historical facts. Undated work has no delivery commitment.
- A phase remains incomplete until its recorded acceptance checks pass.
- Implementation, installed-device acceptance, and release are separate states.

The old next action, “05.2, then 05.6,” must not replace the owner's 2026-11-03 migration-first decision.
That decision already exists in the parent's roadmap and state edits.
No placeholder “Review needed” paragraph requires migration as project content.
The old evidence remains available in vault Git history after the folder deletion.

### Exact vault edits

1. In `meta/project-pages.json:29`, replace the legacy string with this object:

   ```json
   {"mode":"repo","hub":"work-personal/projects/macos-apps-mcp/macos-apps-mcp.md","slug":"macos-apps-mcp"}
   ```

2. In `work-personal/projects/macos-apps-mcp/macos-apps-mcp.md`, retain `id: personal-macos-apps-mcp`.
   Retain `type`, `domain`, `status`, `repo`, `icon`, and the properties used by `projects.base`.
   The missing `title` is acceptable: the renderer uses the note basename.
   Replace `sources[0].resource` at line 12 with the final committed repository roadmap URL and its actual evidence date.
   Replace the line 70 `[[macos-apps-mcp-roadmap|Canonical roadmap]]` link with the repository plan link.
   Retain the hosted roadmap URL. Add source and hosted architecture links after those sources land.
   The source links are:

   - `https://github.com/elfensky/macos-apps-mcp/blob/develop/.planning/ROADMAP.md`
   - `https://github.com/elfensky/macos-apps-mcp/blob/develop/.planning/architecture/macos-apps-mcp-architecture.md`
   - `https://projects.static.lav.ren/macos-apps-mcp/architecture/`

   Retain the short project summary and relevant artifacts links.
   Replace the current-tense FastMCP 2.0, v0.8.0, installed 0.9.0, and old issue-count claims with verified summary text.
   Dated history can remain history. The publication task is complete only after the hosted result is verified.

3. One project-specific preparation note outside this repository needs its legacy references updated.
   The authorized reviewer must update its enrollment check and preserve the task reference.
   Old phase order and single-file upload guidance must be marked historical.
   Its private location is not part of this public evidence.

4. Delete the seven duplicate notes after preserving the qualifications and replacing those references:

   ```text
   work-personal/projects/macos-apps-mcp/roadmap/
     macos-apps-mcp-roadmap.md
     macos-apps-mcp-phase-5-operator-controls.md
     macos-apps-mcp-phase-05-1-dashboard-fixes.md
     macos-apps-mcp-phase-05-2-bug-fixes.md
     macos-apps-mcp-phase-05-4-mcp-migration.md
     macos-apps-mcp-phase-05-6-notes-write-safety.md
     macos-apps-mcp-phase-6-distribution.md
   ```

No pictures or logo files were present in this roadmap folder.
A tracked-file search found no additional milestone wikilinks or roadmap-path references outside the entries listed above.
Repeat that targeted search before deleting the folder, because concurrent vault work can add references.

The cutover must merge before the repository upload.
The script used for the upload must resolve against a vault checkout containing that merged enrollment.
A root-only enrollment preserves the overview row and URL, but supplies no inferred milestone counts or evidence dates.

## 3. Implemented page contract and local files

The current page-kit chapter specifies plain HTML and CSS.
Its component reference is a visual reference, not an executable renderer.
`project-pages.py` renders vault roadmap notes and the overview. Repo entries generate only overview rows.
It has no implemented parser for repository architecture or component notes.

The 2026-11-02 design explicitly marks its documentation implementation as unbuilt.
Its older keijiban/Astro steps are superseded by the plain HTML decision.
Automated Mermaid rendering, retired-slug checks, component validation, and derived cross-project backlinks are not available in this publisher.

The current publisher already accepts an HTML folder with nested paths.
Therefore, the minimal implementation is a locally authored HTML display copy from committed Markdown, with normal relative links.
The architecture overview can contain an inline linked SVG and an equivalent component list.
Mermaid can remain in the Markdown source; there is no requirement to install a renderer for this publication.
Any generated SVG must exist locally before upload and load no remote scripts.

| Location | Contract |
|---|---|
| `.planning/PROJECT.md`, `ROADMAP.md`, `STATE.md`, `REQUIREMENTS.md`, selected phase records | Committed roadmap sources. Published statements refer to the same Git revision. |
| `.planning/architecture/macos-apps-mcp-*.md` | Committed architecture sources. No filename contains `roadmap`. |
| `.planning/architecture/files/` | Optional committed source pictures or diagram assets, only when used. |
| Fresh `$page_tmp/site/index.html` | Local generated roadmap page. Not committed. |
| `$page_tmp/site/architecture/index.html` | Local generated architecture overview. Not committed. |
| `$page_tmp/site/architecture/<component>/index.html` | One local generated page per component. Not committed. |
| `$page_tmp/site/<old-milestone-slug>/index.html` | Compatibility pages for all six existing milestone URLs. |
| `$page_tmp/{enrollment,state,roadmap,blockers,metadata}.json` | Local fact and publication inputs. Outside the uploaded `site/` folder. |
| Vault `meta/files/project-pages/` | Existing gitignored overview preview from the vault `build` command. |

The six compatibility slugs are `phase-5-operator-controls`, `phase-05-1-dashboard-fixes`, `phase-05-2-bug-fixes`,
`phase-05-4-mcp-migration`, `phase-05-6-notes-write-safety`, and `phase-6-distribution`.
Each can redirect locally to its corresponding root phase section, with a visible fallback link.
For example, `phase-05-4-mcp-migration/index.html` can target `../#phase-05-4`.
The root must contain that anchor and link to the committed technical phase records.

Every page needs a title, description, system fonts, light/dark CSS, escaped text, explicit status words, and counts rather than percentages.
The source commit and last `.planning/` commit date must remain separate from evidence review and upload dates.
The current recipe dates all of `.planning/`; the old design's architecture exclusion is not an implemented rule.
The GSD milestone label `v0.11.0` must not be presented as the latest software release.

One directory upload must contain the complete project site.
`publish` replaces the entire slug prefix and deletes absent files.
A root-only HTML upload would remove old milestone pages and architecture pages.
A separate upload using `macos-apps-mcp/architecture` is invalid: the publisher accepts one flat project slug.
The uploaded directory must contain only final display files, never `.planning/`, raw fact JSON, or working notes.

## 4. Source gates, commands, and lock sequence

These are publication instructions for the parent, not commands executed by this audit.

### Current blockers

- The enrollment is still a legacy string. Scheduled vault publication still owns the project folder.
- The ordinary checkout is behind the live default branch. The parent worktree is not an eligible publication checkout.
- Parent-owned roadmap, state, overnight, and migration evidence changes remain uncommitted.
- `.planning/architecture/` does not exist yet.
- The ordinary checkout contains this untracked file:
  `.planning/phases/02.1-mail-fixes-batch-moves-fit-their-timeout-drafts-pick-their-a/.gitkeep`.
- Its ignored `.planning/milestone.lock` and two `05.2-proto/__pycache__/*.pyc` files also fail the current source gate.

The last point is material: `git ls-files --others -- .planning/` includes ignored files.
The recipe says that every planning file must be committed. `publish` also hashes every file under the source folder.
#544's “only `!!` lines remain” instruction does not satisfy this newer gate.
Its untracking of runtime files does not solve that problem when those files remain on disk.
The installed `state json` implementation is read-only; it does not require recreating `state.json` for publication.

The recommended path retains the strict gate and uses an ordinary checkout without untracked planning runtime files.
The parent must resolve ownership before preserving or removing runtime files elsewhere; an active lock cannot be discarded as clutter.
The `.gitkeep` needs an explicit retain-and-commit or remove decision from its owner.
No file was deleted or moved by this audit.

### Minimal sequence

1. Land the repository's reviewed source updates through its PR workflow. Reuse #544's changes where its owner integrates them.
   Include current architecture notes and corrected status distinctions. Keep pending PRs and acceptance gaps explicit.
2. Land the separate vault cutover MR. Validate its enrollment and preview before merge; confirm the merged ordinary vault contains it.
3. Update the ordinary repository checkout with `git pull --ff-only`. Resolve its planning-file blockers without disturbing active sessions.
4. Check the source, extract facts, and create the complete local `site/` folder. Review its pages and links.
5. Acquire the shared refresh lock, recheck the same revision, and upload the entire project folder once.
6. Release that lock. Run the existing vault refresh separately to publish the overview from committed enrollment.
   Verify the canonical page, architecture, component links, six compatibility paths, and source metadata.

Vault checks, from the separate vault lane:

```bash
uv run --script meta/scripts/project-pages.py check
uv run --script meta/scripts/project-pages.py build
meta/scripts/project-pages-refresh --dry-run
```

`--dry-run` renders but does not prove committed-input eligibility. The real refresh checks committed inputs.
The cutover preview must retain the project overview row and omit this project's upload entry.
No shared templates or publisher code need changes for this cutover.

Repository preparation uses Bash, the ordinary checkout, and a new temporary directory:

```bash
set -euo pipefail
export LC_ALL=C
vault="$HOME/vault"
cd "$HOME/Developer/macos-apps-mcp"
repo_root=$(git rev-parse --show-toplevel)
repo=${repo_root##*/}
[[ "$repo_root" == "$HOME/Developer/macos-apps-mcp" ]]
enrollment='work-personal/projects/macos-apps-mcp/macos-apps-mcp.md'
page_tmp=$(mktemp -d)
gsd="$HOME/.codex/gsd-core/bin/gsd-tools.cjs"

check_source() {
  local remote ref sha
  remote=$(git ls-remote --symref origin HEAD) || return 1
  ref=$(printf '%s\n' "$remote" | awk '$1 == "ref:" && $3 == "HEAD" {print $2}')
  sha=$(printf '%s\n' "$remote" | awk '$2 == "HEAD" && $1 != "ref:" {print $1}')
  [[ -n "$ref" && -n "$sha" ]] || return 1
  [[ $(git symbolic-ref --quiet HEAD) == "$ref" ]] || return 1
  [[ $(git rev-parse HEAD) == "$sha" ]] || return 1
  git ls-files --error-unmatch -- .planning/ROADMAP.md .planning/STATE.md >/dev/null || return 1
  git diff --quiet HEAD -- .planning/ || return 1
  [[ -z $(git ls-files --others -- .planning/) ]] || return 1
}
check_source
rendered_head=$(git rev-parse HEAD)
plan_date=$(git log -1 --format='%cI' -- .planning/)
source_sha256=$(
  (cd .planning && find . -type f -print0 | sort -z | xargs -0 shasum -a 256) |
    shasum -a 256 | cut -c1-64
)
```

Use the page-kit chapter's Ruby enrollment extractor with the variables above.
It writes `$page_tmp/enrollment.json` from the explicit enrollment and hub frontmatter.
Require exactly `mode=repo`, `project_id=personal-macos-apps-mcp`, `domain=personal`, and `slug=macos-apps-mcp`.
Do not substitute the obsolete roadmap note path or silently infer an unenrolled project.

```bash
node "$gsd" state json > "$page_tmp/state.json"
node "$gsd" roadmap analyze > "$page_tmp/roadmap.json"
node "$gsd" state get 'Blockers/Concerns' > "$page_tmp/blockers.json"
jq -e 'type == "object" and (has("error") | not)' "$page_tmp/state.json" >/dev/null
jq -e 'type == "object" and (has("error") | not) and (.phases | type == "array")' "$page_tmp/roadmap.json" >/dev/null
jq -e 'if has("error") then .error == "Section or field \"Blockers/Concerns\" not found" else true end' "$page_tmp/blockers.json" >/dev/null
jq '{total: (.phases | length), checked_complete: ([.phases[] | select(.roadmap_complete == true)] | length)}' "$page_tmp/roadmap.json"
```

Use `state json` for the current phase. Inspect roadmap scope and preserve roadmap order, including decimal insertions.
A missing blockers section means “No blockers section recorded,” not “No blockers.”
Checkboxes record roadmap state; they do not prove delivery. Conflicts with summaries or acceptance records need visible qualification.
Create all HTML files locally before the upload, from these facts and the committed architecture notes.

The final upload block uses only supported publisher options:

```bash
jq -e '.mode == "repo" and .project_id == "personal-macos-apps-mcp"
  and .domain == "personal" and .slug == "macos-apps-mcp"' "$page_tmp/enrollment.json" >/dev/null
jq '{project_id}' "$page_tmp/enrollment.json" > "$page_tmp/metadata.json"
slug=$(jq -r '.slug' "$page_tmp/enrollment.json")
domain=$(jq -r '.domain' "$page_tmp/enrollment.json")
lock="$(cd "${TMPDIR:-/tmp}" && pwd -P)/project-pages-refresh.lock"
(
  mkdir "$lock" || { echo 'Another refresh holds the lock' >&2; exit 1; }
  trap 'rmdir "$lock"' EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  check_source
  [[ $(git rev-parse HEAD) == "$rendered_head" ]]
  "$vault/meta/scripts/publish" "$page_tmp/site" "$slug" \
    --bucket projects --domain "$domain" --tags roadmap \
    --source "$repo:.planning" --metadata "$page_tmp/metadata.json" \
    --source-sha256 "$source_sha256"
)
"$vault/meta/scripts/project-pages-refresh"
```

The lock is shared across local worktrees. It is not a distributed lock across Macs.
Another host must not publish concurrently. A pre-existing lock requires investigation, not automatic removal.
The refresh acquires this lock itself; calling it inside the upload's lock would fail.
It checks vault ancestry against freshly fetched `origin/main`, validates and stages all enrolled vault pages, then publishes the overview last.
Repo enrollment excludes this project from those project uploads.
The repo publisher rebuilds `index.json`; it does not render the root overview HTML. That requires the refresh.

The upload writes `page.json`: title, description, domain, tags, source, created, updated, SHA-256, and `project_id`.
Optional project metadata permits only string `status`, `health`, `as_of`, `stale_after`, and `next_action` fields.
The minimal identity-only metadata avoids inventing review dates or health. The Git commit belongs in the HTML, not an unsupported metadata field.
`updated` is publication time; `sha256` is a content hash, not the Git commit.
No input folder should contain its own `page.json`; the publisher reserves that file.

Publication invokes the existing credential mechanism internally.
This audit attempted no 1Password reads. The parent must not expose credentials or bypass a failed bootstrap.
Post-publication checks include 200 HTML, local resource success, the overview link, metadata identity, and the exact displayed source commit.
The source checks must pass again after rendering; a newer default branch requires a new render.

## 5. Required architecture notes

The proposed source files below provide a small component map without copying every adapter into a separate documentation system.
Each component note needs its responsibility, interfaces, limits, source paths, relevant phases, and an eli14 paragraph.
Use `kind: architecture` for the overview and `kind: component` for the component notes as descriptive frontmatter.
No current publisher validates that frontmatter. Stable filenames and URLs remain a manual contract.

| File under `.planning/architecture/` | Required content and source evidence |
|---|---|
| `macos-apps-mcp-architecture.md` | Plain-language overview, component map, source revision, boundaries, and implementation/acceptance/release distinctions. Link the roadmap and every component. |
| `macos-apps-mcp-transport.md` | `daemon.py`: stdio and daemon modes; public FastMCP proxy; MCP 2/httpx2; ten-second connect limit; unlimited read duration and SSE event size; 4 MiB HTTP envelope limit; protocol mirroring; uncertain-outcome warning without replay. Link Phase 05.4. |
| `macos-apps-mcp-tools-and-policy.md` | `server.py`, `contracts.py`, `registry.py`, `tiers.py`, `notices.py`: thin dispatch, typed adapters, pointers and bounded reads, registration gates, read-only precedence, dry runs, untrusted content. Link Phase 1 and planned 05.10/05.7 changes. |
| `macos-apps-mcp-native-access.md` | `runtime.py`, `eventkit.py`, `lifecycle.py`, `errors.py`: one native worker, EventKit affinity, bounded native operations, subprocess cleanup, typed refusals, and macOS-only access. Link Phases 1, 3, and 05.2. |
| `macos-apps-mcp-adapters.md` | Native read stores and action paths for the app families. Mail recovery versus Notes safety gaps; Photos through osxphotos; EventKit for Calendar/Reminders. Link Phase 4 and 05.6. Distinguish #554's pending changes from merged behavior. |
| `macos-apps-mcp-audit-and-recovery.md` | `audit.py`, `files.py`, Mail recovery modules: before-state, receipts, backups, ownership and file modes, and uncertain outcomes. Caller names and shim IDs are advisory. Include merged #552 with its exact scope; do not imply Notes recovery is already complete. |
| `macos-apps-mcp-operator-controls.md` | `dashboard/`, `doctor.py`, `deploy.py`: loopback dashboard separate from UDS MCP, access key, Host/Origin/token checks, adapter toggles, restart, read-only recovery UI, and CLI-only outbound enablement. Link Phases 5, 05.1, 05.2, and pending 05.5. |
| `macos-apps-mcp-packaging-and-release.md` | Locked dependencies, universal2 bundle, TCC bundle identity, daemon restart plus client reconnection, cryptography compatibility exception, signing/notarization and device proof. Link 05.4, #553, Phase 6, and `docs/RELEASING.md`. |

The August `.planning/codebase/ARCHITECTURE.md` is raw historical input, not publication-ready architecture.
It predates the current registry, separated EventKit module, dashboard, osxphotos read plane, and MCP 2 transport.
Its private dead-stream helper, old registries, and broad write guarantees must not be repeated as current facts.
`DESIGN.md` also mixes current SDK decisions with older scope statements, including a historical dashboard exclusion.
The current source and `docs/DAEMON.md` take precedence for implemented behavior.

The migration source records FastMCP 4.1.6, MCP 2.3.0, httpx2 2.16.0, and retained cryptography 48.0.1.
Its unsigned bundle checks passed on both slices. Installed-daemon acceptance, signing, notarization, and release remain pending.
The architecture must preserve the limited cryptography exception and its reassessment triggers.
It must not describe the latest public release, current source, and installed bundle as the same build.
The future Notes guards, CLI expansion, agent guidance, and distribution work need explicit planned states.

## Material alternative for the parent's debate

The strict page-kit gate and #544's runtime policy have different assumptions.
The recommended option preserves runtime data outside the ordinary checkout's planning source, after ownership checks, and retains the gate.
This changes no shared publishing code and keeps the full-folder hash meaningful.
The alternative changes the approved source gate and hash contract to exclude designated runtime files.
That requires an explicit shared-rule decision and consistent publisher changes; adding `--exclude-standard` locally is insufficient.
It also broadens this overnight task. No shared renderer work is needed under either option.

The separate architecture design remains unbuilt. Manual HTML pages and links satisfy the requested publication now.
Automated cross-project links or guaranteed Mermaid compilation would require additional implementation and must not be represented as existing support.

## Evidence and working notes

Primary local rules: publish-page skill,
developer handbook,
roadmaps,
project-pages, and
Garage.
Implemented behavior was checked in `meta/scripts/publish`, `meta/scripts/project-pages-refresh`, and `meta/scripts/project-pages.py`.
Vault inputs were read from checkout `3fd40637f6173c96eb4c79368f332b98d97ff010`.
The selected publication inputs had no local modifications. Unrelated vault changes remain outside scope.

### Working notes — exploratory limits and dead ends

- Initial sandbox network reads failed with `Could not resolve host: github.com`. Read-only escalated requests succeeded.
- PR #544's body is stale: its final commit restores tracking of debug records; its current-head check list is shorter than its narrative.
- A read-only three-tree comparison against `dce3324` confirmed the `state.json` modify/delete overlap. It produced no text conflict markers.
  It does not certify GitHub mergeability after later base changes.
- The old preparation note's legacy enrollment value and single-file upload would be wrong for this cutover.
- The Garage service note's older vault-only ownership description is superseded by the newer project-pages and page-kit rules.
- Web reads used unauthenticated GETs. No archive write was made because this assignment permits only this report file to be written.
- No application tests, native calls, publisher commands, installations, or credential reads were run. This is a publication-path audit.
- Only this report was written. Parent-owned files and the ordinary checkout's `.gitkeep`, lock, and bytecode remain untouched.
