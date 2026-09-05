"""Mail indexed read plane (#70): a read-only sqlite reader over Mail's Envelope Index
for header/subject/sender search at scale, plus a best-effort FTS5 body sidecar in our
own state dir. Pure/sqlite only — no EventKit, no Mail.app. The MailAdapter delegates
here; this module never launches Mail (read-at-rest)."""

from __future__ import annotations

import hashlib
import os
import platform
import sqlite3
from email import message_from_bytes
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote

from ..audit import state_dir
from ..contracts import Pointer
from ..errors import NativeError, SchemaDrift
from ..runtime import read_via_sqlite
from . import mail_ids, mailbox_url

# The Envelope Index tables + the exact columns we read/filter on. A macOS schema move
# that renames/drops any of these trips SchemaDrift → AppleScript fallback (never a
# mis-parsed Pointer). Mirrors notes._FINGERPRINT.
HEADER_FINGERPRINT: dict[str, set[str]] = {
    "messages": {
        "ROWID",
        "subject",
        "sender",
        "global_message_id",
        "mailbox",
        "date_received",
        "date_sent",
        "read",
        "flagged",
        "deleted",
        "conversation_id",
    },
    "subjects": {"ROWID", "subject"},
    "addresses": {"ROWID", "address", "comment"},
    "mailboxes": {"ROWID", "url"},
    "message_global_data": {"ROWID", "message_id_header"},
    "recipients": {"message", "address"},
    # conversation_id: Mail's own threading key (five dedicated indexes on it),
    # read by build_thread_query. attachments: backs has_attachments — an indexed
    # EXISTS, never a per-message AppleScript probe.
    "attachments": {"ROWID", "message", "name"},
}


def envelope_index_path() -> Path | None:
    """Newest ~/Library/Mail/V*/MailData/Envelope Index, or None if Mail data absent.
    V* moves between macOS versions; pick the highest-numbered MailData — NUMERICALLY:
    a lexicographic sort reads 'V10' < 'V9', and a Mac that kept an old V9 dir from
    before an OS upgrade would silently serve the stale index to every read."""

    def _version(p: Path) -> int:
        v = p.parts[-3][1:]  # ".../V10/MailData/Envelope Index" -> "10"
        return int(v) if v.isdigit() else -1

    roots = sorted(
        (Path.home() / "Library" / "Mail").glob("V*/MailData/Envelope Index"),
        key=_version,
    )
    return roots[-1] if roots else None


def mail_root() -> Path | None:
    """~/Library/Mail (the parent of the V* dirs), or None if it doesn't exist."""
    root = Path.home() / "Library" / "Mail"
    return root if root.exists() else None


def _deeplink(message_id: str) -> str:
    # message://%3C<id>%3E opens the message in Mail. The angle brackets are percent-
    # encoded (%3C/%3E) and the id itself is percent-encoded with safe='@' (an RFC822
    # message-id is local@domain, so '@' stays literal; spaces/other chars escaped) —
    # the patrickfreyer recipe (#61). Best-effort; verified on-device (integration).
    # Lives HERE (not mail.py) because row_to_pointer needs it: this was the one
    # mail_index -> mail edge, and it forced every mail.py index read into a lazy
    # import. mail.py re-exports it for its own Pointer builders.
    mid = message_id.strip().lstrip("<").rstrip(">")
    return f"message://%3C{quote(mid, safe='@')}%3E"


def account_of(url: str) -> str | None:
    """The account id embedded in a mailbox url — ``<scheme>://<UUID>/<path>`` (#155).

    The account is already inside the token every mail read returns, but that token is
    documented as opaque and a model must not be doing string surgery on it to answer
    "which inbox is this?". Lifting it into its own field costs no query and launches
    nothing; ``mail_overview`` reports the same id next to its display name, so one call
    gives the caller the whole map. (#175: the parse itself lives in mailbox_url.)"""
    return mailbox_url.account(url)


def row_to_pointer(row) -> Pointer | None:
    """Map one joined Envelope Index row → Pointer. None when the message has no RFC822
    Message-ID (no stable citation — same rule the adapter documents for header-less
    messages)."""
    mid = row["message_id_header"]
    if not mid or not str(mid).strip():
        return None
    url = row["mailbox_url"]
    return Pointer(
        id=str(mid),
        summary=row["subject"] or "",
        deeplink=_deeplink(str(mid)),
        folder=url,
        account=account_of(url),
    )


# Dedup (#75/#76/#77): a real mailbox stores the SAME RFC822 Message-ID in several
# mailboxes — device-verified, 36,112 non-deleted rows resolving to 22,223 distinct ids.
# Three causes, none fixable by cleaning up: Gmail shows one server message under both a
# label and All Mail, a migration leaves copies on two accounts, and every reply makes a
# Sent-plus-folder pair. Apple hit this too (mailboxes.unread_count_adjusted_for_
# duplicates). So one row per Message-ID, ranked: a live INBOX copy beats a filed copy,
# which beats an All Mail / Archive / Trash / Junk copy. Fixed literals, no user input —
# every *filter* value is still a bound param. The patterns and their hard-won anchoring
# rules (final-segment anchoring against 'Junkyard'/'Wallets/Old Mail' false matches,
# the Junk/Spam '%20' prefix for Exchange's `Junk%20E-mail`) live in mailbox_url (#175),
# the ONE table behind this rank, build_trash_query and dedupe's is_trash — which is
# what closed the Bin gap: a `Bin`-spelling trash used to rank as a FILED copy and beat
# an Archive copy for keeper and citation.
_MAILBOX_RANK = mailbox_url.rank_case("mb.url")

# The projected columns every deduped read returns; row_to_pointer consumes exactly
# these names. Shared with build_thread_query.
_DEDUP_SELECT_COLS = """gd.message_id_header AS message_id_header,
       s.subject            AS subject,
       mb.url               AS mailbox_url,
       m.date_received      AS date_received"""

_BASE_SQL = f"""
SELECT {_DEDUP_SELECT_COLS},
       ROW_NUMBER() OVER (PARTITION BY gd.message_id_header
                          ORDER BY {_MAILBOX_RANK}, m.date_received DESC, m.ROWID) AS rn
FROM messages m
JOIN subjects s ON s.ROWID = m.subject
LEFT JOIN addresses a ON a.ROWID = m.sender
JOIN mailboxes mb ON mb.ROWID = m.mailbox
JOIN message_global_data gd ON gd.ROWID = m.global_message_id
WHERE m.deleted = 0
  AND gd.message_id_header IS NOT NULL AND gd.message_id_header <> ''
"""

# has_attachments means "carries a real document". Mail counts inline signature and
# newsletter images as attachment rows, so a naive EXISTS is noise-dominated — on a real
# Mac 4,474 messages "have an attachment" while only 2,223 carry a document. Names with
# no extension count as documents: a false positive beats a silently dropped attachment.
_IMAGE_EXTS = (
    "png",
    "jpg",
    "jpeg",
    "gif",
    "webp",
    "heic",
    "bmp",
    "tiff",
    "tif",
    "svg",
    "ico",
)

_HAS_DOCUMENT_EXPR = (
    "EXISTS (SELECT 1 FROM attachments at WHERE at.message = m.ROWID"
    " AND (at.name IS NULL OR NOT ("
    + " OR ".join(f"lower(at.name) LIKE '%.{e}'" for e in _IMAGE_EXTS)
    + ")))"
)
_HAS_DOCUMENT = " AND " + _HAS_DOCUMENT_EXPR


def like_escape(value: str) -> str:
    r"""Escape LIKE metacharacters so a bound value matches LITERALLY.

    Binding a parameter stops injection; it does NOT stop ``%`` and ``_`` from being
    read as wildcards, so an un-escaped ``account='%'`` quietly matches every mailbox
    and returns a confidently wrong answer. Pair with ``ESCAPE '\'``.
    """
    return value.replace("\\", r"\\").replace("%", r"\%").replace("_", r"\_")


