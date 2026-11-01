"""The claim window of the native reply's Drafts sweep, end to end (facts 4e `Refusal
cleanup` (3)): a refused ``mail_reply`` over the REAL ``index_top``, ``new_rows``,
``find_own_draft`` and ``.emlx`` reads (a schema-only Envelope Index and a V10 tree in a
tmp dir). Only the AppleScript seam, the insert and the clock are faked. A row lands
at a chosen moment: during a script, during the insert (before the discard) or during
the 45 s wait (after it). Nothing here touches Mail or the real Envelope Index."""

from __future__ import annotations

import urllib.parse

import pytest

from macos_apps_mcp.adapters import mail, mail_outgoing, mail_reply_cleanup
from macos_apps_mcp.errors import ComposeRefused
from tests.test_mail import (
    _FAMILY_UUID,
    _GMAIL_UUID,
    _ORIGINAL_TEXT,
    _REAL_FIND_OWN_DRAFT,
    _REPLY_FOLDER,
    _SweepRig,
)
from tests.test_mail_reply_cleanup import _REAL_READ

_REAL_TOP = mail_reply_cleanup.index_top
DRAFTS = f"imap://{_GMAIL_UUID}/Drafts"
FAMILY_DRAFTS = f"imap://{_FAMILY_UUID}/Drafts"
ATTR = "On 1 Jul 2026, at 14:39, Jane <j@x.com> wrote:"
ATTR_HTML = "On 1 Jul 2026, at 14:39, Jane &lt;j@x.com&gt; wrote:"
# Mail's quote: it carries the original's last six words (the tail the insert confirmed)
QUOTE = f'<blockquote type="cite"><div>{ATTR_HTML}</div>{_ORIGINAL_TEXT}</blockquote>'
OWN = f"<div>Hi</div>{QUOTE}"


def _emlx(body: str, mid: str) -> bytes:
    raw = (
        f"Message-ID: <{mid}>\r\nIn-Reply-To: <abc@x>\r\nSubject: Re: x\r\n"
        f"Content-Type: text/html; charset=utf-8\r\n\r\n{body}"
    ).encode()
    return str(len(raw)).encode() + b"\n" + raw + b"\n<plist></plist>"


