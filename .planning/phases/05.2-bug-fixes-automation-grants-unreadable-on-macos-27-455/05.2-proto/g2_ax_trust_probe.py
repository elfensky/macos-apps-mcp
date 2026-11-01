"""G2 probe (05.2 gap round 2): what does AXIsProcessTrusted() read in a long-lived plain
process, and what do the candidate live reads cost?

Usage:  uv run python -I <this file> [--watch SECONDS]
Reads only: the plain trust read (never the prompting WithOptions form), a child process
that repeats it, and one AX call on the system-wide element whose error code tells trust
apart. No window, no event tap, no setting changed. Run it as a plain process, NOT as
the installed bundle.

--watch N   repeat the three reads every second for N seconds, so a person can flip the
            Accessibility switch of THIS host app meanwhile and see which reads follow.
            (A device check for the owner; research did not flip any setting.)
"""

from __future__ import annotations

import ctypes
import statistics
import subprocess
import sys
import time

HI = (
    "/System/Library/Frameworks/ApplicationServices.framework/Frameworks/"
    "HIServices.framework/HIServices"
)
CF = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"

# A fresh interpreter that only calls the plain trust read through ctypes (no PyObjC).
CHILD = (
    "import ctypes;"
    f"l=ctypes.CDLL({HI!r});l.AXIsProcessTrusted.restype=ctypes.c_bool;"
    "print(int(l.AXIsProcessTrusted()))"
)


def _libs():
    hi, cf = ctypes.CDLL(HI), ctypes.CDLL(CF)
    hi.AXIsProcessTrusted.restype = ctypes.c_bool
    hi.AXUIElementCreateSystemWide.restype = ctypes.c_void_p
    hi.AXUIElementCopyAttributeValue.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    hi.AXUIElementCopyAttributeValue.restype = ctypes.c_int32
    cf.CFStringCreateWithCString.restype = ctypes.c_void_p
    cf.CFStringCreateWithCString.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_uint32,
    ]
    return hi, cf


HI_LIB, CF_LIB = _libs()
_ATTR = CF_LIB.CFStringCreateWithCString(None, b"AXFocusedUIElement", 0x08000100)


def in_process() -> bool:
    return bool(HI_LIB.AXIsProcessTrusted())


def child() -> tuple[bool, float]:
    t0 = time.perf_counter()
    out = subprocess.run(
        [sys.executable, "-I", "-c", CHILD], capture_output=True, text=True
    ).stdout.strip()
    return out == "1", (time.perf_counter() - t0) * 1000


def ax_error() -> int:
    """kAXErrorAPIDisabled (-25211) when this process is not trusted; other codes
    (0, -25204 cannot complete, -25212 no value ...) when it is."""
    el = HI_LIB.AXUIElementCreateSystemWide()
    val = ctypes.c_void_p()
    return HI_LIB.AXUIElementCopyAttributeValue(el, _ATTR, ctypes.byref(val))


def row(tag: str) -> None:
    c, ms = child()
    print(f"{tag}: in_process={in_process()} child={c} ({ms:.0f} ms) ax_error={ax_error()}")


def main() -> None:
    row("first")
    ts = []
    for _ in range(50):
        t0 = time.perf_counter()
        in_process()
        ts.append((time.perf_counter() - t0) * 1e6)
    print(f"in-process read: median {statistics.median(ts):.1f} us over 50")
    ts = []
    for _ in range(50):
        t0 = time.perf_counter()
        ax_error()
        ts.append((time.perf_counter() - t0) * 1e6)
    print(f"AX system-wide call: median {statistics.median(ts):.1f} us over 50")
    cs = [child()[1] for _ in range(15)]
    print(f"child process: median {statistics.median(cs):.0f} ms, max {max(cs):.0f} ms over 15")
    if "--watch" in sys.argv:
        n = int(sys.argv[sys.argv.index("--watch") + 1])
        for i in range(n):
            time.sleep(1)
            row(f"t+{i + 1}s")


if __name__ == "__main__":
    main()
