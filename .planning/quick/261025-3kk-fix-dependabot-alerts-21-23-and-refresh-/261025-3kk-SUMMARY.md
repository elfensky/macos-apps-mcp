---
phase: quick-261025-3kk
plan: 01
status: complete
commit: 000308f
---

# Quick 261025-3kk summary

- `uv.lock`: fastmcp and fastmcp-slim 3.4.9 → 3.4.11 (GHSA-7xgj-8392-5q4r, alerts #22,
  #23), opentelemetry-api 1.44.0 → 1.45.1 (GHSA-xcq7-p3pf-p88h, alert #21), plus 29 other
  updates inside the `pyproject.toml` limits. Cooldown cutoff 2026-10-18 01:34 UTC: 19
  fresh versions are held back to the newest earlier release (8 of them stay at the
  locked version, certifi at 2026.10.19 among them). `uv lock --check` passes, no
  `exclude-newer`, one cryptography entry (48.0.1).
- GHSA-7xgj-8392-5q4r needs FastMCP component authorization (`AuthCheck`) with a
  transform or a proxy template; the package has neither, so the daemon is not affected.
- `uv audit --frozen`: only cryptography 48.0.1 remains (alerts #2, #17, #18; Intel cap
  #322).
- `ci.yml` and `publish.yml` use `astral-sh/setup-uv@v10.3.2`. setup-uv has published no
  major or minor tags since v8.0.0, so `@v10` does not resolve. Defaults stay.
- Verification: `uv run pytest` 2614 passed; `MACOS_APPS_READ_ONLY=1` 2599 passed, 15
  skipped; `ruff check` and `ruff format --check` clean.
- Python 3.15 (3.15.1 is current): PyObjC 12.2.2 and osxphotos 0.77.2 have wheels;
  PyYAML 6.0.3 and xattr 1.3.0 have none and build from source.
- The `.app` keeps the old versions until it is rebuilt and reinstalled.
