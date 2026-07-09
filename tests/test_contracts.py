"""Unit tests for the adapter contract + native runtime — the test seam is the
adapter boundary."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta, timezone

import pytest

from mac_mcp.contracts import (
    CalendarEventData,
    Pointer,
    PointerSource,
    Recurrence,
    ReminderData,
    _format_offset,
    now_local,
    parse_all_day,
    parse_datetime,
)
from mac_mcp.runtime import run_native


class FakeReminders:
    """Satisfies PointerSource structurally — no native calls. This is how the
    tool layer is mocked."""

    def get_pointers(self, query: str) -> list[Pointer]:
        return [
            Pointer(
                id="x-1",
                summary=f"reminder ~ {query}",
                deeplink="x-apple-reminderkit://x-1",
            )
        ]


def test_fake_satisfies_pointersource():
    fake = FakeReminders()
    assert isinstance(
        fake, PointerSource
    )  # runtime_checkable structural match — no inheritance
    ptrs = fake.get_pointers("dentist")
    assert ptrs[0].id == "x-1"
    assert ptrs[0].deeplink.startswith("x-apple")


def test_pointer_is_frozen():
    p = Pointer(id="a", summary="s", deeplink="d")
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.id = "b"  # type: ignore[misc]


def test_typed_write_payload_defaults():
    r = ReminderData(title="Call dentist")
    assert r.due is None and r.list_name is None
    assert r.priority == 0 and r.start is None  # unset = no priority, no start date
    assert r.recurrence is None

    e = CalendarEventData(
        title="Standup",
        start=datetime(2026, 6, 24, 9),
        end=datetime(2026, 6, 24, 9, 15),
    )
    assert e.calendar is None and e.location is None
    assert e.all_day is False and e.recurrence is None


def test_recurrence_from_rrule_basic():
    assert Recurrence.from_rrule("FREQ=WEEKLY;INTERVAL=2;COUNT=10") == Recurrence(
        frequency="weekly", interval=2, count=10
    )


def test_recurrence_defaults_interval_to_one():
    assert Recurrence.from_rrule("FREQ=DAILY").interval == 1


def test_recurrence_until_utc_preserves_instant():
    # UNTIL=...Z is a UTC instant; the naive-local result must name the SAME instant,
    # not shift by the local offset (the old code dropped tzinfo without converting).
    r = Recurrence.from_rrule("FREQ=MONTHLY;UNTIL=20261231T120000Z")
    assert r.frequency == "monthly"
    assert r.until.astimezone(UTC) == datetime(2026, 12, 31, 12, tzinfo=UTC)


def test_recurrence_until_date_only_is_end_of_day():
    # a date-only UNTIL includes occurrences on that day → resolves to end-of-day, so a
    # 09:00 series on the final day isn't dropped for falling after midnight.
    assert Recurrence.from_rrule("FREQ=DAILY;UNTIL=2026-12-31").until == datetime(
        2026, 12, 31, 23, 59, 59
    )
    assert Recurrence.from_rrule("FREQ=DAILY;UNTIL=20261231").until == datetime(
        2026, 12, 31, 23, 59, 59
    )


def test_recurrence_strips_rrule_prefix():
    assert Recurrence.from_rrule("RRULE:FREQ=YEARLY").frequency == "yearly"


def test_recurrence_rejects_unknown_freq():
    with pytest.raises(ValueError, match="FREQ must be"):
        Recurrence.from_rrule("FREQ=HOURLY")


def test_recurrence_rejects_unsupported_part():
    with pytest.raises(ValueError, match="unsupported RRULE"):
        Recurrence.from_rrule("FREQ=WEEKLY;BYDAY=MO")


def test_recurrence_rejects_count_and_until_together():
    with pytest.raises(ValueError, match="mutually exclusive"):
        Recurrence.from_rrule("FREQ=DAILY;COUNT=5;UNTIL=2026-12-31")


def test_recurrence_rejects_nonpositive_count():
    # COUNT must be validated like INTERVAL — a zero/negative count isn't a valid series
    with pytest.raises(ValueError, match="COUNT must be"):
        Recurrence.from_rrule("FREQ=DAILY;COUNT=0")


def test_recurrence_rejects_malformed_part():
    with pytest.raises(ValueError, match="expected KEY=VALUE"):
        Recurrence.from_rrule("FREQ=DAILY;GARBAGE")


def test_reminder_recurrence_requires_due():
    with pytest.raises(ValueError, match="needs a due date"):
        ReminderData(title="Standup", recurrence=Recurrence(frequency="daily"))


def test_reminder_rejects_out_of_range_priority():
    # the priority invariant belongs on the contract, not only at the tool boundary.
    with pytest.raises(ValueError, match="priority"):
        ReminderData(title="Standup", priority=10)


def test_run_native_runs_on_worker():
    assert run_native(lambda: 2 + 2) == 4


def test_pointer_folder_defaults_none():
    p = Pointer(id="x", summary="s", deeplink="d")
    assert p.folder is None


def test_pointer_folder_set():
    p = Pointer(id="x", summary="s", deeplink="d", folder="iCloud / Notes")
    assert p.folder == "iCloud / Notes"


# --- datetime normalization + now() (#50) --------------------------------------------


def test_parse_datetime_naive_is_kept_as_local():
    # a naive ISO is the user's local wall-time — passed through unchanged, NOT shifted.
    assert parse_datetime("2026-06-24T09:00:00") == datetime(2026, 6, 24, 9, 0)
    assert parse_datetime("2026-06-24T09:00:00").tzinfo is None


def test_parse_datetime_date_only_is_local_midnight_not_utc():
    # the ecosystem's day-shift bug: a date parsed as UTC lands on the wrong day. Ours
    # is local midnight, naive — so an all-day date never drifts.
    assert parse_datetime("2026-07-01") == datetime(2026, 7, 1, 0, 0)
    assert parse_datetime("2026-07-01").tzinfo is None


def test_parse_datetime_aware_preserves_instant():
    # an aware ISO is converted to local then made naive — the naive result must name
    # the SAME instant, on any machine tz (assert via .timestamp() equality).
    aware = "2026-06-24T09:00:00+00:00"
    assert (
        parse_datetime(aware).timestamp() == datetime.fromisoformat(aware).timestamp()
    )


def test_parse_datetime_trailing_z_preserves_instant():
    aware = "2026-12-31T23:30:00Z"
    assert (
        parse_datetime(aware).timestamp() == datetime.fromisoformat(aware).timestamp()
    )
    assert parse_datetime(aware).tzinfo is None


def test_parse_datetime_naive_on_dst_day_is_not_shifted():
    # a naive time on a spring-forward day keeps its wall-clock — we never apply a DST
    # correction to a naive input (that's the point of naive = local wall-time).
    assert parse_datetime("2026-03-08T02:30:00") == datetime(2026, 3, 8, 2, 30)


def test_parse_datetime_aware_across_offset_preserves_instant():
    # a non-UTC offset (e.g. a DST-affected zone) still round-trips the instant.
    aware = "2026-03-08T02:30:00-05:00"
    assert (
        parse_datetime(aware).timestamp() == datetime.fromisoformat(aware).timestamp()
    )


def test_parse_datetime_preserves_instant_across_fall_back_fold(monkeypatch):
    # DST fall-back fold (found by adversarial review): an aware instant in the REPEATED
    # hour must keep its instant when canonicalized to naive-local — else the fold info
    # is lost and to_nsdate's later .timestamp() picks the earlier occurrence (−1h). Pin
    # the tz for determinism (US fall-back is 2026-11-01 02:00 EDT).
    import time

    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    try:
        for v in (
            "2026-11-01T05:30:00+00:00",  # first 01:30 (EDT, pre-fold)
            "2026-11-01T06:30:00+00:00",  # second 01:30 (EST) — the fold that shifted
            "2026-11-01T07:00:00+00:00",  # 02:00 EST (post-transition, unambiguous)
        ):
            assert (
                parse_datetime(v).timestamp() == datetime.fromisoformat(v).timestamp()
            ), v
    finally:
        monkeypatch.undo()
        time.tzset()


def test_parse_datetime_rejects_garbage():
    with pytest.raises(ValueError, match="ISO-8601"):
        parse_datetime("next tuesday")


# --- all-day boundary (#50 review): a calendar DATE, not an instant ------------------


def test_parse_all_day_accepts_date_only():
    # an all-day param is a calendar DATE — date-only parses to naive local midnight.
    assert parse_all_day("2026-07-01") == datetime(2026, 7, 1, 0, 0)
    assert parse_all_day("2026-07-01").tzinfo is None


def test_parse_all_day_accepts_naive_datetime():
    # a naive datetime passes through; the adapter floors it to the day downstream.
    assert parse_all_day("2026-07-01T09:30:00") == datetime(2026, 7, 1, 9, 30)


@pytest.mark.parametrize("value", ["2026-07-01T00:00:00Z", "2026-07-01T00:00:00+09:00"])
def test_parse_all_day_rejects_aware_instant(value):
    # midnight-Z is an instant, not a date — west of UTC it converts to the PREVIOUS
    # local day, so aware values are rejected instead of silently day-shifting.
    with pytest.raises(ValueError, match="calendar date"):
        parse_all_day(value)


def test_parse_all_day_rejection_carries_date_hint():
    # the error hands the agent the exact fix: the date-only form of its own input.
    with pytest.raises(ValueError, match="date-only string like '2026-07-01'"):
        parse_all_day("2026-07-01T12:00:00+09:00")


def test_parse_all_day_rejects_garbage():
    with pytest.raises(ValueError, match="ISO-8601"):
        parse_all_day("next tuesday")


def test_format_offset():
    assert _format_offset(timedelta(hours=2)) == "+02:00"
    assert _format_offset(timedelta(hours=-5, minutes=-30)) == "-05:30"
    assert _format_offset(timedelta()) == "+00:00"
    assert _format_offset(None) == "+00:00"


def test_now_local_shape_with_injected_clock():
    clock = datetime(2026, 7, 4, 14, 30, 0, tzinfo=timezone(timedelta(hours=2), "CEST"))
    info = now_local(clock)
    assert info["datetime"] == "2026-07-04T14:30:00+02:00"
    assert info["date"] == "2026-07-04"
    assert info["utc_offset"] == "+02:00"
    assert info["weekday"] == "Saturday"
    assert info["timezone"] == "CEST"


def test_now_local_default_has_all_keys():
    info = now_local()
    assert set(info) == {"datetime", "date", "timezone", "utc_offset", "weekday"}
    assert info["weekday"] in {
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    }
