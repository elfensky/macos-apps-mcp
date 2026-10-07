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
    # 15.0 = oldest macOS device-verified (15.6.1, 15.7.9); the code needs 14 (EventKit
    # requestFullAccessTo*). build_app.sh reads it for wheel tags + minos gate (#205).
    assert info["LSMinimumSystemVersion"] == "15.0"
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


def test_build_script_gates_universal2():
    """A missing slice or a too-new binary installs fine and fails only on the user's
    Mac; only the build gate sees it (#205)."""
    src = (ROOT / "scripts" / "build_app.sh").read_text()
    for needle in (
        "plutil -extract LSMinimumSystemVersion raw",
        'MACOSX_DEPLOYMENT_TARGET="$MACOS_MIN"',
        "--prune cryptography",
        "lipo -archs",
        '"x86_64 arm64"',
        "vtool -arch",
        "for a in arm64 x86_64",
        '/usr/bin/arch "-$a"',
        "smoke_stream.py",
        "universal2 gate ok",
    ):
        assert needle in src, needle
    assert src.index("universal2 gate ok") < src.index('if [[ -n "$SIGN" ]]')
    # the unsigned smokes cannot see a hardened-runtime fault (x86_64 ctypes hang)
    assert src.index('-s "$SIGN" "$APP"\n') < src.index("signed smoke ok")
