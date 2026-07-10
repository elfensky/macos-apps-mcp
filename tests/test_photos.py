"""Unit tests for the photos adapter — pure parsing (no osascript)."""

from __future__ import annotations

from mac_mcp.adapters.photos import _parse
from mac_mcp.contracts import Pointer


def test_parse_id_and_filename():
    ptrs = _parse("ABC123\tIMG_0001.jpg\nDEF456\t\n")
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
    ptr = _parse("ABC123\tIMG\x07_1.jpg\n")[0]
    assert ptr.summary == "IMG_1.jpg" and "\x07" not in ptr.summary
