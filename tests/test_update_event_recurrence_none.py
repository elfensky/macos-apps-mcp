"""#579: ``update_event(recurrence='none')`` cannot stop a series, so it refuses.

On a repeating event the refusal comes before any setter or save. On a single event
'none' already holds, so the rest of the update runs."""

from __future__ import annotations

from datetime import datetime

import pytest

import macos_apps_mcp.server as srv
from macos_apps_mcp.contracts import CLEAR_RECURRENCE, CalendarEventData, Pointer
from macos_apps_mcp.errors import SpanRequired
from tests._fakes import fake_rule
from tests.test_eventkit_update_container import _cal_store, _event_world, _Item

_START, _END = datetime(2026, 6, 24, 9, 0), datetime(2026, 6, 24, 9, 30)


def _data(**kw):
    return CalendarEventData(title="Standup", start=_START, end=_END, **kw)


def _saves(store):
    saved = []
    store.saveEvent_span_commit_error_ = lambda *a: saved.append(a) or (True, None)
    return saved


def test_none_on_a_repeating_event_is_refused_before_any_write(monkeypatch):
    s = _cal_store()
    item = _Item(calendar=s.calendarsForEntityType_(None)[1])
    item.state["recurrenceRules"] = [fake_rule(freq=1)]
    adapter = _event_world(monkeypatch, item, s)
    saved = _saves(s)
    with pytest.raises(SpanRequired) as exc:
        adapter.update_event(
            "I-1|1", _data(recurrence=CLEAR_RECURRENCE), span="future-events"
        )
    msg = str(exc.value)
    assert "No change was made" in msg
    assert "delete_event" in msg and "span='future-events'" in msg
    assert item.calls == [] and saved == []


def test_none_on_a_single_event_updates_and_sets_no_rule(monkeypatch):
    s = _cal_store()
    item = _Item(calendar=s.calendarsForEntityType_(None)[1], title="Old")
    adapter = _event_world(monkeypatch, item, s)
    saved = _saves(s)
    p = adapter.update_event("I-1|1", _data(recurrence=CLEAR_RECURRENCE))
    assert item.state["title"] == "Standup" and len(saved) == 1
    assert "recurrenceRules" not in item.calls
    assert "extra first occurrence" not in p.summary


def test_omitted_recurrence_on_a_repeating_event_is_unchanged(monkeypatch):
    s = _cal_store()
    item = _Item(calendar=s.calendarsForEntityType_(None)[1])
    item.state["recurrenceRules"] = [fake_rule(freq=1)]
    adapter = _event_world(monkeypatch, item, s)
    saved = _saves(s)
    adapter.update_event("I-1|1", _data(), span="this-event")
    assert len(saved) == 1 and "recurrenceRules" not in item.calls


def test_tool_passes_none_as_the_clear_marker(monkeypatch):
    calls = []

    class _Fake:
        def update_event(self, ident, data, span=None):
            calls.append(data)
            return Pointer(id=ident, summary="s", deeplink="d")

    monkeypatch.setattr(srv, "_calendar", _Fake())
    srv.update_event(
        "E-1",
        "Standup",
        "2026-06-24T09:00:00",
        "2026-06-24T09:30:00",
        recurrence="none",
    )
    assert calls[0].recurrence is CLEAR_RECURRENCE
