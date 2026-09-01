# 2. Use a local embedding model rather than a hosted API

- Status: accepted
- Date: 2026-08-25

## Context

Dense retrieval needs an embedding model. A hosted embedding API is the least
effort: no download, no local compute, one HTTP call.

## Decision

Use `sentence-transformers/all-MiniLM-L6-v2` locally, pinned to a resolved
revision, on CPU, with normalised 384-dimensional output.

## Consequences

The project has no API key, no per-query cost and no vendor dependency, so
anyone can reproduce the evaluation from a clean clone.

Embeddings are bound to a resolved model revision rather than a mutable model
name, and to a hash of the exact text that was embedded. A model or text change
therefore invalidates stored vectors instead of silently mixing generations.

The model runtime is a multi-gigabyte install, so it is an explicit optional
extra rather than a default dependency. Unit tests use deterministic mock
vectors, one opt-in smoke test exercises the real model, and CI does not depend
on Hugging Face being reachable.

The cost is quality: a small local model is weaker than a large hosted one. The
evaluation reports what this model actually achieved rather than what a larger
one might have.
