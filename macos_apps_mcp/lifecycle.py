"""Lifecycle hygiene (#56) — orphan watcher + exit-path child cleanup.

A stdio MCP server orphaned by its parent (Claude exits/crashes) must not linger,
re-launching Mail.app forever (patrickfreyer #58, python-sdk #526). We watch our
parent pid and hard-exit on reparent; on every exit path we also terminate any
in-flight osascript child via runtime's child registry (the AppleScript
``with timeout`` in each template is the backstop for when we can't). Installed by
the server entry point, NOT runtime.bootstrap(), so importing a module or running
unit tests never starts a watcher or grabs SIGTERM.
"""

from __future__ import annotations

import atexit
import contextlib
import os
import signal
import threading
import time

from .runtime import terminate_children

_PPID_POLL = 1.0  # seconds — well inside the 5s orphan-exit budget

# The launching parent's pid, captured at IMPORT — deliberately NOT at
# install_lifecycle_guards() time. bootstrap() blocks up to 120s on the TCC permission
# prompt *before* the guards install; if the parent died during that wait, an
# install-time os.getppid() would already read 1 (reparented) and the watcher could
# never fire (1 == 1 forever). Import runs right after the parent spawns us (alive).
_LAUNCH_PPID = os.getppid()


def _parent_died(original_ppid: int) -> bool:
    """True once our launching parent is gone: its pid was reaped and we were reparented
    (``getppid`` changes, typically to 1/launchd). A process's parent never changes
    while that parent is alive, so a changed ppid reliably means the parent died."""
    return os.getppid() != original_ppid


_lifecycle_installed = False


def install_lifecycle_guards() -> None:
    """Start the orphan watcher and register child-cleanup on exit (#56). Idempotent.

    Call once from the server entry point (after bootstrap). The watcher is a daemon
    thread; SIGTERM and normal exit both terminate any in-flight osascript child so a
    graceful stop doesn't leave one hung until its AppleScript timeout.
    """
    global _lifecycle_installed
    if _lifecycle_installed:
        return
    _lifecycle_installed = True

    atexit.register(terminate_children)
    # signal.signal only works on the main thread — skip (suppress ValueError) if not.
    with contextlib.suppress(ValueError):
        signal.signal(signal.SIGTERM, lambda *_: (terminate_children(), os._exit(0)))

    def _watch() -> None:
        # compare against the import-time launch ppid (see _LAUNCH_PPID) so a parent
        # that died during bootstrap's permission prompt is still detected as gone.
        while not _parent_died(_LAUNCH_PPID):
            time.sleep(_PPID_POLL)
        # parent gone: kill any in-flight child, then hard-exit (skip Python teardown —
        # its stdio pipes point at a dead parent and could block).
        terminate_children()
        os._exit(0)

    threading.Thread(target=_watch, name="mac-ppid-watch", daemon=True).start()
