# SkillScope

SkillScope is a reproducible observatory for discovering, validating, searching,
and evaluating public Agent Skills.

Its central result is an evidence-backed retrieval system rather than a UI
demo. The same frozen 144-skill corpus is searched with transparent BM25,
exact local dense retrieval, and reciprocal-rank-fusion hybrid retrieval. A
manually reviewed query set and qrels measure nDCG@10, MRR@10, and judged-pool
Recall@10 on development and locked test splits.

## Current evidence

- 200 discovered candidates across 169 public repositories
- 157 stored skills, including explicit invalid-skill evidence
- 144 valid or warning-status retrieval documents
- 482 relevance judgements across 24 frozen queries
- pinned all-MiniLM-L6-v2 revision and 144/144 embedding provenance
- exact pgvector cosine search with no approximate index
- successful BM25, dense, and hybrid held-out comparison

The final eight-query test results are:

| Method | nDCG@10 | MRR@10 | Recall@10 | p50 | p95 |
|---|---:|---:|---:|---:|---:|
| BM25 | 0.8363 | 0.8750 | 0.8750 | 0.584 ms | 0.958 ms |
| Dense | 0.8274 | 0.9063 | 0.8542 | 14.203 ms | 20.448 ms |
| Hybrid RRF | 0.7788 | 0.8125 | 0.8750 | 13.331 ms | 14.783 ms |

BM25 is therefore the API default: it has the highest held-out nDCG@10 and is
substantially faster on this corpus. Dense and hybrid remain explicit modes,
and their raw scores are never presented as numerically comparable.

## Development setup

Requirements:

- Python 3.12
- uv
- Docker with Compose

Install the locked ordinary development environment:

~~~bash
uv sync --locked
~~~

Install the pinned local embedding runtime when running dense or hybrid search:

~~~bash
uv sync --locked --extra model
~~~

Start PostgreSQL 18 with pgvector and apply migrations:

~~~bash
docker compose up -d --wait --wait-timeout 60 db
uv run alembic upgrade head
~~~

The checked-in snapshot expects the database state produced during the
reproducible ingestion milestones. See [ingestion.md](docs/ingestion.md) for
the evidence and commands, and [retrieval.md](docs/retrieval.md) for indexing
and ranking contracts.

## Versioned API

Start the API from the repository root:

~~~bash
uv run --extra model skillscope serve
~~~

The public surface is:

- GET /healthz
- GET /readyz
- GET /api/v1/search
- GET /api/v1/skills/{skill_id}
- GET /api/v1/stats
- GET /api/v1/evaluations/latest

Example searches:

~~~bash
curl --get http://127.0.0.1:8000/api/v1/search \
  --data-urlencode 'q=create and edit spreadsheets'

curl --get http://127.0.0.1:8000/api/v1/search \
  --data-urlencode 'q=build an MCP server' \
  --data-urlencode 'mode=dense' \
  --data-urlencode 'limit=5'
~~~

Interactive OpenAPI documentation is available at
http://127.0.0.1:8000/docs. See [api.md](docs/api.md) for filters, score
explanations, error envelopes, readiness semantics, and security boundaries.

## Interface

The React and TypeScript client is a demonstration layer over the evaluated
retrieval system. Start the API first, then:

~~~bash
npm ci --prefix frontend
npm run dev --prefix frontend
~~~

It serves on http://localhost:5173, which is the single origin the API's CORS
policy allows by default. The client offers search with all three retrieval
modes and filters, a skill-detail view and an observatory view carrying the
corpus distributions and the held-out comparison. See
[interface.md](docs/interface.md).

Frontend checks:

~~~bash
npm run lint --prefix frontend
npm run typecheck --prefix frontend
npm test --prefix frontend
npm run build --prefix frontend
~~~

## Quality gate

Start the isolated test database, then run the complete local gate:

~~~bash
docker compose --profile test up -d --wait --wait-timeout 60 db-test
export SKILLSCOPE_TEST_DATABASE_URL='postgresql+psycopg://skillscope_test:skillscope_test@127.0.0.1:5433/skillscope_test'

uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest --cov=skillscope --cov-report=term-missing --cov-fail-under=80
DATABASE_URL="$SKILLSCOPE_TEST_DATABASE_URL" uv run alembic current
DATABASE_URL="$SKILLSCOPE_TEST_DATABASE_URL" uv run alembic check
git diff --check
~~~

The real model smoke test is intentionally opt-in so ordinary CI does not
depend on Hugging Face availability:

~~~bash
SKILLSCOPE_RUN_MODEL_SMOKE=1 \
  uv run --extra model pytest tests/model -v
~~~

## Safety and reproducibility

- GitHub ingestion is authenticated, read-only, versioned, rate-limit aware,
  bounded, and covered by offline transport tests.
- SKILL.md files are parsed as untrusted inert data. Their instructions,
  links, and scripts are never executed.
- Candidate and dataset manifests contain identifiers, hashes, statuses, and
  safe failures, never upstream bodies or tokens.
- Search responses use safe snippets. Detail responses return a bounded
  plain-text excerpt and supporting-file metadata, never raw scripts or a full
  bundle.
- Frozen hashes bind discovery, ingestion, qrels, configuration, embeddings,
  and reports to exact evidence bytes.
- The test split was evaluated once after configuration was frozen.

## Documentation

- [Discovery and sampling limits](docs/discovery.md)
- [Ingestion and frozen dataset](docs/ingestion.md)
- [Retrieval design and score semantics](docs/retrieval.md)
- [Evaluation methodology and limitations](docs/evaluation.md)
- [Versioned API contract](docs/api.md)
- [Interface structure and safety](docs/interface.md)

SkillScope remains private while development proceeds toward v0.1.0. The full
verified checkpoint is maintained in [PROJECT_STATUS.md](PROJECT_STATUS.md).
