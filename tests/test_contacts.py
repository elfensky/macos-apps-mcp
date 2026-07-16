"""Unit tests for the contacts adapter — pure parsing helpers (no osascript)."""

from __future__ import annotations

import pytest

from macos_apps_mcp.adapters.contacts import (
    _FIELD,
    _RECORD,
    MAX_CONTACTS,
    ContactsAdapter,
    _deeplink,
    _parse,
    _summary,
    _verify_contact,
)
from macos_apps_mcp.contracts import ContactData, Pointer
from macos_apps_mcp.runtime import VerificationFailed


def test_get_pointers_passes_cap_into_applescript(monkeypatch):
    # the cap must reach the AppleScript (so it stops fetching after MAX_CONTACTS) —
    # not just trim in Python after the fact. Assert it's forwarded as an argv arg.
    seen: dict = {}

    def fake(script, *args, **kw):
        seen["args"] = args
        return ""  # no matches; we only care about the call shape

    monkeypatch.setattr("macos_apps_mcp.adapters.contacts.run_osascript", fake)
    ContactsAdapter().get_pointers("jane")
    assert seen["args"] == ("jane", str(MAX_CONTACTS))


def test_summary_name_and_org():
    assert _summary("Jane Doe", "Acme") == "Jane Doe — Acme"


def test_summary_name_only():
    assert _summary("Jane Doe", "") == "Jane Doe"


def test_summary_org_only():
    assert _summary("", "Acme") == "Acme"


def test_summary_empty_is_placeholder():
    assert _summary("  ", "  ") == "(unnamed contact)"


def test_summary_with_phone_and_email():
    s = _summary("Jane Doe", "Acme", "+3212345", "jane@acme.com")
    assert s == "Jane Doe — Acme · +3212345 · jane@acme.com"


def test_summary_phone_only_no_org():
    assert _summary("Bob", "", "+15550100", "") == "Bob · +15550100"


def test_summary_email_only_no_name():
    assert _summary("", "", "", "x@y.com") == "x@y.com"


def test_deeplink_scheme():
    assert _deeplink("X:ABPerson") == "addressbook://X:ABPerson"


def _rec(*fields: str) -> str:
    return _FIELD.join(fields) + _RECORD


def test_parse_records():
    raw = _rec("C-1", "Jane Doe", "Acme") + _rec("C-2", "Bob", "")
    ptrs = _parse(raw)
    assert len(ptrs) == 2
    assert isinstance(ptrs[0], Pointer)
    assert ptrs[0].id == "C-1" and ptrs[0].summary == "Jane Doe — Acme"
    assert ptrs[0].deeplink == "addressbook://C-1"
    assert ptrs[1].id == "C-2" and ptrs[1].summary == "Bob"


def test_parse_five_field_record_with_phone_email():
    raw = _rec("C-1", "Jane Doe", "Acme", "+3212345", "jane@acme.com")
    ptrs = _parse(raw)
    assert ptrs[0].id == "C-1"
    assert ptrs[0].summary == "Jane Doe — Acme · +3212345 · jane@acme.com"


def test_parse_three_field_record_still_works():
    # back-compat: a person with no phone/email yields the old name—org summary
    ptrs = _parse(_rec("C-2", "Bob", "Acme"))
    assert ptrs[0].summary == "Bob — Acme"


def test_parse_skips_blank_records():
    assert _parse(_RECORD + "   " + _RECORD) == []


def test_parse_tolerates_tab_and_newline_in_field():
    # finding-5 fix: a tab/newline inside a field can no longer split or spoof a pointer
    # — fields/records are delimited by control chars, not tab/newline.
    raw = _rec("C-1", "Jane\tDoe", "Ev\nil Corp")
    ptrs = _parse(raw)
    assert len(ptrs) == 1  # the record is NOT split by the embedded tab/newline
    assert ptrs[0].id == "C-1"
    # #52: the summary is sanitized — the tab/newline collapse to spaces (never a raw
    # control char reaches the model), but the field data survives as text.
    assert ptrs[0].summary == "Jane Doe — Ev il Corp"
    assert "\t" not in ptrs[0].summary and "\n" not in ptrs[0].summary


# --- verify-after-write (#49) --------------------------------------------------------


def _verify_raw(fn: str, ln: str, org: str) -> str:
    return _FIELD.join((fn, ln, org))


def test_verify_contact_passes_on_match():
    data = ContactData(given_name="Jane", family_name="Doe", organization="Acme")
    _verify_contact(_verify_raw("Jane", "Doe", "Acme"), "C-1", data)  # no raise


def test_verify_contact_empty_raw_is_not_found():
    data = ContactData(given_name="Jane")
    with pytest.raises(VerificationFailed, match="could not be re-read"):
        _verify_contact("", "C-1", data)


def test_verify_contact_dropped_org_raises():
    data = ContactData(given_name="Jane", family_name="Doe", organization="Acme")
    with pytest.raises(VerificationFailed, match="organization"):
        _verify_contact(_verify_raw("Jane", "Doe", ""), "C-1", data)  # org dropped


def test_verify_contact_dropped_family_name_raises():
    data = ContactData(given_name="Jane", family_name="Doe")
    with pytest.raises(VerificationFailed, match="family_name"):
        _verify_contact(_verify_raw("Jane", "", ""), "C-1", data)


def test_verify_contact_given_name_only_matches():
    # optional fields absent on both sides ("" ↔ None) must not read as a drop.
    data = ContactData(given_name="Jane")
    _verify_contact(_verify_raw("Jane", "", ""), "C-1", data)  # no raise


def test_verify_contact_empty_given_name_does_not_false_fail():
    # #49 review: an org-only contact (empty given_name) that persisted correctly must
    # not false-fail — given_name must normalize "" ↔ None on BOTH sides.
    data = ContactData(given_name="", organization="Acme")
    _verify_contact(_verify_raw("", "", "Acme"), "C-1", data)  # no raise
