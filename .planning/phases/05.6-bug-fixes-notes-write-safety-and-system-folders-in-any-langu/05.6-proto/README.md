# 05.6-proto

`notes_probe.py` is a throwaway probe for the Phase 05.6 owner sitting (D-23, plan 05.6-06).
It is not part of the package, and no test imports it.

- It uses the standard library only: `/usr/bin/osascript`, read-only `sqlite3`, `/bin/ps` for Mail's CPU share, and `/usr/bin/osacompile` for `compile`.
- It writes only to a note whose live name is exactly `P056-SCRATCH-<LABEL>`. It has no Mail write.
- Every printed line goes through `say()`: counts, booleans, type names, column values and scratch note ids.

How the sheet calls it:

- Offline: `uv run --no-project python -I notes_probe.py selftest` (no app, no database).
- At the sitting, as the installed bundle, for its Automation and Full Disk Access grants:
  `open -g -n -W --stdout <out> --stderr <err> -a /Applications/macos-apps-mcp.app --args -E -s -P <absolute path>/notes_probe.py <subcommand> …`
- The docstring at the top of the file lists the subcommands and their arguments.
