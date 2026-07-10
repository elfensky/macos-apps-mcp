"""Unit tests for the native runtime — pure helpers only; no EventKit calls."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import EventKit as EK
import pytest

from mac_mcp.contracts import CLEAR_RECURRENCE, Recurrence
from mac_mcp.runtime import (
    BODY_HARD_MAX,
    BODY_MAX,
    SUMMARY_MAX,
    AccessDenied,
    AppNotRunning,
    AutomationDenied,
    NativeError,
    NativeTimeout,
    OutputOverflow,
    RecurrenceRequired,
    SchemaDrift,
    SpanRequired,
    VerificationFailed,
    WriteRefused,
    _classify_osascript_failure,
    _decide,
    clean_body,
    clean_summary,
    due_components,
    epoch_nsdate,
    from_nsdate,
    norm_text,
    persisted_recurrence_signature,
    recurrence_signature,
    rrule_text,
    run_native,
    run_native_async,
    run_osascript,
    sanitize_block,
    sanitize_line,
    store,
    to_nsdate,
    to_recurrence_rule,
    verify_persisted,
)


def test_decide_passes_on_full_access():
    _decide(3)  # EKAuthorizationStatusFullAccess — returns without raising


@pytest.mark.parametrize(
    "status", [0, 1, 2, 4]
)  # notDetermined, restricted, denied, writeOnly
def test_decide_raises_on_anything_else(status):
    with pytest.raises(AccessDenied, match="System Settings"):
        _decide(status)


def test_store_rejects_off_worker_calls():
    # Called directly (main thread, not the mac-native worker) → must refuse.
    with pytest.raises(RuntimeError, match="run_native"):
        store()


def test_store_returns_same_instance_on_worker():
    s1 = run_native(store)
    s2 = run_native(store)
    assert s1 is s2  # one store, created once, on the worker


def test_nsdate_roundtrip():
    dt = datetime(2026, 6, 23, 9, 30, 0)
    assert abs((from_nsdate(to_nsdate(dt)) - dt).total_seconds()) < 1


def test_epoch_nsdate_preserves_exact_epoch(monkeypatch):
    # 1793514600 is the *second* 01:30 in the US fall-back repeated hour — the instant
    # datetime±timedelta arithmetic shifts by 1h (fold reset). Pin the tz so the
    # fold-proof claim is exercised where it matters.
    import time

    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    try:
        assert epoch_nsdate(1793514600).timeIntervalSince1970() == 1793514600
    finally:
        monkeypatch.undo()
        time.tzset()


def test_due_components_fields():
    c = due_components(datetime(2026, 6, 23, 18, 45))
    assert (c.year(), c.month(), c.day(), c.hour(), c.minute()) == (2026, 6, 23, 18, 45)


def test_to_recurrence_rule_frequency_and_interval():
    # EKRecurrenceRule is a value object — buildable off the worker, no store/TCC.
    rule = to_recurrence_rule(Recurrence(frequency="weekly", interval=2))
    assert rule.frequency() == EK.EKRecurrenceFrequencyWeekly
    assert rule.interval() == 2
    assert rule.recurrenceEnd() is None  # open-ended


def test_to_recurrence_rule_count_end():
    rule = to_recurrence_rule(Recurrence(frequency="daily", count=5))
    assert rule.recurrenceEnd().occurrenceCount() == 5


def test_to_recurrence_rule_until_end():
    r = Recurrence(frequency="monthly", until=datetime(2026, 12, 31))
    end = to_recurrence_rule(r).recurrenceEnd()
    assert end is not None and end.occurrenceCount() == 0  # date-based, not count


def test_run_osascript_returns_output():
    # Pure AppleScript expression — no app/TCC needed, so this is CI-safe.
    assert run_osascript('return "hello"') == "hello"


def test_run_osascript_strips_only_its_own_terminator():
    # osascript appends exactly one \n of its own; a trailing linefeed INSIDE the data
    # must survive. stdout here is "x\n\n" → exactly one strip leaves "x\n".
    assert run_osascript('return "x" & linefeed') == "x\n"


def test_run_osascript_raises_on_error():
    # A failing script must raise, never return "" (don't mask failures as "no result").
    # A script error with no OSStatus fingerprint stays the loud generic NativeError.
    with pytest.raises(NativeError, match="osascript failed"):
        run_osascript('error "boom"')


# --- typed error taxonomy (#47) ------------------------------------------------------


def test_taxonomy_all_subclass_native_error_and_runtime_error():
    # One `except NativeError` at the dispatch seam must catch every native failure, and
    # nothing weaker breaks the existing `except RuntimeError` callers.
    for cls in (
        AccessDenied,
        AutomationDenied,
        AppNotRunning,
        NativeTimeout,
        OutputOverflow,
        SchemaDrift,
        SpanRequired,
        VerificationFailed,
        WriteRefused,
        RecurrenceRequired,
    ):
        assert issubclass(cls, NativeError)
        assert issubclass(cls, RuntimeError)


def test_taxonomy_kinds_are_distinct_machine_codes():
    # `kind` is what doctor (#48) and agents branch on — no two classes may collide.
    kinds = [
        c.kind
        for c in (
            NativeError,
            AccessDenied,
            AutomationDenied,
            AppNotRunning,
            NativeTimeout,
            OutputOverflow,
            SchemaDrift,
            SpanRequired,
            VerificationFailed,
            WriteRefused,
            RecurrenceRequired,
        )
    ]
    assert len(kinds) == len(set(kinds))


def test_classify_automation_denied():
    err = _classify_osascript_failure(
        "execution error: Not authorized to send Apple events to Mail. (-1743)"
    )
    assert isinstance(err, AutomationDenied)
    assert "System Settings" in str(err) and "-1743" in str(err)


@pytest.mark.parametrize("code", ["(-609)", "(-10810)"])
def test_classify_app_not_running(code):
    err = _classify_osascript_failure(f"execution error: something {code}")
    assert isinstance(err, AppNotRunning)


def test_classify_unknown_code_stays_generic_native_error():
    # An unrecognized OSStatus must NOT be mis-fingerprinted as denied/not-running —
    # it stays a loud generic error carrying the raw native detail.
    err = _classify_osascript_failure("execution error: weird thing (-2700)")
    assert type(err) is NativeError
    assert "weird thing" in str(err)


def test_classify_bare_digits_do_not_false_match():
    # We match the parenthesized OSStatus, so a 1743 appearing bare in a subject/body
    # must not be read as an Automation denial.
    err = _classify_osascript_failure("execution error: order 1743 shipped (-2700)")
    assert type(err) is NativeError


def test_run_osascript_timeout_raises_native_timeout():
    # Real osascript, no TCC needed: a 2s delay against a 0.1s budget must surface as
    # NativeTimeout (not a bare TimeoutError, not a masked hang).
    with pytest.raises(NativeTimeout):
        run_osascript("delay 2", timeout=0.1)


# --- verify-after-write diff (#49) ---------------------------------------------------


def test_verify_persisted_passes_when_all_match():
    verify_persisted(
        "reminder",
        {"title": "x", "due": (2026, 6, 23)},
        {"title": "x", "due": (2026, 6, 23)},
    )


def test_verify_persisted_raises_naming_dropped_fields():
    with pytest.raises(VerificationFailed) as exc:
        verify_persisted(
            "reminder",
            {"title": "Pay rent", "due": (2026, 6, 25), "list": "Home"},
            {
                "title": "Pay rent",
                "due": None,
                "list": "Inbox",
            },  # due dropped, wrong list
        )
    msg = str(exc.value)
    assert "due" in msg and "list" in msg
    assert "title" not in msg  # unchanged fields aren't reported


def test_verify_persisted_ignores_keys_absent_from_expected():
    # only requested fields are diffed; extra persisted state (e.g. EventKit metadata)
    # is not a mismatch.
    verify_persisted(
        "event", {"title": "x"}, {"title": "x", "lastModified": "whenever"}
    )


def test_norm_text_folds_unset_variants_to_none():
    assert norm_text(None) is None
    assert norm_text("") is None


def test_norm_text_equates_nfd_and_nfc():
    # Cocoa treats NFC/NFD as equal — a byte-exact compare would false-fail (#49).
    assert norm_text("Cafe\u0301") == norm_text("Caf\u00e9")  # NFD vs NFC "Café"


def test_norm_text_normalizes_line_endings_to_lf():
    assert norm_text("a\r\nb\rc") == "a\nb\nc"


def test_norm_text_stringifies_non_text():
    # NSString-ish values from PyObjC go through str() rather than raising.
    assert norm_text(42) == "42"


def test_recurrence_signature_requested():
    assert recurrence_signature(None) is None
    assert recurrence_signature(CLEAR_RECURRENCE) is None  # explicit clear == no rule
    # frequency maps to the EK constant; interval defaults 1; no count → 0
    assert recurrence_signature(Recurrence(frequency="daily")) == (
        int(EK.EKRecurrenceFrequencyDaily),
        1,
        0,
    )
    assert recurrence_signature(
        Recurrence(frequency="weekly", interval=2, count=10)
    ) == (int(EK.EKRecurrenceFrequencyWeekly), 2, 10)


def test_persisted_recurrence_signature_readback():
    assert persisted_recurrence_signature(None) is None
    assert persisted_recurrence_signature([]) is None
    rule = SimpleNamespace(
        frequency=lambda: EK.EKRecurrenceFrequencyWeekly,
        interval=lambda: 2,
        recurrenceEnd=lambda: SimpleNamespace(occurrenceCount=lambda: 10),
    )
    assert persisted_recurrence_signature([rule]) == (
        int(EK.EKRecurrenceFrequencyWeekly),
        2,
        10,
    )


def test_rrule_text_renders_freq_interval_count():
    rule = SimpleNamespace(
        frequency=lambda: EK.EKRecurrenceFrequencyWeekly,
        interval=lambda: 2,
        recurrenceEnd=lambda: SimpleNamespace(occurrenceCount=lambda: 10),
    )
    assert rrule_text(rule) == "FREQ=WEEKLY;INTERVAL=2;COUNT=10"


def test_rrule_text_omits_count_when_open_ended_or_date_based():
    open_ended = SimpleNamespace(
        frequency=lambda: EK.EKRecurrenceFrequencyDaily,
        interval=lambda: 1,
        recurrenceEnd=lambda: None,
    )
    assert rrule_text(open_ended) == "FREQ=DAILY;INTERVAL=1"
    # date-based end reports occurrenceCount 0 → no COUNT= (matches signature rules)
    until_based = SimpleNamespace(
        frequency=lambda: EK.EKRecurrenceFrequencyMonthly,
        interval=lambda: 3,
        recurrenceEnd=lambda: SimpleNamespace(occurrenceCount=lambda: 0),
    )
    assert rrule_text(until_based) == "FREQ=MONTHLY;INTERVAL=3"


def test_recurrence_signatures_agree_for_equivalent_rule():
    # the requested and persisted signatures must be equal for an unchanged write, so
    # verify-after-write doesn't false-fail a correct recurrence.
    req = recurrence_signature(Recurrence(frequency="monthly", interval=1))
    rule = SimpleNamespace(
        frequency=lambda: EK.EKRecurrenceFrequencyMonthly,
        interval=lambda: 1,
        recurrenceEnd=lambda: None,  # open-ended → count 0
    )
    assert req == persisted_recurrence_signature([rule])


def test_run_native_async_returns_result():
    # start() invokes the completion immediately; the result flows back through finish.
    assert run_native_async(lambda finish: finish("ok")) == "ok"


def test_run_native_async_timeout_raises_native_timeout():
    # a callback that never fires must raise the TYPED timeout (agent-directed, caught
    # by the `except NativeError` dispatch seam), not a bare builtin TimeoutError.
    with pytest.raises(NativeTimeout, match="callback never fired"):
        run_native_async(lambda finish: None, timeout=0.05)


def test_bootstrap_is_nonfatal_on_denied_surface(monkeypatch):
    # #13 safe-mode: a denied TCC surface must not crash startup.
    import mac_mcp.runtime as rt

    def deny(_s, _entity):
        raise rt.AccessDenied("denied")

    monkeypatch.setattr(rt, "_request_one", deny)
    rt.bootstrap()  # returns without raising despite every surface being denied


# --- output hygiene (#52) ------------------------------------------------------------
# The shared sanitize/truncate helper every Pointer.summary and hydrated body routes
# through. Two ecosystem bugs motivate it: control chars / U+2028-9 blanked Claude
# Desktop conversations (carterlasalle #2); unbounded fetches hit maxBuffer (FradSer
# #66/#69). U+2028/U+2029 are built via chr() so the source file can't mangle them.
_LS = chr(0x2028)  # LINE SEPARATOR
_PS = chr(0x2029)  # PARAGRAPH SEPARATOR


def test_sanitize_line_strips_c0_del_and_c1_controls():
    # NUL, BEL (C0), DEL, and a C1 control must all vanish; ordinary text survives.
    assert sanitize_line("a\x00b\x07c\x7fd\x9ee") == "abcde"


def test_sanitize_line_flattens_every_newline_kind_to_space():
    # \n, \r\n, \r, VT, FF, NEL, LINE SEP, PARA SEP all collapse to a single space.
    assert (
        sanitize_line(f"a\nb\r\nc\rd\x0be\x0cf\x85g{_LS}h{_PS}i") == "a b c d e f g h i"
    )


def test_sanitize_line_collapses_whitespace_runs_and_trims():
    assert sanitize_line("  x\t\t  y  ") == "x y"


def test_sanitize_block_preserves_newlines_and_tabs():
    # a body legitimately spans lines: \n and \t survive; other controls are stripped.
    assert sanitize_block("line1\nline2\tcol\x00x") == "line1\nline2\tcolx"


def test_sanitize_block_folds_exotic_breaks_to_newline():
    # CR / CRLF / VT / FF / NEL / U+2028 / U+2029 all normalize to \n (never doubled).
    assert (
        sanitize_block(f"a\r\nb\rc\x0bd\x0ce\x85f{_LS}g{_PS}h")
        == "a\nb\nc\nd\ne\nf\ng\nh"
    )


def test_none_is_treated_as_empty():
    assert sanitize_line(None) == "" and sanitize_block(None) == ""
    assert clean_summary(None) == "" and clean_body(None) == ""


def test_clean_summary_truncates_with_explicit_marker():
    text = "z" * (SUMMARY_MAX + 42)
    out = clean_summary(text)
    # the marker is exact and names the dropped count so the model knows what it missed
    assert out == "z" * SUMMARY_MAX + " [truncated 42 chars]"


def test_clean_summary_short_text_is_unchanged():
    assert clean_summary("Groceries — due 2026-07-11") == "Groceries — due 2026-07-11"


def test_clean_body_truncates_past_soft_cap_with_marker():
    out = clean_body("y" * (BODY_MAX + 7))
    assert out == "y" * BODY_MAX + " [truncated 7 chars]"


def test_clean_body_raises_output_overflow_past_hard_cap():
    with pytest.raises(OutputOverflow, match="too large to hydrate"):
        clean_body("q" * (BODY_HARD_MAX + 1))


def test_clean_body_hard_none_never_raises_only_truncates():
    # the batch-safe path (note_bodies): one huge item truncates instead of failing.
    out = clean_body("q" * (BODY_HARD_MAX + 100), hard=None)
    assert out.startswith("q" * BODY_MAX) and "[truncated" in out


def test_output_overflow_is_a_native_error_for_the_dispatch_seam():
    # server._guard catches NativeError → ToolError, so OutputOverflow must subclass it.
    assert issubclass(OutputOverflow, NativeError)
    assert OutputOverflow.kind == "output_overflow"


def test_clean_helpers_are_idempotent_on_clean_text():
    clean = "Jane Doe — Acme"
    assert sanitize_line(clean) == clean == clean_summary(clean)
    body = "first line\nsecond line"
    assert sanitize_block(body) == body == clean_body(body)
