"""Unit tests for the reminders adapter — pure mapping only (fakes, no EventKit)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from macos_apps_mcp.adapters.reminders import (
    _due_tuple,
    _expected_due_tuple,
    _list_pointer,
    _reminder_deeplink,
    _reminder_pointer,
    _reminder_summary,
    _resolve_list,
    _verify_completed,
    _verify_reminder,
)
from macos_apps_mcp.contracts import Pointer, Recurrence, ReminderData
from macos_apps_mcp.errors import AmbiguousTarget, VerificationFailed
from tests._fakes import fake_rule


def _fake_reminder(title, ident, due=None):
    due_comps = None
    if due is not None:
        y, m, d = due
        due_comps = SimpleNamespace(year=lambda: y, month=lambda: m, day=lambda: d)
    return SimpleNamespace(
        title=lambda: title,
        calendarItemIdentifier=lambda: ident,
        dueDateComponents=lambda: due_comps,
    )


def test_summary_with_due():
    item = _fake_reminder("Call dentist", "R-1", due=(2026, 6, 23))
    assert _reminder_summary(item) == "Call dentist — due 2026-06-23"


def test_summary_without_due():
    assert _reminder_summary(_fake_reminder("Buy milk", "R-2")) == "Buy milk"


def test_reminder_pointer_summary_is_sanitized():
    # #52 routing: a control char in the title is stripped from the pointer summary
    # (deleting clean_summary from _reminder_pointer would fail this).
    p = _reminder_pointer(_fake_reminder("Call\x07 dentist", "R-1"))
    assert p.summary == "Call dentist" and "\x07" not in p.summary


def test_list_pointer_summary_is_the_raw_write_key():
    # #52 review: a reminder-list summary IS its write-resolution key (_resolve_list
    # matches title exactly, no id fallback), so it must stay RAW — trimming a trailing
    # space would make the list untargetable via its own displayed name.
    cal = SimpleNamespace(calendarIdentifier=lambda: "L-1", title=lambda: "Shopping ")
    p = _list_pointer(cal)
    assert p.summary == "Shopping "  # not trimmed to "Shopping"
    store = SimpleNamespace(calendarsForEntityType_=lambda _e: [cal])
    assert _resolve_list(store, p.summary) is cal  # round-trips by the displayed name


def test_deeplink_format():
    assert _reminder_deeplink("R-1") == "x-apple-reminderkit://REMCDReminder/R-1"


def test_pointer_shape():
    p = _reminder_pointer(_fake_reminder("Call dentist", "R-1", due=(2026, 6, 23)))
    assert isinstance(p, Pointer)
    assert (
        p.id == "R-1"
        and p.summary.startswith("Call dentist")
        and p.deeplink.endswith("/R-1")
    )


def _fake_store(list_names, default="Inbox"):
    # each list gets a stable, distinct id (L0, L1, …) so id-first resolution (#55) and
    # the candidate-listing on ambiguity can be exercised even with duplicate names.
    cals = [
        SimpleNamespace(calendarIdentifier=lambda i=i: f"L{i}", title=lambda n=n: n)
        for i, n in enumerate(list_names)
    ]
    return SimpleNamespace(
        calendarsForEntityType_=lambda _e: cals,
        defaultCalendarForNewReminders=lambda: SimpleNamespace(title=lambda: default),
    )


def test_resolve_named_list():
    s = _fake_store(["Work", "Home"])
    assert _resolve_list(s, "Home").title() == "Home"


def test_resolve_default_when_none():
    s = _fake_store(["Work"])
    assert _resolve_list(s, None).title() == "Inbox"


def test_resolve_missing_list_raises():
    s = _fake_store(["Work"])
    with pytest.raises(ValueError, match="no reminder list"):
        _resolve_list(s, "Nope")


def test_resolve_ambiguous_list_refuses_instead_of_first_match():
    # #55: two lists named "Home" must NOT silently first-match for a write — refuse
    # loudly (the mcp-ical #16 duplicate-name mis-target, prevented).
    s = _fake_store(["Home", "Work", "Home"])
    with pytest.raises(AmbiguousTarget, match="2 reminder lists are named 'Home'"):
        _resolve_list(s, "Home")


def test_resolve_ambiguous_list_lists_candidate_ids():
    # #55 DECISION: the refusal must LIST the candidate ids so the caller can recover by
    # re-issuing the write with one — not just "rename your lists" (a dead end).
    s = _fake_store(["Home", "Work", "Home"])  # "Home" at index 0 and 2 → ids L0, L2
    with pytest.raises(AmbiguousTarget) as ei:
        _resolve_list(s, "Home")
    assert "L0" in str(ei.value) and "L2" in str(ei.value)


def test_resolve_list_by_pointer_id():
    # #55 DECISION: a write may target a list by its Pointer.id directly — used as-is,
    # no name lookup, so even a duplicate-named list is unambiguously reachable.
    s = _fake_store(["Home", "Work", "Home"])
    assert _resolve_list(s, "L2") is s.calendarsForEntityType_(None)[2]


def test_resolve_single_match_still_works_when_others_share_no_name():
    # the rule only fires on DUPLICATES — a unique name among many still resolves.
    s = _fake_store(["Home", "Work", "Errands"])
    assert _resolve_list(s, "Work").title() == "Work"


# --- #64: read-side list-name folding (get_pointers), writes stay exact ---------------


def _patch_read(monkeypatch, list_names):
    """Wire get_pointers' work() to fakes: store, run_native (inline), and a predicate/
    fetch that returns one reminder per matched list so the count reflects the match."""
    import macos_apps_mcp.adapters.reminders as rem

    s = _fake_store(list_names)
    monkeypatch.setattr(rem, "store", lambda: s)
    monkeypatch.setattr(rem, "run_native", lambda f: f())
    monkeypatch.setattr(rem, "_incomplete_due_pred", lambda s, end, cals: cals)
    monkeypatch.setattr(
        rem,
        "_fetch_reminders",
        lambda s, cals: [_fake_reminder(c.title(), f"R-{c.title()}") for c in cals],
    )


def test_get_pointers_list_name_is_diacritic_insensitive(monkeypatch):
    # #64: searching reminders in the "Café" list by typing ASCII "cafe" works.
    from macos_apps_mcp.adapters.reminders import RemindersAdapter

    _patch_read(monkeypatch, ["Café", "Work"])
    ptrs = RemindersAdapter().get_pointers("cafe")
    assert [p.summary for p in ptrs] == ["Café"]


def test_get_pointers_fold_collision_returns_both_as_superset(monkeypatch):
    # a fold-collision on a READ ("Café"/"Cafe") returns reminders from BOTH lists — a
    # search superset is safe (unlike a write, it can't mis-home anything).
    from macos_apps_mcp.adapters.reminders import RemindersAdapter

    _patch_read(monkeypatch, ["Café", "Cafe", "Work"])
    ptrs = RemindersAdapter().get_pointers("cafe")
    assert sorted(p.summary for p in ptrs) == ["Cafe", "Café"]


def test_get_pointers_unknown_list_still_raises(monkeypatch):
    from macos_apps_mcp.adapters.reminders import RemindersAdapter

    _patch_read(monkeypatch, ["Work"])
    with pytest.raises(ValueError, match="no reminder list named"):
        RemindersAdapter().get_pointers("cafe")


# --- verify-after-write (#49) --------------------------------------------------------


def _comps(y, m, d, h, mi):
    return SimpleNamespace(
        year=lambda: y,
        month=lambda: m,
        day=lambda: d,
        hour=lambda: h,
        minute=lambda: mi,
    )


def _fake_persisted(
    title="Pay rent",
    notes=None,
    priority=0,
    due=None,
    list_title="Home",
    list_id="L-Home",  # verify keys on the identifier now, not the title (#55 review)
    rule=None,
    completed=False,
):
    return SimpleNamespace(
        title=lambda: title,
        notes=lambda: notes,
        priority=lambda: priority,
        dueDateComponents=lambda: due,
        startDateComponents=lambda: None,
        calendar=lambda: SimpleNamespace(
            title=lambda: list_title, calendarIdentifier=lambda: list_id
        ),
        recurrenceRules=lambda: [rule] if rule is not None else None,
        isCompleted=lambda: completed,
    )


def test_due_tuple_roundtrip():
    assert _due_tuple(_comps(2026, 6, 25, 9, 30)) == (2026, 6, 25, 9, 30)
    assert _due_tuple(None) is None
    assert _expected_due_tuple(datetime(2026, 6, 25, 9, 30)) == (2026, 6, 25, 9, 30)
    assert _expected_due_tuple(None) is None


def test_verify_reminder_passes_on_full_match():
    data = ReminderData(
        title="Pay rent", due=datetime(2026, 6, 25, 9, 0), list_name="Home", priority=1
    )
    fresh = _fake_persisted(
        title="Pay rent", priority=1, due=_comps(2026, 6, 25, 9, 0), list_title="Home"
    )
    _verify_reminder(fresh, "R-1", data, "L-Home")  # no raise


def test_verify_reminder_none_fresh_is_rollback():
    data = ReminderData(title="x")
    with pytest.raises(VerificationFailed, match="could not be re-fetched"):
        _verify_reminder(None, "R-1", data, "L-Home")


def test_verify_reminder_dropped_due_raises():
    data = ReminderData(title="Pay rent", due=datetime(2026, 6, 25, 9, 0))
    # list matches (L-Inbox) so only the dropped due can trip verify
    fresh = _fake_persisted(
        title="Pay rent", due=None, list_title="Inbox", list_id="L-Inbox"
    )
    with pytest.raises(VerificationFailed, match="due"):
        _verify_reminder(fresh, "R-1", data, "L-Inbox")


def test_verify_reminder_wrong_list_raises():
    data = ReminderData(title="Pay rent", list_name="Home")
    fresh = _fake_persisted(
        title="Pay rent", list_title="Inbox", list_id="L-Inbox"
    )  # landed in wrong list
    with pytest.raises(VerificationFailed, match="list"):
        _verify_reminder(fresh, "R-1", data, "L-Home")


def test_verify_reminder_same_name_wrong_id_raises():
    # #55 review: verify keys on the list IDENTIFIER, not its name. A re-home to a
    # DIFFERENT list that happens to SHARE the name (the duplicate-named case that
    # id-targeting exists to serve) must still fail loudly — a title-only compare would
    # falsely pass, silently confirming a write to the wrong list.
    data = ReminderData(title="Pay rent", list_name="L2")
    # targeted list id "L2"; store re-homed it to "L0" — SAME name "Home"
    fresh = _fake_persisted(title="Pay rent", list_title="Home", list_id="L0")
    with pytest.raises(VerificationFailed, match="list"):
        _verify_reminder(fresh, "R-1", data, "L2")


def test_verify_reminder_dropped_recurrence_raises():
    data = ReminderData(
        title="Water plants",
        due=datetime(2026, 6, 25, 9, 0),
        recurrence=Recurrence(frequency="daily"),
    )
    fresh = _fake_persisted(  # rule=None → the series rule was dropped
        title="Water plants", due=_comps(2026, 6, 25, 9, 0)
    )
    with pytest.raises(VerificationFailed, match="recurs"):
        _verify_reminder(fresh, "R-1", data, "L-Home")


def test_verify_reminder_wrong_frequency_raises():
    # presence-only was insufficient (#49 review): a non-empty rule with the WRONG
    # cadence must still fail loudly.
    data = ReminderData(
        title="Water plants",
        due=datetime(2026, 6, 25, 9, 0),
        recurrence=Recurrence(frequency="weekly", interval=2),
    )
    fresh = _fake_persisted(
        title="Water plants",
        due=_comps(2026, 6, 25, 9, 0),
        rule=fake_rule(freq=0, interval=2),  # persisted DAILY, not weekly
    )
    with pytest.raises(VerificationFailed, match="recurs"):
        _verify_reminder(fresh, "R-1", data, "L-Home")


def test_verify_reminder_matching_recurrence_passes():
    data = ReminderData(
        title="Water plants",
        due=datetime(2026, 6, 25, 9, 0),
        recurrence=Recurrence(frequency="weekly", interval=2, count=10),
    )
    fresh = _fake_persisted(
        title="Water plants",
        due=_comps(2026, 6, 25, 9, 0),
        rule=fake_rule(freq=1, interval=2, count=10),  # weekly/2/10 — exact match
    )
    _verify_reminder(fresh, "R-1", data, "L-Home")  # no raise


def test_verify_reminder_nfd_title_matches_nfc_persisted():
    # Cocoa normalizes to NFC on store — a byte-exact diff would false-fail a
    # correct write (#49).
    data = ReminderData(title="Cafe\u0301 run")  # NFD: e + combining acute
    fresh = _fake_persisted(title="Caf\u00e9 run")  # persisted as NFC
    _verify_reminder(fresh, "R-1", data, "L-Home")  # no raise


def test_verify_reminder_crlf_notes_match_lf_persisted():
    data = ReminderData(title="Pay rent", notes="first\r\nsecond")
    fresh = _fake_persisted(notes="first\nsecond")  # store folded CRLF → LF
    _verify_reminder(fresh, "R-1", data, "L-Home")  # no raise


def test_verify_reminder_changed_notes_raises():
    # normalization must not swallow a genuinely different value
    data = ReminderData(title="Pay rent", notes="pay by the 1st")
    fresh = _fake_persisted(notes="pay by the 5th")
    with pytest.raises(VerificationFailed, match="notes"):
        _verify_reminder(fresh, "R-1", data, "L-Home")


def test_verify_reminder_dropped_notes_raises():
    data = ReminderData(title="Pay rent", notes="pay by the 1st")
    fresh = _fake_persisted(notes=None)
    with pytest.raises(VerificationFailed, match="notes"):
        _verify_reminder(fresh, "R-1", data, "L-Home")


def test_verify_completed_passes_when_completed():
    _verify_completed(_fake_persisted(completed=True), "R-1")  # no raise


def test_verify_completed_raises_when_not_completed():
    with pytest.raises(VerificationFailed, match="did not persist as completed"):
        _verify_completed(_fake_persisted(completed=False), "R-1")


def test_verify_completed_none_fresh_raises():
    with pytest.raises(VerificationFailed, match="could not be re-fetched"):
        _verify_completed(None, "R-1")


def test_reminders_snapshot_missing_returns_none(monkeypatch):
    import macos_apps_mcp.adapters.reminders as rem

    monkeypatch.setattr(rem, "run_native", lambda fn: fn())
    fake_store = SimpleNamespace(calendarItemWithIdentifier_=lambda i: None)
    monkeypatch.setattr(rem, "store", lambda: fake_store)
    assert rem.RemindersAdapter().snapshot("R-1") is None
