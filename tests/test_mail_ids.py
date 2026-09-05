"""The Message-ID sidecar store + harvester (#201, PR-A) over a fake Mail tree.

The tree mirrors what was device-verified on the Sequoia rig: message files named
``<messages.ROWID>.emlx`` / ``.partial.emlx`` under
``V10/<account-uuid>/<segment>.mbox[/<segment>.mbox…]/<store-uuid>/Data/``, and an
Envelope Index whose ``message_global_data`` never stored the RFC822 Message-ID."""

import sqlite3

import pytest

from macos_apps_mcp.adapters import mail_ids, mail_index
from macos_apps_mcp.adapters.mail import MailAdapter
from macos_apps_mcp.errors import NativeError

ACCT = "AAAAAAAA-1111-2222-3333-444444444444"
STORE = "12345678-ABCD-EF01-2345-6789ABCDEF01"


def _fake_index(path, mailboxes, messages):
    """A minimal Envelope Index carrying exactly the harvester's REDUCED fingerprint
    — deliberately WITHOUT message_global_data.message_id_header, because the
    harvester must run on precisely the stores where that column is absent."""
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path)
    c.executescript(
        """
        CREATE TABLE mailboxes(ROWID INTEGER PRIMARY KEY, url TEXT);
        CREATE TABLE messages(
            ROWID INTEGER PRIMARY KEY, global_message_id INT, mailbox INT,
            deleted INT DEFAULT 0);
        """
    )
    c.executemany("INSERT INTO mailboxes VALUES (?,?)", mailboxes)
    c.executemany("INSERT INTO messages VALUES (?,?,?,?)", messages)
    c.commit()
    c.close()


def _write_emlx(path, mid, body="hello"):
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = f"Message-ID: {mid}\r\n" if mid else ""
    rfc = (f"{headers}Content-Type: text/plain\r\n\r\n{body}").encode()
    path.write_bytes(f"{len(rfc)}\n".encode() + rfc + b"<plist/>")


@pytest.fixture
def tree(tmp_path):
    """(index_path, sidecar_db, data_dir) — one INBOX mailbox, empty tree."""
    v10 = tmp_path / "Mail" / "V10"
    index = v10 / "MailData" / "Envelope Index"
    data = v10 / ACCT / "INBOX.mbox" / STORE / "Data" / "0" / "Messages"
    data.mkdir(parents=True)
    return index, tmp_path / "mail_ids.sqlite", data


def _sidecar_rows(db):
    conn = sqlite3.connect(db)
    try:
        return dict(conn.execute("SELECT * FROM global_ids"))
    finally:
        conn.close()


def test_build_maps_ids_including_partials(tree):
    index, side, data = tree
    _fake_index(
        index,
        [(1, f"imap://{ACCT}/INBOX")],
        [(10, 100, 1, 0), (11, 101, 1, 0)],
    )
    _write_emlx(data / "10.emlx", "<a@x>")
    # a .partial is missing its ATTACHMENTS, not its headers (#119) — an id source
    _write_emlx(data / "11.partial.emlx", "<b@x>")
    res = mail_ids.build(index, sidecar_db=side)
    assert _sidecar_rows(side) == {100: "<a@x>", 101: "<b@x>"}
    assert res["harvested"] == 2
    assert res["mapped"] == 2 and res["total_ids"] == 2
    assert res["coverage"].startswith("2 of 2 ids mapped (100.0%)")
    assert res["high_water_rowid"] == 11
    assert res["index_rebuilt"] is False


def test_build_resolves_nested_mailbox_segments(tmp_path):
    # 'Clients/Acme' → Clients.mbox/Acme.mbox/<store-uuid>/Data — each path segment
    # appends .mbox (device-verified); the %20 decodes before hitting the filesystem.
    v10 = tmp_path / "V10"
    index = v10 / "MailData" / "Envelope Index"
    _fake_index(index, [(1, f"imap://{ACCT}/Clients/Acme%20Co")], [(7, 70, 1, 0)])
    nested = v10 / ACCT / "Clients.mbox" / "Acme Co.mbox" / STORE / "Data" / "Messages"
    _write_emlx(nested / "7.emlx", "<nested@x>")
    side = tmp_path / "ids.sqlite"
    res = mail_ids.build(index, sidecar_db=side)
    assert _sidecar_rows(side) == {70: "<nested@x>"}
    assert res["harvested"] == 1


