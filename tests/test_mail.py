"""Unit tests for the mail adapter — pure parsing helpers (no osascript)."""

from __future__ import annotations

import pytest

from mac_mcp.adapters.mail import (
    MAX_MAILS,
    MailAdapter,
    _deeplink,
    _parse,
    _summary,
    system_mailbox_names,
)
from mac_mcp.contracts import Pointer


def test_summary_subject_and_sender():
    assert _summary("Invoice", "Bob <bob@x.com>") == "Invoice — Bob <bob@x.com>"


def test_summary_subject_only():
    assert _summary("Invoice", "") == "Invoice"


def test_summary_empty_is_placeholder():
    assert _summary("  ", "  ") == "(no subject)"


def test_deeplink_wraps_message_id():
    # #61: uppercase %3C/%3E, id percent-encoded with safe='@' (@ stays literal).
    assert _deeplink("abc@host") == "message://%3Cabc@host%3E"


def test_deeplink_strips_existing_brackets():
    assert _deeplink("<abc@host>") == "message://%3Cabc@host%3E"


def test_deeplink_percent_encodes_special_chars():
    # a space (or other unsafe char) in the id is percent-encoded so the URL is valid;
    # '@' is preserved (safe='@').
    assert _deeplink("a b@ho st") == "message://%3Ca%20b@ho%20st%3E"


def test_parse_tab_lines():
    raw = "abc@host\tInvoice\tBob\n<def@host>\tHello\t\n"
    ptrs = _parse(raw)
    assert len(ptrs) == 2
    assert isinstance(ptrs[0], Pointer)
    assert ptrs[0].id == "abc@host" and ptrs[0].summary == "Invoice — Bob"
    assert ptrs[0].deeplink == "message://%3Cabc@host%3E"
    assert ptrs[1].summary == "Hello"


def test_parse_skips_blank():
    assert _parse("\n  \n") == []


def test_parse_skips_missing_message_id():
    # a header-less message has no stable RFC822 citation: AppleScript emits "missing
    # value" (or ""), which must be skipped, never a garbage id/deeplink (#61).
    raw = (
        "missing value\tNo header\tSpammer\n\tEmpty id\tNobody\ngood@host\tReal\tBob\n"
    )
    ptrs = _parse(raw)
    assert [p.id for p in ptrs] == ["good@host"]  # only the message with a real id


def test_parse_sanitizes_control_chars_in_summary():
    # #52: control chars in a subject (which blanked Claude Desktop, carterlasalle #2)
    # must be stripped before the summary reaches the model. NUL/BEL/US are used here
    # because the tab-delimited parser frames records with splitlines(), which would
    # itself split on U+2028/NEL — that framing fragility is pre-existing (a literal
    # newline in a subject splits too) and out of #52's scope; the helper's own
    # U+2028/9 folding is covered in test_runtime.
    raw = "m@host\tInv\x00oice\x1fQ3\x07\tBob\n"
    ptr = _parse(raw)[0]
    assert ptr.summary == "InvoiceQ3 — Bob"
    assert "\x00" not in ptr.summary and "\x07" not in ptr.summary


def test_get_pointers_bounds_host_side(monkeypatch):
    # #52 acceptance: the cap is pushed INTO the AppleScript (argv[2]) so the search
    # stops emitting after MAX_MAILS — not fetched whole then sliced in Python.
    seen = {}
    monkeypatch.setattr(
        "mac_mcp.adapters.mail.run_osascript",
        lambda script, *args: seen.setdefault("args", args) and "" or "",
    )
    MailAdapter().get_pointers("invoice")
    assert seen["args"] == ("invoice", str(MAX_MAILS))


# --- localized system-mailbox tables (#61) -------------------------------------------


def test_system_mailbox_names_localized():
    # en/nl/ru at least (the acceptance floor) — a US-hardcoded "Inbox" fails on a
    # non-English Mac, so mailbox-scoped ops try each localized candidate.
    inbox = system_mailbox_names("inbox")
    assert "Inbox" in inbox and "Postvak IN" in inbox and "Входящие" in inbox


def test_system_mailbox_names_case_insensitive_canonical():
    assert system_mailbox_names("SENT") == system_mailbox_names("sent")


def test_system_mailbox_names_unknown_raises():
    with pytest.raises(ValueError, match="unknown system mailbox"):
        system_mailbox_names("archive")


def test_system_mailbox_covers_the_core_five():
    for canonical in ("inbox", "sent", "drafts", "trash", "junk"):
        names = system_mailbox_names(canonical)
        assert len(names) >= 3  # en + nl + ru at minimum


# --- sender search (#61) -------------------------------------------------------------


def test_search_matches_subject_or_sender(monkeypatch):
    # the AppleScript `whose` clause must match subject OR sender — assert the emitted
    # script contains both predicates (the search is no longer subject-only).
    seen = {}
    monkeypatch.setattr(
        "mac_mcp.adapters.mail.run_osascript",
        lambda script, *args: seen.setdefault("script", script) and "" or "",
    )
    MailAdapter().get_pointers("acme")
    assert "subject contains q or sender contains q" in seen["script"]


def test_search_empty_query_raises():
    with pytest.raises(ValueError, match="search substring"):
        MailAdapter().get_pointers("   ")
