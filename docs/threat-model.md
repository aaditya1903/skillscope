# Threat model

SkillScope reads untrusted content from public repositories and republishes
metadata about it. The interesting risks are therefore about what that content
can make the system do, and what the system might leak or redistribute.

## Assets

- The GitHub token used for ingestion.
- The PostgreSQL database and its connection credentials.
- The frozen corpus, qrels and evaluation reports, whose value depends entirely
  on nobody being able to quietly change them.
- The reader, who must not be served executable or misleading content.

## Trust boundaries

1. **GitHub responses.** Untrusted. Structure is validated before use.
2. **Skill content.** Untrusted and inert. Parsed and measured, never executed
   or obeyed.
3. **API requests.** Untrusted. Bounded and read-only.
4. **The ingestion CLI.** Trusted, run locally by someone holding a token, and
   never reachable over HTTP.

## Threats and controls

| Threat | Control |
|---|---|
| Prompt injection inside `SKILL.md` | Content is parsed as data and never sent to an instruction-following model. The project uses no generative model at all. A committed prompt-injection fixture asserts the text is stored and returned inert. |
| Malicious or hostile YAML | 256 KiB file cap and separate 16 KiB frontmatter cap applied before parsing; safe loader with no object construction; result must be a mapping; fields validated with Pydantic; unknown keys retained as extensions rather than trusted. |
| Script execution | Supporting files are never downloaded or run. Only path, classified type, size, blob SHA and extension are recorded. |
| Path traversal | Repository-relative paths are validated: no absolute paths, no `.` or `..` components, no backslashes or percent-encoding, 4,096-byte cap. Directory entries outside the skill's own directory are rejected. Referenced paths inside a body are recorded as strings and never resolved. |
| Server-side request forgery | Only `api.github.com` is contacted. URLs are built from validated owner, repository, path and ref values, never from anything found inside indexed content. Redirects must stay on GitHub. Pagination follows GitHub's own `Link` headers. |
| Cross-site scripting | The API returns text, never markup. The interface renders every indexed value as React text, never calls `dangerouslySetInnerHTML`, and never builds markup from a response. Excerpts are control-character filtered. Responses carry `X-Content-Type-Options: nosniff`. A component test asserts markup in a description or excerpt renders as visible text and creates no element. |
| Token leakage | The token is read from the environment, never logged, never returned, never given to the container image, and never sent to the browser. Authorization headers are redacted in client errors, and `.env` is ignored while `.env.example` holds placeholders only. |
| Log leakage | The application's structured access log records only a generated request ID, method, status and duration. `skillscope serve` disables Uvicorn's own access log, which would otherwise record raw query strings. Bodies, URLs and exception text are never logged. |
| Error leakage | One error envelope with a stable code and a fixed safe message. Validation errors name the field and category but never echo the rejected value. Unexpected exceptions return a generic 500 with no stack trace. |
| API abuse | Query length capped at 500 characters, results at 50, retrieval concurrency bounded to five per process with an immediate 429 rather than an unbounded queue, timeouts on every outbound request, and no endpoint that triggers ingestion. |
| CORS abuse | Exactly one configured origin, validated as a bare HTTP(S) origin. Wildcards are rejected by the settings validator. Only `GET` is allowed and credentials are disabled. |
| Corpus tampering | Configurations, snapshot, candidate manifest and every stored skill are bound by SHA-256. The serving cache is keyed on all of them, so drift forces a full reconciling rebuild that rejects a mismatched corpus rather than serving it. |
| Result inflation | Every published number is produced by a committed command. Test-split metrics are locked behind an explicit flag and the canonical test report refuses to be overwritten. |
| Data redistribution | Committed evidence holds identifiers, hashes, statuses and derived signals only. Bodies stay in the local database; responses carry bounded excerpts and source links. Upstream licence status is recorded and displayed. |
| Dependency compromise | Locked dependencies for both workspaces, pinned action major versions with the setup action pinned by commit SHA, minimal direct dependencies, and CI runs with `contents: read` only. |
| Supply chain via CI | CI never uses a real GitHub token or contacts the GitHub API. The container smoke test loads the committed demonstration corpus. `persist-credentials: false` on every checkout. |

## Residual risks

**Availability of upstream content.** Ingestion pins commits, but a deleted or
force-pushed repository can still make one unreachable. The pipeline reports
this as a categorised per-item failure rather than silently shrinking the
corpus.

**Judgement bias.** Relevance labels were produced with rank- and split-blinded
AI-assisted pre-annotation, reviewed and accepted by the project author. One
reviewer means one perspective; there is no inter-annotator agreement figure.

**The demonstration encoder.** The token-free demonstration corpus uses a
deterministic hashing encoder with no learned semantics. It is refused for the
evaluated configuration and produces no evaluation report, but a reader
skimming a demonstration deployment could still mistake its dense results for
the evaluated model's. The interface therefore reports which corpus and model
it is serving.

**A single maintainer.** There is no second reviewer on changes to this
repository.

## Reporting

See [SECURITY.md](../SECURITY.md).
