import sqlite3

import pytest

from macos_apps_mcp.adapters import mail_index
from macos_apps_mcp.errors import SchemaDrift


def test_envelope_index_path_prefers_v10_over_v9(tmp_path, monkeypatch):
    # sorted() on p.parts is LEXICOGRAPHIC: 'V10' < 'V9', so a Mac that kept an old
    # V9 dir from before an OS upgrade silently read the STALE index — every index
    # tool (search/thread/overview) reporting success against outdated data.
    for v in ("V2", "V9", "V10"):
        d = tmp_path / "Library" / "Mail" / v / "MailData"
        d.mkdir(parents=True)
        (d / "Envelope Index").touch()
    monkeypatch.setenv("HOME", str(tmp_path))
    path = mail_index.envelope_index_path()
    assert path is not None
    assert path.parts[-3] == "V10"


def test_text_filter_like_metacharacters_are_escaped():
    # like_escape existed for exactly this and was applied to `account` only: the
    # other LIKE filters still read '%'/'_' as wildcards, so subject='50% off'
    # matched '50 anything off' — a confidently wrong answer, not a literal match.
    # (mailbox is no longer a LIKE at all — #144 resolves it to exact urls.)
    _, params = mail_index.build_header_query(
        subject="50%", from_="j_x", to="a%b", limit=5
    )
    assert r"%50\%%" in params
    assert r"%j\_x%" in params
    assert r"%a\%b%" in params


class _Row(dict):
    # sqlite3.Row supports __getitem__ by column name; a dict stands in for tests.
    pass


def _emlx(rfc822: bytes) -> bytes:
    plist_tail = b"<?xml version='1.0'?><plist></plist>"
    return f"{len(rfc822)}\n".encode() + rfc822 + plist_tail


def test_row_to_pointer_maps_all_fields():
    row = _Row(
        message_id_header="<abc@ex.com>",
        subject="Invoice 42",
        mailbox_url="imap://acct/INBOX",
    )
    p = mail_index.row_to_pointer(row)
    assert p.id == "<abc@ex.com>"
    assert p.summary == "Invoice 42"
    assert p.deeplink == "message://%3Cabc@ex.com%3E"
    assert p.folder == "imap://acct/INBOX"


def test_row_to_pointer_skips_headerless():
    assert (
        mail_index.row_to_pointer(
            _Row(message_id_header=None, subject="x", mailbox_url="m")
        )
        is None
    )
    assert (
        mail_index.row_to_pointer(
            _Row(message_id_header="  ", subject="x", mailbox_url="m")
        )
        is None
    )


def test_build_header_query_binds_all_filters():
    sql, params = mail_index.build_header_query(
        subject="inv",
        from_="jane",
        mailbox_urls=["imap://A/INBOX"],
        since=1000,
        until=2000,
        unread=True,
        flagged=True,
        limit=10,
    )
    low = sql.lower()
    assert "from messages" in low and "join subjects" in low
    assert "message_global_data" in low
    assert "m.deleted = 0" in low
    # final ORDER BY runs on the deduped outer query, so it's unqualified
    assert "order by date_received desc" in low
    assert "limit ?" in low
    # every filter value is a bound param, none interpolated
    assert "inv" not in sql and "jane" not in sql
    assert "%inv%" in params and "%jane%" in params
    assert 1000 in params and 2000 in params and 10 in params


def test_build_header_query_mailbox_urls_uses_in_clause():
    # #144: the mailbox filter binds RESOLVED urls exactly (IN), never a LIKE over
    # the encoded url — exact IN also kills the '%Trash%'-matches-"Trash Archive"
    # trap the account clause already documents.
    sql, params = mail_index.build_header_query(
        mailbox_urls=["imap://A/INBOX", "imap://A/Junk%20E-mail"], limit=5
    )
    assert "mb.url in (?,?)" in sql.lower()
    assert "imap://A/INBOX" in params and "imap://A/Junk%20E-mail" in params
    assert "like" not in sql.lower().split("mb.url in")[1].split("and")[0]


def test_build_header_query_message_ids_uses_in_clause():
    sql, params = mail_index.build_header_query(
        message_ids=["<a@x>", "<b@x>"], limit=25
    )
    assert "message_id_header in (?" in sql.lower()
    assert "<a@x>" in params and "<b@x>" in params


