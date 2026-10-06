"""Gmail label membership, exercised through both native and sidecar index reads."""

import sqlite3

import pytest

from macos_apps_mcp.adapters import mail_index
from macos_apps_mcp.adapters.mail import MailAdapter
from macos_apps_mcp.errors import SchemaDrift
from tests.envelope import ACCT_A, ACCT_B


@pytest.fixture
def gmail_envelope(blank_envelope):
    db = blank_envelope
    urls = {
        "all": f"imap://{ACCT_A}/%5BGmail%5D/All%20Mail",
        "inbox": f"imap://{ACCT_A}/INBOX",
        "sent": f"imap://{ACCT_A}/%5BGmail%5D/Sent%20Mail",
        "label": f"imap://{ACCT_A}/Receipts",
        "empty": f"imap://{ACCT_A}/Empty",
        "other": f"imap://{ACCT_B}/INBOX",
        "stale": f"imap://{ACCT_A}/Stale",
    }
    boxes = {"all": db.add_mailbox(urls["all"])}
    for name in ("inbox", "sent", "label", "empty"):
        boxes[name] = db.add_mailbox(urls[name], source=boxes["all"])
    boxes["other"] = db.add_mailbox(urls["other"])
    boxes["stale"] = db.add_mailbox(urls["stale"], source=boxes["other"])
    db.execute("INSERT INTO subjects VALUES (1, 'Membership regression')")
    for i in range(1, 6):
        # ROWID, global_message_id and message_id intentionally differ. Labels
        # refer to the first, even though their column is named message_id.
        mid = f"<gmail-{1 if i == 4 else i}@example.test>"
        db.execute(
            "INSERT INTO message_global_data(ROWID, message_id_header) VALUES (?, ?)",
            (500 + i, mid),
        )
        db.add_message(
            ROWID=100 + i,
            subject=1,
            global_message_id=500 + i,
            message_id=900 + i,
            mailbox=boxes["all"],
            date_received=1000 + i,
            read=int(i in (2, 3)),
            deleted=int(i == 5),
        )
    for rowid, names in (
        (101, ("inbox", "label")),
        (102, ("inbox",)),
        (103, ("sent", "label")),
        (104, ("inbox", "label")),  # duplicate Message-ID, distinct stored row
        (105, ("inbox", "sent", "label")),  # deleted, never counted
    ):
        for name in names:
            db.execute("INSERT INTO labels VALUES (?, ?)", (rowid, boxes[name]))
    return db, boxes, urls


def _overview():
    return {
        r["mailbox_url"]: (r["total"], r["unread"])
        for r in mail_index.query_overview_rows()
    }


def test_overview_counts_label_memberships_and_preserves_dedup(gmail_envelope):
    _, _, urls = gmail_envelope
    assert _overview() == {
        urls["all"]: (3, 1),
        urls["inbox"]: (2, 1),
        urls["sent"]: (1, 0),
        urls["label"]: (2, 1),
        urls["empty"]: (0, 0),
        urls["other"]: (0, 0),
        urls["stale"]: (0, 0),
    }


def test_overview_keeps_headerless_label_members(gmail_envelope):
    db, boxes, urls = gmail_envelope
    for rowid, is_read in ((106, 0), (107, 1)):
        db.add_message(ROWID=rowid, mailbox=boxes["all"], deleted=0, read=is_read)
        db.execute("INSERT INTO labels VALUES (?, ?)", (rowid, boxes["inbox"]))
    assert _overview()[urls["inbox"]] == (4, 2)


def test_overview_url_round_trips_into_indexed_search(gmail_envelope):
    _, _, urls = gmail_envelope
    inbox_url = next(
        r["mailbox_url"]
        for r in mail_index.query_overview_rows()
        if r["mailbox_url"] == urls["inbox"]
    )
    results = MailAdapter().search(mailbox=inbox_url, account=ACCT_A)["results"]
    assert {p["id"] for p in results} == {
        "<gmail-1@example.test>",
        "<gmail-2@example.test>",
    }
    assert len(results) == 2
    assert all(p["folder"] == inbox_url and p["account"] == ACCT_A for p in results)
    unread = MailAdapter().search(mailbox=inbox_url, unread=True)["results"]
    assert [p["id"] for p in unread] == ["<gmail-1@example.test>"]


