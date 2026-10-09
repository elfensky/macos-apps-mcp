---
phase: quick-261009-tqc
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - docs/mail-applescript-facts.md
autonomous: true
requirements: [ISSUE-291]
must_haves:
  truths:
    - "facts §5f records the 2026-10-09 rerun of #291 T1/T3 on a healthy Mail (health reads 1.35/0.65/1.62/1.56 s): T3 read ok at +20 s and the label copy was back at +2 min, held at +5 and +15 min"
    - "facts §5f replaces 'Not known … A rerun on a healthy Mail decides it' with the decision: not a slow-Mail drop; the delete never takes effect on Gmail; Mail's IMAP commands not measured"
    - "facts §5f records mail_reply, reply_all and forward_mail run once each from a Gmail label folder, judged on the delivered messages (headers and bodies), sends to andrei@lav.ren only"
    - "§2 and the §3 -1728 row name both the slow and the healthy run"
  artifacts:
    - path: "docs/mail-applescript-facts.md"
      contains: "2026-10-09"
---

# Quick 261009-tqc: facts §5f — the #291 label undo on a healthy Mail, and reply/forward from a label

Executed inline by the orchestrator: the evidence comes from this session's own device run
(observer logs in the session scratchpad, `291/obs.log`); a separate executor would only copy it.

<lanes>
- Code lane: `/Users/andrei/Developer/macos-apps-mcp/.worktrees/facts-5f`, branch
  `docs/291-label-device-results` from `origin/develop` (`fdfd5ac`).
- Records lane: this directory (PLAN and SUMMARY, committed by the records PR).
</lanes>

<tasks>
<task type="auto">
  <name>Task 1: record both device results in facts §2, §3 and §5f</name>
  <files>docs/mail-applescript-facts.md</files>
  <action>Edit §2 (Gmail timing sentence), the §3 `-1728` row, the §5f "Outcome" bullet (replace the open question with the decision), add a "Device-verified 2026-10-09 (#291 T3 rerun)" block with a T1/T3 table, and replace the "Not run: mail_reply …" bullet in "the other Mail tools on a label folder" with the three results. Simplified Technical English; facts only; no family account, no real subject.</action>
  <verify><automated>grep -q "2026-10-09" docs/mail-applescript-facts.md && ! grep -q "A rerun on a healthy Mail decides it" docs/mail-applescript-facts.md && uv run pytest -q && uv run ruff check . && uv run ruff format --check .</automated></verify>
  <done>One commit, subject ending (#291), trailer present; only the facts doc changed.</done>
</task>
</tasks>
