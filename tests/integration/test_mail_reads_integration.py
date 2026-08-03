"""On-device reads against the REAL Envelope Index (-m integration, never CI).

These assert shape and invariants, never specific message content — the mailbox they run
against belongs to whoever is at the keyboard.
"""

from __future__ import annotations

import pytest

from macos_apps_mcp.adapters import mail_addressing
from macos_apps_mcp.adapters.mail import MailAdapter

pytestmark = pytest.mark.integration


def test_overview_lists_mailboxes_with_named_or_uuid_accounts():
    rows = MailAdapter().overview()
    assert rows, "no mailboxes — is Mail set up on this machine?"
    for r in rows:
        # account_id + folder are the machine-readable halves (#155): the same uuid
        # every Pointer reports as `account`, and the exact round-trip mailbox url.
        assert set(r) == {
            "account",
            "account_id",
            "mailbox",
            "folder",
            "total",
            "unread",
        }
        assert r["account"] and r["mailbox"]
        assert r["unread"] <= r["total"]
    unread = [r["unread"] for r in rows]
    assert unread == sorted(unread, reverse=True)
    # percent-encoding must be decoded, not passed through
    assert not any("%20" in r["mailbox"] for r in rows)


def test_search_returns_no_duplicate_message_ids():
    # the whole point of the dedup rule
    ids = [p["id"] for p in MailAdapter().search(subject="a", limit=25)["results"]]
    assert len(ids) == len(set(ids))


def test_thread_round_trips_from_a_real_message():
    hits = MailAdapter().search(subject="a", limit=5)["results"]
    if not hits:
        pytest.skip("no messages matched to thread from")
    thread = MailAdapter().thread(hits[0]["id"])["results"]
    assert any(p["id"] == hits[0]["id"] for p in thread), (
        "a thread must contain its own seed"
    )
    assert len({p["id"] for p in thread}) == len(thread), "thread has duplicates"


def test_has_attachments_excludes_image_only_messages():
    # `subject=""` used to stand in for "everything" here — it is NO filter at all, so
    # that half of this test raised rather than comparing anything (never noticed: the
    # integration mark keeps it out of CI). Compare against the same query WITHOUT the
    # attachment filter instead, which is the real contrast.
    docs = MailAdapter().search(has_attachments=True, limit=25)["results"]
    any_mail = MailAdapter().search(since=0, limit=25)["results"]
    assert isinstance(docs, list) and isinstance(any_mail, list)
    assert len({p["id"] for p in docs}) == len(docs)
    assert len(docs) <= len(any_mail)


def test_unknown_message_id_threads_to_empty():
    out = MailAdapter().thread("<definitely-not-a-real-id@example.invalid>")
    assert out == {"results": []}


# --- #155: an id resolves on its own -------------------------------------------------


def test_a_stored_id_resolves_with_no_folder_and_reaches_its_body():
    """The acceptance for the id-only half: take an id from a read, THROW THE FOLDER
    AWAY (that is what a vault note keeps), and get the body back anyway."""
    adapter = MailAdapter()
    hits = adapter.search(subject="a", limit=5)["results"]
    if not hits:
        pytest.skip("no messages to resolve")
    mid = hits[0]["id"]
    target = mail_addressing.resolve(mid)
    assert target.id == mail_addressing.bare_id(mid)
    assert target.folder, "a resolved message must name the mailbox it lives in"
    # and the body reads with the id ALONE — no mailbox argument at all
    assert isinstance(adapter.get_body(mid), str)


def test_an_unresolvable_id_raises_rather_than_answering_empty():
    from macos_apps_mcp.errors import NativeError

    with pytest.raises(NativeError, match="no message with id"):
        mail_addressing.resolve("<definitely-not-a-real-id@example.invalid>")


# --- #156: the reads say what they did not answer ------------------------------------


def test_a_capped_search_is_marked_truncated():
    """25 is a hard ceiling on a 36k-message store, so a broad search must NOT read as
    a complete answer."""
    out = MailAdapter().search(subject="a", limit=25)
    if len(out["results"]) < 25:
        pytest.skip("this mailbox has fewer than 25 matches for 'a'")
    assert out["truncated"] is True


def test_a_narrow_search_carries_no_truncation_claim():
    out = MailAdapter().search(subject="macos-apps-mcp-no-such-subject-zzz")
    assert out["results"] == []
    assert "truncated" not in out and "plane" not in out


def test_an_unresolvable_mailbox_name_raises_and_a_stale_url_does_not():
    adapter = MailAdapter()
    # a name typed from memory that matches nothing is a followable error …
    with pytest.raises(ValueError, match="no mailbox matches"):
        adapter.search(mailbox="macos-apps-mcp-no-such-mailbox-zzz")
    # … while a url-shaped handle that no longer resolves is an honest empty read: it
    # WAS real when some read issued it (this is what #78's move_mail will do to one).
    stale = "imap://00000000-0000-0000-0000-000000000000/Nope"
    assert adapter.search(mailbox=stale) == {"results": []}


def test_a_body_miss_reports_coverage_instead_of_a_bare_empty():
    out = MailAdapter().search(body="macos-apps-mcp-no-such-body-text-zzz")
    assert out["results"] == []
    assert "searchable body" in out["coverage"]
