"""Messages adapter — Messages.app via osascript (Automation TCC). Read-only: chat list.

Lists conversations (chats). ``Pointer.id`` = chat guid; ``summary`` = chat name (group
chats show their name; 1:1 chats may be empty → a placeholder); ``deeplink`` empty. NO
message content is read — that needs Full Disk Access + the private ``chat.db``. Sending
is not implemented: the AppleScript send handler is regressed since macOS 11.
Capped; Messages scripting can be slow.
"""

from __future__ import annotations

from ..contracts import Pointer
from ..runtime import clean_summary, run_osascript

MAX_CHATS = 30

# with timeout (#56): bound the Apple Events so an orphaned osascript can't pin the app.
_CHATS = """with timeout of 120 seconds
tell application "Messages"
  set out to ""
  repeat with c in chats
    set out to out & (id of c) & tab & (name of c) & linefeed
  end repeat
  return out
end tell
end timeout"""


def _parse(raw: str) -> list[Pointer]:
    out = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        guid, _, name = line.partition("\t")
        summary = clean_summary(name) or "(chat)"
        out.append(Pointer(id=guid, summary=summary, deeplink=""))
    return out


class MessagesAdapter:
    def get_chats(self) -> list[Pointer]:
        """List Messages conversations (id + name). No message content."""
        return _parse(run_osascript(_CHATS))[:MAX_CHATS]
