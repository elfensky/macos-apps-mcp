"""Unit tests for the messages adapter — pure parsing (no osascript)."""

from __future__ import annotations

from mac_mcp.adapters.messages import _parse
from mac_mcp.contracts import Pointer


def test_parse_guid_and_name():
    ptrs = _parse("guid-1\tFamily\nguid-2\t\n")
    assert len(ptrs) == 2
    assert isinstance(ptrs[0], Pointer)
    assert ptrs[0].id == "guid-1" and ptrs[0].summary == "Family"
    assert ptrs[0].deeplink == ""
    assert ptrs[1].summary == "(chat)"  # unnamed 1:1 chat


def test_parse_skips_blank():
    assert _parse("\n  \n") == []


def test_parse_sanitizes_control_chars_in_summary():
    # #52 routing: a chat name carrying a control char is stripped before it reaches the
    # model (deleting clean_summary from _parse would fail this).
    ptr = _parse("guid-1\tTeam\x07Alert\n")[0]
    assert ptr.summary == "TeamAlert" and "\x07" not in ptr.summary
