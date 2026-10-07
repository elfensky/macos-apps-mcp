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
    # the gate names a bad binary before a smoke can trip over it
    assert src.index("universal2 gate ok") < src.index("# Smokes on BOTH slices")
    # kept safety properties of the build: pinned interpreter, identical per-arch
    # trees, no unexplained arch-specific file, bytecode sealed in before signing
    for needle in ("shasum -a 256 -c", "ARCH TREES DIFFER", "ARCH-SPECIFIC NON-BINARY"):
        assert needle in src, needle
    assert src.index("-m compileall") < src.index('if [[ -n "$SIGN" ]]')
    # the unsigned smokes cannot see a hardened-runtime fault (x86_64 ctypes hang)
    assert src.index('-s "$SIGN" "$APP"\n') < src.index("signed smoke ok")


def test_only_the_intel_slice_carries_the_memory_exception():
    """#205: libffi has no x86_64 trampoline pages, so the Intel slice needs
    allow-unsigned-executable-memory; arm64 keeps the strict set
    (test_entitlements_minimal). The build derives the x86_64 set from the strict
    file by adding exactly that one key, joins the per-set slices, and gates on both."""
    src = (ROOT / "scripts" / "build_app.sh").read_text()
    key = "com.apple.security.cs.allow-unsigned-executable-memory"
    assert src.count("PlistBuddy -c") == 1
    assert f'"Add :{key} bool true"' in src
    assert 'lipo -create "$WORK/exe-x86_64" "$WORK/exe-arm64"' in src
    assert "entitlements ok: x86_64 has the exception, arm64 is strict" in src
    sign = src.index('if [[ -n "$SIGN" ]]')
    assert sign < src.index("entitlements ok") < src.index("signed smoke ok")
