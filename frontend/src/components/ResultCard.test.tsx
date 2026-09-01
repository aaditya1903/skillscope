import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ResultCard } from './ResultCard'
import { searchResponse } from '../test/fixtures'
import type { SearchResult } from '../api/types'

const result = searchResponse.results[0]!

function renderResult(overrides: Partial<SearchResult> = {}) {
  render(
    <ul>
      <ResultCard result={{ ...result, ...overrides }} onOpen={() => {}} />
    </ul>,
  )
}

describe('ResultCard', () => {
  it('renders provenance badges and safe outbound links', () => {
    renderResult()

    expect(screen.getByText('spec valid')).toBeInTheDocument()
    expect(screen.getByText('licence permissive')).toBeInTheDocument()
    expect(screen.getByText('bundles scripts')).toBeInTheDocument()

    const source = screen.getByRole('link', { name: 'View SKILL.md on GitHub' })
    expect(source).toHaveAttribute('href', result.source_url)
    expect(source).toHaveAttribute('target', '_blank')
    expect(source).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it('escapes markup embedded in indexed content instead of rendering it', () => {
    const injection = '<img src=x onerror="alert(1)">'
    renderResult({ description: injection, snippet: `${injection} tail` })

    expect(screen.getByText(injection)).toBeInTheDocument()
    expect(document.querySelector('img')).toBeNull()
  })

  it('explains a BM25 ranking with per-term contributions', () => {
    renderResult()

    expect(screen.getByText(/2 matched terms/)).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: 'charts' })).toBeInTheDocument()
  })

  it('explains a hybrid ranking with its source ranks', () => {
    renderResult({
      score_components: {
        method: 'hybrid',
        rrf_score: 0.0328,
        bm25_rank: 1,
        dense_rank: 4,
        bm25_score: 9.78,
        dense_similarity: 0.34,
      },
    })

    expect(screen.getByText(/BM25 rank 1, dense rank 4/)).toBeInTheDocument()
  })
})

describe('ResultCard snippets', () => {
  it('hides a snippet that only repeats the start of the description', () => {
    renderResult({
      description: 'Read and write spreadsheet workbooks, including charts.',
      snippet: 'Read and write spreadsheet workbooks...',
    })

    expect(screen.queryByText(/Read and write spreadsheet workbooks\.\.\./)).toBeNull()
  })

  it('keeps a snippet that adds text the description does not have', () => {
    renderResult({
      description: 'Read and write spreadsheet workbooks.',
      snippet: 'Supports pivot tables and named ranges.',
    })

    expect(screen.getByText('Supports pivot tables and named ranges.')).toBeInTheDocument()
  })
})
