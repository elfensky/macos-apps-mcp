"""Unit tests for the photos adapter — the osxphotos read plane (no real library)."""

from __future__ import annotations

import asyncio
import errno
import inspect
import os
import pathlib
import shutil
import subprocess
import sys
import threading
import types
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

import macos_apps_mcp.server as srv
import macos_apps_mcp.tiers as tiers
from macos_apps_mcp import registry, runtime
from macos_apps_mcp.adapters import photos as photos_mod
from macos_apps_mcp.adapters.photos import MAX_ALBUMS, MAX_PHOTOS, PhotosAdapter
from macos_apps_mcp.contracts import Pointer
from macos_apps_mcp.errors import (
    FullDiskAccessDenied,
    NativeError,
    SchemaDrift,
    VerificationFailed,
    WriteRefused,
)

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
    """A PhotoInfo stand-in carrying every attribute the adapter reads. ``export`` is a
    recorder (``export_calls``) that writes nothing, like osxphotos on a missing
    file."""
    calls: list = []

    def export(dest, *args, **kw):
        calls.append((dest, args, kw))
        return []

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
        hidden=False,
        path=None,
        path_edited=None,
        export=export,
        export_calls=calls,
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

    def photos(self, **kw):  # like osxphotos: Hidden photos are returned too
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


def test_photo_info_hidden_photo_refuses_with_the_unhide_directive(monkeypatch):
    # D-17: Photos keeps the Hidden album locked; osxphotos would read it anyway
    _fake_seam(monkeypatch, _photo(hidden=True))
    with pytest.raises(ValueError, match="Unhide it in Photos") as e:
        PhotosAdapter().info(UUID)
    assert "Beach" not in str(e.value) and "IMG_0001" not in str(e.value)
    with pytest.raises(ToolError, match="Hidden album"):
        srv.photo_info(UUID)


def test_photo_info_dates_and_shutter_speed_carry_their_values(monkeypatch):
    got = _info(
        monkeypatch,
        date_added=datetime(2026, 2, 3, 4, 5, 6, tzinfo=UTC),
        date_modified=datetime(2026, 3, 4, 5, 6, 7, tzinfo=UTC),
    )
    assert got["added"] == "2026-02-03T04:05:06+00:00"
    assert got["modified"] == "2026-03-04T05:06:07+00:00"
    assert got["shutter_speed"] == 1 / 60


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


def _prefs(monkeypatch, path):
    """Point the Full Disk Access probe at a test file, never the real Photos prefs."""
    monkeypatch.setattr(runtime, "_PHOTOS_PREFS", path, raising=False)


@pytest.mark.skipif(os.getuid() == 0, reason="root bypasses file permissions")
def test_photos_db_tcc_denial_is_full_disk_access(monkeypatch, tmp_path):
    # osxphotos swallows the PermissionError on the Photos prefs and reports
    # FileNotFoundError; the unreadable prefs file tells a TCC denial apart.
    locked = tmp_path / "prefs.plist"
    locked.write_bytes(b"x")
    locked.chmod(0o000)
    _prefs(monkeypatch, locked)
    _fake_osxphotos(monkeypatch, raises=FileNotFoundError("no library path"))
    try:
        with pytest.raises(FullDiskAccessDenied, match="Full Disk Access"):
            _REAL_PHOTOS_DB()
    finally:
        locked.chmod(0o600)


def test_photos_db_permission_error_that_escapes_is_full_disk_access(monkeypatch):
    _fake_osxphotos(monkeypatch, raises=PermissionError("denied"))
    with pytest.raises(FullDiskAccessDenied, match="Full Disk Access"):
        _REAL_PHOTOS_DB()


@pytest.mark.parametrize("readable", [True, False], ids=["prefs-readable", "no-prefs"])
def test_photos_db_missing_library_is_a_plain_native_error(
    monkeypatch, tmp_path, readable
):
    prefs = tmp_path / "prefs.plist"
    if readable:
        prefs.write_bytes(b"x")
    _prefs(monkeypatch, prefs)
    _fake_osxphotos(monkeypatch, raises=FileNotFoundError("gone"))
    with pytest.raises(NativeError, match="no Photos library") as e:
        _REAL_PHOTOS_DB()
    assert not isinstance(e.value, FullDiskAccessDenied)


