"""#57: every registered tool is annotated (readOnlyHint/destructiveHint) from the
read/write seam, and its docstring states read-only-vs-side-effect + which macOS
permission it needs. The permission map is checked against the live tool list, so adding
a tool without classifying it fails here.
"""

from __future__ import annotations

import asyncio

from fastmcp import Client

import macos_apps_mcp.server as srv

# Writes that only ADD a new item (create/open) — not read-only, but not destructive.
_ADDITIVE_TOOLS = frozenset(
    {
        "create_reminder",
        "create_event",
        "create_contact",
        "safari_open",
        "create_draft",
        "mail_reply",
        "create_note",
        "music_control",
        "play_playlist",
        "set_volume",
        "set_mode",
    }
)
# Writes that modify/overwrite/delete existing state, or run arbitrary automation.
_DESTRUCTIVE_TOOLS = frozenset(
    {
        "update_reminder",
        "complete_reminder",
        "update_event",
        "delete_event",
        "delete_note",
        "run_shortcut",
        "update_note",
        "delete_draft",
        "send_mail",
        "reply_all",
        "forward_mail",
    }
)
# The full write half of the read/write seam. Everything else is read-only.
_WRITE_TOOLS = _ADDITIVE_TOOLS | _DESTRUCTIVE_TOOLS

# The permission keyword each tool's docstring must name (None = meta tool, no keyword).
_PERMISSION = {
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
    "mail_attachments": "Automation",
    "mail_needs_response": "Automation",
    "mail_awaiting_reply": "Automation",
    "mail_search": "Automation",
    "mail_index_bodies": "Automation",
    "mail_thread": "Full Disk Access",
    "mail_overview": "Full Disk Access",
    "create_draft": "Automation",
    "mail_reply": "Automation",
    "drafts": "Automation",
    "delete_draft": "Automation",
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


def _tools():
    async def _run():
        async with Client(srv.mcp) as c:
            return await c.list_tools()

    return asyncio.run(_run())


def test_every_tool_is_annotated_from_the_read_write_seam():
    for t in _tools():
        a = t.annotations
        assert a is not None, f"{t.name} has no annotations"
        assert isinstance(a.readOnlyHint, bool), f"{t.name} readOnlyHint not set"
        expected_readonly = t.name not in _WRITE_TOOLS
        assert a.readOnlyHint is expected_readonly, (
            f"{t.name} readOnlyHint={a.readOnlyHint}, expected {expected_readonly}"
        )
        # reads + additive writes (create/open) are non-destructive; only
        # modify/overwrite/delete/run-automation tools are destructive (#57).
        want_destructive = t.name in _DESTRUCTIVE_TOOLS
        assert a.destructiveHint is want_destructive, (
            f"{t.name} destructiveHint={a.destructiveHint}, want {want_destructive}"
        )


def test_permission_map_matches_registered_tools():
    # a new tool that isn't classified here (read/write + permission) fails loudly.
    # Robust to MACOS_APPS_READ_ONLY=1 (writes unregistered): only unclassified tools
    # or a missing READ tool are failures.
    live = {t.name for t in _tools()}
    unclassified = live - set(_PERMISSION)
    assert not unclassified, (
        f"tools with no read/write + permission class: {unclassified}"
    )
    missing = set(_PERMISSION) - live
    assert missing <= _WRITE_TOOLS, f"read tool(s) missing from registration: {missing}"


def test_every_tool_docstring_states_permission_and_is_nontrivial():
    for t in _tools():
        doc = t.description or ""
        assert len(doc) > 20, f"{t.name} docstring is too thin"
        keyword = _PERMISSION[t.name]
        if keyword is not None:
            assert keyword.lower() in doc.lower(), (
                f"{t.name} docstring must name its permission ({keyword!r})"
            )


def test_every_write_tool_is_audit_classified():
    import macos_apps_mcp.server as srv

    # writes with no id-addressed before-state: creates + non-id actions
    envelope_only = {
        "create_reminder",
        "create_event",
        "create_note",
        "create_contact",
        "create_draft",
        "mail_reply",
        "safari_open",
        "run_shortcut",
        "music_control",
        "play_playlist",
        "set_volume",
        "set_mode",
    }
    if srv._allow_send("mail"):
        envelope_only |= {"send_mail", "reply_all", "forward_mail"}
    assert set(srv._SNAPSHOT_SOURCES) | envelope_only == srv._WRITE_TOOLS


def test_send_tools_registered_only_when_gate_is_on():
    # "Never sends" is the default: with MACOS_APPS_ALLOW_SEND unset, the outbound
    # tools are not registered at all — absent, not erroring. Consistent with
    # test_every_write_tool_is_audit_classified's convention (F6 review): rather than
    # skipping this test under the gate into uselessness, assert the tools ARE
    # registered when the operator opted in — this is exactly the scenario
    # `MACOS_APPS_ALLOW_SEND=mail uv run pytest` must exercise and pass.
    live = {t.name for t in _tools()}
    send_tools = {"send_mail", "reply_all", "forward_mail"}
    if srv._allow_send("mail"):
        assert send_tools <= live
    else:
        assert not (send_tools & live)
