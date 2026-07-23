"""Mail indexed read plane (#70): a read-only sqlite reader over Mail's Envelope Index
for header/subject/sender search at scale, plus a best-effort FTS5 body sidecar in our
own state dir. Pure/sqlite only — no EventKit, no Mail.app. The MailAdapter delegates
here; this module never launches Mail (read-at-rest)."""

from __future__ import annotations

from pathlib import Path

from ..contracts import Pointer
from .mail import _deeplink

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
    },
    "subjects": {"ROWID", "subject"},
    "addresses": {"ROWID", "address", "comment"},
    "mailboxes": {"ROWID", "url"},
    "message_global_data": {"ROWID", "message_id_header"},
    "recipients": {"message", "address"},
}


def envelope_index_path() -> Path | None:
    """Newest ~/Library/Mail/V*/MailData/Envelope Index, or None if Mail data absent.
    V* moves between macOS versions; pick the highest-numbered MailData."""
    roots = sorted(
        (Path.home() / "Library" / "Mail").glob("V*/MailData/Envelope Index"),
        key=lambda p: p.parts,
    )
    return roots[-1] if roots else None


def row_to_pointer(row) -> Pointer | None:
    """Map one joined Envelope Index row → Pointer. None when the message has no RFC822
    Message-ID (no stable citation — same rule the adapter documents for header-less
    messages)."""
    mid = row["message_id_header"]
    if not mid or not str(mid).strip():
        return None
    return Pointer(
        id=str(mid),
        summary=row["subject"] or "",
        deeplink=_deeplink(str(mid)),
        folder=row["mailbox_url"],
    )
