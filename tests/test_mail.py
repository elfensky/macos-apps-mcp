"""Unit tests for the mail adapter — pure parsing helpers (no osascript)."""

from __future__ import annotations

from contextlib import nullcontext

import pytest

from macos_apps_mcp.adapters import mail
from macos_apps_mcp.adapters.mail import (
    MAX_MAILS,
    MailAdapter,
    _deeplink,
    _parse_search_results,
    _summary,
    _validate_mailbox,
)
from macos_apps_mcp.contracts import Pointer
from macos_apps_mcp.text import RS, US


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
    ptrs = _parse_search_results(raw)
    assert len(ptrs) == 2
    assert isinstance(ptrs[0], Pointer)
    assert ptrs[0].id == "abc@host" and ptrs[0].summary == "Invoice — Bob"
    assert ptrs[0].deeplink == "message://%3Cabc@host%3E"
    assert ptrs[1].summary == "Hello"


def test_parse_skips_blank():
    assert _parse_search_results("\n  \n") == []


def test_parse_skips_missing_message_id():
    # a header-less message has no stable RFC822 citation: AppleScript emits "missing
    # value" (or ""), which must be skipped, never a garbage id/deeplink (#61).
    raw = (
        "missing value\tNo header\tSpammer\n\tEmpty id\tNobody\ngood@host\tReal\tBob\n"
    )
    ptrs = _parse_search_results(raw)
    assert [p.id for p in ptrs] == ["good@host"]  # only the message with a real id


def test_parse_sanitizes_control_chars_in_summary():
    # #52: control chars in a subject (which blanked Claude Desktop, carterlasalle #2)
    # must be stripped before the summary reaches the model. NUL/BEL/US are used here
    # because the tab-delimited parser frames records with splitlines(), which would
    # itself split on U+2028/NEL — that framing fragility is pre-existing (a literal
    # newline in a subject splits too) and out of #52's scope; the helper's own
    # U+2028/9 folding is covered in test_runtime.
    raw = "m@host\tInv\x00oice\x1fQ3\x07\tBob\n"
    ptr = _parse_search_results(raw)[0]
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


# --- system-mailbox validation ------------------------------------------------------


def test_validate_mailbox_returns_canonical_lowercase():
    assert _validate_mailbox("  SENT ") == "sent"


def test_validate_mailbox_unknown_raises():
    with pytest.raises(ValueError, match="unknown system mailbox"):
        _validate_mailbox("archive")


def test_validate_mailbox_covers_the_core_five():
    for canonical in ("inbox", "sent", "drafts", "trash", "junk"):
        assert _validate_mailbox(canonical) == canonical


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
    # #43: a freshly opened compose window has no stable Message-ID YET, so
    # create_draft returns a locator (where to find it) instead of a fabricated id.
    # #82/F4 review: once saved to Drafts it DOES get one (drafts()/delete_draft()
    # resolve by it) — the note must point at that recovery path, not claim drafts
    # are permanently unaddressable.
    monkeypatch.setattr("macos_apps_mcp.adapters.mail.run_osascript", lambda *a: "")
    out = MailAdapter().create_draft("x@example.com", "Hi", "body")
    assert out["created"] is True
    assert out["mailbox"] == "Drafts"
    assert out["subject"] == "Hi"
    assert "drafts()" in out["note"]


def test_create_draft_reads_body_through_shared_handler():
    # Bug 1 (device-verified): a bare `read (POSIX file …) as «class utf8»` raises -39
    # ("End of file error") on a ZERO-BYTE file — an empty create_draft body crashed
    # since 0.8.0. The script must compose the shared readBody handler instead of
    # reading directly.
    assert "on readBody(p)" in _CREATE_DRAFT
    assert "my readBody(item 3 of argv)" in _CREATE_DRAFT
    # "read (POSIX file" legitimately appears ONCE, inside the readBody handler itself
    # — the `on run` body must never call it bare (a second, direct occurrence).
    assert _CREATE_DRAFT.count("read (POSIX file") == 1


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

    framed = (
        mail._ORIGINAL,
        mail._ATTACHMENTS,
        mail._INBOX_TRIAGE,
        mail._SENT_TRIAGE,
        mail._REPLY_ALL_RECIPIENTS,
    )
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


