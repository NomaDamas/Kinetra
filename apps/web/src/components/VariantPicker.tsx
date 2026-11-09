import type { Control, Variant } from '../bundle'
import { trim } from '../util'

interface Props {
  control: Control
  variants: Variant[]
  index: number
  onChange: (i: number) => void
}

/** The recorded sweep of one control assumption: each tick is a separate seeded run (nothing between ticks is simulated). */
export function VariantPicker({ control, variants, index, onChange }: Props) {
  const val = control.values
  if (variants.length < 2) {
    return (
      <div className="control">
        <div className="eyebrow">single run</div>
        <p className="muted small">{control.hint}</p>
      </div>
    )
  }
  return (
    <div className="control">
      <div className="control-h">
        <div>
          <div className="eyebrow">control assumption · swept</div>
          <h3>{control.label}</h3>
        </div>
        <div className="control-v mono">
          {trim(variants[index].value)} <span>{control.unit}</span>
        </div>
      </div>
      <input
        className="slider"
        type="range"
        min={0}
        max={val.length - 1}
        step={1}
        value={index}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-label={control.label}
      />
      <div className="ticks">
        {val.map((v, i) => (
          <button key={i} className={`tick ${i === index ? 'on' : ''} ${variants[i]?.verdict.status === 'FEASIBLE_FOUND' ? 'okk' : 'nok'}`} onClick={() => onChange(i)} aria-pressed={i === index}>
            <i />
            <span className="mono">{trim(v)}</span>
          </button>
        ))}
      </div>
      <p className="muted small">
        {control.hint} <b>The slider snaps to {val.length} precomputed runs</b>: values between ticks are not simulated. Each tick is a real, seeded MuJoCo run. Green = feasible found, red = not.
      </p>
    </div>
  )
}
