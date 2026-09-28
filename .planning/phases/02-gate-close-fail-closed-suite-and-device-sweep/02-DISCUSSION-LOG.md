# Phase 2: Gate Close — Fail-Closed Suite and Device Sweep - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-28
**Phase:** 02-gate-close-fail-closed-suite-and-device-sweep
**Areas discussed:** Read-only test repair, Device sweep safety, Sweep failure policy, Release at phase close

---

## Read-only test repair

| Option | Description | Selected |
|--------|-------------|----------|
| Split by intent | The 4 fact tests read `registry.TOOLS` and run in both modes. The 8 call tests skip in read-only mode, with one named marker and a reason. No copied wrapping code. | ✓ |
| Skip all 12 | The smallest diff. The 4 fact tests do not run in read-only mode. | |
| Run all 12 in both modes | The tests wrap the plain function with `_guard` themselves. More code, and they prove their own copy of the wrapping, not the server's. | |

**User's choice:** Split by intent.
**Notes:** The owner asked for the trade-offs with diagrams and an eli14 explanation before choosing.
The explanation showed that in read-only mode a gated-off tool keeps its record, and the decorator
returns the plain function without `_guard` (`server.py:180-182`). The "both modes" option would
therefore test a wrapping that no read-only client can reach, and it could stay green while the
server's real wrapping changes.

| Option | Description | Selected |
|--------|-------------|----------|
| Add a CI step | `MACOS_APPS_READ_ONLY=1 uv run pytest` in `ci.yml`, about 15 s. | ✓ |
| Local check only | Add the command to the CLAUDE.md verification list. | |

**User's choice:** Add a CI step.

---

## Device sweep safety

| Option | Description | Selected |
|--------|-------------|----------|
| Run as written | Move 2 real INBOX messages (move → undo, cross-account move, flag flip), with the watchdog on and the owner present. | |
| Seed test mail first | 2 marker mails sent to self. The fixture picks only those, never real mail. | ✓ |
| Reads + dry runs only | Leave the Mail write tests out of the sweep. | |

**User's choice:** Seed test mail first.

| Option | Description | Selected |
|--------|-------------|----------|
| Seed once, reuse | One plan step sends 2 marker mails. They stay in the INBOX, and each run reuses them. The fixture fails and names the seed command when they are missing. | ✓ |
| Fixture seeds each run | The fixture sends new mails and waits for them when fewer than 2 are found. | |

**User's choice:** Seed once, reuse.
**Notes:** Locked with the choice: the fixture never falls back to real INBOX messages.

| Option | Description | Selected |
|--------|-------------|----------|
| Include it | Run with `MACOS_APPS_ALLOW_SEND=mail`, so the real send to `andrei@lav.ren` runs. | ✓ |
| Leave it skipped | Report it as 1 skip. Outbound is proven by dry runs only. | |

**User's choice:** Include it.

| Option | Description | Selected |
|--------|-------------|----------|
| 0 failed, skips listed | 0 failures and 0 errors. Each skip is named with its reason in VERIFICATION.md. | ✓ |
| 0 failed, 0 skipped | Create the missing data until nothing skips. | |

**User's choice:** 0 failed, skips listed.

---

## Sweep failure policy

| Option | Description | Selected |
|--------|-------------|----------|
| Small here, big filed | A fix that fits one PR, touches one adapter and is not a Mail write path lands here with a unit test. Other bugs get an issue for the owning phase and a strict xfail. | ✓ |
| Fix everything here | The gate closes only when each test passes on its merits. | |
| File everything | Phase 2 fixes no adapter code. Each failure gets an issue and a strict xfail. | |

**User's choice:** Small here, big filed.

| Option | Description | Selected |
|--------|-------------|----------|
| Only with a device record | An assertion changes only when the new behaviour is observed on device and recorded (mail-applescript-facts.md or the PR). | ✓ |
| My judgement per case | Claude decides and explains it in the PR. | |

**User's choice:** Only with a device record.

---

## Release at phase close

| Option | Description | Selected |
|--------|-------------|----------|
| Last plan, you approve | Cut v0.12.0 after the sweep is green. The owner approves before the push. Build, notarize, install, and prove `doctor().version`. | ✓ |
| Separate, your call | Phase 2 ends on a dev-build daemon. The owner cuts the release later, for example after 02.1. | |

**User's choice:** Last plan, you approve.

---

## Claude's Discretion

- The GATE-11 fix: route `doctor._process_name` through `runtime.tracked_run`, and extend the
  native-seam tripwire to catch a direct `subprocess` call.
- The GATE-11 proof method (a `Popen` spy plugin that counts `ps`/`pgrep` spawns per test).
- The plan order: unit PRs → seed → dev-build daemon → sweep → fixes/xfails → release.
- Music, volume and Safari side effects run as written.
- The marker subject, the seed command and the choice of account.

## Deferred Ideas

- The daemon code-seal fix (`scripts/build_app.sh`, a STATE.md pending todo). The discussion did not
  decide whether it goes into the v0.12.0 build.
