"""Unit tests for the photos adapter — the osxphotos read plane (no real library)."""

from __future__ import annotations

import asyncio
import pathlib
import sys
import threading
import types
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

import macos_apps_mcp.server as srv
from macos_apps_mcp import runtime
from macos_apps_mcp.adapters import photos as photos_mod
from macos_apps_mcp.adapters.photos import MAX_ALBUMS, MAX_PHOTOS, PhotosAdapter
from macos_apps_mcp.contracts import Pointer
from macos_apps_mcp.errors import FullDiskAccessDenied, NativeError, SchemaDrift

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


# --- photos(query): one osxphotos pass, folded, newest first, capped ----------------


def _u(n: int) -> str:
    return f"A1B2C3D4-0000-4000-8000-{n:012d}"


def _search(monkeypatch, query, *photos):
    _fake_seam(monkeypatch, *photos)
    return PhotosAdapter().get_pointers(query)


_FIELDS = [
    ("original_filename", "needle_orig.HEIC"),
    ("filename", "needle_disk.heic"),
    ("title", "a needle title"),
    ("description", "a needle description"),
    ("keywords", ["plain", "needle"]),
    ("place", SimpleNamespace(name="Needle Town")),
    ("persons", ["Needle Person"]),
    ("labels", ["needle label"]),
]


@pytest.mark.parametrize(("field", "value"), _FIELDS, ids=[f for f, _ in _FIELDS])
def test_photos_search_matches_each_searched_field(monkeypatch, field, value):
    hit = _photo(uuid=_u(1), **{field: value})
    miss = _photo(uuid=_u(2), original_filename="IMG_9.HEIC", filename="x.heic")
    assert [p.id for p in _search(monkeypatch, "needle", hit, miss)] == [_u(1)]


@pytest.mark.parametrize(
    ("title", "query"),
    [("Café", "cafe"), ("Andrei\u2019s trip", "andrei's"), ("BEACH", "beach")],
)
def test_photos_search_folds_case_diacritics_and_smart_punctuation(
    monkeypatch, title, query
):
    assert len(_search(monkeypatch, query, _photo(title=title))) == 1


@pytest.mark.parametrize("query", ["", "   ", "\u0301"])
def test_photos_search_empty_query_asks_for_a_search_string(monkeypatch, query):
    _fake_seam(monkeypatch, _photo())
    with pytest.raises(ValueError, match="search string"):
        PhotosAdapter().get_pointers(query)


def test_photos_search_never_matches_trashed_photos(monkeypatch):
    assert _search(monkeypatch, "beach", _photo(intrash=True)) == []


def test_photos_search_is_newest_first_and_ties_break_by_uuid_descending(monkeypatch):
    old = _photo(uuid=_u(1), date=datetime(2025, 1, 1, tzinfo=UTC))
    new = _photo(uuid=_u(2), date=datetime(2026, 1, 1, tzinfo=UTC))
    tie_a = _photo(uuid=_u(3), date=datetime(2026, 1, 1, tzinfo=UTC))
    got = [p.id for p in _search(monkeypatch, "beach", old, new, tie_a)]
    assert got == [_u(3), _u(2), _u(1)]


@pytest.mark.parametrize(
    ("n", "want", "truncated"), [(24, 24, False), (25, 25, True), (26, 25, True)]
)
def test_photos_search_caps_at_max_photos(monkeypatch, n, want, truncated):
    assert MAX_PHOTOS == 25
    _fake_seam(monkeypatch, *[_photo(uuid=_u(i)) for i in range(n)])
    out = PhotosAdapter().read("beach")
    assert len(out["results"]) == want
    assert ("truncated" in out) is truncated


def test_photos_search_pointer_shape_holds_no_location_or_person(monkeypatch):
    p = _photo(
        uuid=_u(7),
        title=None,
        original_filename="IMG_0002.JPG",
        date=datetime(2026, 1, 3, 9, tzinfo=UTC),
        keywords=["beach"],
    )
    (ptr,) = _search(monkeypatch, "beach", p)
    assert isinstance(ptr, Pointer)
    assert ptr.id == _u(7) and ptr.deeplink == ""
    assert ptr.summary == "IMG_0002.JPG · 2026-01-03"
    assert set(ptr.as_dict()) == {"id", "summary", "deeplink"}
    assert "50.85" not in repr(ptr) and "Ana" not in repr(ptr)


