import type { Variant } from '../bundle'
import { fmt } from '../bundle'
import { trim } from '../util'
import type { Control } from '../bundle'

interface Props {
  variant: Variant
  control: Control
  fixedIdx: number | null
  onApply: () => void
  compare: boolean
  onCompare: (v: boolean) => void
}

export function FixCallout({ variant, control, fixedIdx, onApply, compare, onCompare }: Props) {
  const fix = variant.verdict.suggested_fix
  if (!fix || variant.verdict.status === 'FEASIBLE_FOUND') return null
  return (
    <section className="panel fix" id="fix">
      <header className="panel-h">
        <h2>Suggested fix <span className="kr">수정 제안</span></h2>
        {fix.verified ? (
          <span className="pill ok">VERIFIED BY RE-SIMULATION · p={fix.verified_p_success !== null ? fmt(fix.verified_p_success, 3) : '—'}</span>
        ) : (
          <span className="pill warn">NOT VERIFIED (not re-simulated)</span>
        )}
      </header>
      <ul className="changes mono">
        {fix.changes.map((c) => (
          <li key={c.param}>
            {c.param}: <s>{trim(c.from_value)}</s> → <b>{trim(c.to_value)}</b> {c.unit}
          </li>
        ))}
      </ul>
      <p>{fix.rationale}</p>
      <p className="muted small">Produced by the optimizer / sweep, not by a language model.</p>
      <div className="row">
        <button className="btn primary" onClick={onApply} disabled={fixedIdx === null}>
          ▶ Apply fix: move {control.label} slider and replay
        </button>
        <label className="chk">
          <input type="checkbox" checked={compare} disabled={fixedIdx === null} onChange={(e) => onCompare(e.target.checked)} /> side-by-side: failing vs fixed
        </label>
        {fixedIdx === null && <span className="muted small">The fixed configuration is not among the precomputed variants.</span>}
      </div>
    </section>
  )
}
