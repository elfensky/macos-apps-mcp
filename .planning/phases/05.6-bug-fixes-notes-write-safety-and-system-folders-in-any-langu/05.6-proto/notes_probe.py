"""Phase 05.6 owner probe sitting (D-23): Notes write safety (#500), system folders
in another language (#501) and the scoped Drafts query (#521). A throwaway probe.

Standard library only: /usr/bin/osascript and read-only sqlite3. Run it as the
INSTALLED BUNDLE (its Automation and Full Disk Access grants):

    open -g -n -W --stdout R/<name>.txt --stderr R/<name>.err \
        -a /Applications/macos-apps-mcp.app \
        --args -E -s -P <absolute path to this file> <subcommand> ...

or as a plain process where no grant is needed
(`uv run --no-project python -I <this file> selftest`).

Every printed line goes through say(): counts, booleans, type names, column values
and the ids of scratch notes. Never a note body, never a note title other than a
scratch name, never an address, never a Message-ID. `locked=` is the read of
`password protected of n`.

Scratch rule: a note command takes the note id AND its label. The live name must be
exactly P056-SCRATCH-<LABEL>, else the command refuses before it does anything else.
A draft is found by its subject P056-SCRATCH-<LABEL> in the Mail index, never by an
id on the command line. This file has no Mail write.

Subcommands:
  selftest                         no app, no database, no child process
  compile                          osacompile on every script; it runs no script
  notes-find                       ids and labels of the scratch notes
  note-read ID LABEL [--save-html FILE]
  store-note ID LABEL              NoteStore columns of that note (read-only)
  notes-trash                      the trash folder's name: AppleScript and store
  note-set-body ID LABEL own|fixed WRITE: own = its own HTML (COPY only),
                                   fixed = one fixed line (LOCKED only)
  note-from-html FILE              WRITE: a NEW note from saved scratch HTML; no
                                   note that exists changes, so it takes no id:
                                   the file must open with a scratch name
  note-delete ID LABEL             WRITE: move the scratch note to Recently Deleted
  mail-leaves ACCOUNT-NAME         root-level mailbox names of ONE account; these
                                   lines stay in the evidence folder
  drafts-find [--label L --wait S] scratch drafts in the Mail index
  drafts-whose ROWID [--runs N]    `whose message id is` on that draft's own
                                   per-account Drafts mailbox, N single runs
"""

from __future__ import annotations

import argparse
import contextlib
import html
import io
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import unicodedata
from collections import Counter
from pathlib import Path
from urllib.parse import quote, unquote

MARKER = "P056-SCRATCH"
WORDS = (
    "P056BOLD",
    "P056LINK",
    "P056CHK1",
    "P056CHK2",
    "P056BULL",  # a plain bullet list: the control for a checklist marker
    "P056CELL",
    "P056BODY",
    "P056WRITTEN",
)
FIXED_BODY = f"<div>{MARKER}-LOCKED</div><div>{WORDS[-1]}</div>"
NOTESTORE = (
    Path.home() / "Library/Group Containers/group.com.apple.notes/NoteStore.sqlite"
)
OSASCRIPT = "/usr/bin/osascript"
OSACOMPILE = "/usr/bin/osacompile"
GOOGLE_ROOTS = ("[Gmail]", "[Google Mail]")
US, RS = "\x1f", "\x1e"
_OSA_TIMEOUT = 150  # host-side cap; every app block inside is `with timeout of 120`
_LABEL = re.compile(r"[A-Z0-9]{1,16}")
_NOTE_ID = re.compile(r"x-coredata://([0-9A-Fa-f-]{36})/ICNote/p(\d+)")
_MID = re.compile(r"<[^<>\s]+@[^<>\s]+>")
_ADDR = re.compile(r"[\w.%+-]+@[\w.-]+")
_QUOTED = re.compile(r'"((?:[^"\\]|\\.)*)"|“([^”]*)”|["“].*')
_CORE_ID = re.compile(r"x-coredata://[0-9A-Fa-f-]{36}/IC[A-Za-z]+/p\d+")
_ATTR_VALUE = re.compile(r'"[^"]*"|\'[^\']*\'')
_SUFFIX = re.compile(r"\.[a-z0-9]{1,8}")
_CLASS = re.compile(r'\bclass="([^"]*)"')
_PLAIN = re.compile(r"true|false|\d+|missing|err:-?\w+")
_TAG = re.compile(r"<(/?)([A-Za-z][A-Za-z0-9]*)([^>]*)>")
_VOID = frozenset({"br", "img", "meta", "hr", "input", "col", "link"})
_FAILED = re.compile(r"err:-?\w+")


class Refuse(Exception):
    """A safety check failed BEFORE any write."""


def redact(text: str) -> str:
    """One line of at most 300 characters with no Message-ID, no address and no
    quoted text. Quoted text stays only when it is EXACTLY a scratch name or a Core
    Data id. A quote with no partner masks the rest of the line."""

    def quoted(m: re.Match) -> str:
        inner = m.group(1) if m.group(1) is not None else m.group(2)
        keep = inner is not None and (
            label_of(inner) != "?" or _CORE_ID.fullmatch(inner)
        )
        return m.group(0) if keep else '"..."'

    text = " ".join(text.split())
    text = _MID.sub("<mid>", text)
    text = _ADDR.sub("<addr>", text)
    return _QUOTED.sub(quoted, text)[:300]


