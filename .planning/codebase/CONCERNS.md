# Codebase Concerns

**Analysis Date:** 2026-08-28

## Tech Debt

### Native seam leak — six adapters + doctor + shortcuts unguarded (Strong priority)

**Issue:** Mail's native access seam (`runtime.run_osascript`) is guarded by conftest for unit tests, but six other adapters (`adapters/notes.py`, `adapters/messages.py`, `adapters/contacts.py`, `adapters/photos.py`, `adapters/safari.py`, `adapters/music.py`), doctor (`doctor.py`), and shortcuts (`adapters/shortcuts.py`'s `tracked_run`) hold module-global copies of these seam functions. A forgotten test fake in any adapter or the doctor reaches real apps.

**Files:** `adapters/notes.py:30`, `adapters/messages.py:23`, `adapters/contacts.py:16`, `adapters/photos.py:13`, `adapters/safari.py:11`, `adapters/music.py:16`, `adapters/shortcuts.py:21`, `doctor.py:30`, `tests/conftest.py:56-75`

**Impact:** Unit tests are meant to be fail-closed drills — no real app access. A missed test patch in any adapter silently launches the real app instead of failing loudly. No test has failed this way yet (the hole is latent), but the risk scales with every new adapter. EventKit adapters (`calendar.py`, `reminders.py`) hold `run_native` and `store` by name with no conftest guard — a forgotten fake reaches the real `EKEventStore` under TCC.

**Fix approach:** Extract seam locking into `tests/test_native_seam.py` using a glob over all adapters. One conftest fixture guards every seam import; modules that import the seam fail the test on first run if the test is missing the fake. Branches `spike/arch-review-1-native-seam` has the implementation (~2 h to land). Separately fix `doctor` tests (19 failures when `tracked_run` is locked) by faking `app_process_info` (~2–3 h) and EventKit seam (~3–4 h).

---

### Tool registration scattered across eight clipboards (Strong priority)

**Issue:** Facts about tools (tier, permission string, audit verb, backup-notice flag, sign exemption, snapshot source) live in eight separate locations in the codebase:
- `server.py:135-147` tier + decorator
- `server.py:159-246` tool definitions + docstrings
- `server.py:281` `_NO_NOTICE` exemptions
- `server.py:290` `_BACKUP_NOTICE_TOOLS` list
- `audit.py:185-200` `_audit_op` verb mappings
- `tests/test_tool_annotations.py` permission table, `_ADDITIVE_TOOLS`, `_DESTRUCTIVE_TOOLS`, `envelope_only`, `_RECOVERABLE_MAIL_TOOLS`
- `tests/test_audit_middleware.py:155-163` snapshot set

Two of these clipboards fail silently (`_NO_NOTICE` and `_audit_op`): `usage` shipped mis-classified (zero `_NO_NOTICE` edits) with the untrusted notice until a review sweep caught it a day later; nine writes audit as generic "write" (`trash_mail`, `move_mail`, `mail_undo`, `export_mail`, `save_mail_attachment`, `music_control`, `play_playlist`, `set_mode`, `set_volume`) instead of their specific verbs.

**Files:** `macos_apps_mcp/server.py`, `macos_apps_mcp/audit.py`, `tests/test_tool_annotations.py`, `tests/test_audit_middleware.py`

**Impact:** Adding a new tool requires hand-edits to all eight lists; two of them silently accept wrong values. Yesterday's `usage` incident proves even a suite of 1,196 tests can pass with the wrong notice.

**Fix approach:** Create a single `@_tool()` decorator that carries all facts as parameters (tier, adapter, permission, audit verb, backup notice). Derive the eight clipboards from the decorator at module load time. Branch `spike/arch-review-2-registration-record` implements this (~4–6 h).

---

### Fake envelope fixture private to one test file, 31 stubs scattered across six files (Strong priority)

**Issue:** The `_fake_envelope` fixture lives in `tests/test_mail_search.py:23-130` and is only used there, despite Mail tests across 14 files using 31 lambda stubs to mock query results. The fixture's schema is incomplete: it's missing `m.size` and `message_references` columns that `query_duplicate_rows` and `query_sent_triage` actually read. Two test functions (`test_mail_addressing.py:141-156`) knowingly pass against a store shape the plane never produces (two Pointers with one id), exposing a schema-drift risk.

**Files:** `tests/test_mail_search.py:23-130`, `tests/test_mail_cleanup.py`, `tests/test_mail_addressing.py:141-156`, `macos_apps_mcp/adapters/mail_index.py:731`

**Impact:** Executors run query bindings against incomplete fixtures; a real store missing `m.size` surfaces as a query-time error on one function, while missing `message_references` surfaces on another. The late-bound `envelope_index_path` in `mail_index.py` violates convention #180 (new Mail reads are tested through the fixture).

