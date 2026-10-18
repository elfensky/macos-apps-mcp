# Notes semantic search (NOTE-01, #93)

## Decision

Semantic search for Notes is not adopted. The owner decided this on 2026-09-28.
NOTE-01 (#93) closes on this decision. NOTE-02 (a `notes_semantic` tool behind a
`[semantic]` extra) does not apply.

## Why

Spike 004 measured the real library on this Mac
(`.planning/spikes/004-notes-semantic-cost/README.md`):

- The library holds 17 notes. All bodies together are about 6K tokens. One `note_bodies`
  call already delivers them.
- FTS5 over the decoded bodies lifts hit@1 from 0.31 to 0.54. It needs no new dependency.
- The two public native macOS embedding APIs (`NLEmbedding`, `NLContextualEmbedding`)
  score below the current substring matcher. The better API is private.
- An ONNX model (`all-MiniLM-L6-v2`) reaches hit@1 1.00. It adds 142 MB of packages and an
  87 MB model. An index would also copy note text, which can hold credentials, into a
  second file.

## What ships instead

`notes()` searches note bodies with an FTS5 index. The index lives in memory for one call.
It is built from the bodies the adapter already decodes. No file is written. Locked notes
are never indexed.

## If it is ever adopted

- Embedding model: `all-MiniLM-L6-v2` (ONNX, through fastembed).
- Chunking: 1,000-character chunks, the title prepended to each chunk. The note score is
  the best chunk score.
- Index build and refresh: a sidecar in the server's 0700 state directory, in the shape of
  the Mail FTS sidecar. Each note refreshes on `ZMODIFICATIONDATE1`. Locked notes are
  excluded.
- Size cap: 10,000 notes. The spike extrapolates about 11 minutes for a cold build and
  about 28 MB of vectors at that size. Above the cap, the read says so in `coverage`.
- Optional-extra boundary: only behind a `[semantic]` extra. A plain `uv sync` pulls no ML
  dependency.

## Revisit when

The library grows far past 17 notes (a few thousand).