def test_photos_db_any_other_failure_is_schema_drift_naming_the_version(
    monkeypatch, caplog
):
    # IN-02: the cause's text can name the library path, so only the log carries it
    detail = "/x/Photos Library.photoslibrary/database/Photos.sqlite"
    _fake_osxphotos(monkeypatch, raises=KeyError(detail))
    with pytest.raises(SchemaDrift, match=r"osxphotos 9\.9\.9.*KeyError") as e:
        _REAL_PHOTOS_DB()
    assert detail not in str(e.value)
    assert detail in caplog.text


def test_server_import_leaves_osxphotos_unloaded():
    # 04-04 must-have (W-03): osxphotos loads only inside runtime.photos_db. A fresh
    # interpreter proves it; this one may hold a fake module from another test.
    code = "import sys, macos_apps_mcp.server; sys.exit('osxphotos' in sys.modules)"
    subprocess.run([sys.executable, "-c", code], check=True, timeout=120)


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


def test_photos_search_never_matches_hidden_photos(monkeypatch):
    # D-17: a hidden photo stays behind the Hidden album's lock
    assert _search(monkeypatch, "beach", _photo(hidden=True)) == []


@pytest.mark.parametrize("query", ["unknown", "own", "now", "unk"])
def test_photos_search_skips_the_unknown_face_placeholder(monkeypatch, query):
    # osxphotos names an unnamed face "_UNKNOWN_"; it is not a person to match
    assert _search(monkeypatch, query, _photo(persons=["_UNKNOWN_", None])) == []


_DOC_FIELDS = {
    "original filename": "original_filename",
    "filename": "filename",
    "title": "title",
    "description": "description",
    "keywords": "keywords",
    "place name": "place",
    "person names": "persons",
    "labels": "labels",
}


def test_photos_docstrings_name_the_searched_fields():
    # the docstring is the MCP tool description: it names what _haystack searches
    assert set(_DOC_FIELDS.values()) == {f for f, _ in _FIELDS}
    for doc in (srv.photos.__doc__, PhotosAdapter.get_pointers.__doc__):
        flat = " ".join(doc.split())
        assert all(name in flat for name in _DOC_FIELDS), flat


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
        FakeAlbum(_u(1), "Trips", [_photo(), _photo()], ["Family", "2026"]),
        FakeAlbum(_u(2), "Top", [_photo()]),
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
        FakeAlbum(_u(1), "Trips", [_photo()]),
        FakeAlbum(_u(2), "Trips", [_photo(), _photo()], ["Family"]),
        FakeAlbum(_u(3), "Trips", []),
    )
    assert sorted(r["id"] for r in out["results"]) == [_u(1), _u(2), _u(3)]


def test_photo_albums_empty_library_is_an_empty_envelope(monkeypatch):
    assert _albums(monkeypatch) == {"results": []}


def test_photo_albums_zero_photos_and_untitled(monkeypatch):
    out = _albums(
        monkeypatch, FakeAlbum(_u(1), "Empty", []), FakeAlbum(_u(2), None, [_photo()])
    )
    assert [r["summary"] for r in out["results"]] == [
        "(untitled album) (1 photos)",
        "Empty (0 photos)",
    ]


def test_photo_albums_count_only_live_photos(monkeypatch):
    # AlbumInfo.photos holds trashed and hidden photos too (D-17)
    live, gone, hidden = _photo(), _photo(intrash=True), _photo(hidden=True)
    out = _albums(monkeypatch, FakeAlbum(_u(1), "Trips", [live, gone, hidden]))
    assert out["results"][0]["summary"] == "Trips (1 photos)"


def test_photo_albums_reads_the_library_on_the_native_worker(monkeypatch):
    db = _fake_seam(monkeypatch, albums=[FakeAlbum(_u(1), "Trips", [_photo()])])
    PhotosAdapter().albums()
    assert db.threads and all(t.startswith("mac-native") for t in db.threads)


def test_photo_albums_folder_sort_is_folded(monkeypatch):
    out = _albums(
        monkeypatch,
        FakeAlbum(_u(1), "x", [], ["Zoo"]),
        FakeAlbum(_u(2), "x", [], ["\u00c9t\u00e9"]),
        FakeAlbum(_u(3), "x", [], ["apple"]),
    )
    assert [r["id"] for r in out["results"]] == [_u(3), _u(2), _u(1)]


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


# --- export_photo: the tracer, end to end through FastMCP (PHO-04, D-08..D-11) ------


_write_gate_on_only = pytest.mark.skipif(
    tiers.read_only(), reason="export_photo is absent under MACOS_APPS_READ_ONLY"
)


