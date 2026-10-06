---
phase: quick-261006-uff
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - macos_apps_mcp/adapters/mail_recover.py
  - tests/test_mail_recover.py
  - macos_apps_mcp/adapters/mail_index.py
  - tests/test_mail_membership.py
  - tests/test_mail_index.py
  - tests/envelope.py
  - CHANGELOG.md
  - docs/mail-applescript-facts.md
autonomous: true
requirements: [PR-251-HARDEN]

estimate:
  tokens: 45000
  raw_tokens: 45000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "A move/trash whose source folder is a Gmail label url locates (and so backs up) the physical row in the target's OWN account, even when query_message_locations lists another account's copy first"
    - "A target with no account (unified accessor / empty folder) still takes the first located row, exactly as before"
    - "When one stored message sits in two equal-rank Gmail labels, an unscoped search cites the label with the lower mailboxes.ROWID, on every run"
    - "mail_overview / mail_search counts are unchanged by UNION ALL — every existing membership and overview test stays green"
    - "Every comment, docstring, CHANGELOG line and facts-doc line touched states only true, dated facts and carries no account name, UUID, address or custom label name"
    - "None of the three new commits touches a .planning/ path, and the contributor commit 096cccf is an unmodified ancestor of HEAD"
  artifacts:
    - path: "macos_apps_mcp/adapters/mail_recover.py"
      provides: "locate() same-account fallback before candidates[0]"
      contains: "account_of"
    - path: "macos_apps_mcp/adapters/mail_index.py"
      provides: "_MAILBOX_MEMBERSHIP_CTE with UNION ALL; _BASE_SQL window ordered to a unique last key"
      contains: "mb.ROWID) AS rn"
    - path: "tests/test_mail_recover.py"
      provides: "regression test for the cross-account label-folder locate"
    - path: "tests/test_mail_membership.py"
      provides: "regression test for the equal-rank label tie-break"
  key_links:
    - from: "macos_apps_mcp/adapters/mail_recover.py:locate"
      to: "macos_apps_mcp/adapters/mail_index.py:account_of"
      via: "account of each candidate's mailbox_url compared with Target.account (#175: no hand-parsed urls)"
      pattern: "mail_index\\.account_of\\("
    - from: "macos_apps_mcp/adapters/mail_index.py:_BASE_SQL"
      to: "ROW_NUMBER() OVER (PARTITION BY gd.message_id_header ...)"
      via: "final ORDER BY key mb.ROWID"
      pattern: "mb\\.ROWID\\) AS rn"
    - from: "macos_apps_mcp/adapters/mail_index.py:HEADER_FINGERPRINT"
      to: "tests/envelope.py:SCHEMA"
      via: "lockstep widening comment for mailboxes.source + labels"
      pattern: "251"
---

<objective>
Harden outside-contributor PR #251 (Gmail label membership in `mail_overview` / `mail_search`) on its own branch before merge: close one backup-safety hole the PR opens in the recover plane, make the cited label folder deterministic, take the cheaper `UNION ALL`, and correct the comments, CHANGELOG and facts doc so they state only true, device-verified facts.

Purpose: the project's core value is safe writes. After #251, search cites Gmail label folders (for example the Gmail INBOX url). A label folder is never a physical row, so `mail_recover.locate` falls through to an unordered `candidates[0]` — live on the owner's Mac that is another account's copy for 272 of 1,056 label members, so the backup and the receipt would record the wrong account's file.

Output: three atomic commits on branch `pr-251` in the code lane, on top of `096cccf`; nothing pushed.

Tracer note: no `type="tracer"` task. This is review hardening inside a proven architecture (no new layer, no new path), so a thin slice adds no information. T1 is the riskiest change and runs first.
</objective>

