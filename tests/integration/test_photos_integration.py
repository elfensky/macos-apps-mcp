"""Real Photos library tests (PHO-04, #96) — on-device only, NEVER CI.

Run by hand:
`uv run pytest -m integration tests/integration/test_photos_integration.py`.
The test host needs Full Disk Access (osxphotos reads the library at rest); importing a
new test photo also needs Automation for Photos.

The module reuses a test photo already in the album `macos-apps-mcp-test` and imports
one only when none exists, so the album never gains more than one photo from this test,
however often it runs. Photos AppleScript cannot delete media items, so the owner
deletes the photo (and empties Recently Deleted) — see the printed `REUSED TEST PHOTO` /
`NEW TEST PHOTO` line. The export directory is removed at once.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from macos_apps_mcp import runtime
from macos_apps_mcp.adapters.photos import PhotosAdapter
from macos_apps_mcp.errors import WriteRefused

pytestmark = pytest.mark.integration

ALBUM = "macos-apps-mcp-test"
PREFIX = "macos-apps-mcp-test-"

# Argv-driven, so no value is interpolated into the script. Photos cannot add a photo to
# an album that does not exist, hence the make-if-absent first.
_IMPORT = """
on run argv
    set theFile to item 1 of argv
    set albumName to item 2 of argv
    with timeout of 120 seconds
        tell application "Photos"
            set theAlbum to missing value
            try
                set theAlbum to album albumName
            end try
            if theAlbum is missing value then
                set theAlbum to make new album named albumName
            end if
            set theList to {POSIX file theFile}
            set imported to import theList into theAlbum skip check duplicates true
            return id of item 1 of imported
        end tell
    end timeout
end run
"""


def _write_jpeg(out: Path) -> None:
    """A 320x240 JPEG with the EXIF, date and GPS the 04-01 test photos carry."""
    from Foundation import NSURL
    from Quartz import (
        CGBitmapContextCreate,
        CGBitmapContextCreateImage,
        CGColorSpaceCreateDeviceRGB,
        CGContextFillRect,
        CGContextSetRGBFillColor,
        CGImageDestinationAddImage,
        CGImageDestinationCreateWithURL,
        CGImageDestinationFinalize,
        CGRectMake,
        kCGImageAlphaNoneSkipLast,
        kCGImagePropertyExifDateTimeOriginal,
        kCGImagePropertyExifDictionary,
        kCGImagePropertyExifExposureTime,
        kCGImagePropertyExifFNumber,
        kCGImagePropertyExifFocalLength,
        kCGImagePropertyExifISOSpeedRatings,
        kCGImagePropertyExifLensModel,
        kCGImagePropertyGPSDictionary,
        kCGImagePropertyGPSLatitude,
        kCGImagePropertyGPSLatitudeRef,
        kCGImagePropertyGPSLongitude,
        kCGImagePropertyGPSLongitudeRef,
        kCGImagePropertyTIFFDictionary,
        kCGImagePropertyTIFFMake,
        kCGImagePropertyTIFFModel,
    )

    ctx = CGBitmapContextCreate(
        None, 320, 240, 8, 0, CGColorSpaceCreateDeviceRGB(), kCGImageAlphaNoneSkipLast
    )
    CGContextSetRGBFillColor(ctx, 0.9, 0.2, 0.2, 1)
    CGContextFillRect(ctx, CGRectMake(0, 0, 160, 120))
    CGContextSetRGBFillColor(ctx, 0.2, 0.3, 0.9, 1)
    CGContextFillRect(ctx, CGRectMake(160, 120, 160, 120))
    dest = CGImageDestinationCreateWithURL(
        NSURL.fileURLWithPath_(str(out)), "public.jpeg", 1, None
    )
    props = {
        kCGImagePropertyTIFFDictionary: {
            kCGImagePropertyTIFFMake: "TestMake",
            kCGImagePropertyTIFFModel: "TestModel",
        },
        kCGImagePropertyExifDictionary: {
            kCGImagePropertyExifDateTimeOriginal: "2026:01:02 03:04:05",
            kCGImagePropertyExifISOSpeedRatings: [100],
            kCGImagePropertyExifFNumber: 2.8,
            kCGImagePropertyExifFocalLength: 4.2,
            kCGImagePropertyExifExposureTime: 1 / 60,
            kCGImagePropertyExifLensModel: "TestLens",
        },
        kCGImagePropertyGPSDictionary: {
            kCGImagePropertyGPSLatitude: 50.8503,
            kCGImagePropertyGPSLatitudeRef: "N",
            kCGImagePropertyGPSLongitude: 4.3517,
            kCGImagePropertyGPSLongitudeRef: "E",
        },
    }
    CGImageDestinationAddImage(dest, CGBitmapContextCreateImage(ctx), props)
    assert CGImageDestinationFinalize(dest)


def _existing_test_photos() -> list[tuple[str, str]]:
    """(original filename, uuid) of the live test photos already in the album. Plain
    strings leave the worker, never a PhotoInfo; a hidden photo is skipped, as every
    tool refuses it (D-17)."""

    def work() -> list[tuple[str, str]]:
        return sorted(
            (p.original_filename, p.uuid)
            for p in runtime.photos_db().photos(albums=[ALBUM])
            if not p.hidden and (p.original_filename or "").startswith(PREFIX)
        )

    return runtime.run_native(work)


def _import_new(tmp: Path) -> tuple[str, str]:
    """Import one throwaway photo; return (uuid, original filename)."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    name = f"{PREFIX}integration-{stamp}.jpg"
    src = tmp / name
    _write_jpeg(src)
    got = runtime.run_osascript(_IMPORT, str(src), ALBUM, timeout=150)
    uuid = got.strip().split("/")[0].upper()
    deadline = time.monotonic() + 30
    while True:
        try:
            PhotosAdapter().info(uuid)
            return uuid, name
        except ValueError:
            if time.monotonic() > deadline:
                raise
            time.sleep(1)