def build_header_query(
    *,
    subject=None,
    from_=None,
    to=None,
    mailbox_urls=None,
    since=None,
    until=None,
    unread=None,
    flagged=None,
    has_attachments=None,
    account=None,
    message_ids=None,
    limit=25,
):
    """Build (sql, params) for the header plane. All filters optional, ANDed; every
    value is a bound param (injection-safe). Newest-first, deleted excluded.
    `has_attachments` means a real document (images excluded); `account` matches the
    account segment of the mailbox url (<scheme>://<UUID>/<path>) — exactly, not as a
    substring of the path. `mailbox_urls` are RESOLVED raw urls matched with exact
    IN, never a LIKE over the encoded url (#144): name→url resolution cannot happen
    in SQL (no urldecode), so it lives in the adapter's _resolve_mailbox."""
    # Every LIKE filter escapes its value: a bound param stops injection, not '%'/'_'
    # being read as wildcards — subject='50% off' matched '50 anything off', and
    # mailbox='_' matched every mailbox (the exact failure like_escape documents).
    sql = _BASE_SQL
    params: list = []
    if subject:
        sql += r" AND s.subject LIKE ? ESCAPE '\'"
        params.append(f"%{like_escape(subject)}%")
    if from_:
        sql += r" AND (a.address LIKE ? ESCAPE '\' OR a.comment LIKE ? ESCAPE '\')"
        params += [f"%{like_escape(from_)}%", f"%{like_escape(from_)}%"]
    if to:
        sql += (
            " AND EXISTS (SELECT 1 FROM recipients r JOIN addresses ra"
            " ON ra.ROWID = r.address WHERE r.message = m.ROWID"
            r" AND ra.address LIKE ? ESCAPE '\')"
        )
        params.append(f"%{like_escape(to)}%")
    if mailbox_urls:
        placeholders = ",".join("?" for _ in mailbox_urls)
        sql += f" AND mb.url IN ({placeholders})"
        params += list(mailbox_urls)
    if since is not None:
        sql += " AND m.date_received >= ?"
        params.append(since)
    if until is not None:
        sql += " AND m.date_received <= ?"
        params.append(until)
    if unread:
        sql += " AND m.read = 0"
    if flagged:
        sql += " AND m.flagged = 1"
    if has_attachments:
        sql += _HAS_DOCUMENT
    if account:
        # Anchored to the ACCOUNT SEGMENT of mailboxes.url (<scheme>://<UUID>/<path>),
        # not a substring of the whole url: an unanchored '%value%' also matches any
        # mailbox whose PATH contains the text, under any account, and reports it as
        # though the account filter worked. The trailing '/' is appended to mb.url so
        # an account-root mailbox with no path still matches. LIKE metacharacters in
        # the value are escaped for the same honesty reason — account='%' must match
        # one account, not every mailbox (it is a bound param, so never injection).
        sql += r" AND mb.url || '/' LIKE '%://' || ? || '/%' ESCAPE '\'"
        params.append(like_escape(account))
    if message_ids:
        placeholders = ",".join("?" for _ in message_ids)
        sql += f" AND gd.message_id_header IN ({placeholders})"
        params += list(message_ids)
    # Dedup and LIMIT wrap the filtered set: rank inside, pick rn = 1, then LIMIT — so
    # LIMIT counts distinct messages, not rows that collapse afterwards.
    sql = (
        f"SELECT message_id_header, subject, mailbox_url, date_received FROM ({sql})"
        " WHERE rn = 1 ORDER BY date_received DESC LIMIT ?"
    )
    params.append(limit)
    return sql, params


def build_thread_query(message_id: str, limit: int):
    """Build (sql, params) for one conversation, addressed by any member's Message-ID.

    Threads on messages.conversation_id — Mail's own threading key, which carries
    five dedicated indexes, so matching References/In-Reply-To by hand would be
    redundant work on top of an answer Mail already computed. Deduped by the same
    rule as search, and ordered OLDEST-first: a thread reads as a transcript.
    Truncation keeps the NEWEST ``limit`` messages (the old end is the end to drop
    when the point is to reply), then re-sorts ascending for the caller.

    The seed matches EVERY conversation the Message-ID belongs to, not one of them:
    the premise of this module is that one Message-ID has several rows, and a
    cross-account copy can carry a DIFFERENT conversation_id, so a `= (SELECT …
    LIMIT 1)` seed silently drops the other branch — and picks a deleted copy just as
    happily. Which one won was up to SQLite's query plan and could flip on an OS
    upgrade. Deleted copies are excluded from the seed for the same reason.

    ``sort_date`` guards a date_sent of 0 (not just NULL): a zero sorts to the very
    front of an oldest-first transcript and would be the first message dropped under
    truncation.
    """
    sql = f"""
SELECT message_id_header, subject, mailbox_url, date_received FROM (
  SELECT message_id_header, subject, mailbox_url, date_received, sort_date FROM (
    SELECT {_DEDUP_SELECT_COLS},
           COALESCE(NULLIF(m.date_sent, 0), m.date_received) AS sort_date,
           ROW_NUMBER() OVER (PARTITION BY gd.message_id_header
                              ORDER BY {_MAILBOX_RANK},
                                       m.date_received DESC, m.ROWID) AS rn
    FROM messages m
    JOIN subjects s ON s.ROWID = m.subject
    JOIN mailboxes mb ON mb.ROWID = m.mailbox
    JOIN message_global_data gd ON gd.ROWID = m.global_message_id
    WHERE m.deleted = 0
      AND gd.message_id_header IS NOT NULL AND gd.message_id_header <> ''
      AND m.conversation_id IN (
            SELECT m2.conversation_id FROM messages m2
            JOIN message_global_data gd2 ON gd2.ROWID = m2.global_message_id
            WHERE gd2.message_id_header = ? AND m2.deleted = 0)
  ) WHERE rn = 1
  ORDER BY sort_date DESC
  LIMIT ?
) ORDER BY sort_date ASC
"""
    return sql, [message_id, limit]


def build_message_location_query(stored_ids):
    """Build (sql, params) for "where does each of these Message-IDs physically live?"
    — ``(message_id, rowid, mailbox_url)`` per ROW, deliberately NOT deduped (#159).

    The one query the recoverable plane needs and no other read wants. Every other read
    here collapses a Message-ID to its best-ranked copy, because a citation names one
    message; a BACKUP names one file, and the file is keyed by ``messages.ROWID`` —
    device-verified 2026-08-03: a message's ``.emlx`` is named by its ROWID, and across
    36,417 files on a real Mac no two rows shared one. So the plane needs every row, and
    picks the one whose mailbox matches the target it is about to act on.

    ``stored_ids`` are BRACKETED (``mail_addressing.stored_id``) — the form the index
    stores. Deleted rows are excluded: a row Mail has already tombstoned has no file
    worth preserving.
    """
    placeholders = ",".join("?" for _ in stored_ids)
    sql = f"""
SELECT gd.message_id_header AS message_id,
       m.ROWID              AS rowid,
       mb.url               AS mailbox_url
FROM messages m
JOIN mailboxes mb ON mb.ROWID = m.mailbox
JOIN message_global_data gd ON gd.ROWID = m.global_message_id
WHERE m.deleted = 0 AND gd.message_id_header IN ({placeholders})
"""
    return sql, list(stored_ids)


# --- duplicates (#140/#153) ----------------------------------------------------------
# The dedup KEY, shared by every query below and identical to build_overview_query's:
# a message with no RFC822 Message-ID keys on its own ROWID, so 26 header-less rows on
# this store stay 26 distinct messages instead of collapsing into one (#142). That makes
# them structurally un-deduplicable, which is correct — AppleScript addresses a message
# BY Message-ID, so a row without one cannot be targeted at all. The report and the CLI
# therefore agree by construction: what cannot be counted as redundant cannot be
# deleted.
_DUP_KEY = "COALESCE(NULLIF(gd.message_id_header, ''), 'rowid:' || m.ROWID)"

# Rows a dedupe may consider: present, and addressable by Message-ID. Deleted rows are
# already tombstoned and header-less rows have no handle.
_DUP_WHERE = """m.deleted = 0
  AND gd.message_id_header IS NOT NULL AND gd.message_id_header <> ''"""


def build_duplicate_summary_query():
    """Build (sql, params) for the per-mailbox SAME-MAILBOX redundancy table (#140) —
    ``(mailbox_url, total, distinct_, redundant)``, worst first, mailboxes with no
    redundancy omitted.

    This is the table the issue asks a dry run to reproduce, and it is deliberately the
    same arithmetic ``build_overview_query`` uses for its counts — ``total`` here is the
    RAW row count and ``distinct_`` is what ``mail_overview`` reports, so the two tools
    can be read side by side and their difference IS ``redundant``. Measured on this
    store 2026-08-05: 9,879 redundant rows, matching the issue's re-measurement.
    """
    sql = f"""
SELECT mb.url                     AS mailbox_url,
       COUNT(*)                   AS total,
       COUNT(DISTINCT {_DUP_KEY}) AS distinct_,
       COUNT(*) - COUNT(DISTINCT {_DUP_KEY}) AS redundant
FROM messages m
JOIN mailboxes mb ON mb.ROWID = m.mailbox
LEFT JOIN message_global_data gd ON gd.ROWID = m.global_message_id
WHERE m.deleted = 0
GROUP BY mb.ROWID
HAVING redundant > 0
ORDER BY redundant DESC, mailbox_url ASC
"""
    return sql, []


