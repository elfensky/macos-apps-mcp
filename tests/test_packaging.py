import json
import plistlib
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "packaging"


def test_bundle_version_tracks_pyproject():
    """The .app carried 0.8.0 for a whole release cycle because the version lives in
    two files and only one gets bumped. `doctor` reports the bundle's, so the drift is
    what a user sees."""
    info = plistlib.loads((PKG / "Info.plist").read_bytes())
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert info["CFBundleShortVersionString"] == project["project"]["version"]


def test_only_intel_macs_cap_cryptography():
    """cryptography 49+ ships no Intel macOS wheel, so a plain uvx on an Intel Mac built
    it from source and needed Rust (#322). The cap must stay Intel-only: Apple silicon
    keeps the current release."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    reqs = [Requirement(d) for d in project["project"]["dependencies"]]
    (crypto,) = [r for r in reqs if r.name == "cryptography"]
    assert str(crypto.specifier) == "<49"
    assert not crypto.extras
    intel = {"sys_platform": "darwin", "platform_machine": "x86_64"}
    assert crypto.marker.evaluate(intel)
    assert not crypto.marker.evaluate({**intel, "platform_machine": "arm64"})
    assert not crypto.marker.evaluate({**intel, "sys_platform": "linux"})


def test_osxphotos_is_a_capped_base_dependency():
    """Photos (D-01) reads the library through osxphotos: a base dependency, capped
    below 0.78 (0.x, its export must never start a download). D-16: the Python 3.12
    floor is what lets it lock beside pyobjc 10+, and UniformTypeIdentifiers is a base
    line with no marker, because the bundle install drops a platform_release marker
    in silence."""
    text = (ROOT / "pyproject.toml").read_text()
    project = tomllib.loads(text)["project"]
    reqs = [Requirement(d) for d in project["dependencies"]]
    (photos,) = [r for r in reqs if r.name == "osxphotos"]
    assert {str(s) for s in photos.specifier} == {">=0.77.2", "<0.78"}
    assert not any(
        Requirement(d).name == "osxphotos"
        for group in project.get("optional-dependencies", {}).values()
        for d in group
    )
    assert "Photos extra deferred" not in text
    assert project["requires-python"] == ">=3.12"
    assert not any("3.11" in c for c in project["classifiers"])
    (uti,) = [r for r in reqs if r.name == "pyobjc-framework-uniformtypeidentifiers"]
    assert uti.marker is None


def test_ruff_targets_the_python_floor():
    """#384, D-16: the ruff target must track the requires-python floor."""
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text())
    floor = cfg["project"]["requires-python"].removeprefix(">=")
    assert cfg["tool"]["ruff"]["target-version"] == "py" + floor.replace(".", "")


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


def test_info_plist_names_the_icon():
    """macOS 26 finds the Liquid Glass icon in Assets.car by CFBundleIconName, and
    older macOS loads AppIcon.icns by CFBundleIconFile; both must match the build's
    `--app-icon AppIcon`, or the .app shows the generic icon."""
    info = plistlib.loads((PKG / "Info.plist").read_bytes())
    assert info["CFBundleIconFile"] == "AppIcon"
    assert info["CFBundleIconName"] == "AppIcon"


def test_icon_composer_package_is_consistent():
    """actool fails, or drops a layer, when a name in icon.json has no file; a stray
    file is an asset no layer uses."""
    icon = PKG / "AppIcon.icon"
    doc = json.loads((icon / "icon.json").read_text())
    named = {
        layer["image-name"]
        for group in doc["groups"]
        for layer in group.get("layers", [])
    }
    assert named
    assert named == {p.name for p in (icon / "Assets").iterdir()}
    assert "macOS" in doc["supported-platforms"]["squares"]


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
    install = '--target "$WORK/site-$a" -r "$WORK/reqs"'
    rm_dylibs = 'rm -f "$WORK/site-$a/osxphotos/lib/"libdisclaim_*.dylib'
    guard = 'if grep -q platform_release "$WORK/reqs"; then'
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
        install,
        rm_dylibs,
        # -s -P: with cwd = the checkout, a bare import would load the repo's package
        '-E -s -P -c "import macos_apps_mcp, osxphotos, UniformTypeIdentifiers"',
        "import ctypes, macos_apps_mcp.server, osxphotos, UniformTypeIdentifiers",
        guard,
        "EXPORT HOLDS platform_release MARKERS",
    ):
        assert needle in src, needle
    # the thin osxphotos CLI dylibs go inside the install loop, before the tree diff
    assert src.index(install) < src.index(rm_dylibs) < src.index("ARCH TREES DIFFER")
    # an export that holds a platform_release marker is refused before anything installs
    assert src.index("uv export") < src.index(guard) < src.index(install)
    assert "exit 1" in src[src.index(guard) : src.index("\nfi\n", src.index(guard))]
    assert src.index("universal2 gate ok") < src.index('if [[ -n "$SIGN" ]]')
    # the gate names a bad binary before a smoke can trip over it
    assert src.index("universal2 gate ok") < src.index("BUNDLE SMOKE FAILED")
    # three per-slice loops: the minos gate, the unsigned smokes, the signed smokes
    assert src.count("for a in arm64 x86_64; do") == 3
    # kept safety properties of the build: pinned interpreter, identical per-arch
    # trees, no unexplained arch-specific file, bytecode sealed in before signing
    for needle in ("shasum -a 256 -c", "ARCH TREES DIFFER", "ARCH-SPECIFIC NON-BINARY"):
        assert needle in src, needle
    assert src.index("-m compileall") < src.index('if [[ -n "$SIGN" ]]')
    # the unsigned smokes cannot see a hardened-runtime fault (x86_64 ctypes hang)
    assert src.index('-s "$SIGN" "$APP"\n') < src.index("signed smoke ok")


