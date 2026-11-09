// Autoresearch tab. Data: public/demo/autoresearch/*.json (see docs/autoresearch.md). SYNTHETIC data only.
import { useMemo, useState } from 'react'
import { fmt } from '../bundle'
import { trim } from '../util'

/* ---------- loose shapes (engine adds fields; we only read what we show) ---------- */
export interface LedgerEntry {
  id: string
  parent_id: string | null
  hypothesis: string
  change: { op: string; path: string; value?: unknown }[]
  decision: 'keep' | 'discard' | 'crash' | 'gated' | string
  value: number | null
  incumbent_value: number | null
  gate: string
  approved_by: string | null
  metric?: string
  seed?: number
  wall_s?: number
  prev_hash: string
  entry_hash: string
  budget?: Record<string, unknown>
  details?: Record<string, unknown>
}
export interface LedgerFile {
  chain_verified?: boolean
  head_hash?: string
  metric_name?: string
  entries: LedgerEntry[]
  excitation_entries?: LedgerEntry[]
  calibration_entries?: LedgerEntry[]
  excitation_chain_verified?: boolean
  calibration_chain_verified?: boolean
  confirmation?: Record<string, unknown>[]
  family_seeds?: Record<string, unknown>
  counts?: Record<string, number>
}
type Series = Record<string, number[]>
interface TrajCmp {
  trial?: string
  t: number[]
  reference?: Series
  fitted?: Series
  prior?: Series
}
interface Ident {
  status: string
  prior_mean: number
  prior_sd: number
  fit: number
  post_sd: number
  contraction: number
}
export interface CalibFile {
  note?: string
  assumptions: { key: string; label: string; value: number; unit: string; confidence: string; source: string }[]
  identifiability: Record<string, Ident>
  residual_rms_noise_units?: { train: number; heldout_validation: number }
  condition_number?: number
  truth?: Record<string, number>
  campaign?: string
  trajectory_compare?: TrajCmp
  failure_case?: {
    note?: string
    identifiability?: Record<string, Ident>
    residual_rms_noise_units?: { train: number; heldout_validation: number }
    not_identified?: string[]
    weak?: string[]
    lesson?: string
    trajectory_compare?: TrajCmp
    campaign?: string
    assumptions?: CalibFile['assumptions']
  }
}
export interface IntegrationFile {
  rows: {
    family: string
    label: string
    stage?: string
    p: number
    ci: [number, number]
    k?: number
    n?: number
    fuel?: number
    truth_ok?: boolean
    window_s?: number
  }[]
  tight_windows?: Record<string, IntegrationFile['rows']>
  note?: string
}
export interface ExcitationFile {
  baseline_eig: number
  recommended_eig: number
  campaign: string[]
  unit?: string
  rig_time_s?: number
  n_identified?: Record<string, number> | number[]
  per_trial?: { name: string; T_s: number; eig_alone_nats: number; eig_cumulative_nats: number; marginal_gain_nats: number }[]
  per_param?: Record<string, { baseline: number; recommended: number }>
}

export interface ArData {
  ledger: LedgerFile | null
  calibration: CalibFile | null
  integration: IntegrationFile | null
  excitation: ExcitationFile | null
}

const DEC_COLOR: Record<string, string> = { keep: '#4fd1c5', discard: '#7b8794', crash: '#ff6b6b', gated: '#ffb347' }
const STATUS_COLOR: Record<string, string> = { identified: '#4fd1c5', weak: '#ffb347', 'NOT identified': '#ff6b6b', not_identified: '#ff6b6b' }
const statusColor = (s: string) => STATUS_COLOR[s] ?? (s.toLowerCase().includes('not') ? '#ff6b6b' : '#7b8794')

