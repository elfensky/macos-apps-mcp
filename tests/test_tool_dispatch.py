"""#581: every tool hands each argument to its adapter under the right name.

Discovery is ``registry.TOOLS``: ``record.fn`` is the plain body (no ``_guard``, no
FastMCP), callable in every gate mode. Each tool gets a recording fake on its adapter
slot (``server._<adapter>``) and one distinct sentinel per parameter. The recorded
call is bound to the REAL adapter method's signature, so a swapped, dropped or
misnamed argument fails here, and so does a call to a method the adapter lacks.
"""

from __future__ import annotations

import dataclasses
import inspect
import types
import typing

import pytest

import macos_apps_mcp.registry as reg
import macos_apps_mcp.server as srv
from macos_apps_mcp.contracts import parse_datetime, parse_recurrence

# Tools the generic test cannot cover, each with its reason. A destructive or
# outbound entry needs a hand-written dispatch test below.
_NOT_GENERIC = {
    # meta tools: no adapter slot; each calls a module function or returns a constant
    "ping": "returns a constant",
    "doctor": "calls doctor.diagnose, no adapter",
    "now": "calls contracts.now_local, no adapter",
    "audit": "calls audit.audit_read, no adapter",
    "usage": "async; calls usage_report over mcp.list_tools(), no adapter",
}

# The tools whose body builds a typed data object, parsing some arguments on the way.
_PARSING = {"create_reminder", "update_reminder", "create_event", "update_event"}

# In a _PARSING tool: parameter -> (input, value the adapter must receive). Keyed by
# name so a signature change in update_event or update_reminder needs no edit here. The
# datetimes are distinct, so a start/due/end swap still fails.
_TRANSFORMED = {
    "due": ("2026-07-20T09:00:00", parse_datetime("2026-07-20T09:00:00")),
    "start": ("2026-07-20T10:00:00", parse_datetime("2026-07-20T10:00:00")),
    "end": ("2026-07-20T11:00:00", parse_datetime("2026-07-20T11:00:00")),
    "recurrence": ("FREQ=WEEKLY;COUNT=3", parse_recurrence("FREQ=WEEKLY;COUNT=3")),
    "all_day": (False, False),  # parse_bound needs a real bool
    "priority": (5, 5),  # ReminderData refuses a priority outside 0-9
    "alarms": ([15, 30], (15, 30)),
}


class _Sentinel:
    """A value equal only to itself — for the bools: two values cannot tell three
    swapped flags apart."""

    def __init__(self, label: str) -> None:
        self.label = label

    def __repr__(self) -> str:
        return f"<{self.label}>"


class _Result:
    """Whatever the adapter returns: a body may iterate it, call ``.as_dict()`` on it,
    or return it as is."""

    def __iter__(self):
        return iter(())

    def as_dict(self) -> dict:
        return {}


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def __getattr__(self, method: str):
        def record(*args, **kwargs):
            self.calls.append((method, args, kwargs))
            return _Result()

        return record


def _sentinel(tool: str, name: str, hint, n: int):
    label = f"{tool}.{name}"
    if typing.get_origin(hint) in (typing.Union, types.UnionType):
        hint = next(a for a in typing.get_args(hint) if a is not type(None))
    if hint is str:
        return label
    if hint is int:
        return 1000 + n
    if typing.get_origin(hint) is list:
        return [_sentinel(tool, name, typing.get_args(hint)[0], n)]
    return _Sentinel(label)


def _flatten(arguments: dict) -> dict:
    """The bound adapter arguments, with each typed data object (ReminderData, …)
    opened into its fields."""
    out = {}
    for key, value in arguments.items():
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            out.update(
                {f.name: getattr(value, f.name) for f in dataclasses.fields(value)}
            )
        else:
            out[key] = value
    return out


def _dispatch(monkeypatch, name: str):
    """Call ``name`` with sentinels; return (sent, received by adapter param name)."""
    rec = reg.TOOLS[name]
    slot = f"_{rec.adapter}"
    real = type(getattr(srv, slot))
    fake = _Recorder()
    monkeypatch.setattr(srv, slot, fake)

    hints = typing.get_type_hints(rec.fn)
    sent, expected = {}, {}
    for n, p in enumerate(inspect.signature(rec.fn).parameters):
        if name in _PARSING and p in _TRANSFORMED:
            sent[p], expected[p] = _TRANSFORMED[p]
        else:
            sent[p] = expected[p] = _sentinel(name, p, hints[p], n)
    rec.fn(**sent)

    assert len(fake.calls) == 1, f"{name}: expected one adapter call, got {fake.calls}"
    method, args, kwargs = fake.calls[0]
    target = getattr(real, method, None)
    assert target is not None, f"{name}: {real.__name__} has no method {method!r}"
    bound = inspect.signature(target).bind(None, *args, **kwargs)
    return expected, _flatten(bound.arguments)


# Tool parameter -> adapter parameter, where the two names differ: per tool, or for
# every tool (bare key).
_RENAMED = {
    "id": "ident",
    ("contacts", "name"): "query",
    ("events", "when"): "query",
    ("mail_body", "id"): "message_id",
    ("mail_thread", "id"): "message_id",
    ("mail_undo", "receipt"): "receipt_id",
    ("message_body", "id"): "guid",
    ("messages_with", "contact"): "address",
    ("notes", "title"): "query",
    ("reminders", "due"): "query",
    ("shortcuts", "name"): "query",
}

_GENERIC = sorted(n for n in reg.TOOLS if n not in _NOT_GENERIC)


@pytest.mark.parametrize("name", _GENERIC)
def test_tool_forwards_each_argument_to_its_adapter(monkeypatch, name):
    expected, received = _dispatch(monkeypatch, name)
    for param, value in expected.items():
        key = _RENAMED.get((name, param), _RENAMED.get(param, param))
        assert key in received, f"{name}: {param!r} never reached the adapter"
        assert received[key] == value, (
            f"{name}: adapter {key!r} got {received[key]!r}, expected {value!r}"
        )


def test_every_tool_is_covered_or_allowlisted():
    # Meta-guard: a new tool lands in the generic test unless it is named above.
    assert set(_NOT_GENERIC) <= set(reg.TOOLS), "stale _NOT_GENERIC entry"
    assert {n for n, r in reg.TOOLS.items() if r.adapter is None} == set(_NOT_GENERIC)
    assert len(_GENERIC) == len(reg.TOOLS) - len(_NOT_GENERIC) >= 66