def test_missing_file_is_skipped_and_retried_next_run(tree):
    index, side, data = tree
    _fake_index(index, [(1, f"imap://{ACCT}/INBOX")], [(10, 100, 1, 0)])
    res = mail_ids.build(index, sidecar_db=side)
    assert res["skipped_no_file"] == 1 and res["harvested"] == 0
    assert _sidecar_rows(side) == {}
    # the message downloads later — the next run picks it up, no rebuild needed
    _write_emlx(data / "10.emlx", "<late@x>")
    res = mail_ids.build(index, sidecar_db=side)
    assert res["harvested"] == 1
    assert _sidecar_rows(side) == {100: "<late@x>"}


def test_headerless_message_is_reported_not_mapped(tree):
    # No RFC822 Message-ID exists to map — uncitable on EVERY macOS (Tahoe's own
    # native column imposes the same rule); reported, never crashed on.
    index, side, data = tree
    _fake_index(index, [(1, f"imap://{ACCT}/INBOX")], [(10, 100, 1, 0)])
    _write_emlx(data / "10.emlx", mid=None)
    res = mail_ids.build(index, sidecar_db=side)
    assert res["skipped_no_message_id"] == 1
    assert _sidecar_rows(side) == {}


def test_account_without_local_store_counts_rows_never_crashes(tree):
    # 14 such rows on the rig: the account exists in the index but keeps no local
    # store under V* at all. Its rows are counted into the report — the coverage
    # denominator still includes them — and the build completes.
    index, side, data = tree
    other = "BBBBBBBB-1111-2222-3333-444444444444"
    _fake_index(
        index,
        [(1, f"imap://{ACCT}/INBOX"), (2, f"imap://{other}/INBOX")],
        [(10, 100, 1, 0), (20, 200, 2, 0), (21, 201, 2, 0)],
    )
    _write_emlx(data / "10.emlx", "<a@x>")
    res = mail_ids.build(index, sidecar_db=side)
    assert res["rows_without_local_store"] == 2
    assert res["harvested"] == 1
    assert res["mapped"] == 1 and res["total_ids"] == 3


def test_deleted_rows_are_not_harvested(tree):
    index, side, data = tree
    _fake_index(
        index, [(1, f"imap://{ACCT}/INBOX")], [(10, 100, 1, 0), (11, 101, 1, 1)]
    )
    _write_emlx(data / "10.emlx", "<live@x>")
    _write_emlx(data / "11.emlx", "<tombstoned@x>")
    res = mail_ids.build(index, sidecar_db=side)
    assert _sidecar_rows(side) == {100: "<live@x>"}
    assert res["total_ids"] == 1


def test_attachment_sidecar_files_are_not_messages(tree):
    # Mail parks fetched attachment payloads under Data/…/Attachments/<rowid>/… —
    # a file there matching <n>.emlx must never be read as message <n>'s bytes.
    index, side, data = tree
    _fake_index(index, [(1, f"imap://{ACCT}/INBOX")], [(10, 100, 1, 0)])
    _write_emlx(data.parent / "Attachments" / "10" / "2" / "10.emlx", "<fake@x>")
    res = mail_ids.build(index, sidecar_db=side)
    assert res["skipped_no_file"] == 1
    assert _sidecar_rows(side) == {}


def test_copies_sharing_a_gid_need_only_one_file(tree):
    # A filed copy and an All Mail copy share global_message_id; one readable file
    # maps them both — which is why the sidecar keys on gid, not ROWID.
    index, side, data = tree
    _fake_index(
        index,
        [(1, f"imap://{ACCT}/INBOX")],
        [(10, 100, 1, 0), (11, 100, 1, 0)],
    )
    _write_emlx(data / "10.emlx", "<shared@x>")
    res = mail_ids.build(index, sidecar_db=side)
    assert _sidecar_rows(side) == {100: "<shared@x>"}
    assert res["harvested"] == 1
    assert res["skipped_no_file"] == 0  # the second copy was never a candidate
    assert res["coverage"].startswith("1 of 1 ids mapped")


