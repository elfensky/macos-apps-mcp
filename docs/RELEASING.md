# Releasing

Two branches, two different shapes of history — on purpose.

- **`develop` is the trunk.** Every PR is **rebase-merged**, so develop is linear: one commit per
  logical change, no merge bubbles. All work lands here first.
- **`main` is release-only.** It receives nothing but release cuts, each a **merge commit** from
  develop, tagged `vX.Y.Z`. `main` therefore holds one commit per release and nothing else.

`.github/workflows/publish.yml` states the same rule from the CI side: *"`main` is release-only
(develop is the trunk), so a push to main is a per-release event."*

History note: develop was merge-committed until #74 (2026-07-13) and has been rebase-only since.
Merge commits before that point are historical, not the convention.

## Feature work

Every change — the release bump included — is made in its own worktree under `.worktrees/` and
reaches `develop` by a PR; the procedure is in [AGENTS.md](../AGENTS.md) ("Worktrees — one lane,
always"). The main checkout never branches or commits.

Rebase-merge, always — `--merge` would put a bubble on the trunk, `--squash` would collapse
commits whose messages are written to stand alone.

## Cutting a release

**1. Bump the version in BOTH files.** They must match; `tests/test_packaging.py` enforces it, and
a mismatch ships an `.app` that lies about itself (this happened — 0.8.0 shipped for a whole cycle
reporting the wrong version).

- `pyproject.toml` → `version = "X.Y.Z"`
- `packaging/Info.plist` → `CFBundleShortVersionString`

Make the bump in a worktree (`.worktrees/release-X.Y.Z`, branch `chore/release-X.Y.Z`) and land it
on `develop` by PR like any other change:

```sh
uv run pytest tests/test_packaging.py
git commit -am "chore(release): X.Y.Z — <milestone name>"
git push -u origin HEAD && gh pr create --base develop --fill
gh pr checks --watch --required && gh pr merge --rebase --delete-branch
```

**2. Verify develop is green** — the tree you are about to release, not one from earlier:

```sh
uv run pytest
MACOS_APPS_ALLOW_SEND=mail uv run pytest
uv run ruff check . && uv run ruff format --check .
```

**3. Merge to main and tag.** The release cut is a PR `develop` → `main`, merged with a merge
commit: the merge commit *is* the release marker, and the tag points at it. The `main` ruleset
allows only that merge method — a rebase-merge would rewrite the SHAs and fork `main` from
`develop`. Never pass `--delete-branch` here: the head branch is `develop`.

```sh
gh pr create --base main --head develop --title "Release vX.Y.Z — <milestone name>" --body ""
gh pr checks --watch --required && gh pr merge --merge --subject "Release vX.Y.Z — <milestone name>"
git fetch -q origin
git tag -a vX.Y.Z origin/main -m "vX.Y.Z — <milestone name>"
git push origin vX.Y.Z
```

Merging to main triggers **TestPyPI** automatically. Production PyPI is the next step.

**4. Upload to production PyPI — only with the operator's explicit approval.** A PyPI upload is
permanent: a version number can never be uploaded again, even after deletion. So the upload is a
manual `workflow_dispatch` with `target=pypi`, and the operator approves it at every release — an
agent asks, and never dispatches on its own. Dispatch on the **tag**, not on `develop`, so the
package is built from the released commit. Auth is Trusted Publishing (OIDC); there are no stored
tokens.

```sh
gh workflow run publish.yml --ref vX.Y.Z -f target=pypi
gh run list --workflow publish.yml --limit 1          # note the run id
gh run watch <run-id> --exit-status
curl -sf -o /dev/null https://pypi.org/pypi/macos-apps-mcp/X.Y.Z/json && echo "X.Y.Z is on PyPI"
```

The per-version URL is the proof; the project page's "latest" lags behind the CDN cache. This step
is easy to skip — 0.9.0, 0.11.0 and 0.12.0 reached PyPI only on 2026-10-01. Never upload a tag
before `v0.6.0`: those build `apple-mcp` (a PyPI name owned by someone else) or `mac-mcp`.

**5. Publish the GitHub release** with `gh release create vX.Y.Z`, and close the milestone if the
release completes it. A release may ship without closing its milestone — see below.

## Deploying to the daemon

**The repo is not the daemon.** Merging and tagging changes nothing about what Claude Code sees;
`/Applications/macos-apps-mcp.app` keeps serving its old build until you rebuild and reinstall.
0.8.0 served for three sessions of fixes because this step was skipped.

Follow [DAEMON.md](DAEMON.md) for build → sign → notarize → staple → install → kickstart, then
**prove it**:

```
doctor().version   # must report the version you just cut
doctor().build     # must report the sha you just built (#143) — version alone
                   # cannot see a same-version rebuild
```

Judge that output. A successful build says nothing about which binary launchd is running.

## Milestones vs releases

They are not the same thing and do not have to line up. A milestone is a body of work; a release is
a cut of the trunk on a given day. `0.9.0` shipped with its milestone still open — the remaining
issues land in `0.9.1`, `0.9.2`, and so on. Do not hold a release hostage to a milestone, and do
not close a milestone just because a same-numbered release went out.

## Checklist

- [ ] Version bumped in `pyproject.toml` **and** `packaging/Info.plist`
- [ ] `uv run pytest` green, gated **and** ungated
- [ ] `ruff check` + `ruff format --check` clean
- [ ] Release PR `develop` → `main` merged with a merge commit, tagged `vX.Y.Z`, tag pushed
- [ ] PyPI upload **approved by the operator**, dispatched on the tag, and
      `https://pypi.org/pypi/macos-apps-mcp/X.Y.Z/json` returns 200
- [ ] GitHub release published
- [ ] Daemon rebuilt, reinstalled, kickstarted
- [ ] `doctor().version` reports the new version and `doctor().build` the built sha
