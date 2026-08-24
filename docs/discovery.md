# GitHub Discovery Method and Limitations

## Claim boundary

SkillScope discovers public `SKILL.md` candidates through GitHub's supported
REST API. The result is a reproducible sample produced by explicit queries and
checked-in seeds. It is not, and must not be described as, a complete census of
Agent Skills on GitHub.

A discovered candidate is only a file identity. It does not become a validated
skill until the ingestion pipeline fetches and parses it successfully.

## Reproducible inputs

The discovery implementation uses:

- `GET /search/code` with GitHub REST API version `2026-03-10`;
- checked-in public repository identifiers from
  `data/seeds/repositories.txt`;
- seed-specific queries before broader queries;
- public files whose final path component is exactly `SKILL.md`;
- deduplication by GitHub repository ID and file path;
- deterministic sorting by repository full name and path;
- bounded pagination by validated GitHub `Link` URLs.

The current discovery plan records these exact queries:

1. `description filename:SKILL.md repo:anthropics/skills`
2. `name filename:SKILL.md repo:anthropics/skills`
3. `description filename:SKILL.md`
4. `name filename:SKILL.md`

The checked-in manifest is canonical UTF-8 JSONL using schema version 1. Its
header records the timestamp, generating Git commit, seeds, complete query
plan, target and counts. Page records identify the queries and result
boundaries actually consumed. Candidate records contain repository and file
identifiers, paths, source URLs and Git blob SHAs.

The manifest contains no GitHub token, authorization header, file body or
decoded third-party content.

## Verified smoke manifest

The bounded authenticated smoke run on 24 August 2026 produced:

| Field | Verified value |
|---|---|
| Manifest | `data/manifests/candidates.jsonl` |
| Schema version | `1` |
| Generated at | `2026-08-24T08:51:30.226222Z` |
| Generating Git commit | `4e30e196e018ee91b78c58a4b4612e13586daa21` |
| Target | 10 candidates |
| Target reached | Yes |
| Candidate records | 10 |
| Consumed search pages | 1 |
| Total JSONL records | 12 |
| File size | 5,321 bytes |
| SHA-256 | `6165af211a783f4c5c710772f11d0b26f52e2f0f6fbae5c2eda1c28c4802f18f` |
| Code-search budget | 10 remaining before, 9 after |
| Token present | No |
| Third-party bodies present | No |

The run used `target_skills=10`, `per_page=25` and
`max_pages_per_query=1`. The first seed query reached the target, so discovery
stopped after one page. All four planned queries remain recorded in the header,
while the page records show that only the first query was consumed. This smoke
manifest proves the end-to-end contract; it is not the later evaluation corpus.

## Discovery limitations

The following limitations prevent an exhaustive claim:

1. GitHub provides at most 1,000 results for an individual REST search and
   searches through at most 4,000 repositories matching the supplied filters.
2. Code search considers only the default branch and only files smaller than
   384 KB. Skills on other branches or in larger files are absent.
3. A query can time out. GitHub may then return partial matches and set
   `incomplete_results` to `true`.
4. Authenticated code search is limited to 10 requests per minute. SkillScope
   therefore bounds pages, follows rate-limit headers and stops predictably.
5. Default search ordering is GitHub's changing best-match ranking. Search
   index updates, repository changes and ranking changes can alter later runs
   even when SkillScope's own ordering is deterministic.
6. The current marker queries require `description` or `name` to appear in an
   indexed `SKILL.md`. Files using different conventions can be missed.
7. Seed-first execution deliberately favours known repositories. Early stopping
   can prevent broad queries from being consumed, as happened in the smoke run.
8. Results are limited to repositories visible to the credential. Private,
   deleted, renamed or access-restricted repositories may be absent.
9. A search hit is not evidence that a file is standards-compliant, safe or
   useful. Those properties are established later by bounded fetching, parsing
   and validation.

These API behaviours are documented by GitHub in its
[REST search documentation](https://docs.github.com/en/rest/search/search).
SkillScope records exact inputs and boundaries so that a run can be audited,
not so that a finite sample can masquerade as the whole ecosystem.

## Verification commands

Validate the discovery and manifest implementations without network access:

```bash
uv run pytest \
  tests/unit/test_discovery.py \
  tests/unit/test_manifest.py
```

Validate the checked-in manifest and its evidence hash:

```bash
uv run python - <<'PY'
from hashlib import sha256
from pathlib import Path

from skillscope.ingestion.manifest import read_candidate_manifest

manifest_path = Path("data/manifests/candidates.jsonl")
manifest = read_candidate_manifest(manifest_path)
serialized = manifest_path.read_bytes()

print(f"candidates: {manifest.header.candidate_count}")
print(f"pages: {manifest.header.page_count}")
print(f"sha256: {sha256(serialized).hexdigest()}")
PY
```

