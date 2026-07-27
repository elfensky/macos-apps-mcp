import asyncio
import sqlite3

import pytest
from fastmcp import Client

import macos_apps_mcp.server as srv
from macos_apps_mcp.adapters import mail_index
from macos_apps_mcp.adapters.mail import MAX_MAILS, MailAdapter
from macos_apps_mcp.errors import NativeError


def _fake_envelope(path):
    """A minimal Envelope Index with the fingerprinted tables + columns.

    Deliberately includes the duplicate shapes found on a real Mac: <abc@ex.com> exists
    in INBOX *and* Archive (cross-folder), and <dup@ex.com> exists twice in the SAME
    folder (a migration copy that ran twice). Dedup tests depend on both.
    """
    c = sqlite3.connect(path)
    c.executescript(
        """
        CREATE TABLE subjects(ROWID INTEGER PRIMARY KEY, subject TEXT);
        CREATE TABLE addresses(ROWID INTEGER PRIMARY KEY, address TEXT, comment TEXT);
        CREATE TABLE mailboxes(ROWID INTEGER PRIMARY KEY, url TEXT);
        CREATE TABLE message_global_data(
            ROWID INTEGER PRIMARY KEY, message_id_header TEXT);
        CREATE TABLE recipients(ROWID INTEGER PRIMARY KEY, message INT, address INT);
        CREATE TABLE attachments(
            ROWID INTEGER PRIMARY KEY, message INT, name TEXT);
        CREATE TABLE messages(
            ROWID INTEGER PRIMARY KEY, subject INT, sender INT, global_message_id INT,
            mailbox INT, date_received INT, date_sent INT, read INT, flagged INT,
            deleted INT, conversation_id INT);
        INSERT INTO subjects VALUES (1,'Invoice 42'),(2,'Re: Invoice 42');
        INSERT INTO addresses VALUES (1,'jane@ex.com','Jane Doe');
        INSERT INTO mailboxes VALUES
            (1,'imap://AAAA/INBOX'),(2,'imap://AAAA/Archive'),(3,'imap://BBBB/Travel');
        INSERT INTO message_global_data VALUES
            (1,'<abc@ex.com>'),(2,'<reply@ex.com>'),(3,'<dup@ex.com>');
        -- <abc@ex.com>: INBOX + Archive, same conversation 7 as its reply
        INSERT INTO messages VALUES (10,1,1,1,1,1700000000,1700000000,0,0,0,7);
        INSERT INTO messages VALUES (11,1,1,1,2,1700000000,1700000000,0,0,0,7);
        -- the reply, newer, in Travel, conversation 7
        INSERT INTO messages VALUES (12,2,1,2,3,1700000900,1700000900,1,0,0,7);
        -- <dup@ex.com>: twice in the SAME mailbox, unrelated conversation
        INSERT INTO messages VALUES (13,1,1,3,3,1700000500,1700000500,0,0,0,9);
        INSERT INTO messages VALUES (14,1,1,3,3,1700000500,1700000500,0,0,0,9);
        INSERT INTO attachments VALUES (1,10,'contract.pdf'),(2,12,'image001.png');
        """
    )
    c.commit()
    c.close()


def test_search_returns_pointers_from_sqlite(tmp_path, monkeypatch):
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    out = MailAdapter().search(subject="Invoice")
    hit = [p for p in out if p.id == "<abc@ex.com>"]
    assert len(hit) == 1  # INBOX + Archive copies collapse to one
    assert hit[0].summary == "Invoice 42"


def test_search_falls_back_on_drift(tmp_path, monkeypatch):
    db = tmp_path / "Envelope Index"
    # missing cols → drift
    sqlite3.connect(db).executescript("CREATE TABLE messages(ROWID INTEGER);")
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    adapter = MailAdapter()
    monkeypatch.setattr(adapter, "get_pointers", lambda q: ["FALLBACK"])
    assert adapter.search(subject="x") == ["FALLBACK"]


def test_search_no_store_raises(monkeypatch):
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: None)
    with pytest.raises(NativeError):
        MailAdapter().search(subject="x")


