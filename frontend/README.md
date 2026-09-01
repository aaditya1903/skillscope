# SkillScope interface

A small React and TypeScript client for the SkillScope API. It is a
demonstration layer over the evaluated retrieval system, not the project's
central contribution.

## Views

- **Search** — query entry, BM25/dense/hybrid mode selection, licence,
  validation and script filters, and ranked result cards with the score
  components the API publishes for that mode.
- **Skill detail** — declared frontmatter, specification findings, structural
  signals, supporting-file metadata, upstream licence and a bounded plain-text
  excerpt. Reachable at `#/skills/{id}`.
- **Observatory** — corpus composition, licence and validation distributions,
  the held-out three-method comparison, and the hashes that identify the
  evidence behind it.

## Safety

Every field arriving from the API is indexed third-party content and is
rendered as text. The application never calls `dangerouslySetInnerHTML`, never
constructs markup from a response, and never executes a skill. Outbound
repository links carry `rel="noopener noreferrer"`.

## Commands

Run these from this directory. The API must be running separately.

```bash
npm ci
npm run dev
npm run lint
npm run typecheck
npm test
npm run build
```

`VITE_API_BASE_URL` overrides the API origin, which defaults to
`http://127.0.0.1:8000`. The backend allows exactly one browser origin through
`FRONTEND_ORIGIN`, which defaults to `http://localhost:5173`.
