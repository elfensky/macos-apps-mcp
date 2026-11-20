"""A seeded generator of reply bodies in Mail's layout, and of crafted texts, for the
differential test of the reply sweep's HTML strip (FIX-34, #611).

Every text here is generated from the fixed lists below with the caller's
``random.Random``. None of it is real mail, and no stored mail is read.

- ``reply_html`` / ``message``: one reply as Mail writes it (text, optional signature,
  attribution, ``blockquote type="cite"``). The quote holds style and script blocks,
  comments, entities, both inline-image placeholder forms, nested quotes, tables,
  attributes with ``<`` and ``>``, bare angle brackets and U+FFFC.
- ``crafted``: a random chain of ``_TOKENS``, every piece the two strip patterns react
  to.
- ``SAMPLES`` / ``script_text``: words in 13 scripts (Latin with accents, Vietnamese,
  Hebrew with points and with cantillation, Arabic with marks, Thai, Devanagari, Korean,
  emoji with modifiers and joiners, Tibetan, phonetic notation, polytonic Greek, Bengali
  and Tamil), for the scan that refuses a long run of combining characters before the
  sweep normalizes a text (FIX-36, #626). They are generated text: common words and
  phrases typed as escapes, in NFC, NFD or as written. ``_PINS`` holds one code point of
  each sample that an editor could fold away.

The four characters that decide a test are written as escapes, never as glyphs (an
editor once normalized such a glyph and the test went vacuous): U+017F, U+0130 and
U+0131 case-fold to ``s`` or ``i``, and U+FFFC is the object mark.
"""

from __future__ import annotations

import email.message
import email.policy
import unicodedata

_WORDS = (  # noqa: SIM905 - the prototype's form, kept as copied
    "meeting invoice thanks regards project update please find attached the report "
    "Größe naïve café Привет 日本語 déjà vu price 3 5 total a b c d"
).split()
_ENT = ["&amp;", "&lt;", "&gt;", "&nbsp;", "&#8217;", "&#x2019;", "&quot;", "&euro;"]


def _sentence(rng, n=None) -> str:
    n = n or rng.randint(3, 14)
    out = []
    for _ in range(n):
        out.append(rng.choice(_ENT) if rng.random() < 0.08 else rng.choice(_WORDS))
    return " ".join(out)


def _css(rng) -> str:
    rules = [
        "body { margin:0; padding:0 }",
        "table > tr > td { border:0 }",
        "a[href^='http'] > span { color:#00f }",
        "@media only screen and (max-width:600px) { .w { width:100% !important } }",
        "/* a comment with </b> and <i> */",
        ".x:after { content:'>' }",
        "p.MsoNormal, li.MsoNormal { margin:0cm; font-size:11.0pt }",
    ]
    return "\n".join(rng.sample(rules, rng.randint(1, len(rules))))


def _js(rng) -> str:
    lines = [
        "if (a < b && c > d) { track('open'); }",
        "var s = '</div><p>x</p>';",
        "document.write('<img src=\"x.gif\">');",
        "for (var i = 0; i < 3; i++) {}",
    ]
    return "\n".join(rng.sample(lines, rng.randint(1, len(lines))))


def _cid(rng) -> str:
    name = rng.choice(["logo.png", "image001.jpg", "a b.gif", "Größe.png"])
    cls = rng.choice(['class="AppleTemporaryEditingElement" ', ""])
    return f'<span {cls}id="cid:{rng.randint(1, 9999)}@x">&lt;{name}&gt;</span>'


