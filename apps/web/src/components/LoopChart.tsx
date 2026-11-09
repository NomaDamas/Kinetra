import type { DLoopStep } from '../lib/design'

/** Closed loop: x = total mass after each design iteration, y = p_success with its 95% CI. Every point is a real pipeline re-run. */
export function LoopChart({ steps }: { steps: DLoopStep[] }) {
  const W = 640
  const H = 260
  const pad = { l: 52, r: 24, t: 16, b: 40 }
  const masses = steps.map((s) => s.mass_kg)
  let x0 = Math.min(...masses)
  let x1 = Math.max(...masses)
  if (x1 - x0 < 1e-9) {
    x0 -= 1
    x1 += 1
  }
  const span = x1 - x0
  x0 -= span * 0.12
  x1 += span * 0.12
  const yMax = Math.min(1, Math.max(0.1, ...steps.map((s) => s.ci[1])) * 1.15)
  const X = (m: number) => pad.l + ((m - x0) / (x1 - x0)) * (W - pad.l - pad.r)
  const Y = (p: number) => H - pad.b - (p / yMax) * (H - pad.t - pad.b)
  const yt = [0, yMax / 2, yMax]
  const xt = [x0 + span * 0.12, (x0 + x1) / 2, x1 - span * 0.12]
  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="p_success versus total mass across design iterations">
      {yt.map((t, i) => (
        <g key={i}>
          <line x1={pad.l} x2={W - pad.r} y1={Y(t)} y2={Y(t)} stroke="#1f2d3d" />
          <text className="ax" x={pad.l - 6} y={Y(t) + 3} textAnchor="end">{(t * 100).toFixed(0)}%</text>
        </g>
      ))}
      {xt.map((t, i) => (
        <text key={i} className="ax" x={X(t)} y={H - pad.b + 16} textAnchor="middle">{t.toFixed(span < 5 ? 1 : 0)} kg</text>
      ))}
      <text className="ax" x={(pad.l + W - pad.r) / 2} y={H - 6} textAnchor="middle">total mass after iteration</text>
      <text className="ax" x={12} y={(pad.t + H - pad.b) / 2} textAnchor="middle" transform={`rotate(-90 12 ${(pad.t + H - pad.b) / 2})`}>p_success (95% CI)</text>
      <polyline fill="none" stroke="#4fd1c5" strokeWidth={1.5} strokeDasharray="4 3" points={steps.map((s) => `${X(s.mass_kg)},${Y(s.p_success)}`).join(' ')} />
      {steps.map((s) => (
        <g key={s.iteration}>
          <line x1={X(s.mass_kg)} x2={X(s.mass_kg)} y1={Y(s.ci[0])} y2={Y(s.ci[1])} stroke="#e3ebf3" strokeWidth={2} />
          <line x1={X(s.mass_kg) - 4} x2={X(s.mass_kg) + 4} y1={Y(s.ci[0])} y2={Y(s.ci[0])} stroke="#e3ebf3" />
          <line x1={X(s.mass_kg) - 4} x2={X(s.mass_kg) + 4} y1={Y(s.ci[1])} y2={Y(s.ci[1])} stroke="#e3ebf3" />
          <circle cx={X(s.mass_kg)} cy={Y(s.p_success)} r={5} fill={s.status === 'FEASIBLE_FOUND' ? '#4fd1c5' : '#ffb347'} stroke="#0a0f16" strokeWidth={1.5} />
          <text className="ax" x={X(s.mass_kg) + 8} y={Y(s.p_success) - 8}>#{s.iteration}</text>
        </g>
      ))}
    </svg>
  )
}
