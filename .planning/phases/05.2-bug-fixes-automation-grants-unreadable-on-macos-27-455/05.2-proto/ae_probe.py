"""Phase 05.2 / FIX-14 (#455) probe: AEDeterminePermissionToAutomateTarget via ctypes.

READ-ONLY and NON-PROMPTING: askUserIfNeeded is False, so no Apple Event is sent and no
dialog shows. It reports the TCC identity of the process that RUNS it.

From a terminal (identity = the terminal app):

    uv run python -I <this file> [bundle-id ...]

As the installed bundle (identity = ren.lav.macos-apps-mcp; own responsible process, so
its answers differ from the terminal's -- measured 2026-10-25 on macOS 27.0.1):

    open -n -W --stdout OUT --stderr OUT.err -a /Applications/macos-apps-mcp.app \
        --args -E -s -P <absolute path to this file> [bundle-id ...]

The binding below is the candidate body of ``runtime.automation_permission``.
Return codes (AppleEvents.h, SDK 27): 0 noErr, -1743 errAEEventNotPermitted,
-1744 errAEEventWouldRequireUserConsent, -600 procNotFound.
"""

from __future__ import annotations

import ctypes
import sys

_FW = "/System/Library/Frameworks/CoreServices.framework/CoreServices"
_TYPE_BUNDLE_ID = 0x62756E64  # 'bund' = typeApplicationBundleID
_TYPE_WILD = 0x2A2A2A2A  # '****' = typeWildCard


class AEDesc(ctypes.Structure):
    # struct AEDesc { DescType descriptorType; AEDataStorage dataHandle; }
    _fields_ = [("descriptorType", ctypes.c_uint32), ("dataHandle", ctypes.c_void_p)]


def _load():
    lib = ctypes.CDLL(_FW)
    lib.AECreateDesc.argtypes = [
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_long,  # Size (long)
        ctypes.POINTER(AEDesc),
    ]
    lib.AECreateDesc.restype = ctypes.c_int16  # OSErr (16 bit in AEDataModel.h)
    lib.AEDisposeDesc.argtypes = [ctypes.POINTER(AEDesc)]
    lib.AEDisposeDesc.restype = ctypes.c_int16  # OSErr
    lib.AEDeterminePermissionToAutomateTarget.argtypes = [
        ctypes.POINTER(AEDesc),
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_ubyte,  # Boolean
    ]
    lib.AEDeterminePermissionToAutomateTarget.restype = ctypes.c_int32  # OSStatus
    return lib


def automation_permission(bundle_id: str) -> int:
    """OSStatus for this process's Automation grant to ``bundle_id`` (never prompts)."""
    lib = _load()
    raw = bundle_id.encode("utf-8")
    desc = AEDesc()
    err = lib.AECreateDesc(_TYPE_BUNDLE_ID, raw, len(raw), ctypes.byref(desc))
    if err != 0:
        return err
    try:
        return lib.AEDeterminePermissionToAutomateTarget(
            ctypes.byref(desc), _TYPE_WILD, _TYPE_WILD, 0
        )
    finally:
        lib.AEDisposeDesc(ctypes.byref(desc))


_DEFAULT = {
    "com.apple.mail": "Mail",
    "com.apple.Notes": "Notes",
    "com.apple.AddressBook": "Contacts",
    "com.apple.Safari": "Safari",
    "com.apple.MobileSMS": "Messages",
    "com.apple.Music": "Music",
    "com.apple.Photos": "Photos",
    "com.apple.Shortcuts": "Shortcuts",
    "com.example.not-installed": "(no such app)",
    "": "(empty id)",
}


def _running(bundle_id: str) -> bool:
    import AppKit  # PyObjC: NSRunningApplication, no Apple Event, no TCC

    apps = AppKit.NSRunningApplication.runningApplicationsWithBundleIdentifier_(
        bundle_id
    )
    return bool(apps)


def main(argv: list[str]) -> None:
    ids = argv or list(_DEFAULT)
    print(f"{'bundle id':28} {'running':8} rc")
    for b in ids:
        print(f"{b or '<empty>':28} {str(_running(b)):8} {automation_permission(b)}")


if __name__ == "__main__":
    main(sys.argv[1:])
