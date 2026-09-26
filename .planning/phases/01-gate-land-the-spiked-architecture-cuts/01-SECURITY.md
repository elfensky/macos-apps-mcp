---
phase: "1"
slug: "gate-land-the-spiked-architecture-cuts"
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on severity (the blocking gate)
threats_open: 0
asvs_level: 1
created: "2026-09-26"
---

# Phase 1 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| repo → GitHub (`main`, tag, release) | Outward, public, permanent once pushed | Release commits, tag, signed `.app` zip |
| build tree → signed `.app` → launchd daemon | The installed bundle serves every MCP client with the owner's TCC grants | Executable code under the owner's TCC identity |
| keychain → build script | Developer ID key and notary credentials are used, never exported | Signing key, notary credentials (secret) |
| unit test → native seam | A test run on the owner's Mac must never reach Mail, Notes, Shortcuts or a live process table | Apple Events, osascript argv, process table (live user data) |
| host process → Mail via osascript | The script's own `with timeout` is the backstop when the host cannot stop Mail | Destructive Mail batches |
| model → destructive tool call | The dry-run preview and the omitted-`dry_run` default decide whether data is removed | Mail, Notes, Calendar content (user data) |
| server → Mail Envelope Index (read-only sqlite) | A schema mismatch must surface as typed `SchemaDrift`, never as a mis-parsed Pointer | Mail headers (user data) |
| server process → EventKit/TCC | One `EKEventStore` on one worker thread; TCC grants attach to the responsible process | Calendar and Reminders data, TCC consent |
| device test run → owner's Calendar, Reminders, Mail | Device tests act on live user data | Live user items |
| deploy config (env, consent file, argv role) → tool registration | Decides which write and send tools exist at all | Capability tier |
| tool result → model context | The untrusted-data notice marks user-store content as data | Untrusted user-store text |
| tool call → audit trail | The append-only record of every write | Before-state snapshots, verbs |
| cleanup → local and remote git refs | Deleting refs is irreversible outside the reflog | Branches, worktrees |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-1-01 | Tampering | daemon bundle built from a dirty or wrong tree | high | mitigate | Built in a detached worktree at the `v0.11.0` tag; probe proved build `f52e9d5` with no `-dirty` (01-01-SUMMARY) | closed |
| T-1-02 | Repudiation | one-way push of `main`/tag without consent | high | mitigate | Task 2 owner go checkpoint answered "cut-now" before the push (01-01-SUMMARY) | closed |
| T-1-03 | Spoofing | unsigned or un-notarized bundle installed | medium | mitigate | `xcrun stapler validate` + `spctl -a -vv -t install` reported `Notarized Developer ID` before install (01-01-SUMMARY) | closed |
| T-1-04 | Information disclosure | notary credentials | medium | mitigate | Keychain profile `notary` only; no credential in repo, log or argv (01-01-SUMMARY) | closed |
| T-1-SC | Tampering | package installs | low | accept | See Accepted Risks Log AR-1-01; `uv.lock` v0.10.0→v0.11.0 diff is the root version line only | closed |
| T-1-05 | Tampering | unit test forgets a fake and dials a real app | high | mitigate | `tests/conftest.py::_no_real_osascript` refuses `run_osascript`, `body_file`, `tracked_run`; `tests/test_native_seam.py::test_unit_tests_cannot_reach_a_seam_unfaked` proves each | closed |
| T-1-06 | Elevation of privilege | module-wide exemption re-opens the seam | medium | mitigate | No module-level opt-out of the autouse lock in `tests/`; real use is per test via `monkeypatch` (`test_a_test_fake_overrides_the_lock`) | closed |
| T-1-07 | Information disclosure | doctor tests read the dev machine's process table | low | mitigate | `tests/test_doctor.py`, `tests/test_doctor_deploy.py` fake `runtime.tracked_run` | closed |
| T-1-08 | Denial of service | script self-aborts before its host cap mid-batch | medium | mitigate | `tests/test_applescript_timeout.py::test_every_call_site_backstop_covers_host_cap`; `_DEDUPE_TIMEOUT = 900.0` and `with timeout of 900 seconds` in `adapters/mail.py` | closed |
| T-1-09 | Tampering | new template with unresolvable timeout escapes the check | low | mitigate | `_Unresolved` raised by the resolver in `tests/test_applescript_timeout.py` fails the test | closed |
| T-1-10 | Tampering | by-name seam copy in an adapter escapes the lock | high | mitigate | `tests/test_native_seam.py::test_native_module_does_not_import_the_seam_by_name` over every `adapters/*.py` + `doctor.py`; `test_the_tripwire_sees_the_native_modules` | closed |
| T-1-11 | Tampering | osascript argv injection through qualified calls | low | accept | See Accepted Risks Log AR-1-02; `runtime.py` keeps the `"--"` argv separator | closed |
| T-1-12 | Repudiation | dry-run reports present/planned for unchecked targets | high | mitigate | `adapters/mail_recover.py` raises `TypeError` when `present` is missing on a dry run; pinned by `tests/test_mail_recover.py` | closed |
| T-1-13 | Tampering | refactor changes dry-run argv or report | high | mitigate | `tests/test_mail_recover_dry_run_identity.py` vs `tests/mail_recover_dry_run_baseline.json`; device dry-run identity diff (01-08-SUMMARY) | closed |
| T-1-14 | Information disclosure | refusal text misleads about backups | low | mitigate | `mail_recover.check_batch` refusal text makes no backup claim | closed |
| T-1-15 | Denial of service | second store or executor breaks EventKit thread affinity | medium | mitigate | `tests/test_eventkit.py` asserts no executor in `eventkit` and `runtime._executor._max_workers == 1` | closed |
| T-1-16 | Tampering | moved EventKit body changes behaviour | medium | mitigate | Byte-identical move recorded (01-06-SUMMARY); device proof 7/7 green (01-08-SUMMARY) | closed |
| T-1-17 | Elevation of privilege | TCC consent request no longer fires from the daemon | medium | mitigate | `doctor.py` imports `request_access_each` from `eventkit`, `server.py` imports `bootstrap`; device proof `-k request_access` green (01-08-SUMMARY) | closed |
| T-1-18 | Denial of service | fingerprint column absent in the real store forces the AppleScript fallback | medium | mitigate | Daemon doctor `mail_index: ok` (01-10-SUMMARY; live `doctor()` 2026-09-26) | closed |
| T-1-19 | Tampering | executor reads a column the fingerprint does not guard | medium | mitigate | HEADER_FINGERPRINT coverage tests in `tests/test_mail_index.py` (GATE-08 section) | closed |
| T-1-20 | Information disclosure | test fixtures read the owner's real Mail store | low | mitigate | `tests/conftest.py::envelope_mode` builds under `tmp_path`; reshape skips paths under `Path.home()` | closed |
| T-1-21 | Tampering | real INBOX messages moved during verification | high | mitigate | Move → undo only on `Personal/macos-apps-mcp-test`, independently read back (01-08-SUMMARY) | closed |
| T-1-22 | Denial of service | Mail wedges and evidence is lost | medium | mitigate | Mail watchdog running for the device session (01-08-SUMMARY) | closed |
| T-1-23 | Tampering | EventKit test items left in the owner's calendar | low | mitigate | `macos-apps-mcp-test:` prefix + fixture cleanup; no leftovers read back (01-08-SUMMARY) | closed |
| T-1-24 | Repudiation | card 4 merged without device proof | high | mitigate | PR #215 held until device verification, then rebase-merged (01-08-SUMMARY) | closed |
| T-1-25 | Elevation of privilege | gate not consulted at registration after the move | high | mitigate | `tests/test_gate_on_dispatch.py`, `tests/test_deploy.py`, `tests/test_server.py` gate tests in default and `ALLOW_SEND=mail` modes | closed |
| T-1-26 | Spoofing | prompt-injection notice drops after the middleware move | medium | mitigate | `tests/test_server.py::test_untrusted_notice_covers_every_registered_tool_except_meta` and siblings | closed |
| T-1-27 | Tampering | lower module imports back into `server` | low | mitigate | `tests/test_import_layers.py::test_nothing_below_server_imports_server` (+ non-vacuous check) | closed |
| T-1-28 | Elevation of privilege | daemon registers send tools while outbound is off | high | mitigate | Dev-build probe: outbound gated correctly, `send_mail` answers dry-run only (01-10-SUMMARY) | closed |
| T-1-29 | Tampering | dirty or wrong tree installed as the daemon (card 5) | medium | mitigate | Detached worktree at `origin/develop`; build stamp equals built commit without `-dirty` (01-10-SUMMARY) | closed |
| T-1-30 | Spoofing | re-sign with another identity breaks TCC grants | medium | mitigate | Same Developer ID signing; daemon grants intact (01-10-SUMMARY; live `doctor()` 2026-09-26: calendar/reminders `full_access`) | closed |
| T-1-31 | Elevation of privilege | gated-off tool registered anyway | high | mitigate | `_tool` calls `mcp.tool` only when registered; registered-set = FastMCP list in default, `ALLOW_SEND=mail`, `READ_ONLY=1` (`tests/test_gate_on_dispatch.py`, `tests/test_registry.py`) | closed |
| T-1-32 | Repudiation | write completes without an audit record or under a generic verb | high | mitigate | `registry.derive_audit_verb` raises (no `"write"` fallback); `tests/test_audit_middleware.py`, `tests/test_registry.py` | closed |
| T-1-33 | Tampering | published tool contract changes during the refactor | medium | mitigate | Tool-list snapshot diffed against BASE `bd6fe53` in default and send modes: identical (01-12-SUMMARY D6) | closed |
| T-1-34 | Spoofing | a tool loses the notice because its exemption is derived | medium | mitigate | `tests/test_server.py::test_no_notice_exempts_exactly_the_meta_tools`, `test_unregistered_tool_name_gets_the_notice_fail_safe` | closed |
| T-1-35 | Repudiation | doctor's outbound report disagrees with registration | medium | mitigate | One ledger from `registry`; `outbound_pending` test in `tests/test_doctor_deploy.py` | closed |
| T-1-36 | Elevation of privilege | send gate consulted differently after the ledger move | high | mitigate | `server.py` `_tool` send branch: `registered = tiers.allow_send(adapter)`; FastMCP-vs-records tests in both modes | closed |
| T-1-37 | Tampering | `update_note` preview path writes | high | mitigate | `tests/test_notes.py::test_update_dry_run_returns_would_update_preview_and_writes_nothing`; `tests/test_server.py::test_update_note_bare_call_previews` | closed |
| T-1-38 | Tampering | new destructive tool ships with a destructive default | high | mitigate | `tests/test_registry.py::test_content_removing_tools_default_to_dry_run` over every record | closed |
| T-1-39 | Repudiation | callers not told the contract changed | low | mitigate | `CHANGELOG.md` `[Unreleased]` entry; tool docstrings state the default | closed |
| T-1-40 | Denial of service | device-test cleanup silently previews and leaks items | medium | mitigate | Adapter methods keep `dry_run: bool = False` (`calendar.py:489`, `notes.py:713`, `notes.py:793`, `mail.py:904`); only published tool defaults flip | closed |
| T-1-41 | Elevation of privilege | after card 2 the daemon registers a send or write tool it should not | high | mitigate | Probe: outbound ledger agrees with tool list, dry-run-only sends (01-14-SUMMARY); live client check 2026-09-26 (01-UAT test 1) | closed |
| T-1-42 | Tampering | cleanup deletes a non-spike branch or another session's worktree | medium | mitigate | Delete set from `spike/arch-review-*` only: 11 branches, 9 worktrees (01-14-SUMMARY) | closed |
| T-1-43 | Tampering | uncommitted work in a spike worktree destroyed | medium | mitigate | `git status --porcelain` per worktree; none had uncommitted changes (01-14-SUMMARY) | closed |
| T-1-44 | Tampering | dirty or wrong tree installed as the daemon (card 2) | medium | mitigate | Build token `8885ad0` without `-dirty` (01-14-SUMMARY); live `doctor()` 2026-09-26 reports `8885ad0 2026-09-26T08:48:01Z` | closed |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above workflow.security_block_on count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-1-01 | T-1-SC | The phase adds or upgrades no package; the v0.11.0 `uv.lock` change is the root version line only. | plan-time disposition (01-01-PLAN) | 2026-09-26 |
| AR-1-02 | T-1-11 | Argument passing is unchanged by the seam qualification; `runtime.run_osascript` keeps the `--` separator between script and argv. A full osascript injection review is out of scope for this phase. | plan-time disposition (01-04-PLAN) | 2026-09-26 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-09-26 | 45 | 45 | 0 | gsd-secure-phase (L1 grep-depth; register authored at plan time, auditor skipped per short-circuit rule) |

## Security Audit 2026-09-26

| Metric | Count |
|--------|-------|
| Threats found | 45 |
| Closed | 45 |
| Open | 0 |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-09-26
