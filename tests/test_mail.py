"""Unit tests for the mail adapter — pure parsing helpers (no osascript)."""

from __future__ import annotations

import threading
from contextlib import nullcontext

import pytest

from macos_apps_mcp import runtime
from macos_apps_mcp.adapters import (
    mail,
    mail_addressing,
    mail_attachments,
    mail_drafts,
    mail_outgoing,
    mail_triage,
)
from macos_apps_mcp.adapters.mail import (
    MAX_MAILS,
    MailAdapter,
    _deeplink,
    _parse_search_results,
    _summary,
)
from macos_apps_mcp.contracts import Pointer
from macos_apps_mcp.errors import BatchTooLarge, NativeError, NativeTimeout
from macos_apps_mcp.text import RS, US
from tests._fakes import FakeMail


def _patch_run(monkeypatch, fake):
    """Fake the AppleScript boundary — ONE seam, whatever the module.

    The mail modules call ``runtime.run_osascript`` qualified (#176), so patching the
    attribute on ``runtime`` covers every one of them. Before that they each held
    their own module-global copy and this helper had to name them all — after #160's
    split a test that patched only ``mail`` let a send tool spawn osascript against
    real Mail. A missed member failed OPEN; ``tests/test_native_seam.py`` is the
    tripwire that keeps the by-name import from coming back."""
    monkeypatch.setattr(runtime, "run_osascript", fake)


def _patch_body_file(monkeypatch, fake):
    """Same single seam for the tempfile boundary the send bodies go through."""
    monkeypatch.setattr(runtime, "body_file", fake)


def _script(name):
    """Resolve a script constant by name across the adapter's modules — the send
    scripts live in ``mail_outgoing`` (#160); #178 moved the draft, attachment and
    triage ones into their own modules. The by-name lookup is what lets the ~40
    identity tests keep pinning constants wherever a split files them."""
    for mod in (mail, mail_outgoing, mail_drafts, mail_attachments, mail_triage):
        if hasattr(mod, name):
            return getattr(mod, name)
    raise AssertionError(f"no script constant named {name}")


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
        "macos_apps_mcp.runtime.run_osascript",
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
        "macos_apps_mcp.runtime.run_osascript",
        lambda script, *args: seen.setdefault("script", script) and "" or "",
    )
    MailAdapter().get_pointers("acme")
    assert "subject contains q or sender contains q" in seen["script"]


def test_search_empty_query_raises():
    with pytest.raises(ValueError, match="search substring"):
        MailAdapter().get_pointers("   ")


# --- mail_body + create_draft (#62) --------------------------------------------------

import re  # noqa: E402

from macos_apps_mcp.adapters.mail import _BODY  # noqa: E402


def test_get_body_resolves_and_bounds(monkeypatch):
    # body-by-id: the RFC id is passed via argv (injection-safe) and the result is
    # hygiene-budgeted via clean_body (control-stripped here).
    seen = {}

    def fake(script, *a):
        seen["call"] = (script, a)
        return "Hello\x00 body"

    monkeypatch.setattr("macos_apps_mcp.runtime.run_osascript", fake)
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
        "macos_apps_mcp.runtime.run_osascript", lambda *a: "missing value"
    )
    with pytest.raises(NativeError, match="not available locally"):
        MailAdapter().get_body("abc@host", "inbox")


def test_get_body_huge_body_overflows(monkeypatch):
    # a pasted-dump body over the hard cap surfaces OutputOverflow (open it in Mail),
    # not a silently-truncated blob.
    from macos_apps_mcp.errors import OutputOverflow
    from macos_apps_mcp.text import BODY_HARD_MAX

    monkeypatch.setattr(
        "macos_apps_mcp.runtime.run_osascript",
        lambda *a: "z" * (BODY_HARD_MAX + 1),
    )
    with pytest.raises(OutputOverflow):
        MailAdapter().get_body("abc@host", "inbox")


# --- reply (#42/#46) ------------------------------------------------------------------

from macos_apps_mcp.adapters.mail_outgoing import (  # noqa: E402
    _ORIGINAL,
)


def _original_reply(body="original body", sender="Jane <j@x.com>"):
    """What ``_ORIGINAL`` returns: the stripped sender, the date as five integers
    (2026-07-01 14:39), then the content, US-framed — seven fields."""
    return US.join([sender, "2026", "7", "1", "14", "39", body])


def test_attribution_line_uses_mails_format():
    # what is left of the plain quote (#348): the sweep's ownership proof allows Mail's
    # attribution line after the call's text, built from the original's sender and date
    line = mail_outgoing.build_attribution("Jane <j@x.com>", ("13 Oct 2026", "14:39"))
    assert line == "On 13 Oct 2026, at 14:39, Jane <j@x.com> wrote:"
    # no stamp (unreadable date): the line says who wrote, with no date
    assert mail_outgoing.build_attribution("Jane <j@x.com>", None) == (
        "Jane <j@x.com> wrote:"
    )


def test_quote_facts_keep_a_us_char_inside_the_original(monkeypatch):
    # PM-19: only the first six US split, so a US inside the original stays in the tail
    _patch_run(monkeypatch, lambda *a, **k: _original_reply(f"a{US}b gamma"))
    tail, attribution = mail_outgoing._quote_facts("<abc@x>", ("ACCT", "inbox"))
    assert tail.endswith("gamma")
    assert attribution.endswith("Jane <j@x.com> wrote:")


def test_quote_facts_sanitize_control_chars_from_the_sender(monkeypatch):
    # Defense in depth: run_osascript is replaced outright, so the AppleScript
    # stripFraming never runs; the Python-side sanitize_line guard is what is tested.
    # BEL (\x07), not the US separator: a US in a field would desync the split first.
    _patch_run(
        monkeypatch,
        lambda *a, **k: _original_reply("hello", sender="Jane\x07 <j@x.com>"),
    )
    _, attribution = mail_outgoing._quote_facts("abc@x", ("", "inbox"))
    assert "\x07" not in attribution and attribution.endswith("wrote:")


# --- _ORIGINAL sender/date framing hazard (#42/#46 review) ---------------------------


def test_original_strips_framing_from_sender():
    # MEDIUM fix: _ORIGINAL must apply the SAME stripFraming handler _ATTACHMENTS uses
    # to the sender, so a display name containing a literal US/RS char can't desync
    # the seven-field split in _quote_facts.
    assert "my stripFraming(snd)" in _ORIGINAL
    assert "on stripFraming" in _ORIGINAL


def test_original_returns_the_date_as_integers():
    # #348: Mail's attribution needs the date in the Mac's own format, which only
    # Foundation gives; AppleScript hands over integers, never a locale string.
    for part in (
        "year of",
        "month of",
        "as integer",
        "day of",
        "hours of",
        "minutes of",
    ):
        assert part in _ORIGINAL
    assert "as text" not in _ORIGINAL.split("on run argv")[1]


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
    for name in (
        "mail",
        "mail_attachments",
        "mail_drafts",
        "mail_triage",
        "messages",
        "notes",
        "photos",
        "safari",
        "music",
        "contacts",
    ):
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
    assert not re.search(r"^\s*send \w+\s*$", mail_outgoing._REPLY_OPEN, re.M)
    # Mail's native reply verb (real threading), opened for human review
    assert "reply (item 1 of matches)" in mail_outgoing._REPLY_OPEN
    assert "opening window yes" in mail_outgoing._REPLY_OPEN


def test_reply_cleanup_on_failure_is_in_script():
    # #44: atomicity is enforced INSIDE the osascript — the partial outgoing message is
    # deleted in the error path, structurally (not just present as loose words). Since
    # #135 that delete goes through the verifying rollback handler.
    assert re.search(
        r"on error errMsg\s+if my rollback\(r\) then\s+error errMsg",
        mail_outgoing._REPLY_OPEN,
    ), "the on-error handler must roll back the partial reply, then re-raise"


# --- send (#83) -------------------------------------------------------------------


def test_split_addrs_accepts_string_and_list():
    assert mail_outgoing.split_addrs("a@b.com, c@d.com") == ["a@b.com", "c@d.com"]
    assert mail_outgoing.split_addrs(["a@b.com", " c@d.com "]) == ["a@b.com", "c@d.com"]
    assert mail_outgoing.split_addrs(None) == []
    assert mail_outgoing.split_addrs(" , ") == []


def test_split_addrs_strips_unit_separator_injection():
    # F1 review: a literal U+001F (the wire's own field separator, US) embedded in an
    # address must NOT survive into the list — otherwise US.join(...) on the result
    # produces a string that _SEND's `text items of` (which splits on US) parses back
    # into TWO recipients, even though this function only ever emitted one entry.
    # Written as an explicit \u001f escape (never a literal control glyph in source),
    # and asserted on the actual bytes of the result.
    injected = "alice@corp.com\u001fexfil@evil.tld"
    out = mail_outgoing.split_addrs(injected)
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
        if script is mail_outgoing._SEND:
            seen["argv"] = argv
            return "sent"
        return "0"

    # Patched BEFORE the first send() call below: that call is dry_run=True by
    # default and relies on the early return to never reach run_osascript, but
    # patching up front means a regression in that early return fails loudly here
    # instead of firing a real osascript send into Mail.app under a plain
    # `uv run pytest`.
    _patch_run(monkeypatch, fake)
    _patch_body_file(monkeypatch, lambda text: nullcontext("/tmp/fake-body"))

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

    _patch_run(monkeypatch, boom)
    out = mail.MailAdapter().send(
        "a@b.com", "Hi", "body text", cc="c@d.com", from_address="me@corp.com"
    )
    # #160: ONE would_send shape across every send tool — fixed keys, so a caller
    # writes one dry-run handler. `action`/`source` replaced the per-tool
    # reply_to/forwarding/reply_all spellings.
    assert out == {
        "dry_run": True,
        "would_send": {
            "action": "send",
            "to": ["a@b.com"],
            "cc": ["c@d.com"],
            "bcc": [],
            "from": "me@corp.com",
            "subject": "Hi",
            "source": "",
            "body_chars": 9,
            "html": False,
        },
    }


def test_send_dry_run_reports_default_account_when_from_omitted(monkeypatch):
    _patch_run(monkeypatch, lambda *a: "")
    out = mail.MailAdapter().send("a@b.com", "Hi", "x")
    # Mail's default sender is NOT predictable from account order (device-verified), so
    # never report a computed guess.
    assert out["would_send"]["from"] == "(Mail default account)"


def test_send_passes_addresses_via_argv_us_joined(monkeypatch):
    seen = {}

    def fake(script, *argv):
        # a real send now dispatches THREE scripts: the ownership read
        # (mail_addressing._MY_ADDRESSES, #208/D-09), _SEND, then _OUTBOX_COUNT
        # (#134's outbox truth-check) — recorded separately so asserting the _SEND
        # argv can't be clobbered by another call's (empty) argv.
        if script is mail_addressing._MY_ADDRESSES:
            return f"Me@Corp.com{US}other@corp.com"
        if script is mail_outgoing._SEND:
            seen["send_script"], seen["send_argv"] = script, argv
            return "sent"
        seen["outbox_script"] = script
        return "3"

    _patch_run(monkeypatch, fake)
    _patch_body_file(monkeypatch, lambda text: nullcontext("/tmp/fake-body"))
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
    # Mail's own spelling (D-09), not the caller's lower-cased typing.
    assert (subj, is_html, from_addr) == ("Hi", "1", "Me@Corp.com")
    assert to_j == f"a@b.com{US}e@f.com"
    assert (cc_j, bcc_j) == ("c@d.com", "x@y.com")
    # the truth-check ran too
    assert seen["outbox_script"] is mail_outgoing._OUTBOX_COUNT


def test_send_reads_body_through_shared_handler():
    # Bug 1 (device-verified): a subject-only send leaves the body tempfile EMPTY,
    # which crashes a bare `read … as «class utf8»` with -39. _SEND must compose the
    # shared readBody handler instead.
    assert "on readBody(p)" in mail_outgoing._SEND
    assert "my readBody(item 2 of argv)" in mail_outgoing._SEND
    # only inside the handler itself
    assert mail_outgoing._SEND.count("read (POSIX file") == 1


# --- outbox_pending truth-check (#134) -------------------------------------------


def test_outbox_count_script_counts_the_outgoing_messages():
    # the AppleScript that backs outbox_pending must count Mail's REAL send queue (see
    # test_outbox_count_reads_the_real_queue_not_session_objects for why that is
    # `messages of outbox` and not `outgoing messages`) and be bounded like every other
    # template in this file.
    assert "count of (messages of outbox)" in mail_outgoing._OUTBOX_COUNT
    assert "with timeout of 120 seconds" in mail_outgoing._OUTBOX_COUNT


def test_outbox_pending_runs_the_count_script(monkeypatch):
    seen = []
    _patch_run(monkeypatch, lambda *a: seen.append(a) or "4")
    assert mail_outgoing._outbox_pending() == 4
    assert seen == [(mail_outgoing._OUTBOX_COUNT,)]  # no argv — the script needs none


def test_with_outbox_pending_failure_degrades_to_unknown_not_error(monkeypatch):
    """The truth-check runs AFTER Mail accepted the send. If that follow-up READ
    fails (a timeout counting the outbox), raising turns a COMPLETED send into a
    reported failure — and a model that retries a "failed" send sends the mail
    twice. Same principle as never rolling back past the `send` verb, applied to
    the reporting side: degrade to unknown + note, never an error."""
    from macos_apps_mcp.errors import NativeError

    def boom(*a):
        raise NativeError("timeout counting outbox")

    _patch_run(monkeypatch, boom)
    out = mail_outgoing.with_outbox_pending({"sent": True})
    assert out["sent"] is True
    assert out["outbox_pending"] is None  # unknown, never a fake clean 0
    assert "not confirmed" in out["note"].lower()
    assert "Outbox" in out["note"]


def test_send_still_reports_sent_when_outbox_count_fails(monkeypatch):
    # end-to-end guard: the NativeError from the outbox read must not escape send().
    from macos_apps_mcp.errors import NativeError

    def fake(script, *argv):
        if script is mail_outgoing._SEND:
            return "sent"
        raise NativeError("timeout counting outbox")

    _patch_run(monkeypatch, fake)
    _patch_body_file(monkeypatch, lambda text: nullcontext("/tmp/fake-body"))
    out = mail.MailAdapter().send("a@b.com", "Hi", "body", dry_run=False)
    assert out["sent"] is True
    assert out["outbox_pending"] is None


