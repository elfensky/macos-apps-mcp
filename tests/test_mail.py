"""Unit tests for the mail adapter — pure parsing helpers (no osascript)."""

from __future__ import annotations

from contextlib import nullcontext

import pytest

from macos_apps_mcp.adapters import mail, mail_addressing
from macos_apps_mcp.adapters.mail import (
    MAX_MAILS,
    MailAdapter,
    _deeplink,
    _parse_search_results,
    _summary,
)
from macos_apps_mcp.contracts import Pointer
from macos_apps_mcp.errors import BatchTooLarge
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


def test_parse_framed_records():
    raw = f"abc@host{US}Invoice{US}Bob{RS}<def@host>{US}Hello{US}{RS}"
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
        f"missing value{US}No header{US}Spammer{RS}"
        f"{US}Empty id{US}Nobody{RS}"
        f"good@host{US}Real{US}Bob{RS}"
    )
    ptrs = _parse_search_results(raw)
    assert [p.id for p in ptrs] == ["good@host"]  # only the message with a real id


def test_parse_survives_newline_in_subject():
    # US/RS framing (C4-B): a literal newline in a subject no longer splits the
    # record — the old tab/linefeed wire broke here — and clean_summary folds it.
    raw = f"m@host{US}Line one\nline two{US}Bob{RS}"
    ptr = _parse_search_results(raw)[0]
    assert ptr.summary == "Line one line two — Bob"


def test_parse_sanitizes_control_chars_in_summary():
    # #52: control chars in a subject (which blanked Claude Desktop, carterlasalle #2)
    # must be stripped before the summary reaches the model. (A raw US/RS byte in a
    # subject never reaches the parser — the template's stripFraming removes it.)
    raw = f"m@host{US}Inv\x00oice Q3\x07{US}Bob{RS}"
    ptr = _parse_search_results(raw)[0]
    assert ptr.summary == "Invoice Q3 — Bob"
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
    assert mail_addressing.validate_mailbox("  SENT ") == "sent"


def test_validate_mailbox_unknown_raises():
    with pytest.raises(ValueError, match="unknown mailbox"):
        mail_addressing.validate_mailbox("archive")


def test_validate_mailbox_covers_the_core_five():
    for canonical in ("inbox", "sent", "drafts", "trash", "junk"):
        assert mail_addressing.validate_mailbox(canonical) == canonical


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
    out = MailAdapter().get_body("<abc@host>", "inbox")
    assert out == "Hello body"  # NUL stripped by clean_body
    assert seen["call"][0] is _BODY
    assert seen["call"][1] == ("abc@host", "", "inbox")  # bare id + mailbox via argv


def test_get_body_empty_id_raises():
    with pytest.raises(ValueError, match="message id"):
        MailAdapter().get_body("   ", "inbox")


def test_get_body_missing_value_is_not_surfaced_as_body(monkeypatch):
    # #62 review: an HTML-only / not-yet-downloaded message yields AppleScript `missing
    # value`, coerced to the literal string — it must NOT be handed back as the body.
    from macos_apps_mcp.errors import NativeError

    monkeypatch.setattr(
        "macos_apps_mcp.adapters.mail.run_osascript", lambda *a: "missing value"
    )
    with pytest.raises(NativeError, match="not available locally"):
        MailAdapter().get_body("abc@host", "inbox")


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
        MailAdapter().get_body("abc@host", "inbox")


def test_create_draft_never_sends():
    # the SAFETY invariant: the draft script has NO `send` verb anywhere — it can only
    # create-and-open, never send (joshrutkowski's two-tier gate; the #62 acceptance).
    # Anchored on the VERB, not the substring: the shared #135 rollback preamble prose
    # contains the word "sends", and a bare substring check would fail on that while
    # still not proving anything about the verb.
    assert not re.search(r"^\s*send \w+\s*$", _CREATE_DRAFT, re.M)
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
    # deleted in the error path. Assert the STRUCTURE (the rollback between `on error`
    # and the re-raise), not just the words: a substring check would pass even if the
    # block were gutted and a stray "delete"/"on error" comment left behind (#43/#44
    # review). Since #135 the delete goes through the VERIFYING rollback handler, so the
    # structure is `on error` -> rollback -> re-raise either way.
    assert re.search(
        r"on error errMsg\s+if my rollback\(msg\) then\s+error errMsg", _CREATE_DRAFT
    ), "the on-error handler must roll back the partial draft, then re-raise"


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
        f"<a@x>{us}Logo files{us}LOGO.zip{us}1200000{us}true"
        f"{us}spec.pdf{us}0{us}false{rs}"
        f"{us}No attach subject{rs}"
    )
    out = _parse_attachments(raw)
    assert out[0]["summary"] == "Logo files"
    assert out[0]["attachments"] == [
        {"name": "LOGO.zip", "size": 1200000, "downloaded": True},
        {"name": "spec.pdf", "size": 0, "downloaded": False},
    ]
    assert out[1]["summary"] == "No attach subject"
    assert out[1]["attachments"] == []
    # #155: the row is addressable — id + deeplink — and an unsaved draft (blank id) is
    # still listed rather than dropped, but gets NO deeplink to a message that has none.
    assert out[0]["id"] == "<a@x>"
    assert out[0]["deeplink"] == "message://%3Ca@x%3E"
    assert out[1]["id"] == ""
    assert "deeplink" not in out[1]


def test_list_attachments_resolves_mailbox_and_caps(monkeypatch):
    import macos_apps_mcp.adapters.mail as mail

    captured = {}

    def fake(script, *args):
        captured["script"] = script
        captured["args"] = args
        # more records than MAX_MAILS — the cap must actually bite
        records = "".join(
            f"<m{i}@x>\x1fLogo files {i}\x1fLOGO.zip\x1f100\x1ftrue\x1e"
            for i in range(mail.MAX_MAILS + 5)
        )
        return records

    monkeypatch.setattr(mail, "run_osascript", fake)
    out = mail.MailAdapter().list_attachments("drafts", "Logo")
    # query, cap, the (account, path) mailbox pair and the (empty) message-id travel via
    # argv — no localized candidates (the unified `drafts mailbox` accessor is
    # locale-independent), and an empty account id is what selects that unified branch
    # in the shared resolver
    assert captured["args"] == ("Logo", str(mail.MAX_MAILS), "", "drafts", "")
    assert len(out["results"]) == mail.MAX_MAILS
    # #156: at the cap and NOT complete — the caller must be able to tell.
    assert out["truncated"] is True


def test_list_attachments_empty_query_lists_all(monkeypatch):
    import macos_apps_mcp.adapters.mail as mail

    def fake(script, *args):
        return (
            "<1@x>\x1fFirst\x1fa.pdf\x1f10\x1ftrue\x1e"
            "<2@x>\x1fSecond\x1fb.pdf\x1f20\x1ffalse\x1e"
            "<3@x>\x1fThird\x1e"
        )

    monkeypatch.setattr(mail, "run_osascript", fake)
    out = mail.MailAdapter().list_attachments("inbox")
    assert [r["summary"] for r in out["results"]] == ["First", "Second", "Third"]
    # #155: the mailbox the caller passed is echoed back, so each row round-trips on its
    # own into mail_body / a future save-attachment tool.
    assert {r["folder"] for r in out["results"]} == {"inbox"}
    # under the cap: no truncation claim either way
    assert "truncated" not in out