def test_reply_reads_body_through_shared_handler():
    # Bug 1: same -39-on-empty-file hazard as _CREATE_DRAFT — _REPLY must compose the
    # shared readBody handler rather than reading the tempfile directly.
    assert "on readBody(p)" in _REPLY
    assert "my readBody(item 2 of argv)" in _REPLY
    assert _REPLY.count("read (POSIX file") == 1  # only inside the handler itself


def test_reply_cleanup_on_failure_is_in_script():
    # #44: atomicity is enforced INSIDE the osascript — the partial outgoing message is
    # deleted in the error path, structurally (not just present as loose words).
    assert re.search(r"on error errMsg\s+delete r\s+error errMsg", _REPLY), (
        "the on-error handler must delete the partial reply, then re-raise"
    )


# --- drafts (#82) ---------------------------------------------------------------


def test_list_drafts_parses_framed_records(monkeypatch):
    raw = (
        f"<a@b.com>{US}Q3 numbers{US}boss@corp.com{RS}"
        f"<c@d.com>{US}Lunch?{US}pal@example.org{RS}"
    )
    monkeypatch.setattr(mail, "run_osascript", lambda *a: raw)
    out = mail.MailAdapter().list_drafts()
    assert [p.id for p in out] == ["<a@b.com>", "<c@d.com>"]
    assert out[0].summary == "Q3 numbers — to boss@corp.com"
    assert out[0].deeplink.startswith("message://")


def test_list_drafts_skips_records_without_message_id(monkeypatch):
    # a draft with no Message-ID has no stable citation — never emit a garbage id.
    raw = f"missing value{US}No id{US}x@y.com{RS}<ok@z>{US}Fine{US}a@b.com{RS}"
    monkeypatch.setattr(mail, "run_osascript", lambda *a: raw)
    assert [p.id for p in mail.MailAdapter().list_drafts()] == ["<ok@z>"]


def test_list_drafts_empty_mailbox(monkeypatch):
    monkeypatch.setattr(mail, "run_osascript", lambda *a: "")
    assert mail.MailAdapter().list_drafts() == []


def test_list_drafts_summary_without_recipient(monkeypatch):
    raw = f"<a@b>{US}Just a subject{US}{RS}"
    monkeypatch.setattr(mail, "run_osascript", lambda *a: raw)
    assert mail.MailAdapter().list_drafts()[0].summary == "Just a subject"


def test_snapshot_returns_pointer_for_known_draft(monkeypatch):
    raw = f"<a@b>{US}Q3 numbers{US}boss@corp.com{RS}"
    monkeypatch.setattr(mail, "run_osascript", lambda *a: raw)
    p = mail.MailAdapter().snapshot("<a@b>")
    assert p.summary == "Q3 numbers — to boss@corp.com"


def test_snapshot_returns_none_for_unknown_id(monkeypatch):
    monkeypatch.setattr(mail, "run_osascript", lambda *a: "")
    assert mail.MailAdapter().snapshot("<nope@nowhere>") is None


def test_delete_draft_dry_run_makes_no_native_call(monkeypatch):
    raw = f"<a@b>{US}Q3 numbers{US}boss@corp.com{RS}"
    calls = []

    def fake(script, *argv):
        calls.append(script)
        return raw

    monkeypatch.setattr(mail, "run_osascript", fake)
    out = mail.MailAdapter().delete_draft("<a@b>", dry_run=True)
    assert out["dry_run"] is True
    assert out["would_delete"]["id"] == "<a@b>"
    # exactly one call — the snapshot read. Never the delete script.
    assert calls == [mail._DRAFTS]


def test_delete_draft_dry_run_unknown_id_raises(monkeypatch):
    monkeypatch.setattr(mail, "run_osascript", lambda *a: "")
    with pytest.raises(ValueError, match="no draft"):
        mail.MailAdapter().delete_draft("<nope@nowhere>", dry_run=True)