def test_with_outbox_pending_zero_omits_note(monkeypatch):
    _patch_run(monkeypatch, lambda *a: "0")
    out = mail_outgoing.with_outbox_pending({"sent": True})
    assert out == {"sent": True, "outbox_pending": 0}
    assert "note" not in out


def test_with_outbox_pending_nonzero_adds_actionable_note(monkeypatch):
    _patch_run(monkeypatch, lambda *a: "2")
    out = mail_outgoing.with_outbox_pending({"sent": True})
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
    # NEVER reach the reply flow (accessibility, window, send) at all.
    seen = []

    def fake(script, *argv, **_):
        seen.append(script)
        if script is mail_outgoing._REPLY_ALL_RECIPIENTS:
            return (
                f"to{US}alice@corp.com{RS}to{US}bob@corp.com{RS}"
                f"cc{US}carol@corp.com{RS}sender{US}orig-sender@corp.com{RS}"
                f"subject{US}Quarterly numbers{RS}self{US}bob@corp.com{RS}"
            )
        raise AssertionError(f"dry run must not call {script!r} (the send script)")

    _patch_run(monkeypatch, fake)
    out = mail.MailAdapter().reply_all("<orig@x>", "inbox", "Sounds good")
    # #160: the SAME would_send keys `send` and `forward` report, plus #516's
    # `recipients_note`. to/cc are the REPLY's (the sender; everyone else on the
    # original minus this account's own address), `from` is a label, and `source` names
    # the message being replied to.
    note = out["would_send"].pop("recipients_note")
    assert "Mail's own reply-all decides" in note
    assert out == {
        "dry_run": True,
        "would_send": {
            "action": "reply_all",
            "to": ["orig-sender@corp.com"],
            "cc": ["alice@corp.com", "carol@corp.com"],
            "bcc": [],
            "from": mail_outgoing.REPLY_SENDER,
            "subject": "Quarterly numbers",
            "source": "<orig@x>",
            "body_chars": 11,
            "html": False,
        },
    }
    # exactly one call — the read, only
    assert seen == [mail_outgoing._REPLY_ALL_RECIPIENTS]


def _recipients_payload(**kinds):
    """A _REPLY_ALL_RECIPIENTS answer: each keyword is a record kind, a list
    (to/cc/self) or a text (sender/replyto/subject)."""
    out = ""
    for kind, value in kinds.items():
        for v in value if isinstance(value, list) else [value]:
            out += f"{kind}{US}{v}{RS}"
    return out


def _preview(monkeypatch, **kinds):
    """Run reply_all(dry_run=True) over a faked recipients read; return (out, calls)."""
    calls = []

    def fake(script, *argv, **_):
        calls.append(script)
        if script is mail_outgoing._REPLY_ALL_RECIPIENTS:
            return _recipients_payload(**kinds)
        raise AssertionError(f"dry run must not call {script!r}")

    _patch_run(monkeypatch, fake)
    out = mail.MailAdapter().reply_all("<orig@x>", "inbox", "ok")
    return out, calls


def test_reply_all_preview_lists_the_replys_recipients(monkeypatch):
    # #516: the original is from the boss, addressed only to this account -> the reply
    # goes To the boss alone, and `from` is no longer the original's sender.
    out, _ = _preview(
        monkeypatch,
        to=["me@example.com"],
        sender="Boss <boss@corp.com>",
        self=["me@example.com"],
        subject="Hi",
    )
    w = out["would_send"]
    assert w["to"] == ["boss@corp.com"]
    assert w["cc"] == []
    assert w["from"] == mail_outgoing.REPLY_SENDER
    assert w["from"] != "boss@corp.com"


def test_reply_all_preview_uses_reply_to_when_present(monkeypatch):
    out, _ = _preview(
        monkeypatch,
        to=["me@example.com"],
        sender="Boss <boss@corp.com>",
        replyto="Lists <list@corp.com>, b@corp.com",
        self=["me@example.com"],
    )
    w = out["would_send"]
    assert w["to"] == ["list@corp.com", "b@corp.com"]
    assert "boss@corp.com" not in w["to"] + w["cc"]


def test_reply_all_preview_drops_own_addresses_and_duplicates(monkeypatch):
    out, _ = _preview(
        monkeypatch,
        to=["Alice@Corp.com", "me@example.com"],
        cc=["alice@corp.com", "carol@corp.com", "BOSS@corp.com"],
        sender="boss@corp.com",
        self=["ME@example.com"],
    )
    w = out["would_send"]
    assert w["to"] == ["boss@corp.com"]
    assert w["cc"] == ["Alice@Corp.com", "carol@corp.com"]


def test_reply_all_preview_subtracts_reply_to_not_the_sender_from_cc(monkeypatch):
    # With a Reply-To, cc loses the `to` addresses (the list), never the sender: a
    # sender in the original's cc is still reached by Mail's reply-all.
    out, _ = _preview(
        monkeypatch,
        to=["me@example.com"],
        cc=["list@corp.com", "boss@corp.com"],
        sender="Boss <boss@corp.com>",
        replyto="list@corp.com",
        self=["me@example.com"],
    )
    w = out["would_send"]
    assert w["to"] == ["list@corp.com"]
    assert w["cc"] == ["boss@corp.com"]


def test_reply_all_preview_drops_every_address_of_the_account(monkeypatch):
    out, _ = _preview(
        monkeypatch,
        to=["alias@example.com", "alice@corp.com"],
        sender="boss@corp.com",
        self=["me@example.com", "Alias@Example.com"],
    )
    w = out["would_send"]
    assert w["to"] == ["boss@corp.com"]
    assert w["cc"] == ["alice@corp.com"]


def test_reply_all_preview_drops_the_to_addresses_case_insensitively(monkeypatch):
    out, _ = _preview(
        monkeypatch,
        to=["me@example.com"],
        cc=["boss@corp.com", "carol@corp.com"],
        sender="Boss <Boss@Corp.com>",
        self=["me@example.com"],
    )
    w = out["would_send"]
    assert w["to"] == ["Boss@Corp.com"]
    assert w["cc"] == ["carol@corp.com"]


def test_reply_all_preview_keeps_a_self_sent_originals_sender(monkeypatch):
    # facts 5f: Mail's reply-all of a self-sent original went To the owner's address.
    out, _ = _preview(
        monkeypatch,
        to=["me@example.com"],
        sender="me@example.com",
        self=["me@example.com"],
    )
    w = out["would_send"]
    assert w["to"] == ["me@example.com"]
    assert w["cc"] == []


def test_reply_all_preview_falls_back_to_the_sender_when_reply_to_has_no_address(
    monkeypatch,
):
    out, _ = _preview(
        monkeypatch,
        sender="Boss <boss@corp.com>",
        replyto="undisclosed, nobody",
        self=["me@example.com"],
    )
    assert out["would_send"]["to"] == ["boss@corp.com"]


def test_reply_all_preview_refuses_an_original_with_no_sender(monkeypatch):
    calls = []

    def fake(script, *argv, **_):
        calls.append(script)
        return _recipients_payload(to=["me@example.com"], sender="", replyto="")

    _patch_run(monkeypatch, fake)
    with pytest.raises(ValueError, match="no sender or Reply-To"):
        mail.MailAdapter().reply_all("<orig@x>", "inbox", "ok")
    assert calls == [mail_outgoing._REPLY_ALL_RECIPIENTS]


def test_reply_all_preview_subtracts_nothing_when_the_account_is_unreadable(
    monkeypatch,
):
    # prohibition: never hide an address the reply reaches.
    out, _ = _preview(
        monkeypatch,
        to=["me@example.com"],
        cc=["carol@corp.com"],
        sender="boss@corp.com",
    )
    w = out["would_send"]
    assert w["to"] == ["boss@corp.com"]
    assert w["cc"] == ["me@example.com", "carol@corp.com"]
    assert "could not be read" in w["recipients_note"]


def test_reply_all_result_labels_the_computed_recipients(monkeypatch):
    kinds = dict(to=["me@example.com"], sender="boss@corp.com", self=["me@example.com"])
    out, _ = _preview(monkeypatch, **kinds)
    assert "Mail's own reply-all decides" in out["would_send"]["recipients_note"]
    assert "could not be read" not in out["would_send"]["recipients_note"]

    _SweepRig(
        monkeypatch,
        answers={
            "_REPLY_ALL_RECIPIENTS": _recipients_payload(**kinds),
            "_OUTBOX_COUNT": "2",
        },
    )
    sent = mail.MailAdapter().reply_all("<orig@x>", "inbox", "ok", dry_run=False)
    assert sent["to"] == ["boss@corp.com"]
    assert sent["recipients_note"] == out["would_send"]["recipients_note"]
    assert "not confirmed" in sent["note"].lower()  # the outbox note is kept


def test_reply_all_rejects_empty_body():
    with pytest.raises(ValueError, match="non-empty"):
        mail.MailAdapter().reply_all("<orig@x>", "inbox", "   ", dry_run=False)


def test_forward_dry_run_reports_recipients(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("dry run must not call osascript")

    _patch_run(monkeypatch, boom)
    out = mail.MailAdapter().forward("<orig@x>", "inbox", "a@b.com, c@d.com")
    assert out["dry_run"] is True
    # #160: the same fixed keys the other send tools report. `subject` stays empty —
    # Mail composes the "Fwd: …" subject itself at send time, and reading the original
    # just to guess at it would make this preview launch Mail for nothing.
    assert out["would_send"] == {
        "action": "forward",
        "to": ["a@b.com", "c@d.com"],
        "cc": [],
        "bcc": [],
        "from": "(Mail default account)",
        "subject": "",
        "source": "<orig@x>",
        "body_chars": 0,
        "html": False,
    }


def test_forward_sends_via_argv(monkeypatch):
    # forward carries NO body/note — its argv is just (message id, US-joined
    # recipients); no tempfile is ever created for it.
    seen = {}

    def fake(script, *argv, **_):
        seen[script] = argv
        # #134: forward now also runs the outbox truth-check (_OUTBOX_COUNT) after
        # _FORWARD — it must return a real count, not the opaque "sent" _FORWARD uses.
        if script is mail_outgoing._OUTBOX_COUNT:
            return "2"
        return "sent"

    _patch_run(monkeypatch, fake)
    out = mail.MailAdapter().forward("<orig@x>", "inbox", "a@b.com", dry_run=False)
    assert out["sent"] is True
    assert out["to"] == ["a@b.com"]
    assert out["action"] == "forward"
    assert out["source"] == "<orig@x>"  # #160: `source`, not the old `forwarding` key
    assert out["outbox_pending"] == 2
    assert "Outbox" in out["note"]  # non-zero pending: caveat included
    assert seen[mail_outgoing._FORWARD] == ("orig@x", "a@b.com", "", "inbox")
    assert seen[mail_outgoing._OUTBOX_COUNT] == ()  # the truth-check ran, with no args


def test_forward_rejects_missing_recipient():
    with pytest.raises(ValueError, match="recipient"):
        mail.MailAdapter().forward("<orig@x>", "inbox", "", dry_run=False)


def test_forward_script_never_touches_content():
    # Bug 2 (device-verified): writing `content` of a forward is both a no-op read
    # (the original is permanently unreadable via AppleScript) and destructive
    # (writing it at all strips every attachment — a real 7-attachment forward was
    # delivered with 0 once `content` was touched). _FORWARD must never set it.
    assert "set content of" not in mail_outgoing._FORWARD


# --- #135: never delete after send; verify the pre-send rollback ------------------

# the scripts that hand a message to Mail's `send` verb. `_SEND_OUTGOING` sends a reply
# that is already built and rolls nothing back (the discard runs before it, never
# after).
_SENDING_SCRIPTS = ("_SEND", "_FORWARD", "_SEND_OUTGOING")
# the scripts that build a message and roll it back through the verifying handler
_ROLLING_BACK_SCRIPTS = ("_SEND", "_FORWARD", "_CREATE_DRAFT", "_REPLY_OPEN")


@pytest.mark.parametrize("name", _SENDING_SCRIPTS)
def test_send_scripts_never_delete_after_the_send_verb(name):
    # #135, device-verified 2026-07-26: `delete` on a message Mail has already accepted
    # via `send` is a SILENT NO-OP — both `delete <ref>` and `delete outgoing message i`
    # returned cleanly, removed nothing, and the message delivered anyway. A post-send
    # rollback therefore cannot succeed; it can only report a cleanup that never
    # happened. So `send` must sit outside the rollback `try` entirely. This is the test
    # that fails if anyone re-nests it.
    script = _script(name)
    verb = re.search(r"^\s*send \w+\s*$", script, re.M)
    assert verb, f"{name} has no `send <msg>` verb to anchor on"
    assert "delete" not in script[verb.start() :], (
        f"{name} deletes after `send` — that strands a zombie in Mail's outbox (#135)"
    )


@pytest.mark.parametrize("name", _ROLLING_BACK_SCRIPTS)
def test_rollback_goes_through_the_verifying_handler(name):
    # a bare `delete` reports success whether or not it removed anything, so every
    # rollback path composes the handler and calls it instead.
    script = _script(name)
    assert "on rollback(msg)" in script, f"{name} lacks the rollback handler"
    assert "my rollback(" in script, f"{name} never calls the rollback handler"


@pytest.mark.parametrize("name", _ROLLING_BACK_SCRIPTS)
def test_rollback_is_the_only_delete_in_a_rollback_script(name):
    # the handler owns the delete; a stray `delete` elsewhere would be an unverified
    # rollback sneaking back in.
    assert _script(name).count("delete ") == 1


def test_rollback_handler_trusts_only_1728_as_proof_of_deletion():
    # device-verified: a successfully deleted outgoing message's reference goes DEAD,
    # and reading a property off it raises -1728. Any OTHER error (a timeout, say)
    # leaves the outcome unknown — and unknown must never be reported as a clean
    # rollback, or we hand the caller the reassuring lie this issue is made of.
    assert "delete msg" in mail_outgoing.ROLLBACK
    assert "-1728" in mail_outgoing.ROLLBACK
    # still readable => the delete did not take
    assert "return false" in mail_outgoing.ROLLBACK


@pytest.mark.parametrize("name", _ROLLING_BACK_SCRIPTS)
def test_unverified_rollback_warns_about_the_leftover(name):
    # when the handler returns false the original error still propagates, but it carries
    # the fact that a partial message may remain — and where to look for it. Both
    # warning
    # texts live in the shared preamble, so assert the CALL SITE: a script that sends
    # leaves an outbox leftover, one that only drafts leaves a Drafts leftover. Checking
    # for the words themselves would pass vacuously on every script.
    script = _script(name)
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
    assert "messages of outbox" in mail_outgoing._OUTBOX_COUNT
    assert "count of outgoing messages" not in mail_outgoing._OUTBOX_COUNT


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
    assert "retry can't strand a duplicate" not in mail_drafts._CREATE_DRAFT
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
        runtime,
        "run_osascript",
        lambda *a: f"{_UUID_1}\x1fPersonal\x1e{_UUID_2}\x1fGoogle",
    )
    assert ma.account_map() == {_UUID_1: "Personal", _UUID_2: "Google"}