def build_duplicate_offenders_query(limit: int):
    """Build (sql, params) for the worst individual duplicate SETS — one row per
    ``(mailbox, Message-ID)`` that has more than one copy, most copies first. The
    "which messages are actually doing this?" half of the report, next to the
    per-mailbox totals."""
    sql = f"""
SELECT mb.url                AS mailbox_url,
       gd.message_id_header  AS message_id,
       s.subject             AS subject,
       COUNT(*)              AS copies
FROM messages m
JOIN mailboxes mb ON mb.ROWID = m.mailbox
JOIN message_global_data gd ON gd.ROWID = m.global_message_id
LEFT JOIN subjects s ON s.ROWID = m.subject
WHERE {_DUP_WHERE}
GROUP BY mb.ROWID, gd.message_id_header
HAVING copies > 1
ORDER BY copies DESC, mailbox_url ASC
LIMIT ?
"""
    return sql, [limit]


def build_duplicate_rows_query(mailbox_url: str):
    """Build (sql, params) for one mailbox's duplicate sets, every row (#140) —
    ``(message_id, rowid, size, date_sent, subject)`` ordered by set then ROWID, so the
    CLI's winner (LOWEST ROWID) is simply the first row of each group.

    ``size`` and ``date_sent`` ride along because the CLI refuses to delete on a
    matching Message-ID alone: a loser must be byte-identical to the winner on both,
    or it is left alone and reported. A Message-ID is a claim about identity; two rows
    of different sizes are not the same bytes whatever the header says.
    """
    sql = f"""
SELECT gd.message_id_header AS message_id,
       m.ROWID              AS rowid,
       m.size               AS size,
       m.date_sent          AS date_sent,
       s.subject            AS subject
FROM messages m
JOIN mailboxes mb ON mb.ROWID = m.mailbox
JOIN message_global_data gd ON gd.ROWID = m.global_message_id
LEFT JOIN subjects s ON s.ROWID = m.subject
WHERE {_DUP_WHERE} AND mb.url = ?
  AND gd.message_id_header IN (
      SELECT gd2.message_id_header
      FROM messages m2
      JOIN message_global_data gd2 ON gd2.ROWID = m2.global_message_id
      WHERE m2.mailbox = mb.ROWID AND m2.deleted = 0
        AND gd2.message_id_header IS NOT NULL AND gd2.message_id_header <> ''
      GROUP BY gd2.message_id_header
      HAVING COUNT(*) > 1)
ORDER BY gd.message_id_header ASC, m.ROWID ASC
"""
    return sql, [mailbox_url]


def build_cross_account_summary_query():
    """Build (sql, params) for CROSS-ACCOUNT redundancy (#153) — one row per account
    pair-free summary: ``(account, copies)`` counting rows whose Message-ID also exists
    under a DIFFERENT account.

    Deliberately not a "which account should win" ranking. #153 settled that the winner
    is a human decision (``--keep-account``) and that no heuristic ever picks it, so
    this reports the size of the problem per account and stops there.
    """
    sql = """
SELECT substr(mb.url, instr(mb.url, '://') + 3,
              instr(substr(mb.url, instr(mb.url, '://') + 3), '/') - 1) AS account,
       COUNT(*) AS copies
FROM messages m
JOIN mailboxes mb ON mb.ROWID = m.mailbox
JOIN message_global_data gd ON gd.ROWID = m.global_message_id
WHERE m.deleted = 0
  AND gd.message_id_header IS NOT NULL AND gd.message_id_header <> ''
  AND gd.message_id_header IN (
      SELECT gd2.message_id_header
      FROM messages m2
      JOIN mailboxes mb2 ON mb2.ROWID = m2.mailbox
      JOIN message_global_data gd2 ON gd2.ROWID = m2.global_message_id
      WHERE m2.deleted = 0
        AND gd2.message_id_header IS NOT NULL AND gd2.message_id_header <> ''
      GROUP BY gd2.message_id_header
      HAVING COUNT(DISTINCT substr(mb2.url, 1,
             instr(mb2.url, '://') + 2 +
             instr(substr(mb2.url, instr(mb2.url, '://') + 3), '/'))) > 1)
GROUP BY account
ORDER BY copies DESC
"""
    return sql, []


def build_cross_account_rows_query():
    """Build (sql, params) for EVERY row of every cross-account duplicate set (#153) —
    ``(message_id, rowid, mailbox_url, account)``, one row per physical copy.

    The summary above counts the problem; this one is what a cleanup acts on, and the
    difference matters. Cross-account copies live in DIFFERENT mailboxes under DIFFERENT
    accounts, so the caller has to address each loser's own mailbox by url — there is no
    "keep item 1 of this mailbox's matches" to lean on the way #140 does. ``rowid`` is
    the ``<n>`` in ``<n>.emlx``, which is how the body-identity gate reaches each copy's
    bytes without asking Mail anything.

    Deliberately NOT filtered to a keeper: which account wins is the caller's
    (human's) decision, and a query that pre-selected losers would be making it.
    """
    sql = """
SELECT gd.message_id_header AS message_id,
       m.ROWID              AS rowid,
       mb.url               AS mailbox_url,
       substr(mb.url, instr(mb.url, '://') + 3,
              instr(substr(mb.url, instr(mb.url, '://') + 3), '/') - 1) AS account
FROM messages m
JOIN mailboxes mb ON mb.ROWID = m.mailbox
JOIN message_global_data gd ON gd.ROWID = m.global_message_id
WHERE m.deleted = 0
  AND gd.message_id_header IS NOT NULL AND gd.message_id_header <> ''
  AND gd.message_id_header IN (
      SELECT gd2.message_id_header
      FROM messages m2
      JOIN mailboxes mb2 ON mb2.ROWID = m2.mailbox
      JOIN message_global_data gd2 ON gd2.ROWID = m2.global_message_id
      WHERE m2.deleted = 0
        AND gd2.message_id_header IS NOT NULL AND gd2.message_id_header <> ''
      GROUP BY gd2.message_id_header
      HAVING COUNT(DISTINCT substr(mb2.url, 1,
             instr(mb2.url, '://') + 2 +
             instr(substr(mb2.url, instr(mb2.url, '://') + 3), '/'))) > 1)
ORDER BY message_id
"""
    return sql, []


# The mailbox names a "Trash" is spelled with, per account type — device-verified
# 2026-08-05 on four accounts. Sourced from mailbox_url's one table (#175), same
# vocabulary as _MAILBOX_RANK's demotions and dedupe's is_trash.
_TRASH_SUFFIXES = mailbox_url.TRASH_SUFFIXES


def build_trash_query(account: str):
    """Build (sql, params) for "which mailbox is this account's Trash?" (#80).

    Needed because Mail will not answer it. ``Mail.sdef`` declares ``trash mailbox`` on
    the ACCOUNT class next to ``drafts mailbox``/``sent mailbox``, but device-verified
    2026-08-05 it raises **-1728 for every account**; only the application-level
    ``trash mailbox`` resolves, and that is the UNIFIED "All Trash". The unified
    accessor is not a substitute: a `move` OUT of it moved the messages and then crashed
    Mail (facts doc §5c), so `trash_mail`'s undo has to name the account's own Trash.

    Ordered so the shortest url wins — a nested user folder like `Trash/2019` would
    match `%/Trash`'s sibling patterns on some stores, and the account's real Trash is
    always the shallowest of them.
    """
    clauses = " OR ".join("url LIKE ? ESCAPE '\\'" for _ in _TRASH_SUFFIXES)
    sql = f"""
SELECT url FROM mailboxes
WHERE url LIKE ? ESCAPE '\\' AND ({clauses})
ORDER BY length(url) ASC LIMIT 1
"""
    return sql, [f"%://{like_escape(account)}/%", *_TRASH_SUFFIXES]


# Sent-role spellings, one per account type — same one-table sourcing as
# _TRASH_SUFFIXES (#175), consumed by the awaiting-reply index plane (#192).
_SENT_SUFFIXES = mailbox_url.SENT_SUFFIXES


