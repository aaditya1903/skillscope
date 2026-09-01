# 3. Use exact vector search before any approximate index

- Status: accepted
- Date: 2026-08-25

## Context

pgvector supports HNSW and IVFFlat approximate indexes. Naming one is an easy
way to make a project sound like it operates at scale.

The evaluated corpus holds 144 documents.

## Decision

Use exact cosine-distance search with no approximate index.

## Consequences

Every dense result is the true nearest neighbour, so a ranking difference
between BM25 and dense retrieval is a property of the embeddings rather than an
artefact of an index that traded recall for speed.

Measured dense latency on the evaluated corpus is 14.2 ms p50 and 20.4 ms p95,
which is far below anything that would justify approximate search. Adding an
index here would cost recall and operational complexity to fix a problem that
does not exist.

The threshold for revisiting this is a measurement, not a corpus size that
feels large: an approximate index becomes justified when exact search misses a
stated latency target on the corpus actually being served, and the recall loss
is measured against the same qrels.