def _fragment(rng, depth=0) -> str:
    pick = rng.random()
    if pick < 0.30:
        return f"<div>{_sentence(rng)}</div>"
    if pick < 0.38:
        tag = rng.choice(["style", "STYLE", "Style"])
        attr = rng.choice(["", ' type="text/css"', ' media="all"'])
        return f"<{tag}{attr}>{_css(rng)}</{tag}>"
    if pick < 0.43:
        tag = rng.choice(["script", "SCRIPT"])
        return f'<{tag} type="text/javascript">{_js(rng)}</{tag}>'
    if pick < 0.50:
        return f"<!-- {_sentence(rng, 4)} -->"
    if pick < 0.55:
        return "<!--[if gte mso 9]><xml><o:p>x</o:p></xml><![endif]-->"
    if pick < 0.63:
        title = rng.choice(["a > b", "plain", "x&gt;y", "5 > 3 and 2 < 4"])
        return (
            f'<a href="https://example.com/?a=1&amp;b=2" title="{title}">'
            f"{_sentence(rng, 3)}</a>"
        )
    if pick < 0.70:
        return _cid(rng)
    if pick < 0.76:
        return (
            '<table border="0" cellpadding="0"><tbody><tr><td style="padding:0">'
            f"{_sentence(rng)}</td><td>{_sentence(rng, 2)}</td></tr></tbody></table>"
        )
    if pick < 0.80:
        return rng.choice(["<br>", "<br/>", '<br class="">', "<hr>", "<o:p></o:p>"])
    if pick < 0.84:
        return f"<p>{_sentence(rng, 3)} 3 &lt; 5 {rng.choice(['', '&gt;'])}</p>"
    if pick < 0.87:  # sloppy sender markup: a bare angle bracket in text
        return (
            f"<p>{_sentence(rng, 2)} {rng.choice(['a < b', 'x > y', '<3', '->'])}</p>"
        )
    if pick < 0.90:
        return f"<b>{_sentence(rng, 2)}</b>\ufffc<i>{_sentence(rng, 2)}</i>\r\n"
    if pick < 0.94 and depth < 3:  # an older reply in the thread
        inner = "".join(_fragment(rng, depth + 1) for _ in range(rng.randint(1, 4)))
        return f'<blockquote type="cite"><div>{inner}</div></blockquote>'
    if pick < 0.97:
        alt = rng.choice(["logo", "a > b", "&lt;logo.png&gt;"])
        return f'<img src="cid:{rng.randint(1, 99)}@x" alt="{alt}" width="10">'
    return (
        '<span style="font-family: Helvetica; font-size: 12px;">'
        f"{_sentence(rng)}</span>"
    )


def reply_html(rng) -> str:
    """One reply body in Mail's layout: text, optional signature, attribution, quote."""
    original = "".join(_fragment(rng) for _ in range(rng.randint(1, 25)))
    text = "<br>".join(_sentence(rng) for _ in range(rng.randint(1, 3)))
    sig = ""
    if rng.random() < 0.5:
        sig = (
            '<div id="AppleMailSignature" dir="ltr">'
            f"<div>{_sentence(rng, 4)}</div></div>"
        )
    attribution = (
        "<div>On 26 Oct 2026, at 01:36, Jane Doe &lt;jane@example&gt; wrote:</div>"
    )
    close = "" if rng.random() < 0.03 else "</blockquote>"  # an unclosed quote
    below = f"<div>{_sentence(rng, 3)}</div>" if rng.random() < 0.05 else ""
    head = rng.choice(
        [
            '<html><head><meta http-equiv="content-type" '
            'content="text/html; charset=utf-8">'
            '</head><body style="overflow-wrap: break-word; '
            '-webkit-nbsp-mode: space;">',
            "<html><head></head><body>",
            "",
        ]
    )
    return (
        f"{head}{text}{sig}<br><div><br>"
        f'<blockquote type="cite">{attribution}<br class="Apple-interchange-newline">'
        f"<div>{original}</div>{close}</div>{below}"
        + ("</body></html>" if head else "")
    )


def message(markup: str, rng) -> email.message.EmailMessage:
    msg = email.message.EmailMessage(policy=email.policy.default)
    msg["Subject"] = "Re: x"
    if rng.random() < 0.3:
        msg.set_content("plain " + _sentence(rng))
        msg.add_alternative(markup, subtype="html")
    else:
        msg.set_content(markup, subtype="html")
    return msg


