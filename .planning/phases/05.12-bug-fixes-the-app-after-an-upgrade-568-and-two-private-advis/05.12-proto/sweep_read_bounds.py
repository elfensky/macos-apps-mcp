"""FIX-36 (#626) prototype: bounds for the read path of the reply sweep, with the
measurements that set them and the differential proof that the output does not change.

Run from the repo root:  uv run python <this file> [--bodies N] [--texts N] [--chains N]

No Mail call, no osascript, no native call: pure work on generated text and bytes. No
stored mail is read. Every address here is made up and has no top-level domain.

Three steps of the read had no bound (unit probes of 2026-11-20). A fourth was found
here: the value parse of a MIME part's ``Content-Type`` field.

A. Text normalization. NFC is quadratic on a long run of non-starters (combining class
   not 0) in mixed order. ``long_combining_run`` is a linear scan that refuses a text
   before NFC runs. The limit is 30, the bound of Unicode's Stream-Safe Text Format
   (UAX #15, section 13). A scan with ``unicodedata.combining`` alone is NOT enough:
   three characters of class 0 (U+0F73, U+0F75, U+0F81) decompose into two non-starters.
B. Header read. Only the first ``HEADER_READ_BYTES`` of a stored message are read.
   The standard library splits the fields (linear). A field value is parsed only when it
   is needed and only when it is at most ``MAX_HEADER_FIELD_CHARS`` long (RFC 5322,
   section 2.1.1: a line is at most 998 characters). So the output is the old output by
   construction, or a refusal.
C. Message parse. A candidate row is parsed only when its stored size, its line count
   and its count of part delimiters are under their bounds, and with the same field
   bound plus a budget for all field values that the parse reads.
"""

from __future__ import annotations

import argparse
import email
import email.message
import email.parser
import email.policy
import random
import sys
import time
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))  # the repo root: `tests`

from macos_apps_mcp import runtime  # noqa: E402
from macos_apps_mcp.adapters import mail_outgoing  # noqa: E402
from macos_apps_mcp.adapters import mail_reply_cleanup as cleanup  # noqa: E402
from macos_apps_mcp.text import US, squash_text  # noqa: E402
from tests import mailhtml  # noqa: E402

# --- the proposed bounds --------------------------------------------------------------

MAX_COMBINING_RUN = 30
HEADER_READ_BYTES = 131_072
MAX_HEADER_FIELD_CHARS = 998
MAX_HEADER_FETCH_CHARS = 200_000
MAX_MESSAGE_BYTES = 50_000_000
MAX_MESSAGE_LINES = 1_000_000
MAX_MESSAGE_PARTS = 1_000


def timed(fn, *args):
    started = time.perf_counter()
    try:
        out = fn(*args)
    except RecursionError:
        out = "RecursionError"
    except (CombiningRun, HeaderTooLarge, MessageTooLarge) as exc:
        out = type(exc).__name__
    return time.perf_counter() - started, out


# === A. normalization =================================================================

# Class 0 characters whose canonical decomposition STARTS with a non-starter. A scan
# with ``unicodedata.combining`` reads a run of them as 0 marks; NFC sorts 2 marks each.
_SPLIT = {"\u0f73": "\u0f71\u0f72", "\u0f75": "\u0f71\u0f74", "\u0f81": "\u0f71\u0f80"}


class CombiningRun(Exception):
    """A text holds a run of more than ``MAX_COMBINING_RUN`` non-starters."""


def long_combining_run(text: str, limit: int = MAX_COMBINING_RUN) -> bool:
    """True when ``text`` holds more than ``limit`` non-starters in a row. Linear."""
    if text.isascii():
        return False
    for char, parts in _SPLIT.items():
        text = text.replace(char, parts)
    run = 0
    for char in text:
        if unicodedata.combining(char):
            run += 1
            if run > limit:
                return True
        else:
            run = 0
    return False


def naive_run(text: str, limit: int = MAX_COMBINING_RUN) -> bool:
    """The scan WITHOUT the three split characters: the mutant."""
    run = 0
    for char in text:
        run = run + 1 if unicodedata.combining(char) else 0
        if run > limit:
            return True
    return False


def longest_run(text: str) -> int:
    for char, parts in _SPLIT.items():
        text = text.replace(char, parts)
    best = run = 0
    for char in text:
        run = run + 1 if unicodedata.combining(char) else 0
        best = max(best, run)
    return best


def guarded_squash(text: object) -> str:
    plain = str(text or "")
    if long_combining_run(plain):
        raise CombiningRun
    return squash_text(plain)


def new_split_quote(msg):
    """``_split_quote`` with the guard before each ``squash_text``. The guard sees the
    text that NFC would see (after the object mark is removed from the head)."""
    old = cleanup.squash_text
    cleanup.squash_text = guarded_squash
    try:
        return cleanup._split_quote(msg)
    finally:
        cleanup.squash_text = old


