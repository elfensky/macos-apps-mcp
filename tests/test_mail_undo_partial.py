"""#578: undo replays a target that left its source in part.

The act's per-id status text stays display-only; the DONE record's ``left_source``
says whether each target left its source. All Mail state is the FakeMail model.
"""

from __future__ import annotations

from datetime import datetime

from macos_apps_mcp.adapters import mail_recover
from macos_apps_mcp.adapters.mail import MailAdapter
from macos_apps_mcp.audit import audit_read, audit_write
from tests._fakes import FakeMail
from tests.test_mail import (  # noqa: F401  (no_backup is a fixture)
    _ARCHIVE,
    _INBOX,
    _INBOX_BOX,
    _patch_run,
    no_backup,
)

ACCT = "AAAAAAAA-1111-2222-3333-444444444444"
BOX = f"imap://{ACCT}/INBOX"
ARCHIVE = f"imap://{ACCT}/Archive"
PARTIAL = "ERROR Mail got an error (1 of 2 copies moved)"


def _targets(*ids):
    return [mail_recover.Target(id=i, folder=BOX, account=ACCT) for i in ids]


def _done(receipt):
    return next(
        r
        for r in audit_read(limit=50)
        if r.get("receipt") == receipt and r.get("phase") == "done"
    )


def test_a_partial_target_is_replayed_and_its_text_is_unchanged():
    result = mail_recover.recoverable(
        "move",
        _targets("a@x", "b@x", "c@x"),
        lambda ts: {
            "a@x": mail_recover.Outcome(PARTIAL, mail_recover.LEFT),
            "b@x": "not-in-source",
            "c@x": "ERROR boom",
        },
        destination=ARCHIVE,
        backup=False,
    )
    assert [t["status"] for t in result["targets"]] == [
        PARTIAL,
        "not-in-source",
        "ERROR boom",
    ]
    done = _done(result["receipt"])
    assert done["results"]["a@x"] == PARTIAL
    assert done["left_source"] == {"a@x": "left", "b@x": "stayed", "c@x": "stayed"}
    _rec, targets = mail_recover.undo_plan(result["receipt"])
    assert [t.id for t in targets] == ["a@x"]


def test_ok_and_unknown_still_replay_with_the_new_field():
    result = mail_recover.recoverable(
        "move",
        _targets("a@x", "b@x", "c@x"),
        lambda ts: {"a@x": "ok", "b@x": "unknown"},  # c@x not answered
        destination=ARCHIVE,
        backup=False,
    )
    assert _done(result["receipt"])["left_source"] == {
        "a@x": "left",
        "b@x": "unknown",
        "c@x": "unknown",
    }
    _rec, targets = mail_recover.undo_plan(result["receipt"])
    assert [t.id for t in targets] == ["a@x", "b@x", "c@x"]


def test_an_old_receipt_without_the_field_keeps_todays_rule():
    rid = "20261106-000000-000000-000-move"
    ts = datetime.now().isoformat(timespec="seconds")
    base = {"ts": ts, "tool": "mail_recover", "op": "move", "receipt": rid}
    audit_write(
        base
        | {
            "phase": "plan",
            "destination": ARCHIVE,
            "backup_dir": None,
            "targets": [{"id": i, "folder": BOX, "status": "planned"} for i in "abcd"],
        }
    )
    results = {"a": "ok", "b": "unknown", "c": PARTIAL, "d": "not-in-source"}
    audit_write(base | {"phase": "done", "results": results})
    _rec, targets = mail_recover.undo_plan(rid)
    assert [t.id for t in targets] == ["a", "b"]


def test_move_mail_partial_duplicate_is_undoable(monkeypatch, no_backup):  # noqa: F811
    fake = FakeMail()
    nids = fake.seed(_INBOX_BOX, "a@x", "a@x")
    fake.survives.add(nids[1])  # one copy moves, the other stays in the source
    _patch_run(monkeypatch, fake)
    out = MailAdapter().move_mail("a@x", _INBOX, _ARCHIVE, dry_run=False)
    assert out["targets"][0]["status"].endswith("(1 of 2 copies moved)")
    assert _done(out["receipt"])["left_source"] == {"a@x": "left"}
    _rec, targets = mail_recover.undo_plan(out["receipt"])
    assert [t.id for t in targets] == ["a@x"]
