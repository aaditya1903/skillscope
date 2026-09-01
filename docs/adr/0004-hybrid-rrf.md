# 4. Fuse rankings with reciprocal rank fusion, not score addition

- Status: accepted
- Date: 2026-08-25

## Context

Hybrid retrieval has to combine a BM25 ranking with a dense ranking. The
shortest implementation adds the two scores, optionally after scaling them.

BM25 scores are unbounded sums of term contributions whose magnitude depends on
corpus statistics and document length. Cosine similarities lie in [-1, 1] and
mean something entirely different. Adding them produces a number with no
interpretation, and min-max normalising them per query makes the result depend
on which documents happened to be retrieved.

## Decision

Fuse the rankings with reciprocal rank fusion over the top 50 candidates from
each retriever, with `k = 60` and equal weights:

```text
RRF(d) = sum over rankers r of weight_r / (k + rank_r(d))
```

## Consequences

Only ranks are combined, so the incomparable score scales never meet. A
document ranked highly by either retriever is promoted, and agreement between
them promotes it further.

Search responses return the BM25 rank, the dense rank and the fused score, so a
hybrid result can be explained. The source scores are returned for debugging
and are explicitly labelled as never being summed.

The parameters were chosen on the development split and frozen before the test
split ran once. On the held-out split hybrid did not beat BM25, and the
evaluation report says so rather than re-tuning until it did.