**Fix approach:** Promote `_fake_envelope` to conftest as a shared builder (`tests/envelope.py` with `add_message()` and `add_mailbox()` helpers). Add the missing columns. Convert the 18 convertible stubs; keep 13 that must remain (NativeError guards, negative "must not query" tests, deliberate no-index isolation). Branch `spike/arch-review-3-fake-envelope-fixture` implements this (~3–4 h).

---

### Recoverable plane's preflight duplicated between move_mail and trash_mail (Moderate priority)

**Issue:** Five identical lines of preflight logic exist in two places:
- `adapters/mail.py:1293-1298` (`move_mail` dry-run)
- `adapters/mail.py:1362-1367` (`trash_mail` dry-run)
- `mail_recover.py:141` as the `check_batch` docstring obligation
- `adapters/mail.py:1473-1474` (`dedupe_batch` dry-run — skips the read entirely, reads all as "planned")
- `mail_recover.py:332` `preview()` docstring: "caller is expected to have refreshed status through a READ"

A caller can violate this invariant: `dedupe_batch(dry_run=True)` already skips the read and returns "planned" for everything — a lie the docstring warns about. No caller passes `dry_run=True` today (dead path), but it's a live defect the moment someone wires it.

**Files:** `macos_apps_mcp/adapters/mail.py:1293-1298`, `macos_apps_mcp/adapters/mail.py:1362-1367`, `macos_apps_mcp/adapters/mail_recover.py:141`, `macos_apps_mcp/adapters/mail.py:1473-1474`

**Impact:** Copy-paste between move/trash raises the chance of a future update being missed; the dead path in dedupe becomes a live bug if someone refactors without re-reading docstrings.

**Fix approach:** Move the preflight check into `recoverable()` itself. Make `dry_run` without an explicit `present` parameter a `TypeError` rather than silently lying. Byte-identical output verified; ~2–3 h to land. Branch `spike/arch-review-4-recoverable-preflight` has it.

---

### Tier policy lives in server.py, doctor lazy-imports it (Moderate priority)

**Issue:** House rules (read-only mode, which adapters can send, outbound status) are defined in `server.py:61-103` alongside 1,225 lines of tool code. The `doctor` module imports `server` lazily on line 264 (`from . import server`) to read the gates, creating the package's only circular import. The import cycle is the only reason this import pattern exists (`deploy.py` also depends on these rules, forcing the cycle).

**Files:** `macos_apps_mcp/server.py:61-69`, `macos_apps_mcp/server.py:72-103`, `macos_apps_mcp/doctor.py:264-271`, `macos_apps_mcp/daemon.py:157-158`

**Impact:** The circular import makes the codebase harder to reason about and harder to test in isolation. The stale comment on `daemon.py:158` ("before server import (doctor reads it)") is false since commit 0f01e09 moved the gate-reading logic.

**Fix approach:** Extract tier policy to `macos_apps_mcp/tiers.py` below everything that asks it (doctor, server, deploy, mail_recover). Extract `UntrustedDataNotice` to `macos_apps_mcp/notices.py`. No behavioral change; the gates are read at process start, so moving them doesn't change when they're evaluated. Branch `spike/arch-review-5-tier-policy` implements this (~2–3 h).

---

### MailFilter — twelve search filters as 12 separate enumerations across 10 sites (Speculative/low priority)

**Issue:** The mail search order form has twelve tickboxes (filters) that are hand-enumerated in ten places across six files in two dialects (guest-facing names like "Archive" vs index-facing names like `mailbox_urls`). Adding a thirteenth filter requires edits at 12+ sites. A single `MailFilter` type could derive the enumerations from one place.

**Files:** `macos_apps_mcp/server.py:514-526`, `macos_apps_mcp/server.py:555-568`, `macos_apps_mcp/adapters/mail.py:1633-1647`, `macos_apps_mcp/adapters/mail.py:1666-1677`, `macos_apps_mcp/adapters/mail.py:1745-1755`, `macos_apps_mcp/adapters/mail.py:1766-1780`, `macos_apps_mcp/adapters/mail_index.py:186-199`, `macos_apps_mcp/adapters/mail_index.py:773-787`, `macos_apps_mcp/adapters/mail_index.py:796-809`, `macos_apps_mcp/adapters/mail_addressing.py:481`, `tests/test_mail_search.py:311-324`

**Impact:** Moderate. Six of the ten sites are irreducible as long as the MCP schema stays flat (tool signature, docstring, tool→adapter kwargs, adapter signature, SQL clause, test dict), so the win is real but small (~3 lines saved per new filter instead of 12).

