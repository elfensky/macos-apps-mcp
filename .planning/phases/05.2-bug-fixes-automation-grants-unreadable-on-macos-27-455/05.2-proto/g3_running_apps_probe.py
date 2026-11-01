"""G3 probe (05.2 gap round 2): does NSRunningApplication see an app launch/quit when
the main run loop never turns? Compares the AppKit reads with live process-table reads.

Usage:  uv run python -I <this file> [--thread] [--pump]
  --thread  do every AppKit read on a worker thread (like runtime.run_native)
  --pump    pump the main run loop (NSRunLoop.runUntilDate_) between reads
Target is Calculator ONLY, launched in the background (open -g) and ended with SIGTERM.
Refuses to start when Calculator is already running. Touches no Mail, no TCC entry.
"""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import AppKit
import Foundation

BUNDLE, NAME = "com.apple.calculator", "Calculator"
THREAD = "--thread" in sys.argv
PUMP = "--pump" in sys.argv
_pool = ThreadPoolExecutor(max_workers=1) if THREAD else None
libproc = ctypes.CDLL("/usr/lib/libproc.dylib")


def on_thread(fn):
    return _pool.submit(fn).result() if _pool else fn()


def appkit_pid() -> int | None:
    apps = AppKit.NSRunningApplication.runningApplicationsWithBundleIdentifier_(BUNDLE)
    return int(apps[0].processIdentifier()) if apps else None


def workspace_pid() -> int | None:
    for a in AppKit.NSWorkspace.sharedWorkspace().runningApplications():
        if a.bundleIdentifier() == BUNDLE:
            return int(a.processIdentifier())
    return None


def pgrep_pid() -> int | None:
    out = subprocess.run(["pgrep", "-x", NAME], capture_output=True, text=True).stdout
    return int(out.split()[0]) if out.split() else None


def lsappinfo_pid() -> int | None:
    out = subprocess.run(
        ["lsappinfo", "find", f"bundleid={BUNDLE}"], capture_output=True, text=True
    ).stdout
    # prints an ASN like ASN:0x0-0x1234: ; ask for the pid
    asn = out.strip().splitlines()[0] if out.strip() else ""
    if not asn:
        return None
    info = subprocess.run(
        ["lsappinfo", "info", "-only", "pid", asn], capture_output=True, text=True
    ).stdout
    digits = "".join(c for c in info.split("=")[-1] if c.isdigit())
    return int(digits) if digits else None


def pump(seconds: float = 0.0) -> None:
    if PUMP:
        Foundation.NSRunLoop.currentRunLoop().runUntilDate_(
            Foundation.NSDate.dateWithTimeIntervalSinceNow_(seconds or 0.05)
        )


def snapshot(label: str) -> dict:
    t0 = time.perf_counter()
    row = {
        "appkit": on_thread(appkit_pid),
        "workspace": on_thread(workspace_pid),
        "pgrep": pgrep_pid(),
        "lsappinfo": lsappinfo_pid(),
    }
    print(f"{label:<28} {row}  ({(time.perf_counter() - t0) * 1000:.0f} ms)")
    return row


def main() -> int:
    if pgrep_pid() is not None:
        print("Calculator is already running: refusing")
        return 2
    print(f"mode: thread={THREAD} pump={PUMP}")
    # warm the AppKit caches BEFORE the launch, as a long-lived daemon would have
    snapshot("before launch")
    subprocess.run(["open", "-g", "-a", NAME], check=True)
    pid = None
    try:
        for i in range(8):
            time.sleep(0.5)
            pump()
            row = snapshot(f"launch +{(i + 1) * 0.5:.1f}s")
            pid = row["pgrep"] or pid
        # runningApplicationWithProcessIdentifier_ by pid
        if pid:
            one = on_thread(
                lambda: AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(
                    pid
                )
            )
            print("runningApplicationWithProcessIdentifier_ ->", bool(one))
    finally:
        if pid:
            os.kill(pid, signal.SIGTERM)
        elif pgrep_pid():
            os.kill(pgrep_pid(), signal.SIGTERM)
    for i in range(8):
        time.sleep(0.5)
        pump()
        snapshot(f"quit +{(i + 1) * 0.5:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