def _exporting(tmp_path, monkeypatch, *, name="IMG_0001.HEIC", size=1234, **over):
    """A photo whose source file is real and whose fake ``export`` copies it to
    ``dest/filename`` with ``shutil.copy`` like osxphotos 0.77.2 (O_TRUNC, follows a
    symlink at the target); the file root is ``tmp_path/root``."""
    monkeypatch.setenv("MACOS_APPS_FILE_ROOT", str(tmp_path / "root"))
    src = tmp_path / "lib" / name
    src.parent.mkdir(exist_ok=True)
    src.write_bytes(b"x" * size)
    edited = bool(over.get("hasadjustments"))
    over.setdefault("path_edited" if edited else "path", str(src))
    p = _photo(**over)

    def export(dest, *args, **kw):
        p.export_calls.append((dest, args, kw))
        out = pathlib.Path(dest) / kw["filename"]
        shutil.copy(src, out)
        return [str(out)]

    p.export = export
    _fake_seam(monkeypatch, p)
    return p


@_write_gate_on_only
def test_export_photo_end_to_end_writes_the_original_into_the_root(
    tmp_path, monkeypatch
):
    p = _exporting(tmp_path, monkeypatch)
    got = _call("export_photo", {"id": UUID, "dest_dir": "exports"}).structured_content
    out = (tmp_path / "root").resolve() / "exports"
    assert got == {
        "id": UUID,
        "status": "written",
        "path": str(out / "IMG_0001_A1B2C3D4.HEIC"),
        "bytes": 1234,
        "edited": False,
        "dest_dir": str(out),
    }
    assert (out / "IMG_0001_A1B2C3D4.HEIC").stat().st_size == 1234
    assert len(p.export_calls) == 1
    # published by a link out of a private directory, which is gone again
    assert os.listdir(out) == ["IMG_0001_A1B2C3D4.HEIC"]
    assert (out / "IMG_0001_A1B2C3D4.HEIC").stat().st_nlink == 1
    assert pathlib.Path(p.export_calls[0][0]).name.startswith(".macos-apps-mcp-export-")


def test_export_photo_is_an_additive_audited_export_without_dry_run_or_snapshot():
    t = registry.TOOLS["export_photo"]
    assert (t.tier, t.audit_verb, t.snapshot) == ("additive", "export", None)
    assert t.permission == ("Full Disk Access",)
    assert "dry_run" not in inspect.signature(srv.export_photo).parameters


# --- export_photo: every edge (D-08 to D-11) ----------------------------------------

DEST = "exports"


def _out(tmp_path):
    return (tmp_path / "root").resolve() / DEST


def _export(ident=UUID, dest=DEST):
    return PhotosAdapter().export(ident, dest)


NAME = "IMG_0001_A1B2C3D4.HEIC"


def _private_dirs(tmp_path) -> list:
    """The per-call staging directories still in the destination: always none."""
    return list(_out(tmp_path).glob(".macos-apps-mcp-export-*"))


def _racing(p, before):
    """Wrap the fake export so ``before(filename)`` runs first: another writer acting
    after target_path proved the name free, the window osxphotos' own check misses."""
    inner = p.export

    def export(dest, **kw):
        before(kw["filename"])
        return inner(dest, **kw)

    p.export = export


def test_export_photo_writes_the_edited_still_when_there_are_adjustments(
    tmp_path, monkeypatch
):
    p = _exporting(
        tmp_path, monkeypatch, name="IMG_0001_edit.jpeg", hasadjustments=True
    )
    got = _export()
    assert got["edited"] is True and got["status"] == "written"
    assert pathlib.Path(got["path"]).name == "IMG_0001_A1B2C3D4.jpeg"
    assert p.export_calls[0][2]["edited"] is True


@pytest.mark.parametrize("over", [{"path": None}, {"hasadjustments": True}])
def test_export_photo_absent_when_the_source_path_is_unset(tmp_path, monkeypatch, over):
    p = _exporting(tmp_path, monkeypatch, **{"path": None, **over})
    p.path_edited = None
    got = _export()
    assert got.keys() == {"id", "status", "reason"}
    assert got["status"] == "absent" and "iCloud" in got["reason"]
    assert p.export_calls == [] and not _out(tmp_path).exists()


def test_export_photo_absent_when_path_set_but_file_missing(tmp_path, monkeypatch):
    p = _exporting(tmp_path, monkeypatch)
    p.path = str(tmp_path / "lib" / "gone.HEIC")
    got = _export()
    assert got["status"] == "absent" and got["id"] == UUID and got["reason"]
    assert p.export_calls == [] and not _out(tmp_path).exists()


