"""Tier policy: the three capability tiers as one module (GATE-03).

read → write (``@_write_tool``/``@_additive_tool``, skipped by ``read_only()``) →
outbound (``@_send_tool``, admitted only when ``allow_send(adapter)`` says so).
Consumers import DOWN into this module (``server.py``, ``doctor.py``) — nothing
here imports ``server`` or ``doctor``.

Registration happens at package import (tools are defined at module level in
``server.py``), so every gate below reads a PROCESS-START fact — an environment
variable, argv — never a flag set later in ``daemon.serve()``. Setting
``MACOS_APPS_READ_ONLY``/``MACOS_APPS_ALLOW_SEND`` after the process has already
imported ``server`` has no effect; they must be set before launch.

The outbound ledger below (``_SEND_ADAPTERS``, ``_SEND_REGISTERED``,
``admit_send``, ``outbound_status``) is PROVISIONAL: card 2 (the one
registration record per tool, GATE-04) makes ``registry.py`` the sole ledger
owner and this module goes back to holding only the pure gate predicates
(``read_only``, ``allow_send``).
"""

from __future__ import annotations

import os

from . import deploy


def read_only() -> bool:
    """True when MACOS_APPS_READ_ONLY is set; writes are then not registered.

    Reads the environment on every call. The write decorators consult it at
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


# --- provisional outbound ledger (card 2 deletes this block, see module docstring) ---

# Every adapter name a `@_send_tool(...)` call below names (#130) — DERIVED at
# registration, never hand-maintained (the `_SNAPSHOT_SOURCES` rule): a new outbound
# adapter can't silently miss `doctor()`'s report by forgetting a second edit. Recorded
# BEFORE the gate check, so it lists every adapter CAPABLE of sending, not just the ones
# currently enabled — which is what makes doctor able to say "mail: off".
_SEND_ADAPTERS: set[str] = set()

# Adapters whose send tools actually GOT registered — the gate as it stood at import.
# `allow_send` re-reads env + toggle per call, so after `allow-send` flips the toggle
# without a daemon restart the two diverge; outbound_status() surfaces that (C6).
_SEND_REGISTERED: set[str] = set()


def admit_send(adapter: str) -> bool:
    """Records send capability for ``adapter``, then answers the registration gate
    (True = the tool should register) and records admission when it does. Replaces
    the two inline set updates ``server.py``'s ``_send_tool`` used to do itself."""
    _SEND_ADAPTERS.add(adapter)  # capability, not state — before the gate check
    if not allow_send(adapter):
        return False
    _SEND_REGISTERED.add(adapter)  # the gate was ON when this tool registered
    return True


def outbound_status() -> dict[str, list[str]]:
    """The two outbound facts that can DISAGREE (C6): ``registered`` = the adapters
    whose tools actually got registered at import; ``configured`` = what the env/toggle
    enables RIGHT NOW. They diverge when ``macos-apps-mcp allow-send`` writes the toggle
    but the daemon keeps running (deploy's "no daemon restarted" branch) — doctor
    reports the delta as ``outbound_pending`` with a restart directive.

    A third key, ``capable`` (= every adapter a ``@_send_tool`` names), was carried here
    and read by nothing; ``_SEND_ADAPTERS`` is right there for whoever needs it. Add it
    back when a second send adapter gives it a job."""
    return {
        "registered": sorted(_SEND_REGISTERED),
        "configured": sorted(a for a in _SEND_ADAPTERS if allow_send(a)),
    }
