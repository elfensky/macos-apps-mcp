"""#556: both CLI plans must resolve every target account before the first batch.

All mailbox rows and message metadata are synthetic SQLite data. Bodies and native
actions are faked; the production planners and Trash selector run unchanged.
"""

from unittest.mock import Mock

import pytest

from macos_apps_mcp import dedupe
from macos_apps_mcp.adapters import mail_index
from tests.envelope import ACCT_A, ACCT_B

KEEP = "CCCCCCCC-1111-2222-3333-444444444444"
BOXES = [
    f"imap://{ACCT_A}/Archive",
    f"imap://{ACCT_A}/Other",
    f"imap://{ACCT_B}/Archive",
]


def _seed(env, kind, monkeypatch, *, eligible=True):
    keeper = env.add_mailbox(f"imap://{KEEP}/Archive")
    for i, url in enumerate(BOXES, 1):
        box = env.add_mailbox(url)
        env.execute(
            "INSERT INTO message_global_data(ROWID,message_id_header) VALUES(?,?)",
            (i, f"<m{i}@example.invalid>"),
        )
        for j, mailbox in enumerate((box, box if kind == "same" else keeper)):
            env.add_message(
                global_message_id=i,
                mailbox=mailbox,
                size=100 if eligible else 100 + j,
                date_sent=1000,
            )
    monkeypatch.setattr(
        mail_index,
        "body_fingerprints",
        lambda rowids: {r: "same-body" if eligible else str(r) for r in rowids},
    )


def _args(kind, execute):
    args = ["--cross-account", f"--keep-account={KEEP}"] if kind == "cross" else []
    return args + (["--execute"] if execute else [])


def _adapter(monkeypatch):
    adapter = Mock()
    adapter.dedupe_batch.return_value = {"succeeded": 1, "receipt": "synthetic"}
    adapter.trash_mail.return_value = {"succeeded": 1, "receipt": "synthetic"}
    adapter.presence.side_effect = lambda ids, url: dict.fromkeys(ids, "present")
    monkeypatch.setattr(dedupe, "MailAdapter", lambda: adapter)
    return adapter


@pytest.mark.parametrize("kind", ["same", "cross"])
@pytest.mark.parametrize("execute", [False, True])
@pytest.mark.parametrize("problem", ["ambiguous", "missing"])
def test_later_account_refuses_whole_pass_before_any_batch(
    blank_envelope, monkeypatch, capsys, kind, execute, problem
):
    _seed(blank_envelope, kind, monkeypatch)
    blank_envelope.add_mailbox(f"imap://{ACCT_A}/Trash")
    if problem == "ambiguous":
        blank_envelope.add_mailbox(f"imap://{ACCT_B}/Trash")
        blank_envelope.add_mailbox(f"imap://{ACCT_B}/%5BGmail%5D/Papierkorb")
    selector = Mock(wraps=mail_index.query_trash_url)
    monkeypatch.setattr(mail_index, "query_trash_url", selector)
    adapter = _adapter(monkeypatch)

    with pytest.raises(SystemExit) as err:
        dedupe.dedupe_mail(_args(kind, execute))
    assert err.value.code == 2
    out = capsys.readouterr()
    assert ACCT_B in out.err and "Trash" in out.err
    assert "Nothing was changed by this call" in out.err
    assert "Traceback" not in out.err
    assert "EXECUTING" not in out.out
    assert [c.args[0] for c in selector.call_args_list] == [ACCT_A, ACCT_B]
    adapter.dedupe_batch.assert_not_called()
    adapter.trash_mail.assert_not_called()
    adapter.presence.assert_not_called()


@pytest.mark.parametrize("kind", ["same", "cross"])
@pytest.mark.parametrize("execute", [False, True])
def test_preflight_resolves_distinct_target_accounts_before_first_batch(
    blank_envelope, monkeypatch, kind, execute
):
    _seed(blank_envelope, kind, monkeypatch)
    for acct in (ACCT_A, ACCT_B):
        blank_envelope.add_mailbox(f"imap://{acct}/Corbeille")
    # The keeper has ambiguous Trash, but none of its mailboxes is a target.
    for leaf in ("Trash", "Papierkorb"):
        blank_envelope.add_mailbox(f"imap://{KEEP}/{leaf}")
    selector = Mock(wraps=mail_index.query_trash_url)
    monkeypatch.setattr(mail_index, "query_trash_url", selector)
    adapter = _adapter(monkeypatch)

    def act(ids, url, *, dry_run):
        assert [c.args[0] for c in selector.call_args_list] == [ACCT_A, ACCT_B]
        assert dry_run is False
        return {"succeeded": len(ids), "receipt": "synthetic"}

    adapter.dedupe_batch.side_effect = act
    adapter.trash_mail.side_effect = act
    dedupe.dedupe_mail(_args(kind, execute))
    assert [c.args[0] for c in selector.call_args_list] == [ACCT_A, ACCT_B]
    action = adapter.dedupe_batch if kind == "same" else adapter.trash_mail
    assert action.call_count == (3 if execute else 0)
    if kind == "cross" and execute:
        adapter.presence.assert_called_once()


@pytest.mark.parametrize("kind", ["same", "cross"])
@pytest.mark.parametrize("execute", [False, True])
@pytest.mark.parametrize("empty", [False, True])
def test_no_planned_targets_need_no_trash_or_native_calls(
    blank_envelope, monkeypatch, kind, execute, empty
):
    if not empty:
        _seed(blank_envelope, kind, monkeypatch, eligible=False)
    selector = Mock(side_effect=AssertionError("no planned targets need Trash"))
    monkeypatch.setattr(mail_index, "query_trash_url", selector)
    adapter = _adapter(monkeypatch)
    dedupe.dedupe_mail(_args(kind, execute))
    selector.assert_not_called()
    adapter.dedupe_batch.assert_not_called()
    adapter.trash_mail.assert_not_called()
    adapter.presence.assert_not_called()


@pytest.mark.parametrize("kind", ["same", "cross"])
@pytest.mark.parametrize("execute", [False, True])
def test_mailbox_filter_excludes_accounts_without_planned_targets(
    blank_envelope, monkeypatch, kind, execute
):
    _seed(blank_envelope, kind, monkeypatch)
    blank_envelope.add_mailbox(f"imap://{ACCT_A}/Trash")
    selector = Mock(wraps=mail_index.query_trash_url)
    monkeypatch.setattr(mail_index, "query_trash_url", selector)
    adapter = _adapter(monkeypatch)
    dedupe.dedupe_mail(_args(kind, execute) + [f"--mailbox={BOXES[0]}"])
    selector.assert_called_once_with(ACCT_A)
    action = adapter.dedupe_batch if kind == "same" else adapter.trash_mail
    assert action.call_count == (1 if execute else 0)


@pytest.mark.parametrize("execute", [False, True])
def test_cross_account_limit_precedes_preflight(blank_envelope, monkeypatch, execute):
    _seed(blank_envelope, "cross", monkeypatch)
    blank_envelope.add_mailbox(f"imap://{ACCT_A}/Trash")
    selector = Mock(wraps=mail_index.query_trash_url)
    monkeypatch.setattr(mail_index, "query_trash_url", selector)
    adapter = _adapter(monkeypatch)
    dedupe.dedupe_mail(_args("cross", execute) + ["--limit=1"])
    selector.assert_called_once_with(ACCT_A)
    assert adapter.trash_mail.call_count == (1 if execute else 0)
