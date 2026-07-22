"""Unit tests for the mail adapter — pure parsing helpers (no osascript)."""

from __future__ import annotations

import pytest

from macos_apps_mcp.adapters.mail import (
    MAX_MAILS,
    MailAdapter,
    _deeplink,
    _parse,
    _summary,
    system_mailbox_names,
)
from macos_apps_mcp.contracts import Pointer


def test_summary_subject_and_sender():
    assert _summary("Invoice", "Bob <bob@x.com>") == "Invoice — Bob <bob@x.com>"


def test_summary_subject_only():
    assert _summary("Invoice", "") == "Invoice"


def test_summary_empty_is_placeholder():
    assert _summary("  ", "  ") == "(no subject)"


def test_deeplink_wraps_message_id():
    # #61: uppercase %3C/%3E, id percent-encoded with safe='@' (@ stays literal).
    assert _deeplink("abc@host") == "message://%3Cabc@host%3E"


def test_deeplink_strips_existing_brackets():
    assert _deeplink("<abc@host>") == "message://%3Cabc@host%3E"


def test_deeplink_percent_encodes_special_chars():
    # a space (or other unsafe char) in the id is percent-encoded so the URL is valid;
    # '@' is preserved (safe='@').
    assert _deeplink("a b@ho st") == "message://%3Ca%20b@ho%20st%3E"


def test_parse_tab_lines():
    raw = "abc@host\tInvoice\tBob\n<def@host>\tHello\t\n"
    ptrs = _parse(raw)
    assert len(ptrs) == 2
    assert isinstance(ptrs[0], Pointer)
    assert ptrs[0].id == "abc@host" and ptrs[0].summary == "Invoice — Bob"
    assert ptrs[0].deeplink == "message://%3Cabc@host%3E"
    assert ptrs[1].summary == "Hello"


def test_parse_skips_blank():
    assert _parse("\n  \n") == []


def test_parse_skips_missing_message_id():
    # a header-less message has no stable RFC822 citation: AppleScript emits "missing
    # value" (or ""), which must be skipped, never a garbage id/deeplink (#61).
    raw = (
        "missing value\tNo header\tSpammer\n\tEmpty id\tNobody\ngood@host\tReal\tBob\n"
    )
    ptrs = _parse(raw)
    assert [p.id for p in ptrs] == ["good@host"]  # only the message with a real id


def test_parse_sanitizes_control_chars_in_summary():
    # #52: control chars in a subject (which blanked Claude Desktop, carterlasalle #2)
    # must be stripped before the summary reaches the model. NUL/BEL/US are used here
    # because the tab-delimited parser frames records with splitlines(), which would
    # itself split on U+2028/NEL — that framing fragility is pre-existing (a literal
    # newline in a subject splits too) and out of #52's scope; the helper's own
    # U+2028/9 folding is covered in test_runtime.
    raw = "m@host\tInv\x00oice\x1fQ3\x07\tBob\n"
    ptr = _parse(raw)[0]
    assert ptr.summary == "InvoiceQ3 — Bob"
    assert "\x00" not in ptr.summary and "\x07" not in ptr.summary


def test_get_pointers_bounds_host_side(monkeypatch):
    # #52 acceptance: the cap is pushed INTO the AppleScript (argv[2]) so the search
    # stops emitting after MAX_MAILS — not fetched whole then sliced in Python.
    seen = {}
    monkeypatch.setattr(
        "macos_apps_mcp.adapters.mail.run_osascript",
        lambda script, *args: seen.setdefault("args", args) and "" or "",
    )
    MailAdapter().get_pointers("invoice")
    assert seen["args"] == ("invoice", str(MAX_MAILS))


# --- localized system-mailbox tables (#61) -------------------------------------------


