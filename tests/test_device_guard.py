"""The device-suite guard (tests/device/guard.py) and its wiring. No daemon used."""

from __future__ import annotations

import ast
import asyncio
import tomllib
from pathlib import Path

import pytest

from macos_apps_mcp import registry
from tests.device.guard import TEST_CONTAINER, Guard, Owned, refusal

ROOT = Path(__file__).resolve().parents[1]
MARK = "macos-apps-mcp device 20261106-120000"
ME = "me@example.invalid"


def _owned(**kw) -> Owned:
    o = Owned(marker=MARK, address=ME)
    o.containers.add("cal-test")
    o.items.add("ev-mine")
    o.sent.add("<sent@x>")
    o.mail.update({"<sent@x>", "<fwd@x>"})
    o.receipts.add("r-mine")
    o.drafts.add("d-mine")
    for k, v in kw.items():
        setattr(o, k, v)
    return o


def _tier(tool: str) -> str | None:
    rec = registry.TOOLS.get(tool)
    return rec.tier if rec else None


def _decide(tool: str, **args) -> str | None:
    return refusal(tool, args, _tier(tool), _owned())


ALLOWED = [
    ("doctor", {}),
    ("mail_search", {"subject": "anything"}),
    ("create_event", {"title": MARK, "calendar": "cal-test"}),
    ("create_reminder", {"title": MARK + " x", "list_name": "cal-test"}),
    ("create_reminder_list", {"name": TEST_CONTAINER}),
    ("update_event", {"id": "ev-mine"}),
    ("update_event", {"id": "ev-mine", "calendar": "cal-test"}),
    ("doctor", {"request": False}),
    ("delete_reminder", {"id": "ev-mine", "dry_run": False}),
    ("send_mail", {"to": ME, "subject": MARK, "body": "b", "from_address": ME}),
    ("forward_mail", {"message_id": "<sent@x>", "mailbox": "m", "to": ME}),
    ("trash_mail", {"ids": "<sent@x>, <fwd@x>", "mailbox": "m"}),
    ("mail_undo", {"receipt": "r-mine"}),
    ("delete_draft", {"id": "d-mine"}),
]

REFUSED = [
    ("create_event", {"title": MARK, "calendar": "cal-family"}),
    ("create_event", {"title": "lunch", "calendar": "cal-test"}),
    ("create_reminder_list", {"name": "Groceries"}),
    ("update_event", {"id": "ev-not-mine"}),
    # an owned item must not move into a real calendar or list
    ("update_event", {"id": "ev-mine", "calendar": "cal-family"}),
    ("update_reminder", {"id": "ev-mine", "list_name": "Groceries"}),
    # read tier, but with a side effect
    ("doctor", {"request": True}),
    ("mail_index_bodies", {}),
    ("mail_index_ids", {}),
    ("delete_event", {"id": "ev-not-mine"}),
    ("update_reminder", {"id": "ev-not-mine"}),
    ("send_mail", {"to": "other@example.invalid", "subject": MARK}),
    ("send_mail", {"to": ME, "subject": MARK, "cc": "other@example.invalid"}),
    ("send_mail", {"to": ME, "subject": MARK, "bcc": "other@example.invalid"}),
    ("send_mail", {"to": ME, "subject": "no marker"}),
    ("send_mail", {"to": ME, "subject": MARK, "draft_id": "d-mine"}),
    ("forward_mail", {"message_id": "<fwd@x>", "mailbox": "m", "to": ME}),
    ("forward_mail", {"message_id": "<sent@x>", "mailbox": "m", "to": "o@x"}),
    ("trash_mail", {"ids": "<sent@x>,<other@x>", "mailbox": "m"}),
    ("trash_mail", {"ids": "", "mailbox": "m"}),
    ("mail_undo", {"receipt": "r-other"}),
    ("delete_draft", {"id": "d-other"}),
    ("delete_note", {"id": "x"}),
    ("move_mail", {"ids": "<sent@x>"}),
    ("no_such_tool", {}),
]


@pytest.mark.parametrize(("tool", "args"), ALLOWED)
def test_guard_allows(tool, args):
    assert _decide(tool, **args) is None


@pytest.mark.parametrize(("tool", "args"), REFUSED)
def test_guard_refuses(tool, args):
    assert _decide(tool, **args)


def test_a_send_without_a_configured_address_is_refused():
    o = _owned(address=None)
    assert refusal("send_mail", {"to": None, "subject": MARK}, "send", o)


def test_every_registered_write_without_a_rule_is_refused():
    ruled = {t for t, _ in ALLOWED}
    for name, rec in registry.TOOLS.items():
        if rec.is_write and name not in ruled:
            assert refusal(name, {}, rec.tier, _owned()), name


def test_guard_call_raises_before_reaching_a_client():
    g = Guard(Path("/nonexistent.sock"), MARK, ME)  # no client: a call would crash

    async def go():
        await g.call("delete_note", id="x")

    with pytest.raises(AssertionError, match="delete_note"):
        asyncio.run(go())


def test_guard_tracks_created_and_changed_ids():
    g = Guard(Path("/nonexistent.sock"), MARK, ME)
    g._record("create_event", {"id": "a"})
    g._record("update_event", {"id": "b"})
    g._record("trash_mail", {"receipt": "r1"})
    g._record("create_reminder_list", {"id": "L"})
    assert g.owned.items == {"a", "b"}
    assert g.owned.receipts == {"r1"} and g.owned.containers == {"L"}


def test_guard_adopts_only_rows_with_the_marker():
    g = Guard(Path("/nonexistent.sock"), MARK, ME)
    rows = [{"id": "m1", "summary": f"Fwd: {MARK}"}, {"id": "m2", "summary": "other"}]
    assert [r["id"] for r in g.adopt_mail(rows, sent=True)] == ["m1"]
    assert g.owned.mail == {"m1"} and g.owned.sent == {"m1"}
    assert [r["id"] for r in g.adopt_drafts(rows)] == ["m1"]
    g.adopt_container({"id": "c1", "summary": "Family"})
    assert not g.owned.containers


def test_every_device_module_wears_the_device_marker():
    files = sorted((ROOT / "tests" / "device").glob("test_*.py"))
    assert files
    for f in files:
        tree = ast.parse(f.read_text(encoding="utf-8"))
        marks = [
            ast.unparse(n.value)
            for n in tree.body
            if isinstance(n, ast.Assign)
            and any(getattr(t, "id", None) == "pytestmark" for t in n.targets)
        ]
        assert marks == ["pytest.mark.device"], f.name


def test_the_default_run_deselects_device_and_integration():
    with (ROOT / "pyproject.toml").open("rb") as fh:
        opts = tomllib.load(fh)["tool"]["pytest"]["ini_options"]
    assert opts["addopts"] == "-m 'not integration and not device'"
    assert any(m.startswith("device:") for m in opts["markers"])
