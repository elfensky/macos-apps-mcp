"""0.9.4 extras — save an attachment (#81) and statistics + export (#85).

The filesystem boundary itself is pinned in ``test_mail_files.py``; these tests are
about the two features wired onto it — that #81 refuses BEFORE the Apple Event rather
than after, and that #85 counts DISTINCT messages rather than rows (raw rows overcount
by up to 3.6x on a real store, the same margin ``mail_overview`` was fixed for).
"""

from __future__ import annotations

import time

import pytest

from macos_apps_mcp import runtime
from macos_apps_mcp.adapters import (
    mail,
    mail_addressing,
    mail_attachments,
    mail_index,
    mail_recover,
)
from macos_apps_mcp.errors import BatchTooLarge
from macos_apps_mcp.text import US

_ACCT = "AAAAAAAA-1111-2222-3333-444444444444"
_BOX = f"imap://{_ACCT}/INBOX"


@pytest.fixture
def root(tmp_path, monkeypatch):
    r = tmp_path / "root"
    r.mkdir()
    monkeypatch.setenv("MACOS_APPS_FILE_ROOT", str(r))
    return r


@pytest.fixture
def resolved(monkeypatch):
    """``mail_addressing.resolve`` answers with one target, no index, no Mail."""
    monkeypatch.setattr(
        mail_addressing,
        "resolve",
        lambda mid, folder=None, account=None: mail_addressing.ResolvedMessage(
            id=mail_addressing.bare_id(mid), folder=_BOX, account=_ACCT
        ),
    )


# --- #81: save one attachment --------------------------------------------------------


def test_save_passes_the_target_path_and_cap_through_argv(root, resolved, monkeypatch):
    seen = {}

    def fake(script, *argv, **kw):
        seen["script"], seen["argv"], seen["kw"] = script, argv, kw
        (root / "invoices" / "deal.pdf").write_bytes(b"%PDF-1.4")
        return f"1234{US}true"

    monkeypatch.setattr(runtime, "run_osascript", fake)
    out = mail.MailAdapter().save_attachment("<a@x>", "invoices", name="deal.pdf")
    assert seen["script"] is mail_attachments._SAVE_ATTACHMENT
    assert seen["argv"] == (
        "a@x",
        _ACCT,
        "INBOX",
        "deal.pdf",
        "",
        str(root / "invoices" / "deal.pdf"),
        str(mail.mail_files.MAX_BYTES),
    )
    # saving can make Mail FETCH the message off the server, so this is not a 30s read
    assert seen["kw"] == {"timeout": mail_attachments._SAVE_TIMEOUT}
    assert out["bytes"] == 8
    assert out["reported_size"] == 1234
    assert out["was_downloaded"] is True
    assert out["name"] == "deal.pdf"


def test_save_derives_the_filename_from_a_hostile_attachment_name(
    root, resolved, monkeypatch
):
    """The whole point of #81's security posture: the name is attacker-controlled and
    reaches the filesystem. It must land inside dest_dir, basename only."""
    seen = {}

    def fake(script, *argv, **kw):
        seen["dest"] = argv[5]
        (root / "in" / "authorized_keys").write_bytes(b"x")
        return f"10{US}true"

    monkeypatch.setattr(runtime, "run_osascript", fake)
    out = mail.MailAdapter().save_attachment(
        "<a@x>", "in", name="../../../.ssh/authorized_keys"
    )
    assert seen["dest"] == str(root / "in" / "authorized_keys")
    assert out["original_name"] == "../../../.ssh/authorized_keys"


def test_save_refuses_an_existing_file_before_any_native_call(
    root, resolved, monkeypatch
):
    (root / "deal.pdf").write_bytes(b"mine")

    def boom(*a, **k):
        raise AssertionError("must refuse before touching Mail")

    monkeypatch.setattr(runtime, "run_osascript", boom)
    with pytest.raises(FileExistsError):
        mail.MailAdapter().save_attachment("<a@x>", "", name="deal.pdf")
    assert (root / "deal.pdf").read_bytes() == b"mine"


def test_save_removes_an_empty_file_and_reports_it(root, resolved, monkeypatch):
    """Mail fetches an undownloaded attachment on demand (device-verified), but an
    offline account cannot — and a 0-byte file that looks like a success is the
    reassuring-direction lie this repo keeps refusing."""

    def fake(script, *argv, **kw):
        (root / "empty.pdf").touch()
        return f"0{US}false"

    monkeypatch.setattr(runtime, "run_osascript", fake)
    with pytest.raises(ValueError, match="0 bytes"):
        mail.MailAdapter().save_attachment("<a@x>", "", name="empty.pdf")
    assert not (root / "empty.pdf").exists()


