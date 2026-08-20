"""Unit tests for the messages adapter — pure helpers + synthetic chat.db fixtures.

No real macOS store: the sqlite reads run against a fixture .db built with just the
tables/columns the queries touch. The osascript chat list stays pure-parse."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime

import pytest

from macos_apps_mcp.adapters import messages
from macos_apps_mcp.adapters.messages import (
    _APPLE_EPOCH,
    _apple_date_to_dt,
    _calling_code_for_region,
    _clamp,
    _decode_attributed_body,
    _escape_like,
    _handle_variants,
    _message_pointer,
    _parse,
    _resolve_calling_code,
)
from macos_apps_mcp.contracts import Pointer
from macos_apps_mcp.errors import FullDiskAccessDenied, SchemaDrift
from macos_apps_mcp.text import RS, US

# --- chat list (osascript) — unchanged -----------------------------------------------


def test_parse_guid_and_name():
    ptrs = _parse(f"guid-1{US}Family{RS}guid-2{US}{RS}")
    assert len(ptrs) == 2
    assert isinstance(ptrs[0], Pointer)
    assert ptrs[0].id == "guid-1" and ptrs[0].summary == "Family"
    assert ptrs[0].deeplink == ""
    assert ptrs[1].summary == "(chat)"  # unnamed 1:1 chat


def test_parse_skips_blank():
    assert _parse("\n  \n") == []


def test_parse_sanitizes_control_chars_in_summary():
    ptr = _parse(f"guid-1{US}Team\x07Alert{RS}")[0]
    assert ptr.summary == "TeamAlert" and "\x07" not in ptr.summary


def test_parse_survives_newline_in_chat_name():
    # US/RS framing (C4-B): a newline in a chat name no longer splits the record.
    ptr = _parse(f"guid-1{US}Line one\nline two{RS}")[0]
    assert ptr.summary == "Line one line two"


# --- Apple-epoch conversion ----------------------------------------------------------


def _ns(dt: datetime) -> int:
    return int((dt.timestamp() - _APPLE_EPOCH) * 1e9)


def test_apple_date_nanoseconds():
    dt = datetime(2024, 6, 15, 9, 30)
    got = _apple_date_to_dt(_ns(dt))
    assert abs((got - dt).total_seconds()) < 1


def test_apple_date_seconds_legacy():
    # pre-Yosemite chat.db stored SECONDS since the Apple epoch, not nanoseconds.
    dt = datetime(2013, 3, 1, 8, 0)
    secs = int(dt.timestamp() - _APPLE_EPOCH)
    got = _apple_date_to_dt(secs)
    assert abs((got - dt).total_seconds()) < 1


def test_apple_date_none_and_zero():
    assert _apple_date_to_dt(None) is None
    assert _apple_date_to_dt(0) is None


def test_apple_date_garbage_returns_none_not_crash():
    # a corrupt/out-of-range date must degrade to None, not raise and abort the read.
    assert _apple_date_to_dt(10**30) is None
    assert _apple_date_to_dt(-(10**30)) is None


def test_clamp_bounds():
    assert _clamp(-5) == 1  # never below 1
    assert _clamp(0) == 1
    assert _clamp(10) == 10
    assert _clamp(10_000) == 200  # capped at the hard ceiling


# --- handle fan-out / country code ---------------------------------------------------


def test_handle_variants_international_normalizes():
    v = _handle_variants("+32 470 12 34 56")
    assert "+32470123456" in v and "32470123456" in v


def test_handle_variants_national_with_calling_code():
    # a national number promotes to E.164: drop the trunk 0, prefix the calling code.
    v = _handle_variants("0470123456", "32")
    assert "+32470123456" in v and "32470123456" in v
    assert "0470123456" in v  # as-typed still tried


def test_handle_variants_national_without_code_stays_local():
    # no calling code → no international guess (never a hardcoded default).
    assert _handle_variants("0470123456") == ["0470123456"]


def test_handle_variants_double_zero_prefix():
    assert "+32470123456" in _handle_variants("0032470123456")


def test_handle_variants_italy_keeps_trunk_zero():
    # Italy RETAINS the trunk 0 in E.164 (+39 06…) — the keep-0 variant must be built
    # so a Rome landline stored as +39061234567 is still matched.
    v = _handle_variants("061234567", "39")
    assert "+39061234567" in v  # keep-0 form (correct for IT)
    assert "+3961234567" in v  # drop-0 form (a harmless superset variant)


def test_handle_variants_reverse_e164_to_national():
    # an E.164 input must also try the national forms a store might keep instead.
    v = _handle_variants("+32470123456", "32")
    assert "0470123456" in v and "470123456" in v


def test_resolve_calling_code_common_region_aliases():
    # "UK"/"USA" are everyday non-ISO spellings — resolve them, don't silently drop.
    assert _resolve_calling_code("UK") == "44"
    assert _resolve_calling_code("USA") == "1"


def test_handle_variants_email_lowercased():
    assert _handle_variants("User@ICloud.com") == ["user@icloud.com"]


def test_handle_variants_empty():
    assert _handle_variants("   ") == []


def test_resolve_calling_code_accepts_code_or_region():
    assert _resolve_calling_code("+32") == "32"
    assert _resolve_calling_code("32") == "32"
    assert _resolve_calling_code("BE") == "32"
    assert _resolve_calling_code("be") == "32"
    assert _resolve_calling_code("ZZ") is None  # unknown region
    assert _resolve_calling_code("") is None
    assert _resolve_calling_code(None) is None


def test_calling_code_never_defaults_to_us():
    # the EU-first invariant: US maps only when the region really is US, not by default.
    assert _calling_code_for_region(None) is None
    assert _calling_code_for_region("BE") == "32"
    assert _calling_code_for_region("US") == "1"


def test_escape_like_makes_wildcards_literal():
    assert _escape_like("50%_off\\") == "50\\%\\_off\\\\"


# --- Pointer projection --------------------------------------------------------------


def test_message_pointer_from_them():
    dt = datetime(2024, 6, 15, 9, 30)
    p = _message_pointer(("g1", "hi there", _ns(dt), 0, "+32470123456"))
    assert p.id == "g1"
    assert "hi there" in p.summary and "+32470123456" in p.summary
    assert "2024-06-15 09:30" in p.summary
    assert p.deeplink == "imessage://+32470123456"


def test_message_pointer_from_me():
    p = _message_pointer(("g2", "yo", _ns(datetime(2024, 1, 1)), 1, "+32470123456"))
    assert "me:" in p.summary


def test_message_pointer_null_text_gets_placeholder():
    p = _message_pointer(("g3", None, _ns(datetime(2024, 1, 1)), 0, "+3210"))
    assert "no preview" in p.summary


def test_message_pointer_no_handle_empty_deeplink():
    p = _message_pointer(("g4", "x", _ns(datetime(2024, 1, 1)), 0, None))
    assert p.deeplink == "" and "?:" in p.summary


# --- synthetic chat.db fixtures ------------------------------------------------------


# message row shape: (guid, text, attributedBody, date, is_from_me, item_type,
# is_audio_message, associated_message_type, handle_id)
def _make_chatdb(path, *, messages_rows, handles):
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT, service TEXT)"
    )
    conn.execute(
        "CREATE TABLE message (ROWID INTEGER PRIMARY KEY, guid TEXT, text TEXT, "
        "attributedBody BLOB, date INTEGER, is_from_me INTEGER, item_type INTEGER, "
        "is_audio_message INTEGER, associated_message_type INTEGER, handle_id INTEGER)"
    )
    conn.executemany("INSERT INTO handle (ROWID, id) VALUES (?, ?)", handles)
    conn.executemany(
        "INSERT INTO message (guid, text, attributedBody, date, is_from_me, item_type, "
        "is_audio_message, associated_message_type, handle_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        messages_rows,
    )
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def chatdb(tmp_path, monkeypatch):
    # handle 1 = "+32470123456"; 2 text messages, 1 audio, 1 non-message item_type, 1
    # reaction (newest — must be excluded); 1 NULL-text message on handle 2 (email).
    d1, d2 = _ns(datetime(2024, 1, 1, 8, 0)), _ns(datetime(2024, 6, 1, 8, 0))
    d3 = _ns(datetime(2024, 6, 2, 8, 0))  # newest
    path = _make_chatdb(
        tmp_path / "chat.db",
        handles=[(1, "+32470123456"), (2, "friend@icloud.com")],
        messages_rows=[
            ("g-old", "hello world", None, d1, 0, 0, 0, 0, 1),
            ("g-new", "hello again", None, d2, 1, 0, 0, 0, 1),
            ("g-audio", "transcript", None, d2, 0, 0, 1, 0, 1),  # audio → excluded
            ("g-item", "joined", None, d2, 0, 1, 0, 0, 1),  # item_type=1 → excluded
            ("g-react", None, None, d3, 0, 0, 0, 2000, 1),  # reaction → excluded
            ("g-null", None, None, d2, 0, 0, 0, 0, 2),  # email handle, no text
        ],
    )
    monkeypatch.setattr(messages, "CHAT_DB", path)
    return path


def test_search_messages_matches_text_newest_first(chatdb):
    ptrs = messages.MessagesAdapter().search_messages("hello")
    # newest first; audio / item_type / reaction / null-text all excluded.
    assert [p.id for p in ptrs] == ["g-new", "g-old"]


def test_search_matches_attributedbody_when_text_null(tmp_path, monkeypatch):
    # modern iMessages keep the body in attributedBody with text NULL — search must
    # find them (the text-only version silently under-reported).
    d = _ns(datetime(2024, 5, 1))
    path = _make_chatdb(
        tmp_path / "chat.db",
        handles=[(1, "+3210")],
        messages_rows=[
            ("g-ab", None, b"streamtyped...hello from body...", d, 0, 0, 0, 0, 1)
        ],
    )
    monkeypatch.setattr(messages, "CHAT_DB", path)
    assert [p.id for p in messages.MessagesAdapter().search_messages("hello")] == [
        "g-ab"
    ]


def test_messages_with_excludes_reactions(chatdb):
    # the newest row on handle 1 is a tapback (associated_message_type=2000); must NOT
    # appear, and must not consume the LIMIT ahead of real messages.
    ids = {p.id for p in messages.MessagesAdapter().messages_with("+32470123456")}
    assert "g-react" not in ids and ids == {"g-old", "g-new"}


def test_search_messages_like_wildcards_are_literal(chatdb):
    # "%" is escaped, so it matches no row (none contains a literal percent).
    assert messages.MessagesAdapter().search_messages("%") == []


def test_search_messages_empty_query_raises(chatdb):
    with pytest.raises(ValueError, match="search term"):
        messages.MessagesAdapter().search_messages("   ")


def test_messages_with_fans_out_national_to_stored_e164(chatdb):
    # stored handle is +32470123456; a national input + BE code must still match it.
    ptrs = messages.MessagesAdapter().messages_with("0470123456", country="32")
    assert {p.id for p in ptrs} == {"g-old", "g-new"}


def test_messages_with_region_override(chatdb):
    ptrs = messages.MessagesAdapter().messages_with("0470123456", country="BE")
    assert {p.id for p in ptrs} == {"g-old", "g-new"}


def test_messages_with_email(chatdb):
    # handle 2's only message has NULL text — but messages_with is not text-filtered, so
    # it still returns the message (with a placeholder snippet).
    assert [
        p.id for p in messages.MessagesAdapter().messages_with("friend@icloud.com")
    ] == ["g-null"]


def test_messages_with_empty_address_raises(chatdb):
    with pytest.raises(ValueError, match="phone number or email"):
        messages.MessagesAdapter().messages_with("   ")


def test_missing_store_raises_not_empty(chatdb, monkeypatch):
    # Messages content has NO AppleScript fallback → an unreadable store must raise,
    # never silently return [] (the #47 fake-success trap).
    monkeypatch.setattr(messages, "CHAT_DB", chatdb.parent / "absent.db")
    with pytest.raises(Exception):  # noqa: B017 - NativeError subtree, never empty
        messages.MessagesAdapter().search_messages("hello")


@pytest.mark.skipif(os.getuid() == 0, reason="root bypasses file permissions")
def test_permission_denied_is_fda(chatdb):
    os.chmod(chatdb, 0o000)
    try:
        with pytest.raises(FullDiskAccessDenied):
            messages.MessagesAdapter().search_messages("hello")
    finally:
        os.chmod(chatdb, 0o644)


def test_schema_drift_raises(tmp_path, monkeypatch):
    # a chat.db missing columns (a macOS schema move) → SchemaDrift (no fallback)
    bad = tmp_path / "chat.db"
    conn = sqlite3.connect(bad)
    conn.execute("CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT)")
    conn.execute("CREATE TABLE message (guid TEXT)")  # missing text/date/… columns
    conn.commit()
    conn.close()
    monkeypatch.setattr(messages, "CHAT_DB", bad)
    with pytest.raises(SchemaDrift):
        messages.MessagesAdapter().search_messages("hello")


# --- attributedBody typedstream decoder (commit 2) -----------------------------------


# the header + class chain up to and including the '+' value tag — the real byte layout.
_TS_HEAD = (
    b"\x04\x0bstreamtyped\x81\xe8\x03\x84\x01@\x84\x84\x84"
    b"\x19NSMutableAttributedString\x00\x84\x84\x08NSObject"
    b"\x00\x85\x92\x84\x84\x84\x0fNSMutableString\x01\x94\x84"
    b"\x84\x08NSString\x01\x95\x84\x01+"
)
_TS_TRAILER = b"\x86\x84\x02iI\x01\x00"  # attribute-run cruft the decoder must ignore


def _typedstream(
    text: bytes, *, long_prefix: bool = False, trailer: bytes = _TS_TRAILER
) -> bytes:
    """Craft a realistic ``streamtyped`` attributedBody: header + class chain, the ``+``
    value tag, a typedstream length, the text bytes, then a trailer. Built from the real
    byte layout the decoder parses — NOT the decoder's own output. ``trailer=b""`` puts
    the text at the very end (exact-fit boundary)."""
    if long_prefix:
        prefix = b"\x81" + len(text).to_bytes(2, "little")
    else:
        prefix = bytes([len(text)])
    return _TS_HEAD + prefix + text + trailer


def test_decode_ascii():
    assert _decode_attributed_body(_typedstream(b"Hello world")) == "Hello world"


def test_decode_long_string_uses_two_byte_length():
    text = b"x" * 200  # > 127 → 0x81 + LE uint16 length prefix
    assert _decode_attributed_body(_typedstream(text, long_prefix=True)) == "x" * 200


def test_decode_multibyte_utf8():
    text = (
        "café 🎉".encode()
    )  # accent (2 bytes) + emoji (4 bytes); length is byte count
    assert _decode_attributed_body(_typedstream(text)) == "café 🎉"


def test_decode_empty_text():
    assert _decode_attributed_body(_typedstream(b"")) == ""


def test_decode_none_and_empty_blob():
    assert _decode_attributed_body(None) is None
    assert _decode_attributed_body(b"") is None


def test_decode_not_streamtyped_declines():
    # an NSKeyedArchiver/bplist blob is a different format — decline, don't mis-parse.
    assert _decode_attributed_body(b"bplist00\xd1\x01\x02NSString+\x05Hello") is None


def test_decode_no_nsstring_declines():
    assert (
        _decode_attributed_body(b"\x04\x0bstreamtyped\x81\xe8\x03 no string here")
        is None
    )


def test_decode_truncated_declines_not_partial():
    # length claims 50 bytes but only 3 follow → decline rather than return a fragment.
    truncated = _TS_HEAD + b"\x32" + b"abc"  # says 0x32=50 bytes, only 3 present
    assert _decode_attributed_body(truncated) is None


def test_decode_invalid_length_tag_declines_not_fabricate():
    # a single length byte is a signed char: only 0x00-0x7f are valid. 0x80 / 0x83-0xFF
    # are negative/invalid — the decoder must DECLINE, not read that many bytes as a
    # fabricated body (the decoder's "never fabricate a wrong body" contract).
    for bad_tag in (b"\x80", b"\x83", b"\xff"):
        blob = (
            _TS_HEAD + bad_tag + (b"\x00\x01\x02" * 100)
        )  # plenty of trailer to over-read
        assert _decode_attributed_body(blob) is None


def test_decode_exact_fit_no_trailer():
    # the string is the LAST bytes of the blob (start+length == len): the boundary guard
    # is `>` not `>=`, so a legitimate trailer-less body must still decode.
    assert _decode_attributed_body(_typedstream(b"Hi", trailer=b"")) == "Hi"


def test_decode_str_input_declines_not_crash():
    # a str (not bytes) from an unexpected column type must decline, never raise.
    assert _decode_attributed_body("streamtyped NSString+\x05Hello") is None  # type: ignore[arg-type]


# --- message_body (get-by-id) --------------------------------------------------------


@pytest.fixture
def bodydb(tmp_path, monkeypatch):
    d = _ns(datetime(2024, 5, 1))
    path = _make_chatdb(
        tmp_path / "chat.db",
        handles=[(1, "+3210")],
        messages_rows=[
            ("g-text", "plain text here", None, d, 0, 0, 0, 0, 1),  # text present
            (
                "g-body",
                None,
                _typedstream(b"decoded body"),
                d,
                0,
                0,
                0,
                0,
                1,
            ),  # NULL text
            ("g-none", None, None, d, 0, 0, 0, 0, 1),  # no text, no body
        ],
    )
    monkeypatch.setattr(messages, "CHAT_DB", path)
    return path


def test_message_body_prefers_text_column(bodydb):
    assert messages.MessagesAdapter().message_body("g-text") == "plain text here"


def test_message_body_decodes_attributedbody_when_text_null(bodydb):
    assert messages.MessagesAdapter().message_body("g-body") == "decoded body"


def test_message_body_empty_when_no_content(bodydb):
    assert messages.MessagesAdapter().message_body("g-none") == ""


def test_message_body_unknown_id_raises(bodydb):
    with pytest.raises(ValueError, match="no message with id"):
        messages.MessagesAdapter().message_body("nope")


def test_message_body_empty_id_raises(bodydb):
    with pytest.raises(ValueError, match="message id"):
        messages.MessagesAdapter().message_body("  ")


def test_parse_absent_chat_name_falls_back_to_the_placeholder():
    # An unnamed 1:1 chat has no `name`; AppleScript writes the literal "missing value"
    # onto the wire, which is truthy and defeated the `or "(chat)"` fallback.
    ptr = _parse(f"guid-1{US}missing value{RS}")[0]
    assert ptr.summary == "(chat)"
