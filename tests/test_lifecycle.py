"""Unit tests for lifecycle.py — orphan detection + guard installation (#56). The
child-termination half lives in test_runtime.py with the child registry it exercises.

install_lifecycle_guards() is tested hermetically: atexit/signal/threading are faked at
the module boundary, so no real signal handler is installed, no watcher thread starts,
and the process never exits. The captured watcher target and SIGTERM handler are then
driven synchronously.
"""

from __future__ import annotations

import os
import signal

import pytest

import macos_apps_mcp.lifecycle as lifecycle
from macos_apps_mcp.lifecycle import _parent_died


def test_parent_died_false_when_ppid_unchanged():
    # our real parent is alive and unchanged → not orphaned.
    assert _parent_died(os.getppid()) is False


def test_parent_died_true_when_reparented():
    # getppid() no longer equals the launch-time pid → parent gone, we're orphaned.
    assert _parent_died(os.getppid() + 999_999) is True


# --- install_lifecycle_guards() -------------------------------------------------------


class _Exit(BaseException):
    """Stands in for os._exit so a test can observe it without dying."""


@pytest.fixture
def guards(monkeypatch):
    """Fake every process-touching boundary; return the capture dict.

    Resets the idempotency latch so each test installs fresh, and swaps atexit.register,
    signal.signal and threading.Thread for recorders — nothing real is installed.
    """
    seen: dict = {"atexit": [], "signals": {}, "threads": []}
    monkeypatch.setattr(lifecycle, "_lifecycle_installed", False)
    monkeypatch.setattr(lifecycle.atexit, "register", seen["atexit"].append)
    monkeypatch.setattr(
        lifecycle.signal, "signal", lambda sig, h: seen["signals"].__setitem__(sig, h)
    )

    class FakeThread:
        def __init__(self, *, target, name, daemon):
            self.target, self.name, self.daemon = target, name, daemon
            self.started = False

        def start(self):
            self.started = True
            seen["threads"].append(self)

    monkeypatch.setattr(lifecycle.threading, "Thread", FakeThread)
    return seen


def test_install_registers_atexit_cleanup(guards):
    lifecycle.install_lifecycle_guards()
    # normal exit terminates any in-flight child via runtime's registry.
    assert guards["atexit"] == [lifecycle.terminate_children]


def test_install_grabs_sigterm(guards):
    lifecycle.install_lifecycle_guards()
    assert signal.SIGTERM in guards["signals"]


def test_install_starts_daemon_watcher_thread(guards):
    lifecycle.install_lifecycle_guards()
    (thread,) = guards["threads"]
    assert thread.started and thread.daemon  # daemon: must never block interpreter exit
    assert thread.name == "mac-ppid-watch"


def test_install_is_idempotent(guards):
    lifecycle.install_lifecycle_guards()
    lifecycle.install_lifecycle_guards()
    assert len(guards["threads"]) == 1  # one watcher, not one per call
    assert len(guards["atexit"]) == 1


def test_sigterm_handler_terminates_children_then_exits(guards, monkeypatch):
    events: list = []
    monkeypatch.setattr(
        lifecycle, "terminate_children", lambda: events.append("terminate")
    )
    monkeypatch.setattr(lifecycle.os, "_exit", lambda code: events.append(code))
    lifecycle.install_lifecycle_guards()
    guards["signals"][signal.SIGTERM](signal.SIGTERM, None)  # deliver a fake SIGTERM
    # children die BEFORE the exit, and the exit is the hard os._exit(0).
    assert events == ["terminate", 0]


def test_watcher_kills_children_and_hard_exits_when_parent_dies(guards, monkeypatch):
    events: list = []
    monkeypatch.setattr(lifecycle, "_parent_died", lambda ppid: True)  # orphaned now
    monkeypatch.setattr(
        lifecycle, "terminate_children", lambda: events.append("terminate")
    )

    def fake_exit(code):
        events.append(code)
        raise _Exit  # os._exit never returns; neither does the stand-in

    monkeypatch.setattr(lifecycle.os, "_exit", fake_exit)
    lifecycle.install_lifecycle_guards()
    (thread,) = guards["threads"]
    with pytest.raises(_Exit):
        thread.target()  # run the watcher loop body synchronously — no sleep taken
    assert events == ["terminate", 0]