def test_build_header_query_no_filters_ok():
    sql, params = mail_index.build_header_query(limit=5)
    assert params == [5]  # only the limit


def test_build_local_account_query_is_pure():
    # PURE (sql, params) — no connection, matching every other builder here.
    sql, params = mail_index.build_local_account_query()
    assert params == []
    assert "local://" in sql.lower()
    assert "mailboxes" in sql.lower()


def test_parse_emlx_plaintext():
    raw = _emlx(
        b"From: a@x.com\r\nMessage-ID: <m1@x.com>\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"Hello invoice body"
    )
    mid, body = mail_index.parse_emlx(raw)
    assert mid == "<m1@x.com>"
    assert "invoice body" in body


def test_parse_emlx_html_stripped():
    raw = _emlx(
        b"Message-ID: <m2@x.com>\r\nContent-Type: text/html\r\n\r\n"
        b"<p>Hello <b>world</b></p>"
    )
    mid, body = mail_index.parse_emlx(raw)
    assert mid == "<m2@x.com>"
    assert "Hello" in body
    assert "<b>" not in body


def test_parse_emlx_headerless_returns_none():
    raw = _emlx(b"From: a@x.com\r\n\r\nno message id here")
    assert mail_index.parse_emlx(raw) is None


def test_parse_emlx_malformed_returns_none():
    assert mail_index.parse_emlx(b"not an emlx at all") is None


def test_parse_emlx_negative_length_returns_none():
    # A negative length prefix must not be accepted: int() parses "-5" fine, and a
    # negative-index slice (raw[nl+1 : nl+1-5]) would silently splice trailing plist
    # bytes into what's treated as the RFC822 body instead of failing loudly.
    rfc822 = (
        b"From: a@x.com\r\nMessage-ID: <neg@x.com>\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"Hello invoice body"
    )
    plist_tail = b"<?xml version='1.0'?><plist></plist>"
    raw = b"-5\n" + rfc822 + plist_tail
    assert mail_index.parse_emlx(raw) is None


def _write_emlx(path, mid, body):
    rfc = (f"Message-ID: {mid}\r\nContent-Type: text/plain\r\n\r\n{body}").encode()
    path.write_bytes(f"{len(rfc)}\n".encode() + rfc + b"<plist/>")


def test_build_body_index_indexes_partials_too(tmp_path):
    """#119: a ``.partial.emlx`` is missing its ATTACHMENTS, not its body.

    Device-measured 2026-08-06 over all 22,748 partials on the dev Mac: 22,627 (99.47%)
    carry a complete body, byte-identical to what Mail returns after fetching the whole
    message. This test used to assert the opposite — that a partial is skipped — which
    is how ~62% of the store stayed invisible to ``mail_search(body=…)``.
    """
    root = tmp_path / "Mail"
    msgs = root / "V10/acct/INBOX.mbox/Data/Messages"
    msgs.mkdir(parents=True)
    _write_emlx(msgs / "1.emlx", "<a@x>", "quarterly invoice total")
    _write_emlx(msgs / "2.partial.emlx", "<b@x>", "partial carries a real body")
    fts = tmp_path / "mail_fts.sqlite"
    res = mail_index.build_body_index(mail_root=root, fts_db=fts, max_bytes=10**9)
    assert res["indexed"] == 2 and res["total_emlx"] == 2
    assert mail_index.fts_search(fts, "invoice") == ["<a@x>"]
    assert mail_index.fts_search(fts, "carries") == ["<b@x>"]


def test_partial_that_fills_in_is_reindexed_without_duplicating(tmp_path):
    """``1.partial.emlx`` → ``1.emlx`` is a NEW key in indexed_files, so the filled-in
    message is re-read rather than skipped as unchanged — and the DELETE-by-message-id
    before each insert keeps that from leaving two FTS rows for one message."""
    root = tmp_path / "Mail"
    msgs = root / "V10/M"
    msgs.mkdir(parents=True)
    _write_emlx(msgs / "7.partial.emlx", "<c@x>", "receipt enclosed")
    fts = tmp_path / "mail_fts.sqlite"
    mail_index.build_body_index(mail_root=root, fts_db=fts, max_bytes=10**9)
    (msgs / "7.partial.emlx").unlink()
    _write_emlx(msgs / "7.emlx", "<c@x>", "receipt enclosed plus the attachment text")
    res = mail_index.build_body_index(mail_root=root, fts_db=fts, max_bytes=10**9)
    assert res["indexed"] == 1
    assert mail_index.fts_search(fts, "receipt") == ["<c@x>"]  # one row, not two
    assert mail_index.fts_search(fts, "attachment") == ["<c@x>"]