def say(line: str) -> None:
    print(redact(line), flush=True)


# --- the scratch guard (pure) ------------------------------------------------------


def scratch_name(label: str) -> str:
    """The exact name a scratch note must have; Refuse for a bad label."""
    if not _LABEL.fullmatch(label):
        raise Refuse("the label must be 1 to 16 characters of A-Z and 0-9")
    return f"{MARKER}-{label}"


def label_of(name: str) -> str:
    """The label of a scratch name; `?` for every other text (never the text)."""
    head, sep, label = name.partition(MARKER + "-")
    return label if sep and not head and _LABEL.fullmatch(label) else "?"


def split_note_id(note_id: str) -> tuple[str, int]:
    m = _NOTE_ID.fullmatch(note_id)
    if not m:
        raise Refuse("the note id must be x-coredata://<store uuid>/ICNote/p<number>")
    return m.group(1), int(m.group(2))


def scratch_html(markup: str) -> str:
    """The scratch name that opens this HTML; Refuse when its first text is not one."""
    for part in re.sub(r"<[^>]*>", "\n", markup).splitlines():
        text = html.unescape(part).strip()
        if text:
            if label_of(text) == "?":
                break
            return text
    raise Refuse("the HTML does not start with a scratch name")


# --- HTML census (pure): tag names, attribute names, never text ---------------------


def tag_counts(body: str) -> str:
    c = Counter(m.group(2).lower() for m in _TAG.finditer(body) if not m.group(1))
    return ",".join(f"{t}:{n}" for t, n in sorted(c.items())) or "none"


def attr_names(body: str) -> str:
    names = {
        a.lower()
        for m in _TAG.finditer(body)
        for a in re.findall(r"([A-Za-z-]+)=", _ATTR_VALUE.sub("", m.group(3)))
    }
    return ",".join(sorted(names)) or "none"


def class_values(body: str) -> str:
    return ",".join(sorted(set(_CLASS.findall(body)))) or "none"


def url_schemes(body: str) -> str:
    found = re.findall(r'\b(src|href)="([A-Za-z][A-Za-z0-9+.-]*):', body)
    c = Counter(f"{attr.lower()}:{scheme.lower()}" for attr, scheme in found)
    return ",".join(f"{k}={n}" for k, n in sorted(c.items())) or "none"


def word_context(body: str, word: str) -> str:
    """The open tags around the first hit of `word`, outermost first. Each tag
    carries its own class value (`ul.<class>`), so a class belongs to one item: a
    checklist line and a bullet line can then be told apart (D-03)."""
    at = body.find(word)
    if at < 0:
        return "absent"
    tags: list[str] = []  # the open tag names
    shown: list[str] = []  # the same tags, each with its class value
    for m in _TAG.finditer(body[:at]):
        tag = m.group(2).lower()
        if tag in _VOID or m.group(3).rstrip().endswith("/"):
            continue
        if not m.group(1):
            found = _CLASS.search(m.group(3))
            classes = found.group(1).split() if found else []
            tags.append(tag)
            shown.append(".".join([tag, *classes]))
        elif tag in tags:
            cut = len(tags) - 1 - tags[::-1].index(tag)
            del tags[cut:], shown[cut:]
    return ">".join(shown[-4:]) or "(no tag)"


# --- mailbox urls (pure) -----------------------------------------------------------


def split_url(url: str) -> tuple[str, str, str]:
    """(scheme, account id, decoded path) of a Mail index mailbox url."""
    scheme, sep, rest = url.partition("://")
    account, _, path = rest.partition("/")
    if not (sep and account and path):
        raise Refuse("the index row has no mailbox url")
    return scheme.lower(), account, unquote(path)


def is_root_level(path: str) -> bool:
    parts = path.split("/")
    return len(parts) == 1 or (len(parts) == 2 and parts[0] in GOOGLE_ROOTS)


def is_drafts(path: str) -> bool:
    return is_root_level(path) and path.rsplit("/", 1)[-1] in ("Drafts", "Draft")


def kind_of(scheme: str, path: str) -> str:
    """The account kind the url shows. IMAP and iCloud look the same here: the
    owner's label on the draft says which one it is."""
    if path.split("/")[0] in GOOGLE_ROOTS:
        return "gmail"
    return scheme if scheme in ("ews", "local") else "imap-or-icloud"


# --- scripts -----------------------------------------------------------------------

# The guard of every script that addresses a note: the live name must equal the
# scratch name EXACTLY (case too). It sits in the same script as the write.
_GUARD = """      set n to note id (item 1 of argv)
      set liveName to name of n
      considering case
        if liveName is not (item 2 of argv) then return "refused"
      end considering
"""


def _prop(field: str, expr: str) -> str:
    """One property read that answers its own native error number."""
    return (
        "      try\n"
        f'        set end of out to "{field}=" & (({expr}) as text)\n'
        "      on error number errNum\n"
        f'        set end of out to "{field}=err:" & errNum\n'
        "      end try\n"
    )