def build_sent_triage_query(limit: int):
    """Build (sql, params) for the awaiting-reply sent scan (#192) — the index-plane
    replacement for the AppleScript ``_SENT_TRIAGE`` + ``_INBOX_REFS`` pair, which
    was high-variance O(store) against Mail's unified All Sent (measured 209s idle,
    >600s busy, on a 13k-message store; this query answers in ~0.3s at rest).

    One row per DISTINCT sent message (same dedupe rule as every count here),
    newest-first, capped. ``answered`` uses Mail's own References graph:
    ``message_references.reference`` stores the CITED message's ``messages.message_id``
    integer (device-verified 2026-08-20 against a live reply), and the citing message
    is required to sit in an ``%/INBOX`` mailbox — the exact semantics the AppleScript
    scan had (unified inbox only), which is also what keeps a reply DRAFT (it cites
    the original too, from Drafts) from clearing a send prematurely.

    ``MIN(COALESCE(m.subject_prefix,'') || s.subject)``: subjects.subject stores the
    stripped subject and the "Re: "/"Fwd: " lives in subject_prefix — concatenated so
    the record reads like AppleScript's ``subject of m`` did."""
    clauses = " OR ".join("mb.url LIKE ? ESCAPE '\\'" for _ in _SENT_SUFFIXES)
    sql = f"""
WITH sent AS (
  SELECT m.message_id AS mid_int,
         MIN(m.ROWID) AS rowid,
         MIN(g.message_id_header) AS mid,
         MIN(COALESCE(m.subject_prefix, '') || s.subject) AS subject,
         MAX(m.date_sent) AS date_sent
  FROM messages m
  JOIN mailboxes mb ON mb.ROWID = m.mailbox
  JOIN subjects s ON s.ROWID = m.subject
  LEFT JOIN message_global_data g ON g.message_id = m.message_id
  WHERE m.deleted = 0 AND m.message_id != 0 AND ({clauses})
  GROUP BY m.message_id
  ORDER BY date_sent DESC LIMIT ?
)
SELECT mid, subject, date_sent, rowid,
  EXISTS (
    SELECT 1 FROM message_references r
    JOIN messages cm ON cm.ROWID = r.message
    JOIN mailboxes cmb ON cmb.ROWID = cm.mailbox
    WHERE r.reference = sent.mid_int AND cm.deleted = 0
      AND cmb.url LIKE '%/INBOX'
  ) AS answered
FROM sent ORDER BY date_sent DESC
"""
    return sql, [*_SENT_SUFFIXES, limit]


def build_sent_recipients_query(rowids):
    """Build (sql, params) hydrating To-addresses for ``build_sent_triage_query``'s
    representative rowids. ``type = 0`` is the To list (probed 2026-08-20 against a
    known single-recipient send); position keeps Mail's own ordering."""
    placeholders = ",".join("?" for _ in rowids)
    sql = f"""
SELECT r.message AS rowid, a.address
FROM recipients r JOIN addresses a ON a.ROWID = r.address
WHERE r.type = 0 AND r.message IN ({placeholders})
ORDER BY r.message, r.position
"""
    return sql, list(rowids)


def build_local_account_query():
    """Build (sql, params) that finds the account segment mailboxes.url embeds for the
    On My Mac store — the value ``build_header_query``'s ``account`` clause anchors on
    for a ``local://`` mailbox (``<scheme>://<UUID>/<path>``, same shape as an
    ``imap://`` account). AppleScript's `every account` never lists this store (see
    ``mail.overview``'s docstring), so it has no name to resolve from Mail — this is
    read straight from the same Envelope Index the account filter itself queries,
    which guarantees the two agree. Every ``local://`` mailbox on a device shares the
    same account segment, so the first row is enough; no rows means no On My Mac
    store in this index."""
    return "SELECT url FROM mailboxes WHERE url LIKE 'local://%' LIMIT 1", []


def build_stats_query(since: int, account: str | None = None):
    """Build (sql, params) for #85: one narrow row per DISTINCT message in the window.

    Deduped, like every other count here. Raw rows overcount by up to 3.6x on this Mac
    (Travel: 4,423 rows, 1,252 distinct), so statistics computed over rows would be
    wrong by exactly the margin ``mail_overview`` was fixed for — same
    ``COALESCE(NULLIF(message_id_header,''), 'rowid:'||ROWID)`` key, so the two reads
    cannot disagree.

    Rows, not aggregates: the window is bounded by ``since``, the row is six narrow
    columns, and the totals/top-N are a ``Counter`` pass in Python. One SQL statement
    beats four near-identical GROUP BYs, and the caller keeps the freedom to add a
    breakdown without a new query.

    The per-message FLAGS are aggregated over the whole duplicate group, not read off
    whichever row won the dedup: unread iff EVERY copy is unread (``MIN``), flagged or
    carrying-a-document iff ANY copy is (``MAX``). That is exactly what
    ``build_overview_query`` counts, and it is not a detail — device-verified
    2026-08-05 on a 30-day window, taking the winning row's own ``read`` reported 449
    unread where ``mail_overview``'s rule reports 451. Two tools reading one store must
    not disagree about it. The sender/mailbox columns still come from the winning row,
    because those are properties of a copy and there is nothing to aggregate.

    ponytail: no LIMIT — a "last 3650 days" call materialises the whole store (~36k
    six-column rows, a few MB). Add a cap if a caller ever asks for that AND it bites;
    a bounded window is the normal use and the honest one.
    """
    key = "COALESCE(NULLIF(gd.message_id_header, ''), 'rowid:' || m.ROWID)"
    inner = f"""
SELECT lower(COALESCE(a.address, ''))            AS sender,
       mb.url                                    AS mailbox_url,
       MIN(m.read) OVER (PARTITION BY {key})     AS is_read,
       MAX(m.flagged) OVER (PARTITION BY {key})  AS flagged,
       MAX(CASE WHEN {_HAS_DOCUMENT_EXPR} THEN 1 ELSE 0 END)
           OVER (PARTITION BY {key})             AS has_document,
       m.date_received                           AS date_received,
       ROW_NUMBER() OVER (PARTITION BY {key}
                          ORDER BY m.date_received DESC, m.ROWID) AS rn
FROM messages m
LEFT JOIN addresses a ON a.ROWID = m.sender
JOIN mailboxes mb ON mb.ROWID = m.mailbox
LEFT JOIN message_global_data gd ON gd.ROWID = m.global_message_id
WHERE m.deleted = 0 AND m.date_received >= ?
"""
    params: list = [since]
    if account:
        # anchored to the ACCOUNT SEGMENT of the url, exactly as build_header_query
        # does — an unanchored match also catches any mailbox whose PATH contains it.
        inner += r" AND mb.url || '/' LIKE '%://' || ? || '/%' ESCAPE '\'"
        params.append(like_escape(account))
    sql = (
        "SELECT sender, mailbox_url, is_read, flagged, has_document, date_received"
        f" FROM ({inner}) WHERE rn = 1"
    )
    return sql, params


def build_overview_query():
    """Build (sql, params) for per-mailbox totals and unread counts.

    Counts are computed LIVE rather than read from mailboxes.unread_count: that column
    is trigger-maintained and device-verified stale — on a real Mac the Gmail INBOX row
    reports 1 unread where a live count returns 0, and
    unread_count_adjusted_for_duplicates carries the same wrong value. A live count over
    36k rows measured 16 ms, backed by the partial index on (read = 0 AND deleted = 0).

    Counted per DISTINCT Message-ID, not per row. A raw COUNT(m.ROWID) is inflated by
    the same duplication the search plane dedups — device-verified against a 36k store,
    Travel reported 4,423 against a true 1,241 (3.6x), Expense 3,535 against 1,127,
    Investing 2,611 against 410. This is same-mailbox dedup, so it needs no mailbox
    rank; the rows collapse inside one GROUP BY. A message with no RFC822 Message-ID
    still counts (keyed on its ROWID) — it has no citation, but it is genuinely in the
    mailbox, and a count that silently omits it is the same class of lie.

    Mailboxes with no messages are included via the LEFT JOINs (both of them — the
    message_global_data join must not turn the outer join inner), so a newly-created
    folder shows as 0/0 rather than vanishing.
    """
    # One expression, used twice: the dedup key. COUNT(DISTINCT …) ignores NULLs, so
    # the unread count is the same key wrapped in a CASE with no ELSE.
    key = "COALESCE(NULLIF(gd.message_id_header, ''), 'rowid:' || m.ROWID)"
    sql = f"""
SELECT mb.url                                       AS mailbox_url,
       COUNT(DISTINCT {key})                        AS total,
       COUNT(DISTINCT CASE WHEN m.read = 0 THEN {key} END) AS unread
FROM mailboxes mb
LEFT JOIN messages m ON m.mailbox = mb.ROWID AND m.deleted = 0
LEFT JOIN message_global_data gd ON gd.ROWID = m.global_message_id
GROUP BY mb.ROWID
ORDER BY unread DESC, mailbox_url ASC
"""
    return sql, []


