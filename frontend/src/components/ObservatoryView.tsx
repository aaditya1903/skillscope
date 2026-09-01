/** Observatory: corpus composition and the held-out retrieval comparison. */

import { useEffect, useState } from 'react'
import { ApiError, fetchLatestEvaluation, fetchStats } from '../api/client'
import type { LatestEvaluation, RetrievalMode, StatsResponse } from '../api/types'
import { Notice } from './Notice'

const METHOD_LABELS: Record<RetrievalMode, string> = {
  bm25: 'BM25',
  dense: 'Dense',
  hybrid: 'Hybrid RRF',
}

function percentage(part: number, whole: number): string {
  return whole === 0 ? '0%' : `${((part / whole) * 100).toFixed(1)}%`
}

export function ObservatoryView() {
  const [stats, setStats] = useState<StatsResponse | null>(null)
  const [evaluation, setEvaluation] = useState<LatestEvaluation | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    Promise.all([fetchStats(), fetchLatestEvaluation()])
      .then(([statsResponse, evaluationResponse]) => {
        if (!active) return
        setStats(statsResponse)
        setEvaluation(evaluationResponse)
      })
      .catch((caught: unknown) => {
        if (!active) return
        setError(
          caught instanceof ApiError
            ? caught.message
            : 'Observatory evidence could not be loaded.',
        )
      })
    return () => {
      active = false
    }
  }, [])

  if (error) {
    return <Notice title="Observatory unavailable" detail={error} tone="error" />
  }
  if (!stats || !evaluation) {
    return <Notice title="Loading" detail="Fetching corpus and evaluation evidence." />
  }

  return (
    <section aria-labelledby="observatory-heading">
      <h2 id="observatory-heading">Corpus</h2>
      <div className="stat-grid">
        <div className="stat">
          <span className="value">{stats.skill_count}</span>
          <span className="label">stored skills</span>
        </div>
        <div className="stat">
          <span className="value">{stats.retrieval_eligible_skill_count}</span>
          <span className="label">retrieval documents</span>
        </div>
        <div className="stat">
          <span className="value">{stats.repository_count}</span>
          <span className="label">repositories</span>
        </div>
      </div>

      <div className="panel">
        <h2>Specification validation</h2>
        <div className="table-scroll">
          <table className="data">
            <caption>
              Invalid skills are stored as validation evidence and excluded from
              retrieval.
            </caption>
            <thead>
              <tr>
                <th scope="col">Status</th>
                <th scope="col" className="number">
                  Skills
                </th>
                <th scope="col" className="number">
                  Share
                </th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(stats.validation_statuses).map(([status, count]) => (
                <tr key={status}>
                  <td>{status}</td>
                  <td className="number">{count}</td>
                  <td className="number">{percentage(count, stats.skill_count)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="panel">
        <h2>Upstream licences</h2>
        <div className="table-scroll">
          <table className="data">
            <caption>
              Counted per repository. SkillScope never relicenses upstream content.
            </caption>
            <thead>
              <tr>
                <th scope="col">Licence status</th>
                <th scope="col" className="number">
                  Repositories
                </th>
                <th scope="col" className="number">
                  Share
                </th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(stats.license_statuses).map(([status, count]) => (
                <tr key={status}>
                  <td>{status}</td>
                  <td className="number">{count}</td>
                  <td className="number">{percentage(count, stats.repository_count)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="panel">
        <h2>Bundled directories</h2>
        <div className="stat-grid">
          <div className="stat">
            <span className="value">{stats.features.scripts}</span>
            <span className="label">with scripts/</span>
          </div>
          <div className="stat">
            <span className="value">{stats.features.references}</span>
            <span className="label">with references/</span>
          </div>
          <div className="stat">
            <span className="value">{stats.features.assets}</span>
            <span className="label">with assets/</span>
          </div>
        </div>
        {stats.common_declared_tools.length > 0 ? (
          <>
            <h3>Most declared tools</h3>
            <p>
              {stats.common_declared_tools
                .slice(0, 10)
                .map((item) => `${item.tool} (${item.count})`)
                .join(', ')}
            </p>
          </>
        ) : null}
      </div>

      <div className="panel">
        <h2>Held-out retrieval comparison</h2>
        <div className="table-scroll">
          <table className="data">
            <caption>
              {evaluation.methods[0]?.query_count ?? 0} locked test queries, evaluated once
              after the configuration was frozen. Latency measures retrieval only.
            </caption>
            <thead>
              <tr>
                <th scope="col">Method</th>
                <th scope="col" className="number">
                  nDCG@10
                </th>
                <th scope="col" className="number">
                  MRR@10
                </th>
                <th scope="col" className="number">
                  Recall@10
                </th>
                <th scope="col" className="number">
                  p50 ms
                </th>
                <th scope="col" className="number">
                  p95 ms
                </th>
              </tr>
            </thead>
            <tbody>
              {evaluation.methods.map((method) => (
                <tr key={method.method}>
                  <td>{METHOD_LABELS[method.method]}</td>
                  <td className="number">{method.ndcg_at_10.toFixed(4)}</td>
                  <td className="number">{method.mrr_at_10.toFixed(4)}</td>
                  <td className="number">{method.recall_at_10.toFixed(4)}</td>
                  <td className="number">{method.latency.p50_ms.toFixed(3)}</td>
                  <td className="number">{method.latency.p95_ms.toFixed(3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <h3>Reading these metrics</h3>
        <dl className="definitions">
          <dt>nDCG@10</dt>
          <dd>
            Rewards putting the most relevant skills highest, using graded labels where
            2 is directly relevant and 1 is relevant with adaptation. 1.0 is a perfect
            ordering.
          </dd>
          <dt>MRR@10</dt>
          <dd>
            The reciprocal of the rank of the first relevant result, averaged over
            queries. It measures how quickly a searcher finds anything useful.
          </dd>
          <dt>Recall@10</dt>
          <dd>
            The share of judged relevant skills that appear in the top ten. It is
            recall over the judged pool, not over unjudged skills outside it.
          </dd>
        </dl>
      </div>

      <div className="panel">
        <h2>Provenance</h2>
        <dl className="definitions">
          <dt>Dataset snapshot</dt>
          <dd className="mono">{stats.dataset_snapshot.sha256}</dd>
          <dt>Snapshot path</dt>
          <dd className="mono">{stats.dataset_snapshot.path}</dd>
          <dt>Evaluation report</dt>
          <dd className="mono">{evaluation.report_sha256}</dd>
          <dt>Source commit</dt>
          <dd className="mono">{evaluation.git_commit}</dd>
          <dt>Embedding model</dt>
          <dd className="mono">
            {evaluation.configuration.model_id}@
            {evaluation.configuration.model_revision.slice(0, 12)} (
            {evaluation.configuration.model_dimension}d)
          </dd>
          <dt>Fusion</dt>
          <dd>
            Reciprocal-rank fusion over the top{' '}
            {evaluation.configuration.rrf_candidate_depth} results from each ranker, with
            k = {evaluation.configuration.rrf_k}.
          </dd>
          <dt>Last ingestion</dt>
          <dd>{stats.latest_ingestion_at ?? 'Not recorded'}</dd>
        </dl>
      </div>
    </section>
  )
}
