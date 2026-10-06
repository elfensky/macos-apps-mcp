"""Gmail label membership, exercised through both native and sidecar index reads."""

import sqlite3

import pytest

from macos_apps_mcp import runtime
from macos_apps_mcp.adapters import mail, mail_index, mail_recover
from macos_apps_mcp.adapters.mail import MailAdapter
from macos_apps_mcp.errors import SchemaDrift, WriteRefused
from macos_apps_mcp.text import RS, US
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


# --- a label folder is never a write source (#287) ---------------------------


def test_is_label_mailbox_tells_labels_from_physical_and_unknown(gmail_envelope):
    _, _, urls = gmail_envelope
    for name in ("inbox", "sent", "label"):
        assert mail_index.is_label_mailbox(urls[name])
    for name in ("all", "other"):
        assert not mail_index.is_label_mailbox(urls[name])
    assert not mail_index.is_label_mailbox(f"imap://{ACCT_A}/NoSuchFolder")
    assert not mail_index.is_label_mailbox("inbox")


@pytest.mark.parametrize("dry_run", [True, False])
def test_move_mail_refuses_a_label_source(gmail_envelope, dry_run):
    _, _, urls = gmail_envelope
    # The conftest native seam makes runtime.run_osascript raise AssertionError, so a
    # WriteRefused here proves the refusal came before any osascript call.
    with pytest.raises(WriteRefused, match=r"label.*#287"):
        MailAdapter().move_mail(
            "<gmail-2@example.test>", urls["inbox"], urls["other"], dry_run=dry_run
        )


@pytest.mark.parametrize("dry_run", [True, False])
def test_trash_mail_refuses_a_label_source(gmail_envelope, dry_run):
    _, _, urls = gmail_envelope
    # Same seam argument: no osascript ran, or the conftest guard would have fired.
    with pytest.raises(WriteRefused, match=r"label.*#287"):
        MailAdapter().trash_mail(
            "<gmail-2@example.test>", urls["inbox"], dry_run=dry_run
        )


def _present_recorder(monkeypatch):
    seen = []

    def fake(script, *args, **kw):
        seen.append(script)
        ids = args[-1].split(US) if args else []
        return "".join(f"{m}{US}present{RS}" for m in ids if m)

    monkeypatch.setattr(runtime, "run_osascript", fake)
    monkeypatch.setattr(mail_index, "mail_root", lambda: None)
    return seen


def test_move_mail_from_a_physical_source_still_previews(gmail_envelope, monkeypatch):
    _, _, urls = gmail_envelope
    seen = _present_recorder(monkeypatch)
    out = MailAdapter().move_mail("<gmail-2@example.test>", urls["all"], urls["other"])
    assert mail_recover.is_preview(out)
    assert mail._PRESENT in seen


def test_trash_mail_from_a_physical_source_still_previews(gmail_envelope, monkeypatch):
    db, _, urls = gmail_envelope
    db.add_mailbox(f"imap://{ACCT_A}/%5BGmail%5D/Trash")
    seen = _present_recorder(monkeypatch)
    out = MailAdapter().trash_mail("<gmail-2@example.test>", urls["all"])
    assert mail_recover.is_preview(out)
    assert mail._PRESENT in seen


# --- #291: label spelling, canonical source, move into a label ---------------------


def test_is_label_mailbox_matches_any_spelling(gmail_envelope):
    assert mail_index.is_label_mailbox(f"imap://{ACCT_A}/[Gmail]/Sent Mail")
    assert mail_index.is_label_mailbox(
        f"imap://{ACCT_A.lower()}/%5bgmail%5d/sent%20mail"
    )
    assert mail_index.is_label_mailbox(f"imap://{ACCT_A}/inbox")
    assert not mail_index.is_label_mailbox(f"imap://{ACCT_A}/[Gmail]/All Mail")
    assert not mail_index.is_label_mailbox("inbox")


def test_account_has_labels(gmail_envelope):
    assert mail_index.account_has_labels(ACCT_A)
    assert mail_index.account_has_labels(ACCT_A.lower())
    assert not mail_index.account_has_labels(ACCT_B)
    assert not mail_index.account_has_labels(None)


@pytest.mark.parametrize("dry_run", [True, False])
def test_move_and_trash_refuse_a_label_source_in_any_spelling(gmail_envelope, dry_run):
    _, _, urls = gmail_envelope
    # No osascript ran, or the conftest native seam would have raised AssertionError.
    with pytest.raises(WriteRefused, match=r"#287"):
        MailAdapter().move_mail(
            "<gmail-2@example.test>",
            f"imap://{ACCT_A}/[Gmail]/Sent Mail",
            urls["other"],
            dry_run=dry_run,
        )
    with pytest.raises(WriteRefused, match=r"#287"):
        MailAdapter().trash_mail(
            "<gmail-2@example.test>", f"imap://{ACCT_A.lower()}/inbox", dry_run=dry_run
        )


@pytest.mark.parametrize("dry_run", [True, False])
def test_move_mail_refuses_a_label_destination(gmail_envelope, dry_run):
    _, _, urls = gmail_envelope
    # Same seam argument: a WriteRefused proves the refusal came before any osascript.
    for source, dest in (
        (urls["all"], urls["label"]),
        (urls["all"], f"imap://{ACCT_A}/[Gmail]/Sent Mail"),
        (urls["other"], urls["inbox"]),
    ):
        with pytest.raises(WriteRefused, match=r"label.*#291"):
            MailAdapter().move_mail(
                "<gmail-2@example.test>", source, dest, dry_run=dry_run
            )


