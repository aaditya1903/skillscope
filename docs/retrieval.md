# Retrieval baselines

SkillScope evaluates every retrieval method against the same frozen corpus. The
Milestone 6 baseline is ordinary, unweighted Okapi BM25 implemented directly in
the repository. It is rebuilt in memory because the current corpus is small;
no opaque search service or stale serialized index is involved.

## Frozen corpus contract

`config/retrieval/bm25-v1.json` records the exact dataset-snapshot SHA-256. A
corpus build fails before ranking if any of these checks fail:

1. the canonical dataset snapshot no longer has the configured SHA-256;
2. its referenced candidate manifest no longer has the recorded SHA-256;
3. an eligible snapshot identity is missing from PostgreSQL;
4. a stored content hash or validation status differs from the snapshot.

Only skills with `valid` or `warning` validation status enter retrieval. Invalid
rows remain useful observatory evidence but cannot enter the evaluated corpus.
For the Milestone 5 snapshot, this produces 144 retrieval documents.

## Text construction

Each skill retains five separately testable lexical fields:

- `name_text`
- `description_text`
- `metadata_text`, including declared licence, compatibility, allowed tools and
  sorted string metadata
- `heading_text`
- `body_text`, excluding headings so headings are not counted twice

The baseline concatenates the five fields once with no field weighting.

Normalisation applies Unicode NFKC, strips inert Markdown and HTML syntax,
decodes entities, collapses whitespace, and lowercases. It never renders HTML,
executes code, translates text, removes stop words, stems words, or lemmatises
them.

The versioned tokenizer uses this Python regular expression:

```text
[^\W_]+(?:(?:[./:_-][^\W_]+)|(?:\+\+|\+|#))*
```

It retains common compounds such as `skill.md`, `c++`, `c#`, `ci/cd`,
`scikit-learn`, `node.js` and `foo_bar`. Known limitations are deliberate: it
does not perform language-specific segmentation, treat punctuation as semantic
outside the listed technical separators, expand acronyms, or infer synonyms.

## BM25 definition

The saved baseline uses `k1 = 1.5` and `b = 0.75`:

```text
score(D, Q) = sum over unique query terms t of:
IDF(t) * [f(t,D) * (k1 + 1)] /
          [f(t,D) + k1 * (1 - b + b * |D| / avgdl)]

IDF(t) = ln(1 + (N - df(t) + 0.5) / (df(t) + 0.5))
```

Repeated normalized query terms use binary weight. Unseen terms contribute
nothing. Empty and all-unseen queries return an empty result set. Equal scores
are ordered by case-insensitive repository name, path, and stable document ID.
Each result exposes matched terms, term frequency, document frequency, IDF and
the exact per-term score contribution.

Index construction is `O(T)` time and space for `T` corpus tokens. A query is
`O(sum(df(t)) + R log R)` with the current full deterministic sort over `R`
matching documents. At this corpus size that is simpler and more auditable than
maintaining a heap; a later benchmark can justify changing it.

## CLI search

Start the database containing the frozen ingestion state, then run:

```bash
uv run skillscope search "create and edit spreadsheets" --top-k 5
```

The command emits sorted JSON containing the normalized query, query terms,
corpus hash and size, baseline parameters, ranked safe metadata, and score
explanations. It never returns or commits third-party skill bodies.

The five Milestone 6 human-review queries live in
`data/evaluation/bm25-smoke-queries.txt`. They are exploratory smoke checks, not
relevance judgements or qrels; formal labelling begins in Milestone 7.
