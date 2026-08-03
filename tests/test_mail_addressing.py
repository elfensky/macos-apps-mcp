"""Unit tests for the mail addressing module (#155) and the bounded-read envelope
(#156) — the two mechanisms 0.9.2's writes inherit instead of re-deriving."""

from __future__ import annotations

import pytest

from macos_apps_mcp.adapters import mail
from macos_apps_mcp.adapters import mail_addressing as ma
from macos_apps_mcp.contracts import Pointer, read_result
from macos_apps_mcp.errors import NativeError

_ACCT = "AAAAAAAA-1111-2222-3333-444444444444"
_SPAM_URL = f"imap://{_ACCT}/%5BGmail%5D/Spam"


# --- the two id forms ----------------------------------------------------------------


@pytest.mark.parametrize("raw", ["<a@b>", "a@b", "  <a@b>  ", " a@b "])
def test_bare_id_accepts_either_form(raw):
    assert ma.bare_id(raw) == "a@b"


@pytest.mark.parametrize("raw", ["<a@b>", "a@b", "  a@b "])
def test_stored_id_is_always_bracketed(raw):
    assert ma.stored_id(raw) == "<a@b>"


def test_the_two_forms_round_trip():
    # The bug they exist to kill: sqlite stores <a@b>, AppleScript reports a@b, so an
    # id crossing planes matched zero rows and looked exactly like a genuine miss.
    assert ma.bare_id(ma.stored_id("a@b")) == "a@b"
    assert ma.stored_id(ma.bare_id("<a@b>")) == "<a@b>"


def test_bare_id_of_nothing_is_empty_not_a_crash():
    assert ma.bare_id("   ") == ""
    assert ma.bare_id("<>") == ""


# --- is_mailbox_url: the name-vs-handle distinction #156(2) turns on -----------------


def test_is_mailbox_url_separates_handles_from_typed_names():
    assert ma.is_mailbox_url(_SPAM_URL)
    assert ma.is_mailbox_url(f"local://{_ACCT}/Outbox")
    assert not ma.is_mailbox_url("inbox")
    assert not ma.is_mailbox_url("Junk E-mail")


# --- resolve() -----------------------------------------------------------------------


def test_resolve_with_a_folder_trusts_it_and_reads_no_index(monkeypatch):
    # The cheap path, and the one mail_body has always taken: a round-trip token is
    # authoritative, so resolving it must not cost a query (nor Full Disk Access).
    monkeypatch.setattr(
        ma.mail_index,
        "query_search",
        lambda **kw: pytest.fail("a folder-given resolve queried the index"),
    )
    target = ma.resolve("<a@b>", folder=_SPAM_URL)
    assert target.id == "a@b"
    assert target.folder == _SPAM_URL
    assert target.account == _ACCT
    assert target.mailbox_args == (_ACCT, "[Gmail]/Spam")


def test_resolve_with_a_canonical_name_leaves_the_account_unset(monkeypatch):
    monkeypatch.setattr(
        ma.mail_index, "query_search", lambda **kw: pytest.fail("queried the index")
    )
    target = ma.resolve("<a@b>", folder="inbox")
    # A unified accessor spans every account, so the account genuinely is unknown —
    # omitting it is honest, guessing is how a reply goes out from the wrong address.
    assert target.account is None
    assert target.mailbox_args == ("", "inbox")


def test_resolve_with_a_bad_folder_fails_at_the_boundary(monkeypatch):
    monkeypatch.setattr(
        ma.mail_index, "query_search", lambda **kw: pytest.fail("queried the index")
    )
    with pytest.raises(ValueError, match="unknown mailbox"):
        ma.resolve("<a@b>", folder="archive")


