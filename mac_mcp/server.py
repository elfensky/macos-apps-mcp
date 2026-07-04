"""mac-mcp — FastMCP server.

Tools are *thin dispatch* to adapters (see contracts.py). Set MAC_MCP_READ_ONLY=1 to
register reads only (the destructive write tools are skipped) — a safe-deploy guard.
"""

from __future__ import annotations

import functools
import os
from datetime import datetime

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from .adapters.calendar import CalendarAdapter
from .adapters.contacts import ContactsAdapter
from .adapters.mail import MailAdapter
from .adapters.messages import MessagesAdapter
from .adapters.notes import NotesAdapter
from .adapters.photos import PhotosAdapter
from .adapters.reminders import RemindersAdapter
from .adapters.safari import SafariAdapter
from .adapters.shortcuts import ShortcutsAdapter
from .contracts import (
    CalendarEventData,
    ContactData,
    Pointer,
    Recurrence,
    ReminderData,
    now_local,
    parse_datetime,
)
from .doctor import diagnose
from .runtime import NativeError

mcp = FastMCP("mac-mcp")

_reminders = RemindersAdapter()
_calendar = CalendarAdapter()
_contacts = ContactsAdapter()
_mail = MailAdapter()
_notes = NotesAdapter()
_safari = SafariAdapter()
_photos = PhotosAdapter()
_messages = MessagesAdapter()
_shortcuts = ShortcutsAdapter()


def _emit(p: Pointer) -> dict[str, str]:
    d = {"id": p.id, "summary": p.summary, "deeplink": p.deeplink}
    if p.folder is not None:
        d["folder"] = p.folder
    return d


def _read_only() -> bool:
    """True when MAC_MCP_READ_ONLY is set; writes are then not registered."""
    val = os.environ.get("MAC_MCP_READ_ONLY", "").strip().lower()
    return val in ("1", "true", "yes")


