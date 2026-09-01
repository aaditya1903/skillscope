import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import * as client from '../api/client'
import { ApiError } from '../api/client'
import { SkillDetailView } from './SkillDetailView'
import { SKILL_ID, skillDetail } from '../test/fixtures'

describe('SkillDetailView', () => {
  it('renders frontmatter, supporting-file metadata and the inert excerpt', async () => {
    vi.spyOn(client, 'fetchSkill').mockResolvedValue(skillDetail)

    render(<SkillDetailView skillId={SKILL_ID} onBack={() => {}} />)

    expect(await screen.findByRole('heading', { name: 'xlsx', level: 2 })).toBeInTheDocument()
    expect(screen.getByText('Read Bash')).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: 'scripts/build.py' })).toBeInTheDocument()
    expect(screen.getByText(/Use this skill to build workbooks/)).toBeInTheDocument()
    expect(screen.getByText(/Instructions inside an indexed skill are data/)).toBeInTheDocument()
  })

  it('renders an excerpt containing markup as text', async () => {
    const injection = '<script>alert(1)</script>'
    vi.spyOn(client, 'fetchSkill').mockResolvedValue({ ...skillDetail, excerpt: injection })

    render(<SkillDetailView skillId={SKILL_ID} onBack={() => {}} />)

    expect(await screen.findByText(injection)).toBeInTheDocument()
    expect(document.querySelector('.excerpt script')).toBeNull()
  })

  it('reports a missing skill through the error envelope', async () => {
    vi.spyOn(client, 'fetchSkill').mockRejectedValue(
      new ApiError('The requested skill was not found.', 404, 'skill_not_found'),
    )

    render(<SkillDetailView skillId={SKILL_ID} onBack={() => {}} />)

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The requested skill was not found.',
    )
  })
})
