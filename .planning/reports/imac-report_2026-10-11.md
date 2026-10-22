# Device report: Intel iMac, v0.14.3 upgrade and verification (2026-10-11)

Machine: `imac2012`, Intel iMac, macOS 15.7.9, Local-source
Reminders list. Run by Claude Code through the installed daemon
(`deployment.mode: daemon`) with the user at the screen. Worktree under test:
`origin/develop` at `4d6c183`. Issues covered: #297, #302, #307, #317, #318, #322.

Outcome: 0.14.3 is installed and verified as the daemon. 19 checks pass. Two did
not: the subtask half of Part 4 was blocked because Reminders.app would not nest a
reminder on this Local list, and `contacts()` timed out twice in Part 7.

## Results

| Part | Check | Expected | Actual | Result |
|---|---|---|---|---|
| 0 | `uv sync` on origin/develop (4d6c183), no flag | finishes, nothing built | 2.2 s, nothing built; `uv sync --reinstall-package cryptography` shows `~ cryptography==48.0.1`, no "Built" line | PASS |
| 0 | cryptography version in worktree | 48.x | 48.0.1 | PASS |
| 0 | OS / installed app before upgrade | record | 15.7.9 / 0.14.2 | PASS |
| 1 | zip sha256 | `42c8b46c…8408e` | `42c8b46ce31b14d365eb824baeeffd1612f04613871405c3682289f8f9d8408e` | PASS |
| 1 | `spctl -a -vv -t install` | accepted, Notarized Developer ID | accepted, source=Notarized Developer ID | PASS |
| 1 | `doctor()` after `launchctl kickstart -k` | 0.14.3, build `85a3baf 2026-10-11T01:32:20Z`, mcp 1.29.0 / fastmcp 3.4.7, daemon | exactly that; no surface not ok (automation surfaces unprobed until 5a) | PASS |
| 1 | `codesign --verify --strict` on /Applications after tool calls | valid on disk | valid on disk, satisfies its Designated Requirement | PASS |
| 2 | #297 `cp -R` copy keeps its seal | PRE-OK, import ok, valid on disk | PRE-OK; `import ok`; valid on disk + satisfies DR (0.14.2 failed here) | PASS |
| 3 | #302 `scripts/smoke_stream.py` x20 via bundle python | 20 ok, 0 InvalidStateError | 20/20 `stream smoke ok`, 20/20 exit 0, 0 `InvalidStateError` | PASS |
| 4a | `create_reminder` in "Reminders" (Local) | id | id returned, `folder` = list id | PASS |
| 4b | `reminders(due="Reminders")` | R listed, no coverage note | R listed, no `coverage` key | PASS |
| 4c | `complete_reminder(R)` | ok | ok, no WriteRefused | PASS |
| 4d | `delete_reminder` dry-run, then `dry_run=False` | deleted, gone | `would_delete`, then `{"deleted": id}`; list empty | PASS |
| 4e–i | subtask + tag read, parent refusal, `with_subtasks` delete | `parent` + `tags`, refusal naming 1 subtask | BLOCKED: in Reminders.app "Indent Reminder" (⌘]) stayed greyed out for C, also after View > Sort By > Manual, reordering C under P, and drag-onto-P. Not run. P and C deleted | FAIL (manual step impossible on this list) |
| 5a | #317 repro on installed 0.14.3, Photos quit, `doctor(request=True)` | photos `native_error` -1728 | `ok=false`, `native_error`, "osascript failed: 81:94: execution error: Photos got an error: Can’t get every window. (-1728)"; other 11 surfaces ok | PASS (reproduced) |
| 5b | develop probe: `runtime.run_osascript(doctor._PROBE, 'Photos', timeout=120)`, Photos quit | `photos probe ok` | `photos probe ok` in ~12 s, no prompt | PASS |
| 5c | #318 `deploy.grant_report()` | AppleEvents entries carry `target`; denied carry `reason`; prompt-timeout carry a `tccutil reset` remediation | 7 `kTCCServiceAppleEvents` entries for `ren.lav.macos-apps-mcp`, all with `target` (com.apple.AddressBook, MobileSMS, Music, Notes, Photos, Safari, mail), all granted; `reasons: {'user': None, 'system': None}`; 1 entry with `reason` (a third-party `kTCCServiceSystemPolicyAllFiles` client, `granted=False`, `reason='service-policy'`); 0 with `remediation` because no prompt-timeout entry exists on this Mac | PASS (remediation path not exercisable here) |
| 6a | `uvx --no-cache --from macos-apps-mcp==0.14.3`, no flag | record | resolved cryptography 50.0.2 (mcp 1.30.0 → pyjwt[crypto] 2.15.1); built from source via maturin with a temporary Rust install; FAILED after 51 s on openssl-sys | confirms #322 |
| 6b | same with `--no-build-package cryptography` | ok 48.x | `ok 48.0.1`, 16 s | PASS |
| 6c | `uv build --wheel` from develop, `uvx --no-cache --from <wheel>`, no flag | ok 48.x, nothing built | `ok 48.0.1`, 16 s, cryptography downloaded as a wheel, nothing built (develop wheel is still versioned 0.14.3) | PASS |
| 7 | read sweep through the daemon | no errors | 12 of 13 tools ok; `contacts` errored twice | FAIL (contacts only) |
| 8 | cleanup | no test reminders; temp dirs and worktree gone; backup kept | `reminders(due="Reminders")` = `[]`; `/tmp/mam-0143` and `.worktrees/check-full` removed; `~/.local/state/macos-apps-mcp/app-backup/macos-apps-mcp-0.14.2.app` kept | PASS |