def _guard(fn):
    """Convert a typed native failure into a loud, agent-directed tool result (#47).

    Errors-as-results, never exceptions through the protocol: a ``NativeError`` becomes
    a FastMCP ``ToolError`` carrying the remediation directive, so the model sees an
    ``isError`` result with *what to do* — never a masked stack trace, and never an
    empty list masquerading as "no matches". A real empty result stays a plain ``[]``.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except NativeError as e:
            raise ToolError(str(e)) from e

    return wrapper


def _read_tool(fn):
    """Register a read tool, wrapped so typed native failures surface as directives."""
    return mcp.tool()(_guard(fn))


def _write_tool(fn):
    """Register a destructive tool — skipped in read-only mode (safe-deploy guard)."""
    return fn if _read_only() else mcp.tool()(_guard(fn))


@mcp.tool()
def ping() -> str:
    """Health check — confirms mac-mcp is alive (no native call, so never guarded)."""
    return "mac-mcp ok"


@_read_tool
def doctor(request: bool = False) -> dict:
    """Diagnose per-surface macOS permissions + health with exact remediation.

    Read-only and prompt-free by default. `request=True` also triggers permission
    prompts (EventKit consent + per-app Automation probes) — use it once to grant.
    """
    return diagnose(request=request)


@mcp.tool()
def now() -> dict:
    """Current local date, time, timezone, UTC offset, and weekday.

    Call this FIRST to ground any relative date ("today", "tomorrow", "next Friday") —
    never guess the date from memory. Every date parameter on the write tools is
    interpreted in THIS timezone (naive ISO = local time).
    """
    return now_local()


@_read_tool
def reminders(due: str = "today") -> list[dict]:
    """List reminders as pointers. `due`: today | overdue | this-week | a list name."""
    return [_emit(p) for p in _reminders.get_pointers(due)]


@_read_tool
def events(when: str = "today") -> list[dict]:
    """List calendar events as pointers. `when`: today | week | YYYY-MM-DD."""
    return [_emit(p) for p in _calendar.get_pointers(when)]


@_read_tool
def reminder_lists() -> list[dict]:
    """List reminder lists as pointers (id + name); use a name to target writes."""
    return [_emit(p) for p in _reminders.get_lists()]


@_read_tool
def calendars() -> list[dict]:
    """List calendars as pointers (id + name); use a name to target writes."""
    return [_emit(p) for p in _calendar.get_calendars()]


@_read_tool
def contacts(name: str) -> list[dict]:
    """Find contacts by name (substring). Returns pointers (id + name/org)."""
    return [_emit(p) for p in _contacts.get_pointers(name)]


@_read_tool
def mail(subject: str) -> list[dict]:
    """Search the Mail inbox by subject substring. Pointers (id + subject/sender)."""
    return [_emit(p) for p in _mail.get_pointers(subject)]


@_read_tool
def notes(title: str) -> list[dict]:
    """Search Notes by title substring. Returns pointers (id + title)."""
    return [_emit(p) for p in _notes.get_pointers(title)]


@_read_tool
def notes_all() -> list[dict]:
    """List every note as pointers (id + "Account / Folder" + title), excluding
    Recently Deleted. No cap; very large libraries can hit the osascript timeout
    (all-or-nothing)."""
    return [_emit(p) for p in _notes.get_all()]


@_read_tool
def note_bodies(ids: list[str]) -> list[dict]:
    """Hydrate plaintext bodies for up to 50 note ids (opt-in; search stays
    pointer-only). Returns [{"id", "body"}]; unknown ids are silently skipped."""
    return _notes.get_bodies(ids)


@_read_tool
def safari_tabs() -> list[dict]:
    """List open Safari tabs as pointers (url + title)."""
    return [_emit(p) for p in _safari.get_tabs()]


@_read_tool
def photos(query: str) -> list[dict]:
    """Search Photos (filename, place, date). Returns pointers (id + filename)."""
    return [_emit(p) for p in _photos.get_pointers(query)]


@_read_tool
def messages_chats() -> list[dict]:
    """List Messages conversations (id + name). No content; sending isn't supported."""
    return [_emit(p) for p in _messages.get_chats()]


@_read_tool
def shortcuts(name: str = "") -> list[dict]:
    """List/search Shortcuts by name (empty lists all). Pointers (name)."""
    return [_emit(p) for p in _shortcuts.get_pointers(name)]


def _parse(s: str | None) -> datetime | None:
    """Optional ISO datetime → naive local (contracts.parse_datetime). Empty/absent →
    None."""
    return parse_datetime(s) if s else None


def _parse_required(label: str, s: str) -> datetime:
    """Required ISO datetime (event start/end) → naive local.

    Bad/empty input fails clearly at the tool boundary.
    """
    try:
        return parse_datetime(s)
    except (TypeError, ValueError) as e:
        raise ValueError(
            f"{label} must be an ISO datetime string "
            f"(e.g. 2026-06-24T09:00:00), got {s!r}"
        ) from e


def _priority(n: int) -> int:
    """EventKit reminder priority: 0 (none) or 1–9 (1 highest). Reject out-of-range."""
    if not 0 <= n <= 9:
        raise ValueError(f"priority must be 0–9 (0=none, 1=highest), got {n}")
    return n


def _recurrence(rrule: str | None) -> Recurrence | None:
    """Optional RFC-5545 RRULE string → Recurrence. Empty/absent → None."""
    return Recurrence.from_rrule(rrule) if rrule else None


@_write_tool
def create_reminder(
    title: str,
    due: str | None = None,
    list_name: str | None = None,
    notes: str | None = None,
    priority: int = 0,
    start: str | None = None,
    recurrence: str | None = None,
) -> dict:
    """Create a reminder. `due`/`start` ISO datetime — naive = local time, call now()
    first; `priority` 0–9; `recurrence` an RRULE."""
    data = ReminderData(
        title=title,
        due=_parse(due),
        list_name=list_name,
        notes=notes,
        priority=_priority(priority),
        start=_parse(start),
        recurrence=_recurrence(recurrence),
    )
    return _emit(_reminders.create_reminder(data))


