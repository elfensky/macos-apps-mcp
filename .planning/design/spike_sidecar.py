"""Sidecar viability spike (#201): full-store harvest, then run the REAL adapter
code unmodified against the real Sequoia Envelope Index, with the sidecar injected
at the one connection-setup seam (_open_sqlite_ro wrapper: ATTACH + TEMP VIEW).

Read-only on all Mail data. Sidecar lives in the scratchpad. Only dry-run writes.
"""

import email
import re
import sqlite3
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

from macos_apps_mcp import runtime
from macos_apps_mcp.adapters import mail_addressing, mail_index
from macos_apps_mcp.adapters.mail import MailAdapter

SCRATCH = Path(__file__).parent
SIDE = SCRATCH / "mail_ids_full.sqlite"
V10 = Path.home() / "Library/Mail/V10"
IDX = mail_index.envelope_index_path()
STEM = re.compile(r"^(\d+)(\.partial)?\.emlx$")


def mbox_dir(url):
    u = urlparse(url)
    d = V10 / u.netloc
    for part in unquote(u.path.lstrip("/")).split("/"):
        d = d / f"{part}.mbox"
    if d.is_dir():
        for sub in d.iterdir():
            if sub.is_dir() and (sub / "Data").is_dir():
                return sub
    return None


def harvest():
    conn = sqlite3.connect(f"file:{IDX}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    boxes = conn.execute(
        "SELECT mb.ROWID, mb.url, COUNT(*) n FROM mailboxes mb "
        "JOIN messages m ON m.mailbox = mb.ROWID AND m.deleted=0 "
        "GROUP BY mb.ROWID ORDER BY n DESC"
    ).fetchall()
    distinct, = conn.execute(
        "SELECT COUNT(DISTINCT global_message_id) FROM messages WHERE deleted=0"
    ).fetchone()

    SIDE.unlink(missing_ok=True)
    sc = sqlite3.connect(SIDE)
    sc.execute(
        "CREATE TABLE global_ids("
        "global_message_id INTEGER PRIMARY KEY, message_id_header TEXT NOT NULL)"
    )
    t0 = time.monotonic()
    files_seen = inserted = no_dir_rows = no_file = no_mid = 0
    for b in boxes:
        d = mbox_dir(b["url"])
        rows = conn.execute(
            "SELECT ROWID, global_message_id FROM messages "
            "WHERE mailbox=? AND deleted=0", (b["ROWID"],)
        ).fetchall()
        if d is None:
            no_dir_rows += len(rows)
            print(f"    unresolved dir: {unquote(b['url'])[:70]} ({len(rows)} rows)")
            continue
        disk = {}
        for f in (d / "Data").rglob("*.emlx"):
            m = STEM.match(f.name)
            if m and "Attachments" not in f.parts:
                disk[int(m.group(1))] = f
        for r in rows:
            f = disk.get(r["ROWID"])
            if f is None:
                no_file += 1
                continue
            files_seen += 1
            try:
                with open(f, "rb") as fh:
                    fh.readline()
                    msg = email.message_from_bytes(fh.read(16384))
                mid = (msg.get("Message-ID") or "").strip()
            except OSError:
                mid = ""
            if not mid:
                no_mid += 1
                continue
            sc.execute(
                "INSERT OR REPLACE INTO global_ids VALUES (?,?)",
                (r["global_message_id"], mid),
            )
            inserted += 1
    sc.commit()
    got, = sc.execute("SELECT COUNT(*) FROM global_ids").fetchone()
    sc.close()
    dt = time.monotonic() - t0
    print(f"  harvest: {files_seen} files parsed in {dt:.0f}s "
          f"({files_seen / dt:.0f}/s), {inserted} inserts")
    print(f"  coverage: {got}/{distinct} distinct global ids "
          f"({100 * got / distinct:.2f}%)  [rows w/o dir={no_dir_rows}, "
          f"w/o file={no_file}, w/o Message-ID={no_mid}]")
    conn.close()
    return got, distinct


