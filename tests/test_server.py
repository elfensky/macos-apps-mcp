"""Server tool tests — tools are thin dispatch; we swap fake adapters at the
boundary (no EventKit)."""

from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from fastmcp.tools.tool import ToolResult
from mcp.types import TextContent

import macos_apps_mcp.server as srv
from macos_apps_mcp.contracts import (
    CLEAR_RECURRENCE,
    CalendarEventData,
    ContactData,
    Pointer,
    Recurrence,
    ReminderData,
)
from macos_apps_mcp.runtime import AppNotRunning, AutomationDenied


class _FakeSource:
    def __init__(self):
        self.queries: list[str] = []
        self.enumerated = 0

    def get_pointers(self, query: str) -> list[Pointer]:
        self.queries.append(query)
        return [Pointer(id="P-1", summary="s", deeplink="d")]

    def get_lists(self) -> list[Pointer]:
        self.enumerated += 1
        return [Pointer(id="L-1", summary="Home", deeplink="")]

    def get_calendars(self) -> list[Pointer]:
        self.enumerated += 1
        return [Pointer(id="C-1", summary="Work", deeplink="")]

    def get_all(self) -> list[Pointer]:
        self.enumerated += 1
        return [
            Pointer(id="N-1", summary="Milk", deeplink="", folder="iCloud / Groceries")
        ]

    def get_free_busy(self, start, end, calendars=None):
        self.queries.append((start, end, calendars))
        return {
            "busy": [{"start": start, "end": end}],
            "free": [],
        }


def test_server_constructs():
    assert srv.mcp is not None


def test_reminders_tool_dispatches(monkeypatch):
    fake = _FakeSource()
    monkeypatch.setattr(srv, "_reminders", fake)
    out = srv.reminders("overdue")
    assert fake.queries == ["overdue"]
    assert out == [{"id": "P-1", "summary": "s", "deeplink": "d"}]


def test_events_tool_dispatches(monkeypatch):
    fake = _FakeSource()
    monkeypatch.setattr(srv, "_calendar", fake)
    out = srv.events("week")
    assert fake.queries == ["week"]
    assert out[0]["id"] == "P-1"


def test_free_busy_tool_dispatches(monkeypatch):
    fake = _FakeSource()
    monkeypatch.setattr(srv, "_calendar", fake)
    out = srv.free_busy("2026-07-20T08:00:00", "2026-07-20T17:00:00", ["C-1"])
    assert fake.queries == [("2026-07-20T08:00:00", "2026-07-20T17:00:00", ["C-1"])]
    assert out == {
        "busy": [{"start": "2026-07-20T08:00:00", "end": "2026-07-20T17:00:00"}],
        "free": [],
    }


def test_contacts_tool_dispatches(monkeypatch):
    fake = _FakeSource()
    monkeypatch.setattr(srv, "_contacts", fake)
    out = srv.contacts("jane")
    assert fake.queries == ["jane"]
    assert out == [{"id": "P-1", "summary": "s", "deeplink": "d"}]


def test_mail_tool_dispatches(monkeypatch):
    fake = _FakeSource()
    monkeypatch.setattr(srv, "_mail", fake)
    out = srv.mail("invoice")
    assert fake.queries == ["invoice"]
    assert out == [{"id": "P-1", "summary": "s", "deeplink": "d"}]


def test_notes_tool_dispatches(monkeypatch):
    fake = _FakeSource()
    monkeypatch.setattr(srv, "_notes", fake)
    out = srv.notes("groceries")
    assert fake.queries == ["groceries"]
    assert out == [{"id": "P-1", "summary": "s", "deeplink": "d"}]


def test_notes_all_dispatches(monkeypatch):
    fake = _FakeSource()
    monkeypatch.setattr(srv, "_notes", fake)
    out = srv.notes_all()
    assert fake.enumerated == 1
    assert out == [
        {
            "id": "N-1",
            "summary": "Milk",
            "deeplink": "",
            "folder": "iCloud / Groceries",
        }
    ]


def test_safari_tabs_dispatches(monkeypatch):
    class _FakeSafari:
        def get_tabs(self):
            return [Pointer(id="u", summary="t", deeplink="u")]

    monkeypatch.setattr(srv, "_safari", _FakeSafari())
    assert srv.safari_tabs() == [{"id": "u", "summary": "t", "deeplink": "u"}]


