# Tester brief

The message to send to 3–5 Mac users before the public launch (see
[PROMOTION.md](PROMOTION.md), week 3). Send it by mail or chat as it stands.

```text
Subject: Could you try a Mac tool for Claude? (about 20 minutes)

Hi —

I built macos-apps-mcp: it lets Claude (Claude Code or Claude Desktop) work with your Mac's own apps —
Mail, Calendar, Reminders, Notes, Messages and a few more. Before I announce it publicly, I'd like 3–5
people to try it and tell me where it breaks or confuses.

Two things to know first:
- The server runs on your Mac and adds no telemetry. But what Claude reads through it (event titles, email
  subjects) goes to Claude like anything else in your chat. Use a test account or calendar if you prefer.
- Every change made through the server is logged on your Mac. Deletes, moves and sends show a preview first; other changes (a new
  reminder, an edited event) happen when Claude makes them. Sending mail is off: the send tools do not exist
  unless you switch them on — please leave them off.

1. Install uv (one time): open Terminal and run
     curl -LsSf https://astral.sh/uv/install.sh | sh
   then open a new Terminal window and run `which uvx`. Keep the path it prints.

2. Add the server
   - Claude Code: claude mcp add macos-apps --scope user -- uvx macos-apps-mcp
   - Claude Desktop: Settings → Developer → Edit Config, put this in the file, save, restart Claude:
     {"mcpServers": {"macos-apps": {"command": "/full/path/from/which/uvx", "args": ["macos-apps-mcp"]}}}
     (Claude Desktop may not find uvx on its own; the path from `which uvx` works.)

3. Ask Claude to "run the doctor tool". It shows what is granted. macOS asks for each permission the
   first time Claude uses that app — allow the ones for the apps you want to test. Mail search
   and moves also need Full Disk Access, which has no prompt: System Settings → Privacy & Security
   → Full Disk Access, add the app that runs Claude (Claude Desktop or your terminal), restart it.

4. Try three things:
   - "What's on my calendar this week, and when am I free on Thursday afternoon?"
   - "Which emails need a reply? Draft a reply to the first one." (It only opens a draft in Mail.)
   - "Find two newsletters in my inbox and move them to a folder called Test. Show me first." Check the
     preview, say "go ahead", then say "undo that move" and confirm its preview too. If your mail is Gmail, skip this one: in Gmail
     every folder is a label, and the server refuses label moves on purpose (Gmail reverts them a few
     minutes later). iCloud and other IMAP accounts work.

5. Tell me what happened — reply to this message, or post at
   https://github.com/elfensky/macos-apps-mcp/discussions. The four things I most want to know:
   - Where did setup stall, and which permission prompt confused you?
   - Did any answer look wrong or miss something?
   - Did anything feel unsafe?
   - Would you keep it installed?

If you report a bug, the doctor output helps a lot — check it before you paste it, because it shows
file paths on your Mac.

Thank you!
Andrei
```
