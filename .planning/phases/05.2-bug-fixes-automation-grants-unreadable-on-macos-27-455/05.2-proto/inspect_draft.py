"""Phase 05.2 / FIX-16 (#348): read ONE saved draft (.eml) and report what the device
probe must decide. Pure Python, no Mail, no native call: safe to run anywhere.

    uv run python -I inspect_draft.py DRAFT.eml MARKER [LAST_WORDS_OF_ORIGINAL]

MARKER is the probe text the script put in the draft (for example PROBE-P1).
LAST_WORDS_OF_ORIGINAL is a short unique phrase from the END of the original mail: its
presence proves the quote is not truncated.
"""

from __future__ import annotations

import email
import email.policy
import json
import re
import sys

_ATTRIBUTION = re.compile(r"On [^\n<]{3,40}?, at [^\n<]{3,12}?, .{1,120}? wrote:")


def _plain(markup: str) -> str:
    return re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style).*?</\1>", "", markup))


_BQ = re.compile(r"(?i)<(/?)blockquote\b")


def _in_blockquote(body: str, offset: int) -> bool:
    """True when ``offset`` lies inside a <blockquote> ... </blockquote> span (nesting
    counted)."""
    depth = 0
    for m in _BQ.finditer(body, 0, max(offset, 0)):
        depth += -1 if m.group(1) else 1
    return offset != -1 and depth > 0


def inspect(raw: bytes, marker: str, tail: str | None = None) -> dict:
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    html, text, images = "", "", []
    for part in msg.walk():
        kind = part.get_content_type()
        if kind == "text/html":
            html += part.get_content()
        elif kind == "text/plain":
            text += part.get_content()
        elif kind.startswith("image/"):
            images.append(
                [kind, part.get("Content-ID"), part.get_content_disposition()]
            )
    body = html or text
    low = body.lower()
    quote_at = low.find("<blockquote")  # -1 when the quote is plain text with "> "
    marker_at = body.find(marker)
    plain = _plain(body) if html else body
    attribution = _ATTRIBUTION.search(re.sub(r"\s+", " ", plain))
    # Mail's scripted-body wrapper: a div class plus a blockquote with the bar styled
    # away. One wrapper shows as both, so the count is the larger of the two.
    wrapper = max(
        body.count("Apple-Mail-URLShareWrapperClass"),
        body.count('<blockquote type="cite" style="border-left-style: none'),
    )
    lines = [ln.strip() for ln in text.splitlines()]
    first_line = next((ln for ln in lines if ln), None)
    return {
        "body_is_html": bool(html),
        "marker_at": marker_at,
        "blockquote_cite_at": quote_at,
        "marker_before_quote": marker_at != -1
        and (quote_at == -1 or marker_at < quote_at),
        "gt_prefixed_lines": len(re.findall(r"(?m)^> ", text)),
        "attribution_line": attribution.group(0) if attribution else None,
        "replacement_chars_U_FFFC": plain.count("￼"),
        "image_parts": images,
        "cid_references": re.findall(r"cid:([^\"' >]+)", html),
        "attachments_count": len(list(msg.iter_attachments())),
        "tail_present": None if tail is None else tail in re.sub(r"\s+", " ", plain),
        "body_chars": len(plain),
        "in_reply_to": msg.get("In-Reply-To"),
        "subject": msg.get("Subject"),
        "references": msg.get("References"),
        "wrapper_cite": wrapper,
        "marker_in_blockquote": bool(html) and _in_blockquote(body, marker_at),
        "text_plain_first_line": first_line,
        "text_plain_stray_i": first_line == "i",
        "text_plain_marker_quoted": any(
            ln.startswith(">") and marker in ln for ln in lines
        ),
        "text_plain_U_FFFC": text.count("\ufffc"),
    }


if __name__ == "__main__":
    path, marker, *rest = sys.argv[1:]
    with open(path, "rb") as f:
        print(
            json.dumps(inspect(f.read(), marker, rest[0] if rest else None), indent=2)
        )