def test_rerun_is_incremental(tree):
    index, side, data = tree
    _fake_index(index, [(1, f"imap://{ACCT}/INBOX")], [(10, 100, 1, 0)])
    _write_emlx(data / "10.emlx", "<a@x>")
    mail_ids.build(index, sidecar_db=side)
    # new mail arrives
    conn = sqlite3.connect(index)
    conn.execute("INSERT INTO messages VALUES (11, 101, 1, 0)")
    conn.commit()
    conn.close()
    _write_emlx(data / "11.emlx", "<new@x>")
    res = mail_ids.build(index, sidecar_db=side)
    assert res["harvested"] == 1  # only the new row was touched
    assert _sidecar_rows(side) == {100: "<a@x>", 101: "<new@x>"}
    assert res["high_water_rowid"] == 11


def test_index_rebuild_triggers_full_reharvest(tree):
    # Mailbox → Rebuild reassigns ROWIDs (and can reissue gids), so max(ROWID)
    # falling BELOW the stored high-water mark means every stored mapping is
    # suspect: everything is re-read and INSERT OR REPLACE overwrites in place.
    index, side, data = tree
    _fake_index(index, [(1, f"imap://{ACCT}/INBOX")], [(10, 100, 1, 0)])
    _write_emlx(data / "10.emlx", "<old@x>")
    assert mail_ids.build(index, sidecar_db=side)["high_water_rowid"] == 10
    conn = sqlite3.connect(index)
    conn.execute("DELETE FROM messages")
    conn.execute("INSERT INTO messages VALUES (5, 100, 1, 0)")  # same gid, new ROWID
    conn.commit()
    conn.close()
    (data / "10.emlx").unlink()
    _write_emlx(data / "5.emlx", "<rebuilt@x>")
    res = mail_ids.build(index, sidecar_db=side)
    assert res["index_rebuilt"] is True
    assert _sidecar_rows(side) == {100: "<rebuilt@x>"}  # replaced, not duplicated
    assert res["high_water_rowid"] == 5


def test_meta_records_high_water_and_built_at(tree):
    index, side, data = tree
    _fake_index(index, [(1, f"imap://{ACCT}/INBOX")], [(10, 100, 1, 0)])
    _write_emlx(data / "10.emlx", "<a@x>")
    mail_ids.build(index, sidecar_db=side)
    assert mail_ids.stored_high_water(side) == 10
    conn = sqlite3.connect(side)
    built = conn.execute("SELECT value FROM meta WHERE key='built_at'").fetchone()
    conn.close()
    assert built and built[0]


def test_stored_high_water_absent_sidecar_is_none(tmp_path):
    assert mail_ids.stored_high_water(tmp_path / "nope.sqlite") is None


def test_coverage_intersects_live_ids_only(tree):
    # The sidecar keeps mappings for since-deleted messages forever (harmless to
    # queries); coverage must intersect with LIVE gids, never divide row counts —
    # the same rule body_coverage() learned when its ratio exceeded 1 (#119).
    index, side, data = tree
    _fake_index(index, [(1, f"imap://{ACCT}/INBOX")], [(10, 100, 1, 0)])
    _write_emlx(data / "10.emlx", "<a@x>")
    mail_ids.build(index, sidecar_db=side)
    conn = sqlite3.connect(side)
    conn.execute("INSERT INTO global_ids VALUES (999, '<gone@x>')")
    conn.commit()
    conn.close()
    c = mail_ids.coverage(index, sidecar_db=side)
    assert c["mapped"] == 1 and c["total"] == 1
    assert c["high_water"] == 10 and c["max_rowid"] == 10


def test_coverage_none_without_a_sidecar(tree):
    index, side, _ = tree
    _fake_index(index, [(1, f"imap://{ACCT}/INBOX")], [(10, 100, 1, 0)])
    assert mail_ids.coverage(index, sidecar_db=side) is None
    assert mail_ids.coverage_line(index, sidecar_db=side) == "no sidecar built"


def test_coverage_line_reports_the_unharvested_tail(tree):
    index, side, data = tree
    _fake_index(index, [(1, f"imap://{ACCT}/INBOX")], [(10, 100, 1, 0)])
    _write_emlx(data / "10.emlx", "<a@x>")
    mail_ids.build(index, sidecar_db=side)
    conn = sqlite3.connect(index)
    conn.execute("INSERT INTO messages VALUES (14, 104, 1, 0)")
    conn.commit()
    conn.close()
    line = mail_ids.coverage_line(index, sidecar_db=side)
    assert line.startswith("1 of 2 ids mapped (50.0%), high-water ROWID 10, built ")
    assert "4 newer rows not yet harvested" in line


