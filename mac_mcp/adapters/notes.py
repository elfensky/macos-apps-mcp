"""Notes adapter — dual-backend (#60): NoteStore.sqlite for reads, osascript for writes.

Enumeration reads (get_all, get_pointers search) go through the fast read-only sqlite
plane over NoteStore.sqlite — Apple precomputes ZSNIPPET (the summary) and the stable
x-coredata://…/ICNote/pN id the vault sync needs, so reads are far cheaper than
AppleScript's O(n) enumeration (the sin that hollowed out apple-mcp). Per the FDA
policy, Notes DEGRADES: on missing Full Disk Access OR a schema-fingerprint mismatch,
read_via_sqlite falls back to the AppleScript reader (still works without FDA — no
regression). Writes (delete) and body hydration (get_bodies) stay on osascript.
Pointer.id is the x-coredata:// id, summary the snippet, folder the "Account / Folder"
label; deeplink empty (no open-by-id scheme). User input goes via argv (no injection);
templates are timeout-bounded.
"""

from __future__ import annotations

from pathlib import Path

from ..contracts import Pointer
from ..runtime import (
    OutputOverflow,
    clean_body,
    clean_summary,
    read_via_sqlite,
    run_osascript,
)

MAX_NOTES = 25
MAX_BODIES = 50

NOTESTORE = (
    Path.home() / "Library/Group Containers/group.com.apple.notes/NoteStore.sqlite"
)

# NoteStore is Core Data: notes, folders, and accounts all live in
# ZICCLOUDSYNCINGOBJECT (single-table inheritance). Only the columns the queries below
# read are fingerprinted — a macOS schema move that renames/drops any of them trips
# SchemaDrift and the read DEGRADES to the AppleScript fallback (never a hard error,
# never a mis-parse). The exact schema is version-variable (sirmews recipe) — the
# @integration cross-check validates it against the real store.
_FINGERPRINT = {
    "ZICCLOUDSYNCINGOBJECT": {
        "Z_PK",
        "ZTITLE1",  # note title
        "ZSNIPPET",  # Apple's precomputed preview → Pointer.summary
        "ZFOLDER",  # → folder row's Z_PK
        "ZNOTEDATA",  # set on notes (not folders/accounts) → distinguishes a note row
        "ZMARKEDFORDELETION",  # tombstone flag
        "ZISPINNED",
        "ZISPASSWORDPROTECTED",  # locked
        "ZTITLE2",  # folder name (on a folder row)
        "ZOWNER",  # folder → account row's Z_PK
        "ZNAME",  # account name (on an account row)
    },
    "Z_METADATA": {"Z_UUID"},  # the store UUID for the x-coredata:// id
}

# All templates carry `with timeout` (#56): bound the Apple Events so an orphaned
# osascript self-terminates instead of pinning Notes.
_SEARCH = """on run argv
  set q to item 1 of argv
  set out to ""
  with timeout of 120 seconds
  tell application "Notes"
    repeat with n in (notes whose name contains q)
      set out to out & (id of n) & tab & (name of n) & linefeed
    end repeat
  end tell
  end timeout
  return out
end run"""

# notes_all: every note across accounts, excluding Recently Deleted. id+name read in
# one multi-property snapshot ({id, name} of (notes of f)) stay aligned — do NOT split
# into separate "id of every note" / "name of every note" events (they can mispair if
# Notes mutates between calls). Lines via `set end of` + TID join avoid O(n^2) string
# concatenation on large libraries. ponytail: no cap — 30s osascript timeout is the
# de-facto ceiling; a too-large library fails whole. Add pagination only if needed.
_LIST_ALL = """on run argv
  set theLines to {}
  with timeout of 120 seconds
  tell application "Notes"
    repeat with acc in accounts
      set accName to name of acc
      repeat with f in folders of acc
        if name of f is not "Recently Deleted" then
          set {theIds, theNames} to ({id, name} of (notes of f))
          set fName to name of f
          set folder_label to accName & " / " & fName
          repeat with i from 1 to (count of theIds)
            set nId to item i of theIds
            set nName to item i of theNames
            set noteLine to (nId & tab & folder_label & tab & nName)
            set end of theLines to noteLine
          end repeat
        end if
      end repeat
    end repeat
  end tell
  end timeout
  set AppleScript's text item delimiters to linefeed
  return theLines as text
end run"""

# note_bodies: opt-in, batched body hydration. plaintext contains newlines/tabs,
# so a line/tab-delimited format can't frame it — use ASCII control chars that
# text never carries: US (\x1f, character id 31) between id and body, RS (\x1e,
# character id 30) between records. A literal-text sentinel (e.g. "@@@END@@@")
# could appear in a body and corrupt parsing; control chars effectively cannot.
# Unknown ids are skipped (try).
_BODIES = """on run argv
  set us to character id 31
  set rs to character id 30
  set out to ""
  with timeout of 120 seconds
  tell application "Notes"
    repeat with theId in argv
      try
        set noteBody to plaintext of note id theId
        set out to out & theId & us & noteBody & rs
      end try
    end repeat
  end tell
  end timeout
  return out
end run"""

