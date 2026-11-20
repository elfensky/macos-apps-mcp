"""Unit tests for text.py — output hygiene, verify normalization, read folding.

Pure string work; no native imports (the module's whole point).
"""

from __future__ import annotations

import random
import sys
import unicodedata

import pytest

from macos_apps_mcp import text as text_module
from macos_apps_mcp.errors import NativeError, OutputOverflow
from macos_apps_mcp.text import (
    BODY_HARD_MAX,
    BODY_MAX,
    MAX_COMBINING_RUN,
    RS,
    SUMMARY_MAX,
    US,
    Field,
    addr_list,
    blank_if_missing,
    bool_or_none,
    bool_strict,
    clean_body,
    clean_summary,
    fold_text,
    int_or_none,
    int_or_zero,
    long_combining_run,
    norm_text,
    parse_framed,
    sanitize_block,
    sanitize_line,
)
from tests import mailhtml


def _rec(*fields):
    return US.join(fields)


# --- parse_framed: the declarative counterpart of split_framed (C4 Phase A) --------


def test_parse_framed_maps_named_fields_with_coercion():
    raw = _rec("id-1", "Subject", "5") + RS + _rec("id-2", "Other", "junk")
    out = parse_framed(raw, [Field("id"), Field("subject"), Field("n", int_or_zero)])
    assert out == [
        {"id": "id-1", "subject": "Subject", "n": 5},
        {"id": "id-2", "subject": "Other", "n": 0},
    ]


def test_parse_framed_skips_records_shorter_than_the_field_list():
    # default min_fields = len(fields): a partial trailing record is malformed wire,
    # not a half-usable answer — same rule every hand-rolled parser applied.
    raw = _rec("id-1", "s", "x") + RS + _rec("only-two", "fields")
    out = parse_framed(raw, [Field("a"), Field("b"), Field("c")])
    assert [r["a"] for r in out] == ["id-1"]


def test_parse_framed_min_fields_defaults_missing_tail_to_empty():
    # drafts-style: one required head field, optional tail — a missing tail field is
    # "" through the coercer, exactly what the hand-rolled `if len > n else ""` did.
    raw = _rec("id-1")
    out = parse_framed(
        raw, [Field("id"), Field("subject"), Field("rcpt", str.strip)], min_fields=1
    )
    assert out == [{"id": "id-1", "subject": "", "rcpt": ""}]


def test_parse_framed_required_drops_the_record():
    # "" and AppleScript's literal "missing value" both mean no stable field — the
    # record has no citation and is dropped whole, never half-emitted.
    raw = (
        _rec("", "no id")
        + RS
        + _rec("missing value", "astrology")
        + RS
        + _rec("id-1", "real")
    )
    out = parse_framed(raw, [Field("id", required=True), Field("s")])
    assert [r["id"] for r in out] == ["id-1"]


def test_parse_framed_repeat_consumes_trailing_tuples():
    raw = _rec("Subject", "a.pdf", "10", "true", "b.pdf", "20", "false")
    out = parse_framed(
        raw,
        [Field("summary")],
        repeat=[Field("name"), Field("size", int_or_none), Field("dl", bool_or_none)],
        repeat_key="atts",
    )
    assert out == [
        {
            "summary": "Subject",
            "atts": [
                {"name": "a.pdf", "size": 10, "dl": True},
                {"name": "b.pdf", "size": 20, "dl": False},
            ],
        }
    ]


def test_parse_framed_repeat_drops_partial_trailing_tuple_and_required_gaps():
    # a partial trailing triple is malformed wire; a required-empty NAME drops just
    # that tuple, not the record — both rules from the attachments parser.
    raw = _rec("S", "", "10", "true", "b.pdf", "20", "false", "c.pdf", "5")
    out = parse_framed(
        raw,
        [Field("summary")],
        repeat=[
            Field("name", required=True),
            Field("size", int_or_none),
            Field("dl", bool_or_none),
        ],
        repeat_key="atts",
    )
    assert [a["name"] for a in out[0]["atts"]] == ["b.pdf"]


