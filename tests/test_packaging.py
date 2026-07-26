import plistlib
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "packaging"


def test_bundle_version_tracks_pyproject():
    """The .app carried 0.8.0 for a whole release cycle because the version lives in
    two files and only one gets bumped. `doctor` reports the bundle's, so the drift is
    what a user sees."""
    info = plistlib.loads((PKG / "Info.plist").read_bytes())
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert info["CFBundleShortVersionString"] == project["project"]["version"]


def test_info_plist_contract():
    info = plistlib.loads((PKG / "Info.plist").read_bytes())
    assert info["CFBundleIdentifier"] == "ren.lav.macos-apps-mcp"
    assert info["CFBundleExecutable"] == "macos-apps-mcp"
    assert info["LSUIElement"] is True
    for key in (
        "NSCalendarsFullAccessUsageDescription",
        "NSRemindersFullAccessUsageDescription",
        "NSContactsUsageDescription",
        "NSAppleEventsUsageDescription",
    ):
        assert info[key]


def test_entitlements_minimal():
    ents = plistlib.loads((PKG / "entitlements.plist").read_bytes())
    # calendars: macOS 26 silently instant-denies EventKit EVENTS full access for
    # hardened-runtime apps without it (no prompt, no TCC row) — #71 acceptance find.
    assert ents == {
        "com.apple.security.automation.apple-events": True,
        "com.apple.security.personal-information.calendars": True,
    }


def test_launchagent_plist_contract():
    la = plistlib.loads((PKG / "ren.lav.macos-apps-mcp.plist").read_bytes())
    assert la["Label"] == "ren.lav.macos-apps-mcp"
    assert la["ProgramArguments"][1:] == [
        "-E",
        "-s",
        "-P",
        "-m",
        "macos_apps_mcp",
        "daemon",
    ]
    assert la["KeepAlive"] is True and la["ThrottleInterval"] >= 5


def test_build_script_never_deep_signs():
    src = (Path(__file__).resolve().parents[1] / "scripts" / "build_app.sh").read_text()
    assert "--deep" not in src
    assert "--timestamp" in src and "runtime" in src
    assert "sort -V" in src
    assert "--notarize requires --sign" in src
