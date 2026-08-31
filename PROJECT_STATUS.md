# SkillScope Project Status

## Project contract

SkillScope is an Agent Skills observatory that discovers public `SKILL.md`
files, parses and validates them safely, stores reproducible metadata, and
compares lexical, dense and hybrid retrieval using objective evaluation.

The project's principal technical evidence is the evaluated retrieval system,
not the user interface.

## Release policy

- Repository visibility: private during development
- Public release: only after the `v0.1.0` definition of done passes
- Public metrics: generated from reproducible commands only
- Third-party bodies: never committed as a dataset
- Secrets: local environment variables only

## Current milestone

- Milestone: 10, React and TypeScript interface
- Objective: build the accessible search, skill-detail and observatory views on the verified versioned API
- Exit gate: frontend type check, tests and production build pass; loading, empty and error states render; source links are safe; indexed content cannot inject HTML or script; the layout works on laptop and mobile
- Status: active

## P0 release checklist

- [x] Reproducible GitHub discovery and ingestion
- [x] Safe Agent Skills parser and validation
- [x] PostgreSQL/pgvector schema and migrations
- [x] Frozen dataset snapshot
- [x] BM25 implementation and tests
- [x] Labelled queries and qrels
- [x] Dense retrieval
- [x] Hybrid RRF retrieval
- [x] nDCG@10, MRR@10 and Recall@10 evaluation
- [x] Versioned FastAPI endpoints
- [ ] Minimal React/TypeScript search, detail and statistics interface
- [ ] Unit and integration tests
- [ ] Docker Compose demonstration
- [x] GitHub Actions green
- [ ] README, architecture, data card, evaluation and threat model
- [ ] Clean-clone verification

## P1 portfolio checklist

- [ ] Additional interface polish and visualisations
- [ ] Richer query filters and score explanations
- [ ] p50 and p95 latency benchmark
- [ ] Demo GIF or video
- [ ] Social-preview image
- [ ] `v0.1.0` GitHub release

## P2 deferred scope

- [ ] User accounts
- [ ] LLM-generated summaries
- [ ] Recommendation systems
- [ ] Scheduled cloud ingestion
- [ ] Multiple embedding models
- [ ] Learning-to-rank
- [ ] Approximate vector indexes without a measured need
- [ ] Kafka or Kubernetes
- [ ] Marketplace or installation workflow

## Current verified metrics

