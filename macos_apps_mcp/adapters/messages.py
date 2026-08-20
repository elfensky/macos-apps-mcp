"""Messages adapter — read-only content via ``chat.db``, chat list via osascript.

Two backends by concern (the dual-backend pattern, #58):
- **Content** (search, history) reads ``~/Library/Messages/chat.db`` strictly
  read-only via ``runtime.read_via_sqlite``. Needs Full Disk Access; there is NO
  AppleScript content path, so missing FDA raises a typed error (never empty results).
- **Chat list** (``get_chats``) stays on osascript (Automation) — it needs no FDA.

Reverses v1's content scope-out (#21/#59). Sending stays unimplemented (the AppleScript
send handler is regressed since macOS 11). Reads return Pointers: ``id`` = message guid;
``summary`` = a sanitized ``[date] sender: snippet``; the full body is fetched by id via
the attributedBody decoder (a fast-follow — ``message.text`` is often NULL on modern
macOS). ``item_type=0`` + ``is_audio_message=0`` filter out non-message rows.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from ..contracts import Pointer
from ..runtime import mac_region, read_via_sqlite, run_osascript
from ..text import (
    STRIP_FRAMING,
    Field,
    blank_if_missing,
    clean_body,
    clean_summary,
    parse_framed,
)

MAX_CHATS = 30
MAX_MESSAGES = 40  # default cap on a content read
_HARD_CAP = 200  # ceiling even if a caller asks for more

CHAT_DB = Path.home() / "Library/Messages/chat.db"

# Only the tables/columns the queries below touch. ROWID is EXPLICIT in chat.db's schema
# (`ROWID INTEGER PRIMARY KEY`), so pragma_table_info lists it — the fixture declares it
# the same way. A macOS schema move trips SchemaDrift (no fallback → a loud error).
_FINGERPRINT = {
    "message": {
        "guid",
        "text",
        "attributedBody",  # modern body lives here (text is often NULL); also searched
        "date",
        "is_from_me",
        "item_type",
        "is_audio_message",
        "associated_message_type",  # 0 = a real message; 2000-3999 = tapback/reaction
        "handle_id",
    },
    "handle": {"ROWID", "id"},
}

# unix seconds at 2001-01-01T00:00:00Z — the Apple/Cocoa reference epoch.
_APPLE_EPOCH = 978307200
# Modern chat.db stores `date` in NANOSECONDS since the Apple epoch; pre-Yosemite stored
# SECONDS. A real seconds value (year ≤ ~2033) is ≪ 1e11; a real ns value (anytime after
# 2001-01-01 + ~100s) is ≫ 1e11 — so the threshold cleanly tells them apart.
_NS_THRESHOLD = 1e11

# EU-first calling codes for the locale-derived default; NOT exhaustive by design (full
# E.164 table or a phonenumbers dep is overkill for a fan-out heuristic). An unmapped
# region yields no international variant and the caller passes `country` explicitly. The
# default is the Mac's ACTUAL region — never a hardcoded +1 (US only if the Mac is US).
_CALLING_CODES = {
    "BE": "32", "NL": "31", "FR": "33", "DE": "49", "LU": "352", "GB": "44",
    "IE": "353", "ES": "34", "IT": "39", "PT": "351", "AT": "43", "CH": "41",
    "DK": "45", "SE": "46", "NO": "47", "FI": "358", "PL": "48", "CZ": "420",
    "GR": "30", "RO": "40", "HU": "36", "SK": "421", "BG": "359", "HR": "385",
    "SI": "386", "EE": "372", "LV": "371", "LT": "370", "US": "1", "CA": "1",
    "AU": "61", "NZ": "64", "IN": "91", "JP": "81",
}  # fmt: skip


# Common non-ISO region spellings a model/user is likely to type. ISO-3166 is "GB"/"US";
# "UK"/"USA" are everyday aliases — resolve them rather than silently returning None.
_REGION_ALIASES = {"UK": "GB", "USA": "US", "UAE": "AE", "EN": "GB"}


def _calling_code_for_region(region: str | None) -> str | None:
    if not region:
        return None
    r = region.upper()
    return _CALLING_CODES.get(_REGION_ALIASES.get(r, r))


def _resolve_calling_code(country: str | None) -> str | None:
    """A caller's `country` override → bare calling-code digits. Accepts a calling code
    (``'+32'`` / ``'32'``) or a region (``'BE'``, ``'UK'``, ``'USA'``); else None."""
    if not country:
        return None
    c = country.strip()
    if c.isalpha() and 2 <= len(c) <= 3:  # a region (incl. 3-letter aliases like USA)
        return _calling_code_for_region(c)
    digits = re.sub(r"\D", "", c)
    return digits or None


def _handle_variants(address: str, calling_code: str | None = None) -> list[str]:
    """Format variants of a phone/email to match ``handle.id`` (identity fan-out).

    One contact reaches you across many stored handle formats (E.164, national, bare
    digits). We generate the plausible set rather than guess one. A heuristic, not a
    parser (no phonenumbers dep) — an email is matched as-is (lowercased); a phone is
    tried as-typed, as bare digits, and — given a calling code — promoted national-to
    international (dropping a single leading trunk ``0``). Order-preserving, deduped.
    """
    a = address.strip()
    if not a:
        return []
    if "@" in a:
        return [a.lower()]
    variants: list[str] = []

    def add(v: str) -> None:
        if v and v not in variants:
            variants.append(v)

    add(a)  # exactly as typed
    digits = re.sub(r"\D", "", a)
    add(digits)
    if a.startswith("+") or a.startswith("00"):
        e164 = digits[2:] if a.startswith("00") else digits
        add("+" + e164)  # normalize to E.164
        # reverse fan-out: if it carries the known calling code, also try the national
        # forms a store might keep instead (E.164 → national). Fixes one-directionality.
        if calling_code and e164.startswith(calling_code):
            rest = e164[len(calling_code) :]
            add("0" + rest)  # national with a trunk 0 (BE, FR, …)
            add(rest)  # bare national (and IT, which keeps its 0 inside `rest`)
    elif calling_code:
        national = digits[1:] if digits.startswith("0") else digits
        add("+" + calling_code + national)  # drop trunk 0 (BE, FR, …)
        add(calling_code + national)
        # …but some countries KEEP the trunk 0 in E.164 (Italy): try that form too. A
        # superset is safe — a malformed variant just matches no real stored handle.
        add("+" + calling_code + digits)
        add(calling_code + digits)
    return variants


def _apple_date_to_dt(raw: int | None) -> datetime | None:
    """chat.db ``date`` (Apple epoch, ns on modern macOS / s on old) → naive local
    datetime — the codebase's canonical form (matches runtime.from_nsdate)."""
    if not raw:
        return None
    secs = raw / 1e9 if abs(raw) >= _NS_THRESHOLD else raw
    try:
        return datetime.fromtimestamp(secs + _APPLE_EPOCH)
    except (OverflowError, OSError, ValueError):
        # a corrupt/garbage date must not abort the whole read — one bad row → no stamp.
        return None


