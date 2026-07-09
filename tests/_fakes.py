"""Shared test fakes — plain SimpleNamespace stand-ins for EventKit objects,
used by the calendar and reminders adapter tests (no native calls)."""

from __future__ import annotations

from types import SimpleNamespace


def fake_rule(freq=0, interval=1, count=None):
    # freq is the EKRecurrenceFrequency int (daily=0, weekly=1, monthly=2, yearly=3).
    end = None if count is None else SimpleNamespace(occurrenceCount=lambda: count)
    return SimpleNamespace(
        frequency=lambda: freq, interval=lambda: interval, recurrenceEnd=lambda: end
    )