def test_list_attachments_unknown_mailbox_raises():
    import pytest

    from macos_apps_mcp.adapters.mail import MailAdapter

    with pytest.raises(ValueError, match="unknown mailbox"):
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
    out = mail.MailAdapter().reply("<abc@x>", "inbox", "thanks", include_quote=True)
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
    # copy drifted. Every template that emits US/RS-framed free text must COMPOSE the
    # single STRIP_FRAMING constant — exactly one handler definition per script.
    #
    # DISCOVERED, not enumerated: the old hand-listed tuple named 5 of mail's 8 framed
    # templates and none of the other adapters', so the five C4-B conversions adopted an
    # invariant nothing checked. Walking the modules means a NEW template is covered the
    # day it is written, which a list cannot promise.
    import importlib

    from macos_apps_mcp.text import STRIP_FRAMING

    checked = []
    for name in ("mail", "messages", "notes", "photos", "safari", "music", "contacts"):
        mod = importlib.import_module(f"macos_apps_mcp.adapters.{name}")
        for attr in dir(mod):
            tpl = getattr(mod, attr)
            if not isinstance(tpl, str) or "on stripFraming" not in tpl:
                continue
            if attr == "STRIP_FRAMING":  # the constant itself, not a template
                continue
            assert tpl.startswith(STRIP_FRAMING), (
                f"{name}.{attr} carries a stripFraming handler that is not the shared "
                "constant — a pasted copy can drift (a6ce7fd)"
            )
            assert tpl.count("on stripFraming") == 1, (
                f"{name}.{attr} defines the handler more than once"
            )
            checked.append(f"{name}.{attr}")

    # guard the guard: if discovery silently matches nothing, the test goes vacuous
    assert len(checked) >= 10, f"expected to find framed templates, found {checked}"
    assert any(c.startswith("messages.") for c in checked), checked
    assert "mail._SEARCH" in checked, checked


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
    mail.MailAdapter().reply("<abc@x>", "inbox", "my reply", include_quote=True)
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
    out = mail.MailAdapter().reply("<abc@x>", "inbox", "my reply", include_quote=True)
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
    mail.MailAdapter().reply("<abc@x>", "inbox", "just this", include_quote=False)
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
    out = mail.MailAdapter().reply("<abc@x>", "inbox", "my reply", include_quote=True)
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
    mail.MailAdapter().reply("<abc@x>", "inbox", "body", include_quote=False)
    assert paths and not os.path.exists(paths[0])


def test_reply_empty_id_raises():
    import pytest

    from macos_apps_mcp.adapters.mail import MailAdapter

    with pytest.raises(ValueError, match="message"):
        MailAdapter().reply("", "inbox", "body")


def test_reply_empty_body_raises():
    import pytest

    from macos_apps_mcp.adapters.mail import MailAdapter

    with pytest.raises(ValueError, match="reply_body"):
        MailAdapter().reply("<abc@x>", "inbox", "  ")


def test_reply_never_sends():
    # the SAFETY invariant: neither template contains a `send` VERB (as opposed to
    # `sender`, which legitimately appears in _ORIGINAL, or the #135 rollback preamble's
    # prose, which mentions sending) — a reply can only open a draft window for the
    # human, never send on its own. Anchored on the verb in statement position.
    assert not re.search(r"^\s*send \w+\s*$", _ORIGINAL, re.M)
    assert not re.search(r"^\s*send \w+\s*$", _REPLY, re.M)
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
    # deleted in the error path, structurally (not just present as loose words). Since
    # #135 that delete goes through the verifying rollback handler.
    assert re.search(
        r"on error errMsg\s+if my rollback\(r\) then\s+error errMsg", _REPLY
    ), "the on-error handler must roll back the partial reply, then re-raise"


# --- drafts (#82) ---------------------------------------------------------------


def test_list_drafts_parses_framed_records(monkeypatch):
    raw = (
        f"<a@b.com>{US}Q3 numbers{US}boss@corp.com{RS}"
        f"<c@d.com>{US}Lunch?{US}pal@example.org{RS}"
    )
    monkeypatch.setattr(mail, "run_osascript", lambda *a: raw)
    out = mail.MailAdapter().list_drafts()["results"]
    assert [p["id"] for p in out] == ["<a@b.com>", "<c@d.com>"]
    assert out[0]["summary"] == "Q3 numbers — to boss@corp.com"
    assert out[0]["deeplink"].startswith("message://")


def test_list_drafts_skips_records_without_message_id(monkeypatch):
    # a draft with no Message-ID has no stable citation — never emit a garbage id.
    raw = f"missing value{US}No id{US}x@y.com{RS}<ok@z>{US}Fine{US}a@b.com{RS}"
    monkeypatch.setattr(mail, "run_osascript", lambda *a: raw)
    assert [p["id"] for p in mail.MailAdapter().list_drafts()["results"]] == ["<ok@z>"]


def test_list_drafts_empty_mailbox(monkeypatch):
    monkeypatch.setattr(mail, "run_osascript", lambda *a: "")
    assert mail.MailAdapter().list_drafts() == {"results": []}


def test_list_drafts_summary_without_recipient(monkeypatch):
    raw = f"<a@b>{US}Just a subject{US}{RS}"
    monkeypatch.setattr(mail, "run_osascript", lambda *a: raw)
    out = mail.MailAdapter().list_drafts()["results"]
    assert out[0]["summary"] == "Just a subject"


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
    assert out == {"deleted": "a@b"}  # C5d: the ONE deletion envelope
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
    assert out == {"deleted": "a@b"}  # C5d envelope; id bare like the wire
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
    # the AppleScript that backs outbox_pending must count Mail's REAL send queue (see
    # test_outbox_count_reads_the_real_queue_not_session_objects for why that is
    # `messages of outbox` and not `outgoing messages`) and be bounded like every other
    # template in this file.
    assert "count of (messages of outbox)" in mail._OUTBOX_COUNT
    assert "with timeout of 120 seconds" in mail._OUTBOX_COUNT


def test_outbox_pending_runs_the_count_script(monkeypatch):
    seen = []
    monkeypatch.setattr(mail, "run_osascript", lambda *a: seen.append(a) or "4")
    assert mail._outbox_pending() == 4
    assert seen == [(mail._OUTBOX_COUNT,)]  # no argv — the script needs none


def test_with_outbox_pending_failure_degrades_to_unknown_not_error(monkeypatch):
    """The truth-check runs AFTER Mail accepted the send. If that follow-up READ
    fails (a timeout counting the outbox), raising turns a COMPLETED send into a
    reported failure — and a model that retries a "failed" send sends the mail
    twice. Same principle as never rolling back past the `send` verb, applied to
    the reporting side: degrade to unknown + note, never an error."""
    from macos_apps_mcp.errors import NativeError

    def boom(*a):
        raise NativeError("timeout counting outbox")

    monkeypatch.setattr(mail, "run_osascript", boom)
    out = mail._with_outbox_pending({"sent": True})
    assert out["sent"] is True
    assert out["outbox_pending"] is None  # unknown, never a fake clean 0
    assert "not confirmed" in out["note"].lower()
    assert "Outbox" in out["note"]