def test_build_body_index_resumes(tmp_path):
    root = tmp_path / "Mail"
    msgs = root / "V10/M"
    msgs.mkdir(parents=True)
    _write_emlx(msgs / "1.emlx", "<a@x>", "first")
    fts = tmp_path / "mail_fts.sqlite"
    mail_index.build_body_index(mail_root=root, fts_db=fts, max_bytes=10**9)
    _write_emlx(msgs / "2.emlx", "<b@x>", "second")
    res = mail_index.build_body_index(mail_root=root, fts_db=fts, max_bytes=10**9)
    assert res["indexed"] == 1 and res["skipped"] == 1  # only the new file indexed


def test_build_body_index_size_capped(tmp_path):
    root = tmp_path / "Mail"
    msgs = root / "V10/M"
    msgs.mkdir(parents=True)
    for i in range(5):
        _write_emlx(msgs / f"{i}.emlx", f"<{i}@x>", "body " * 50)
    fts = tmp_path / "mail_fts.sqlite"
    res = mail_index.build_body_index(
        mail_root=root, fts_db=fts, max_bytes=1
    )  # tiny cap
    assert res["capped"] is True and res["indexed"] >= 1


def test_fts_connect_sets_wal_and_busy_timeout(tmp_path):
    # #71 concurrency fix: mail_index_bodies runs off run_native, so the sidecar
    # writer needs WAL (readers proceed during a build) + a busy_timeout (writer/writer
    # contention waits instead of raising a raw sqlite OperationalError). Pin both.
    conn = mail_index._fts_connect(tmp_path / "x.sqlite")
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    finally:
        conn.close()


def test_fts_search_reads_during_open_build_write(tmp_path):
    # A mail_search(body=) reader must return the committed snapshot without raising
    # "database is locked" while a build holds the sidecar open with a write (WAL).
    root = tmp_path / "Mail"
    msgs = root / "V10/M"
    msgs.mkdir(parents=True)
    _write_emlx(msgs / "1.emlx", "<a@x>", "invoice quarterly")
    fts = tmp_path / "mail_fts.sqlite"
    mail_index.build_body_index(mail_root=root, fts_db=fts, max_bytes=10**9)
    writer = mail_index._fts_connect(fts)
    writer.execute("BEGIN IMMEDIATE")
    writer.execute("INSERT INTO bodies (message_id, body) VALUES ('<b@x>', 'later')")
    try:
        assert mail_index.fts_search(fts, "invoice") == ["<a@x>"]
    finally:
        writer.rollback()
        writer.close()


def test_build_body_index_skips_vanished_file(tmp_path, monkeypatch):
    # Mail.app can expunge/rename a .emlx between rglob() enumerating it and us
    # reading it. That must skip the one vanished file, not abort the whole run.
    root = tmp_path / "Mail"
    msgs = root / "V10/M"
    msgs.mkdir(parents=True)
    _write_emlx(msgs / "1.emlx", "<a@x>", "surviving invoice body")
    _write_emlx(msgs / "2.emlx", "<b@x>", "vanished invoice body")
    fts = tmp_path / "mail_fts.sqlite"
    vanished = msgs / "2.emlx"

    from pathlib import Path

    real_read_bytes = Path.read_bytes

    def flaky_read_bytes(self, *a, **kw):
        if self == vanished:
            raise FileNotFoundError(f"vanished: {self}")
        return real_read_bytes(self, *a, **kw)

    monkeypatch.setattr(Path, "read_bytes", flaky_read_bytes)

    res = mail_index.build_body_index(mail_root=root, fts_db=fts, max_bytes=10**9)

    assert res["total_emlx"] == 2
    assert res["indexed"] == 1
    assert res["skipped"] == 1
    assert mail_index.fts_search(fts, "surviving") == ["<a@x>"]


