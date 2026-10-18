"""Unit tests for the photos adapter — the osxphotos read plane (no real library)."""

from __future__ import annotations

import asyncio
import sys
import threading
import types
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

import macos_apps_mcp.server as srv
from macos_apps_mcp import runtime
from macos_apps_mcp.adapters.photos import PhotosAdapter, _parse
from macos_apps_mcp.contracts import Pointer
from macos_apps_mcp.errors import FullDiskAccessDenied, NativeError, SchemaDrift
from macos_apps_mcp.text import RS, US

# The seam's own self-tests need the REAL function: conftest replaces runtime.photos_db
# for every unit test, so bind it at import (the tests/test_runtime.py convention).
_REAL_PHOTOS_DB = runtime.photos_db

UUID = "A1B2C3D4-0000-4000-8000-000000000001"
OTHER = "A1B2C3D4-0000-4000-8000-000000000002"
INFO_KEYS = {
    "id", "filename", "title", "description", "kind", "edited", "taken", "added",
    "modified", "latitude", "longitude", "place", "persons", "camera_make",
    "camera_model", "lens", "focal_length", "aperture", "shutter_speed", "iso",
    "width", "height",
}  # fmt: skip


def _photo(**over):
    """A PhotoInfo stand-in carrying every attribute the adapter reads."""
    p = SimpleNamespace(
        uuid=UUID,
        original_filename="IMG_0001.HEIC",
        filename="A1B2C3D4_x.heic",
        title="Beach",
        description=None,
        keywords=[],
        labels=[],
        persons=["Ana"],
        place=SimpleNamespace(name="Brussels"),
        date=datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone(timedelta(hours=1))),
        date_added=None,
        date_modified=None,
        latitude=50.85,
        longitude=4.35,
        exif_info=SimpleNamespace(
            camera_make="TestMake",
            camera_model="TestModel",
            lens_model="TestLens",
            focal_length=4.2,
            aperture=2.8,
            shutter_speed=1 / 60,
            iso=100,
        ),
        width=320,
        height=240,
        ismovie=False,
        live_photo=False,
        hasadjustments=False,
        intrash=False,
    )
    for k, v in over.items():
        setattr(p, k, v)
    return p


class FakeAlbum:
    def __init__(self, uuid, title, photos=(), folder_names=()):
        self.uuid, self.title = uuid, title
        self.photos, self.folder_names = list(photos), list(folder_names)


class FakePhotosDB:
    """osxphotos.PhotosDB stand-in; records the thread of every access (D-06)."""

    def __init__(self, photos=(), albums=()):
        self._photos, self._albums = list(photos), list(albums)
        self.threads: list[str] = []

    def _touch(self):
        self.threads.append(threading.current_thread().name)

    def photos(self, **kw):
        self._touch()
        trash = kw.get("intrash", False)
        return [p for p in self._photos if p.intrash == trash]

    def get_photo(self, uuid):  # case-sensitive, and returns trashed photos too
        self._touch()
        return next((p for p in self._photos if p.uuid == uuid), None)

    @property
    def album_info(self):
        self._touch()
        return list(self._albums)


def _call(name, args=None):
    async def go():
        async with Client(srv.mcp) as c:
            return await c.call_tool(name, args or {})

    return asyncio.run(go())


def _fake_seam(monkeypatch, *photos, albums=()):
    db = FakePhotosDB(photos, albums)
    monkeypatch.setattr(runtime, "photos_db", lambda: db)
    return db


def _info(monkeypatch, ident=UUID, **over):
    _fake_seam(monkeypatch, _photo(**over))
    return srv.photo_info(ident)


# --- photo_info: the tracer, end to end through FastMCP ----------------------------


