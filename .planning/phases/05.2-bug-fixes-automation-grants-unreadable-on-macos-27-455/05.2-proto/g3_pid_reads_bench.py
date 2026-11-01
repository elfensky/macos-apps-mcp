"""G3 bench (05.2 gap round 2): cost and agreement of the live "which pid is app X"
reads that need no main run loop, plus a flicker count for the AppKit class method.

Usage:  uv run python -I <this file> [bundle-id exec-path-suffix name]
Defaults to Finder (always running). Pass Mail's three values to measure Mail: the reads
are process-table and LaunchServices queries only, no Apple Event, no window.

Reads compared:
  appkit   NSRunningApplication.runningApplicationsWithBundleIdentifier_ (on a worker)
  libproc  proc_listpids + proc_pidpath, exact executable path (ctypes, no fork)
  pgrep    pgrep -x NAME -U uid, then ps -o comm= -p PID (two forks)
Also counts how often `appkit` answered empty while `libproc` saw the app (flicker).
"""

from __future__ import annotations

import ctypes
import os
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import AppKit

BUNDLE = sys.argv[1] if len(sys.argv) > 1 else "com.apple.finder"
PATH = (
    sys.argv[2]
    if len(sys.argv) > 2
    else "/System/Library/CoreServices/Finder.app/Contents/MacOS/Finder"
)
NAME = sys.argv[3] if len(sys.argv) > 3 else "Finder"

_lp = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
_lp.proc_listpids.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_int]
_lp.proc_listpids.restype = ctypes.c_int
_lp.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
_lp.proc_pidpath.restype = ctypes.c_int
PROC_ALL_PIDS, PROC_PIDPATHINFO_MAXSIZE = 1, 4096


def libproc_pids(path: str) -> list[int]:
    size = _lp.proc_listpids(PROC_ALL_PIDS, 0, None, 0)
    buf = (ctypes.c_int * (size // 4 + 64))()
    got = _lp.proc_listpids(PROC_ALL_PIDS, 0, buf, ctypes.sizeof(buf))
    want, out = path.encode(), []
    pbuf = ctypes.create_string_buffer(PROC_PIDPATHINFO_MAXSIZE)
    for pid in buf[: got // 4]:
        if pid and _lp.proc_pidpath(pid, pbuf, PROC_PIDPATHINFO_MAXSIZE) > 0:
            if pbuf.value == want:
                out.append(pid)
    return out


def appkit_pids() -> list[int]:
    apps = AppKit.NSRunningApplication.runningApplicationsWithBundleIdentifier_(BUNDLE)
    return [int(a.processIdentifier()) for a in apps]


def pgrep_pids() -> list[int]:
    r = subprocess.run(
        ["pgrep", "-x", "-U", str(os.getuid()), NAME], capture_output=True, text=True
    )
    out = []
    for tok in r.stdout.split():
        comm = subprocess.run(
            ["ps", "-o", "comm=", "-p", tok], capture_output=True, text=True
        ).stdout.strip()
        if comm == PATH:
            out.append(int(tok))
    return out


def timed(fn, n):
    ts, last = [], None
    for _ in range(n):
        t0 = time.perf_counter()
        last = fn()
        ts.append((time.perf_counter() - t0) * 1000)
    return statistics.median(ts), max(ts), last


def main() -> None:
    pool = ThreadPoolExecutor(max_workers=1)
    on_worker = lambda fn: pool.submit(fn).result()  # noqa: E731
    for label, fn, n in (
        ("appkit (worker)", lambda: on_worker(appkit_pids), 500),
        ("libproc", lambda: libproc_pids(PATH), 200),
        ("pgrep+ps", pgrep_pids, 30),
    ):
        med, mx, last = timed(fn, n)
        print(f"{label:<16} median {med:7.2f} ms  max {mx:7.2f} ms  last={last}")
    # flicker: the AppKit class method against the process table, 20000 reads
    empty = diff = 0
    n = 20000
    for _ in range(n):
        a = on_worker(appkit_pids)
        if not a:
            empty += 1
    print(f"appkit empty answers while the app runs: {empty} of {n}")
    print(f"agree now: appkit={on_worker(appkit_pids)} libproc={libproc_pids(PATH)}")


if __name__ == "__main__":
    main()
