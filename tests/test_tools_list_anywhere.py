"""The one test the Linux CI job runs: the server starts and lists its tools anywhere.

Glama's build test starts the server in a Linux container and reads ``tools/list``. This
test does the same: it launches the server as a subprocess over stdio, runs the MCP
handshake and compares the listed names with the registered records of
``registry.TOOLS``. On Linux the child is the plain ``python -m macos_apps_mcp``; on
macOS it skips only the EventKit bootstrap, so a unit test never waits on a TCC prompt.
"""

from __future__ import annotations

import asyncio
import os
import sys

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

import macos_apps_mcp.registry as reg
import macos_apps_mcp.server  # noqa: F401  (registers the tools in this process)


def _listed_by_a_real_start() -> set[str]:
    # The child must see the same gates (READ_ONLY / ALLOW_SEND) as this process; the
    # transport passes only a small safe environment unless it is given the whole one.
    args = ["-m", "macos_apps_mcp"]
    if sys.platform == "darwin":
        # A unit test never touches EventKit: skip the startup TCC request, which can
        # block on a consent prompt. Off macOS bootstrap() is a no-op, so the start is
        # unmodified there.
        args = [
            "-c",
            "import macos_apps_mcp.server as s; s.bootstrap = lambda: None; s.main()",
        ]
    transport = StdioTransport(command=sys.executable, args=args, env=dict(os.environ))

    async def _run() -> set[str]:
        async with Client(transport) as c:
            return {t.name for t in await c.list_tools()}

    # A server that hangs before it answers must fail the job, not stall it.
    return asyncio.run(asyncio.wait_for(_run(), timeout=60))


def test_tools_list_matches_the_registry():
    expected = {n for n, r in reg.TOOLS.items() if r.registered}
    assert expected
    assert _listed_by_a_real_start() == expected
