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

import contextlib
import gzip
import html
import zlib
from pathlib import Path

from ..contracts import NoteData, Pointer
from ..runtime import (
    NativeError,
    OutputOverflow,
    VerificationFailed,
    body_file,
    read_via_sqlite,
    run_osascript,
    verify_persisted,
)
from ..text import clean_body, clean_summary, fold_text, norm_text

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
        "ZNOTEDATA",  # note-row discriminator AND fk → ZICNOTEDATA.Z_PK (body decode)
        "ZMARKEDFORDELETION",  # tombstone flag
        "ZISPINNED",
        "ZISPASSWORDPROTECTED",  # locked
        "ZTITLE2",  # folder name (on a folder row)
        "ZOWNER",  # folder → account row's Z_PK
        "ZNAME",  # account name (on an account row)
    },
    "Z_METADATA": {"Z_UUID"},  # the store UUID for the x-coredata:// id
}

# get_bodies has its OWN fingerprint (#60 review): the body table is NOT in the
# enumeration fingerprint above, so a drift in ZICNOTEDATA/ZDATA degrades ONLY the body
# read — the (independent) get_all/get_pointers enumeration keeps working on sqlite.
_BODY_FINGERPRINT = {
    "ZICCLOUDSYNCINGOBJECT": {"Z_PK", "ZNOTEDATA"},  # the note → body join
    "ZICNOTEDATA": {"Z_PK", "ZDATA"},  # the gzip+protobuf note body
    "Z_METADATA": {"Z_UUID"},  # the store UUID, to reject foreign/stale ids
}

# All templates carry `with timeout` (#56): bound the Apple Events so an orphaned
# osascript self-terminates instead of pinning Notes.
#
# There is no AppleScript title-SEARCH template: search folds diacritics/smart
# punctuation (#64), which `whose name contains` can't express, so both backends
# enumerate (_LIST_ALL / _ALL_SQL) and post-filter in Python (see get_pointers).

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

# verify-fallback title read (no FDA path): name of a note by id.
_TITLE_BY_ID = """on run argv
  with timeout of 120 seconds
  tell application "Notes"
    return name of note id (item 1 of argv)
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

# create_note: make a note (body from the tempfile as «class utf8» — never interpolated,
# so markup/newlines/unicode can't inject). folder "" → the default folder; else locate
# a folder by name across accounts, erroring on 0 (not found) or >1 (ambiguous). Returns
# the new note's x-coredata id — the canonical id (same one _LIST_ALL returns). No post-
# make mutation, so nothing to roll back.
_CREATE_NOTE = """on run argv
  set folderName to item 1 of argv
  set bodyText to (read (POSIX file (item 2 of argv)) as «class utf8»)
  with timeout of 120 seconds
  tell application "Notes"
    if folderName is "" then
      set newNote to make new note with properties {body:bodyText}
    else
      set matches to {}
      repeat with acc in accounts
        repeat with f in folders of acc
          if name of f is folderName then set end of matches to f
        end repeat
      end repeat
      if (count of matches) is 0 then error "no folder named " & folderName
      if (count of matches) > 1 then ¬
        error "folder name is ambiguous across accounts: " & folderName
      set newNote to make new note at (item 1 of matches) ¬
        with properties {body:bodyText}
    end if
    return id of newNote
  end tell
  end timeout
end run"""

# update_note: full-replace a note's content by id (body from the tempfile as «class
# utf8»). `note id` errors on an unknown id (surfaces as a typed NativeError). Returns
# the id (Z_PK is stable across a body edit, so it's unchanged — verify asserts it).
_UPDATE_NOTE = """on run argv
  set noteId to item 1 of argv
  set bodyText to (read (POSIX file (item 2 of argv)) as «class utf8»)
  with timeout of 120 seconds
  tell application "Notes"
    set n to note id noteId
    set body of n to bodyText
    return id of n
  end tell
  end timeout