def test_coercers():
    assert int_or_none("42") == 42
    assert int_or_none(" 42 ") == 42
    assert int_or_none("-1") is None  # sizes are unsigned; a negative is malformed
    assert int_or_none("x") is None
    assert int_or_zero("-7") == -7  # secs_ago may be negative (clock skew)
    assert int_or_zero("x") == 0
    assert bool_or_none("TRUE") is True
    assert bool_or_none("false") is False
    assert bool_or_none("maybe") is None
    assert bool_strict(" True ") is True
    assert bool_strict("anything-else") is False
    assert addr_list("A@x.com, b@Y.com ,,") == ["a@x.com", "b@y.com"]
    assert addr_list("") == []


def test_norm_text_folds_unset_variants_to_none():
    assert norm_text(None) is None
    assert norm_text("") is None


def test_norm_text_equates_nfd_and_nfc():
    # Cocoa treats NFC/NFD as equal — a byte-exact compare would false-fail (#49).
    assert norm_text("Cafe\u0301") == norm_text("Caf\u00e9")  # NFD vs NFC "Café"


def test_norm_text_normalizes_line_endings_to_lf():
    assert norm_text("a\r\nb\rc") == "a\nb\nc"


def test_norm_text_stringifies_non_text():
    # NSString-ish values from PyObjC go through str() rather than raising.
    assert norm_text(42) == "42"


# --- fold_text (#64): read-side diacritic/smart-punctuation folding ------------------


def test_fold_text_strips_diacritics():
    assert fold_text("Café résumé") == fold_text("cafe resume")


def test_fold_text_folds_smart_apostrophe():
    # the U+2019 culprit (#26): a curly apostrophe folds to the ASCII one.
    assert fold_text("Andrei’s list") == fold_text("Andrei's list")


def test_fold_text_folds_curly_quotes_and_ellipsis():
    assert fold_text("“hi”…") == fold_text('"hi"...')


def test_fold_text_is_case_insensitive():
    assert fold_text("HELLO") == fold_text("hello")


def test_fold_text_leaves_hyphens_alone():
    # the explicit non-goal: hyphens/dashes are NOT folded (real names broke otherwise).
    assert fold_text("well-known") != fold_text("wellknown")
    assert "-" in fold_text("well-known")
    # an em-dash is a distinct char and stays distinct — not collapsed to a hyphen.
    assert fold_text("a—b") != fold_text("a-b")


def test_fold_text_handles_none_and_nonstr():
    assert fold_text(None) == ""
    assert fold_text(42) == "42"


# --- output hygiene (#52) ------------------------------------------------------------
# The shared sanitize/truncate helper every Pointer.summary and hydrated body routes
# through. Two ecosystem bugs motivate it: control chars / U+2028-9 blanked Claude
# Desktop conversations (carterlasalle #2); unbounded fetches hit maxBuffer (FradSer
# #66/#69). U+2028/U+2029 are built via chr() so the source file can't mangle them.
_LS = chr(0x2028)  # LINE SEPARATOR
_PS = chr(0x2029)  # PARAGRAPH SEPARATOR


def test_sanitize_line_strips_c0_del_and_c1_controls():
    # NUL, BEL (C0), DEL, and a C1 control must all vanish; ordinary text survives.
    assert sanitize_line("a\x00b\x07c\x7fd\x9ee") == "abcde"


def test_sanitize_line_flattens_every_newline_kind_to_space():
    # \n, \r\n, \r, VT, FF, NEL, LINE SEP, PARA SEP all collapse to a single space.
    assert (
        sanitize_line(f"a\nb\r\nc\rd\x0be\x0cf\x85g{_LS}h{_PS}i") == "a b c d e f g h i"
    )


def test_sanitize_line_collapses_whitespace_runs_and_trims():
    assert sanitize_line("  x\t\t  y  ") == "x y"


