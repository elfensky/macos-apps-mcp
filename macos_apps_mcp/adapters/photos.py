"""Photos adapter — the Photos library at rest, read through osxphotos (FDA).

No AppleScript and no PhotoKit: osxphotos reads the library database directly, so no
Apple Event reaches Photos.app and the tools need Full Disk Access, not Automation
(Phase 4, D-01, D-07). One id for every tool, the Photos uuid; the old AppleScript form
``<UUID>/L0/001`` is still accepted as input (D-04). Pointers, not media: search and
albums return citable handles, ``info`` a fixed whitelist of metadata (D-05) — never
image bytes, thumbnails or file paths.

Every osxphotos object is touched on the single native worker, and only through
``runtime.photos_db()`` — the one lazy, fail-closed door (D-06).
"""

from __future__ import annotations

import re
from datetime import datetime

from .. import runtime
from ..contracts import Pointer, read_result
from ..text import clean_summary, fold_text

MAX_PHOTOS = 25
MAX_ALBUMS = 100

_UNKNOWN_PERSON = "_UNKNOWN_"  # osxphotos' name for an unnamed face
_UUID = re.compile(r"[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}")


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
    """The photo with this uuid; a trashed one counts as unknown and a hidden one is
    refused (``get_photo`` returns both; D-17)."""
    p = db.get_photo(uuid)
    if p is None or p.intrash:
        raise ValueError(f"no photo with id {uuid} (unknown, or in Recently Deleted)")
    if p.hidden:
        raise ValueError(
            f"photo {uuid} is in the Hidden album, which Photos keeps locked. Unhide "
            "it in Photos to use it here. Do not retry."
        )
    return p


def _kind(p) -> str:
    return "video" if p.ismovie else "live photo" if p.live_photo else "photo"


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def _text(v: object) -> str | None:
    return None if v is None else clean_summary(v)


def _haystack(p) -> list[str]:
    """Every string a search needle may match; None parts and unnamed faces are
    skipped."""
    parts = [
        p.original_filename,
        p.filename,
        p.title,
        p.description,
        *p.keywords,
        p.place.name if p.place else None,
        *(n for n in p.persons if n != _UNKNOWN_PERSON),
        *p.labels,
    ]
    return [str(x) for x in parts if x]


def _photo_pointer(p) -> Pointer:
    taken = p.date.strftime("%Y-%m-%d") if p.date else ""
    parts = [p.title, p.original_filename or p.filename, taken]
    return Pointer(
        id=p.uuid,
        summary=clean_summary(" · ".join(x for x in parts if x)) or "(photo)",
        deeplink="",
    )


def _album_pointer(a) -> Pointer:
    live = sum(not (p.intrash or p.hidden) for p in a.photos)  # D-17
    folder = " / ".join(a.folder_names)
    return Pointer(
        id=a.uuid,
        summary=clean_summary(f"{a.title or '(untitled album)'} ({live} photos)"),
        deeplink="",
        folder=clean_summary(folder) or None,
    )


def _info(p) -> dict:
    """The D-05 whitelist for one photo: dates, place, persons, EXIF subset, pixel size.
    No bytes, no thumbnail, no path. Every string is one clean line (untrusted text)."""
    ex = p.exif_info
    persons = dict.fromkeys(
        n
        for n in (clean_summary(n) for n in p.persons if n)
        if n and n != _UNKNOWN_PERSON
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
        """query: a search string, folded and matched against original filename,
        filename, title, description, keywords, place name, person names and labels.
        Newest first, at most ``MAX_PHOTOS``; Recently Deleted and Hidden photos never
        match (D-17)."""
        needle = fold_text(query).strip()
        if not needle:
            raise ValueError("photos read needs a search string (got an empty query)")

        def work() -> list[Pointer]:
            hits = [
                p
                for p in runtime.photos_db().photos()
                if not p.hidden and any(needle in fold_text(s) for s in _haystack(p))
            ]
            hits.sort(key=lambda p: (p.date, p.uuid), reverse=True)
            return [_photo_pointer(p) for p in hits[:MAX_PHOTOS]]

        return runtime.run_native(work)

    def read(self, query: str) -> dict:
        """``get_pointers`` in the bounded-read envelope: ``{results, truncated?}``."""
        return read_result(self.get_pointers(query), cap=MAX_PHOTOS)

    def albums(self) -> dict:
        """Every non-shared album as a Pointer (id = album uuid, folder path in
        ``folder``), ordered by folder then title; at most ``MAX_ALBUMS``."""

        def work() -> list[Pointer]:
            rows = sorted(
                runtime.photos_db().album_info,
                key=lambda a: (
                    fold_text(" / ".join(a.folder_names)),
                    fold_text(a.title),
                    a.uuid,
                ),
            )
            return [_album_pointer(a) for a in rows[:MAX_ALBUMS]]

        return read_result(runtime.run_native(work), cap=MAX_ALBUMS)

    def info(self, ident: str) -> dict:
        """Bounded metadata for one photo, by uuid (or an alias ``_uuid`` reduces)."""
        uuid = _uuid(ident)
        return runtime.run_native(lambda: _info(_live(runtime.photos_db(), uuid)))
