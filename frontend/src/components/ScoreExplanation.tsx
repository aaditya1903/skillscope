/**
 * Renders the score components the API attaches to each result.
 *
 * The three methods report different quantities, so each one is labelled with
 * what it actually measures rather than a single shared "score" column.
 */

import type { ScoreComponents } from '../api/types'

function round(value: number, places = 4): string {
  return value.toFixed(places)
}

export function ScoreExplanation({ components }: { components: ScoreComponents }) {
  if (components.method === 'bm25') {
    if (components.term_contributions.length === 0) {
      return (
        <details className="explain">
          <summary>Why this ranked here</summary>
          <p>No query term matched this document's index terms.</p>
        </details>
      )
    }
    return (
      <details className="explain">
        <summary>
          Why this ranked here: {components.matched_terms.length} matched term
          {components.matched_terms.length === 1 ? '' : 's'}
        </summary>
        <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th scope="col">Term</th>
              <th scope="col" className="number">
                TF
              </th>
              <th scope="col" className="number">
                DF
              </th>
              <th scope="col" className="number">
                IDF
              </th>
              <th scope="col" className="number">
                Contribution
              </th>
            </tr>
          </thead>
          <tbody>
            {components.term_contributions.map((item) => (
              <tr key={item.term}>
                <td>{item.term}</td>
                <td className="number">{item.term_frequency}</td>
                <td className="number">{item.document_frequency}</td>
                <td className="number">{round(item.inverse_document_frequency, 3)}</td>
                <td className="number">{round(item.score, 3)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </details>
    )
  }

  if (components.method === 'dense') {
    return (
      <details className="explain">
        <summary>Why this ranked here: exact cosine similarity</summary>
        <p>
          Cosine similarity {round(components.cosine_similarity)}, cosine distance{' '}
          {round(components.cosine_distance)}.
        </p>
      </details>
    )
  }

  return (
    <details className="explain">
      <summary>Why this ranked here: fused source ranks</summary>
      <p>
        BM25 rank {components.bm25_rank ?? 'not retrieved'}, dense rank{' '}
        {components.dense_rank ?? 'not retrieved'}, fused score{' '}
        {round(components.rrf_score, 5)}.
      </p>
      <p>
        Reciprocal-rank fusion adds reciprocals of those ranks. The BM25 score
        {components.bm25_score === null ? ' is unavailable' : ` (${round(components.bm25_score, 3)})`}{' '}
        and cosine similarity
        {components.dense_similarity === null
          ? ' is unavailable'
          : ` (${round(components.dense_similarity)})`}{' '}
        are shown for debugging only and are never summed.
      </p>
    </details>
  )
}