# Every piece the two strip patterns react to.
_TOKENS = [
    "<",
    ">",
    "<>",
    "</",
    "/>",
    "<<",
    ">>",
    " ",
    "\n",
    "a",
    "x y",
    "&lt;",
    "&gt;",
    "<script",
    "<script>",
    "<script ",
    "</script>",
    "</script >",
    "<SCRIPT>",
    "</SCRIPT>",
    "<Script>",
    "</ScRiPt>",
    "<scripts>",
    "</scripts>",
    "<script/>",
    "<style",
    "<style>",
    "<style ",
    "</style>",
    "<STYLE>",
    "</STYLE>",
    "<styled>",
    "</style >",
    "<\u017fcript>",
    "</\u017fcript>",
    "<scr\u0130pt>",
    "</scr\u0130pt>",
    "<scr\u0131pt>",
    "</scr\u0131pt>",
    "<\u017ftyle>",
    "</\u017ftyle>",
    "<blockquote>",
    "</blockquote>",
    "<b>",
    "</b>",
    '<a title="x<y">',
    '<a title="x>y">',
    "<!--",
    "-->",
    '<span id="cid:1">&lt;a.png&gt;</span>',
    "\ufffc",
    "<br>",
]


def crafted(rng) -> str:
    return "".join(rng.choice(_TOKENS) for _ in range(rng.randint(0, 24)))


# --- text in 13 scripts, for the combining-run scan (FIX-36, #626) ---

