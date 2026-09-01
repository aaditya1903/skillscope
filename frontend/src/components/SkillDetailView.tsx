/** Skill detail: frontmatter, spec findings, structural signals and provenance. */

import { useEffect, useState } from 'react'
import { ApiError, fetchSkill } from '../api/client'
import type { SkillDetail } from '../api/types'
import { LicenseBadge, ScriptsBadge, ValidationBadge } from './badges'
import { Notice } from './Notice'

function formatBytes(bytes: number): string {
  return bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KiB`
}

export function SkillDetailView({
  skillId,
  onBack,
}: {
  skillId: string
  onBack: () => void
}) {
  const [skill, setSkill] = useState<SkillDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  // The parent keys this component by skill identifier, so each skill starts
  // from fresh state instead of clearing it inside the effect.
  useEffect(() => {
    let active = true
    fetchSkill(skillId)
      .then((detail) => {
        if (active) setSkill(detail)
      })
      .catch((caught: unknown) => {
        if (!active) return
        setError(
          caught instanceof ApiError ? caught.message : 'This skill could not be loaded.',
        )
      })
    return () => {
      active = false
    }
  }, [skillId])

  return (
    <section aria-labelledby="detail-heading">
      <button type="button" className="back" onClick={onBack}>
        &larr; Back to search
      </button>

      {error ? <Notice title="Skill unavailable" detail={error} tone="error" /> : null}
      {!skill && !error ? <Notice title="Loading" detail="Fetching skill detail." /> : null}

      {skill ? (
        <>
          <h2 id="detail-heading">{skill.name}</h2>
          <p>{skill.description}</p>
          <div className="badges">
            <ValidationBadge status={skill.validation_status} />
            <LicenseBadge status={skill.repository.license_status} />
            <ScriptsBadge hasScripts={skill.structural_signals.has_scripts} />
          </div>

          <div className="panel">
            <h2>Declared frontmatter</h2>
            <dl className="definitions">
              <dt>Name</dt>
              <dd className="mono">{skill.name}</dd>
              <dt>Declared licence</dt>
              <dd>{skill.declared_license ?? 'Not declared'}</dd>
              <dt>Compatibility</dt>
              <dd>{skill.compatibility ?? 'Not declared'}</dd>
              <dt>Allowed tools</dt>
              <dd>
                {skill.allowed_tools.length > 0
                  ? skill.allowed_tools.join(' ')
                  : 'Not declared'}
              </dd>
              {Object.entries(skill.metadata).map(([key, value]) => (
                <div key={key} style={{ display: 'contents' }}>
                  <dt>{key}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
          </div>

          <div className="panel">
            <h2>Specification findings</h2>
            {skill.validation_messages.length === 0 ? (
              <p>The parser reported no warnings against the Agent Skills specification.</p>
            ) : (
              <ul>
                {skill.validation_messages.map((message) => (
                  <li key={`${message.code}-${message.field ?? 'document'}`}>
                    <strong>{message.severity}</strong>{' '}
                    <span className="mono">{message.code}</span>
                    {message.field ? <span className="mono"> ({message.field})</span> : null}
                    {' — '}
                    {message.message}
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="panel">
            <h2>Structural signals</h2>
            <div className="stat-grid">
              <div className="stat">
                <span className="value">{skill.structural_signals.heading_count}</span>
                <span className="label">headings</span>
              </div>
              <div className="stat">
                <span className="value">{skill.structural_signals.code_block_count}</span>
                <span className="label">code blocks</span>
              </div>
              <div className="stat">
                <span className="value">{skill.structural_signals.external_link_count}</span>
                <span className="label">external links</span>
              </div>
              <div className="stat">
                <span className="value">{skill.structural_signals.word_count}</span>
                <span className="label">words</span>
              </div>
              <div className="stat">
                <span className="value">
                  {formatBytes(skill.structural_signals.byte_count)}
                </span>
                <span className="label">SKILL.md size</span>
              </div>
            </div>
            <p className="snippet">
              Directory flags report whether scripts/, references/ and assets/ exist:{' '}
              {skill.structural_signals.has_scripts ? 'scripts' : 'no scripts'},{' '}
              {skill.structural_signals.has_references ? 'references' : 'no references'},{' '}
              {skill.structural_signals.has_assets ? 'assets' : 'no assets'}. Ingestion
              inspects only the immediate skill directory and never fetches or runs a
              supporting file.
            </p>
          </div>

          <div className="panel">
            <h2>Supporting files</h2>
            {skill.supporting_files.length === 0 ? (
              <p>No supporting files were recorded beside this SKILL.md.</p>
            ) : (
              <div className="table-scroll">
                <table className="data">
                  <caption>Metadata only. Contents are never fetched or stored.</caption>
                  <thead>
                    <tr>
                      <th scope="col">Path</th>
                      <th scope="col">Type</th>
                      <th scope="col" className="number">
                        Size
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {skill.supporting_files.map((file) => (
                      <tr key={file.relative_path}>
                        <td className="mono">{file.relative_path}</td>
                        <td>{file.file_type}</td>
                        <td className="number">{formatBytes(file.size_bytes)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="panel">
            <h2>Source and upstream licence</h2>
            <dl className="definitions">
              <dt>Repository</dt>
              <dd>
                <a href={skill.repository.url} target="_blank" rel="noopener noreferrer">
                  {skill.repository.full_name}
                </a>
              </dd>
              <dt>Path</dt>
              <dd className="mono">{skill.path}</dd>
              <dt>Source file</dt>
              <dd>
                <a href={skill.source_url} target="_blank" rel="noopener noreferrer">
                  View SKILL.md on GitHub
                </a>
              </dd>
              <dt>Upstream licence</dt>
              <dd>
                {skill.repository.license_name ?? 'None detected'} (
                {skill.repository.license_status})
              </dd>
              <dt>Stars / forks</dt>
              <dd className="mono">
                {skill.repository.stars} / {skill.repository.forks}
              </dd>
            </dl>
            <p className="snippet">
              SkillScope does not relicense upstream content. The skill remains governed
              by its own repository licence.
            </p>
          </div>

          <div className="panel">
            <h2>Plain-text excerpt</h2>
            <pre className="excerpt">{skill.excerpt}</pre>
            <p className="snippet">
              {skill.excerpt_truncated
                ? 'Truncated to the first 2,000 characters and rendered as inert text.'
                : 'Rendered as inert text.'}{' '}
              Instructions inside an indexed skill are data, never commands.
            </p>
          </div>
        </>
      ) : null}
    </section>
  )
}
