"""Fixtures of the device suite: the real socket, the four switches, the Guard.

The suite-wide ``_isolated_state`` points ``MACOS_APPS_MCP_SOCKET`` at a temporary
path, so ``daemon.socket_path()`` is NOT the real socket here. The real one is named
by ``MACOS_APPS_DEVICE_SOCKET``; every other home path stays isolated. With
``MACOS_APPS_DEVICE_SSH`` the daemon of another Mac is under test: its socket is
forwarded over SSH for the session.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.device.guard import SSH, Guard

MARKER = f"macos-apps-mcp device {time.strftime('%Y%m%d-%H%M%S')}"
HOST = os.environ.get("MACOS_APPS_DEVICE_SSH") or None  # an ssh destination


@pytest.fixture(scope="session")
def device_socket() -> Iterator[Path]:
    """The daemon's socket: on this Mac, or forwarded from ``MACOS_APPS_DEVICE_SSH``."""
    raw = os.environ.get("MACOS_APPS_DEVICE_SOCKET")
    raw = raw or "~/.local/state/macos-apps-mcp/daemon/mcp.sock"
    if not HOST:
        yield Path(raw).expanduser()
        return
    # An ssh session starts in the home folder: `pwd` expands the `~` of that Mac.
    home = subprocess.run([*SSH, HOST, "pwd"], capture_output=True, text=True)
    there = home.stdout.strip() + raw[1:] if raw.startswith("~") else raw
    # /tmp, not pytest's tmp_path: a unix socket path has a 104-byte limit.
    with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
        here = Path(tmp) / "mcp.sock"
        forward = ["-o", "ExitOnForwardFailure=yes", "-N", "-L", f"{here}:{there}"]
        tunnel = subprocess.Popen([*SSH, *forward, HOST])
        try:
            for _ in range(75):  # at most 15 s
                if here.exists() or tunnel.poll() is not None:
                    break
                time.sleep(0.2)
            yield here
        finally:
            tunnel.terminate()
            tunnel.wait()


@pytest.fixture(scope="session")
def guard(device_socket) -> Guard:
    if not device_socket.exists():
        why = f"no forward from {HOST}" if HOST else "set MACOS_APPS_DEVICE_SOCKET"
        pytest.skip(f"no daemon socket at {device_socket} ({why})")
    address = os.environ.get("MACOS_APPS_TEST_ADDRESS") or None
    return Guard(device_socket, MARKER, address, HOST)


@pytest.fixture(autouse=True)
def _socket_present(guard):
    """Every device test needs the socket: skip, never fail, when it is absent."""


@pytest.fixture(scope="session")
def writes(guard) -> None:
    if os.environ.get("MACOS_APPS_DEVICE_WRITES") != "1":
        pytest.skip("a write test: set MACOS_APPS_DEVICE_WRITES=1 to run it")


@pytest.fixture(scope="session")
def sender(guard, writes) -> str:
    if not guard.owned.address:
        pytest.skip("a send test: set MACOS_APPS_TEST_ADDRESS to your own address")

    async def names():
        async with guard.connect():
            return await guard.tool_names()

    if "send_mail" not in asyncio.run(names()):
        pytest.skip("a send test: the daemon does not list send_mail (ALLOW_SEND)")
    return guard.owned.address