def test_system_mailbox_names_localized():
    # en/nl/ru at least (the acceptance floor) — a US-hardcoded "Inbox" fails on a
    # non-English Mac, so mailbox-scoped ops try each localized candidate.
    inbox = system_mailbox_names("inbox")
    assert "Inbox" in inbox and "Postvak IN" in inbox and "Входящие" in inbox


def test_system_mailbox_names_case_insensitive_canonical():
    assert system_mailbox_names("SENT") == system_mailbox_names("sent")


def test_system_mailbox_names_unknown_raises():
    with pytest.raises(ValueError, match="unknown system mailbox"):
        system_mailbox_names("archive")


def test_system_mailbox_covers_the_core_five():
    for canonical in ("inbox", "sent", "drafts", "trash", "junk"):
        names = system_mailbox_names(canonical)
        assert len(names) >= 3  # en + nl + ru at minimum


# --- sender search (#61) -------------------------------------------------------------


def test_search_matches_subject_or_sender(monkeypatch):
    # the AppleScript `whose` clause must match subject OR sender — assert the emitted
    # script contains both predicates (the search is no longer subject-only).
    seen = {}
    monkeypatch.setattr(
        "macos_apps_mcp.adapters.mail.run_osascript",
        lambda script, *args: seen.setdefault("script", script) and "" or "",
    )
    MailAdapter().get_pointers("acme")
    assert "subject contains q or sender contains q" in seen["script"]


def test_search_empty_query_raises():
    with pytest.raises(ValueError, match="search substring"):
        MailAdapter().get_pointers("   ")


# --- mail_body + create_draft (#62) --------------------------------------------------

import os  # noqa: E402
import re  # noqa: E402

from macos_apps_mcp.adapters.mail import _BODY, _CREATE_DRAFT  # noqa: E402


def test_get_body_resolves_and_bounds(monkeypatch):
    # body-by-id: the RFC id is passed via argv (injection-safe) and the result is
    # hygiene-budgeted via clean_body (control-stripped here).
    seen = {}

    def fake(script, *a):
        seen["call"] = (script, a)
        return "Hello\x00 body"

    monkeypatch.setattr("macos_apps_mcp.adapters.mail.run_osascript", fake)
    out = MailAdapter().get_body("<abc@host>")
    assert out == "Hello body"  # NUL stripped by clean_body
    assert seen["call"][0] is _BODY
    assert seen["call"][1] == ("abc@host",)  # brackets stripped, bare id via argv


def test_get_body_empty_id_raises():
    with pytest.raises(ValueError, match="message id"):
        MailAdapter().get_body("   ")


def test_get_body_missing_value_is_not_surfaced_as_body(monkeypatch):
    # #62 review: an HTML-only / not-yet-downloaded message yields AppleScript `missing
    # value`, coerced to the literal string — it must NOT be handed back as the body.
    from macos_apps_mcp.errors import NativeError

    monkeypatch.setattr(
        "macos_apps_mcp.adapters.mail.run_osascript", lambda *a: "missing value"
    )
    with pytest.raises(NativeError, match="not available locally"):
        MailAdapter().get_body("abc@host")


def test_get_body_huge_body_overflows(monkeypatch):
    # a pasted-dump body over the hard cap surfaces OutputOverflow (open it in Mail),
    # not a silently-truncated blob.
    from macos_apps_mcp.errors import OutputOverflow
    from macos_apps_mcp.text import BODY_HARD_MAX

    monkeypatch.setattr(
        "macos_apps_mcp.adapters.mail.run_osascript",
        lambda *a: "z" * (BODY_HARD_MAX + 1),
    )
    with pytest.raises(OutputOverflow):
        MailAdapter().get_body("abc@host")


def test_create_draft_never_sends():
    # the SAFETY invariant: the draft script has NO `send` verb anywhere — it can only
    # create-and-open, never send (joshrutkowski's two-tier gate; the #62 acceptance).
    assert "send" not in _CREATE_DRAFT.lower()
    assert "make new outgoing message" in _CREATE_DRAFT
    assert "visible:true" in _CREATE_DRAFT  # opens for human review


