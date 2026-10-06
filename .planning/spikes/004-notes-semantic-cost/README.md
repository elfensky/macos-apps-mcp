---
spike: 004
idea: notes-semantic-search
name: notes-semantic-cost
type: standard
validates: "Given the real Notes corpus, when lexical and embedding retrievers index it, then corpus size, build time, index size, dependency weight and retrieval quality are measured for the NOTE-01 decision"
verdict: VALIDATED
related: []
tags: [notes, semantic-search, embeddings, fts5, fastembed, onnx, naturallanguage]
---

# Spike 004: Notes semantic search — cost and quality

## What This Validates

Given the real Notes corpus on this Mac, when three lexical and five embedding retrievers
index it, then the NOTE-01 decision gets numbers for corpus size, build time, index size,
dependency weight and retrieval quality.

**Answer:**

- The corpus is too small to need semantic search.
- Native macOS embeddings are not usable.
- Full-body FTS5 needs no new dependency and closes the largest gap.
- If embeddings are adopted later, the choice is `all-MiniLM-L6-v2` through fastembed/ONNX.
  It adds 142 MB of packages and an 87 MB model.

## Research

- `notes()` today matches a folded substring against **title and snippet only**
  (`adapters/notes.py` `get_pointers`). The body is not searched. `note_bodies` decodes bodies
  from `ZICNOTEDATA.ZDATA` (gzip + protobuf) with `_decode_note_data`, and the spike reuses it.
- Precedent: the Mail FTS5 body sidecar (`mail_index.build_body_index`): own state dir,
  size-capped, resumable.
- Candidates:

| Approach | Tool | Dependency | Status |
|----------|------|-----------|--------|
| Folded substring, title + snippet | current adapter | none | baseline |
| Folded substring, full body | `fold_text` | none | measured |
| FTS5 bm25, full body | sqlite (porter + unicode61, diacritics removed) | none | measured |
| Sentence embedding | `NLEmbedding.sentenceEmbeddingForLanguage("en")`, macOS 11+ | `pyobjc-framework-NaturalLanguage` | measured |
| Contextual embedding, mean-pooled | `NLContextualEmbedding`, macOS 14+ | same | measured |
| Contextual sentence vector | `NLContextualEmbedding.sentenceEmbeddingVector…` | same | **private** on macOS 27 (not in SDK headers or `.tbd`): excluded |
| ONNX sentence model | fastembed `all-MiniLM-L6-v2` | fastembed tree | measured |
| ONNX multilingual model | fastembed `paraphrase-multilingual-MiniLM-L12-v2` | fastembed tree | measured |
| Static embedding | fastembed `potion-multilingual-128M` | fastembed tree | measured |

## How to Run

```sh
export SPIKE_PRIVATE_DIR=<a private dir outside the repo>
uv run --with pyobjc-framework-NaturalLanguage python .planning/spikes/004-notes-semantic-cost/corpus.py
# write $SPIKE_PRIVATE_DIR/gsd-spike-004-queries.json: [{"q": "...", "id": <note Z_PK>}]
uv run --with pyobjc-framework-NaturalLanguage --with fastembed \
    python .planning/spikes/004-notes-semantic-cost/measure.py
```

Note text, titles and the queries stay in `$SPIKE_PRIVATE_DIR`. The repo is public, so only
aggregates are committed (`results-retrieval.json`).

## What to Expect

`corpus.py` prints counts, a length distribution, chunk counts and the language mix.
`measure.py` prints hit@1, hit@3, MRR, ms per query, index size and throughput per method.

## Investigation Trail

1. **Corpus.** 17 notes, 21,084 chars. Median 570 chars, largest 4,570. Chunks: 32 at 1,000
   chars, 19 at 4,000. Languages: en 11, nl 2, and 1 each ro, pt, nb, cs. The short ones may be
   misdetected. 0 locked notes, 0 decoder declines.
2. **Distrusted the count.** The raw store has 49 note rows: 27 have no folder (remnants the
   adapter already drops) and 5 are in Recently Deleted, which leaves 17. The daemon's
   `notes_all` also returns 17.
