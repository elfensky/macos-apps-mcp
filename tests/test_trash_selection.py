"""#556: synthetic index candidates and refusal before any recoverable/native act."""

from unittest.mock import Mock

import pytest

from macos_apps_mcp import runtime
from macos_apps_mcp.adapters import mail_index, mail_recover
from macos_apps_mcp.adapters.mail import MailAdapter
from macos_apps_mcp.errors import (
    AmbiguousTarget,
    NativeError,
    SchemaDrift,
    WriteRefused,
)
from tests.envelope import ACCT_A, ACCT_B

SOURCE = f"imap://{ACCT_A}/Archive"
TRASH = f"imap://{ACCT_A}/[Gmail]/Trash"


@pytest.mark.parametrize("reverse", [False, True])
def test_exact_aliases_choose_one_original_url(blank_envelope, reverse):
    urls = [TRASH, f"imap://{ACCT_A}/%5BGmail%5D/Trash"]
    for url in reversed(urls) if reverse else urls:
        blank_envelope.add_mailbox(url)
    blank_envelope.add_mailbox(f"imap://{ACCT_B}/Bin")
    # The existing deterministic ordering keeps the shorter original URL.
    assert mail_index.query_trash_url(ACCT_A) == TRASH


def test_no_candidate_does_not_use_another_accounts_trash(blank_envelope):
    blank_envelope.add_mailbox(SOURCE)
    blank_envelope.add_mailbox(f"imap://{ACCT_B}/Trash")
    assert mail_index.query_trash_url(ACCT_A) is None


@pytest.mark.parametrize("nested", ["Archive/2019/Bin", "Trash/Bin"])
def test_nested_trash_names_remain_distinct_candidates(blank_envelope, nested):
    blank_envelope.add_mailbox(f"imap://{ACCT_A}/Trash")
    blank_envelope.add_mailbox(f"imap://{ACCT_A}/{nested}")
    with pytest.raises(AmbiguousTarget):
        mail_index.query_trash_url(ACCT_A)


@pytest.mark.parametrize("failure", [NativeError("unreadable"), SchemaDrift("schema")])
def test_index_errors_propagate_unchanged(monkeypatch, failure):
    monkeypatch.setattr(mail_index, "_dict_rows", Mock(side_effect=failure))
    with pytest.raises(type(failure)) as err:
        mail_index.query_trash_url(ACCT_A)
    assert err.value is failure


def test_ambiguity_details_are_bounded_and_control_free(blank_envelope):
    for i in range(30):
        blank_envelope.add_mailbox(
            f"imap://{ACCT_A}/folder-{i}-" + "x" * 1000 + "%0A%1B/Trash"
        )
    with pytest.raises(AmbiguousTarget) as err:
        mail_index.query_trash_url(ACCT_A)
    reason = str(err.value)
    assert "30" in reason
    assert "truncated" in reason
    assert len(reason) < 2200
    assert not any(c in reason for c in "\n\r\x1b")
    assert "Nothing was changed by this call" in reason


@pytest.mark.parametrize("method", ["trash_mail", "dedupe_batch"])
@pytest.mark.parametrize("dry_run", [True, False])
def test_ambiguous_adapter_refuses_before_native_backup_or_plan(
    blank_envelope, monkeypatch, method, dry_run
):
    blank_envelope.add_mailbox(SOURCE)
    blank_envelope.add_mailbox(TRASH)
    blank_envelope.add_mailbox(f"imap://{ACCT_A}/Prullenbak")
    native = Mock(side_effect=AssertionError("native call before refusal"))
    plane = Mock(side_effect=AssertionError("recovery plane before refusal"))
    monkeypatch.setattr(runtime, "run_osascript", native)
    monkeypatch.setattr(mail_recover, "recoverable", plane)
    with pytest.raises(AmbiguousTarget):
        getattr(MailAdapter(), method)(["synthetic@example.invalid"], SOURCE, dry_run)
    native.assert_not_called()
    plane.assert_not_called()


def _receipt(monkeypatch, op, dest=TRASH):
    rec = {"op": op, "destination": dest}
    target = mail_recover.Target(
        id="synthetic@example.invalid", folder=SOURCE, account=ACCT_A
    )
    monkeypatch.setattr(mail_recover, "undo_plan", lambda rid: (rec, [target]))
    return rec


