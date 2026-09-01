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

  it('round-trips every route', () => {
    const routes = [
      { view: 'search' },
      { view: 'observatory' },
      { view: 'skill', skillId: '11111111-1111-4111-8111-111111111111' },
    ] as const

    for (const route of routes) {
      expect(parseRoute(routeToHash(route))).toEqual(route)
    }
  })
})
