"""#501: execute localized mailbox reads and bound classification work."""

import sqlite3
import unicodedata
from urllib.parse import quote

import pytest

from macos_apps_mcp.adapters import mail_index, mailbox_url
from macos_apps_mcp.errors import AmbiguousTarget
from tests.envelope import ACCT_A, ACCT_B, SCHEMA, seed_base


@pytest.mark.usefixtures("envelope_mode")
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize(
    "candidates",
    [
        ("Deleted%20Messages", "Corbeille"),
        ("Deleted%20Items", "Papierkorb"),
        ("%5BGmail%5D/Trash", "Prullenbak"),
        ("%5BGoogle%20Mail%5D/Trash", "Prullenbak"),
        ("[Gmail]/Trash", "Prullenbak"),
        ("[Google Mail]/Trash", "Prullenbak"),
        ("%5bgmail%5d/Trash", "Prullenbak"),
        ("a/Trash", "Deleted%20Messages"),
        ("Folder/Trash", "Corbeille"),
        ("Folder/%5BGmail%5D/Trash", "Corbeille"),
        ("%5BGmail%5D/Folder/Trash", "Corbeille"),
        ("%5BGmail%5Dfake/Trash", "Corbeille"),
        ("Trash", "Bin", "Deleted%20Messages"),
        ("b/Trash", "a/Trash"),
        ("Trash", "%5BGmail%5D/Papierkorb"),
        ("Deleted%20Messages", "Trash"),
        ("Trash", "trash"),
        tuple(
            quote(unicodedata.normalize(form, "Gelöschte Elemente"))
            for form in ("NFC", "NFD")
        ),
    ],
)
def test_trash_lookup_refuses_distinct_candidates_regardless_of_rank(
    tmp_path, monkeypatch, reverse, candidates
):
    # #556 replaces the old depth/English ranking contract deliberately.
    db = tmp_path / "Envelope Index"
    seed_base(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    with sqlite3.connect(db) as conn:
        paths = reversed(candidates) if reverse else candidates
        conn.executemany(
            "INSERT INTO mailboxes(url) VALUES(?)",
            [(f"imap://{ACCT_A}/{path}",) for path in paths],
        )
        conn.execute("INSERT INTO mailboxes(url) VALUES(?)", (f"imap://{ACCT_B}/Bin",))
    with pytest.raises(AmbiguousTarget) as err:
        mail_index.query_trash_url(ACCT_A)
    assert "Nothing was changed by this call" in str(err.value)
    for candidate in candidates:
        assert mailbox_url.path(f"imap://{ACCT_A}/{candidate}") in str(err.value)


@pytest.mark.usefixtures("envelope_mode")
@pytest.mark.parametrize("form", ["NFC", "NFD"])
@pytest.mark.parametrize(
    "trash,sent,junk",
    [
        ("Prullenbak", "Verzonden berichten", "Ongewenste e-mail"),
        ("Gelöschte Elemente", "Gesendete Elemente", "Junk-E-Mail"),
        ("Éléments supprimés", "Éléments envoyés", "Courrier indésirable"),
        ("Корзина", "Отправленные", "Нежелательная почта"),
    ],
)
def test_localized_queries_preserve_addresses_and_choose_the_filed_copy(
    tmp_path, monkeypatch, form, trash, sent, junk
):
    db = tmp_path / "Envelope Index"
    seed_base(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)

    def url(name):
        return f"imap://{ACCT_A}/" + quote(
            "[Google Mail]/" + unicodedata.normalize(form, name), safe="/&()"
        )

    trash_url, sent_url, junk_url = map(url, (trash, sent, junk))
    with sqlite3.connect(db) as conn:
        # A newer junk copy must still lose to the original filed copy.
        conn.execute("UPDATE mailboxes SET url = ? WHERE ROWID = 5", (junk_url,))
        conn.execute("INSERT INTO mailboxes(ROWID,url) VALUES(6,?)", (trash_url,))
        conn.execute(
            "INSERT INTO mailboxes(ROWID,url,source) VALUES(7,?,3)", (sent_url,)
        )
        # Sent is a logical label over Travel, not a physical message location.
        conn.execute("UPDATE messages SET message_id = 10 WHERE ROWID = 50")
        conn.execute("UPDATE message_global_data SET message_id = 10 WHERE ROWID = 10")
        conn.execute("INSERT INTO labels VALUES(50,7)")

    assert mail_index.query_trash_url(ACCT_A) == trash_url
    assert mailbox_url.is_trash(trash_url)
    assert mail_index.query_trash_url(ACCT_B) is None
    assert [r["mid"] for r in mail_index.query_sent_triage(25)] == ["<junky@ex.com>"]
    # Execute the public read path, including the Sequoia shadow view.
    rows = mail_index.query_search(message_ids=["<junky@ex.com>"], limit=25)
    assert rows[0].folder == f"imap://{ACCT_B}/Travel"


def _cost_fixture():
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    conn.executescript("""
        INSERT INTO subjects VALUES(1,'Fixture');
        INSERT INTO addresses VALUES(1,'fixture@example.invalid','Fixture');
        CREATE INDEX messages_mailbox_deleted ON messages(mailbox,deleted);
    """)
    names = ("INBOX", "Travel", "Corbeille", "Courrier indésirable", "Éléments envoyés")
    conn.executemany(
        "INSERT INTO mailboxes(ROWID,url) VALUES(?,?)",
        [(i, "imap://A/" + quote(name)) for i, name in enumerate(names, 1)],
    )
    return conn


def _grow_messages(conn, start, stop):
    for i in range(start, stop):
        conn.execute(
            "INSERT INTO message_global_data VALUES(?,?,?)",
            (i, f"<m{i}@fixture.invalid>", i),
        )
        conn.execute(
            """INSERT INTO messages(ROWID,subject,sender,global_message_id,mailbox,
               date_received,date_sent,read,flagged,conversation_id,message_id)
               VALUES(?,1,1,?,?,100,100,0,0,1,?)""",
            (i, i, 1 + i % 5, i),
        )


@pytest.mark.parametrize("read", ["search", "thread", "stats"])
def test_classification_work_depends_on_mailboxes_not_messages(read):
    # Count actual escaped LIKE evaluations, delegating matching to another SQLite
    # connection. No wall-clock threshold, and no assumption about the query text.
    conn = _cost_fixture()
    matcher = sqlite3.connect(":memory:")
    calls = []

    def counted_like(pattern, value, escape):
        calls.append(value)
        return matcher.execute(
            "SELECT ? LIKE ? ESCAPE ?", (value, pattern, escape)
        ).fetchone()[0]

    conn.create_function("like", 3, counted_like)
    queries = {
        "search": mail_index.build_header_query(limit=25),
        "thread": mail_index.build_thread_query("<m1@fixture.invalid>", 25),
        "stats": mail_index.build_stats_query(0),
    }
    sql, params = queries[read]
    try:
        _grow_messages(conn, 1, 11)
        assert conn.execute(sql, params).fetchall()
        small = list(calls)
        calls.clear()
        _grow_messages(conn, 11, 501)
        assert conn.execute(sql, params).fetchall()
        assert calls == small
        assert 0 < len(calls) < 250  # five mailbox rows, not 500 message rows
    finally:
        conn.close()
        matcher.close()
