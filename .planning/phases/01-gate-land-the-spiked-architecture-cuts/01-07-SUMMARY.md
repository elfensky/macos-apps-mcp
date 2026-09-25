---
phase: 01-gate-land-the-spiked-architecture-cuts
plan: 07
subsystem: testing
tags: [pytest, sqlite, mail-index, envelope-fixture, gate-08, sequoia-sidecar]

# Dependency graph
requires:
  - phase: 01-04
    provides: native seam fail-closed (GATE-01) on this same branch lineage; card-1 landed
provides:
  - tests/envelope.py — the one fake Envelope Index (SCHEMA, seed_base, Envelope,
    ACCT_A/ACCT_B/ACCT_LOCAL, MSG_COLS), schema widened to every column any
    query_* executor reads
  - tests/conftest.py::fake_envelope / ::blank_envelope fixtures, both parametrized
    over envelope_mode (native + Sequoia-sidecar) so every consumer runs both shapes
  - sequoiaify_envelope carries message_global_data.message_id across the Sequoia
    reshape instead of nulling it (the column build_sent_triage_query joins on)
  - HEADER_FINGERPRINT widened to messages.size/message_id/subject_prefix,
    message_global_data.message_id, recipients.type/position, and a new
    message_references entry — pinned by a static coverage test
  - query_sent_triage and query_duplicate_rows proven against the fixture in both
    shapes with no stub (the two GATE-08 "adjacency"/ordering executors)
  - store-compensating query_* stubs in test_mail_search/triage/cleanup/
    addressing/extras routed through the shared fixture; disk-plane isolation,
    NativeError guards, and "must not query" negatives left untouched