def test_photos_tool_dispatches(monkeypatch):
    fake = _FakeSource()
    monkeypatch.setattr(srv, "_photos", fake)
    out = srv.photos("beach")
    assert fake.queries == ["beach"]
    assert out == [{"id": "P-1", "summary": "s", "deeplink": "d"}]


def test_messages_chats_dispatches(monkeypatch):
    class _FakeMessages:
        def get_chats(self):
            return [Pointer(id="g", summary="Family", deeplink="")]

    monkeypatch.setattr(srv, "_messages", _FakeMessages())
    assert srv.messages_chats() == [{"id": "g", "summary": "Family", "deeplink": ""}]


def test_shortcuts_tool_dispatches(monkeypatch):
    fake = _FakeSource()
    monkeypatch.setattr(srv, "_shortcuts", fake)
    out = srv.shortcuts("water")
    assert fake.queries == ["water"]
    assert out == [{"id": "P-1", "summary": "s", "deeplink": "d"}]


def test_reminder_lists_tool_dispatches(monkeypatch):
    fake = _FakeSource()
    monkeypatch.setattr(srv, "_reminders", fake)
    out = srv.reminder_lists()
    assert fake.enumerated == 1
    assert out == [{"id": "L-1", "summary": "Home", "deeplink": ""}]


def test_calendars_tool_dispatches(monkeypatch):
    fake = _FakeSource()
    monkeypatch.setattr(srv, "_calendar", fake)
    out = srv.calendars()
    assert fake.enumerated == 1
    assert out == [{"id": "C-1", "summary": "Work", "deeplink": ""}]


class _FakeWriter:
    def __init__(self):
        self.calls: list = []

    def create_reminder(self, data: ReminderData) -> Pointer:
        self.calls.append(("create_reminder", data))
        return Pointer(id="R-9", summary="s", deeplink="d")

    def update_reminder(self, ident: str, data: ReminderData) -> Pointer:
        self.calls.append(("update_reminder", ident, data))
        return Pointer(id=ident, summary="s", deeplink="d")

    def complete_reminder(self, ident: str) -> Pointer:
        self.calls.append(("complete_reminder", ident))
        return Pointer(id=ident, summary="done", deeplink="d")

    def create_event(self, data: CalendarEventData) -> Pointer:
        self.calls.append(("create_event", data))
        return Pointer(id="E-9", summary="s", deeplink="d")

    def update_event(
        self, ident: str, data: CalendarEventData, span: str | None = None
    ) -> Pointer:
        self.calls.append(("update_event", ident, data, span))
        return Pointer(id=ident, summary="s", deeplink="d")

    def delete_event(self, ident: str, span: str | None = None) -> None:
        self.calls.append(("delete_event", ident, span))

    def create_contact(self, data: ContactData) -> Pointer:
        self.calls.append(("create_contact", data))
        return Pointer(id="C-9", summary="s", deeplink="d")


def test_create_reminder_builds_typed_payload(monkeypatch):
    fake = _FakeWriter()
    monkeypatch.setattr(srv, "_reminders", fake)
    out = srv.create_reminder(
        "Call dentist", due="2026-06-23T18:00:00", list_name="Home"
    )
    kind, data = fake.calls[0]
    assert kind == "create_reminder"
    assert data == ReminderData(
        title="Call dentist",
        due=datetime(2026, 6, 23, 18, 0),
        list_name="Home",
        notes=None,
    )
    assert out == {"id": "R-9", "summary": "s", "deeplink": "d"}


def test_update_reminder_builds_typed_payload(monkeypatch):
    fake = _FakeWriter()
    monkeypatch.setattr(srv, "_reminders", fake)
    out = srv.update_reminder(
        "R-1", "Call dentist", due="2026-06-23T18:00:00", list_name="Home"
    )
    kind, ident, data = fake.calls[0]
    assert kind == "update_reminder" and ident == "R-1"
    assert data == ReminderData(
        title="Call dentist",
        due=datetime(2026, 6, 23, 18, 0),
        list_name="Home",
        notes=None,
    )
    assert out == {"id": "R-1", "summary": "s", "deeplink": "d"}


