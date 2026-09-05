"""Message-ID sidecar store + harvester (#201): map ``messages.global_message_id`` →
RFC822 ``Message-ID``, harvested from the ``.emlx`` files Mail keeps on disk.

Pre-Tahoe Envelope Indexes never stored the RFC822 Message-ID
(``message_global_data.message_id_header`` is a macOS 26 migration — #199), and that
one column is everything the sqlite mail plane is missing on macOS 15. This module
rebuilds the mapping in a sidecar sqlite in OUR state dir (never Mail's data), read
headers-only off the store at rest — device-verified on the Sequoia rig 2026-09-05:
100.0% of live rows have their ``<ROWID>.emlx``/``<ROWID>.partial.emlx``, every
sampled file carries a Message-ID, and a full 36k-store harvest runs in under a
minute on a 2012 spinning disk. Design + spike: .planning/design/mail-sequoia-id-
sidecar.md.

Deliberately import-free of ``mail_index`` (which imports THIS module for its mode
handling): callers pass the Envelope Index path in. Reads the index through
``read_via_sqlite`` with a REDUCED fingerprint — only the tables/columns the
harvester touches — because the harvester must run precisely on the machines where
the full ``HEADER_FINGERPRINT`` fails (that failure is what it exists to fix)."""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime
from email import message_from_bytes
from pathlib import Path
from urllib.parse import unquote, urlparse

from ..audit import state_dir
from ..runtime import read_via_sqlite

# Only what the harvester reads. The full HEADER_FINGERPRINT requires the very column
# this module exists to replace, so verifying it here would make the fix impossible on
# every machine that needs it.
_INDEX_FINGERPRINT: dict[str, set[str]] = {
    "messages": {"ROWID", "global_message_id", "mailbox", "deleted"},
    "mailboxes": {"ROWID", "url"},
}

# <ROWID>.emlx or <ROWID>.partial.emlx — a partial is missing its ATTACHMENTS, not its
# headers (#119), so both are id sources. Anything else under Data/ is not a message.
_EMLX_STEM = re.compile(r"^(\d+)(\.partial)?\.emlx$")

# Headers-only read: the emlx byte-count line, then the first 16 KB — enough for any
# real header block, and what makes a full-store harvest ~1 minute instead of hours.
_HEADER_BYTES = 16384


def sidecar_path() -> Path:
    """Where the Message-ID sidecar lives: our state dir, next to the FTS body
    sidecar, never inside Mail's data."""
    return state_dir() / "mail_ids.sqlite"


def _connect(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db)
    # Same concurrency posture as the FTS sidecar (_fts_connect): the build runs off
    # run_native (pure file/sqlite I/O), so a reader ATTACHing mode=ro during a build
    # must see the committed snapshot instead of an instant-fail lock. Ours to WAL:
    # this file is never Mail's.
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        # Keyed on global_message_id, NOT messages.ROWID: copies of one message share
        # the gid (dedup partitions on it), and a move mints a new ROWID but keeps the
        # gid — so the mapping survives filing. INSERT OR REPLACE on re-harvest
        # self-heals; rows for since-deleted messages are inert because every query
        # joins FROM live index rows.
        "CREATE TABLE IF NOT EXISTS global_ids("
        "global_message_id INTEGER PRIMARY KEY,"
        " message_id_header TEXT NOT NULL);"
        "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value);"
    )
    return conn


def stored_high_water(db: Path) -> int | None:
    """The ``max_rowid_harvested`` mark, or None for a sidecar never built. Reads
    mode=ro so a read-time caller (the bounded top-up check) can never create or
    write the file as a side effect."""
    if not db.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'max_rowid_harvested'"
        ).fetchone()
        return int(row[0]) if row and str(row[0]).isdigit() else None
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def _mailbox_store_dir(v_root: Path, url: str) -> Path | None:
    """The directory holding one mailbox's ``Data/`` tree, from its mailboxes.url —
    ``V10/<account-uuid>/<segment>.mbox/…/<store-uuid>/``, each nested path segment
    appending ``.mbox`` (device-verified on the rig). None when the account has no
    local store under V* at all (a real state — 14 such rows on the rig) or the
    mailbox's own directory is absent; the caller counts those rows, never crashes."""
    u = urlparse(url)
    d = v_root / u.netloc
    if not d.is_dir():
        return None
    for part in unquote(u.path).strip("/").split("/"):
        if part:
            d = d / f"{part}.mbox"
    if not d.is_dir():
        return None
    if (d / "Data").is_dir():  # fake trees in tests skip the store-uuid level
        return d
    for sub in sorted(d.iterdir()):
        if sub.is_dir() and (sub / "Data").is_dir():
            return sub
    return None


