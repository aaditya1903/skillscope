# Retrieval evaluation and relevance labelling

SkillScope evaluates retrieval against frozen, author-reviewed information
needs. The evaluation files are canonical evidence, not convenient caches: a
changed byte, stale content hash, missing skill identity, modified worksheet
field, or unintentional test run must fail before a metric is reported.

## Version 1 dataset

`data/evaluation/queries-v1.jsonl` contains 24 realistic task queries tied to
the frozen 144-skill corpus:

- 16 development queries may be used for analysis and configuration choices;
- 8 test queries are labelled but their metrics remain locked until the final
  Milestone 8 comparison;
- each query has a category, a plain-language intent, and one or more pooling
  seeds selected before evaluation;
- pooling seeds guarantee that an intended candidate can be judged, but they
  are not automatic relevance labels and the ranker never receives them.

The split is manually balanced across document productivity, creative design,
software quality, agent tooling, developer infrastructure, business operations,
research, and career-document tasks. Query IDs and texts must not be moved
between splits after qrel labelling begins.

## What is relevant?

Judge whether the candidate skill itself would materially help an agent
complete the query. Do not judge repository popularity, writing quality,
licence, author reputation, or whether another result might be better.

Use this three-point scale:

| Grade | Meaning | Decision rule |
|---:|---|---|
| 2 | Highly relevant | The skill directly targets the requested task and could be selected without changing the user's intent. |
| 1 | Partially relevant | The skill provides a useful component or adjacent workflow, but needs another tool, substantial adaptation, or a narrower interpretation. |
| 0 | Not relevant | Shared words or a broad domain overlap do not make the skill useful for the requested task. |

Examples:

- For “merge PDFs and extract selected pages”, a dedicated PDF manipulation
  skill is grade 2, a general document-conversion skill may be grade 1, and a
  slide-design skill mentioning PDF export is grade 0.
- For “review a pull request for code quality issues”, a code-review skill is
  grade 2, a pull-request creation skill is grade 1 at most, and a generic Git
  command reference is grade 0.

When uncertain between adjacent grades, choose the lower grade and explain the
missing capability. Relevant grades 1 and 2 require a short rationale. Grade 0
does not require one, although a rationale is useful for genuinely ambiguous
cases.

## Labelling protocol

Generate the body-free pool and worksheet from the populated isolated database:

```bash
uv run skillscope evaluate pool \
  --worksheet /tmp/skillscope-m7-labels.csv
```

The canonical JSONL pool records BM25 ranks and authored pooling seeds for
reproducibility. It uses portable repository-ID/path document identifiers, not
database UUIDs that can change after a clean ingestion. The CSV worksheet
includes the query text and its authored intent, but deliberately omits the
dev/test split, rank, score, and pool source. Candidates within each query are
ordered by a deterministic SHA-256 key so the labeller cannot simply agree
with BM25's ordering or label the test split differently. Untrusted metadata
that could be interpreted as a spreadsheet formula is prefixed so opening the
worksheet cannot execute it.

For every worksheet row:

1. read the query text and intent represented by the query;
2. inspect only the candidate name, repository path, and safe description;
3. enter `0`, `1`, or `2` in `relevance`;
4. enter a concise rationale for every grade 1 or 2;
5. do not modify identity, query, hash, snippet, or ordering columns.

If the safe metadata is genuinely insufficient, label conservatively and note
that uncertainty in the rationale. Do not fetch or execute supporting files as
part of relevance assessment.

After all rows are labelled:

```bash
uv run skillscope evaluate import-labels /tmp/skillscope-m7-labels.csv
uv run skillscope evaluate validate
```

Import fails unless every row is labelled, relevant rows have rationales, all
immutable worksheet fields are unchanged, every query has a positive
judgement, and every stable document ID plus content hash resolves against the
frozen corpus.

### Version 1 judgement provenance

The version 1 worksheet contains 482 complete judgements: 435 grade 0, 21
grade 1, and 26 grade 2. An AI assistant drafted conservative pre-annotations
from only the rank- and split-blinded worksheet fields. The project author then
reviewed every proposed grade 1 and grade 2 decision and its rationale before
allowing the import. The canonical qrels therefore describe this process as
AI-assisted and author-reviewed rather than implying that every annotation was
entered manually from scratch.

The review did not expose BM25 rank, score, pool source, or development/test
membership. No supporting files were fetched or executed. Every query has at
least one positive judgement, every relevant judgement has a concise rationale,
and all 482 stable document identifiers and content hashes resolve against the
frozen corpus. The canonical qrels SHA-256 is
`e437c04690c5c6de5dd8b777d8290c77b6a5ce49a1889c10ea5dc7718a32eecc`.

## Metrics

SkillScope reports macro-averaged nDCG@10, MRR@10, and Recall@10.

For graded relevance `rel_i` at rank `i`:

```text
DCG@10 = sum from i=1 to 10 of (2^rel_i - 1) / log2(i + 1)
nDCG@10 = DCG@10 / ideal DCG@10
MRR@10 = reciprocal rank of the first result with relevance >= 1
Recall@10 = relevant judged documents retrieved in the top 10
            / all judged documents with relevance >= 1
```

Unjudged retrieved documents count as non-relevant. Queries with no positive
judgement are invalid rather than silently omitted from macro averages. Metric
functions reject duplicate ranked IDs, invalid grades, mismatched query sets,
and invalid cutoffs.

## Development and test discipline

Milestone 7 evaluates only the development split:

```bash
uv run skillscope evaluate bm25 \
  --split development \
  --output reports/evaluation/bm25-development-v1.json
```

The report stores exact input hashes, parameters, per-query metrics, safe top-10
metadata, and the three lowest-performing queries. These development failures
may inform documented hypotheses, but the ordinary Milestone 6 BM25 result
must remain the saved baseline.

The test command fails unless `--allow-test` is supplied. That flag is reserved
for the one final BM25, dense, and hybrid comparison in Milestone 8. Test
metrics must not be inspected while choosing embedding, dense, or RRF settings.

## BM25 development baseline

The frozen BM25 baseline was evaluated on the 16 development queries only:

| Metric | Development result |
|---|---:|
| nDCG@10 | 0.8159700661 |
| MRR@10 | 0.9131944444 |
| judged-pool Recall@10 | 0.8500000000 |

The three deterministic lowest-performing examples expose useful lexical
failure modes:

- `q008`, “write a reusable agent skill”: the first relevant result appeared
  at rank 9 and only 1 of 3 relevant pooled candidates appeared in the top 10;
- `q009`, “apply company brand colours and typography”: BM25 found a relevant
  result at rank 1 but retrieved only 2 of 3 relevant pooled candidates; and
- `q005`, “design a polished responsive landing page”: the first relevant
  result appeared at rank 2 and only 3 of 5 relevant pooled candidates appeared
  in the top 10.

These results are a saved baseline, not a parameter-tuning exercise. The eight
test queries have frozen judgements, but their metrics remain uncomputed until
the single final Milestone 8 comparison.

## Limitations

The version 1 pool is the union of BM25 top-20 results and pre-authored query
seeds. This is transparent and reproducible, but it is not exhaustive. Recall
therefore means recall over judged pooled candidates, not unknown relevance
across the entire public GitHub ecosystem. Milestone 8 must report this pooling
bias alongside the final comparison rather than pretending the qrels are a
complete census.
