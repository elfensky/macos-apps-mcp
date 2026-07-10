"""Unit tests for the mail adapter — pure parsing helpers (no osascript)."""

from __future__ import annotations

from mac_mcp.adapters.mail import MAX_MAILS, MailAdapter, _deeplink, _parse, _summary
from mac_mcp.contracts import Pointer


def test_summary_subject_and_sender():
    assert _summary("Invoice", "Bob <bob@x.com>") == "Invoice — Bob <bob@x.com>"


def test_summary_subject_only():
    assert _summary("Invoice", "") == "Invoice"


def test_summary_empty_is_placeholder():
    assert _summary("  ", "  ") == "(no subject)"


def test_deeplink_wraps_message_id():
    assert _deeplink("abc@host") == "message://%3cabc@host%3e"


def test_deeplink_strips_existing_brackets():
    assert _deeplink("<abc@host>") == "message://%3cabc@host%3e"


def test_parse_tab_lines():
    raw = "abc@host\tInvoice\tBob\n<def@host>\tHello\t\n"
    ptrs = _parse(raw)
    assert len(ptrs) == 2
    assert isinstance(ptrs[0], Pointer)
    assert ptrs[0].id == "abc@host" and ptrs[0].summary == "Invoice — Bob"
    assert ptrs[0].deeplink == "message://%3cabc@host%3e"
    assert ptrs[1].summary == "Hello"


def test_parse_skips_blank():
    assert _parse("\n  \n") == []


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
