"""Spike 004 — the Notes corpus, decoded once and cached OUTSIDE the repo.

Uses the adapter's own filter (`_FROM`) and body decoder (`_decode_note_data`), so the
corpus is exactly what `notes()` / `note_bodies` see. Note text is personal: the cache
lives in $SPIKE_PRIVATE_DIR (default: the OS temp dir), and every print is aggregate.

    uv run --with pyobjc-framework-NaturalLanguage python \
        .planning/spikes/004-notes-semantic-cost/corpus.py     # prints corpus stats
"""

from __future__ import annotations

import json
import os
import sqlite3
import statistics
import tempfile
from collections import Counter
from pathlib import Path

from macos_apps_mcp.adapters.notes import _FROM, _decode_note_data

STORE = Path.home() / "Library/Group Containers/group.com.apple.notes/NoteStore.sqlite"
PRIVATE = Path(os.environ.get("SPIKE_PRIVATE_DIR", tempfile.gettempdir()))
CACHE = PRIVATE / "gsd-spike-004-corpus.json"


def load() -> list[dict]:
    """[{id, title, text, modified}] for every visible, unlocked note."""
    if CACHE.exists():
        return json.loads(CACHE.read_text())
    conn = sqlite3.connect(f"file:{STORE}?mode=ro", uri=True)
    head = "FROM ZICCLOUDSYNCINGOBJECT o"
    frm = _FROM.replace(head, f"{head} JOIN ZICNOTEDATA d ON d.Z_PK = o.ZNOTEDATA", 1)
    rows = conn.execute(
        "SELECT o.Z_PK, o.ZTITLE1, d.ZDATA, o.ZMODIFICATIONDATE1, "
        f"o.ZISPASSWORDPROTECTED {frm}"
    ).fetchall()
    notes, declined, locked = [], 0, 0
    for pk, title, blob, modified, is_locked in rows:
        if is_locked:
            locked += 1
            continue
        text = _decode_note_data(blob)
        if text is None:
            declined += 1
            continue
        notes.append(
            {"id": pk, "title": title or "", "text": text, "modified": modified or 0}
        )
    PRIVATE.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(notes))
    print(
        f"(decoded {len(notes)}, locked skipped {locked}, decoder declined "
        f"{declined}; cached to {CACHE})"
    )
    return notes


def languages(notes: list[dict]) -> Counter:
    from NaturalLanguage import NLLanguageRecognizer

    c: Counter = Counter()
    for n in notes:
        r = NLLanguageRecognizer.alloc().init()
        r.processString_((n["title"] + "\n" + n["text"])[:2000])
        c[str(r.dominantLanguage() or "und")] += 1
    return c


def main() -> None:
    notes = load()
    lens = sorted(len(n["text"]) for n in notes)
    q = statistics.quantiles(lens, n=20)
    print(f"notes: {len(notes)}  total chars: {sum(lens):,}")
    print(
        f"chars/note p50={q[9]:.0f} p90={q[17]:.0f} p95={q[18]:.0f} "
        f"max={lens[-1]:,}  empty(<20)={sum(1 for x in lens if x < 20)}"
    )
    for cap in (1000, 2000, 4000):
        chunks = sum(max(1, -(-x // cap)) for x in lens)
        print(f"  chunks at {cap} chars: {chunks}")
    langs = languages(notes)
    print("dominant language:", ", ".join(f"{k}={v}" for k, v in langs.most_common()))


if __name__ == "__main__":
    main()
