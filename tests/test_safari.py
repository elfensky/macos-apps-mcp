"""Unit tests for the safari adapter — pure parsing (no osascript)."""

from __future__ import annotations

import pytest

from mac_mcp.adapters.safari import _normalize_url, _parse
from mac_mcp.contracts import Pointer


def test_parse_url_and_title():
    raw = "https://x.com/a\tPage A\nhttps://y.com/\t\n"
    ptrs = _parse(raw)
    assert len(ptrs) == 2
    assert isinstance(ptrs[0], Pointer)
    assert ptrs[0].id == "https://x.com/a" and ptrs[0].summary == "Page A"
    assert ptrs[0].deeplink == "https://x.com/a"
    # empty title falls back to the URL
    assert ptrs[1].summary == "https://y.com/"


def test_parse_skips_blank():
    assert _parse("\n  \n") == []


def test_normalize_url_adds_scheme():
    assert _normalize_url("example.com") == "https://example.com"


def test_normalize_url_keeps_existing_scheme():
    assert _normalize_url("  http://x.com/a  ") == "http://x.com/a"


def test_normalize_url_empty_raises():
    with pytest.raises(ValueError, match="needs a URL"):
        _normalize_url("   ")


def test_normalize_url_keeps_host_port():
    # schemeless host:port must still default to https, not be read as a scheme
    assert _normalize_url("localhost:8080") == "https://localhost:8080"


def test_normalize_url_rejects_file_scheme():
    with pytest.raises(ValueError, match="http/https"):
        _normalize_url("file:///etc/passwd")


def test_normalize_url_rejects_app_scheme():
    with pytest.raises(ValueError, match="http/https"):
        _normalize_url("shortcuts://run-shortcut?name=Evil")


def test_parse_sanitizes_control_chars_in_summary():
    # #52 routing: a web page title (attacker-controllable) carrying a control char is
    # stripped before it reaches the model (deleting clean_summary from _parse fails).
    ptr = _parse("https://x.com/a\tBreaking\x07 News\n")[0]
    assert ptr.summary == "Breaking News" and "\x07" not in ptr.summary
