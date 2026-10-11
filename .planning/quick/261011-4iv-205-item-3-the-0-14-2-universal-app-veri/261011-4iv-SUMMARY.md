---
phase: quick-261011-4iv
plan: 01
subsystem: packaging
tags: [intel, universal2, daemon, "#205", device]
status: complete
key-files:
  modified:
    - docs/DAEMON.md
    - CHANGELOG.md
metrics:
  completed: 2026-10-11
actuals:
  tasks: 1
  commits: 1
---

# Quick 261011-4iv: the 0.14.2 universal app on an Intel CPU (item 3)

PR #323, commit `4b404eb`. The device checks ran on 2026-10-11 through the iMac's own Claude
session (Remote Control), after the owner's install on 2026-10-09.

## Results (iMac 2012, OpenCore Legacy Patcher, SIP off, macOS 15)

- launchd `state = running`; app version 0.14.2.
- `doctor()` through the shim: 0.14.2, build `aa27d32`, mcp 1.29.0 / fastmcp 3.4.7, daemon mode,
  agent enabled, no denied surface; Automation surfaces unprobed in a `request=False` call.
  `grant_identities`: the bundle holds Calendar, Reminders, AddressBook and 7 AppleEvents rows.
- Reads through the shim: `mail_overview` 0.3 s (5 accounts, 51 mailboxes), `mail_search` 25 hits,
  `events` today 11, `reminders` ok.
- `codesign --verify --strict`: valid after the daemon ran.
- Found: #317, #318 (doctor), #322 (`uvx` on Intel resolves cryptography 50 with no x86_64 wheel).
  The #302 traceback appeared on every shim call (fixed for 0.14.3).

## Checks

`uv run pytest -q` 1960 passed (exit 0); send-gated 1956 passed, 4 skipped (exit 0); `ruff check`
exit 0; `ruff format --check` exit 0.
