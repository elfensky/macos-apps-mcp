import asyncio
import sqlite3

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

import macos_apps_mcp.server as srv
from macos_apps_mcp.adapters import mail_index
from macos_apps_mcp.adapters.mail import MAX_MAILS, MailAdapter
from macos_apps_mcp.errors import NativeError

# Real account UUIDs, not placeholders: _resolve_account short-circuits on the
# 8-4-4-4-12 shape precisely so a UUID filter never has to ask Mail (and so never
# launches it), and a fixture with `AAAA` in it would test the osascript path by
# accident.
ACCT_A = "AAAAAAAA-1111-2222-3333-444444444444"
ACCT_B = "BBBBBBBB-1111-2222-3333-444444444444"
ACCT_LOCAL = "A2025935-B0B2-4A77-9003-68EF6E541361"  # the real On My Mac store's id


def _fake_envelope(path):
    """A minimal Envelope Index with the fingerprinted tables + columns.

    Deliberately includes the duplicate shapes found on a real Mac: <abc@ex.com> exists
    in INBOX *and* Archive (cross-folder), and <dup@ex.com> exists twice in the SAME
    folder (a migration copy that ran twice). Dedup tests depend on both — and
    <dup@ex.com>'s two copies are the NEWEST rows in the store, so an un-deduped
    `LIMIT 2` would hand back two rows carrying one distinct message.

    <split@ex.com> is the cross-account copy whose two rows carry DIFFERENT
    conversation_ids (Mail threads per account), which is what makes a single-branch
    thread seed observable. The local:// mailbox carries a percent-encoded name so the
    overview's decoding is actually exercised.
    """
    c = sqlite3.connect(path)
    c.executescript(
        f"""
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
        INSERT INTO subjects VALUES
            (1,'Invoice 42'),(2,'Re: Invoice 42'),(3,'Split thread'),(4,'Re: Split'),
            (5,'Zero dated'),(6,'Re: Zero dated'),(7,'Junk ranking');
        INSERT INTO addresses VALUES (1,'jane@ex.com','Jane Doe');
        INSERT INTO mailboxes VALUES
            (1,'imap://{ACCT_A}/INBOX'),
            (2,'imap://{ACCT_A}/Archive'),
            (3,'imap://{ACCT_B}/Travel'),
            (4,'local://{ACCT_LOCAL}/Some%20Folder'),
            (5,'imap://{ACCT_A}/Junk%20E-mail');
        INSERT INTO message_global_data VALUES
            (1,'<abc@ex.com>'),(2,'<reply@ex.com>'),(3,'<dup@ex.com>'),
            (4,'<split@ex.com>'),(5,'<branchA@ex.com>'),(6,'<branchB@ex.com>'),
            (7,'<zero@ex.com>'),(8,'<zeroold@ex.com>'),(9,NULL),
            (10,'<junky@ex.com>');
        -- <abc@ex.com>: INBOX + Archive, same conversation 7 as its reply
        INSERT INTO messages VALUES (10,1,1,1,1,1700000000,1700000000,0,0,0,7);
        INSERT INTO messages VALUES (11,1,1,1,2,1700000000,1700000000,0,0,0,7);
        -- the reply, in Travel, conversation 7
        INSERT INTO messages VALUES (12,2,1,2,3,1700000900,1700000900,1,0,0,7);
        -- <dup@ex.com>: twice in the SAME mailbox, unrelated conversation, and the two
        -- NEWEST rows in the store (the LIMIT-after-dedup guard depends on that).
        INSERT INTO messages VALUES (13,1,1,3,3,1700001000,1700001000,0,0,0,9);
        INSERT INTO messages VALUES (14,1,1,3,3,1700001000,1700001000,0,0,0,9);
        -- <split@ex.com>: one copy per account, each in its own conversation (20/21),
        -- each conversation holding one further member.
        INSERT INTO messages VALUES (20,3,1,4,1,1700002000,1700002000,0,0,0,20);
        INSERT INTO messages VALUES (21,3,1,4,3,1700002000,1700002000,0,0,0,21);
        INSERT INTO messages VALUES (22,4,1,5,1,1700002100,1700002100,0,0,0,20);
        INSERT INTO messages VALUES (23,4,1,6,3,1700002200,1700002200,0,0,0,21);
        -- conversation 30: the NEWER message carries date_sent = 0 (Mail stores a zero,
        -- not a NULL), which a NULL-only COALESCE would sort to the very front.
        INSERT INTO messages VALUES (30,5,1,7,1,1700003000,0,0,0,0,30);
        INSERT INTO messages VALUES (31,6,1,8,1,1700002500,1700002500,0,0,0,30);
        -- a header-less message (no RFC822 Message-ID): uncitable, so search skips it,
        -- but it IS in the mailbox and the overview must still count it.
        INSERT INTO messages VALUES (40,1,1,9,2,1700000100,1700000100,1,0,0,11);
        -- <junky@ex.com>: a real filed copy (Travel) plus a NEWER copy in Exchange's
        -- `Junk%20E-mail`. An end-anchored '%Junk' rank pattern misses that name, so
        -- the junk copy ranked as a preferred filed folder and won on recency.
        INSERT INTO messages VALUES (50,7,1,10,3,1700000700,1700000700,1,0,0,12);
        INSERT INTO messages VALUES (51,7,1,10,5,1700000800,1700000800,1,0,0,12);
        INSERT INTO attachments VALUES (1,10,'contract.pdf'),(2,12,'image001.png');
        """
    )
    c.commit()
    c.close()