def test_delete_draft_deletes_by_message_id(monkeypatch):
    seen = {}

    def fake(script, *argv):
        seen[script] = argv
        return f"<a@b>{US}Q3{US}x@y.com{RS}" if script is mail._DRAFTS else "deleted"

    monkeypatch.setattr(mail, "run_osascript", fake)
    out = mail.MailAdapter().delete_draft("a@b")
    assert out == {"deleted": True, "id": "a@b"}
    assert seen[mail._DELETE_DRAFT] == ("a@b",)


def test_delete_draft_rejects_empty_id():
    with pytest.raises(ValueError, match="draft id"):
        mail.MailAdapter().delete_draft("   ")


# --- M1 review: delete_draft accepts a bracketed id like every other id-taking method -


def test_delete_draft_accepts_bracketed_id(monkeypatch):
    # a caller passing "<id>" (the RFC822-looking form, matching what get_body/reply/
    # reply_all/forward all accept) must resolve — not fail loudly. Brackets are
    # stripped before the id reaches the AppleScript argv.
    seen = {}

    def fake(script, *argv):
        seen[script] = argv
        return f"<a@b>{US}Q3{US}x@y.com{RS}" if script is mail._DRAFTS else "deleted"

    monkeypatch.setattr(mail, "run_osascript", fake)
    out = mail.MailAdapter().delete_draft("<a@b>")
    assert out == {"deleted": True, "id": "a@b"}
    assert seen[mail._DELETE_DRAFT] == ("a@b",)  # bare on the wire, not "<a@b>"


def test_delete_draft_dry_run_resolves_bracketed_id_against_bare_snapshot(monkeypatch):
    # snapshot() must match regardless of whether the caller's id or the stored
    # Pointer.id is bracketed (M1 review) — the dry-run path depends on this.
    raw = f"a@b{US}Q3 numbers{US}boss@corp.com{RS}"  # stored id is BARE
    monkeypatch.setattr(mail, "run_osascript", lambda *a: raw)
    out = mail.MailAdapter().delete_draft("<a@b>", dry_run=True)  # caller id bracketed
    assert out["dry_run"] is True
    assert out["would_delete"]["id"] == "a@b"


# --- send (#83) -------------------------------------------------------------------


def test_split_addrs_accepts_string_and_list():
    assert mail._split_addrs("a@b.com, c@d.com") == ["a@b.com", "c@d.com"]
    assert mail._split_addrs(["a@b.com", " c@d.com "]) == ["a@b.com", "c@d.com"]
    assert mail._split_addrs(None) == []
    assert mail._split_addrs(" , ") == []


def test_split_addrs_strips_unit_separator_injection():
    # F1 review: a literal U+001F (the wire's own field separator, US) embedded in an
    # address must NOT survive into the list — otherwise US.join(...) on the result
    # produces a string that _SEND's `text items of` (which splits on US) parses back
    # into TWO recipients, even though this function only ever emitted one entry.
    # Written as an explicit \u001f escape (never a literal control glyph in source),
    # and asserted on the actual bytes of the result.
    injected = "alice@corp.com\u001fexfil@evil.tld"
    out = mail._split_addrs(injected)
    assert out == ["alice@corp.comexfil@evil.tld"]  # ONE entry — the US byte is gone
    assert "\u001f" not in out[0]
    # the wire-level invariant this exists to protect: joining the result and
    # re-splitting on US (exactly what _SEND's AppleScript does) must yield the SAME
    # count as the parsed list — no smuggled extra recipient.
    joined = mail.US.join(out)
    assert len(joined.split(mail.US)) == len(out) == 1


