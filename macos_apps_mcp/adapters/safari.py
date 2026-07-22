"""Safari adapter — Safari.app via osascript (Automation TCC). List tabs + open a URL.

Lists every open tab across windows. ``Pointer.id`` and ``deeplink`` are the tab URL;
``summary`` is the page title. ``open_url`` opens a URL in a new tab. User input goes
via argv (no injection). Pointers, not page content.
"""

from __future__ import annotations

from ..contracts import Pointer
from ..runtime import run_osascript
from ..text import clean_summary

# with timeout (#56): bound the Apple Events so an orphaned osascript can't pin the app.
_TABS = """with timeout of 120 seconds
tell application "Safari"
  set out to ""
  repeat with w in windows
    repeat with t in tabs of w
      set out to out & (URL of t) & tab & (name of t) & linefeed
    end repeat
  end repeat
  return out
end tell
end timeout"""

# A new tab in the front window, or a fresh document if Safari has no window open.
_OPEN = """on run argv
  set u to item 1 of argv
  with timeout of 120 seconds
  tell application "Safari"
    if (count of windows) is 0 then
      make new document with properties {URL:u}
    else
      tell front window to make new tab with properties {URL:u}
    end if
  end tell
  end timeout
  return u
end run"""


def _parse(raw: str) -> list[Pointer]:
    out = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        url, _, name = line.partition("\t")
        out.append(Pointer(id=url, summary=clean_summary(name) or url, deeplink=url))
    return out


def _normalize_url(url: str) -> str:
    """Trim, default a bare host to https://, and refuse non-web hierarchical schemes.

    An explicit ``scheme://`` must be http/https — this stops safari_open from being
    steered (e.g. by prompt injection) into ``file://`` (local files) or app schemes
    (``shortcuts://`` …). Schemeless input (a bare host or ``host:port``) gets https://.
    """
    u = url.strip()
    if not u:
        raise ValueError("safari_open needs a URL (got an empty string)")
    if "://" in u:
        scheme = u.split("://", 1)[0].lower()
        if scheme not in ("http", "https"):
            raise ValueError(
                f"safari_open only opens http/https URLs; got {scheme!r}://"
            )
    else:
        u = "https://" + u
    return u


class SafariAdapter:
    def get_tabs(self) -> list[Pointer]:
        """All open Safari tabs (id/deeplink = URL, summary = page title)."""
        return _parse(run_osascript(_TABS))

    def open_url(self, url: str) -> Pointer:
        """Open ``url`` in a new Safari tab (a new window if none is open)."""
        u = _normalize_url(url)
        run_osascript(_OPEN, u)
        return Pointer(id=u, summary=clean_summary(f"opened {u}"), deeplink=u)
