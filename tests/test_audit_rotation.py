"""#575: the audit and usage readers see both retained files after a rotation, and a
recoverable-mail op stops before acting when its plan record was not written."""

from __future__ import annotations

import json

import pytest

from macos_apps_mcp import audit
from macos_apps_mcp.adapters import mail_index, mail_recover
from macos_apps_mcp.errors import WriteRefused

ACCT = "AAAAAAAA-1111-2222-3333-444444444444"
BOX = f"imap://{ACCT}/INBOX"


@pytest.fixture(autouse=True)
def _own_state(tmp_path, monkeypatch):
    # conftest's state folder lives for the whole session: keep these logs out of it
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


def _write(name: str, records: list[dict]) -> None:
    path = audit.state_dir() / name
    path.write_text("".join(json.dumps(r) + "\n" for r in records) + "not json\n")


def test_find_receipt_joins_a_plan_in_the_rotated_file_to_a_done_in_the_live_one():
    _write(
        "audit.jsonl.1",
        [{"tool": "mail_recover", "phase": "plan", "receipt": "r1", "targets": []}],
    )
    _write(
        "audit.jsonl",
        [
            {
                "tool": "mail_recover",
                "phase": "done",
                "receipt": "r1",
                "results": {"a": "ok"},
            }
        ],
    )
    plan, outcomes = mail_recover.find_receipt("r1")
    assert plan["phase"] == "plan"
    assert outcomes == {"a": "ok"}


def test_audit_read_spans_both_files_newest_first_within_limit():
    _write("audit.jsonl.1", [{"tool": "t", "n": 1}, {"tool": "t", "n": 2}])
    _write("audit.jsonl", [{"tool": "t", "n": 3}, {"tool": "t", "n": 4}])
    assert [r["n"] for r in audit.audit_read()] == [4, 3, 2, 1]
    assert [r["n"] for r in audit.audit_read(limit=3)] == [4, 3, 2]


def test_usage_read_counts_both_files():
    _write("usage.jsonl.1", [{"tool": "mail", "ts": "2026-01-01T00:00:00"}])
    _write("usage.jsonl", [{"tool": "mail", "ts": "2026-02-01T00:00:00"}])
    assert audit.usage_read() == {
        "mail": {
            "count": 2,
            "first": "2026-01-01T00:00:00",
            "last": "2026-02-01T00:00:00",
        }
    }


def test_a_failed_plan_write_stops_before_act(tmp_path, monkeypatch):
    monkeypatch.setattr(mail_index, "mail_root", lambda: tmp_path / "Mail")
    monkeypatch.setattr(mail_index, "query_message_locations", lambda ids: [])
    monkeypatch.setattr(mail_recover, "audit_write", lambda rec: False)
    ran = []
    target = mail_recover.Target(id="a@x", folder=BOX, account=ACCT)
    with pytest.raises(WriteRefused, match="nothing was moved"):
        mail_recover.recoverable(
            "move",
            [target],
            lambda ts: ran.append(ts),
            destination=f"imap://{ACCT}/Archive",
            backup=False,
        )
    assert ran == []