def test_send_dry_run_preview_matches_argv_recipient_set(monkeypatch):
    # F1 review: the dry-run preview (what the model sees before deciding to send) and
    # the argv actually handed to run_osascript (what Mail actually sends to) must
    # describe the SAME recipient set — an injected \u001f must not let them diverge
    # (the preview showing ONE recipient while the wire actually carries TWO).
    seen = {}

    def fake(script, *argv):
        # a real send now makes TWO calls: _SEND, then the outbox truth-check
        # (_OUTBOX_COUNT). Dispatch on script identity so the outbox call (whose
        # argv is empty) can't clobber the _SEND argv this test cares about.
        if script is mail._SEND:
            seen["argv"] = argv
            return "sent"
        return "0"

    # Patched BEFORE the first send() call below: that call is dry_run=True by
    # default and relies on the early return to never reach run_osascript, but
    # patching up front means a regression in that early return fails loudly here
    # instead of firing a real osascript send into Mail.app under a plain
    # `uv run pytest`.
    monkeypatch.setattr(mail, "run_osascript", fake)

    injected_to = "alice@corp.com\u001fexfil@evil.tld"
    preview = mail.MailAdapter().send(injected_to, "Hi", "body")
    previewed_to = preview["would_send"]["to"]
    assert previewed_to == ["alice@corp.comexfil@evil.tld"]

    mail.MailAdapter().send(injected_to, "Hi", "body", dry_run=False)
    _subj, _path, _html, _from, to_j, _cc_j, _bcc_j = seen["argv"]
    wire_to = [a for a in to_j.split(mail.US) if a]
    assert wire_to == previewed_to  # preview and wire agree by construction


def test_send_dry_run_touches_nothing(monkeypatch):
    # A dry run must make NO native call: constructing an outgoing message can strand an
    # autosaved copy in Drafts even when the script deletes it (device-verified). This
    # is the load-bearing safety invariant for `send` — the most dangerous of the three
    # outbound paths — mirroring the equivalent guard on forward below. reply_all is a
    # documented exception (#129): its dry run DOES make one native call, a read of the
    # original message's recipients — see test_reply_all_dry_run_reads_recipients_only.
    def boom(*a, **k):
        raise AssertionError("dry run must not call osascript")

    monkeypatch.setattr(mail, "run_osascript", boom)
    out = mail.MailAdapter().send(
        "a@b.com", "Hi", "body text", cc="c@d.com", from_address="me@corp.com"
    )
    assert out == {
        "dry_run": True,
        "would_send": {
            "to": ["a@b.com"],
            "cc": ["c@d.com"],
            "bcc": [],
            "from": "me@corp.com",
            "subject": "Hi",
            "body_chars": 9,
            "html": False,
        },
    }


def test_send_dry_run_reports_default_account_when_from_omitted(monkeypatch):
    monkeypatch.setattr(mail, "run_osascript", lambda *a: "")
    out = mail.MailAdapter().send("a@b.com", "Hi", "x")
    # Mail's default sender is NOT predictable from account order (device-verified), so
    # never report a computed guess.
    assert out["would_send"]["from"] == "(Mail default account)"


def test_send_passes_addresses_via_argv_us_joined(monkeypatch):
    seen = {}

    def fake(script, *argv):
        # a real send now dispatches TWO scripts: _SEND, then _OUTBOX_COUNT (#134's
        # outbox truth-check) — recorded separately so asserting the _SEND argv can't
        # be clobbered by the outbox call's (empty) argv.
        if script is mail._SEND:
            seen["send_script"], seen["send_argv"] = script, argv
            return "sent"
        seen["outbox_script"] = script
        return "3"

    monkeypatch.setattr(mail, "run_osascript", fake)
    out = mail.MailAdapter().send(
        "a@b.com,e@f.com",
        "Hi",
        "body",
        cc="c@d.com",
        bcc="x@y.com",
        html=True,
        from_address="me@corp.com",
        dry_run=False,
    )
    assert out["sent"] is True
    # outbox_pending (#134) reports the real outbox count and, when non-zero, a note
    # for the model to relay — a "sent" result alone is not delivery confirmation.
    assert out["outbox_pending"] == 3
    assert "Outbox" in out["note"]
    subj, _path, is_html, from_addr, to_j, cc_j, bcc_j = seen["send_argv"]
    assert (subj, is_html, from_addr) == ("Hi", "1", "me@corp.com")
    assert to_j == f"a@b.com{US}e@f.com"
    assert (cc_j, bcc_j) == ("c@d.com", "x@y.com")
    assert seen["outbox_script"] is mail._OUTBOX_COUNT  # the truth-check ran too


