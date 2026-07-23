from macos_apps_mcp.adapters import mail_index


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