def _add_rank_overmatch_messages(db):
    """Copies whose NEWER row lives in a real user folder that a wildcard rank
    pattern mis-reads as Junk/All Mail ('Junkyard', 'Wallets/Old Mail'), plus one
    genuine [Gmail]/All Mail copy as the keep-demoting guard. The rank picks which
    physical copy a Pointer cites — and which copy a future move/status write acts
    on — so an over-match is not cosmetic."""
    conn = sqlite3.connect(db)
    conn.executescript(
        f"""
        INSERT INTO mailboxes VALUES
            (6,'imap://{ACCT_B}/Junkyard'),
            (7,'imap://{ACCT_B}/Wallets/Old%20Mail'),
            (8,'imap://{ACCT_A}/%5BGmail%5D/All%20Mail');
        INSERT INTO subjects VALUES
            (9,'Yard sale'),(10,'Old mail folder'),(11,'Gmail label');
        INSERT INTO message_global_data VALUES
            (12,'<yard@ex.com>'),(13,'<oldmail@ex.com>'),(14,'<label@ex.com>');
        -- <yard@ex.com>: newer copy in Junkyard (a real folder), older in Travel
        INSERT INTO messages VALUES (70,9,1,12,6,1700005000,1700005000,1,0,0,50);
        INSERT INTO messages VALUES (71,9,1,12,3,1700004900,1700004900,1,0,0,50);
        -- <oldmail@ex.com>: newer copy in Wallets/Old Mail, older in Travel
        INSERT INTO messages VALUES (72,10,1,13,7,1700005100,1700005100,1,0,0,51);
        INSERT INTO messages VALUES (73,10,1,13,3,1700005000,1700005000,1,0,0,51);
        -- <label@ex.com>: newer copy in [Gmail]/All Mail, older in Travel
        INSERT INTO messages VALUES (74,11,1,14,8,1700005200,1700005200,1,0,0,52);
        INSERT INTO messages VALUES (75,11,1,14,3,1700005100,1700005100,1,0,0,52);
        """
    )
    conn.commit()
    conn.close()


def test_search_returns_pointers_from_sqlite(tmp_path, monkeypatch):
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    out = MailAdapter().search(subject="Invoice")["results"]
    hit = [p for p in out if p["id"] == "<abc@ex.com>"]
    assert len(hit) == 1  # INBOX + Archive copies collapse to one
    assert hit[0]["summary"] == "Invoice 42"


def test_search_falls_back_on_drift(tmp_path, monkeypatch):
    db = tmp_path / "Envelope Index"
    # missing cols → drift
    sqlite3.connect(db).executescript("CREATE TABLE messages(ROWID INTEGER);")
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    adapter = MailAdapter()
    monkeypatch.setattr(adapter, "get_pointers", lambda q: ["FALLBACK"])
    assert adapter.search(subject="x")["results"] == ["FALLBACK"]


def test_search_no_store_raises(monkeypatch):
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: None)
    with pytest.raises(NativeError):
        MailAdapter().search(subject="x")["results"]


def test_search_body_intersects_fts(tmp_path, monkeypatch):
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    # FTS returns the one indexed message-id; header join keeps it
    monkeypatch.setattr(mail_index, "fts_path", lambda: tmp_path / "fts.sqlite")
    monkeypatch.setattr(
        mail_index, "fts_search", lambda db_, q, limit=200: ["<abc@ex.com>"]
    )
    out = MailAdapter().search(body="invoice")["results"]
    assert [p["id"] for p in out] == ["<abc@ex.com>"]


def test_search_body_empty_index_returns_empty(tmp_path, monkeypatch):
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    monkeypatch.setattr(mail_index, "fts_search", lambda db_, q, limit=200: [])
    assert MailAdapter().search(body="nothing")["results"] == []


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
        adapter.search(body="x", subject="x")["results"]


def test_index_bodies_no_mail_root_raises(monkeypatch):
    from macos_apps_mcp.adapters import mail_index

    monkeypatch.setattr(mail_index, "mail_root", lambda: None)
    with pytest.raises(NativeError):
        MailAdapter().index_bodies()


def test_index_bodies_reports_this_run_not_coverage(tmp_path, monkeypatch):
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
    # #168 review: this field must NOT claim to be coverage. On a fully-indexed store a
    # resume run reports a tiny `indexed`, and "3/4 indexed" then reads as "the store is
    # 75% searchable" when it is 100%. mail_search owns the coverage answer.
    assert "coverage" not in out
    assert out["indexed_this_run"].startswith("3 newly indexed, 1 already current")
    assert "mail_search" in out["indexed_this_run"]


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
    MailAdapter().search(subject="Invoice", limit=10_000)["results"]
    assert captured["limit"] == MAX_MAILS


def test_search_requires_at_least_one_filter():
    # C5c: the at-least-one-filter rule is the ADAPTER's domain rule, enforced before
    # any index read (an unfiltered search would walk the whole store).
    with pytest.raises(ValueError, match="at least one filter"):
        MailAdapter().search()["results"]


def test_search_empty_strings_are_absent_filters():
    # the ""→None normalization lives in the adapter too (C5c): all-empty text
    # filters are no filters at all.
    with pytest.raises(ValueError, match="at least one filter"):
        MailAdapter().search(subject="", from_="", to="", mailbox="", account="")[
            "results"
        ]