@_write_tool
def update_reminder(
    id: str,
    title: str,
    due: str | None = None,
    list_name: str | None = None,
    notes: str | None = None,
    priority: int = 0,
    start: str | None = None,
    recurrence: str | None = None,
) -> dict:
    """Update a reminder by id (full replace). `due`/`start` ISO (naive = local)."""
    data = ReminderData(
        title=title,
        due=_parse(due),
        list_name=list_name,
        notes=notes,
        priority=_priority(priority),
        start=_parse(start),
        recurrence=_recurrence(recurrence),
    )
    return _emit(_reminders.update_reminder(id, data))


@_write_tool
def complete_reminder(id: str) -> dict:
    """Mark a reminder complete by id."""
    return _emit(_reminders.complete_reminder(id))


@_write_tool
def create_event(
    title: str,
    start: str,
    end: str,
    calendar: str | None = None,
    location: str | None = None,
    notes: str | None = None,
    all_day: bool = False,
    recurrence: str | None = None,
) -> dict:
    """Create an event. `start`/`end` ISO datetime — naive = local time, call now()
    first; `all_day` snaps to a pure date; `recurrence` an RRULE."""
    data = CalendarEventData(
        title=title,
        start=_parse_required("start", start),
        end=_parse_required("end", end),
        calendar=calendar,
        location=location,
        notes=notes,
        all_day=all_day,
        recurrence=_recurrence(recurrence),
    )
    return _emit(_calendar.create_event(data))


@_write_tool
def update_event(
    id: str,
    title: str,
    start: str,
    end: str,
    calendar: str | None = None,
    location: str | None = None,
    notes: str | None = None,
    all_day: bool = False,
    recurrence: str | None = None,
    span: str | None = None,
) -> dict:
    """Update an event by id (full replace). `start`/`end` ISO — naive = local time.
    `span` REQUIRED if the target is recurring: 'this-event' (only this occurrence) or
    'future-events' (this + all later); ignored for single events."""
    data = CalendarEventData(
        title=title,
        start=_parse_required("start", start),
        end=_parse_required("end", end),
        calendar=calendar,
        location=location,
        notes=notes,
        all_day=all_day,
        recurrence=_recurrence(recurrence),
    )
    return _emit(_calendar.update_event(id, data, span=span))


@_write_tool
def delete_event(id: str, span: str | None = None) -> dict:
    """Delete a calendar event by id. `span` REQUIRED if the target is recurring:
    'this-event' (only this occurrence) or 'future-events' (this + all later); ignored
    for single events."""
    _calendar.delete_event(id, span=span)
    return {"deleted": id}


@_write_tool
def delete_note(id: str, expect_title: str | None = None) -> dict:
    """Delete a note by id → Recently Deleted (recoverable ~30 days). Destructive.
    Pass expect_title to verify the target before deleting (content-verify first)."""
    _notes.delete(id, expect_title)
    return {"deleted": id}


@_write_tool
def create_contact(
    given_name: str,
    family_name: str | None = None,
    organization: str | None = None,
) -> dict:
    """Create a contact (given/family name + organization)."""
    data = ContactData(
        given_name=given_name, family_name=family_name, organization=organization
    )
    return _emit(_contacts.create_contact(data))


@_write_tool
def run_shortcut(name: str, input_text: str | None = None) -> dict:
    """Run a Shortcut by name; optional `input_text` piped in. Returns a pointer."""
    return _emit(_shortcuts.run_shortcut(name, input_text))


@_write_tool
def safari_open(url: str) -> dict:
    """Open a URL in a new Safari tab; adds https:// if no scheme."""
    return _emit(_safari.open_url(url))


def main() -> None:
    """Console entry point (`mac-mcp`) and `python -m mac_mcp`."""
    from .runtime import bootstrap

    bootstrap()
    mcp.run()  # stdio transport