# Natural-language samples, written as escapes (an editor once normalized a glyph).
SAMPLES = {
    "latin": "Cr\xe8me br\xfbl\xe9e \xe0 la fa\xe7on de Zo\xeb; \xc5ngstr\xf6m, se\xf1"
    "or, Dvo\u0159\xe1k, \u0141\xf3d\u017a, sm\xf6rg\xe5sbord, na\xefve co\xf6perate, "
    "\u0130stanbul, Gy\u0151r, \u0160koda",
    "vietnamese": "Ti\u1ebfng Vi\u1ec7t l\xe0 ng\xf4n ng\u1eef c\u1ee7a ng\u01b0\u1edd"
    "i Vi\u1ec7t; ph\u1edf b\xf2, b\xe1nh m\xec, Nguy\u1ec5n Th\u1ecb H\u1ed3ng, "
    "\u0111\u01b0\u1eddng L\xea L\u1ee3i, nh\u1eefng gi\u1ea5c m\u01a1, \u1edf Hu"
    "\u1ebf",
    "hebrew_points": "\u05d1\u05b0\u05bc\u05e8\u05b5\u05d0\u05e9\u05b4\u05c1\u05d9"
    "\u05ea \u05d1\u05b8\u05bc\u05e8\u05b8\u05d0 \u05d0\u05b1\u05dc\u05b9\u05d4\u05b4"
    "\u05d9\u05dd \u05d0\u05b5\u05ea \u05d4\u05b7\u05e9\u05b8\u05bc\u05c1\u05de\u05b7"
    "\u05d9\u05b4\u05dd \u05d5\u05b0\u05d0\u05b5\u05ea \u05d4\u05b8\u05d0\u05b8\u05e8"
    "\u05b6\u05e5",
    "hebrew_cantillation": "\u05d1\u05b0\u05bc\u05e8\u05b5\u05d0\u05e9\u05b4\u05c1"
    "\u0596\u05d9\u05ea \u05d1\u05b8\u05bc\u05e8\u05b8\u05a3\u05d0 \u05d0\u05b1\u05dc"
    "\u05b9\u05d4\u05b4\u0591\u05d9\u05dd \u05d0\u05b5\u05a5\u05ea \u05d4\u05b7\u05e9"
    "\u05b8\u05bc\u05c1\u05de\u05b7\u0596\u05d9\u05b4\u05dd \u05d5\u05b0\u05d0\u05b5"
    "\u05a5\u05ea \u05d4\u05b8\u05d0\u05b8\u05bd\u05e8\u05b6\u05e5\u05c3",
    "arabic_marks": "\u0628\u0650\u0633\u0652\u0645\u0650 \u0627\u0644\u0644\u064e"
    "\u0651\u0647\u0650 \u0627\u0644\u0631\u064e\u0651\u062d\u0652\u0645\u064e\u0670"
    "\u0646\u0650 \u0627\u0644\u0631\u064e\u0651\u062d\u0650\u064a\u0645\u0650 \u0627"
    "\u0644\u0652\u062d\u064e\u0645\u0652\u062f\u064f \u0644\u0650\u0644\u064e\u0651"
    "\u0647\u0650 \u0645\u064f\u062d\u064e\u0645\u064e\u0651\u062f\u064c",
    "thai": "\u0e20\u0e32\u0e29\u0e32\u0e44\u0e17\u0e22\u0e40\u0e1b\u0e47\u0e19\u0e20"
    "\u0e32\u0e29\u0e32\u0e17\u0e35\u0e48\u0e21\u0e35\u0e27\u0e23\u0e23\u0e13\u0e22"
    "\u0e38\u0e01\u0e15\u0e4c \u0e19\u0e49\u0e33 \u0e1c\u0e39\u0e49\u0e43\u0e2b\u0e0d"
    "\u0e48 \u0e17\u0e35\u0e48\u0e19\u0e35\u0e48 \u0e02\u0e2d\u0e1a\u0e04\u0e38\u0e13"
    "\u0e04\u0e23\u0e31\u0e1a \u0e40\u0e01\u0e49\u0e32\u0e2d\u0e35\u0e49 \u0e1b\u0e39"
    "\u0e48\u0e22\u0e48\u0e32",
    "devanagari": "\u0939\u093f\u0928\u094d\u0926\u0940 \u092d\u093e\u0937\u093e "
    "\u0915\u093c\u093f\u0932\u093e \u091c\u093c\u0930\u0942\u0930\u0940 \u0915\u0943"
    "\u0937\u094d\u0923 \u0936\u094d\u0930\u0940\u092e\u093e\u0928\u094d \u0935\u093f"
    "\u0926\u094d\u092f\u093e\u0930\u094d\u0925\u0940 \u092b\u093c\u094d\u0930\u093e"
    "\u0902\u0938 \u0939\u0942\u0901",
    "korean": "\ud55c\uad6d\uc5b4 \uac10\uc0ac\ud569\ub2c8\ub2e4 \uc548\ub155\ud558"
    "\uc138\uc694 \ub300\ud55c\ubbfc\uad6d \uc11c\uc6b8\ud2b9\ubcc4\uc2dc \uae40\uce58"
    "\ucc0c\uac1c",
    "emoji": "\U0001f44d\U0001f3fd \U0001f468\u200d\U0001f469\u200d\U0001f467\u200d"
    "\U0001f466 \U0001f3f3\ufe0f\u200d\U0001f308 \U0001f469\U0001f3ff\u200d\U0001f4bb "
    "\U0001f1e7\U0001f1ea 1\ufe0f\u20e3 \u2764\ufe0f\u200d\U0001f525 \u270c\U0001f3fc",
    "tibetan": "\u0f67\u0f71\u0f74\u0f83 \u0f56\u0f7c\u0f51\u0f0b\u0f66\u0f90\u0f51"
    "\u0f0b \u0f68\u0f7c\u0f7e\u0f0b\u0f58\u0f0b\u0f4e\u0f72\u0f0b\u0f54\u0f51\u0fa8"
    "\u0f7a\u0f0b\u0f67\u0f71\u0f74\u0f83 \u0f56\u0f40\u0fb2\u0f0b\u0f64\u0f72\u0f66",
    "ipa": "p\u02b0\u0279\u0325\u0259\u0303\u02c8n\u028c\u0303n.si.e\u026a\u032f."
    "\u0283n\u0329 t\u032a\u0361s\u032a\u02bc \xe3\u0320\u0303 x\u0304\u0303 \u1e8d"
    "\u0302 e\u030b\u0342",
    "greek_polytonic": "\u1f18\u03bd \u1f00\u03c1\u03c7\u1fc7 \u1f26\u03bd \u1f41 "
    "\u03bb\u03cc\u03b3\u03bf\u03c2, \u03ba\u03b1\u1f76 \u1f41 \u03bb\u03cc\u03b3"
    "\u03bf\u03c2 \u1f26\u03bd \u03c0\u03c1\u1f78\u03c2 \u03c4\u1f78\u03bd \u03b8"
    "\u03b5\u03cc\u03bd \u1fa7 \u1f97 \u1fa0\u03b4\u03ae",
    "bengali_tamil": "\u09ac\u09be\u0982\u09b2\u09be \u09ad\u09be\u09b7\u09be \u0995"
    "\u09c3\u09b7\u09cd\u09a3 \u09a4\u09be\u0981\u09b0 \u0ba4\u0bae\u0bbf\u0bb4\u0bcd "
    "\u0bae\u0bca\u0bb4\u0bbf \u0b95\u0bca\u0bb3\u0bcd\u0b95\u0bc8",
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
