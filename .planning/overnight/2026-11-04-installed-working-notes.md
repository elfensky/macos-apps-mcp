# Installed acceptance working notes — 2026-11-04

- Two research handoffs stopped before supplying a runnable harness. The parent prepared bounded stdio, dashboard, restart, and census harnesses.
- The native test census collected 105 cases across ten files. The broad suite was not run: fixtures include default/shared containers, persistent scratch data, sends, playback changes, and indexing writes.
- `test_doctor_integration_real` failed with `AssertionError: assert 12 == 11`. Its count omitted the Accessibility surface. The assertion and explanatory comment now include that existing surface. Runtime code is unchanged.
- The corrected read-only subset returned `3 passed, 1 skipped, 193 deselected`. The skipped test requires a running Mail process.
- Sandboxed codesign reported `invalid signature (code or signature have been modified)`. Strict verification outside the sandbox passed for both the installed app and preserved signed artifact. Do not treat restricted verification as proof of modified bytes.
- The build's signed archive has no notarization ticket. The documented remote-distribution step remains pending; no Gatekeeper bypass was used.
- The installed restart test used the documented launchctl kickstart. It waited for a new socket inode and listener before one explicit list and doctor call. It does not establish behavior during a controlled absence or measure automatic replay.
- The signed installed build remains 7bc8607. This branch changes an integration assertion and evidence only; it does not imply a rebuilt runtime from the evidence commit.

- Final branch gates: 3475 passed, 105 deselected, seven upstream warnings; Ruff lint/format passed; 98 relative links resolved.
