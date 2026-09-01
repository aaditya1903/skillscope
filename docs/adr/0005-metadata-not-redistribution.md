# 5. Publish metadata and derived signals, not upstream content

- Status: accepted
- Date: 2026-08-24

## Context

SkillScope indexes third-party `SKILL.md` files. Committing them would make the
dataset trivially reproducible and the repository self-contained.

Those files belong to their authors. Many of the discovered repositories carry
no licence at all, which means no redistribution right, and several carry
restrictive ones.

## Decision

Committed evidence contains identifiers, paths, hashes, statuses and derived
structural signals only. Skill bodies are fetched into the local database for
indexing and are never written to a committed file. The API returns short safe
snippets and a bounded plain-text excerpt, and links to the source on GitHub.

## Consequences

The candidate manifest and dataset snapshot are body-free and are checked for
that property. Licence status is recorded per repository and surfaced in both
the API and the interface, so a reader can see what they may reuse.

Reproducing the corpus locally requires a GitHub token and an ingestion run
rather than a `git clone`. The token-free demonstration corpus exists so that
a clean clone can still exercise the whole system, using original content
written for this repository.

The excerpt is bounded and control-character filtered, which limits both the
redistribution surface and what a hostile skill can push into a response.
