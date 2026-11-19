# Installed acceptance — 2026-11-04

The signed universal bundle from clean source `7bc86078e64bfbbe8d019cda8ef85a0dcc11583f` is installed on the arm64 Mac.
The running daemon reports version `0.15.1`, build `7bc8607 2026-11-04T11:41:03Z`, MCP `2.3.0`, and FastMCP `4.1.6`.
The prior app is preserved for rollback. No release or issue closure is claimed.

## Verified state

| Check | Result |
|---|---|
| Universal build | Both architectures, imports, stream cases, entitlements, and signed runtime gates passed |
| Installed signature | Strict verification passed after native calls and daemon restart |
| Actual stdio shim | Modern and legacy protocol clients each listed 71 annotated tools |
| Native reads | Calendar enumeration, reminder-list enumeration, and one-day free/busy passed |
| Result boundary | Each native result retained structured content and exactly one leading untrusted-data notice |
| Native call duration | Selected reads stayed below five seconds; a later installed Trash call completed in 6.087 seconds |
| Restart recovery | One existing stdio client listed tools and called doctor after the daemon PID and socket changed |
| Restart limits | No deliberate stopped interval, destructive interruption, replay count, or real Claude frontend was tested |
| Private storage | State and daemon directories: `0700`; socket and dashboard key: `0600`; owner matched; no symlinks |
| Signed notices | 133 distributions, including 15 fallback users; all fallback hashes and installed notice records matched |
| Dashboard | Four HTTP 200 responses; Health completed; Adapters retained that timestamp on reload |
| Permission chips | Health and active-adapter denial warnings agreed; no denied adapter existed in this observation |
| Native integration subset | Three read-only tests passed; the Mail process-identity test skipped because Mail was not running |

The native reads ran through the installed daemon. Repository-Python integration tests are supplemental evidence and have a different permission identity.
The dashboard check made authenticated HTTP requests without browser interaction or settings changes. It retained no page key or personal payload.
No permission was revoked to construct a denial. In-flight report replacement remains covered by synthetic tests, not this device observation.

The evidence branch passed 3475 default tests, with 105 integration tests deselected and seven upstream deprecation warnings.
Ruff lint and formatting passed. All 98 checked relative Markdown links resolve.

[Later Mail acceptance](2026-11-04-mail-recovery-acceptance.md) proves the one-message recovery route, new backup modes, and a real call exceeding five seconds.

## Physical Intel compatibility census

The physical iMac13,2 runs x86_64 macOS 15.8.1. Its installed app remains version `0.14.3`.
Its existing Developer ID signature passed verification. The bundled interpreter is Python 3.14.5.

The mailbox-only census completed at `2026-11-04T11:50:22Z`, using selector source `872577effc45187d97f1380f932bcb434e82472f`.
Three remote account roots had one distinct candidate each. One remote root and one local root had no candidate. None had multiple candidates.
Both machines passed 26 synthetic checks before the Intel database read.
The connection used SQLite `mode=ro`, `query_only`, a snapshot transaction, and a 30-second query bound.
It read mailbox URLs only, without message reads, sidecars, setup, or fallback.
The report retained ordinals and counts, not mailbox URLs or account identifiers.

All folder depths were counted. Exact decoded aliases collapsed; case and Unicode normalization differences remained distinct.
One candidate does not prove Mail's system-folder role. Zero candidates are reported as missing, not accepted as a valid destination.
This census establishes index readability for the SSH process, not permissions for the installed daemon.

## Remaining acceptance

- [Notarization, stapling, and physical Intel installation](2026-11-04-notarization-intel-acceptance.md) subsequently passed using the existing `notary` profile. The earlier credential-search failure is resolved.
- The installed Trash call exceeded five seconds successfully. Real frontend recovery and the original #543 incident remain unproved.
- Fresh Mail backup modes and the single-message recovery route passed on arm64. Localized trash/undo and applicable Gmail Trash observations remain pending.
- PR #559 is not installed or merged. Its physical candidate census is complete; its write acceptance remains open.
- Non-English Notes/Mail behavior, forced permission refusals, and Notes/draft safety probes remain separate acceptance work.
- Dependency advisories remain open under the recorded cryptography exception.

**eli14:** The new toolbox is signed and working on the main Mac. Its labels, locks, and basic tools passed inspection.
The older Mac now has Apple's approved toolbox too. Its basic read tools passed; specialized routes still need separate checks.

## Evidence

Private local artifacts retain the build log, signed archive, machine-readable checks, and read-only harnesses.
Artifact names: `mcp-signed-install-20261104/results.json`, `mcp-installed-modern-20261104.json`, `mcp-installed-legacy-20261104.json`,
`mcp-installed-files-dashboard-20261104.json`, `mcp-installed-restart-20261104.json`, and `mcp-intel-preflight-20261104/census.json`.
Absolute evidence addresses remain outside this public repository.

[Working notes](2026-11-04-installed-working-notes.md) record the test correction and verification limits.
