"""Q4 probe: is NSPasteboard.changeCount live in a process that never turns a run loop?
Uses a PRIVATE NAMED pasteboard ("ren.lav.research.probe"), never the general one, so the
user's clipboard is untouched. Process A (this) reads changeCount in a loop on a worker
thread with no run loop; a child process writes the named pasteboard twice.
Usage: uv run python -I <this file>"""
import subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
import AppKit
NAME = "ren.lav.research.probe"
WRITER = (
    "import AppKit,sys;pb=AppKit.NSPasteboard.pasteboardWithName_(%r);"
    "pb.clearContents();pb.setString_forType_(sys.argv[1],AppKit.NSPasteboardTypeString)" % NAME
)
pool = ThreadPoolExecutor(max_workers=1)
pb = AppKit.NSPasteboard.pasteboardWithName_(NAME)
cc = lambda: pool.submit(lambda: int(pb.changeCount())).result()
print("before:", cc())
for i in (1, 2):
    subprocess.run([sys.executable, "-I", "-c", WRITER, f"v{i}"], check=True)
    t0 = time.perf_counter()
    print(f"after child write {i}: changeCount={cc()} read in {(time.perf_counter()-t0)*1000:.1f} ms")
pb.releaseGlobally()
