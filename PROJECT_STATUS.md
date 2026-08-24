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

- Milestone: 4, GitHub client and discovery
- Objective: implement deterministic GitHub discovery and reproducible candidate manifest output using the verified read-only client
- Exit gate: client tests pass without network access; one authenticated smoke test discovers real public candidates; tokens never appear in logs; the candidate manifest records exact queries and identifiers; discovery limitations are documented
- Status: active

## P0 release checklist

- [ ] Reproducible GitHub discovery and ingestion
- [x] Safe Agent Skills parser and validation
- [x] PostgreSQL/pgvector schema and migrations
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
- Backend tests: 133 passing locally
- Backend coverage: 95%
- Database integration tests: 7 passing
- Parser core tests: 10 passing
- Parser structural-signal tests: 10 passing
- Total parser tests: 20 passing
- GitHub payload and validation tests: 28 passing
- GitHub REST transport tests: 30 passing
- GitHub endpoint tests: 26 passing
- Total GitHub payload and client tests: 84 passing
- Deterministic discovery tests: 10 passing
- Discovery seeds: 1 checked-in public repository identifier
- Discovery queries: 4 deterministic seed-first and broad code-search queries
- Discovery candidate handling: public-only filtering, repository-ID/path deduplication, stable sorting and conflict detection verified
- Ruff formatting: passing across 54 files
- Ruff linting: passing
- Strict mypy: passing across 26 source files
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
- Repositories ingested: not measured
- Skills ingested: not measured
- Retrieval evaluation: not started
- Private GitHub repository: aaditya1903/skillscope
- Latest pushed GitHub Actions workflow: passing
- Latest CI-verified commit: `385d83fc639bebd40165134df2f7a39564e21c43`
- Latest verified CI run: [32688116615](https://github.com/aaditya1903/skillscope/actions/runs/32688116615)

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

## Blockers

No active blockers.

## Next three actions

1. Implement deterministic JSONL candidate-manifest serialization with run metadata and atomic writes.
2. Add manifest schema validation, byte-for-byte determinism and round-trip tests.
3. Run one authenticated local discovery to create and inspect a small manifest, then document discovery limitations and close Milestone 4.
