---
status: diagnosed
trigger: "reply-drafts-cleanup-unproven: A sent reply reports a proven Drafts cleanup result and has the required timed observations."
created: 2026-11-14T00:00:00Z
updated: 2026-11-14T00:00:00Z
---

## Current Focus

bug_class: Bohrbug at the decision level (the value is set by deterministic in-call rules); the input that fires a rule is device state (Mail's body shape, file write timing, delete latency), so the branch is environment-dependent.

hypothesis: (a) product. `drafts_copy` is set INSIDE the `reply_all` call, by `_ReplyFlow.after_send()` -> `sweep(sent=True)`, about 45 s after the reply window opened. This happens before the result reaches the operator, so the operator's first check at 111 s cannot change it. The later observations (no new reply draft at 111 s, 152 s and 27.8 min; final Drafts equal to the baseline) eliminate every `unproven` branch that leaves a copy behind. So `unproven` came from a fail-safe branch that left nothing: R1, R2 or R3 below. The sweep records no reason, so the branch cannot be identified from the records. (b) is a separate gap: the +45 s Drafts observation after the send was not made (first check at 111 s). It explains the missing observation, not the `unproven` value.

reasoning_checkpoint:
  hypothesis: "The `unproven` value is a product outcome. A no-leftover fail-safe branch of the in-call sweep produced it: R1 (the delete was not confirmed), R2 (a sent twin was not set aside) or R3 (a new row could not be read). The 111-s operator timing (b) had no input into it."
  confirming_evidence:
    - "mail_outgoing.py open_reply_with_text: `_send_reply` then `flow.after_send()`. sweep() runs `_wait_until(opened_at + SWEEP_AFTER_S)` (45 s), then `find_own_draft`, and returns the value that `deliver()` merges into the result. test_reply_all_waits_until_45_s_after_the_window_opened_then_sweeps pins `waits == [145.0]` for opened_at = 100."
    - "05.2-16-SUMMARY Gap 1 and Facts: no new reply draft at 111 s, 152 s or 27.8 min. Section I: the final Drafts comparison matched the initial baseline."
    - "Every branch that leaves a found copy undeleted (_may_claim False, rowid > landed_by, two Drafts rows, a localized or label Drafts) deletes nothing. Facts §3 and §4e run 12 say an autosave copy survives a send (still there at +2 min, 12 h+ seen). So a copy left by those branches would have been visible at 111 s. None was."
    - "No logger in mail_reply_cleanup.py or mail_outgoing.py, and `_SENT_COPY['unproven']` merges two cause families ('could not prove ... or could not confirm a delete'). So the device record cannot name the branch."
  falsification_test: "With a reason code (or a log line) on the sweep, repeat step D. If the reason is a branch that leaves a copy (claim refused, or the copy landed after the send) AND a Drafts copy is visible afterwards, the elimination is wrong. If `drafts_copy` changes with the operator's check time, (b) caused it."
  fix_rationale: "Out of scope (diagnose only). The first fix must make `unproven` attributable. Without that, a further sitting reproduces this gap and still cannot say which rule fired."
  blind_spots: "The private sitting log (p052-probe/acceptance-gaps2.md, outside this worktree) was not read, under the 'stay inside the worktree' constraint. It may hold the call's wall time and the exact note. The call's duration beyond opened_at + 45 s would separate R1 (adds a delete script with `delay 3`, plus two Mail reads) from R2 and R3 (about 0 s extra). The operator's `P drafts-since` filter (`Re:` subject, baseline file) was assumed to be reliable."
  candidate_causes:
    - "code: R1, `_SWEEP_DELETE` answers `alive`/`gone`/`several` or raises after a real delete, and sweep() maps every answer except `deleted` to `unproven`. Its one `delay 3` re-count had never run on device (05.2-13 SUMMARY: the own-copy delete was not exercised)."
    - "data: R2, the delivered reply's own rows (the sending account's `Sent Messages` copy, Gmail `[Gmail]/All Mail` copy) thread to the original and fail `_is_own` or `_has_quote`. UAT gap 3 shows that the device body shape differs from the 05.2-15 assumption (the delivered HTML has no `div#AppleMailSignature`)."
    - "environment: R3, a new row in any account has no `.emlx` on disk at +45 s (a body Mail has not written yet, for example the delivered Gmail copy or unrelated incoming mail). find_own_draft returns `unproven` at the first such row (mail_reply_cleanup.py:356)."
    - "procedure: (b), the plan's +45 s check after the send falls about 0-10 s after the call returns (the call blocks until opened_at + 45 s), and it was run at 111 s. This does not affect the value."
  and_gate: "Yes, for the UAT gap as written (two failed parts). The `unproven` value needs (a) only. The missing 45-second observation needs (b) only. The two causes are independent, and each needs its own fix."

next_action: Diagnosis complete; return ROOT CAUSE FOUND to the caller (goal: find_root_cause_only).

## Symptoms

expected: `drafts_copy` is `removed` or `none`, with the required timed Drafts checks.
actual: The result was unproven; the first post-send comparison was at 111 seconds. (UAT observed: `drafts_copy` was `unproven`; the first Drafts comparison ran at 111 seconds.)
errors: None reported
reproduction: Test 2 in UAT (Phase 05.2, plan 05.2-16 device acceptance, 2026-11-03)
started: Discovered during UAT

## Eliminated

- hypothesis: The operator's late first check (111 s) caused or changed `drafts_copy`.
  evidence: The value is set inside the call by sweep() after `_wait_until(opened_at + 45)` and is returned with `sent`. No operator action after the return feeds back into it (mail_outgoing.py open_reply_with_text, _ReplyFlow.after_send, deliver).
  timestamp: 2026-11-14

- hypothesis: The sweep found the call's Drafts copy but refused to claim it (sender unreadable, From address held by zero or two accounts, `_BASELINE_CLEAR` block, claim span over 120 s), so a copy was left.
  evidence: These branches delete nothing, and an autosave copy survives a send (facts §4e run 12, §3). The operator found no new reply draft at 111 s, 152 s or 27.8 min, and the final Drafts comparison matched the baseline.
  timestamp: 2026-11-14

- hypothesis: The copy landed after the send answered (rowid > landed_by), or a second or localized Drafts row was found, so it was reported and left.
  evidence: Same as above: a copy that is not deleted stays, and none was seen.
  timestamp: 2026-11-14

- hypothesis: The Envelope Index was unreadable (Full Disk Access) or the read came too soon.
  evidence: These produce `unavailable` and `late`, not `unproven` (sweep() lines 1285-1312).
  timestamp: 2026-11-14

## Evidence

- timestamp: 2026-11-14
  checked: 05.2-UAT.md Test 2, 05.2-16-SUMMARY.md (D, I, Gap 1, Facts)
  found: The send returned `drafts_copy: unproven`. The first operator Drafts comparison was at 111 s, then 152 s and 27.8 min, and none found a new reply draft. The final Drafts comparison matched the initial baseline. The delivered reply's route checks passed.
  implication: No Drafts copy was left at any observed time. Either no copy landed, or a copy landed and was removed before 111 s.

- timestamp: 2026-11-14
  checked: 05.2-16-PLAN.md Task 2 step D and must_haves
  found: "`P drafts-since R/acc2-drafts.json Re:` at +45 s and +2 min: nothing new; when the result says `removed`, again at +15 min (Gmail)." The +45 s has no stated origin. The sheet does not say that the call itself blocks until 45 s after the window opened.
  implication: The +45 s check falls about 0-10 s after the call returns, so it is almost impossible to meet through an orchestrator relay. The 111-s first check is a procedure gap (b).

- timestamp: 2026-11-14
  checked: macos_apps_mcp/adapters/mail_outgoing.py open_reply_with_text (1372-1458), _ReplyFlow.after_send (1358-1369), sweep (1272-1324)
  found: The sequence is send -> window_gone() (landed_by) -> sweep(sent=True) -> wait until opened_at + 45 s -> find_own_draft -> optional _ACCOUNT_ADDRESSES, _BASELINE_CLEAR and _SWEEP_DELETE -> value. `unproven` comes from: find_own_draft kind `unproven`; kind `one` with _may_claim False; any _SWEEP_DELETE answer except `deleted` (`alive`, `gone`, `several`) or an exception; or any non-NativeError exception in find_own_draft.
  implication: `drafts_copy` is fixed in-call, before the operator's first check. At least 8 distinct branches share the same value.

- timestamp: 2026-11-14
  checked: macos_apps_mcp/adapters/mail_reply_cleanup.py find_own_draft (323-379)
  found: `unproven` when more than 300 new rows exist (351); at the FIRST new row in any mailbox of any account whose `.emlx` cannot be found or read, threaded or not (356); for a threaded row that is not a claimable Drafts row and not a set-aside sent twin (376); for two or more threaded rows (379). A sent twin is set aside only if it is in a Sent leaf or `[Gmail]/All Mail`, has a Message-ID, matches `_is_own` (exact text, then optional signature equal except for white space, then optional attribution) AND `_has_quote` (the original's tail is the last thing).
  implication: The after-send sweep reads the delivered reply's own rows (Sent copy, Gmail All Mail copy) and every unrelated new row. Any one of these can turn the result `unproven` with nothing left in Drafts.

- timestamp: 2026-11-14
  checked: _SWEEP_DELETE (mail_outgoing.py 727-746) and the 05.2-13 SUMMARY
  found: One `delete`, one `delay 3`, one re-count. `deleted` only when the re-count is 0. `gone` (no match before the delete) is also mapped to `unproven`. 05.2-13: "The own-copy delete (`one`) ... [was] not exercised". Facts §5c: delete clears the source "by t3", measured on another account.
  implication: If a copy landed in 05.2-16, this was the first device run of the 3-s confirm. A delete that clears after 3 s gives `unproven` and a clean Drafts at 111 s. This matches the observations (R1).

- timestamp: 2026-11-14
  checked: 05.2-13-SUMMARY G4, 05.2-15-PLAN, UAT Test 3 and 05.2-16 Gap 2
  found: 05.2-13: the signature appeared as `div#AppleMailSignature` between the text and the quote, and "every own copy and sent twin read `unproven`". 05.2-15 added the signature shape to `_is_own`, with synthetic tests only. 05.2-16: the outgoing signature reads (alnum length 58), but the delivered HTML has NO `AppleMailSignature` element.
  implication: The body shape that the set-aside rule was written for was not the shape on device in 05.2-16. Whether the twin passed is unknown (R2). A signature in another element still compares by text. A signature below the quote, or text that differs from `content` by more than white space, fails.

- timestamp: 2026-11-14
  checked: grep for logger/logging in mail_reply_cleanup.py and mail_outgoing.py; `_SENT_COPY['unproven']`
  found: No logging. The note says "found a message it could not prove to be this reply's own copy, or could not confirm a delete".
  implication: Neither the result nor the daemon log can name the branch. This is why the UAT gap cannot be closed from the existing evidence.

- timestamp: 2026-11-14
  checked: `uv run pytest tests/test_mail_reply_cleanup.py tests/test_mail.py -k "sweep or find_own_draft or is_own or reply_all_waits"`
  found: 171 passed. Includes test_find_own_draft_with_an_unreadable_new_row_proves_nothing, test_find_own_draft_stops_at_the_first_unreadable_row, test_send_then_sweep_with_an_unknown_row_alone_is_unproven, test_send_then_sweep_whose_delete_is_not_confirmed_says_so, test_send_then_sweep_whose_delete_raises_still_reports_the_send.
  implication: The no-leftover `unproven` branches (R1, R2, R3) are deliberate fail-safe rules, and the code behaves as read. The device run hit one of them.

- timestamp: 2026-11-14
  checked: Phase 1.25 SBFL
  found: Skipped. No failing unit test exists; the failure is device-only.
  implication: Localization by code reading and elimination against the device observations.

## Resolution

root_cause: "(a) product: the in-call after-send sweep (`_ReplyFlow.after_send` -> `sweep(sent=True)`, read at about 45 s after the window opened) returned `unproven` through a fail-safe branch that leaves nothing in Drafts. The branch is one of: R1 `_SWEEP_DELETE` did not answer `deleted` (its one `delay 3` re-count, first run on device) although the copy was removed; R2 the delivered reply's Sent or Gmail All Mail copy failed the `_is_own`/`_has_quote` set-aside (the device body shape differs from the 05.2-15 assumption, UAT gap 3); R3 a new row in any account had no readable `.emlx` at +45 s. The sweep records no reason, so the branch cannot be named from the records; (b) procedure, independent: the plan's +45 s Drafts check after the send falls about 0-10 s after the call returns (the call blocks until opened_at + 45 s), and it was taken at 111 s. (b) explains only the missing observation, not the `unproven` value."
fix:
verification:
files_changed: []
