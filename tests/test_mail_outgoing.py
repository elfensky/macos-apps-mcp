"""0.9.4 — the outgoing-message lifecycle (#160) and send-an-approved-draft (#157).

``mail_outgoing`` is the module every outbound tool routes through, so these tests pin
the two things a green suite has historically failed to pin about that plane: that the
FOUR send paths report the SAME ``would_send`` shape, and that
``send_mail(draft_id=…)`` refuses rather than silently degrades. Device behaviour is in
``docs/mail-applescript-facts.md`` §3b — Mail cannot script-send a stored draft, which
is why #157 rebuilds one and why the refusals exist at all.
"""

from __future__ import annotations

import pytest

from macos_apps_mcp.adapters import mail, mail_outgoing
from macos_apps_mcp.text import RS, US

_PREVIEW_KEYS = {
    "action",
    "to",
    "cc",
    "bcc",
    "from",
    "subject",
    "source",
    "body_chars",
    "html",
}


def _patch_run(monkeypatch, fake):
    monkeypatch.setattr(mail, "run_osascript", fake)
    monkeypatch.setattr(mail_outgoing, "run_osascript", fake)


def _draft_payload(
    subject="Quarterly numbers",
    sender="Andrei <andrei@lav.ren>",
    to=("boss@corp.com",),
    cc=(),
    bcc=(),
    attachments=0,
    threaded=False,
    body="the approved text",
):
    """One _DRAFT_ENVELOPE wire payload: seven US fields then the body."""
    return US.join(
        [
            subject,
            sender,
            RS.join(to) + (RS if to else ""),
            RS.join(cc) + (RS if cc else ""),
            RS.join(bcc) + (RS if bcc else ""),
            str(attachments),
            "1" if threaded else "0",
            body,
        ]
    )


# --- #160: ONE would_send shape ------------------------------------------------------


def test_every_send_path_previews_the_same_keys(monkeypatch):
    """The acceptance box: a caller writes ONE dry-run handler. Before #160 there were
    three shapes (`reply_to`/`reply_all`, `forwarding`, and the bare envelope), so a
    model had to branch on which tool it had called to read its own preview back."""

    def fake(script, *argv):
        if script is mail_outgoing._REPLY_ALL_RECIPIENTS:
            return f"to{US}a@x{RS}sender{US}s@x{RS}subject{US}Re: hi{RS}"
        if script is mail_outgoing._DRAFT_ENVELOPE:
            return _draft_payload()
        raise AssertionError(f"a dry run must not run {script!r}")

    _patch_run(monkeypatch, fake)
    adapter = mail.MailAdapter()
    previews = [
        adapter.send("a@b.com", "Hi", "body"),
        adapter.reply_all("<orig@x>", "inbox", "sounds good"),
        adapter.forward("<orig@x>", "inbox", "a@b.com"),
        adapter.send(draft_id="<d@x>"),
    ]
    for p in previews:
        assert p["dry_run"] is True
        assert set(p["would_send"]) == _PREVIEW_KEYS
    assert [p["would_send"]["action"] for p in previews] == [
        "send",
        "reply_all",
        "forward",
        "send_draft",
    ]


def test_forward_builder_has_no_body_parameter():
    """#160 turns "never write `content` on a forward" from an absent line guarded by a
    grep into interface shape: there is no parameter to pass, so there is nothing to
    get wrong. (The grep-test in test_mail.py stays as belt-and-braces.)"""
    import inspect

    params = inspect.signature(mail_outgoing.forward_of).parameters
    assert set(params) == {"message_id", "mailbox", "to"}


