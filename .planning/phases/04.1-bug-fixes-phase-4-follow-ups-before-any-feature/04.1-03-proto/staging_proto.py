"""Prototype of the FIX-10 staging() — scratch only, not the repo."""
import contextlib, logging, os, re, shutil, stat, tempfile
from pathlib import Path
from collections.abc import Iterator

log = logging.getLogger("macos_apps_mcp.files")
_PREFIX = ".macos-apps-mcp-export-"
# mkdtemp appends 8 chars of [a-z0-9_]; the pid sits between prefix and suffix
_STAGING_NAME = re.compile(re.escape(_PREFIX) + r"(\d+)-[a-z0-9_]{8}")


def _pid_alive(pid: int) -> bool:
    if pid <= 1:  # 0 / -1 would signal a process group / everyone; 1 is launchd
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OverflowError):  # exists under another user / not a pid
        return True
    return True


def _sweep(parent: Path) -> None:
    """Remove staging dirs a killed export left in ``parent``: ours by name, owner,
    mode and type, and their pid dead. Never a live one."""
    try:
        entries = list(os.scandir(parent))
    except OSError:
        return
    for e in entries:
        m = _STAGING_NAME.fullmatch(e.name)
        if not m or int(m[1]) == os.getpid() or _pid_alive(int(m[1])):
            continue
        try:
            st = e.stat(follow_symlinks=False)
            if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) != 0o700:
                continue
            shutil.rmtree(e.path)
            log.info("removed staging directory %s left by dead pid %s", e.path, m[1])
        except OSError as err:
            log.warning("could not remove stale staging directory %s (%s)", e.path, err.strerror)


@contextlib.contextmanager
def staging(dest: Path) -> Iterator[Path]:
    _sweep(dest.parent)
    d = Path(tempfile.mkdtemp(prefix=f"{_PREFIX}{os.getpid()}-", dir=dest.parent))
    try:
        yield d
    finally:
        try:
            shutil.rmtree(d, onexc=_gone_ok)
        except OSError as e:
            log.warning("staging directory %s was left behind (%s)", d, e.strerror)


def _gone_ok(_f, _p, exc):
    if not isinstance(exc, FileNotFoundError):
        raise exc