def test_export_photo_absent_when_path_is_a_directory(tmp_path, monkeypatch):
    p = _exporting(tmp_path, monkeypatch)
    p.path = str(tmp_path / "lib")
    assert _export()["status"] == "absent" and p.export_calls == []


def test_export_photo_edit_render_not_written_yet_does_not_blame_icloud(
    tmp_path, monkeypatch
):
    # 04-01: Photos sets hasadjustments first and writes the render up to a minute later
    p = _exporting(tmp_path, monkeypatch)
    p.hasadjustments, p.path_edited = True, None
    got = _export()
    assert got["status"] == "absent" and "rendering" in got["reason"]
    assert got["reason"] != photos_mod._NOT_ON_DISK
    assert p.export_calls == [] and not _out(tmp_path).exists()


def test_export_photo_refuses_a_video_before_any_file_work(tmp_path, monkeypatch):
    p = _exporting(tmp_path, monkeypatch, ismovie=True)
    with pytest.raises(WriteRefused, match="video"):
        _export()
    assert p.export_calls == [] and not _out(tmp_path).exists()


def test_export_photo_live_photo_exports_the_still_and_says_motion_was_skipped(
    tmp_path, monkeypatch
):
    _exporting(tmp_path, monkeypatch, live_photo=True)
    got = _export()
    assert got["status"] == "written" and got["skipped"] == "live photo motion"


def test_export_photo_never_overwrites(tmp_path, monkeypatch):
    p = _exporting(tmp_path, monkeypatch)
    _out(tmp_path).mkdir(parents=True)
    (_out(tmp_path) / "IMG_0001_A1B2C3D4.HEIC").write_bytes(b"mine")
    with pytest.raises(FileExistsError):
        _export()
    assert p.export_calls == []
    assert (_out(tmp_path) / "IMG_0001_A1B2C3D4.HEIC").read_bytes() == b"mine"


@pytest.mark.parametrize("dest", ["/etc", "../../x"])
def test_export_photo_outside_the_root_is_refused_and_creates_nothing(
    tmp_path, monkeypatch, dest
):
    p = _exporting(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="outside"):
        _export(dest=dest)
    assert p.export_calls == [] and not (tmp_path.parent / "x").exists()
    assert not (tmp_path / "root").exists()


def test_export_photo_cap_refuses_before_the_export(tmp_path, monkeypatch):
    p = _exporting(tmp_path, monkeypatch)  # 1,234 bytes
    monkeypatch.setattr(photos_mod, "PHOTO_MAX_BYTES", 1000)
    with pytest.raises(ValueError, match="cap"):
        _export()
    assert p.export_calls == [] and not _out(tmp_path).exists()


def test_export_photo_empty_osxphotos_result_is_a_verification_failure(
    tmp_path, monkeypatch
):
    p = _exporting(tmp_path, monkeypatch)
    p.export = lambda dest, **kw: []
    with pytest.raises(VerificationFailed, match="nothing was exported"):
        _export()
    assert os.listdir(_out(tmp_path)) == []


@pytest.mark.parametrize(
    "where", ["private", "dest-dir", "dest-dir-case-variant", "outside"]
)
def test_export_photo_a_different_written_path_is_a_verification_failure(
    tmp_path, monkeypatch, where
):
    # A name osxphotos writes in this call's private directory goes with it. A path it
    # reports anywhere else is not this call's and stays, also when it is a case
    # variant of another writer's file on APFS (WR-02 compared names case-sensitively).
    p = _exporting(tmp_path, monkeypatch)
    _out(tmp_path).mkdir(parents=True)
    theirs = _out(tmp_path) / "Stray.bin"
    theirs.write_bytes(b"theirs")
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside")
    reported = {
        "dest-dir": theirs,
        "dest-dir-case-variant": theirs.with_name("stray.bin"),
        "outside": outside,
    }

    def export(dest, **kw):
        if where != "private":
            return [str(reported[where])]
        (pathlib.Path(dest) / "other.bin").write_bytes(b"s")
        return [str(pathlib.Path(dest) / "other.bin")]

    p.export = export
    with pytest.raises(VerificationFailed, match="nothing was exported") as e:
        _export()
    msg = str(e.value)
    name = "other.bin" if where == "private" else reported[where].name
    assert name in msg and ("removed" in msg) == (where == "private")
    assert theirs.read_bytes() == b"theirs" and outside.read_bytes() == b"outside"
    assert os.listdir(_out(tmp_path)) == ["Stray.bin"]


