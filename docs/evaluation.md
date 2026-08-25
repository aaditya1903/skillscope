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

## Milestone 8 method-comparison protocol

Development comparison runs BM25, exact dense cosine search, and equal-weight
RRF against the same 16 queries, 482 qrels, and frozen 144-document snapshot:

```bash
uv run --extra model skillscope evaluate compare \
  --split development \
  --output reports/evaluation/method-comparison-development-v1.json
```

The report records every input-configuration hash, the exact model revision,
per-query top-10 safe metadata, source ranks, method metrics, deterministic
failure examples, and nearest-rank p50/p95 latency after one unmeasured warm-up
query per method. Latency includes query encoding and PostgreSQL work for dense
search, and both component retrievals plus fusion for hybrid search.

Model, text construction, cosine distance, candidate depth 50, `rrf_k = 60`,
and equal weights are fixed before inspecting the test split. After reviewing
and committing the development report, the final test command is run once with
an explicit output path and unlock:

```bash
uv run --extra model skillscope evaluate compare \
  --split test \
  --allow-test \
  --output reports/evaluation/method-comparison-test-v1.json
```

The test report writer refuses to overwrite an existing final report. The
single command compares all three methods together, so no method receives a
different held-out sample. Results are reported honestly even if hybrid does
not beat BM25.

## Limitations

The version 1 pool is the union of BM25 top-20 results and pre-authored query
seeds. This is transparent and reproducible, but it is not exhaustive. Recall
therefore means recall over judged pooled candidates, not unknown relevance
across the entire public GitHub ecosystem. Milestone 8 must report this pooling
bias alongside the final comparison rather than pretending the qrels are a
complete census.

<!-- M8_FINAL_COMPARISON_START -->
## Milestone 8 final method comparison

The retrieval configuration was committed before the locked test split was
opened. BM25, exact pgvector cosine retrieval, and equal-weight RRF were then
evaluated together against the same frozen snapshot and qrels. The canonical
test report was created once by the overwrite-refusing writer; this section was
generated from the saved reports rather than editing metric values by hand.

| Split | Method | nDCG@10 | MRR@10 | judged-pool Recall@10 | p50 ms | p95 ms |
|---|---|---:|---:|---:|---:|---:|
| Development | bm25 | 0.8159700661 | 0.9131944444 | 0.8500000000 | 0.649 | 1.048 |
| Development | dense | 0.8778725187 | 0.9375000000 | 0.8937500000 | 16.721 | 71.556 |
| Development | hybrid | 0.8777519964 | 0.9166666667 | 0.9875000000 | 17.841 | 24.408 |
| Test | bm25 | 0.8363377669 | 0.8750000000 | 0.8750000000 | 0.584 | 0.958 |
| Test | dense | 0.8273775132 | 0.9062500000 | 0.8541666667 | 14.203 | 20.448 |
| Test | hybrid | 0.7788241976 | 0.8125000000 | 0.8750000000 | 13.331 | 14.783 |

On the development split, the highest nDCG@10 was produced by `dense`;
on the locked test split it was produced by `bm25`.
BM25 remains the transparent no-model baseline. Dense retrieval adds semantic
matching at model-loading and query-encoding cost. Hybrid RRF combines lexical
and semantic ranks without pretending their raw score scales are comparable.
The measured latency values describe this local CPU/PostgreSQL run, not a hosted
service-level objective.

Deterministic failure examples:

- Development `bm25`: `q008` (first relevant result below rank 3), `q009` (relevant pool items missed), `q005` (relevant pool items missed).
- Development `dense`: `q010` (no relevant result in top 10), `q005` (relevant pool items missed), `q003` (relative ordering error).
- Development `hybrid`: `q008` (relative ordering error), `q010` (relative ordering error), `q009` (relative ordering error).
- Test `bm25`: `q020` (no relevant result in top 10), `q022` (relative ordering error), `q023` (relative ordering error).
- Test `dense`: `q022` (first relevant result below rank 3), `q024` (relative ordering error), `q023` (relevant pool items missed).
- Test `hybrid`: `q020` (no relevant result in top 10), `q022` (relative ordering error), `q024` (relative ordering error).

Development report: `reports/evaluation/method-comparison-development-v1.json`
(SHA-256 `bb49125eeb0ec693cd95d42325a3019e375a71c4981c8bb1eca5eeb4a0af211c`, 181,083 bytes).
Test report: `reports/evaluation/method-comparison-test-v1.json`
(SHA-256 `6967f552d2afd4f94b34a5daea036d5d6669f0ae51635616f4a22a7e6e359088`, 92,909 bytes).
Both reports contain safe ranked metadata and scores only; no upstream body or
credential is stored.

The Recall@10 values remain judged-pool recall. The pool was built from BM25
top-20 results plus pre-authored seeds, so unknown relevant documents outside
that pool are not counted. The 144-document GitHub sample and local latency
measurements should not be generalized to a complete marketplace or production
deployment.
<!-- M8_FINAL_COMPARISON_END -->