def _message_pointer(row) -> Pointer:
    """(guid, text, date, is_from_me, handle_id-address) row → a snippet Pointer."""
    guid, text, date, is_from_me, handle = row
    dt = _apple_date_to_dt(date)
    stamp = dt.strftime("%Y-%m-%d %H:%M") if dt else "?"
    who = "me" if is_from_me else (handle or "?")
    body = text if text else "(no preview — fetch the body by id)"
    deeplink = f"imessage://{handle}" if handle else ""
    return Pointer(
        id=guid, summary=clean_summary(f"[{stamp}] {who}: {body}"), deeplink=deeplink
    )


def _escape_like(term: str) -> str:
    r"""Escape LIKE wildcards so a user's ``%``/``_`` is literal (ESCAPE ``\``)."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _clamp(limit: int) -> int:
    return max(1, min(limit, _HARD_CAP))


# the legacy typedstream header (NOT bplist / NSKeyedArchiver)
_STREAMTYPED = b"streamtyped"


def _decode_attributed_body(blob: bytes | None) -> str | None:
    """Best-effort extract a message's text from a chat.db ``attributedBody`` blob.

    ``attributedBody`` is an ``NSMutableAttributedString`` in the legacy *typedstream*
    format (header ``streamtyped``), not NSKeyedArchiver/bplist. The backing string is
    the FIRST ``NSString`` instance (the class name literal appears once; later ones
    reference it by index), so: find ``NSString``, then the ``+`` (0x2b) type tag before
    the value, then a typedstream length — one byte, or ``0x81`` + little-endian uint16
    (``0x82`` + uint32 for very long) — then that many UTF-8 bytes.

    Returns ``None`` on anything unparseable (wrong format, no string, truncated). The
    caller prefers the ``text`` column and treats this as a fallback, so a mis-parse
    must NEVER fabricate a wrong body — it declines. Length is a byte count; non-ASCII
    is read as UTF-8 (errors replaced). ponytail: rich attribute runs are ignored — we
    want the plain text, not the styling; add an attribute parser only if one is needed.
    """
    if not isinstance(blob, (bytes, bytearray)) or _STREAMTYPED not in blob[:16]:
        return None  # None, a str, or a non-typedstream blob — decline, never crash
    marker = blob.find(b"NSString")
    if marker == -1:
        return None
    plus = blob.find(b"+", marker)  # 0x2b — the value's type tag after the class chain
    if plus == -1 or plus + 1 >= len(blob):
        return None
    i = plus + 1
    tag = blob[i]
    if tag == 0x81:  # 0x81 marker → length is the next 2 bytes (LE uint16)
        if i + 3 > len(blob):
            return None
        length, start = int.from_bytes(blob[i + 1 : i + 3], "little"), i + 3
    elif tag == 0x82:  # 0x82 marker → length is the next 4 bytes (LE uint32)
        if i + 5 > len(blob):
            return None
        length, start = int.from_bytes(blob[i + 1 : i + 5], "little"), i + 5
    elif tag <= 0x7F:  # a single signed-char length: only 0x00-0x7f are valid
        length, start = tag, i + 1
    else:  # 0x80 / 0x83-0xFF: negative/invalid length byte → decline, don't fabricate
        return None
    if start + length > len(blob):  # truncated → decline, don't mis-parse a fragment
        return None
    return blob[start : start + length].decode("utf-8", errors="replace")


# Real messages only: item_type=0 (not a group action), not an audio message, and
# associated_message_type=0 (exclude tapbacks/reactions/stickers, which are message rows
# too and would otherwise flood a LIMIT). Search matches `text` OR the `attributedBody`
# blob bytes — modern iMessages keep the body in attributedBody with text NULL, so a
# a text-only search silently under-reports (full decode is a fast-follow).
_MSG_FILTER = (
    "m.item_type = 0 AND m.is_audio_message = 0 AND m.associated_message_type = 0"
)

_SEARCH_SQL = f"""
    SELECT m.guid, m.text, m.date, m.is_from_me, h.id
    FROM message m
    LEFT JOIN handle h ON m.handle_id = h.ROWID
    WHERE {_MSG_FILTER}
      AND (m.text LIKE ? ESCAPE '\\' OR m.attributedBody LIKE ? ESCAPE '\\')
    ORDER BY m.date DESC
    LIMIT ?
