# Problem reports and improvement suggestions — design

**Date:** 2026-10-25 · **Tracker:** `elfensky/macos-apps-mcp` · **Status:** approved design, not
yet planned

## Why

The server runs on other people's Macs. When it fails, nobody tells the maintainer. When an agent
works around a missing tool, the lesson is lost at the end of the session. An Apple update can
break part of the server or all of it, and the first sign today is a person who gives up.

The feature has two jobs:

- **Problem reports.** Record failures on the Mac, without help from the agent. When enough real
  failures add up, bring the person one prepared report to send.
- **Feature funnel.** Let agents record "a tool was missing" or "this took 30 calls". These
  suggestions reach the same tracker and drive continuous improvement of the server.

The server's job ends when the person submits the report. The maintainer's tracker and roadmap
take it from there.

## Goals

- Automatic capture, with the least interruption to the person.
- One path for everyone. The maintainer's own Mac takes the same path.
- People without a GitHub account can report.
- It works when the server is fully broken.

## Non-goals

- No automatic upload, telemetry or crash reporting service. Nothing leaves the Mac by itself.
- No private web form or intake service. Mail is the channel for people without GitHub.
- No automatic triage or implementation of suggestions. The tracker and roadmap own that.
- No server-started Claude sessions (`claude -p` from the daemon). That would spend the person's
  tokens out of sight, and it works only where the Claude CLI is installed.

## Anti-goals (a failure even if it works)

- A report that carries private data: a mail subject, a contact name, an account name, a path
  under the home folder, the text of a note or a message.
- A report that an agent sends without the person's own click.
- A new install that nags about setup errors the person must fix.
- 50 issues for one Apple regression.

## Constraints from the codebase

- **Safe writes is the core value** (`.claude/CLAUDE.md`). Filing leaves the Mac. It is safe only
  because a person clicks the final Submit or Send button in a window outside the server.
- **Tiers are gated at registration.** The two new tools are a documented exception: see
  "Tier placement".
- **Tools are thin dispatch.** Logic goes into a new module, not into `server.py`.
- **`call_next` raises on a tool error.** `_guard` turns `NativeError`/`ValueError` into a raised
  `ToolError` ([notices.py:47](../../../macos_apps_mcp/notices.py)). The recorder must catch the
  exception around `call_next`, record, and re-raise. It never changes the result, with one
  exception: the nudge (§7) re-raises a `ToolError` with one sentence added to the message.
- **Every role imports EventKit today.** [`__init__.py`](../../../macos_apps_mcp/__init__.py)
  imports `server`, which imports `doctor`, which imports `EventKit`. Both launch paths
  (`macos_apps_mcp:main` and `-m macos_apps_mcp <role>`) load the package first. So an Apple
  update that breaks PyObjC kills the shim, the daemon, the stdio server and every CLI role
  before [cli.py](../../../macos_apps_mcp/cli.py) runs. **Cut 1 makes the package import lazy**
  (for example a module `__getattr__` for `mcp`), so `shim`, `report` and the start-up recorders
  load no native module. A test asserts that `report` imports no `EventKit`, `Foundation` or
  `objc`.