_NOTE_READ = (
    """on run argv
  set us to character id 31
  set rs to character id 30
  set AppleScript's text item delimiters to us
  set out to {}
  with timeout of 120 seconds
    tell application "Notes"
"""
    + _GUARD
    + _prop("locked", "password protected of n")
    + _prop("shared", "shared of n")
    + _prop("container_shared", "shared of (container of n)")
    + _prop("attachments", "count of attachments of n")
    + _prop("attachment_names", "name of attachments of n")
    + _prop("attachment_cids", "content identifier of attachments of n")
    + _prop("attachment_urls", "URL of attachments of n")
    + _prop("body", "body of n")
    + _prop("plaintext", "plaintext of n")
    + """    end tell
  end timeout
  set AppleScript's text item delimiters to rs
  return out as text
end run"""
)

# The {id, name} snapshot per folder is the shape of notes._LIST_ALL (proven here).
_NOTES_FIND = """on run argv
  set us to character id 31
  set rs to character id 30
  set theLines to {}
  with timeout of 120 seconds
    tell application "Notes"
      repeat with acc in accounts
        repeat with f in folders of acc
          set folderId to (id of f) as text
          set {theIds, theNames} to ({id, name} of (notes of f))
          repeat with i from 1 to (count of theIds)
            try
              set noteLine to ((item i of theIds) as text) & us
              set noteLine to noteLine & ((item i of theNames) as text) & us & folderId
              set end of theLines to noteLine
            end try
          end repeat
        end repeat
      end repeat
    end tell
  end timeout
  set AppleScript's text item delimiters to rs
  return theLines as text
end run"""

_FOLDERS = """on run argv
  set us to character id 31
  set rs to character id 30
  set theLines to {}
  with timeout of 120 seconds
    tell application "Notes"
      repeat with acc in accounts
        repeat with f in folders of acc
          try
            set end of theLines to ((id of f) as text) & us & ((name of f) as text)
          end try
        end repeat
      end repeat
    end tell
  end timeout
  set AppleScript's text item delimiters to rs
  return theLines as text
end run"""

_NOTE_SET_BODY = (
    """on run argv
  with timeout of 120 seconds
    tell application "Notes"
"""
    + _GUARD
    + """      if (item 3 of argv) is "own" then
        try
          set newBody to body of n
        on error number errNum
          return "read-err:" & errNum
        end try
      else
        set newBody to (item 4 of argv)
      end if
      set body of n to newBody
      return "written"
    end tell
  end timeout
end run"""
)

_NOTE_DELETE = (
    """on run argv
  with timeout of 120 seconds
    tell application "Notes"
"""
    + _GUARD
    + """      delete n
      return "deleted"
    end tell
  end timeout
end run"""
)

# The read-from-file shape of notes._CREATE_NOTE. It changes no existing note.
_NOTE_FROM_HTML = """on run argv
  set bodyText to (read (POSIX file (item 1 of argv)) as «class utf8»)
  with timeout of 120 seconds
    tell application "Notes"
      set newNote to make new note with properties {body:bodyText}
      return ((id of newNote) as text) & (character id 31) & (name of newNote)
    end tell
  end timeout
end run"""

# One mailbox, addressed by account id and path (Mail facts 8b: never a walk). The
# shape of mail_addressing.MAILBOX_REF and mail_outgoing._SWEEP_DELETE: every value a
# `whose` test compares is a variable set BEFORE the tell block, never `item k of
# argv` inside the test.
_WHOSE = """on run argv
  set acctId to item 1 of argv
  set mbPath to item 2 of argv
  set mid to item 3 of argv
  with timeout of 120 seconds
    tell application "Mail"
      set mb to mailbox mbPath of (first account whose id is acctId)
      return (count of (messages of mb whose message id is mid)) as text
    end tell
  end timeout
end run"""

_ACCOUNT_ID = """on run argv
  set acctName to item 1 of argv
  with timeout of 120 seconds
    tell application "Mail"
      return (id of (first account whose name is acctName)) as text
    end tell
  end timeout
end run"""

SCRIPTS = {
    "note_read": _NOTE_READ,
    "notes_find": _NOTES_FIND,
    "folders": _FOLDERS,
    "note_set_body": _NOTE_SET_BODY,
    "note_delete": _NOTE_DELETE,
    "note_from_html": _NOTE_FROM_HTML,
    "drafts_whose": _WHOSE,
    "account_id": _ACCOUNT_ID,
}
# script name -> its one write statement; selftest proves the guard comes first.
_WRITES = {
    "note_set_body": "set body of n",
    "note_delete": "delete n",
    "note_from_html": "make new note",
}


