/** Deterministic API payloads shared by the component tests. */

import type {
  LatestEvaluation,
  SearchResponse,
  SkillDetail,
  StatsResponse,
} from '../api/types'

export const SKILL_ID = '11111111-1111-4111-8111-111111111111'

export const searchResponse: SearchResponse = {
  request_id: 'a'.repeat(32),
  query: 'create charts from a spreadsheet',
  mode: 'bm25',
  limit: 10,
  took_ms: 12.4,
  score_semantics: 'BM25 lexical score; compare only within this response.',
  dataset_snapshot: { path: 'data/manifests/dataset-snapshot.jsonl', sha256: 'd'.repeat(64) },
  results: [
    {
      rank: 1,
      skill_id: SKILL_ID,
      name: 'xlsx',
      description: 'Read and write spreadsheet workbooks.',
      snippet: 'Creates charts and pivot tables in xlsx workbooks.',
      repository: {
        full_name: 'anthropics/skills',
        url: 'https://github.com/anthropics/skills',
        stars: 1200,
        license_status: 'permissive',
      },
      path: 'document-skills/xlsx/SKILL.md',
      source_url: 'https://github.com/anthropics/skills/blob/main/document-skills/xlsx/SKILL.md',
      validation_status: 'valid',
      has_scripts: true,
      score: 9.78,
      score_components: {
        method: 'bm25',
        matched_terms: ['charts', 'spreadsheet'],
        term_contributions: [
          {
            term: 'charts',
            term_frequency: 3,
            document_frequency: 12,
            inverse_document_frequency: 2.41,
            score: 4.02,
          },
        ],
      },
    },
  ],
}

export const skillDetail: SkillDetail = {
  request_id: 'b'.repeat(32),
  skill_id: SKILL_ID,
  name: 'xlsx',
  description: 'Read and write spreadsheet workbooks.',
  path: 'document-skills/xlsx/SKILL.md',
  source_url: 'https://github.com/anthropics/skills/blob/main/document-skills/xlsx/SKILL.md',
  declared_license: 'MIT',
  compatibility: null,
  allowed_tools: ['Read', 'Bash'],
  metadata: { category: 'documents' },
  validation_status: 'valid',
  validation_messages: [],
  structural_signals: {
    has_scripts: true,
    has_references: false,
    has_assets: false,
    script_count: 0,
    reference_count: 0,
    asset_count: 0,
    heading_count: 12,
    code_block_count: 8,
    external_link_count: 1,
    word_count: 264,
    byte_count: 8072,
  },
  supporting_files: [
    { relative_path: 'scripts/build.py', file_type: 'script', size_bytes: 2048, extension: 'py' },
  ],
  repository: {
    full_name: 'anthropics/skills',
    url: 'https://github.com/anthropics/skills',
    default_branch: 'main',
    stars: 1200,
    forks: 90,
    license_status: 'permissive',
    license_spdx_id: 'MIT',
    license_name: 'MIT License',
  },
  excerpt: '# Xlsx\n\nUse this skill to build workbooks.',
  excerpt_truncated: false,
  first_seen_at: '2026-08-24T19:00:00Z',
  last_seen_at: '2026-08-31T16:45:00Z',
}

export const statsResponse: StatsResponse = {
  request_id: 'c'.repeat(32),
  repository_count: 169,
  skill_count: 157,
  retrieval_eligible_skill_count: 144,
  validation_statuses: { valid: 51, warning: 93, invalid: 13 },
  license_statuses: { permissive: 89, restrictive: 9, missing: 59, unknown: 12 },
  features: { scripts: 48, references: 33, assets: 13 },
  common_declared_tools: [{ tool: 'read', count: 13 }],
  latest_ingestion_at: '2026-08-31T16:45:20Z',
  dataset_snapshot: { path: 'data/manifests/dataset-snapshot.jsonl', sha256: 'd'.repeat(64) },
}

export const latestEvaluation: LatestEvaluation = {
  request_id: 'e'.repeat(32),
  generated_at: '2026-08-25T03:00:00Z',
  git_commit: '5c3407f2649fd23448361623355b68decfc88a9c',
  split: 'test',
  report_sha256: 'f'.repeat(64),
  dataset_snapshot: { path: 'data/manifests/dataset-snapshot.jsonl', sha256: 'd'.repeat(64) },
  configuration: {
    model_id: 'sentence-transformers/all-MiniLM-L6-v2',
    model_revision: '1110a243fdf4706b3f48f1d95db1a4f5529b4d41',
    model_dimension: 384,
    exact_dense_search: true,
    rrf_candidate_depth: 50,
    rrf_k: 60,
    bm25_weight: 1,
    dense_weight: 1,
    cutoff: 10,
  },
  methods: [
    {
      method: 'bm25',
      query_count: 8,
      ndcg_at_10: 0.8363377669222886,
      mrr_at_10: 0.875,
      recall_at_10: 0.875,
      latency: { p50_ms: 0.584417, p95_ms: 0.95825, sample_count: 80 },
    },
    {
      method: 'dense',
      query_count: 8,
      ndcg_at_10: 0.8273775132,
      mrr_at_10: 0.90625,
      recall_at_10: 0.8541666667,
      latency: { p50_ms: 14.203417, p95_ms: 20.448208, sample_count: 80 },
    },
    {
      method: 'hybrid',
      query_count: 8,
      ndcg_at_10: 0.7788241976,
      mrr_at_10: 0.8125,
      recall_at_10: 0.875,
      latency: { p50_ms: 13.330875, p95_ms: 14.783416, sample_count: 80 },
    },
  ],
}
