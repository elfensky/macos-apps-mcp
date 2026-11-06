"""The single arbiter of every device-suite call to the installed daemon.

``refusal`` is a pure decision: it names the rule a call breaks, or returns ``None``.
``Guard`` is the thin session around it: it keeps what this run owns (test containers,
created items, its mail, receipts and drafts) and is the only way a device test calls
a tool. A refusal is an ``AssertionError`` raised BEFORE the call.
"""

from __future__ import annotations

import asyncio
import subprocess
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from fastmcp import Client

import macos_apps_mcp.server  # noqa: F401 — its decorators fill registry.TOOLS
from macos_apps_mcp import daemon, registry

TEST_CONTAINER = "macos-apps-mcp-test"  # the test calendar and the test reminder list
_EVENTKIT_ITEM = {"update_event", "delete_event", "update_reminder", "delete_reminder"}
# The container argument of an update: a named container moves the item there.
_MOVES_TO = {"update_event": "calendar", "update_reminder": "list_name"}
# Read tier, but they build an index file: no device test may start one.
_INDEX_BUILDERS = {"mail_index_bodies", "mail_index_ids"}
# BatchMode: a key logs in, or the call fails. It never waits for a password.
SSH = ("ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10")


@dataclass
class Owned:
    """What this run may write. Every set starts empty; only the Guard fills it."""

    marker: str
    address: str | None = None
    containers: set[str] = field(default_factory=set)
    items: set[str] = field(default_factory=set)
    sent: set[str] = field(default_factory=set)
    mail: set[str] = field(default_factory=set)
    receipts: set[str] = field(default_factory=set)
    drafts: set[str] = field(default_factory=set)


def _titled(args: dict, owned: Owned) -> bool:
    return str(args.get("title") or "").startswith(owned.marker)


def _own_recipient(args: dict, owned: Owned) -> bool:
    return (
        bool(owned.address)
        and args.get("to") == owned.address
        and not args.get("cc")
        and not args.get("bcc")
    )


def refusal(tool: str, args: dict, tier: str | None, owned: Owned) -> str | None:
    """The rule ``tool(**args)`` breaks, or ``None`` when the call is allowed."""
    if tier == "read":
        if tool in _INDEX_BUILDERS:
            return "an index builder writes a sidecar file"
        if tool == "doctor" and args.get("request"):
            return "doctor(request=True) opens permission prompts"
        return None
    if tool == "create_event":
        if args.get("calendar") in owned.containers and _titled(args, owned):
            return None
        return "only in the test calendar, with a title that starts with the marker"
    if tool == "create_reminder":
        if args.get("list_name") in owned.containers and _titled(args, owned):
            return None
        return "only in the test list, with a title that starts with the marker"
    if tool == "create_reminder_list":
        if args.get("name") == TEST_CONTAINER:
            return None
        return f"only the list named {TEST_CONTAINER}"
    if tool in _EVENTKIT_ITEM:
        moves_to = args.get(_MOVES_TO.get(tool, ""))
        if args.get("id") in owned.items and (
            moves_to is None or moves_to in owned.containers
        ):
            return None
        return "only an id that this session created, and only into a test container"
    if tool == "send_mail":
        if (
            _own_recipient(args, owned)
            and not args.get("draft_id")
            and str(args.get("subject") or "").startswith(owned.marker)
        ):
            return None
        return (
            "only to the own address, no cc, no bcc, no draft_id, "
            "a subject that starts with the marker"
        )
    if tool == "forward_mail":
        if _own_recipient(args, owned) and args.get("message_id") in owned.sent:
            return None
        return "only to the own address, no cc, no bcc, a message this session sent"
    if tool == "trash_mail":
        ids = [i.strip() for i in str(args.get("ids") or "").split(",") if i.strip()]
        if ids and all(i in owned.mail for i in ids):
            return None
        return "only messages that this session found by its marker"
    if tool == "mail_undo":
        if args.get("receipt") in owned.receipts:
            return None
        return "only a receipt that this session produced"
    if tool == "delete_draft":
        if args.get("id") in owned.drafts:
            return None
        return "only a draft that this session found by its marker"
    return "no rule allows this write tool"


class Guard:
    """One device-test session: the owned state plus the only door to the daemon."""

    def __init__(
        self, socket: Path, marker: str, address: str | None, host: str | None = None
    ) -> None:
        self.socket = socket
        self.host = host  # an ssh destination, when another Mac owns the daemon
        self.owned = Owned(marker=marker, address=address)
        self._client: Client | None = None

    @property
    def marker(self) -> str:
        return self.owned.marker

    def on_device(self, *command: str) -> subprocess.CompletedProcess[str]:
        """Run ``command`` on the Mac that owns the daemon: here, or over SSH."""
        argv = [*SSH, self.host, *command] if self.host else list(command)
        return subprocess.run(argv, capture_output=True, text=True)

    @asynccontextmanager
    async def connect(self):
        async with Client(daemon.build_shim(self.socket)) as client:
            self._client = client
            try:
                yield self
            finally:
                self._client = None

    def run(self, tool: str, **args):
        """One call on its own connection, for a plain (sync) test."""

        async def go():
            async with self.connect():
                return await self.call(tool, **args)

        return asyncio.run(go())

    async def tool_names(self) -> set[str]:
        return {t.name for t in await self._client.list_tools()}

    async def call(self, tool: str, **args):
        """``(is_error, data, error_text, seconds)``; refuses first. Show at most
        ``error_text[:200]`` in a message."""
        rec = registry.TOOLS.get(tool)
        why = refusal(tool, args, rec.tier if rec else None, self.owned)
        if why:
            raise AssertionError(f"device guard refused {tool}: {why}")
        t = time.monotonic()
        r = await self._client.call_tool(tool, args, raise_on_error=False)
        secs = round(time.monotonic() - t, 3)
        data = r.structured_content
        if isinstance(data, dict) and set(data) == {"result"}:
            data = data["result"]
        text = ""
        if r.is_error:
            text = " ".join(getattr(b, "text", "") or "" for b in r.content or [])
        if not r.is_error:
            self._record(tool, data)
        return bool(r.is_error), data, text, secs

    def _record(self, tool: str, data) -> None:
        if not isinstance(data, dict):
            return
        if tool == "create_reminder_list" and data.get("id"):
            self.owned.containers.add(data["id"])
        elif tool in {"create_event", "create_reminder"} | _EVENTKIT_ITEM:
            if data.get("id") and not tool.startswith("delete_"):
                self.owned.items.add(data["id"])  # an update may change the id
        elif tool in {"trash_mail", "mail_undo"} and data.get("receipt"):
            self.owned.receipts.add(data["receipt"])

    def _marked(self, row) -> bool:
        if not isinstance(row, dict) or not row.get("id"):
            return False
        return self.marker in f"{row.get('subject') or ''} {row.get('summary') or ''}"

    def adopt_container(self, row: dict) -> None:
        """A test calendar or list found by its exact name."""
        if row.get("summary") == TEST_CONTAINER and row.get("id"):
            self.owned.containers.add(row["id"])

    def adopt_mail(self, rows, *, sent: bool = False) -> list[dict]:
        """Own the rows that carry this run's marker; return only those."""
        mine = [r for r in rows or [] if self._marked(r)]
        for r in mine:
            self.owned.mail.add(r["id"])
            if sent:
                self.owned.sent.add(r["id"])
        return mine

    def adopt_drafts(self, rows) -> list[dict]:
        mine = [r for r in rows or [] if self._marked(r)]
        self.owned.drafts.update(r["id"] for r in mine)
        return mine