end run"""


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


def _compose_html(title: str, body: str) -> str:
    """Plaintext title + body → note HTML `body`; injection-safe via escaping.

    Everything is `html.escape`d so user markup renders as literal text (never
    HTML/script). The title is the first line (how Notes derives ZTITLE1); body
    newlines become <br>.
    """
    title_html = html.escape(title)
    body_html = "<br>".join(html.escape(line) for line in body.split("\n"))
    return f"<div>{title_html}</div><div>{body_html}</div>"


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
# Live consistency: reads open mode=ro WITHOUT immutable=1. NoteStore is a WAL-mode
# database (there is a -wal alongside it), and WAL permits concurrent readers, so a
# read-only connection opens fine while Notes.app is running — verified on-device. The
# #60 design originally used immutable=1 (per the sirmews recipe) to "read past the
# lock", but immutable IGNORES the -wal: it pins a stale point-in-time snapshot, so a
# just-created note is missed AND a just-deleted note lingers (both surfaced against the
# real store once FDA enabled the sqlite path). mode=ro reads the -wal → live state,
# matching AppleScript (and matching Messages, #59). If a read ever can't open, the
# adapter's AppleScript fallback still sees current state — so mode=ro is strictly safer
# than a silently-stale immutable snapshot.
_TRASH = "Recently Deleted"
_COLS = """o.Z_PK, o.ZTITLE1, o.ZSNIPPET, o.ZISPINNED, o.ZISPASSWORDPROTECTED,
       f.ZTITLE2, a.ZNAME"""
# A real, user-visible note always belongs to a folder. A row with ZNOTEDATA set but
# ZFOLDER NULL is an orphaned/deleted remnant (empty title, no container) that
# AppleScript never enumerates — but it is NOT tombstoned (ZMARKEDFORDELETION=0) and its
# NULL folder slips past the trash-name check, so without an explicit ZFOLDER filter the
# sqlite path leaks it (real store: 25 such orphans surfaced once FDA enabled the sqlite
# path). Require a folder so sqlite matches what AppleScript shows.
_FROM = f"""FROM ZICCLOUDSYNCINGOBJECT o
    LEFT JOIN ZICCLOUDSYNCINGOBJECT f ON o.ZFOLDER = f.Z_PK
    LEFT JOIN ZICCLOUDSYNCINGOBJECT a ON f.ZOWNER = a.Z_PK
    WHERE o.ZNOTEDATA IS NOT NULL
      AND o.ZFOLDER IS NOT NULL
      AND (o.ZMARKEDFORDELETION IS NULL OR o.ZMARKEDFORDELETION = 0)
      AND (f.ZTITLE2 IS NULL OR f.ZTITLE2 <> '{_TRASH}')"""

# One enumeration query; search folds in Python (no _SEARCH_SQL LIKE — SQLite LIKE is
# ASCII-only, so it can't do the diacritic/smart-punctuation fold #64 needs).
_ALL_SQL = f"SELECT {_COLS} {_FROM} ORDER BY o.Z_PK DESC"


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


# --- note-body decode (#60 commit 2): gzip + protobuf ZDATA --------------------------
# ZICNOTEDATA.ZDATA is a gzip-compressed protobuf (Apple's NoteStoreProto). The plain
# text sits at a fixed field path: NoteStoreProto.document(2) → Document.note(3) →
# Note.note_text(2, a string). We parse the protobuf WIRE FORMAT precisely (varint tags
# + length-delimited nesting) and follow 2→3→2 — not a "longest string" byte heuristic —
# so a real note decodes exactly and anything malformed DECLINES (returns None), never
# fabricates. get_bodies gap-fills a decline via AppleScript, so there's no regression.
# ponytail: attribute runs / tables / attachments are ignored — we want plain text; add
# a richer walk only if a caller needs formatting.

# the field path from the message root to the plain-text string
_NOTE_TEXT_PATH = (2, 3, 2)  # document → note → note_text


def _read_varint(data: bytes, pos: int) -> tuple[int, int]:
    """Decode a base-128 varint at ``pos``; return (value, next_pos). Raises ValueError
    on a truncated/over-long varint so the caller declines rather than mis-reads."""
    result = shift = 0
    while True:
        if pos >= len(data) or shift > 63:  # truncated, or a >10-byte (bogus) varint
            raise ValueError("bad varint")
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7


def _pb_field(data: bytes, want: int) -> bytes | None:
    """The bytes of the FIRST length-delimited (wire type 2) field numbered ``want`` in
    a protobuf message ``data`` — skipping other fields by wire type. Returns None if
    absent; raises ValueError on a malformed stream (truncation / unknown wire type)."""
    pos, n = 0, len(data)
    while pos < n:
        tag, pos = _read_varint(data, pos)
        field, wire = tag >> 3, tag & 7
        if wire == 2:  # length-delimited: bytes/string/nested message
            length, pos = _read_varint(data, pos)
            if pos + length > n:
                raise ValueError("length-delimited field overruns the message")
            chunk = data[pos : pos + length]
            pos += length
            if field == want:
                return chunk
        elif wire == 0:  # varint
            _, pos = _read_varint(data, pos)
        elif wire == 1:  # 64-bit
            pos += 8
        elif wire == 5:  # 32-bit
            pos += 4
        else:  # 3/4 = deprecated groups → can't skip reliably; decline
            raise ValueError(f"unsupported protobuf wire type {wire}")
    return None


def _decode_note_data(blob) -> str | None:
    """Best-effort plain text of a note from its gzip+protobuf ``ZDATA`` blob.

    Declines (None) on a non-bytes input, a non-gzip / corrupt payload, or a protobuf
    that lacks the note-text field — the caller prefers AppleScript for those, so a
    mis-parse must NEVER fabricate a body. Text is read as UTF-8 (errors replaced)."""
    if not isinstance(blob, (bytes, bytearray)):
        return None
    if len(blob) < 2 or blob[0] != 0x1F or blob[1] != 0x8B:  # gzip magic
        return None
    try:
        msg = gzip.decompress(blob)
    except (OSError, EOFError, zlib.error, ValueError):
        return None
    try:
        for field in _NOTE_TEXT_PATH:
            if msg is None:
                return None
            msg = _pb_field(msg, field)
    except ValueError:
        return None  # malformed wire format → decline
    return msg.decode("utf-8", errors="replace") if msg is not None else None


def _pk_from_id(ident: str) -> int | None:
    """The Z_PK from an ``x-coredata://…/ICNote/p<N>`` id; None if not that shape."""
    _head, sep, tail = ident.rpartition("/p")
    return int(tail) if sep and tail.isdigit() else None


