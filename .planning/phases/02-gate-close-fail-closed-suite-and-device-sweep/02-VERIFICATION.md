---
phase: 02-gate-close-fail-closed-suite-and-device-sweep
verified: 2026-10-01T00:00:00Z
status: passed
score: 3/3 must-haves verified
covered_files:
  - ".github/workflows/ci.yml"
  - ".planning/REQUIREMENTS.md"
  - ".planning/phases/02-gate-close-fail-closed-suite-and-device-sweep/02-01-PLAN.md"
  - ".planning/phases/02-gate-close-fail-closed-suite-and-device-sweep/02-01-SUMMARY.md"
  - ".planning/phases/02-gate-close-fail-closed-suite-and-device-sweep/02-02-PLAN.md"
  - ".planning/phases/02-gate-close-fail-closed-suite-and-device-sweep/02-02-SUMMARY.md"
  - ".planning/phases/02-gate-close-fail-closed-suite-and-device-sweep/02-03-PLAN.md"
  - ".planning/phases/02-gate-close-fail-closed-suite-and-device-sweep/02-03-SUMMARY.md"
  - ".planning/phases/02-gate-close-fail-closed-suite-and-device-sweep/02-04-PLAN.md"
  - ".planning/phases/02-gate-close-fail-closed-suite-and-device-sweep/02-04-SUMMARY.md"
  - ".planning/phases/02-gate-close-fail-closed-suite-and-device-sweep/02-05-PLAN.md"
  - ".planning/phases/02-gate-close-fail-closed-suite-and-device-sweep/02-05-SUMMARY.md"
  - ".planning/phases/02-gate-close-fail-closed-suite-and-device-sweep/02-06-PLAN.md"
  - ".planning/phases/02-gate-close-fail-closed-suite-and-device-sweep/02-06-SUMMARY.md"
  - "CHANGELOG.md"
  - "macos_apps_mcp/doctor.py"
  - "packaging/Info.plist"
  - "pyproject.toml"
  - "tests/integration/test_mail_outbound.py"
  - "tests/test_audit_middleware.py"
  - "tests/test_doctor.py"
  - "tests/test_integration.py"
  - "tests/test_mail_cleanup.py"
  - "tests/test_native_seam.py"
  - "tests/test_server.py"
  - "tests/test_tool_annotations.py"
  - "uv.lock"
covered_digest: "v1:sha256:908fef4f10507190ff6b39faf2b3b1af44ef091f26800e021f929c88c5aa9a51"
behavior_unverified: 0
overrides_applied: 0
---

# Phase 2: Gate Close — Fail-Closed Suite and Device Sweep Verification Report