def test_photo_info_end_to_end_returns_the_whitelist(monkeypatch):
    _fake_seam(monkeypatch, _photo())
    got = _call("photo_info", {"id": UUID}).structured_content
    assert set(got) == INFO_KEYS
    assert got["id"] == UUID and got["filename"] == "IMG_0001.HEIC"
    assert got["title"] == "Beach" and got["description"] is None
    assert got["kind"] == "photo" and got["edited"] is False
    assert got["taken"] == "2026-01-02T03:04:05+01:00"
    assert got["added"] is None and got["modified"] is None
    assert (got["latitude"], got["longitude"], got["place"]) == (
        50.85,
        4.35,
        "Brussels",
    )
    assert got["persons"] == ["Ana"]
    assert (got["camera_make"], got["camera_model"]) == ("TestMake", "TestModel")
    assert got["lens"] == "TestLens" and got["focal_length"] == 4.2
    assert got["aperture"] == 2.8 and got["iso"] == 100
    assert (got["width"], got["height"]) == (320, 240)


def test_photo_info_holds_no_bytes_or_path(monkeypatch):
    got = _info(monkeypatch, path="/x/y.heic", path_edited="/x/z.jpeg", thumb=b"\x00")
    assert set(got) == INFO_KEYS
    assert not any(isinstance(v, bytes) for v in got.values())
    assert "/x/" not in repr(got)


@pytest.mark.parametrize("ident", [UUID, UUID.lower(), f" {UUID} ", f"{UUID}/L0/001"])
def test_photo_info_aliases_resolve_to_one_record(monkeypatch, ident):
    # D-04 invariant: the AppleScript form and the lower-case form are input aliases
    assert _info(monkeypatch, ident) == _info(monkeypatch, UUID)
    assert _info(monkeypatch, ident)["id"] == UUID


def test_photo_info_unknown_uuid_names_the_id(monkeypatch):
    _fake_seam(monkeypatch, _photo())
    with pytest.raises(ValueError, match=OTHER):
        PhotosAdapter().info(OTHER)
    with pytest.raises(ToolError, match=OTHER):  # the tool surfaces it as an error
        srv.photo_info(OTHER)


@pytest.mark.parametrize("ident", ["not-a-uuid", "", "../x"])
def test_photo_info_malformed_id_raises_before_the_seam(monkeypatch, ident):
    def boom():
        raise AssertionError("the seam must not be reached for a malformed id")

    monkeypatch.setattr(runtime, "photos_db", boom)
    with pytest.raises(ValueError):
        PhotosAdapter().info(ident)


def test_photo_info_trashed_photo_is_unknown(monkeypatch):
    _fake_seam(monkeypatch, _photo(intrash=True))
    with pytest.raises(ValueError, match="Recently Deleted"):
        PhotosAdapter().info(UUID)


def test_photo_info_strings_are_one_clean_line(monkeypatch):
    got = _info(monkeypatch, title="Beach\x07 day\nnight", description="a\x00b\nc")
    assert got["title"] == "Beach day night"
    assert got["description"] == "ab c"


def test_photo_info_persons_drop_unknown_empty_and_duplicates(monkeypatch):
    got = _info(monkeypatch, persons=["_UNKNOWN_", None, "", "Ana", "Ana"])
    assert got["persons"] == ["Ana"]


def test_photo_info_without_a_place_or_exif_is_none(monkeypatch):
    blank = SimpleNamespace(
        camera_make=None, camera_model=None, lens_model=None,
        focal_length=None, aperture=None, shutter_speed=None, iso=None,
    )  # fmt: skip
    got = _info(monkeypatch, place=None, exif_info=blank, latitude=None, longitude=None)
    assert got["place"] is None and got["camera_make"] is None
    assert got["latitude"] is None and got["iso"] is None


@pytest.mark.parametrize(
    ("over", "kind"),
    [({}, "photo"), ({"ismovie": True}, "video"), ({"live_photo": True}, "live photo")],
)
def test_photo_info_kind(monkeypatch, over, kind):
    assert _info(monkeypatch, **over)["kind"] == kind


def test_photo_info_edited_follows_the_adjustments_flag(monkeypatch):
    assert _info(monkeypatch, hasadjustments=True)["edited"] is True