def test_send_still_reports_sent_when_outbox_count_fails(monkeypatch):
    # end-to-end guard: the NativeError from the outbox read must not escape send().
    from macos_apps_mcp.errors import NativeError

    def fake(script, *argv):
        if script is mail._SEND:
            return "sent"
        raise NativeError("timeout counting outbox")

    monkeypatch.setattr(mail, "run_osascript", fake)
    out = mail.MailAdapter().send("a@b.com", "Hi", "body", dry_run=False)
    assert out["sent"] is True
    assert out["outbox_pending"] is None


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
    out = mail.MailAdapter().reply_all("<orig@x>", "inbox", "Sounds good")
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
    out = mail.MailAdapter().reply_all(
        "<orig@x>", "inbox", "Sounds good", dry_run=False
    )
    assert out == {
        "sent": True,
        "reply_to": "<orig@x>",
        "reply_all": True,
        "outbox_pending": 0,
    }
    assert "note" not in out  # zero pending: no caveat needed
    assert bodies["text"].startswith("Sounds good")
    assert "> Original text" in bodies["text"]
    assert seen[mail._REPLY_ALL] == ("orig@x", "/tmp/fake-body", "", "inbox")
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
        mail.MailAdapter().reply_all("<orig@x>", "inbox", "   ", dry_run=False)


