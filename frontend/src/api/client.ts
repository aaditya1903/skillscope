/** Typed fetch wrapper that surfaces the API's structured error envelope. */

import type {
  LatestEvaluation,
  RetrievalMode,
  SearchFilters,
  SearchResponse,
  SkillDetail,
  StatsResponse,
} from './types'

const DEFAULT_BASE_URL = 'http://127.0.0.1:8000'

export const apiBaseUrl = (
  import.meta.env.VITE_API_BASE_URL ?? DEFAULT_BASE_URL
).replace(/\/$/, '')

/** A failed request carrying the safe message the API chose to publish. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(message: string, status: number, code: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

interface ErrorEnvelope {
  error?: { code?: unknown; message?: unknown }
}

async function request<T>(path: string, parameters?: URLSearchParams): Promise<T> {
  const query = parameters?.toString()
  const url = `${apiBaseUrl}${path}${query ? `?${query}` : ''}`

  let response: Response
  try {
    response = await fetch(url, { headers: { Accept: 'application/json' } })
  } catch {
    // A network or CORS failure gives no envelope to read, so say only that.
    throw new ApiError(
      'The API could not be reached. Confirm that it is running.',
      0,
      'network_unavailable',
    )
  }

  if (!response.ok) {
    throw new ApiError(
      await safeErrorMessage(response),
      response.status,
      await safeErrorCode(response.clone()),
    )
  }
  return (await response.json()) as T
}

async function readEnvelope(response: Response): Promise<ErrorEnvelope | null> {
  try {
    return (await response.json()) as ErrorEnvelope
  } catch {
    return null
  }
}

async function safeErrorMessage(response: Response): Promise<string> {
  const envelope = await readEnvelope(response.clone())
  const message = envelope?.error?.message
  if (typeof message === 'string' && message.length > 0) {
    return message
  }
  return `The API returned an unexpected ${response.status} response.`
}

async function safeErrorCode(response: Response): Promise<string> {
  const envelope = await readEnvelope(response)
  const code = envelope?.error?.code
  return typeof code === 'string' && code.length > 0 ? code : 'unexpected_error'
}

export function searchSkills(options: {
  query: string
  mode: RetrievalMode
  limit: number
  filters: SearchFilters
}): Promise<SearchResponse> {
  const parameters = new URLSearchParams({
    q: options.query,
    mode: options.mode,
    limit: String(options.limit),
  })
  if (options.filters.license_status) {
    parameters.set('license_status', options.filters.license_status)
  }
  if (options.filters.validation_status) {
    parameters.set('validation_status', options.filters.validation_status)
  }
  if (options.filters.has_scripts) {
    parameters.set('has_scripts', options.filters.has_scripts)
  }
  return request<SearchResponse>('/api/v1/search', parameters)
}

export function fetchSkill(skillId: string): Promise<SkillDetail> {
  return request<SkillDetail>(`/api/v1/skills/${encodeURIComponent(skillId)}`)
}

export function fetchStats(): Promise<StatsResponse> {
  return request<StatsResponse>('/api/v1/stats')
}

export function fetchLatestEvaluation(): Promise<LatestEvaluation> {
  return request<LatestEvaluation>('/api/v1/evaluations/latest')
}