# --- the one sqlite entry per read shape (C1) ----------------------------------------
# Everything below is the ONLY place adapter code reaches the Envelope Index: path
# resolution, the missing-store error, the schema fingerprint and the read_via_sqlite
# wiring each live here exactly once. Policy stays with the caller — mail.py still
# decides WHEN an AppleScript fallback is honest and passes it through as an opaque
# callable; this module never learns AppleScript semantics.

_NO_MAIL_DATA = (
    "no Mail data found (~/Library/Mail/V*/MailData/Envelope Index). "
    "Open Mail once to create it. Do not retry."
)


def require_index_path() -> Path:
    """``envelope_index_path()`` or the one followable missing-store error.

    PUBLIC (#161): ``mail.search`` has to raise this before consulting the FTS sidecar
    — body= with no Envelope Index is a followable error, not a silent empty — so the
    call was reaching through the underscore into another module's private seam. It is
    part of this module's interface, not an accident of it; the name now says so.

    Late-binds the path lookup deliberately: tests monkeypatch
    ``envelope_index_path`` as a module attribute, and that seam must keep
    resolving at call time."""
    path = envelope_index_path()
    if path is None:
        raise NativeError(_NO_MAIL_DATA)
    return path


# The first macOS whose Envelope Index stores the RFC822 Message-ID: Apple added
# message_global_data.message_id_header in macOS 26 (Tahoe) by ALTER TABLE migration.
# Device-verified absent on 15.6.1 and 15.7.9 (#199) — not drift, a platform floor.
_MACOS_FLOOR = 26

# Terse on purpose: this rides inside every doctor report on an affected machine,
# and the whole report has a hard context budget (test_report_stays_under_token_
# budget) — trim here before trimming anything else.
_FLOOR_MESSAGE = (
    "Mail's Envelope Index on this macOS ({ver}) does not store the RFC822 "
    "Message-ID: message_global_data.message_id_header was added in macOS 26 "
    "(Tahoe); macOS 15 (Sequoia) and earlier never had it (#199). Without it the "
    "sqlite mail reads (mail_overview, mail_stats, mail_thread, filtered "
    "mail_search, ...) cannot answer, and only they emit the folder urls "
    "trash_mail/move_mail need — a platform floor, not schema drift; do not "
    "update the fingerprint. The fix: run mail_index_ids once to build the "
    "Message-ID sidecar from the .emlx files on disk (#201); the sqlite plane "
    "then works. Do not retry before that build has run."
)


def _specialize_drift(e: SchemaDrift) -> SchemaDrift:
    """#199: the one KNOWN drift — message_id_header missing on a pre-Tahoe macOS —
    gets the platform-floor diagnosis instead of the generic "macOS likely changed
    the schema", which sent readers hunting in the wrong direction (the fingerprint
    was never stale; the machine is below the floor). Any other drift, and this
    same condition on macOS 26+, keep the generic message: there it really is
    drift, and the fingerprint really is the thing to update."""
    if "message_id_header" not in str(e):
        return e
    major = platform.mac_ver()[0].split(".")[0]
    if not major.isdigit() or int(major) >= _MACOS_FLOOR:
        return e
    floor = SchemaDrift(_FLOOR_MESSAGE.format(ver=platform.mac_ver()[0]))
    # Marked so callers (doctor's sidecar state) can tell THIS diagnosis from any
    # other drift without string-matching the prose.
    floor.platform_floor = True
    return floor


# --- store mode (#201): native column, sidecar shadow, or the #199 floor -------------

# Cache key is (index path, sidecar-file-exists): the second half is what lets a
# machine flip floor → sidecar the moment mail_index_ids finishes, with no process
# restart — and a Tahoe store never re-probes just because a sidecar appeared.
_MODE_CACHE: dict[tuple[str, bool], str] = {}

# How many not-yet-harvested rows a READ will absorb inline before it stops paying
# and reports staleness instead (~0.3 s for a small batch on a 2012 spinning disk;
# past this, the build is mail_index_ids' job — a read must stay a read).
_TOPUP_MAX_ROWS = 200

# The last sidecar-mode read's staleness finding, if any — popped by the adapter via
# take_staleness_note() right after its query returns. A module slot, not a return
# value, because the note is born inside the connection-setup hook where no result
# channel exists; the single native worker serializes the writers, and a mis-paired
# pop across two concurrent mail reads would still attach a TRUE statement (the
# staleness is a property of the store, not of one query).
_STALENESS_NOTE: str | None = None


def take_staleness_note() -> str | None:
    """Pop the staleness note the last sidecar-mode read left (None when fresh)."""
    global _STALENESS_NOTE
    note, _STALENESS_NOTE = _STALENESS_NOTE, None
    return note


def _index_mode(path) -> str:
    """``"native"`` | ``"sidecar"`` | ``"floor"`` for this Envelope Index, cached.

    native: the store has message_id_header — Tahoe+; zero new behavior.
    sidecar: pre-floor macOS, column absent, a built sidecar exists — reads get the
    attach-and-shadow hook. floor: no hook; the fingerprint check raises the #199
    floor message (now carrying the mail_index_ids remediation). Column absent on
    macOS 26+ is REAL drift, not a mode — a sidecar must never mask it, so it also
    resolves "floor" and the generic drift message surfaces."""
    key = (str(path), mail_ids.sidecar_path().exists())
    mode = _MODE_CACHE.get(key)
    if mode is None:
        mode = _detect_mode(path)
        _MODE_CACHE[key] = mode
    return mode


def _detect_mode(path) -> str:
    def probe(conn):
        # Schema-qualified against main. so the probe can NEVER be answered by the
        # shadow view (which satisfies the unqualified pragma by design).
        cols = {
            r[0].lower()
            for r in conn.execute(
                "SELECT name FROM pragma_table_info('message_global_data', 'main')"
            )
        }
        return "message_id_header" in cols

    if read_via_sqlite(path, {}, probe, immutable=False):
        return "native"
    major = platform.mac_ver()[0].split(".")[0]
    # The sidecar stat runs AFTER the probe on purpose: existence is re-checked at
    # the last moment so a sidecar that appeared while this detection was running
    # (a just-finished mail_index_ids) is honored, never floored.
    if (
        major.isdigit()
        and int(major) < _MACOS_FLOOR
        and mail_ids.sidecar_path().exists()
    ):
        return "sidecar"
    return "floor"


# The shadow (#201, spike-verified): SQLite resolves unqualified names temp-first,
# so this view stands in for Sequoia's column-less message_global_data in every
# existing query AND in the unqualified pragma_table_info the fingerprint check
# runs — zero SQL-builder changes, zero fingerprint variants. It joins back to the
# REAL table (rather than projecting the sidecar alone) so the columns the plane
# reads beyond the missing one — message_id, which the #192 sent-triage query joins
# on — stay served from Mail's own data; only message_id_header comes from ours.
_SHADOW_VIEW_SQL = """
CREATE TEMP VIEW message_global_data AS
SELECT g.ROWID              AS ROWID,
       i.message_id_header  AS message_id_header,
       g.message_id         AS message_id
FROM main.message_global_data AS g
LEFT JOIN mid.global_ids AS i ON i.global_message_id = g.ROWID
"""


def _sidecar_setup(conn, path) -> None:
    """Sidecar mode's connection prep, run by ``read_via_sqlite`` before the
    fingerprint check: bounded top-up first (the sidecar must not be attached while
    being written), then ATTACH read-only and shadow. sqlite failures here degrade
    exactly like any store-unavailable — runtime wraps them into SchemaDrift."""
    side = mail_ids.sidecar_path()
    _top_up_or_note(conn, side, path)
    conn.execute("ATTACH DATABASE ? AS mid", (f"file:{side}?mode=ro",))
    conn.execute(_SHADOW_VIEW_SQL)