def test_forward_dry_run_reports_recipients(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("dry run must not call osascript")

    monkeypatch.setattr(mail, "run_osascript", boom)
    out = mail.MailAdapter().forward("<orig@x>", "inbox", "a@b.com, c@d.com")
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
    out = mail.MailAdapter().forward("<orig@x>", "inbox", "a@b.com", dry_run=False)
    assert out["sent"] is True
    assert out["to"] == ["a@b.com"]
    assert out["forwarding"] == "<orig@x>"
    assert out["outbox_pending"] == 2
    assert "Outbox" in out["note"]  # non-zero pending: caveat included
    assert seen[mail._FORWARD] == ("orig@x", "a@b.com", "", "inbox")
    assert seen[mail._OUTBOX_COUNT] == ()  # the truth-check ran, with no args


def test_forward_rejects_missing_recipient():
    with pytest.raises(ValueError, match="recipient"):
        mail.MailAdapter().forward("<orig@x>", "inbox", "", dry_run=False)


def test_forward_script_never_touches_content():
    # Bug 2 (device-verified): writing `content` of a forward is both a no-op read
    # (the original is permanently unreadable via AppleScript) and destructive
    # (writing it at all strips every attachment — a real 7-attachment forward was
    # delivered with 0 once `content` was touched). _FORWARD must never set it.
    assert "set content of" not in mail._FORWARD


# --- #135: never delete after send; verify the pre-send rollback ------------------

# the three scripts that hand a message to Mail's `send` verb, vs. the two that roll
# back but never send. Every one of them must roll back through the verifying handler.
_SENDING_SCRIPTS = ("_SEND", "_REPLY_ALL", "_FORWARD")
_ROLLING_BACK_SCRIPTS = _SENDING_SCRIPTS + ("_CREATE_DRAFT", "_REPLY")


@pytest.mark.parametrize("name", _SENDING_SCRIPTS)
def test_send_scripts_never_delete_after_the_send_verb(name):
    # #135, device-verified 2026-07-26: `delete` on a message Mail has already accepted
    # via `send` is a SILENT NO-OP — both `delete <ref>` and `delete outgoing message i`
    # returned cleanly, removed nothing, and the message delivered anyway. A post-send
    # rollback therefore cannot succeed; it can only report a cleanup that never
    # happened. So `send` must sit outside the rollback `try` entirely. This is the test
    # that fails if anyone re-nests it.
    script = getattr(mail, name)
    verb = re.search(r"^\s*send \w+\s*$", script, re.M)
    assert verb, f"{name} has no `send <msg>` verb to anchor on"
    assert "delete" not in script[verb.start() :], (
        f"{name} deletes after `send` — that strands a zombie in Mail's outbox (#135)"
    )


@pytest.mark.parametrize("name", _ROLLING_BACK_SCRIPTS)
def test_rollback_goes_through_the_verifying_handler(name):
    # a bare `delete` reports success whether or not it removed anything, so every
    # rollback path composes the handler and calls it instead.
    script = getattr(mail, name)
    assert "on rollback(msg)" in script, f"{name} lacks the rollback handler"
    assert "my rollback(" in script, f"{name} never calls the rollback handler"


@pytest.mark.parametrize("name", _ROLLING_BACK_SCRIPTS)
def test_rollback_is_the_only_delete_in_a_rollback_script(name):
    # the handler owns the delete; a stray `delete` elsewhere would be an unverified
    # rollback sneaking back in.
    assert getattr(mail, name).count("delete ") == 1


def test_rollback_handler_trusts_only_1728_as_proof_of_deletion():
    # device-verified: a successfully deleted outgoing message's reference goes DEAD,
    # and reading a property off it raises -1728. Any OTHER error (a timeout, say)
    # leaves the outcome unknown — and unknown must never be reported as a clean
    # rollback, or we hand the caller the reassuring lie this issue is made of.
    assert "delete msg" in mail._ROLLBACK
    assert "-1728" in mail._ROLLBACK
    assert "return false" in mail._ROLLBACK  # still readable => the delete did not take


@pytest.mark.parametrize("name", _ROLLING_BACK_SCRIPTS)
def test_unverified_rollback_warns_about_the_leftover(name):
    # when the handler returns false the original error still propagates, but it carries
    # the fact that a partial message may remain — and where to look for it. Both
    # warning
    # texts live in the shared preamble, so assert the CALL SITE: a script that sends
    # leaves an outbox leftover, one that only drafts leaves a Drafts leftover. Checking
    # for the words themselves would pass vacuously on every script.
    script = getattr(mail, name)
    expected = (
        "my outgoingLeftover()" if name in _SENDING_SCRIPTS else "my draftLeftover()"
    )
    assert expected in script
    assert "error errMsg" in script  # the ORIGINAL failure still propagates


def test_outbox_count_reads_the_real_queue_not_session_objects():
    # #135, device-verified 2026-07-26 by sampling BOTH counters across one real send:
    # `count of outgoing messages` counts script-created message OBJECTS alive in Mail's
    # session — including already-delivered ones — and read 2 before the send and 2 for
    # ten seconds after, never moving. `messages of outbox` is the real queue: 0 -> 1 on
    # send, back to 0 within ~10s on delivery. Counting objects (how #134 shipped) means
    # a permanent non-zero after the session's first send, so the "delivery is NOT
    # confirmed" note fires on every later send forever and trains the caller to ignore
    # the one signal that matters.
    assert "messages of outbox" in mail._OUTBOX_COUNT
    assert "count of outgoing messages" not in mail._OUTBOX_COUNT


# --- #133: the autosave limit is documented, not silently claimed away ---------------


def test_send_tools_document_the_unsuppressable_autosave():
    # #133, device-verified 2026-07-26: Mail autosaves ANY outgoing message into Drafts
    # ~10-15s after creation, asynchronously — verified across a delete, a rollback AND
    # a fully successful send, and unsuppressed by all five construction/teardown
    # variants tried (one-shot `with properties`, post-creation writes, visible:true,
    # visible:false, `close … saving no`). It cannot be swept safely either: an outgoing
    # message has no readable `message id` (-1700) and the draft's id is only assigned
    # at autosave, so matching would have to guess by subject and could delete a real
    # draft. Since the behaviour cannot be fixed, it MUST be documented where the caller
    # reads it — the tool docstring is the MCP tool description.
    from macos_apps_mcp import server

    for tool in (server.send_mail, server.reply_all, server.forward_mail):
        doc = tool.__doc__ or ""
        assert "#133" in doc, f"{tool.__name__} does not document the autosave"
        assert "delete_draft" in doc, f"{tool.__name__} omits the recovery path"


def test_atomicity_comments_do_not_overclaim():
    # the #44 comments used to promise "a retry can't strand a duplicate draft". That is
    # false (see above), and a false safety claim in a comment is worse than none — it
    # is what let #133 sit misdiagnosed. Assert the claim stays retired.
    assert "retry can't strand a duplicate" not in mail.__doc__
    assert "retry can't strand a duplicate" not in mail._CREATE_DRAFT
    assert "#133" in mail.__doc__  # the real limit is stated instead


# Real account UUIDs: _resolve_account short-circuits on the 8-4-4-4-12 shape, so a
# placeholder like "UUID-1" would silently exercise the osascript path instead.
_UUID_1 = "11111111-2222-3333-4444-555555555555"
_UUID_2 = "66666666-7777-8888-9999-000000000000"


# _ACCOUNT_MAP_CACHE is a process-wide global: set it via monkeypatch (restored at
# teardown), never by plain assignment, or one test's cache silently satisfies the next.
def test_account_map_parses_osascript_pairs(monkeypatch):
    import macos_apps_mcp.adapters.mail_addressing as ma

    monkeypatch.setattr(ma, "_ACCOUNT_MAP_CACHE", None)
    monkeypatch.setattr(
        ma, "run_osascript", lambda *a: f"{_UUID_1}\x1fPersonal\x1e{_UUID_2}\x1fGoogle"
    )
    assert ma.account_map() == {_UUID_1: "Personal", _UUID_2: "Google"}


def test_account_map_empty_when_mail_unreachable(monkeypatch):
    import macos_apps_mcp.adapters.mail_addressing as ma
    from macos_apps_mcp.errors import NativeError

    monkeypatch.setattr(ma, "_ACCOUNT_MAP_CACHE", None)

    def boom(*a):
        raise NativeError("Automation denied")

    monkeypatch.setattr(ma, "run_osascript", boom)
    # a cosmetic label must never fail the call that wanted counts
    assert ma.account_map() == {}


def test_account_map_empty_success_is_leashed_not_cached_forever(monkeypatch):
    """The 872767d symptom, reachable through the branch that fix didn't touch: Mail
    launched at login can RETURN (exit 0) with no account records yet. That empty map
    took the success path — cached forever, failure leash explicitly cleared — so
    mail_overview showed raw UUIDs and mail_search(account=name) raised for the
    daemon's whole life. An empty success is indistinguishable from that transient,
    so it gets the same TTL leash a failure does."""
    import macos_apps_mcp.adapters.mail_addressing as ma

    now = [1_000.0]
    monkeypatch.setattr(ma.time, "monotonic", lambda: now[0])
    calls = []

    def warming_up(*a):
        calls.append(a)
        return "" if len(calls) == 1 else f"{_UUID_1}\x1fPersonal"

    monkeypatch.setattr(ma, "run_osascript", warming_up)
    assert ma.account_map() == {}
    now[0] += ma._ACCOUNT_MAP_FAILURE_TTL - 1  # inside the TTL: no re-spawn
    assert ma.account_map() == {}
    assert len(calls) == 1
    now[0] += 1  # TTL elapsed: one more attempt, and the real names come back
    assert ma.account_map() == {_UUID_1: "Personal"}
    assert len(calls) == 2


def test_resolve_account_duplicate_display_names_raise_ambiguous(monkeypatch):
    """Two accounts named 'Work' resolved silently to whichever Mail listed first —
    the docstring's own rule ('a confident wrong answer is worse than a typed
    error') applied to the unresolvable case but not the ambiguous one. #55's
    AmbiguousTarget names the candidate UUIDs so the caller can re-issue."""
    import macos_apps_mcp.adapters.mail_addressing as ma
    from macos_apps_mcp.errors import AmbiguousTarget

    monkeypatch.setattr(ma, "_ACCOUNT_MAP_CACHE", {_UUID_1: "Work", _UUID_2: "work"})
    with pytest.raises(AmbiguousTarget, match=_UUID_1):
        ma.resolve_account("Work")


def test_account_map_caches_the_failure_too(monkeypatch):
    """Automation denied is cached like a success — for a bit (see
    _ACCOUNT_MAP_FAILURE_TTL): within that window, a second call must not re-spawn
    osascript, whose script waits `with timeout of 120 seconds`."""
    import macos_apps_mcp.adapters.mail_addressing as ma
    from macos_apps_mcp.errors import NativeError

    monkeypatch.setattr(ma, "_ACCOUNT_MAP_CACHE", None)
    monkeypatch.setattr(ma, "_ACCOUNT_MAP_FAILURE_AT", None)
    now = [1_000.0]
    monkeypatch.setattr(ma.time, "monotonic", lambda: now[0])
    calls = []

    def boom(*a):
        calls.append(a)
        raise NativeError("Automation denied")

    monkeypatch.setattr(ma, "run_osascript", boom)
    assert ma.account_map() == {}
    now[0] += ma._ACCOUNT_MAP_FAILURE_TTL - 1  # still inside the TTL
    assert ma.account_map() == {}
    assert len(calls) == 1


def test_account_map_failure_expires_and_retries(monkeypatch):
    """The bug this fixes: this adapter ships inside a launchd daemon that can run for
    days. Without a TTL, a transient failure — Mail still launching at login, or an
    unanswered Automation prompt — got cached FOREVER: mail_overview kept showing raw
    UUIDs and mail_search(account=...) kept raising even after the user fixed the
    underlying problem, cured only by restarting the daemon. Past the TTL, one more
    attempt is allowed — and if Mail is reachable by then, the real names come back."""
    import macos_apps_mcp.adapters.mail_addressing as ma
    from macos_apps_mcp.errors import NativeError

    monkeypatch.setattr(ma, "_ACCOUNT_MAP_CACHE", None)
    monkeypatch.setattr(ma, "_ACCOUNT_MAP_FAILURE_AT", None)
    now = [1_000.0]
    monkeypatch.setattr(ma.time, "monotonic", lambda: now[0])
    calls = []

    def flaky(*a):
        calls.append(a)
        if len(calls) == 1:
            raise NativeError("Automation denied")
        return f"{_UUID_1}\x1fPersonal"

    monkeypatch.setattr(ma, "run_osascript", flaky)
    assert ma.account_map() == {}
    now[0] += ma._ACCOUNT_MAP_FAILURE_TTL  # TTL fully elapsed
    assert ma.account_map() == {_UUID_1: "Personal"}
    assert len(calls) == 2


def test_account_map_success_survives_past_the_failure_ttl(monkeypatch):
    """The TTL is a FAILURE-only leash — a real success must stay cached forever, the
    same as before this change, or the "success is stable" half of the fix is a lie."""
    import macos_apps_mcp.adapters.mail_addressing as ma

    monkeypatch.setattr(ma, "_ACCOUNT_MAP_CACHE", None)
    monkeypatch.setattr(ma, "_ACCOUNT_MAP_FAILURE_AT", None)
    now = [1_000.0]
    monkeypatch.setattr(ma.time, "monotonic", lambda: now[0])
    calls = []

    def ok(*a):
        calls.append(a)
        return f"{_UUID_1}\x1fPersonal"

    monkeypatch.setattr(ma, "run_osascript", ok)
    assert ma.account_map() == {_UUID_1: "Personal"}
    now[0] += ma._ACCOUNT_MAP_FAILURE_TTL * 100  # far past any failure TTL
    assert ma.account_map() == {_UUID_1: "Personal"}
    assert len(calls) == 1


def test_account_map_leak_repro_a_real_failure_leaks_timestamp(monkeypatch):
    """Regression repro, part A (see `_reset_account_map_globals` in tests/conftest.py).
    Mirrors test_account_map_empty_when_mail_unreachable above: resets
    _ACCOUNT_MAP_CACHE but — deliberately, to reproduce the leak a reviewer found —
    does NOT reset _ACCOUNT_MAP_FAILURE_AT. A real failure sets that global to a
    genuine (unpatched) time.monotonic() reading that nothing in THIS test undoes.
    Must run immediately before part B below; pytest's default file-order execution
    (no randomization plugin in this repo) makes that ordering reliable."""
    import macos_apps_mcp.adapters.mail_addressing as ma
    from macos_apps_mcp.errors import NativeError

    monkeypatch.setattr(ma, "_ACCOUNT_MAP_CACHE", None)

    def boom(*a):
        raise NativeError("Automation denied")

    monkeypatch.setattr(ma, "run_osascript", boom)
    assert ma.account_map() == {}
    # _ACCOUNT_MAP_FAILURE_AT now holds a real time.monotonic() reading, left in place
    # on purpose — part B checks whether that survives into the next test.


def test_account_map_leak_repro_b_stale_failure_must_not_wipe_a_later_cache(
    monkeypatch,
):
    """Part B. Forcing monotonic time far enough forward reproduces "60 real seconds
    elapsed" without an actual sleep. A cache installed here for this test's own
    purposes must survive: before the conftest fix (which resets BOTH
    _ACCOUNT_MAP_CACHE and _ACCOUNT_MAP_FAILURE_AT before every test), the timestamp
    leaked by part A aged out on its own, `_account_map()` wiped THIS test's cache,
    and fell through to run_osascript — which here is treated as a hard failure,
    because in production that call spawns osascript against real Mail.app."""
    import macos_apps_mcp.adapters.mail_addressing as ma

    future = ma.time.monotonic() + ma._ACCOUNT_MAP_FAILURE_TTL + 10
    monkeypatch.setattr(ma.time, "monotonic", lambda: future)
    monkeypatch.setattr(ma, "_ACCOUNT_MAP_CACHE", {"some-uuid": "Personal"})
    monkeypatch.setattr(
        ma,
        "run_osascript",
        lambda *a: pytest.fail("stale failure timestamp wiped a live cache"),
    )
    assert ma.account_map() == {"some-uuid": "Personal"}


def test_resolve_account_maps_name_and_passes_uuid_through(monkeypatch):
    import macos_apps_mcp.adapters.mail_addressing as ma

    monkeypatch.setattr(ma, "_ACCOUNT_MAP_CACHE", None)
    monkeypatch.setattr(ma, "run_osascript", lambda *a: f"{_UUID_1}\x1fPersonal")
    assert ma.resolve_account("Personal") == _UUID_1
    assert ma.resolve_account(_UUID_1) == _UUID_1


def test_resolve_account_uuid_never_contacts_mail(monkeypatch):
    """The UUID path is what lets mail_search/mail_overview keep their "reads the index
    at rest" promise — resolving a NAME runs osascript, which launches Mail."""
    import macos_apps_mcp.adapters.mail_addressing as ma

    monkeypatch.setattr(ma, "_ACCOUNT_MAP_CACHE", None)
    monkeypatch.setattr(
        ma, "run_osascript", lambda *a: pytest.fail("a UUID account launched Mail")
    )
    assert ma.resolve_account(_UUID_1.upper()) == _UUID_1.upper()


def test_resolve_account_unknown_name_raises(monkeypatch):
    """Returning the name unchanged degraded into a substring match over the whole
    mailbox url — account="Business" then matched any account's Business* FOLDER and
    reported it as though the account filter had worked."""
    import macos_apps_mcp.adapters.mail_addressing as ma
    from macos_apps_mcp.errors import NativeError

    monkeypatch.setattr(ma, "_ACCOUNT_MAP_CACHE", {_UUID_1: "Personal"})
    with pytest.raises(NativeError, match="unknown Mail account"):
        ma.resolve_account("Nonexistent")
    with pytest.raises(NativeError, match="Personal"):  # names what DOES exist
        ma.resolve_account("Nonexistent")


def test_resolve_account_unknown_name_error_does_not_misdirect_to_overview(
    monkeypatch,
):
    """The old remediation told the caller to "use the account UUID that mail_overview
    reports" — exactly the value mail_overview stopped reporting once it started
    showing the "On My Mac" friendly name for the local store. The message must point
    at something a caller can actually follow instead."""
    import macos_apps_mcp.adapters.mail_addressing as ma
    from macos_apps_mcp.errors import NativeError

    monkeypatch.setattr(ma, "_ACCOUNT_MAP_CACHE", {_UUID_1: "Personal"})
    with pytest.raises(NativeError) as exc:
        ma.resolve_account("Nonexistent")
    assert "mail_overview reports" not in str(exc.value)


def test_parse_search_absent_subject_falls_through_to_sender():
    # A mail with no subject puts the literal "missing value" on the wire; _summary is
    # `subject or sender or "(no subject)"`, so a truthy bogus subject stopped it ever
    # reaching the sender.
    raw = f"<mid@ex.com>{US}missing value{US}alice@ex.com{RS}"
    assert _parse_search_results(raw)[0].summary == "alice@ex.com"


def test_parse_search_absent_subject_and_sender_use_the_placeholder():
    raw = f"<mid@ex.com>{US}missing value{US}missing value{RS}"
    assert _parse_search_results(raw)[0].summary == "(no subject)"


# --- mailbox scope: any mailbox, not just the inbox (#146) ----------------------------
#
# `mail_search` reads every mailbox via the Envelope Index, but the body/reply/forward/
# attachment scripts were hard-scoped to `messages of inbox` — so a filed message could
# be found and then not opened. The fix: every one of them takes a `mailbox` argument,
# the `folder` value from a search result passed back VERBATIM (an opaque round-trip
# token, NOT a name — requiring a name hands #144's percent-encoding mismatch back to
# the model). `_mailbox_args` is the inverse of `_resolve_mailbox`: url -> the
# (account-id, decoded path) pair the shared `mailboxFor` AppleScript handler needs.

_GMAIL_UUID = "5936B2CE-D3DC-4072-A81B-E79E6DA94B15"
_SPAM_URL = f"imap://{_GMAIL_UUID}/%5BGmail%5D/Spam"


def test_mailbox_args_decodes_the_url_into_account_and_path():
    # device-verified: `mailbox "[Gmail]/Spam" of account …` resolves; the ENCODED
    # spelling ("%5BGmail%5D/Spam") does not — AppleScript wants the decoded path.
    assert mail_addressing.mailbox_args(_SPAM_URL) == (_GMAIL_UUID, "[Gmail]/Spam")


def test_mailbox_args_decodes_spaces_and_leaves_literal_ampersands():
    # live sample: Mail encodes the space but NOT the "&" (Social%20&%20SEO), which is
    # exactly why the url can't be reproduced with quote() and must be round-tripped.
    url = f"imap://{_GMAIL_UUID}/Social%20&%20SEO"
    assert mail_addressing.mailbox_args(url) == (_GMAIL_UUID, "Social & SEO")


def test_mailbox_args_maps_the_local_store_to_the_account_less_sentinel():
    # On My Mac mailboxes hang off the application, not an account — Mail's `every
    # account` never lists that store, so its UUID would never resolve.
    url = "local://A2025935-B0B2-4A77-9003-68EF6E541361/Outbox"
    assert mail_addressing.mailbox_args(url) == ("local", "Outbox")


def test_mailbox_args_still_accepts_the_five_special_names():
    # the alias layer: mail_attachments' existing vocabulary keeps working, and an
    # empty account id selects Mail's unified accessors in the handler.
    for canonical in ("inbox", "sent", "drafts", "trash", "junk"):
        assert mail_addressing.mailbox_args(f"  {canonical.upper()} ") == (
            "",
            canonical,
        )


def test_mailbox_args_rejects_an_empty_mailbox():
    with pytest.raises(ValueError, match="mailbox"):
        mail_addressing.mailbox_args("   ")


def test_mailbox_args_rejects_a_bare_name_and_says_where_to_get_one():
    # a human-readable folder name is exactly the thing that must NOT be accepted —
    # the error has to point at the `folder` field of a search result.
    with pytest.raises(ValueError) as exc:
        mail_addressing.mailbox_args("Leasing")
    assert "folder" in str(exc.value)


def test_mailbox_args_rejects_a_url_with_no_path():
    with pytest.raises(ValueError, match="names no mailbox"):
        mail_addressing.mailbox_args(f"imap://{_GMAIL_UUID}/")


def test_mailbox_args_rejects_a_url_with_no_account():
    with pytest.raises(ValueError, match="no account"):
        mail_addressing.mailbox_args("imap:///Leasing")


_MAILBOX_SCOPED_SCRIPTS = (
    "_ATTACHMENTS",
    "_BODY",
    "_FORWARD",
    "_ORIGINAL",
    "_REPLY",
    "_REPLY_ALL",
    "_REPLY_ALL_RECIPIENTS",
)


@pytest.mark.parametrize("name", _MAILBOX_SCOPED_SCRIPTS)
def test_mailbox_scoped_scripts_resolve_the_mailbox_instead_of_hard_coding_inbox(name):
    """The guard that stops #146 recurring. Each script that addresses a message by id
    must take its mailbox from argv through the ONE shared resolver — not name `inbox`
    itself. This is the assertion whose absence let the #62 inbox scope survive #70/#75
    widening search to every mailbox."""
    script = getattr(mail, name)
    assert script.count("on mailboxFor(") == 1  # composes the shared resolver, once
    assert "my mailboxFor(" in script  # ...and actually calls it
    assert "messages of inbox" not in script  # #146: no hard-coded inbox scope


def test_mailbox_resolver_is_the_only_place_a_mailbox_accessor_is_named():
    # the unified accessors (`sent mailbox`/`drafts mailbox`/…) live in one handler, so
    # the alias layer can't drift apart across seven scripts the way the scope did.
    for name in _MAILBOX_SCOPED_SCRIPTS:
        script = getattr(mail, name)
        body = script.replace(mail_addressing.MAILBOX_REF, "")
        assert "sent mailbox" not in body
        assert "junk mailbox" not in body


def test_get_body_passes_the_mailbox_through_argv(monkeypatch):
    seen = {}

    def fake(script, *a):
        seen["call"] = (script, a)
        return "Filed body"

    monkeypatch.setattr(mail, "run_osascript", fake)
    out = mail.MailAdapter().get_body("<abc@host>", _SPAM_URL)
    assert out == "Filed body"
    assert seen["call"][1] == ("abc@host", _GMAIL_UUID, "[Gmail]/Spam")


def test_get_body_rejects_an_empty_id():
    # #155 made `mailbox` optional — an empty ID is what is left to reject.
    with pytest.raises(ValueError, match="message id"):
        mail.MailAdapter().get_body("  ", "inbox")


def test_reply_passes_the_mailbox_to_both_scripts(monkeypatch):
    # the quote read (_ORIGINAL) and the draft build (_REPLY) must target the SAME
    # mailbox — a reply that quotes nothing because the original wasn't in the inbox
    # is the silent half of this bug.
    seen = {}

    def fake(script, *argv):
        seen[script] = argv
        if script is mail._ORIGINAL:
            return f"Boss <boss@corp.com>{US}Tue, 1 Jul 2026{US}Original text"
        return ""

    monkeypatch.setattr(mail, "run_osascript", fake)
    monkeypatch.setattr(mail, "body_file", lambda text: nullcontext("/tmp/fake-body"))
    mail.MailAdapter().reply("<orig@x>", _SPAM_URL, "Sounds good")
    assert seen[mail._ORIGINAL] == ("orig@x", _GMAIL_UUID, "[Gmail]/Spam")
    assert seen[mail._REPLY] == (
        "orig@x",
        "/tmp/fake-body",
        _GMAIL_UUID,
        "[Gmail]/Spam",
    )


def test_reply_all_dry_run_reads_recipients_from_the_named_mailbox(monkeypatch):
    def fake(script, *argv):
        assert script is mail._REPLY_ALL_RECIPIENTS
        assert argv == ("orig@x", _GMAIL_UUID, "[Gmail]/Spam")
        return f"to{US}alice@corp.com{RS}sender{US}orig@corp.com{RS}"

    monkeypatch.setattr(mail, "run_osascript", fake)
    out = mail.MailAdapter().reply_all("<orig@x>", _SPAM_URL, "Sounds good")
    assert out["would_send"]["to"] == ["alice@corp.com"]


def test_reply_all_send_passes_the_mailbox(monkeypatch):
    seen = {}

    def fake(script, *argv):
        seen[script] = argv
        if script is mail._ORIGINAL:
            return f"Boss <boss@corp.com>{US}Tue, 1 Jul 2026{US}Original text"
        if script is mail._OUTBOX_COUNT:
            return "0"
        return "sent"

    monkeypatch.setattr(mail, "run_osascript", fake)
    monkeypatch.setattr(mail, "body_file", lambda text: nullcontext("/tmp/fake-body"))
    mail.MailAdapter().reply_all("<orig@x>", _SPAM_URL, "ok", dry_run=False)
    assert seen[mail._ORIGINAL] == ("orig@x", _GMAIL_UUID, "[Gmail]/Spam")
    assert seen[mail._REPLY_ALL] == (
        "orig@x",
        "/tmp/fake-body",
        _GMAIL_UUID,
        "[Gmail]/Spam",
    )


def test_forward_passes_the_mailbox(monkeypatch):
    seen = {}

    def fake(script, *argv):
        seen[script] = argv
        return "0" if script is mail._OUTBOX_COUNT else "sent"

    monkeypatch.setattr(mail, "run_osascript", fake)
    mail.MailAdapter().forward("<orig@x>", _SPAM_URL, "a@b.com", dry_run=False)
    assert seen[mail._FORWARD] == (
        "orig@x",
        "a@b.com",
        _GMAIL_UUID,
        "[Gmail]/Spam",
    )


def test_forward_dry_run_still_makes_no_native_call(monkeypatch):
    # the mailbox argument must not tempt the dry run into a resolve-it-first call:
    # constructing an outgoing message is what strands an autosaved draft (#133).
    def boom(*a, **k):
        raise AssertionError("dry run must not call osascript")

    monkeypatch.setattr(mail, "run_osascript", boom)
    out = mail.MailAdapter().forward("<orig@x>", _SPAM_URL, "a@b.com")
    assert out["dry_run"] is True


def test_list_attachments_reaches_a_user_folder(monkeypatch):
    # #45 gave mail_attachments a mailbox, but only the five special ones — a user
    # folder was unreachable there too.
    seen = {}

    def fake(script, *args):
        seen["args"] = args
        return "<c@x>\x1fContract\x1fdeal.pdf\x1f100\x1ftrue\x1e"

    monkeypatch.setattr(mail, "run_osascript", fake)
    out = mail.MailAdapter().list_attachments(f"imap://{_GMAIL_UUID}/Backup")
    assert out["results"][0]["attachments"][0]["name"] == "deal.pdf"
    assert seen["args"] == ("", str(mail.MAX_MAILS), _GMAIL_UUID, "Backup", "")


# --- the addressing triple: id + folder + account (#155) ------------------------------


def test_applescript_path_pointers_carry_their_canonical_folder(monkeypatch):
    # The whole point: an id from ANY read must reach mail_body, which requires a
    # mailbox and documents it as coming "from the SAME search result". Before #155
    # only the indexed path emitted `folder`, so the triage entry point handed back
    # ids that were dead on arrival.
    from macos_apps_mcp.adapters.mail import _parse_draft_records

    assert _parse_search_results(f"<a@x>{US}Subject{US}her@x{RS}")[0].folder == "inbox"
    assert _parse_draft_records(f"<d@x>{US}Draft{US}to@x{RS}")[0].folder == "drafts"


def test_needs_response_and_awaiting_reply_carry_a_folder(monkeypatch):
    from macos_apps_mcp.adapters.mail import (
        _classify_awaiting_reply,
        _classify_needs_response,
    )

    needs = _classify_needs_response(
        [
            {
                "id": "<n@x>",
                "subject": "Ping",
                "sender": "her@x",
                "to_addrs": ["me@x"],
                "secs_ago": 10,
                "was_replied_to": False,
                "read": False,
                "flagged": False,
            }
        ],
        {"me@x"},
    )
    assert needs[0].folder == "inbox"

    awaiting = _classify_awaiting_reply(
        [
            {
                "id": "<s@x>",
                "subject": "Quote?",
                "recipient_addrs": ["them@x"],
                "secs_ago": 10 * 86400,
            }
        ],
        set(),
        days=3,
    )
    assert awaiting[0].folder == "sent"


def test_indexed_pointer_carries_the_account_without_touching_mail():
    # The account is already inside the folder url; lifting it out costs no query and
    # launches nothing — which is what lets mail_search keep its no-Mail-launch promise
    # while still answering "which inbox is this?".
    from macos_apps_mcp.adapters import mail_index

    row = {
        "message_id_header": "<m@x>",
        "subject": "Hi",
        "mailbox_url": f"imap://{_GMAIL_UUID}/Archive",
    }
    p = mail_index.row_to_pointer(row)
    assert p.account == _GMAIL_UUID
    assert p.as_dict()["account"] == _GMAIL_UUID
    # local:// (On My Mac) parses the same way; a url with no scheme has no account
    assert mail_index.account_of("local://ABC/Notes") == "ABC"
    assert mail_index.account_of("not-a-url") is None


def test_pointer_omits_account_when_unset():
    # Unified cross-account accessors genuinely do not know the account. Omitting the
    # key is honest; emitting a guessed or empty one is what would send a reply from
    # the wrong address.
    assert "account" not in Pointer(id="1", summary="s", deeplink="d").as_dict()


# --- organize: create_mailbox / move_mail / undo / status (#78/#79) ------------------

_ACCT = "AAAAAAAA-1111-2222-3333-444444444444"
_INBOX = f"imap://{_ACCT}/INBOX"
_ARCHIVE = f"imap://{_ACCT}/Archive"


def _statuses(pairs) -> str:
    return "".join(f"{mid}{US}{st}{RS}" for mid, st in pairs)


@pytest.fixture
def no_backup(monkeypatch):
    """Neutralize the plane's disk half — these tests are about the adapter's scripts
    and envelopes, not about #159's preservation (tests/test_mail_recover.py owns that).
    """
    monkeypatch.setattr(mail.mail_index, "mail_root", lambda: None)
    monkeypatch.setattr(mail.mail_index, "query_message_locations", lambda ids: [])


def test_split_ids_dedupes_and_strips_framing_bytes():
    # a US inside an id would be ONE target in the preview and TWO on the wire, since
    # every script here re-splits the joined list on US
    assert mail._split_ids(f"<a@x>, a@x , b{US}@x, ") == ["a@x", "b@x"]


def test_parse_statuses_skips_partial_records():
    raw = _statuses([("a@x", "ok"), ("b@x", "not-in-source")]) + "trailing"
    assert mail._parse_statuses(raw) == {"a@x": "ok", "b@x": "not-in-source"}


def test_tri_state_distinguishes_absent_from_false():
    # argv carries only text, so "leave it alone" needs a spelling of its own —
    # collapsing it to "0" would silently mark a whole batch unread
    assert (mail._tri(None), mail._tri(True), mail._tri(False)) == ("", "1", "0")


# --- create_mailbox ------------------------------------------------------------------


def test_create_mailbox_synthesises_an_address_that_round_trips(monkeypatch):
    monkeypatch.setattr(mail_addressing, "resolve_account", lambda v: _ACCT)
    monkeypatch.setattr(mail_addressing, "local_account_id", lambda: None)
    monkeypatch.setattr(mail, "run_osascript", lambda *a: "2026")
    out = MailAdapter().create_mailbox("Projects/2026", "Personal")
    assert out["folder"] == f"imap://{_ACCT}/Projects/2026"
    # the whole point: the synthesised token is usable by the id-taking tools at once,
    # because mailbox_args DECODES a path and a plain name passes through untouched
    assert mail_addressing.mailbox_args(out["folder"]) == (_ACCT, "Projects/2026")


def test_create_mailbox_rejects_a_percent_in_the_name(monkeypatch):
    monkeypatch.setattr(mail_addressing, "resolve_account", lambda v: _ACCT)
    with pytest.raises(ValueError, match="%"):
        MailAdapter().create_mailbox("50% off", "Personal")


def test_create_mailbox_raises_when_the_verify_finds_nothing(monkeypatch):
    # `make new mailbox` returns `missing value`, so the create is verified by ADDRESS;
    # a blank answer means the folder is not there and must not report success
    monkeypatch.setattr(mail_addressing, "resolve_account", lambda v: _ACCT)
    monkeypatch.setattr(mail_addressing, "local_account_id", lambda: None)
    monkeypatch.setattr(mail, "run_osascript", lambda *a: "")
    with pytest.raises(mail.NativeError):
        MailAdapter().create_mailbox("Nope", "Personal")


def test_create_mailbox_uses_the_local_sentinel_for_on_my_mac(monkeypatch):
    local = "BBBBBBBB-1111-2222-3333-444444444444"
    seen = []
    monkeypatch.setattr(mail_addressing, "resolve_account", lambda v: local)
    monkeypatch.setattr(mail_addressing, "local_account_id", lambda: local)
    monkeypatch.setattr(mail, "run_osascript", lambda *a: seen.append(a) or "Scratch")
    out = MailAdapter().create_mailbox("Scratch", "On My Mac")
    # Mail's `every account` never lists the local store, so its mailboxes hang off the
    # application — mailboxFor takes the "local" sentinel, never a UUID
    assert seen[0][1] == "local"
    assert out["folder"] == f"local://{local}/Scratch"


# --- move_mail -----------------------------------------------------------------------


def test_move_mail_dry_run_reports_per_id_presence_and_moves_nothing(
    monkeypatch, no_backup
):
    calls = []

    def fake(script, *args, **kw):
        calls.append(script)
        return _statuses([("a@x", "present"), ("b@x", "missing")])

    monkeypatch.setattr(mail, "run_osascript", fake)
    out = MailAdapter().move_mail("a@x,b@x", _INBOX, _ARCHIVE)
    assert calls == [mail._PRESENT]  # the READ, never the move
    assert mail.mail_recover.is_preview(out)
    assert [t["status"] for t in out["would_affect"]] == ["present", "missing"]
    assert out["destination"] == _ARCHIVE


def test_move_mail_caps_the_batch_before_any_native_call(monkeypatch, no_backup):
    def boom(*a, **kw):
        raise AssertionError("the cap must be enforced before Mail is touched")

    monkeypatch.setattr(mail, "run_osascript", boom)
    with pytest.raises(BatchTooLarge):
        MailAdapter().move_mail(
            ",".join(f"m{i}@x" for i in range(26)), _INBOX, _ARCHIVE
        )


def test_move_mail_refuses_a_move_onto_itself(monkeypatch, no_backup):
    monkeypatch.setattr(mail, "run_osascript", lambda *a, **kw: "")
    with pytest.raises(ValueError, match="same mailbox"):
        MailAdapter().move_mail("a@x", _INBOX, _INBOX)


def test_move_mail_reports_what_the_verify_found_not_what_it_hoped(
    monkeypatch, no_backup
):
    monkeypatch.setattr(
        mail,
        "run_osascript",
        lambda *a, **kw: _statuses(
            [("a@x", "ok"), ("b@x", "not-in-source"), ("c@x", "ERROR boom")]
        ),
    )
    out = MailAdapter().move_mail("a@x,b@x,c@x", _INBOX, _ARCHIVE, dry_run=False)
    assert out["succeeded"] == 1
    assert [t["status"] for t in out["targets"]] == [
        "ok",
        "not-in-source",
        "ERROR boom",
    ]
    assert "were NOT affected" in out["note"]
    assert out["undo"].startswith("mail_undo(")


def test_move_mail_gets_a_raised_timeout(monkeypatch, no_backup):
    # 25 moves against a remote IMAP store, each with two verifying counts, is not a
    # 30-second job — the host-side default would kill a legitimate batch
    seen = {}
    monkeypatch.setattr(
        mail,
        "run_osascript",
        lambda *a, **kw: seen.update(kw) or _statuses([("a@x", "ok")]),
    )
    MailAdapter().move_mail("a@x", _INBOX, _ARCHIVE, dry_run=False)
    assert seen["timeout"] == mail._MOVE_TIMEOUT


# --- mail_undo -----------------------------------------------------------------------


def test_undo_moves_the_batch_back_to_each_messages_source(monkeypatch, no_backup):
    monkeypatch.setattr(
        mail, "run_osascript", lambda *a, **kw: _statuses([("a@x", "ok")])
    )
    adapter = MailAdapter()
    moved = adapter.move_mail("a@x", _INBOX, _ARCHIVE, dry_run=False)

    seen = []

    def fake(script, *args, **kw):
        seen.append(args)
        return _statuses([("a@x", "ok")])

    monkeypatch.setattr(mail, "run_osascript", fake)
    out = adapter.undo(moved["receipt"], dry_run=False)
    # source and destination swapped: argv is (srcAcct, srcPath, dstAcct, dstPath, ids)
    assert seen[0][:4] == (_ACCT, "Archive", _ACCT, "INBOX")
    # the undo is itself a plane operation, so it has its own receipt and can be undone
    assert out["receipt"] != moved["receipt"]


def test_undo_of_an_unknown_receipt_raises(no_backup):
    with pytest.raises(mail.NativeError):
        MailAdapter().undo("19990101-000000-000-move")


# --- update_mail_status --------------------------------------------------------------


def test_update_status_needs_something_to_change(monkeypatch):
    monkeypatch.setattr(mail_addressing, "resolve", lambda mid, **kw: None)
    with pytest.raises(ValueError, match="at least one"):
        MailAdapter().update_status("a@x", mailbox=_INBOX)


def test_update_status_rejects_an_unknown_flag_colour():
    with pytest.raises(ValueError, match="unknown flag colour"):
        MailAdapter().update_status("a@x", mailbox=_INBOX, flag_color="chartreuse")


def test_update_status_sends_the_tri_state_and_colour_index(monkeypatch):
    seen = []
    monkeypatch.setattr(
        mail,
        "run_osascript",
        lambda *a, **kw: seen.append(a) or _statuses([("a@x", "ok")]),
    )
    out = MailAdapter().update_status("a@x", mailbox=_INBOX, flag_color="blue")
    # argv is (acct, path, read, flagged, colour, ids) after the script itself:
    # read untouched (""), flagged implied by the colour, blue = flag index 4
    assert seen[0][1:] == (_ACCT, "INBOX", "", "1", "4", "a@x")
    assert out["set"] == {"flagged": True, "flag_color": "blue"}
    assert out["results"] == {"a@x": "ok"}


def test_update_status_groups_a_batch_by_the_mailbox_each_id_lives_in(monkeypatch):
    homes = {"a@x": _INBOX, "b@x": _ARCHIVE, "c@x": _INBOX}
    monkeypatch.setattr(
        mail_addressing,
        "resolve",
        lambda mid, folder=None, account=None: mail_addressing.ResolvedMessage(
            mid, homes[mid], _ACCT
        ),
    )
    seen = []

    def fake(script, *args, **kw):
        seen.append(args[1])
        return _statuses([(m, "ok") for m in args[5].split(US)])

    monkeypatch.setattr(mail, "run_osascript", fake)
    out = MailAdapter().update_status("a@x,b@x,c@x", read=True)
    # two mailboxes -> two Apple Event runs, not three and not one wrong one
    assert seen == ["INBOX", "Archive"]
    assert out["succeeded"] == 3


def test_update_status_reports_a_message_it_could_not_find(monkeypatch):
    monkeypatch.setattr(
        mail, "run_osascript", lambda *a, **kw: _statuses([("a@x", "not-found")])
    )
    out = MailAdapter().update_status("a@x", mailbox=_INBOX, read=True)
    assert out["succeeded"] == 0
    assert "were NOT updated" in out["note"]


# --- #161: the one untested degradation branch ---------------------------------------


def test_outbox_read_failure_degrades_to_unknown_never_an_exception(monkeypatch):
    # The send already happened. Raising here would report a COMPLETED send as a failed
    # call, and a model that retries that "failure" sends the mail twice.
    def boom():
        raise mail.NativeError("Mail is not responding")

    monkeypatch.setattr(mail, "_outbox_pending", boom)
    out = mail._with_outbox_pending({"sent": True})
    assert out["outbox_pending"] is None  # unknown, never a fake clean queue of 0
    assert "NOT confirmed" in out["note"]
    assert "Do NOT retry" in out["note"]