def test_search_body_intersects_fts(tmp_path, monkeypatch):
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    # FTS returns the one indexed message-id; header join keeps it
    monkeypatch.setattr(mail_index, "fts_path", lambda: tmp_path / "fts.sqlite")
    monkeypatch.setattr(
        mail_index, "fts_search", lambda db_, q, limit=200: ["<abc@ex.com>"]
    )
    out = MailAdapter().search(body="invoice")
    assert [p.id for p in out] == ["<abc@ex.com>"]


def test_search_body_empty_index_returns_empty(tmp_path, monkeypatch):
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    monkeypatch.setattr(mail_index, "fts_search", lambda db_, q, limit=200: [])
    assert MailAdapter().search(body="nothing") == []


def test_search_body_does_not_fall_back_on_drift(tmp_path, monkeypatch):
    db = tmp_path / "Envelope Index"
    # missing cols → drift
    sqlite3.connect(db).executescript("CREATE TABLE messages(ROWID INTEGER);")
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    monkeypatch.setattr(mail_index, "fts_path", lambda: tmp_path / "fts.sqlite")
    monkeypatch.setattr(
        mail_index, "fts_search", lambda db_, q, limit=200: ["<abc@ex.com>"]
    )
    adapter = MailAdapter()
    monkeypatch.setattr(adapter, "get_pointers", lambda q: ["SENTINEL"])
    # subject= is also set so `needle` is non-empty (as it would be for a realistic
    # combined body+header search) — this is what makes the AppleScript fallback
    # eligible to fire under the pre-fix wiring.
    with pytest.raises(NativeError):
        adapter.search(body="x", subject="x")


def test_index_bodies_no_mail_root_raises(monkeypatch):
    from macos_apps_mcp.adapters import mail_index

    monkeypatch.setattr(mail_index, "mail_root", lambda: None)
    with pytest.raises(NativeError):
        MailAdapter().index_bodies()


def test_index_bodies_builds_coverage(tmp_path, monkeypatch):
    from macos_apps_mcp.adapters import mail_index

    monkeypatch.setattr(mail_index, "mail_root", lambda: tmp_path)
    fixed = {"indexed": 3, "skipped": 1, "total_emlx": 4, "capped": False}
    monkeypatch.setattr(
        mail_index,
        "build_body_index",
        lambda mail_root, fts_db, rebuild: dict(fixed),
    )
    out = MailAdapter().index_bodies()
    assert out["indexed"] == 3
    assert out["skipped"] == 1
    assert out["total_emlx"] == 4
    assert out["capped"] is False
    assert out["coverage"] == "3/4 downloaded .emlx indexed"


def test_search_clamps_limit_to_max_mails(tmp_path, monkeypatch):
    # A huge limit with body= would otherwise build an oversized `message_ids IN
    # (...)` clause and ignore the promised MAX_MAILS backstop (#70 review M1).
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    captured = {}
    real_build_header_query = mail_index.build_header_query

    def spy(**kwargs):
        captured["limit"] = kwargs.get("limit")
        return real_build_header_query(**kwargs)

    monkeypatch.setattr(mail_index, "build_header_query", spy)
    MailAdapter().search(subject="Invoice", limit=10_000)
    assert captured["limit"] == MAX_MAILS


def test_mail_search_since_zero_not_rejected(monkeypatch):
    # since=0 (epoch 0) is a valid timestamp, not an absent filter — the `not any([...
    # since ...])` guard wrongly treated it as falsy (#70 review M3).
    class _F:
        def search(self, **kwargs):
            return []

    monkeypatch.setattr(srv, "_mail", _F())
    assert srv.mail_search(since=0) == []


def test_mail_search_tool_registered_read_only():
    async def go():
        async with Client(srv.mcp) as c:
            tools = {t.name: t for t in await c.list_tools()}
            assert "mail_search" in tools and "mail_index_bodies" in tools
            assert tools["mail_search"].annotations.readOnlyHint is True
            assert tools["mail_index_bodies"].annotations.readOnlyHint is True

    asyncio.run(go())


def test_search_dedupes_cross_folder_preferring_inbox(tmp_path, monkeypatch):
    # <abc@ex.com> is in INBOX and Archive. One Pointer, and it cites the INBOX copy.
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    out = MailAdapter().search(subject="Invoice 42")
    assert [p.id for p in out].count("<abc@ex.com>") == 1
    inbox = [p for p in out if p.id == "<abc@ex.com>"][0]
    assert inbox.folder == "imap://AAAA/INBOX"


