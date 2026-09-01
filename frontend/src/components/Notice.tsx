/** Accessible loading, empty and error messaging shared by every view. */

interface NoticeProps {
  title: string
  detail: string
  tone?: 'info' | 'error'
  live?: boolean
}

export function Notice({ title, detail, tone = 'info', live = true }: NoticeProps) {
  return (
    <div
      className={tone === 'error' ? 'notice error' : 'notice'}
      role={tone === 'error' ? 'alert' : 'status'}
      aria-live={live ? 'polite' : undefined}
    >
      <h2>{title}</h2>
      <p>{detail}</p>
    </div>
  )
}