# Natural-language samples, written as escapes (an editor once normalized a glyph).
SAMPLES = {
    "latin": "Cr\xe8me br\xfbl\xe9e \xe0 la fa\xe7on de Zo\xeb; \xc5ngstr\xf6m, "
    "se\xf1or, Dvo\u0159\xe1k, \u0141\xf3d\u017a, sm\xf6rg\xe5sbord, na\xefve "
    "co\xf6perate, \u0130stanbul, Gy\u0151r, \u0160koda",
    "vietnamese": "Ti\u1ebfng Vi\u1ec7t l\xe0 ng\xf4n ng\u1eef c\u1ee7a ng\u01b0\u1eddi "
    "Vi\u1ec7t; ph\u1edf b\xf2, b\xe1nh m\xec, Nguy\u1ec5n Th\u1ecb H\u1ed3ng, "
    "\u0111\u01b0\u1eddng L\xea L\u1ee3i, nh\u1eefng gi\u1ea5c m\u01a1, \u1edf Hu\u1ebf",
    "hebrew_points": "\u05d1\u05b0\u05bc\u05e8\u05b5\u05d0\u05e9\u05b4\u05c1\u05d9\u05ea "
    "\u05d1\u05b8\u05bc\u05e8\u05b8\u05d0 \u05d0\u05b1\u05dc\u05b9\u05d4\u05b4\u05d9\u05dd "
    "\u05d0\u05b5\u05ea \u05d4\u05b7\u05e9\u05b8\u05bc\u05c1\u05de\u05b7\u05d9\u05b4\u05dd "
    "\u05d5\u05b0\u05d0\u05b5\u05ea \u05d4\u05b8\u05d0\u05b8\u05e8\u05b6\u05e5",
    "hebrew_cantillation": "\u05d1\u05b0\u05bc\u05e8\u05b5\u05d0\u05e9\u05b4\u05c1\u0596"
    "\u05d9\u05ea \u05d1\u05b8\u05bc\u05e8\u05b8\u05a3\u05d0 \u05d0\u05b1\u05dc\u05b9"
    "\u05d4\u05b4\u0591\u05d9\u05dd \u05d0\u05b5\u05a5\u05ea \u05d4\u05b7\u05e9\u05b8"
    "\u05bc\u05c1\u05de\u05b7\u0596\u05d9\u05b4\u05dd \u05d5\u05b0\u05d0\u05b5\u05a5\u05ea "
    "\u05d4\u05b8\u05d0\u05b8\u05bd\u05e8\u05b6\u05e5\u05c3",
    "arabic_marks": "\u0628\u0650\u0633\u0652\u0645\u0650 \u0627\u0644\u0644\u064e\u0651"
    "\u0647\u0650 \u0627\u0644\u0631\u064e\u0651\u062d\u0652\u0645\u064e\u0670\u0646\u0650 "
    "\u0627\u0644\u0631\u064e\u0651\u062d\u0650\u064a\u0645\u0650 \u0627\u0644\u0652\u062d"
    "\u064e\u0645\u0652\u062f\u064f \u0644\u0650\u0644\u064e\u0651\u0647\u0650 \u0645\u064f"
    "\u062d\u064e\u0645\u064e\u0651\u062f\u064c",
    "thai": "\u0e20\u0e32\u0e29\u0e32\u0e44\u0e17\u0e22\u0e40\u0e1b\u0e47\u0e19\u0e20\u0e32"
    "\u0e29\u0e32\u0e17\u0e35\u0e48\u0e21\u0e35\u0e27\u0e23\u0e23\u0e13\u0e22\u0e38\u0e01"
    "\u0e15\u0e4c \u0e19\u0e49\u0e33 \u0e1c\u0e39\u0e49\u0e43\u0e2b\u0e0d\u0e48 \u0e17\u0e35"
    "\u0e48\u0e19\u0e35\u0e48 \u0e02\u0e2d\u0e1a\u0e04\u0e38\u0e13\u0e04\u0e23\u0e31\u0e1a "
    "\u0e40\u0e01\u0e49\u0e32\u0e2d\u0e35\u0e49 \u0e1b\u0e39\u0e48\u0e22\u0e48\u0e32",
    "devanagari": "\u0939\u093f\u0928\u094d\u0926\u0940 \u092d\u093e\u0937\u093e \u0915"
    "\u093c\u093f\u0932\u093e \u091c\u093c\u0930\u0942\u0930\u0940 \u0915\u0943\u0937\u094d"
    "\u0923 \u0936\u094d\u0930\u0940\u092e\u093e\u0928\u094d \u0935\u093f\u0926\u094d\u092f"
    "\u093e\u0930\u094d\u0925\u0940 \u092b\u093c\u094d\u0930\u093e\u0902\u0938 \u0939\u0942"
    "\u0901",
    "korean": "\ud55c\uad6d\uc5b4 \uac10\uc0ac\ud569\ub2c8\ub2e4 \uc548\ub155\ud558\uc138"
    "\uc694 \ub300\ud55c\ubbfc\uad6d \uc11c\uc6b8\ud2b9\ubcc4\uc2dc \uae40\uce58\ucc0c\uac1c",
    "emoji": "\U0001f44d\U0001f3fd \U0001f468\u200d\U0001f469\u200d\U0001f467\u200d"
    "\U0001f466 \U0001f3f3\ufe0f\u200d\U0001f308 \U0001f469\U0001f3ff\u200d\U0001f4bb "
    "\U0001f1e7\U0001f1ea 1\ufe0f\u20e3 \u2764\ufe0f\u200d\U0001f525 \u270c\U0001f3fc",
    "tibetan": "\u0f67\u0f71\u0f74\u0f83 \u0f56\u0f7c\u0f51\u0f0b\u0f66\u0f90\u0f51\u0f0b "
    "\u0f68\u0f7c\u0f7e\u0f0b\u0f58\u0f0b\u0f4e\u0f72\u0f0b\u0f54\u0f51\u0fa8\u0f7a\u0f0b"
    "\u0f67\u0f71\u0f74\u0f83 \u0f56\u0f40\u0fb2\u0f0b\u0f64\u0f72\u0f66",
    "ipa": "p\u02b0\u0279\u0325\u0259\u0303\u02c8n\u028c\u0303n.si.e\u026a\u032f.\u0283n"
    "\u0329 t\u032a\u0361s\u032a\u02bc \xe3\u0320\u0303 x\u0304\u0303 \u1e8d\u0302 e\u030b"
    "\u0342",
    "greek_polytonic": "\u1f18\u03bd \u1f00\u03c1\u03c7\u1fc7 \u1f26\u03bd \u1f41 \u03bb"
    "\u03cc\u03b3\u03bf\u03c2, \u03ba\u03b1\u1f76 \u1f41 \u03bb\u03cc\u03b3\u03bf\u03c2 "
    "\u1f26\u03bd \u03c0\u03c1\u1f78\u03c2 \u03c4\u1f78\u03bd \u03b8\u03b5\u03cc\u03bd "
    "\u1fa7 \u1f97 \u1fa0\u03b4\u03ae",
    "bengali_tamil": "\u09ac\u09be\u0982\u09b2\u09be \u09ad\u09be\u09b7\u09be \u0995\u09c3"
    "\u09b7\u09cd\u09a3 \u09a4\u09be\u0981\u09b0 \u0ba4\u0bae\u0bbf\u0bb4\u0bcd \u0bae\u0bca"
    "\u0bb4\u0bbf \u0b95\u0bca\u0bb3\u0bcd\u0b95\u0bc8",
}
# One code point of each sample that an editor could fold away.
_PINS = {
    "vietnamese": 0x1EBF,
    "hebrew_points": 0x05B0,
    "hebrew_cantillation": 0x0596,
    "arabic_marks": 0x0651,
    "thai": 0x0E48,
    "devanagari": 0x093C,
    "korean": 0xD55C,
    "emoji": 0x200D,
    "tibetan": 0x0F71,
    "ipa": 0x0361,
    "greek_polytonic": 0x1FA7,
}
_SPACES = [" ", "  ", "\n", "\r\n", "\t", "\xa0", "\u2028", "\u2029", " \ufffc "]


