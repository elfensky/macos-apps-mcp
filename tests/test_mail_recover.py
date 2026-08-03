"""#159: the recoverable destructive plane — backup → log → act, receipts, undo.

Unit-tested through the module's own seams: ``mail_index.query_message_locations`` and
``mail_root`` are the sqlite/disk boundary, and the ``act`` callable is the AppleScript
boundary. Nothing here launches Mail. The on-device half — that a move really moves,
that a cross-account move leaves ONE copy, that a backup ``.eml`` imports — is
``tests/test_integration.py``; per CLAUDE.md a green suite here proves nothing about
Mail's actual behaviour.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from macos_apps_mcp import audit
from macos_apps_mcp.adapters import mail_index, mail_recover
from macos_apps_mcp.errors import BatchTooLarge, NativeError

ACCT = "AAAAAAAA-1111-2222-3333-444444444444"
BOX = f"imap://{ACCT}/INBOX"
ARCHIVE = f"imap://{ACCT}/Archive"


def _emlx(body: bytes, *, plist: bytes = b"<plist>junk</plist>") -> bytes:
    """An .emlx as Mail writes it: byte-count line, payload, trailing plist."""
    return str(len(body)).encode() + b"\n" + body + plist


def _target(mid: str, folder: str = BOX) -> mail_recover.Target:
    return mail_recover.Target(id=mid, folder=folder, account=ACCT)


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A fake Mail store: ROWID-named .emlx files plus the index rows that point at
    them. Returns the root so a test can add/remove files."""
    root = tmp_path / "Mail"
    msgs = root / "V10" / ACCT / "INBOX.mbox" / "uuid" / "Data" / "Messages"
    msgs.mkdir(parents=True)
    (msgs / "10.emlx").write_bytes(_emlx(b"Subject: full\r\n\r\nbody one"))
    (msgs / "11.partial.emlx").write_bytes(_emlx(b"Subject: partial\r\n\r\n"))
    monkeypatch.setattr(mail_index, "mail_root", lambda: root)
    monkeypatch.setattr(
        mail_index,
        "query_message_locations",
        lambda ids: [
            {"message_id": "<a@x>", "rowid": 10, "mailbox_url": BOX},
            {"message_id": "<b@x>", "rowid": 11, "mailbox_url": BOX},
            # a second copy of a@x, filed elsewhere — locate must not pick this one
            {"message_id": "<a@x>", "rowid": 99, "mailbox_url": ARCHIVE},
        ],
    )
    return root


# --- .emlx framing -------------------------------------------------------------------


def test_emlx_payload_keeps_exactly_the_declared_bytes():
    # The count line is a byte count, and Mail appends its own plist AFTER the message.
    # Both ends have to be cut or the backup is not a valid .eml.
    assert mail_index.emlx_payload(_emlx(b"Subject: x\r\n\r\nhi")) == (
        b"Subject: x\r\n\r\nhi"
    )


@pytest.mark.parametrize("raw", [b"", b"no newline", b"notanumber\nbody", b"-1\nbody"])
def test_emlx_payload_refuses_malformed_framing(raw):
    assert mail_index.emlx_payload(raw) == b""


# --- the cap -------------------------------------------------------------------------


def test_batch_cap_is_hard_and_rejects_before_anything_runs():
    with pytest.raises(BatchTooLarge) as e:
        mail_recover.check_batch([_target(f"m{i}@x") for i in range(26)])
    # the message must say the cap is not overridable — a caller told to "pass
    # max=N" would, and the recovery path is bounded by how many files we copy first
    assert "not overridable" in str(e.value)


def test_empty_batch_is_a_caller_bug_not_a_quiet_success():
    with pytest.raises(ValueError):
        mail_recover.check_batch([])


# --- locate --------------------------------------------------------------------------


def test_locate_picks_the_row_in_the_targets_own_mailbox(store):
    [t] = mail_recover.locate([_target("a@x")])
    assert (t.rowid, t.fidelity) == (10, "full")


def test_locate_stamps_a_headers_only_message_partial(store):
    # 62.5% of local messages are .partial.emlx on a real Mac — the fidelity stamp is
    # what makes a backup honest rather than merely present.
    [t] = mail_recover.locate([_target("b@x")])
    assert (t.rowid, t.fidelity) == (11, "partial")


