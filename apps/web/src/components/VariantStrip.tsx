import type { Control, Variant } from '../bundle'
import { pct, shortStatus, trim } from '../util'

interface Props {
  control: Control
  variants: Variant[]
  /** highlighted variant */
  active?: number
  onPick?: (i: number) => void
  /** dashboard card: smaller, no labels row */
  compact?: boolean
}

/** One cell per recorded variant: status colour + p_success bar. Compact comparison of the whole sweep. */
export function VariantStrip({ control, variants, active, onPick, compact }: Props) {
  if (variants.length < 2) return null
  return (
    <div className={`vstrip ${compact ? 'compact' : ''}`} role="list" aria-label={`${control.label} sweep`}>
      {variants.map((v, i) => {
        const s = shortStatus(v.verdict)
        const p = v.verdict.feasibility.n_samples > 0 ? v.verdict.feasibility.p_success : null
        const inner = (
          <>
            <span className="vs-bar" aria-hidden>
              <i className={s.tone} style={{ height: `${p === null ? 6 : Math.max(6, p * 100)}%` }} />
            </span>
            <span className="vs-v mono">{trim(v.value)}</span>
            {!compact && <span className="vs-p mono small">{p === null ? s.tone === 'bad' ? 'impossible' : 'not found' : pct(p, 0)}</span>}
          </>
        )
        const title = `${control.label} = ${trim(v.value)} ${control.unit}: ${s.label}${p !== null ? `, p_success ${pct(p)}` : ''}`
        return onPick ? (
          <button key={i} role="listitem" className={`vs-cell ${i === active ? 'on' : ''}`} onClick={() => onPick(i)} title={title} aria-pressed={i === active}>
            {inner}
          </button>
        ) : (
          <div key={i} role="listitem" className={`vs-cell ${i === active ? 'on' : ''}`} title={title}>
            {inner}
          </div>
        )
      })}
    </div>
  )
}