def _top_up_or_note(conn, side, path) -> None:
    """Absorb ≤ ``_TOPUP_MAX_ROWS`` of new mail into the sidecar inline; past the
    cap — or on a detected index rebuild — answer anyway and leave the staleness
    note naming ``mail_index_ids`` (#156's honesty pattern: never silently stale)."""
    global _STALENESS_NOTE
    high_water = mail_ids.stored_high_water(side)
    if high_water is None:
        return  # no mark to measure against; the doctor coverage line reports it
    (max_rowid,) = conn.execute(
        "SELECT COALESCE(MAX(ROWID), 0) FROM messages WHERE deleted = 0"
    ).fetchone()
    if max_rowid < high_water:
        _STALENESS_NOTE = (
            "Mail's Envelope Index looks rebuilt (its row ids regressed below the "
            "sidecar's high-water mark) — every Message-ID mapping is suspect until "
            "mail_index_ids runs a full re-harvest. Answers may cite stale ids."
        )
        return
    delta = max_rowid - high_water
    if delta == 0:
        return
    if delta > _TOPUP_MAX_ROWS:
        _STALENESS_NOTE = (
            f"{delta} messages arrived since the Message-ID sidecar was last "
            "harvested and are missing from sqlite-backed answers — run "
            "mail_index_ids to catch up."
        )
        return
    try:
        mail_ids.top_up(
            conn,
            v_root=Path(path).parent.parent,
            sidecar_db=side,
            high_water=high_water,
            new_high_water=max_rowid,
        )
    except Exception:  # opportunistic freshness must degrade, never kill a read
        _STALENESS_NOTE = (
            f"{delta} recent messages could not be absorbed into the Message-ID "
            "sidecar and are missing from sqlite-backed answers — run "
            "mail_index_ids."
        )


def _read_index(path, read, *, fallback=None):
    """The ONE ``read_via_sqlite`` wiring for the Envelope Index — every read below
    goes through here so the #199 floor specialization and the #201 sidecar mode
    can't be skipped by a new call site. A fallback (when the caller passed one)
    still runs inside ``read_via_sqlite`` before anything raises; only the raising
    path is rewritten."""
    setup = None
    try:
        if _index_mode(path) == "sidecar":
            setup = lambda conn: _sidecar_setup(conn, path)  # noqa: E731
    except NativeError:
        # Detection could not open/read the store (FDA, missing file, corruption).
        # Proceed hook-less: the main read hits the same wall and classifies it
        # through the one degrade path — fallback, or the typed raise.
        pass
    try:
        return read_via_sqlite(
            path,
            HEADER_FINGERPRINT,
            read,
            fallback=fallback,
            immutable=False,
            setup=setup,
        )
    except SchemaDrift as e:
        specialized = _specialize_drift(e)
        if specialized is e:
            raise
        raise specialized from e


def check_index_schema() -> str:
    """Doctor's Envelope Index probe (#199/#201): ``"ok"``, ``"no_mail_data"``,
    ``"sidecar"``, or a raise.

    Read-only and prompt-free — a fingerprint check on the open store, nothing
    else — so doctor can run it in its default path. Raises ``SchemaDrift`` (floor-
    specialized like every index read) or ``FullDiskAccessDenied``; without this
    surface, doctor reported "no denied surfaces" on a machine where every sqlite
    mail read was broken. ``"sidecar"`` is a pre-Tahoe store WITH a built Message-ID
    sidecar (#201) — doctor reports its coverage instead of the floor."""
    path = envelope_index_path()
    if path is None:
        return "no_mail_data"
    _read_index(path, lambda conn: None)
    # In sidecar mode the shadow view satisfies the fingerprint, so the read above
    # passes — the MODE says which plane answered, and doctor reports its coverage.
    return "sidecar" if _index_mode(path) == "sidecar" else "ok"


def _pointer_rows(sql, params, *, fallback=None) -> list[Pointer]:
    """Run a Pointer-projecting query against the required index.

    search and thread differ only in SQL — this is their one shared read. The
    missing-store raise happens BEFORE any fallback is consulted (matching the
    adapter's long-standing behavior: no store is a followable error, not a reason
    to silently scan the inbox). ``immutable=False`` always: the Envelope Index is
    a live WAL store, and ``immutable=1`` would freeze pre-WAL data and silently
    drop recent mail (see runtime's warning)."""
    path = require_index_path()

    def read(conn):
        conn.row_factory = sqlite3.Row
        out = []
        for row in conn.execute(sql, params):
            p = row_to_pointer(row)
            if p is not None:
                out.append(p)
        return out

    return _read_index(path, read, fallback=fallback)


def query_search(
    *,
    subject=None,
    from_=None,
    to=None,
    mailbox_urls=None,
    since=None,
    until=None,
    unread=None,
    flagged=None,
    has_attachments=None,
    account=None,
    message_ids=None,
    limit=25,
    fallback=None,
) -> list[Pointer]:
    """Header search over ALL mailboxes, deduped, newest-first → Pointers.

    ``account`` must already be a resolved UUID segment and ``mailbox_urls``
    already-resolved raw urls (both resolutions are adapter jobs — one can talk to
    Mail, the other needs urldecode). FTS body search stays with the caller too —
    it is a different store with a different lifecycle; pass its hits as
    ``message_ids``."""
    sql, params = build_header_query(
        subject=subject,
        from_=from_,
        to=to,
        mailbox_urls=mailbox_urls,
        since=since,
        until=until,
        unread=unread,
        flagged=flagged,
        has_attachments=has_attachments,
        account=account,
        message_ids=message_ids,
        limit=limit,
    )
    return _pointer_rows(sql, params, fallback=fallback)


def query_mailbox_urls() -> list[str]:
    """Every mailboxes.url, raw/encoded — the resolver's input. Raises on a missing
    store: a mailbox filter against no store is the followable error, same as the
    other raising reads."""
    path = require_index_path()

    def read(conn):
        return [r[0] for r in conn.execute("SELECT url FROM mailboxes")]

    return _read_index(path, read)


def query_thread(message_id: str, limit: int) -> list[Pointer]:
    """One conversation by any member's EXACT-form (bracketed) Message-ID →
    Pointers, oldest-first. Id-form normalization is the adapter's concern."""
    sql, params = build_thread_query(message_id, limit)
    return _pointer_rows(sql, params)


def query_overview_rows() -> list[dict]:
    """Per-mailbox totals/unread as RAW rows — percent-encoded ``mailbox_url``, no
    account names. Decoding and naming are adapter concerns (naming can launch
    Mail, which this module never does); the ``_rows`` suffix is the warning that
    this is not the Pointer shape."""
    path = require_index_path()
    sql, params = build_overview_query()

    def read(conn):
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(sql, params)]

    return _read_index(path, read)


def query_message_locations(stored_ids) -> list[dict]:
    """Every ``{message_id, rowid, mailbox_url}`` row for these BRACKETED Message-IDs
    (#159) — the plane's "which file backs this message?" read. Not deduped and not
    Pointer-shaped (the ``_rows``-style warning that this is raw): a Message-ID has one
    citation but several files, and the plane wants the file in the mailbox it is about
    to act on. ``[]`` for an empty id list — no query, no store requirement, because
    nothing was asked."""
    ids = list(stored_ids)
    if not ids:
        return []
    path = require_index_path()
    sql, params = build_message_location_query(ids)

    def read(conn):
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(sql, params)]

    return _read_index(path, read)


def _dict_rows(sql, params) -> list[dict]:
    """Run a raw (non-Pointer) read against the Envelope Index. The `_rows`-style
    warning applies: these are raw columns, not the citation shape."""
    path = require_index_path()

    def read(conn):
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(sql, params)]

    return _read_index(path, read)


def query_sent_triage(limit: int) -> list[dict]:
    """Awaiting-reply's sent scan off the index at rest (#192): one dict per distinct
    sent message — {mid, subject, date_sent, rowid, answered, to_addrs} — newest
    first. Two reads: the triage rows, then one To-address hydration over the
    representative rowids. Pure sqlite; never launches Mail. Raises NativeError when
    the store or FDA is missing — the caller decides whether to fall back."""
    rows = _dict_rows(*build_sent_triage_query(limit))
    rowids = [r["rowid"] for r in rows]
    to_map: dict[int, list[str]] = {}
    if rowids:
        for rec in _dict_rows(*build_sent_recipients_query(rowids)):
            to_map.setdefault(rec["rowid"], []).append(rec["address"])
    for r in rows:
        r["to_addrs"] = to_map.get(r["rowid"], [])
    return rows


def query_stats_rows(since: int, account: str | None = None) -> list[dict]:
    """One deduped row per message in the window (#85). Pure sqlite — never launches
    Mail; the aggregation is the caller's Counter pass."""
    return _dict_rows(*build_stats_query(since, account))


def query_duplicate_summary() -> list[dict]:
    """Per-mailbox same-mailbox redundancy (#140), worst first."""
    return _dict_rows(*build_duplicate_summary_query())


def query_duplicate_offenders(limit: int) -> list[dict]:
    """The worst individual duplicate sets (#140), most copies first."""
    return _dict_rows(*build_duplicate_offenders_query(limit))


def query_duplicate_rows(mailbox_url: str) -> list[dict]:
    """Every row of every duplicate set in ONE mailbox (#140), set then ROWID order."""
    return _dict_rows(*build_duplicate_rows_query(mailbox_url))