class World:
    """The index and the tree: ``land`` stores one reply to the original."""

    def __init__(self, env, root):
        self.env, self.root, self.boxes = env, root, {}

    def box(self, url):
        if url not in self.boxes:
            self.boxes[url] = self.env.add_mailbox(url)
        return self.boxes[url]

    def land(self, url, body, mid):
        rowid = self.env.add_message(mailbox=self.box(url), deleted=0)
        account, _, path = url.partition("://")[2].partition("/")
        folder = self.root / "V10" / account
        for seg in urllib.parse.unquote(path).split("/"):
            folder = folder / f"{seg}.mbox"
        shard = "/".join(reversed(str(rowid // 1000))) if rowid >= 1000 else ""
        messages = folder / "GUID" / "Data" / shard / "Messages"
        messages.mkdir(parents=True, exist_ok=True)
        (messages / f"{rowid}.emlx").write_bytes(_emlx(body, mid))
        return rowid


@pytest.fixture
def world(blank_envelope, tmp_path, monkeypatch):
    monkeypatch.setattr(mail_reply_cleanup, "_read", _REAL_READ)
    w = World(blank_envelope, tmp_path)
    blank_envelope.add_message(mailbox=w.box(f"imap://{_GMAIL_UUID}/INBOX"))  # older
    blank_envelope.add_message(mailbox=w.box(DRAFTS))
    return w


def run(monkeypatch, *, during=None, on_insert=(), on_wait=(), top=None):
    """One refused ``mail_reply`` over the real index. ``during``: ``{script name:
    callable}`` run INSIDE that script's call; ``on_insert``: rows landing before the
    discard; ``on_wait``: rows landing during the 45 s wait, after the discard.
    ``top``: replaces ``index_top`` (called with the real one)."""
    rig = _SweepRig(monkeypatch, insert_error=ComposeRefused("confirmation: no"))
    monkeypatch.setattr(mail_reply_cleanup, "index_top", top or _REAL_TOP)
    monkeypatch.setattr(mail_reply_cleanup, "find_own_draft", _REAL_FIND_OWN_DRAFT)
    rig.insert_hook = lambda _kw: [land() for land in on_insert]
    real_osa = rig._osa
    hooks = during or {}

    def osa(script, *argv, **kw):
        names = rig._names()
        if names[script] in hooks:
            hooks[names[script]]()
        return real_osa(script, *argv, **kw)

    monkeypatch.setattr(mail_outgoing.runtime, "run_osascript", osa)

    def wait(deadline):
        rig.waits.append(deadline)
        rig.clock[0] = max(rig.clock[0], deadline)
        for land in on_wait:
            land()

    monkeypatch.setattr(mail_outgoing, "_wait_until", wait)
    with pytest.raises(ComposeRefused) as exc:
        mail.MailAdapter().reply("<abc@x>", _REPLY_FOLDER, "Hi")
    return rig, str(exc.value)


def deleted(rig):
    return [c[1] for c in rig.calls if c[0] == "_SWEEP_DELETE"]


def assert_left_loudly(rig, msg):
    assert deleted(rig) == [], (deleted(rig), msg)
    assert "nothing was created" not in msg and "found and deleted" not in msg, msg
    assert "may NOT be fully removed" in msg, msg


def test_a_row_landing_during_the_wait_is_never_claimed(world, monkeypatch):
    # rv533 M6: landed_by is read right after the discard answers, BEFORE the 45 s wait.
    # A same-text, full-quote draft in the sending account's own Drafts that arrives
    # during the wait (a hand draft) is reported, not deleted.
    rig, msg = run(monkeypatch, on_wait=[lambda: world.land(DRAFTS, OWN, "hand@x")])
    assert_left_loudly(rig, msg)


def test_the_same_row_landing_during_the_insert_is_the_calls_own(world, monkeypatch):
    # the control: before the discard answered, it is the window's autosave
    rig, msg = run(monkeypatch, on_insert=[lambda: world.land(DRAFTS, OWN, "own@x")])
    assert [a[0] for a in deleted(rig)] == ["own@x"]
    assert "found and deleted" in msg and "nothing was created" in msg


@pytest.mark.parametrize("script", ["_ORIGINAL", "_OUTGOING_IDS"])
def test_a_row_landing_before_the_baseline_is_not_new(world, monkeypatch, script):
    # rv533: the whose-scan of the original (_ORIGINAL) and the baseline read come
    # before the index baseline, so a row that lands in them is older than the window.
    rig, msg = run(
        monkeypatch,
        during={script: lambda: world.land(FAMILY_DRAFTS, OWN, "fam@x")},
    )
    assert deleted(rig) == []
    assert "nothing was created" in msg  # no new row threads to the original anywhere


def test_a_family_row_landing_during_the_open_is_not_claimed(world, monkeypatch):
    # rv533: the row is new (it landed after the baseline) but sits in an account the
    # reply is not sent from
    rig, msg = run(
        monkeypatch,
        during={"_REPLY_OPEN": lambda: world.land(FAMILY_DRAFTS, OWN, "fam@x")},
    )
    assert_left_loudly(rig, msg)


def test_a_family_row_landing_during_the_insert_is_not_claimed(world, monkeypatch):
    rig, msg = run(
        monkeypatch, on_insert=[lambda: world.land(FAMILY_DRAFTS, OWN, "fam@x")]
    )
    assert_left_loudly(rig, msg)


def test_residual_a_same_text_hand_draft_in_the_sending_account_inside_the_window(
    world, monkeypatch
):
    # facts 4e (3) Residual: a hand draft with the same text and the full quote in the
    # SENDING account that lands between the reply verb and the discard cannot be told
    # from the call's own. It is bounded (the account, the span) and written down.
    rig, _ = run(
        monkeypatch,
        during={"_REPLY_OPEN": lambda: world.land(DRAFTS, OWN, "hand@x")},
    )
    assert [a[0] for a in deleted(rig)] == ["hand@x"]


def test_a_top_that_cannot_be_read_after_the_discard_claims_nothing(world, monkeypatch):
    # rv533 B9: landed_by is None when the second index read raises: no row is proven
    # the window's own, so nothing is deleted and the refusal is loud
    reads = []

    def top():
        reads.append(1)
        if len(reads) > 1:
            raise RuntimeError("worker gone")
        return _REAL_TOP()

    rig, msg = run(
        monkeypatch,
        on_insert=[lambda: world.land(DRAFTS, OWN, "own@x")],
        top=top,
    )
    assert_left_loudly(rig, msg)