def test_search_normalizes_empty_text_filters_to_none_downstream(tmp_path, monkeypatch):
    # The line above only proves the GUARD rejects all-empty. The normalization itself
    # was unobservable — deleting it kept the suite green, because every downstream
    # consumer happens to be truthiness-based today. Pin what the adapter actually hands
    # over, so a future consumer that distinguishes "" from None can't silently break.
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    captured = {}
    real_build_header_query = mail_index.build_header_query

    def spy(**kwargs):
        captured.update(kwargs)
        return real_build_header_query(**kwargs)

    monkeypatch.setattr(mail_index, "build_header_query", spy)
    MailAdapter().search(subject="Invoice", from_="", to="")["results"]
    assert captured["subject"] == "Invoice"
    assert captured["from_"] is None and captured["to"] is None  # not ""


def test_search_since_zero_not_rejected(tmp_path, monkeypatch):
    # since=0 (epoch 0) is a valid timestamp, not an absent filter — compared
    # `is not None`, never truthiness (#70 review M3). Adapter-level since C5c moved
    # the guard out of the tool layer.
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    assert isinstance(
        MailAdapter().search(since=0)["results"], list
    )  # guard lets it through


def test_mail_search_tool_delegates_guard_to_adapter():
    # the tool body is a plain delegation — the adapter's rule surfaces through
    # _guard as the agent-directed ToolError.
    from fastmcp.exceptions import ToolError

    with pytest.raises(ToolError, match="at least one filter"):
        srv.mail_search()


def test_mail_search_tool_forwards_every_filter_to_the_adapter(monkeypatch):
    # C5c left the tool a pure delegation, which means NOTHING but this pins the
    # wiring: every kwarg was independently replaceable with None and the suite
    # stayed green. A swapped pair (to=from_) would silently answer the wrong
    # question — mail_search(to="boss@x") returning mail FROM the boss.
    # Distinct sentinel per field so a swap can't alias.
    sent = {
        "subject": "s-subject",
        "from_": "s-from",
        "to": "s-to",
        "mailbox": "s-mailbox",
        "since": 11,
        "until": 22,
        "unread": True,
        "flagged": True,
        "body": "s-body",
        "has_attachments": True,
        "account": "s-account",
        "limit": 7,
    }
    got = {}

    class _Recorder:
        def search(self, **kwargs):
            got.update(kwargs)
            return []

    monkeypatch.setattr(srv, "_mail", _Recorder())
    assert srv.mail_search(**sent) == []
    assert got == sent


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
    out = MailAdapter().search(subject="Invoice 42")["results"]
    assert [p["id"] for p in out].count("<abc@ex.com>") == 1
    inbox = [p for p in out if p["id"] == "<abc@ex.com>"][0]
    assert inbox["folder"] == f"imap://{ACCT_A}/INBOX"


def test_search_dedupes_same_folder_copies(tmp_path, monkeypatch):
    # <dup@ex.com> exists twice in the SAME mailbox (migration ran twice) — collapses.
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    out = MailAdapter().search(subject="Invoice", limit=25)["results"]
    assert [p["id"] for p in out].count("<dup@ex.com>") == 1


def test_search_limit_counts_distinct_messages(tmp_path, monkeypatch):
    # LIMIT must apply AFTER dedup. The two NEWEST rows matching 'Invoice' are the two
    # <dup@ex.com> copies, so an un-deduped `LIMIT 2` returns 2 rows carrying ONE
    # distinct message — which is exactly the bug. Verified discriminating: removing
    # `WHERE rn = 1` from build_header_query makes this fail (1 distinct, not 2).
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    out = MailAdapter().search(subject="Invoice", limit=2)["results"]
    assert len(out) == 2
    assert len({p["id"] for p in out}) == 2
    assert {p["id"] for p in out} == {"<dup@ex.com>", "<reply@ex.com>"}


def test_search_limit_cannot_go_negative(tmp_path, monkeypatch):
    # SQLite reads `LIMIT -1` as unlimited, and limit is caller-supplied straight from
    # the MCP schema — a one-sided min() would dump the whole store.
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    assert len(MailAdapter().search(subject="Invoice", limit=-1)["results"]) == 1


def test_thread_limit_cannot_go_negative(tmp_path, monkeypatch):
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    assert len(MailAdapter().thread("<abc@ex.com>", limit=-1)["results"]) == 1


def test_search_ranks_exchange_junk_below_a_real_folder(tmp_path, monkeypatch):
    # Exchange names the folder `Junk%20E-mail`, which an end-anchored '%Junk' pattern
    # does not match — so the junk copy ranked as a preferred FILED folder and, being
    # newer, became the citation.
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    out = MailAdapter().search(subject="Junk ranking")["results"]
    assert [p["id"] for p in out] == ["<junky@ex.com>"]
    assert out[0]["folder"] == f"imap://{ACCT_B}/Travel"


def test_search_subject_wildcard_is_not_a_wildcard(tmp_path, monkeypatch):
    # '%' is a bound param (never injection) but LIKE still read it as "everything":
    # subject='%' matched every message in the store. It must match only a literal
    # '%' — the same honesty rule the account filter already got.
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    assert MailAdapter().search(subject="%")["results"] == []


def test_search_mailbox_underscore_is_not_a_wildcard(tmp_path, monkeypatch):
    # '_' is LIKE's any-one-char wildcard: mailbox='_' matched every mailbox. It now
    # RAISES rather than answering [] (#156 case 2) — which proves the same thing even
    # more loudly: a wildcard would have matched every mailbox and returned messages.
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    with pytest.raises(ValueError, match="no mailbox matches"):
        MailAdapter().search(mailbox="_")