def test_search_dedupes_same_folder_copies(tmp_path, monkeypatch):
    # <dup@ex.com> exists twice in the SAME mailbox (migration ran twice) — collapses.
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    out = MailAdapter().search(subject="Invoice", limit=25)
    assert [p.id for p in out].count("<dup@ex.com>") == 1


def test_search_limit_counts_distinct_messages(tmp_path, monkeypatch):
    # LIMIT must apply AFTER dedup: limit=2 over 5 rows / 3 distinct ids returns 2
    # messages, not 2 rows that collapse to 1.
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    out = MailAdapter().search(subject="Invoice", limit=2)
    assert len(out) == 2
    assert len({p.id for p in out}) == 2


def test_search_has_attachments_matches_document_not_image(tmp_path, monkeypatch):
    # msg 10 (<abc@ex.com>) has contract.pdf; msg 12 (<reply@ex.com>) has only
    # image001.png and must NOT match.
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    ids = [p.id for p in MailAdapter().search(has_attachments=True)]
    assert "<abc@ex.com>" in ids
    assert "<reply@ex.com>" not in ids


def test_search_account_filters_by_uuid(tmp_path, monkeypatch):
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    # mailbox 3 (imap://BBBB/Travel) holds <reply@ex.com> and both <dup@ex.com> copies
    ids = [p.id for p in MailAdapter().search(account="BBBB")]
    assert set(ids) == {"<reply@ex.com>", "<dup@ex.com>"}
    assert "<abc@ex.com>" not in ids  # lives only under account AAAA


def test_thread_returns_whole_conversation_oldest_first(tmp_path, monkeypatch):
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    out = MailAdapter().thread("<abc@ex.com>")
    # conversation 7 holds <abc@ex.com> (INBOX + Archive) and its reply
    assert [p.id for p in out] == ["<abc@ex.com>", "<reply@ex.com>"]
    assert out[0].folder == "imap://AAAA/INBOX"  # deduped to the INBOX copy


def test_thread_finds_conversation_from_any_member(tmp_path, monkeypatch):
    # asking with the REPLY's id must return the same thread, not just the reply
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    assert len(MailAdapter().thread("<reply@ex.com>")) == 2


def test_thread_truncation_keeps_the_newest(tmp_path, monkeypatch):
    # when the point of reading a thread is to reply, the OLD end is the end to drop
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    out = MailAdapter().thread("<abc@ex.com>", limit=1)
    assert [p.id for p in out] == ["<reply@ex.com>"]


def test_thread_unknown_id_returns_empty(tmp_path, monkeypatch):
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    assert MailAdapter().thread("<nope@ex.com>") == []


def test_overview_reports_counts_and_decodes_names(tmp_path, monkeypatch):
    import macos_apps_mcp.adapters.mail as m

    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    m._ACCOUNT_MAP_CACHE = {"AAAA": "Personal"}
    rows = MailAdapter().overview()
    by_box = {r["mailbox"]: r for r in rows}
    assert by_box["INBOX"]["account"] == "Personal"
    assert by_box["INBOX"]["total"] == 1 and by_box["INBOX"]["unread"] == 1
    # BBBB has no name in the map -> the UUID stands in, the call still succeeds
    assert by_box["Travel"]["account"] == "BBBB"


def test_overview_survives_mail_being_unreachable(tmp_path, monkeypatch):
    import macos_apps_mcp.adapters.mail as m

    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    m._ACCOUNT_MAP_CACHE = None
    monkeypatch.setattr(m, "run_osascript", lambda *a: (_ for _ in ()).throw(OSError()))
    rows = MailAdapter().overview()
    assert rows  # counts never needed Mail
    assert all(r["account"] for r in rows)  # UUID stands in for the name


def test_overview_sorts_unread_first(tmp_path, monkeypatch):
    import macos_apps_mcp.adapters.mail as m

    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    m._ACCOUNT_MAP_CACHE = {}
    unread = [r["unread"] for r in MailAdapter().overview()]
    assert unread == sorted(unread, reverse=True)
