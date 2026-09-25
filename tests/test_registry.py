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

import macos_apps_mcp.audit as au
import macos_apps_mcp.registry as reg
import macos_apps_mcp.server as srv
import macos_apps_mcp.tiers as tiers

# The hand tables exactly as they stood on develop before this plan (01-12) turned
# tests/test_tool_annotations.py's three hand tables into views over registry.TOOLS —
# frozen here as the pin, so that move changes no fact. Copied verbatim from that
# file's _ADDITIVE_TOOLS/_DESTRUCTIVE_TOOLS/_PERMISSION before editing it.
_DEVELOP_ADDITIVE = frozenset(
    {
        "create_reminder",
        "create_event",
        "create_contact",
        "safari_open",
        "create_draft",
        "mail_reply",
        "create_note",
        "create_mailbox",
        "save_mail_attachment",
        "export_mail",
        "music_control",
        "play_playlist",
        "set_volume",
        "set_mode",
    }
)
_DEVELOP_DESTRUCTIVE = frozenset(
    {
        "update_reminder",
        "complete_reminder",
        "update_event",
        "delete_event",
        "delete_note",
        "run_shortcut",
        "update_note",
        "delete_draft",
        "move_mail",
        "trash_mail",
        "mail_undo",
        "update_mail_status",
        "send_mail",
        "reply_all",
        "forward_mail",
    }
)
_DEVELOP_PERMISSION = {
    "ping": None,
    "now": None,
    "doctor": None,
    "audit": None,
    "usage": None,
    "reminders": "EventKit",
    "events": "EventKit",
    "free_busy": "EventKit",
    "reminder_lists": "EventKit",
    "calendars": "EventKit",
    "create_reminder": "EventKit",
    "update_reminder": "EventKit",
    "complete_reminder": "EventKit",
    "create_event": "EventKit",
    "update_event": "EventKit",
    "delete_event": "EventKit",
    "contacts": "Automation",
    "mail": "Automation",
    "mail_body": "Automation",
    "mail_bodies": "Full Disk Access",
    "mail_attachments": "Automation",
    "mail_needs_response": "Automation",
    "mail_awaiting_reply": "Automation",
    "mail_index_bodies": "Full Disk Access",
    "mail_index_ids": "Full Disk Access",
    "mail_thread": "Full Disk Access",
    "mail_overview": ("Full Disk Access", "Automation"),
    "mail_search": ("Full Disk Access", "Automation"),
    "create_draft": "Automation",
    "mail_reply": "Automation",
    "drafts": "Automation",
    "delete_draft": "Automation",
    "create_mailbox": ("Automation", "Full Disk Access"),
    "mail_stats": "Full Disk Access",
    "export_mail": "Full Disk Access",
    "save_mail_attachment": ("Automation", "Full Disk Access"),
    "move_mail": ("Automation", "Full Disk Access"),
    "trash_mail": ("Automation", "Full Disk Access"),
    "mail_undo": ("Automation", "Full Disk Access"),
    "mail_duplicates": "Full Disk Access",
    "update_mail_status": "Automation",
    "send_mail": "Automation",
    "reply_all": "Automation",
    "forward_mail": "Automation",
    "notes": "Automation",
    "notes_all": "Automation",
    "note_bodies": "Automation",
    "photos": "Automation",
    "messages_chats": "Automation",
    "messages_search": "Full Disk Access",
    "messages_with": "Full Disk Access",
    "message_body": "Full Disk Access",
    "safari_tabs": "Automation",
    "delete_note": "Automation",
    "create_note": "Automation",
    "update_note": "Automation",
    "create_contact": "Automation",
    "safari_open": "Automation",
    "shortcuts": "Shortcuts CLI",
    "run_shortcut": "Shortcuts CLI",
    "music_search": "Automation",
    "now_playing": "Automation",
    "music_control": "Automation",
    "play_playlist": "Automation",
    "set_volume": "Automation",
    "set_mode": "Automation",
}


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


def test_every_registered_write_has_its_own_verb():
    for name, r in reg.TOOLS.items():
        if r.is_write and r.registered:
            assert r.audit_verb, name
            assert r.audit_verb != "write", name


def test_audit_op_is_gone():
    assert not hasattr(au, "_audit_op")


def test_tier_reproduces_the_develop_era_additive_and_destructive_sets():
    # Card 2 (GATE-04): test_tool_annotations.py's _ADDITIVE_TOOLS/_DESTRUCTIVE_TOOLS
    # became views over registry.TOOLS in this plan — pin them against the tables as
    # they stood on develop BEFORE that move, so the move changes no fact.
    additive = {n for n, r in reg.TOOLS.items() if r.tier == "additive"}
    destructive = {n for n, r in reg.TOOLS.items() if r.tier in ("destructive", "send")}
    assert additive == _DEVELOP_ADDITIVE
    assert destructive == _DEVELOP_DESTRUCTIVE


def test_permission_reproduces_the_develop_era_hand_map():
    # Same pin for the 65-entry permission map — registry.ToolRecord.permission
    # normalises a single grant to a 1-tuple and "none" (a meta tool) to ().
    want = {
        n: (() if p is None else (p,) if isinstance(p, str) else tuple(p))
        for n, p in _DEVELOP_PERMISSION.items()
    }
    got = {n: r.permission for n, r in reg.TOOLS.items()}
    assert got == want


def test_meta_tools_have_no_adapter_permission_or_notice():
    # ping/now/doctor/usage make no native call and return no user-store content — no
    # adapter, no permission, and exempt from the untrusted-data notice. audit DOES
    # carry the notice: its entries embed (truncated) user-store args (#53).
    for name in ("ping", "now", "doctor", "usage"):
        r = reg.TOOLS[name]
        assert r.adapter is None, name
        assert r.permission == (), name
        assert r.notice is False, name
    r = reg.TOOLS["audit"]
    assert r.adapter is None
    assert r.permission == ()
    assert r.notice is True


def test_every_other_tool_names_its_adapter():
    # GATE-04: every tool except the five meta tools declares adapter= at its call
    # site — a new tool that dispatches to an adapter but forgets adapter= fails here.
    meta = {"ping", "now", "doctor", "usage", "audit"}
    for name, r in reg.TOOLS.items():
        if name in meta:
            continue
        assert r.adapter is not None, f"{name}: no adapter= declared"


def test_create_contact_is_logged_with_its_verb(monkeypatch):
    from macos_apps_mcp.contracts import ContactData, Pointer

    class _FakeContacts:
        def create_contact(self, data: ContactData) -> Pointer:
            return Pointer(id="C-9", summary="s", deeplink="d")

    monkeypatch.setattr(srv, "_contacts", _FakeContacts())
    records = []
    monkeypatch.setattr(au, "audit_write", records.append)
    monkeypatch.setattr(au, "usage_log", lambda tool: None)

    async def _run():
        async with Client(srv.mcp) as c:
            return await c.call_tool("create_contact", {"given_name": "Jane"})

    asyncio.run(_run())
    assert len(records) == 1
    assert records[0]["tool"] == "create_contact"
    assert records[0]["op"] == "create"
