/**
 * Hand-written mirrors of the SkillScope API response models.
 *
 * The surface is six read-only endpoints, so a small explicit client stays
 * easier to review than a generated one, and every field here is checked
 * against `/openapi.json` by the backend contract tests.
 */

export const RETRIEVAL_MODES = ['bm25', 'dense', 'hybrid'] as const
export type RetrievalMode = (typeof RETRIEVAL_MODES)[number]

export const LICENSE_STATUSES = [
  'permissive',
  'restrictive',
  'missing',
  'unknown',
] as const
export type LicenseStatus = (typeof LICENSE_STATUSES)[number]

export const VALIDATION_STATUSES = ['valid', 'warning', 'invalid'] as const
export type ValidationStatus = (typeof VALIDATION_STATUSES)[number]

export type ValidationSeverity = ValidationStatus

export type SupportingFileType = 'script' | 'reference' | 'asset' | 'other'

export interface DatasetSnapshotReference {
  path: string
  sha256: string
}

export interface RepositorySummary {
  full_name: string
  url: string
  stars: number
  license_status: LicenseStatus
}

export interface BM25TermContribution {
  term: string
  term_frequency: number
  document_frequency: number
  inverse_document_frequency: number
  score: number
}

export interface BM25ScoreComponents {
  method: 'bm25'
  matched_terms: string[]
  term_contributions: BM25TermContribution[]
}

export interface DenseScoreComponents {
  method: 'dense'
  cosine_similarity: number
  cosine_distance: number
}

export interface HybridScoreComponents {
  method: 'hybrid'
  rrf_score: number
  bm25_rank: number | null
  dense_rank: number | null
  bm25_score: number | null
  dense_similarity: number | null
}

export type ScoreComponents =
  | BM25ScoreComponents
  | DenseScoreComponents
  | HybridScoreComponents

export interface SearchResult {
  rank: number
  skill_id: string
  name: string
  description: string
  snippet: string
  repository: RepositorySummary
  path: string
  source_url: string
  validation_status: ValidationStatus
  has_scripts: boolean
  score: number
  score_components: ScoreComponents
}

export interface SearchResponse {
  request_id: string
  query: string
  mode: RetrievalMode
  limit: number
  took_ms: number
  score_semantics: string
  dataset_snapshot: DatasetSnapshotReference
  results: SearchResult[]
}

export interface ValidationMessage {
  code: string
  severity: ValidationSeverity
  message: string
  field: string | null
}

export interface StructuralSignals {
  has_scripts: boolean
  has_references: boolean
  has_assets: boolean
  script_count: number
  reference_count: number
  asset_count: number
  heading_count: number
  code_block_count: number
  external_link_count: number
  word_count: number
  byte_count: number
}

export interface SupportingFile {
  relative_path: string
  file_type: SupportingFileType
  size_bytes: number
  extension: string | null
}

export interface RepositoryDetail {
  full_name: string
  url: string
  default_branch: string
  stars: number
  forks: number
  license_status: LicenseStatus
  license_spdx_id: string | null
  license_name: string | null
}

export interface SkillDetail {
  request_id: string
  skill_id: string
  name: string
  description: string
  path: string
  source_url: string
  declared_license: string | null
  compatibility: string | null
  allowed_tools: string[]
  metadata: Record<string, string>
  validation_status: ValidationStatus
  validation_messages: ValidationMessage[]
  structural_signals: StructuralSignals
  supporting_files: SupportingFile[]
  repository: RepositoryDetail
  excerpt: string
  excerpt_truncated: boolean
  first_seen_at: string
  last_seen_at: string
}

export interface FeatureCounts {
  scripts: number
  references: number
  assets: number
}

export interface ToolCount {
  tool: string
  count: number
}

export interface StatsResponse {
  request_id: string
  repository_count: number
  skill_count: number
  retrieval_eligible_skill_count: number
  validation_statuses: Record<ValidationStatus, number>
  license_statuses: Record<LicenseStatus, number>
  features: FeatureCounts
  common_declared_tools: ToolCount[]
  latest_ingestion_at: string | null
  dataset_snapshot: DatasetSnapshotReference
}

export interface EvaluationLatency {
  p50_ms: number
  p95_ms: number
  sample_count: number
}

export interface EvaluationMetrics {
  method: RetrievalMode
  query_count: number
  ndcg_at_10: number
  mrr_at_10: number
  recall_at_10: number
  latency: EvaluationLatency
}

export interface EvaluationConfiguration {
  model_id: string
  model_revision: string
  model_dimension: number
  exact_dense_search: boolean
  rrf_candidate_depth: number
  rrf_k: number
  bm25_weight: number
  dense_weight: number
  cutoff: number
}

export interface LatestEvaluation {
  request_id: string
  generated_at: string
  git_commit: string
  split: 'test'
  report_sha256: string
  dataset_snapshot: DatasetSnapshotReference
  configuration: EvaluationConfiguration
  methods: EvaluationMetrics[]
}

export interface SearchFilters {
  license_status: LicenseStatus | ''
  validation_status: ValidationStatus | ''
  has_scripts: '' | 'true' | 'false'
}
