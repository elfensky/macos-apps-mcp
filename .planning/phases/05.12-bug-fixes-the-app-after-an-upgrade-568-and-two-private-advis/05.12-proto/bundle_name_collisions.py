"""FIX-30 (#585) probe: which bundles inside each scripted app carry the app's own name?

AppleScript resolves ``application "Mail"`` by name. A second bundle with the same
``CFBundleName`` (an app extension inside the app) can take that name while its process
runs and the app does not. This lists, for each app the package scripts by name, every
nested bundle whose name equals the app's name.

Run:  uv run python <this file>

Reads ``Info.plist`` files only (plistlib). It starts no app and sends no Apple Event.
"""

from __future__ import annotations

import pathlib
import platform
import plistlib

# name -> bundle id, as macos_apps_mcp/doctor.py _AUTOMATION_BUNDLES has them
APPS = {
    "Mail": "com.apple.mail",
    "Notes": "com.apple.Notes",
    "Contacts": "com.apple.AddressBook",
    "Safari": "com.apple.Safari",
    "Messages": "com.apple.MobileSMS",
    "Music": "com.apple.Music",
}
ROOTS = (
    pathlib.Path("/System/Applications"),
    pathlib.Path("/Applications"),
    pathlib.Path("/System/Volumes/Preboot/Cryptexes/App/System/Applications"),
)
NAME_KEYS = ("CFBundleName", "CFBundleDisplayName", "CFBundleExecutable")


def info(bundle: pathlib.Path) -> dict:
    try:
        with open(bundle / "Contents" / "Info.plist", "rb") as f:
            return plistlib.load(f)
    except (OSError, plistlib.InvalidFileException):
        return {}


def main() -> None:
    print("macOS", platform.mac_ver()[0])
    for app, bundle_id in APPS.items():
        home = next((r / f"{app}.app" for r in ROOTS if (r / f"{app}.app").exists()), None)
        if home is None:
            print(f"{app}: not found")
            continue
        own = info(home)
        nested = [
            p
            for pattern in ("*.appex", "*.xpc", "*.app", "*.bundle")
            for p in home.rglob(pattern)
            if p != home
        ]
        same = []
        for p in nested:
            meta = info(p)
            hit = [k for k in NAME_KEYS if meta.get(k) == app]
            if hit:
                same.append((p.name, meta.get("CFBundleIdentifier"), hit))
        print(
            f"{app}: id {own.get('CFBundleIdentifier')} (expected {bundle_id}); "
            f"{len(nested)} nested bundles; {len(same)} carry the name {app!r}"
        )
        for name, ident, keys in same:
            print(f"    {name}: {ident}: {', '.join(keys)}")


if __name__ == "__main__":
    main()