def inject():
    """Wrap the ONE opener: Envelope Index connections get the sidecar attached and
    a TEMP VIEW shadowing message_global_data. Everything else untouched."""
    orig = runtime._open_sqlite_ro

    def wrapped(path, *, immutable=False):
        conn = orig(path, immutable=immutable)
        if Path(path).name == "Envelope Index":
            conn.execute("ATTACH DATABASE ? AS mid", (f"file:{SIDE}?mode=ro",))
            conn.execute(
                "CREATE TEMP VIEW message_global_data AS "
                "SELECT global_message_id AS ROWID, message_id_header "
                "FROM mid.global_ids"
            )
        return conn

    runtime._open_sqlite_ro = wrapped
    # Does the native fingerprint pass against the shadowing view?
    c = wrapped(IDX)
    cols = {r[0] for r in c.execute(
        "SELECT name FROM pragma_table_info('message_global_data')")}
    c.close()
    print(f"  pragma_table_info on shadowed name -> {sorted(cols)}")
    print(f"  native fingerprint satisfied: "
          f"{ {'ROWID', 'message_id_header'} <= cols }")


def timed(label, fn):
    t0 = time.monotonic()
    try:
        out = fn()
        dt = (time.monotonic() - t0) * 1000
        return out, dt, None
    except Exception as e:  # noqa: BLE001
        dt = (time.monotonic() - t0) * 1000
        return None, dt, f"{type(e).__name__}: {e}"


def battery():
    a = MailAdapter()

    r, dt, err = timed("overview", a.overview)
    print(f"  mail_overview: {dt:.0f}ms " + (
        f"-> {len(r)} mailboxes, e.g. {r[0]['account']}/{r[0]['mailbox']} "
        f"unread={r[0]['unread']}" if r else f"ERR {err}"))

    r, dt, err = timed("search", lambda: a.search(subject="invoice", unread=True))
    hits = r["results"] if r else []
    print(f"  mail_search(subject+unread) [was BROKEN]: {dt:.0f}ms -> "
          + (f"{len(hits)} hits, plane={r.get('plane', 'sqlite')}" if r else f"ERR {err}"))

    r2, dt, err = timed("search2", lambda: a.search(from_="github", limit=10))
    hits2 = r2["results"] if r2 else []
    print(f"  mail_search(from_) : {dt:.0f}ms -> "
          + (f"{len(hits2)} hits" if r2 else f"ERR {err}"))

    r3, dt, err = timed("stats", lambda: a.stats(days=365))
    print(f"  mail_stats(365d) [was BROKEN]: {dt:.0f}ms -> " + (
        f"received={r3.get('received')} " if r3 else f"ERR {err}"))

    seed = hits[0] if hits else (hits2[0] if hits2 else None)
    if seed:
        rt, dt, err = timed("thread", lambda: a.thread(seed["id"], 10, False))
        n = len(rt["results"]) if rt else 0
        print(f"  mail_thread [was BROKEN]: {dt:.0f}ms -> "
              + (f"{n} members" if rt else f"ERR {err}"))

        rr, dt, err = timed("resolve", lambda: mail_addressing.resolve(seed["id"]))
        print(f"  mail_addressing.resolve(id) [was BROKEN]: {dt:.0f}ms -> "
              + (f"folder={rr.folder[:55]} account={rr.account[:13]}…"
                 if rr else f"ERR {err}"))

    rd, dt, err = timed("dups", lambda: a.duplicates(limit=3))
    print(f"  mail_duplicates [was BROKEN]: {dt:.0f}ms -> " + (
        f"{len(rd.get('mailboxes', []))} mailbox rows" if rd else f"ERR {err}"))

    # THE knock-on: destructive gates with a real per-account folder url, dry-run.
    if seed:
        folder = seed["folder"]
        rw, dt, err = timed(
            "trash", lambda: a.trash_mail(seed["id"], folder, dry_run=True))
        print(f"  trash_mail(dry_run, real folder url) [was UNREACHABLE]: {dt:.0f}ms")
        if rw:
            print(f"    -> preview ok: destination={str(rw)[:100]}")
        else:
            print(f"    -> ERR {err}")


print("=== 1. full-store harvest ===")
harvest()
print("=== 2. inject sidecar at _open_sqlite_ro (ATTACH + TEMP VIEW) ===")
inject()
print("=== 3. real-adapter battery (unmodified adapter/query code) ===")
battery()