def test_create_draft_passes_body_via_tempfile(monkeypatch, tmp_path):
    # body must be READ from a tempfile as «class utf8», never interpolated into the
    # script; to/subject/path go via argv. Assert the body reaches a real file and the
    # path is argv[3].
    captured = {}

    def fake(script, *args):
        captured["script"] = script
        captured["args"] = args
        # the tempfile must exist and hold the body at call time (script reads it)
        with open(args[2], encoding="utf-8") as f:
            captured["body_on_disk"] = f.read()
        return ""

    monkeypatch.setattr("macos_apps_mcp.adapters.mail.run_osascript", fake)
    MailAdapter().create_draft("bob@x.com", "Hi", "multi\nline © body")
    assert captured["script"] is _CREATE_DRAFT
    assert captured["args"][0] == "bob@x.com" and captured["args"][1] == "Hi"
    assert captured["body_on_disk"] == "multi\nline © body"  # never interpolated
    assert "«class utf8»" in _CREATE_DRAFT  # read as utf8, not string-built


def test_create_draft_cleans_up_tempfile(monkeypatch):
    # the tempfile is deleted after the (synchronous) script read it.
    paths = []
    monkeypatch.setattr(
        "macos_apps_mcp.adapters.mail.run_osascript",
        lambda script, *a: paths.append(a[2]) or "",
    )
    MailAdapter().create_draft("bob@x.com", "Hi", "body")
    assert paths and not os.path.exists(paths[0])  # cleaned up


def test_create_draft_empty_recipient_raises():
    with pytest.raises(ValueError, match="recipient"):
        MailAdapter().create_draft("  ", "Hi", "body")


def test_create_draft_returns_locator_dict(monkeypatch):
    # #43: an unsent draft has no stable Message-ID, so create_draft returns a locator
    # (where to find it) instead of a fabricated id.
    monkeypatch.setattr("macos_apps_mcp.adapters.mail.run_osascript", lambda *a: "")
    out = MailAdapter().create_draft("x@example.com", "Hi", "body")
    assert out["created"] is True
    assert out["mailbox"] == "Drafts"
    assert out["subject"] == "Hi"
    assert "no stable id" in out["note"].lower()


def test_create_draft_cleanup_on_failure_is_in_script():
    # #44: atomicity is enforced INSIDE the osascript — the partial outgoing message is
    # deleted in the error path. Assert the STRUCTURE (delete msg between `on error` and
    # the re-raise), not just the words: a substring check would pass even if the block
    # were gutted and a stray "delete"/"on error" comment left behind (#43/#44 review).
    assert re.search(r"on error errMsg\s+delete msg\s+error errMsg", _CREATE_DRAFT), (
        "the on-error handler must delete the partial draft, then re-raise"
    )


def test_create_draft_propagates_error_and_cleans_tempfile(monkeypatch):
    # #44 Python-side contract: if osascript surfaces the propagated error, create_draft
    # re-raises AND does not leak the body tempfile (the finally unlinks it) — so a
    # failed create leaves nothing behind on either side.
    seen = {}

    def boom(script, *args):
        seen["path"] = args[2]  # argv: to, subject, tempfile-path
        raise RuntimeError("osascript failed")

    monkeypatch.setattr("macos_apps_mcp.adapters.mail.run_osascript", boom)
    with pytest.raises(RuntimeError, match="osascript failed"):
        MailAdapter().create_draft("x@example.com", "Hi", "body")
    assert not os.path.exists(seen["path"])  # tempfile cleaned up despite the error


# --- list_attachments (#45) -----------------------------------------------------------


