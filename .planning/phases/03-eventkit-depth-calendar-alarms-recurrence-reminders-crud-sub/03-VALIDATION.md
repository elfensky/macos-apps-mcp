---
phase: "3"
slug: "eventkit-depth-calendar-alarms-recurrence-reminders-crud-sub"
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: "2026-10-05"
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 (`>=8,<10`), marker `integration` deselected by default |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths = ["tests"]`, `addopts = "-m 'not integration'"`) |
| **Quick run command** | `uv run pytest tests/test_contracts.py tests/test_eventkit.py tests/test_calendar.py tests/test_reminders.py tests/test_reminders_store.py -q` |
| **Full suite command** | `uv run pytest && uv run ruff check . && uv run ruff format --check .` |
| **Estimated runtime** | ~16 seconds (baseline 1538 passed, 15.27 s) |

---

## Sampling Rate

- **After every task commit:** Run the quick run command for the files the task touches
- **After every plan wave:** Run `uv run pytest && uv run ruff check . && uv run ruff format --check .`
- **Before `/gsd-verify-work`:** Full suite must be green, plus the manual `uv run pytest -m integration` device runs named in RESEARCH.md § Validation Architecture
- **Max feedback latency:** 20 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 3-01-01 | 01 | 1 | TBD | T-3-01 / — | TBD — filled by validate-phase from the PLAN.md tasks | unit | `TBD` | ⬜ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_reminders_store.py` — `tmp_path` sqlite fixture with `Z_PRIMARYKEY` rows (`REMCDHashtag`, `REMCDReminder`), `ZREMCDOBJECT`, `ZREMCDREMINDER` (the `test_notes._make_notestore` pattern) plus a patched store-path function
- [ ] `tests/_fakes.py` — `fake_rule` BY* attributes; a shared fake `calendar()` for event and reminder fakes
- [ ] `tests/test_integration.py` — new device tests; teardown extended for list removal, parent cleanup and the Google prefix sweep to `left=0`
- [ ] `uv add --dev python-dateutil` — RFC 5545 reference for the six-month expansion check, after a human-verify checkpoint (package legitimacy seam flagged `unknown-downloads`)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| All-day and recurring all-day alarm fires on the right day in a non-UTC zone | CAL-02 | Needs a live EventKit store and the device clock; spike 008 harness | `uv run pytest -m integration -k allday_alarm` on the device, with the four reader zones from spike 008 |
| Six-month occurrence expansion matches RFC 5545 on iCloud and Google | CAL-03 | Needs live CalDAV sources; Google rewrites rules after save | `uv run pytest -m integration -k recurrence_expansion`; sweep prefixed titles to `left=0` |
| Parent delete cascades N subtasks; delete gone on device | REM-01 | EventKit cannot create a subtask; the owner indents the fixture by hand in Reminders.app | Owner builds the fixture, then `uv run pytest -m integration -k reminder_delete` |
| `saveCalendar` on the default reminders source | REM-02 | Apple documents no per-source "allows add" flag; probe first | `uv run pytest -m integration -k reminder_list` |
| Reminder BY* round trip | D-11 | Needs a live reminders store | `uv run pytest -m integration -k reminder_byday` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 20s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