- Development platform: macOS 26.0.1 arm64
- Python runtime: 3.12.14
- Backend tests: 289 passing in the full Milestone 8 local quality gate
- Backend coverage: 84% in the full Milestone 8 local quality gate
- PostgreSQL-backed integration tests: 20 passing
- Parser core tests: 11 passing
- Parser structural-signal tests: 10 passing
- Total parser tests: 21 passing
- GitHub payload and validation tests: 28 passing
- GitHub REST transport tests: 30 passing
- GitHub endpoint tests: 26 passing
- Total GitHub payload and client tests: 84 passing
- Deterministic discovery tests: 10 passing
- Discovery seeds: 1 checked-in public repository identifier
- Discovery queries: 4 deterministic seed-first and broad code-search queries
- Discovery candidate handling: public-only filtering, repository-ID/path deduplication, stable sorting and conflict detection verified
- Candidate manifest tests: 16 passing
- Candidate manifest format: versioned canonical UTF-8 JSONL recording run metadata, exact queries, page boundaries and candidate identifiers
- Candidate manifest determinism: byte-for-byte serialization and validated read/write round trips verified
- Candidate manifest safety: atomic replacement preserves prior files on failure; upstream skill bodies are excluded
- Dataset snapshot tests: 9 passing, including PostgreSQL-backed reconciliation
- Dataset snapshot format: canonical versioned UTF-8 JSONL containing identifiers, hashes, statuses and safe failures only
- Ingestion runner behavior: transactional upserts, unchanged-SHA detection, per-item continuation and reconciled run counters verified
- Integration-test isolation: each test sees an empty application schema while its outer rollback restores pre-existing test-database rows
- Repository-root skill handling: safe root `SKILL.md` paths are retained with an explicit `root_directory_name_unverified` warning
- Milestone 4 exit gate: complete
- Milestone 5 exit gate: complete
- Milestone 6 exit gate: complete
- Live candidate manifest: `data/manifests/candidates.jsonl`
- Frozen dataset snapshot: `data/manifests/dataset-snapshot.jsonl`
- Snapshot source commit: `0aba78808db36a40c79d5b272a929b1fb8ab4de0`
- Candidate manifest evidence: 200 unique candidates across 169 public repositories; 95,331 bytes
- Candidate manifest SHA-256: `4da341401d807ea9f7436ffb98637f8fb6200afe6b7dbc2e396be2bd2663d8ee`
- Dataset snapshot evidence: 200 reconciled candidate outcomes; 77,770 bytes
- Dataset snapshot SHA-256: `d5f2c2ced677a468862edb25bbb8edea8b05ce63039916bbaeb02c7fb78c6562`
- Database state: 169 repositories and 157 stored skills after the clean ingestion run
- Stored-skill repository coverage: 135 repositories
- Retrieval-eligible frozen corpus: 144 skills, comprising 51 valid and 93 warning-status skills
- Stored invalid skills: 13, retained as explicit validation evidence and excluded from the retrieval corpus
- First 200-candidate run: 144 ingested, 56 invalid, 0 unchanged, 0 skipped and 0 errors
- Identical rerun: 0 ingested, 157 unchanged, 43 invalid, 0 skipped and 0 errors
- Ingestion audit trail: 2 completed runs with no duplicate skill rows
- Ingestion failure evidence: every unsuccessful item has a stable validation category, safe message and machine-readable codes
- Manifest/database reconciliation: candidate, item, stored-skill and repository counts verified
- Frozen-evidence safety: candidate manifest and dataset snapshot are token-free and upstream-body-free
- Discovery limitations: documented in `docs/discovery.md`; results are a reproducible sample, not a complete census
- BM25 frozen corpus: 144 valid or warning-status skills with an average document length of 1,142.22 tokens
- BM25 parameters: `k1 = 1.5`, `b = 0.75`, binary repeated-query-term weighting and no stemming or stop-word removal
- BM25 test additions: 20 text-processing, configuration and ranking unit tests; 2 CLI tests; 4 PostgreSQL corpus-integrity tests
- BM25 hand calculations: IDF, term contribution and length normalization match independent reference calculations
- BM25 edge cases: empty queries, unseen terms, duplicate documents, Unicode technical tokens, bounded top-k and deterministic ties verified
- BM25 stale-corpus protection: snapshot, candidate-manifest, stored-content and validation-status drift verified
- BM25 manual review: all 5 smoke queries returned a clearly relevant skill within the top 5
- BM25 direct-intent ranks across the 5 smoke queries: 2, 1, 2, 5 and 1
- BM25 qualitative limitation: unweighted term frequency and document-length effects can rank adjacent document tools or broadly matching skills above the most literal skill; the PDF query was the weakest case
- BM25 CLI: deterministic JSON results expose matched terms and per-term score components without returning skill bodies
- Ruff formatting: passing across 122 files
- Ruff linting: passing
- Strict mypy: passing across 56 source files
- CLI version command: 0.1.0
- API liveness: /healthz returned HTTP 200 with the expected response
- Database service: PostgreSQL 18.6 healthy through Docker Compose
- Vector extension: pgvector 0.8.6
- Migration head: 8c0d2f64a1b7
- Migration round trip: base -> head -> base -> head passing
- Alembic migration drift: no new upgrade operations detected
- Alembic logging isolation: existing application loggers remain enabled during migration-backed workflows
- GitHub REST transport: authenticated, versioned and read-only
- GitHub REST transport endpoints: rate-limit inspection, repository metadata, code search, file contents and directory metadata
- GitHub REST transport reliability: bounded retries, explicit timeouts and maximum concurrency of five verified
- GitHub rate-limit handling: Retry-After, reset timestamps and exhausted-limit behavior verified
- GitHub transport security: authorization redaction, safe error messages and GitHub-only redirects verified
- GitHub request observability: correlation IDs verified in structured logs
- Authenticated GitHub REST client smoke test: search, repository, file, directory and HTTP 304 paths passing
- Official seed search: 20 indexed SKILL.md matches in anthropics/skills
- Authenticated API limits observed: 5,000 core requests/hour, 30 search requests/minute and 10 code-search requests/minute
- GitHub code-search pagination: live Link header observed; bounded safe-link following verified with mocked tests
- GitHub contents conditional request: HTTP 304 verified using ETag in live and mocked tests
- GitHub content safety bounds: 256 KiB files, 1,000 directory entries and strict Base64 validation
- GitHub REST API version: 2026-03-10
- Formal retrieval evaluation: BM25, exact dense and hybrid RRF development/test comparison complete
- Frozen evaluation queries: 24 total, comprising 16 development and 8 locked test queries
- Evaluation query provenance: canonical JSONL tied to the frozen dataset snapshot SHA-256
- Evaluation pooling design: union of BM25 top-20 results and pre-authored query seeds, with deterministic rank- and split-blinded worksheet ordering
- Evaluation relevance scale: 0 not relevant, 1 partially relevant and 2 highly relevant
- Evaluation identity contract: portable GitHub repository ID/path document IDs plus frozen content SHA-256, resolved to live skill UUIDs during validation
- Evaluation metrics implemented: macro nDCG@10, MRR@10 and Recall@10 with graded gain and hand-calculated unit tests
- Evaluation leakage protection: test metrics require an explicit unlock and remain prohibited until the final Milestone 8 comparison
- Milestone 7 Batch 1 tests: 53 query-contract, qrel-validation, pooling, worksheet-safety, metric, report and CLI tests
- Frozen qrels: 482 complete judgements across all 24 queries, comprising 435 grade-0, 21 grade-1 and 26 grade-2 judgements
- Qrel provenance: rank- and split-blinded AI-assisted pre-annotations reviewed by the project author before import; every relevant judgement includes a rationale
- Qrels SHA-256: `e437c04690c5c6de5dd8b777d8290c77b6a5ce49a1889c10ea5dc7718a32eecc`
- Qrel integrity: all 482 stable document IDs and content hashes resolve against the frozen 144-skill corpus; every query has at least one relevant judgement
- BM25 development evaluation: 16 queries, nDCG@10 `0.8159700661`, MRR@10 `0.9131944444` and judged-pool Recall@10 `0.8500000000`
- BM25 development failure examples: `q008` first relevant result at rank 9; `q009` missed 1 of 3 relevant pooled items; `q005` retrieved 3 of 5 relevant pooled items in the top 10
- Evaluation limitation: Recall@10 measures recall over the judged BM25-plus-seed pool, not unknown relevant skills outside that pool
- Test-split discipline: configuration and code were frozen before one final three-method test comparison; the canonical test report refuses overwrite
- Milestone 7 exit gate: complete
<!-- M8_VERIFIED_METRICS_START -->
- Milestone 8 exit gate: complete
- Dense/hybrid retrieval configuration SHA-256: `75a447cfa29f7a072805224f95c998be6e045f011e4f5642ca01d247fa4c12d3`
- Embedding model: `sentence-transformers/all-MiniLM-L6-v2` at revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`
- Embedding runtime: sentence-transformers `6.0.0`, CPU, 384 dimensions and unit normalization
- Embedding coverage: 144 of 144 frozen retrieval-eligible skills with complete content/config/model provenance
- Dense retrieval: exact pgvector cosine distance with no ANN index
- Hybrid retrieval: equal-weight reciprocal rank fusion over top-50 BM25 and dense candidates with `k = 60`
- Development comparison report: `reports/evaluation/method-comparison-development-v1.json`; SHA-256 `bb49125eeb0ec693cd95d42325a3019e375a71c4981c8bb1eca5eeb4a0af211c`
- Final test comparison report: `reports/evaluation/method-comparison-test-v1.json`; SHA-256 `6967f552d2afd4f94b34a5daea036d5d6669f0ae51635616f4a22a7e6e359088`
- Development `bm25`: nDCG@10 `0.8159700661`, MRR@10 `0.9131944444`, judged-pool Recall@10 `0.8500000000`, p50 `0.649` ms and p95 `1.048` ms
- Development `dense`: nDCG@10 `0.8778725187`, MRR@10 `0.9375000000`, judged-pool Recall@10 `0.8937500000`, p50 `16.721` ms and p95 `71.556` ms
- Development `hybrid`: nDCG@10 `0.8777519964`, MRR@10 `0.9166666667`, judged-pool Recall@10 `0.9875000000`, p50 `17.841` ms and p95 `24.408` ms
- Final test `bm25`: nDCG@10 `0.8363377669`, MRR@10 `0.8750000000`, judged-pool Recall@10 `0.8750000000`, p50 `0.584` ms and p95 `0.958` ms
- Final test `dense`: nDCG@10 `0.8273775132`, MRR@10 `0.9062500000`, judged-pool Recall@10 `0.8541666667`, p50 `14.203` ms and p95 `20.448` ms
- Final test `hybrid`: nDCG@10 `0.7788241976`, MRR@10 `0.8125000000`, judged-pool Recall@10 `0.8750000000`, p50 `13.331` ms and p95 `14.783` ms
- Retrieval comparison safety: development/test inputs match; reports are token-free and upstream-body-free
- Milestone 8 implementation commit: `5c3407f2649fd23448361623355b68decfc88a9c`
- Milestone 8 implementation CI run: [32799235688](https://github.com/aaditya1903/skillscope/actions/runs/32799235688)
<!-- M8_VERIFIED_METRICS_END -->
<!-- M9_VERIFIED_METRICS_START -->
- Milestone 9 exit gate: complete
- Backend tests: 328 passing and 1 opt-in model smoke test skipped
- Backend coverage: 85% against the 80% threshold
- API surface: `/healthz`, `/readyz`, `/api/v1/search`, `/api/v1/skills/{skill_id}`, `/api/v1/stats` and `/api/v1/evaluations/latest`
- API liveness and readiness: `/healthz` answers without PostgreSQL while `/readyz` verified database, 144-document frozen retrieval evidence and the pinned model runtime
- API retrieval modes: `bm25`, `dense` and `hybrid` verified against the populated local database with method-specific score explanations
- API filters: licence, validation and script filters verified, including the empty result an `invalid` validation filter correctly produces
- API error paths verified: 400 whitespace query, 404 missing skill, 422 invalid UUID, enum, bound and missing parameter
- API leakage checks: no body sentinel, token, database URL or stack trace in responses or logs
- API CORS: exactly one configured origin echoed; a foreign origin received no allow-origin header
- OpenAPI: 3.1.0 with 6 documented operations, 31 schemas and `/docs` reachable
- Uvicorn access log disabled in `skillscope serve` so raw query strings are never recorded
- Corpus reload cost before caching: roughly 393 ms of reconciliation plus 57 ms of BM25 index construction per request
- Warm API latency after caching: BM25 about 10 ms, dense and hybrid about 45 ms per whole request
- Corpus cache invalidation: verified to rebuild and reject drift rather than serve a stale corpus
- Ingestion commit pinning: candidates are fetched at the discovery permalink commit
- Frozen-manifest rerun after pinning: 2 previously `candidate_changed` skills restored; 155 unchanged; 43 invalid; 0 errors
- Restored database state: 169 repositories, 157 stored skills and the frozen 144-document retrieval corpus
- Restored embedding coverage: 144 of 144 at model revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`
- Reproduced development comparison on the restored corpus: `bm25` nDCG@10 `0.8159700661`, `dense` `0.8778725187` and `hybrid` `0.8777519964`, matching the Milestone 8 report exactly
<!-- M9_VERIFIED_METRICS_END -->
- Private GitHub repository: aaditya1903/skillscope
- GitHub Actions: passing
- Milestone 5 implementation commit: `0aba78808db36a40c79d5b272a929b1fb8ab4de0`
- Milestone 5 implementation CI run: [32766779848](https://github.com/aaditya1903/skillscope/actions/runs/32766779848)
- Milestone 6 implementation commit: `c71aa40f388c88aa7fe9d5c8124c8fca52228d3d`
- Milestone 6 implementation CI run: [32777591410](https://github.com/aaditya1903/skillscope/actions/runs/32777591410)

## Decisions

| Decision | Reason | Date | ADR |
|---|---|---|---|
| Keep the repository private until release | Allows security and evidence review before publication | 2026-08-23 | Not required |
| Use Python 3.12 through `uv` | Strong dependency compatibility without modifying system Python | 2026-08-23 | Not required |
| Pin Node 24 LTS when frontend work begins | Prefer an LTS runtime for local development and CI | 2026-08-23 | Not required |
| Treat PostgreSQL as the source of truth | Required for realistic JSONB, migrations and pgvector behaviour | 2026-08-23 | Planned |
| Build evaluated retrieval before the interface | Evaluation is the project's central technical contribution | 2026-08-23 | Planned |
| Keep upstream skill bodies out of committed datasets | Respect licensing and redistribution boundaries | 2026-08-23 | Planned |
| Manage pgvector through the initial migration | Guarantees reproducible extension setup and a reversible clean-database migration | 2026-08-23 | Not required |
| Represent non-native enums with explicit named CHECK constraints | Preserves Python enum validation while allowing Alembic 1.19 to compare the constraints accurately | 2026-08-23 | Not required |
| Pin GitHub REST requests to version `2026-03-10` | Live contents response confirmed the selected version; explicit versioning prevents silent API drift | 2026-08-23 | Not required |
| Bound fetched skill files and directory metadata | Limits memory use and keeps untrusted GitHub responses within explicit ingestion constraints | 2026-08-24 | Not required |
| Deduplicate discovered skills by GitHub repository ID and path | Repository IDs remain stable across renames while the path identifies the file within a repository | 2026-08-24 | Not required |
| Store candidate manifests as canonical versioned JSONL | Supports deterministic diffs, streaming validation and reproducible discovery evidence without committing upstream bodies | 2026-08-24 | Not required |
| Treat discovery output as a reproducible sample rather than a census | GitHub search caps, scope restrictions, index changes and query choices make exhaustiveness unverifiable | 2026-08-24 | Not required |
| Treat repository-root `SKILL.md` as safe but parent-name-unverifiable | GitHub repository-relative paths do not encode the local clone directory name, so root files receive an explicit warning while nested paths retain strict validation | 2026-08-24 | Not required |
| Isolate integration tests with transactional baseline cleanup | Tests must remain deterministic even after legitimate live evidence has populated the isolated test database | 2026-08-24 | Not required |
| Freeze 200 candidate outcomes and use 144 valid or warning-status skills for retrieval | Preserves truthful validation evidence while keeping invalid records out of the evaluated retrieval corpus | 2026-08-24 | Not required |
| Use ordinary unweighted BM25 with binary repeated-query-term weighting | Keeps the first lexical baseline transparent and prevents repeated query words from silently multiplying their influence | 2026-08-24 | Not required |
| Keep stop words and avoid stemming in the initial BM25 baseline | Preserves a reproducible untuned baseline whose weaknesses can be measured against labelled development queries | 2026-08-24 | Not required |
| Do not tune BM25 on the five manual smoke queries | The smoke review checks basic usefulness; parameter choices must wait for the frozen development split to avoid informal overfitting | 2026-08-24 | Not required |
| Freeze 24 task-oriented queries into a 16-development and 8-test split | Provides enough category diversity for a portfolio evaluation while keeping manual qrel labelling tractable | 2026-08-25 | Not required |
| Use stable repository-ID/path document identifiers with content hashes in qrels | Database UUIDs can change after clean ingestion, while repository IDs, paths and frozen hashes remain portable and drift-detectable | 2026-08-25 | Not required |
| Blind candidate ranks during relevance labelling | Prevents the labeller from treating BM25 order as ground truth while retaining full pooling provenance separately | 2026-08-25 | Not required |
| Lock test metrics behind an explicit release flag | Keeps embedding and hybrid configuration decisions restricted to development evidence | 2026-08-25 | Not required |
| Use AI-assisted blinded pre-annotations with explicit author review | Reduces manual transcription while preserving accountable human acceptance of every positive or partial relevance decision | 2026-08-25 | Not required |
| Report Recall@10 as judged-pool recall | The BM25-plus-seed pool is reproducible but cannot establish relevance for unjudged documents outside the pool | 2026-08-25 | Not required |
| Pin `all-MiniLM-L6-v2` by resolved model revision and retrieval-config hash | Model names and mutable branches are insufficient provenance for reproducible stored embeddings | 2026-08-25 | Not required |
| Keep the real embedding runtime as an explicit local extra | Deterministic mock-vector tests should keep CI independent of Hugging Face availability and multi-gigabyte PyTorch downloads | 2026-08-25 | Not required |
| Use exact pgvector cosine search without an ANN index | The 144-document frozen corpus does not justify approximate-search recall loss or operational complexity | 2026-08-25 | Not required |
| Fuse top-50 BM25 and dense ranks with equal-weight RRF at `k = 60` | Rank fusion avoids adding incomparable lexical and cosine score scales while preserving source-rank explanations | 2026-08-25 | Not required |
| Use BM25 as the API default while retaining explicit dense and hybrid modes | BM25 achieved the highest held-out nDCG@10 and sub-millisecond p95 latency; exposing every mode preserves comparison evidence without implying raw scores are comparable | 2026-08-25 | Not required |
| Keep the retrieval API read-only and return only bounded body excerpts | Separating observatory reads from ingestion writes and raw upstream content reduces the public attack and leakage surface | 2026-08-25 | Not required |
| Fetch each candidate at the commit recorded by discovery | The default branch may already serve different bytes, which made a frozen manifest unreproducible; the permalink commit is existing manifest evidence | 2026-08-31 | Planned |
| Cache the reconciled corpus behind a configuration and stored-skill fingerprint | Tokenizing 144 documents per request cost roughly 450 ms; the fingerprint still forces the rebuild that rejects any drift | 2026-08-31 | Not required |
| Normalise declared-tool separators for aggregate display only | The specification calls `allowed-tools` space separated, so stored parser evidence must stay verbatim while statistics stay readable | 2026-08-31 | Not required |

## Blockers

No active blockers.

## Next three actions

1. Scaffold the React, TypeScript and Vite workspace with a typed API client.
2. Implement the search, skill-detail and observatory views with accessible loading, empty and error states.
3. Add focused component tests and wire frontend lint, type-check, test and build into CI.