@pytest.fixture(scope="module")
def test_photo(tmp_path_factory):
    existing = _existing_test_photos()
    if existing:
        name, uuid = existing[0]
        print(f"REUSED TEST PHOTO: {name} in album {ALBUM}")
    else:
        uuid, name = _import_new(tmp_path_factory.mktemp("photo-import"))
        print(f"NEW TEST PHOTO for the owner: {name} in album {ALBUM}")
    return SimpleNamespace(
        uuid=uuid, old_id=f"{uuid}/L0/001", stem=Path(name).stem, name=name
    )


def test_info_by_old_id_uuid_and_lowercase_uuid_agree(test_photo):
    a = PhotosAdapter()
    by_uuid = a.info(test_photo.uuid)
    assert a.info(test_photo.old_id) == by_uuid
    assert a.info(test_photo.uuid.lower()) == by_uuid
    assert by_uuid["id"] == test_photo.uuid and by_uuid["filename"] == test_photo.name


def test_info_matches_the_written_exif_date_and_location(test_photo):
    got = PhotosAdapter().info(test_photo.uuid)
    assert got["camera_make"] == "TestMake" and got["camera_model"] == "TestModel"
    assert got["lens"] == "TestLens" and got["iso"] == 100
    assert got["focal_length"] == pytest.approx(4.2, abs=0.01)
    assert got["aperture"] == pytest.approx(2.8, abs=0.01)
    assert got["shutter_speed"] == pytest.approx(1 / 60, rel=0.02)
    assert got["latitude"] == pytest.approx(50.8503, abs=1e-3)
    assert got["longitude"] == pytest.approx(4.3517, abs=1e-3)
    assert got["taken"].startswith("2026-01-02T03:04:05")


def test_search_finds_the_photo_by_its_filename(test_photo):
    ids = [p.id for p in PhotosAdapter().get_pointers(test_photo.stem)]
    assert test_photo.uuid in ids


def test_albums_lists_the_test_album(test_photo):
    summaries = [p["summary"] for p in PhotosAdapter().albums()["results"]]
    assert any(s.startswith(f"{ALBUM} (") for s in summaries)


def _size(path: str) -> list[int]:
    out = subprocess.run(
        ["sips", "-g", "pixelWidth", "-g", "pixelHeight", path],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sorted(int(n) for n in re.findall(r"pixel(?:Width|Height): (\d+)", out))


def test_export_writes_an_image_and_a_second_export_is_refused(
    test_photo, tmp_path, monkeypatch
):
    monkeypatch.setenv("MACOS_APPS_FILE_ROOT", str(tmp_path / "root"))
    a = PhotosAdapter()
    out_dir = (tmp_path / "root").resolve() / "out"
    try:
        got = a.export(test_photo.uuid, "out")
        assert got["status"] == "written", got
        assert got["edited"] == a.info(test_photo.uuid)["edited"]
        assert Path(got["path"]).parent == out_dir and got["bytes"] > 0
        # a reused 04-01 photo is rotated, a new one is not: both are 320x240 sides
        assert _size(got["path"]) == [240, 320]
        with pytest.raises(WriteRefused):
            a.export(test_photo.uuid, "out")
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
