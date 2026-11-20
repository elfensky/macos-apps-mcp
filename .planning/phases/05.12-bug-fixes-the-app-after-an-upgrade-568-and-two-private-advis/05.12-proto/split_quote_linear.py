"""FIX-34 (#611) prototype: the two HTML strips of ``_split_quote`` in linear time, and
the differential proof that the output does not change.

Run from the repo root:  uv run python <this file> [--bodies N] [--fuzz N]

No Mail call, no native call: pure string work on generated text.

Design (EXACT form): both helpers return what the old ``re.sub`` returns, for every
input. They only stop the regex engine from repeating a scan that cannot succeed.

- ``drop_tags``: ``<[^>]+>`` can only match up to the last ``>``. The old pattern scanned
  to the end of the text from every ``<`` after that point. Cut the text there first.
- ``drop_blocks``: the old pattern is tried only where an opener starts. A failed try
  means no closing tag for that captured name exists from there on, so a later opener
  with the same name fails too and is skipped without a scan.

The REVIEW form (05.2-REVIEW.md WR-04) is kept here only to count where it differs.
"""

from __future__ import annotations

import argparse
import email.message
import email.policy
import html
import random
import re
import sys
import time

from macos_apps_mcp.adapters import mail_reply_cleanup as cleanup
from macos_apps_mcp.text import squash_text

# --- the old steps (mail_reply_cleanup.py:306-307), as two functions ----------------

_OLD_BLOCK = re.compile(r"(?is)<(script|style).*?</\1>")
_OLD_TAG = re.compile(r"<[^>]+>")


def old_blocks(chunk: str) -> str:
    return _OLD_BLOCK.sub("", chunk)


def old_tags(chunk: str) -> str:
    return _OLD_TAG.sub(" ", chunk)


# --- the EXACT linear form (the proposal) -------------------------------------------

_OPENER = re.compile(r"(?i)<(script|style)")


def drop_blocks(chunk: str) -> str:
    """``re.sub(r"(?is)<(script|style).*?</\\1>", "", chunk)`` in linear time."""
    out: list[str] = []
    done = at = 0
    dead: set[str] = set()  # captured names with no closing tag from here on
    while (opener := _OPENER.search(chunk, at)) is not None:
        # equal keys differ in ASCII case only, so they have the same closing tags
        key = opener.group(1).lower()
        block = None if key in dead else _OLD_BLOCK.match(chunk, opener.start())
        if block is None:
            dead.add(key)
            at = opener.end()
            continue
        out.append(chunk[done : opener.start()])
        done = at = block.end()
    out.append(chunk[done:])
    return "".join(out)


def drop_tags(chunk: str) -> str:
    """``re.sub(r"<[^>]+>", " ", chunk)`` in linear time: no tag ends after the last
    ``>``, and before it every ``<`` meets a ``>``."""
    last = chunk.rfind(">") + 1
    return _OLD_TAG.sub(" ", chunk[:last]) + chunk[last:]


# --- the REVIEW form (WR-04), for comparison only -----------------------------------


def review_blocks(chunk: str) -> str:
    for tag in ("script", "style"):
        out, pos = [], 0
        close = re.compile(rf"(?i)</{tag}>")
        for m in re.finditer(rf"(?i)<{tag}\b", chunk):
            if m.start() < pos:
                continue
            end = close.search(chunk, m.end())
            if end is None:
                break
            out.append(chunk[pos : m.start()])
            pos = end.end()
        chunk = "".join(out) + chunk[pos:]
    return chunk


def review_tags(chunk: str) -> str:
    return re.sub(r"<[^<>]+>", " ", chunk)


# --- _split_quote with the strip steps as parameters --------------------------------


