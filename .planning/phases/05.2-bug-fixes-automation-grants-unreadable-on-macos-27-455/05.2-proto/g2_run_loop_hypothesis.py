"""G2 device experiment (05.2 gap round 2): does the in-process AXIsProcessTrusted()
read follow a switch change only when a run loop turns?

Research could not run this: it needs the owner to flip the Accessibility switch of the
app that hosts the terminal (a TCC change, forbidden in research). Run it at the
re-sitting, as a PLAIN process (never as the installed bundle):

    uv run python -I <this file> nopump 60     # reads every second, no run loop
    uv run python -I <this file> pump 60       # same reads, main run loop pumped
    uv run python -I <this file> notify 60     # pumped + prints each notification

While it runs, switch the host app's Accessibility entry off, wait 10 s, switch it on.
Read the output: a column `plain` (AXIsProcessTrusted in this process), `child` (a fresh
interpreter, the proven-live reference) and `axcall` (AX error code of an application
element read: -25211 means not trusted).

Expected if the hypothesis holds: `child` and `axcall` flip at once in every mode; `plain`
stays at its first answer in `nopump`, and follows (within a second or two) in `pump`
and `notify`, where the notification line appears at the flip.
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
import time

HI = (
    "/System/Library/Frameworks/ApplicationServices.framework/Frameworks/"
    "HIServices.framework/HIServices"
)
CF = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
CHILD = (
    "import ctypes;"
    f"l=ctypes.CDLL({HI!r});l.AXIsProcessTrusted.restype=ctypes.c_bool;"
    "print(int(l.AXIsProcessTrusted()))"
)
hi, cf = ctypes.CDLL(HI), ctypes.CDLL(CF)
hi.AXIsProcessTrusted.restype = ctypes.c_bool
hi.AXUIElementCreateApplication.restype = ctypes.c_void_p
hi.AXUIElementCreateApplication.argtypes = [ctypes.c_int]
hi.AXUIElementCopyAttributeValue.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.POINTER(ctypes.c_void_p),
]
hi.AXUIElementCopyAttributeValue.restype = ctypes.c_int32
cf.CFStringCreateWithCString.restype = ctypes.c_void_p
cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
ROLE = cf.CFStringCreateWithCString(None, b"AXRole", 0x08000100)


def finder_pid() -> int:
    out = subprocess.run(["pgrep", "-x", "Finder"], capture_output=True, text=True)
    return int(out.stdout.split()[0])


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "nopump"
    secs = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    pid = finder_pid()
    if mode in ("pump", "notify"):
        import Foundation

        loop = Foundation.NSRunLoop.currentRunLoop()
    if mode == "notify":
        import Foundation

        def seen(note):
            print(f"  NOTIFICATION {note.name()} at {time.strftime('%H:%M:%S')}")

        center = Foundation.NSDistributedNotificationCenter.defaultCenter()
        center.addObserverForName_object_queue_usingBlock_(
            "com.apple.accessibility.api", None, None, seen
        )
    for i in range(secs):
        if mode in ("pump", "notify"):
            loop.runUntilDate_(Foundation.NSDate.dateWithTimeIntervalSinceNow_(1.0))
        else:
            time.sleep(1.0)
        child = subprocess.run(
            [sys.executable, "-I", "-c", CHILD], capture_output=True, text=True
        ).stdout.strip()
        out = ctypes.c_void_p()
        err = hi.AXUIElementCopyAttributeValue(
            hi.AXUIElementCreateApplication(pid), ROLE, ctypes.byref(out)
        )
        print(
            f"t+{i + 1:>3}s {mode}: plain={int(hi.AXIsProcessTrusted())} "
            f"child={child} axcall={err}"
        )


if __name__ == "__main__":
    main()