def test_complete_reminder_dispatches(monkeypatch):
    fake = _FakeWriter()
    monkeypatch.setattr(srv, "_reminders", fake)
    out = srv.complete_reminder("R-1")
    assert fake.calls[0] == ("complete_reminder", "R-1") and out["id"] == "R-1"


def test_create_event_builds_typed_payload(monkeypatch):
    fake = _FakeWriter()
    monkeypatch.setattr(srv, "_calendar", fake)
    srv.create_event("Standup", start="2026-06-24T09:00:00", end="2026-06-24T09:15:00")
    kind, data = fake.calls[0]
    assert kind == "create_event"
    assert data == CalendarEventData(
        title="Standup",
        start=datetime(2026, 6, 24, 9, 0),
        end=datetime(2026, 6, 24, 9, 15),
    )


def test_update_event_builds_typed_payload(monkeypatch):
    fake = _FakeWriter()
    monkeypatch.setattr(srv, "_calendar", fake)
    out = srv.update_event(
        "E-1", "Standup", start="2026-06-24T09:00:00", end="2026-06-24T09:15:00"
    )
    kind, ident, data, span = fake.calls[0]
    assert kind == "update_event" and ident == "E-1" and span is None
    assert data == CalendarEventData(
        title="Standup",
        start=datetime(2026, 6, 24, 9, 0),
        end=datetime(2026, 6, 24, 9, 15),
    )
    assert out == {"id": "E-1", "summary": "s", "deeplink": "d"}


def test_delete_event_dispatches(monkeypatch):
    fake = _FakeWriter()
    monkeypatch.setattr(srv, "_calendar", fake)
    out = srv.delete_event("E-1")
    assert fake.calls[0] == ("delete_event", "E-1", None) and out == {"deleted": "E-1"}


def test_update_event_passes_span(monkeypatch):
    fake = _FakeWriter()
    monkeypatch.setattr(srv, "_calendar", fake)
    srv.update_event(
        "E-1",
        "Standup",
        start="2026-06-24T09:00:00",
        end="2026-06-24T09:15:00",
        span="future-events",
    )
    assert fake.calls[0][0] == "update_event" and fake.calls[0][3] == "future-events"


def test_delete_event_passes_span(monkeypatch):
    fake = _FakeWriter()
    monkeypatch.setattr(srv, "_calendar", fake)
    srv.delete_event("E-1", span="this-event")
    assert fake.calls[0] == ("delete_event", "E-1", "this-event")


def test_create_contact_builds_typed_payload(monkeypatch):
    fake = _FakeWriter()
    monkeypatch.setattr(srv, "_contacts", fake)
    out = srv.create_contact("Jane", family_name="Doe", organization="Acme")
    kind, data = fake.calls[0]
    assert kind == "create_contact"
    assert data == ContactData(
        given_name="Jane", family_name="Doe", organization="Acme"
    )
    assert out == {"id": "C-9", "summary": "s", "deeplink": "d"}


def test_create_reminder_passes_priority_and_start(monkeypatch):
    fake = _FakeWriter()
    monkeypatch.setattr(srv, "_reminders", fake)
    srv.create_reminder("Pay rent", priority=1, start="2026-06-25T09:00:00")
    _, data = fake.calls[0]
    assert data.priority == 1 and data.start == datetime(2026, 6, 25, 9, 0)


def test_create_reminder_rejects_out_of_range_priority(monkeypatch):
    monkeypatch.setattr(srv, "_reminders", _FakeWriter())
    with pytest.raises(ValueError, match="priority must be"):
        srv.create_reminder("x", priority=11)


def test_create_event_passes_all_day(monkeypatch):
    fake = _FakeWriter()
    monkeypatch.setattr(srv, "_calendar", fake)
    srv.create_event(
        "Holiday", start="2026-07-01T00:00:00", end="2026-07-02T00:00:00", all_day=True
    )
    _, data = fake.calls[0]
    assert data.all_day is True


