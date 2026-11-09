// Hand-rolled SVG line chart (same visual language as the Autoresearch charts; no chart library).
import { fmt } from '../bundle'

interface Props {
  title: string
  /** x values; or give `dt` to use x = index * dt. */
  xs?: ArrayLike<number>
  dt?: number
  ys: ArrayLike<number>
  /** Number of valid points (the arrays may be longer, e.g. preallocated). */
  n: number
  xlabel: string
  ylabel: string
  /** Fixed x range; defaults to the data range. */
  xRange?: [number, number]
  /** Vertical cursor (stream frontier), in x units. */
  cursor?: number | null
  color?: string
  h?: number
  testId?: string
}

const W = 420
const PAD = { l: 44, r: 10, t: 8, b: 26 }

export function XYChart({ title, xs, dt = 1, ys, n, xlabel, ylabel, xRange, cursor, color = '#4fd1c5', h = 150, testId }: Props) {
  const pts: [number, number][] = []
  for (let i = 0; i < n; i++) {
    const x = xs ? xs[i] : i * dt
    const y = ys[i]
    if (Number.isFinite(x) && Number.isFinite(y)) pts.push([x, y])
  }
  let x0 = xRange ? xRange[0] : pts.length ? pts[0][0] : 0
  let x1 = xRange ? xRange[1] : pts.length ? pts[pts.length - 1][0] : 1
  if (x1 <= x0) x1 = x0 + 1
  let y0 = Infinity
  let y1 = -Infinity
  for (const p of pts) {
    if (p[1] < y0) y0 = p[1]
    if (p[1] > y1) y1 = p[1]
  }
  if (!Number.isFinite(y0)) {
    y0 = 0
    y1 = 1
  }
  if (y1 === y0) {
    y1 += 1
    y0 -= 1
  }
  const yp = (y1 - y0) * 0.08
  y0 -= yp
  y1 += yp
  const X = (x: number) => PAD.l + ((x - x0) / (x1 - x0)) * (W - PAD.l - PAD.r)
  const Y = (y: number) => h - PAD.b - ((y - y0) / (y1 - y0)) * (h - PAD.t - PAD.b)
  const yt = Array.from({ length: 4 }, (_, i) => y0 + ((y1 - y0) * i) / 3)
  const xt = Array.from({ length: 5 }, (_, i) => x0 + ((x1 - x0) * i) / 4)
  const line = pts.map(([x, y]) => `${X(x).toFixed(1)},${Y(y).toFixed(1)}`).join(' ')
  return (
    <figure className="live-chart" data-testid={testId}>
      <figcaption className="small">
        <b>{title}</b>
        {pts.length > 0 && (
          <span className="mono muted"> · {fmt(pts[pts.length - 1][1], 4)} {ylabel}</span>
        )}
      </figcaption>
      <svg viewBox={`0 0 ${W} ${h}`} className="chart" role="img" aria-label={`${title}: ${ylabel} vs ${xlabel}`}>
        {yt.map((v, i) => (
          <g key={i}>
            <line x1={PAD.l} x2={W - PAD.r} y1={Y(v)} y2={Y(v)} stroke="#1f2d3b" />
            <text x={PAD.l - 5} y={Y(v) + 3} textAnchor="end" className="ax">{fmt(v, 3)}</text>
          </g>
        ))}
        {xt.map((v, i) => (
          <text key={i} x={X(v)} y={h - PAD.b + 12} textAnchor="middle" className="ax">{fmt(v, 3)}</text>
        ))}
        <text x={W / 2} y={h - 2} textAnchor="middle" className="ax">{xlabel}</text>
        {pts.length > 1 && <polyline fill="none" stroke={color} strokeWidth={1.7} points={line} />}
        {pts.length === 1 && <circle cx={X(pts[0][0])} cy={Y(pts[0][1])} r={2.5} fill={color} />}
        {cursor != null && cursor >= x0 && cursor <= x1 && (
          <line x1={X(cursor)} x2={X(cursor)} y1={PAD.t} y2={h - PAD.b} stroke="#ff6b6b" strokeWidth={1.2} strokeDasharray="3 3" />
        )}
      </svg>
    </figure>
  )
}