- **Shared files are home-pinned.** The launchd daemon (no env), a client-spawned shim or stdio
  server, and a Terminal CLI can see different `XDG_STATE_HOME` values. Every feedback file uses
  `Path.home() / ".local/state/macos-apps-mcp/…"`, as `_ALLOW_SEND_FILE` does (#141), not
  `state_dir()`. Tests patch the constants (`tests/conftest.py`), never HOME.
- **The shim exits before the MCP handshake** when the daemon is down
  ([daemon.py:383](../../../macos_apps_mcp/daemon.py), stderr line, exit 2). The agent sees no
  tools and no message. Only the client's MCP log shows the stderr line.
- **The shim answers `initialize` itself.** `FastMCPProxy` returns its own initialize result, so
  daemon-mode clients never see the daemon's `instructions`. `run_shim` sets the same text.
- **`deploy.agent_status()` needs the bundle and PyObjC.** The `report` command checks the launch
  agent with `launchctl print gui/<uid>/ren.lav.macos-apps-mcp` (exit code and state line).

## Design

### 1. The local store

One file, `~/.local/state/macos-apps-mcp/feedback.jsonl` (home-pinned, see Constraints). Lines are
appended only (one `json.dumps` + `\n` per write, file opened in append mode), and the file
rotates past `_AUDIT_MAX_BYTES` with one backup, as `usage_log` does today. Recording never
raises and never fails a tool call.

Each line has `kind`: `problem` or `suggestion`, a `ts`, and `source`: `middleware`, `shim`,
`daemon-start`, `stdio-start`, `report_problem` or `suggest_improvement`.

A `problem` line holds only these fields:

| Field | Value |
|---|---|
| `adapter`, `tool` | names from the registry; unknown names are stored as `"unknown"` |
| `error_kind` | `NativeError.kind`, or `unexpected` for any other exception class (class name kept) |
| `site` | the innermost traceback frames inside `macos_apps_mcp`, as `module:function:line`, max 5 frames. No locals, no values |
| `message` | only for `schema_drift`, `native_timeout` and `output_overflow`: the message after redaction (§4), max 500 characters. Their messages hold table names, column names, numbers and ids. Every other kind stores no message: its messages insert names and field values without quotes, which redaction cannot find (owner decision, 2026-10-25) |
| `fingerprint` | see §5 |
| `server_version` | `doctor.version()` |
| `macos` | `platform.mac_ver()` version and the build (`sw_vers -buildVersion`) |
| `mode` | `stdio` or `daemon` |

No tool arguments. They hold mail subjects, contact names and paths.

A `suggestion` line holds: `task` (what the agent tried, in general terms), `tools_used` (names,
checked against the registry), `missing` (what was missing or slow), `idea` (the proposed fix),
`area` (adapter name or `general`). Each text field max 500 characters, redacted on write.

**Grouping.** The reader folds lines with the same fingerprint into one entry: count, first and
last `ts`, the newest message, the set of macOS builds and server versions. One outage that
writes 2,000 lines reads as one entry with a count of 2,000. The writer stays append-only;
grouping happens on read, as `usage_read` does.

**Reported marks.** A separate small file, `~/.local/state/macos-apps-mcp/feedback_reported.json`,
maps each fingerprint to the `ts` of its newest line when that group was opened for sending. A
group is "open" when it has lines newer than its mark. No line is ever rewritten. A group the
person declines keeps no mark and stays open, but it does not trigger a new nudge (§7). If a
report is lost (the person closes the window), the next line in that group makes it open again.
Duplicates on the tracker are handled by §5.

### 2. What gets recorded

**Automatic, in the middleware.** A new `FeedbackMiddleware`, or a `try/except` around
`call_next` in the existing `AuditMiddleware`. It records one `problem` line when a tool call
raises.

**Reportable kinds.** Only these count toward the nudge, appear in the report and get filed:

- `schema_drift`, `verification_failed`, `native_timeout`, `output_overflow`;
- `unexpected` (any exception that is not a `NativeError` or `ValueError`).

Setup and input errors are **not recorded**: `access_denied`, `automation_denied`,
`full_disk_access_denied`, `app_not_running`, `write_refused`, `ambiguous_target`,
`span_required`, `subtasks_required`, `recurrence_required`, `batch_too_large`, and
`ValueError` (bad input from the agent). Their messages already tell the person or the agent
what to fix. `doctor` covers setup.

The base class `native_error` is **not recorded** either. The code raises it directly in about
36 places, and most are setup or input conditions ("open Mail once", "Reminders store not
found", "body is not available locally", a failing user shortcut). When a base-class raise turns
out to be a real defect, it gets a typed subclass, and that subclass joins the reportable list.

**Automatic, outside the server.**

- **Shim:** `shim_check` appends one `problem` line (`source: shim`, `error_kind:
  daemon_unreachable`) before it exits. Its stderr line gets a second sentence: "Run
  `<command text>` to prepare a problem report." (§3)
- **Start-up, daemon and stdio:** `cli.main` wraps the import and start of the `daemon` role and
  of the no-argument stdio role. An exception there, including an import error, appends one
  `problem` line (`source: daemon-start` or `stdio-start`, `error_kind: unexpected`), then
  re-raises. The recorder itself imports only the standard library and the lazy package.

The shim always records `daemon_unreachable`, and stays lean: it imports nothing new. The
`report` command counts it as reportable only when the launch agent is registered (the person
installed the daemon and it does not run), from the `launchctl print` check (Constraints). If no
agent is registered, the stderr line already says "run `install-agent`".

**By the agent.** Two new tools (§6): `report_problem` and `suggest_improvement`.

### 3. The `report` command

`macos-apps-mcp report` is a new CLI role. A person runs it in Terminal, or any agent with a shell
runs it. It is the main path. The agent nudge (§7) only points to it.

It needs no running daemon and imports no native code. Steps:

1. **Collect** (each source best-effort, with a time limit; a missing or unreadable source is
   listed under "Not collected", never an error):
   - open reportable entries from `feedback.jsonl`, grouped (§1);
   - open suggestions;
   - server version, macOS version and build, CPU architecture, deployment mode;
   - `launchctl print gui/<uid>/ren.lav.macos-apps-mcp`: only the state, last exit code and
     run count lines;
   - the last 60 minutes of the unified log for the server process, at error level and above,
     at most 50 lines;
   - names and dates of crash reports for the server in `~/Library/Logs/DiagnosticReports`
     from the last 7 days. Names and dates only, never their content;
   - the date of the last macOS update (`softwareupdate --history`), so the report can say
     "the first problem came 2 days after the update to 27.1".
2. **Redact** everything (§4).
3. **Cap** each issue so the whole `issues/new` URL stays under 8,000 characters after URL
   encoding. Large groups are cut to their newest entries, with a line that says how many were
   left out.
4. **Show** the full final text in the terminal, and save it as
   `~/.local/state/macos-apps-mcp/reports/report-<ts>.md`.
5. **Ask** "Open this report for sending? [y/N]", once per issue. The prompt reads from the
   terminal (`/dev/tty`). With no terminal and no `--open`, the command stops after step 4 and
   prints the file path.
6. **Open for sending** (§5). The person clicks the last button.
7. **Mark** each opened group as reported (§1).

Flags:

- `--dry-run` stops after step 4.
- `--json` prints the redacted groups as JSON, with their fingerprints, for an agent to read.
- `--open` skips the terminal question in step 5 and opens every issue. An agent uses it after
  the person said yes in chat: a Claude Code shell has no terminal (`/dev/tty` fails). The person
  still clicks Submit or Send in the window that opens.
- `--match <fingerprint>=<issue number>` (repeatable) sends a group to an existing issue that the
  agent judged to be the same. This is for suggestions, whose exact fingerprints rarely match
  across Macs. The repository stays fixed. The browser shows the issue before the person posts.

**The command text** in the shim's stderr line, the nudge and `doctor` matches how this copy
runs:

- inside the .app bundle: the bundle form,
  `/Applications/macos-apps-mcp.app/Contents/MacOS/macos-apps-mcp -E -s -P -m macos_apps_mcp report`;
- a uvx install: `uvx macos-apps-mcp@<running version> report`, pinned so it reads with the same
  code version;
- otherwise: `macos-apps-mcp report`.

`doctor` gets one field: `feedback: {"open_problems": n, "open_suggestions": m, "command":
"<command text>"}`. The dashboard Health page shows the same count and the command.

### 4. Redaction

One function, `redact(text) -> str`, in the new module, applied on write to the store and again
on the final report. It replaces:

- the home folder path with `~`, and the user name anywhere else with `<user>`;
- mail addresses with `<email>`;
- phone numbers with `<phone>`;
- Apple and Mail ids (`x-apple-…`, `message://…`, `<…@…>` Message-IDs, mailbox URLs with their
  account UUID, UUIDs, long hex runs) with `<id>`;
- quoted strings in AppleScript error text (`"…"`) with `"<text>"`. Those quotes hold mailbox,
  note and contact names;
- the computer name (`scutil --get ComputerName`) with `<name>`.

The redaction is code, not a request to the agent. Unit tests use real error messages from
`docs/mail-applescript-facts.md` and from the adapters as fixtures.

### 5. Filing

The command picks the channel by itself:

- **GitHub.** If `gh` is on `PATH` and `gh auth status` exits 0:
  1. Search: `gh issue list --repo elfensky/macos-apps-mcp --state open --search
     "<fingerprint> in:body"`. The repository is fixed in code, never taken from config or
     agent input.
  2. No match: `gh issue create --web --repo elfensky/macos-apps-mcp --title … --body …
     --label bug|enhancement`. The browser opens the filled-in form. The person clicks Submit.
  3. Match: the command copies the report to the clipboard (`pbcopy`), opens the existing issue
     in the browser and prints "Paste the report as a comment". The person posts it.
  4. Problems and suggestions go in separate issues: one per fingerprint group. A report with
     several groups opens them one at a time, each after its own `[y/N]`.
- **Mail.** Otherwise the command opens `mailto:<maintainer address>?subject=…&body=…` with
  `open`, one mail for the whole report. The body is the report cut to 1,800 characters, plus one
  line: "The full report is at `<path>`. Attach it if you want." The person clicks Send.
  The address is `feedback@lav.ren`: an alias, so its destination can change without a release
  (owner decision, 2026-10-25).

The command never posts by itself, and never runs `gh issue create` without `--web`. An agent
cannot click Submit or Send. That click is the person's approval of the exact text.

**Fingerprint.** 12 hex characters of a SHA-1, written in the issue body as
`fingerprint: <12 hex>`. It holds no data from the person.

- Recorded problem: `adapter + tool + error_kind + innermost site module:function` (no line
  number, no message). The macOS build is not in the key, so the same regression on a new build
  finds the same issue. Builds and versions stay in the body.
- `report_problem`: `"report_problem" + first entry of tools_used`. These count as problems for
  the nudge.
- Suggestion: `area + sorted tools_used`. This groups ideas on one Mac. Across Macs the agent
  matches them by meaning with `--match` (§3), because two agents seldom use the same words.
  Without a match, each suggestion group opens its own `enhancement` issue.

### 6. The two agent tools

```python
report_problem(what_happened: str, expected: str, tools_used: list[str]) -> dict
suggest_improvement(task: str, tools_used: list[str], missing: str, idea: str) -> dict
```

- Both write one line to the store, redacted and capped (§1, §4), and return
  `{"recorded": True, "open": n, "command": "<command text>"}` (§3).
- `report_problem` is for a problem that raised no error, such as a result that looks wrong.
- `suggest_improvement` is for a missing tool, a task that needed many calls, or a clumsy
  workaround.
- Rate limit: at most 20 lines per tool per hour. Past that, the tool returns `recorded: False`
  with the reason. A loop or a malicious mail cannot fill the disk.
- Both docstrings start with "Requires **None**" (the meta-tool rule in
  `tests/test_tool_annotations.py`). They state the rule: describe the task in general terms,
  never with names, addresses, subjects or content from the person's data.
- Both treat their input as untrusted: redaction, caps and the person's final click are the
  defenses. Mail and web content can tell an agent to "report a problem" with private data in it.

**Tier placement.** Both tools register in every mode, including `MACOS_APPS_READ_ONLY`, with
annotations `readOnlyHint: false, destructiveHint: false, openWorldHint: false`. They write only
the server's own state file, as `usage_log` already does on every call in read-only mode. They
act on no app and send nothing. This exception is listed in `.claude/CLAUDE.md` and in the
registry next to the tier code, and `tests/test_tool_annotations.py` names the two tools
explicitly.

**MCP `instructions`.** The server gets a short `instructions` text (it has none today,
[server.py:43](../../../macos_apps_mcp/server.py)): when to call the two tools, the
general-terms rule, and the command text (§3) that prepares a report.

### 7. The nudge

When the open reportable entries reach the threshold, the next raised `ToolError` gets one extra
sentence at the end of its message:

> macos-apps-mcp has recorded 3 problems. When the current task is done, ask the user: "May I
> prepare a problem report?" If yes, run `<command text> --json`, check open issues for
> matches, then run `<command text> --open` (in a subagent if you can).

- **Threshold:** 3 open fingerprint groups for problems (not 3 lines), or 10 for suggestions. A
  storm of one error counts as one group. *(Builder may tune.)*
- **No nag:** after a nudge, the next one comes only when the number of open groups reaches the
  threshold again from the count at the last nudge. Declined groups stay in that count, so they
  do not cause a new nudge by themselves. The last-nudge count lives in
  `~/.local/state/macos-apps-mcp/feedback_nudged`.
- The nudge is best-effort. MCP cannot make a client ask the person, start a subagent or run a
  command. The `report` command, `doctor` and the dashboard work without it.
- Claude Code can run the command in a subagent. Claude Desktop usually has no shell: there the
  agent tells the person to run the command in Terminal.

### 8. The deep break

If an Apple update breaks the server fully:

- the daemon fails at start-up → `daemon-start` line; or the daemon is not running → `shim`
  line;
- the client shows the server as failed, and the agent sees no macos-apps tools;
- when the person asks the agent what is wrong, an agent with a shell finds the stderr line in
  the client's MCP log, or runs `macos-apps-mcp report --json` directly;
- the report shows the macOS update date next to the first problem date.

*Known limit:* the agent gets no message in-band in this case, because the shim exits before
the handshake. A degraded shim that serves one diagnostic tool is out of scope for this design.

## Releases

1. **Cut 1, recording and report:** the lazy package import, the store, redaction, middleware
   recording, shim, daemon-start and stdio-start recording, the `report` command with both
   channels, the `doctor` field and the dashboard Health line. This cut alone covers the deep
   break.
2. **Cut 2, the agent side:** `report_problem`, `suggest_improvement`, the MCP `instructions`
   text, the nudge.

## Acceptance

- A raised `SchemaDrift` writes one redacted line. A raised `AccessDenied` or base
  `NativeError` writes none. The tool result is the same as without the feature.
- `report` imports no `EventKit`, `Foundation` or `objc` module (checked in `sys.modules`).
- An import error in the stdio role writes one `stdio-start` line, then the process still fails.
- With `XDG_STATE_HOME` set differently for the writer and for `report`, `report` still reads
  every line (home-pinned paths).
- `report --open` with no terminal opens the issue forms. `--match` sends a group to the given
  issue in the fixed repository.
- Accept group A and decline group B: A gets a mark, B stays open and causes no new nudge.
- A daemon-mode client sees the MCP `instructions` text through the shim.
- 2,000 identical failures read as one group with count 2,000. The file rotates past 5 MB.
- A recording failure (read-only disk) does not change the tool result.
- With the daemon stopped and the agent registered, a shim start writes one `daemon_unreachable`
  line, and the stderr line names `macos-apps-mcp report`.
- `macos-apps-mcp report --dry-run` works with the daemon stopped and EventKit unavailable.
- Redaction fixtures: none of the home path, the user name, mail addresses, Message-IDs,
  mailbox UUIDs or quoted AppleScript names survives in the final report.
- A raised `VerificationFailed` or unexpected exception stores no `message`, only its `site`.
- With `gh` logged in: no match → `gh issue create --web` with the fixed repository; match →
  the existing issue opens and the clipboard holds the report. `gh` is mocked in unit tests.
- Without `gh`: `open mailto:…` with a body of at most 1,800 characters.
- With no terminal, the command stops after it saves the file.
- `report_problem` past 20 calls in an hour returns `recorded: False`.
- Both new tools are present in `MACOS_APPS_READ_ONLY` mode, and the annotation test names them.
- The nudge appears once at the threshold, and again only after the threshold is reached again.
- On device: one real report end to end through each channel, on this Mac and on the iMac
  (Intel, macOS 15).

## Left to the builder

- Module name and layout (for example `macos_apps_mcp/feedback.py`), and the reader's grouping
  code.
- A separate `FeedbackMiddleware` or a `try/except` in `AuditMiddleware`.
- Exact redaction patterns, as long as the fixtures pass.
- The threshold numbers.
- Report text layout and the issue title format.
