# SkillScope

SkillScope is a reproducible observatory for discovering, validating and
searching public Agent Skills.

The project will compare BM25 lexical retrieval, local dense retrieval and
reciprocal-rank-fusion hybrid retrieval using a manually labelled evaluation
set.

Dense retrieval uses the local
[`sentence-transformers/all-MiniLM-L6-v2`](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)
model at a pinned revision, normalized 384-dimensional embeddings, and exact
pgvector cosine search. The heavyweight model runtime is opt-in so ordinary CI
uses deterministic mock vectors and does not depend on a model download.

## Status

SkillScope is under active development toward `v0.1.0`. No retrieval metrics
or corpus counts have been published yet.

## Development

Install the locked environment:

```bash
uv sync --locked
