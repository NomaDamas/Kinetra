// Small shared presentational pieces: badges, stat tiles, and the empty / loading / error states every panel uses.
import type { ReactNode } from 'react'
import type { Verdict } from '../types'
import { shortStatus } from '../util'

export function StatusBadge({ verdict, big }: { verdict: Verdict; big?: boolean }) {
  const s = shortStatus(verdict)
  return (
    <span className={`pill ${s.tone} ${big ? 'big' : ''}`} title={s.strength}>
      {s.label}
    </span>
  )
}

export function Stat({ label, value, sub, tone, hint }: { label: string; value: ReactNode; sub?: ReactNode; tone?: 'ok' | 'bad' | 'weak'; hint?: string }) {
  return (
    <div className="stat" title={hint}>
      <div className="stat-l">{label}</div>
      <div className={`stat-v mono ${tone ?? ''}`}>{value}</div>
      {sub && <div className="stat-s">{sub}</div>}
    </div>
  )
}

export function Loading({ what }: { what: string }) {
  return (
    <div className="state loading" role="status" aria-live="polite">
      <span className="spinner" aria-hidden /> Loading {what}…
    </div>
  )
}

export function ErrorBox({ title, error, children }: { title: string; error?: string; children?: ReactNode }) {
  return (
    <div className="state err" role="alert">
      <b>{title}</b>
      {error && <div className="mono small err-detail">{error}</div>}
      {children}
    </div>
  )
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="state empty">
      <b>{title}</b>
      {children && <div className="muted small">{children}</div>}
    </div>
  )
}

export function Panel({ id, title, kr, right, children, className }: { id?: string; title: ReactNode; kr?: string; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`panel ${className ?? ''}`} id={id}>
      <header className="panel-h">
        <h2>
          {title}
          {kr && <span className="kr">{kr}</span>}
        </h2>
        {right && <div className="row">{right}</div>}
      </header>
      {children}
    </section>
  )
}

export function PageHead({ eyebrow, title, sub, right }: { eyebrow?: string; title: ReactNode; sub?: ReactNode; right?: ReactNode }) {
  return (
    <div className="page-head">
      <div className="page-head-t">
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1 className="page-title">{title}</h1>
        {sub && <p className="page-sub">{sub}</p>}
      </div>
      {right && <div className="page-head-r">{right}</div>}
    </div>
  )
}