def test_create_event_all_day_accepts_date_only(monkeypatch):
    # all_day takes a calendar DATE — date-only parses to naive local midnight.
    fake = _FakeWriter()
    monkeypatch.setattr(srv, "_calendar", fake)
    srv.create_event("Holiday", start="2026-07-01", end="2026-07-02", all_day=True)
    _, data = fake.calls[0]
    assert data.all_day is True
    assert data.start == datetime(2026, 7, 1) and data.end == datetime(2026, 7, 2)


def test_create_event_all_day_rejects_utc_offset(monkeypatch):
    # an all-day instant with a UTC offset can land on the wrong calendar day —
    # rejected with the date-only hint, prefixed by the failing param's label.
    monkeypatch.setattr(srv, "_calendar", _FakeWriter())
    with pytest.raises(ValueError, match=r"start: .*date-only"):
        srv.create_event(
            "Holiday",
            start="2026-07-01T00:00:00Z",
            end="2026-07-02T00:00:00Z",
            all_day=True,
        )


def test_update_event_all_day_rejects_utc_offset(monkeypatch):
    monkeypatch.setattr(srv, "_calendar", _FakeWriter())
    with pytest.raises(ValueError, match="date-only"):
        srv.update_event(
            "E-1",
            "Holiday",
            start="2026-07-01T00:00:00Z",
            end="2026-07-02T00:00:00Z",
            all_day=True,
        )


def test_create_event_parses_recurrence(monkeypatch):
    fake = _FakeWriter()
    monkeypatch.setattr(srv, "_calendar", fake)
    srv.create_event(
        "Standup",
        start="2026-06-24T09:00:00",
        end="2026-06-24T09:15:00",
        recurrence="FREQ=WEEKLY;INTERVAL=2",
    )
    _, data = fake.calls[0]
    assert data.recurrence == Recurrence(frequency="weekly", interval=2)


def test_create_reminder_parses_recurrence(monkeypatch):
    fake = _FakeWriter()
    monkeypatch.setattr(srv, "_reminders", fake)
    # a recurring reminder needs a due date (EventKit invariant)
    srv.create_reminder(
        "Water plants", due="2026-06-25T09:00:00", recurrence="FREQ=DAILY"
    )
    _, data = fake.calls[0]
    assert data.recurrence == Recurrence(frequency="daily")


def test_create_reminder_recurrence_without_due_rejected(monkeypatch):
    monkeypatch.setattr(srv, "_reminders", _FakeWriter())
    with pytest.raises(ValueError, match="needs a due date"):
        srv.create_reminder("Water plants", recurrence="FREQ=DAILY")


@pytest.mark.parametrize("val", ["none", "None", "NONE", " none "])
def test_update_reminder_recurrence_none_is_clear_sentinel(monkeypatch, val):
    # tri-state: the literal 'none' is an explicit stop — the adapter clears the rule
    # instead of refusing the update.
    fake = _FakeWriter()
    monkeypatch.setattr(srv, "_reminders", fake)
    srv.update_reminder("R-1", "Call dentist", recurrence=val)
    _, _, data = fake.calls[0]
    assert data.recurrence is CLEAR_RECURRENCE


def test_update_reminder_recurrence_omitted_is_none(monkeypatch):
    # omitted stays None (unspecified) — the adapter refuses that on a repeating
    # target, so a rename can't silently kill the series.
    fake = _FakeWriter()
    monkeypatch.setattr(srv, "_reminders", fake)
    srv.update_reminder("R-1", "Call dentist")
    _, _, data = fake.calls[0]
    assert data.recurrence is None


def test_update_reminder_recurrence_rrule_parses(monkeypatch):
    fake = _FakeWriter()
    monkeypatch.setattr(srv, "_reminders", fake)
    srv.update_reminder(
        "R-1", "Water plants", due="2026-06-25T09:00:00", recurrence="FREQ=DAILY"
    )
    _, _, data = fake.calls[0]
    assert data.recurrence == Recurrence(frequency="daily")


def test_create_event_rejects_bad_rrule(monkeypatch):
    monkeypatch.setattr(srv, "_calendar", _FakeWriter())
    with pytest.raises(ValueError, match="unsupported RRULE"):
        srv.create_event(
            "x",
            start="2026-06-24T09:00:00",
            end="2026-06-24T09:15:00",
            recurrence="FREQ=WEEKLY;BYDAY=MO",
        )