<lanes>
- **Code lane** (ALL edits, tests and commits): `/Users/andrei/Developer/macos-apps-mcp/.worktrees/review-251`, branch `pr-251`, HEAD at start = `096cccf` (author Aaron Dippner). Every path in this plan is relative to this root and every `<automated>` command assumes cwd = this root. The branch is pushed to the contributor's fork, so NO `.planning/` file may ever be created, staged or committed here.
- **Records lane** (this PLAN and the executor's SUMMARY only, nothing committed by the executor): `/Users/andrei/Developer/macos-apps-mcp/.worktrees/quick-251-records/.planning/quick/261006-uff-harden-pr-251-gmail-label-membership-bef/`.
- Commit rules for every task: stage ONLY the files the task names (`git -C <code lane> add <paths>`, never `add -A` / `add .`); message style `fix(mail): … (#251)` / `docs(mail): … (#251)`; body ends with the trailer line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never amend, rebase or rewrite `096cccf`. Do not push.
</lanes>

<execution_context>
@~/.claude/gsd-core/workflows/execute-plan.md
@~/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@/Users/andrei/Developer/macos-apps-mcp/.worktrees/review-251/CLAUDE.md
@/Users/andrei/Developer/macos-apps-mcp/.worktrees/review-251/.claude/CLAUDE.md
@/Users/andrei/Developer/macos-apps-mcp/.worktrees/review-251/docs/mail-applescript-facts.md (§5f new in the PR; §8b "sqlite locates, AppleScript acts")

Interfaces the executor needs (verified by the planner at `096cccf`):

- `mail_recover.Target` (frozen dataclass): `id`, `folder` (round-trip `mailboxes.url` or a canonical name), `account` (owning account uuid, or None for a unified accessor), `rowid`, `path`, `fidelity`, … `move_mail` builds it with `account=mail_index.account_of(from_mailbox)`; `delete_draft` builds it with `folder=""` and no account.
- `mail_recover.locate(targets) -> list[Target]` (~lines 184-230): groups `mail_index.query_message_locations(...)` rows by `mail_addressing.bare_id`, then picks `row = next((c for c in candidates if c["mailbox_url"] == t.folder), candidates[0] if candidates else None)`. Each row is a dict `{"message_id", "rowid", "mailbox_url"}`; rows are PHYSICAL locations (`messages.mailbox`) only.
- `mail_index.account_of(url: str) -> str | None` (line ~103) delegates to `mailbox_url.account` — the one url parse (#175). `mail_recover` already imports `mail_index`; no new import is needed.
- `mail_index._MAILBOX_MEMBERSHIP_CTE` (~lines 153-171) and `_BASE_SQL` (~173-185); `_BASE_SQL`'s window line is `ORDER BY {_MAILBOX_RANK}, m.date_received DESC, m.ROWID) AS rn` and is already exactly 88 columns wide.
- `HEADER_FINGERPRINT` (~lines 23-64), `build_duplicate_summary_query` docstring (~396-404), `build_overview_query` docstring (~719-741).
- Test helpers: `tests/test_mail_recover.py` fixture `store` (fake root with `10.emlx` full and `11.partial.emlx`; it monkeypatches `mail_index.query_message_locations` and `mail_index.mail_root`), helper `_target(mid, folder=BOX)`, constants `ACCT`, `BOX`, `ARCHIVE`. `tests/test_mail_membership.py` fixture `gmail_envelope` returns `(db, boxes, urls)`; `db.add_mailbox(url, *, source=None) -> int`, `db.add_message(**cols) -> int`, `db.execute(sql, params)`; `ACCT_A`, `ACCT_B` from `tests.envelope`. `gmail_envelope` runs in both native and sidecar `envelope_mode`.
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: locate() backs up the target account's own copy for a Gmail label folder</name>
  <files>macos_apps_mcp/adapters/mail_recover.py, tests/test_mail_recover.py</files>
  <read_first>macos_apps_mcp/adapters/mail_recover.py lines 90-125 and 184-230; tests/test_mail_recover.py lines 1-140</read_first>
  <behavior>
    - Test A (fails at 096cccf): target `_target("a@x", folder=<label url in ACCT>)` where `query_message_locations` returns FIRST a row for `<a@x>` with rowid 99 in another account's INBOX (`imap://BBBBBBBB-1111-2222-3333-444444444444/INBOX`), THEN a row with rowid 10 in `imap://{ACCT}/%5BGmail%5D/All%20Mail` → locate stamps rowid 10, fidelity `full`, and a path ending `10.emlx`. Today it picks rowid 99 (no file in the fake store) → fidelity `absent`.
    - Test A, same body: a target with no account (`mail_recover.Target(id="a@x", folder="inbox")`) against the same rows still gets rowid 99 (the first row) — the unified-accessor fallback is unchanged.
    - Existing locate tests (own-mailbox match, partial, absent, path not in receipt, single store walk) stay green.
  </behavior>
  <action>
RED first. In tests/test_mail_recover.py, under the `# --- locate ---` section, add one test, for example `test_locate_prefers_the_targets_own_account_for_a_gmail_label_folder(store, monkeypatch)`. Use the `store` fixture for the fake root, then re-patch `mail_index.query_message_locations` inside the test (a later `monkeypatch.setattr` wins) with the two rows from the behavior block, other account FIRST. Define the label url locally (for example `imap://{ACCT}/Receipts`) and the other account's uuid as a local constant. Add a two-line comment: a Gmail label folder is never a physical row (#251), so no row matches `t.folder`, and the old first-row fallback backed up another account's file (live: 272 of 1,056 label members). Assert both behavior bullets. Run the test and confirm it FAILS (rowid 99 / absent) before touching the adapter; commit nothing yet.

GREEN. In `locate`, replace the single `next(...)` pick with a three-step choice, in this order: (1) the candidate whose `mailbox_url` equals `t.folder` (unchanged); (2) only when `t.account is not None`, the first candidate whose `mail_index.account_of(c["mailbox_url"]) == t.account`; (3) `candidates[0]` if any candidates, else None. Use `mail_index.account_of` — do NOT hand-parse or split the url (#175 keeps one parse, in `mailbox_url`). No AppleScript, no mailbox enumeration, no change to `query_message_locations` (§8b: sqlite locates, AppleScript acts). Keep the loop shape and everything after the pick as is.

Docstring. Extend the `locate` docstring paragraph about folder matching: a Gmail label folder (#251) is a mailbox url but never a physical row — `query_message_locations` reads `messages.mailbox` only — so it matches nothing; the row in the target's own account (its All Mail copy) wins next, and only then the first row. Keep the existing canonical-name sentence (an account-less target still takes the first row). One dated clause is enough: live 2026-10-06, 272 of 1,056 label members had a copy in another account that the bare first-row fallback picked.

Run the full suite, ruff check and ruff format check. Commit only the two files: `fix(mail): back up the target account's copy for a Gmail label folder (#251)`, body one or two lines, ending with the Co-Authored-By trailer.
  </action>
  <verify>
    <automated>uv run pytest -q tests/test_mail_recover.py && uv run pytest -q && uv run ruff check . && uv run ruff format --check .</automated>
  </verify>
  <done>The new test failed at 096cccf and passes now; `grep -c "mail_index.account_of(" macos_apps_mcp/adapters/mail_recover.py` is at least 1; full suite, ruff check and ruff format check pass; one new commit touching exactly mail_recover.py and test_mail_recover.py.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: deterministic label citation, UNION ALL membership, true comments and docstrings</name>
  <files>macos_apps_mcp/adapters/mail_index.py, tests/test_mail_membership.py, tests/test_mail_index.py, tests/envelope.py</files>
  <read_first>macos_apps_mcp/adapters/mail_index.py lines 20-66, 140-186, 390-420, 715-745; tests/test_mail_membership.py (whole file); tests/test_mail_index.py lines 420-432; tests/envelope.py lines 40-62</read_first>
  <behavior>
    - Tie-break test: one live message (new Message-ID, newest `date_received`) labelled ONLY in two custom labels of equal rank, both `source = boxes["all"]`. Label "Zeta" is created FIRST (lower mailboxes.ROWID, later url); label "Alpha" second (higher ROWID, earlier url). `mail_index.query_search(message_ids=[<that id>])` cites the Zeta url; a second identical call cites the same url.
    - Same test, RED gate: the whitespace-normalised `mail_index._BASE_SQL` (`" ".join(mail_index._BASE_SQL.split())`) contains `m.ROWID, mb.ROWID) AS rn`. Planner-measured at 096cccf: on a fixture-size store SQLite already returns this tie in labels-primary-key order (lower mailbox ROWID first), with and without `PRAGMA reverse_unordered_selects`, so the behavioural assertion passes before the fix. The SQL-shape assertion is the real RED step; the behavioural one guards against a later regression to a url- or rank-only order. Do not spend time trying to make the behavioural half fail.
    - All existing overview/search/membership tests stay green after `UNION ALL` (counts are COUNT(DISTINCT …) and search keeps `rn = 1`, so the switch cannot change any result).
  </behavior>
  <action>
RED first. In tests/test_mail_membership.py add `test_unscoped_search_breaks_an_equal_rank_label_tie_by_mailbox_rowid(gmail_envelope)` per the behavior block. Build it on the fixture: `db.add_mailbox(f"imap://{ACCT_A}/Zeta", source=boxes["all"])`, then the Alpha one; insert a `message_global_data` row (for example ROWID 510, header `<tie@example.test>`); `db.add_message(ROWID=110, subject=1, global_message_id=510, message_id=910, mailbox=boxes["all"], date_received=2000, read=0, deleted=0)`; two `labels` rows. Comment in two lines why: one stored row appears once per label membership (#251), so `m.ROWID` no longer ends the window order; Zeta/Alpha are named against url order so a url sort cannot pass by accident. Run it and confirm the SQL-shape assertion FAILS.

GREEN, all in macos_apps_mcp/adapters/mail_index.py:
1. `_BASE_SQL` window: append `mb.ROWID` as the final ORDER BY key, after `m.ROWID`, written as `m.ROWID, mb.ROWID) AS rn`. The line is already 88 columns, so wrap the ORDER BY over two lines the way `build_thread_query`'s window does (~line 330). Add a short comment above `_BASE_SQL`: with label membership one stored row appears once per label (#251), `m.ROWID` ties across equal-rank labels, and `mb.ROWID` makes the cited folder independent of the query plan. Do not touch `build_thread_query`, `build_sent_triage_query` or `build_stats_query` (separate follow-up).
2. `_MAILBOX_MEMBERSHIP_CTE`: change the set operator between the two arms to `UNION ALL`. Rewrite the comment block above it: cite #251; keep the physical-vs-logical point and the warning to keep backup/file-location reads on `messages.mailbox`; add one line why `UNION ALL` is safe — arm 1 requires `mb.source IS NULL`, arm 2 requires `mb.source = m.mailbox` (non-NULL), so the arms are disjoint, and the `labels` primary key `(message_id, mailbox_id)` rules out repeats inside arm 2; it skips the dedup sort (measured: identical counts, about half the added search latency recovered). Note the trigger rule as device-verified 2026-10-06 (facts §5f).
3. `HEADER_FINGERPRINT`: add a comment above the `"mailboxes"` line in the same style as the existing `# conversation_id: …` comment: `mailboxes.source` + `labels` (#251) — Gmail label membership, read by `_MAILBOX_MEMBERSHIP_CTE` (overview + search); a mailbox with a `source` is a label backed by that store (facts §5f).
4. `build_overview_query` docstring:
   - First paragraph: remove the false reason. The "Gmail INBOX row reports 1 unread where a live count returns 0" observation was this query ignoring `labels` (#251); live 2026-10-06 Mail's stored counters equal these counts on every label-backed mailbox. Drop the `unread_count_adjusted_for_duplicates … same wrong value` clause (it rests on the same misreading). The true reason to count live: the stored counters are trigger-maintained per stored row and do not dedupe by Message-ID the way this count does. Keep the 16 ms measurement.
   - Last paragraph: restore the warning the PR dropped. The LEFT JOIN chain must stay outer all the way — all three LEFT JOINs (membership, messages, message_global_data); none may become inner — so an empty mailbox or a label with no live members reads 0/0 instead of vanishing. Keep the "count logical memberships, including Gmail labels (#251)" sentence.
5. `build_duplicate_summary_query` docstring: the claim that `distinct_` "is what `mail_overview` reports" holds only for a direct (physical) mailbox. Say so: for a Gmail label mailbox (`mailboxes.source` set, #251) `mail_overview` counts label memberships, which this physical-row table never sees, so the two read side by side only on direct mailboxes. Do not change the SQL.

Other test/fixture text:
6. tests/test_mail_index.py `test_overview_query_counts_live_not_stored` (~lines 423-425): keep every assertion; replace the comment with the true reason — Mail's stored counters count stored rows and do not dedupe by Message-ID, this query does; the old "stale Gmail INBOX" reading was this query ignoring `labels` (#251), and live 2026-10-06 the stored counters match the #251 counts.
7. tests/envelope.py, the `# Widened beyond the original _fake_envelope …` comment above `SCHEMA`: add one sentence — `mailboxes` gains `source` and `labels` is new (#251), the Gmail label membership `_MAILBOX_MEMBERSHIP_CTE` reads. Do not touch the DDL, the duplicate `labels` DDL in tests/test_mail_index.py, or the missing future import in tests/test_mail_membership.py (out of scope).

Run the full suite, ruff check and ruff format check. Commit only the four files: `fix(mail): deterministic label citation and UNION ALL membership (#251)`, ending with the Co-Authored-By trailer.
  </action>
  <verify>
    <automated>uv run pytest -q tests/test_mail_membership.py tests/test_mail_index.py && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && test "$(grep -c 'UNION ALL' macos_apps_mcp/adapters/mail_index.py)" -ge 1 && test -z "$(grep -nE '^[[:space:]]+UNION[[:space:]]*$' macos_apps_mcp/adapters/mail_index.py)"</automated>
  </verify>
  <done>The SQL-shape assertion failed at the Task 1 commit and the whole new test passes now in both envelope modes; `_BASE_SQL` ends its window order with `mb.ROWID`; the CTE uses `UNION ALL` with the disjointness comment citing #251; the fingerprint, overview docstring (outer-join warning restored, false stale-counter reason gone), duplicate-summary docstring, test_mail_index comment and envelope.py comment are corrected; full suite, ruff check and ruff format check pass; one new commit touching exactly the four files.</done>
</task>

<task type="auto">
  <name>Task 3: CHANGELOG house-form entry and device-verified facts §5f</name>
  <files>CHANGELOG.md, docs/mail-applescript-facts.md</files>
  <read_first>CHANGELOG.md lines 1-75; docs/mail-applescript-facts.md lines 1-15 and 309-326</read_first>
  <action>
CHANGELOG.md, `## [Unreleased]` → `### Fixed`: replace the contributor's four-line entry (starts "Mail overview and indexed search now include Gmail Inbox…") with one entry in the house form `- **bold lead** (#251) — why.`, wrapped at about 88 columns and as short as its neighbours. Content: Gmail Inbox, Sent Mail and labels no longer read empty in `mail_overview` / `mail_search` (Mail stores a Gmail message once, under All Mail, and records the rest as label membership); a move or trash from a Gmail label folder now backs up the target account's own copy. Leave every other entry untouched.

docs/mail-applescript-facts.md §5f: keep the contributor's observation paragraph and bullets. Add a dated device-verification block (bold lead, then bullets, matching the file's style): verified 2026-10-06 on macOS 27.0.1 against one Gmail account —
- Mail's own triggers `after_insert_message`, `after_insert_label` and `before_delete_message` use exactly this membership rule.
- With the rule, overview counts equal `mailboxes.total_count` / `unread_count` on all 4 label-backed mailboxes (Inbox, Sent Mail and 2 custom labels); the other 152 mailboxes read unchanged.
- Backup consequence: a label folder is never a physical row, so the recover plane's location query never matches it; `locate` now prefers the row in the target's own account and only then the first row — 272 of 1,056 label members had a copy in another account that the old fallback picked.

The repo is PUBLIC: write no account name, account UUID, email address or custom label name in either file. Use only the counts and generic names above.

Run the full suite, ruff check and ruff format check (docs are ruff-excluded, but the gate is per task). Commit only the two files: `docs(mail): changelog and device-verified facts for Gmail labels (#251)`, ending with the Co-Authored-By trailer.
  </action>
  <verify>
    <automated>test "$(grep -c '(#251)' CHANGELOG.md)" -eq 1 && grep -q '2026-10-06' docs/mail-applescript-facts.md && D="$(git diff 096cccf -- CHANGELOG.md docs/mail-applescript-facts.md)" && test -n "$D" && test -z "$(printf '%s\n' "$D" | grep '^+' | grep -E '[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-|@[a-z0-9-]+\.[a-z]')" && uv run pytest -q && uv run ruff check . && uv run ruff format --check .</automated>
  </verify>
  <done>Exactly one `(#251)` entry under Unreleased/Fixed in house form; §5f carries the dated 2026-10-06 verification with the three facts; the lines added since 096cccf contain no UUID or email address (the diff is taken against 096cccf, so the gate holds before and after the commit; Tasks 1-2 do not touch these files); suite and ruff pass; one new commit touching exactly CHANGELOG.md and docs/mail-applescript-facts.md.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| Envelope Index (sqlite, read-only) → recover plane | Index rows choose which `.emlx` file a destructive Mail op backs up and records in its receipt |
| Code lane → public fork PR #251 | Everything committed on `pr-251` becomes public on push |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-uff-01 | Tampering (integrity of backup) | `mail_recover.locate` | high | mitigate | Task 1: same-account preference before `candidates[0]`, via `mail_index.account_of`; regression test with the other account's row listed first |
| T-uff-02 | Repudiation (unstable citation) | `_BASE_SQL` window order | medium | mitigate | Task 2: `mb.ROWID` final key; SQL-shape plus behavioural test |
| T-uff-03 | Information disclosure | CHANGELOG / facts §5f | medium | mitigate | Task 3: counts and generic names only; verify gate rejects added UUIDs and email addresses |
| T-uff-04 | Information disclosure | `.planning/` artifacts | low | mitigate | Records lane holds all planning files; explicit-path staging only; final check that no commit in `096cccf..HEAD` touches a `.planning/` path |
| T-uff-SC | Tampering | package installs | low | accept | No dependency is added or changed |
</threat_model>

<verification>
From the code lane root, after Task 3:
- `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .` all pass.
- `git log --oneline 096cccf..HEAD` shows exactly three commits, each subject ending `(#251)`, each body ending with the Co-Authored-By trailer.
- `git merge-base --is-ancestor 096cccf HEAD` succeeds, and `git log -1 --format=%an 096cccf` is still the contributor.
- `F="$(git diff --name-only 096cccf..HEAD)" && test -z "$(printf '%s\n' "$F" | grep '^\.planning/')"` succeeds (develop already tracks about 208 `.planning/` files — the gate is that none of OUR three commits touches one), and `git status --porcelain` shows nothing under `.planning/`.
- Nothing pushed: `git status -sb` may show `pr-251` ahead of its upstream; that is expected.
</verification>

<success_criteria>
- A Gmail label-folder move/trash backs up the target account's own copy (Task 1 test green; it was red at 096cccf).
- Equal-rank label ties cite the lower `mailboxes.ROWID` deterministically (Task 2 test green; its SQL-shape half was red before).
- `UNION ALL` in place with no count change.
- All six review findings addressed; out-of-scope queries (`build_sent_triage_query`, `build_thread_query`, `build_stats_query`, `query_message_locations`, dedupe SQL) untouched.
</success_criteria>

<output>
Write the SUMMARY to the RECORDS lane, never the code lane:
`/Users/andrei/Developer/macos-apps-mcp/.worktrees/quick-251-records/.planning/quick/261006-uff-harden-pr-251-gmail-label-membership-bef/261006-uff-SUMMARY.md`
Include the three commit SHAs, the RED-then-GREEN evidence for Task 1 and the Task 2 SQL-shape assertion, and the final pytest/ruff output lines.
</output>
