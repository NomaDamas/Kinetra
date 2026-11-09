import type { Verdict } from '../types'
import { isUrl } from '../util'

export function Bom({ verdict }: { verdict: Verdict }) {
  const items = verdict.bom
  const mass = items.reduce((a, b) => a + (b.mass_kg ?? 0) * b.quantity, 0)
  const cost = items.reduce((a, b) => a + (b.unit_cost_usd ?? 0) * b.quantity, 0)
  const unknown = items.filter((i) => i.unit_cost_usd === null).length
  return (
    <section className="panel" id="bom">
      <header className="panel-h">
        <h2>Bill of materials <span className="kr">부품</span></h2>
        <span className="pill muted-pill mono">{items.length} lines</span>
      </header>
      {items.length === 0 ? (
        <p className="muted">No BOM attached to this variant (usually because nothing feasible was found to build).</p>
      ) : (
        <div className="tablewrap">
          <table className="tbl compact">
            <thead><tr><th>Part</th><th>Role</th><th>Qty</th><th>Mass</th><th>Unit cost</th><th>Source</th></tr></thead>
            <tbody>
              {items.map((b, i) => (
                <tr key={i}>
                  <td><b>{b.name}</b></td>
                  <td className="mono small">{b.role}</td>
                  <td className="mono">{b.quantity}</td>
                  <td className="mono">{b.mass_kg !== null ? `${b.mass_kg} kg` : '—'}</td>
                  <td className="mono">{b.unit_cost_usd !== null ? `$${b.unit_cost_usd.toLocaleString('en-US')}` : '—'}</td>
                  <td className="small">
                    {isUrl(b.source) ? <a href={b.source} target="_blank" rel="noreferrer">{b.source.replace(/^https?:\/\//, '').slice(0, 40)}↗</a> : <span className="src llm">{b.source}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td colSpan={3}>Total (priced lines only)</td>
                <td className="mono">{mass.toFixed(1)} kg</td>
                <td className="mono">{cost > 0 ? `$${cost.toLocaleString('en-US')}` : '—'}</td>
                <td className="small muted">{unknown > 0 ? `${unknown} line(s) without a price` : ''}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
      <p className="muted small">Catalog values marked <code>llm_estimate</code> or unverified are not live web research; check them before relying on them.</p>
    </section>
  )
}
