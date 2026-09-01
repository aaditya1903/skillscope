# Interface

The React and TypeScript client is a demonstration layer over the evaluated
retrieval system. It was built after the API and evaluation were verified, and
it adds no ranking, scoring or filtering logic of its own.

## Structure

```text
frontend/src/
  api/types.ts        hand-written mirrors of the API response models
  api/client.ts       typed fetch wrapper over the six read-only endpoints
  route.ts            hash routing for the three views
  components/         search, result card, score explanation, detail, observatory
```

Types are handwritten rather than generated. The surface is six endpoints, and
a small explicit client is easier to review than a generator and its toolchain.
The backend contract tests assert the same field set against `/openapi.json`,
so drift is caught on the side that owns the schema.

Two screens and one detail view do not justify a router dependency, so
`route.ts` parses `#/observatory` and `#/skills/{uuid}` directly. A malformed
hash falls back to search rather than rendering an error.

## Views

### Search

Query entry submits on Enter or the button. The retrieval mode control is a
fieldset of toggle buttons for BM25, dense and hybrid; licence, validation,
script and result-count filters map one-to-one onto documented query
parameters.

Each result card shows the rank, name, description, provenance badges, source
links, and an expandable explanation built from the score components for that
mode:

- BM25 lists each matched term with its TF, DF, IDF and contribution.
- Dense shows cosine similarity and distance.
- Hybrid shows the source ranks and the fused score, and states that the
  BM25 score and cosine similarity are shown for debugging and never summed.

The snippet is hidden when it only repeats the start of the description, which
is the common case for skills whose description is their opening text.

Loading, empty and error states are distinct. An empty result set is reported
as an empty result set, not as a failure, and notes that invalid skills are
excluded from retrieval by design.

### Skill detail

Declared frontmatter, parser findings, structural signals, supporting-file
metadata, repository provenance, upstream licence and the bounded plain-text
excerpt. The view states that directory flags describe whether `scripts/`,
`references/` and `assets/` exist while the counts describe recorded files, and
that ingestion inspects only the immediate skill directory.

### Observatory

Corpus counts, validation and licence distributions, bundled-directory counts,
declared-tool frequencies, and the held-out three-method comparison, followed
by short definitions of nDCG@10, MRR@10 and judged-pool Recall@10.

A provenance panel prints the snapshot hash, report hash, source commit, pinned
model revision and fusion parameters, so every number on the page can be traced
to committed evidence.

## Safety

Every value arriving from the API is untrusted third-party content. React
escapes it, and the application never calls `dangerouslySetInnerHTML`, builds
markup from a response, or renders a supporting file. A component test asserts
that markup embedded in a description or excerpt appears as visible text and
produces no element.

Outbound repository links open in a new tab with `rel="noopener noreferrer"`.
The client only ever constructs URLs against its configured API origin; it
never follows a URL taken from indexed content.

## Accessibility

Semantic landmarks, a labelled search region, a fieldset and legend for the
mode control, explicit labels on every select, `aria-pressed` on the mode
toggles and `aria-current` on the view tabs. Loading and empty states are
polite live regions and errors are alerts, so a screen reader hears the
outcome without moving focus.

Lint runs the `jsx-a11y` plugin with warnings denied.

## Verified behaviour

| Check | Evidence |
|---|---|
| Type check, lint, tests, build | `npm run typecheck`, `npm run lint`, `npm test`, `npm run build` |
| Keyboard submission | Component test types `{Enter}` into the search box |
| All three modes and filters | Component test asserts the exact request the client sends |
| Empty results | Rendered as an empty state with no alert |
| API failure | The API's safe message is surfaced; no stack trace or URL |
| Markup in indexed content | Rendered as text; no element is created |
| Mobile layout | No horizontal page overflow at 375 px on any view |
