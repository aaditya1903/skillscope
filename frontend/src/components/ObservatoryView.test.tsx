import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import * as client from '../api/client'
import { ApiError } from '../api/client'
import { ObservatoryView } from './ObservatoryView'
import { latestEvaluation, statsResponse } from '../test/fixtures'

describe('ObservatoryView', () => {
  it('shows a loading state before the evidence arrives', () => {
    vi.spyOn(client, 'fetchStats').mockReturnValue(new Promise(() => {}))
    vi.spyOn(client, 'fetchLatestEvaluation').mockReturnValue(new Promise(() => {}))

    render(<ObservatoryView />)

    expect(screen.getByRole('status')).toHaveTextContent('Loading')
  })

  it('renders corpus composition and the held-out comparison', async () => {
    vi.spyOn(client, 'fetchStats').mockResolvedValue(statsResponse)
    vi.spyOn(client, 'fetchLatestEvaluation').mockResolvedValue(latestEvaluation)

    render(<ObservatoryView />)

    expect(await screen.findByText('144')).toBeInTheDocument()
    expect(screen.getByText('retrieval documents')).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: '0.8363' })).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: 'Hybrid RRF' })).toBeInTheDocument()
    expect(screen.getByText(/8 locked test queries/)).toBeInTheDocument()
  })

  it('reports a failed load without inventing numbers', async () => {
    vi.spyOn(client, 'fetchStats').mockRejectedValue(
      new ApiError('Corpus statistics are temporarily unavailable.', 503, 'statistics_unavailable'),
    )
    vi.spyOn(client, 'fetchLatestEvaluation').mockResolvedValue(latestEvaluation)

    render(<ObservatoryView />)

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Corpus statistics are temporarily unavailable.',
    )
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })
})