def query_cross_account_summary() -> list[dict]:
    """Per-account cross-account redundancy (#153)."""
    return _dict_rows(*build_cross_account_summary_query())


def query_cross_account_rows() -> list[dict]:
    """Every physical copy of every cross-account duplicate set (#153)."""
    return _dict_rows(*build_cross_account_rows_query())


def body_texts(rowids, *, root: Path | None = None) -> dict[int, str]:
    """``{rowid: body text}`` read from ``.emlx`` AT REST — no Mail, no sidecar (#158).

    The one place bodies are read off disk. Two callers want it for different reasons:
    ``body_fingerprints`` hashes the text to prove two copies are the same message, and
    ``mail_bodies``/thread snippets hand the text to the model.

    **Why at rest and not the FTS sidecar** (device-probed 2026-08-11): the sidecar
    covered **0 of the 30 newest** messages on this Mac while the ``.emlx`` files
    covered **30/30**. The sidecar is keyed to the last ``mail_index_bodies`` run, so it
    is a cold archive — precisely missing the message you are about to reply to. At rest
    is fresh, because Mail writes the file as the message arrives.

    Cost is one walk of the store regardless of how many rowids are asked for — 36,748
    files in 0.90s here — so callers should ask for a whole batch at once, never per id.

    A rowid whose file is absent, malformed, or carries no text part is simply ABSENT
    from the result. The caller must report that as MISSING, never as an empty body:
    "we could not read it" and "the author wrote nothing" are different answers.
    """
    base = root if root is not None else mail_root()
    if base is None:
        return {}
    wanted = {int(r) for r in rowids}
    if not wanted:
        return {}
    out: dict[int, str] = {}
    for f in base.rglob("*.emlx"):
        try:
            rowid = int(f.name.split(".")[0])
        except ValueError:
            continue
        if rowid not in wanted or rowid in out:
            continue
        try:
            payload = emlx_payload(f.read_bytes())
        except OSError:
            continue  # Mail can expunge between rglob and read — same race as indexing
        if not payload:
            continue
        text = _body_text(message_from_bytes(payload))
        if text.strip():
            out[rowid] = text
    return out


def body_fingerprints(rowids, *, root: Path | None = None) -> dict[int, str]:
    """``{rowid: sha256-of-normalised-body}`` for the copies that have a readable body.

    **This is the identity gate #153 actually needs, and it is NOT the one #153 was
    filed with.** That issue inherited #140's rule — same Message-ID plus identical
    ``size`` and ``date_sent`` — which works inside one mailbox because every copy came
    off one server. Measured across accounts on this Mac (2026-08-06, all 3,948
    cross-account sets): ``size + date_sent`` agrees on **1.2%** of them, and just 1.1%
    of the 3,926 Google+Personal sets. ``date_sent`` always matches (it is a header);
    ``size`` almost never does, because Gmail rewrites headers in transit (``X-GM-*``,
    extra ``Received:``) without altering a word of the content. Gating on it would have
    shipped a cleanup that declines 99% of the garbage it exists to remove.

    The body is the thing a human means by "the same message", and #119 made it local:
    on a 400-set sample every copy's body was readable and **397/397 Google+Personal
    sets matched, 100%**, while only 6 matched on size.

    A hash is NOT an identity on its own and this must not be read as one — negative
    control over 792 distinct Message-IDs found 784 distinct hashes, i.e. **6 real
    collisions**, all bulk-sender templates (the same newsletter sent twice). So this is
    only ever the CONFIRMATION on copies that already share a Message-ID; the id stays
    the key. Whitespace is normalised and nothing else, because anything more aggressive
    starts fusing messages that genuinely differ.

    Missing/unreadable/body-less copies are simply ABSENT from the result — the caller
    must treat "no fingerprint" as "cannot prove identity, do not delete", never as a
    match.
    """
    return {
        rowid: hashlib.sha256(
            " ".join(text.split()).encode("utf-8", "replace")
        ).hexdigest()
        for rowid, text in body_texts(rowids, root=root).items()
    }


def query_trash_url(account: str) -> str | None:
    """The mailboxes.url of ``account``'s own Trash, or None when the index knows of
    none (#80). None is a real answer — a freshly added account may have no Trash row
    yet — and the caller must say so rather than falling back to the unified accessor,
    which crashes Mail on a move out of it (facts doc §5c)."""
    rows = _dict_rows(*build_trash_query(account))
    return rows[0]["url"] if rows else None


def query_local_account_url() -> str | None:
    """First ``local://`` mailbox url, or None when the store (or the local store
    inside it) is absent. Asymmetric with the raising reads BY CONTRACT: the
    account resolver owns the richer "no On My Mac store" error, so this read must
    answer None, never ``_NO_MAIL_DATA``. URL parsing stays with the caller."""
    path = envelope_index_path()
    if path is None:
        return None
    sql, params = build_local_account_query()

    def read(conn):
        conn.row_factory = sqlite3.Row
        row = conn.execute(sql, params).fetchone()
        return row["url"] if row else None

    return _read_index(path, read)


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._chunks: list[str] = []

    def handle_data(self, data):
        self._chunks.append(data)

    def text(self) -> str:
        return " ".join(" ".join(self._chunks).split())


def _html_to_text(html: str) -> str:
    p = _TextExtractor()
    p.feed(html)
    return p.text()


def _body_text(msg) -> str:
    """Prefer text/plain; else the first text/html rendered to text.

    Empty if neither.
    """
    plain, html = None, None
    for part in msg.walk() if msg.is_multipart() else [msg]:
        ctype = part.get_content_type()
        if ctype == "text/plain" and plain is None:
            plain = part.get_payload(decode=True)
        elif ctype == "text/html" and html is None:
            html = part.get_payload(decode=True)
    if plain:
        return plain.decode("utf-8", "replace")
    if html:
        return _html_to_text(html.decode("utf-8", "replace"))
    return ""


def emlx_payload(raw: bytes) -> bytes:
    """The RFC822 bytes inside an ``.emlx`` — ``b""`` when the framing is malformed.

    The ONE home for Mail's on-disk message framing: a first line holding a byte count,
    then exactly that many bytes of message, then Mail's own trailing plist. Two callers
    need it for opposite reasons — ``parse_emlx`` wants the text inside, and #159's
    backup wants those same bytes written out verbatim as a plain ``.eml`` — so the
    format fact is stated once here rather than re-derived on each side.
    """
    nl = raw.find(b"\n")
    if nl == -1:
        return b""
    try:
        length = int(raw[:nl].strip())
    except ValueError:
        return b""
    if length < 0:
        return b""
    return raw[nl + 1 : nl + 1 + length]


def parse_emlx(raw: bytes) -> tuple[str, str] | None:
    """(message_id, body_text) from an .emlx byte string.

    Returns None if malformed, header-less, or no extractable text.
    Strips the length-prefix line and trailing plist.
    """
    rfc822 = emlx_payload(raw)
    if not rfc822:
        return None
    try:
        msg = message_from_bytes(rfc822)
        mid = msg.get("Message-ID")
        if not mid or not mid.strip():
            return None
        body = _body_text(msg).strip()
    except Exception:
        # Untrusted-input boundary: .emlx bytes are attacker-influenceable (deeply
        # nested multipart can overflow stdlib email's own recursive descent before
        # we ever see a Message object). Never let a parse failure escape — None.
        return None
    if not body:
        return None
    return mid.strip(), body


# --- FTS5 body sidecar (#70) ---------------------------------------------------------
# Best-effort full-text index over .emlx bodies, keyed by RFC822 Message-ID. Lives in
# our own state dir — NEVER inside Mail's data — so it can be rebuilt or deleted freely
# without touching anything Mail.app owns.

# Raised 200 MB → 512 MB by #119. The old cap was sized for the corpus this indexer
# could actually see — the ~13.8k full .emlx — and indexing partials as well roughly
# TRIPLES it to ~36.5k. Measured on this Mac at ~6.3 MB per 1,000 bodies, a complete
# store lands near 230 MB, so the old default would have stopped the run at ~90% and
# set `capped` — technically honest, but it would cap on its first full build, which
# reads as "the feature doesn't work". 512 MB is nothing against the 1 TB free here.
# MACOS_APPS_MCP_FTS_MAX_BYTES still overrides; `capped` is still reported.
_FTS_DEFAULT_MAX = 512 * 1024 * 1024  # ~512 MB


def fts_path() -> Path:
    """Where the FTS5 body sidecar lives: our state dir, never Mail's."""
    return state_dir() / "mail_fts.sqlite"