def test_locate_stamps_an_unknown_message_absent_instead_of_raising(store):
    # Refusing the whole batch because one message was never downloaded would make the
    # common case unusable; `absent` is the signal the permanent-delete gate reads.
    [t] = mail_recover.locate([_target("nope@x")])
    assert (t.rowid, t.fidelity) == (None, "absent")


# --- backup → log → act --------------------------------------------------------------


def test_backup_lands_on_disk_before_the_act_runs(store):
    seen = {}

    def act(targets):
        # the ordering assertion: by the time AppleScript would run, the bytes are safe
        seen["backups"] = [
            (t.id, t.backup, Path(t.backup).read_bytes()) for t in targets if t.backup
        ]
        return {t.id: "ok" for t in targets}

    result = mail_recover.recoverable(
        "move", [_target("a@x")], act, destination=ARCHIVE
    )
    assert seen["backups"] == [
        (
            "a@x",
            result["targets"][0]["backup"],
            b"Subject: full\r\n\r\nbody one",
        )
    ]
    # plain .eml: Mail's byte-count line and trailing plist are gone, so the file is
    # importable by Mail.app and by anything else
    assert result["targets"][0]["backup"].endswith("/10.eml")


def test_receipt_lists_every_target_with_its_fidelity(store):
    result = mail_recover.recoverable(
        "move",
        [_target("a@x"), _target("b@x"), _target("nope@x")],
        lambda ts: {t.id: "ok" for t in ts},
        destination=ARCHIVE,
    )
    assert [(t["id"], t["fidelity"]) for t in result["targets"]] == [
        ("a@x", "full"),
        ("b@x", "partial"),
        ("nope@x", "absent"),
    ]
    assert result["partial_backups"] == ["b@x", "nope@x"]
    assert result["undo"] == f'mail_undo("{result["receipt"]}")'


def test_a_target_the_act_did_not_report_is_unknown_never_ok(store):
    # The reassuring-direction default is the bug this whole module exists to refuse.
    result = mail_recover.recoverable(
        "move",
        [_target("a@x"), _target("b@x")],
        lambda ts: {"a@x": "ok"},
        destination=ARCHIVE,
    )
    assert [t["status"] for t in result["targets"]] == ["ok", "unknown"]
    assert result["succeeded"] == 1
    assert "were NOT affected" in result["note"]


def test_backup_false_is_log_only_and_writes_no_files(store, tmp_path):
    # #140/#153 need this: both dedupes require byte-identity, so the surviving copy IS
    # the backup and copying files would be pure cost.
    result = mail_recover.recoverable(
        "move",
        [_target("a@x")],
        lambda ts: {t.id: "ok" for t in ts},
        destination=ARCHIVE,
        backup=False,
    )
    assert "backup_dir" not in result
    assert result["targets"][0].get("backup") is None
    assert not (audit.state_dir() / "backup" / "mail" / result["receipt"]).exists()


def test_an_unknown_op_cannot_mint_a_receipt(store):
    with pytest.raises(ValueError):
        mail_recover.recoverable("obliterate", [_target("a@x")], lambda ts: {})


# --- the action log ------------------------------------------------------------------


def _audit_lines() -> list[dict]:
    path = audit.state_dir() / "audit.jsonl"
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def test_the_plan_is_logged_before_acting_and_is_not_truncated(store):
    long_id = "x" * 400 + "@example.com"

    def act(targets):
        # logged BEFORE the act: if the process dies here, undo still has every source
        assert any(r.get("phase") == "plan" for r in _audit_lines())
        return {t.id: "ok" for t in targets}

    mail_recover.recoverable("move", [_target(long_id)], act, destination=ARCHIVE)
    plan = [r for r in _audit_lines() if r.get("phase") == "plan"][-1]
    # AuditMiddleware's _audit_args truncates every string at 200 chars, which is
    # exactly why the plane writes through audit_write instead of riding it
    assert plan["targets"][0]["id"] == long_id
    assert plan["destination"] == ARCHIVE
    done = [r for r in _audit_lines() if r.get("phase") == "done"][-1]
    assert done["results"] == {long_id: "ok"}


# --- the lossy gate ------------------------------------------------------------------


