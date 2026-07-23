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
