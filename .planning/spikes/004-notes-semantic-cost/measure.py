"""Spike 004 — lexical vs embedding retrieval on the real Notes corpus, plus cost.

Queries are paraphrases of real notes, so they live beside the corpus cache in
$SPIKE_PRIVATE_DIR (gsd-spike-004-queries.json: [{"q": ..., "id": <Z_PK>}]). Output is
aggregate only: hit@1 / hit@3 / MRR per method, build + query time, index bytes.

    uv run --with pyobjc-framework-NaturalLanguage --with fastembed python \
        .planning/spikes/004-notes-semantic-cost/measure.py
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from corpus import PRIVATE, load  # noqa: E402

from macos_apps_mcp.text import fold_text  # noqa: E402

CHUNK = 1000  # chars; title is prepended to every chunk
FASTEMBED = [
    "sentence-transformers/all-MiniLM-L6-v2",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "minishlab/potion-multilingual-128M",
]


def chunks(notes: list[dict]) -> list[tuple[int, str]]:
    out = []
    for n in notes:
        body = n["text"] or ""
        for i in range(0, max(len(body), 1), CHUNK):
            out.append((n["id"], f"{n['title']}\n{body[i : i + CHUNK]}"))
    return out


def tokens(q: str) -> list[str]:
    return [t for t in re.findall(r"\w+", fold_text(q)) if len(t) >= 4]


# ------------------------------------------------------------------ lexical


def substring_ranker(notes, field):
    """Rank by query tokens found as substrings (today's matcher, per token)."""
    docs = {n["id"]: fold_text(field(n)) for n in notes}

    def rank(q):
        toks = tokens(q)
        scored = [(sum(t in d for t in toks), i) for i, d in docs.items()]
        return [i for s, i in sorted(scored, reverse=True) if s > 0]

    return rank, 0


def fts5_ranker(notes):
    db = sqlite3.connect(":memory:")
    db.execute(
        "create virtual table f using fts5(id unindexed, body, "
        "tokenize='porter unicode61 remove_diacritics 2')"
    )
    db.executemany(
        "insert into f values (?, ?)",
        [(n["id"], n["title"] + "\n" + n["text"]) for n in notes],
    )
    size = sum(len(n["title"]) + len(n["text"]) for n in notes)  # ≈ sidecar floor

    def rank(q):
        expr = " OR ".join(f'"{t}"' for t in tokens(q)) or '""'
        rows = db.execute(
            "select id from f where f match ? order by bm25(f)", (expr,)
        ).fetchall()
        return [r[0] for r in rows]

    return rank, size


# ---------------------------------------------------------------- embeddings


def vector_ranker(chs, embed_docs, embed_query):
    ids = [i for i, _ in chs]
    t0 = time.perf_counter()
    m = np.asarray(embed_docs([t for _, t in chs]), dtype=np.float32)
    build = time.perf_counter() - t0
    m /= np.linalg.norm(m, axis=1, keepdims=True) + 1e-9
    texts = [t for _, t in chs] * 10  # warm throughput on 10x the corpus
    t0 = time.perf_counter()
    embed_docs(texts)
    rate = len(texts) / (time.perf_counter() - t0)

    def rank(q):
        v = np.asarray(embed_query(q), dtype=np.float32)
        s = m @ (v / (np.linalg.norm(v) + 1e-9))
        best: dict[int, float] = {}
        for i, sc in zip(ids, s, strict=True):  # note score = best chunk
            best[i] = max(best.get(i, -1.0), float(sc))
        return [i for i, _ in sorted(best.items(), key=lambda kv: -kv[1])]

    return rank, m.nbytes, build, m.shape[1], rate


def native_nl(chs):
    from NaturalLanguage import NLEmbedding

    emb = NLEmbedding.sentenceEmbeddingForLanguage_("en")
    if emb is None:
        raise RuntimeError("NLEmbedding sentence model for 'en' is unavailable")

    def one(t):
        v = emb.vectorForString_(t)
        return list(v) if v is not None else [0.0] * emb.dimension()

    return vector_ranker(chs, lambda ts: [one(t) for t in ts], one)


def native_contextual(chs):
    """Public NLContextualEmbedding (macOS 14+): mean-pool its token vectors.
    (macOS 27's sentenceEmbeddingVector* selectors are NOT in the SDK — private.)"""
    from NaturalLanguage import NLContextualEmbedding

    emb = NLContextualEmbedding.contextualEmbeddingWithLanguage_("en")
    ok, err = emb.loadWithError_(None)
    if not ok:
        raise RuntimeError(f"NLContextualEmbedding load failed: {err}")

    def one(t):
        res, err = emb.embeddingResultForString_language_error_(t, "en", None)
        if res is None:
            return [0.0] * emb.dimension()
        vecs = []
        res.enumerateTokenVectorsInRange_usingBlock_(
            (0, len(t)), lambda v, _rng, _stop: vecs.append(list(v))
        )
        return np.mean(vecs, axis=0) if vecs else [0.0] * emb.dimension()

    return vector_ranker(chs, lambda ts: [one(t) for t in ts], one)


def fastembed_model(name, chs):
    from fastembed import TextEmbedding

    t0 = time.perf_counter()
    m = TextEmbedding(name, cache_dir=str(PRIVATE / "fastembed_cache"))
    load_s = time.perf_counter() - t0
    r = vector_ranker(
        chs, lambda ts: list(m.embed(ts)), lambda q: next(iter(m.query_embed(q)))
    )
    return (*r, load_s)


# -------------------------------------------------------------------- scoring


def score(rank, queries) -> dict:
    h1 = h3 = rr = 0.0
    t0 = time.perf_counter()
    for qu in queries:
        order = rank(qu["q"])
        pos = order.index(qu["id"]) + 1 if qu["id"] in order else None
        h1 += pos == 1
        h3 += pos is not None and pos <= 3
        rr += 1 / pos if pos else 0
    per_q = (time.perf_counter() - t0) / len(queries) * 1000
    n = len(queries)
    return {"hit@1": h1 / n, "hit@3": h3 / n, "mrr": rr / n, "ms/query": per_q}


def main() -> None:
    notes = load()
    queries = json.loads((PRIVATE / "gsd-spike-004-queries.json").read_text())
    chs = chunks(notes)
    print(f"notes={len(notes)} chunks={len(chs)} queries={len(queries)}\n")
    rows = []

    def add(name, rank, size, **extra):
        r = {"method": name, **score(rank, queries), "index_bytes": size, **extra}
        rows.append(r)
        print(
            f"{name:52} hit@1={r['hit@1']:.2f} hit@3={r['hit@3']:.2f} "
            f"mrr={r['mrr']:.2f} {r['ms/query']:.1f}ms/q "
            f"index={size / 1024:.0f}KiB {extra or ''}"
        )

    add(
        "today: title+snippet substring",
        *substring_ranker(notes, lambda n: n["title"] + " " + n["text"][:200]),
    )
    add(
        "body substring (fold_text, per token)",
        *substring_ranker(notes, lambda n: n["title"] + " " + n["text"]),
    )
    add("FTS5 bm25 (porter, OR of tokens)", *fts5_ranker(notes))

    rank, size, build, dim, rate = native_contextual(chs)
    add(
        "native NLContextualEmbedding mean-pool (public)",
        rank,
        size,
        build_s=round(build, 3),
        dim=dim,
        chunks_per_s=round(rate),
    )
    rank, size, build, dim, rate = native_nl(chs)
    add(
        "native NLEmbedding 'en' (macOS, no download)",
        rank,
        size,
        build_s=round(build, 3),
        dim=dim,
        chunks_per_s=round(rate),
    )
    for name in FASTEMBED:
        rank, size, build, dim, rate, load_s = fastembed_model(name, chs)
        add(
            name,
            rank,
            size,
            build_s=round(build, 3),
            load_s=round(load_s, 1),
            dim=dim,
            chunks_per_s=round(rate),
        )

    out = Path(__file__).parent / "results-retrieval.json"
    out.write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
