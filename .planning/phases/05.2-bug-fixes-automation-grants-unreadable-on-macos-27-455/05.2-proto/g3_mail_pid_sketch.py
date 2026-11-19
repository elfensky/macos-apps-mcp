"""G3 reference for the recommended `runtime._mail_pid`: the pid of THIS user's Mail from
the kernel process table (libproc), matched on the exact executable path. No AppKit, no
run loop, no fork, no Apple Event. Read-only; Mail is never touched.
Usage: uv run python -I <this file>   (prints the pid list and the cost)"""
import ctypes, os, time

_MAIL_EXECUTABLE = b"/System/Applications/Mail.app/Contents/MacOS/Mail"
_PROC_UID_ONLY = 4  # <sys/proc_info.h>: PROC_UID_ONLY (PROC_ALL_PIDS is 1)
_PATH_MAX = 4 * 1024  # PROC_PIDPATHINFO_MAXSIZE = 4 * MAXPATHLEN


def _proc_lib():
    lib = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    lib.proc_listpids.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_int]
    lib.proc_listpids.restype = ctypes.c_int
    lib.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    lib.proc_pidpath.restype = ctypes.c_int
    return lib


def mail_pids(lib=None) -> list[int]:
    lib = lib or _proc_lib()
    size = lib.proc_listpids(_PROC_UID_ONLY, os.getuid(), None, 0)
    buf = (ctypes.c_int * (size // 4 + 64))()  # +64: processes may start in between
    got = lib.proc_listpids(_PROC_UID_ONLY, os.getuid(), buf, ctypes.sizeof(buf))
    path = ctypes.create_string_buffer(_PATH_MAX)
    return [
        pid
        for pid in buf[: max(got, 0) // 4]
        if pid and lib.proc_pidpath(pid, path, _PATH_MAX) > 0 and path.value == _MAIL_EXECUTABLE
    ]


if __name__ == "__main__":
    t0 = time.perf_counter()
    pids = mail_pids()
    print(pids, f"{(time.perf_counter() - t0) * 1000:.2f} ms")
