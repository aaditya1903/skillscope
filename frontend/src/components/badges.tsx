/** Small labelled indicators reused by result cards and skill detail. */

import type { LicenseStatus, ValidationStatus } from '../api/types'

export function ValidationBadge({ status }: { status: ValidationStatus }) {
  return (
    <span className={`badge ${status}`}>
      {status === 'valid' ? 'spec valid' : `spec ${status}`}
    </span>
  )
}

export function LicenseBadge({ status }: { status: LicenseStatus }) {
  return <span className="badge">licence {status}</span>
}

export function ScriptsBadge({ hasScripts }: { hasScripts: boolean }) {
  return <span className="badge">{hasScripts ? 'bundles scripts' : 'no scripts'}</span>
}
