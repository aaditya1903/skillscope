/** Search screen: query entry, retrieval mode, filters and ranked results. */

import { useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError, searchSkills } from '../api/client'
import {
  LICENSE_STATUSES,
  RETRIEVAL_MODES,
  VALIDATION_STATUSES,
} from '../api/types'
import type {
  LicenseStatus,
  RetrievalMode,
  SearchFilters,
  SearchResponse,
  ValidationStatus,
} from '../api/types'
import { Notice } from './Notice'
import { ResultCard } from './ResultCard'

const MODE_LABELS: Record<RetrievalMode, string> = {
  bm25: 'BM25',
  dense: 'Dense',
  hybrid: 'Hybrid RRF',
}

const EMPTY_FILTERS: SearchFilters = {
  license_status: '',
  validation_status: '',
  has_scripts: '',
}

export function SearchView({ onOpenSkill }: { onOpenSkill: (skillId: string) => void }) {
  const [query, setQuery] = useState('')
  const [mode, setMode] = useState<RetrievalMode>('bm25')
  const [limit, setLimit] = useState(10)
  const [filters, setFilters] = useState<SearchFilters>(EMPTY_FILTERS)
  const [response, setResponse] = useState<SearchResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function runSearch(event: FormEvent) {
    event.preventDefault()
    const trimmed = query.trim()
    if (!trimmed) {
      setError('Enter a task to search for.')
      setResponse(null)
      return
    }

    setLoading(true)
    setError(null)
    try {
      setResponse(await searchSkills({ query: trimmed, mode, limit, filters }))
    } catch (caught) {
      setResponse(null)
      setError(
        caught instanceof ApiError ? caught.message : 'The search could not be completed.',
      )
    } finally {
      setLoading(false)
    }
  }

  return (
    <section aria-labelledby="search-heading">
      <h2 id="search-heading" className="visually-hidden-heading">
        Search the corpus
      </h2>

      <search>
      <form className="search-form" onSubmit={runSearch}>
        <div className="search-row">
          <label htmlFor="query" className="visually-hidden-heading">
            Describe the task you need a skill for
          </label>
          <input
            id="query"
            name="q"
            type="search"
            value={query}
            maxLength={500}
            placeholder="Describe a task, for example: create charts from a spreadsheet"
            onChange={(event) => setQuery(event.target.value)}
          />
          <button type="submit" className="primary" disabled={loading}>
            {loading ? 'Searching' : 'Search'}
          </button>
        </div>

        <div className="controls">
          <fieldset className="field mode-field">
            <legend>Retrieval mode</legend>
            <div className="modes">
              {RETRIEVAL_MODES.map((option) => (
                <button
                  key={option}
                  type="button"
                  aria-pressed={mode === option}
                  onClick={() => setMode(option)}
                >
                  {MODE_LABELS[option]}
                </button>
              ))}
            </div>
          </fieldset>

          <div className="field">
            <label htmlFor="license">Licence</label>
            <select
              id="license"
              value={filters.license_status}
              onChange={(event) =>
                setFilters({
                  ...filters,
                  license_status: event.target.value as LicenseStatus | '',
                })
              }
            >
              <option value="">Any</option>
              {LICENSE_STATUSES.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <label htmlFor="validation">Validation</label>
            <select
              id="validation"
              value={filters.validation_status}
              onChange={(event) =>
                setFilters({
                  ...filters,
                  validation_status: event.target.value as ValidationStatus | '',
                })
              }
            >
              <option value="">Any</option>
              {VALIDATION_STATUSES.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <label htmlFor="scripts">Scripts</label>
            <select
              id="scripts"
              value={filters.has_scripts}
              onChange={(event) =>
                setFilters({
                  ...filters,
                  has_scripts: event.target.value as SearchFilters['has_scripts'],
                })
              }
            >
              <option value="">Any</option>
              <option value="true">Bundles scripts</option>
              <option value="false">No scripts</option>
            </select>
          </div>

          <div className="field">
            <label htmlFor="limit">Results</label>
            <select
              id="limit"
              value={limit}
              onChange={(event) => setLimit(Number(event.target.value))}
            >
              {[10, 20, 50].map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </div>
        </div>
      </form>
      </search>

      {loading ? <Notice title="Searching" detail="Ranking the frozen corpus." /> : null}

      {error ? <Notice title="Search failed" detail={error} tone="error" /> : null}

      {!loading && !error && response ? (
        response.results.length === 0 ? (
          <Notice
            title="No matching skills"
            detail="No skill in the frozen corpus matched this query and filter combination. Invalid skills are excluded from retrieval by design."
          />
        ) : (
          <>
            <p className="meta-line">
              <span>
                {response.results.length} result
                {response.results.length === 1 ? '' : 's'} in {response.took_ms.toFixed(1)} ms
              </span>
              <span>{response.score_semantics}</span>
              <span className="mono">
                snapshot {response.dataset_snapshot.sha256.slice(0, 12)}
              </span>
            </p>
            <ul className="results">
              {response.results.map((result) => (
                <ResultCard key={result.skill_id} result={result} onOpen={onOpenSkill} />
              ))}
            </ul>
          </>
        )
      ) : null}
    </section>
  )
}
