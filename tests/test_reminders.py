"""Unit tests for the reminders adapter — pure mapping only (fakes, no EventKit)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from macos_apps_mcp import tiers
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


def _fake_reminder(title, ident, due=None, calendar_id="L-1"):
    due_comps = None
    if due is not None:
        y, m, d = due
        due_comps = SimpleNamespace(year=lambda: y, month=lambda: m, day=lambda: d)
    return SimpleNamespace(
        title=lambda: title,
        calendarItemIdentifier=lambda: ident,
        dueDateComponents=lambda: due_comps,
        # None means a reminder with no list
        calendar=(
            (lambda: None)
            if calendar_id is None
            else (lambda: SimpleNamespace(calendarIdentifier=lambda: calendar_id))
        ),
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


def test_verify_reminder_dropped_bymonthday_raises():
    data = ReminderData(
        title="Pay rent",
        due=datetime(2026, 6, 25, 9, 0),
        recurrence=Recurrence.from_rrule("FREQ=MONTHLY;BYMONTHDAY=1,15"),
    )
    fresh = _fake_persisted(
        title="Pay rent", due=_comps(2026, 6, 25, 9, 0), rule=fake_rule(freq=2)
    )
    with pytest.raises(VerificationFailed, match="recurs"):
        _verify_reminder(fresh, "R-1", data, "L-Home")


def _until_data():
    return ReminderData(
        title="Gym",
        due=datetime(2026, 6, 25, 9, 0),
        recurrence=Recurrence.from_rrule("FREQ=WEEKLY;BYDAY=MO;UNTIL=20270115"),
    )


def test_verify_reminder_until_on_another_day_raises():
    # owner override of A5 (2026-10-06): a reminder's UNTIL is compared by day
    rule = fake_rule(freq=1, byday=[(0, "MO")], until=datetime(2027, 1, 16, 9, 0))
    fresh = _fake_persisted(title="Gym", due=_comps(2026, 6, 25, 9, 0), rule=rule)
    with pytest.raises(VerificationFailed, match="recurs"):
        _verify_reminder(fresh, "R-1", _until_data(), "L-Home")


def test_verify_reminder_until_any_time_that_day_passes():
    for end in (datetime(2027, 1, 15, 0, 0), datetime(2027, 1, 15, 23, 59, 59)):
        rule = fake_rule(freq=1, byday=[(0, "MO")], until=end)
        fresh = _fake_persisted(title="Gym", due=_comps(2026, 6, 25, 9, 0), rule=rule)
        _verify_reminder(fresh, "R-1", _until_data(), "L-Home")  # no raise


def test_update_reminder_resend_text_carries_the_byday_part(monkeypatch):
    import macos_apps_mcp.adapters.reminders as rem
    from macos_apps_mcp.errors import RecurrenceRequired

    target = SimpleNamespace(
        recurrenceRules=lambda: [fake_rule(freq=1, byday=[(0, "MO"), (0, "WE")])]
    )
    s = SimpleNamespace(calendarItemWithIdentifier_=lambda _i: target)
    monkeypatch.setattr(rem, "store", lambda: s)
    monkeypatch.setattr(rem, "run_native", lambda f: f())
    with pytest.raises(RecurrenceRequired, match="BYDAY=MO,WE"):
        rem.RemindersAdapter().update_reminder("R-1", ReminderData(title="Renamed"))


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


# --- container id on the pointer (REM-06, D-12, #207) --------------------------------


def test_reminder_pointer_folder_is_the_list_identifier():
    p = _reminder_pointer(_fake_reminder("Buy milk", "R-1", calendar_id="L-9"))
    assert p.as_dict()["folder"] == "L-9"


def test_reminder_pointer_folder_omitted_when_no_list():
    p = _reminder_pointer(_fake_reminder("Orphan", "R-2", calendar_id=None))
    assert "folder" not in p.as_dict()


def test_reminder_pointer_folder_separates_lists_that_share_a_title():
    # two lists both titled "Inbox": the folder (identifier) tells their reminders apart
    a = _reminder_pointer(_fake_reminder("Inbox", "R-1", calendar_id="L-1"))
    b = _reminder_pointer(_fake_reminder("Inbox", "R-2", calendar_id="L-2"))
    assert (a.folder, b.folder) == ("L-1", "L-2")


def test_reminder_pointer_folder_equals_the_list_pointer_id():
    cal = SimpleNamespace(calendarIdentifier=lambda: "L:1/x ", title=lambda: "Inbox")
    r = _fake_reminder("Buy milk", "R-1", calendar_id="L:1/x ")
    assert _reminder_pointer(r).folder == _list_pointer(cal).id


def test_get_pointers_folder_keeps_fetch_order(monkeypatch):
    # adding folder must not reorder: EventKit's fetch order r3, r1, r2 survives
    import macos_apps_mcp.adapters.reminders as rem
    from macos_apps_mcp.adapters.reminders import RemindersAdapter

    s = _fake_store(["Work"])
    monkeypatch.setattr(rem, "store", lambda: s)
    monkeypatch.setattr(rem, "run_native", lambda f: f())
    monkeypatch.setattr(rem, "_incomplete_due_pred", lambda s, end, cals: cals)
    order = [
        _fake_reminder("c", "R-3", calendar_id="L-3"),
        _fake_reminder("a", "R-1", calendar_id="L-1"),
        _fake_reminder("b", "R-2", calendar_id="L-2"),
    ]
    monkeypatch.setattr(rem, "_fetch_reminders", lambda s, cals: order)
    ptrs = RemindersAdapter().get_pointers("today")
    assert [(p.id, p.folder) for p in ptrs] == [
        ("R-3", "L-3"),
        ("R-1", "L-1"),
        ("R-2", "L-2"),
    ]


# --- create_reminder_list on the default account (REM-02, D-22, #92) -----------------


def _list_env(
    monkeypatch,
    existing=(("L-1", "Inbox"),),
    source="iCloud",
    save_error=None,
    persist=True,
    has_default=True,
):
    """Wire create_reminder_list to fakes. ``save_error``: an error code (int) the save
    reports; ``persist=False``: the save says OK but the list never shows up."""
    import macos_apps_mcp.adapters.reminders as rem

    cals = [
        SimpleNamespace(calendarIdentifier=lambda i=i: i, title=lambda t=t: t)
        for i, t in existing
    ]
    saves, runs = [], []

    def new_cal(_etype, _store):
        c = SimpleNamespace(src=None, name=None, ident=f"NEW-{len(saves) + 1}")
        c.setTitle_ = lambda t: setattr(c, "name", t)
        c.setSource_ = lambda src: setattr(c, "src", src)
        c.title = lambda: c.name
        c.calendarIdentifier = lambda: c.ident
        return c

    def save(cal, commit, _err):
        saves.append((cal, commit))
        if save_error is not None:
            return (False, SimpleNamespace(code=lambda: save_error))
        if persist:
            cals.append(cal)
        return (True, None)

    default = SimpleNamespace(source=lambda: SimpleNamespace(title=lambda: source))
    s = SimpleNamespace(
        calendarsForEntityType_=lambda _e: list(cals),
        defaultCalendarForNewReminders=lambda: default if has_default else None,
        saveCalendar_commit_error_=save,
    )
    fake_ek = SimpleNamespace(
        EKEntityTypeReminder=1,
        EKErrorSourceDoesNotAllowCalendarAddDelete=17,
        EKErrorSourceDoesNotAllowReminders=24,
        EKCalendar=SimpleNamespace(calendarForEntityType_eventStore_=new_cal),
    )
    monkeypatch.setattr(rem, "EK", fake_ek)
    monkeypatch.setattr(rem, "store", lambda: s)
    monkeypatch.setattr(rem, "run_native", lambda f: (runs.append(1), f())[1])
    return SimpleNamespace(adapter=rem.RemindersAdapter(), saves=saves, runs=runs)


def test_create_reminder_list_saves_once_and_returns_the_list_pointer(monkeypatch):
    env = _list_env(monkeypatch)
    p = env.adapter.create_reminder_list("Groceries")
    assert len(env.saves) == 1 and env.saves[0][1] is True
    assert (p.id, p.summary, p.deeplink) == ("NEW-1", "Groceries", "")
    assert env.saves[0][0].src.title() == "iCloud"  # the default list's source


def test_create_reminder_list_refuses_an_exact_duplicate_naming_its_id(monkeypatch):
    env = _list_env(monkeypatch)
    with pytest.raises(ValueError, match="L-1") as ei:
        env.adapter.create_reminder_list("Inbox")
    assert "list_name" in str(ei.value)
    assert env.saves == []


def test_create_reminder_list_accepts_a_name_differing_only_in_case(monkeypatch):
    env = _list_env(monkeypatch)
    env.adapter.create_reminder_list("inbox")  # write resolution is exact (#55)
    assert len(env.saves) == 1


@pytest.mark.parametrize("bad", ["", "   ", "a\x07b", "tab\there"])
def test_create_reminder_list_bad_name_raises_before_any_native_call(monkeypatch, bad):
    env = _list_env(monkeypatch)
    with pytest.raises(ValueError):
        env.adapter.create_reminder_list(bad)
    assert env.runs == [] and env.saves == []


def test_create_reminder_list_keeps_the_name_raw(monkeypatch):
    env = _list_env(monkeypatch)
    assert env.adapter.create_reminder_list(" Spaced  Out ").summary == " Spaced  Out "


@pytest.mark.parametrize("code", [17, 24])
def test_create_reminder_list_refusing_source_maps_to_write_refused(monkeypatch, code):
    from macos_apps_mcp.errors import WriteRefused

    env = _list_env(monkeypatch, save_error=code)
    with pytest.raises(WriteRefused, match="iCloud") as ei:
        env.adapter.create_reminder_list("Groceries")
    assert "no list was created" in str(ei.value)


def test_create_reminder_list_other_save_failure_uses_refused_write(monkeypatch):
    from macos_apps_mcp.errors import WriteRefused

    env = _list_env(monkeypatch, save_error=5)
    with pytest.raises(WriteRefused, match="refused by the store"):
        env.adapter.create_reminder_list("Groceries")


def test_create_reminder_list_without_a_default_list_is_write_refused(monkeypatch):
    from macos_apps_mcp.errors import WriteRefused

    env = _list_env(monkeypatch, has_default=False)
    with pytest.raises(WriteRefused, match="default"):
        env.adapter.create_reminder_list("Groceries")
    assert env.saves == []


def test_create_reminder_list_unverified_save_is_verification_failed(monkeypatch):
    env = _list_env(monkeypatch, persist=False)
    with pytest.raises(VerificationFailed):
        env.adapter.create_reminder_list("Groceries")


def test_create_reminder_list_second_identical_create_is_a_duplicate(monkeypatch):
    env = _list_env(monkeypatch)
    env.adapter.create_reminder_list("Groceries")
    with pytest.raises(ValueError, match="NEW-1"):
        env.adapter.create_reminder_list("Groceries")
    assert len(env.saves) == 1  # exactly one list exists


def test_create_reminder_list_scan_save_and_verify_share_one_run_native(monkeypatch):
    env = _list_env(monkeypatch)
    env.adapter.create_reminder_list("Groceries")
    assert env.runs == [1]


# --- RemindersAdapter.read: the store plane degrades loudly (#91, D-15) ---------------


def _adapter_with_pointers(monkeypatch):
    from macos_apps_mcp.adapters.reminders import RemindersAdapter

    pointers = [
        Pointer(id="R1", summary="one", deeplink="d1", folder="L-1"),
        Pointer(id="R2", summary="two", deeplink="d2", folder="L-1"),
    ]
    monkeypatch.setattr(RemindersAdapter, "get_pointers", lambda self, q: pointers)
    return RemindersAdapter(), pointers


def _plain(pointers):
    return [p.as_dict() for p in pointers]


def test_read_with_an_ungranted_store_keeps_the_eventkit_pointers(monkeypatch):
    from macos_apps_mcp.adapters import reminders_store
    from macos_apps_mcp.errors import FullDiskAccessDenied

    adapter, pointers = _adapter_with_pointers(monkeypatch)

    def denied():
        raise FullDiskAccessDenied("Grant Full Disk Access in System Settings.")

    monkeypatch.setattr(reminders_store, "store_path", denied)
    out = adapter.read("today")
    assert out["results"] == _plain(pointers)  # no tags, no parent keys
    assert out["coverage"].startswith("tags and parent links unavailable:")
    assert "Grant Full Disk Access" in out["coverage"]


def test_read_with_a_drifted_store_names_the_drift(monkeypatch, tmp_path):
    from macos_apps_mcp.adapters import reminders_store
    from tests.test_reminders_store import _make_reminders_store

    adapter, pointers = _adapter_with_pointers(monkeypatch)
    path = _make_reminders_store(tmp_path / "Data-d.sqlite", drop_parent_column=True)
    monkeypatch.setattr(reminders_store, "store_path", lambda: path)
    out = adapter.read("today")
    assert out["results"] == _plain(pointers)
    assert out["coverage"].startswith("tags and parent links unavailable:")
    assert "ZPARENTREMINDER" in out["coverage"]


def test_read_with_a_store_that_fails_mid_read_gives_no_partial_tags(
    monkeypatch, tmp_path
):
    # a locked or rewritten store: the sqlite error becomes SchemaDrift inside
    # read_via_sqlite, so the tags read first are NOT presented as the whole answer
    from macos_apps_mcp.adapters import reminders_store
    from tests.test_reminders_store import _make_reminders_store

    adapter, pointers = _adapter_with_pointers(monkeypatch)
    path = _make_reminders_store(tmp_path / "Data-m.sqlite")
    monkeypatch.setattr(reminders_store, "store_path", lambda: path)
    monkeypatch.setattr(reminders_store, "_PARENTS", "SELECT nope FROM nowhere")
    out = adapter.read("today")
    assert out["results"] == _plain(pointers)  # R1 has tags in the store, none shown
    assert "coverage" in out


def test_read_with_a_missing_store_still_returns_the_pointers(monkeypatch, tmp_path):
    from macos_apps_mcp.adapters import reminders_store

    adapter, pointers = _adapter_with_pointers(monkeypatch)
    monkeypatch.setattr(reminders_store, "_STORES", tmp_path / "absent")
    out = adapter.read("today")
    assert out["results"] == _plain(pointers)
    assert "not found" in out["coverage"]


def test_read_never_folds_an_eventkit_failure_into_coverage(monkeypatch):
    from macos_apps_mcp.adapters.reminders import RemindersAdapter
    from macos_apps_mcp.errors import AccessDenied

    def boom(self, query):
        raise AccessDenied("no Reminders access")

    monkeypatch.setattr(RemindersAdapter, "get_pointers", boom)
    with pytest.raises(AccessDenied):
        RemindersAdapter().read("today")


# --- delete_reminder (REM-01, #92) ----------------------------------------------------


class _EKWorld:
    """An EKEventStore stand-in for the delete tests: it answers the by-id fetch and the
    remove, records every remove call, and can make a removal NOT stick.

    ``cascade``   parent id -> ids EventKit removes with it (the subtasks).
    ``survivors`` ids that stay fetchable after the remove (an iCloud restore)."""

    def __init__(self, *items, cascade=None, survivors=()):
        self.items = {i.calendarItemIdentifier(): i for i in items}
        self.cascade = cascade or {}
        self.survivors = set(survivors)
        self.removed: list[str] = []

    def calendarItemWithIdentifier_(self, ident):
        return self.items.get(ident)

    def removeReminder_commit_error_(self, r, commit, err):
        ident = r.calendarItemIdentifier()
        self.removed.append(ident)
        for gone in (ident, *self.cascade.get(ident, ())):
            if gone not in self.survivors:
                self.items.pop(gone, None)
        return True, None


def _ek_item(ident, title="Item", *, reminder=True):
    item = SimpleNamespace(
        title=lambda: title,
        calendarItemIdentifier=lambda: ident,
        dueDateComponents=lambda: None,
        calendar=lambda: SimpleNamespace(calendarIdentifier=lambda: "L-1"),
        refresh=lambda: True,
    )
    if reminder:
        item.isCompleted = lambda: False  # only an EKReminder has it
    return item


def _wire_delete(monkeypatch, tmp_path, world, *, rows=()):
    """Patch the adapter's store and worker, and point the store plane at a fixture
    Reminders store carrying ``rows`` (pk, ckid, parent pk, tombstone)."""
    import macos_apps_mcp.adapters.reminders as rem
    from macos_apps_mcp.adapters import reminders_store
    from tests.test_reminders_store import _add_reminders, _make_reminders_store

    path = _make_reminders_store(tmp_path / "Data-del.sqlite")
    _add_reminders(path, list(rows))
    monkeypatch.setattr(reminders_store, "store_path", lambda: path)
    monkeypatch.setattr(rem, "store", lambda: world)
    monkeypatch.setattr(rem, "run_native", lambda f: f())
    return rem.RemindersAdapter()


_P0 = [(30, "P0", None, 0)]  # a reminder with no subtasks


def test_delete_reminder_dry_run_previews_and_removes_nothing(monkeypatch, tmp_path):
    world = _EKWorld(_ek_item("P0", "Water plants"))
    out = _wire_delete(monkeypatch, tmp_path, world, rows=_P0).delete_reminder("P0")
    assert out["dry_run"] is True
    assert out["would_delete"]["id"] == "P0" and out["would_delete"]["folder"] == "L-1"
    assert world.removed == []


def test_delete_reminder_removes_once_and_proves_it_gone(monkeypatch, tmp_path):
    world = _EKWorld(_ek_item("P0"))
    out = _wire_delete(monkeypatch, tmp_path, world, rows=_P0).delete_reminder(
        "P0", dry_run=False
    )
    assert out == {"deleted": "P0"}
    assert world.removed == ["P0"]


def test_delete_reminder_still_there_after_the_remove_is_not_reported_deleted(
    monkeypatch, tmp_path
):
    world = _EKWorld(_ek_item("P0"), survivors={"P0"})  # iCloud put it back
    adapter = _wire_delete(monkeypatch, tmp_path, world, rows=_P0)
    with pytest.raises(VerificationFailed, match="still present"):
        adapter.delete_reminder("P0", dry_run=False)


def test_delete_reminder_unknown_id_is_refused(monkeypatch, tmp_path):
    world = _EKWorld()
    adapter = _wire_delete(monkeypatch, tmp_path, world)
    with pytest.raises(ValueError, match="no reminder with id"):
        adapter.delete_reminder("nope", dry_run=False)
    assert world.removed == []


def test_delete_reminder_never_removes_a_calendar_event(monkeypatch, tmp_path):
    # the base id of an event resolves through calendarItemWithIdentifier_ too
    world = _EKWorld(_ek_item("E-1", reminder=False))
    adapter = _wire_delete(monkeypatch, tmp_path, world)
    with pytest.raises(ValueError, match="not a reminder"):
        adapter.delete_reminder("E-1", dry_run=False)
    assert world.removed == []


@pytest.mark.parametrize("dry_run", [True, False])
def test_delete_reminder_with_an_unreadable_store_refuses_and_changes_nothing(
    monkeypatch, tmp_path, dry_run
):
    # D-18: without the store the cascade is unknowable — a blind delete is refused
    from macos_apps_mcp.adapters import reminders_store
    from macos_apps_mcp.errors import FullDiskAccessDenied, WriteRefused

    world = _EKWorld(_ek_item("P0"))
    adapter = _wire_delete(monkeypatch, tmp_path, world, rows=_P0)

    def denied(_ident):
        raise FullDiskAccessDenied("grant Full Disk Access to the launcher")

    monkeypatch.setattr(reminders_store, "subtasks_of", denied)
    with pytest.raises(WriteRefused) as exc:
        adapter.delete_reminder("P0", dry_run=dry_run)
    assert "grant Full Disk Access" in str(exc.value)
    assert "No change was made" in str(exc.value)
    assert world.removed == []


def test_second_real_delete_of_the_same_id_is_an_error_not_a_second_success(
    monkeypatch, tmp_path
):
    world = _EKWorld(_ek_item("P0"))
    adapter = _wire_delete(monkeypatch, tmp_path, world, rows=_P0)
    assert adapter.delete_reminder("P0", dry_run=False) == {"deleted": "P0"}
    with pytest.raises(ValueError, match="no reminder with id"):
        adapter.delete_reminder("P0", dry_run=False)
    assert world.removed == ["P0"]


def test_two_dry_runs_agree_and_change_nothing(monkeypatch, tmp_path):
    world = _EKWorld(_ek_item("P0"))
    adapter = _wire_delete(monkeypatch, tmp_path, world, rows=_P0)
    assert adapter.delete_reminder("P0") == adapter.delete_reminder("P0")
    assert world.removed == []


def test_delete_snapshotter_returns_the_pointer_or_none(monkeypatch, tmp_path):
    import macos_apps_mcp.adapters.reminders as rem

    world = _EKWorld(_ek_item("P0", "Water plants"), _ek_item("E-1", reminder=False))
    _wire_delete(monkeypatch, tmp_path, world, rows=_P0)
    snap = rem.ReminderDeleteSnapshotter()
    assert snap.snapshot("P0").id == "P0"
    assert snap.snapshot("absent") is None
    assert snap.snapshot("E-1") is None  # an event is no reminder: no before-state


# --- delete_reminder: the subtask guard (D-19, D-20) ---------------------------------

_P1_ROWS = [  # a parent with three live subtasks, in creation order
    (10, "P1", None, 0),
    (11, "C1", 10, 0),
    (12, "C2", 10, 0),
    (13, "C3", 10, 0),
]


def _parent_world(*, survivors=(), missing=()):
    """P1 with children C1..C3 in EventKit; ``missing`` children EventKit cannot fetch
    (the store lists them, EventKit does not — spike 007)."""
    kids = [_ek_item(c, f"child {c}") for c in ("C1", "C2", "C3") if c not in missing]
    return _EKWorld(
        _ek_item("P1", "Parent task"),
        *kids,
        cascade={"P1": ["C1", "C2", "C3"]},
        survivors=survivors,
    )


@pytest.mark.parametrize("dry_run", [True, False])
def test_a_parent_with_subtasks_is_refused_unless_confirmed(
    monkeypatch, tmp_path, dry_run
):
    from macos_apps_mcp.errors import SubtasksRequired

    world = _parent_world()
    adapter = _wire_delete(monkeypatch, tmp_path, world, rows=_P1_ROWS)
    with pytest.raises(SubtasksRequired) as exc:
        adapter.delete_reminder("P1", dry_run=dry_run)
    text = str(exc.value)
    assert "3 subtasks" in text and "with_subtasks=True" in text
    assert "No change was made" in text
    for kid in ("C1", "C2", "C3"):
        assert f"child {kid} [{kid}]" in text  # each subtask as `summary [id]`
    assert world.removed == []  # not removed, in the dry run or the real call
    assert SubtasksRequired.kind == "subtasks_required"


def test_confirmed_dry_run_lists_every_subtask_and_removes_nothing(
    monkeypatch, tmp_path
):
    world = _parent_world()
    adapter = _wire_delete(monkeypatch, tmp_path, world, rows=_P1_ROWS)
    out = adapter.delete_reminder("P1", with_subtasks=True)
    assert out["dry_run"] is True
    assert [s["id"] for s in out["would_delete"]["subtasks"]] == ["C1", "C2", "C3"]
    assert out["cascade"].startswith("and 3 subtasks")
    assert world.removed == []


def test_confirmed_delete_names_every_removed_reminder(monkeypatch, tmp_path):
    world = _parent_world()
    adapter = _wire_delete(monkeypatch, tmp_path, world, rows=_P1_ROWS)
    out = adapter.delete_reminder("P1", dry_run=False, with_subtasks=True)
    assert out["deleted"] == "P1"
    assert [s["id"] for s in out["subtasks"]] == ["C1", "C2", "C3"]
    assert out["cascade"].startswith("and 3 subtasks")
    assert world.removed == ["P1"]  # one remove call; EventKit takes the children


def test_a_subtask_that_is_still_there_after_the_delete_is_named(monkeypatch, tmp_path):
    world = _parent_world(survivors={"C2"})
    adapter = _wire_delete(monkeypatch, tmp_path, world, rows=_P1_ROWS)
    with pytest.raises(VerificationFailed, match="C2"):
        adapter.delete_reminder("P1", dry_run=False, with_subtasks=True)


def test_a_store_subtask_eventkit_cannot_fetch_is_still_counted(monkeypatch, tmp_path):
    # RESEARCH Pitfall 7: dropping it would report fewer reminders than were removed
    world = _parent_world(missing={"C3"})
    adapter = _wire_delete(monkeypatch, tmp_path, world, rows=_P1_ROWS)
    out = adapter.delete_reminder("P1", with_subtasks=True)
    ghost = out["would_delete"]["subtasks"][2]
    assert ghost["id"] == "C3"
    assert ghost["summary"] == "(subtask not visible to EventKit)"
    assert out["cascade"].startswith("and 3 subtasks")


def test_a_parent_without_subtasks_needs_no_confirmation(monkeypatch, tmp_path):
    world = _EKWorld(_ek_item("P0"))
    adapter = _wire_delete(monkeypatch, tmp_path, world, rows=_P0)
    out = adapter.delete_reminder("P0", dry_run=False)
    assert out == {"deleted": "P0"}  # no `subtasks`, no `cascade`


def test_the_delete_snapshotter_records_the_parent_and_every_subtask(
    monkeypatch, tmp_path
):
    import macos_apps_mcp.adapters.reminders as rem

    world = _parent_world(missing={"C3"})
    _wire_delete(monkeypatch, tmp_path, world, rows=_P1_ROWS)
    before = rem.ReminderDeleteSnapshotter().snapshot("P1").as_dict()
    assert [s["id"] for s in before["subtasks"]] == ["C1", "C2", "C3"]


def test_the_shared_snapshot_makes_no_store_read(monkeypatch, tmp_path):
    # D-20: update/complete share this snapshot; a store read there would log
    # before=None whenever the grant is missing
    from macos_apps_mcp.adapters import reminders_store
    from macos_apps_mcp.errors import FullDiskAccessDenied

    world = _parent_world()
    adapter = _wire_delete(monkeypatch, tmp_path, world, rows=_P1_ROWS)

    def denied(_ident):
        raise FullDiskAccessDenied("no grant")

    monkeypatch.setattr(reminders_store, "subtasks_of", denied)
    assert adapter.snapshot("P1").id == "P1"


@pytest.mark.skipif(
    tiers.read_only(),
    reason="delete_reminder is a write tool — absent under MACOS_APPS_READ_ONLY, so "
    "the live MCP Client cannot call it (its absence is test_registry's concern)",
)
def test_the_audit_before_state_records_all_the_reminders_a_delete_removes(
    monkeypatch, tmp_path
):
    import asyncio

    from fastmcp import Client

    import macos_apps_mcp.audit as au
    import macos_apps_mcp.server as srv

    world = _parent_world()
    _wire_delete(monkeypatch, tmp_path, world, rows=_P1_ROWS)
    monkeypatch.setattr(au, "state_dir", lambda: tmp_path)

    async def _run():
        async with Client(srv.mcp) as c:
            await c.call_tool(
                "delete_reminder",
                {"id": "P1", "dry_run": False, "with_subtasks": True},
            )
            return await c.call_tool("audit", {})

    records = asyncio.run(_run()).data
    newest = next(r for r in records if r["tool"] == "delete_reminder")
    assert newest["op"] == "delete"
    assert [s["id"] for s in newest["before"]["subtasks"]] == ["C1", "C2", "C3"]
    assert world.removed == ["P1"]