def test_the_quote_preamble_exists_once(monkeypatch):
    """reply and reply_all each carried a copy of fetch/guard/partition/sanitize/build.
    Both go through ``quoted_body`` now — proved by patching that one function and
    seeing both paths change."""
    seen = []
    monkeypatch.setattr(
        mail_outgoing,
        "quoted_body",
        lambda body, mid, mb: seen.append(mid) or (body + " [QUOTE]"),
    )
    bodies = []

    class _FakeFile:
        def __init__(self, text):
            bodies.append(text)

        def __enter__(self):
            return "/tmp/fake"

        def __exit__(self, *a):
            return False

    def fake(script, *argv):
        if script is mail_outgoing._REPLY_ALL_RECIPIENTS:
            return f"to{US}a@x{RS}sender{US}s@x{RS}subject{US}Re: hi{RS}"
        if script is mail_outgoing._OUTBOX_COUNT:
            return "0"
        return "sent"

    _patch_run(monkeypatch, fake)
    monkeypatch.setattr(mail, "body_file", _FakeFile)
    monkeypatch.setattr(mail_outgoing, "body_file", _FakeFile)
    mail.MailAdapter().reply("<a@x>", "inbox", "hello")
    mail.MailAdapter().reply_all("<b@x>", "inbox", "hello", dry_run=False)
    assert seen == ["a@x", "b@x"]
    assert bodies == ["hello [QUOTE]", "hello [QUOTE]"]


# --- #157: send an approved draft by id ----------------------------------------------


def test_draft_preview_reads_the_draft_and_constructs_nothing(monkeypatch):
    """An id alone tells an approving human nothing, so this preview READS the draft —
    rule 2 of the module: reading a stored message strands nothing, CONSTRUCTING one
    strands an autosaved copy nobody can identify 15s later."""
    seen = []

    def fake(script, *argv):
        seen.append(script)
        assert script is mail_outgoing._DRAFT_ENVELOPE
        return _draft_payload(to=("boss@corp.com", "cfo@corp.com"), cc=("cc@corp.com",))

    _patch_run(monkeypatch, fake)
    out = mail.MailAdapter().send(draft_id="<d@x>")
    assert out["would_send"] == {
        "action": "send_draft",
        "to": ["boss@corp.com", "cfo@corp.com"],
        "cc": ["cc@corp.com"],
        "bcc": [],
        "from": "Andrei <andrei@lav.ren>",
        "subject": "Quarterly numbers",
        "source": "d@x",
        "body_chars": len("the approved text"),
        "html": False,
    }
    assert seen == [mail_outgoing._DRAFT_ENVELOPE]  # the read only — nothing built


def test_draft_send_uses_the_drafts_own_bytes_and_removes_the_source(monkeypatch):
    """The point of #157: the model never re-types the body, so what was approved and
    what goes out are the same text — and the approved copy does not stay in Drafts
    waiting for a human to send it a second time."""
    seen = {}
    bodies = []

    class _FakeFile:
        def __init__(self, text):
            bodies.append(text)

        def __enter__(self):
            return "/tmp/fake-body"

        def __exit__(self, *a):
            return False

    def fake(script, *argv):
        seen[script] = argv
        if script is mail_outgoing._DRAFT_ENVELOPE:
            return _draft_payload()
        if script is mail_outgoing._OUTBOX_COUNT:
            return "0"
        return "sent"

    _patch_run(monkeypatch, fake)
    monkeypatch.setattr(mail_outgoing, "body_file", _FakeFile)
    out = mail.MailAdapter().send(draft_id="<d@x>", dry_run=False)
    assert out["sent"] is True
    assert out["action"] == "send_draft"
    assert out["source"] == "d@x"
    assert out["draft_removed"] is True
    assert bodies == ["the approved text"]  # not rebuilt from anything the model typed
    assert seen[mail_outgoing._SEND] == (
        "Quarterly numbers",
        "/tmp/fake-body",
        "0",
        "Andrei <andrei@lav.ren>",
        "boss@corp.com",
        "",
        "",
    )
    assert seen[mail._DELETE_DRAFT] == ("d@x",)


