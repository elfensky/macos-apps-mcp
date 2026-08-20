"""Unit tests for the photos adapter — pure parsing (no osascript)."""

from __future__ import annotations

from macos_apps_mcp.adapters.photos import _parse
from macos_apps_mcp.contracts import Pointer
from macos_apps_mcp.text import RS, US


def test_parse_id_and_filename():
    ptrs = _parse(f"ABC123{US}IMG_0001.jpg{RS}DEF456{US}{RS}")
    assert len(ptrs) == 2
    assert isinstance(ptrs[0], Pointer)
    assert ptrs[0].id == "ABC123" and ptrs[0].summary == "IMG_0001.jpg"
    assert ptrs[0].deeplink == ""
    assert ptrs[1].summary == "(photo)"


def test_parse_skips_blank():
    assert _parse("\n  \n") == []


def test_parse_sanitizes_control_chars_in_summary():
    # #52 routing: a filename carrying a control char is stripped before it reaches the
    # model (deleting clean_summary from _parse would fail this).
    ptr = _parse(f"ABC123{US}IMG\x07_1.jpg{RS}")[0]
    assert ptr.summary == "IMG_1.jpg" and "\x07" not in ptr.summary


def test_parse_survives_newline_in_filename():
    # US/RS framing (C4-B): a newline in a filename no longer splits the record.
    ptr = _parse(f"ABC123{US}IMG\n_1.jpg{RS}")[0]
    assert ptr.summary == "IMG _1.jpg"


def test_parse_absent_filename_falls_back_to_the_placeholder():
    # AppleScript reports an absent property as the literal "missing value" once it is
    # concatenated into the wire — indistinguishable from a real value, so it defeated
    # the `or "(photo)"` fallback and shipped `missing value` as the summary.
    ptr = _parse(f"ABC123{US}missing value{RS}")[0]
    assert ptr.summary == "(photo)"