def test_photo_info_reads_the_library_on_the_native_worker(monkeypatch):
    # D-06: the real run_native, the fake library records every access thread
    db = _fake_seam(monkeypatch, _photo())
    srv.photo_info(UUID)
    assert db.threads and all(t.startswith("mac-native") for t in db.threads)


# --- the photos_db seam itself (D-01, D-06, D-15) ------------------------------------


def _fake_osxphotos(monkeypatch, *, raises=None):
    seen: dict = {}

    class PhotosDB:
        def __init__(self):
            seen["thread"] = threading.current_thread().name
            if raises is not None:
                raise raises

    mod = types.ModuleType("osxphotos")
    mod.PhotosDB = PhotosDB
    mod.__version__ = "9.9.9"
    monkeypatch.setitem(sys.modules, "osxphotos", mod)
    return seen


def test_photos_db_builds_the_library_on_the_native_worker(monkeypatch):
    seen = _fake_osxphotos(monkeypatch)
    db = _REAL_PHOTOS_DB()
    assert type(db).__name__ == "PhotosDB"
    assert seen["thread"].startswith("mac-native")


def test_photos_db_permission_error_is_full_disk_access(monkeypatch):
    _fake_osxphotos(monkeypatch, raises=PermissionError("denied"))
    with pytest.raises(FullDiskAccessDenied, match="Full Disk Access"):
        _REAL_PHOTOS_DB()


def test_photos_db_missing_library_is_a_plain_native_error(monkeypatch):
    _fake_osxphotos(monkeypatch, raises=FileNotFoundError("gone"))
    with pytest.raises(NativeError, match="no Photos library") as e:
        _REAL_PHOTOS_DB()
    assert not isinstance(e.value, FullDiskAccessDenied)


def test_photos_db_any_other_failure_is_schema_drift_naming_the_version(monkeypatch):
    _fake_osxphotos(monkeypatch, raises=KeyError("ZNEWCOLUMN"))
    with pytest.raises(SchemaDrift, match=r"osxphotos 9\.9\.9"):
        _REAL_PHOTOS_DB()


def test_photos_db_without_osxphotos_says_not_installed(monkeypatch):
    monkeypatch.setitem(sys.modules, "osxphotos", None)
    with pytest.raises(NativeError, match="not installed"):
        _REAL_PHOTOS_DB()


def test_parse_id_and_filename():
    ptrs = _parse(f"ABC123{US}IMG_0001.jpg{RS}DEF456{US}{RS}")
    assert len(ptrs) == 2
    assert isinstance(ptrs[0], Pointer)
    assert ptrs[0].id == "ABC123" and ptrs[0].summary == "IMG_0001.jpg"
    assert ptrs[0].deeplink == ""
    assert ptrs[1].summary == "(photo)"


def test_parse_skips_blank():
    assert _parse("\n  \n") == []


def test_parse_sanitizes_control_chars_in_summary():
    # #52 routing: a filename carrying a control char is stripped before it reaches the
    # model (deleting clean_summary from _parse would fail this).
    ptr = _parse(f"ABC123{US}IMG\x07_1.jpg{RS}")[0]
    assert ptr.summary == "IMG_1.jpg" and "\x07" not in ptr.summary


def test_parse_survives_newline_in_filename():
    # US/RS framing (C4-B): a newline in a filename no longer splits the record.
    ptr = _parse(f"ABC123{US}IMG\n_1.jpg{RS}")[0]
    assert ptr.summary == "IMG _1.jpg"


def test_parse_absent_filename_falls_back_to_the_placeholder():
    # AppleScript reports an absent property as the literal "missing value" once it is
    # concatenated into the wire — indistinguishable from a real value, so it defeated
    # the `or "(photo)"` fallback and shipped `missing value` as the summary.
    ptr = _parse(f"ABC123{US}missing value{RS}")[0]
    assert ptr.summary == "(photo)"