def test_account_map_empty_when_mail_unreachable(monkeypatch):
    import macos_apps_mcp.adapters.mail_addressing as ma
    from macos_apps_mcp.errors import NativeError

    monkeypatch.setattr(ma, "_ACCOUNT_MAP_CACHE", None)

    def boom(*a):
        raise NativeError("Automation denied")

    monkeypatch.setattr(runtime, "run_osascript", boom)
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

    monkeypatch.setattr(runtime, "run_osascript", warming_up)
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

    monkeypatch.setattr(runtime, "run_osascript", boom)
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

    monkeypatch.setattr(runtime, "run_osascript", flaky)
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

    monkeypatch.setattr(runtime, "run_osascript", ok)
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

    monkeypatch.setattr(runtime, "run_osascript", boom)
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
        runtime,
        "run_osascript",
        lambda *a: pytest.fail("stale failure timestamp wiped a live cache"),
    )
    assert ma.account_map() == {"some-uuid": "Personal"}


def test_resolve_account_maps_name_and_passes_uuid_through(monkeypatch):
    import macos_apps_mcp.adapters.mail_addressing as ma

    monkeypatch.setattr(ma, "_ACCOUNT_MAP_CACHE", None)
    monkeypatch.setattr(runtime, "run_osascript", lambda *a: f"{_UUID_1}\x1fPersonal")
    assert ma.resolve_account("Personal") == _UUID_1
    assert ma.resolve_account(_UUID_1) == _UUID_1


def test_resolve_account_uuid_never_contacts_mail(monkeypatch):
    """The UUID path is what lets mail_search/mail_overview keep their "reads the index
    at rest" promise — resolving a NAME runs osascript, which launches Mail."""
    import macos_apps_mcp.adapters.mail_addressing as ma

    monkeypatch.setattr(ma, "_ACCOUNT_MAP_CACHE", None)
    monkeypatch.setattr(
        runtime, "run_osascript", lambda *a: pytest.fail("a UUID account launched Mail")
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
    "_REPLY_OPEN",
    "_DISCARD_NEW_REPLY",
    "_REPLY_ALL_RECIPIENTS",
)


@pytest.mark.parametrize("name", _MAILBOX_SCOPED_SCRIPTS)
def test_mailbox_scoped_scripts_resolve_the_mailbox_instead_of_hard_coding_inbox(name):
    """The guard that stops #146 recurring. Each script that addresses a message by id
    must take its mailbox from argv through the ONE shared resolver — not name `inbox`
    itself. This is the assertion whose absence let the #62 inbox scope survive #70/#75
    widening search to every mailbox."""
    script = _script(name)
    assert script.count("on mailboxFor(") == 1  # composes the shared resolver, once
    assert "my mailboxFor(" in script  # ...and actually calls it
    assert "messages of inbox" not in script  # #146: no hard-coded inbox scope


def test_mailbox_resolver_is_the_only_place_a_mailbox_accessor_is_named():
    # the unified accessors (`sent mailbox`/`drafts mailbox`/…) live in one handler, so
    # the alias layer can't drift apart across seven scripts the way the scope did.
    for name in _MAILBOX_SCOPED_SCRIPTS:
        script = _script(name)
        body = script.replace(mail_addressing.MAILBOX_REF, "")
        assert "sent mailbox" not in body
        assert "junk mailbox" not in body


def test_get_body_passes_the_mailbox_through_argv(monkeypatch):
    seen = {}

    def fake(script, *a):
        seen["call"] = (script, a)
        return "Filed body"

    _patch_run(monkeypatch, fake)
    out = mail.MailAdapter().get_body("<abc@host>", _SPAM_URL)
    assert out == "Filed body"
    assert seen["call"][1] == ("abc@host", _GMAIL_UUID, "[Gmail]/Spam")


def test_get_body_rejects_an_empty_id():
    # #155 made `mailbox` optional — an empty ID is what is left to reject.
    with pytest.raises(ValueError, match="message id"):
        mail.MailAdapter().get_body("  ", "inbox")


def test_reply_passes_the_mailbox_to_every_script(monkeypatch):
    # the quote-tail read (_ORIGINAL) and the reply build (_REPLY_OPEN) must target the
    # SAME mailbox — a reply that checks a quote of nothing because the original wasn't
    # in the inbox is the silent half of this bug.
    rig = _ReplyRig(monkeypatch)
    mail.MailAdapter().reply("<orig@x>", _SPAM_URL, "Sounds good")
    assert rig.call("_ORIGINAL")[1] == ("orig@x", _GMAIL_UUID, "[Gmail]/Spam")
    assert rig.call("_REPLY_OPEN")[1] == ("orig@x", _GMAIL_UUID, "[Gmail]/Spam", "0")


def test_reply_all_dry_run_reads_recipients_from_the_named_mailbox(monkeypatch):
    def fake(script, *argv, **_):
        assert script is mail_outgoing._REPLY_ALL_RECIPIENTS
        assert argv == ("orig@x", _GMAIL_UUID, "[Gmail]/Spam")
        return f"to{US}alice@corp.com{RS}sender{US}orig@corp.com{RS}"

    _patch_run(monkeypatch, fake)
    out = mail.MailAdapter().reply_all("<orig@x>", _SPAM_URL, "Sounds good")
    assert out["would_send"]["to"] == ["orig@corp.com"]
    assert out["would_send"]["cc"] == ["alice@corp.com"]