def _hydrate_body(body: str) -> str:
    """Bound a note body for output (#52): ``clean_body`` truncates + control-strips; a
    body over the hard cap downgrades to a per-item notice, not a batch failure."""
    try:
        return clean_body(body)
    except OutputOverflow as e:
        return f"[not hydrated: {e}]"


# get-by-id body: join the note to its ZICNOTEDATA row for the gzip+protobuf blob.
_BODY_SQL = (
    "SELECT o.Z_PK, d.ZDATA FROM ZICCLOUDSYNCINGOBJECT o "
    "JOIN ZICNOTEDATA d ON o.ZNOTEDATA = d.Z_PK WHERE o.Z_PK IN ({placeholders})"
)


# verify read-back: the note's title by id. Its OWN small fingerprint — a drift here
# degrades only the verify read (falls back to AppleScript), like the body read.
_TITLE_FINGERPRINT = {
    "ZICCLOUDSYNCINGOBJECT": {"Z_PK", "ZTITLE1"},
    "Z_METADATA": {"Z_UUID"},
}
_TITLE_SQL = "SELECT ZTITLE1 FROM ZICCLOUDSYNCINGOBJECT WHERE Z_PK = ?"


def _title_key(title: str | None) -> str | None:
    """Compare-key for a note title. Apple Notes derives ZTITLE1 from the HTML-rendered
    first line, which collapses whitespace (leading/trailing trimmed, internal runs and
    tabs/newlines → one space). norm_text only does NFC/LF, so collapse whitespace too —
    otherwise verify false-fails a correct write whose title had e.g. a trailing space.
    """
    n = norm_text(title)
    return " ".join(n.split()) if n is not None else None


def _verify_note(
    persisted_title: str | None,
    ident: str,
    data: NoteData,
    *,
    expected_id: str | None = None,
) -> None:
    """Verify-after-write (#49): the note must be re-readable by the returned id with
    the requested title; on update the id must survive the edit. Raises
    VerificationFailed naming the mismatch — the caller must not reuse the id. Body
    persistence is NOT checked here; it's covered only by the manual integration tests.
    """
    if persisted_title is None:
        raise VerificationFailed(
            f"note {ident!r} could not be re-read after the write — it did not persist "
            "(a fabricated id or an iCloud rollback). Do not trust the id."
        )
    expected: dict[str, object] = {"title": _title_key(data.title)}
    actual: dict[str, object] = {"title": _title_key(persisted_title)}
    if expected_id is not None:  # update: Z_PK is stable, so the id must be unchanged
        expected["id"] = expected_id
        actual["id"] = ident
    verify_persisted("note", expected, actual)