def test_parse_attachments_groups_by_message():
    from macos_apps_mcp.adapters.mail import _parse_attachments

    us, rs = "\x1f", "\x1e"
    raw = (
        f"Logo files{us}LOGO.zip{us}1200000{us}true{us}spec.pdf{us}0{us}false{rs}"
        f"No attach subject{rs}"
    )
    out = _parse_attachments(raw)
    assert out[0]["summary"] == "Logo files"
    assert out[0]["attachments"] == [
        {"name": "LOGO.zip", "size": 1200000, "downloaded": True},
        {"name": "spec.pdf", "size": 0, "downloaded": False},
    ]
    assert out[1]["summary"] == "No attach subject"
    assert out[1]["attachments"] == []


def test_list_attachments_resolves_mailbox_and_caps(monkeypatch):
    import macos_apps_mcp.adapters.mail as mail

    captured = {}

    def fake(script, *args):
        captured["script"] = script
        captured["args"] = args
        # more records than MAX_MAILS — the cap must actually bite
        records = "".join(
            f"Logo files {i}\x1fLOGO.zip\x1f100\x1ftrue\x1e"
            for i in range(mail.MAX_MAILS + 5)
        )
        return records

    monkeypatch.setattr(mail, "run_osascript", fake)
    out = mail.MailAdapter().list_attachments("drafts", "Logo")
    # only query, cap, and canonical mailbox travel via argv now — no localized
    # candidates (the unified `drafts mailbox` accessor is locale-independent)
    assert captured["args"] == ("Logo", str(mail.MAX_MAILS), "drafts")
    assert len(out) == mail.MAX_MAILS


def test_list_attachments_empty_query_lists_all(monkeypatch):
    import macos_apps_mcp.adapters.mail as mail

    def fake(script, *args):
        return (
            "First\x1fa.pdf\x1f10\x1ftrue\x1e"
            "Second\x1fb.pdf\x1f20\x1ffalse\x1e"
            "Third\x1e"
        )

    monkeypatch.setattr(mail, "run_osascript", fake)
    out = mail.MailAdapter().list_attachments("inbox")
    assert [r["summary"] for r in out] == ["First", "Second", "Third"]


def test_list_attachments_unknown_mailbox_raises():
    import pytest

    from macos_apps_mcp.adapters.mail import MailAdapter

    with pytest.raises(ValueError, match="unknown system mailbox"):
        MailAdapter().list_attachments("nope", "x")


# --- reply (#42/#46) ------------------------------------------------------------------

from macos_apps_mcp.adapters.mail import _ORIGINAL, _REPLY, _build_quote  # noqa: E402


def _is_reply_script(script: str) -> bool:
    # _REPLY is the only one of the two templates that invokes the native reply verb;
    # _ORIGINAL only fetches sender/date/content. Distinguish on that, not on "reply"
    # substring in a comment (both docstrings/templates mention "reply" in prose).
    return "reply (item 1 of matches)" in script


def test_build_quote_prefixes_and_headers():
    q = _build_quote("Jane <j@x.com>", "2026-07-01", "line one\nline two")
    assert "On 2026-07-01, Jane <j@x.com> wrote:" in q
    assert "> line one" in q and "> line two" in q


def test_reply_quote_truncates_huge_original(monkeypatch):
    # HIGH fix: _build_quote must TRUNCATE a huge original, not crash the whole reply
    # (clean_body's default hard=BODY_HARD_MAX would raise OutputOverflow here).
    import macos_apps_mcp.adapters.mail as mail
    from macos_apps_mcp.text import BODY_HARD_MAX

    huge = "z" * (BODY_HARD_MAX + 100)

    def fake(script, *args):
        if _is_reply_script(script):
            return ""
        # _ORIGINAL: sender, date, then a body over the hard cap
        return f"Jane <j@x.com>\x1f2026-07-01\x1f{huge}"

    monkeypatch.setattr(mail, "run_osascript", fake)
    out = mail.MailAdapter().reply("<abc@x>", "thanks", include_quote=True)
    assert out["created"] is True


# --- _ORIGINAL sender/date framing hazard (#42/#46 review) ---------------------------