def _read_message_id(f: Path) -> str:
    """The exact bracketed Message-ID from one ``.emlx``'s headers, or ``""``.

    Reads the byte-count line plus ``_HEADER_BYTES`` — never the body. Broad except
    for the same reason as ``parse_emlx``: ``.emlx`` bytes are attacker-influenceable
    and a parse failure must yield "no id", never an escape."""
    try:
        with open(f, "rb") as fh:
            fh.readline()  # the emlx length-prefix line, not part of the RFC822
            msg = message_from_bytes(fh.read(_HEADER_BYTES))
        return (msg.get("Message-ID") or "").strip()
    except Exception:
        return ""


def _rowid_files(store_dir: Path) -> dict[int, Path]:
    """``{messages.ROWID: file}`` for every message file under one mailbox's
    ``Data/``. ``Attachments/<rowid>/…`` sidecars are excluded — their payload files
    are not messages, whatever their names."""
    out: dict[int, Path] = {}
    for f in (store_dir / "Data").rglob("*.emlx"):
        m = _EMLX_STEM.match(f.name)
        if m and "Attachments" not in f.parts:
            out[int(m.group(1))] = f
    return out


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def build(index_path: Path, *, sidecar_db: Path | None = None) -> dict:
    """Harvest Message-IDs for every live index row not yet mapped → the sidecar.

    Resumable and self-healing: a row whose file is absent (message not downloaded
    yet) is skipped and RETRIED on the next run; a message whose file carries no
    Message-ID header is uncitable on every macOS (the same rule Tahoe's own lazily
    backfilled column imposes) and stays unmapped; an account with no local store
    under V* contributes its row count to the report instead of a crash. When
    ``max(messages.ROWID)`` has moved BELOW the stored high-water mark, Mail's index
    was rebuilt (ROWIDs reassigned, gids possibly reissued) — every row is
    re-harvested with ``INSERT OR REPLACE`` so stale mappings cannot survive as
    false coverage.

    Returns run stats + coverage; ``high_water_rowid`` is what the bounded read-time
    top-up (#201 PR-B) measures new mail against."""
    side = sidecar_db if sidecar_db is not None else sidecar_path()
    v_root = index_path.parent.parent  # …/V10/MailData/Envelope Index → …/V10

    def read(conn):
        conn.row_factory = sqlite3.Row
        urls = {
            r["ROWID"]: r["url"]
            for r in conn.execute("SELECT ROWID, url FROM mailboxes")
        }
        rows = [
            (r["ROWID"], r["global_message_id"], r["mailbox"])
            for r in conn.execute(
                "SELECT ROWID, global_message_id, mailbox FROM messages"
                " WHERE deleted = 0 AND global_message_id IS NOT NULL"
            )
        ]
        return urls, rows

    urls, rows = read_via_sqlite(index_path, _INDEX_FINGERPRINT, read, immutable=False)
    max_rowid = max((r[0] for r in rows), default=0)
    high_water = stored_high_water(side)
    index_rebuilt = high_water is not None and max_rowid < high_water

    conn = _connect(side)
    try:
        covered: set[int] = (
            set()
            if index_rebuilt
            else {
                r[0] for r in conn.execute("SELECT global_message_id FROM global_ids")
            }
        )
        by_mailbox: dict[int, list[tuple[int, int]]] = {}
        for rowid, gid, mailbox in rows:
            if gid not in covered:
                by_mailbox.setdefault(mailbox, []).append((rowid, gid))

        harvested = no_file = no_mid = no_store_rows = 0
        for mailbox, wanted in by_mailbox.items():
            store = _mailbox_store_dir(v_root, urls.get(mailbox, ""))
            if store is None:
                no_store_rows += len(wanted)
                continue
            files = _rowid_files(store)
            for rowid, gid in wanted:
                if gid in covered:  # a sibling copy already mapped this gid
                    continue
                f = files.get(rowid)
                if f is None:
                    no_file += 1
                    continue
                mid = _read_message_id(f)
                if not mid:
                    no_mid += 1
                    continue
                conn.execute(
                    "INSERT OR REPLACE INTO global_ids VALUES (?, ?)", (gid, mid)
                )
                covered.add(gid)  # copies share a gid; one file is enough
                harvested += 1
        conn.execute(
            "INSERT OR REPLACE INTO meta VALUES ('max_rowid_harvested', ?)",
            (str(max_rowid),),
        )
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('built_at', ?)", (_now(),))
        conn.commit()
        sidecar_gids = {
            r[0] for r in conn.execute("SELECT global_message_id FROM global_ids")
        }
    finally:
        conn.close()

    live_gids = {r[1] for r in rows}
    mapped, total = len(live_gids & sidecar_gids), len(live_gids)
    return {
        "harvested": harvested,
        "mapped": mapped,
        "total_ids": total,
        "coverage": _coverage_text(mapped, total),
        # Retried next run — the file may simply not be downloaded yet.
        "skipped_no_file": no_file,
        # Uncitable on every macOS: no RFC822 Message-ID exists to map.
        "skipped_no_message_id": no_mid,
        # Accounts with no local store under V* — nothing on disk to harvest from.
        "rows_without_local_store": no_store_rows,
        "high_water_rowid": max_rowid,
        "index_rebuilt": index_rebuilt,
    }


