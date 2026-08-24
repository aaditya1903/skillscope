# SkillScope ingestion contract

SkillScope ingests a bounded, reproducible sample of public `SKILL.md` files.
It does not claim to crawl GitHub exhaustively.

## Safety boundary

The ingestion pipeline treats every GitHub response and skill file as
untrusted data.

- GitHub requests are authenticated, read-only, versioned and restricted to
  allowlisted API hosts.
- A skill body is parsed as inert UTF-8 text. It is never executed or followed
  as an instruction.
- Fetched files, API responses and database dumps are excluded from Git.
- Supporting files contribute structural metadata only. Their contents are not
  fetched automatically.
- Candidate and dataset manifests contain identifiers, statuses and hashes,
  never third-party skill bodies or credentials.
- Per-item failures use stable categories and fixed safe messages. Unexpected
  exception text is not copied into manifests.

Repository-root `SKILL.md` files are safe relative paths and remain eligible
for ingestion. GitHub's repository-relative path does not encode the local
directory name that a clone will use, so the Agent Skills name-to-parent rule
cannot be verified for those files. SkillScope records the stable
`root_directory_name_unverified` warning instead. Nested `SKILL.md` files still
receive strict name-to-parent-directory validation.

## Discovery

Run bounded discovery from the checked-in seed list:

```bash
uv run skillscope ingest discover \
  --target-skills 200 \
  --seeds data/seeds/repositories.txt \
  --output data/manifests/candidates.jsonl
```

The candidate manifest records:

- schema version and generation time;
- source Git commit;
- exact seed repositories and search queries;
- consumed page boundaries;
- GitHub repository IDs, repository names, paths and Git blob SHAs;
- matched queries for each candidate.

Candidate identity is `(GitHub repository ID, repository-relative path)`.
Candidates are sorted by `(repository full name, path)` before output.

## Ingestion

Apply migrations, then ingest one candidate manifest:

```bash
DATABASE_URL="$SKILLSCOPE_TEST_DATABASE_URL" uv run alembic upgrade head

DATABASE_URL="$SKILLSCOPE_TEST_DATABASE_URL" \
  uv run skillscope ingest run \
  --manifest data/manifests/candidates.jsonl \
  --snapshot data/manifests/dataset-snapshot.jsonl \
  --fail-on-errors
```

For each candidate, the runner:

1. refreshes public repository metadata once per repository;
2. checks for an existing `(repository_id, path)` skill;
3. records `unchanged` without fetching the file when the Git blob SHA matches;
4. otherwise fetches the bounded `SKILL.md` and its containing-directory
   metadata;
5. verifies that the fetched path and blob SHA still match discovery;
6. parses the file and extracts structural signals without execution;
7. transactionally inserts or updates the repository, skill and supporting-file
   metadata;
8. records a body-free item outcome even if that candidate fails;
9. continues with later candidates after safe per-item failures;
10. finalises reconciled run counters and writes a canonical dataset snapshot.

Short database transactions surround persistence only. Network requests do not
hold database locks open.

## Outcome semantics

| Status | Meaning |
|---|---|
| `ingested` | A new or changed candidate was parsed and stored. |
| `unchanged` | The stored Git blob SHA matched, so the body was not fetched again. |
| `invalid` | Parsing completed but validation found a fatal content issue. Records with unusable required frontmatter are not given invented fields. |
| `skipped` | A policy boundary, such as a repository becoming private, excluded the candidate. |
| `error` | A transport, payload, consistency or persistence failure prevented completion. |

An ingestion run can complete while containing isolated invalid, skipped or
error items. `--fail-on-errors` writes all safe evidence first and then returns
a non-zero exit code when any item has status `error`.

## Idempotency

Repository identity uses GitHub's numeric repository ID. Skill uniqueness uses
the database constraint on `(repository_id, path)`.

An identical second run must satisfy all of the following:

- no duplicate repository or skill rows;
- every previously stored current candidate is `unchanged`;
- no GitHub file or directory request is required for those unchanged skills;
- `last_seen_at` advances;
- a new ingestion run and item records preserve the audit trail.

A changed Git blob SHA updates the existing skill row, replaces supporting-file
metadata, clears stale embeddings and clears `indexed_at`.

## Failure categories

Stored failures use structured JSON with a category and fixed safe message.
Categories currently include:

- `authentication`
- `permission`
- `not_found`
- `rate_limit`
- `transport`
- `payload`
- `payload_too_large`
- `candidate_changed`
- `private_repository`
- `validation`
- `persistence`
- `unexpected`

GitHub correlation IDs may be retained for debugging. Tokens, response bodies
and arbitrary exception messages are excluded.

## Dataset snapshot

`data/manifests/dataset-snapshot.jsonl` is canonical, versioned UTF-8 JSONL.
Its first record contains:

- source Git commit and ingestion-run ID;
- candidate-manifest path and SHA-256;
- candidate and item counts;
- stored skill and repository counts;
- status counts;
- validation-status counts.

Each later record contains only:

- GitHub repository ID and full name;
- repository-relative path;
- Git blob SHA and deterministic content SHA-256;
- ingestion status;
- whether the current candidate is represented in PostgreSQL;
- validation status when stored;
- structured safe failure evidence when unsuccessful.

Snapshot construction fails if candidate, run-item and current database state do
not reconcile. Canonical serialisation makes the snapshot SHA-256 independently
reproducible from the committed file.

The snapshot freezes the retrieval corpus for later BM25, dense and hybrid
comparisons. Re-running ingestion does not silently change an already evaluated
snapshot.

## Verified Milestone 5 snapshot

The frozen Milestone 5 evidence was generated from implementation commit
`0aba78808db36a40c79d5b272a929b1fb8ab4de0`, verified by GitHub Actions run
[32766779848](https://github.com/aaditya1903/skillscope/actions/runs/32766779848).

The candidate manifest contains 200 unique candidate identities across 169
public repositories. It is 95,331 bytes with SHA-256
`4da341401d807ea9f7436ffb98637f8fb6200afe6b7dbc2e396be2bd2663d8ee`.

The final dataset snapshot contains 200 reconciled outcomes. It is 77,770 bytes
with SHA-256
`d5f2c2ced677a468862edb25bbb8edea8b05ce63039916bbaeb02c7fb78c6562`.
The corresponding clean database contains 169 repositories and 157 stored
skills across 135 represented repositories.

The frozen retrieval corpus consists of 144 skills: 51 with `valid` status and
93 with `warning` status. The remaining 13 stored skills are explicitly invalid
and stay in the observatory as validation evidence, but retrieval baselines must
exclude them.

The first run produced 144 `ingested` and 56 `invalid` outcomes, with no skips
or errors. The identical rerun produced 157 `unchanged` and 43 `invalid`
outcomes, again with no skips or errors. Thirteen first-run invalid candidates
had usable frontmatter and were stored with their invalid status, so their
unchanged Git blob SHAs were correctly skipped on the rerun. This explains the
change in outcome counts without hiding validation failures or creating
duplicates.

Both committed manifests are canonical, token-free and free of upstream skill
bodies. Candidate, run-item, stored-skill and repository counts reconcile with
PostgreSQL. The manifests freeze identifiers, hashes, validation state and safe
failure evidence only; PostgreSQL remains the source of truth for parsed skill
content.