def test_build_script_builds_the_project_wheel_in_a_hash_locked_environment():
    """#373: hatchling and its dependencies come from uv.lock under --require-hashes,
    and the bundle gets the built wheel, never the source directory."""
    src = (ROOT / "scripts" / "build_app.sh").read_text()
    export = 'uv export --project "$REPO" --frozen --only-group build'
    start = src.index("uv build")
    build = src[start : src.index("\n", src.index("--out-dir", start))]
    for needle in (
        "--wheel",
        '--build-constraints "$WORK/build-reqs"',
        "--require-hashes",
    ):
        assert needle in build, needle
    assert export in src
    assert not re.search(r'uv pip install[^\n]*"\$REPO"', src)  # no directory install
    install = src[src.index("uv pip install -q --python", start) :].split("\n", 1)[0]
    assert "--no-deps" in install and ".whl" in install
    assert src.index(export) < src.index("uv build") < src.index(install)
    assert src.index(install) < src.index("universal2 gate ok")


def test_the_build_group_pins_the_backend_with_hashes():
    """The backend named in [build-system].requires is in the `build` group, and the
    export carries a sha256 for every requirement (so --require-hashes can hold)."""
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv not on PATH")
    out = subprocess.run(
        [
            uv,
            "export",
            "--project",
            str(ROOT),
            "--frozen",
            "--only-group",
            "build",
            "--no-emit-project",
            "--no-header",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    reqs = [b for b in re.split(r"\n(?=\S)", out.strip()) if not b.startswith("#")]
    assert reqs and all("--hash=sha256:" in r for r in reqs)
    pinned = {r.split("==")[0] for r in reqs}
    required = {
        Requirement(r).name
        for r in tomllib.loads((ROOT / "pyproject.toml").read_text())["build-system"][
            "requires"
        ]
    }
    assert required <= pinned


def test_build_script_compiles_the_icon():
    """The bundle reset would delete an earlier compile, and codesign seals
    Contents/Resources, so an icon written after signing breaks the seal."""
    src = (ROOT / "scripts" / "build_app.sh").read_text()
    for needle in (
        "DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcrun -f actool",
        "the Command Line Tools have no actool",
        '"$ACTOOL" "$REPO/packaging/AppIcon.icon"',
        '--compile "$APP/Contents/Resources"',
        "--platform macosx",
        '--minimum-deployment-target "$MACOS_MIN"',
        "--app-icon AppIcon",
        '--output-partial-info-plist "$WORK/',
        "for f in AppIcon.icns Assets.car",
        "ICON COMPILE FAILED",
    ):
        assert needle in src, needle
    # a Mac without actool fails before any download
    assert src.index("the Command Line Tools have no actool") < src.index("curl -fsSL")
    compile_at = src.index('"$ACTOOL" "$REPO/packaging/AppIcon.icon"')
    assert src.index('rm -rf "$APP"; mkdir -p') < compile_at
    assert compile_at < src.index('cp "$REPO/packaging/Info.plist"')
    assert compile_at < src.index('if [[ -n "$SIGN" ]]')


def test_build_script_compiles_hash_pyc():
    """`cp -R` resets file times, so timestamp .pyc read as stale and the daemon
    rewrites them inside the signed bundle, breaking the seal (#297). `-f` is needed
    because the smokes already wrote timestamp .pyc, which compileall would keep."""
    src = (ROOT / "scripts" / "build_app.sh").read_text()
    cmd = src[src.index("-m compileall") : src.index("BYTECODE PRECOMPILE FAILED")]
    assert "--invalidation-mode checked-hash" in cmd
    assert " -f " in cmd
    # import hooks (beartype claw) write opt-* timestamp .pyc that compileall skips: a
    # generic conversion step must run after compileall and before signing
    for needle in ("source_from_cache", "source_hash", "HASH PYC CONVERSION FAILED"):
        assert needle in src, needle
    assert (
        src.index("-m compileall")
        < src.index("HASH PYC CONVERSION FAILED")
        < src.index('if [[ -n "$SIGN" ]]')
    )
    assert "beartype" not in src[src.index("source_from_cache") :].split("PY\n")[0]


def test_only_the_intel_slice_carries_the_memory_exception():
    """#205: libffi has no x86_64 trampoline pages, so the Intel slice needs
    allow-unsigned-executable-memory; arm64 keeps the strict set
    (test_entitlements_minimal). The build derives the x86_64 set from the strict
    file by adding exactly that one key, joins the per-set slices, and gates on both."""
    src = (ROOT / "scripts" / "build_app.sh").read_text()
    key = "com.apple.security.cs.allow-unsigned-executable-memory"
    assert 'cp "$ENTS" "$ENTS_X86"' in src  # derived from the strict file
    assert src.count("PlistBuddy -c") == 1
    assert f'"Add :{key} bool true"' in src
    # ...and the gate proves strict-plus-ONE-key, then exact sets and the runtime flag
    assert "$((n_strict + 1))" in src
    assert 'want="$ENTS"; [[ "$a" == x86_64 ]] && want="$ENTS_X86"' in src
    assert '"flags=0x10000(runtime)"' in src
    assert 'lipo -create "$WORK/exe-x86_64" "$WORK/exe-arm64"' in src
    # the signed smoke loads PyObjC and allocates a real closure, time-capped
    assert "ctypes.CFUNCTYPE(None)(lambda: None)" in src
    assert "alarm shift; exec @ARGV' 120" in src
    sign = src.index('if [[ -n "$SIGN" ]]')
    assert sign < src.index("entitlements ok") < src.index("signed smoke ok")
