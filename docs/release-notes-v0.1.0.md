# SkillScope v0.1.0

The first release of an observatory for public Agent Skills: a reproducible
corpus, three retrieval methods, and an evaluation that reports what actually
happened.

## What it does

SkillScope discovers public `SKILL.md` files on GitHub, parses and validates
them against the Agent Skills specification as inert data, stores reproducible
metadata in PostgreSQL with pgvector, and compares BM25, dense and hybrid
retrieval on one frozen corpus.

## Evidence

Eight held-out test queries, evaluated once after the configuration was frozen:

| Method | nDCG@10 | MRR@10 | Recall@10 | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|
| BM25 | 0.8363 | 0.8750 | 0.8750 | 0.584 | 0.958 |
| Dense | 0.8274 | 0.9063 | 0.8542 | 14.203 | 20.448 |
| Hybrid RRF | 0.7788 | 0.8125 | 0.8750 | 13.331 | 14.783 |

BM25 won on this corpus and is the API default. That was not the expected
result, and the report says so rather than re-tuning until hybrid led.

Corpus: 200 candidates discovered, 157 skills stored across 135 repositories,
144 retrieval-eligible, 482 relevance judgements over 24 queries.

Quality: 342 backend tests at 85% coverage, 27 frontend tests, Ruff, strict
mypy, oxlint with warnings denied, and three CI jobs including a container
smoke test.

## Included

- Reproducible GitHub discovery with a committed candidate manifest recording
  every query and page boundary.
- Idempotent ingestion that fetches each file at the commit discovery recorded,
  so a frozen manifest reproduces the same bytes.
- A safe parser that treats YAML frontmatter and Markdown as untrusted data,
  with bounded sizes and a safe loader.
- PostgreSQL and pgvector schema with Alembic migrations.
- Transparent BM25 implemented in-repository, exact pgvector cosine search, and
  reciprocal rank fusion.
- nDCG@10, MRR@10 and judged-pool Recall@10 with a written failure analysis.
- Six read-only versioned API endpoints with interactive OpenAPI documentation.
- A React and TypeScript interface with search, skill detail and observatory
  views.
- A token-free demonstration corpus, container stack and clean-clone
  verification.

## Reproducing this

From a clean clone, with no GitHub token:

```bash
make docker-up
```

To rebuild the evaluated corpus, with a read-only fine-grained token in `.env`:

```bash
make setup && make db-up && make migrate
uv run skillscope ingest run --manifest data/manifests/candidates.jsonl
uv run --extra model skillscope index dense
uv run --extra model skillscope evaluate compare --split development
```

Frozen evidence:

- Candidate manifest `4da341401d807ea9f7436ffb98637f8fb6200afe6b7dbc2e396be2bd2663d8ee`
- Dataset snapshot `d5f2c2ced677a468862edb25bbb8edea8b05ce63039916bbaeb02c7fb78c6562`
- Qrels `e437c04690c5c6de5dd8b777d8290c77b6a5ce49a1889c10ea5dc7718a32eecc`
- Test report `6967f552d2afd4f94b34a5daea036d5d6669f0ae51635616f4a22a7e6e359088`
- Embedding model `sentence-transformers/all-MiniLM-L6-v2` at revision
  `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`

## Known limitations

- The corpus is a reproducible sample, not a census. Four discovery queries and
  one seed repository decide what is in it.
- Recall is judged-pool recall over BM25 results plus authored seeds.
- One labeller, so there is no inter-annotator agreement figure.
- 144 documents and eight test queries mean small metric differences are not
  statistically strong.
- Validation measures specification conformance, not usefulness.

Details in [docs/data-card.md](data-card.md) and
[docs/evaluation.md](evaluation.md).

## Security and licensing

Indexed skills are untrusted third-party content. Nothing discovered is ever
executed. No complete upstream `SKILL.md` bodies or supporting files are
committed. The frozen evaluation pool retains bounded, source-attributed
description excerpts of at most 500 characters for auditability. Each skill
remains under its own repository licence. SkillScope's own source is MIT.

See [SECURITY.md](../SECURITY.md) and
[docs/threat-model.md](threat-model.md).