**Fix approach:** Create a `MailFilter` type in `mail_index.py` (the lowest consumer). Derive the guard for "at least one filter is set" and the dropped predicates from `fields()` so they cannot be forgotten. Branch `spike/arch-review-6-mailfilter` measures the win as small enough that it should be done only when another filter is being added. Currently Speculative.

---

### runtime.py is 734 lines, holds 13 EventKit-only names alongside 10 shared names (Strong priority)

**Issue:** `macos_apps_mcp/runtime.py` is the service elevator every department (adapter) must use to reach a room (a native app). It also stores spare parts: date converters, repeat-rule translators, permission slips (EventKit imports and the `request_access` harness). Every EventKit change churns a file CLAUDE.md marks "don't drift". The module is three times longer than its job.

**Files:** `macos_apps_mcp/runtime.py:82`, `macos_apps_mcp/runtime.py:113`, `macos_apps_mcp/runtime.py:382`, `macos_apps_mcp/runtime.py:577-667`, `macos_apps_mcp/runtime.py:677-731`, `macos_apps_mcp/adapters/calendar.py:23-33`, `macos_apps_mcp/adapters/reminders.py:21-32`, `macos_apps_mcp/doctor.py:30`, `macos_apps_mcp/server.py:45`, `macos_apps_mcp/server.py:1356`

**Impact:** The elevator's control room cannot be opened without importing EventKit. Changes to recurrence rules or date handling churn a core file and require broader testing than they might otherwise.

**Fix approach:** Extract EventKit-specific code (RRULE mapping, date coercion, TCC bootstrap) to a new `macos_apps_mcp/eventkit.py` module at the package root (same tier as `runtime`, `errors`, `text`). Calendar and Reminders import it instead of importing 9–10 individual names from runtime. Branch `spike/arch-review-7-runtime-split` has the implementation (~2–3 h).

---

## Known Bugs

### One AppleScript timeout inversion: mail._DEDUPE script backstop (600 s) shorter than host cap (900 s)

**Issue:** In `macos_apps_mcp/adapters/mail.py`, the `_DEDUPE` script has `with timeout of 600 seconds` on line 514, but the host timeout is `_DEDUPE_TIMEOUT = 900.0` on line 467. The invariant that matters (runtime.py:236-241) is script timeout ≥ host timeout, so the host fires first and the script is a backstop. This inversion violates that invariant.

**Files:** `macos_apps_mcp/adapters/mail.py:514`, `macos_apps_mcp/adapters/mail.py:467`

**Impact:** If the host timeout ever fires on a dedupe operation, the script is already dead and cannot report status. Low likelihood (dedupes are usually under 600s), but it's a latent ordering bug.

**Fix approach:** Raise the script timeout to ≥ 900 seconds, or lower the host timeout. Verify against 0.9.5's large dedupe runs to confirm the typical ranges. Also implement the architecture review's card 9 recommendation: a ~25-line AST test that verifies script ≥ timeout for every template and call site.

---

### check_batch() refusal message misleading for update_status()

**Issue:** `mail_recover.check_batch()` on line 154 says "every target is backed up to disk before anything moves". But `update_status()` calls this for flag flips (read/unread, flag/unflag), which do not move anything and do not use the recoverable plane at all.

**Files:** `macos_apps_mcp/adapters/mail_recover.py:154`, `macos_apps_mcp/adapters/mail.py:1555`

**Impact:** User sees "everything is backed up before anything moves" when rejecting a batch that's "too big to flag-flip" — the message is confusing and partially false for this use case.

**Fix approach:** Make the message context-aware or move the batch check to a separate function specific to the recoverable plane. `check_batch()` should live only in `mail_recover.py` and have a message tailored to backup/move/trash semantics. `update_status()` should call a simpler `check_batch_size()` with a message about flag caps.

---

### Doctor tests run live pgrep/ps on the dev machine (17 tests, latent)

**Issue:** When the `tracked_run` seam is guarded by conftest, 17 doctor tests fail because they call `doctor.diagnose()`, which calls `runtime.app_process_info()`, which runs a live `pgrep` and `ps` command. These are not mocked and depend on whatever processes happen to be running during the test.

**Files:** `macos_apps_mcp/doctor.py:217` (and all callers), `tests/test_doctor.py` (17 test functions)

**Impact:** Machine-dependent tests. A developer's environment (what apps are running, PIDs, process names) affects whether the suite passes. The doctor's diagnosis itself is correct, but the harness is wrong.

**Fix approach:** Fake `app_process_info()` to return a canned response in doctor tests. Done when closing the native seam leak (card 1 effort: +2–3 h).

---

## Security Considerations

### Untrusted data notice misclassified on the usage tool until post-ship review (caught and fixed)