def test_sanitize_block_preserves_newlines_and_tabs():
    # a body legitimately spans lines: \n and \t survive; other controls are stripped.
    assert sanitize_block("line1\nline2\tcol\x00x") == "line1\nline2\tcolx"


def test_sanitize_block_folds_exotic_breaks_to_newline():
    # CR / CRLF / VT / FF / NEL / U+2028 / U+2029 all normalize to \n (never doubled).
    assert (
        sanitize_block(f"a\r\nb\rc\x0bd\x0ce\x85f{_LS}g{_PS}h")
        == "a\nb\nc\nd\ne\nf\ng\nh"
    )


def test_none_is_treated_as_empty():
    assert sanitize_line(None) == "" and sanitize_block(None) == ""
    assert clean_summary(None) == "" and clean_body(None) == ""


def test_clean_summary_truncates_with_explicit_marker():
    text = "z" * (SUMMARY_MAX + 42)
    out = clean_summary(text)
    # the marker is exact and names the dropped count so the model knows what it missed
    assert out == "z" * SUMMARY_MAX + " [truncated 42 chars]"


def test_clean_summary_short_text_is_unchanged():
    assert clean_summary("Groceries — due 2026-07-11") == "Groceries — due 2026-07-11"


def test_clean_body_truncates_past_soft_cap_with_marker():
    out = clean_body("y" * (BODY_MAX + 7))
    assert out == "y" * BODY_MAX + " [truncated 7 chars]"


def test_clean_body_raises_output_overflow_past_hard_cap():
    with pytest.raises(OutputOverflow, match="too large to hydrate"):
        clean_body("q" * (BODY_HARD_MAX + 1))


def test_clean_body_hard_none_never_raises_only_truncates():
    # the batch-safe path (note_bodies): one huge item truncates instead of failing.
    out = clean_body("q" * (BODY_HARD_MAX + 100), hard=None)
    assert out.startswith("q" * BODY_MAX) and "[truncated" in out


def test_output_overflow_is_a_native_error_for_the_dispatch_seam():
    # server._guard catches NativeError → ToolError, so OutputOverflow must subclass it.
    assert issubclass(OutputOverflow, NativeError)
    assert OutputOverflow.kind == "output_overflow"


def test_clean_helpers_are_idempotent_on_clean_text():
    clean = "Jane Doe — Acme"
    assert sanitize_line(clean) == clean == clean_summary(clean)
    body = "first line\nsecond line"
    assert sanitize_block(body) == body == clean_body(body)


# --- missing value (AppleScript's absent property) ------------------------------------


def test_blank_if_missing_blanks_the_applescript_absent_marker():
    # AppleScript has no null: an absent property concatenated into text becomes the
    # literal "missing value", indistinguishable on the wire from a real value.
    assert blank_if_missing("missing value") == ""
    assert blank_if_missing("  missing value  ") == ""
    assert blank_if_missing("") == ""
    assert blank_if_missing("Real Name") == "Real Name"
    # a value merely CONTAINING the marker is a real value — only an exact match blanks
    assert blank_if_missing("re: missing value") == "re: missing value"


# --- the combining-run scan before normalization (FIX-36, #626) -----------------------
# Every mark is written as an escape and checked by code point: an editor that turns an
# escape into a glyph, or normalizes one, must fail a test here.

_GRAVE = "\u0300"  # a combining mark of class 230
_COMMA = "\u0315"  # a combining mark of class 232: NFC sorts it after class 230
_SPLIT_CHARS = {"\u0f73": 0x0F73, "\u0f75": 0x0F75, "\u0f81": 0x0F81}


def _longest_run(text: str) -> int:
    """The longest run of non-starters in ``text``, written out here on its own."""
    best = run = 0
    for char in text:
        run = run + 1 if unicodedata.combining(char) else 0
        best = max(best, run)
    return best


def test_combining_run_limit_is_thirty():
    assert MAX_COMBINING_RUN == 30