# --- the adapter method + tool/CLI wiring -------------------------------------------


def test_adapter_index_ids_requires_a_store(monkeypatch):
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: None)
    with pytest.raises(NativeError, match="Open Mail once"):
        MailAdapter().index_ids()


def test_adapter_index_ids_delegates_and_rebuild_unlinks(tmp_path, monkeypatch):
    import macos_apps_mcp.adapters.mail as mail_mod

    index = tmp_path / "Envelope Index"
    index.touch()
    side = tmp_path / "mail_ids.sqlite"
    side.write_bytes(b"stale")
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: index)
    monkeypatch.setattr(mail_mod.mail_ids, "sidecar_path", lambda: side)
    calls = []
    monkeypatch.setattr(
        mail_mod.mail_ids, "build", lambda path: calls.append(path) or {"ok": 1}
    )
    assert MailAdapter().index_ids(rebuild=True) == {"ok": 1}
    assert calls == [index]
    assert not side.exists()  # rebuild starts from an empty sidecar


def test_cli_role_dispatches(monkeypatch, capsys, tmp_path):
    from macos_apps_mcp import cli
    from macos_apps_mcp.adapters import mail_ids as ids_mod

    index = tmp_path / "Envelope Index"
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: None)
    monkeypatch.setattr(ids_mod, "build", lambda path: {"harvested": 3})
    monkeypatch.setattr("sys.argv", ["macos-apps-mcp", "index-mail-ids"])

    # require_index_path raises on a missing store even from the CLI
    with pytest.raises(NativeError, match="Open Mail once"):
        cli.main()
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: index)
    cli.main()
    assert "harvested: 3" in capsys.readouterr().out


def test_mail_index_ids_tool_registered_read_only():
    import asyncio

    from fastmcp import Client

    import macos_apps_mcp.server as srv

    async def go():
        async with Client(srv.mcp) as c:
            tools = {t.name: t for t in await c.list_tools()}
            # same tier and pattern as mail_index_bodies — see the tool's comment
            assert tools["mail_index_ids"].annotations.readOnlyHint is True

    asyncio.run(go())


# --- check_index_schema's sidecar state (#201) --------------------------------------


def test_check_index_schema_reports_sidecar_on_floor_with_sidecar(
    tmp_path, monkeypatch
):
    from tests.test_mail_index import _fingerprint_index, _mac_ver

    db = tmp_path / "Envelope Index"
    _fingerprint_index(db, message_id_header=False)
    side = tmp_path / "mail_ids.sqlite"
    side.touch()
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    monkeypatch.setattr(mail_index.mail_ids, "sidecar_path", lambda: side)
    _mac_ver(monkeypatch, "15.7.9")
    assert mail_index.check_index_schema() == "sidecar"


def test_check_index_schema_floor_without_sidecar_still_raises(tmp_path, monkeypatch):
    from macos_apps_mcp.errors import SchemaDrift
    from tests.test_mail_index import _fingerprint_index, _mac_ver

    db = tmp_path / "Envelope Index"
    _fingerprint_index(db, message_id_header=False)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    monkeypatch.setattr(
        mail_index.mail_ids, "sidecar_path", lambda: tmp_path / "absent.sqlite"
    )
    _mac_ver(monkeypatch, "15.7.9")
    with pytest.raises(SchemaDrift, match="platform floor"):
        mail_index.check_index_schema()


def test_check_index_schema_generic_drift_ignores_sidecar(tmp_path, monkeypatch):
    # a sidecar must not mask REAL drift (a missing table, or the same condition on
    # macOS 26+) — only the diagnosed platform floor earns the sidecar state.
    from macos_apps_mcp.errors import SchemaDrift
    from tests.test_mail_index import _fingerprint_index, _mac_ver

    db = tmp_path / "Envelope Index"
    _fingerprint_index(db, message_id_header=False)
    side = tmp_path / "mail_ids.sqlite"
    side.touch()
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    monkeypatch.setattr(mail_index.mail_ids, "sidecar_path", lambda: side)
    _mac_ver(monkeypatch, "26.1")
    with pytest.raises(SchemaDrift, match="likely changed the schema"):
        mail_index.check_index_schema()