def top_up(
    index_conn: sqlite3.Connection,
    *,
    v_root: Path,
    sidecar_db: Path,
    high_water: int,
    new_high_water: int,
) -> int:
    """Harvest rows above ``high_water`` through an ALREADY-OPEN index connection —
    the bounded read-time top-up (#201 PR-B). The caller has counted the delta and
    decided it is small; this just does the work and advances the mark.

    Runs BEFORE the sidecar is ATTACHed to ``index_conn`` (a database being written
    must not also be attached read-only to the reader). A row skipped here (file not
    on disk yet, no Message-ID) is behind the advanced mark and is retried by the
    next ``build`` run, not the next read — reads stay bounded.

    Returns the number of ids written."""
    rows = index_conn.execute(
        "SELECT m.ROWID, m.global_message_id, mb.url"
        " FROM messages m JOIN mailboxes mb ON mb.ROWID = m.mailbox"
        " WHERE m.deleted = 0 AND m.ROWID > ? AND m.global_message_id IS NOT NULL",
        (high_water,),
    ).fetchall()
    by_url: dict[str, list[tuple[int, int]]] = {}
    for rowid, gid, url in rows:
        by_url.setdefault(url, []).append((rowid, gid))
    conn = _connect(sidecar_db)
    try:
        harvested = 0
        for url, wanted in by_url.items():
            store = _mailbox_store_dir(v_root, url)
            if store is None:
                continue
            files = _rowid_files(store)
            for rowid, gid in wanted:
                f = files.get(rowid)
                mid = _read_message_id(f) if f is not None else ""
                if mid:
                    conn.execute(
                        "INSERT OR REPLACE INTO global_ids VALUES (?, ?)", (gid, mid)
                    )
                    harvested += 1
        conn.execute(
            "INSERT OR REPLACE INTO meta VALUES ('max_rowid_harvested', ?)",
            (str(new_high_water),),
        )
        conn.commit()
    finally:
        conn.close()
    return harvested


def _coverage_text(mapped: int, total: int) -> str:
    pct = f" ({100 * mapped / total:.1f}%)" if total else ""
    return f"{mapped} of {total} ids mapped{pct}"


def coverage(index_path: Path, *, sidecar_db: Path | None = None) -> dict | None:
    """Sidecar coverage against the LIVE index — None when no sidecar exists.

    ``mapped`` counts the intersection with live distinct gids, not sidecar rows: the
    sidecar keeps mappings for since-deleted messages forever (harmless to queries,
    a lie in a ratio) — the same intersect-don't-divide rule ``body_coverage``
    learned in #119."""
    side = sidecar_db if sidecar_db is not None else sidecar_path()
    if not side.exists():
        return None

    def read(conn):
        gids = {
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT global_message_id FROM messages WHERE deleted = 0"
                " AND global_message_id IS NOT NULL"
            )
        }
        (max_rowid,) = conn.execute(
            "SELECT COALESCE(MAX(ROWID), 0) FROM messages WHERE deleted = 0"
        ).fetchone()
        return gids, max_rowid

    live_gids, max_rowid = read_via_sqlite(
        index_path, _INDEX_FINGERPRINT, read, immutable=False
    )
    try:
        conn = sqlite3.connect(f"file:{side}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        sidecar_gids = {
            r[0] for r in conn.execute("SELECT global_message_id FROM global_ids")
        }
        built = conn.execute("SELECT value FROM meta WHERE key = 'built_at'").fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    return {
        "mapped": len(live_gids & sidecar_gids),
        "total": len(live_gids),
        "high_water": stored_high_water(side) or 0,
        "max_rowid": max_rowid,
        "built_at": built[0] if built else "unknown",
    }


def coverage_line(index_path: Path, *, sidecar_db: Path | None = None) -> str:
    """The one doctor line: "N of M ids mapped (X%), high-water ROWID R, built T".
    Never raises — doctor reports, it does not die (its own rule)."""
    try:
        c = coverage(index_path, sidecar_db=sidecar_db)
    except Exception as e:  # doctor-only surface: report the failure as the line
        return f"coverage unavailable: {e}"
    if c is None:
        return "no sidecar built"
    line = (
        f"{_coverage_text(c['mapped'], c['total'])}, "
        f"high-water ROWID {c['high_water']}, built {c['built_at']}"
    )
    if c["max_rowid"] > c["high_water"]:
        line += f"; {c['max_rowid'] - c['high_water']} newer rows not yet harvested"
    return line