def test_search_ranks_inbox_and_limits_distinct_messages(gmail_envelope):
    _, _, urls = gmail_envelope
    results = mail_index.query_search(subject="Membership", account=ACCT_A, limit=2)
    assert [p.id for p in results] == [
        "<gmail-1@example.test>",
        "<gmail-3@example.test>",
    ]
    assert results[0].folder == urls["inbox"]
    # One stored message belongs to several labels. A label-scoped result must
    # still cite that label, even when Inbox would win an unscoped search.
    results = mail_index.query_search(mailbox_urls=[urls["label"]], limit=10)
    assert {p.id for p in results} == {
        "<gmail-1@example.test>",
        "<gmail-3@example.test>",
    }
    assert all(p.folder == urls["label"] for p in results)
    assert mail_index.query_search(account=ACCT_B) == []


def test_unscoped_search_breaks_an_equal_rank_label_tie_by_mailbox_rowid(
    gmail_envelope,
):
    db, boxes, _ = gmail_envelope
    # One stored row appears once per label membership (#251), so m.ROWID no longer
    # ends the window order. Zeta/Alpha are named against url order so a url sort
    # cannot pass by accident: Zeta has the lower mailboxes.ROWID and must win.
    zeta = f"imap://{ACCT_A}/Zeta"
    zeta_id = db.add_mailbox(zeta, source=boxes["all"])
    alpha_id = db.add_mailbox(f"imap://{ACCT_A}/Alpha", source=boxes["all"])
    db.execute(
        "INSERT INTO message_global_data(ROWID, message_id_header) VALUES (510, ?)",
        ("<tie@example.test>",),
    )
    db.add_message(
        ROWID=110,
        subject=1,
        global_message_id=510,
        message_id=910,
        mailbox=boxes["all"],
        date_received=2000,
        read=0,
        deleted=0,
    )
    for box in (zeta_id, alpha_id):
        db.execute("INSERT INTO labels VALUES (110, ?)", (box,))
    assert "m.ROWID, mb.ROWID) AS rn" in " ".join(mail_index._BASE_SQL.split())
    for _ in range(2):
        [p] = mail_index.query_search(message_ids=["<tie@example.test>"])
        assert p.folder == zeta


def test_membership_obeys_the_mailbox_source(gmail_envelope):
    db, boxes, urls = gmail_envelope
    # Existing label rows can refer to a different backing store or to an
    # ordinary mailbox. Mail's own counter triggers exclude both relationships.
    db.execute("INSERT INTO labels VALUES (?, ?)", (101, boxes["stale"]))
    db.execute("INSERT INTO labels VALUES (?, ?)", (101, boxes["other"]))
    # Direct rows on a virtual mailbox are not logical members either.
    db.add_message(
        ROWID=108,
        mailbox=boxes["empty"],
        subject=1,
        global_message_id=501,
        deleted=0,
        read=0,
    )
    counts = _overview()
    for name in ("stale", "other", "empty"):
        assert counts[urls[name]] == (0, 0)
        assert mail_index.query_search(mailbox_urls=[urls[name]]) == []
    assert counts[urls["inbox"]] == (2, 1)


def test_label_expansion_does_not_change_physical_file_locations(gmail_envelope):
    _, _, urls = gmail_envelope
    rows = mail_index.query_message_locations(["<gmail-1@example.test>"])
    assert {r["rowid"] for r in rows} == {101, 104}
    assert all(r["mailbox_url"] == urls["all"] for r in rows)


@pytest.mark.parametrize(
    "change",
    [
        "DROP TABLE labels",
        "ALTER TABLE labels RENAME COLUMN message_id TO unknown_message_id",
        "ALTER TABLE mailboxes RENAME COLUMN source TO unknown_source",
    ],
)
def test_missing_membership_schema_fails_loudly(gmail_envelope, change):
    db, _, _ = gmail_envelope
    # ALTER/DROP operate only on the isolated fixture, never on the user's index.
    with sqlite3.connect(db.path) as conn:
        conn.execute(change)
    with pytest.raises(SchemaDrift):
        mail_index.query_overview_rows()