def test_resolve_id_only_goes_through_the_message_ids_filter(monkeypatch):
    seen = {}

    def fake(**kw):
        seen.update(kw)
        return [
            Pointer(
                id="<a@b>",
                summary="s",
                deeplink="message://x",
                folder=_SPAM_URL,
                account=_ACCT,
            )
        ]

    monkeypatch.setattr(ma.mail_index, "query_search", fake)
    target = ma.resolve("a@b")
    # the id crosses into the index in the STORED (bracketed) form, or it matches
    # nothing at all
    assert seen["message_ids"] == ["<a@b>"]
    assert seen["limit"] == 1
    assert (target.id, target.folder, target.account) == ("a@b", _SPAM_URL, _ACCT)


def test_resolve_id_only_narrows_by_account_when_asked(monkeypatch):
    seen = {}

    def fake(**kw):
        seen.update(kw)
        return [Pointer(id="<a@b>", summary="s", deeplink="d", folder=_SPAM_URL)]

    monkeypatch.setattr(ma.mail_index, "query_search", fake)
    ma.resolve("a@b", account=_ACCT)
    assert seen["account"] == _ACCT  # a UUID resolves without contacting Mail


def test_resolve_unknown_id_raises_rather_than_answering_nothing(monkeypatch):
    # A stored citation that no longer resolves is exactly what a caller must be told
    # about — an empty answer here reads as "the message is fine, it just has no body".
    monkeypatch.setattr(ma.mail_index, "query_search", lambda **kw: [])
    with pytest.raises(NativeError, match="no message with id 'gone@x'"):
        ma.resolve("<gone@x>")


def test_resolve_rejects_an_empty_id(monkeypatch):
    monkeypatch.setattr(
        ma.mail_index, "query_search", lambda **kw: pytest.fail("queried the index")
    )
    with pytest.raises(ValueError, match="message id"):
        ma.resolve("  ")


def test_resolve_takes_the_ranked_copy_the_rest_of_the_project_cites(monkeypatch):
    # "Exactly one target" is not a tie-break invented here: query_search dedups by
    # Message-ID and hands back the ranked winner, so resolve() cannot be ambiguous by
    # construction. This pins that it consumes the FIRST (only) row rather than
    # re-ranking on its own.
    monkeypatch.setattr(
        ma.mail_index,
        "query_search",
        lambda **kw: [
            Pointer(id="<a@b>", summary="s", deeplink="d", folder="imap://X/INBOX"),
            Pointer(id="<a@b>", summary="s", deeplink="d", folder="imap://X/Trash"),
        ],
    )
    assert ma.resolve("a@b").folder == "imap://X/INBOX"


# --- the adapter consumes it ---------------------------------------------------------


def test_get_body_with_no_mailbox_resolves_the_id_first(monkeypatch):
    monkeypatch.setattr(
        ma.mail_index,
        "query_search",
        lambda **kw: [Pointer(id="<a@b>", summary="s", deeplink="d", folder=_SPAM_URL)],
    )
    seen = {}

    def fake(script, *argv):
        seen["argv"] = argv
        return "the body"

    monkeypatch.setattr(mail, "run_osascript", fake)
    assert mail.MailAdapter().get_body("<a@b>") == "the body"
    # the resolved mailbox reaches the script as the (account, decoded path) pair
    assert seen["argv"] == ("a@b", _ACCT, "[Gmail]/Spam")


def test_attachments_by_id_addresses_one_message_and_makes_no_cap_claim(monkeypatch):
    monkeypatch.setattr(
        ma.mail_index,
        "query_search",
        lambda **kw: [Pointer(id="<a@b>", summary="s", deeplink="d", folder=_SPAM_URL)],
    )
    seen = {}

    def fake(script, *argv):
        seen["argv"] = argv
        return "<a@b>\x1fContract\x1fdeal.pdf\x1f100\x1ftrue\x1e"

    monkeypatch.setattr(mail, "run_osascript", fake)
    out = mail.MailAdapter().list_attachments(message_id="<a@b>")
    # query is empty, the mailbox came from the resolver, and the id is the 5th arg
    assert seen["argv"] == ("", str(mail.MAX_MAILS), _ACCT, "[Gmail]/Spam", "a@b")
    assert out["results"][0]["folder"] == _SPAM_URL
    # an id names ONE message, so the 25 cap cannot have hidden anything
    assert "truncated" not in out