def test_run_shortcut_dispatches(monkeypatch):
    class _FakeShortcuts:
        def __init__(self):
            self.calls = []

        def run_shortcut(self, name, input_text=None):
            self.calls.append((name, input_text))
            return Pointer(id=name, summary=f"ran {name}", deeplink="")

    fake = _FakeShortcuts()
    monkeypatch.setattr(srv, "_shortcuts", fake)
    out = srv.run_shortcut("Driving Mode", input_text="go")
    assert fake.calls == [("Driving Mode", "go")]
    assert out == {"id": "Driving Mode", "summary": "ran Driving Mode", "deeplink": ""}


def test_safari_open_dispatches(monkeypatch):
    class _FakeSafari:
        def __init__(self):
            self.calls = []

        def open_url(self, url):
            self.calls.append(url)
            return Pointer(id=url, summary=f"opened {url}", deeplink=url)

    fake = _FakeSafari()
    monkeypatch.setattr(srv, "_safari", fake)
    out = srv.safari_open("example.com")
    assert fake.calls == ["example.com"]
    assert out == {
        "id": "example.com",
        "summary": "opened example.com",
        "deeplink": "example.com",
    }


def test_create_event_rejects_empty_start():
    # Required event dates fail clearly at the tool boundary, not as an obscure
    # worker-thread crash: the label prefixes contracts.parse_datetime's message
    # verbatim (which rightly still offers the date-only form for timed events).
    with pytest.raises(ValueError, match=r"start: expected an ISO-8601 .* or date"):
        srv.create_event("Standup", start="", end="2026-06-24T09:15:00")


@pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "Yes"])
def test_read_only_truthy(monkeypatch, val):
    monkeypatch.setenv("MACOS_APPS_READ_ONLY", val)
    assert srv._read_only() is True


@pytest.mark.parametrize("val", ["", "0", "no", "false", "off"])
def test_read_only_falsy(monkeypatch, val):
    monkeypatch.setenv("MACOS_APPS_READ_ONLY", val)
    assert srv._read_only() is False


def test_read_only_unset_is_false(monkeypatch):
    monkeypatch.delenv("MACOS_APPS_READ_ONLY", raising=False)
    assert srv._read_only() is False


def test_emit_omits_folder_when_none():
    out = srv._emit(Pointer(id="P-1", summary="s", deeplink="d"))
    assert out == {"id": "P-1", "summary": "s", "deeplink": "d"}


def test_emit_includes_folder_when_set():
    out = srv._emit(
        Pointer(id="P-1", summary="s", deeplink="d", folder="iCloud / Notes")
    )
    assert out == {
        "id": "P-1",
        "summary": "s",
        "deeplink": "d",
        "folder": "iCloud / Notes",
    }


def test_note_bodies_dispatches(monkeypatch):
    class _FakeNotes:
        def get_bodies(self, ids):
            self.got = ids
            return [{"id": ids[0], "body": "B"}]

    fake = _FakeNotes()
    monkeypatch.setattr(srv, "_notes", fake)
    out = srv.note_bodies(["N-1"])
    assert fake.got == ["N-1"]
    assert out == [{"id": "N-1", "body": "B"}]


def test_delete_note_dispatches(monkeypatch):
    class _FakeNotes:
        def __init__(self):
            self.calls = []

        def delete(self, ident, expect_title=None):
            self.calls.append((ident, expect_title))

    fake = _FakeNotes()
    monkeypatch.setattr(srv, "_notes", fake)
    out = srv.delete_note("N-1", expect_title="Milk")
    assert fake.calls == [("N-1", "Milk")]
    assert out == {"deleted": "N-1"}


# --- errors-as-results: the dispatch seam converts typed native failures (#47) --------


class _DeniedSource:
    """A read adapter whose native call is TCC-denied — the failure #47 must surface."""

    def get_pointers(self, query: str) -> list[Pointer]:
        raise AutomationDenied("grant Automation access, then restart macos-apps-mcp")


class _EmptySource:
    """A read adapter with a genuine no-match — must stay [], never an error."""

    def get_pointers(self, query: str) -> list[Pointer]:
        return []