def test_draft_cleanup_failure_never_turns_a_completed_send_into_an_error(monkeypatch):
    """The send already happened. Raising here reports a COMPLETED send as a failed
    call, and a model that retries that "failure" sends the mail twice."""

    class _FakeFile:
        def __init__(self, text):
            pass

        def __enter__(self):
            return "/tmp/fake-body"

        def __exit__(self, *a):
            return False

    def fake(script, *argv):
        if script is mail_outgoing._DRAFT_ENVELOPE:
            return _draft_payload()
        if script is mail_outgoing._OUTBOX_COUNT:
            return "0"
        if script is mail._DELETE_DRAFT:
            raise mail.NativeError("Mail is not responding")
        return "sent"

    _patch_run(monkeypatch, fake)
    monkeypatch.setattr(mail_outgoing, "body_file", _FakeFile)
    out = mail.MailAdapter().send(draft_id="<d@x>", dry_run=False)
    assert out["sent"] is True
    assert out["draft_removed"] is False


def test_draft_with_attachments_is_refused_not_sent_stripped(monkeypatch):
    """Mail cannot script-send a stored draft, so this rebuilds it — and a rebuilt
    message carries no attachments. Sending it anyway would deliver a mail the human
    approved WITH its attachments, without them. Refuse."""
    _patch_run(monkeypatch, lambda *a, **k: _draft_payload(attachments=3))
    with pytest.raises(ValueError, match="3 attachment"):
        mail.MailAdapter().send(draft_id="<d@x>", dry_run=False)


def test_reply_draft_is_refused_and_points_at_reply_all(monkeypatch):
    """In-Reply-To/References can only be set by Mail's native reply verb, so a rebuilt
    reply arrives detached from its thread — the exact failure the vault's
    draft-then-approve flow would notice last."""
    _patch_run(monkeypatch, lambda *a, **k: _draft_payload(threaded=True))
    with pytest.raises(ValueError, match="reply_all"):
        mail.MailAdapter().send(draft_id="<d@x>", dry_run=False)


def test_draft_without_a_recipient_is_refused(monkeypatch):
    _patch_run(monkeypatch, lambda *a, **k: _draft_payload(to=()))
    with pytest.raises(ValueError, match="no recipient"):
        mail.MailAdapter().send(draft_id="<d@x>")


@pytest.mark.parametrize(
    "extra",
    [
        {"to": "a@b.com"},
        {"subject": "Hi"},
        {"body": "text"},
        {"cc": "c@d.com"},
        {"bcc": "b@d.com"},
        {"from_address": "me@x.com"},
        {"html": True},
    ],
)
def test_draft_id_with_fresh_content_raises_instead_of_guessing(monkeypatch, extra):
    """Settled on #157: passing both RAISES, never guesses. A draft already carries its
    own recipients and text, so "which one gets sent?" has no safe default."""
    _patch_run(
        monkeypatch,
        lambda *a, **k: pytest.fail("must raise before any native call"),
    )
    with pytest.raises(ValueError, match="EITHER draft_id OR"):
        mail.MailAdapter().send(draft_id="<d@x>", **extra)


def test_draft_id_rejects_an_empty_id():
    with pytest.raises(ValueError, match="draft"):
        mail.MailAdapter().send(draft_id="   <>  ")


def test_draft_envelope_parses_a_body_containing_framing_bytes():
    """The body is the LAST field and is US-partitioned from the left, so a payload
    that itself contains US/RS cannot desync the parse — the _ORIGINAL idiom."""
    body = f"line one{US}still body{RS}and more"
    parsed = mail_outgoing._parse_draft_envelope(_draft_payload(body=body))
    assert parsed["body"] == body
    assert parsed["to"] == ["boss@corp.com"]
    assert parsed["attachments"] == 0


# --- drafts() discrete fields (#157) -------------------------------------------------


def test_drafts_expose_to_and_subject_as_discrete_fields(monkeypatch):
    """Reacquiring "the draft I just made" was substring guesswork against the free-text
    summary, and collided outright whenever two drafts shared a subject."""
    _patch_run(
        monkeypatch,
        lambda *a, **k: f"<d@x>{US}Quarterly numbers{US}boss@corp.com{RS}",
    )
    rec = mail.MailAdapter().list_drafts()["results"][0]
    assert rec["subject"] == "Quarterly numbers"
    assert rec["to"] == "boss@corp.com"
    assert rec["id"] == "<d@x>"
    assert rec["folder"] == "drafts"