def test_export_photo_a_file_another_writer_lands_at_dest_is_never_overwritten(
    tmp_path, monkeypatch
):
    # Phase 4 close re-verification: osxphotos checks dest once, early, then copies
    # with O_TRUNC. A file a parallel session lands in that window survives byte for
    # byte, and the call refuses instead of reporting `written`.
    p = _exporting(tmp_path, monkeypatch)
    dest = _out(tmp_path) / NAME
    _racing(p, lambda name: dest.write_bytes(b"theirs"))
    with pytest.raises(FileExistsError, match="never overwrites"):
        _export()
    assert dest.read_bytes() == b"theirs" and _private_dirs(tmp_path) == []


def test_export_photo_a_symlink_at_dest_is_never_written_through(tmp_path, monkeypatch):
    # shutil.copy follows a symlink at its target: one dropped at dest after the check
    # must not carry the export to a file outside the root
    p = _exporting(tmp_path, monkeypatch)
    victim = tmp_path / "outside.txt"
    victim.write_bytes(b"keep")
    dest = _out(tmp_path) / NAME
    _racing(p, lambda name: dest.symlink_to(victim))
    with pytest.raises(FileExistsError, match="never overwrites"):
        _export()
    assert victim.read_bytes() == b"keep" and dest.is_symlink()
    assert _private_dirs(tmp_path) == []


def _case_insensitive(d: pathlib.Path) -> bool:
    probe = d / "Case-Probe"
    probe.touch()
    try:
        return (d / "case-probe").exists()
    finally:
        probe.unlink()


def test_export_photo_a_case_variant_at_dest_is_never_overwritten(
    tmp_path, monkeypatch
):
    # APFS is case-insensitive by default, so img_0001_a1b2c3d4.heic IS the dest entry
    if not _case_insensitive(tmp_path):
        pytest.skip("the tmp filesystem is case-sensitive")
    p = _exporting(tmp_path, monkeypatch)
    variant = _out(tmp_path) / NAME.lower()
    _racing(p, lambda name: variant.write_bytes(b"theirs"))
    with pytest.raises(FileExistsError, match="never overwrites"):
        _export()
    assert variant.read_bytes() == b"theirs"
    assert os.listdir(_out(tmp_path)) == [NAME.lower()]


class _ExportError(Exception):
    """Stands in for osxphotos' ExportError, whose text names the library file."""


def _causes(lib: str) -> dict:
    return {
        "export-error": _ExportError(
            f"Error copying {lib}/IMG_0001.HEIC: No space left on device"
        ),
        "enospc": OSError(errno.ENOSPC, "No space left on device", f"{lib}/x.HEIC"),
    }


@pytest.mark.parametrize("cause", ["export-error", "enospc"])
@pytest.mark.parametrize("writes", [True, False], ids=["partial-file", "no-file"])
def test_export_photo_a_failing_export_leaves_no_file_and_raises_typed(
    tmp_path, monkeypatch, writes, cause
):
    # #379 review: ENOSPC mid-copy, or osxphotos' post-copy bookkeeping, must not leave
    # a file that looks like a save, nor leak the library path through _guard untyped.
    p = _exporting(tmp_path, monkeypatch)
    lib = str(tmp_path / "lib")
    cause = _causes(lib)[cause]

    def export(dest, **kw):
        if writes:
            (pathlib.Path(dest) / kw["filename"]).write_bytes(b"part")
        raise cause

    p.export = export
    with pytest.raises(NativeError) as e:
        _export()
    msg = str(e.value)
    assert UUID in msg and NAME in msg
    assert msg.endswith("Do not retry.") and lib not in msg
    assert e.value.__cause__ is cause
    assert list(_out(tmp_path).iterdir()) == []


@pytest.mark.parametrize("cause", ["export-error", "enospc"])
def test_export_photo_a_failing_export_never_deletes_another_writer_s_file(
    tmp_path, monkeypatch, cause
):
    # #381's cleanup unlinked dest on any failure: a file another writer landed there
    # after target_path was deleted with it. Only the private directory is cleaned.
    p = _exporting(tmp_path, monkeypatch)
    cause = _causes(str(tmp_path / "lib"))[cause]
    dest = _out(tmp_path) / NAME

    def export(d, **kw):
        dest.write_bytes(b"theirs")
        (pathlib.Path(d) / kw["filename"]).write_bytes(b"part")
        raise cause

    p.export = export
    with pytest.raises(NativeError) as e:
        _export()
    assert e.value.__cause__ is cause
    assert dest.read_bytes() == b"theirs" and _private_dirs(tmp_path) == []


