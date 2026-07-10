"""#57: every registered tool is annotated (readOnlyHint/destructiveHint) from the
read/write seam, and its docstring states read-only-vs-side-effect + which macOS
permission it needs. The permission map is checked against the live tool list, so adding
a tool without classifying it fails here.
"""

from __future__ import annotations

import asyncio

from fastmcp import Client

import mac_mcp.server as srv

# The write half of the read/write seam (@_write_tool). Everything else is read-only.
_WRITE_TOOLS = frozenset(
    {
        "create_reminder",
        "update_reminder",
        "complete_reminder",
        "create_event",
        "update_event",
        "delete_event",
        "delete_note",
        "create_contact",
        "run_shortcut",
        "safari_open",
    }
)

# The permission keyword each tool's docstring must name (None = meta tool, no keyword).
_PERMISSION = {
    "ping": None,
    "now": None,
    "doctor": None,
    "reminders": "EventKit",
    "events": "EventKit",
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
    "notes": "Automation",
    "notes_all": "Automation",
    "note_bodies": "Automation",
    "photos": "Automation",
    "messages_chats": "Automation",
    "safari_tabs": "Automation",
    "delete_note": "Automation",
    "create_contact": "Automation",
    "safari_open": "Automation",
    "shortcuts": "Shortcuts CLI",
    "run_shortcut": "Shortcuts CLI",
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
        # writes are conservatively marked destructive; reads are additive (not destr.)
        assert a.destructiveHint is (not expected_readonly), (
            f"{t.name} destructiveHint mismatch"
        )


def test_permission_map_matches_registered_tools():
    # a new tool that isn't classified here (read/write + permission) fails loudly.
    # Robust to MAC_MCP_READ_ONLY=1 (writes unregistered): only unclassified tools or a
    # missing READ tool are failures.
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
