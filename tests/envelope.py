"""The ONE fake Envelope Index (GATE-08): a sqlite store shaped like Mail's real one,
schema = the superset every ``query_*`` executor in ``mail_index`` reads — not just the
columns one test happened to need. Promoted from ``tests/test_mail_search.py``'s private
``_fake_envelope``: ``seed_base`` inserts the exact same rows, byte-for-byte, on top of
the widened ``SCHEMA``. A test that wants more than the base rows builds on top with
``Envelope.add_mailbox``/``add_message``/``execute`` rather than hand-rolling another
``CREATE TABLE`` block — one schema, read everywhere.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

# Real account UUIDs, not placeholders: _resolve_account short-circuits on the
# 8-4-4-4-12 shape precisely so a UUID filter never has to ask Mail (and so never
# launches it), and a fixture with `AAAA` in it would test the osascript path by
# accident.
ACCT_A = "AAAAAAAA-1111-2222-3333-444444444444"
ACCT_B = "BBBBBBBB-1111-2222-3333-444444444444"
ACCT_LOCAL = "A2025935-B0B2-4A77-9003-68EF6E541361"  # the real On My Mac store's id

# Named columns of the widened `messages` table, in schema order — what
# ``Envelope.add_message(**cols)`` will accept. A caller states only the columns it
# cares about; every other column falls back to its schema default.
MSG_COLS = (
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
    "size",
    "message_id",
    "subject_prefix",
)

# The Envelope Index tables + every column any query_* executor reads (mirrors, and
# stays in lockstep with, macos_apps_mcp.adapters.mail_index.HEADER_FINGERPRINT).
# Widened beyond the original `_fake_envelope` (RESEARCH.md Pitfall 2): messages
# gains `size`/`message_id`/`subject_prefix`, message_global_data gains `message_id`
# (the internal int build_sent_triage_query joins on — NOT the same value as
# global_message_id), recipients gains `type`/`position`, and message_references is
# new — all four read by build_duplicate_rows_query/build_sent_triage_query/
# build_sent_recipients_query, none of them covered by the old fingerprint.
SCHEMA = """
CREATE TABLE subjects(ROWID INTEGER PRIMARY KEY, subject TEXT);
CREATE TABLE addresses(ROWID INTEGER PRIMARY KEY, address TEXT, comment TEXT);
CREATE TABLE mailboxes(ROWID INTEGER PRIMARY KEY, url TEXT);
CREATE TABLE message_global_data(
    ROWID INTEGER PRIMARY KEY,
    message_id_header TEXT,
    message_id INT NOT NULL DEFAULT 0);
CREATE TABLE recipients(
    ROWID INTEGER PRIMARY KEY, message INT, address INT,
    type INT NOT NULL DEFAULT 0, position INT NOT NULL DEFAULT 0);
CREATE TABLE attachments(ROWID INTEGER PRIMARY KEY, message INT, name TEXT);
CREATE TABLE messages(
    ROWID INTEGER PRIMARY KEY, subject INT, sender INT, global_message_id INT,
    mailbox INT, date_received INT, date_sent INT, read INT, flagged INT,
    deleted INT, conversation_id INT,
    size INT NOT NULL DEFAULT 0,
    message_id INT NOT NULL DEFAULT 0,
    subject_prefix TEXT);
CREATE TABLE message_references(
    ROWID INTEGER PRIMARY KEY, message INT, reference INT);
