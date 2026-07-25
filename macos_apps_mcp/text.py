"""Text hygiene + matching normalization — pure, native-free (#52, #49, #64).

Every string that reaches the model or a verify comparison passes through here, in
ONE place with one uniform rule set:
- **output hygiene** (#52): control-strip + bound summaries and hydrated bodies, so a
  pathological item can neither corrupt the client nor blow the context;
- **verify normalization** (#49): ``norm_text`` for NFC/LF-insensitive write-verify
  diffs;
- **read matching** (#64): ``fold_text`` for case/diacritic/smart-punctuation-
  insensitive name/title search;
- **wire framing** (#68): the canonical US/RS separators + strip/split contract for
  AppleScript payloads.

No native imports — everything unit-tests with plain strings (tests/test_text.py).
"""

from __future__ import annotations

import re
import unicodedata

from .errors import OutputOverflow

# --- US/RS wire-framing contract (#68) -----------------------------------------------
# AppleScript templates emit fields joined with US (\x1f) and records joined with RS
# (\x1e); every free-text field (subject, sender, note body, contact name) passes
# through the stripFraming handler FIRST so a payload containing those bytes can't
# desync parsing. This block is the protocol's ONE home — the separators, the one
# AppleScript handler (prepended to every framed template), and the one Python splitter
# (split_framed). No adapter may hard-code \x1f/\x1e or re-declare the handler: that
# per-adapter scatter is exactly what caused the a6ce7fd subject-framing bug (the
# subject path missed the strip the other fields had).
US = "\x1f"  # unit separator — joins fields
RS = "\x1e"  # record separator — joins records

STRIP_FRAMING = """on stripFraming(t)
  set t to t as text
  set AppleScript's text item delimiters to (character id 30)
  set t to text items of t
  set AppleScript's text item delimiters to ""
  set t to t as text
  set AppleScript's text item delimiters to (character id 31)
  set t to text items of t
  set AppleScript's text item delimiters to ""
  set t to t as text
  return t
end stripFraming"""


# AppleScript's `read … as «class utf8»` raises -39 ("End of file") on a ZERO-BYTE file,
# so a body-carrying script must read through this handler, never `read` directly: an
# EMPTY body is empty text, not an error. (create_draft with an empty body has been
# broken since 0.8.0 for exactly this reason; device-verified 2026-07-26.)
READ_BODY = """on readBody(p)
  try
    return (read (POSIX file p) as «class utf8»)
  on error number -39
    return ""
  end try
end readBody"""


def split_framed(raw: str) -> list[list[str]]:
    """Split a US/RS-framed payload into records of fields, skipping blank records —
    the single Python-side counterpart of the framing contract above."""
    return [record.split(US) for record in raw.split(RS) if record.strip()]


def norm_text(v) -> str | None:
    """NFC + LF-normalize a free-text field for verify comparison (#49): Cocoa treats
    NFC/NFD as equal and stores may fold CRLF, so byte-exact != would false-fail a
    correct write. "" and None both mean "unset"."""
    if v is None:
        return None
    s = unicodedata.normalize("NFC", str(v)).replace("\r\n", "\n").replace("\r", "\n")
    return s or None


# Typographic glyphs Apple's stores keep but users type ASCII for (#64). Curly single/
# double quotes + primes → ASCII ' and ", ellipsis → "...". NOT hyphens/dashes: folding
# the dash family broke real hyphenated names elsewhere, and the acceptance requires
# hyphenated titles unaffected — so dashes pass through fold_text untouched.
_PUNCT_FOLD = {
    0x2018: "'",  # ‘ left single quote
    0x2019: "'",  # ’ right single quote (the U+2019 apostrophe — the #26 culprit)
    0x201A: "'",  # ‚ single low-9 quote
    0x201B: "'",  # ‛ single high-reversed-9 quote
    0x2032: "'",  # ′ prime
    0x201C: '"',  # “ left double quote
    0x201D: '"',  # ” right double quote
    0x201E: '"',  # „ double low-9 quote
    0x201F: '"',  # ‟ double high-reversed-9 quote
    0x2033: '"',  # ″ double prime
    0x2026: "...",  # … horizontal ellipsis
}


