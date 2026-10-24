---
phase: quick-261025-2fq
plan: 01
status: complete
commit: b4ced7e
---

# Quick 261025-2fq summary

- `.github/dependabot.yml` uses the `uv` ecosystem with `versioning-strategy: lockfile-only`,
  so only `uv.lock` moves and the deliberate caps in `pyproject.toml` (#286, #322,
  `osxphotos<0.78`, dev pins) stay.
- The Dependabot options reference lists `uv` as supported for `versioning-strategy` and
  states no limit on `lockfile-only`; the fallback `ignore` list for majors is not needed.
- Updates wait 7 days (`cooldown.default-days: 7`).
- Version updates: one group per ecosystem (`uv`, `actions`). Security updates: one `uv-security`
  group (`applies-to: security-updates`).
- `CHANGELOG.md` has a `### Changed` entry under `## [Unreleased]`.
- Verification: `uv run pytest` 2614 passed; `ruff check` and `ruff format --check` clean.