# delete_note: moves the note to Recently Deleted (recoverable ~30 days). Notes ids are
# x-coredata:// URLs that embed the store id → globally unique, so delete-by-id targets
# exactly one note. expect_title (optional argv[2]) guards against stale/wrong ids: the
# script errors before deleting if the live title doesn't match.
_DELETE = """on run argv
  with timeout of 120 seconds
  tell application "Notes"
    set n to note id (item 1 of argv)
    if (count of argv) > 1 then
      if (name of n) is not (item 2 of argv) then
        error "note title does not match expect_title"
      end if
    end if
    delete n
  end tell
  end timeout
end run"""

# dry_run preview (#54): the real-delete guard EXACTLY — same `note id` lookup and same
# AppleScript `is not` title comparison as _DELETE (case-insensitive + whitespace-
# significant) — minus the `delete n`, plus `return name of n`. The expect_title check
# MUST run here, not in Python: a Python `!=` on the title diverged from AppleScript on
# case AND whitespace, so the preview could report the opposite of what the real delete
# does (#54 review). Errors on an unknown id or a title mismatch, exactly as _DELETE.
_PREVIEW_DELETE = """on run argv
  with timeout of 120 seconds
  tell application "Notes"
    set n to note id (item 1 of argv)
    if (count of argv) > 1 then
      if (name of n) is not (item 2 of argv) then
        error "note title does not match expect_title"
      end if
    end if
    return name of n
  end tell
  end timeout
end run"""


def _parse(raw: str) -> list[Pointer]:
    out = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        ident, _, name = line.partition("\t")
        out.append(
            Pointer(
                id=ident,
                summary=clean_summary(name) or "(untitled note)",
                deeplink="",
            )
        )
    return out


def _parse_all(raw: str) -> list[Pointer]:
    out = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        ident = parts[0]
        folder = parts[1] if len(parts) > 1 else None
        title = parts[2] if len(parts) > 2 else ""
        out.append(
            Pointer(
                id=ident,
                summary=clean_summary(title) or "(untitled note)",
                deeplink="",
                folder=folder,
            )
        )
    return out


def _parse_bodies(raw: str) -> list[dict]:
    out = []
    for record in raw.split("\x1e"):
        ident, sep, body = record.partition("\x1f")
        if not sep:  # trailing "" after final RS, or a malformed record — skip
            continue
        out.append({"id": ident.strip(), "body": body})
    return out


# --- sqlite read plane (#60) ---------------------------------------------------------
# A note row: ZNOTEDATA set (folders/accounts have none) and not tombstoned. Newest
# first via Z_PK DESC (higher pk ≈ more recent; avoids depending on a date column that
# varies by macOS version). Folder + account resolved by self-join (Core Data keeps
# notes/folders/accounts in the same table).
#
# Recently Deleted: a trashed note is NOT ZMARKEDFORDELETION=1 (that flag is the
# CloudKit PERMANENT-purge tombstone) — it stays a live row that just MOVES to the
# "Recently Deleted" folder for ~30 days. So we also exclude notes whose folder is named
# "Recently Deleted", exactly as the AppleScript reader does — otherwise the sqlite path
# leaks trashed notes the AppleScript path hides (#60 review). ponytail: matching by the
# English folder name mirrors the AppleScript path's own localization limitation, so the
# two backends AGREE (the @integration cross-check needs that); a locale-independent
# ZFOLDERTYPE-based exclusion is the upgrade path if a non-English store needs it.
#
# WAL staleness: reads use immutable=1 (per the #60 Design + the sirmews recipe) so they
# open past the lock Notes.app holds on the live store. The tradeoff is that immutable
# ignores the -wal, so a just-typed note not yet checkpointed can be briefly missing —
# acceptable staleness for search/list, and the AppleScript fallback always sees current
# state. (Messages, #59, uses mode=ro without immutable — chat.db isn't held locked.)
_TRASH = "Recently Deleted"
_COLS = """o.Z_PK, o.ZTITLE1, o.ZSNIPPET, o.ZISPINNED, o.ZISPASSWORDPROTECTED,
       f.ZTITLE2, a.ZNAME"""
_FROM = f"""FROM ZICCLOUDSYNCINGOBJECT o
    LEFT JOIN ZICCLOUDSYNCINGOBJECT f ON o.ZFOLDER = f.Z_PK
    LEFT JOIN ZICCLOUDSYNCINGOBJECT a ON f.ZOWNER = a.Z_PK
    WHERE o.ZNOTEDATA IS NOT NULL
      AND (o.ZMARKEDFORDELETION IS NULL OR o.ZMARKEDFORDELETION = 0)
      AND (f.ZTITLE2 IS NULL OR f.ZTITLE2 <> '{_TRASH}')"""

_ALL_SQL = f"SELECT {_COLS} {_FROM} ORDER BY o.Z_PK DESC"
_SEARCH_SQL = (
    f"SELECT {_COLS} {_FROM} "
    r"AND (o.ZTITLE1 LIKE ? ESCAPE '\' OR o.ZSNIPPET LIKE ? ESCAPE '\') "
    "ORDER BY o.Z_PK DESC"
)


