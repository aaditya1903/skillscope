/**
 * A minimal hash route so a skill detail view can be linked and reloaded.
 *
 * Two screens and one detail view do not justify a router dependency.
 */

export type Route =
  | { view: 'search' }
  | { view: 'observatory' }
  | { view: 'skill'; skillId: string }

const SKILL_PATTERN = /^#\/skills\/([0-9a-fA-F-]{36})$/

export function parseRoute(hash: string): Route {
  const skillId = SKILL_PATTERN.exec(hash)?.[1]
  if (skillId) {
    return { view: 'skill', skillId: skillId.toLowerCase() }
  }
  if (hash === '#/observatory') {
    return { view: 'observatory' }
  }
  return { view: 'search' }
}

export function routeToHash(route: Route): string {
  if (route.view === 'skill') {
    return `#/skills/${route.skillId}`
  }
  return route.view === 'observatory' ? '#/observatory' : '#/'
}
