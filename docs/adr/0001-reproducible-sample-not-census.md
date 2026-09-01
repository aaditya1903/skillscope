# 1. Treat the corpus as a reproducible sample, not a census

- Status: accepted
- Date: 2026-08-24

## Context

SkillScope discovers public `SKILL.md` files through the GitHub code-search
API. It is tempting to describe the result as "all public Agent Skills", which
would be a stronger claim and an easy one to make.

That claim cannot be verified. GitHub code search indexes a subset of public
repositories, caps result pages, and changes what it returns over time.
Discovery also depends on the exact queries chosen, and those queries were
written by one person with a particular idea of what a skill file looks like.

## Decision

The corpus is a reproducible sample. Every discovery query, page boundary,
repository identifier, path and content hash is recorded in a committed
candidate manifest, so anyone can see exactly what was asked for and what came
back. Coverage claims are stated as counts of what was found, never as a
proportion of what exists.

## Consequences

The README and data card report absolute counts and name the discovery
queries. No percentage-of-ecosystem figure appears anywhere.

Reproducing the exact corpus requires the frozen manifest rather than a fresh
discovery run, because a later run will legitimately find different files.
Ingestion therefore fetches each file at the commit discovery recorded, so a
frozen manifest keeps resolving to the same bytes.

The alternative — claiming completeness and quietly hoping nobody checks — would
have made every downstream number untrustworthy.
