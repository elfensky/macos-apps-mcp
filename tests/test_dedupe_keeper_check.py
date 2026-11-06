"""#577: a native failure in one cross-account batch still runs the keeper check.

All mailbox rows and message metadata are synthetic SQLite data. Native actions are
faked; the production planner and batch loop run unchanged.
"""

import pytest

from macos_apps_mcp import dedupe
from macos_apps_mcp.errors import NativeTimeout
from tests.envelope import ACCT_A, ACCT_B
from tests.test_dedupe_preflight import KEEP, _adapter, _args, _seed


@pytest.mark.parametrize(
    "failure",
    [
        NativeTimeout("timed out; receipt R-2 written, outcome unknown"),
        # a refused argument is no NativeError: it must not skip the check either
        ValueError("refused; receipt R-2 written before the refusal"),
    ],
)
def test_failure_in_second_batch_still_verifies_keepers(
    blank_envelope, monkeypatch, capsys, failure
):
    _seed(blank_envelope, "cross", monkeypatch)
    for acct in (ACCT_A, ACCT_B):
        blank_envelope.add_mailbox(f"imap://{acct}/Trash")
    adapter = _adapter(monkeypatch)
    calls = []

    def act(ids, url, *, dry_run):
        calls.append(url)
        if len(calls) == 2:
            raise failure
        return {"succeeded": len(ids), "receipt": f"R-{len(calls)}"}

    adapter.trash_mail.side_effect = act

    with pytest.raises(SystemExit) as err:
        dedupe.dedupe_mail(_args("cross", True))
    assert err.value.code == 2
    assert len(calls) == 2  # the third batch never ran
    adapter.presence.assert_called_once()
    ids, url = adapter.presence.call_args.args
    assert url == f"imap://{KEEP}/Archive" and len(ids) == 3
    out = capsys.readouterr()
    assert "receipt R-2 written" in out.err
    assert "Traceback" not in out.err
    assert "all 3 keeper copies still present" in out.out