def test_read_tool_converts_native_error_to_agent_directive(monkeypatch):
    # A denied read is a loud ToolError carrying the remediation — the model is told to
    # stop and ask the user, not handed a silent [] it would retry against.
    monkeypatch.setattr(srv, "_mail", _DeniedSource())
    with pytest.raises(ToolError, match="Automation access"):
        srv.mail("invoice")


def test_read_tool_empty_result_is_not_an_error(monkeypatch):
    # The whole point of the taxonomy: no-matches ([]) is distinct from failure. An
    # empty search must return [] cleanly, never raise.
    monkeypatch.setattr(srv, "_notes", _EmptySource())
    assert srv.notes("nonexistent") == []


def test_write_tool_converts_native_error_to_agent_directive(monkeypatch):
    class _DeadWriter:
        def create_reminder(self, data: ReminderData) -> Pointer:
            raise AppNotRunning("open the app, then try again")

    monkeypatch.setattr(srv, "_reminders", _DeadWriter())
    with pytest.raises(ToolError, match="open the app"):
        srv.create_reminder("Call dentist")


def test_now_tool_returns_local_context():
    info = srv.now()
    assert set(info) == {"datetime", "date", "timezone", "utc_offset", "weekday"}


def test_event_date_params_route_through_parser(monkeypatch):
    # #50: an aware ISO start must reach the adapter as naive-local with the instant
    # preserved — proves date params go through contracts.parse_datetime.
    fake = _FakeWriter()
    monkeypatch.setattr(srv, "_calendar", fake)
    srv.create_event(
        "Standup", start="2026-06-24T09:00:00+00:00", end="2026-06-24T10:00:00+00:00"
    )
    _, data = fake.calls[0]
    assert data.start.tzinfo is None  # canonicalized to naive-local
    assert (
        data.start.timestamp()
        == datetime.fromisoformat("2026-06-24T09:00:00+00:00").timestamp()
    )


def test_doctor_tool_dispatches(monkeypatch):
    # Thin dispatch: the tool just forwards `request` to doctor.diagnose and returns it.
    calls = []

    def fake_diagnose(request=False):
        calls.append(request)
        return {"summary": "ok", "surfaces": []}

    monkeypatch.setattr(srv, "diagnose", fake_diagnose)
    out = srv.doctor(request=True)
    assert calls == [True]
    assert out == {"summary": "ok", "surfaces": []}


def test_guard_does_not_swallow_value_errors(monkeypatch):
    # Only NativeError becomes a directive; a validation error stays a ValueError so a
    # caller bug reads as a caller bug, not a bogus "grant access" directive.
    class _BadInput:
        def get_pointers(self, query: str) -> list[Pointer]:
            raise ValueError("bad query")

    monkeypatch.setattr(srv, "_contacts", _BadInput())
    with pytest.raises(ValueError, match="bad query"):
        srv.contacts("jane")


# --- untrusted-data notice (#53) -----------------------------------------------------


def test_untrusted_notice_covers_every_registered_tool_except_meta():
    # Acceptance: iterate the REAL server's registered tools; the notice rides on every
    # one carrying user-store content, and only the meta tools (ping/now/doctor) are
    # exempt. Driven through the middleware directly (fake call_next) so no tool needs a
    # live native call — the decision is purely name-based, so this covers all of them.
    async def _run():
        async with Client(srv.mcp) as c:
            names = [t.name for t in await c.list_tools()]
        mw = srv.UntrustedDataNotice()
        out = {}
        for name in names:
            ctx = SimpleNamespace(message=SimpleNamespace(name=name))

            async def call_next(_ctx):
                return ToolResult(content=[TextContent(type="text", text="payload")])

            out[name] = (await mw.on_call_tool(ctx, call_next)).content
        return names, out

    names, out = asyncio.run(_run())
    assert names, "no tools registered"
    assert set(names) >= srv._NO_NOTICE  # the exempt tools really exist
    for name in names:
        first = out[name][0].text
        if name in srv._NO_NOTICE:
            assert first == "payload", f"{name} must be exempt from the notice"
        else:
            assert first == srv.UNTRUSTED_NOTICE, f"{name} is missing the notice"


