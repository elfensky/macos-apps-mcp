"""Photos adapter — Photos.app via osascript (Automation TCC). Read-only: media search.

Photos.app is scriptable, so NO PhotoKit bundle is needed (the bundle wall was a false
alarm). Uses Photos' own ``search`` command (same matching as the Search field).
``Pointer.id`` = media item id; ``summary`` = filename; ``deeplink`` empty (no per-photo
URL scheme). Pointers, not media. Capped + osascript-timeout-bounded (Photos AppleScript
is slow — a cold search takes ~20s); user input via argv (no injection).
"""

from __future__ import annotations

import re
from datetime import datetime

from .. import runtime
from ..contracts import Pointer
from ..text import (
    STRIP_FRAMING,
    Field,
    blank_if_missing,
    clean_summary,
    parse_framed,
)

MAX_PHOTOS = 25
MAX_ALBUMS = 100

_UUID = re.compile(r"[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}")

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
        for r in parse_framed(
            raw, [Field("id"), Field("name", blank_if_missing)], min_fields=1
        )
    ]


def _uuid(ident: str) -> str:
    """Reduce a Photos id to the osxphotos uuid: upper-case, the old AppleScript
    ``<UUID>/L0/001`` suffix dropped. Raises before any library access (D-04)."""
    uuid = ident.strip().split("/")[0].upper()
    if not _UUID.fullmatch(uuid):
        raise ValueError(
            f"{clean_summary(ident)!r} is not a Photos id — use an id from photos or "
            "photo_albums"
        )
    return uuid


def _live(db, uuid: str):
    """The photo with this uuid; a trashed one counts as unknown (``get_photo`` still
    returns it)."""
    p = db.get_photo(uuid)
    if p is None or p.intrash:
        raise ValueError(f"no photo with id {uuid} (unknown, or in Recently Deleted)")
    return p


def _kind(p) -> str:
    return "video" if p.ismovie else "live photo" if p.live_photo else "photo"


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def _text(v: object) -> str | None:
    return None if v is None else clean_summary(v)


def _info(p) -> dict:
    """The D-05 whitelist for one photo: dates, place, persons, EXIF subset, pixel size.
    No bytes, no thumbnail, no path. Every string is one clean line (untrusted text)."""
    ex = p.exif_info
    persons = dict.fromkeys(
        n for n in (clean_summary(n) for n in p.persons if n) if n and n != "_UNKNOWN_"
    )
    return {
        "id": p.uuid,
        "filename": _text(p.original_filename or p.filename),
        "title": _text(p.title),
        "description": _text(p.description),
        "kind": _kind(p),
        "edited": bool(p.hasadjustments),
        "taken": _iso(p.date),
        "added": _iso(p.date_added),
        "modified": _iso(p.date_modified),
        "latitude": p.latitude,
        "longitude": p.longitude,
        "place": _text(p.place.name) if p.place else None,
        "persons": list(persons),
        "camera_make": _text(ex.camera_make),
        "camera_model": _text(ex.camera_model),
        "lens": _text(ex.lens_model),
        "focal_length": ex.focal_length,
        "aperture": ex.aperture,
        "shutter_speed": ex.shutter_speed,
        "iso": ex.iso,
        "width": p.width,
        "height": p.height,
    }


class PhotosAdapter:
    def get_pointers(self, query: str) -> list[Pointer]:
        """query: a Photos search string (filename, place, etc.)."""
        q = query.strip()
        if not q:
            raise ValueError("photos read needs a search string (got an empty query)")
        return _parse(runtime.run_osascript(_SEARCH, q))[:MAX_PHOTOS]

    def info(self, ident: str) -> dict:
        """Bounded metadata for one photo, by uuid (or an alias ``_uuid`` reduces)."""
        uuid = _uuid(ident)
        return runtime.run_native(lambda: _info(_live(runtime.photos_db(), uuid)))
