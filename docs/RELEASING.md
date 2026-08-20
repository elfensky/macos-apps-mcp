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

```sh
git checkout -b feat/<topic> develop
# … work, commit …
gh pr create --base develop
gh pr merge <N> --rebase --delete-branch
```

Rebase-merge, always — `--merge` would put a bubble on the trunk, `--squash` would collapse
commits whose messages are written to stand alone.

## Cutting a release

**1. Bump the version in BOTH files.** They must match; `tests/test_packaging.py` enforces it, and
a mismatch ships an `.app` that lies about itself (this happened — 0.8.0 shipped for a whole cycle
reporting the wrong version).

- `pyproject.toml` → `version = "X.Y.Z"`
- `packaging/Info.plist` → `CFBundleShortVersionString`

```sh
uv run pytest tests/test_packaging.py
git commit -am "chore(release): X.Y.Z — <milestone name>"
git push origin develop
```

**2. Verify develop is green** — the tree you are about to release, not one from earlier:

```sh
uv run pytest
MACOS_APPS_ALLOW_SEND=mail uv run pytest
uv run ruff check . && uv run ruff format --check .
```

**3. Merge to main and tag.** `--no-ff` is required: the merge commit *is* the release marker, and
the tag points at it.

```sh
git checkout main && git pull
git merge --no-ff develop -m "Release vX.Y.Z — <milestone name>"
git tag -a vX.Y.Z -m "vX.Y.Z — <milestone name>"
git push origin main --follow-tags
git checkout develop
```

Pushing main triggers **TestPyPI** automatically. Production PyPI is a deliberate manual step —
`workflow_dispatch` with `target=pypi` — because PyPI uploads are permanent. Auth is Trusted
Publishing (OIDC); there are no stored tokens.

**4. Publish the GitHub release** with `gh release create vX.Y.Z`, and close the milestone if the
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
- [ ] Merged to `main` with `--no-ff`, tagged `vX.Y.Z`, pushed with `--follow-tags`
- [ ] GitHub release published
- [ ] Daemon rebuilt, reinstalled, kickstarted
- [ ] `doctor().version` reports the new version and `doctor().build` the built sha