@pytest.mark.parametrize("dry_run", [True, False])
def test_move_mail_refuses_a_canonical_destination_into_a_labelled_account(
    gmail_envelope, dry_run
):
    _, _, urls = gmail_envelope
    with pytest.raises(WriteRefused, match=r"unified.*#291"):
        MailAdapter().move_mail(
            "<gmail-2@example.test>", urls["all"], "inbox", dry_run=dry_run
        )


def test_move_mail_allows_a_canonical_destination_from_an_unlabelled_account(
    gmail_envelope, monkeypatch
):
    _, _, urls = gmail_envelope
    seen = _present_recorder(monkeypatch)
    out = MailAdapter().move_mail("<gmail-2@example.test>", urls["other"], "drafts")
    assert mail_recover.is_preview(out)
    assert mail._PRESENT in seen


def _receipt(monkeypatch, dest, source):
    rec = {"destination": dest, "backup_dir": "/tmp/backup-291"}
    target = mail_recover.Target(
        id="gmail-2@example.test", folder=source, account=ACCT_A
    )
    monkeypatch.setattr(mail_recover, "undo_plan", lambda rid: (rec, [target]))


@pytest.mark.parametrize("dry_run", [True, False])
def test_undo_refuses_a_receipt_into_a_label_folder(
    gmail_envelope, monkeypatch, dry_run
):
    _, _, urls = gmail_envelope
    # No osascript ran, or the conftest native seam would have raised AssertionError.
    for dest in (urls["label"], f"imap://{ACCT_A}/[Gmail]/Sent Mail"):
        _receipt(monkeypatch, dest, urls["all"])
        with pytest.raises(WriteRefused) as err:
            MailAdapter().undo("r", dry_run=dry_run)
        for part in (urls["all"], "/tmp/backup-291", "by hand"):
            assert part in str(err.value)


@pytest.mark.parametrize("dry_run", [True, False])
def test_undo_refuses_a_receipt_into_a_canonical_name(
    gmail_envelope, monkeypatch, dry_run
):
    _, _, urls = gmail_envelope
    _receipt(monkeypatch, "inbox", urls["all"])
    with pytest.raises(WriteRefused) as err:
        MailAdapter().undo("r", dry_run=dry_run)
    assert "mail_search" in str(err.value)
    assert urls["all"] in str(err.value)


def test_undo_replays_a_receipt_into_a_physical_folder(gmail_envelope, monkeypatch):
    _, _, urls = gmail_envelope
    _receipt(monkeypatch, urls["other"], urls["all"])
    seen = _present_recorder(monkeypatch)
    out = MailAdapter().undo("r")
    assert mail_recover.is_preview(out)
    assert mail._PRESENT in seen


# --- thread, sent triage and stats follow logical membership (#287) -----------------


def _sent_triage_setup(db):
    db.execute("UPDATE message_global_data SET message_id = 903 WHERE ROWID = 503")


def _add_reply(db, boxes, *names):
    """Row 106: a physical All Mail row citing row 103, labelled with ``names``."""
    db.add_message(
        ROWID=106,
        subject=1,
        global_message_id=506,
        message_id=906,
        mailbox=boxes["all"],
        date_received=1006,
        deleted=0,
    )
    for name in names:
        db.execute("INSERT INTO labels VALUES (106, ?)", (boxes[name],))
    db.execute("INSERT INTO message_references(message, reference) VALUES (106, 903)")


def test_sent_triage_counts_a_label_only_sent_message(gmail_envelope):
    db, _, _ = gmail_envelope
    _sent_triage_setup(db)
    [row] = mail_index.query_sent_triage(10)
    assert (row["rowid"], row["mid"], row["answered"]) == (
        103,
        "<gmail-3@example.test>",
        0,
    )


def test_sent_triage_answered_needs_a_reply_under_the_inbox_label(gmail_envelope):
    db, boxes, _ = gmail_envelope
    _sent_triage_setup(db)
    _add_reply(db, boxes, "inbox")
    [row] = mail_index.query_sent_triage(10)
    assert row["answered"] == 1


def test_sent_triage_reply_under_another_label_does_not_answer(gmail_envelope):
    db, boxes, _ = gmail_envelope
    _sent_triage_setup(db)
    _add_reply(db, boxes, "label")
    [row] = mail_index.query_sent_triage(10)
    assert row["answered"] == 0


def test_thread_cites_the_same_folder_search_cites(gmail_envelope):
    db, _, urls = gmail_envelope
    db.execute("UPDATE messages SET conversation_id = 7 WHERE ROWID IN (101, 102)")
    thread = mail_index.query_thread("<gmail-1@example.test>", 10)
    assert {p.id for p in thread} == {
        "<gmail-1@example.test>",
        "<gmail-2@example.test>",
    }
    for p in thread:
        assert p.folder == urls["inbox"]
        assert p.folder == mail_index.query_search(message_ids=[p.id])[0].folder


def test_stats_attribute_gmail_messages_to_inbox_and_sent(gmail_envelope):
    _, _, urls = gmail_envelope
    rows = mail_index.query_stats_rows(0)
    assert sorted(r["mailbox_url"] for r in rows) == sorted(
        [urls["inbox"], urls["inbox"], urls["sent"]]
    )
