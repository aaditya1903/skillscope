# Security

## Reporting a vulnerability

Please report suspected vulnerabilities privately through GitHub's security
advisory form on this repository, rather than opening a public issue.

Include what you did, what happened, and what you expected. A proof of concept
helps, but please do not run one against anything you do not own.

This is a personal portfolio project maintained by one person. Expect a first
response within a week. There is no bounty programme.

## What is in scope

- The SkillScope backend, API, ingestion pipeline and interface in this
  repository.
- The container and Compose definitions committed here.

## What is not in scope

- **Indexed skills.** Every `SKILL.md` in the corpus is untrusted third-party
  content from a public repository. SkillScope parses it as inert data: it
  never executes a script, follows an embedded instruction or fetches a linked
  URL. A skill that contains hostile or misleading text is not a vulnerability
  in SkillScope; a way to make SkillScope act on that text is.
- Findings against GitHub, PostgreSQL, pgvector or other upstream projects.
  Please report those to their maintainers.
- Denial of service produced by pointing large amounts of traffic at a local
  development server.

## Handling of secrets

SkillScope needs a read-only fine-grained GitHub token for ingestion only. It
is read from the `GITHUB_TOKEN` environment variable, never logged, never
returned by the API, never built into a container image and never exposed to
the browser. `.env` is git-ignored; `.env.example` holds placeholders.

If you believe a secret has been committed to this repository, please report it
privately rather than opening an issue.

## Security posture

The threats considered and the controls in place are documented in
[docs/threat-model.md](docs/threat-model.md).