def _escape_like(term: str) -> str:
    r"""Escape LIKE wildcards so a user's ``%``/``_`` is literal (ESCAPE ``\``)."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _store_uuid(conn) -> str:
    row = conn.execute("SELECT Z_UUID FROM Z_METADATA LIMIT 1").fetchone()
    return row[0] if row and row[0] else ""


def _note_pointer(row, uuid: str) -> Pointer:
    """(Z_PK, title, snippet, pinned, locked, folder_name, account) → note Pointer.

    id is the x-coredata URL AppleScript returns for the same note (so a note has ONE id
    across both backends — the @integration cross-check asserts it). Pinned/locked ride
    as a prefix on the summary (Pointer has no dedicated flag field). folder is
    "Account / Folder"."""
    pk, title, snippet, pinned, locked, folder_name, account = row
    prefix = ("📌 " if pinned else "") + ("🔒 " if locked else "")
    label = snippet or title or ""
    folder = " / ".join(x for x in (account, folder_name) if x) or None
    return Pointer(
        id=f"x-coredata://{uuid}/ICNote/p{pk}",
        summary=clean_summary(prefix + label) or "(untitled note)",
        deeplink="",
        folder=folder,
    )


class NotesAdapter:
    def get_pointers(self, query: str) -> list[Pointer]:
        """Search notes by title/snippet (sqlite, read-only), newest first. `query` a
        substring. Falls back to the AppleScript title search on missing FDA / drift."""
        q = query.strip()
        if not q:
            raise ValueError("notes read needs a title substring (got an empty query)")
        like = f"%{_escape_like(q)}%"

        def sqlite(conn):
            uuid = _store_uuid(conn)
            rows = conn.execute(_SEARCH_SQL, (like, like)).fetchall()
            return [_note_pointer(r, uuid) for r in rows][:MAX_NOTES]

        return read_via_sqlite(
            NOTESTORE,
            _FINGERPRINT,
            sqlite,
            fallback=lambda: _parse(run_osascript(_SEARCH, q))[:MAX_NOTES],
            immutable=True,  # read past Notes' lock; see module note on WAL staleness
        )

    def get_all(self) -> list[Pointer]:
        """Every live note (excludes Recently Deleted + tombstoned) as account-qualified
        pointers (sqlite, read-only, newest first). Folder is "Account / Folder". Falls
        back to the AppleScript enumeration on missing FDA / schema drift."""

        def sqlite(conn):
            uuid = _store_uuid(conn)
            return [_note_pointer(r, uuid) for r in conn.execute(_ALL_SQL).fetchall()]

        return read_via_sqlite(
            NOTESTORE,
            _FINGERPRINT,
            sqlite,
            fallback=lambda: _parse_all(run_osascript(_LIST_ALL)),
            immutable=True,  # read past Notes' lock; see module note on WAL staleness
        )

    def get_bodies(self, ids: list[str]) -> list[dict]:
        """Hydrate plaintext bodies for up to MAX_BODIES ids → [{"id", "body"}].

        Each body is sanitized and per-item bounded through ``clean_body`` (#52): a
        control-char-laden body can't corrupt the client and a long one is truncated
        with a marker. A single pathological body (over the hard cap) is caught here so
        it downgrades to a per-item notice instead of failing the whole batch. Unknown
        ids are silently skipped; the caller diffs returned vs requested ids.
        """
        if not ids:
            raise ValueError("note_bodies needs at least one note id")
        if len(ids) > MAX_BODIES:
            raise ValueError(
                f"note_bodies accepts at most {MAX_BODIES} ids per call; "
                f"got {len(ids)} — chunk your requests"
            )
        out = []
        for rec in _parse_bodies(run_osascript(_BODIES, *ids)):
            try:
                body = clean_body(rec["body"])
            except OutputOverflow as e:
                body = f"[not hydrated: {e}]"
            out.append({"id": rec["id"], "body": body})
        return out

    def delete(
        self, ident: str, expect_title: str | None = None, dry_run: bool = False
    ) -> Pointer | None:
        """Delete a note by id → Recently Deleted (recoverable).

        When expect_title is given, the note is deleted only if its current title
        matches — content-verify first by passing it. Without it, delete-by-id fires
        immediately (ids are globally unique, but a stale id deletes the wrong note).

        ``dry_run=True`` runs the SAME id + expect_title guard as the real delete — in
        AppleScript, so the case/whitespace semantics are byte-identical — but returns
        the pointer that WOULD be deleted instead of deleting it. A title mismatch or
        unknown id raises exactly as the real delete would, so the preview can never
        disagree with the real op (#54).
        """
        if not ident.strip():
            raise ValueError("delete_note needs a note id")
        if dry_run:
            args = (ident,) if expect_title is None else (ident, expect_title)
            title = run_osascript(_PREVIEW_DELETE, *args)
            return Pointer(
                id=ident,
                summary=clean_summary(title) or "(untitled note)",
                deeplink="",
            )
        if expect_title is not None:
            run_osascript(_DELETE, ident, expect_title)
        else:
            run_osascript(_DELETE, ident)
        return None
