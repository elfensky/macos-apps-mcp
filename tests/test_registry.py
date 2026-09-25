"""GATE-04/GATE-06: one registration record per tool.

Each test pins one property of the ``registry.TOOLS`` record store: the live FastMCP
tool list equals exactly the registered records (in every capability-gate mode), a
duplicate name at import is a bug, an unprefixed write must state its verb explicitly
(no silent "write" fallback), and the GATE-06 audit-verb map holds for the twelve
tools CONTEXT.md names.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys

import pytest
from fastmcp import Client

import macos_apps_mcp.registry as reg
import macos_apps_mcp.server as srv
import macos_apps_mcp.tiers as tiers


def _live() -> set[str]:
    async def _run():
        async with Client(srv.mcp) as c:
            return {t.name for t in await c.list_tools()}

    return asyncio.run(_run())


def _subprocess_registry_snapshot(env_extra: dict[str, str]) -> dict:
    """Run a fresh interpreter with ``env_extra`` set BEFORE import — the only way to
    exercise the import-time registration gate (MACOS_APPS_READ_ONLY /
    MACOS_APPS_ALLOW_SEND are read once, at module import)."""
    code = (
        "import asyncio, json; "
        "import macos_apps_mcp.server as srv, macos_apps_mcp.registry as reg; "
        "from fastmcp import Client\n"
        "async def _run():\n"
        "    async with Client(srv.mcp) as c:\n"
        "        return sorted(t.name for t in await c.list_tools())\n"
        "print(json.dumps({"
        "'tools': asyncio.run(_run()), "
        "'registered': sorted(n for n, r in reg.TOOLS.items() if r.registered), "
        "'all_recorded': sorted(reg.TOOLS)}))"
    )
    env = {"PATH": "/usr/bin:/bin", "HOME": os.environ["HOME"], **env_extra}
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_fastmcp_lists_exactly_the_registered_records():
    # default (this process): the live FastMCP list equals the registered records.
    live = _live()
    registered = {n for n, r in reg.TOOLS.items() if r.registered}
    assert registered == live
    # gated-off outbound tools are still RECORDED — never simply absent (GATE-04's
    # elevation-of-privilege mitigation, and what lets doctor say "mail: off").
    # Robust to MACOS_APPS_ALLOW_SEND=mail already being set in THIS process,
    # mirroring test_tool_annotations.py's convention.
    send_gate_on = tiers.allow_send("mail")
    for name in ("send_mail", "reply_all", "forward_mail"):
        assert name in reg.TOOLS
        assert reg.TOOLS[name].registered is send_gate_on

    # MACOS_APPS_ALLOW_SEND=mail: the outbound tools also register.
    got_send = _subprocess_registry_snapshot({"MACOS_APPS_ALLOW_SEND": "mail"})
    assert got_send["tools"] == got_send["registered"]
    assert {"send_mail", "reply_all", "forward_mail"} <= set(got_send["tools"])

    # MACOS_APPS_READ_ONLY=1: no write/send tool is LISTED, but every one is still
    # RECORDED (registered=False) — that is the whole point of the record.
    got_ro = _subprocess_registry_snapshot({"MACOS_APPS_READ_ONLY": "1"})
    assert got_ro["tools"] == got_ro["registered"]
    assert "create_event" not in got_ro["tools"]
    assert "send_mail" not in got_ro["tools"]
    assert "create_event" in got_ro["all_recorded"]
    assert "send_mail" in got_ro["all_recorded"]


def test_duplicate_registration_raises():
    # "ping" is already registered by the real server import above — registering it
    # again must raise, never silently overwrite (GATE-04 adjacency edge).
    dup = reg.ToolRecord(
        name="ping",
        tier="read",
        adapter=None,
        permission=(),
        audit_verb=None,
        notice=True,
        backup_notice=False,
        snapshot=None,
        open_world=False,
        registered=True,
        fn=lambda: None,
    )
    with pytest.raises(TypeError):
        reg.add(dup)


def test_unprefixed_write_without_verb_raises():
    with pytest.raises(TypeError):
        reg.derive_audit_verb("frobnicate", "destructive", None)


def test_no_record_carries_a_generic_write_verb():
    assert all(v != "write" for v in reg.audit_verbs().values())


def test_gate06_verbs():
    # CONTEXT.md's discretion note: the twelve writes with no create/update/delete/
    # complete prefix each carry an explicit, non-generic verb.
    want = {
        "export_mail": "export",
        "save_mail_attachment": "save",
        "mail_reply": "reply",
        "move_mail": "move",
        "trash_mail": "trash",
        "mail_undo": "undo",
        "run_shortcut": "action",
        "safari_open": "open",
        "music_control": "control",
        "play_playlist": "play",
        "set_volume": "set",
        "set_mode": "set",
    }
    for name, verb in want.items():
        assert reg.TOOLS[name].audit_verb == verb, name
