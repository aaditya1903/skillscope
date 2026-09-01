# 6. Fetch each candidate at the commit discovery recorded

- Status: accepted
- Date: 2026-08-31

## Context

Ingestion originally fetched each `SKILL.md` from its repository's default
branch and compared the returned blob SHA with the one discovery recorded. A
mismatch was reported as `candidate_changed` and the candidate was dropped.

That is correct behaviour for detecting drift, but it made a frozen manifest
stop reproducing. Re-running the frozen 200-candidate manifest after two
upstream repositories rewrote their skill files produced 142 of the 144
retrieval documents, and the corpus could no longer be rebuilt at all — which
also broke the qrels and evaluation reports bound to it.

## Decision

Fetch the file and its directory metadata at the commit GitHub recorded in the
code-search permalink, which the candidate manifest already stores. Fall back
to the default branch when a manifest entry has no permalink, keeping the
original behaviour and the `candidate_changed` guard.

## Consequences

A frozen manifest resolves to the same bytes for as long as those commits
remain reachable, so the corpus, qrels and evaluation reports stay bound to one
another. Re-running the frozen manifest restored both missing skills and
reproduced the recorded development metrics exactly.

Nothing about drift detection is weakened: the blob SHA is still verified after
the fetch, so a manifest that points at content which has changed identity is
still rejected.

This does not make the corpus permanent. A force-pushed or deleted repository
can still make a commit unreachable, which is a limitation of sampling live
public content and is recorded in the data card.
