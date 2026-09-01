import { useCallback, useEffect, useState } from "react";
import "./app.css";
import { apiBaseUrl } from "./api/client";
import { ObservatoryView } from "./components/ObservatoryView";
import { SearchView } from "./components/SearchView";
import { SkillDetailView } from "./components/SkillDetailView";
import { parseRoute, routeToHash } from "./route";
import type { Route } from "./route";

export function App() {
  const [route, setRoute] = useState<Route>(() =>
    parseRoute(window.location.hash),
  );
  // Captured once: a link's query seeds the first search, and later navigation
  // must not re-run it.
  const [initialSearch] = useState(() => {
    const opened = parseRoute(window.location.hash);
    return opened.view === "search"
      ? opened
      : { query: undefined, mode: undefined };
  });

  useEffect(() => {
    const onHashChange = () => setRoute(parseRoute(window.location.hash));
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const navigate = useCallback((next: Route) => {
    window.location.hash = routeToHash(next);
    setRoute(next);
  }, []);

  const openSkill = useCallback(
    (skillId: string) => navigate({ view: "skill", skillId }),
    [navigate],
  );

  return (
    <div className="app">
      <header className="masthead">
        <h1>SkillScope</h1>
        <p>
          An observatory for public Agent Skills: a frozen, validated corpus
          searched three ways and measured against author-reviewed relevance judgements.
        </p>
        <nav className="tabs" aria-label="Views">
          <button
            type="button"
            aria-current={route.view !== "observatory" ? "page" : undefined}
            onClick={() => navigate({ view: "search" })}
          >
            Search
          </button>
          <button
            type="button"
            aria-current={route.view === "observatory" ? "page" : undefined}
            onClick={() => navigate({ view: "observatory" })}
          >
            Observatory
          </button>
        </nav>
      </header>

      <main>
        {route.view === "observatory" ? <ObservatoryView /> : null}
        {route.view === "skill" ? (
          <SkillDetailView
            key={route.skillId}
            skillId={route.skillId}
            onBack={() => navigate({ view: "search" })}
          />
        ) : null}
        {/* Kept mounted so returning from a skill preserves the last results. */}
        <div hidden={route.view !== "search"}>
          <SearchView
            onOpenSkill={openSkill}
            initialQuery={initialSearch.query}
            initialMode={initialSearch.mode}
          />
        </div>
      </main>

      <footer className="footnote">
        <p>
          Indexed skills are untrusted third-party content, rendered as inert
          text and never executed. Each skill remains governed by its own
          repository licence.
        </p>
        <p className="mono">API: {apiBaseUrl}</p>
      </footer>
    </div>
  );
}
