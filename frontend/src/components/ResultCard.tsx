/** One ranked search result. All indexed text renders as escaped text. */

import type { SearchResult } from '../api/types'
import { LicenseBadge, ScriptsBadge, ValidationBadge } from './badges'
import { ScoreExplanation } from './ScoreExplanation'

/**
 * The API builds the snippet from the same leading text as the description for
 * most skills, so show it only when it actually adds something.
 */
function addsContext(snippet: string, description: string): boolean {
  const trimmed = snippet.trim()
  if (trimmed.length === 0) {
    return false
  }
  const normalize = (value: string) => value.replace(/\s+/g, ' ').trim()
  return !normalize(description).startsWith(normalize(trimmed).replace(/\.{3}$/, ''))
}

interface ResultCardProps {
  result: SearchResult
  onOpen: (skillId: string) => void
}

export function ResultCard({ result, onOpen }: ResultCardProps) {
  return (
    <li className="card">
      <div className="card-head">
        <span className="rank" aria-label={`Rank ${result.rank}`}>
          #{result.rank}
        </span>
        <h3>
          <button type="button" onClick={() => onOpen(result.skill_id)}>
            {result.name}
          </button>
        </h3>
      </div>
      <p>{result.description}</p>
      {addsContext(result.snippet, result.description) ? (
        <p className="snippet">{result.snippet}</p>
      ) : null}

      <div className="badges">
        <ValidationBadge status={result.validation_status} />
        <LicenseBadge status={result.repository.license_status} />
        <ScriptsBadge hasScripts={result.has_scripts} />
      </div>

      <ScoreExplanation components={result.score_components} />

      <div className="card-foot">
        <a href={result.repository.url} target="_blank" rel="noopener noreferrer">
          {result.repository.full_name}
        </a>
        <span className="path">{result.path}</span>
        <a href={result.source_url} target="_blank" rel="noopener noreferrer">
          View SKILL.md on GitHub
        </a>
      </div>
    </li>
  )
}