def fold_text(v: object) -> str:
    """Case/diacritic/smart-punctuation-insensitive key for READ-side name/title
    matching (#64). Apply to BOTH sides of a comparison so "café" matches "cafe" and
    "Andrei's list" (U+2019) matches "Andrei's list" (ASCII) — Apple stores typographic
    glyphs, models type ASCII, and the mismatch silently returned nothing (epheterson
    #26). Steps: map curly quotes/apostrophes/ellipsis → ASCII, NFKD-decompose and drop
    combining marks (strips diacritics), then casefold. Hyphens/dashes are LEFT ALONE
    (see _PUNCT_FOLD). Pure / native-free; composes with norm_text (#49).

    READS ONLY. Write-target resolution (resolve_container) stays byte-exact by design:
    folding a write target could collapse two real containers ("Café"/"Cafe") and
    silently mis-home the write — the exact opposite of the AmbiguousTarget guard's
    intent. Fold search results, never write targets.

    ponytail: NFKD is *compatibility* decomposition, so it also folds ligatures/width/
    superscripts (ﬁ→"fi", №→"no", ①→"1"). That only ever WIDENS a read match (a
    harmless superset), never drops a legitimate one, and can't reach a write — fine
    for search. Switch to NFD if a caller ever needs canonical-only folding.
    """
    s = str(v) if v is not None else ""
    s = s.translate(_PUNCT_FOLD)
    s = "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )
    return s.casefold()


# --- output hygiene (#52) ------------------------------------------------------------
# Raw native text reaches the model two ways: as a one-line Pointer.summary and as an
# opt-in hydrated body. Both are control-stripped and bounded here — in ONE place, one
# uniform rule (no per-tool truncation knobs) — so a pathological item can neither
# corrupt the client (control chars / U+2028-9 blanked Claude Desktop conversations
# retroactively, carterlasalle #2) nor blow the buffer/context (a 150k-char body failed
# *silently* at maxBuffer, FradSer #66/#69). ponytail: the three MAX constants are
# tuning knobs — change the numbers, not the mechanism.
SUMMARY_MAX = 200  # a one-line citable extract
BODY_MAX = 4000  # per-item hydrated body — soft cap: truncate + marker past this
BODY_HARD_MAX = 50_000  # a body past this is a dump, not a note → OutputOverflow

# Fold every kind of line break to one char first: CRLF/CR, VT, FF, NEL (U+0085), and
# the Unicode LINE/PARAGRAPH SEPARATORS (U+2028/9) that historically blank JS/JSON
# consumers. \r\n is one alternative so a Windows newline folds to a single char.
_LINE_BREAKS = re.compile(r"\r\n|[\r\n\x0b\x0c\x85\u2028\u2029]")
# Disallowed chars remaining after breaks are folded: C0 controls (minus TAB \x09 and
# the fold char \n \x0a, both kept), DEL \x7f, and C1 \x80-\x9f. \x0b-\x0d never survive
# folding, so the class starts at \x0e.
_CTRL = re.compile(r"[\x00-\x08\x0e-\x1f\x7f-\x9f]")


def _truncate(text: str, limit: int) -> str:
    """Cap ``text`` at ``limit`` chars, appending an explicit ``[truncated N chars]``
    marker (N = chars dropped) so the model never mistakes a clip for the whole."""
    if len(text) <= limit:
        return text
    return f"{text[:limit]} [truncated {len(text) - limit} chars]"


def sanitize_line(text: object) -> str:
    """Collapse ``text`` to one control-char-free line (NO truncation): every line break
    → space, C0/C1/DEL controls removed, whitespace runs collapsed. For anything that
    lands in a one-line ``Pointer.summary``. ``None`` → ``""``."""
    folded = _LINE_BREAKS.sub(" ", str(text) if text is not None else "")
    return re.sub(r"\s+", " ", _CTRL.sub("", folded)).strip()


def sanitize_block(text: object) -> str:
    """Strip control chars from multi-line ``text``, preserving line structure (NO
    truncation): every line break → ``\\n``, TAB kept, other C0/C1/DEL removed. For
    opt-in hydrated bodies (a body legitimately spans lines — do not flatten it)."""
    folded = _LINE_BREAKS.sub("\n", str(text) if text is not None else "")
    return _CTRL.sub("", folded)


def clean_summary(text: object) -> str:
    """One-line, control-free, ``SUMMARY_MAX``-bounded ``Pointer.summary`` text."""
    return _truncate(sanitize_line(text), SUMMARY_MAX)


def clean_body(
    text: object, limit: int = BODY_MAX, hard: int | None = BODY_HARD_MAX
) -> str:
    """Control-free, line-preserving body truncated at ``limit`` with a marker.

    Raises ``OutputOverflow`` when the sanitized body exceeds ``hard``: a single item
    that large is a pasted dump, not a note, and truncating it to a few KB would just
    hand back misleading noise — the model should open it in-app instead. Pass
    ``hard=None`` to always truncate (where one huge item must not fail a batch)."""
    s = sanitize_block(text)
    if hard is not None and len(s) > hard:
        raise OutputOverflow(
            f"this item is {len(s)} chars — too large to hydrate (cap {hard}). Open it "
            "in the app instead of fetching its body; do not retry the hydrate."
        )
    return _truncate(s, limit)