def test_rank_does_not_treat_junkyard_as_junk(tmp_path, monkeypatch):
    # '%Junk%' also matched a real folder named 'Junkyard' and demoted it to the
    # junk tier — so the OLDER Travel copy was cited instead of the newest one.
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    _add_rank_overmatch_messages(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    out = MailAdapter().search(subject="Yard sale")["results"]
    assert [p["id"] for p in out] == ["<yard@ex.com>"]
    assert out[0]["folder"] == f"imap://{ACCT_B}/Junkyard"


def test_rank_does_not_treat_old_mail_folder_as_all_mail(tmp_path, monkeypatch):
    # '%All%Mail' is wildcarded on BOTH sides of 'All', so any url containing 'all'
    # and ending in 'Mail' — 'Wallets/Old Mail' — ranked as an All Mail copy.
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    _add_rank_overmatch_messages(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    out = MailAdapter().search(subject="Old mail folder")["results"]
    assert [p["id"] for p in out] == ["<oldmail@ex.com>"]
    assert out[0]["folder"] == f"imap://{ACCT_B}/Wallets/Old%20Mail"


def test_rank_still_demotes_gmail_all_mail(tmp_path, monkeypatch):
    # the guard for the two tests above: a GENUINE [Gmail]/All Mail copy must keep
    # losing to a filed copy even when the All Mail row is newer.
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    _add_rank_overmatch_messages(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    out = MailAdapter().search(subject="Gmail label")["results"]
    assert [p["id"] for p in out] == ["<label@ex.com>"]
    assert out[0]["folder"] == f"imap://{ACCT_B}/Travel"


def test_search_mailbox_accepts_the_decoded_name_overview_reports(
    tmp_path, monkeypatch
):
    # #144: mail_overview reports "Junk E-mail" (decoded); mail_search matched the
    # ENCODED url, so feeding overview's own output back in returned 0 hits for
    # every mailbox whose name encodes (10 of 51 on the reference Mac).
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    ids = [p["id"] for p in MailAdapter().search(mailbox="Junk E-mail")["results"]]
    assert ids == ["<junky@ex.com>"]


def test_search_mailbox_encoded_spelling_keeps_working(tmp_path, monkeypatch):
    # the encoded form worked before the fix (it's what the url literally contains);
    # models learned it from error output, so it must not break now.
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    ids = [p["id"] for p in MailAdapter().search(mailbox="Junk%20E-mail")["results"]]
    assert ids == ["<junky@ex.com>"]


def test_search_mailbox_is_case_insensitive(tmp_path, monkeypatch):
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    assert MailAdapter().search(mailbox="travel")["results"]  # Travel, lowercased


def test_resolve_mailbox_matches_decoded_paths(tmp_path, monkeypatch):
    import macos_apps_mcp.adapters.mail_addressing as ma

    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    _add_rank_overmatch_messages(db)  # adds Junkyard under ACCT_B
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    urls = ma.resolve_mailbox("junk")
    assert set(urls) == {
        f"imap://{ACCT_A}/Junk%20E-mail",
        f"imap://{ACCT_B}/Junkyard",
    }


def test_resolve_mailbox_account_restricts_to_that_uuid(tmp_path, monkeypatch):
    import macos_apps_mcp.adapters.mail_addressing as ma

    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    _add_rank_overmatch_messages(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    assert ma.resolve_mailbox("junk", account=ACCT_A) == [
        f"imap://{ACCT_A}/Junk%20E-mail"
    ]


def test_resolve_mailbox_no_store_raises(monkeypatch):
    import macos_apps_mcp.adapters.mail_addressing as ma

    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: None)
    with pytest.raises(NativeError, match="Open Mail once"):
        ma.resolve_mailbox("Travel")


def test_query_mailbox_urls_lists_every_mailbox(tmp_path, monkeypatch):
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    urls = mail_index.query_mailbox_urls()
    assert f"imap://{ACCT_A}/INBOX" in urls
    assert len(urls) == 5  # the base fixture's five mailboxes


def test_search_has_attachments_matches_document_not_image(tmp_path, monkeypatch):
    # msg 10 (<abc@ex.com>) has contract.pdf; msg 12 (<reply@ex.com>) has only
    # image001.png and must NOT match.
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    ids = [p["id"] for p in MailAdapter().search(has_attachments=True)["results"]]
    assert "<abc@ex.com>" in ids
    assert "<reply@ex.com>" not in ids


def test_search_account_filters_by_uuid(tmp_path, monkeypatch):
    import macos_apps_mcp.adapters.mail_addressing as ma

    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    # A UUID must never reach osascript — that is what "no Mail launch" means.
    monkeypatch.setattr(
        ma, "run_osascript", lambda *a: pytest.fail("a UUID account launched Mail")
    )
    ids = [p["id"] for p in MailAdapter().search(account=ACCT_B)["results"]]
    assert set(ids) == {
        "<reply@ex.com>",
        "<dup@ex.com>",
        "<split@ex.com>",
        "<branchB@ex.com>",
        "<junky@ex.com>",
    }
    assert "<abc@ex.com>" not in ids  # lives only under account A


def test_search_account_name_that_cannot_be_resolved_raises(tmp_path, monkeypatch):
    # Returning the name unchanged degraded into `url LIKE '%Business%'`, which matches
    # any account's Business* FOLDER and reports it as though the filter had worked.
    import macos_apps_mcp.adapters.mail_addressing as ma

    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    monkeypatch.setattr(ma, "_ACCOUNT_MAP_CACHE", {ACCT_A: "Personal"})
    with pytest.raises(NativeError, match="unknown Mail account"):
        MailAdapter().search(account="Travel")["results"]


def test_search_account_name_resolves_to_its_uuid(tmp_path, monkeypatch):
    import macos_apps_mcp.adapters.mail_addressing as ma

    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    monkeypatch.setattr(ma, "_ACCOUNT_MAP_CACHE", {ACCT_B: "Trips"})
    assert "<reply@ex.com>" in [
        p["id"] for p in MailAdapter().search(account="Trips")["results"]
    ]


def _add_local_message(db):
    """Insert one message into the fixture's local:// mailbox (ROWID 4) — the base
    fixture leaves it empty (only exercised via overview's 0/0 count), but resolving
    account="On My Mac" needs something filed there to prove the filter actually
    selects local:// rows and not just that it fails to raise."""
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO subjects VALUES (8,'Local note')")
    conn.execute("INSERT INTO message_global_data VALUES (11,'<localnote@ex.com>')")
    conn.execute(
        "INSERT INTO messages VALUES (60,8,1,11,4,1700004000,1700004000,0,0,0,40)"
    )
    conn.commit()
    conn.close()


def test_search_account_on_my_mac_matches_the_local_store(tmp_path, monkeypatch):
    # N1: mail_overview maps local:// to the literal "On My Mac", so mail_search must
    # accept that exact name — and it must resolve without contacting Mail, the same
    # "no Mail launch" guarantee a real account UUID gets.
    import macos_apps_mcp.adapters.mail_addressing as ma

    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    _add_local_message(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    monkeypatch.setattr(
        ma, "run_osascript", lambda *a: pytest.fail("On My Mac launched Mail")
    )
    ids = [p["id"] for p in MailAdapter().search(account="On My Mac")["results"]]
    assert ids == ["<localnote@ex.com>"]
    # and it must not leak messages filed under a real account
    assert "<abc@ex.com>" not in ids


def test_search_account_local_alias_matches_the_local_store(tmp_path, monkeypatch):
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    _add_local_message(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    ids = [p["id"] for p in MailAdapter().search(account="local")["results"]]
    assert ids == ["<localnote@ex.com>"]


def test_on_my_mac_name_round_trips_from_overview_into_search(tmp_path, monkeypatch):
    # N1's actual bug: mail_overview started reporting "On My Mac" as the account name
    # while mail_search(account=...) still rejected it. Feed overview()'s own output
    # straight back into search() so the two can't drift apart again.
    import macos_apps_mcp.adapters.mail_addressing as ma

    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    _add_local_message(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    monkeypatch.setattr(ma, "_ACCOUNT_MAP_CACHE", {ACCT_A: "Personal"})
    overview = MailAdapter().overview()
    local_name = next(r["account"] for r in overview if r["mailbox"] == "Some Folder")
    assert local_name == "On My Mac"
    ids = [p["id"] for p in MailAdapter().search(account=local_name)["results"]]
    assert ids == ["<localnote@ex.com>"]


def test_search_account_on_my_mac_no_local_store_raises_followable_error(
    tmp_path, monkeypatch
):
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)  # base fixture: local:// mailbox exists but carries no rows —
    # remove it so there is truly no local:// store to resolve
    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM mailboxes WHERE url LIKE 'local://%'")
    conn.commit()
    conn.close()
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    with pytest.raises(NativeError, match="Open Mail once"):
        MailAdapter().search(account="On My Mac")["results"]


def test_search_account_wildcard_is_not_a_wildcard(tmp_path, monkeypatch):
    # '%' is a bound param (never injection) but LIKE still read it as "everything",
    # so the filter silently matched every mailbox instead of failing.
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    sql, params = mail_index.build_header_query(account="%")
    conn = sqlite3.connect(db)
    assert conn.execute(sql, params).fetchall() == []
    conn.close()


def test_account_filter_does_not_match_a_folder_name(tmp_path, monkeypatch):
    # 'Travel' is a FOLDER under account B; as an account value it must match nothing,
    # not every message that happens to live in a path containing "Travel".
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    sql, params = mail_index.build_header_query(account="Travel")
    conn = sqlite3.connect(db)
    assert conn.execute(sql, params).fetchall() == []
    conn.close()


def test_thread_returns_whole_conversation_oldest_first(tmp_path, monkeypatch):
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    out = MailAdapter().thread("<abc@ex.com>")["results"]
    # conversation 7 holds <abc@ex.com> (INBOX + Archive) and its reply
    assert [p["id"] for p in out] == ["<abc@ex.com>", "<reply@ex.com>"]
    assert out[0]["folder"] == f"imap://{ACCT_A}/INBOX"  # deduped to the INBOX copy


def test_thread_finds_conversation_from_any_member(tmp_path, monkeypatch):
    # asking with the REPLY's id must return the same thread, not just the reply
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    assert len(MailAdapter().thread("<reply@ex.com>")["results"]) == 2


def test_thread_truncation_keeps_the_newest(tmp_path, monkeypatch):
    # when the point of reading a thread is to reply, the OLD end is the end to drop
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    out = MailAdapter().thread("<abc@ex.com>", limit=1)["results"]
    assert [p["id"] for p in out] == ["<reply@ex.com>"]


def test_thread_spans_every_conversation_the_id_belongs_to(tmp_path, monkeypatch):
    # <split@ex.com> is copied across two accounts and Mail gave each copy its OWN
    # conversation_id. A `= (SELECT … LIMIT 1)` seed picked one branch at the query
    # planner's discretion and silently dropped the other.
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    ids = {p["id"] for p in MailAdapter().thread("<split@ex.com>")["results"]}
    assert {"<branchA@ex.com>", "<branchB@ex.com>"} <= ids
    assert "<split@ex.com>" in ids


def test_thread_seed_ignores_deleted_copies(tmp_path, monkeypatch):
    # a deleted copy was as eligible a seed as a live one; mark the ONLY live copy's
    # conversation and check the thread still resolves through it.
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    conn = sqlite3.connect(db)
    conn.execute("UPDATE messages SET deleted = 1, conversation_id = 99 WHERE ROWID=21")
    conn.commit()
    conn.close()
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    ids = {p["id"] for p in MailAdapter().thread("<split@ex.com>")["results"]}
    assert ids == {"<split@ex.com>", "<branchA@ex.com>"}


def test_thread_orders_a_zero_date_sent_by_date_received(tmp_path, monkeypatch):
    # date_sent = 0 is not NULL, so a plain COALESCE left it sorting to the very front
    # of an oldest-first transcript — and made it the first message dropped on
    # truncation, which is the opposite of "keep the newest".
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    out = MailAdapter().thread("<zero@ex.com>")["results"]
    assert [p["id"] for p in out] == ["<zeroold@ex.com>", "<zero@ex.com>"]
    assert [
        p["id"] for p in MailAdapter().thread("<zero@ex.com>", limit=1)["results"]
    ] == ["<zero@ex.com>"]


def test_thread_accepts_the_bare_id_the_applescript_plane_reports(
    tmp_path, monkeypatch
):
    # AppleScript's `message id of m` returns the BARE form (which is why every
    # id-taking method strips <>), while the index stores '<bracketed>'. thread()
    # passed the id through to an EXACT match, so a Pointer.id from mail /
    # mail_needs_response / drafts always threaded to [] — indistinguishable from a
    # genuine miss.
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    out = MailAdapter().thread("abc@ex.com")["results"]
    assert [p["id"] for p in out] == ["<abc@ex.com>", "<reply@ex.com>"]


def test_search_fallback_refuses_when_a_filter_would_be_dropped(tmp_path, monkeypatch):
    # The AppleScript inbox scan can express a subject/sender substring — nothing
    # else. Falling back with unread=True silently returned unfiltered inbox hits
    # while the caller believed the filter applied.
    db = tmp_path / "Envelope Index"
    sqlite3.connect(db).executescript("CREATE TABLE messages(ROWID INTEGER);")
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    adapter = MailAdapter()
    monkeypatch.setattr(
        adapter, "get_pointers", lambda q: pytest.fail("dropped unread= and fell back")
    )
    with pytest.raises(NativeError):
        adapter.search(subject="x", unread=True)["results"]


def test_search_fallback_refuses_a_to_filter(tmp_path, monkeypatch):
    # get_pointers matches subject OR SENDER — a to= filter is not expressible, so
    # falling back turned "sent TO alice" into "mentions alice anywhere".
    db = tmp_path / "Envelope Index"
    sqlite3.connect(db).executescript("CREATE TABLE messages(ROWID INTEGER);")
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    adapter = MailAdapter()
    monkeypatch.setattr(
        adapter, "get_pointers", lambda q: pytest.fail("to= became a sender match")
    )
    with pytest.raises(NativeError):
        adapter.search(to="alice@ex.com")["results"]


def test_search_fallback_honors_the_limit(tmp_path, monkeypatch):
    # get_pointers slices to MAX_MAILS, not to the caller's clamped limit.
    db = tmp_path / "Envelope Index"
    sqlite3.connect(db).executescript("CREATE TABLE messages(ROWID INTEGER);")
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    adapter = MailAdapter()
    monkeypatch.setattr(adapter, "get_pointers", lambda q: ["a", "b", "c"])
    assert adapter.search(subject="x", limit=2)["results"] == ["a", "b"]


def test_thread_unknown_id_returns_empty(tmp_path, monkeypatch):
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    assert MailAdapter().thread("<nope@ex.com>")["results"] == []


# --- mail_index query_* accessors (C1): the ONE sqlite entry per read shape --------


def test_query_search_returns_pointers(tmp_path, monkeypatch):
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    out = mail_index.query_search(subject="Invoice 42")
    # deduped (one <abc@ex.com> despite INBOX+Archive copies), newest-first
    ids = [p.id for p in out]  # the store plane answers Pointers, not the envelope
    assert ids == ["<dup@ex.com>", "<reply@ex.com>", "<abc@ex.com>"]


def test_query_search_missing_store_raises(monkeypatch):
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: None)
    with pytest.raises(NativeError, match="Open Mail once"):
        mail_index.query_search(subject="x")


def test_query_search_passes_fallback_through(tmp_path, monkeypatch):
    db = tmp_path / "Envelope Index"
    # missing cols → drift → the passed-through fallback answers
    sqlite3.connect(db).executescript("CREATE TABLE messages(ROWID INTEGER);")
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    assert mail_index.query_search(subject="x", fallback=lambda: ["FB"]) == ["FB"]


def test_query_thread_returns_conversation(tmp_path, monkeypatch):
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    out = mail_index.query_thread("<abc@ex.com>", limit=100)
    assert [p.id for p in out] == ["<abc@ex.com>", "<reply@ex.com>"]


def test_query_overview_rows_returns_raw_rows(tmp_path, monkeypatch):
    # RAW rows by design — encoded mailbox_url, no account names: decoding and
    # account naming are adapter concerns (the "_rows" suffix is the warning).
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    rows = mail_index.query_overview_rows()
    assert rows and set(rows[0]) == {"mailbox_url", "total", "unread"}
    assert any("%20" in r["mailbox_url"] for r in rows)  # still percent-encoded


def test_query_overview_rows_missing_store_raises(monkeypatch):
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: None)
    with pytest.raises(NativeError, match="Open Mail once"):
        mail_index.query_overview_rows()


def test_query_local_account_url_returns_url(tmp_path, monkeypatch):
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    url = mail_index.query_local_account_url()
    assert url is not None and url.startswith(f"local://{ACCT_LOCAL}")


def test_query_local_account_url_missing_store_is_none(monkeypatch):
    # Asymmetric by contract: the account resolver owns the richer error, so a
    # missing store answers None here — never the _NO_MAIL_DATA raise.
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: None)
    assert mail_index.query_local_account_url() is None


def test_overview_reports_counts_and_decodes_names(tmp_path, monkeypatch):
    import macos_apps_mcp.adapters.mail_addressing as ma

    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    monkeypatch.setattr(ma, "_ACCOUNT_MAP_CACHE", {ACCT_A: "Personal"})
    rows = MailAdapter().overview()
    by_box = {r["mailbox"]: r for r in rows}
    assert by_box["INBOX"]["account"] == "Personal"
    assert by_box["INBOX"]["total"] == 5 and by_box["INBOX"]["unread"] == 5
    # account B has no name in the map -> the UUID stands in, the call still succeeds
    assert by_box["Travel"]["account"] == ACCT_B
    # the local:// store's name is percent-encoded in mailboxes.url
    assert "Some Folder" in by_box


def test_overview_counts_distinct_messages_not_rows(tmp_path, monkeypatch):
    # Travel holds 6 rows but 5 messages — <dup@ex.com> is filed there twice. Against
    # the real 36k store the un-deduped count reported Travel 4,423 vs a true 1,241.
    import macos_apps_mcp.adapters.mail_addressing as ma

    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    monkeypatch.setattr(ma, "_ACCOUNT_MAP_CACHE", {})
    by_box = {r["mailbox"]: r for r in MailAdapter().overview()}
    assert by_box["Travel"]["total"] == 5
    assert by_box["Travel"]["unread"] == 3  # <reply@ex.com> is read; dup counts once


def test_overview_keeps_empty_mailboxes_and_header_less_messages(tmp_path, monkeypatch):
    # the second join (message_global_data) must stay a LEFT JOIN: an inner one would
    # drop empty mailboxes back out of the listing.
    import macos_apps_mcp.adapters.mail_addressing as ma

    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    monkeypatch.setattr(ma, "_ACCOUNT_MAP_CACHE", {})
    by_box = {r["mailbox"]: r for r in MailAdapter().overview()}
    assert by_box["Some Folder"]["total"] == 0
    assert by_box["Some Folder"]["unread"] == 0
    # Archive holds <abc@ex.com> plus one message with no Message-ID — uncitable, but
    # it IS in the mailbox, so a count that omitted it would be its own small lie.
    assert by_box["Archive"]["total"] == 2


def test_overview_names_the_on_my_mac_store(tmp_path, monkeypatch):
    # device-verified 2026-07-27: AppleScript `every account` lists only the configured
    # mail accounts, so the local:// store is NEVER named by Mail — permanently, not
    # "while Mail is unreachable". Map the scheme instead of showing a raw UUID.
    import macos_apps_mcp.adapters.mail_addressing as ma

    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    monkeypatch.setattr(ma, "_ACCOUNT_MAP_CACHE", {ACCT_A: "Personal"})
    by_box = {r["mailbox"]: r for r in MailAdapter().overview()}
    assert by_box["Some Folder"]["account"] == "On My Mac"


def test_overview_survives_mail_being_unreachable(tmp_path, monkeypatch):
    import macos_apps_mcp.adapters.mail_addressing as ma

    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    calls = []

    def _boom(*a):
        calls.append(a)
        raise OSError()

    monkeypatch.setattr(ma, "run_osascript", _boom)
    rows = MailAdapter().overview()
    assert rows  # counts never needed Mail
    assert all(r["account"] for r in rows)  # UUID stands in for the name
    # the FAILURE is cached too: without that, every call on a machine where Automation
    # is denied re-spawns osascript, and the script waits `with timeout of 120 seconds`.
    MailAdapter().overview()
    assert len(calls) == 1


def test_overview_sorts_unread_first(tmp_path, monkeypatch):
    import macos_apps_mcp.adapters.mail_addressing as ma

    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    monkeypatch.setattr(ma, "_ACCOUNT_MAP_CACHE", {})
    unread = [r["unread"] for r in MailAdapter().overview()]
    assert unread == sorted(unread, reverse=True)


def test_new_read_tools_are_registered():
    async def go():
        async with Client(srv.mcp) as c:
            return {t.name for t in await c.list_tools()}

    names = asyncio.run(go())
    assert {"mail_thread", "mail_overview"} <= names


def test_mail_search_exposes_new_filters():
    async def go():
        async with Client(srv.mcp) as c:
            return {t.name: t for t in await c.list_tools()}

    props = asyncio.run(go())["mail_search"].inputSchema["properties"]
    assert "has_attachments" in props and "account" in props


def test_mail_search_still_requires_a_filter():
    # has_attachments/account must COUNT as filters, and an all-empty call must still
    # raise rather than dumping the whole mailbox. mail_search is registered via
    # @_read_tool, which wraps it in _guard — a plain ValueError raised inside the
    # tool body surfaces to a direct caller as fastmcp's ToolError (#47), not the
    # original ValueError, so that's what this asserts against (matches the runtime
    # behavior verified against the actual guarded callable, not the brief's assumed
    # `.fn()` unwrap which fastmcp 3.4.2 doesn't expose on `@mcp.tool`-registered
    # functions).
    with pytest.raises(ToolError):
        srv.mail_search()


def test_overview_reports_the_account_id_search_pointers_carry(tmp_path, monkeypatch):
    # #155: overview() is the uuid -> display-name map. It only works as one if the id
    # it reports is byte-identical to the `account` every search Pointer carries —
    # otherwise the caller is back to string surgery on the opaque folder token.
    import macos_apps_mcp.adapters.mail_addressing as ma

    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    monkeypatch.setattr(ma, "_ACCOUNT_MAP_CACHE", {ACCT_A: "Personal"})

    row = next(r for r in MailAdapter().overview() if r["account"] == "Personal")
    assert row["account_id"] == ACCT_A
    assert row["folder"].startswith(f"imap://{ACCT_A}/")

    pointers = MailAdapter().search(account="Personal")["results"]
    assert pointers, "fixture must yield at least one hit to compare against"
    assert {p["account"] for p in pointers} == {ACCT_A}
    # and the folder overview reports is the exact token the pointer round-trips
    assert all(p["folder"].startswith(f"imap://{ACCT_A}/") for p in pointers)


# --- #156: a successful read says what it did NOT answer -----------------------------


def test_a_capped_search_is_marked_truncated(tmp_path, monkeypatch):
    # MAX_MAILS is a hard CEILING, not a default — on a real 36k store no search can
    # ever return more than 25, and the bare list read as a complete answer.
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    out = MailAdapter().search(subject="Invoice", limit=1)
    assert len(out["results"]) == 1
    assert out["truncated"] is True
    # the same search with room to spare makes no such claim
    assert "truncated" not in MailAdapter().search(subject="Invoice", limit=25)


def test_an_unresolvable_mailbox_name_raises_with_where_to_look(tmp_path, monkeypatch):
    # #156 case 2: a typo, a wrong-account guess and a genuinely empty mailbox were
    # indistinguishable. A name is something a model typed from memory — a followable
    # error beats a 0-hit read that reads as authoritative.
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    with pytest.raises(ValueError, match="no mailbox matches 'Nonexistent'"):
        MailAdapter().search(mailbox="Nonexistent")
    with pytest.raises(ValueError, match="mail_overview"):
        MailAdapter().search(mailbox="Nonexistent")


def test_a_stale_mailbox_url_still_answers_empty(tmp_path, monkeypatch):
    # …but a URL was a REAL handle when a read issued it. #78's move_mail will strand
    # exactly these, and a stranded handle is an honest no-match, not a caller error.
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    stale = f"imap://{ACCT_A}/Gone%20Folder"
    assert MailAdapter().search(mailbox=stale) == {"results": []}


def test_the_applescript_fallback_names_its_plane(tmp_path, monkeypatch):
    # #156 case 3: the fallback scans the INBOX ONLY but is shaped identically to a
    # whole-store result, so a caller could not tell it searched 1 mailbox of 200.
    db = tmp_path / "Envelope Index"
    sqlite3.connect(db).executescript("CREATE TABLE messages(ROWID INTEGER);")
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    adapter = MailAdapter()
    monkeypatch.setattr(adapter, "get_pointers", lambda q: ["a"])
    out = adapter.search(subject="x")
    assert out["results"] == ["a"]
    assert out["plane"] == "applescript-inbox"


def test_an_indexed_search_claims_no_plane(tmp_path, monkeypatch):
    # absence means "the documented plane" — the signal only fires on a degradation
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    assert "plane" not in MailAdapter().search(subject="Invoice 42")


def test_a_body_miss_reports_coverage(tmp_path, monkeypatch):
    # #156 case 4: ~63% of local messages are headers-only, so an empty body= answer
    # is usually about the INDEX, not the mailbox.
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    monkeypatch.setattr(mail_index, "fts_path", lambda: tmp_path / "absent.sqlite")
    monkeypatch.setattr(mail_index, "fts_search", lambda db_, q, limit=200: [])
    out = MailAdapter().search(body="nothing")
    assert out["results"] == []
    # an absent sidecar counts as 0 indexed — which is exactly the case to report
    assert out["coverage"].startswith("0 of ")
    assert "mail_index_bodies" in out["coverage"]


def test_body_coverage_counts_the_sidecar_against_distinct_message_ids(
    tmp_path, monkeypatch
):
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    fts = tmp_path / "fts.sqlite"
    conn = mail_index._fts_connect(fts)
    conn.execute("INSERT INTO bodies (message_id, body) VALUES ('<abc@ex.com>', 'hi')")
    # A body for a message no longer in the store — Mail deleted it, and re-indexing
    # never drops the row. It must NOT be counted: the two sides are intersected, not
    # divided. Counting rows made the real store report "22840 of 22379" once #119 let
    # partials be indexed and the sidecar overshot the live message count.
    conn.execute("INSERT INTO bodies (message_id, body) VALUES ('<gone@ex.com>', 'x')")
    conn.commit()
    conn.close()
    monkeypatch.setattr(mail_index, "fts_path", lambda: fts)
    text = mail_index.body_coverage()
    # denominator = distinct, non-deleted Message-IDs — the same set search dedups to
    # (the fixture's NULL-header row and every duplicate copy collapse out of it)
    assert text.startswith("1 of 9 messages")
    assert "(11.1%)" in text