def _osa(script: str, *args: str) -> tuple[int, str, str]:
    """(exit code, stdout, stderr) of one script; arguments travel as argv."""
    try:
        r = subprocess.run(
            [OSASCRIPT, "-e", script, "--", *args],
            capture_output=True,
            text=True,
            timeout=_OSA_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    return r.returncode, r.stdout.rstrip("\n"), r.stderr.strip()


def _native(err: str) -> str:
    """A native failure as `err:<number> <masked text>`. The text is masked BEFORE
    it is cut: a cut inside a quoted string would print the rest of that string."""
    m = re.search(r"\((-?\d+)\)\s*$", err)
    return f"err:{m.group(1) if m else 'unknown'} {redact(err)[:200]}"


def _failed(value: str) -> bool:
    return bool(_FAILED.fullmatch(value))


# --- read-only stores --------------------------------------------------------------


def _ro(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{quote(str(path))}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _index_path() -> Path:
    dbs = sorted(
        Path.home().glob("Library/Mail/V*/MailData/Envelope Index"),
        key=lambda p: int(p.parts[-3][1:]) if p.parts[-3][1:].isdigit() else -1,
    )
    if not dbs:
        raise Refuse("this Mac has no Mail index")
    return dbs[-1]


def _pk(ident: str) -> int | None:
    m = re.search(r"/p(\d+)$", ident)
    return int(m.group(1)) if m else None


def _trash_folders() -> dict[int, str] | None:
    """Z_PK -> ZTITLE2 of every folder with ZFOLDERTYPE 1; None when unreadable."""
    sql = "SELECT Z_PK, ZTITLE2 FROM ZICCLOUDSYNCINGOBJECT WHERE ZFOLDERTYPE = 1"
    try:
        with contextlib.closing(_ro(NOTESTORE)) as conn:
            return {r["Z_PK"]: r["ZTITLE2"] or "" for r in conn.execute(sql)}
    except sqlite3.Error:
        return None


def _set_or_null(row: sqlite3.Row, col: str) -> str:
    if col not in row.keys():  # noqa: SIM118 (sqlite3.Row: `in` tests values)
        return "no-column"
    return "null" if row[col] is None else "set"


def _flags(row: sqlite3.Row, prefix: str = "") -> None:
    """Every integer ZHAS*/ZIS* column that holds a value, as `column=value`."""
    for col in sorted(row.keys()):
        if col.startswith(("ZHAS", "ZIS")) and isinstance(row[col], int):
            say(f"{prefix}{col}={row[col]}")


# --- Notes commands ----------------------------------------------------------------


def cmd_notes_find(_a) -> int:
    rc, out, err = _osa(_NOTES_FIND)
    if rc:
        say(f"notes-find: {_native(err)}")
        return 1
    trash = _trash_folders()
    rows = [r.split(US) for r in out.split(RS) if r.count(US) == 2]
    found = 0
    for note_id, name, folder_id in rows:
        if not name.startswith(MARKER):
            continue
        found += 1
        where = "unknown"
        if trash is not None:
            where = "yes" if _pk(folder_id) in trash else "no"
        say(f"id={note_id} label={label_of(name)} trash={where}")
    say(f"notes-find: scanned={len(rows)} scratch={found}")
    return 0


def _suffixes(names: str) -> str:
    if not names or _failed(names):
        return names or "none"
    found = (Path(x).suffix.lower() for x in names.split(US))
    return ",".join(
        sorted(
            s if _SUFFIX.fullmatch(s) else ("(other)" if s else "(none)") for s in found
        )
    )


def _filled(values: str) -> str:
    if not values or _failed(values):
        return values or "none"
    items = values.split(US)
    return f"{sum(v not in ('', 'missing value') for v in items)}/{len(items)}"


def cmd_note_read(a) -> int:
    want = scratch_name(a.label)
    split_note_id(a.note_id)
    rc, out, err = _osa(_NOTE_READ, a.note_id, want)
    if rc:
        say(f"note-read: {_native(err)}")
        return 1
    if out == "refused":
        raise Refuse(f"the live name is not {want}")
    f = dict(rec.partition("=")[::2] for rec in out.split(RS) if "=" in rec)
    for name in ("locked", "shared", "container_shared", "attachments"):
        value = f.get(name, "missing")
        say(f"{name}={value if _PLAIN.fullmatch(value) else 'other'}")
    say(f"attachment_suffixes={_suffixes(f.get('attachment_names', ''))}")
    say(f"attachment_cids={_filled(f.get('attachment_cids', ''))}")
    say(f"attachment_urls={_filled(f.get('attachment_urls', ''))}")
    body = f.get("body", "err:missing")
    plain = f.get("plaintext", "err:missing")
    for name, text in (("body", body), ("plaintext", plain)):
        say(f"{name}={text}" if _failed(text) else f"{name}_chars={len(text)}")
    if not _failed(body):
        say(f"body_tags={tag_counts(body)}")
        say(f"body_attr_names={attr_names(body)}")
        say(f"body_classes={class_values(body)}")
        say(f"body_url_schemes={url_schemes(body)}")
    for word in WORDS:
        in_body = "err" if _failed(body) else word_context(body, word)
        in_plain = "err" if _failed(plain) else ("yes" if word in plain else "no")
        say(f"word {word}: body={in_body} plaintext={in_plain}")
    if a.save_html:
        if _failed(body):
            raise Refuse("the body did not read; nothing is saved")
        fd = os.open(a.save_html, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(body)
        say(f"saved_html_chars={len(body)}")
    return 0


def cmd_store_note(a) -> int:
    want = scratch_name(a.label)
    uuid, pk = split_note_id(a.note_id)
    table = "ZICCLOUDSYNCINGOBJECT"
    with contextlib.closing(_ro(NOTESTORE)) as conn:
        store = conn.execute("SELECT Z_UUID FROM Z_METADATA LIMIT 1").fetchone()
        if not store or store[0] != uuid:
            raise Refuse("the note id is not from this note store")
        row = conn.execute(f"SELECT * FROM {table} WHERE Z_PK = ?", (pk,)).fetchone()
        if row is None or row["ZTITLE1"] != want:
            raise Refuse(f"the store row is not {want}")
        ents = dict(map(tuple, conn.execute("SELECT Z_ENT, Z_NAME FROM Z_PRIMARYKEY")))
        say(f"entity={ents.get(row['Z_ENT'], row['Z_ENT'])}")
        _flags(row)
        say(f"ZSERVERSHAREDATA={_set_or_null(row, 'ZSERVERSHAREDATA')}")
        folder = conn.execute(
            f"SELECT * FROM {table} WHERE Z_PK = ?", (row["ZFOLDER"],)
        ).fetchone()
        if folder is not None:
            say(f"folder.ZFOLDERTYPE={folder['ZFOLDERTYPE']}")
            say(f"folder.ZSERVERSHAREDATA={_set_or_null(folder, 'ZSERVERSHAREDATA')}")
            _flags(folder, "folder.")
        cols = set(row.keys())
        links = [c for c in ("ZNOTE", "ZNOTE1") if c in cols]
        utis = [c for c in ("ZTYPEUTI", "ZTYPEUTI1") if c in cols]
        counts: Counter = Counter()
        if links:
            where = " OR ".join(f"{c} = ?" for c in links)
            sql = f"SELECT {', '.join(['Z_ENT', *utis])} FROM {table} WHERE {where}"
            for r in conn.execute(sql, [pk] * len(links)):
                uti = next((r[c] for c in utis if r[c]), "none")
                counts[(str(ents.get(r["Z_ENT"], r["Z_ENT"])), uti)] += 1
        for (ent, uti), n in sorted(counts.items()):
            say(f"attachment entity={ent} uti={uti} n={n}")
        say(f"attachment_rows={sum(counts.values())} link_columns={','.join(links)}")
    return 0


def cmd_notes_trash(_a) -> int:
    trash = _trash_folders()
    if trash is None:
        say("store=unreadable (Full Disk Access is needed: run as the bundle)")
    else:
        sql = "SELECT ZFOLDERTYPE FROM ZICCLOUDSYNCINGOBJECT WHERE ZFOLDERTYPE NOT NULL"
        with contextlib.closing(_ro(NOTESTORE)) as conn:
            types = Counter(r[0] for r in conn.execute(sql))
        say("foldertypes=" + ",".join(f"{k}:{n}" for k, n in sorted(types.items())))
        for pk, title in sorted(trash.items()):
            say(f"store: pk={pk} ZFOLDERTYPE=1 ZTITLE2={title}")
    rc, out, err = _osa(_FOLDERS)
    if rc:
        say(f"notes-trash: {_native(err)}")
        return 1
    folders = [r.split(US) for r in out.split(RS) if r.count(US) == 1]
    matched = 0
    for folder_id, name in folders:
        if trash is not None and _pk(folder_id) in trash:
            matched += 1
            say(f"applescript: pk={_pk(folder_id)} name={name}")
    say(f"notes-trash: folders={len(folders)} trash_matched={matched}")
    return 0


def _write(what: str, script: str, *args: str) -> int:
    rc, out, err = _osa(script, *args)
    if rc:
        say(f"{what}: {_native(err)}")
        return 1
    if out == "refused":
        raise Refuse("the live name is not the scratch name; nothing was written")
    say(f"{what}: {out}")
    return 0


def cmd_note_set_body(a) -> int:
    want = scratch_name(a.label)
    split_note_id(a.note_id)
    need = {"own": "COPY", "fixed": "LOCKED"}[a.mode]
    if a.label != need:
        raise Refuse(f"mode {a.mode} runs only on the {need} scratch note")
    return _write("set-body", _NOTE_SET_BODY, a.note_id, want, a.mode, FIXED_BODY)


def cmd_note_delete(a) -> int:
    want = scratch_name(a.label)
    split_note_id(a.note_id)
    return _write("delete", _NOTE_DELETE, a.note_id, want)


def cmd_note_from_html(a) -> int:
    name = scratch_html(Path(a.html_file).read_text("utf-8"))
    rc, out, err = _osa(_NOTE_FROM_HTML, a.html_file)
    if rc:
        say(f"from-html: {_native(err)}")
        return 1
    note_id, _, made = out.partition(US)
    say(f"from-html: created id={note_id} label={label_of(made)}")
    say(f"from-html: html_label={label_of(name)}")
    return 0


# --- Mail commands (index reads, one scoped count; no write) ------------------------

_SCRATCH_SQL = """SELECT m.ROWID AS rowid, s.subject AS subject, mb.url AS url,
       gd.message_id_header AS mid
FROM messages m
JOIN subjects s ON s.ROWID = m.subject
JOIN mailboxes mb ON mb.ROWID = m.mailbox
LEFT JOIN message_global_data gd ON gd.ROWID = m.global_message_id
WHERE m.deleted = 0 AND s.subject LIKE ?
ORDER BY m.ROWID"""
_ID_ROWS_SQL = """SELECT mb.url AS url FROM messages m
JOIN mailboxes mb ON mb.ROWID = m.mailbox
JOIN message_global_data gd ON gd.ROWID = m.global_message_id
WHERE m.deleted = 0 AND gd.message_id_header = ?"""


def _leaf(url: str) -> str:
    return unquote(url.rsplit("/", 1)[-1])


def _scratch_rows() -> list[dict]:
    """Live index rows whose subject is a scratch name, each with the leaves of
    every live row that holds the same Message-ID (the id itself stays inside)."""
    with contextlib.closing(_ro(_index_path())) as conn:
        rows = [dict(r) for r in conn.execute(_SCRATCH_SQL, (MARKER + "-%",))]
        for r in rows:
            urls = conn.execute(_ID_ROWS_SQL, (r["mid"],)) if r["mid"] else ()
            r["leaves"] = Counter(_leaf(u["url"]) for u in urls)
    return rows


def cmd_drafts_find(a) -> int:
    start = time.monotonic()
    while True:  # reads the index file only: Mail gets no event; bounded by --wait
        rows = _scratch_rows()
        seen = any(label_of(r["subject"]) == a.label for r in rows)
        waited = time.monotonic() - start
        if seen or not a.label or waited >= a.wait:
            break
        time.sleep(0.5)
    if a.label:
        say(f"label={a.label} seen={'yes' if seen else 'no'} after_s={waited:.1f}")
    in_drafts = 0
    for r in rows:
        scheme, _account, path = split_url(r["url"])
        in_drafts += is_drafts(path)
        leaves = ",".join(f"{k}:{n}" for k, n in sorted(r["leaves"].items()))
        say(
            f"rowid={r['rowid']} label={label_of(r['subject'])}"
            f" kind={kind_of(scheme, path)} drafts={'yes' if is_drafts(path) else 'no'}"
            f" leaf={_leaf(r['url'])} id_rows={sum(r['leaves'].values())}"
            f" id_leaves={leaves or 'none'}"
        )
    say(f"drafts-find: scratch_rows={len(rows)} in_drafts={in_drafts}")
    return 0


def _mail_cpu() -> str:
    """Mail's CPU share from ps: passive, no Apple Event (the watchdog's method)."""
    r = subprocess.run(
        ["/bin/ps", "-Ao", "%cpu=,comm="], capture_output=True, text=True, timeout=10
    )
    for line in r.stdout.splitlines():
        cpu, _, comm = line.strip().partition(" ")
        if comm.strip().endswith("/Mail.app/Contents/MacOS/Mail"):
            return cpu
    return "not-running"


def cmd_drafts_whose(a) -> int:
    row = next((r for r in _scratch_rows() if r["rowid"] == a.rowid), None)
    if row is None:
        raise Refuse("no live scratch row has that rowid")
    scheme, account, path = split_url(row["url"])
    if scheme == "local" or not is_drafts(path) or not row["mid"]:
        raise Refuse("that row is not in an account's Drafts mailbox")
    mid = row["mid"].strip("<>")  # the index stores <a@b>, Mail's `message id` a@b
    ok = worst = 0
    for i in range(1, a.runs + 1):  # at most 10 single events, never a loop on Mail
        cpu = _mail_cpu()
        t0 = time.monotonic()
        rc, out, err = _osa(_WHOSE, account, path, mid)
        ms = int((time.monotonic() - t0) * 1000)
        worst = max(worst, ms)
        ok += rc == 0 and out == "1"
        result = f"count={out}" if rc == 0 else _native(err)
        say(f"run={i} {result} ms={ms} mail_cpu={cpu}")
        if i < a.runs:
            time.sleep(2)
    say(
        f"whose: label={label_of(row['subject'])} kind={kind_of(scheme, path)}"
        f" ok={ok}/{a.runs} max_ms={worst}"
    )
    return 0 if ok == a.runs else 1


def cmd_mail_leaves(a) -> int:
    rc, account, err = _osa(_ACCOUNT_ID, a.account_name)
    if rc:
        say(f"mail-leaves: {_native(err)}")
        return 1
    with contextlib.closing(_ro(_index_path())) as conn:
        urls = [r[0] for r in conn.execute("SELECT url FROM mailboxes")]
    total = shown = 0
    for url in urls:
        try:
            scheme, owner, path = split_url(url)
        except Refuse:
            continue
        if owner != account:
            continue
        total += 1
        if is_root_level(path):
            shown += 1
            leaf = _leaf(url)
            form = "ascii" if leaf.isascii() else "NFD-or-other"
            if not leaf.isascii() and unicodedata.is_normalized("NFC", leaf):
                form = "NFC"
            say(f"leaf={leaf} form={form} scheme={scheme}")
    say(f"mail-leaves: mailboxes={total} root_level={shown}")
    return 0


# --- offline checks ----------------------------------------------------------------


def cmd_compile(_a) -> int:
    """Compile every script with osacompile. It runs no script."""
    bad = 0
    with tempfile.TemporaryDirectory(prefix="p056-") as d:
        for name, script in SCRIPTS.items():
            r = subprocess.run(
                [OSACOMPILE, "-e", script, "-o", str(Path(d) / f"{name}.scpt")],
                capture_output=True,
                text=True,
                timeout=60,
            )
            bad += r.returncode != 0
            say(f"compile {name}: {'ok' if r.returncode == 0 else _native(r.stderr)}")
    say(f"compile: scripts={len(SCRIPTS)} failed={bad}")
    return 1 if bad else 0


def cmd_selftest(_a) -> int:
    """The parser, the scratch guard and the redaction: no app, no database."""
    n = 0

    def check(cond: object, what: str) -> None:
        nonlocal n
        if not cond:
            raise AssertionError(what)
        n += 1

    def refuses(fn, *args) -> bool:
        try:
            fn(*args)
        except Refuse:
            return True
        return False

    note = "x-coredata://0A1B2C3D-0000-4000-8000-000000000001/ICNote/p7"

    # the scratch guard
    check(scratch_name("COPY") == "P056-SCRATCH-COPY", "scratch_name")
    for bad in ("", "copy", "A B", "X" * 17, "COPY\n", "A-B"):
        check(refuses(scratch_name, bad), f"bad label accepted: {bad!r}")
    check(label_of("P056-SCRATCH-RICH") == "RICH", "label_of")
    for other in ("Shopping", "P056-SCRATCH-rich", "x P056-SCRATCH-RICH", MARKER):
        check(label_of(other) == "?", f"label_of leaks: {other!r}")
    check(split_note_id(note) == (note[13:49], 7), "split_note_id")
    check(refuses(split_note_id, "p7"), "a short note id was accepted")
    check(refuses(split_note_id, note.replace("ICNote", "ICFolder")), "folder id")
    check(scratch_html("<div><b>P056-SCRATCH-RICH</b></div><div>x</div>"), "html")
    check(refuses(scratch_html, "<div>Tax 2026</div>"), "real HTML was accepted")
    check(refuses(scratch_html, ""), "empty HTML was accepted")

    # every script that addresses a note checks the name before its write
    for name, verb in _WRITES.items():
        script = SCRIPTS[name]
        check(script.count(verb) == 1, f"{name}: one write statement")
        if name != "note_from_html":
            check(script.index(_GUARD) < script.index(verb), f"{name}: guard first")
    for name, script in SCRIPTS.items():
        if name not in _WRITES:
            hit = [
                v for v in ("set body", "delete ", "make new", "move ") if v in script
            ]
            check(not hit, f"{name} is a read but holds {hit}")
    check("Mail" not in "".join(SCRIPTS[k] for k in _WRITES), "a Mail write exists")

    # redaction
    red = redact('Notes got an error: Can’t get note "Tax 2026". (-1728)')
    check("Tax" not in red and "(-1728)" in red, "quoted text leaked")
    check("Tax" not in redact("note “Tax 2026”"), "curly quotes leaked")
    check(redact("id <abc.1@mail.example> x") == "id <mid> x", "Message-ID leaked")
    check("@" not in redact("from a.b+c@example.org to d@example.net"), "address")
    check(note in redact(f'note id "{note}"'), "a scratch note id was masked")
    check('"P056-SCRATCH-COPY"' in redact('name "P056-SCRATCH-COPY"'), "marker")
    check(len(redact("x" * 1000)) == 300, "long line not cut")
    check("\n" not in redact("a\nb"), "line break kept")
    check(_native("Notes got an error. (-10000)")[:10] == "err:-10000", "number")
    # a quoted body: escaped quotes, a marker at its start, a cut, a lone quote
    escaped = r'set body to "<a href=\"https://private.example/\">private</a>". (-1)'
    check("private" not in redact(escaped), "escaped quotes leaked")
    check("Tax" not in redact('name "P056-SCRATCH-COPY Tax 2026"'), "marker prefix")
    long_body = 'Can’t set body to "' + "private " * 60 + '". (-10000)'
    check("private" not in _native(long_body), "a cut quoted string leaked")
    check(_native(long_body).startswith("err:-10000 "), "the number was lost")
    check("private" not in redact('ok "open private text'), "a lone quote leaked")
    check(redact(redact(escaped)) == redact(escaped), "redact is not stable")
    check(attr_names('<a href="https://e.x/?private=1&q=2">y</a>') == "href", "value")
    names = US.join(["a.PNG", "my.private file name", "missing value"])
    check(_suffixes(names) == "(none),(other),.png", "a file name leaked")
    check(_PLAIN.fullmatch("err:-1728") and not _PLAIN.fullmatch("Tax 2026"), "plain")

    # census and urls
    sample = (
        '<div><b>P056BOLD</b></div><ul class="c1"><li>P056CHK1</li></ul>'
        '<div><img src="data:image/png;base64,AAAA"><a href="https://e.x/">y</a><br>'
        "P056BODY</div>"
    )
    check(word_context(sample, "P056BOLD") == "div>b", "context bold")
    check(word_context(sample, "P056CHK1") == "ul.c1>li", "context list")
    lists = '<ul class="a b"><li class="x">P056CHK1</li></ul><ul><li>P056BULL</li></ul>'
    check(word_context(lists, "P056CHK1") == "ul.a.b>li.x", "class on its own tag")
    check(word_context(lists, "P056BULL") == "ul>li", "a closed tag kept its class")
    check(word_context(sample, "P056BODY") == "div", "context after void tags")
    check(word_context(sample, "P056CELL") == "absent", "context absent")
    check("img:1" in tag_counts(sample) and "li:1" in tag_counts(sample), "tags")
    check(class_values(sample) == "c1", "classes")
    check(attr_names(sample) == "class,href,src", "attribute names")
    check(url_schemes(sample) == "href:https=1,src:data=1", "url schemes")
    url = "imap://ACC/%5BGmail%5D/Drafts"
    check(split_url(url) == ("imap", "ACC", "[Gmail]/Drafts"), "split_url")
    check(is_drafts("[Gmail]/Drafts") and is_drafts("Drafts"), "is_drafts")
    check(not is_drafts("Old/Drafts") and not is_drafts("Draftsman"), "is_drafts no")
    check(kind_of("imap", "[Gmail]/Drafts") == "gmail", "kind gmail")
    check(kind_of("imap", "Drafts") == "imap-or-icloud", "kind imap")
    check(refuses(split_url, "nonsense"), "a bad url was accepted")

    # the parser, and a refusal BEFORE any script: _osa is replaced, so no app runs
    for argv in (
        ["selftest"],
        ["compile"],
        ["notes-find"],
        ["note-read", note, "RICH", "--save-html", "/tmp/x.html"],
        ["store-note", note, "RICH"],
        ["notes-trash"],
        ["note-set-body", note, "COPY", "own"],
        ["note-from-html", "/tmp/x.html"],
        ["note-delete", note, "BIN"],
        ["mail-leaves", "Some Account"],
        ["drafts-find", "--label", "GMAIL", "--wait", "90"],
        ["drafts-whose", "12", "--runs", "5"],
    ):
        check(callable(_parser().parse_args(argv).fn), f"parser: {argv[0]}")
    quiet = io.StringIO()
    for argv in (
        ["note-delete", note],  # no label
        ["note-set-body", note, "COPY", "other"],
        ["drafts-find", "--wait", "181"],
        ["drafts-whose", "12", "--runs", "11"],
    ):
        with contextlib.redirect_stderr(quiet), contextlib.suppress(SystemExit):
            _parser().parse_args(argv)
            check(False, f"parser accepted {argv}")
        n += 1
    calls: list[tuple] = []
    real = globals()["_osa"]
    globals()["_osa"] = lambda *a: calls.append(a) or (0, "refused", "")
    try:
        with contextlib.redirect_stdout(quiet):
            for argv in (
                ["note-set-body", note, "RICH", "own"],  # own runs on COPY only
                ["note-set-body", note, "COPY", "fixed"],  # fixed runs on LOCKED only
                ["note-delete", "x-coredata://bad", "BIN"],
                ["note-delete", note, "bin"],
                ["note-read", note, "rich"],
            ):
                check(main(argv) == 3 and not calls, f"ran a script: {argv}")
            # the script itself answers `refused` when the live name differs
            check(main(["note-delete", note, "BIN"]) == 3, "refused is not a refusal")
            check(main(["note-set-body", note, "COPY", "own"]) == 3, "set-body")
            check(len(calls) == 2, "the script guard was not reached")
    finally:
        globals()["_osa"] = real
    say(f"selftest ok checks={n}")
    return 0


def _bounded(lo: int, hi: int):
    def parse(text: str) -> int:
        value = int(text)
        if not lo <= value <= hi:
            raise argparse.ArgumentTypeError(f"must be {lo} to {hi}")
        return value

    return parse


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, *pos):
        sp = sub.add_parser(name)
        for x in pos:
            sp.add_argument(x)
        sp.set_defaults(fn=fn)
        return sp

    add("selftest", cmd_selftest)
    add("compile", cmd_compile)
    add("notes-find", cmd_notes_find)
    add("note-read", cmd_note_read, "note_id", "label").add_argument("--save-html")
    add("store-note", cmd_store_note, "note_id", "label")
    add("notes-trash", cmd_notes_trash)
    sb = add("note-set-body", cmd_note_set_body, "note_id", "label")
    sb.add_argument("mode", choices=["own", "fixed"])
    add("note-from-html", cmd_note_from_html, "html_file")
    add("note-delete", cmd_note_delete, "note_id", "label")
    add("mail-leaves", cmd_mail_leaves, "account_name")
    df = add("drafts-find", cmd_drafts_find)
    df.add_argument("--label")
    df.add_argument("--wait", type=_bounded(0, 180), default=0)
    dw = add("drafts-whose", cmd_drafts_whose)
    dw.add_argument("rowid", type=int)
    dw.add_argument("--runs", type=_bounded(1, 10), default=5)
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return args.fn(args)
    except Refuse as e:
        say(f"refused: {e}")
        return 3
    except Exception as e:  # a probe prints a verdict, never a trace
        say(f"error: {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
