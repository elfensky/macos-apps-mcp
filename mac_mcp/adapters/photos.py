"""Photos adapter — Photos.app via osascript (Automation TCC). Read-only: media search.

Photos.app is scriptable, so NO PhotoKit bundle is needed (the bundle wall was a false
alarm). Uses Photos' own ``search`` command (same matching as the Search field).
``Pointer.id`` = media item id; ``summary`` = filename; ``deeplink`` empty (no per-photo
URL scheme). Pointers, not media. Capped + osascript-timeout-bounded (Photos AppleScript
is slow — a cold search takes ~20s); user input via argv (no injection).
"""

from __future__ import annotations

from ..contracts import Pointer
from ..runtime import clean_summary, run_osascript

MAX_PHOTOS = 25

_SEARCH = """on run argv
  set q to item 1 of argv
  set out to ""
  tell application "Photos"
    repeat with m in (search for q)
      set out to out & (id of m) & tab & (filename of m) & linefeed
    end repeat
  end tell
  return out
end run"""


def _parse(raw: str) -> list[Pointer]:
    out = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        ident, _, filename = line.partition("\t")
        out.append(
            Pointer(id=ident, summary=clean_summary(filename) or "(photo)", deeplink="")
        )
    return out


class PhotosAdapter:
    def get_pointers(self, query: str) -> list[Pointer]:
        """query: a Photos search string (filename, place, etc.)."""
        q = query.strip()
        if not q:
            raise ValueError("photos read needs a search string (got an empty query)")
        return _parse(run_osascript(_SEARCH, q))[:MAX_PHOTOS]