def fts_max_bytes() -> int:
    """Size cap for the sidecar: env override or the ~512 MB default."""
    raw = os.environ.get("MACOS_APPS_MCP_FTS_MAX_BYTES")
    return int(raw) if raw and raw.isdigit() else _FTS_DEFAULT_MAX


def _fts_connect(fts_db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(fts_db)
    # Concurrency (#71 panel): mail_index_bodies runs OFF run_native (pure file/sqlite
    # I/O), so two overlapping builds — or a mail_search(body=) reader racing a build —
    # would hit the default instant-fail lock and raise a raw sqlite OperationalError.
    # WAL lets readers proceed during a write; busy_timeout makes writer/writer
    # contention wait instead of erroring. Safe: this is OUR sidecar, never Mail's data.
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        "CREATE VIRTUAL TABLE IF NOT EXISTS bodies"
        " USING fts5(message_id UNINDEXED, body);"
        "CREATE TABLE IF NOT EXISTS indexed_files"
        "(path TEXT PRIMARY KEY, mtime INTEGER, size INTEGER);"
    )
    return conn


def build_body_index(
    *,
    mail_root: Path,
    fts_db: Path,
    rebuild: bool = False,
    max_bytes: int | None = None,
) -> dict:
    """Best-effort FTS body index over EVERY .emlx, ``.partial`` included. Resumable
    (skips unchanged files), size-capped (stops when fts_db exceeds max_bytes). Never
    touches Mail's data — reads .emlx at rest, writes only fts_db.

    **``.partial.emlx`` does NOT mean "body not downloaded"** — it means the ATTACHMENTS
    were not downloaded. Measured 2026-08-06 over all 22,748 partials on this Mac:
    22,627 (99.47%) carry a complete, extractable body; 99 (0.44%) are genuinely
    body-stubbed, 13 are attachment-only messages with no text part at all, and 9 have
    no Message-ID. Verified byte-for-byte, not inferred: for sampled partials the body
    on disk is IDENTICAL to the body Mail returns after fetching the whole message
    (`source`), including a 27 MB message whose 2,131-char body was already fully
    present in its 17 KB partial. So skipping these files — which this function did
    until #119 — hid ~62% of the store from ``mail_search(body=…)`` for no reason, and
    the "download the bodies first" remediation it implied would have bought 99
    messages for GB of IMAP.

    A partial that later fills in is re-indexed for free: ``indexed_files`` is keyed by
    PATH, so ``1234.partial.emlx`` → ``1234.emlx`` is a new key, and the ``DELETE FROM
    bodies WHERE message_id`` before each insert keeps that from double-counting.
    """
    if max_bytes is None:
        max_bytes = fts_max_bytes()
    if rebuild and fts_db.exists():
        fts_db.unlink()
    conn = _fts_connect(fts_db)
    seen = {
        r[0]: (r[1], r[2])
        for r in conn.execute("SELECT path, mtime, size FROM indexed_files")
    }
    indexed = skipped = total = 0
    capped = False
    try:
        for f in sorted(mail_root.rglob("*.emlx")):
            total += 1
            key = str(f)
            try:
                st = f.stat()
                if seen.get(key) == (int(st.st_mtime), st.st_size):
                    skipped += 1
                    continue
                raw = f.read_bytes()
            except OSError:
                # Mail.app can expunge/rename a file between rglob() enumerating it
                # and us reading it — skip just this file, never abort the run.
                skipped += 1
                continue
            parsed = parse_emlx(raw)
            if parsed is None:
                # record so a re-run doesn't reparse an unindexable file
                conn.execute(
                    "INSERT OR REPLACE INTO indexed_files VALUES (?,?,?)",
                    (key, int(st.st_mtime), st.st_size),
                )
                skipped += 1
            else:
                mid, body = parsed
                conn.execute("DELETE FROM bodies WHERE message_id = ?", (mid,))
                conn.execute(
                    "INSERT INTO bodies (message_id, body) VALUES (?, ?)", (mid, body)
                )
                conn.execute(
                    "INSERT OR REPLACE INTO indexed_files VALUES (?,?,?)",
                    (key, int(st.st_mtime), st.st_size),
                )
                conn.commit()
                indexed += 1
            # Check the cap only *after* committing progress on this file: a bare
            # CREATE VIRTUAL TABLE fts5 schema already occupies more than a few bytes,
            # so checking before the first write would cap the run at zero files
            # indexed instead of stopping once real progress has been recorded.
            if fts_db.stat().st_size >= max_bytes:
                capped = True
                break
    finally:
        try:
            conn.commit()
        finally:
            conn.close()
    return {
        "indexed": indexed,
        "skipped": skipped,
        "total_emlx": total,
        "capped": capped,
    }


def _fts_query(raw: str) -> str:
    """Sanitize a raw user query into an always-valid FTS5 MATCH expression.

    FTS5 parses the MATCH value as query syntax, not literal text — bound params only
    stop injection, they don't stop e.g. `jane@acme.com` ("syntax error near @") or
    `invoice AND` from raising sqlite3.OperationalError. So every whitespace-split
    token is quoted as a literal phrase (embedded `"` doubled per SQL-string-escaping
    convention) and the quoted tokens are joined with a space — FTS5's implicit AND —
    which is valid for ANY input, including punctuation, bare operators, or an
    unbalanced `"`. Returns "" when there are no tokens (query was all whitespace);
    the caller must not call MATCH with that (#70 review I1)."""
    tokens = raw.split()
    return " ".join('"' + t.replace('"', '""') + '"' for t in tokens)


def fts_search(fts_db: Path, query: str, limit: int = 200) -> list[str]:
    """Message-IDs whose body matches the FTS query, or [] if the sidecar is absent."""
    if not fts_db.exists():
        return []
    fts_query = _fts_query(query)
    if not fts_query:
        return []
    conn = sqlite3.connect(f"file:{fts_db}?mode=ro", uri=True)
    conn.execute("PRAGMA busy_timeout=5000")  # wait out a concurrent build, don't error
    try:
        rows = conn.execute(
            "SELECT message_id FROM bodies WHERE bodies MATCH ? LIMIT ?",
            (fts_query, limit),
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


def body_coverage() -> str:
    """One line saying how much of the store ``body=`` can actually SEE (#156 case 4).

    A ``body=`` search that finds nothing is indistinguishable from a store that
    contains nothing, so every empty answer says which one it was. A sidecar that is
    absent or unreadable counts as 0 — that is the honest reading, and it is exactly the
    case the remediation addresses.

    **The two sides are INTERSECTED, not divided.** This used to count the sidecar's
    rows against the store's distinct-Message-ID total, which was fine only while the
    numerator was small: once #119 let partials be indexed, the sidecar (22,840 rows)
    OVERSHOT the live store (22,382) and the line printed "22840 of 22379", a ratio
    above 1. The two sets are not nested — the sidecar keeps bodies for messages since
    deleted from Mail (571 here), and re-indexing will never drop them — so the only
    meaningful number is how many LIVE messages actually have a body indexed. Both
    sides spell the Message-ID with its angle brackets (``.emlx`` headers and
    ``message_global_data`` agree; it is the AppleScript ``message id`` property that
    strips them), so the sets intersect directly with no normalising.

    Costs ~1.9 s against ~16 ms for the old pair of counts, which is affordable because
    this runs on ONE path only: a ``body=`` search that already came back empty.
    """
    have: set[str] = set()
    fts = fts_path()
    if fts.exists():
        conn = sqlite3.connect(f"file:{fts}?mode=ro", uri=True)
        conn.execute("PRAGMA busy_timeout=5000")  # wait out a build, don't error
        try:
            have = {r[0] for r in conn.execute("SELECT message_id FROM bodies")}
        except sqlite3.Error:
            have = set()  # no bodies table yet: never built
        finally:
            conn.close()

    def read(conn):
        return {
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT gd.message_id_header FROM messages m"
                " JOIN message_global_data gd ON gd.ROWID = m.global_message_id"
                " WHERE m.deleted = 0 AND gd.message_id_header IS NOT NULL"
                " AND gd.message_id_header <> ''"
            )
        }

    live = _read_index(require_index_path(), read)
    total = len(live)
    searchable = len(have & live)
    pct = f" ({100 * searchable / total:.1f}%)" if total else ""
    return (
        f"{searchable} of {total} messages have a searchable body{pct} — body= can "
        "only match those. Run mail_index_bodies to close the gap; it indexes every "
        ".emlx on disk, including .partial ones (a partial is missing its ATTACHMENTS, "
        "not its body). A message Mail never stored a text part for stays unsearchable "
        "— about 0.5% of this store — and no amount of re-indexing changes that."
    )