def test_fts_query_escapes_operators():
    # Ordinary body-search inputs must become an always-valid FTS5 expression: each
    # whitespace token quoted as a literal phrase (embedded `"` doubled), joined with
    # a space (FTS5 implicit AND) — never handed raw to MATCH (#70 review I1).
    assert mail_index._fts_query("jane@acme.com") == '"jane@acme.com"'
    assert mail_index._fts_query("C++") == '"C++"'
    assert mail_index._fts_query("invoice AND") == '"invoice" "AND"'
    assert mail_index._fts_query('foo"bar') == '"foo""bar"'
    assert mail_index._fts_query("   ") == ""


def test_fts_search_handles_operator_chars(tmp_path):
    # A body containing FTS5-special characters must be indexable AND searchable by a
    # query containing those same characters, without fts_search raising
    # sqlite3.OperationalError (#70 review I1: raw MATCH on '@'/'AND' syntax crashed).
    root = tmp_path / "Mail"
    msgs = root / "V10/M"
    msgs.mkdir(parents=True)
    _write_emlx(msgs / "1.emlx", "<a@x>", "contact jane@acme.com about C++")
    fts = tmp_path / "mail_fts.sqlite"
    mail_index.build_body_index(mail_root=root, fts_db=fts, max_bytes=10**9)

    assert mail_index.fts_search(fts, "jane@acme.com") == ["<a@x>"]
    assert mail_index.fts_search(fts, "C++") == ["<a@x>"]
    assert mail_index.fts_search(fts, "nomatch AND") == []


def test_parse_emlx_deeply_nested_multipart_returns_none():
    # A .emlx whose RFC822 nests multipart parts deeply enough overflows stdlib
    # email.message_from_bytes's own recursive descent (RecursionError), which must
    # not escape parse_emlx: malformed/attacker-influenceable input -> None, never
    # raise.
    inner = b"Content-Type: text/plain\r\n\r\nHello\r\n"
    for i in range(1500):
        boundary = f"b{i}".encode()
        inner = (
            b'Content-Type: multipart/mixed; boundary="' + boundary + b'"\r\n\r\n'
            b"--" + boundary + b"\r\n" + inner + b"\r\n--" + boundary + b"--\r\n"
        )
    rfc822 = b"Message-ID: <deep@x.com>\r\n" + inner
    raw = _emlx(rfc822)
    assert mail_index.parse_emlx(raw) is None


def test_fingerprint_covers_conversation_and_attachments():
    # conversation_id backs mail_thread; attachments backs has_attachments.
    # Both must be fingerprinted or a macOS schema move would silently
    # mis-answer instead of drifting.
    assert "conversation_id" in mail_index.HEADER_FINGERPRINT["messages"]
    assert mail_index.HEADER_FINGERPRINT["attachments"] == {"ROWID", "message", "name"}


def test_header_query_deduplicates_by_message_id():
    sql, _ = mail_index.build_header_query(subject="x", limit=5)
    low = sql.lower()
    assert "row_number() over" in low
    assert "partition by gd.message_id_header" in low
    assert "where rn = 1" in low


def test_header_query_excludes_headerless_rows():
    # no Message-ID means no citable Pointer; excluding in SQL (not after) keeps LIMIT
    # honest — otherwise LIMIT 25 can return 20 usable rows.
    sql, _ = mail_index.build_header_query(subject="x", limit=5)
    low = sql.lower()
    assert "gd.message_id_header is not null" in low
    assert "gd.message_id_header <> ''" in low


def test_has_attachments_excludes_inline_images():
    # Mail records signature/newsletter images as attachment rows — device-verified,
    # top names on a real Mac are image001.png (426) and embed0.png (285). A naive
    # EXISTS matched 4,474 messages where only 2,223 carried a real document.
    sql, _ = mail_index.build_header_query(has_attachments=True, limit=5)
    low = sql.lower()
    assert "exists" in low and "attachments" in low
    for ext in ("png", "jpg", "jpeg", "gif"):
        assert f"%.{ext}" in low