def test_send_reads_body_through_shared_handler():
    # Bug 1 (device-verified): a subject-only send leaves the body tempfile EMPTY,
    # which crashes a bare `read … as «class utf8»` with -39. _SEND must compose the
    # shared readBody handler instead.
    assert "on readBody(p)" in mail._SEND
    assert "my readBody(item 2 of argv)" in mail._SEND
    assert mail._SEND.count("read (POSIX file") == 1  # only inside the handler itself


# --- outbox_pending truth-check (#134) -------------------------------------------


def test_outbox_count_script_counts_the_outgoing_messages():
    # the AppleScript that backs outbox_pending must actually count Mail's outbox and
    # be bounded like every other template in this file.
    assert "count of outgoing messages" in mail._OUTBOX_COUNT
    assert "with timeout of 120 seconds" in mail._OUTBOX_COUNT


def test_outbox_pending_runs_the_count_script(monkeypatch):
    seen = []
    monkeypatch.setattr(mail, "run_osascript", lambda *a: seen.append(a) or "4")
    assert mail._outbox_pending() == 4
    assert seen == [(mail._OUTBOX_COUNT,)]  # no argv — the script needs none


def test_with_outbox_pending_zero_omits_note(monkeypatch):
    monkeypatch.setattr(mail, "run_osascript", lambda *a: "0")
    out = mail._with_outbox_pending({"sent": True})
    assert out == {"sent": True, "outbox_pending": 0}
    assert "note" not in out


def test_with_outbox_pending_nonzero_adds_actionable_note(monkeypatch):
    monkeypatch.setattr(mail, "run_osascript", lambda *a: "2")
    out = mail._with_outbox_pending({"sent": True})
    assert out["outbox_pending"] == 2
    # worded so a model relaying it to a human states delivery is NOT confirmed and
    # points at where to check.
    assert "not confirmed" in out["note"].lower()
    assert "Outbox" in out["note"]


def test_send_rejects_missing_recipient():
    with pytest.raises(ValueError, match="recipient"):
        mail.MailAdapter().send("  ", "Hi", "body", dry_run=False)


def test_send_rejects_empty_subject_and_body():
    with pytest.raises(ValueError, match="subject or a body"):
        mail.MailAdapter().send("a@b.com", "", "", dry_run=False)


def test_reply_all_dry_run_reads_recipients_only(monkeypatch):
    # #129: reply_all's dry run is a documented exception to the "no native call" rule
    # — it reads the original message's recipients (a read strands nothing) but must
    # NEVER reach the send script (_REPLY_ALL) itself.
    seen = []

    def fake(script, *argv):
        seen.append(script)
        if script is mail._REPLY_ALL_RECIPIENTS:
            return (
                f"to{US}alice@corp.com{RS}to{US}bob@corp.com{RS}"
                f"cc{US}carol@corp.com{RS}sender{US}orig-sender@corp.com{RS}"
            )
        raise AssertionError(f"dry run must not call {script!r} (the send script)")

    monkeypatch.setattr(mail, "run_osascript", fake)
    out = mail.MailAdapter().reply_all("<orig@x>", "Sounds good")
    assert out == {
        "dry_run": True,
        "would_send": {
            "to": ["alice@corp.com", "bob@corp.com"],
            "cc": ["carol@corp.com"],
            "reply_to": "<orig@x>",
            "reply_all": True,
            "body_chars": 11,
            "include_quote": True,
        },
    }
    assert seen == [mail._REPLY_ALL_RECIPIENTS]  # exactly one call — the read, only


