import { describe, expect, it } from 'vitest'
import { parseRoute, routeToHash } from './route'

describe('parseRoute', () => {
  it('reads a skill identifier from the hash', () => {
    expect(parseRoute('#/skills/11111111-1111-4111-8111-111111111111')).toEqual({
      view: 'skill',
      skillId: '11111111-1111-4111-8111-111111111111',
    })
  })

  it('falls back to search for an unknown or malformed hash', () => {
    expect(parseRoute('')).toEqual({ view: 'search' })
    expect(parseRoute('#/skills/not-a-uuid')).toEqual({ view: 'search' })
    expect(parseRoute('#/observatory')).toEqual({ view: 'observatory' })
  })

  it('reads a shared query and mode from a search link', () => {
    expect(parseRoute('#/search?q=create+charts&mode=hybrid')).toEqual({
      view: 'search',
      query: 'create charts',
      mode: 'hybrid',
    })
  })

  it('ignores an unsupported mode rather than sending it to the API', () => {
    expect(parseRoute('#/search?q=charts&mode=magic')).toEqual({
      view: 'search',
      query: 'charts',
    })
  })

  it('bounds a shared query to the length the API accepts', () => {
    const route = parseRoute(`#/search?q=${'a'.repeat(600)}`)

    expect(route.view).toBe('search')
    expect(route.view === 'search' && route.query?.length).toBe(500)
  })

  it('round-trips every route', () => {
    const routes = [
      { view: 'search' },
      { view: 'observatory' },
      { view: 'skill', skillId: '11111111-1111-4111-8111-111111111111' },
      { view: 'search', query: 'create charts', mode: 'hybrid' },
    ] as const

    for (const route of routes) {
      expect(parseRoute(routeToHash(route))).toEqual(route)
    }
  })
})