def test_has_attachments_false_adds_no_clause():
    with_f, _ = mail_index.build_header_query(
        subject="x", has_attachments=False, limit=5
    )
    without, _ = mail_index.build_header_query(subject="x", limit=5)
    assert with_f == without


def test_account_is_a_bound_param():
    sql, params = mail_index.build_header_query(account="AAAA", limit=5)
    assert "AAAA" not in sql
    assert "AAAA" in params
    # anchored to the account SEGMENT of <scheme>://<UUID>/<path>, not a substring of
    # the whole url (which also matched any account's similarly-named FOLDER)
    assert "'%://' || ? || '/%'" in sql


def test_account_like_metacharacters_are_escaped():
    # a bound param stops injection; it does not stop LIKE reading '%' as "everything",
    # which turned account='%' into a filter that silently matched every mailbox.
    _, params = mail_index.build_header_query(account="a%b_c", limit=5)
    assert r"a\%b\_c" in params


def test_like_escape_escapes_its_own_escape_char():
    assert mail_index.like_escape(r"a\%") == r"a\\\%"


def test_thread_query_binds_message_id_and_limit():
    sql, params = mail_index.build_thread_query("<abc@ex.com>", limit=50)
    assert "<abc@ex.com>" not in sql
    assert params == ["<abc@ex.com>", 50]
    low = sql.lower()
    assert "conversation_id" in low
    assert "row_number() over" in low  # same dedup rule as search


def test_overview_query_counts_live_not_stored():
    # mailboxes.unread_count is trigger-maintained and STALE on a real Mac — the Gmail
    # INBOX row claims 1 unread where a live count returns 0. Never read that column.
    sql, params = mail_index.build_overview_query()
    low = sql.lower()
    assert params == []
    assert "unread_count" not in low
    assert "count(" in low and "m.read = 0" in low
    assert "m.deleted = 0" in low


# --- #192: the awaiting-reply sent scan, off the index at rest -----------------------


def test_sent_triage_query_binds_sent_suffixes_and_limit():
    sql, params = mail_index.build_sent_triage_query(100)
    # one LIKE clause per sent spelling, bound as params ahead of the limit
    assert sql.count("mb.url LIKE ? ESCAPE") == len(mail_index._SENT_SUFFIXES)
    assert params == [*mail_index._SENT_SUFFIXES, 100]
    # deduped per distinct message, newest first, and correlated through Mail's own
    # References graph — the citing message must sit in an inbox, so a reply DRAFT
    # (which also cites the original) cannot clear a send prematurely
    assert "GROUP BY m.message_id" in sql
    assert "message_references" in sql
    assert "'%/INBOX'" in sql
    assert "m.deleted = 0" in sql


def test_sent_recipients_query_is_to_only_and_ordered():
    sql, params = mail_index.build_sent_recipients_query([7, 9])
    assert params == [7, 9]
    assert "r.type = 0" in sql  # To — probed 2026-08-20
    assert "ORDER BY r.message, r.position" in sql


# --- check_index_schema + the #199 platform floor ------------------------------------
# A Sequoia (macOS 15) Envelope Index has no message_global_data.message_id_header —
# the column is a macOS 26 (Tahoe) migration. That exact condition on a pre-Tahoe
# system must diagnose as a platform floor, NOT as "macOS likely changed the schema";
# any other drift (and the same condition on 26+) keeps the generic message.


def _fingerprint_index(path, *, message_id_header=True, subjects_table=True):
    """A rowless store carrying exactly the fingerprinted tables/columns, with the
    two knobs these tests turn: the #199 column, and an unrelated whole table."""
    subjects = (
        "CREATE TABLE subjects(ROWID INTEGER PRIMARY KEY, subject TEXT);"
        if subjects_table
        else ""
    )
    header_col = ", message_id_header TEXT" if message_id_header else ""
    c = sqlite3.connect(path)
    # message_global_data carries message_id (an internal integer id) on BOTH shapes
    # — device-verified: Sequoia 15.7.9 has it, Tahoe has it; only message_id_header
    # is the Tahoe-only migration. The #201 shadow view reads it, so the fixture
    # must be shaped like the device.
    c.executescript(
        f"""
        CREATE TABLE messages(
            ROWID INTEGER PRIMARY KEY, subject INT, sender INT, global_message_id INT,
            mailbox INT, date_received INT, date_sent INT, read INT, flagged INT,
            deleted INT, conversation_id INT);
        {subjects}
        CREATE TABLE addresses(ROWID INTEGER PRIMARY KEY, address TEXT, comment TEXT);
        CREATE TABLE mailboxes(ROWID INTEGER PRIMARY KEY, url TEXT);
        CREATE TABLE message_global_data(
            ROWID INTEGER PRIMARY KEY, message_id INTEGER{header_col});
        CREATE TABLE recipients(ROWID INTEGER PRIMARY KEY, message INT, address INT);
        CREATE TABLE attachments(ROWID INTEGER PRIMARY KEY, message INT, name TEXT);
        """
    )
    c.commit()
    c.close()