def test_attachments_needs_a_mailbox_or_an_id():
    with pytest.raises(ValueError, match="mailbox .* or a message_id"):
        mail.MailAdapter().list_attachments()


# --- the bounded-read envelope (#156) ------------------------------------------------


def test_read_result_serializes_pointers_and_stays_quiet_when_complete():
    out = read_result([Pointer(id="a", summary="s", deeplink="d")], cap=25)
    assert out == {"results": [{"id": "a", "summary": "s", "deeplink": "d"}]}
    # every optional field is emitted ONLY when set — absence is meaningful because
    # every bounded read goes through this one helper
    assert set(out) == {"results"}


def test_read_result_marks_a_result_that_came_back_at_the_cap():
    ptrs = [Pointer(id=str(i), summary="s", deeplink="d") for i in range(3)]
    assert read_result(ptrs, cap=3)["truncated"] is True
    assert "truncated" not in read_result(ptrs, cap=4)


def test_read_result_without_a_cap_never_claims_truncation():
    ptrs = [Pointer(id=str(i), summary="s", deeplink="d") for i in range(3)]
    assert "truncated" not in read_result(ptrs)


def test_read_result_passes_plain_dict_rows_through():
    # mail_attachments rows are dicts, not Pointers — one envelope serves both.
    assert read_result([{"id": "x", "attachments": []}])["results"] == [
        {"id": "x", "attachments": []}
    ]


def test_read_result_carries_plane_and_coverage_when_given():
    out = read_result([], plane="applescript-inbox", coverage="1 of 2")
    assert out == {"results": [], "plane": "applescript-inbox", "coverage": "1 of 2"}


def test_resolve_mailbox_matches_a_round_trip_url_exactly(monkeypatch):
    # Every mail read returns `folder` as a url and documents it as the token to pass
    # back verbatim — but a url is never a substring of a bare mailbox PATH, so
    # mail_search(mailbox=<that folder>) matched zero rows and read as "empty mailbox".
    a, b = "AAAA-1", "BBBB-2"
    urls = [f"imap://{a}/INBOX", f"imap://{b}/INBOX", f"imap://{a}/Archive"]
    monkeypatch.setattr(ma.mail_index, "query_mailbox_urls", lambda: urls)
    assert ma.resolve_mailbox(f"imap://{a}/INBOX") == [f"imap://{a}/INBOX"]


def test_resolve_mailbox_url_match_survives_a_percent_encoding_difference(monkeypatch):
    # create_mailbox synthesises `.../Social & SEO`; Mail re-spells it
    # `Social%20&%20SEO` once it syncs. Not byte-equal, one mailbox — both resolve.
    stored = "imap://AAAA-1/Social%20&%20SEO"
    monkeypatch.setattr(ma.mail_index, "query_mailbox_urls", lambda: [stored])
    assert ma.resolve_mailbox("imap://AAAA-1/Social & SEO") == [stored]
    assert ma.resolve_mailbox(stored) == [stored]


def test_resolve_mailbox_url_does_not_match_the_same_path_elsewhere(monkeypatch):
    # the account segment is half the address — a url must not resolve across accounts
    urls = ["imap://AAAA-1/INBOX", "imap://BBBB-2/INBOX"]
    monkeypatch.setattr(ma.mail_index, "query_mailbox_urls", lambda: urls)
    assert ma.resolve_mailbox("imap://CCCC-3/INBOX") == []


def test_resolve_mailbox_still_substring_matches_a_plain_name(monkeypatch):
    urls = ["imap://AAAA-1/Junk%20E-mail", "imap://AAAA-1/INBOX"]
    monkeypatch.setattr(ma.mail_index, "query_mailbox_urls", lambda: urls)
    assert ma.resolve_mailbox("junk") == ["imap://AAAA-1/Junk%20E-mail"]
