"""#572 and #579 on the installed daemon, in the containers named macos-apps-mcp-test.

Writes only test objects of this run (title starts with the marker). Every test
object is deleted in a fixture teardown, which also runs after a failure, and the
teardown then counts the leftovers. Titles of other items are never shown.
"""

from __future__ import annotations

import pytest

from tests.device.guard import TEST_CONTAINER

pytestmark = pytest.mark.device

DAY, D2, D3, D4 = "2027-03-15", "2027-03-16", "2027-03-17", "2027-03-18"


def _rows(data) -> list[dict]:
    if isinstance(data, dict):
        data = data.get("results")
    return [r for r in data or [] if isinstance(r, dict)]


def _events(guard, day: str, needle: str) -> list[dict]:
    _err, rows, _text, _ = guard.run("events", when=day)
    return [r for r in _rows(rows) if needle in r.get("summary", "")]


def _reminders(guard) -> tuple[bool, list[dict]]:
    err, res, _text, _ = guard.run("reminders", due=TEST_CONTAINER)
    return err, [r for r in _rows(res) if guard.marker in r.get("summary", "")]


@pytest.fixture(scope="module")
def calendar_id(guard, writes) -> str:
    err, rows, text, _ = guard.run("calendars")
    hits = [r for r in _rows(rows) if r.get("summary") == TEST_CONTAINER]
    if err or len(hits) != 1:
        pytest.skip(
            f"{len(hits)} calendars are named {TEST_CONTAINER}: create exactly one "
            "in Calendar.app"
        )
    guard.adopt_container(hits[0])
    return hits[0]["id"]


@pytest.fixture(scope="module")
def list_id(guard, writes) -> str:
    err, rows, text, _ = guard.run("reminder_lists")
    hits = [r for r in _rows(rows) if r.get("summary") == TEST_CONTAINER]
    if err or len(hits) > 1:
        pytest.skip(f"{len(hits)} reminder lists are named {TEST_CONTAINER}")
    if hits:
        guard.adopt_container(hits[0])
        return hits[0]["id"]
    err, lp, text, _ = guard.run("create_reminder_list", name=TEST_CONTAINER)
    assert not err and (lp or {}).get("id"), f"create test list: {text[:200]}"
    return lp["id"]


@pytest.fixture
def events_made(guard):
    """``{"id", "span"}`` of every test event; deleted after the test."""
    made: list[dict] = []
    yield made
    failed = 0
    for item in reversed(made):
        args = {"id": item["id"], "dry_run": False}
        if item["span"]:
            args["span"] = item["span"]
        failed += guard.run("delete_event", **args)[0]
    left = sum(len(_events(guard, day, guard.marker)) for day in (DAY, D2, D3, D4))
    assert failed == 0 and left == 0, f"cleanup: delete_errors={failed} left={left}"


@pytest.fixture
def reminders_made(guard):
    made: list[str] = []
    yield made
    failed = sum(guard.run("delete_reminder", id=rid, dry_run=False)[0] for rid in made)
    err, left = _reminders(guard)
    ok = failed == 0 and not err and not left
    assert ok, f"cleanup: delete_errors={failed} left={len(left)} read_error={err}"


def _create_event(guard, made, cal, title, day, **extra) -> dict:
    err, p, text, _ = guard.run(
        "create_event",
        title=title,
        start=f"{day}T10:00:00",
        end=f"{day}T10:30:00",
        calendar=cal,
        **extra,
    )
    ok = not err and (p or {}).get("folder") == cal
    if (p or {}).get("id"):
        made.append(
            {"id": p["id"], "span": extra.get("recurrence") and "future-events"}
        )
    assert ok, f"setup: test event in the test calendar: error={err} {text[:200]}"
    return p


def test_572_event_keeps_its_calendar_on_update(guard, calendar_id, events_made):
    _create_event(guard, events_made, calendar_id, guard.marker, DAY, notes="device")
    err, p2, text, secs = guard.run(
        "update_event",
        id=events_made[0]["id"],
        title=guard.marker + " renamed",
        start=f"{DAY}T11:00:00",
        end=f"{DAY}T11:30:00",
    )
    if not err and (p2 or {}).get("id"):
        events_made[0]["id"] = p2["id"]
    ok = not err and (p2 or {}).get("folder") == calendar_id
    assert ok, f"update without calendar: error={err} secs={secs} {text[:200]}"
    mine = _events(guard, DAY, guard.marker)
    ok = len(mine) == 1 and mine[0].get("folder") == calendar_id
    assert ok, f"read back in the test calendar: found={len(mine)}"


def test_579_none_on_a_repeating_event_is_refused(guard, calendar_id, events_made):
    title = guard.marker + " series"
    rule = "FREQ=DAILY;COUNT=3"
    _create_event(guard, events_made, calendar_id, title, D2, recurrence=rule)
    err, _d, text, secs = guard.run(
        "update_event",
        id=events_made[0]["id"],
        title=title,
        start=f"{D2}T10:00:00",
        end=f"{D2}T10:30:00",
        calendar=calendar_id,
        recurrence="none",
        span="future-events",
    )
    named = all(
        s in text
        for s in ("cannot stop a repeating event", "delete_event", "future-events")
    )
    assert err and named, f"refused={err} names_delete_event={named} secs={secs}"
    n = sum(len(_events(guard, day, title)) for day in (D2, D3, D4))
    assert n == 3, f"the series keeps its 3 occurrences: occurrences={n}"


def test_579_none_on_a_single_event_is_a_noop(guard, calendar_id, events_made):
    _create_event(guard, events_made, calendar_id, guard.marker, DAY)
    err, p3, text, secs = guard.run(
        "update_event",
        id=events_made[0]["id"],
        title=guard.marker + " renamed",
        start=f"{DAY}T11:00:00",
        end=f"{DAY}T11:30:00",
        recurrence="none",
    )
    if not err and (p3 or {}).get("id"):
        events_made[0]["id"] = p3["id"]
    ok = not err and (p3 or {}).get("folder") == calendar_id
    assert ok, f"'none' on a single event: error={err} secs={secs} {text[:200]}"


def test_572_reminder_keeps_its_list_on_update(guard, list_id, reminders_made):
    err, r, text, _ = guard.run(
        "create_reminder",
        title=guard.marker,
        due=f"{DAY}T09:00:00",
        list_name=list_id,
        notes="device",
    )
    if (r or {}).get("id"):
        reminders_made.append(r["id"])
    ok = not err and (r or {}).get("folder") == list_id
    assert ok, f"setup: test reminder in the test list: error={err} {text[:200]}"
    err, r2, text, secs = guard.run(
        "update_reminder",
        id=r["id"],
        title=guard.marker + " renamed",
        due=f"{DAY}T10:00:00",
    )
    if not err and (r2 or {}).get("id"):
        reminders_made[0] = r2["id"]
    ok = not err and (r2 or {}).get("folder") == list_id
    assert ok, f"update without list_name: error={err} secs={secs} {text[:200]}"
    err, mine = _reminders(guard)
    ok = not err and len(mine) == 1 and mine[0].get("folder") == list_id
    assert ok, f"read back in the test list: found={len(mine)} read_error={err}"