def test_permanent_delete_of_a_partial_bodied_message_refuses(store, monkeypatch):
    # 0.9.3's `delete` op registered early so the rule is written where it is enforced.
    monkeypatch.setattr(mail_recover, "OPS", mail_recover.OPS | {"delete"})
    monkeypatch.setattr(mail_recover, "PERMANENT_OPS", frozenset({"delete"}))
    ran = []
    with pytest.raises(NativeError) as e:
        mail_recover.recoverable("delete", [_target("b@x")], lambda ts: ran.append(ts))
    assert "allow_lossy" in str(e.value)
    assert ran == []  # refused before any Apple Event


def test_allow_lossy_lets_a_partial_delete_through(store, monkeypatch):
    monkeypatch.setattr(mail_recover, "OPS", mail_recover.OPS | {"delete"})
    monkeypatch.setattr(mail_recover, "PERMANENT_OPS", frozenset({"delete"}))
    result = mail_recover.recoverable(
        "delete", [_target("b@x")], lambda ts: {"b@x": "ok"}, allow_lossy=True
    )
    assert result["succeeded"] == 1


def test_a_move_never_needs_the_lossy_gate(store):
    # the server copy survives a move, so fidelity is reported but never blocking
    result = mail_recover.recoverable(
        "move", [_target("b@x")], lambda ts: {"b@x": "ok"}, destination=ARCHIVE
    )
    assert result["succeeded"] == 1


# --- preview -------------------------------------------------------------------------


def test_preview_is_the_one_dry_run_envelope():
    out = mail_recover.preview("move", [_target("a@x")], destination=ARCHIVE)
    assert out == {
        "dry_run": True,
        "op": "move",
        "count": 1,
        # no `fidelity`: a dry run never looks at disk, and stamping one would be a
        # claim nobody checked
        "would_affect": [
            {"id": "a@x", "folder": BOX, "account": ACCT, "status": "planned"}
        ],
        "destination": ARCHIVE,
    }
    assert mail_recover.is_preview(out)


def test_preview_writes_nothing(store):
    backups = audit.state_dir() / "backup" / "mail"
    before = sorted(backups.glob("*")) if backups.exists() else []
    log = audit.state_dir() / "audit.jsonl"
    log_before = log.stat().st_size if log.exists() else 0
    mail_recover.preview("move", [_target("a@x")], destination=ARCHIVE)
    # a dry run mints no receipt, copies no bytes and logs no action
    assert (sorted(backups.glob("*")) if backups.exists() else []) == before
    assert (log.stat().st_size if log.exists() else 0) == log_before


def test_is_preview_rejects_a_hand_rolled_dry_run():
    assert not mail_recover.is_preview({"dry_run": True, "would_delete": {}})
    assert not mail_recover.is_preview("nope")


# --- receipts and undo ---------------------------------------------------------------


def test_undo_plan_returns_each_targets_source_mailbox(store):
    result = mail_recover.recoverable(
        "move",
        [_target("a@x"), _target("b@x")],
        lambda ts: {"a@x": "ok", "b@x": "not-in-source"},
        destination=ARCHIVE,
    )
    rec, targets = mail_recover.undo_plan(result["receipt"])
    assert rec["destination"] == ARCHIVE
    # only what actually moved is replayed: "moving back" an untouched message would
    # report a fake success
    assert [t.id for t in targets] == ["a@x"]
    assert targets[0].folder == BOX


def test_undo_refuses_a_receipt_with_no_destination(store):
    result = mail_recover.recoverable(
        "move", [_target("a@x")], lambda ts: {"a@x": "ok"}
    )
    with pytest.raises(NativeError) as e:
        mail_recover.undo_plan(result["receipt"])
    # the honest answer points at the preserved bytes rather than pretending
    assert result["backup_dir"] in str(e.value)


def test_an_unknown_receipt_raises_rather_than_answering_empty():
    with pytest.raises(NativeError) as e:
        mail_recover.find_receipt("20200101-000000-move")
    assert "audit" in str(e.value)


def test_purge_backup_removes_the_receipts_directory(store):
    result = mail_recover.recoverable(
        "move", [_target("a@x")], lambda ts: {"a@x": "ok"}, destination=ARCHIVE
    )
    assert mail_recover.purge_backup(result["receipt"]) == 1
    assert mail_recover.purge_backup(result["receipt"]) == 0