**Phase Goal:** The suite tells the truth in every deployment shape — read-only, unit, and
on-device — so the adapter phases can trust it.
**Verified:** 2026-10-01
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `MACOS_APPS_READ_ONLY=1 uv run pytest` is green — gated-off tools are absent, not registered-and-erroring | ✓ VERIFIED | Re-ran locally: `1483 passed, 0 failed, 9 skipped`. `tests/test_server.py` has exactly one `_write_gate_on_only` marker (`grep -c` → 1) applied to 8 named tests (`grep -c "^@_write_gate_on_only"` → 8); 4 fact tests read `registry.TOOLS.items()` unfiltered (confirmed by reading `tests/test_tool_annotations.py`, `tests/test_audit_middleware.py`, `tests/test_mail_cleanup.py`). |
| 2 | `uv run pytest` runs no live `pgrep`/`ps`: doctor's process-probe goes through the locked `tracked_run` seam | ✓ VERIFIED | `macos_apps_mcp/doctor.py:254` reads `runtime.tracked_run(["ps", "-o", "comm=", "-p", str(pid)], timeout=5.0)` — the only `ps`/`pgrep` spawn path in `_process_name`. `tests/test_native_seam.py` has `test_native_module_spawns_no_subprocess_directly`, an AST tripwire over every native module (`doctor.py` + `adapters/*.py`) that fails on a direct `subprocess.{run,Popen,call,check_call,check_output}` call or by-name import, while sparing `shortcuts.py`'s bare `except subprocess.TimeoutExpired` reference (confirmed by reading the AST predicate: only `ast.Call`/`ast.ImportFrom` nodes are checked). |
| 3 | `uv run pytest -m integration` is green on the current macOS against a daemon rebuilt/reinstalled from the gate; `ruff check .` and `ruff format --check .` pass | ✓ VERIFIED | `.worktrees/sweep-02-final.xml` (read-only, git-ignored, parsed per task instructions): `tests="80" errors="0" failures="0" skipped="3"` (2 of the 3 are xfails: #229 strict, #230 non-strict; 1 is a deliberate device-data skip). `.worktrees/sweep-02-final.log` tail confirms the pytest summary `77 passed, 1 skipped, 1492 deselected, 2 xfailed in 7248.22s`. Release proof independently re-checked: `git rev-parse v0.12.0^{commit}` == `git rev-parse origin/main` == `5ce98abf99dfe5c3d7d1f8eecc02325f71de926e`; `git log -1 --format=%P origin/main` → two parents (`f52e9d5`, `50b9def`); `gh release view v0.12.0 --json assets` lists `macos-apps-mcp-0.12.0.zip`. `ruff check .` and `ruff format --check .` re-run locally: clean. |

**Score:** 3/3 truths verified (0 present, behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `tests/test_server.py` | one named read-only skip marker, 8 call tests decorated | ✓ VERIFIED | `_write_gate_on_only = pytest.mark.skipif(...)` defined once (line 36), applied to exactly 8 tests (lines 436, 463, 477, 514, 552, 600, 831, 890) |
| `tests/test_tool_annotations.py` / `test_audit_middleware.py` / `test_mail_cleanup.py` | fact tests read `registry.TOOLS` unfiltered | ✓ VERIFIED | Read all three files; each reads `registry.TOOLS.items()` directly, no `registered`-filtered view |
| `.github/workflows/ci.yml` | second test step, read-only | ✓ VERIFIED | `- run: MACOS_APPS_READ_ONLY=1 uv run pytest` directly after `- run: uv run pytest`, same job; header comment documents the rationale |
| `macos_apps_mcp/doctor.py` | `_process_name` through `runtime.tracked_run` | ✓ VERIFIED | `grep -c "runtime.tracked_run("` → 1 |
| `tests/test_native_seam.py` | AST tripwire against direct subprocess spawns | ✓ VERIFIED | `test_native_module_spawns_no_subprocess_directly` present, parametrized over all native modules including `doctor.py` |
| `tests/test_integration.py` | marker-mail-only fixture (`MARKER_SUBJECT`, `SEED_MARKERS`, `_scratch_account`) | ✓ VERIFIED | Constants and helper present; confirmed via the device-sweep junit that the fixture selected exactly the 2 marker mails (2/2 reported after the final run) |
| `pyproject.toml` / `packaging/Info.plist` / `CHANGELOG.md` | v0.12.0 release artifacts | ✓ VERIFIED | `v0.12.0` tag resolves to `origin/main` tip; CHANGELOG has a dated `## [0.12.0]` section |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `tests/test_server.py _write_gate_on_only` | `macos_apps_mcp/server.py` registration gate | `tiers.read_only()` predicate, same boolean the write-tier gate uses | ✓ WIRED | Confirmed by reading the marker definition (`tiers.read_only()`) |
| `doctor._process_name` | `runtime.tracked_run` | qualified call, faked by the existing `_no_live_process_probe` autouse fixtures | ✓ WIRED | Confirmed: `tests/test_doctor.py`/`test_doctor_deploy.py` fixtures unchanged, still pass after the swap (re-ran `uv run pytest -q`: 1492 passed) |
| CI workflow | `develop` push/PR | `.github/workflows/ci.yml` runs both steps on every push/PR | ✓ WIRED | `gh run list --workflow ci --branch develop --limit 3` shows 3 consecutive `success` runs, the latest at head `1c30018` (current tip) |
| `tests/test_integration.py inbox_messages` | `_scratch_account` | the one shared helper feeds both `scratch_mailbox` and `inbox_messages` | ✓ WIRED | Confirmed by reading the fixture; device-proven in 02-04/02-05 (markers land in the account the helper picks) |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Default unit suite green | `uv run pytest -q --no-header` | `1492 passed` | ✓ PASS |
| Read-only unit suite green (SC1) | `MACOS_APPS_READ_ONLY=1 uv run pytest -q --no-header` | `1483 passed, 0 failed, 9 skipped` | ✓ PASS |
| Lint clean | `uv run ruff check .` | `[]` | ✓ PASS |
| Format clean | `uv run ruff format --check .` | `104 files already formatted` | ✓ PASS |
| No debt markers in phase-touched files | `grep -n -E "TBD\|FIXME\|XXX\|TODO\|HACK\|PLACEHOLDER"` over every file this phase modified | no matches | ✓ PASS |
| CI green on develop after every merge | `gh run list --workflow ci --branch develop --limit 3` | 3/3 `success` | ✓ PASS |

### Probe Execution (SC3, read-only evidence per task constraints)

| Probe | Command | Result | Status |
|-------|---------|--------|--------|
| Device integration sweep (final) | `.worktrees/sweep-02-final.xml` (parsed read-only, not re-run — native-app calls are out of scope for this verifier) | `tests="80" errors="0" failures="0" skipped="3"` | PASS |
| Release tag → main parity | `git rev-parse v0.12.0^{commit}` vs `git rev-parse origin/main` (actually run) | both `5ce98abf99dfe5c3d7d1f8eecc02325f71de926e` | PASS |
| GitHub release assets | `gh release view v0.12.0 --json assets` (actually run) | `macos-apps-mcp-0.12.0.zip` present | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| GATE-07 | 02-01 | `MACOS_APPS_READ_ONLY=1 uv run pytest` passes | ✓ SATISFIED | Re-run confirms 0 failed; `tests/test_server.py` marker + fact-test rewrite present; CI second step present |
| GATE-11 | 02-02 | Doctor unit tests no longer run live `pgrep`/`ps` | ✓ SATISFIED | `doctor.py` seam swap confirmed; AST tripwire present and scoped correctly |
| GATE-12 | 02-03, 02-04, 02-05, 02-06 | Full device integration suite green after the gate lands | ✓ SATISFIED | Marker-mail fixture landed (02-03); daemon rebuilt/reinstalled, markers seeded and account mismatch resolved by owner (02-04); final sweep green 80/0/0 (02-05); v0.12.0 tagged, released, installed (02-06) |

No orphaned requirements: `.planning/REQUIREMENTS.md`'s traceability table maps exactly GATE-07, GATE-11, GATE-12 to "Phase 2 — Complete", matching the three IDs declared for this phase.

### Anti-Patterns Found

None. Scanned every file this phase modified (test files, `doctor.py`, `.github/workflows/ci.yml`,
`pyproject.toml`, `packaging/Info.plist`, `CHANGELOG.md`) for `TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/
`PLACEHOLDER` — zero matches.

### Human Verification Required

None. All three ROADMAP success criteria resolve to observable, independently-reproduced evidence
(local test runs, direct code reads, and read-only git/gh checks against the release). The two
open findings from the device sweep (#229 — `rollback()` cannot verify delete of a windowless
outgoing message; #230 — intermittent reply content-read timeout) are correctly scoped as
xfail-marked, tracked issues owned by Phase 02.1 — they do not block GATE-12 (pytest's own
semantics: an expected failure is not a suite failure), and the roadmap/REQUIREMENTS.md already
route them there (MAIL-01..04, Phase 02.1).

### Gaps Summary

No gaps. All 3 ROADMAP success criteria and all 3 declared requirement IDs (GATE-07, GATE-11,
GATE-12) are backed by evidence independently reproduced by this verifier: a local
`MACOS_APPS_READ_ONLY=1 uv run pytest` run (1483 passed, 0 failed, 9 skipped), a direct read of
`doctor.py`'s seam swap and the AST tripwire, a read-only parse of the device sweep's junit XML
(tests=80, failures=0, errors=0), and read-only git/gh checks confirming the v0.12.0 tag, its
merge-commit parentage, and its GitHub release asset. CI on `develop` is green across the last 3
runs, the latest at the current tip (`1c30018`). No debt markers, no stub artifacts, no broken
key links.

---

*Verified: 2026-10-01*
*Verifier: Claude (gsd-verifier)*