"""

_WITH_SQL = f"""
    SELECT m.guid, m.text, m.date, m.is_from_me, h.id
    FROM message m
    JOIN handle h ON m.handle_id = h.ROWID
    WHERE h.id IN ({{placeholders}}) AND {_MSG_FILTER}
    ORDER BY m.date DESC
    LIMIT ?
"""

# get-by-id fetches an EXACT message the caller cited, so no item_type filtering.
_BODY_SQL = "SELECT text, attributedBody FROM message WHERE guid = ? LIMIT 1"

# with timeout (#56): bound the Apple Events so an orphaned osascript can't pin the app.
# US/RS-framed (#68); id and chat name pass through the shared STRIP_FRAMING handler.
_CHATS = (
    STRIP_FRAMING
    + """

with timeout of 120 seconds
tell application "Messages"
  set us to character id 31
  set rs to character id 30
  set out to ""
  repeat with c in chats
    set out to out & (my stripFraming(id of c)) & us & ¬
      (my stripFraming(name of c)) & rs
  end repeat
  return out
end tell
end timeout"""
)


def _parse(raw: str) -> list[Pointer]:
    """Parse the _CHATS payload: US/RS-framed (chat guid, name) records."""
    return [
        Pointer(id=r["id"], summary=clean_summary(r["name"]) or "(chat)", deeplink="")
        for r in parse_framed(
            raw, [Field("id"), Field("name", blank_if_missing)], min_fields=1
        )
    ]


class MessagesAdapter:
    def get_chats(self) -> list[Pointer]:
        """List Messages conversations (id + name) via osascript. No content, no FDA."""
        return _parse(run_osascript(_CHATS))[:MAX_CHATS]

    def search_messages(self, query: str, limit: int = MAX_MESSAGES) -> list[Pointer]:
        """Search message content (chat.db, read-only), newest first. Snippet Pointers.

        Matches both ``message.text`` and the ``attributedBody`` blob — modern iMessages
        store the body in attributedBody with text NULL, so a text-only search would
        silently miss them. The snippet is still ``text`` (placeholder when NULL) until
        the get-by-id body decoder (fast-follow) lands. Missing Full Disk Access → a
        typed FDA error (no content fallback exists)."""
        q = query.strip()
        if not q:
            raise ValueError("messages_search needs a search term (got an empty query)")
        like = f"%{_escape_like(q)}%"

        def read(conn):
            rows = conn.execute(_SEARCH_SQL, (like, like, _clamp(limit))).fetchall()
            return [_message_pointer(r) for r in rows]

        return read_via_sqlite(CHAT_DB, _FINGERPRINT, read)  # no fallback → FDA raises

    def messages_with(
        self, address: str, country: str | None = None, limit: int = MAX_MESSAGES
    ) -> list[Pointer]:
        """Recent messages with a person by phone/email (chat.db, read-only), newest
        first. Fans out handle format variants (`country` = calling code or region for a
        national number; default from the Mac's locale, never +1). Snippet Pointers;
        missing Full Disk Access raises a typed FDA error."""
        cc = (
            _resolve_calling_code(country)
            if country
            else _calling_code_for_region(mac_region())
        )
        variants = _handle_variants(address, cc)
        if not variants:
            raise ValueError("messages_with needs a phone number or email to match")
        sql = _WITH_SQL.format(placeholders=",".join("?" for _ in variants))

        def read(conn):
            rows = conn.execute(sql, (*variants, _clamp(limit))).fetchall()
            return [_message_pointer(r) for r in rows]

        return read_via_sqlite(CHAT_DB, _FINGERPRINT, read)  # no fallback → FDA raises

    def message_body(self, guid: str) -> str:
        """Full text of ONE message by id (chat.db, read-only), hygiene-budgeted.

        Prefers ``message.text``; when it is NULL (the modern norm) decodes the
        ``attributedBody`` typedstream. Returns "" for a message with no text (e.g. an
        attachment-only row, or an undecodable body). Missing Full Disk Access raises a
        typed FDA error. ``guid`` comes from messages_search / messages_with."""
        g = guid.strip()
        if not g:
            raise ValueError("message_body needs a message id (guid)")

        def read(conn):
            return conn.execute(_BODY_SQL, (g,)).fetchone()

        row = read_via_sqlite(CHAT_DB, _FINGERPRINT, read)  # no fallback → FDA raises
        if row is None:
            raise ValueError(f"no message with id {g!r}")
        text, blob = row
        body = text if text else _decode_attributed_body(blob)
        return clean_body(body or "")  # bounds size; OutputOverflow on a pasted dump
