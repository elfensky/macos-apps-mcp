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

The four characters that decide a test are written as escapes, never as glyphs (an
editor once normalized such a glyph and the test went vacuous): U+017F, U+0130 and
U+0131 case-fold to ``s`` or ``i``, and U+FFFC is the object mark.
"""

from __future__ import annotations

import email.message
import email.policy

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