class NotesAdapter:
    def get_pointers(self, query: str) -> list[Pointer]:
        """Search notes by title/snippet (sqlite, read-only), newest first. `query` a
        substring, matched diacritic- and smart-punctuation-insensitively via fold_text
        (#64): "cafe" finds "café", ASCII "'" finds a U+2019 apostrophe. That fold can't
        be expressed in SQL LIKE (ASCII-only), so the match is a Python post-filter over
        the same rows get_all reads — bounded by library size (title/snippet strings).
        Falls back to the AppleScript enumeration, folded identically, on missing FDA /
        drift. ponytail: O(all-notes) fold per search; add a LIKE prefilter for the
        common ASCII case only if a huge library makes it show up."""
        # Guard on the FOLDED value, not the raw query (#64 review): a non-empty query
        # made only of punctuation/combining marks folds to "" or " " (e.g. a lone
        # diaeresis "¨" NFKD-decomposes to a space; a bare combining accent to nothing).
        # A pre-fold `if not query` would let those through, and then `needle in title`
        # matches nearly every note — the opposite of a search. Guard post-fold instead.
        needle = fold_text(query).strip()
        if not needle:
            raise ValueError("notes read needs a title substring (got an empty query)")

        def sqlite(conn):
            uuid = _store_uuid(conn)
            out = []
            for r in conn.execute(_ALL_SQL):  # r: pk, title, snippet, pinned, locked...
                if needle in fold_text(r[1]) or needle in fold_text(r[2]):
                    out.append(_note_pointer(r, uuid))
                    if len(out) >= MAX_NOTES:
                        break
            return out

        def fallback():
            # degraded path folds the same way, matching on the RAW title only (no
            # snippet — _LIST_ALL doesn't carry one). Filter on the raw title field
            # (`parts[2]`, as _parse_all reads it) BEFORE building Pointers — NOT on
            # the Pointer.summary, which for an untitled note is the display placeholder
            # "(untitled note)" and would spuriously match "note"/"untitled" (#64
            # review). An empty raw title folds to "" and matches nothing, like the
            # sqlite path (raw ZTITLE1 → "") and the old `whose name contains`.
            kept = []
            for line in run_osascript(_LIST_ALL).splitlines():
                if not line.strip():
                    continue
                parts = line.split("\t")
                title = parts[2] if len(parts) > 2 else ""
                if needle in fold_text(title):
                    kept.append(line)
            return _parse_all("\n".join(kept))[:MAX_NOTES]

        return read_via_sqlite(
            NOTESTORE,
            _FINGERPRINT,
            sqlite,
            fallback=fallback,
            immutable=False,  # mode=ro reads the -wal (live); see module note
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
            immutable=False,  # mode=ro reads the -wal (live); see module note
        )

    def get_bodies(self, ids: list[str]) -> list[dict]:
        """Hydrate plaintext bodies for up to MAX_BODIES ids → [{"id", "body"}].

        sqlite-primary: decode each note's gzip+protobuf ZDATA (fast, no Notes launch).
        Any id the decoder can't handle (a non-x-coredata id, a note not in the store,
        or an undecodable body) is GAP-FILLED via AppleScript, so this never returns
        fewer bodies than the AppleScript path alone would. Missing FDA / schema drift →
        the whole batch degrades to AppleScript. Each body is bounded via ``clean_body``
        (#52): an over-hard-cap body downgrades to a per-item notice, not a batch fail.
        Unknown ids are silently skipped; the caller diffs returned vs requested.
        """
        if not ids:
            raise ValueError("note_bodies needs at least one note id")
        if len(ids) > MAX_BODIES:
            raise ValueError(
                f"note_bodies accepts at most {MAX_BODIES} ids per call; "
                f"got {len(ids)} — chunk your requests"
            )

        def sqlite(conn) -> list[dict]:
            # Only map ids belonging to THIS store: the bare pN is not unique across
            # stores, so a stale/foreign id with a colliding pN must NOT resolve to a
            # local note's body (#60 review). Match the full x-coredata prefix.
            prefix = f"x-coredata://{_store_uuid(conn)}/ICNote/p"
            pk_to_id = {
                pk: i
                for i in ids
                if i.startswith(prefix) and (pk := _pk_from_id(i)) is not None
            }
            hydrated: dict[str, str] = {}
            if pk_to_id:
                ph = ",".join("?" for _ in pk_to_id)
                rows = conn.execute(
                    _BODY_SQL.format(placeholders=ph), tuple(pk_to_id)
                ).fetchall()
                for zpk, zdata in rows:
                    body = _decode_note_data(zdata)
                    if body is not None:
                        hydrated[pk_to_id[zpk]] = _hydrate_body(body)
            # gap-fill what sqlite couldn't decode via AppleScript. BEST-EFFORT: if the
            # gap-fill raises (e.g. Automation not granted), keep the bodies sqlite
            # already decoded rather than failing the whole batch (#60 review).
            rest = [i for i in ids if i not in hydrated]
            if rest:
                with contextlib.suppress(NativeError):
                    for rec in self._applescript_bodies(rest):
                        hydrated.setdefault(rec["id"], rec["body"])
            return [{"id": i, "body": hydrated[i]} for i in ids if i in hydrated]

        return read_via_sqlite(
            NOTESTORE,
            _BODY_FINGERPRINT,
            sqlite,
            fallback=lambda: self._applescript_bodies(ids),
            immutable=False,  # mode=ro reads the -wal (live); see module note
        )

    def _read_title_by_id(self, ident: str) -> str | None:
        """The note's ZTITLE1 by x-coredata id (sqlite primary, AppleScript fallback);
        None if the id isn't this store's or the note isn't found."""

        def sqlite(conn) -> str | None:
            prefix = f"x-coredata://{_store_uuid(conn)}/ICNote/p"
            if not ident.startswith(prefix):
                return None  # foreign/stale id — a colliding pN must not resolve
            pk = _pk_from_id(ident)
            if pk is None:
                return None
            row = conn.execute(_TITLE_SQL, (pk,)).fetchone()
            return row[0] if row else None

        return read_via_sqlite(
            NOTESTORE,
            _TITLE_FINGERPRINT,
            sqlite,
            fallback=lambda: self._applescript_title(ident),
            immutable=False,
        )

    def snapshot(self, ident: str) -> Pointer | None:
        """The note's current pointer by id (title only), or None if absent — audit
        before-state. Pointer-level suffices for manual undo; a full-field snapshot is a
        non-breaking later enhancement."""
        title = self._read_title_by_id(ident)
        if title is None:
            return None
        return Pointer(
            id=ident,
            summary=clean_summary(title) or "(untitled note)",
            deeplink="",
        )

    def _applescript_title(self, ident: str) -> str | None:
        """Fallback title read (no FDA): `name of note id`. Unknown id → the osascript
        error surfaces as a typed NativeError."""
        return run_osascript(_TITLE_BY_ID, ident) or None

    def _applescript_bodies(self, ids: list[str]) -> list[dict]:
        """The osascript body reader (fallback + gap-fill path). Unknown ids skipped;
        each body ``clean_body``-bounded, a huge one downgraded to a per-item notice."""
        if not ids:
            return []
        return [
            {"id": rec["id"], "body": _hydrate_body(rec["body"])}
            for rec in _parse_bodies(run_osascript(_BODIES, *ids))
        ]

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

    def create(self, data: NoteData) -> Pointer:
        """Create a note from plaintext title+body; return its stable x-coredata id.

        Body is written to a 0600 tempfile and read by AppleScript as «class utf8»
        (never interpolated). folder=None → the default folder; a name is resolved
        across accounts (unknown/ambiguous → a loud error). The returned id is
        verified by a re-read (#49) before it's trusted.
        """
        html_body = _compose_html(data.title, data.body)
        with body_file(html_body) as path:
            ident = run_osascript(_CREATE_NOTE, data.folder or "", path).strip()
        _verify_note(self._read_title_by_id(ident), ident, data)
        return Pointer(
            id=ident,
            summary=clean_summary(data.title) or "(untitled note)",
            deeplink="",
            folder=data.folder,
        )

    def update(self, ident: str, data: NoteData) -> Pointer:
        """Full-replace a note's title+body by id; the id must survive (verified, #49).

        `data.folder` is IGNORED on update — moving a note between folders is a separate
        op. Body transport and verify match `create`.
        """
        if not ident.strip():
            raise ValueError("update_note needs a note id")
        html_body = _compose_html(data.title, data.body)
        with body_file(html_body) as path:
            ident_after = run_osascript(_UPDATE_NOTE, ident, path).strip()
        _verify_note(
            self._read_title_by_id(ident_after),
            ident_after,
            data,
            expected_id=ident,
        )
        return Pointer(
            id=ident_after,
            summary=clean_summary(data.title) or "(untitled note)",
            deeplink="",
        )