@pytest.mark.parametrize(
    "text, hit",
    [
        ("Z" + _COMMA * 15 + _GRAVE * 15 + "algo", False),  # 30 marks on one letter
        ("Z" + _COMMA * 16 + _GRAVE * 15 + "algo", True),  # 31 marks
        ("plain ASCII text, 31 times over " * 31, False),
        ("", False),
        (("e" + _GRAVE * 30) * 5, False),  # a letter separates the runs
        ((_GRAVE * 30 + " ") * 5, False),  # a space separates them
        # 31 marks of ONE class are in canonical order already: the scan counts, it
        # does not sort
        ("e" + _GRAVE * 31, True),
    ],
)
def test_combining_run_counts_non_starters_in_a_row(text, hit):
    assert (ord(_GRAVE), ord(_COMMA)) == (0x300, 0x315)
    assert (unicodedata.combining(_GRAVE), unicodedata.combining(_COMMA)) == (230, 232)
    assert long_combining_run(text) is hit


def test_combining_run_is_false_for_none():
    # the sweep passes None for the attribution and the tail of a reply without a quote
    assert long_combining_run(None) is False


@pytest.mark.parametrize("char, point", _SPLIT_CHARS.items())
def test_combining_run_counts_the_three_split_characters(char, point):
    # class 0, and the decomposition is two non-starters: NFC sorts two marks for each
    assert ord(char) == point and unicodedata.combining(char) == 0
    assert long_combining_run(char * 15) is False  # 30 non-starters
    assert long_combining_run(char * 16) is True
    # U+0344 is a non-starter whose decomposition is two non-starters: it counts as 2
    dialytika = "\u0344"
    assert ord(dialytika) == 0x344 and unicodedata.combining(dialytika) == 230
    assert long_combining_run("a" + dialytika * 15) is False
    assert long_combining_run("a" + dialytika * 16) is True
    assert long_combining_run("a" + dialytika + _GRAVE * 28) is False
    assert long_combining_run("a" + dialytika + _GRAVE * 29) is True


def test_combining_run_split_characters_match_unicodedata():
    # the scan knows four characters by name. This pass over every code point fails
    # when a later Unicode version adds a fifth.
    lead, longer = [], []
    for point in range(sys.maxunicode + 1):
        if 0xD800 <= point <= 0xDFFF:
            continue
        char = chr(point)
        parts = unicodedata.normalize("NFD", char)
        if parts == char:
            continue
        if unicodedata.combining(char):
            if len(parts) > 1:
                longer.append(point)
        elif unicodedata.combining(parts[0]):
            lead.append(point)
            assert all(unicodedata.combining(part) for part in parts)
            assert len(parts) == 2
    assert lead == [0x0F73, 0x0F75, 0x0F81]
    assert longer == [0x0344]
    # and the scan's table holds exactly these four, each with its decomposition
    expected = {
        chr(point): unicodedata.normalize("NFD", chr(point)) for point in lead + longer
    }
    table = text_module._SPLIT_MARKS
    assert table == expected and all(len(parts) == 2 for parts in table.values())


def test_combining_run_samples_hold_their_code_points():
    assert len(mailhtml.SAMPLES) == 13
    assert set(mailhtml._PINS) <= set(mailhtml.SAMPLES) and len(mailhtml._PINS) == 11
    for name, point in mailhtml._PINS.items():
        assert point in {ord(char) for char in mailhtml.SAMPLES[name]}, name
    assert 0xFFFC in {ord(char) for space in mailhtml._SPACES for char in space}


def test_combining_run_is_false_for_generated_text_in_13_scripts():
    rng = random.Random(626)
    refused = longest = 0
    for _ in range(5_000):
        text = mailhtml.script_text(rng)
        refused += long_combining_run(text)
        for form in ("", "NFC", "NFD", "NFKD"):
            shaped = unicodedata.normalize(form, text) if form else text
            longest = max(longest, _longest_run(shaped))
    assert refused == 0
    assert 1 <= longest <= 3  # 0 would mean that the samples lost their marks
