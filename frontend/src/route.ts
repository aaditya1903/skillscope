/**
 * A minimal hash route so a search and a skill detail can be linked and reloaded.
 *
 * Two screens and one detail view do not justify a router dependency.
 */

import { RETRIEVAL_MODES } from "./api/types";
import type { RetrievalMode } from "./api/types";

export type Route =
  | { view: "search"; query?: string; mode?: RetrievalMode }
  | { view: "observatory" }
  | { view: "skill"; skillId: string };

const SKILL_PATTERN = /^#\/skills\/([0-9a-fA-F-]{36})$/;
const MAX_QUERY_LENGTH = 500;

function isRetrievalMode(value: string | null): value is RetrievalMode {
  return (
    value !== null && (RETRIEVAL_MODES as readonly string[]).includes(value)
  );
}

export function parseRoute(hash: string): Route {
  const skillId = SKILL_PATTERN.exec(hash)?.[1];
  if (skillId) {
    return { view: "skill", skillId: skillId.toLowerCase() };
  }
  if (hash === "#/observatory") {
    return { view: "observatory" };
  }

  const [path, rawParameters] = hash.replace(/^#/, "").split("?", 2);
  if (path === "/search" && rawParameters) {
    const parameters = new URLSearchParams(rawParameters);
    const query = parameters.get("q")?.slice(0, MAX_QUERY_LENGTH).trim();
    const mode = parameters.get("mode");
    return {
      view: "search",
      ...(query ? { query } : {}),
      ...(isRetrievalMode(mode) ? { mode } : {}),
    };
  }
  return { view: "search" };
}

export function routeToHash(route: Route): string {
  if (route.view === "skill") {
    return `#/skills/${route.skillId}`;
  }
  if (route.view === "observatory") {
    return "#/observatory";
  }
  if (route.query) {
    const parameters = new URLSearchParams({ q: route.query });
    if (route.mode) {
      parameters.set("mode", route.mode);
    }
    return `#/search?${parameters.toString()}`;
  }
  return "#/";
}