def test_untrusted_notice_end_to_end_and_leaves_data_intact(monkeypatch):
    # Wired on the real server: a read tool gets the notice as content[0] while its
    # structured data (what a consumer reads) is untouched; a meta tool does not.
    monkeypatch.setattr(srv, "_reminders", _FakeSource())

    async def _run():
        async with Client(srv.mcp) as c:
            return await c.call_tool("reminders", {"due": "today"}), await c.call_tool(
                "now", {}
            )

    reminders_res, now_res = asyncio.run(_run())
    assert reminders_res.content[0].text == srv.UNTRUSTED_NOTICE
    assert reminders_res.data == [{"id": "P-1", "summary": "s", "deeplink": "d"}]
    assert now_res.content[0].text != srv.UNTRUSTED_NOTICE  # meta tool exempt


def test_untrusted_notice_is_one_block_not_per_item(monkeypatch):
    # Acceptance: exactly one line, never repeated per item.
    class _Multi:
        def get_pointers(self, query):
            return [Pointer(id=str(i), summary=f"s{i}", deeplink="d") for i in range(4)]

    monkeypatch.setattr(srv, "_reminders", _Multi())

    async def _run():
        async with Client(srv.mcp) as c:
            return await c.call_tool("reminders", {"due": "today"})

    res = asyncio.run(_run())
    notices = [
        b for b in res.content if getattr(b, "text", None) == srv.UNTRUSTED_NOTICE
    ]
    assert len(notices) == 1 and res.content[0].text == srv.UNTRUSTED_NOTICE


def test_untrusted_notice_not_added_to_error_results(monkeypatch):
    # An error carries a remediation directive, not user data — it must not be prefixed
    # with the notice. (_guard raises ToolError → call_next raises → prepend skipped.)
    class _Boom:
        def get_pointers(self, query):
            raise AutomationDenied("automation off")

    monkeypatch.setattr(srv, "_reminders", _Boom())

    async def _run():
        async with Client(srv.mcp) as c:
            with pytest.raises(ToolError) as exc:
                await c.call_tool("reminders", {"due": "today"})
            return str(exc.value)

    assert srv.UNTRUSTED_NOTICE not in asyncio.run(_run())


# --- dry_run dispatch (#54) ----------------------------------------------------------


def test_delete_event_dry_run_dispatches_and_formats_preview(monkeypatch):
    calls = []

    class _Cal:
        def delete_event(self, ident, span=None, dry_run=False):
            calls.append((ident, span, dry_run))
            return Pointer(
                id=ident, summary="Standup 09:00–09:15", deeplink="calshow:1"
            )

    monkeypatch.setattr(srv, "_calendar", _Cal())
    out = srv.delete_event("E-1", dry_run=True)
    assert calls == [("E-1", None, True)]  # dry_run flag reached the adapter
    assert out == {
        "dry_run": True,
        "would_delete": {
            "id": "E-1",
            "summary": "Standup 09:00–09:15",
            "deeplink": "calshow:1",
        },
    }


def test_delete_event_without_dry_run_still_mutates_and_reports_deleted(monkeypatch):
    # guard the default path: no dry_run -> the mutating adapter call, {"deleted": id}.
    calls = []

    class _Cal:
        def delete_event(self, ident, span=None, dry_run=False):
            calls.append((ident, span, dry_run))
            return None

    monkeypatch.setattr(srv, "_calendar", _Cal())
    assert srv.delete_event("E-1") == {"deleted": "E-1"}
    assert calls == [("E-1", None, False)]


def test_delete_note_dry_run_dispatches_and_formats_preview(monkeypatch):
    calls = []

    class _Notes:
        def delete(self, ident, expect_title=None, dry_run=False):
            calls.append((ident, expect_title, dry_run))
            return Pointer(id=ident, summary="Groceries", deeplink="")

    monkeypatch.setattr(srv, "_notes", _Notes())
    out = srv.delete_note("N-1", dry_run=True)
    assert calls == [("N-1", None, True)]
    assert out == {
        "dry_run": True,
        "would_delete": {"id": "N-1", "summary": "Groceries", "deeplink": ""},
    }
