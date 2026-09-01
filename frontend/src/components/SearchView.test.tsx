import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as client from '../api/client'
import { ApiError } from '../api/client'
import { SearchView } from './SearchView'
import { searchResponse } from '../test/fixtures'

describe('SearchView', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('submits the trimmed query and renders the ranked result', async () => {
    const search = vi.spyOn(client, 'searchSkills').mockResolvedValue(searchResponse)
    render(<SearchView onOpenSkill={() => {}} />)

    await userEvent.type(
      screen.getByRole('searchbox'),
      '  create charts from a spreadsheet  ',
    )
    await userEvent.click(screen.getByRole('button', { name: 'Search' }))

    expect(await screen.findByText('xlsx')).toBeInTheDocument()
    expect(search).toHaveBeenCalledWith(
      expect.objectContaining({ query: 'create charts from a spreadsheet', mode: 'bm25' }),
    )
    expect(screen.getByText(/1 result in 12\.4 ms/)).toBeInTheDocument()
  })

  it('submits from the keyboard without reaching for the button', async () => {
    const search = vi.spyOn(client, 'searchSkills').mockResolvedValue(searchResponse)
    render(<SearchView onOpenSkill={() => {}} />)

    await userEvent.type(screen.getByRole('searchbox'), 'spreadsheets{Enter}')

    expect(await screen.findByText('xlsx')).toBeInTheDocument()
    expect(search).toHaveBeenCalledTimes(1)
  })

  it('runs a shared link query on arrival without a second submit', async () => {
    const search = vi.spyOn(client, 'searchSkills').mockResolvedValue(searchResponse)
    render(
      <SearchView onOpenSkill={() => {}} initialQuery="spreadsheets" initialMode="hybrid" />,
    )

    expect(await screen.findByText('xlsx')).toBeInTheDocument()
    expect(search).toHaveBeenCalledTimes(1)
    expect(search).toHaveBeenCalledWith(
      expect.objectContaining({ query: 'spreadsheets', mode: 'hybrid' }),
    )
  })

  it('sends the selected retrieval mode and filters', async () => {
    const search = vi
      .spyOn(client, 'searchSkills')
      .mockResolvedValue({ ...searchResponse, mode: 'hybrid' })
    render(<SearchView onOpenSkill={() => {}} />)

    await userEvent.type(screen.getByRole('searchbox'), 'deploy to kubernetes')
    await userEvent.click(screen.getByRole('button', { name: 'Hybrid RRF' }))
    await userEvent.selectOptions(screen.getByLabelText('Licence'), 'permissive')
    await userEvent.selectOptions(screen.getByLabelText('Scripts'), 'true')
    await userEvent.click(screen.getByRole('button', { name: 'Search' }))

    await waitFor(() => expect(search).toHaveBeenCalled())
    expect(search).toHaveBeenCalledWith({
      query: 'deploy to kubernetes',
      mode: 'hybrid',
      limit: 10,
      filters: { license_status: 'permissive', validation_status: '', has_scripts: 'true' },
    })
  })

  it('reports an empty result set without claiming failure', async () => {
    vi.spyOn(client, 'searchSkills').mockResolvedValue({ ...searchResponse, results: [] })
    render(<SearchView onOpenSkill={() => {}} />)

    await userEvent.type(screen.getByRole('searchbox'), 'nothing matches this')
    await userEvent.click(screen.getByRole('button', { name: 'Search' }))

    expect(await screen.findByText('No matching skills')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('surfaces the safe message from an API error', async () => {
    vi.spyOn(client, 'searchSkills').mockRejectedValue(
      new ApiError('The frozen retrieval service is unavailable.', 503, 'retrieval_unavailable'),
    )
    render(<SearchView onOpenSkill={() => {}} />)

    await userEvent.type(screen.getByRole('searchbox'), 'anything')
    await userEvent.click(screen.getByRole('button', { name: 'Search' }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('The frozen retrieval service is unavailable.')
  })

  it('rejects a whitespace-only query before calling the API', async () => {
    const search = vi.spyOn(client, 'searchSkills')
    render(<SearchView onOpenSkill={() => {}} />)

    await userEvent.type(screen.getByRole('searchbox'), '   ')
    await userEvent.click(screen.getByRole('button', { name: 'Search' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Enter a task to search for.')
    expect(search).not.toHaveBeenCalled()
  })

  it('opens the selected skill by identifier', async () => {
    vi.spyOn(client, 'searchSkills').mockResolvedValue(searchResponse)
    const onOpenSkill = vi.fn<(skillId: string) => void>()
    render(<SearchView onOpenSkill={onOpenSkill} />)

    await userEvent.type(screen.getByRole('searchbox'), 'spreadsheets')
    await userEvent.click(screen.getByRole('button', { name: 'Search' }))
    await userEvent.click(await screen.findByRole('button', { name: 'xlsx' }))

    expect(onOpenSkill).toHaveBeenCalledWith(searchResponse.results[0]!.skill_id)
  })
})
