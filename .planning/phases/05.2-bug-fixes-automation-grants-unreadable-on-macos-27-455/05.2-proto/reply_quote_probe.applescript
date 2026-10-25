-- Phase 05.2 / FIX-16 (#348) device probe. DRAFT-ONLY: this script never calls `send`.
-- STATUS: WRITTEN, NOT RUN. Research made no Mail write. First step of the sitting:
--   osacompile -o /dev/null reply_quote_probe.applescript     (syntax only, no run)
--
-- Question: can the reply text go AHEAD of Mail's native quote without a read-and-rewrite
-- of the body?  Facts that bind this probe (docs/mail-applescript-facts.md):
--   * `content` of an outgoing message reads empty (section 4), so no read is possible.
--   * Mail autosaves ANY outgoing message into Drafts about 10-15 s later (section 2/3):
--     wait 25 s, then read the stored draft's `source`.
--   * `delete` on a VISIBLE outgoing message works; on a windowless one it can silently
--     no-op (section 3c). So every mode here uses a visible reply unless WINDOW is "no".
--   * Run it as raw osascript, not through runtime: run_osascript caps a script at 30 s.
--
-- Run (Mail watchdog running: `launchctl list | grep mail-watchdog`; if Mail freezes,
-- run ~/mail-watchdog/capture.sh BEFORE force-quitting):
--   osascript reply_quote_probe.applescript MODE MESSAGE-ID WINDOW DELAY OUT.eml
--   MODE    P0 control, no write | P1a insert at beginning (property form)
--           P1b insert `at beginning of content of r` | P2 insert before first paragraph
--           P3 control, today's behaviour: set content | P5 insert at END (position check)
--   WINDOW  yes (mail_reply path) | no (reply_all path; leaves a windowless zombie)
--   DELAY   seconds between `reply` and the write: 0 and 3 (is there a race with the
--           native quote?)
--   OUT.eml where the stored draft's raw source is written; then:
--           uv run python -I inspect_draft.py OUT.eml PROBE-MODE "<last words>"
-- Use ONLY a message from an owned address (andrei@lav.ren). Never the Grandma or Mama
-- accounts (spike-findings: never probe targets).

on run argv
	set theMode to item 1 of argv
	set mid to item 2 of argv
	set withWindow to ((item 3 of argv) is "yes")
	set pause to (item 4 of argv) as integer
	set outPath to item 5 of argv
	set marker to "PROBE-" & theMode
	set report to "mode=" & theMode & " window=" & withWindow & " delay=" & pause
	with timeout of 180 seconds
		tell application "Mail"
			set dm to drafts mailbox
			set baseIds to {}
			repeat with x in (messages of dm)
				set baseIds to baseIds & {(id of x)}
			end repeat
			set m to item 1 of (messages of inbox whose message id is mid)
			set r to reply m opening window withWindow
			delay pause
			try
				set report to report & " content_len_before=" & (length of (content of r))
			on error e number n
				set report to report & " content_len_before=ERR" & n
			end try
			try
				if theMode is "P1a" then
					tell content of r to make new paragraph at beginning with data (marker & return)
				else if theMode is "P1b" then
					make new paragraph at beginning of content of r with data (marker & return)
				else if theMode is "P2" then
					make new paragraph at before first paragraph of content of r with data (marker & return)
				else if theMode is "P3" then
					set content of r to marker
				else if theMode is "P5" then
					make new paragraph at end of content of r with data (marker & return)
				end if
				set report to report & " write=ok"
			on error e number n
				set report to report & " write=ERR" & n & " " & e
			end try
			-- Mail's autosave lands ~15 s late: 25 s, never 3 s (facts section 2).
			delay 25
			set found to missing value
			repeat with x in (messages of dm)
				if (id of x) is not in baseIds then
					set found to contents of x
					exit repeat
				end if
			end repeat
			if found is missing value then
				set report to report & " draft=NOT-AUTOSAVED"
			else
				set src to source of found
				set fh to open for access (POSIX file outPath) with write permission
				set eof of fh to 0
				write src to fh as «class utf8»
				close access fh
				set report to report & " draft=saved to " & outPath & " (" & (length of src) & " chars)"
				try
					delete found
				end try
			end if
			try
				delete r
			on error e number n
				set report to report & " delete_r_error=" & n
			end try
			try
				set s to subject of r
				set report to report & " r_after_delete=ALIVE(silent no-op)"
			on error e number n
				set report to report & " r_after_delete=dead" & n
			end try
		end tell
	end timeout
	return report
end run
-- After the run: the compose window may stay open (facts section 5e). Close it with
-- Cmd-W and choose Delete / Don't Save. Count Drafts at +20 s: it must equal the baseline.
-- `r_after_delete=dead-1728` is the proof that the outgoing message is really gone (facts section 3).