def test_photos_search_summary_joins_title_filename_and_date(monkeypatch):
    (ptr,) = _search(monkeypatch, "beach", _photo())
    assert ptr.summary == "Beach · IMG_0001.HEIC · 2026-01-02"


def test_photos_read_is_the_envelope_of_the_same_pointers(monkeypatch):
    _fake_seam(monkeypatch, _photo())
    out = PhotosAdapter().read("beach")
    assert out == {
        "results": [p.as_dict() for p in PhotosAdapter().get_pointers("beach")]
    }


def test_photos_search_runs_on_the_native_worker(monkeypatch):
    db = _fake_seam(monkeypatch, _photo())
    PhotosAdapter().get_pointers("beach")
    assert db.threads and all(t.startswith("mac-native") for t in db.threads)


# --- photo_albums() ----------------------------------------------------------------


def _albums(monkeypatch, *albums):
    _fake_seam(monkeypatch, albums=albums)
    return PhotosAdapter().albums()


def test_photo_albums_pointer_shape_and_nested_folder(monkeypatch):
    out = _albums(
        monkeypatch,
        FakeAlbum(_u(1), "Trips", [1, 2], ["Family", "2026"]),
        FakeAlbum(_u(2), "Top", [1]),
    )
    top, nested = out["results"]  # top level sorts first
    assert nested == {
        "id": _u(1),
        "summary": "Trips (2 photos)",
        "deeplink": "",
        "folder": "Family / 2026",
    }
    assert top["id"] == _u(2) and "folder" not in top
    assert "truncated" not in out


def test_photo_albums_same_title_stays_two_albums(monkeypatch):
    out = _albums(
        monkeypatch,
        FakeAlbum(_u(1), "Trips", [1]),
        FakeAlbum(_u(2), "Trips", [1, 2], ["Family"]),
        FakeAlbum(_u(3), "Trips", []),
    )
    assert sorted(r["id"] for r in out["results"]) == [_u(1), _u(2), _u(3)]


def test_photo_albums_empty_library_is_an_empty_envelope(monkeypatch):
    assert _albums(monkeypatch) == {"results": []}


def test_photo_albums_zero_photos_and_untitled(monkeypatch):
    out = _albums(
        monkeypatch, FakeAlbum(_u(1), "Empty", []), FakeAlbum(_u(2), None, [1])
    )
    assert [r["summary"] for r in out["results"]] == [
        "(untitled album) (1 photos)",
        "Empty (0 photos)",
    ]


def test_photo_albums_order_is_folder_then_title_then_uuid(monkeypatch):
    out = _albums(
        monkeypatch,
        FakeAlbum(_u(5), "b", [], ["Z"]),
        FakeAlbum(_u(4), "B", []),
        FakeAlbum(_u(3), "a", []),
        FakeAlbum(_u(2), "A", []),
        FakeAlbum(_u(1), "a", [], ["A"]),
    )
    assert [r["id"] for r in out["results"]] == [_u(2), _u(3), _u(4), _u(1), _u(5)]


@pytest.mark.parametrize(
    ("n", "want", "truncated"), [(99, 99, False), (100, 100, True), (101, 100, True)]
)
def test_photo_albums_cap(monkeypatch, n, want, truncated):
    assert MAX_ALBUMS == 100
    out = _albums(monkeypatch, *[FakeAlbum(_u(i), f"A{i:03d}", []) for i in range(n)])
    assert len(out["results"]) == want
    assert ("truncated" in out) is truncated


def test_photo_albums_strings_are_clean_one_liners(monkeypatch):
    out = _albums(monkeypatch, FakeAlbum(_u(1), "Tr\x07ips\nx", [], ["Fam\x00ily"]))
    (row,) = out["results"]
    assert row["summary"] == "Trips x (0 photos)" and row["folder"] == "Family"


# --- the adapter holds no AppleScript (D-01, D-07) ------------------------------------


def test_the_photos_adapter_has_no_applescript():
    src = pathlib.Path(photos_mod.__file__).read_text()
    for banned in (
        "run_osascript",
        "tell application",
        "STRIP_FRAMING",
        "parse_framed",
    ):
        assert banned not in src
