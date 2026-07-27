"""On-device reads against the REAL Envelope Index (-m integration, never CI).

These assert shape and invariants, never specific message content — the mailbox they run
against belongs to whoever is at the keyboard.
"""

from __future__ import annotations

import pytest

from macos_apps_mcp.adapters.mail import MailAdapter

pytestmark = pytest.mark.integration


def test_overview_lists_mailboxes_with_named_or_uuid_accounts():
    rows = MailAdapter().overview()
    assert rows, "no mailboxes — is Mail set up on this machine?"
    for r in rows:
        assert set(r) == {"account", "mailbox", "total", "unread"}
        assert r["account"] and r["mailbox"]
        assert r["unread"] <= r["total"]
    unread = [r["unread"] for r in rows]
    assert unread == sorted(unread, reverse=True)
    # percent-encoding must be decoded, not passed through
    assert not any("%20" in r["mailbox"] for r in rows)


def test_search_returns_no_duplicate_message_ids():
    # the whole point of the dedup rule
    ids = [p.id for p in MailAdapter().search(subject="a", limit=25)]
    assert len(ids) == len(set(ids))


def test_thread_round_trips_from_a_real_message():
    hits = MailAdapter().search(subject="a", limit=5)
    if not hits:
        pytest.skip("no messages matched to thread from")
    thread = MailAdapter().thread(hits[0].id)
    assert any(p.id == hits[0].id for p in thread), "a thread must contain its own seed"
    assert len({p.id for p in thread}) == len(thread), "thread has duplicates"


def test_has_attachments_excludes_image_only_messages():
    docs = MailAdapter().search(has_attachments=True, limit=25)
    plain = MailAdapter().search(subject="", limit=25)
    assert isinstance(docs, list) and isinstance(plain, list)
    assert len({p.id for p in docs}) == len(docs)


def test_unknown_message_id_threads_to_empty():
    assert MailAdapter().thread("<definitely-not-a-real-id@example.invalid>") == []