def test_save_needs_a_name_or_an_id(root, resolved):
    with pytest.raises(ValueError, match="name or its id"):
        mail.MailAdapter().save_attachment("<a@x>", "out")


def test_save_by_attachment_id_leaves_the_name_slot_empty(root, resolved, monkeypatch):
    seen = {}

    def fake(script, *argv, **kw):
        seen["argv"] = argv
        (root / "1.12").write_bytes(b"pdf")
        return f"3{US}false"

    monkeypatch.setattr(runtime, "run_osascript", fake)
    mail.MailAdapter().save_attachment("<a@x>", "", attachment_id="1.12")
    assert seen["argv"][3:5] == ("", "1.12")


def test_save_script_enforces_the_cap_and_the_ambiguous_name():
    # the cap is checked in-script because `file size` is only knowable from Mail, and
    # the fetch above means "look, then save" costs a second Apple Event every time.
    assert "over the cap" in mail_attachments._SAVE_ATTACHMENT
    assert "pass attachment_id instead" in mail_attachments._SAVE_ATTACHMENT
    # ...and the save is the LAST thing the script does, after both refusals
    script = mail_attachments._SAVE_ATTACHMENT
    assert script.index("over the cap") < script.index("save found in")


# --- #85: statistics -----------------------------------------------------------------


def _row(sender="a@x", url=_BOX, read=1, flagged=0, doc=0, when=None):
    return {
        "sender": sender,
        "mailbox_url": url,
        "is_read": read,
        "flagged": flagged,
        "has_document": doc,
        "date_received": when if when is not None else int(time.time()),
    }


def test_stats_reports_a_compact_aggregate(monkeypatch):
    rows = (
        [_row("boss@corp.com", read=0) for _ in range(3)]
        + [_row("news@corp.com", doc=1, flagged=1) for _ in range(2)]
        + [_row("solo@corp.com", url=f"imap://{_ACCT}/Archive")]
    )
    monkeypatch.setattr(mail_index, "query_stats_rows", lambda since, acct: rows)
    out = mail.MailAdapter().stats(days=10)
    assert out["messages"] == 6
    assert out["unread"] == 3
    assert out["read_ratio"] == 0.5
    assert out["flagged"] == 2
    assert out["with_attachments"] == 2
    assert out["per_day"] == 0.6
    assert out["top_senders"][0] == {"address": "boss@corp.com", "messages": 3}
    assert out["plane"] == "envelope-index"
    boxes = {b["mailbox"]: b["messages"] for b in out["top_mailboxes"]}
    assert boxes == {"INBOX": 5, "Archive": 1}
    assert out["top_mailboxes"][0]["account"] == _ACCT


def test_stats_top_lists_are_token_bounded(monkeypatch):
    rows = [_row(f"s{i}@x", url=f"imap://{_ACCT}/box{i}") for i in range(50)]
    monkeypatch.setattr(mail_index, "query_stats_rows", lambda since, acct: rows)
    out = mail.MailAdapter().stats()
    assert len(out["top_senders"]) == 10
    assert len(out["top_mailboxes"]) == 10


def test_stats_empty_window_reports_none_not_a_fake_ratio(monkeypatch):
    monkeypatch.setattr(mail_index, "query_stats_rows", lambda since, acct: [])
    out = mail.MailAdapter().stats()
    assert out["messages"] == 0
    assert out["read_ratio"] is None  # not 1.0 — nothing was read, nothing arrived
    assert out["busiest_day"] is None


def test_stats_window_is_applied_and_the_account_passed_through(monkeypatch):
    seen = {}

    def fake(since, acct):
        seen["since"], seen["acct"] = since, acct
        return []

    monkeypatch.setattr(mail_index, "query_stats_rows", fake)
    mail.MailAdapter().stats(days=7, account=_ACCT)
    assert abs(seen["since"] - (int(time.time()) - 7 * 86400)) < 5
    assert seen["acct"] == _ACCT


def test_stats_rejects_a_nonpositive_window():
    with pytest.raises(ValueError, match="positive window"):
        mail.MailAdapter().stats(days=0)