def test_original_strips_framing_from_sender_and_date():
    # MEDIUM fix: _ORIGINAL must apply the SAME stripFraming handler _ATTACHMENTS uses
    # to the sender and date fields, so a display name containing a literal US/RS char
    # can't desync reply()'s raw.partition("\x1f") parsing.
    assert "my stripFraming(snd)" in _ORIGINAL
    assert "my stripFraming(dt)" in _ORIGINAL
    assert "on stripFraming" in _ORIGINAL


# --- US/RS framing contract (#68) -----------------------------------------------------


def test_framed_templates_compose_the_one_strip_framing_handler():
    # The a6ce7fd bug was a template emitting a raw field because its pasted handler
    # copy drifted. Every template that emits US/RS-framed free text must now COMPOSE
    # the single STRIP_FRAMING constant — exactly one handler definition per script.
    import macos_apps_mcp.adapters.mail as mail

    framed = (mail._ORIGINAL, mail._ATTACHMENTS, mail._INBOX_TRIAGE, mail._SENT_TRIAGE)
    for tpl in framed:
        assert tpl.startswith(mail.STRIP_FRAMING)
        assert tpl.count("on stripFraming") == 1


def testsplit_framed_skips_blank_records_and_splits_fields():
    import macos_apps_mcp.adapters.mail as mail

    raw = f"a{mail.US}b{mail.RS}{mail.RS}c{mail.RS}  {mail.RS}"
    assert mail.split_framed(raw) == [["a", "b"], ["c"]]


def test_framing_literals_live_only_in_the_contract_block():
    # Locality guard: no other line in mail.py may hard-code the framing bytes.
    import inspect

    import macos_apps_mcp.adapters.mail as mail

    src = inspect.getsource(mail)
    offenders = [
        line
        for line in src.splitlines()
        if (r"\x1f" in line or r"\x1e" in line)
        and not line.lstrip().startswith("#")
        and "US =" not in line
        and "RS =" not in line
    ]
    assert offenders == []


def test_reply_sanitizes_control_chars_from_sender_and_date(monkeypatch):
    # Behavioral defense-in-depth: this mock bypasses the AppleScript stripFraming
    # entirely (run_osascript is replaced outright), so it specifically tests the
    # Python-side sanitize_line guard. The stray control char is BEL (\x07), not the
    # \x1f field separator itself — a literal \x1f in a field would desync the
    # partition-based parsing before sanitize_line ever runs, which is the scenario
    # stripFraming (tested above) guards against; sanitize_line's job is catching
    # OTHER control chars stripFraming doesn't touch.
    import macos_apps_mcp.adapters.mail as mail

    bodies = []

    def fake(script, *args):
        if _is_reply_script(script):
            with open(args[1], encoding="utf-8") as f:
                bodies.append(f.read())
            return ""
        # sender carries a stray control char the AppleScript strip doesn't remove
        return "Jane\x07 <j@x.com>\x1f2026-07-01\x1foriginal body"

    monkeypatch.setattr(mail, "run_osascript", fake)
    mail.MailAdapter().reply("<abc@x>", "my reply", include_quote=True)
    header_line = next(
        line for line in bodies[0].splitlines() if line.startswith("On ")
    )
    assert "\x07" not in header_line


