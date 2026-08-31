# Versioned retrieval API

SkillScope exposes a small read-only FastAPI surface over the frozen corpus.
The API never performs discovery, ingestion, parsing, or embedding writes.
Every response model is strict and OpenAPI is generated from the same Pydantic
types used at runtime.

## Runtime requirements

Run from the repository root with:

~~~bash
uv sync --locked --extra model
docker compose up -d --wait --wait-timeout 60 db
uv run alembic upgrade head
uv run --extra model skillscope serve
~~~

FRONTEND_ORIGIN configures the one permitted browser origin and defaults to
http://localhost:5173. Wildcard CORS is not enabled.

## Health semantics

GET /healthz proves only that the application process can answer HTTP. It does
not query PostgreSQL and remains healthy when external dependencies fail.

GET /readyz checks:

1. PostgreSQL connectivity;
2. the frozen snapshot and candidate-manifest hashes;
3. database-to-snapshot reconciliation;
4. current 384-dimensional embedding and provenance coverage; and
5. the pinned sentence-transformers runtime version.

It returns HTTP 200 with status ready only when every check passes. Otherwise
it returns HTTP 503 with safe per-check status. It never includes a database
URL, exception, token, or stack trace.

## Search

GET /api/v1/search accepts:

| Parameter | Contract |
|---|---|
| q | Required, trimmed, 1 to 500 characters |
| mode | bm25, dense, or hybrid; default bm25 |
| limit | Default 10, minimum 1, maximum 50 |
| license_status | Optional permissive, restrictive, missing, or unknown |
| validation_status | Optional valid, warning, or invalid |
| has_scripts | Optional boolean |

Filters are applied before candidate selection by every method. Invalid skills
are absent from the frozen retrieval corpus, so an invalid validation filter
correctly produces no search results rather than bypassing corpus eligibility.

Each response records the normalized query, method, limit, elapsed time,
snapshot path and SHA-256, and a request ID. Results contain safe display
metadata, repository provenance, validation status, and method-specific score
components:

- BM25 returns matched terms and each term's TF, DF, IDF, and contribution.
- Dense returns exact cosine similarity and cosine distance.
- Hybrid returns the RRF score, BM25 and dense ranks, and source scores.

BM25, cosine similarity, and RRF are different quantities. Scores may be
compared only within the same response and method. Hybrid fusion uses ranks
rather than adding incomparable raw scores.

Retrieval concurrency is bounded to five requests per process. Excess work is
rejected immediately with HTTP 429 and Retry-After: 1, preventing an unbounded
CPU/model queue.

took_ms measures the whole service call, including response metadata, and is
not comparable to the retrieval-only p50 and p95 figures in the evaluation
report.

## Corpus caching

Reconciling the frozen corpus tokenizes every document, so a serving process
keeps the reconciled corpus and its BM25 index in memory. The cache is keyed on
both configuration files' SHA-256, the snapshot SHA-256, and a stored-skill
fingerprint covering every content hash, validation status, script flag, and
repository licence status.

Any drift changes that key and forces the full reconciling rebuild, which then
rejects the stale corpus exactly as an uncached load would. The cache therefore
removes repeated work without weakening the integrity guarantee.

## Skill detail

GET /api/v1/skills/{skill_id} accepts a database UUID. A missing UUID returns
HTTP 404; an invalid UUID shape returns HTTP 422.

The response includes:

- standard frontmatter fields and string metadata;
- parser validation messages;
- safe structural counts and feature flags;
  has_scripts, has_references, and has_assets report that the named directory
  exists, while the matching counts report supporting files actually recorded.
  Ingestion inspects only the immediate skill directory, so a skill with a
  populated scripts/ subdirectory reports has_scripts with script_count 0;
- supporting-file path, type, size, and extension metadata;
- repository and upstream licence evidence;
- source links; and
- at most 2,000 characters of a control-character-filtered plain-text excerpt.

The query keeps body_text deferred and asks PostgreSQL for only the bounded
prefix. Extension fields, complete bodies, raw scripts, file contents, and
repository bundles are not returned.

## Statistics

GET /api/v1/stats returns repository, stored-skill, and retrieval-eligible
counts; validation distributions; repository licence distributions; feature
counts; the 20 most common normalized declared tools; latest completed
ingestion time; and snapshot identity.

The specification calls allowed-tools space separated, so the parser stores the
whitespace-split tokens verbatim. Trailing separators left by authors who write
comma-separated lists are folded out of these aggregate counts only; stored
evidence is never rewritten.

Repository licence counts describe repositories, while validation and feature
counts describe skills.

## Evaluation

GET /api/v1/evaluations/latest validates and summarizes the canonical locked
test report at reports/evaluation/method-comparison-test-v1.json.

It returns the report hash, generation time, source commit, test split,
snapshot identity, pinned dense/hybrid configuration, and aggregate
effectiveness and latency for BM25, dense, and hybrid. Per-query text,
rankings, qrels, and failure examples are deliberately omitted from this
public summary.

## Errors and request correlation

Errors use one envelope:

~~~json
{
  "request_id": "32 lowercase hexadecimal characters",
  "error": {
    "code": "stable_machine_code",
    "message": "Safe client-facing message.",
    "fields": []
  }
}
~~~

Supported error classes are HTTP 400, 404, 422, 429, 500, and 503. Validation
responses report field names and stable categories but never echo rejected
input. Unexpected exceptions return a generic 500 envelope.

Every response includes X-Request-ID. Structured access logs record only the
generated request ID, method, status, and duration. Query text, URLs,
authorization values, bodies, and exception messages are not access-log
fields. `skillscope serve` disables Uvicorn's own access log, which would
otherwise record raw query strings alongside it.

## OpenAPI verification

Inspect the live contract at:

- /openapi.json
- /docs

Automated tests verify every route, query bound, response schema, structured
error, CORS origin, request ID, readiness failure, all retrieval modes,
filters, missing skills, leakage boundaries, and the runtime/OpenAPI path set.