/* ---------- generic SVG line chart ---------- */
interface LineSpec {
  name: string
  color: string
  xs: number[]
  ys: number[]
  dash?: string
  width?: number
}
function LineChart({ lines, xlabel, ylabel, h = 200 }: { lines: LineSpec[]; xlabel: string; ylabel: string; h?: number }) {
  const W = 640
  const pad = { l: 46, r: 12, t: 10, b: 30 }
  const all = lines.flatMap((l) => l.ys.map((y, i) => [l.xs[i], y] as const)).filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y))
  if (all.length === 0) return <div className="muted small">no data</div>
  let x0 = Math.min(...all.map((p) => p[0]))
  let x1 = Math.max(...all.map((p) => p[0]))
  let y0 = Math.min(...all.map((p) => p[1]))
  let y1 = Math.max(...all.map((p) => p[1]))
  if (x1 === x0) x1 = x0 + 1
  if (y1 === y0) {
    y1 += 1
    y0 -= 1
  }
  const yp = (y1 - y0) * 0.06
  y0 -= yp
  y1 += yp
  const X = (x: number) => pad.l + ((x - x0) / (x1 - x0)) * (W - pad.l - pad.r)
  const Y = (y: number) => h - pad.b - ((y - y0) / (y1 - y0)) * (h - pad.t - pad.b)
  const yt = Array.from({ length: 5 }, (_, i) => y0 + ((y1 - y0) * i) / 4)
  const xt = Array.from({ length: 5 }, (_, i) => x0 + ((x1 - x0) * i) / 4)
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${h}`} className="chart" role="img" aria-label={`${ylabel} vs ${xlabel}`}>
        {yt.map((v, i) => (
          <g key={i}>
            <line x1={pad.l} x2={W - pad.r} y1={Y(v)} y2={Y(v)} stroke="#1f2d3b" />
            <text x={pad.l - 6} y={Y(v) + 3} textAnchor="end" className="ax">{fmt(v, 3)}</text>
          </g>
        ))}
        {xt.map((v, i) => (
          <text key={i} x={X(v)} y={h - pad.b + 14} textAnchor="middle" className="ax">{fmt(v, 3)}</text>
        ))}
        <text x={W / 2} y={h - 2} textAnchor="middle" className="ax">{xlabel}</text>
        <text transform={`translate(10 ${h / 2}) rotate(-90)`} textAnchor="middle" className="ax">{ylabel}</text>
        {lines.map((l) => (
          <polyline
            key={l.name}
            fill="none"
            stroke={l.color}
            strokeWidth={l.width ?? 1.6}
            strokeDasharray={l.dash}
            points={l.xs.map((x, i) => `${X(x).toFixed(1)},${Y(l.ys[i]).toFixed(1)}`).join(' ')}
          />
        ))}
      </svg>
      <div className="legend">
        {lines.map((l) => (
          <span key={l.name}><i style={{ background: l.color }} />{l.name}</span>
        ))}
      </div>
    </div>
  )
}

/* ---------- ledger timeline ---------- */
function linkOk(es: LedgerEntry[]) {
  let prev: string | null = null
  for (const e of es) {
    if (prev !== null && e.prev_hash !== prev) return false
    prev = e.entry_hash
  }
  return true
}

function Timeline({ entries, title, lowerBetter, engineVerified }: { entries: LedgerEntry[]; title: string; lowerBetter: boolean; engineVerified?: boolean }) {
  const [sel, setSel] = useState<string | null>(null)
  const W = 720
  const H = 230
  const pad = { l: 52, r: 14, t: 14, b: 34 }
  const geo = useMemo(() => {
    const vals = entries.flatMap((e) => [e.value, e.incumbent_value]).filter((v): v is number => v !== null && Number.isFinite(v))
    let lo = Math.min(...vals)
    let hi = Math.max(...vals)
    if (!Number.isFinite(lo)) {
      lo = 0
      hi = 1
    }
    if (hi === lo) hi = lo + 1
    const p = (hi - lo) * 0.08
    // running incumbent: best KEPT value so far (resets where a new baseline starts: parent_id null)
    const inc: (number | null)[] = []
    let best: number | null = null
    for (const e of entries) {
      if (e.parent_id === null) best = null
      if (e.decision === 'keep' && e.value !== null) best = best === null ? e.value : lowerBetter ? Math.min(best, e.value) : Math.max(best, e.value)
      inc.push(best)
    }
    return { lo: lo - p, hi: hi + p, inc }
  }, [entries, lowerBetter])
  const n = entries.length
  const X = (i: number) => pad.l + (n <= 1 ? 0.5 : i / (n - 1)) * (W - pad.l - pad.r)
  const Y = (v: number) => H - pad.b - ((v - geo.lo) / (geo.hi - geo.lo)) * (H - pad.t - pad.b)
  const cur = entries.find((e) => e.id === sel) ?? null
  const counts = entries.reduce<Record<string, number>>((a, e) => ((a[e.decision] = (a[e.decision] ?? 0) + 1), a), {})
  const stepPts: string[] = []
  geo.inc.forEach((v, i) => {
    if (v === null) return
    stepPts.push(`${X(i).toFixed(1)},${Y(v).toFixed(1)}`)
    if (i + 1 < n && geo.inc[i + 1] !== null) stepPts.push(`${X(i + 1).toFixed(1)},${Y(v).toFixed(1)}`)
  })
  const linked = linkOk(entries)
  return (
    <div className="ledger">
      <div className="row between">
        <h4>{title}</h4>
        <div className="row gap">
          <span className={`pill ${engineVerified !== false && linked ? 'ok' : 'bad'}`} title="Engine: SHA-256 chain verified when the bundle was built. Browser: prev_hash links re-checked here.">
            {engineVerified !== false && linked ? '⛓ hash chain verified' : '⛓ chain NOT verified'}
          </span>
          <span className="mono small muted">
            {n} experiments · {Object.entries(counts).map(([k, v]) => `${v} ${k}`).join(' · ')}
          </span>
        </div>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label="experiment metric timeline">
        {[0, 1, 2, 3, 4].map((i) => {
          const v = geo.lo + ((geo.hi - geo.lo) * i) / 4
          return (
            <g key={i}>
              <line x1={pad.l} x2={W - pad.r} y1={Y(v)} y2={Y(v)} stroke="#1f2d3b" />
              <text x={pad.l - 6} y={Y(v) + 3} textAnchor="end" className="ax">{fmt(v, 3)}</text>
            </g>
          )
        })}
        {stepPts.length > 1 && <polyline points={stepPts.join(' ')} fill="none" stroke="#4fd1c5" strokeOpacity={0.55} strokeWidth={2} strokeDasharray="5 3" />}
        {entries.map((e, i) => {
          const y = e.value !== null ? e.value : e.incumbent_value
          if (y === null) return null
          const c = DEC_COLOR[e.decision] ?? '#7b8794'
          const hollow = e.value === null
          return (
            <g key={e.id} onClick={() => setSel(sel === e.id ? null : e.id)} style={{ cursor: 'pointer' }}>
              <line x1={X(i)} x2={X(i)} y1={Y(y)} y2={H - pad.b} stroke={c} strokeOpacity={0.18} />
              {e.decision === 'gated' ? (
                <rect x={X(i) - 5} y={Y(y) - 5} width={10} height={10} transform={`rotate(45 ${X(i)} ${Y(y)})`} fill="#0b1119" stroke={c} strokeWidth={2} />
              ) : e.decision === 'crash' ? (
                <path d={`M${X(i) - 5},${Y(y) - 5} L${X(i) + 5},${Y(y) + 5} M${X(i) + 5},${Y(y) - 5} L${X(i) - 5},${Y(y) + 5}`} stroke={c} strokeWidth={2.4} />
              ) : (
                <circle cx={X(i)} cy={Y(y)} r={sel === e.id ? 7 : 5} fill={hollow ? 'none' : c} stroke={c} strokeWidth={sel === e.id ? 3 : 1.5} />
              )}
              <text x={X(i)} y={H - pad.b + 13} textAnchor="middle" className="ax tiny">{e.id.replace(/^[a-z]+-/, '')}</text>
            </g>
          )
        })}
      </svg>
      <div className="legend">
        <span><i style={{ background: DEC_COLOR.keep }} />keep</span>
        <span><i style={{ background: DEC_COLOR.discard }} />discard</span>
        <span><i style={{ background: DEC_COLOR.crash }} />crash</span>
        <span><i style={{ background: DEC_COLOR.gated }} />gated (not run)</span>
        <span><i className="dash" />incumbent ({lowerBetter ? 'lower' : 'higher'} is better)</span>
      </div>
      {cur ? (
        <div className="expand">
          <div className="row between">
            <b className="mono">{cur.id}</b>
            <span className="pill" style={{ borderColor: DEC_COLOR[cur.decision], color: DEC_COLOR[cur.decision] }}>{cur.decision.toUpperCase()}</span>
          </div>
          <p>{cur.hypothesis}</p>
          <div className="kv mono small">
            <div><span>metric value</span><b>{cur.value !== null ? fmt(cur.value, 5) : '— (not run)'}</b></div>
            <div><span>incumbent</span><b>{cur.incumbent_value !== null ? fmt(cur.incumbent_value, 5) : '—'}</b></div>
            <div><span>gate</span><b>{cur.gate}</b></div>
            {cur.approved_by && <div><span>approved by</span><b>{cur.approved_by}</b></div>}
            {cur.seed !== undefined && <div><span>seed</span><b>{cur.seed}</b></div>}
            {cur.wall_s !== undefined && <div><span>wall</span><b>{cur.wall_s.toFixed(2)} s</b></div>}
            <div><span>entry_hash</span><b>{cur.entry_hash}</b></div>
            <div><span>prev_hash</span><b>{cur.prev_hash || '(genesis)'}</b></div>
          </div>
          <div className="muted small">patch (RFC-6902)</div>
          <pre className="detail">{cur.change.length ? JSON.stringify(cur.change, null, 1) : '[] (baseline)'}</pre>
        </div>
      ) : (
        <p className="muted small">Click a point to expand its hypothesis and patch. Gated entries were <b>not executed</b>: they show where a proposal tried to change assumptions, hardware or the evaluator and was stopped.</p>
      )}
    </div>
  )
}

/* ---------- calibration ---------- */
function IdentStrip({ id, truth, label }: { id: Ident; truth?: number; label: string }) {
  // in prior-sd units, clipped to ±3
  const W = 220
  const z = (v: number) => Math.max(-3, Math.min(3, (v - id.prior_mean) / id.prior_sd))
  const X = (zz: number) => ((zz + 3) / 6) * W
  const c = statusColor(id.status)
  const lo = z(id.fit - 2 * id.post_sd)
  const hi = z(id.fit + 2 * id.post_sd)
  return (
    <svg viewBox={`0 0 ${W} 22`} className="strip" role="img" aria-label={label}>
      <rect x={X(-1)} y={5} width={X(1) - X(-1)} height={12} fill="#1b2a3a" />
      <rect x={X(-2)} y={5} width={X(2) - X(-2)} height={12} fill="#14202c" opacity={0.7} />
      <line x1={X(0)} x2={X(0)} y1={2} y2={20} stroke="#3a5069" />
      <rect x={X(lo)} y={7} width={Math.max(4, X(hi) - X(lo))} height={10} fill={c} />
      {truth !== undefined && <path d={`M${X(z(truth))},3 l4,8 l-4,8 l-4,-8 z`} fill="#fff" />}
    </svg>
  )
}

function Calibration({ cal, failure }: { cal: CalibFile; failure: boolean }) {
  const src = failure && cal.failure_case ? cal.failure_case : cal
  const ident = (src.identifiability ?? cal.identifiability) as Record<string, Ident>
  const labels = new Map(cal.assumptions.map((a) => [a.key, a]))
  const keys = Object.keys(ident)
  const tc = src.trajectory_compare ?? cal.trajectory_compare
  const [ser, setSer] = useState<string>('')
  const serKeys = tc ? Object.keys(tc.reference ?? tc.fitted ?? tc.prior ?? {}) : []
  const sk = serKeys.includes(ser) ? ser : serKeys.includes('pitch_deg') ? 'pitch_deg' : serKeys[0]
  const lines: LineSpec[] = []
  if (tc && sk) {
    const add = (name: string, s: Series | undefined, color: string, dash?: string, w?: number) => s?.[sk] && lines.push({ name, color, xs: tc.t, ys: s[sk], dash, width: w })
    add('prior model', tc.prior, '#ffb347', '4 3')
    add('reference (synthetic "real")', tc.reference, '#e6edf3', undefined, 2.4)
    add('fitted model', tc.fitted, '#4fd1c5')
  }
  const rms = src.residual_rms_noise_units ?? cal.residual_rms_noise_units
  return (
    <div>
      <div className="tablewrap">
        <table className="tbl compact">
          <thead>
            <tr>
              <th>Parameter</th>
              <th>truth*</th>
              <th>prior (mean, sd)</th>
              <th>fitted</th>
              <th>post sd / prior sd</th>
              <th title="prior-sd units, ±3. white diamond = hidden truth, bar = fitted ±2 post sd">distribution vs prior</th>
              <th>identifiability</th>
            </tr>
          </thead>
          <tbody>
            {keys.map((k) => {
              const i = ident[k]
              const a = labels.get(k)
              const tr = cal.truth?.[k]
              const bad = !i.status.startsWith('identified')
              return (
                <tr key={k} className={bad ? 'rv-block' : ''}>
                  <td><b>{a?.label ?? k}</b><div className="mono muted small">{k}{a?.unit ? ` [${a.unit}]` : ''}</div></td>
                  <td className="mono">{tr !== undefined ? trim(tr) : '—'}</td>
                  <td className="mono">{trim(i.prior_mean)}, {trim(i.prior_sd)}</td>
                  <td className="mono">{trim(i.fit)}</td>
                  <td className="mono">{i.contraction.toFixed(3)}</td>
                  <td><IdentStrip id={i} truth={tr} label={k} /></td>
                  <td><span className="pill" style={{ borderColor: statusColor(i.status), color: statusColor(i.status) }}>{i.status}</span></td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="muted small">
        *truth is a hidden, <b>synthetic</b> perturbed model (not real hardware). Strip: grey bands = prior ±1/±2 sd; coloured bar = fitted ±2 posterior sd; white ◆ = truth.
        {rms && <> Residual RMS (noise units): train {rms.train.toFixed(2)}, held-out {rms.heldout_validation.toFixed(2)}.</>}
        {cal.condition_number !== undefined && !failure && <> Condition number {cal.condition_number.toFixed(0)}.</>}
      </p>
      {failure && cal.failure_case && (
        <div className="callout bad">
          <b>NOT-identified failure case.</b> {cal.failure_case.lesson ?? 'A good train fit is not identification: parameters the data cannot constrain stay at the prior and must not be trusted.'}
          {cal.failure_case.not_identified && cal.failure_case.not_identified.length > 0 && (
            <div className="mono small">not identified: {cal.failure_case.not_identified.join(', ')}</div>
          )}
          {cal.failure_case.campaign && <div className="mono small">campaign: {cal.failure_case.campaign}</div>}
        </div>
      )}
      {tc && lines.length > 0 && (
        <>
          <div className="row between">
            <h4>Reference vs fitted trajectory {tc.trial && <span className="muted small">· trial {tc.trial}</span>}</h4>
            <div className="seg">
              {serKeys.map((k) => (
                <button key={k} className={k === sk ? 'on' : ''} onClick={() => setSer(k)}>{k}</button>
              ))}
            </div>
          </div>
          <LineChart lines={lines} xlabel="t [s]" ylabel={sk} />
        </>
      )}
    </div>
  )
}

/* ---------- integration + excitation ---------- */
function Integration({ data }: { data: IntegrationFile }) {
  const fams = Array.from(new Set(data.rows.map((r) => r.family)))
  const find = (f: string, stage: string) => data.rows.find((r) => r.family === f && (r.stage ?? (r.label.startsWith('before') ? 'before' : 'after')) === stage)
  const cell = (r: IntegrationFile['rows'][number] | undefined) =>
    r ? (
      <>
        <b className="mono">{(r.p * 100).toFixed(1)}%</b>
        <div className="mono muted small">CI [{r.ci[0].toFixed(3)}, {r.ci[1].toFixed(3)}] w={(r.ci[1] - r.ci[0]).toFixed(3)}{r.n ? ` · n=${r.n}` : ''}</div>
      </>
    ) : (
      '—'
    )
  return (
    <div>
      <div className="tablewrap">
        <table className="tbl compact">
          <thead><tr><th>Controller</th><th>Before (prior panel, llm_estimate)</th><th>After (calibrated posterior)</th><th>Δ p_success</th><th>At hidden truth (after)</th></tr></thead>
          <tbody>
            {fams.map((f) => {
              const b = find(f, 'before')
              const a = find(f, 'after')
              return (
                <tr key={f}>
                  <td><b>{f}</b></td>
                  <td>{cell(b)}</td>
                  <td>{cell(a)}</td>
                  <td className="mono">{b && a ? `${a.p - b.p >= 0 ? '+' : ''}${((a.p - b.p) * 100).toFixed(1)} pp` : '—'}</td>
                  <td className={a?.truth_ok ? 'pos' : 'neg'}>{a ? (a.truth_ok ? 'ok' : 'FAIL') : '—'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="muted small">Same controller design procedure and seeds; only the assumptions panel changed. Tight flight-time windows can show no gain: calibration narrows uncertainty, it does not create physics. {data.note ?? ''}</p>
      {data.tight_windows && (
        <details>
          <summary className="small">Tight-window cases ({Object.keys(data.tight_windows).map((k) => `${k} s`).join(', ')})</summary>
          {Object.entries(data.tight_windows).map(([w, rs]) => (
            <div key={w} className="mono small">
              <b>{w} s</b>: {rs.map((r) => `${r.family}/${r.stage ?? r.label.split(' ')[0]} ${(r.p * 100).toFixed(0)}%`).join(' · ')}
            </div>
          ))}
        </details>
      )}
    </div>
  )
}

function Excitation({ ex }: { ex: ExcitationFile }) {
  const unit = ex.unit ?? 'nats'
  return (
    <div>
      <div className="grid2">
        <div className="callout">
          <div className="eyebrow">recommended calibration campaign (for a human to run on a rig)</div>
          <div className="chips">
            {ex.campaign.map((c) => <span className="chip" key={c}>{c}</span>)}
          </div>
          <div className="mono">
            EIG {ex.baseline_eig.toFixed(1)} → <b>{ex.recommended_eig.toFixed(1)}</b> {unit}
            {ex.rig_time_s !== undefined && <> · {ex.rig_time_s.toFixed(1)} s rig time</>}
          </div>
          <div className="muted small">Expected information gain, from simulation. It is a recommendation, not a measurement.</div>
        </div>
        {ex.per_trial && ex.per_trial.length > 0 && (
          <div className="tablewrap">
            <table className="tbl compact">
              <thead><tr><th>Trial</th><th>T [s]</th><th>EIG alone</th><th>cumulative</th><th>marginal</th></tr></thead>
              <tbody>
                {ex.per_trial.map((t) => (
                  <tr key={t.name}>
                    <td className="mono">{t.name}</td>
                    <td className="mono">{t.T_s}</td>
                    <td className="mono">{t.eig_alone_nats.toFixed(1)}</td>
                    <td className="mono">{t.eig_cumulative_nats.toFixed(1)}</td>
                    <td className="mono pos">+{t.marginal_gain_nats.toFixed(1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {ex.per_param && (
        <div className="bars">
          <div className="muted small">expected posterior/prior sd per parameter (lower = better identified)</div>
          {Object.entries(ex.per_param).map(([k, v]) => (
            <div className="bar-row" key={k}>
              <span className="bar-l mono">{k}</span>
              <span className="bar-track dual">
                <i className="neg" style={{ width: `${Math.min(1, v.baseline) * 100}%` }} />
                <i className="pos" style={{ width: `${Math.min(1, v.recommended) * 100}%` }} />
              </span>
              <span className="mono small bar-v">{v.baseline.toFixed(2)} → {v.recommended.toFixed(2)}</span>
            </div>
          ))}
          <div className="legend"><span><i style={{ background: '#ff6b6b' }} />baseline (couple-only)</span><span><i style={{ background: '#4fd1c5' }} />recommended campaign</span></div>
        </div>
      )}
    </div>
  )
}

/* ---------- tab ---------- */
export function Autoresearch({ data }: { data: ArData | null }) {
  const [which, setWhich] = useState<'attitude' | 'excitation' | 'calibration'>('attitude')
  const [failure, setFailure] = useState(false)
  if (!data || (!data.ledger && !data.calibration)) {
    return (
      <section className="panel">
        <h2>Autoresearch</h2>
        <p className="muted">No autoresearch bundle found under /demo/autoresearch/. Run <code>packages/engine/scripts/build_autoresearch_bundle.py</code>.</p>
      </section>
    )
  }
  const L = data.ledger
  const groups: { id: typeof which; label: string; entries: LedgerEntry[]; lower: boolean; verified?: boolean }[] = []
  if (L?.entries?.length) groups.push({ id: 'attitude', label: 'Attitude control', entries: L.entries, lower: false, verified: L.chain_verified })
  if (L?.excitation_entries?.length) groups.push({ id: 'excitation', label: 'Excitation design', entries: L.excitation_entries, lower: false, verified: L.excitation_chain_verified ?? L.chain_verified })
  if (L?.calibration_entries?.length) groups.push({ id: 'calibration', label: 'Calibration fit', entries: L.calibration_entries, lower: true, verified: L.calibration_chain_verified ?? L.chain_verified })
  const g = groups.find((x) => x.id === which) ?? groups[0]
  return (
    <div className="ar">
      <div className="banner warn">
        <b>Synthetic data. Sim-to-real is NOT validated.</b> The "real system" below is a hidden perturbed simulation plus sensor noise, and the fitted model class equals the generating class,
        so coverage is self-consistent, not validated against hardware. 이 탭의 데이터는 합성 데이터이며 실물 검증은 되지 않았습니다.
      </div>

      <section className="panel">
        <header className="panel-h">
          <h2>Experiment ledger <span className="kr">실험 원장</span></h2>
          <span className="muted small">propose → gate → fixed-budget experiment → keep/discard → append (hash-chained)</span>
        </header>
        {groups.length > 1 && (
          <div className="seg">
            {groups.map((x) => (
              <button key={x.id} className={g?.id === x.id ? 'on' : ''} onClick={() => setWhich(x.id)}>{x.label}</button>
            ))}
          </div>
        )}
        {g && <Timeline key={g.id} entries={g.entries} title={`${g.label} · metric ${g.entries[0]?.metric ?? L?.metric_name ?? ''}`} lowerBetter={g.lower} engineVerified={g.verified} />}
        {L?.confirmation && L.confirmation.length > 0 && (
          <details>
            <summary className="small">Held-out confirmation runs ({L.confirmation.length})</summary>
            <pre className="detail">{JSON.stringify(L.confirmation, null, 1)}</pre>
          </details>
        )}
      </section>

      {data.calibration && (
        <section className="panel">
          <header className="panel-h">
            <h2>Calibration <span className="kr">보정</span></h2>
            {data.calibration.failure_case && (
              <div className="seg">
                <button className={!failure ? 'on' : ''} onClick={() => setFailure(false)}>recommended campaign</button>
                <button className={failure ? 'on bad' : ''} onClick={() => setFailure(true)}>failure case: couple-only</button>
              </div>
            )}
          </header>
          <Calibration cal={data.calibration} failure={failure} />
        </section>
      )}

      <div className="grid2 top">
        {data.integration && (
          <section className="panel">
            <header className="panel-h"><h2>Verdict impact <span className="kr">판정 영향</span></h2></header>
            <Integration data={data.integration} />
          </section>
        )}
        {data.excitation && (
          <section className="panel">
            <header className="panel-h"><h2>Excitation recommendation <span className="kr">가진 추천</span></h2></header>
            <Excitation ex={data.excitation} />
          </section>
        )}
      </div>
    </div>
  )
}