def test_stats_query_counts_distinct_messages_not_rows():
    """The margin that made mail_overview wrong: Travel reported 4,423 rows against
    1,252 distinct messages. Stats over rows would be wrong by exactly that much."""
    sql, params = mail_index.build_stats_query(0)
    assert "ROW_NUMBER() OVER (PARTITION BY COALESCE(NULLIF(gd.message_id_header" in sql
    assert "WHERE rn = 1" in sql
    assert "m.deleted = 0" in sql
    assert params == [0]


def test_stats_flags_aggregate_over_the_duplicate_group_like_overview_does():
    """Device-verified 2026-08-05: reading `read` off whichever row won the dedup gave
    449 unread on a 30-day window where mail_overview's rule gives 451. Two tools
    reading one store must not disagree — unread iff EVERY copy is unread, flagged /
    has-attachment iff ANY copy is."""
    sql, _ = mail_index.build_stats_query(0)
    assert "MIN(m.read) OVER (PARTITION BY" in sql
    assert "MAX(m.flagged) OVER (PARTITION BY" in sql
    assert "MAX(CASE WHEN EXISTS" in sql


def test_stats_query_anchors_the_account_to_the_url_segment():
    sql, params = mail_index.build_stats_query(0, _ACCT)
    assert "'%://' || ? || '/%'" in sql  # not an unanchored %uuid% over the whole url
    assert params == [0, _ACCT]


# --- #85: export ---------------------------------------------------------------------


def _located(mid, rowid, fidelity="full"):
    return mail_recover.Target(id=mid, folder="", rowid=rowid, fidelity=fidelity)


def test_export_writes_eml_files_and_reports_absent_ids(root, monkeypatch):
    monkeypatch.setattr(
        mail_recover,
        "locate",
        lambda targets: [_located("a@x", 1), _located("b@x", None, "absent")],
    )
    monkeypatch.setattr(
        mail_recover, "read_payloads", lambda t: {"a@x": b"From: x\r\n"}
    )
    out = mail.MailAdapter().export("<a@x>,<b@x>", "archive")
    assert out["written"] == 1
    assert out["results"][0] == {
        "id": "a@x",
        "status": "written",
        "path": str(root / "archive" / "a@x.eml"),
        "bytes": 9,
        "fidelity": "full",
    }
    assert out["results"][1] == {"id": "b@x", "status": "absent", "fidelity": "absent"}
    assert (root / "archive" / "a@x.eml").read_bytes() == b"From: x\r\n"


def test_export_reports_partial_fidelity_rather_than_pretending(root, monkeypatch):
    """62.5% of local messages are headers-only. The .eml is real but truncated, and
    saying so is the difference between an archive and a false one."""
    monkeypatch.setattr(
        mail_recover, "locate", lambda t: [_located("a@x", 1, "partial")]
    )
    monkeypatch.setattr(mail_recover, "read_payloads", lambda t: {"a@x": b"From: x"})
    out = mail.MailAdapter().export("<a@x>", "archive")
    assert out["results"][0]["fidelity"] == "partial"


def test_export_filename_is_derived_from_a_hostile_id(root, monkeypatch):
    hostile = "../../etc/passwd"
    monkeypatch.setattr(mail_recover, "locate", lambda t: [_located(hostile, 1)])
    monkeypatch.setattr(mail_recover, "read_payloads", lambda t: {hostile: b"x"})
    out = mail.MailAdapter().export(hostile, "archive")
    assert out["results"][0]["path"] == str(root / "archive" / "passwd.eml")


def test_export_caps_the_batch(root):
    with pytest.raises(BatchTooLarge):
        mail.MailAdapter().export(",".join(f"<m{i}@x>" for i in range(30)), "archive")


def test_export_rejects_an_empty_batch(root):
    with pytest.raises(ValueError, match="at least one"):
        mail.MailAdapter().export("", "archive")


def test_export_never_launches_mail(root, monkeypatch):
    monkeypatch.setattr(
        runtime,
        "run_osascript",
        lambda *a, **k: pytest.fail("export is a read at rest — it must not run Mail"),
    )
    monkeypatch.setattr(mail_recover, "locate", lambda t: [_located("a@x", 1)])
    monkeypatch.setattr(mail_recover, "read_payloads", lambda t: {"a@x": b"x"})
    mail.MailAdapter().export("<a@x>", "archive")