"""


def seed_base(path) -> None:
    """A minimal Envelope Index with the fingerprinted tables + columns.

    Deliberately includes the duplicate shapes found on a real Mac: <abc@ex.com> exists
    in INBOX *and* Archive (cross-folder), and <dup@ex.com> exists twice in the SAME
    folder (a migration copy that ran twice). Dedup tests depend on both — and
    <dup@ex.com>'s two copies are the NEWEST rows in the store, so an un-deduped
    `LIMIT 2` would hand back two rows carrying one distinct message.

    <split@ex.com> is the cross-account copy whose two rows carry DIFFERENT
    conversation_ids (Mail threads per account), which is what makes a single-branch
    thread seed observable. The local:// mailbox carries a percent-encoded name so the
    overview's decoding is actually exercised.

    Row-for-row identical to the pre-promotion ``_fake_envelope`` (GATE-08's
    byte-for-byte requirement) — only the surrounding ``CREATE TABLE`` statements
    widened; every new column an unlisted row lands on takes its schema default.
    """
    c = sqlite3.connect(path)
    c.executescript(
        SCHEMA
        + f"""
        INSERT INTO subjects VALUES
            (1,'Invoice 42'),(2,'Re: Invoice 42'),(3,'Split thread'),(4,'Re: Split'),
            (5,'Zero dated'),(6,'Re: Zero dated'),(7,'Junk ranking');
        INSERT INTO addresses VALUES (1,'jane@ex.com','Jane Doe');
        INSERT INTO mailboxes VALUES
            (1,'imap://{ACCT_A}/INBOX'),
            (2,'imap://{ACCT_A}/Archive'),
            (3,'imap://{ACCT_B}/Travel'),
            (4,'local://{ACCT_LOCAL}/Some%20Folder'),
            (5,'imap://{ACCT_A}/Junk%20E-mail');
        INSERT INTO message_global_data (ROWID, message_id_header) VALUES
            (1,'<abc@ex.com>'),(2,'<reply@ex.com>'),(3,'<dup@ex.com>'),
            (4,'<split@ex.com>'),(5,'<branchA@ex.com>'),(6,'<branchB@ex.com>'),
            (7,'<zero@ex.com>'),(8,'<zeroold@ex.com>'),(9,NULL),
            (10,'<junky@ex.com>');
        -- <abc@ex.com>: INBOX + Archive, same conversation 7 as its reply
        INSERT INTO messages VALUES (10,1,1,1,1,1700000000,1700000000,0,0,0,7,0,0,NULL);
        INSERT INTO messages VALUES (11,1,1,1,2,1700000000,1700000000,0,0,0,7,0,0,NULL);
        -- the reply, in Travel, conversation 7
        INSERT INTO messages VALUES (12,2,1,2,3,1700000900,1700000900,1,0,0,7,0,0,NULL);
        -- <dup@ex.com>: twice in the SAME mailbox, unrelated conversation, and the two
        -- NEWEST rows in the store (the LIMIT-after-dedup guard depends on that).
        INSERT INTO messages
            VALUES (13,1,1,3,3,1700001000,1700001000,0,0,0,9,0,0,NULL);
        INSERT INTO messages
            VALUES (14,1,1,3,3,1700001000,1700001000,0,0,0,9,0,0,NULL);
        -- <split@ex.com>: one copy per account, each in its own conversation (20/21),
        -- each conversation holding one further member.
        INSERT INTO messages
            VALUES (20,3,1,4,1,1700002000,1700002000,0,0,0,20,0,0,NULL);
        INSERT INTO messages
            VALUES (21,3,1,4,3,1700002000,1700002000,0,0,0,21,0,0,NULL);
        INSERT INTO messages
            VALUES (22,4,1,5,1,1700002100,1700002100,0,0,0,20,0,0,NULL);
        INSERT INTO messages
            VALUES (23,4,1,6,3,1700002200,1700002200,0,0,0,21,0,0,NULL);
        -- conversation 30: the NEWER message carries date_sent = 0 (Mail stores a zero,
        -- not a NULL), which a NULL-only COALESCE would sort to the very front.
        INSERT INTO messages VALUES (30,5,1,7,1,1700003000,0,0,0,0,30,0,0,NULL);
        INSERT INTO messages
            VALUES (31,6,1,8,1,1700002500,1700002500,0,0,0,30,0,0,NULL);
        -- a header-less message (no RFC822 Message-ID): uncitable, so search skips it,
        -- but it IS in the mailbox and the overview must still count it.
        INSERT INTO messages
            VALUES (40,1,1,9,2,1700000100,1700000100,1,0,0,11,0,0,NULL);
        -- <junky@ex.com>: a real filed copy (Travel) plus a NEWER copy in Exchange's
        -- `Junk%20E-mail`. An end-anchored '%Junk' rank pattern misses that name, so
        -- the junk copy ranked as a preferred filed folder and won on recency.
        INSERT INTO messages
            VALUES (50,7,1,10,3,1700000700,1700000700,1,0,0,12,0,0,NULL);
        INSERT INTO messages
            VALUES (51,7,1,10,5,1700000800,1700000800,1,0,0,12,0,0,NULL);
        INSERT INTO attachments VALUES (1,10,'contract.pdf'),(2,12,'image001.png');
        """
    )
    c.commit()
    c.close()


@dataclass
class Envelope:
    """A handle onto a ``seed_base``-shaped store, for tests that need a few more
    rows than the canonical set — named-column inserts against the SAME widened
    schema, so a bespoke test store never drifts from what ``HEADER_FINGERPRINT``
    and the real queries expect."""

    path: Path

    def execute(self, sql: str, params=()) -> None:
        """Escape hatch for anything add_mailbox/add_message doesn't cover
        (subjects, addresses, message_global_data, message_references, ...)."""
        conn = sqlite3.connect(self.path)
        try:
            conn.execute(sql, params)
            conn.commit()
        finally:
            conn.close()

    def add_mailbox(self, url: str) -> int:
        """INSERT one mailboxes row, return its ROWID."""
        conn = sqlite3.connect(self.path)
        try:
            cur = conn.execute("INSERT INTO mailboxes(url) VALUES (?)", (url,))
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def add_message(self, **cols) -> int:
        """INSERT one messages row by NAMED column (only ``MSG_COLS`` names are
        accepted); every column the caller omits takes its schema default.
        Returns the row's ROWID."""
        unknown = set(cols) - set(MSG_COLS)
        if unknown:
            raise ValueError(f"not a messages column: {sorted(unknown)}")
        names = list(cols)
        placeholders = ",".join("?" for _ in names)
        conn = sqlite3.connect(self.path)
        try:
            cur = conn.execute(
                f"INSERT INTO messages({','.join(names)}) VALUES ({placeholders})",
                [cols[n] for n in names],
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()
