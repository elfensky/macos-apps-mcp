"""Photos adapter — Photos.app via osascript (Automation TCC). Read-only: media search.

Photos.app is scriptable, so NO PhotoKit bundle is needed (the bundle wall was a false
alarm). Uses Photos' own ``search`` command (same matching as the Search field).
``Pointer.id`` = media item id; ``summary`` = filename; ``deeplink`` empty (no per-photo
URL scheme). Pointers, not media. Capped + osascript-timeout-bounded (Photos AppleScript
is slow — a cold search takes ~20s); user input via argv (no injection).
"""

from __future__ import annotations

from ..contracts import Pointer
from ..runtime import run_osascript
from ..text import STRIP_FRAMING, Field, clean_summary, parse_framed

MAX_PHOTOS = 25

# with timeout (#56): bound the Apple Events so an orphaned osascript can't pin Photos.
# US/RS-framed (#68); id and filename pass through the shared STRIP_FRAMING handler.
_SEARCH = (
    STRIP_FRAMING
    + """

on run argv
  set q to item 1 of argv
  set us to character id 31
  set rs to character id 30
  set out to ""
  with timeout of 120 seconds
  tell application "Photos"
    repeat with m in (search for q)
      set out to out & (my stripFraming(id of m)) & us & ¬
        (my stripFraming(filename of m)) & rs
    end repeat
  end tell
  end timeout
  return out
end run"""
)


def _parse(raw: str) -> list[Pointer]:
    """Parse the _SEARCH payload: US/RS-framed (media id, filename) records."""
    return [
        Pointer(id=r["id"], summary=clean_summary(r["name"]) or "(photo)", deeplink="")
        for r in parse_framed(raw, [Field("id"), Field("name")], min_fields=1)
    ]


class PhotosAdapter:
    def get_pointers(self, query: str) -> list[Pointer]:
        """query: a Photos search string (filename, place, etc.)."""
        q = query.strip()
        if not q:
            raise ValueError("photos read needs a search string (got an empty query)")
        return _parse(run_osascript(_SEARCH, q))[:MAX_PHOTOS]
