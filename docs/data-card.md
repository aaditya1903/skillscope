# Data card

## Purpose

The SkillScope dataset exists to support an information-retrieval evaluation.
It records where public Agent Skills live, whether they satisfy the Agent
Skills specification, and what safe structural properties they have, so that
lexical, dense and hybrid retrieval can be compared on the same fixed corpus.

It is not a directory, a ranking of skill quality, or a claim about the Agent
Skills ecosystem as a whole.

## Collection

- Collected: 24 August 2026, with the corpus refetched at its recorded commits
  on 31 August 2026 (see ADR 6).
- Source: the public GitHub REST API, authenticated with a read-only
  fine-grained token.
- Seeds: one checked-in public repository identifier, `anthropics/skills`.
- Queries, in the order they were run:
  1. `description filename:SKILL.md repo:anthropics/skills`
  2. `name filename:SKILL.md repo:anthropics/skills`
  3. `description filename:SKILL.md`
  4. `name filename:SKILL.md`
- Discovery target: 200 candidates, reached across 4 result pages.

Every query, page boundary and candidate identity is recorded in
`data/manifests/candidates.jsonl`.

## Unit of observation

One `SKILL.md` file, identified by GitHub repository ID and repository-relative
path. Repositories are a second entity, identified by GitHub repository ID.

## Inclusion and exclusion

Included: public repositories only; files named `SKILL.md`; files within the
256 KiB cap; files whose YAML frontmatter parses to a mapping.

Excluded from the retrieval corpus, but retained as validation evidence: skills
whose parse or specification validation is fatal. Thirteen stored skills are in
this state, and they are visible in the statistics and searchable only in the
sense that a validation filter reports them as absent.

Not collected at all: private repositories, organisation data, and any file
outside the discovered skill's own directory.

## Counts

| Measure | Value |
|---|---:|
| Candidates discovered | 200 |
| Repositories seen during discovery | 169 |
| Stored skills | 157 |
| Repositories with a stored skill | 135 |
| Retrieval-eligible skills | 144 |
| Valid / warning / invalid | 51 / 93 / 13 |
| Evaluation queries | 24 |
| Relevance judgements | 482 |

## Licence distribution

Counted per repository, from GitHub's reported licence:

| Status | Repositories | Share |
|---|---:|---:|
| permissive | 89 | 52.7% |
| missing | 59 | 34.9% |
| restrictive | 9 | 5.3% |
| unknown | 12 | 7.1% |

A third of the repositories publish no licence, which means no redistribution
right. This is the main reason the dataset stores metadata rather than content.

## Fields retained

Repository: GitHub ID, owner, name, full name, URL, default branch,
description, stars, forks, open issues, fork and archive flags, licence SPDX
identifier, licence name, licence status, push time, fetch time, ETag.

Skill: repository reference, path, URLs, Git blob SHA, content SHA-256, the
standard frontmatter fields, vendor extension fields kept separately, metadata,
validation status and messages, structural signals, a safe snippet, timestamps
and a 384-dimensional embedding with its provenance.

Supporting files: relative path, classified type, size, blob SHA and extension.
Never their contents.

## Raw content handling

SkillScope never commits complete upstream `SKILL.md` bodies or supporting
files. Skill bodies are fetched into the local PostgreSQL database because
indexing needs them, and are never written to a committed file. The candidate
manifest and dataset snapshot carry identifiers, hashes, statuses and safe
failure categories only, and a test asserts they contain no body.

One committed file does retain upstream text. The frozen evaluation pool,
`data/evaluation/pools/bm25-v1.jsonl`, stores a bounded, source-attributed
description excerpt for each pooled candidate so that a reader can check a
relevance judgement without re-running ingestion. Precisely:

| Measure | Value |
|---|---:|
| Pooled records carrying an excerpt | 482 |
| Distinct skills excerpted | 124 |
| Maximum excerpt length | 500 characters |
| Mean excerpt length | 324 characters |
| Total excerpt text, distinct skills | 36,441 characters |

Each excerpt is attributed to its repository, path and content hash. They are
drawn from the skill's own description — the field an author writes to explain
what the skill is for — and are bounded rather than complete. The README
screenshots in `docs/media` likewise show upstream descriptions as they appear
in the interface.

This is a deliberate trade-off: without the excerpts the qrels would be a list
of opaque identifiers and the evaluation would not be auditable. If a future
release needs stricter licensing conservatism, the pool can be regenerated
with excerpts replaced by hashes, and the screenshots recaptured from the
demonstration corpus.

The API returns a short snippet in search results and at most 2,000 characters
of control-character-filtered plain text in skill detail, alongside a link to
the source on GitHub.

## Known biases and limitations

**Discovery is query-shaped.** The corpus contains what these four queries
found. A skill whose frontmatter uses different wording, or whose repository is
not indexed by GitHub code search, is absent. Code search also caps results, so
even a matching file can be missed.

**English and Latin-script bias.** The queries and the evaluation set are in
English. Non-English skills are under-represented in both.

**One seed repository.** Starting from `anthropics/skills` biases the sample
towards skills written in that style, and towards repositories that reference
it.

**Popularity is not sampled for.** No star or activity threshold was applied,
so the corpus mixes mature skills with one-file experiments. That is
deliberate — it is what the ecosystem contains — but it means a search result is
not a recommendation.

**Judged-pool recall.** Recall@10 is measured over the judged pool of BM25
results plus pre-authored seeds. A relevant skill nobody pooled is invisible to
the metric, so reported recall is an upper bound on pool coverage rather than
true recall.

**AI-assisted, author-reviewed labelling.** An assistant produced rank- and
split-blinded pre-annotations, and the author reviewed and accepted every
positive or partial grade and its rationale before import. One reviewer means
one perspective and no inter-annotator agreement figure.

**Point-in-time.** Repositories are renamed, made private, force-pushed and
deleted. Ingestion fetches at recorded commits so the corpus reproduces while
those commits remain reachable; it will not reproduce forever.

**Validation is specification conformance, not quality.** A skill can be
perfectly valid and useless, or carry a warning and be excellent.

## Intended and prohibited uses

Intended: retrieval research on a fixed corpus; studying specification
conformance in public skills; demonstrating a reproducible ingestion and
evaluation pipeline.

Prohibited: presenting the corpus as a complete or representative census;
redistributing upstream skill content obtained through it; treating validation
status or rank as a quality, safety or trust judgement about an author;
executing anything discovered through it.

## Reproducing the snapshot

The committed manifests pin the corpus:

- `data/manifests/candidates.jsonl`
  (`4da341401d807ea9f7436ffb98637f8fb6200afe6b7dbc2e396be2bd2663d8ee`)
- `data/manifests/dataset-snapshot.jsonl`
  (`d5f2c2ced677a468862edb25bbb8edea8b05ce63039916bbaeb02c7fb78c6562`)

With a read-only GitHub token:

```bash
uv run alembic upgrade head
uv run skillscope ingest run --manifest data/manifests/candidates.jsonl
uv run --extra model skillscope index dense
```

Running discovery again instead will legitimately produce a different manifest,
because the ecosystem and the search index have both moved on.

Without a token, the committed demonstration corpus under `data/demo/skills/`
exercises the same pipeline on original content authored for this repository.