def script_text(rng) -> str:
    """Words of one to three scripts, in NFC, NFD or as written, with mixed spaces."""
    words: list[str] = []
    for name in rng.sample(sorted(SAMPLES), rng.randint(1, 3)):
        words += SAMPLES[name].split()
    out = []
    for _ in range(rng.randint(1, 40)):
        word = rng.choice(words)
        form = rng.choice(["NFC", "NFD", ""])
        out.append(unicodedata.normalize(form, word) if form else word)
        out.append(rng.choice(_SPACES))
    return "".join(out)


def unicode_facts() -> None:
    non_starters = lead = 0
    lead_chars, trail, expand = [], 0, []
    for point in range(sys.maxunicode + 1):
        if 0xD800 <= point <= 0xDFFF:
            continue
        char = chr(point)
        own = unicodedata.combining(char)
        non_starters += bool(own)
        parts = unicodedata.normalize("NFD", char)
        if parts == char:
            continue
        classes = [unicodedata.combining(c) for c in parts]
        if own and len(parts) > 1:
            expand.append(f"U+{point:04X}->{len(parts)}")
        if not own:
            if classes[0]:
                lead += 1
                lead_chars.append(f"U+{point:04X}")
            tail = 0
            for value in reversed(classes):
                if not value:
                    break
                tail += 1
            trail = max(trail, tail)
    assert sorted(lead_chars) == sorted(f"U+{ord(c):04X}" for c in _SPLIT), lead_chars
    print(f"unicodedata {unicodedata.unidata_version}: {non_starters} non-starters")
    print(f"  class 0 characters whose NFD starts with a non-starter: {lead_chars}")
    print(f"  non-starters with a longer NFD: {expand}")
    print(f"  most non-starters at the end of the NFD of a class 0 character: {trail}")
    print(
        f"  so a raw run of at most {MAX_COMBINING_RUN} is at most "
        f"{2 * MAX_COMBINING_RUN + trail} non-starters after decomposition"
    )