**Issue:** The `usage` tool shipped in 0.9.x with zero entries in `_NO_NOTICE`, so it received the untrusted-data notice by default. The tool returns metadata only (not data from apps), so it should have been in `_NO_NOTICE`. A post-ship review (2c82490) caught it a day later. No test validated that every meta tool was signed-exempted.

**Files:** `macos_apps_mcp/server.py:135-147`, `tests/test_tool_annotations.py`

**Impact:** Low, because the tool was low-sensitivity. But the pattern — a missing entry in a hand-maintained exemption list silently passes tests — is the reason card 2 (the registration record) exists.

**Fix approach:** Implement card 2 (consolidate tool facts into one source). Add a test that validates every meta tool is in `_NO_NOTICE`.

---

## Test Coverage Gaps

### READ_ONLY=1 test suite is never run, 12 failures latent

**Issue:** The test suite includes 80 deselected tests for read-only mode (`MACOS_APPS_READ_ONLY=1`), and 12 currently fail on `develop`. These tests are not run in CI and the failures are unknown.

**Files:** `tests/test_audit_middleware.py::test_server_snapshot_sources_are_derived_and_satisfy_the_protocol`, `tests/test_mail_cleanup.py::test_mail_duplicates_is_registered_read_only`, `tests/test_server.py` (9 failures related to gating and error handling)

**Impact:** The `READ_ONLY` tier is not exercised. A regression in read-only mode would not be caught.

**Fix approach:** Run `MACOS_APPS_READ_ONLY=1 uv run pytest` in CI, or mark the 12 failing tests as known failures and investigate root causes. These are gate-related failures (tools not registered when they should be) or error-handling tests that assume tools exist.

---

## Missing Critical Features

### HEADER_FINGERPRINT doesn't cover columns two executors read

**Issue:** `HEADER_FINGERPRINT` (the Envelope Index schema version check) doesn't include six columns that `query_duplicate_rows` and `query_sent_triage` read: `m.size`, `message_references`, and four others. A real store missing these columns surfaces as a query-time error instead of schema drift.

**Files:** `macos_apps_mcp/adapters/mail_index.py` (HEADER_FINGERPRINT definition), `macos_apps_mcp/adapters/mail_index.py` (query_duplicate_rows and query_sent_triage)

**Impact:** Schema mismatch is detected late (at query time) instead of early (at startup). A model might retry or report confusing errors.

**Fix approach:** Audit all query executors and add their columns to HEADER_FINGERPRINT. Add a test that validates the fingerprint covers every column any query reads.

---

### Daemon comment stale since 0f01e09

**Issue:** `daemon.py:158` says "before server import (doctor reads it)", referring to setting `MACOS_APPS_MCP_ROLE` before importing server. But the gate-reading logic moved in commit 0f01e09, so the comment is outdated.

**Files:** `macos_apps_mcp/daemon.py:157-158`

**Impact:** Misleading for future maintainers. The code is correct; only the comment is wrong.

**Fix approach:** Update the comment to reflect current gate-reading behavior, or remove it if self-evident.

---

## Scaling Limits

### Mail store walk is ~2 seconds for dedupe preflight

**Issue:** `mail_recover.py` notes that a full-tree rglob over the ~36k-message store takes ~2 seconds per destructive call (line 169: `ponytail: one full-tree rglob (~2s on a 36k-message store) per destructive call`). This is bounded for now but could become a bottleneck on very large stores.

**Files:** `macos_apps_mcp/adapters/mail_recover.py:169`

**Impact:** Low for typical users (a few MB/s SSD), but could exceed timeout caps for users with hundreds of thousands of messages. Card 4 (single `.emlx` walk) partially addresses this by caching the path, and card 9's tripwire captures the design option to optimize with rglob-scoping.

---

## Deliberate Simplifications (NOT Tech Debt)

These are documented design choices, not debt:

- **No permanent delete implemented** — Facts doc §5c proves AppleScript offers no targeted permanent delete on current macOS. The `PERMANENT_OPS` set stays empty with a comment explaining why (`mail_recover.py:72-85`).

- **Mail exports `.eml` instead of `.html`/`.txt`** — `.eml` is lossless and opens in Mail; the FTS body search already covers text extraction. Documented in `mail.py` and ROADMAP as deliberate.

- **MailAdapter keeps thin delegation methods** — #178's proposal was rejected because the methods carry distinct engineer-facing docstrings and the hand-list of Mail tools became simpler to maintain. #179 (docstring-only alternative) is floating, not committed.

- **No real attachment payload download to `.emlx`** — #119 measured all 22,748 partials and proved attachments never convert `.partial` → full, despite Mail fetching them to sidecars. #167 verified the trigger (documented as failing), so #167/#119 are closed by probe result, not code.

---

*Concerns audit: 2026-08-28*
