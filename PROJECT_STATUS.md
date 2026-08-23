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

- Milestone: 2, PostgreSQL, pgvector and migrations
- Objective: verify persistence, vector storage and constraints through PostgreSQL-backed integration tests
- Exit gate: healthy database, empty-database migration, vector insert, constraint tests and downgrade/upgrade verification
- Status: active

## P0 release checklist

- [ ] Reproducible GitHub discovery and ingestion
- [ ] Safe Agent Skills parser and validation
- [ ] PostgreSQL/pgvector schema and migrations
- [ ] Frozen dataset snapshot
- [ ] BM25 implementation and tests
- [ ] Labelled queries and qrels
- [ ] Dense retrieval
- [ ] Hybrid RRF retrieval
- [ ] nDCG@10, MRR@10 and Recall@10 evaluation
- [ ] Versioned FastAPI endpoints
- [ ] Minimal React/TypeScript search, detail and statistics interface
- [ ] Unit and integration tests
- [ ] Docker Compose demonstration
- [ ] GitHub Actions green
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
- Backend tests: 12 passing
- Backend coverage: 97%
- Ruff formatting: passing
- Ruff linting: passing
- Strict mypy: passing across 15 source files
- CLI version command: 0.1.0
- API liveness: `/healthz` returned HTTP 200 with the expected response
- Database service: PostgreSQL 18.6 healthy through Docker Compose
- Vector extension: pgvector 0.8.6
- Migration head: `ddfda2ba04bd`
- Migration round trip: `base -> head -> base -> head` passing
- Alembic schema drift: no new upgrade operations detected
- Repositories: not measured
- Skills: not measured
- Retrieval evaluation: not started
- Private GitHub repository: `aaditya1903/skillscope`
- GitHub Actions: passing
- Verified CI commit: `ed592eeba5d01e7bac7e4f05139310d89ca0bd6d`

## Decisions

| Decision | Reason | Date | ADR |
|---|---|---|---|
| Keep the repository private until release | Allows security and evidence review before publication | 2026-08-23 | Not required |
| Use Python 3.12 through `uv` | Strong dependency compatibility without modifying system Python | 2026-08-23 | Not required |
| Pin Node 24 LTS when frontend work begins | Prefer an LTS runtime for local development and CI | 2026-08-23 | Not required |
| Treat PostgreSQL as the source of truth | Required for realistic JSONB, migrations and pgvector behaviour | 2026-08-23 | Planned |
| Build evaluated retrieval before the interface | Evaluation is the project's central technical contribution | 2026-08-23 | Planned |
| Keep upstream skill bodies out of committed datasets | Respect licensing and redistribution boundaries | 2026-08-23 | Planned || Manage pgvector through the initial migration | Guarantees reproducible extension setup and a reversible clean-database migration | 2026-08-23 | Not required |
| Represent non-native enums with explicit named CHECK constraints | Preserves Python enum validation while allowing Alembic 1.19 to compare the constraints accurately | 2026-08-23 | Not required |

## Blockers

No active blockers.

## Next three actions

1. Commit the verified initial Alembic migration.
2. Add isolated PostgreSQL integration-test fixtures that run against the migrated schema.
3. Verify repository and skill insertion, 384-dimensional vector storage and duplicate-constraint rejection.