def worst_passing(limit: int, size: int) -> str:
    unit = "a" + "\u0315" * (limit // 2) + "\u0300" * (limit - limit // 2)
    return unit * (size // len(unit))


def crafted_run(size: int) -> str:
    """The worst order: all marks of class 232, then all of class 230."""
    return "a" + "\u0315" * (size // 2) + "\u0300" * (size // 2)


def normalization(args) -> int:
    print("\n=== A. normalization ===")
    unicode_facts()
    print("today (no guard), squash_text on one run:")
    for size in (40_000, 80_000):
        took, _ = timed(squash_text, crafted_run(size))
        print(f"  {size + 1:,} characters (classes 232 then 230): {took:.2f} s")
    took, _ = timed(squash_text, "\u0f73" * 40_000)
    print(f"  40,000 x U+0F73 (class 0, NFD = 2 non-starters): {took:.2f} s")
    msg = email.message.EmailMessage()
    msg.set_content(f"<div>Hi</div><blockquote>{crafted_run(80_000)}</blockquote>", "html")
    took, _ = timed(cleanup._split_quote, msg)
    print(f"  80,001 characters through _split_quote: {took:.2f} s")
    took, _ = timed(squash_text, crafted_run(120_000))
    print(f"  120,001 characters: {took:.1f} s (x4 at 240,001, the timed test's input)")
    took, _ = timed(squash_text, chr(0x0F73) * 80_000)
    print(f"  80,000 x U+0F73: {took:.1f} s (x4 at 160,000, the timed test's input)")
    print("the guard on crafted text:")
    for label, text in (
        ("240,001 characters (classes 232 then 230)", crafted_run(240_000)),
        ("160,000 x U+0F73", "\u0f73" * 160_000),
    ):
        took, hit = timed(long_combining_run, text)
        print(f"  {label}: refused={hit} in {took * 1000:.2f} ms")
    print(f"  the scan without the split characters on U+0F73: refused="
          f"{naive_run(chr(0x0F73) * 160_000)}  (the mutant passes it to NFC)")
    for marks in (8, 16, 30, 31):
        text = "Z" + "\u0315\u0300" * (marks // 2) + "\u0300" * (marks % 2) + "algo"
        print(f"  a decorative stack of {marks} marks on one letter: refused="
              f"{long_combining_run(text)}")
    print("the worst text that PASSES, 2,000,000 characters, by limit:")
    for limit in (30, 100, 300, 1000):
        text = worst_passing(limit, 2_000_000)
        assert not long_combining_run(text, limit)
        took, _ = timed(squash_text, text)
        scan, _ = timed(long_combining_run, text, limit)
        print(f"  limit {limit:4d}: squash_text {took:.3f} s; the scan {scan:.3f} s")
    row = [timed(squash_text, worst_passing(30, n))[0] for n in (500_000, 1_000_000, 2_000_000)]
    print("  limit 30 at 0.5 M, 1 M, 2 M characters:", ", ".join(f"{t:.3f} s" for t in row))

    rng = random.Random(626)
    bad = fired = 0
    longest: dict[str, int] = {}
    for name, sample in SAMPLES.items():
        if name in _PINS:
            assert chr(_PINS[name]) in sample, name
        for form in ("NFC", "NFD", "NFKD"):
            longest[name] = max(
                longest.get(name, 0), longest_run(unicodedata.normalize(form, sample))
            )
    print("longest run of non-starters, any form (NFC, NFD, NFKD), by sample:")
    print("  " + ", ".join(f"{k} {v}" for k, v in longest.items()))
    corpus_longest = 0
    for _ in range(args.texts):
        text = script_text(rng)
        corpus_longest = max(corpus_longest, longest_run(text))
        if long_combining_run(text):
            fired += 1
            continue
        same = (
            guarded_squash(text) == squash_text(text)
            and cleanup._bare(text) == cleanup._bare(guarded_squash(text))
            and runtime._alnum(text) == runtime._alnum(guarded_squash(text))
        )
        bad += not same
    html_longest = 0
    for n in range(args.bodies):
        markup = mailhtml.reply_html(rng)
        if n % 2:  # every second body carries script text above and inside the quote
            markup = markup.replace(
                "<blockquote", f"<div>{script_text(rng)}</div><blockquote", 1
            ).replace("</blockquote>", f"<p>{script_text(rng)}</p></blockquote>", 1)
        msg = mailhtml.message(markup, rng)
        old = cleanup._split_quote(msg)
        html_longest = max(html_longest, *(longest_run(part) for part in old))
        took, new = timed(new_split_quote, msg)
        fired += new == "CombiningRun"
        bad += new != old
    print(f"differential: {args.texts:,} generated texts in {len(SAMPLES)} scripts and "
          f"{args.bodies:,} Mail-layout bodies")
    print(f"  the guard refused: {fired}; outputs that differ: {bad}")
    print(f"  longest run of non-starters: texts {corpus_longest}, bodies {html_longest}")
    return bad + fired


def compose_reach() -> None:
    print("\n=== A2. the compose path (before the sweep), unit level, fakes only ===")
    original = "one two three four five " + crafted_run(40_000)
    answer = US.join(["12", "Jane Doe <jane@example>", "2026", "11", "20", "10", "0", original])
    old_osa, old_stamp = runtime.run_osascript, mail_outgoing._stamp
    runtime.run_osascript = lambda *a, **k: answer
    mail_outgoing._stamp = lambda parts: ("20 Nov 2026", "10:00")
    try:
        took, facts = timed(mail_outgoing._quote_facts, "o@x", ("inbox", "acct"))
    finally:
        runtime.run_osascript, mail_outgoing._stamp = old_osa, old_stamp
    tail = facts[0]
    print(f"  _quote_facts on an original with one 40,001-character run: {took:.2f} s "
          f"(nothing is created yet; x4 for each doubling)")
    took, _ = timed(runtime._alnum, tail)
    print(f"  runtime._alnum(tail), {len(tail):,} characters, one call: {took:.2f} s")
    body = "Hi\n" + original
    took, _ = timed(runtime._prepended, body, "Hi", squash_text(original))
    print(f"  runtime._prepended on a window text with that run, one call: {took:.2f} s "
          f"(_wait_settled calls it in a loop while the clipboard is borrowed)")


# === B. the header read ===============================================================


class HeaderTooLarge(Exception):
    """A field is over the field bound, the fetch budget ran out, or the field lies in
    the part of an oversized header block that was not read."""


class Bounded(email.policy.EmailPolicy):
    """``email.policy.default`` with two limits on the VALUE parse of a field."""

    budget = None  # [characters left, longest value parsed (for the report only)]

    def header_fetch_parse(self, name, value):
        # the raw field value as the parser stored it: fold bytes included
        if len(value) > MAX_HEADER_FIELD_CHARS:
            raise HeaderTooLarge
        self.budget[0] -= len(value)
        if self.budget[0] < 0:
            raise HeaderTooLarge
        self.budget[1] = max(self.budget[1], len(value))
        return super().header_fetch_parse(name, value)


def bounded() -> Bounded:
    return Bounded(budget=[MAX_HEADER_FETCH_CHARS, 0])


def old_read(payload: bytes):
    """``_read_draft`` as it is today, on the whole message."""
    head = email.parser.BytesParser(policy=email.policy.default).parsebytes(
        payload, headersonly=True
    )
    return (
        str(head.get("In-Reply-To", "") or ""),
        str(head.get("Message-ID", "") or ""),
        any(str(value).strip() for value in head.get_all("Received") or ()),
    )


def new_read(payload: bytes, block: int = HEADER_READ_BYTES):
    """``(in_reply_to, more)``; ``more()`` gives ``(message_id, received)`` and is
    called for a threaded row only. At most ``block`` bytes of the message are used.
    A header block that does not end there keeps every field but its last one."""
    data = payload[:block]
    complete = len(payload) <= block or b"\n\n" in data or b"\n\r\n" in data
    head = email.parser.BytesParser(policy=bounded()).parsebytes(data, headersonly=True)
    items = list(head.raw_items())
    usable = items if complete else items[:-1]

    def first(name: str) -> str:
        for key, raw in usable:
            if key.lower() == name:
                return str(head.policy.header_fetch_parse(key, raw) or "")
        if not complete:
            raise HeaderTooLarge  # it may lie in the part that was not read
        return ""

    def more():
        received = any(
            str(head.policy.header_fetch_parse(key, raw)).strip()
            for key, raw in usable
            if key.lower() == "received"
        )
        if not received and not complete:
            raise HeaderTooLarge  # a postmark may lie in the part that was not read
        return first("message-id"), received

    return first("in-reply-to"), more


def _mid(rng) -> str:
    left = "".join(rng.choice("ABCDEF0123456789-") for _ in range(rng.randint(8, 36)))
    return f"<{left}@{rng.choice(['mail-example', 'host', 'mx1-example', 'icloud'])}>"


def realistic_headers(rng, kind: str) -> bytes:
    """A header block as Mail writes a draft or a Sent copy, or as a mail server
    delivers a message. Generated: sizes are of generated text, not of real mail."""
    eol = "\r\n" if rng.random() < 0.5 else "\n"
    lines = []
    if kind in ("delivered", "heavy"):
        hops = rng.randint(3, 8) if kind == "delivered" else rng.randint(10, 16)
        lines.append("Return-Path: <bounce-17@lists-example>")
        for n in range(hops):
            lines.append(
                f"Received: from mx{n}-example (mx{n}-example [192.0.2.{n + 1}])"
                f"{eol}\tby mx{n + 1}-example with ESMTPS id {rng.getrandbits(60):x}"
                f"{eol}\tfor <jane@example>; Fri, 20 Nov 2026 10:{n:02d}:00 +0000"
            )
        seals = 1 if kind == "delivered" else 4
        for n in range(seals):
            b64 = "".join(rng.choice("ABCDEFabcdef0123456789+/") for _ in range(344))
            folded = f"{eol}\t ".join(b64[i : i + 70] for i in range(0, 344, 70))
            lines.append(f"ARC-Seal: i={n + 1}; a=rsa-sha256; t=1795168800; cv=pass;"
                         f"{eol}\td=example-relay; s=arc-2026; b={folded}")
            lines.append("ARC-Message-Signature: i=1; a=rsa-sha256; c=relaxed/relaxed;"
                         f"{eol}\td=example-relay; h=to:subject:message-id:date:from;"
                         f"{eol}\tbh=abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG=; b={folded}")
            lines.append("Authentication-Results: mx-example; dkim=pass header.i=@example-a"
                         f" header.s=s1 header.b=abc;{eol}\tspf=pass smtp.mailfrom=a;"
                         f"{eol}\tdmarc=pass (p=REJECT sp=REJECT dis=NONE) header.from=example-a")
            lines.append(f"DKIM-Signature: v=1; a=rsa-sha256; c=relaxed/relaxed; d=example-a;"
                         f"{eol}\ts=s1; h=from:to:subject:date:message-id; bh=abc=; b={folded}")
        if kind == "heavy":
            blob = "".join(rng.choice("ABCDEFabcdef0123456789+/") for _ in range(3000))
            lines.append("X-MS-Exchange-AntiSpam-MessageData-0: " + f"{eol}\t".join(
                blob[i : i + 76] for i in range(0, 3000, 76)))
            lines.append("List-Unsubscribe: <https://lists-example/u/" + "x" * 400 + ">")
            refs = f"{eol} ".join(_mid(rng) for _ in range(rng.randint(40, 120)))
            lines.append(f"References: {refs}")
    else:
        lines.append("Content-Type: multipart/alternative;"
                     f'{eol}\tboundary="Apple-Mail=_0A1B2C3D-0000-4000-8000-0123456789AB"')
        lines.append("X-Uniform-Type-Identifier: com.apple.mail-draft")
        lines.append("X-Universally-Unique-Identifier: 0A1B2C3D-0000-4000-8000-0123456789AB")
    lines.append("From: Jane Doe <jane@example>")
    lines.append("To: John Roe <john@example>")
    lines.append("Subject: Re: " + " ".join(rng.choice(["report", "meeting", "x"]) * 2
                                            for _ in range(rng.randint(1, 8))))
    lines.append("Date: Fri, 20 Nov 2026 10:00:00 +0100")
    lines.append("Mime-Version: 1.0 (Mac OS X Mail 16.0 \\(3864.200.21\\))")
    if rng.random() < 0.95:
        lines.append(f"Message-Id: {_mid(rng)}")
    if rng.random() < 0.8:
        lines.append(f"In-Reply-To: {_mid(rng)}")
    if kind != "heavy" and rng.random() < 0.8:
        lines.append("References: " + f"{eol} ".join(_mid(rng) for _ in range(rng.randint(1, 6))))
    rng.shuffle(lines)
    return (eol.join(lines) + eol + eol).encode()


_H_TOKENS = [
    "Message-ID:", "Message-Id:", "MESSAGE-ID:", "In-Reply-To:", "in-reply-to:",
    "Received:", "received:", "References:", "X-A:", "Subject:", ":", "From ", "From: ",
    " <a@b>", "<orig@x>", " <orig@x>", "<ORIG@X>", "<d@x>", "(c)", "((c))", "(", ")",
    "=?utf-8?q?=3Corig=40x=3E?=", "=?utf-8?q??=", '"q"', ",", ";", "<", ">", "@", ".",
    " ", "\t", "\r\n", "\n", "\r", "\r\n ", "\n\t", "\r\n\r\n", "\n\n", "\x0c", "\x0b",
    "\x1c", "\x85", "\xe9", "\x00", "body", "x" * 40,
]


def header_chain(rng) -> bytes:
    text = "".join(rng.choice(_H_TOKENS) for _ in range(rng.randint(0, 28)))
    return text.encode("latin-1")


def compare_read(payload: bytes, block: int) -> str:
    """``equal``, ``refused`` or ``DIFFERENT``."""
    old = old_read(payload)
    try:
        in_reply_to, more = new_read(payload, block)
        new = (in_reply_to, *more())
    except HeaderTooLarge:
        return "refused"
    return "equal" if new == old else "DIFFERENT"


def headers(args) -> int:
    print("\n=== B. the header read ===")
    print("today, one crafted field in an otherwise empty message:")
    shapes = {
        "Message-ID '<' + 'a' x n + '@x>'": lambda n: b"Message-ID: <" + b"a" * n + b"@x>",
        "Message-ID '<' + '.' x n + '@x>'": lambda n: b"Message-ID: <" + b"." * n + b"@x>",
        "In-Reply-To ',' x n": lambda n: b"In-Reply-To: " + b"," * n,
    }
    for label, make in shapes.items():
        row = [timed(old_read, make(n) + b"\r\n\r\nx")[0] for n in (10_000, 20_000)]
        print(f"  {label}: 10 KB {row[0]:.2f} s, 20 KB {row[1]:.2f} s")
    took, out = timed(old_read, b"Message-ID: " + b"(" * 20_000 + b"\r\n\r\nx")
    print(f"  Message-ID of 20,000 '(': {out}")
    low = next(
        n for n in range(100, 1200, 10)
        if timed(old_read, b"Message-ID: " + b"(" * n + b"\r\n\r\nx")[1] == "RecursionError"
    )
    print(f"  smallest count of '(' that raises here: {low} (recursion limit "
          f"{sys.getrecursionlimit()}; it is lower on a deeper stack)")

    print("the field split alone (no value parse), crafted blocks:")
    families = {
        "one long line": lambda n: b"X: " + b"a" * n + b"\r\n\r\n",
        "short fields": lambda n: b"A: b\r\n" * (n // 6) + b"\r\n",
        "continuation lines": lambda n: b"X: a\r\n" + b" b\r\n" * (n // 4) + b"\r\n",
        "bare CR": lambda n: b"A: b\r" * (n // 5) + b"\r\n\r\n",
        "no field name": lambda n: b": x\r\n" * (n // 5) + b"\r\n",
    }

    def split_only(payload):
        head = email.parser.BytesParser(policy=email.policy.default).parsebytes(
            payload, headersonly=True)
        return len(list(head.raw_items()))

    slowest = 0.0
    for label, make in families.items():
        row = [timed(split_only, make(n))[0] for n in (65_536, 131_072, 262_144)]
        slowest = max(slowest, row[1])
        print(f"  {label:18s} 64 / 128 / 256 KiB: " + ", ".join(f"{t:.3f} s" for t in row))
    print("the value parse of ONE field at the field bound (998 characters):")
    values = {
        "Message-ID '<' + '.' x 994 + '@x>'": ("Message-ID", "<" + "." * 994 + "@x>"),
        "In-Reply-To ',' x 998": ("In-Reply-To", "," * 998),
        "In-Reply-To '<a@b> ' x 166": ("In-Reply-To", "<a@b> " * 166),
        "Content-Type 'text/html' + '; =' x 329": ("Content-Type", "text/html" + "; =" * 329),
        "Content-Type 'text/html' + ';' x 989": ("Content-Type", "text/html" + ";" * 989),
    }
    worst = 0.0
    for label, (name, value) in values.items():
        best = min(timed(email.policy.default.header_fetch_parse, name, value)[0]
                   for _ in range(3))
        worst = max(worst, best)
        print(f"  {label}: {best * 1000:.2f} ms")
    print(f"  a row that is not in the thread costs at most the split of "
          f"{HEADER_READ_BYTES:,} bytes ({slowest:.3f} s) and one value parse "
          f"({worst * 1000:.1f} ms)")

    rng = random.Random(626)
    sizes: dict[str, list[int]] = {}
    longest_line = longest_field = 0
    tally = {"equal": 0, "refused": 0, "DIFFERENT": 0}
    for n in range(args.bodies):
        kind = ("draft", "sent", "delivered", "heavy")[n % 4]
        block = realistic_headers(rng, kind)
        sizes.setdefault(kind, []).append(len(block))
        longest_line = max(longest_line, *(len(line) for line in block.splitlines()))
        head = email.parser.BytesParser(policy=email.policy.default).parsebytes(block, True)
        for key, raw in head.raw_items():
            if key.lower() in ("in-reply-to", "message-id", "received"):
                longest_field = max(longest_field, len(raw))
        body = b"<div>Hi</div>" * rng.randint(1, 60_000 if n % 50 == 0 else 40)
        tally[compare_read(block + body, HEADER_READ_BYTES)] += 1
    print(f"realistic header blocks ({args.bodies:,}, generated), bytes min / max:")
    for kind, values_ in sizes.items():
        print(f"  {kind:9s} {min(values_):6,} / {max(values_):6,}")
    print(f"  longest physical line {longest_line}; longest In-Reply-To, Message-ID or "
          f"Received field {longest_field} characters")
    print(f"  bounded read against today's read: {tally}")
    bad = tally["DIFFERENT"] + tally["refused"]
    for block in (HEADER_READ_BYTES, 256, 64):
        tally = {"equal": 0, "refused": 0, "DIFFERENT": 0}
        inside = 0
        for _ in range(args.chains):
            payload = header_chain(rng)
            verdict = compare_read(payload, block)
            tally[verdict] += 1
            inside += verdict == "refused" and len(payload) <= block
        print(f"crafted field chains ({args.chains:,}), block bound {block:,} bytes: "
              f"{tally}; refused although whole: {inside}")
        bad += tally["DIFFERENT"] + inside
    print("crafted rows through the bounded read:")
    cases = {
        "In-Reply-To '<' + '.' x 100,000 + '@x>'": b"In-Reply-To: <" + b"." * 100_000 + b"@x>\r\n\r\nx",
        "Message-ID '<' + '.' x 100,000 + '@x>', not in the thread":
            b"In-Reply-To: <other@x>\r\nMessage-ID: <" + b"." * 100_000 + b"@x>\r\n\r\nx",
        "Message-ID of 20,000 '(', in the thread":
            b"In-Reply-To: <orig@x>\r\nMessage-ID: " + b"(" * 20_000 + b"\r\n\r\nx",
        "400,000 bytes of fields, no In-Reply-To": b"X-A: b\r\n" * 50_000 + b"\r\nx",
        "400,000 bytes of fields after In-Reply-To":
            b"In-Reply-To: <other@x>\r\n" + b"X-A: b\r\n" * 50_000 + b"\r\nx",
    }

    def judge(payload):
        in_reply_to, more = new_read(payload)
        if in_reply_to != "<orig@x>":
            return f"not in the thread ({in_reply_to[:12]!r})"
        return more()

    for label, payload in cases.items():
        took, out = timed(judge, payload)
        print(f"  {label}: {out} in {took * 1000:.1f} ms")
    took, _ = timed(old_read, b"In-Reply-To: <" + b"." * 50_000 + b"@x>\r\n\r\nx")
    print(f"  today, the first case at half size: {took:.1f} s (x4 at full size)")
    return bad


# === C. the message parse =============================================================


class MessageTooLarge(Exception):
    """The stored message is over a size bound; it was not parsed."""


def parse_checked(payload: bytes):
    """The parse of a candidate row. The byte bound is read from ``stat`` in the real
    code, before the file is read."""
    lines = payload.count(b"\n") + payload.count(b"\r") - payload.count(b"\r\n")
    parts = payload.count(b"\n--") + payload.count(b"\r--")
    if (
        len(payload) > MAX_MESSAGE_BYTES
        or lines > MAX_MESSAGE_LINES
        or parts > MAX_MESSAGE_PARTS
    ):
        raise MessageTooLarge
    return email.message_from_bytes(payload, policy=bounded())


def old_split(payload: bytes):
    return cleanup._split_quote(email.message_from_bytes(payload, policy=email.policy.default))


def new_split(payload: bytes):
    return cleanup._split_quote(parse_checked(payload))


_HEAD = b"Message-ID: <d@x>\r\nIn-Reply-To: <orig@x>\r\nMIME-Version: 1.0\r\n"


def many_parts(count: int, part: bytes = b"--b\r\nContent-Type: text/html\r\n\r\nx\r\n", eol=b"\r\n"):
    out = _HEAD + b'Content-Type: multipart/mixed; boundary="b"\r\n\r\n' + part * count + b"--b--\r\n"
    return out.replace(b"\r\n", eol)


def with_attachments(rng, count: int) -> bytes:
    msg = email.message.EmailMessage(policy=email.policy.default)
    msg["Message-ID"], msg["In-Reply-To"] = "<d@x>", "<orig@x>"
    msg.set_content("plain " + script_text(rng))
    msg.add_alternative(mailhtml.reply_html(rng), subtype="html")
    for n in range(count):
        name = "\u56fe" * rng.randint(1, 80) + f"{n}.png"
        if count > 30:  # many parts: short names, so their fields fit the budget of a parse
            name = name[: rng.randint(1, 8)] + f"{n}.png"
        # the name also as an RFC 2231 `name` parameter of Content-Type, as Mail writes it:
        # that field is the one the parse reads (at most 80 characters here: 246 bytes)
        msg.add_attachment(b"\x89PNG" * rng.randint(1, 400), maintype="image",
                           subtype="png", filename=name, params={"name": name})
    return msg.as_bytes()


def named_attachment(chars: int, count: int = 1) -> bytes:
    """``count`` attachments whose non-ASCII file name has ``chars`` characters (3 bytes
    each), on Content-Type and on Content-Disposition, with Mail's ``x-unix-mode``."""
    msg = email.message.EmailMessage(policy=email.policy.default)
    msg["Message-ID"], msg["In-Reply-To"] = "<d@x>", "<orig@x>"
    msg.set_content("<div>Hi</div>", subtype="html")
    for n in range(count):
        name = chr(0x56FE) * (chars - len(str(n))) + f"{n}.png"
        msg.add_attachment(b"\x89PNG" * 10, maintype="image", subtype="png", filename=name,
                           params={"x-unix-mode": "0644", "name": name})
    return msg.as_bytes()


def most_attachments(chars: int) -> int:
    """The largest count of such attachments that the budget of one parse lets through."""
    low, high = 1, MAX_MESSAGE_PARTS
    while low < high:
        mid = (low + high + 1) // 2
        if isinstance(timed(new_split, named_attachment(chars, mid))[1], str):
            high = mid - 1
        else:
            low = mid
    return low


_M_TOKENS = [
    b"--b\r\n", b"--b--\r\n", b"--c\r\n", b"--c--\r\n", b"\r\n", b"\n", b"\r",
    b"Content-Type: text/html\r\n", b"Content-Type: text/plain; charset=utf-8\r\n",
    b'Content-Type: multipart/mixed; boundary="c"\r\n', b"Content-Type: message/rfc822\r\n",
    b"Content-Type: text/html; charset*=utf-8''utf-8; x=(c)\r\n",
    b"Content-Type: TEXT/HTML ; ; =\r\n", b"Content-Type: text/html;\r\n charset=latin-1\r\n",
    b"Content-Transfer-Encoding: quoted-printable\r\n", b"Content-Transfer-Encoding: base64\r\n",
    b"<div>Hi =3D there</div>", b"<blockquote>q</blockquote>", b"PGRpdj5IaTwvZGl2Pg==",
    b"> quoted\r\n", b"-- \r\n", b"-->", b"\xe9", b" ", b"x",
]


def mime_chain(rng) -> bytes:
    top = rng.choice([b'Content-Type: multipart/mixed; boundary="b"\r\n\r\n',
                      b"Content-Type: text/html\r\n\r\n", b"\r\n"])
    return _HEAD + top + b"".join(rng.choice(_M_TOKENS) for _ in range(rng.randint(0, 30)))


def message(args) -> int:
    print("\n=== C. the message parse ===")
    print("today, many small parts (parse, walk and decode; the body cap comes after):")
    for count in (5_000, 10_000, 25_001):
        payload = many_parts(count)
        took, _ = timed(old_split, payload)
        print(f"  {count:6,} parts, {len(payload):9,} bytes: {took:.2f} s")
    print("today, lines of one text part (the parse alone):")
    for label, make in (("1-byte lines", lambda n: b"\n" * n),
                        ("77-byte base64 lines", lambda n: (b"A" * 76 + b"\n") * (n // 77))):
        payload = _HEAD + b"Content-Type: text/plain\r\n\r\n" + make(4_000_000)
        took, _ = timed(email.message_from_bytes, payload)
        print(f"  4,000,000 bytes of {label}: {took:.3f} s")
    print("today, one crafted Content-Type field of a part:")
    for size in (5_000, 10_000, 20_000):
        payload = _HEAD + b"Content-Type: text/html;" + b" ; " * (size // 3) + b"\r\n\r\n<div>x</div>"
        took, _ = timed(old_split, payload)
        print(f"  {size:6,} bytes of ' ; ' after text/html: {took:.2f} s")
    att = (b"A" * 76 + b"\r\n") * (25_000_000 // 78)
    big = (_HEAD + b'Content-Type: multipart/mixed; boundary="b"\r\n\r\n--b\r\n'
           b"Content-Type: text/html\r\n\r\n<div>Hi</div>\r\n--b\r\nContent-Type: image/png\r\n"
           b"Content-Transfer-Encoding: base64\r\n\r\n" + att + b"--b--\r\n")
    old_t, old_out = timed(old_split, big)
    new_t, new_out = timed(new_split, big)
    lines = big.count(b"\n")
    print(f"a 25 MB message of the normal shape ({lines:,} lines): today {old_t:.2f} s, "
          f"bounded {new_t:.2f} s, equal output: {old_out == new_out}")

    print("crafted messages through the bounded parse:")
    cases = {
        "120,000 parts (CRLF)": many_parts(120_000),
        "120,000 parts (bare CR)": many_parts(120_000, eol=b"\r"),
        "1,200,000 one-byte lines": _HEAD + b"Content-Type: text/plain\r\n\r\n" + b"\n" * 1_200_000,
        "one Content-Type of 80,000 bytes": _HEAD + b"Content-Type: text/html;" + b" ; " * 26_666 + b"\r\n\r\nx",
        "900 parts, each a worst 998-character Content-Type": many_parts(
            900, b"--b\r\nContent-Type: " + (b"text/html" + b"; =" * 329) + b"\r\n\r\nx\r\n"),
        "multipart nested 900 deep": _HEAD + b"".join(
            b'Content-Type: multipart/mixed; boundary="b%d"\r\n\r\n--b%d\r\n' % (n, n)
            for n in range(900)) + b"Content-Type: text/html\r\n\r\nx\r\n",
    }
    for label, payload in cases.items():
        took, out = timed(new_split, payload)
        out = out if isinstance(out, str) else "parsed"
        print(f"  {label} ({len(payload):,} bytes): {out} in {took:.3f} s")
    took, _ = timed(old_split, many_parts(30_000))
    print(f"  today, 30,000 parts: {took:.1f} s (x4 at 120,000 parts)")
    payload = _HEAD + b"Content-Type: text/html;" + b" ; " * 13_333 + b"\r\n\r\nx"
    took, _ = timed(old_split, payload)
    print(f"  today, one Content-Type of 40,000 bytes: {took:.1f} s (x4 at 80,000 bytes)")
    worst = many_parts(MAX_MESSAGE_PARTS - 2)
    took, out = timed(new_split, worst)
    print(f"  the most parts that PASS ({MAX_MESSAGE_PARTS - 2}): "
          f"{'parsed' if not isinstance(out, str) else out} in {took:.3f} s")
    print("a long non-ASCII file name as the `name` parameter of Content-Type (the bound "
          "measures the raw field value, fold bytes included):")
    for chars in (83, 90, 120):
        payload = named_attachment(chars)
        part = list(email.message_from_bytes(payload, policy=email.policy.default).walk())[-1]
        raw = dict((k.lower(), v) for k, v in part.raw_items())["content-type"]
        took, out = timed(new_split, payload)
        out = out if isinstance(out, str) else "parsed"
        print(f"  {chars} characters ({3 * chars + 4} bytes of name): the field is "
              f"{len(raw)} characters -> {out}")
    print("the budget of one parse (the parser reads each Content-Type about 6 times): the "
          "most attachments that pass, by length of the non-ASCII name:")
    print("  " + "; ".join(f"{chars} characters: {most_attachments(chars)}"
                           for chars in (83, 40, 10)))

    rng = random.Random(626)
    tally = {"equal": 0, "refused": 0, "DIFFERENT": 0}
    used = calls_max = longest = 0
    for n in range(args.bodies):
        if n % 10 == 0:
            payload = with_attachments(rng, rng.choice([1, 5, 30, 100]))
        else:
            payload = mailhtml.message(mailhtml.reply_html(rng), rng).as_bytes()
        old = old_split(payload)
        policy = bounded()
        try:
            parse_checked(payload)  # the size checks
            new = cleanup._split_quote(email.message_from_bytes(payload, policy=policy))
        except (HeaderTooLarge, MessageTooLarge):
            tally["refused"] += 1
            continue
        used = max(used, MAX_HEADER_FETCH_CHARS - policy.budget[0])
        longest = max(longest, policy.budget[1])
        calls_max = max(calls_max, payload.count(b"\n--"))
        tally["equal" if new == old else "DIFFERENT"] += 1
    print(f"differential on {args.bodies:,} generated messages (every tenth with 1 to 100 "
          f"attachments, each with an RFC 2231 `name` on Content-Type): {tally}")
    print(f"  longest field value that a parse read: {longest} of "
          f"{MAX_HEADER_FIELD_CHARS} characters")
    print(f"  most field characters that one parse read: {used:,} of "
          f"{MAX_HEADER_FETCH_CHARS:,}; most delimiter lines: {calls_max} of {MAX_MESSAGE_PARTS:,}")
    bad = tally["DIFFERENT"] + tally["refused"]
    tally = {"equal": 0, "refused": 0, "DIFFERENT": 0, "both raise": 0}
    for _ in range(args.chains):
        payload = mime_chain(rng)
        try:
            old = old_split(payload)
        except Exception as exc:  # noqa: BLE001 - the old error is compared by type
            old = type(exc).__name__
        try:
            new = new_split(payload)
        except (HeaderTooLarge, MessageTooLarge):
            tally["refused"] += 1
            continue
        except Exception as exc:  # noqa: BLE001
            new = type(exc).__name__
        if isinstance(old, str) and new == old:
            tally["both raise"] += 1
        else:
            tally["equal" if new == old else "DIFFERENT"] += 1
    print(f"crafted MIME chains ({args.chains:,}): {tally}")
    return bad + tally["DIFFERENT"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bodies", type=int, default=4_000)
    ap.add_argument("--texts", type=int, default=100_000)
    ap.add_argument("--chains", type=int, default=100_000)
    args = ap.parse_args()
    print(f"python {sys.version.split()[0]}")
    bad = normalization(args)
    compose_reach()
    bad += headers(args)
    bad += message(args)
    print("\nRESULT:", "every output equal or refused; no legitimate input refused"
          if not bad else f"{bad} PROBLEMS")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