def _mac_ver(monkeypatch, ver):
    monkeypatch.setattr(
        mail_index.platform, "mac_ver", lambda: (ver, ("", "", ""), "x86_64")
    )


def test_check_index_schema_ok(tmp_path, monkeypatch):
    db = tmp_path / "Envelope Index"
    _fingerprint_index(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    assert mail_index.check_index_schema() == "ok"


def test_check_index_schema_no_store(monkeypatch):
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: None)
    assert mail_index.check_index_schema() == "no_mail_data"


def test_missing_header_column_on_sequoia_is_a_platform_floor(tmp_path, monkeypatch):
    db = tmp_path / "Envelope Index"
    _fingerprint_index(db, message_id_header=False)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    _mac_ver(monkeypatch, "15.7.9")
    with pytest.raises(SchemaDrift) as exc:
        mail_index.check_index_schema()
    msg = str(exc.value)
    assert "macOS 26" in msg and "15.7.9" in msg
    assert "platform floor" in msg
    assert "trash_mail" in msg  # the destructive-tool consequence, spelled out
    assert "likely changed the schema" not in msg


def test_missing_header_column_on_tahoe_stays_generic_drift(tmp_path, monkeypatch):
    db = tmp_path / "Envelope Index"
    _fingerprint_index(db, message_id_header=False)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    _mac_ver(monkeypatch, "26.1")
    with pytest.raises(SchemaDrift) as exc:
        mail_index.check_index_schema()
    # On 26+ the column SHOULD exist: this really is drift, and the fingerprint
    # really is the thing to update.
    assert "likely changed the schema" in str(exc.value)
    assert "platform floor" not in str(exc.value)


def test_other_drift_on_sequoia_stays_generic(tmp_path, monkeypatch):
    db = tmp_path / "Envelope Index"
    _fingerprint_index(db, subjects_table=False)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    _mac_ver(monkeypatch, "15.7.9")
    with pytest.raises(SchemaDrift) as exc:
        mail_index.check_index_schema()
    assert "platform floor" not in str(exc.value)


def test_floor_drift_still_runs_fallback(tmp_path, monkeypatch):
    # The specialization must not break #58's degrade policy: a read WITH a
    # fallback still falls back on floor drift instead of raising.
    db = tmp_path / "Envelope Index"
    _fingerprint_index(db, message_id_header=False)
    _mac_ver(monkeypatch, "15.7.9")
    assert mail_index._read_index(db, lambda conn: None, fallback=lambda: "FB") == "FB"


# --- #201: store-mode detection + the sidecar shadow --------------------------------
# native (Tahoe: the column exists), sidecar (pre-26, column absent, sidecar built),
# floor (pre-26, no sidecar → the #199 message, now naming mail_index_ids).


