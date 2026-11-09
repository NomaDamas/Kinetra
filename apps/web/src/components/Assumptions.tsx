import { useState } from 'react'
import type { Control, Variant } from '../bundle'
import type { Assumption, Verdict } from '../types'
import { describeDist, isUrl, sourceTone, trim } from '../util'
import { VariantPicker } from './VariantPicker'

interface Props {
  assumptions: Assumption[]
  verdict: Verdict
  control: Control
  variants: Variant[]
  variantIdx: number
  onVariant: (i: number) => void
  approved: Record<string, boolean>
  onApprove: (key: string, v: boolean) => void
  edits: Record<string, number>
  onEdit: (key: string, v: number | null) => void
  engineUp: boolean
  onRerun: () => void
  rerunning: boolean
}

export function Assumptions(p: Props) {
  const review = new Map<string, { reason: string; severity: string }>()
  for (const it of p.verdict.human_review.items) if (it.assumption_key) review.set(it.assumption_key, it)
  const general = p.verdict.human_review.items.filter((i) => !i.assumption_key)
  const ctlKey = p.control.key
  const nUnapproved = p.assumptions.filter((a) => !p.approved[a.key]).length
  const [draft, setDraft] = useState<Record<string, string>>({})
  const edited = Object.keys(p.edits).length > 0

  return (
    <section className="panel" id="assumptions">
      <header className="panel-h">
        <h2>Assumptions · human review gate <span className="kr">가정 검토</span></h2>
        <span className={`pill ${p.verdict.human_review.required ? 'warn' : 'ok'}`}>
          {p.verdict.human_review.required ? 'REVIEW REQUIRED' : 'review optional'}
        </span>
      </header>

      <VariantPicker control={p.control} variants={p.variants} index={p.variantIdx} onChange={p.onVariant} />

      <div className="tablewrap">
        <table className="tbl">
          <thead>
            <tr>
              <th>Assumption</th>
              <th>Value</th>
              <th>Distribution (Monte-Carlo)</th>
              <th>Source</th>
              <th>Confidence</th>
              <th>Review</th>
            </tr>
          </thead>
          <tbody>
            {p.assumptions.map((a) => {
              const rv = review.get(a.key)
              const isCtl = a.key === ctlKey
              const shown = p.edits[a.key] ?? a.value
              return (
                <tr key={a.key} className={`${rv ? `rv-${rv.severity}` : ''} ${isCtl ? 'is-ctl' : ''}`}>
                  <td>
                    <b>{a.label}</b>
                    <div className="mono muted small">{a.key}{isCtl ? ' · control' : ''}</div>
                  </td>
                  <td className="mono nowrap">
                    {isCtl ? (
                      <span title="Edit via the slider above (snaps to precomputed runs)">{trim(p.variants[p.variantIdx]?.value ?? a.value)} {a.unit} ↑</span>
                    ) : a.editable ? (
                      <span className="edit">
                        <input
                          className="num"
                          value={draft[a.key] ?? String(trim(shown))}
                          onChange={(e) => setDraft({ ...draft, [a.key]: e.target.value })}
                          onBlur={() => {
                            const n = Number(draft[a.key])
                            if (draft[a.key] !== undefined && Number.isFinite(n) && n !== a.value) p.onEdit(a.key, n)
                            else if (draft[a.key] !== undefined && n === a.value) p.onEdit(a.key, null)
                          }}
                          onKeyDown={(e) => e.key === 'Enter' && (e.target as HTMLInputElement).blur()}
                          aria-label={a.label}
                        />{' '}
                        {a.unit}
                      </span>
                    ) : (
                      <>{trim(a.value)} {a.unit}</>
                    )}
                    {p.edits[a.key] !== undefined && <span className="pill warn tiny">edited</span>}
                  </td>
                  <td className="mono small">{describeDist(a)}</td>
                  <td className="small srccell">
                    {isUrl(a.source) ? (
                      <a href={a.source} target="_blank" rel="noreferrer">{a.source.replace(/^https?:\/\//, '').slice(0, 42)}↗</a>
                    ) : (
                      <span className={`src ${sourceTone(a.source)}`}>{a.source}</span>
                    )}
                  </td>
                  <td><span className={`conf ${a.confidence}`}>{a.confidence}</span></td>
                  <td>
                    {rv && <div className={`rvnote ${rv.severity}`}>{rv.severity.toUpperCase()}: {rv.reason}</div>}
                    <label className="chk">
                      <input type="checkbox" checked={!!p.approved[a.key]} onChange={(e) => p.onApprove(a.key, e.target.checked)} /> approve
                    </label>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {general.length > 0 && (
        <ul className="rvlist">
          {general.map((g, i) => (
            <li key={i} className={g.severity}>{g.severity.toUpperCase()}: {g.reason}</li>
          ))}
        </ul>
      )}

      <div className="gate">
        <span className="mono small">{p.assumptions.length - nUnapproved}/{p.assumptions.length} approved</span>
        <button className="btn" onClick={() => p.assumptions.forEach((a) => p.onApprove(a.key, true))}>Approve all</button>
        {edited && (
          <div className="edit-warn">
            Edited values only change the recorded verdict if the local engine re-runs them.
            {p.engineUp ? (
              <button className="btn primary" onClick={p.onRerun} disabled={p.rerunning}>{p.rerunning ? 'Running…' : 'Re-run on local engine'}</button>
            ) : (
              <span> The displayed verdict is <b>unchanged</b> (engine API not reachable at localhost:8000).</span>
            )}
          </div>
        )}
      </div>
    </section>
  )
}
