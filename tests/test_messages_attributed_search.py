"""messages_search / messages_with read text that lives only in ``attributedBody``
(#576). The blobs use the real typedstream layout: NUL bytes come before the text, so
a raw-blob LIKE never reaches it."""

from __future__ import annotations

from datetime import datetime

import pytest

from macos_apps_mcp.adapters import messages
from tests.test_messages import _make_chatdb, _ns, _typedstream


@pytest.fixture
def store(tmp_path, monkeypatch):
    d = _ns(datetime(2024, 5, 1))
    path = _make_chatdb(
        tmp_path / "chat.db",
        handles=[(1, "+3210")],
        messages_rows=[
            ("g-ab", None, _typedstream(b"Hello from body"), d, 0, 0, 0, 0, 1),
            ("g-empty", "", _typedstream(b"50% off_sale"), d - 1, 0, 0, 0, 0, 1),
            ("g-text", "plain hello", None, d - 2, 0, 0, 0, 0, 1),
            ("g-junk", None, b"\x00garbage hello", d - 3, 0, 0, 0, 0, 1),
        ],
    )
    monkeypatch.setattr(messages, "CHAT_DB", path)
    return messages.MessagesAdapter()


def test_null_text_found_by_body_word_and_text_still_matches(store):
    assert [p.id for p in store.search_messages("hello")] == ["g-ab", "g-text"]


def test_snippet_shows_decoded_body(store):
    ptr = store.search_messages("from body")[0]
    assert ptr.id == "g-ab" and ptr.summary.endswith(": Hello from body")


def test_messages_with_snippet_shows_decoded_body(store):
    summaries = {p.id: p.summary for p in store.messages_with("+3210")}
    assert summaries["g-ab"].endswith(": Hello from body")
    assert summaries["g-empty"].endswith(": 50% off_sale")


def test_case_rule_is_like_ascii_insensitive(store):
    assert [p.id for p in store.search_messages("HELLO FROM")] == ["g-ab"]


def test_percent_and_underscore_stay_literal(store):
    assert [p.id for p in store.search_messages("0% off_s")] == ["g-empty"]
    assert store.search_messages("off%sale") == []
    assert store.search_messages("5_%") == []
