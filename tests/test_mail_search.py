import sqlite3

import pytest

from macos_apps_mcp.adapters import mail_index
from macos_apps_mcp.adapters.mail import MailAdapter
from macos_apps_mcp.errors import NativeError


def _fake_envelope(path):
    """A minimal Envelope Index with the fingerprinted tables + columns."""
    c = sqlite3.connect(path)
    c.executescript(
        """
        CREATE TABLE subjects(ROWID INTEGER PRIMARY KEY, subject TEXT);
        CREATE TABLE addresses(ROWID INTEGER PRIMARY KEY, address TEXT, comment TEXT);
        CREATE TABLE mailboxes(ROWID INTEGER PRIMARY KEY, url TEXT);
        CREATE TABLE message_global_data(
            ROWID INTEGER PRIMARY KEY, message_id_header TEXT);
        CREATE TABLE recipients(ROWID INTEGER PRIMARY KEY, message INT, address INT);
        CREATE TABLE messages(
            ROWID INTEGER PRIMARY KEY, subject INT, sender INT, global_message_id INT,
            mailbox INT, date_received INT, date_sent INT, read INT, flagged INT,
            deleted INT);
        INSERT INTO subjects VALUES (1,'Invoice 42');
        INSERT INTO addresses VALUES (1,'jane@ex.com','Jane Doe');
        INSERT INTO mailboxes VALUES (1,'imap://acct/INBOX');
        INSERT INTO message_global_data VALUES (1,'<abc@ex.com>');
        INSERT INTO messages VALUES (10,1,1,1,1,1700000000,1700000000,0,0,0);
        """
    )
    c.commit()
    c.close()


def test_search_returns_pointers_from_sqlite(tmp_path, monkeypatch):
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    out = MailAdapter().search(subject="Invoice")
    assert len(out) == 1
    assert out[0].id == "<abc@ex.com>"
    assert out[0].summary == "Invoice 42"


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