def split_quote(msg, blocks, tags) -> tuple[str, str]:
    """``mail_reply_cleanup._split_quote`` with the two strip steps passed in."""
    markup = text = ""
    for part in msg.walk():
        kind = part.get_content_type()
        try:
            if kind == "text/html":
                markup += part.get_content()
            elif kind == "text/plain":
                text += part.get_content()
        except (LookupError, ValueError):
            continue
    if markup:
        cut = re.search(r"(?i)<blockquote\b", markup)
        at = cut.start() if cut else len(markup)
        parts = []
        quote = markup[at:]
        closes = list(re.finditer(r"(?i)</blockquote>", quote))
        end = closes[-1].end() if closes else 0
        for chunk in (markup[:at], cleanup._drop_placeholders(quote[:end]) + quote[end:]):
            parts.append(html.unescape(tags(blocks(chunk))))
        head, tail = parts
    else:
        lines = text.splitlines()
        at = next((n for n, ln in enumerate(lines) if ln.startswith(">")), len(lines))
        head, tail = "\n".join(lines[:at]), "\n".join(lines[at:])
    return squash_text(head.replace("￼", "")), squash_text(tail)


# --- corpus 1: realistic Mail-written reply bodies ----------------------------------

_WORDS = (
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
        return f'<a href="https://example.com/?a=1&amp;b=2" title="{title}">{_sentence(rng, 3)}</a>'
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
        return f"<p>{_sentence(rng, 2)} {rng.choice(['a < b', 'x > y', '<3', '->'])}</p>"
    if pick < 0.90:
        return f"<b>{_sentence(rng, 2)}</b>￼<i>{_sentence(rng, 2)}</i>\r\n"
    if pick < 0.94 and depth < 3:  # an older reply in the thread
        inner = "".join(_fragment(rng, depth + 1) for _ in range(rng.randint(1, 4)))
        return f'<blockquote type="cite"><div>{inner}</div></blockquote>'
    if pick < 0.97:
        alt = rng.choice(["logo", "a > b", "&lt;logo.png&gt;"])
        return f'<img src="cid:{rng.randint(1, 99)}@x" alt="{alt}" width="10">'
    return f'<span style="font-family: Helvetica; font-size: 12px;">{_sentence(rng)}</span>'


def reply_html(rng) -> str:
    """One reply body in Mail's layout: text, optional signature, attribution, quote."""
    original = "".join(_fragment(rng) for _ in range(rng.randint(1, 25)))
    text = "<br>".join(_sentence(rng) for _ in range(rng.randint(1, 3)))
    sig = ""
    if rng.random() < 0.5:
        sig = f'<div id="AppleMailSignature" dir="ltr"><div>{_sentence(rng, 4)}</div></div>'
    attribution = (
        "<div>On 26 Oct 2026, at 01:36, Jane Doe &lt;jane@example.com&gt; wrote:</div>"
    )
    close = "" if rng.random() < 0.03 else "</blockquote>"  # an unclosed quote
    below = f"<div>{_sentence(rng, 3)}</div>" if rng.random() < 0.05 else ""
    head = rng.choice(
        [
            '<html><head><meta http-equiv="content-type" content="text/html; charset=utf-8">'
            '</head><body style="overflow-wrap: break-word; -webkit-nbsp-mode: space;">',
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


# --- corpus 2: crafted text (every piece the two patterns react to) -----------------

_TOKENS = [
    "<", ">", "<>", "</", "/>", "<<", ">>", " ", "\n", "a", "x y", "&lt;", "&gt;",
    "<script", "<script>", "<script ", "</script>", "</script >", "<SCRIPT>",
    "</SCRIPT>", "<Script>", "</ScRiPt>", "<scripts>", "</scripts>", "<script/>",
    "<style", "<style>", "<style ", "</style>", "<STYLE>", "</STYLE>", "<styled>",
    "</style >", "<ſcript>", "</ſcript>", "<scrİpt>", "</scrİpt>",
    "<scrıpt>", "</scrıpt>", "<ſtyle>", "</ſtyle>",
    "<blockquote>", "</blockquote>", "<b>", "</b>", '<a title="x<y">', '<a title="x>y">',
    "<!--", "-->", '<span id="cid:1">&lt;a.png&gt;</span>', "￼", "<br>",
]  # fmt: skip


def crafted(rng) -> str:
    return "".join(rng.choice(_TOKENS) for _ in range(rng.randint(0, 24)))


# --- the differential runs ----------------------------------------------------------


def _class_of(text: str) -> str:
    """A coarse label of a crafted input, to group where the REVIEW form differs."""
    labels = []
    if re.search(r"(?i)<(script|style)(?![\s>/])", text):
        labels.append("opener followed by a letter (<scripts, <styled) or by nothing")
    if re.search(r"<[^<>]*<", text):
        labels.append("a '<' before the tag's '>'")
    if re.search("[ſİı]", text):
        labels.append("a non-ASCII letter that case-folds to s or i")
    if re.search(r"(?i)<script", text) and re.search(r"(?i)<style", text):
        labels.append("script and style openers both present")
    return "; ".join(labels) or "other"


def run(bodies: int, fuzz: int) -> int:
    rng = random.Random(611)
    failures = 0

    # 1. realistic bodies, through the whole of _split_quote
    exact = review = 0
    for _ in range(bodies):
        msg = message(reply_html(rng), rng)
        want = cleanup._split_quote(msg)  # the code as it is today
        assert want == split_quote(msg, old_blocks, old_tags), "the copy drifted"
        exact += want != split_quote(msg, drop_blocks, drop_tags)
        review += want != split_quote(msg, review_blocks, review_tags)
    print(f"realistic bodies: {bodies}; EXACT form differs: {exact}; REVIEW form differs: {review}")
    failures += exact

    # 2. crafted text, on the two steps and on their composition
    exact = review = 0
    classes: dict[str, int] = {}
    more = other = 0
    for _ in range(fuzz):
        chunk = crafted(rng)
        want = old_tags(old_blocks(chunk))
        got = drop_tags(drop_blocks(chunk))
        if (
            old_blocks(chunk) != drop_blocks(chunk)
            or old_tags(chunk) != drop_tags(chunk)
            or want != got
        ):
            exact += 1
        rev = review_tags(review_blocks(chunk))
        if rev != want:
            review += 1
            classes[_class_of(chunk)] = classes.get(_class_of(chunk), 0) + 1
            # "more text stays" = the old output's visible characters are a subsequence
            it = iter(rev)
            if all(c in it for c in want.replace(" ", "")):
                more += 1
            else:
                other += 1
    print(f"crafted texts: {fuzz}; EXACT form differs: {exact}; REVIEW form differs: {review}")
    print(f"  REVIEW form: only more text stays in {more}; other text stays in {other}")
    for label, n in sorted(classes.items(), key=lambda kv: -kv[1]):
        print(f"  REVIEW form differs, class [{label}]: {n}")
    failures += exact

    # 3. time: the crafted worst cases (seconds)
    def timed(fn, arg) -> float:
        started = time.perf_counter()
        fn(arg)
        return time.perf_counter() - started

    def both(chunk: str) -> str:
        return drop_tags(drop_blocks(chunk))

    def old_both(chunk: str) -> str:
        return old_tags(old_blocks(chunk))

    keys = ["script", "ſcript", "scrİpt", "scrıpt", "ſcrİpt",
            "ſcrıpt", "style", "ſtyle"]  # fmt: skip
    cases = {
        "32,000 x '<script ' (256 KB)": "<script " * 32_000,
        "32,000 x '<a ' (96 KB)": "<a " * 32_000,
        "256 KB of '<'": "<" * 256_000,
        "8 opener names, no closing tag (256 KB)": "".join(f"<{k} " for k in keys) * 3_900,
        "2 MB of '<script '": "<script " * 250_000,
        "2 MB: 8 opener names": "".join(f"<{k} " for k in keys) * 31_000,
    }
    for label, chunk in cases.items():
        new_s = timed(both, chunk)
        small = len(chunk) <= 100_000
        old_s = timed(old_both, chunk) if small else None
        if old_s is None and len(chunk) <= 300_000:
            half = chunk[: len(chunk) // 4]  # the old form at a quarter of the size
            old_s = timed(old_both, half)
            note = f"old form at 1/4 size: {old_s:.2f} s (x16 at full size)"
        else:
            note = f"old form: {old_s:.2f} s" if old_s is not None else "old form: not run"
        same = "" if not small else f"; equal output: {old_both(chunk) == both(chunk)}"
        print(f"time [{label}]: new form {new_s:.3f} s; {note}{same}")
    return failures


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--bodies", type=int, default=8_000)
    ap.add_argument("--fuzz", type=int, default=200_000)
    args = ap.parse_args()
    bad = run(args.bodies, args.fuzz)
    print("RESULT:", "EXACT form equal on every input" if not bad else f"{bad} DIFFERENCES")
    sys.exit(1 if bad else 0)