def test_reply_all_sends_with_quote(monkeypatch):
    seen = {}
    bodies = {}

    def fake(script, *argv):
        seen[script] = argv
        if script is mail._ORIGINAL:
            return f"Boss <boss@corp.com>{US}Tue, 1 Jul 2026{US}Original text"
        # #134: reply_all now also runs the outbox truth-check (_OUTBOX_COUNT)
        # after _REPLY_ALL — return a real count for it, "sent" for _REPLY_ALL.
        if script is mail._OUTBOX_COUNT:
            return "0"
        return "sent"

    def fake_body_file(text):
        bodies["text"] = text
        return nullcontext("/tmp/fake-body")

    monkeypatch.setattr(mail, "run_osascript", fake)
    monkeypatch.setattr(mail, "body_file", fake_body_file)
    out = mail.MailAdapter().reply_all("<orig@x>", "Sounds good", dry_run=False)
    assert out == {
        "sent": True,
        "reply_to": "<orig@x>",
        "reply_all": True,
        "outbox_pending": 0,
    }
    assert "note" not in out  # zero pending: no caveat needed
    assert bodies["text"].startswith("Sounds good")
    assert "> Original text" in bodies["text"]
    assert seen[mail._REPLY_ALL] == ("orig@x", "/tmp/fake-body")
    assert seen[mail._OUTBOX_COUNT] == ()  # the truth-check ran, with no args


def test_reply_all_reads_body_through_shared_handler():
    # Bug 1: same -39-on-empty-file hazard — _REPLY_ALL must compose the shared
    # readBody handler rather than reading the tempfile directly.
    assert "on readBody(p)" in mail._REPLY_ALL
    assert "my readBody(item 2 of argv)" in mail._REPLY_ALL
    # only inside the handler itself
    assert mail._REPLY_ALL.count("read (POSIX file") == 1


def test_reply_all_rejects_empty_body():
    with pytest.raises(ValueError, match="non-empty"):
        mail.MailAdapter().reply_all("<orig@x>", "   ", dry_run=False)


def test_forward_dry_run_reports_recipients(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("dry run must not call osascript")

    monkeypatch.setattr(mail, "run_osascript", boom)
    out = mail.MailAdapter().forward("<orig@x>", "a@b.com, c@d.com")
    assert out["dry_run"] is True
    assert out["would_send"] == {
        "to": ["a@b.com", "c@d.com"],
        "forwarding": "<orig@x>",
    }


def test_forward_sends_via_argv(monkeypatch):
    # forward carries NO body/note — its argv is just (message id, US-joined
    # recipients); no tempfile is ever created for it.
    seen = {}

    def fake(script, *argv):
        seen[script] = argv
        # #134: forward now also runs the outbox truth-check (_OUTBOX_COUNT) after
        # _FORWARD — it must return a real count, not the opaque "sent" _FORWARD uses.
        if script is mail._OUTBOX_COUNT:
            return "2"
        return "sent"

    monkeypatch.setattr(mail, "run_osascript", fake)
    out = mail.MailAdapter().forward("<orig@x>", "a@b.com", dry_run=False)
    assert out["sent"] is True
    assert out["to"] == ["a@b.com"]
    assert out["forwarding"] == "<orig@x>"
    assert out["outbox_pending"] == 2
    assert "Outbox" in out["note"]  # non-zero pending: caveat included
    assert seen[mail._FORWARD] == ("orig@x", "a@b.com")
    assert seen[mail._OUTBOX_COUNT] == ()  # the truth-check ran, with no args


def test_forward_rejects_missing_recipient():
    with pytest.raises(ValueError, match="recipient"):
        mail.MailAdapter().forward("<orig@x>", "", dry_run=False)


def test_forward_script_never_touches_content():
    # Bug 2 (device-verified): writing `content` of a forward is both a no-op read
    # (the original is permanently unreadable via AppleScript) and destructive
    # (writing it at all strips every attachment — a real 7-attachment forward was
    # delivered with 0 once `content` was touched). _FORWARD must never set it.
    assert "set content of" not in mail._FORWARD
