"""#573, #575 and #578 on ONE marker mail of this run, sent to the runner's own address.

At most one send and one forward for each run. The only messages written are this
run's marker mail and its forward. The cleanup fixture moves every copy (Inbox, Sent)
to Trash and deletes the exact Drafts copy, also after a failure. Subjects, senders
and bodies of other mail are never shown.
"""

from __future__ import annotations

import time
from urllib.parse import unquote

import pytest

pytestmark = pytest.mark.device

_TRASH = ("trash", "deleted", "prullenmand")


def _leaf(folder: str | None) -> str:
    return unquote(folder or "").rstrip("/").split("/")[-1].lower()


def _rows(data) -> list[dict]:
    rows = data.get("results") if isinstance(data, dict) else None
    return [r for r in rows or [] if isinstance(r, dict)]


def _copies(guard, **kw) -> list[dict]:
    """This run's marker copies only: the Guard keeps the rows that carry the marker."""
    err, res, _text, _ = guard.run("mail_search", subject=guard.marker, limit=25, **kw)
    return [] if err else guard.adopt_mail(_rows(res))


def _wait(guard, want, tries: int, pause: float, **kw) -> list[dict]:
    """Bounded polls of the index (sqlite, no Apple Event) until ``want(rows)``."""
    rows: list[dict] = []
    for _ in range(tries):
        rows = _copies(guard, **kw)
        if want(rows):
            break
        time.sleep(pause)
    return rows


def _inbox(rows) -> list[dict]:
    return [x for x in rows if _leaf(x.get("folder")) == "inbox"]


@pytest.fixture
def mail_run(guard, sender):
    state = {"sent": False}
    yield state
    if not state["sent"]:
        return
    seen, moved, failed, in_trash = set(), 0, 0, 0
    for x in _copies(guard) + _copies(guard, mailbox="sent"):
        key = (x["id"], x.get("folder"))
        if key in seen:
            continue
        seen.add(key)
        if any(t in _leaf(x.get("folder")) for t in _TRASH):
            in_trash += 1
            continue
        err, res, _t, _ = guard.run(
            "trash_mail", ids=x["id"], mailbox=x["folder"], dry_run=False
        )
        ok = not err and (res or {}).get("succeeded") == 1
        moved, failed = moved + ok, failed + (not ok)
    time.sleep(20)  # Mail's autosave of an outgoing message lands late (#133)
    err, res, _t, _ = guard.run("drafts")
    drafts = [] if err else guard.adopt_drafts(_rows(res))
    draft_errors = sum(
        guard.run("delete_draft", id=d["id"], dry_run=False)[0] for d in drafts
    )
    time.sleep(120)  # a Gmail-backed account can put a moved copy back
    stray = len(_inbox(_copies(guard)))
    ok = failed == 0 and draft_errors == 0 and stray == 0
    assert ok, (
        f"cleanup: moved={moved} in_trash={in_trash} failed={failed} "
        f"drafts={len(drafts)} draft_errors={draft_errors} inbox_after_2min={stray}"
    )


def _own_preview(res, addr: str) -> bool:
    ws = res.get("would_send") or {}
    return (
        res.get("dry_run") is True
        and ws.get("to") == [addr]
        and not ws.get("cc")
        and not ws.get("bcc")
    )


def test_mail_send_trash_undo_forward(guard, sender, mail_run):
    addr, mark = sender, guard.marker
    body = f"{mark}. Automated device check of macos-apps-mcp. Safe to delete."
    mail = {"to": addr, "subject": mark, "body": body, "from_address": addr}

    # #573: preview, then one real send to the runner's own address
    err, res, text, _ = guard.run("send_mail", **mail, dry_run=True)
    res = res if isinstance(res, dict) else {}
    ok = not err and _own_preview(res, addr)
    ok = ok and (res.get("would_send") or {}).get("from") == addr
    assert ok, f"send preview: error={err} {text[:200]}"
    mail_run["sent"] = True  # from here on the cleanup runs
    err, res, text, secs = guard.run("send_mail", **mail, dry_run=False)
    assert not err and (res or {}).get("sent") is True, (
        f"send: secs={secs} {text[:200]}"
    )

    rows = _wait(guard, lambda r: bool(_inbox(r)), 18, 10)
    inbox = _inbox(rows)
    assert len(inbox) == 1, f"inbox_copies={len(inbox)} all_copies={len(rows)}"
    guard.adopt_mail(inbox, sent=True)
    mid, box = inbox[0]["id"], inbox[0]["folder"]

    # trash and undo (#575 reader, #578 left_source)
    err, res, text, _ = guard.run("trash_mail", ids=mid, mailbox=box, dry_run=True)
    assert not err and (res or {}).get("dry_run") is True, f"trash preview {text[:200]}"
    err, res, text, secs = guard.run("trash_mail", ids=mid, mailbox=box, dry_run=False)
    res = res if isinstance(res, dict) else {}
    receipt = res.get("receipt")
    ok = not err and res.get("succeeded") == 1 and bool(receipt)
    assert ok, f"trash: secs={secs} receipt={bool(receipt)} {text[:200]}"
    gone = _wait(guard, lambda r: all(x["id"] != mid for x in r), 8, 5, mailbox=box)
    assert all(x["id"] != mid for x in gone), "the marker did not leave the Inbox"

    err, entries, text, _ = guard.run("audit")
    done = [
        e
        for e in entries or []
        if isinstance(e, dict)
        and e.get("receipt") == receipt
        and e.get("phase") == "done"
    ]
    left = (done[0].get("left_source") or {}) if done else {}
    ok = len(done) == 1 and list(left.values()) == ["left"]
    assert ok, f"#578 done_records={len(done)} left_source={sorted(set(left.values()))}"

    err, _res, text, _ = guard.run("mail_undo", receipt=receipt, dry_run=True)
    assert not err, f"#575 undo preview: {text[:200]}"
    err, res, text, secs = guard.run("mail_undo", receipt=receipt, dry_run=False)
    assert not err and (res or {}).get("succeeded") == 1, f"undo: {text[:200]}"
    back = _wait(guard, lambda r: any(x["id"] == mid for x in r), 8, 5, mailbox=box)
    assert any(x["id"] == mid for x in back), "the marker is not in the Inbox again"

    # #573: forward preview, then one real forward to the runner's own address
    fwd = {"message_id": mid, "mailbox": box, "to": addr}
    err, res, text, _ = guard.run("forward_mail", **fwd, dry_run=True)
    ok = not err and _own_preview(res if isinstance(res, dict) else {}, addr)
    assert ok, f"forward preview: error={err} {text[:200]}"
    err, res, text, secs = guard.run("forward_mail", **fwd, dry_run=False)
    assert not err and (res or {}).get("sent") is True, f"forward: {text[:200]}"

    rows = _wait(guard, lambda r: len(_inbox(r)) >= 2, 18, 10)
    copies = [x for x in _inbox(rows) if x["id"] != mid]
    assert len(copies) == 1, f"forwards_in_inbox={len(copies)}"
    err, text_body, text, _ = guard.run(
        "mail_body", id=copies[0]["id"], mailbox=copies[0]["folder"]
    )
    b = text_body if isinstance(text_body, str) else ""
    ok = not err and bool(b.strip()) and mark in b and "safe to delete" in b.lower()
    assert ok, f"forwarded body: error={err} body_chars={len(b)} {text[:200]}"