3. **Content risk.** Several notes hold credentials, tokens and `.env` output. A sidecar would
   copy that text, or embeddings derived from it, into a second file in the server's state dir.
4. **Quality set.** 13 paraphrase queries, one known target note each, deliberately written to
   avoid title words. This favors embeddings over lexical search (see Limits).
5. **Native first.** `NLEmbedding` sentence 'en': hit@3 0.46, worse than today's matcher.
   Tried `NLContextualEmbedding`. Found the macOS 27 `sentenceEmbeddingVector…` selectors, but
   they are private. Mean-pooled public token vectors: hit@3 0.46 at 2 chunks/s.
6. **ONNX.** `all-MiniLM-L6-v2` found every target at rank 1. The multilingual L12 model is
   close behind. The static potion model only ties FTS5.
7. **Reproducibility.** Two runs gave identical quality scores; timing moved within noise.
8. **Footprint.** Clean venv with `fastembed` only: 142 MB, 28 packages (onnxruntime 75 MB,
   numpy 22 MB, PIL 13 MB, tokenizers 9 MB). Base project venv: 100 MB.

## Results

**Verdict: VALIDATED.** The decision inputs are measured.

| Method | hit@1 | hit@3 | MRR | ms/query | Index | Build throughput | Extra install |
|--------|------:|------:|----:|---------:|------:|-----------------:|---------------|
| Today: title + snippet substring | 0.31 | 0.62 | 0.46 | <0.1 | — | — | — |
| Full-body substring (`fold_text`) | 0.31 | 0.62 | 0.47 | 0.1 | — | — | — |
| **FTS5 bm25, full body** | 0.54 | 0.69 | 0.64 | <0.1 | 21 KiB | instant | **none** |
| NLContextualEmbedding, mean-pool | 0.23 | 0.46 | 0.44 | 47 | 64 KiB | 2 chunks/s | pyobjc NL |
| NLEmbedding sentence 'en' | 0.15 | 0.46 | 0.35 | 6 | 64 KiB | 19 chunks/s | pyobjc NL |
| **all-MiniLM-L6-v2 (ONNX)** | **1.00** | **1.00** | **1.00** | 2–15 | 48 KiB | 29 chunks/s | 142 MB + 87 MB model |
| paraphrase-multilingual-MiniLM-L12-v2 | 0.85 | 0.92 | 0.90 | 6 | 48 KiB | 28–32 chunks/s | 142 MB + 240 MB model |
| potion-multilingual-128M (static) | 0.54 | 0.69 | 0.65 | 0.1 | 32 KiB | ~4,600 chunks/s | 142 MB + 537 MB model |

Scaling (extrapolated at 1.9 chunks per note, 1,000-char chunks, 384-dim float32 vectors):
10,000 notes → ~19,000 chunks → ~11 min cold build with MiniLM-L6 and ~28 MB of vectors.
Refresh is incremental per note, keyed on `ZMODIFICATIONDATE1`.

**Signal for the NOTE-01 decision**

- For this library, an index costs more than it returns. All 17 bodies together are about
  6K tokens, which one `note_bodies` call already delivers.
- The largest gap is lexical, not semantic: `notes()` never searches bodies. FTS5 over
  decoded bodies lifts hit@1 from 0.31 to 0.54 with no new dependency.
- Native macOS embeddings are not a path. Both public APIs score below today's substring
  matcher, and the better-looking one is private.
- If a `[semantic]` extra ships later: fastembed + `all-MiniLM-L6-v2`, 1,000-char chunks with
  the title prepended, note score = best chunk, and brute-force cosine in numpy (no vector DB
  at this size). The sidecar must exclude locked notes and live in the 0700 state dir. It
  duplicates note content, including any credentials the notes hold.

**Limits**

- 13 queries on 17 notes. A random ranker already scores hit@3 ≈ 0.18. The gaps between
  methods are large, but the absolute numbers are not stable.
- The queries were written to avoid title words. A calling model that picks keywords, and can
  retry, would narrow the lexical gap.
- The queries are English. The multilingual model's advantage on nl/ro/pt notes is untested.