def test_forward_passes_the_mailbox(monkeypatch):
    seen = {}

    def fake(script, *argv, **_):
        seen[script] = argv
        return "0" if script is mail_outgoing._OUTBOX_COUNT else "sent"

    _patch_run(monkeypatch, fake)
    mail.MailAdapter().forward("<orig@x>", _SPAM_URL, "a@b.com", dry_run=False)
    assert seen[mail_outgoing._FORWARD] == (
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

    _patch_run(monkeypatch, boom)
    out = mail.MailAdapter().forward("<orig@x>", _SPAM_URL, "a@b.com")
    assert out["dry_run"] is True


# --- the addressing triple: id + folder + account (#155) ------------------------------


def test_applescript_path_pointers_carry_their_canonical_folder(monkeypatch):
    # The whole point: an id from ANY read must reach mail_body, which requires a
    # mailbox and documents it as coming "from the SAME search result". Before #155
    # only the indexed path emitted `folder`, so the triage entry point handed back
    # ids that were dead on arrival.
    from macos_apps_mcp.adapters.mail_drafts import _parse_draft_records

    assert _parse_search_results(f"<a@x>{US}Subject{US}her@x{RS}")[0].folder == "inbox"
    assert _parse_draft_records(f"<d@x>{US}Draft{US}to@x{RS}")[0]["folder"] == "drafts"


def test_needs_response_and_awaiting_reply_carry_a_folder(monkeypatch):
    from macos_apps_mcp.adapters.mail_triage import (
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
        25,
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
        limit=25,
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
_INBOX_BOX = (_ACCT, "INBOX")
_ARCHIVE_BOX = (_ACCT, "Archive")


def _statuses(pairs) -> str:
    return "".join(f"{mid}{US}{st}{RS}" for mid, st in pairs)


@pytest.fixture
def no_backup(monkeypatch):
    """Neutralize the plane's disk half — these tests are about the adapter's scripts
    and envelopes, not about #159's preservation (tests/test_mail_recover.py owns that).
    """
    monkeypatch.setattr(mail.mail_index, "mail_root", lambda: None)
    monkeypatch.setattr(mail.mail_index, "query_message_locations", lambda ids: [])
    # keeps the label checks (#287, #291) off the real Envelope Index
    monkeypatch.setattr(
        mail.mail_index,
        "_label_state",
        lambda: mail.mail_index._LabelState(*[frozenset()] * 3),
    )


def test_split_ids_dedupes_and_strips_framing_bytes():
    # a US inside an id would be ONE target in the preview and TWO on the wire, since
    # every script here re-splits the joined list on US
    assert mail._split_ids(f"<a@x>, a@x , b{US}@x, ") == ["a@x", "b@x"]


def test_parse_statuses_skips_partial_records():
    raw = _statuses([("a@x", "ok"), ("b@x", "not-in-source")]) + "trailing"
    assert mail._parse_statuses(raw) == {"a@x": "ok", "b@x": "not-in-source"}


def test_copies_matches_message_id_exact_bare_form_case_sensitive(monkeypatch):
    # MAIL-01/encoding: equality in the by-ID map is exact on the bare form, never
    # case-folded — "A@X" must not match a target of "a@x". A `missing value` entry
    # (header-less message) and a blank entry never match anything either.
    def fake_run(script, *args, **kw):
        assert script is mail._BULK
        mids = US.join(["A@X", "<a@x>", "missing value", ""])
        nids = US.join(["1", "2", "3", "4"])
        return mids + RS + nids

    monkeypatch.setattr(runtime, "run_osascript", fake_run)
    out = mail._copies(_INBOX_BOX, ["a@x"])
    assert out == {"a@x": ["2"]}  # "A@X" (wrong case) excluded; bracketed form stripped


def test_counts_skips_missing_value_and_blank_counts_case_sensitive(monkeypatch):
    def fake_run(script, *args, **kw):
        assert script is mail._BULK
        mids = US.join(["a@x", "a@x", "A@X", "missing value", ""])
        return mids + RS  # no internal ids requested

    monkeypatch.setattr(runtime, "run_osascript", fake_run)
    out = mail._counts(_INBOX_BOX)
    assert out == {"a@x": 2, "A@X": 1}


def test_tri_state_distinguishes_absent_from_false():
    # argv carries only text, so "leave it alone" needs a spelling of its own —
    # collapsing it to "0" would silently mark a whole batch unread
    assert (mail._tri(None), mail._tri(True), mail._tri(False)) == ("", "1", "0")


# --- create_mailbox ------------------------------------------------------------------


def test_create_mailbox_synthesises_an_address_that_round_trips(monkeypatch):
    monkeypatch.setattr(mail_addressing, "resolve_account", lambda v: _ACCT)
    monkeypatch.setattr(mail_addressing, "local_account_id", lambda: None)
    _patch_run(monkeypatch, lambda *a: "2026")
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
    _patch_run(monkeypatch, lambda *a: "")
    with pytest.raises(mail.NativeError):
        MailAdapter().create_mailbox("Nope", "Personal")


def test_create_mailbox_uses_the_local_sentinel_for_on_my_mac(monkeypatch):
    local = "BBBBBBBB-1111-2222-3333-444444444444"
    seen = []
    monkeypatch.setattr(mail_addressing, "resolve_account", lambda v: local)
    monkeypatch.setattr(mail_addressing, "local_account_id", lambda: local)
    _patch_run(monkeypatch, lambda *a: seen.append(a) or "Scratch")
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

    _patch_run(monkeypatch, fake)
    out = MailAdapter().move_mail("a@x,b@x", _INBOX, _ARCHIVE)
    assert calls == [mail._PRESENT]  # the READ, never the move
    assert mail.mail_recover.is_preview(out)
    assert [t["status"] for t in out["would_affect"]] == ["present", "missing"]
    assert out["destination"] == _ARCHIVE


def test_move_mail_dry_run_presence_reads_once_with_the_scaled_cap(
    monkeypatch, no_backup
):
    # Task 1 tracer (#206/D-04): FakeMail INBOX=[a@x]; the dry-run preview is ONE
    # _PRESENT call whose host cap is mail._present_timeout(len(ids)) — the bulk-read
    # cap, not the old 30s default.
    fake = FakeMail()
    fake.seed(_INBOX_BOX, "a@x")
    _patch_run(monkeypatch, fake)
    out = MailAdapter().move_mail("a@x,b@x", _INBOX, _ARCHIVE)
    assert [c[0] for c in fake.calls] == [mail._PRESENT]
    assert fake.calls[0][2] == {"timeout": mail._present_timeout(2)}
    assert fake.calls[0][2] == {"timeout": 182.0}
    assert [t["status"] for t in out["would_affect"]] == ["present", "missing"]


def test_present_script_is_one_bulk_read_matched_under_considering_case():
    # #206/D-04: _PRESENT reads the mailbox once and matches in AppleScript, not a
    # per-id `whose` scan — the same exact-equality rule the by-ID act uses. The shared
    # `mailboxFor` handler (prefixed onto every by-ID script) legitimately uses `whose`
    # to resolve an ACCOUNT, so the "no whose" check is scoped to _PRESENT's own `on
    # run` body, the part this task rewrote.
    body = mail._PRESENT.split("on run argv", 1)[1]
    assert mail._PRESENT.count("message id of every message of mb") == 1
    assert "whose" not in body
    assert "considering case" in body
    assert "stripFraming" in mail._PRESENT
    # a failed bulk read yields ERROR <message> for every requested id, not a partial
    # answer — the per-id error shape the old per-id script produced.
    assert 'set outcome to "ERROR " & readErr' in body


def test_present_timeout_scales_with_a_floor_from_the_bulk_read_cap():
    # D-02/D-04: _PRESENT's real cost after the bulk-read rewrite follows mailbox SIZE,
    # not batch size, so `base` alone (the _BULK_TIMEOUT floor) covers the worst case —
    # `per_id` stays thin and the clamp at MAX_TARGETS still holds.
    assert mail._present_timeout(1) == 181.0
    assert mail._present_timeout(25) == 205.0
    assert mail._present_timeout(40) == 205.0


def test_move_mail_caps_the_batch_before_any_native_call(monkeypatch, no_backup):
    def boom(*a, **kw):
        raise AssertionError("the cap must be enforced before Mail is touched")

    _patch_run(monkeypatch, boom)
    with pytest.raises(BatchTooLarge):
        MailAdapter().move_mail(
            ",".join(f"m{i}@x" for i in range(26)), _INBOX, _ARCHIVE
        )


def test_move_mail_refuses_a_move_onto_itself(monkeypatch, no_backup):
    _patch_run(monkeypatch, lambda *a, **kw: "")
    with pytest.raises(ValueError, match="same mailbox"):
        MailAdapter().move_mail("a@x", _INBOX, _INBOX)


def test_move_mail_refuses_a_unified_destination_from_on_my_mac(monkeypatch, no_backup):
    # #171, device-verified: a canonical name files into the SOURCE's own account, and
    # On My Mac has none of the five — so all five are a no-op from a local:// source.
    # It must fail at the boundary with the fix in hand, never as a post-hoc verify.
    def boom(*a, **kw):
        raise AssertionError("must refuse before Mail is touched")

    _patch_run(monkeypatch, boom)
    for dest in ("inbox", "sent", "drafts", "trash", "junk"):
        with pytest.raises(ValueError, match="On My Mac"):
            MailAdapter().move_mail("a@x", "local://LOCAL-UUID/Notes", dest)


@pytest.mark.parametrize("dry_run", [True, False])
def test_move_mail_refuses_a_canonical_source(monkeypatch, no_backup, dry_run):
    # #291: a unified name spans accounts and, for a Gmail message, resolves to a label
    # folder (a move there is a copy, #287). Refused before Mail is touched.
    def boom(*a, **kw):
        raise AssertionError("must refuse before Mail is touched")

    _patch_run(monkeypatch, boom)
    for name in ("inbox", "sent", "drafts", "trash", "junk"):
        with pytest.raises(ValueError, match="unified"):
            MailAdapter().move_mail("a@x", name, _ARCHIVE, dry_run=dry_run)


def test_move_mail_allows_a_unified_destination_from_an_imap_source(
    monkeypatch, no_backup
):
    # The other half of the same census: from an imap source every unified destination
    # WORKS (it resolves to that account's concrete mailbox), so the #171 refusal must
    # not widen into "a unified accessor can never be a destination".
    fake = FakeMail()
    fake.seed(_INBOX_BOX, "a@x")
    _patch_run(monkeypatch, fake)
    out = MailAdapter().move_mail("a@x", _INBOX, "drafts", dry_run=False)
    assert out["succeeded"] == 1


def test_move_mail_reports_what_the_verify_found_not_what_it_hoped(
    monkeypatch, no_backup
):
    fake = FakeMail()
    fake.seed(_INBOX_BOX, "a@x")
    [c_nid] = fake.seed(_INBOX_BOX, "c@x")
    fake.lands_nowhere.add(c_nid)  # "ok" per the script, no count rise at dst
    _patch_run(monkeypatch, fake)
    out = MailAdapter().move_mail("a@x,b@x,c@x", _INBOX, _ARCHIVE, dry_run=False)
    assert out["succeeded"] == 1
    statuses = {t["id"]: t["status"] for t in out["targets"]}
    assert statuses["a@x"] == "ok"
    assert statuses["b@x"] == "not-in-source"  # never seeded — no copy anywhere
    assert statuses["c@x"] == (
        "ERROR move returned cleanly but the message is not in the destination"
    )
    assert "were NOT affected" in out["note"]
    assert out["undo"].startswith("mail_undo(")


def test_move_mail_reports_self_move_when_the_source_copy_survives(
    monkeypatch, no_backup
):
    # D-01's post-move probe: the source reference must go dead (-1728); any other
    # outcome is reported, never assumed. "survives" simulates the still-readable case.
    fake = FakeMail()
    [nid] = fake.seed(_INBOX_BOX, "a@x")
    fake.survives.add(nid)
    _patch_run(monkeypatch, fake)
    out = MailAdapter().move_mail("a@x", _INBOX, _ARCHIVE, dry_run=False)
    assert out["targets"][0]["status"] == FakeMail.SURVIVES_ERROR


def test_move_mail_with_no_copies_in_source_reports_not_in_source_with_no_move_call(
    monkeypatch, no_backup
):
    # D-01: zero copies anywhere means no pairs to act on — the whole point of mapping
    # Message-ID -> internal id BEFORE acting is to never issue a no-op `_MOVE` call.
    fake = FakeMail()  # nothing seeded
    _patch_run(monkeypatch, fake)
    out = MailAdapter().move_mail("a@x,b@x", _INBOX, _ARCHIVE, dry_run=False)
    assert [t["status"] for t in out["targets"]] == [
        "not-in-source",
        "not-in-source",
    ]
    assert all(script is not mail._MOVE for script, _args, _kw in fake.calls)


def test_move_script_rechecks_before_reporting_both_and_states_the_observation():
    # #174: the still-in-source branch has two device-verified ways to fire on a move
    # that did nothing wrong — a self-move no-op (facts §5e) and one 2026-08-11
    # full-suite run where a re-locate immediately after proved the move was clean. So
    # the branch re-checks once after a bounded wait before reporting, and what
    # survives states what was SEEN (present in both, naming self-move as a reading),
    # never the old "this was a COPY" inference that sent callers hunting a duplicate
    # that did not exist. The happy path stays poll-free: measured 2026-08-13,
    # 17/17 cross-account moves read source=0 in the statement after the verb.
    assert "delay 2" in mail._MOVE  # bounded, single — never a poll (facts §8)
    assert "was a COPY" not in mail._MOVE  # the unsupported inference
    assert "self-move" in mail._MOVE  # the §5e reading, named
    assert "Nothing was deleted" in mail._MOVE  # a destructive-sounding lie, retired


def test_move_mail_gets_a_raised_timeout(monkeypatch, no_backup):
    # #206/D-02: the by-ID act's host cap scales with the copies it touches, and every
    # `_BULK` read's cap is the flat mailbox-size-driven constant.
    fake = FakeMail()
    fake.seed(_INBOX_BOX, "a@x")
    _patch_run(monkeypatch, fake)
    MailAdapter().move_mail("a@x", _INBOX, _ARCHIVE, dry_run=False)
    move_calls = [c for c in fake.calls if c[0] is mail._MOVE]
    bulk_calls = [c for c in fake.calls if c[0] is mail._BULK]
    assert len(move_calls) == 1
    assert move_calls[0][2]["timeout"] == mail._act_timeout(1)
    assert bulk_calls
    assert all(c[2]["timeout"] == mail._BULK_TIMEOUT for c in bulk_calls)


def test_move_mail_by_id_act_bulk_reads_then_acts_then_recounts(monkeypatch, no_backup):
    # Task 1 tracer behavior: one bulk read of the source (with internal ids), one
    # bulk read of the destination BEFORE acting, one `_MOVE`, one bulk read of the
    # destination AFTER — in that exact order (D-01's count-increase verification).
    fake = FakeMail()
    fake.seed(_INBOX_BOX, "a@x", "b@x")
    _patch_run(monkeypatch, fake)
    adapter = MailAdapter()
    moved = adapter.move_mail("a@x,b@x", _INBOX, _ARCHIVE, dry_run=False)

    assert moved["succeeded"] == 2
    assert all(t["status"] == "ok" for t in moved["targets"])
    assert {mid for _, mid in fake.boxes[_ARCHIVE_BOX]} == {"a@x", "b@x"}
    assert fake.boxes.get(_INBOX_BOX, []) == []

    scripts = [c[0] for c in fake.calls]
    assert scripts == [mail._BULK, mail._BULK, mail._MOVE, mail._BULK]
    assert fake.calls[0][1][2] == "1"  # source read wants internal ids
    assert fake.calls[1][1][2] == "0"  # before-count: destination, no internal ids
    assert fake.calls[3][1][2] == "0"  # after-count: destination, no internal ids
    assert fake.calls[0][2]["timeout"] == mail._BULK_TIMEOUT
    assert fake.calls[1][2]["timeout"] == mail._BULK_TIMEOUT
    assert fake.calls[2][2]["timeout"] == mail._act_timeout(2)
    assert fake.calls[3][2]["timeout"] == mail._BULK_TIMEOUT


# --- mail_undo -----------------------------------------------------------------------


def test_undo_moves_the_batch_back_to_each_messages_source(monkeypatch, no_backup):
    fake = FakeMail()
    fake.seed(_INBOX_BOX, "a@x")
    _patch_run(monkeypatch, fake)
    adapter = MailAdapter()
    moved = adapter.move_mail("a@x", _INBOX, _ARCHIVE, dry_run=False)

    fake.calls.clear()
    out = adapter.undo(moved["receipt"], dry_run=False)
    move_calls = [c for c in fake.calls if c[0] is mail._MOVE]
    assert len(move_calls) == 1
    # source and destination swapped: argv is (srcAcct, srcPath, dstAcct, dstPath, ...)
    assert move_calls[0][1][:4] == (_ACCT, "Archive", _ACCT, "INBOX")
    # the undo is itself a plane operation, so it has its own receipt and can be undone
    assert out["receipt"] != moved["receipt"]
    assert out["succeeded"] == 1
    assert {mid for _, mid in fake.boxes[_INBOX_BOX]} == {"a@x"}


# --- D-03 duplicate rule, D-06 timeout receipt, framing guard, order (#206) ----------


def test_move_mail_moves_every_copy_of_a_duplicated_message_id(monkeypatch, no_backup):
    fake = FakeMail()
    fake.seed(_INBOX_BOX, "a@x", "a@x")  # two copies of the same Message-ID
    _patch_run(monkeypatch, fake)
    out = MailAdapter().move_mail("a@x", _INBOX, _ARCHIVE, dry_run=False)
    assert out["targets"][0]["status"] == "ok"
    move_call = next(c for c in fake.calls if c[0] is mail._MOVE)
    mids_arg, nids_arg = move_call[1][4], move_call[1][5]
    assert mids_arg.split(US) == ["a@x", "a@x"]
    assert len(nids_arg.split(US)) == 2
    assert [mid for _nid, mid in fake.boxes[_ARCHIVE_BOX]] == ["a@x", "a@x"]
    assert fake.boxes.get(_INBOX_BOX, []) == []


def test_move_mail_partial_duplicate_move_reports_error_with_copy_count(
    monkeypatch, no_backup
):
    fake = FakeMail()
    nids = fake.seed(_INBOX_BOX, "a@x", "a@x")
    fake.survives.add(nids[1])  # the second copy's source reference survives
    _patch_run(monkeypatch, fake)
    out = MailAdapter().move_mail("a@x", _INBOX, _ARCHIVE, dry_run=False)
    status = out["targets"][0]["status"]
    assert status.startswith("ERROR")
    assert status.endswith("(1 of 2 copies moved)")


def test_move_mail_partial_duplicate_with_a_missing_answer_is_exactly_unknown(
    monkeypatch, no_backup
):
    fake = FakeMail()
    nids = fake.seed(_INBOX_BOX, "a@x", "a@x")

    def fake_run(script, *args, **kw):
        if script is mail._MOVE:
            fake.calls.append((script, args, kw))
            raw = fake._move(args)
            # drop the SECOND copy's record entirely — the move still happened (its
            # internal FakeMail state is unaffected), but the per-copy script never
            # emitted an answer for it, same as a crash mid-repeat.
            records = [r for r in raw.split(RS) if r]
            kept = [r for r in records if not r.startswith(f"{nids[1]}{US}")]
            return "".join(r + RS for r in kept)
        return fake(script, *args, **kw)

    monkeypatch.setattr(runtime, "run_osascript", fake_run)
    out = MailAdapter().move_mail("a@x", _INBOX, _ARCHIVE, dry_run=False)
    assert out["targets"][0]["status"] == "unknown"


def test_undo_of_a_duplicate_rich_destination_moves_every_copy_back(
    monkeypatch, no_backup
):
    # D-03's documented consequence: undoing into a mailbox that already held a
    # pre-existing copy of the same Message-ID pulls that copy along too, because the
    # by-ID act moves EVERY copy of a Message-ID it finds at the source.
    fake = FakeMail()
    fake.seed(_INBOX_BOX, "a@x")
    fake.seed(_ARCHIVE_BOX, "a@x")  # a copy already sitting in the destination
    _patch_run(monkeypatch, fake)
    adapter = MailAdapter()
    moved = adapter.move_mail("a@x", _INBOX, _ARCHIVE, dry_run=False)
    assert moved["targets"][0]["status"] == "ok"
    assert [mid for _nid, mid in fake.boxes[_ARCHIVE_BOX]] == ["a@x", "a@x"]

    adapter.undo(moved["receipt"], dry_run=False)
    assert [mid for _nid, mid in fake.boxes[_INBOX_BOX]] == ["a@x", "a@x"]
    assert fake.boxes.get(_ARCHIVE_BOX, []) == []


def test_move_mail_timeout_on_the_destination_after_read_leaves_a_receipt(
    monkeypatch, no_backup
):
    # D-06 across plans (02.1-01): a host timeout mid-act still leaves a receipt
    # naming itself, and `mail_undo(..., dry_run=True)` previews every target.
    fake = FakeMail()
    fake.seed(_INBOX_BOX, "a@x")
    dst_bulk_calls = [0]

    def fake_run(script, *args, **kw):
        if script is mail._BULK and args[:2] == _ARCHIVE_BOX:
            dst_bulk_calls[0] += 1
            if dst_bulk_calls[0] == 2:  # the AFTER read, following the move
                fake.calls.append((script, args, kw))
                raise NativeTimeout("osascript killed")
        return fake(script, *args, **kw)

    monkeypatch.setattr(runtime, "run_osascript", fake_run)
    with pytest.raises(NativeTimeout) as exc:
        MailAdapter().move_mail("a@x", _INBOX, _ARCHIVE, dry_run=False)
    match = re.search(r"receipt '([^']+)'", str(exc.value))
    assert match, str(exc.value)

    preview = MailAdapter().undo(match.group(1), dry_run=True)
    assert mail.mail_recover.is_preview(preview)
    assert len(preview["would_affect"]) == 1


def test_move_mail_framing_guard_rejects_a_mismatched_bulk_read(monkeypatch, no_backup):
    # T-02.1-11: a Message-ID carrying a stray US/RS byte shifts the split boundaries —
    # 3 message ids answered against only 2 internal ids must raise before any move.
    def fake_run(script, *args, **kw):
        if script is mail._BULK:
            return f"a@x{US}b@x{US}c@x" + RS + f"1{US}2"
        raise AssertionError("must refuse before any _MOVE call")

    monkeypatch.setattr(runtime, "run_osascript", fake_run)
    with pytest.raises(mail.NativeError):
        MailAdapter().move_mail("a@x", _INBOX, _ARCHIVE, dry_run=False)


def test_move_mail_result_keeps_the_callers_id_order(monkeypatch, no_backup):
    fake = FakeMail()
    fake.seed(_INBOX_BOX, "a@x", "b@x", "c@x")  # Mail's own bulk order: a, b, c
    _patch_run(monkeypatch, fake)
    out = MailAdapter().move_mail("c@x,a@x,b@x", _INBOX, _ARCHIVE, dry_run=False)
    assert [t["id"] for t in out["targets"]] == ["c@x", "a@x", "b@x"]


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
        runtime,
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

    _patch_run(monkeypatch, fake)
    out = MailAdapter().update_status("a@x,b@x,c@x", read=True)
    # two mailboxes -> two Apple Event runs, not three and not one wrong one
    assert seen == ["INBOX", "Archive"]
    assert out["succeeded"] == 3


def test_update_status_reports_a_message_it_could_not_find(monkeypatch):
    monkeypatch.setattr(
        runtime, "run_osascript", lambda *a, **kw: _statuses([("a@x", "not-found")])
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

    monkeypatch.setattr(mail_outgoing, "_outbox_pending", boom)
    out = mail_outgoing.with_outbox_pending({"sent": True})
    assert out["outbox_pending"] is None  # unknown, never a fake clean queue of 0
    assert "NOT confirmed" in out["note"]
    assert "Do NOT retry" in out["note"]


# --- FIX-16 (#348): mail_reply keeps Mail's own quote, or refuses ------------------
#
# Facts section 4e is the contract. The flow runs in ONE run_native closure; every seam
# below is faked, so no AX, CoreGraphics, pasteboard, osascript or Mail call is made.

import email.message  # noqa: E402
import email.policy  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from macos_apps_mcp.adapters import mail_reply_cleanup  # noqa: E402
from macos_apps_mcp.errors import (  # noqa: E402
    AccessibilityDenied,
    ComposeRefused,
)

_REAL_FIND_OWN_DRAFT = mail_reply_cleanup.find_own_draft
_OPEN_OK = f"28{US}15927"
_RECIPIENTS_OK = (
    f"to{US}alice@corp.com{RS}sender{US}orig-sender@corp.com{RS}"
    f"subject{US}Quarterly numbers{RS}self{US}bob@corp.com{RS}"
)
_ORIGINAL_TEXT = "alpha beta gamma delta epsilon zeta eta theta"
_TAIL = "gamma delta epsilon zeta eta theta"  # the last six words


class _ReplyRig:
    """Fakes every seam of the reply flow and records the calls in order."""

    def __init__(self, monkeypatch, **kw):
        self.calls: list = []
        self.answers = {
            "_ORIGINAL": _original_reply(_ORIGINAL_TEXT),
            "_OUTGOING_IDS": "3,4",
            "_REPLY_OPEN": _OPEN_OK,
            "_DISCARD_OUTGOING": "dead",
            "_DISCARD_NEW_REPLY": "dead",
            "_SWEEP_DELETE": "deleted",
            "_SEND_OUTGOING": "sent",
            "_OUTBOX_COUNT": "0",
            "_REPLY_ALL_RECIPIENTS": _RECIPIENTS_OK,
        }
        self.answers.update(kw.pop("answers", {}))
        self.trusted = kw.pop("trusted", True)
        self.insert_error = kw.pop("insert_error", None)
        self.insert_hook = kw.pop("insert_hook", None)
        # the Drafts sweep: the index top, a fake clock and wait, a fake index reader
        top = kw.pop("top", 7)
        top_after = kw.pop("top_after", None)  # the index top right after the discard
        found = kw.pop("found", None) or mail_reply_cleanup.Draft("none")
        assert not kw, kw
        self.waits: list[float] = []
        self.found_args: list = []
        self.found_kw: list = []
        self.threads: list[str] = []
        self.clock = [
            100.0
        ]  # the fake monotonic clock; a wait moves it to its deadline
        monkeypatch.setattr(runtime, "accessibility_trusted", self._trusted)
        monkeypatch.setattr(runtime, "compose_insert", self._insert)
        _patch_run(monkeypatch, self._osa)

        def wait(deadline):
            self.waits.append(deadline)
            self.clock[0] = max(self.clock[0], deadline)

        monkeypatch.setattr(mail_outgoing, "_wait_until", wait)
        monkeypatch.setattr(
            mail_outgoing, "time", SimpleNamespace(monotonic=lambda: self.clock[0])
        )

        tops = [top, top_after if top_after is not None else top]

        def index_top():
            # the first read is the baseline before the open, the next ones follow
            # the discard (the flow takes one right after the discard answers)
            self.calls.append(("index_top",))
            return tops[0] if len(self.calls_of("index_top")) == 1 else tops[1]

        monkeypatch.setattr(mail_reply_cleanup, "index_top", index_top)

        def find(top, mid, text, attribution, **kw):
            self.found_args.append((top, mid, text, attribution))
            self.found_kw.append(kw)
            if isinstance(found, Exception):
                raise found
            return found

        monkeypatch.setattr(mail_reply_cleanup, "find_own_draft", find)

    def _trusted(self):
        self.threads.append(threading.current_thread().name)
        self.calls.append(("accessibility_trusted",))
        return self.trusted

    def _names(self):
        return {
            getattr(mail_outgoing, n): n
            for n in (
                "_ORIGINAL",
                "_OUTGOING_IDS",
                "_REPLY_OPEN",
                "_DISCARD_OUTGOING",
                "_DISCARD_NEW_REPLY",
                "_SWEEP_DELETE",
                "_SEND_OUTGOING",
                "_OUTBOX_COUNT",
                "_REPLY_ALL_RECIPIENTS",
            )
        }

    def _osa(self, script, *argv, **kw):
        self.threads.append(threading.current_thread().name)
        name = self._names()[script]
        self.calls.append((name, argv, kw))
        answer = self.answers[name]
        if isinstance(answer, Exception):
            raise answer
        return answer

    def _insert(self, window_id, text, **kw):
        self.threads.append(threading.current_thread().name)
        self.calls.append(("compose_insert", window_id, text, kw))
        if self.insert_hook:
            self.insert_hook(kw)
        if self.insert_error:
            raise self.insert_error

    def names(self):
        return [c[0] for c in self.calls]

    def calls_of(self, name):
        return [c for c in self.calls if c[0] == name]

    def call(self, name):
        return next(c for c in self.calls if c[0] == name)


def test_reply_keeps_mails_quote_through_the_insert_seam(monkeypatch):
    rig = _ReplyRig(monkeypatch)
    out = mail.MailAdapter().reply("<abc@x>", "inbox", "Hi", include_quote=True)
    assert out["created"] is True and out["mailbox"] == "Drafts"
    assert rig.names() == [
        "accessibility_trusted",
        "_ORIGINAL",  # facts 4e Confirm: the tail comes from the original's own text
        "_OUTGOING_IDS",
        "index_top",  # the sweep baseline is taken BEFORE the window opens
        "_REPLY_OPEN",
        "compose_insert",
    ]
    _, argv, kw = rig.call("_REPLY_OPEN")
    assert argv == ("abc@x", "", "inbox", "0")
    assert kw == {"timeout": mail_outgoing.ORIGINAL_TIMEOUT}
    _, window_id, text, ikw = rig.call("compose_insert")
    assert (window_id, text) == (15927, "Hi")
    assert ikw["replace_all"] is False and ikw["quote_tail"] == _TAIL
    assert callable(ikw["rollback"])
    # no tempfile, no content write on this path
    assert "set content" not in mail_outgoing._REPLY_OPEN


def test_reply_refuses_before_any_write_without_accessibility(monkeypatch):
    rig = _ReplyRig(monkeypatch, trusted=False)
    with pytest.raises(AccessibilityDenied) as exc:
        mail.MailAdapter().reply("<abc@x>", "inbox", "Hi")
    msg = str(exc.value)
    assert "Device Control and Data Access" in msg and "Accessibility" in msg
    assert "nothing was created" in msg.lower() and "restart" not in msg.lower()
    assert rig.names() == ["accessibility_trusted"]  # no osascript call at all


def test_reply_refuses_an_unreadable_original_before_opening_anything(monkeypatch):
    rig = _ReplyRig(monkeypatch, answers={"_ORIGINAL": "missing value"})
    with pytest.raises(ComposeRefused) as exc:
        mail.MailAdapter().reply("<abc@x>", "inbox", "Hi")
    assert "include_quote=False" in str(exc.value)
    assert "nothing was created" in str(exc.value).lower()
    assert "_REPLY_OPEN" not in rig.names()


def test_reply_discards_the_reply_when_the_insert_is_refused(monkeypatch):
    rig = _ReplyRig(
        monkeypatch, insert_error=ComposeRefused("confirmation: the text did not land")
    )
    with pytest.raises(ComposeRefused) as exc:
        mail.MailAdapter().reply("<abc@x>", "inbox", "Hi")
    _, argv, kw = rig.call("_DISCARD_OUTGOING")
    assert argv == ("28",) and kw == {"timeout": mail_outgoing.ORIGINAL_TIMEOUT}
    msg = str(exc.value)
    assert "confirmation" in msg and "nothing was created" in msg
    assert "nothing was sent" in msg
    assert isinstance(exc.value.__cause__, ComposeRefused)


def test_reply_refusal_is_loud_when_the_discard_is_not_proven(monkeypatch):
    for answer in ("alive", NativeTimeout("slow")):
        _ReplyRig(
            monkeypatch,
            insert_error=ComposeRefused("insert: refused"),
            answers={"_DISCARD_OUTGOING": answer},
        )
        with pytest.raises(ComposeRefused) as exc:
            mail.MailAdapter().reply("<abc@x>", "inbox", "Hi")
        msg = str(exc.value)
        assert "nothing was created" not in msg
        assert "Drafts" in msg and "reply window" in msg
        assert "nothing was sent" in msg.lower()


def test_reply_discards_once_when_compose_insert_rolls_back_itself(monkeypatch):
    # facts 4e Pasteboard: an unsettled paste rolls the reply back BEFORE the restore,
    # through the callback; the outer discard must not run a second script
    def hook(kw):
        kw["rollback"]()

    rig = _ReplyRig(
        monkeypatch,
        insert_hook=hook,
        insert_error=ComposeRefused("confirmation: not settled"),
    )
    with pytest.raises(ComposeRefused) as exc:
        mail.MailAdapter().reply("<abc@x>", "inbox", "Hi")
    assert rig.names().count("_DISCARD_OUTGOING") == 1
    assert "nothing was created" in str(exc.value)


@pytest.mark.parametrize("failure", ["timeout", "garbage"])
def test_reply_discards_without_an_id_when_the_open_fails(monkeypatch, failure):
    bad = NativeTimeout("no answer") if failure == "timeout" else "not-a-reply"
    rig = _ReplyRig(monkeypatch, answers={"_REPLY_OPEN": bad})
    with pytest.raises(ComposeRefused) as exc:
        mail.MailAdapter().reply("<abc@x>", "inbox", "Hi")
    _, argv, kw = rig.call("_DISCARD_NEW_REPLY")
    assert argv == ("3,4", "abc@x", "", "inbox")
    assert kw == {"timeout": mail_outgoing.ORIGINAL_TIMEOUT}
    assert (
        "_DISCARD_OUTGOING" not in rig.names() and "compose_insert" not in rig.names()
    )
    assert "nothing was created" in str(exc.value)


@pytest.mark.parametrize("answer", ["none", "several", "alive", "original-missing"])
def test_reply_id_free_discard_that_proves_nothing_is_loud(monkeypatch, answer):
    _ReplyRig(
        monkeypatch,
        answers={
            "_REPLY_OPEN": NativeTimeout("no answer"),
            "_DISCARD_NEW_REPLY": answer,
        },
    )
    with pytest.raises(ComposeRefused) as exc:
        mail.MailAdapter().reply("<abc@x>", "inbox", "Hi")
    msg = str(exc.value)
    assert "nothing was created" not in msg
    assert "reply window" in msg and "Drafts" in msg
    assert "nothing was sent" in msg.lower()


def test_reply_without_quote_replaces_the_whole_body(monkeypatch):
    # gap-no-quote: gui-replace (owner choice 2026-10-31)
    rig = _ReplyRig(monkeypatch)
    mail.MailAdapter().reply("<abc@x>", "inbox", "Just this", include_quote=False)
    assert "_ORIGINAL" not in rig.names()  # no quote, so no tail to look up
    _, _, text, ikw = rig.call("compose_insert")
    assert text == "Just this" and ikw["replace_all"] is True
    assert ikw["quote_tail"] is None


# --- rollback-sweep: the autosaved Drafts copy of a refused reply (facts 4e) --

_DRAFTS_URL = f"imap://{_GMAIL_UUID}/Drafts"
_REPLY_FOLDER = f"imap://{_GMAIL_UUID}/INBOX"  # a folder token names the account


class _SweepRig(_ReplyRig):
    """The reply rig, whose Drafts sweep finds one proven copy by default, with no
    other compose window open at the start (an empty ``_OUTGOING_IDS`` baseline) and an
    index top after the discard that is above every row a test stores."""

    def __init__(self, monkeypatch, found=None, **kw):
        kw["answers"] = {"_OUTGOING_IDS": "", **kw.get("answers", {})}
        kw.setdefault("top_after", 1000)
        super().__init__(
            monkeypatch,
            found=found or mail_reply_cleanup.Draft("one", _DRAFTS_URL, "<d@x>"),
            **kw,
        )


def _refused_reply(monkeypatch, **kw):
    rig = _SweepRig(
        monkeypatch, insert_error=ComposeRefused("confirmation: not there"), **kw
    )
    with pytest.raises(ComposeRefused) as exc:
        mail.MailAdapter().reply("<abc@x>", _REPLY_FOLDER, "Hi")
    return rig, str(exc.value)


def test_reply_sweeps_its_own_autosaved_copy_after_a_refusal(monkeypatch):
    rig, msg = _refused_reply(monkeypatch)
    # owner decision 2026-11-01: one bounded wait until 45 s after the window opened
    assert rig.waits == [145.0]
    # every new row above the baseline is read, in any mailbox; the selector gets
    # Mail's attribution line for the original (stamp faked by conftest)
    attribution = "On 1 Jul 2026, at 14:39, Jane <j@x.com> wrote:"
    assert rig.found_args == [(7, "abc@x", "Hi", attribution)]
    _, argv, kw = rig.call("_SWEEP_DELETE")
    assert argv == ("d@x", _GMAIL_UUID, "Drafts")  # the Drafts the copy sits in
    assert kw == {"timeout": mail_outgoing.ORIGINAL_TIMEOUT}
    names = rig.names()
    assert names.index("_DISCARD_OUTGOING") < names.index("_SWEEP_DELETE")
    assert "nothing was created" in msg and "deleted" in msg


def test_reply_sweep_that_finds_nothing_says_when_it_looked(monkeypatch):
    rig, msg = _refused_reply(monkeypatch, found=mail_reply_cleanup.Draft("none"))
    assert "_SWEEP_DELETE" not in rig.names()
    assert "nothing was created" in msg and "45 s" in msg


@pytest.mark.parametrize("kind", ["unproven"])
def test_reply_sweep_that_cannot_prove_the_copy_is_its_own_deletes_nothing(
    monkeypatch, kind
):
    rig, msg = _refused_reply(monkeypatch, found=mail_reply_cleanup.Draft(kind))
    assert "_SWEEP_DELETE" not in rig.names()
    assert "nothing was created" not in msg
    assert "Drafts" in msg and "reply window" in msg


def test_reply_sweep_whose_delete_is_not_confirmed_is_loud(monkeypatch):
    _, msg = _refused_reply(monkeypatch, answers={"_SWEEP_DELETE": "alive"})
    assert "nothing was created" not in msg and "Drafts" in msg


@pytest.mark.parametrize("failure", [NativeTimeout("slow"), RuntimeError("boom")])
def test_reply_sweep_whose_delete_raises_is_loud(monkeypatch, failure):
    # a delete that raised proves nothing: the copy may still be there, so the refusal
    # must not claim it was removed (a mutant that reported "removed" passed CI)
    rig, msg = _refused_reply(monkeypatch, answers={"_SWEEP_DELETE": failure})
    assert "_SWEEP_DELETE" in rig.names()
    assert "nothing was created" not in msg and "was found and deleted" not in msg
    assert "Drafts" in msg and "reply window" in msg


def test_reply_sweep_is_unavailable_without_an_index_baseline(monkeypatch):
    rig, msg = _refused_reply(monkeypatch, top=None)
    assert rig.waits == [] and rig.found_args == []  # no point waiting
    assert "nothing was created" not in msg and "Drafts" in msg
    # the refusal comes seconds after the open: say the copy may still land
    assert "up to about a minute" in msg and "account the reply is sent from" in msg


def test_reply_sweep_that_cannot_read_the_index_afterwards_is_loud(monkeypatch):
    rig, msg = _refused_reply(monkeypatch, found=NativeTimeout("gone"))
    assert "nothing was created" not in msg and "Drafts" in msg


@pytest.mark.parametrize(
    "failure", [UnboundLocalError("pos"), ValueError("bad"), OSError("gone")]
)
def test_reply_sweep_read_that_raises_anything_still_ends_in_the_loud_refusal(
    monkeypatch, failure
):
    # CPython's header parser raises UnboundLocalError on a malformed In-Reply-To
    rig, msg = _refused_reply(monkeypatch, found=failure)
    assert "_SWEEP_DELETE" not in rig.names()
    assert "mail_reply did not complete" in msg
    assert "nothing was created" not in msg
    assert "Drafts" in msg and "reply window" in msg
    assert "nothing was sent" in msg.lower()
    assert type(failure).__name__ not in msg  # a foreign error text is never echoed


def test_reply_refusal_never_echoes_a_foreign_exceptions_text(monkeypatch):
    # an unexpected exception could carry the reply text: only its type name is said
    _SweepRig(monkeypatch, insert_error=RuntimeError("the secret reply text"))
    with pytest.raises(ComposeRefused) as exc:
        mail.MailAdapter().reply("<abc@x>", _REPLY_FOLDER, "Hi")
    assert "secret" not in str(exc.value) and "RuntimeError" in str(exc.value)


def test_reply_sweep_waits_from_the_failed_open_when_the_window_time_is_unknown(
    monkeypatch,
):
    rig = _SweepRig(monkeypatch, answers={"_REPLY_OPEN": NativeTimeout("no answer")})
    with pytest.raises(ComposeRefused):
        mail.MailAdapter().reply("<abc@x>", _REPLY_FOLDER, "Hi")
    assert rig.waits == [145.0]


def test_reply_sweep_counts_45_s_from_when_the_open_returned(monkeypatch):
    # an open that takes 30 s moves the deadline by 30 s (the clock starts at the open)
    rig = _SweepRig(monkeypatch, insert_error=ComposeRefused("confirmation: no"))
    real = rig._osa

    def osa(script, *argv, **kw):
        out = real(script, *argv, **kw)
        if script is mail_outgoing._REPLY_OPEN:
            rig.clock[0] += 30.0
        return out

    _patch_run(monkeypatch, osa)
    with pytest.raises(ComposeRefused):
        mail.MailAdapter().reply("<abc@x>", _REPLY_FOLDER, "Hi")
    assert rig.waits == [175.0]


def test_reply_sweep_that_reads_right_after_a_late_discard_cannot_say_nothing_was_left(
    monkeypatch,
):
    # facts 4e: a read straight after a discard was never tested. The window lived past
    # +45 s (a stalled Mail), so the read follows the discard at once: say a copy may
    # still land, never "nothing was created".
    def stall(_kw):
        rig.clock[0] += 60.0

    rig = _SweepRig(
        monkeypatch,
        found=mail_reply_cleanup.Draft("none"),
        insert_hook=stall,
        insert_error=ComposeRefused("confirmation: no"),
    )
    with pytest.raises(ComposeRefused) as exc:
        mail.MailAdapter().reply("<abc@x>", _REPLY_FOLDER, "Hi")
    msg = str(exc.value)
    assert rig.waits == [145.0] and rig.found_args  # still waited, still read
    assert "nothing was created" not in msg and "no Drafts copy was there" not in msg
    assert "may still land" in msg
    assert "Drafts" in msg and "nothing was sent" in msg.lower()


def test_reply_sweep_counts_its_gap_from_the_end_of_the_discard(monkeypatch):
    # Mail answers the discard 40 s late (ORIGINAL_TIMEOUT is 120 s): the read follows
    # the END of the discard by 5 s, which the sitting never tested. A gap counted from
    # the start of the discard would read 45 s and call the mailbox clean.
    rig = _SweepRig(
        monkeypatch,
        found=mail_reply_cleanup.Draft("none"),
        insert_error=ComposeRefused("confirmation: no"),
    )
    real = rig._osa

    def osa(script, *argv, **kw):
        out = real(script, *argv, **kw)
        if script is mail_outgoing._DISCARD_OUTGOING:
            rig.clock[0] += 40.0
        return out

    _patch_run(monkeypatch, osa)
    with pytest.raises(ComposeRefused) as exc:
        mail.MailAdapter().reply("<abc@x>", _REPLY_FOLDER, "Hi")
    msg = str(exc.value)
    assert "may still land" in msg and "nothing was created" not in msg


@pytest.mark.parametrize("discard", ["alive", NativeTimeout("slow")])
def test_reply_sweep_that_reads_late_after_an_unproven_discard_does_not_say_discarded(
    monkeypatch, discard
):
    # the discard is not proven (`alive`, or no answer) AND the read followed it too
    # closely: the window may still be open, so "The reply was discarded" is false
    def stall(_kw):
        rig.clock[0] += 60.0

    rig = _SweepRig(
        monkeypatch,
        found=mail_reply_cleanup.Draft("none"),
        insert_hook=stall,
        insert_error=ComposeRefused("confirmation: no"),
        answers={"_DISCARD_OUTGOING": discard},
    )
    with pytest.raises(ComposeRefused) as exc:
        mail.MailAdapter().reply("<abc@x>", _REPLY_FOLDER, "Hi")
    msg = str(exc.value)
    assert "The reply was discarded" not in msg and "nothing was created" not in msg
    assert "reply window" in msg and "Drafts" in msg


def test_reply_sweep_trusts_a_read_that_follows_the_discard_by_the_proven_gap(
    monkeypatch,
):
    # discard at +2 s, read at +45 s: the shape of the sitting
    rig, msg = _refused_reply(monkeypatch, found=mail_reply_cleanup.Draft("none"))
    assert "nothing was created" in msg

    # discard at +20 s, read at +45 s: 25 s is under the proven 35 s gap
    def stall(_kw):
        rig.clock[0] += 20.0

    rig = _SweepRig(
        monkeypatch,
        found=mail_reply_cleanup.Draft("none"),
        insert_hook=stall,
        insert_error=ComposeRefused("confirmation: no"),
    )
    with pytest.raises(ComposeRefused) as exc:
        mail.MailAdapter().reply("<abc@x>", _REPLY_FOLDER, "Hi")
    assert "nothing was created" not in str(exc.value)


_ATTRIBUTION_LINE = "On 1 Jul 2026, at 14:39, Jane <j@x.com> wrote:"  # from _ORIGINAL
_ATTRIBUTION_HTML = "On 1 Jul 2026, at 14:39, Jane &lt;j@x.com&gt; wrote:"
_QUOTE_HTML = (
    f"<blockquote>{_ORIGINAL_TEXT}</blockquote>"  # carries the original's tail
)


def _real_selector(monkeypatch, *stored):
    """The REAL selector over a faked index: ``stored`` is ``(url, body, kind)`` per new
    row (rowids 8, 9, ...), each a reply to the original."""
    monkeypatch.setattr(mail_reply_cleanup, "find_own_draft", _REAL_FIND_OWN_DRAFT)
    rows = [(8 + n, url) for n, (url, _, _) in enumerate(stored)]
    monkeypatch.setattr(mail_reply_cleanup, "new_rows", lambda top: rows)

    def read(url, rowid):
        _, body, kind = stored[rowid - 8]
        msg = email.message.EmailMessage(policy=email.policy.default)
        msg.set_content(body, subtype=kind)
        return ("<abc@x>", f"<own{rowid}@x>", lambda: msg)

    monkeypatch.setattr(mail_reply_cleanup, "_read_draft", read)


def _refuse_with(monkeypatch, text="Hi", folder=_REPLY_FOLDER, **kw):
    rig = _SweepRig(monkeypatch, insert_error=ComposeRefused("confirmation: no"), **kw)
    return rig, folder, text


def _run_refused(rig, folder, text):
    with pytest.raises(ComposeRefused) as exc:
        mail.MailAdapter().reply("<abc@x>", folder, text)
    return str(exc.value)


@pytest.mark.parametrize(
    "text, hand",
    [
        ("Hi", "Hi Jane, sorry, I cannot make it."),
        ("Thanks!", "Thanks! I'll check it tomorrow and send the figures."),
    ],
)
@pytest.mark.parametrize("kind", ["html", "plain"])
def test_reply_flow_never_deletes_a_hand_reply_that_starts_with_the_calls_text(
    monkeypatch, text, hand, kind
):
    # the owner rule: a draft that is not PROVABLY the call's own is never touched. A
    # short call text is the start of the owner's own reply to the same original.
    rig, folder, _ = _refuse_with(monkeypatch)
    if kind == "html":
        body = f"<div>{hand}</div><blockquote>{_ATTRIBUTION_HTML} q</blockquote>"
    else:
        body = f"{hand}\n\n{_ATTRIBUTION_LINE}\n> quoted\n"
    _real_selector(monkeypatch, (_DRAFTS_URL, body, kind))
    msg = _run_refused(rig, folder, text)
    assert "_SWEEP_DELETE" not in rig.names()
    assert "nothing was created" not in msg and "was found and deleted" not in msg
    assert "Drafts" in msg and "reply window" in msg


def test_reply_flow_never_deletes_an_empty_hand_reply_to_the_same_original(
    monkeypatch,
):
    rig, folder, text = _refuse_with(monkeypatch)
    _real_selector(monkeypatch, (_DRAFTS_URL, "", "plain"))
    msg = _run_refused(rig, folder, text)
    assert "_SWEEP_DELETE" not in rig.names()
    assert "nothing was created" not in msg and "Drafts" in msg


@pytest.mark.parametrize("kind", ["html", "plain"])
def test_reply_flow_deletes_the_copy_that_is_exactly_its_text_and_mails_attribution(
    monkeypatch, kind
):
    # the attribution line comes from the ORIGINAL the flow read, and is allowed once,
    # after the call's text
    rig, folder, text = _refuse_with(monkeypatch)
    if kind == "html":
        body = f"<div>Hi</div><div>{_ATTRIBUTION_HTML}</div>{_QUOTE_HTML}"
    else:
        body = f"Hi\n\n{_ATTRIBUTION_LINE}\n> {_ORIGINAL_TEXT}\n"
    _real_selector(monkeypatch, (_DRAFTS_URL, body, kind))
    msg = _run_refused(rig, folder, text)
    _, argv, _ = rig.call("_SWEEP_DELETE")
    assert argv == ("own8@x", _GMAIL_UUID, "Drafts")
    assert "nothing was created" in msg and "deleted" in msg


def test_reply_flow_deletes_a_copy_in_the_account_the_reply_is_sent_from(monkeypatch):
    # spike 005: a reply to a message in this inbox can be sent from ANOTHER account,
    # and Mail files the autosave in that account's Drafts. The copy is the call's own.
    other = "imap://77777777-6666-5555-4444-333333333333/Drafts"
    rig, folder, text = _refuse_with(monkeypatch)
    _real_selector(monkeypatch, (other, "<div>Hi</div>" + _QUOTE_HTML, "html"))
    msg = _run_refused(rig, folder, text)
    _, argv, _ = rig.call("_SWEEP_DELETE")
    assert argv == ("own8@x", "77777777-6666-5555-4444-333333333333", "Drafts")
    assert "nothing was created" in msg


def test_reply_flow_reports_a_copy_in_a_localized_drafts_and_deletes_nothing(
    monkeypatch,
):
    rig, folder, text = _refuse_with(monkeypatch)
    url = f"imap://{_GMAIL_UUID}/Concepten"
    _real_selector(monkeypatch, (url, "<div>Hi</div>", "html"))
    msg = _run_refused(rig, folder, text)
    assert "_SWEEP_DELETE" not in rig.names()
    assert "nothing was created" not in msg and "Drafts" in msg


# --- rv532: ownership beyond equal text, retry, gap timing, refusal texts ---------


def test_reply_sweep_deletes_nothing_when_another_compose_window_was_open(monkeypatch):
    # a retry: the first call's reply window is still open and its OWN autosave (same
    # original, same text) lands during this call's wait. The baseline lists that
    # window, so no copy can be proven this call's own (facts 4e `Refusal cleanup`).
    rig, msg = _refused_reply(monkeypatch, answers={"_OUTGOING_IDS": "28"})
    assert "_SWEEP_DELETE" not in rig.names()
    assert "nothing was created" not in msg and "was found and deleted" not in msg
    assert "may NOT be fully removed" in msg and "Drafts" in msg


def test_reply_sweep_that_finds_no_copy_still_says_so_beside_an_open_window(
    monkeypatch,
):
    # no new row threads to the original anywhere: that is true whoever else is open
    _, msg = _refused_reply(
        monkeypatch,
        found=mail_reply_cleanup.Draft("none"),
        answers={"_OUTGOING_IDS": "28"},
    )
    assert "nothing was created" in msg


def test_reply_flow_hands_the_selector_the_tail_and_the_top_after_the_discard(
    monkeypatch,
):
    rig, _ = _refused_reply(monkeypatch, top_after=55)
    assert rig.found_kw == [{"tail": _TAIL, "landed_by": 55}]
    # the second index read follows the discard answer (the first is the baseline)
    names = rig.names()
    assert names.count("index_top") == 2
    assert names.index("_DISCARD_OUTGOING") < len(names) - 1 - names[::-1].index(
        "index_top"
    )
    assert names.index("index_top") < names.index("_REPLY_OPEN")
    # a reply without a quote has no tail: nothing may follow the text
    rig = _SweepRig(monkeypatch, insert_error=ComposeRefused("confirmation: no"))
    with pytest.raises(ComposeRefused):
        mail.MailAdapter().reply("<abc@x>", _REPLY_FOLDER, "Hi", include_quote=False)
    assert rig.found_kw[0]["tail"] is None


def test_reply_flow_reads_the_top_once_even_when_the_discard_runs_twice(monkeypatch):
    # compose_insert rolls back through the callback, then the outer refusal discards
    # again: the second call returns the first answer and reads nothing
    rig = _SweepRig(
        monkeypatch,
        insert_hook=lambda kw: kw["rollback"](),
        insert_error=ComposeRefused("confirmation: no"),
    )
    with pytest.raises(ComposeRefused):
        mail.MailAdapter().reply("<abc@x>", _REPLY_FOLDER, "Hi")
    assert rig.names().count("index_top") == 2


def test_reply_flow_with_an_unreadable_top_after_the_discard_proves_nothing(
    monkeypatch,
):
    rig, folder, text = _refuse_with(monkeypatch, top_after=None)
    # the baseline was readable (7), the read after the discard is not
    monkeypatch.setattr(
        mail_reply_cleanup,
        "index_top",
        iter([7, None]).__next__,
    )
    _real_selector(monkeypatch, (_DRAFTS_URL, "<div>Hi</div>" + _QUOTE_HTML, "html"))
    msg = _run_refused(rig, folder, text)
    assert "_SWEEP_DELETE" not in rig.names()
    assert "nothing was created" not in msg


_FAMILY_DRAFTS = "imap://77777777-6666-5555-4444-333333333333/Drafts"
_OWN_BODY = "<div>Hi</div>" + _QUOTE_HTML


_PLAIN_RETYPE = f"Hi\n\n{_ATTRIBUTION_LINE}\n> {_ORIGINAL_TEXT}\n"
_LOOKALIKES = [
    # a family member's draft with the same text, in her own Drafts
    (_FAMILY_DRAFTS, _OWN_BODY, "html"),
    # the owner's plain-text retype of the same text, after the window flashed shut
    (_DRAFTS_URL, _PLAIN_RETYPE, "plain"),
]
_WRONG_SHAPES = [
    # the same text with a trimmed quote, or none
    (_DRAFTS_URL, "<div>Hi</div><blockquote>owner trimmed it</blockquote>", "html"),
    (_DRAFTS_URL, "<div>Hi</div>", "html"),
    # a user folder with a bracketed name
    (f"imap://{_GMAIL_UUID}/%5BArchive%202019%5D/Drafts", _OWN_BODY, "html"),
]


def _lookalike_flow(monkeypatch, url, body, kind, top_after):
    rig, folder, text = _refuse_with(monkeypatch, top_after=top_after)
    _real_selector(monkeypatch, (url, body, kind))
    return rig, _run_refused(rig, folder, text)


@pytest.mark.parametrize("url, body, kind", _LOOKALIKES + _WRONG_SHAPES)
def test_reply_flow_never_deletes_a_draft_that_landed_after_the_discard(
    monkeypatch, url, body, kind
):
    # row 8 is above the index top read right after the discard (7): it landed once
    # the window was gone, so whatever its text, it is not proven the window's own
    rig, msg = _lookalike_flow(monkeypatch, url, body, kind, top_after=7)
    assert "_SWEEP_DELETE" not in rig.names()
    assert "nothing was created" not in msg and "was found and deleted" not in msg
    assert "may NOT be fully removed" in msg


@pytest.mark.parametrize("url, body, kind", _WRONG_SHAPES)
def test_reply_flow_never_deletes_a_copy_without_the_calls_text_and_quote_in_drafts(
    monkeypatch, url, body, kind
):
    # even when the row predates the discard: a trimmed or removed quote, or a Drafts
    # that is a user folder, is not the call's own copy
    rig, msg = _lookalike_flow(monkeypatch, url, body, kind, top_after=1000)
    assert "_SWEEP_DELETE" not in rig.names()
    assert "nothing was created" not in msg and "may NOT be fully removed" in msg


def test_reply_sweep_counts_its_gap_to_the_read_not_to_the_end_of_the_read(
    monkeypatch,
):
    # the discard ran at +16 s; the read starts at +45 s (29 s later, under the proven
    # gap) and takes 2 s. A gap measured after the read would call it 31 s and clean.
    rig = _SweepRig(
        monkeypatch,
        found=mail_reply_cleanup.Draft("none"),
        insert_error=ComposeRefused("confirmation: no"),
    )

    def stall(_kw):
        rig.clock[0] += 16.0

    rig.insert_hook = stall

    real_find = mail_reply_cleanup.find_own_draft

    def find(*args, **kw):
        out = real_find(*args, **kw)
        rig.clock[0] += 2.0  # the files of the new rows are read after the snapshot
        return out

    monkeypatch.setattr(mail_reply_cleanup, "find_own_draft", find)
    with pytest.raises(ComposeRefused) as exc:
        mail.MailAdapter().reply("<abc@x>", _REPLY_FOLDER, "Hi")
    msg = str(exc.value)
    assert "may still land" in msg and "nothing was created" not in msg


def test_reply_refusal_after_a_proven_discard_does_not_send_the_user_to_a_window(
    monkeypatch,
):
    # the window is gone (-1728 proof): only a Drafts copy may be left
    _, msg = _refused_reply(monkeypatch, found=mail_reply_cleanup.Draft("unproven"))
    assert "The reply window was discarded" in msg
    assert "Look for the open reply window" not in msg
    assert "may NOT be fully removed" in msg and "Drafts" in msg


def test_reply_refusal_says_a_copy_was_deleted_when_the_discard_was_not_proven(
    monkeypatch,
):
    _, msg = _refused_reply(monkeypatch, answers={"_DISCARD_OUTGOING": "alive"})
    assert "was found and deleted" in msg and "may NOT be fully removed" in msg
    assert "reply window" in msg and "nothing was created" not in msg


@pytest.mark.parametrize("original", ["inbox", "imap://local-uuid/INBOX"])
def test_reply_to_an_alias_or_local_original_still_waits_and_sweeps(
    monkeypatch, original
):
    # no instant "may be left" for an original that names no real account: the sweep
    # reads every new row, so it needs no account (the old read needed one)
    rig, _, text = _refuse_with(monkeypatch)
    msg = _run_refused(rig, original, text)
    assert rig.waits == [145.0] and rig.found_args
    assert "nothing was created" in msg


def test_a_successful_reply_keeps_its_window_and_runs_no_sweep(monkeypatch):
    rig = _SweepRig(monkeypatch)
    mail.MailAdapter().reply("<abc@x>", "inbox", "Hi")
    assert rig.waits == [] and rig.found_args == []
    assert "_SWEEP_DELETE" not in rig.names() and "_DISCARD_OUTGOING" not in rig.names()


def test_the_whole_reply_flow_runs_in_one_run_native_closure(monkeypatch):
    rig = _SweepRig(monkeypatch, insert_error=ComposeRefused("confirmation: no"))
    entered: list[str] = []
    real = runtime.run_native
    monkeypatch.setattr(
        runtime, "run_native", lambda fn: entered.append("run_native") or real(fn)
    )
    with pytest.raises(ComposeRefused):
        mail.MailAdapter().reply("<abc@x>", _REPLY_FOLDER, "Hi")
    assert entered == ["run_native"]  # entered exactly once per call
    # the trust check, every Mail script and the insert all ran on the one worker
    assert len(rig.threads) >= 5
    assert all(t.startswith("mac-native") for t in rig.threads)


def test_sweep_delete_script_takes_one_message_from_the_named_mailbox():
    script = mail_outgoing._SWEEP_DELETE
    assert "on mailboxFor(" in script and "with timeout of 120 seconds" in script
    assert "messages of mb whose message id is mid" in script
    assert "unified" not in script and "drafts mailbox" not in script.replace(
        mail_addressing.MAILBOX_REF, ""
    )
    assert '(count of matches) > 1 then return "several"' in script
    assert script.count("delete ") == 1


def test_sweep_delete_reads_the_result_once_after_the_asynchronous_delete():
    # facts 5c: `delete` clears the source asynchronously (t0 src=1, t3 src=0), so the
    # check is NOT an immediate re-count; it is one bounded wait, then one re-count
    script = mail_outgoing._SWEEP_DELETE
    body = script[script.index("delete (item 1 of matches)") :]
    assert body.count("delay ") == 1 and "repeat" not in script  # one wait, no loop
    assert body.index("delay 3") < body.index("count of (messages of mb")
    assert body.count("count of (messages of mb whose message id is mid)") == 1
    assert 'return "deleted"' in body and 'return "alive"' in body


# --- FIX-16 (#348): reply_all keeps Mail's own quote, sends after a confirmed insert --
#
# The same flow as mail_reply (one run_native closure, THE DISCARD RULE), then the send
# by outgoing message id (facts 3 and 4e `Send after insert`: no delete after the send
# verb), then the owner's rule of 2026-11-01: wait until 45 s after the window opened
# and sweep the call's own Drafts copy, whose outcome rides beside `sent`.

_SENT_URL = f"imap://{_GMAIL_UUID}/Sent%20Messages"
_ALL_MAIL_URL = f"imap://{_GMAIL_UUID}/%5BGmail%5D/All%20Mail"
_REPLY_ALL_SENT_ORDER = [
    "_REPLY_ALL_RECIPIENTS",  # the envelope, read before anything is built
    "accessibility_trusted",
    "_ORIGINAL",
    "_OUTGOING_IDS",
    "index_top",
    "_REPLY_OPEN",
    "compose_insert",
    "_SEND_OUTGOING",
    "index_top",  # right after the send answers: the window is gone
    "_SWEEP_DELETE",
    "_OUTBOX_COUNT",
]


def _reply_all(folder=_REPLY_FOLDER, text="Hi", **kw):
    return mail.MailAdapter().reply_all("<abc@x>", folder, text, dry_run=False, **kw)


def _sent_reply(monkeypatch, *stored, **kw):
    """A reply_all whose Drafts sweep runs the REAL selector over ``stored`` rows."""
    rig = _SweepRig(monkeypatch, **kw)
    if stored:
        _real_selector(monkeypatch, *stored)
    return rig, _reply_all()


def test_reply_all_sends_only_after_the_insert_is_confirmed(monkeypatch):
    rig = _SweepRig(monkeypatch)
    monkeypatch.setattr(
        runtime, "body_file", lambda text: pytest.fail("no tempfile on this path")
    )
    out = _reply_all()
    assert rig.names() == _REPLY_ALL_SENT_ORDER
    assert rig.call("_REPLY_OPEN")[1] == ("abc@x", _GMAIL_UUID, "INBOX", "1")
    _, window_id, text, ikw = rig.call("compose_insert")
    assert (window_id, text) == (15927, "Hi")
    assert ikw["replace_all"] is False and ikw["quote_tail"] == _TAIL
    _, argv, kw = rig.call("_SEND_OUTGOING")
    assert argv == ("28",) and kw == {"timeout": mail_outgoing.ORIGINAL_TIMEOUT}
    # the send is the only thing after the insert that talks to the reply: no discard
    assert "_DISCARD_OUTGOING" not in rig.names()
    assert "_ORIGINAL" in rig.names() and "set content" not in mail_outgoing._REPLY_OPEN
    assert out["sent"] is True and out["outbox_pending"] == 0
    assert out["to"] == ["orig-sender@corp.com"] and out["cc"] == ["alice@corp.com"]


def test_reply_all_waits_until_45_s_after_the_window_opened_then_sweeps(monkeypatch):
    rig = _SweepRig(monkeypatch)
    out = _reply_all()
    assert rig.waits == [145.0]  # owner decision 2026-11-01: opened at 100, +45 s
    attribution = "On 1 Jul 2026, at 14:39, Jane <j@x.com> wrote:"
    assert rig.found_args == [(7, "abc@x", "Hi", attribution)]
    # the index top read right after the send answers bounds what is the window's own
    assert rig.found_kw == [{"tail": _TAIL, "landed_by": 1000, "sent_twins": True}]
    _, argv, kw = rig.call("_SWEEP_DELETE")
    assert argv == ("d@x", _GMAIL_UUID, "Drafts")
    assert kw == {"timeout": mail_outgoing.ORIGINAL_TIMEOUT}
    names = rig.names()
    assert names.index("_SEND_OUTGOING") < names.index("_SWEEP_DELETE")
    assert out["sent"] is True and out["drafts_copy"] == "removed"
    assert "deleted" in out["drafts_copy_note"] and "sent" in out["drafts_copy_note"]


def test_reply_all_without_a_quote_replaces_the_body_and_sweeps_with_no_tail(
    monkeypatch,
):
    rig = _SweepRig(monkeypatch)
    out = _reply_all(text="Just this", include_quote=False)
    assert "_ORIGINAL" not in rig.names()  # no quote, so no tail to look up
    _, _, text, ikw = rig.call("compose_insert")
    assert text == "Just this" and ikw["replace_all"] is True
    assert ikw["quote_tail"] is None
    assert rig.found_kw[0]["tail"] is None and rig.found_args[0][3] is None
    assert out["sent"] is True


def test_reply_all_discards_and_never_sends_on_refusal(monkeypatch):
    rig = _SweepRig(
        monkeypatch, insert_error=ComposeRefused("confirmation: the text did not land")
    )
    with pytest.raises(ComposeRefused) as exc:
        _reply_all()
    msg = str(exc.value)
    assert "reply_all did not complete" in msg and "confirmation" in msg
    assert "nothing was sent" in msg and "nothing was created" in msg
    assert rig.call("_DISCARD_OUTGOING")[1] == ("28",)
    names = rig.names()
    assert "_SEND_OUTGOING" not in names and "_OUTBOX_COUNT" not in names


def test_reply_all_refusal_after_an_unproven_discard_is_loud_and_sends_nothing(
    monkeypatch,
):
    rig = _SweepRig(
        monkeypatch,
        insert_error=ComposeRefused("insert: refused"),
        answers={"_DISCARD_OUTGOING": "alive"},
    )
    with pytest.raises(ComposeRefused) as exc:
        _reply_all()
    msg = str(exc.value)
    assert "nothing was created" not in msg and "nothing was sent" in msg.lower()
    assert "_SEND_OUTGOING" not in rig.names()


def test_reply_all_discards_without_an_id_and_never_sends(monkeypatch):
    # facts 4e `Id-free discard: works`: the open timed out, so the id is unknown
    rig = _SweepRig(monkeypatch, answers={"_REPLY_OPEN": NativeTimeout("no answer")})
    with pytest.raises(ComposeRefused) as exc:
        _reply_all()
    _, argv, kw = rig.call("_DISCARD_NEW_REPLY")
    assert argv == ("", "abc@x", _GMAIL_UUID, "INBOX")
    assert kw == {"timeout": mail_outgoing.ORIGINAL_TIMEOUT}
    names = rig.names()
    assert "_SEND_OUTGOING" not in names and "compose_insert" not in names
    assert "nothing was sent" in str(exc.value)


def test_reply_all_refuses_without_accessibility_before_any_write(monkeypatch):
    rig = _SweepRig(monkeypatch, trusted=False)
    with pytest.raises(AccessibilityDenied) as exc:
        _reply_all()
    msg = str(exc.value)
    assert "reply_all needs Accessibility" in msg
    assert "Device Control and Data Access" in msg and "Accessibility" in msg
    assert "nothing was sent" in msg.lower() and "restart" not in msg.lower()
    # the only Mail script that ran is the recipients read (a read, strands nothing)
    assert rig.names() == ["_REPLY_ALL_RECIPIENTS", "accessibility_trusted"]


def test_reply_all_refuses_an_unreadable_original_before_opening_anything(monkeypatch):
    rig = _SweepRig(monkeypatch, answers={"_ORIGINAL": "missing value"})
    with pytest.raises(ComposeRefused) as exc:
        _reply_all()
    msg = str(exc.value)
    assert "reply_all cannot confirm" in msg and "include_quote=False" in msg
    assert "mail_reply" not in msg and "nothing was sent" in msg.lower()
    assert "_REPLY_OPEN" not in rig.names() and "_SEND_OUTGOING" not in rig.names()


def test_reply_all_dry_run_makes_no_gui_call(monkeypatch):
    rig = _SweepRig(monkeypatch)
    out = mail.MailAdapter().reply_all("<abc@x>", _REPLY_FOLDER, "Hi")
    assert out["dry_run"] is True
    assert rig.names() == ["_REPLY_ALL_RECIPIENTS"]  # no seam, no window, no message
    assert rig.waits == [] and rig.threads == [threading.current_thread().name]


def test_reply_all_runs_open_insert_and_send_in_one_run_native_closure(monkeypatch):
    rig = _SweepRig(monkeypatch)
    entered: list[str] = []
    real = runtime.run_native
    monkeypatch.setattr(
        runtime, "run_native", lambda fn: entered.append("run_native") or real(fn)
    )
    _reply_all()
    assert entered == ["run_native"]
    # everything between the trust check and the sweep ran on the one worker
    between = rig.names()[1:-1]
    assert "_SEND_OUTGOING" in between
    worker = [t for t in rig.threads if t.startswith("mac-native")]
    assert len(worker) >= 7


def test_a_send_that_fails_is_reported_as_possibly_sent_and_never_rolled_back(
    monkeypatch,
):
    # the send call is outside every rollback (facts 3): a timeout may mean Mail
    # accepted it after all, so the error says to look before a retry
    rig = _SweepRig(monkeypatch, answers={"_SEND_OUTGOING": NativeTimeout("slow")})
    with pytest.raises(NativeTimeout) as exc:
        _reply_all()
    msg = str(exc.value)
    assert "Outbox" in msg and "Sent" in msg and "before retrying" in msg
    assert "may have been sent" in msg
    names = rig.names()
    assert "_DISCARD_OUTGOING" not in names and "_DISCARD_NEW_REPLY" not in names
    assert "_SWEEP_DELETE" not in names and "_OUTBOX_COUNT" not in names


def test_a_foreign_failure_of_the_send_is_wrapped_without_its_text(monkeypatch):
    _SweepRig(monkeypatch, answers={"_SEND_OUTGOING": RuntimeError("the secret text")})
    with pytest.raises(NativeError) as exc:
        _reply_all()
    msg = str(exc.value)
    assert "secret" not in msg and "RuntimeError" in msg and "before retrying" in msg


def test_send_outgoing_has_no_delete_after_send():
    script = mail_outgoing._SEND_OUTGOING
    assert "outgoing message id ((item 1 of argv) as integer)" in script
    assert re.search(r"^\s*send r\s*$", script, re.M)
    assert "delete" not in script[script.index("send r") :]
    assert "delete" not in script and "on rollback" not in script
    assert "with timeout of 120 seconds" in script


# --- the sweep after a send (owner decision 2026-11-01; facts 4e `Send after insert`)

_OWN_COPY = ("imap://" + _GMAIL_UUID + "/Drafts", _OWN_BODY, "html")


def test_send_then_sweep_deletes_the_own_drafts_copy(monkeypatch):
    rig, out = _sent_reply(monkeypatch, _OWN_COPY)
    _, argv, _ = rig.call("_SWEEP_DELETE")
    assert argv == ("own8@x", _GMAIL_UUID, "Drafts")  # by its own id, in its own Drafts
    assert out["sent"] is True and out["drafts_copy"] == "removed"
    # facts 3: nothing is deleted off the outgoing message after the send verb
    assert "_DISCARD_OUTGOING" not in rig.names()


@pytest.mark.parametrize("twin_url", [_SENT_URL, _ALL_MAIL_URL])
def test_send_then_sweep_ignores_the_sent_messages_own_copies(monkeypatch, twin_url):
    # the sent message itself creates new rows threaded to the original: its Sent copy,
    # and on Gmail an All Mail twin. They are the send, not a leftover: never touched.
    rig, out = _sent_reply(monkeypatch, _OWN_COPY, (twin_url, _OWN_BODY, "html"))
    calls = rig.calls_of("_SWEEP_DELETE")
    assert [c[1] for c in calls] == [("own8@x", _GMAIL_UUID, "Drafts")]
    assert out["sent"] is True and out["drafts_copy"] == "removed"


def test_send_then_sweep_with_only_the_sent_copy_finds_no_drafts_copy(monkeypatch):
    rig, out = _sent_reply(monkeypatch, (_SENT_URL, _OWN_BODY, "html"))
    assert "_SWEEP_DELETE" not in rig.names()
    assert out["sent"] is True and out["drafts_copy"] == "none"
    assert "45 s" in out["drafts_copy_note"]


@pytest.mark.parametrize(
    "stranger",
    [
        # another reply to the same original, different text, in Sent
        (_SENT_URL, "<div>Something else</div>" + _QUOTE_HTML, "html"),
        # the same text in the Inbox with the quote trimmed away
        (f"imap://{_GMAIL_UUID}/INBOX", "<div>Hi</div>", "html"),
        # a second Drafts copy (a hand draft with the same text)
        (f"imap://{_GMAIL_UUID}/Drafts", _OWN_BODY, "html"),
    ],
)
def test_send_then_sweep_with_another_threaded_row_deletes_nothing(
    monkeypatch, stranger
):
    rig, out = _sent_reply(monkeypatch, _OWN_COPY, stranger)
    assert "_SWEEP_DELETE" not in rig.names()
    assert out["sent"] is True and out["drafts_copy"] == "unproven"  # send still ok
    assert "Drafts" in out["drafts_copy_note"]
    assert out["outbox_pending"] == 0


def test_send_then_sweep_with_an_unknown_row_alone_is_unproven(monkeypatch):
    rig, out = _sent_reply(
        monkeypatch, (_SENT_URL, "<div>Not ours</div>" + _QUOTE_HTML, "html")
    )
    assert "_SWEEP_DELETE" not in rig.names()
    assert out["sent"] is True and out["drafts_copy"] == "unproven"


def test_send_then_sweep_deletes_nothing_beside_an_open_compose_window(monkeypatch):
    # an earlier call's window is still open (a non-empty `_OUTGOING_IDS` baseline): its
    # autosave could hold the same text, so no copy is provably this call's own
    rig, out = _sent_reply(monkeypatch, _OWN_COPY, answers={"_OUTGOING_IDS": "21"})
    assert "_SWEEP_DELETE" not in rig.names()
    assert out["sent"] is True and out["drafts_copy"] == "unproven"


def test_send_then_sweep_never_claims_a_row_that_landed_after_the_send(monkeypatch):
    rig, out = _sent_reply(monkeypatch, _OWN_COPY, top_after=7)
    assert "_SWEEP_DELETE" not in rig.names()
    assert out["sent"] is True and out["drafts_copy"] == "unproven"


def test_send_then_sweep_whose_delete_is_not_confirmed_says_so(monkeypatch):
    _, out = _sent_reply(monkeypatch, _OWN_COPY, answers={"_SWEEP_DELETE": "alive"})
    assert out["sent"] is True and out["drafts_copy"] == "unproven"


@pytest.mark.parametrize("failure", [NativeTimeout("slow"), RuntimeError("boom")])
def test_send_then_sweep_whose_delete_raises_still_reports_the_send(
    monkeypatch, failure
):
    _, out = _sent_reply(monkeypatch, _OWN_COPY, answers={"_SWEEP_DELETE": failure})
    assert out["sent"] is True and out["drafts_copy"] == "unproven"
    assert out["outbox_pending"] == 0


@pytest.mark.parametrize(
    "found, outcome",
    [
        (mail_reply_cleanup.Draft("none"), "none"),
        (mail_reply_cleanup.Draft("unproven"), "unproven"),
        (NativeTimeout("gone"), "unavailable"),
        (UnboundLocalError("pos"), "unproven"),
        (OSError("gone"), "unproven"),
    ],
)
def test_send_then_sweep_outcomes_never_turn_the_send_into_an_error(
    monkeypatch, found, outcome
):
    rig = _SweepRig(monkeypatch, found=found)
    out = _reply_all()
    assert out["sent"] is True and out["drafts_copy"] == outcome
    assert out["drafts_copy_note"] and "_SWEEP_DELETE" not in rig.names()


def test_send_then_sweep_is_unavailable_without_an_index_baseline(monkeypatch):
    rig = _SweepRig(monkeypatch, top=None)
    out = _reply_all()
    assert rig.waits == [] and rig.found_args == []  # no point waiting
    assert out["sent"] is True and out["drafts_copy"] == "unavailable"
    assert "up to about a minute" in out["drafts_copy_note"]


def test_send_then_sweep_that_reads_too_soon_after_the_send_cannot_say_none(
    monkeypatch,
):
    # the send answered 25 s before the read: under the proven 30 s gap, so a copy that
    # has not landed cannot be ruled out (a slow Mail, the same rule as a late discard)
    rig = _SweepRig(monkeypatch, found=mail_reply_cleanup.Draft("none"))
    real = rig._osa

    def osa(script, *argv, **kw):
        out = real(script, *argv, **kw)
        if script is mail_outgoing._SEND_OUTGOING:
            rig.clock[0] += 20.0
        return out

    _patch_run(monkeypatch, osa)
    out = _reply_all()
    assert out["sent"] is True and out["drafts_copy"] == "late"
    assert "again in a minute" in out["drafts_copy_note"]


def test_send_then_sweep_counts_45_s_from_when_the_open_returned(monkeypatch):
    rig = _SweepRig(monkeypatch)
    real = rig._osa

    def osa(script, *argv, **kw):
        out = real(script, *argv, **kw)
        if script is mail_outgoing._REPLY_OPEN:
            rig.clock[0] += 30.0
        return out

    _patch_run(monkeypatch, osa)
    _reply_all()
    assert rig.waits == [175.0]