def test_export_photo_source_evicted_after_the_isfile_check_is_absent(
    tmp_path, monkeypatch
):
    # the file passes isfile, then iCloud evicts it before os.stat reads its size
    p = _exporting(tmp_path, monkeypatch)
    gone = str(tmp_path / "lib" / "evicted.HEIC")
    p.path = gone
    real = os.path.isfile
    monkeypatch.setattr(os.path, "isfile", lambda x: x == gone or real(x))
    got = _export()
    assert got == {"id": UUID, "status": "absent", "reason": photos_mod._NOT_ON_DISK}
    assert p.export_calls == []


def test_export_photo_a_zero_byte_result_is_removed_and_reported(tmp_path, monkeypatch):
    _exporting(tmp_path, monkeypatch, size=0)
    with pytest.raises(ValueError, match="0 bytes"):
        _export()
    assert os.listdir(_out(tmp_path)) == []  # never published; the staged file is gone


def test_export_never_passes_a_download_option(tmp_path, monkeypatch):
    p = _exporting(tmp_path, monkeypatch)
    _export()
    ((dest, args, kw),) = p.export_calls
    # osxphotos writes into this call's private directory beside dest, never at dest
    assert pathlib.Path(dest).parent == _out(tmp_path) and args == ()
    assert pathlib.Path(dest).name.startswith(".macos-apps-mcp-export-")
    assert kw["filename"] == "IMG_0001_A1B2C3D4.HEIC"
    assert set(kw) == {"filename", "edited", "overwrite", "increment"}
    assert kw["overwrite"] is False and kw["increment"] is False
    assert not {"use_photos_export", "use_photokit", "download_missing"} & set(kw)


@pytest.mark.parametrize(
    "ident", ["not-a-uuid", "", "A1B2C3D4-0000-4000-8000-0000000000FF"]
)
def test_export_photo_unknown_and_malformed_ids_raise(tmp_path, monkeypatch, ident):
    p = _exporting(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        _export(ident)
    assert p.export_calls == []


def test_export_photo_trashed_id_raises(tmp_path, monkeypatch):
    p = _exporting(tmp_path, monkeypatch, intrash=True)
    with pytest.raises(ValueError, match="Recently Deleted"):
        _export()
    assert p.export_calls == []


def test_export_photo_hidden_id_is_refused_with_the_unhide_directive(
    tmp_path, monkeypatch
):
    p = _exporting(tmp_path, monkeypatch, hidden=True)
    with pytest.raises(ValueError, match="Unhide it in Photos"):
        _export()
    assert p.export_calls == [] and not _out(tmp_path).exists()


def test_export_photo_accepts_the_old_applescript_id(tmp_path, monkeypatch):
    _exporting(tmp_path, monkeypatch)
    assert _export(f"{UUID}/L0/001")["id"] == UUID


def test_export_photo_hostile_original_filename_stays_inside_the_destination(
    tmp_path, monkeypatch
):
    _exporting(tmp_path, monkeypatch, original_filename="../../.ssh/x.HEIC")
    got = pathlib.Path(_export()["path"])
    assert got.parent == _out(tmp_path) and got.name.endswith("_A1B2C3D4.HEIC")
    assert not (tmp_path / ".ssh").exists()


@pytest.mark.parametrize("stem", ["a" * 295, "\u00e9" * 148], ids=["ascii", "2-byte"])
def test_export_photo_a_long_filename_keeps_the_id_suffix(tmp_path, monkeypatch, stem):
    # IN-03: the stem is cut, never the _<id8> that keeps two photos apart
    name = stem + ".HEIC"
    assert len(name.encode()) >= 300
    _exporting(tmp_path, monkeypatch, original_filename=name)
    got = pathlib.Path(_export()["path"]).name
    assert got.endswith("_A1B2C3D4.HEIC") and len(got.encode()) <= 200


def test_export_photo_runs_on_the_native_worker(tmp_path, monkeypatch):
    p = _exporting(tmp_path, monkeypatch)
    inner, threads = p.export, []

    def export(dest, **kw):
        threads.append(threading.current_thread().name)
        return inner(dest, **kw)

    p.export = export
    _export()
    assert threads and all(t.startswith("mac-native") for t in threads)