def test_reply_composes_body_and_targets_id(monkeypatch):
    import macos_apps_mcp.adapters.mail as mail

    calls = []
    bodies = []

    def fake(script, *args):
        calls.append((script, args))
        if not _is_reply_script(script):
            # _ORIGINAL: return a US-framed sender/date/body triple
            return "Jane <j@x.com>\x1f2026-07-01\x1foriginal body"
        # _REPLY: the tempfile is deleted right after this call returns, so read it
        # now (while it still exists) rather than after reply() has returned.
        with open(args[1], encoding="utf-8") as f:
            bodies.append(f.read())
        return ""

    monkeypatch.setattr(mail, "run_osascript", fake)
    out = mail.MailAdapter().reply("<abc@x>", "my reply", include_quote=True)
    assert out["created"] is True
    assert out["mailbox"] == "Drafts"
    # both scripts ran: _ORIGINAL then _REPLY
    assert [c[0] is _ORIGINAL for c in calls] == [True, False]
    assert calls[1][0] is _REPLY
    reply_call = calls[1]
    assert reply_call[1][0] == "abc@x"  # brackets stripped, bare id via argv
    body_on_disk = bodies[0]
    assert "my reply" in body_on_disk
    assert "> original body" in body_on_disk
    assert "On 2026-07-01, Jane <j@x.com> wrote:" in body_on_disk


def test_reply_without_quote_omits_original(monkeypatch):
    import macos_apps_mcp.adapters.mail as mail

    bodies = []

    def fake(script, *args):
        if _is_reply_script(script):
            with open(args[1], encoding="utf-8") as f:
                bodies.append(f.read())
            return ""
        # _ORIGINAL must NOT be called when include_quote=False
        raise AssertionError("_ORIGINAL should not run when include_quote=False")

    monkeypatch.setattr(mail, "run_osascript", fake)
    mail.MailAdapter().reply("<abc@x>", "just this", include_quote=False)
    assert bodies and bodies[0] == "just this"
    assert ">" not in bodies[0]


def test_reply_original_missing_value_skips_quote(monkeypatch):
    # AppleScript coerces an unset property to the "missing value" literal — same guard
    # as get_body (#62): must not surface it as sender/date/body, and must not blow up
    # the reply — the quote is silently skipped and the reply still goes through.
    import macos_apps_mcp.adapters.mail as mail

    bodies = []

    def fake(script, *args):
        if _is_reply_script(script):
            with open(args[1], encoding="utf-8") as f:
                bodies.append(f.read())
            return ""
        return "missing value"

    monkeypatch.setattr(mail, "run_osascript", fake)
    out = mail.MailAdapter().reply("<abc@x>", "my reply", include_quote=True)
    assert out["created"] is True
    assert bodies[0] == "my reply"  # no quote appended


def test_reply_cleans_up_tempfile(monkeypatch):
    import macos_apps_mcp.adapters.mail as mail

    paths = []

    def fake(script, *args):
        if _is_reply_script(script):
            paths.append(args[1])
            return ""
        return ""

    monkeypatch.setattr(mail, "run_osascript", fake)
    mail.MailAdapter().reply("<abc@x>", "body", include_quote=False)
    assert paths and not os.path.exists(paths[0])


def test_reply_empty_id_raises():
    import pytest

    from macos_apps_mcp.adapters.mail import MailAdapter

    with pytest.raises(ValueError, match="message"):
        MailAdapter().reply("", "body")


def test_reply_empty_body_raises():
    import pytest

    from macos_apps_mcp.adapters.mail import MailAdapter

    with pytest.raises(ValueError, match="reply_body"):
        MailAdapter().reply("<abc@x>", "  ")


def test_reply_never_sends():
    # the SAFETY invariant: neither template contains a `send` verb (as opposed to
    # `sender`, which legitimately appears in _ORIGINAL) — a reply can only open a
    # draft window for the human, never send on its own.
    assert not re.search(r"\bsend\b", _ORIGINAL.lower())
    assert not re.search(r"\bsend\b", _REPLY.lower())
    assert "reply (" in _REPLY  # uses Mail's native reply verb (real threading)
    assert "opening window yes" in _REPLY  # opens for human review


def test_reply_cleanup_on_failure_is_in_script():
    # #44: atomicity is enforced INSIDE the osascript — the partial outgoing message is
    # deleted in the error path, structurally (not just present as loose words).
    assert re.search(r"on error errMsg\s+delete r\s+error errMsg", _REPLY), (
        "the on-error handler must delete the partial reply, then re-raise"
    )