@pytest.mark.parametrize("op", ["trash", "dedupe"])
@pytest.mark.parametrize("dry_run", [True, False])
@pytest.mark.parametrize("state", ["ambiguous", "absent", "different", "case"])
def test_undo_refuses_an_unproven_recorded_destination(
    blank_envelope, monkeypatch, op, dry_run, state
):
    blank_envelope.add_mailbox(SOURCE)
    if state == "ambiguous":
        blank_envelope.add_mailbox(TRASH)
        blank_envelope.add_mailbox(f"imap://{ACCT_A}/Papierkorb")
    elif state == "different":
        blank_envelope.add_mailbox(f"imap://{ACCT_A}/Corbeille")
    elif state == "case":
        blank_envelope.add_mailbox(f"imap://{ACCT_A}/[Gmail]/trash")
    rec = _receipt(monkeypatch, op)
    adapter = MailAdapter()
    move = Mock(side_effect=AssertionError("undo must refuse before move"))
    monkeypatch.setattr(adapter, "move_mail", move)
    with pytest.raises(WriteRefused) as err:
        adapter.undo("old-receipt", dry_run=dry_run)
    reason = str(err.value)
    assert "Nothing was changed by this call" in reason
    assert "mail_search" in reason and "by hand" in reason
    assert SOURCE in reason
    assert "move_mail" not in reason
    assert reason.count("Do not retry unchanged.") == 1
    assert rec["destination"] == TRASH
    move.assert_not_called()


@pytest.mark.parametrize("op", ["trash", "dedupe"])
@pytest.mark.parametrize("dry_run", [True, False])
def test_undo_accepts_equal_decoded_alias_without_replacing_receipt(
    blank_envelope, monkeypatch, op, dry_run
):
    alias = f"imap://{ACCT_A}/%5BGmail%5D/Trash"
    blank_envelope.add_mailbox(TRASH)
    blank_envelope.add_mailbox(alias)
    # Other accounts are not part of this receipt's guard.
    blank_envelope.add_mailbox(f"imap://{ACCT_B}/Trash")
    blank_envelope.add_mailbox(f"imap://{ACCT_B}/Papierkorb")
    rec = _receipt(monkeypatch, op, alias)
    assert mail_index.query_trash_url(ACCT_A) != rec["destination"]
    adapter = MailAdapter()
    result = {"receipt": "undo-receipt"}
    move = Mock(return_value=result)
    monkeypatch.setattr(adapter, "move_mail", move)
    assert adapter.undo("old-receipt", dry_run=dry_run) is result
    move.assert_called_once_with(
        ["synthetic@example.invalid"], alias, SOURCE, dry_run=dry_run
    )
    assert rec["destination"] == alias


@pytest.mark.parametrize("dry_run", [True, False])
def test_move_receipts_never_resolve_trash(blank_envelope, monkeypatch, dry_run):
    _receipt(monkeypatch, "move")
    selector = Mock(side_effect=AssertionError("move receipts need no selector"))
    monkeypatch.setattr(mail_index, "query_trash_url", selector)
    adapter = MailAdapter()
    move = Mock(return_value={"receipt": "undo-receipt"})
    monkeypatch.setattr(adapter, "move_mail", move)
    assert adapter.undo("old-receipt", dry_run=dry_run) == move.return_value
    selector.assert_not_called()
    move.assert_called_once_with(
        ["synthetic@example.invalid"], TRASH, SOURCE, dry_run=dry_run
    )


@pytest.mark.parametrize("dest", ["trash", TRASH])
def test_existing_undo_guards_run_before_trash_selector(monkeypatch, dest):
    _receipt(monkeypatch, "trash", dest)
    monkeypatch.setattr(mail_index, "is_label_mailbox", lambda url: True)
    selector = Mock(side_effect=AssertionError("existing guard must refuse first"))
    monkeypatch.setattr(mail_index, "query_trash_url", selector)
    with pytest.raises(WriteRefused):
        MailAdapter().undo("old-receipt")
    selector.assert_not_called()
