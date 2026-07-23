from macos_apps_mcp.adapters import mail_index


class _Row(dict):
    # sqlite3.Row supports __getitem__ by column name; a dict stands in for tests.
    pass


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
        mailbox="INBOX",
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
    assert "order by m.date_received desc" in low
    assert "limit ?" in low
    # every filter value is a bound param, none interpolated
    assert "inv" not in sql and "jane" not in sql
    assert "%inv%" in params and "%jane%" in params
    assert 1000 in params and 2000 in params and 10 in params


def test_build_header_query_message_ids_uses_in_clause():
    sql, params = mail_index.build_header_query(
        message_ids=["<a@x>", "<b@x>"], limit=25
    )
    assert "message_id_header in (?" in sql.lower()
    assert "<a@x>" in params and "<b@x>" in params


def test_build_header_query_no_filters_ok():
    sql, params = mail_index.build_header_query(limit=5)
    assert params == [5]  # only the limit
