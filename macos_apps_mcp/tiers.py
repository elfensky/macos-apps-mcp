"""Tier policy: the three capability tiers as one module (GATE-03).

read → write (``@_write_tool``/``@_additive_tool``, skipped by ``read_only()``) →
outbound (``@_send_tool``, admitted only when ``allow_send(adapter)`` says so).
Consumers import DOWN into this module (``server.py``, ``doctor.py``, ``registry.py``)
— nothing here imports ``server``, ``doctor`` or ``registry``.

Registration happens at package import (tools are defined at module level in
``server.py``), so every gate below reads a PROCESS-START fact — an environment
variable, argv — never a flag set later in ``daemon.serve()``. Setting
``MACOS_APPS_READ_ONLY``/``MACOS_APPS_ALLOW_SEND`` after the process has already
imported ``server`` has no effect; they must be set before launch.

Card 2 (GATE-04, RESEARCH Pitfall 3): the provisional outbound-capability tracking
that used to live here is gone — ``registry.py`` is the sole ledger owner now
(``registry.outbound_status()``, a view over the send records already sitting in
``registry.TOOLS``). This module holds only the pure gate predicates.
"""

from __future__ import annotations

import os

from . import deploy


def read_only() -> bool:
    """True when MACOS_APPS_READ_ONLY is set; writes are then not registered.

    Reads the environment on every call. The write decorators below consult it at
    registration time — which is module import, since tools are defined at module
    level — so set the variable before launching the server process.
    """
    val = os.environ.get("MACOS_APPS_READ_ONLY", "").strip().lower()
    return val in ("1", "true", "yes")


def allow_send(adapter: str) -> bool:
    """True when OUTBOUND is enabled for ``adapter`` (#104).

    ``MACOS_APPS_ALLOW_SEND`` is unset by default — "never sends" stays the default,
    but absence is a GATE, not a ceiling. ``1``/``true``/``yes``/``all`` enable every
    adapter; a comma list (``mail,messages``) enables named ones, so a user can accept
    Mail send (reviewable, leaves a Sent record) while refusing iMessage send (instant,
    social, no undo). ``MACOS_APPS_READ_ONLY`` wins unconditionally — it is the
    safe-deploy guard. Read at registration time, like ``read_only()``: set it before
    launching the server.

    Under the DAEMON only, an unset env var falls back to the persisted toggle
    (``macos-apps-mcp allow-send mail``) — no env var can reach a launchd-run daemon
    from a client config (#130), so on-disk state is the only way to opt in there. In
    stdio mode the env var is reachable and is the whole story, which also keeps the
    test suite hermetic: it never reads this machine's toggle file.

    "Am I the daemon?" goes through ``deploy.is_daemon_role()``, which reads argv —
    NOT the ``MACOS_APPS_MCP_ROLE`` env var alone. That var is set by ``daemon.serve()``
    long after ``macos_apps_mcp/__init__.py`` has already imported this module and run
    every registration, so reading it here meant the daemon's outbound tier could never
    register no matter what the toggle said. See that function.
    """
    if read_only():
        return False
    val = os.environ.get("MACOS_APPS_ALLOW_SEND", "")
    if not val and deploy.is_daemon_role():
        val = deploy.allow_send_file()
    val = val.strip().lower()
    if val in ("1", "true", "yes", "all"):
        return True
    return adapter in {p.strip() for p in val.split(",") if p.strip()}