## Raw key lines

- `sw_vers -productVersion` 15.7.9; app 0.14.2 before, 0.14.3 after; `hostname -s` imac2012
- doctor: `version 0.14.3`, `build "85a3baf 2026-10-11T01:32:20Z"`, `libs mcp 1.29.0 / fastmcp 3.4.7`, `deployment.mode daemon`, `agent enabled`, `outbound []`
- `doctor(request=True)` summary with Photos quit: `1 of 12 surfaces need attention: photos`
- codesign: `/Applications/macos-apps-mcp.app: valid on disk` and `satisfies its Designated Requirement`; same two lines for the `cp -R` copy after the import
- smoke: `ok=20 invalidstate=0 nonzero_exit=0`
- `uv sync`: 2.179 s total, no build; cryptography 48.0.1 from the pypi registry per `uv.lock`
- 6a error: `× Failed to build cryptography==50.0.2 … Call to maturin.build_wheel failed (exit status: 1) … error: failed to run custom build command for openssl-sys v0.9.117` (no OpenSSL headers; `OPENSSL_DIR` hint). uv's hint: cryptography included because macos-apps-mcp 0.14.3 → mcp 1.30.0 → pyjwt[crypto] 2.15.1
- Part 7 counts: `ping` ok; `now` 2026-10-11T22:51 CEST; `mail_overview` 50 mailboxes over 5 account ids (one shows a bare UUID, no name resolved), at most 33 s wall clock (upper bound, batched with other calls); `mail_search(subject="Re:")` 25 hits, `truncated=true`; `mail_body` about 330 chars; `calendars` 5; `events(today)` 11; `reminder_lists` 1; `reminders(due="today")` 0, no coverage; `notes("the")` 0, `notes("a")` 0, `notes_all` 0, no error; `contacts("an")` error twice; `photos("IMG")` 0, `photos("JPG")` 15; `messages_chats` 30. No Automation prompt appeared at any point.
- contacts error text (both tries, about a minute apart): `The macOS app didn't respond within 30.0s (it may be blocked on a dialog, or the query is too broad). Tell the user to dismiss any stuck prompt, then retry with a narrower query. Do not retry immediately. Contacts (pid 57568, up 03:54, state S, 9.3% CPU) is ACTIVE — likely busy (e.g. an account resync) and usually recovers on its own. Wait a minute, then retry once.` Contacts had been launched by the doctor probe about 4 minutes earlier; at the second failure `ps` showed it at state S with 0.0% CPU, so "busy" looks doubtful.

## Skipped or blocked

- Part 4e–i: nesting is unavailable in Reminders.app on this Local list (Indent greyed out), so the parent/tags read, the subtask refusal and the `with_subtasks` delete of #307 were not exercised. Reminders.app cannot indent a reminder on a Local list, so a Local reminder has no subtasks to read, refuse or delete. The iCloud subtask paths were verified in Phase 3 and #307. Tags on a Local list stay untested. Both test reminders were removed.
- Part 5c: no prompt-timeout TCC entry exists on this Mac, so the `tccutil reset` remediation string was never produced.
- Part 7 notes: three queries returned 0 with no error. A raw count of titled rows in NoteStore.sqlite returned 2, but checking which folder they sit in was blocked by the session's permission classifier, so whether 0 is correct is unverified.
- Part 7 contacts: failed twice, stopped per the run rules.
- Not touched: no Mail writes, no GitHub comments. The main checkout stayed on `develop`.
