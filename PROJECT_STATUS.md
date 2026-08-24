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

- Milestone: 6, BM25 baseline
- Objective: implement transparent lexical retrieval over the frozen Milestone 5 corpus with deterministic scoring and explanations
- Exit gate: hand-calculated tests pass; BM25 returns sensible results for at least five manual queries; empty and unseen queries are handled; stale snapshot detection works; baseline configuration is saved
- Status: active

## P0 release checklist

- [x] Reproducible GitHub discovery and ingestion
- [x] Safe Agent Skills parser and validation
- [x] PostgreSQL/pgvector schema and migrations
- [x] Frozen dataset snapshot
- [ ] BM25 implementation and tests
- [ ] Labelled queries and qrels
- [ ] Dense retrieval
- [ ] Hybrid RRF retrieval
- [ ] nDCG@10, MRR@10 and Recall@10 evaluation
- [ ] Versioned FastAPI endpoints
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
- Backend tests: 174 passing locally and in CI
- Backend coverage: 88%
- PostgreSQL-backed integration tests: 13 passing
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
- Ruff formatting: passing across 67 files
- Ruff linting: passing
- Strict mypy: passing across 30 source files
- CLI version command: 0.1.0
- API liveness: /healthz returned HTTP 200 with the expected response
- Database service: PostgreSQL 18.6 healthy through Docker Compose
- Vector extension: pgvector 0.8.6
- Migration head: ddfda2ba04bd
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
- Retrieval evaluation: not started
- Private GitHub repository: aaditya1903/skillscope
- GitHub Actions: passing
- Milestone 5 implementation commit: `0aba78808db36a40c79d5b272a929b1fb8ab4de0`
- Milestone 5 implementation CI run: [32766779848](https://github.com/aaditya1903/skillscope/actions/runs/32766779848)

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

## Blockers

No active blockers.

## Next three actions

1. Implement a frozen-corpus loader that selects the 144 valid or warning-status skills and rejects stale manifest/database hashes.
2. Define documented text normalisation and tokenisation, then implement BM25 with hand-calculated unit tests.
3. Add deterministic ranking explanations, a CLI search command, saved baseline parameters and five manual-query checks.