affects: [01-10 (daemon doctor check — mail_index_ids remediation), 01-14 (spike
  branch + worktree cleanup, unaffected by this card), any future mail_index
  read (#180 convention: tested through this fixture, not a private stub)]

# Actuals (#2632)
actuals:
  tokens: 23294
  tasks: 3
  commits: 6
  plan_head_before: 8627aa8

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "One shared fake Envelope Index (tests/envelope.py) instead of a
      per-test-file private fixture: SCHEMA is the superset every query_*
      executor reads, seed_base's rows are byte-identical to the pre-promotion
      fixture, and Envelope(path).add_mailbox/add_message/execute build bespoke
      stores on the SAME schema."
    - "fake_envelope/blank_envelope both depend on envelope_mode: every consumer
      is automatically parametrized native + Sequoia-sidecar, no per-test opt-in."
    - "HEADER_FINGERPRINT coverage pinned by parsing GENERATED SQL text (not
      Python source): every build_*_query's FROM/JOIN binds an alias to a table,
      every alias.column reference is resolved through that binding, and an
      alias that resolves to a non-fingerprinted table (a CTE name, a subquery)
      is skipped BY RULE, never by a hardcoded list."
    - "A query_* stub is legitimate only when it isolates the disk plane
      (mail_root/.emlx), pins a NativeError, or asserts a 'must not query'
      negative — everything else routes through the fixture (#180)."

key-files:
  created:
    - tests/envelope.py
  modified:
    - tests/conftest.py
    - macos_apps_mcp/adapters/mail_index.py
    - tests/test_mail_search.py
    - tests/test_mail_ids.py
    - tests/test_mail_triage.py
    - tests/test_mail_index.py
    - tests/test_mail_cleanup.py
    - tests/test_mail_addressing.py
    - tests/test_mail_extras.py

key-decisions:
  - "test_resolve_takes_the_ranked_copy_the_rest_of_the_project_cites
    (test_mail_addressing.py) asserted a shape query_search can never produce
    for real — two Pointers sharing one Message-ID (query_search dedups by
    Message-ID by construction). Re-expressed against the real-store shape:
    one Message-ID filed in two mailboxes of one account (Trash, newer;
    INBOX, older) — resolve() must take the RANKED winner, not the newest row."
  - "test_mail_duplicates_reports_and_points_at_the_cli's exact stubbed numbers
    (total=10, distinct=4, redundant=6) don't reproduce identically once
    computed for real from seeded rows (chosen instead: <a@x> x3 the unique
    worst offender, <b@x>/<c@x>/<d@x> x2 each — total=9, distinct=4,
    redundant=5). The outcome shape is identical — one worst offender at
    copies=3, a redundant count, no cross-account duplicates — the literal
    numbers changed because they're now computed by SQL, not asserted by fiat."
  - "blank_envelope (schema-only, no seed_base rows) promoted from a
    test_mail_cleanup.py-local fixture to tests/conftest.py once
    test_mail_addressing.py and test_mail_extras.py needed the same shape —
    arithmetic/exact-url-list assertions need row-count control seed_base's
    canonical set would silently shift."
  - "query_cross_account_summary's stub in
    test_cross_account_pass_speaks_mails_id_spelling_not_sqlites was dropped
    rather than re-seeded: dedupe._run_cross_account never reads it for the
    assertion under test (only prints it), so stubbing it was compensating
    for nothing once a real store answers the call that matters
    (query_cross_account_rows)."
  - "Code-review (Spec axis, self-run per this plan's Task 3 — no sub-agent
    execution available) found query_duplicate_rows lacked a tracer test with
    real duplicate data in both shapes (only the rowless-store case existed).
    Added test_duplicate_rows_executor_reads_the_fixture using seed_base's own
    <dup@ex.com> pair before landing the PR."

requirements-completed: [GATE-08]

coverage:
  - id: D1
    description: "tests/envelope.py is the one fake Envelope Index; seed_base keeps the former _fake_envelope rows byte-for-byte on the widened schema"
    requirement: "GATE-08"
    verification:
      - kind: unit
        ref: "tests/test_mail_search.py (60 call sites migrated to seed_base) + tests/test_mail_ids.py — full pass"
        status: pass
    human_judgment: false
  - id: D2
    description: "fake_envelope/blank_envelope fixtures run every consumer in both store shapes (native + Sequoia-sidecar) via envelope_mode"
    requirement: "GATE-08"
    verification:
      - kind: unit
        ref: "tests/test_mail_triage.py#test_sent_triage_executor_reads_the_fixture[native and sidecar]"
        status: pass
      - kind: unit
        ref: "tests/test_mail_index.py#test_duplicate_rows_executor_reads_the_fixture[native and sidecar]"
        status: pass
    human_judgment: false
  - id: D3
    description: "sequoiaify_envelope carries message_global_data.message_id across the reshape instead of nulling it out"
    requirement: "GATE-08"
    verification:
      - kind: unit
        ref: "tests/test_mail_index.py#test_sequoiaify_is_idempotent_and_keeps_message_id"
        status: pass
    human_judgment: false
  - id: D4
    description: "HEADER_FINGERPRINT widened to every column an executor reads, pinned by a static coverage test that fails naming the missing column"
    requirement: "GATE-08"
    verification:
      - kind: unit
        ref: "tests/test_mail_index.py#test_header_fingerprint_covers_every_column_an_executor_reads"
        status: pass
      - kind: unit
        ref: "tests/test_mail_index.py#test_fingerprint_coverage_parse_is_not_vacuous"
        status: pass
    human_judgment: false
  - id: D5
    description: "Every query_* executor answers its empty value on a schema-only store, in both shapes — no SchemaDrift on an empty store"
    requirement: "GATE-08"
    verification:
      - kind: unit
        ref: "tests/test_mail_index.py#test_every_executor_is_empty_on_a_rowless_store[native and sidecar]"
        status: pass
    human_judgment: false
  - id: D6
    description: "Store-compensating query_* stubs in test_mail_search/triage/cleanup/addressing/extras routed through the shared fixture; disk-plane isolation and NativeError/negative stubs left alone"
    requirement: "GATE-08"
    verification:
      - kind: unit
        ref: "tests/test_mail_cleanup.py, tests/test_mail_addressing.py, tests/test_mail_extras.py — full pass; stub count in the latter two: 11 before, 4 after (all remaining are 'must not query' negatives)"
        status: pass
    human_judgment: false
  - id: D7
    description: "Real-store check on this Mac: mail_index.check_index_schema() confirms the widened fingerprint against the live Envelope Index"
    requirement: "GATE-08"
    verification:
      - kind: manual_procedural
        ref: "uv run python -c \"from macos_apps_mcp.adapters import mail_index; print(mail_index.check_index_schema())\" -> ok"
        status: pass
    human_judgment: false

duration: 2h05min
completed: 2026-09-25
status: complete
---

# Phase 01 Plan 07: Shared envelope fixture in both shapes + fingerprint coverage (card 3) Summary

**`tests/envelope.py` promotes the private fake Envelope Index to a shared fixture whose schema covers every column `mail_index`'s `query_*` executors read; `HEADER_FINGERPRINT` is widened to match and pinned by a static coverage test; store-compensating stubs across five test files now run against real sqlite in both native and Sequoia-sidecar shapes.**

## Performance

- **Duration:** ~2h05min
- **Tasks:** 3 completed (Task 1 tracer, Task 2 TDD RED/GREEN, Task 3 stub routing + land)
- **Files modified:** 9 (1 created: `tests/envelope.py`)
- **Commits:** 6

## Accomplishments

- `tests/envelope.py` (new): `SCHEMA` (the superset of columns every `query_*` executor reads — `messages.size`/`message_id`/`subject_prefix`, `message_global_data.message_id`, `recipients.type`/`position`, a new `message_references` table), `seed_base` (the former `_fake_envelope`'s rows, byte-for-byte, on the widened schema), `Envelope` (`add_mailbox`, `add_message`, `execute`) for bespoke test stores, and the `ACCT_A`/`ACCT_B`/`ACCT_LOCAL`/`MSG_COLS` constants.
- `tests/conftest.py`: `fake_envelope` (seed_base-backed) and `blank_envelope` (schema-only) fixtures, both depending on `envelope_mode` so every consumer runs native **and** Sequoia-sidecar automatically. `sequoiaify_envelope` now carries `message_global_data.message_id` across the reshape — the previous version copied `ROWID` only, silently nulling the column `build_sent_triage_query` joins the sent-triage scan on.
- `HEADER_FINGERPRINT` widened to exactly the columns a new coverage test (`test_header_fingerprint_covers_every_column_an_executor_reads`) found missing by parsing every `build_*_query`'s generated SQL and resolving `alias.column` references through the query's own `FROM`/`JOIN` bindings — RED confirmed it fails naming `messages.size`; GREEN closed it. A sanity test (`test_fingerprint_coverage_parse_is_not_vacuous`) guards against the parser silently finding nothing.
- Two tracer tests prove the widened schema serves real executors in both shapes with no stub: `test_sent_triage_executor_reads_the_fixture` (query_sent_triage) and `test_duplicate_rows_executor_reads_the_fixture` (query_duplicate_rows, added during the pre-merge code-review pass after the Spec axis found the gap).
- `tests/test_mail_search.py` (60 call sites) and `tests/test_mail_ids.py` migrated off the private `_fake_envelope`/`ACCT_*` to `tests/envelope.py`. `tests/test_mail_triage.py`'s row-returning `query_sent_triage` stub replaced with rows seeded through `fake_envelope` (a real Sent mailbox, `message_references` answering it). `tests/test_mail_cleanup.py`, `tests/test_mail_addressing.py`, `tests/test_mail_extras.py`: every `query_*` stub that only compensated for a missing store now seeds real rows and runs the real query — stub count in addressing+extras dropped from 11 to 4 (all four remaining are "must not query" negatives).
- Real-store check on this Mac: `mail_index.check_index_schema()` → `ok` — every widened fingerprint column exists on the live Envelope Index.
- Card 3 landed by PR #217 (rebase-merged onto `develop`, merge SHA `26550d3`); CI green; self-run code review (Standards + Spec, no sub-agent execution available) found and fixed one Spec gap before merge. Lane (`.worktrees/gate-card-3-envelope-fixture`, branch `refactor/gate-card-3-envelope-fixture`) removed; vault journal bullet logged.

## Task Commits

Each task was committed atomically (Task 2 as a TDD RED/GREEN pair per its `tdd="true"` attribute):

1. **Task 1: Shared envelope fixture in both shapes; test_mail_search migrated; sent-triage executor served through it (tracer)** — `1978bdd` (test)
2. **Task 2, RED: failing test for HEADER_FINGERPRINT column coverage** — `2833a59` (test)
3. **Task 2, GREEN: widen HEADER_FINGERPRINT + route mail_cleanup's stubs** — `b921ff6` (feat), `adb08ff` (test)
4. **Task 3: route addressing/extras' stubs through the fixture; land the PR** — `3b0d4f2` (test)
5. **Task 3, code-review fix: tracer proof for query_duplicate_rows** — `26550d3` (test)

_Note: Task 2's own verify (fingerprint widening) and the mail_cleanup stub-routing were split into two commits (`b921ff6` GREEN, `adb08ff` stub routing) since the latter is additional test work beyond the RED/GREEN pair itself._

No REFACTOR commit — neither TDD cycle needed cleanup.

## Files Created/Modified

- `tests/envelope.py` (new) — the shared fake Envelope Index
- `tests/conftest.py` — `fake_envelope`/`blank_envelope` fixtures; `sequoiaify_envelope` message_id fix
- `macos_apps_mcp/adapters/mail_index.py` — `HEADER_FINGERPRINT` widened
- `tests/test_mail_search.py` — migrated to `tests.envelope`'s `seed_base`/`ACCT_*`
- `tests/test_mail_ids.py` — same migration (one import + one call site)
- `tests/test_mail_triage.py` — real sent-triage fixture data; new tracer test
- `tests/test_mail_index.py` — coverage tests, rowless-store test, sequoiaify idempotency test, duplicate-rows tracer test
- `tests/test_mail_cleanup.py` — cross-account and duplicate-report stubs routed through `blank_envelope`
- `tests/test_mail_addressing.py` — resolve()/resolve_mailbox() stubs routed through `blank_envelope`; the impossible-shape test re-expressed
- `tests/test_mail_extras.py` — stats() stubs routed through `blank_envelope`

## Decisions Made

See `key-decisions` in the frontmatter — five decisions, each already justified inline above (the impossible-shape re-expression, the duplicates-test arithmetic change, the `blank_envelope` promotion, the dropped `query_cross_account_summary` stub, and the code-review-driven `query_duplicate_rows` addition).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `sequoiaify_envelope` nulled `message_global_data.message_id` across the reshape**
- **Found during:** Task 1 (read_first review of `tests/conftest.py`)
- **Issue:** The pre-existing helper copied only `ROWID` into the reshaped table, silently discarding `message_id` — the column `build_sent_triage_query` joins the sent-triage scan on. A sidecar-mode read of that query would answer zero rows even though the same query worked in native mode.
- **Fix:** Carry `message_id` across when the source table has the column (checked via `PRAGMA table_info`); idempotent (a store already reshaped is left alone, unchanged).
- **Files modified:** `tests/conftest.py`
- **Verification:** `test_sequoiaify_is_idempotent_and_keeps_message_id`; `test_sent_triage_executor_reads_the_fixture[sidecar]`
- **Committed in:** `1978bdd` (Task 1 commit)

**2. [Rule 2 - Missing test coverage] `query_duplicate_rows` had no both-shapes tracer test with real duplicate data**
- **Found during:** Task 3's self-run code review (Spec axis, against GATE-08's must_have "query_sent_triage and query_duplicate_rows run against the fixture in both shapes")
- **Issue:** Only the rowless-store test exercised `query_duplicate_rows`; no test proved it correctly reads `size`/`date_sent` (the byte-identity gate's columns) with real duplicate rows in both store shapes.
- **Fix:** Added `test_duplicate_rows_executor_reads_the_fixture`, using `seed_base`'s own `<dup@ex.com>` pair.
- **Files modified:** `tests/test_mail_index.py`
- **Verification:** passes `[native]` and `[sidecar]`
- **Committed in:** `26550d3` (post-CI, pre-merge)

---

**Total deviations:** 2 auto-fixed (1 bug fix, 1 missing test coverage). Both necessary for GATE-08's must_haves; no scope creep.

## Issues Encountered

None — every task's verification passed on the first or second attempt (the fingerprint widening's RED/GREEN cycle behaved exactly as designed).

## User Setup Required

None — no external service configuration required.

## Known Stubs

None — this plan's whole purpose was removing store-compensating stubs; the four remaining `query_search` stubs in `tests/test_mail_addressing.py` are legitimate "must not query" negatives (they assert `resolve()` never touches the index when a `folder` token is trusted verbatim, or refuses before querying), not stand-ins for missing functionality.

## Next Phase Readiness

- GATE-08 is complete: `tests/envelope.py` is the one shared fixture, `HEADER_FINGERPRINT` covers every column an executor reads, and both are pinned by tests.
- Card 3 is on `develop` (PR #217, merge SHA `26550d3`). Cards 4 (PR #215, open) and 9 (already merged, PR #213) round out the Mail-scoped parallel track; card 3's completion does not block either.
- `#180`'s convention (new `mail_index` reads tested through the shared fixture, not a private stub) now has a concrete home for any future `query_*` addition.
- Plan 01-10's daemon doctor check and plan 01-14's spike-branch/worktree cleanup are unaffected by this card and remain open.

## Self-Check: PASSED

All claimed files verified present on `origin/develop` (or locally for the SUMMARY itself); all six claimed commit hashes verified present in git history.

---
*Phase: 01-gate-land-the-spiked-architecture-cuts*
*Completed: 2026-09-25*
