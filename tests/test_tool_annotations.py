"""#57: every registered tool is annotated (readOnlyHint/destructiveHint) from the
read/write seam, and its docstring states read-only-vs-side-effect + which macOS
permission it needs. The permission map is checked against the live tool list, so adding
a tool without classifying it fails here.
"""

from __future__ import annotations

import ast
import asyncio
import inspect

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
        "create_mailbox",
        "save_mail_attachment",
        "export_mail",
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
        "move_mail",
        "trash_mail",
        "mail_undo",
        "update_mail_status",
        "send_mail",
        "reply_all",
        "forward_mail",
    }
)
# The full write half of the read/write seam. Everything else is read-only.
_WRITE_TOOLS = _ADDITIVE_TOOLS | _DESTRUCTIVE_TOOLS

# The permission keyword(s) each tool's docstring must name — a tuple when the tool
# needs more than one grant (None = meta tool, no keyword).
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
    "mail_index_bodies": "Automation",
    "mail_thread": "Full Disk Access",
    # counts are sqlite (FDA), account NAMES go through osascript — which launches
    # Mail — so this tool genuinely needs both and must say both.
    "mail_overview": ("Full Disk Access", "Automation"),
    # account= as a display NAME is resolved through Mail, and the AppleScript inbox
    # search is still the drift fallback; the index itself is read at rest under FDA.
    "mail_search": ("Full Disk Access", "Automation"),
    "create_draft": "Automation",
    "mail_reply": "Automation",
    "drafts": "Automation",
    "delete_draft": "Automation",
    "create_mailbox": ("Automation", "Full Disk Access"),
    # #85: pure sqlite over the Envelope Index — never launches Mail.
    "mail_stats": "Full Disk Access",
    # #85: the message bytes are read AT REST; nothing here talks to Mail.
    "export_mail": "Full Disk Access",
    # #81: the save is Automation; resolving a bare message_id is the index (FDA).
    "save_mail_attachment": ("Automation", "Full Disk Access"),
    # the move is Automation; locating each message's .emlx for the #159 backup is FDA.
    "move_mail": ("Automation", "Full Disk Access"),
    # the delete is Automation; the #159 backup + the account's Trash url are FDA.
    "trash_mail": ("Automation", "Full Disk Access"),
    "mail_undo": ("Automation", "Full Disk Access"),
    # pure sqlite over the Envelope Index — never launches Mail.
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


def test_run_shortcut_carries_open_world_hint():
    # C6c: a shortcut can reach off-machine (post to a webhook), so run_shortcut
    # carries openWorldHint — but it stays in the destructive write tier, NOT the send
    # tier: most shortcuts are local ("unknown world" is the honest label), and the
    # send tier would silently unregister the tool for every existing user.
    by_name = {t.name: t for t in _tools()}
    assert by_name["run_shortcut"].annotations.openWorldHint is True


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
        if keyword is None:
            continue
        # A tuple means the tool needs SEVERAL grants (e.g. sqlite counts under Full
        # Disk Access plus an osascript label lookup under Automation) — the docstring
        # has to name every one of them, not just the cheapest.
        for kw in (keyword,) if isinstance(keyword, str) else keyword:
            assert kw.lower() in doc.lower(), (
                f"{t.name} docstring must name its permission ({kw!r})"
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
        "create_mailbox",
        "save_mail_attachment",
        "export_mail",
        "move_mail",
        "trash_mail",
        "mail_undo",
        "update_mail_status",
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


# #159: a destructive MAIL write either rides the recoverable plane (backup → log →
# act, with an undo) or is one of these documented exemptions. Each exemption is a
# reason, not an oversight:
#   delete_draft        an unsent draft has no server copy and no bytes worth
#                       preserving; it is a single-target write with its own preview.
#   update_mail_status  flips two booleans and an integer. Re-issuing it with the
#                       opposite value IS the undo, so a backup directory per flag flip
#                       would be ceremony, not safety.
#   send/reply_all/forward  past the `send` verb there is no rollback at all
#                       (device-verified #135) — which is why they are the OUTBOUND
#                       tier, gated separately, rather than recoverable writes.
_PLANE_EXEMPT = frozenset(
    {"delete_draft", "update_mail_status", "send_mail", "reply_all", "forward_mail"}
)
_RECOVERABLE_MAIL_TOOLS = frozenset({"move_mail", "trash_mail", "mail_undo"})


def _mail_tools() -> set[str]:
    """Tool names in server.py that dispatch to the mail adapter — DERIVED from the
    dispatch bodies, never hand-listed, so a new mail tool cannot skip the check below
    by being forgotten in a set."""
    tree = ast.parse(inspect.getsource(srv))
    return {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and "_mail." in ast.unparse(node)
    }


def test_every_destructive_mail_write_is_recoverable_or_documented_as_exempt():
    # The registration-guard pattern (#159, mirroring _send_tool): a new destructive
    # mail write fails HERE unless it is declared to ride the plane or exempted with a
    # reason — rather than silently shipping a mail write with no backup and no undo.
    destructive_mail = _mail_tools() & _DESTRUCTIVE_TOOLS
    assert destructive_mail == _RECOVERABLE_MAIL_TOOLS | _PLANE_EXEMPT, (
        "destructive mail tools not classified against the recoverable plane: "
        f"{destructive_mail ^ (_RECOVERABLE_MAIL_TOOLS | _PLANE_EXEMPT)}"
    )
    assert not (_RECOVERABLE_MAIL_TOOLS & _PLANE_EXEMPT)


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