def _built_sidecar(tmp_path, monkeypatch, *, mappings=(), high_water=0):
    """A REAL (schema-complete) sidecar at a monkeypatched location — an empty FILE
    is not enough: the shadow view resolves mid.global_ids at first use, so only a
    store with the actual table stands in for a harvest's output."""
    from macos_apps_mcp.adapters import mail_ids

    side = tmp_path / "mail_ids.sqlite"
    conn = mail_ids._connect(side)
    conn.executemany("INSERT INTO global_ids VALUES (?, ?)", list(mappings))
    conn.execute(
        "INSERT OR REPLACE INTO meta VALUES ('max_rowid_harvested', ?)",
        (str(high_water),),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(mail_ids, "sidecar_path", lambda: side)
    return side


def test_mode_native_when_the_column_exists(tmp_path, monkeypatch):
    db = tmp_path / "Envelope Index"
    _fingerprint_index(db)
    assert mail_index._index_mode(db) == "native"


def test_mode_sidecar_when_column_absent_pre26_with_sidecar(tmp_path, monkeypatch):
    db = tmp_path / "Envelope Index"
    _fingerprint_index(db, message_id_header=False)
    _mac_ver(monkeypatch, "15.7.9")
    _built_sidecar(tmp_path, monkeypatch)
    assert mail_index._index_mode(db) == "sidecar"


def test_mode_floor_without_a_sidecar(tmp_path, monkeypatch):
    from macos_apps_mcp.adapters import mail_ids

    db = tmp_path / "Envelope Index"
    _fingerprint_index(db, message_id_header=False)
    _mac_ver(monkeypatch, "15.7.9")
    monkeypatch.setattr(mail_ids, "sidecar_path", lambda: tmp_path / "absent.sqlite")
    assert mail_index._index_mode(db) == "floor"


def test_mode_on_tahoe_ignores_a_sidecar(tmp_path, monkeypatch):
    # column absent on 26+ is REAL drift — a sidecar must never mask it.
    db = tmp_path / "Envelope Index"
    _fingerprint_index(db, message_id_header=False)
    _mac_ver(monkeypatch, "26.1")
    _built_sidecar(tmp_path, monkeypatch)
    assert mail_index._index_mode(db) == "floor"
    with pytest.raises(SchemaDrift, match="likely changed the schema"):
        mail_index._read_index(db, lambda conn: None)


def test_mode_flips_floor_to_sidecar_without_a_restart(tmp_path, monkeypatch):
    # The cache is keyed on sidecar existence: the moment mail_index_ids finishes,
    # the very next read serves sidecar mode — no process restart, no cache flush.
    from macos_apps_mcp.adapters import mail_ids

    db = tmp_path / "Envelope Index"
    _fingerprint_index(db, message_id_header=False)
    _mac_ver(monkeypatch, "15.7.9")
    side = tmp_path / "mail_ids.sqlite"
    monkeypatch.setattr(mail_ids, "sidecar_path", lambda: side)
    assert mail_index._index_mode(db) == "floor"
    conn = mail_ids._connect(side)
    conn.commit()
    conn.close()
    assert mail_index._index_mode(db) == "sidecar"


def test_sidecar_mode_serves_the_native_fingerprint_and_queries(tmp_path, monkeypatch):
    # The whole spike finding in one test: with the shadow view attached, the
    # UNCHANGED fingerprint passes and the UNCHANGED join answers with the
    # sidecar's Message-ID.
    db = tmp_path / "Envelope Index"
    _fingerprint_index(db, message_id_header=False)
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        INSERT INTO subjects VALUES (1, 'Invoice 42');
        INSERT INTO mailboxes VALUES (1, 'imap://A/INBOX');
        INSERT INTO message_global_data (ROWID) VALUES (100);
        INSERT INTO messages VALUES (10,1,NULL,100,1,1700000000,1700000000,0,0,0,7);
        """
    )
    conn.commit()
    conn.close()
    _mac_ver(monkeypatch, "15.7.9")
    _built_sidecar(tmp_path, monkeypatch, mappings=[(100, "<a@x>")], high_water=10)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    out = mail_index.query_search(subject="Invoice")
    assert [p.id for p in out] == ["<a@x>"]
    assert out[0].folder == "imap://A/INBOX"
    assert mail_index.check_index_schema() == "sidecar"


def test_floor_message_names_mail_index_ids(tmp_path, monkeypatch):
    # #200's floor told the user the platform was the end of the road; #201 makes
    # the same message the START of the fix.
    from macos_apps_mcp.adapters import mail_ids

    db = tmp_path / "Envelope Index"
    _fingerprint_index(db, message_id_header=False)
    _mac_ver(monkeypatch, "15.7.9")
    monkeypatch.setattr(mail_ids, "sidecar_path", lambda: tmp_path / "absent.sqlite")
    with pytest.raises(SchemaDrift, match="mail_index_ids"):
        mail_index._read_index(db, lambda conn: None)
