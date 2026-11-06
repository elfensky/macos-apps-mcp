"""Fixtures of the device suite: the real socket, the three switches, the Guard.

The suite-wide ``_isolated_state`` points ``MACOS_APPS_MCP_SOCKET`` at a temporary
path, so ``daemon.socket_path()`` is NOT the real socket here. The real one is named
by ``MACOS_APPS_DEVICE_SOCKET``; every other home path stays isolated.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest

from tests.device.guard import Guard

MARKER = f"macos-apps-mcp device {time.strftime('%Y%m%d-%H%M%S')}"


def _socket() -> Path:
    raw = os.environ.get("MACOS_APPS_DEVICE_SOCKET")
    return Path(raw or "~/.local/state/macos-apps-mcp/daemon/mcp.sock").expanduser()


@pytest.fixture(scope="session")
def guard() -> Guard:
    path = _socket()
    if not path.exists():
        pytest.skip(f"no daemon socket at {path} (set MACOS_APPS_DEVICE_SOCKET)")
    return Guard(path, MARKER, os.environ.get("MACOS_APPS_TEST_ADDRESS") or None)


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
