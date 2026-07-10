"""Notes adapter — Notes.app via osascript (Automation TCC). Read-only v1: title search.

Notes is scriptable. ``get_pointers(query)`` searches notes whose name (title) contains
the query. ``Pointer.id`` is the note's ``x-coredata://…`` id; ``summary`` is the title.
``deeplink`` is empty — Notes has no verified open-by-id URL scheme, so id + title are
the handle. Pointers, not bodies (the body is never fetched). Capped and osascript-
timeout-bounded; user input goes via argv (no script injection).
"""

from __future__ import annotations

from ..contracts import Pointer
from ..runtime import OutputOverflow, clean_body, clean_summary, run_osascript

MAX_NOTES = 25
MAX_BODIES = 50

_SEARCH = """on run argv
  set q to item 1 of argv
  set out to ""
  tell application "Notes"
    repeat with n in (notes whose name contains q)
      set out to out & (id of n) & tab & (name of n) & linefeed
    end repeat
  end tell
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
  tell application "Notes"
    repeat with theId in argv
      try
        set noteBody to plaintext of note id theId
        set out to out & theId & us & noteBody & rs
      end try
    end repeat
  end tell
  return out
end run"""

# delete_note: moves the note to Recently Deleted (recoverable ~30 days). Notes ids are
# x-coredata:// URLs that embed the store id → globally unique, so delete-by-id targets
# exactly one note. expect_title (optional argv[2]) guards against stale/wrong ids: the
# script errors before deleting if the live title doesn't match.
_DELETE = """on run argv
  tell application "Notes"
    set n to note id (item 1 of argv)
    if (count of argv) > 1 then
      if (name of n) is not (item 2 of argv) then
        error "note title does not match expect_title"
      end if
    end if
    delete n
  end tell
end run"""

# dry_run preview (#54): the real-delete guard EXACTLY — same `note id` lookup and same
# AppleScript `is not` title comparison as _DELETE (case-insensitive + whitespace-
# significant) — minus the `delete n`, plus `return name of n`. The expect_title check
# MUST run here, not in Python: a Python `!=` on the title diverged from AppleScript on
# case AND whitespace, so the preview could report the opposite of what the real delete
# does (#54 review). Errors on an unknown id or a title mismatch, exactly as _DELETE.
_PREVIEW_DELETE = """on run argv
  tell application "Notes"
    set n to note id (item 1 of argv)
    if (count of argv) > 1 then
      if (name of n) is not (item 2 of argv) then
        error "note title does not match expect_title"
      end if
    end if
    return name of n
  end tell
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


class NotesAdapter:
    def get_pointers(self, query: str) -> list[Pointer]:
        """query: a title substring to find."""
        q = query.strip()
        if not q:
            raise ValueError("notes read needs a title substring (got an empty query)")
        return _parse(run_osascript(_SEARCH, q))[:MAX_NOTES]

    def get_all(self) -> list[Pointer]:
        """Every note (excludes Recently Deleted) as account-qualified pointers.

        Folder is "Account / Folder". No cap: a very large library can exceed the
        osascript 30s timeout, in which case the whole call fails (no partial results).
        """
        return _parse_all(run_osascript(_LIST_ALL))

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
