import type { Assumption, Verdict } from '../types'
import { fmt } from '../bundle'
import { evalsOf, statusMeta, trim } from '../util'

function Gauge({ v }: { v: Verdict }) {
  const f = v.feasibility
  const sampled = f.n_samples > 0
  const pct = (x: number) => `${(x * 100).toFixed(2)}%`
  return (
    <div className="gauge-wrap">
      <div className="gauge-num mono">
        {sampled ? `${(f.p_success * 100).toFixed(1)}%` : '—'}
        <span> p_success</span>
      </div>
      <div className={`gauge ${sampled ? '' : 'off'}`} role="img" aria-label={`p_success ${f.p_success}, CI ${f.ci_low} to ${f.ci_high}`}>
        <div className="gauge-ci" style={{ left: pct(f.ci_low), width: pct(Math.max(0.004, f.ci_high - f.ci_low)) }} />
        <div className="gauge-pt" style={{ left: pct(f.p_success) }} />
        <span className="gauge-tick" style={{ left: '0%' }}>0</span>
        <span className="gauge-tick" style={{ left: '50%' }}>0.5</span>
        <span className="gauge-tick" style={{ left: '100%' }}>1</span>
      </div>
      <div className="muted small mono">
        {sampled
          ? `${f.ci_method} 95% CI [${f.ci_low.toFixed(3)}, ${f.ci_high.toFixed(3)}] · n=${f.n_samples} Monte-Carlo samples`
          : 'no Monte-Carlo run: the necessary-condition screen failed first, or nothing feasible was found to sample'}
      </div>
    </div>
  )
}

/** Answer-first block: the two-part claim (existence + reliability) and the status banner. */
export function VerdictAnswer({ verdict: v }: { verdict: Verdict }) {
  const m = statusMeta(v)
  const failed = v.necessary_checks.filter((c) => !c.passed)
  return (
    <>
      <div className="facts">
        <div className="fact">
          <div className="eyebrow">1 · existence on the nominal model</div>
          <b className={`fact-v ${m.tone}`}>
            {v.status === 'FEASIBLE_FOUND'
              ? 'Witness found (strong existence evidence)'
              : v.status === 'INFEASIBLE_NECESSARY_CONDITION'
                ? 'Necessary condition violated (strong impossibility)'
                : v.status === 'NOT_FOUND_IN_BUDGET'
                  ? 'No witness found (weak, not proof)'
                  : 'No verdict (model invalid)'}
          </b>
          <span className="muted small">
            {v.status === 'FEASIBLE_FOUND' ? 'One parameter set works when every assumption sits at its nominal value. It says nothing about how often.' : 'Judged on the nominal model and the stated assumptions.'}
          </span>
        </div>
        <div className="fact">
          <div className="eyebrow">2 · reliability under uncertainty</div>
          <b className="fact-v mono">
            {v.feasibility.n_samples > 0
              ? `p_success ${(v.feasibility.p_success * 100).toFixed(1)}%  CI [${(v.feasibility.ci_low * 100).toFixed(1)}, ${(v.feasibility.ci_high * 100).toFixed(1)}]%`
              : 'not sampled'}
          </b>
          {v.feasibility.n_samples > 0 && v.feasibility.p_success < 0.5 && <span className="pill warn fragile">FRAGILE UNDER UNCERTAINTY</span>}
          <span className="muted small">Share of Monte-Carlo assumption draws (n={v.feasibility.n_samples}) in which the same design still succeeds.</span>
        </div>
      </div>

      <div className={`status ${m.tone}`}>
        <div className="status-t">{m.title}</div>
        <div className="status-kr">{m.kr}</div>
        <p>{v.summary}</p>
        <p className="status-ex">{m.explain}</p>
        {v.status === 'NOT_FOUND_IN_BUDGET' && (
          <p className="weak-note">
            Weak result: not found in {evalsOf(v)?.toLocaleString('en-US') ?? 'N'} evals, <b>not a proof</b> of impossibility.
          </p>
        )}
        {v.status === 'INFEASIBLE_NECESSARY_CONDITION' && failed[0] && (
          <p className="failed-check mono">
            ✕ {failed[0].name}: measured {fmt(failed[0].measured)} {failed[0].unit} vs limit {fmt(failed[0].limit)} {failed[0].unit}
          </p>
        )}
      </div>
    </>
  )
}

/** p_success gauge + witness parameters. */
export function FeasibilityGauge({ verdict: v }: { verdict: Verdict }) {
  return (
    <div>
      <Gauge v={v} />
      {Object.keys(v.best_params).length > 0 && (
        <details className="bp">
          <summary>Witness parameters ({Object.keys(v.best_params).length})</summary>
          <div className="kv mono small">
            {Object.entries(v.best_params).map(([k, x]) => (
              <div key={k}><span>{k}</span><b>{fmt(x, 4)}</b></div>
            ))}
          </div>
        </details>
      )}
    </div>
  )
}

/** What limits you most: binding constraint + sensitivity bars. */
export function BindingPanel({ verdict: v, assumptions }: { verdict: Verdict; assumptions: Assumption[] }) {
  const label = (k: string) => assumptions.find((a) => a.key === k)?.label ?? k
  const bc = v.binding_constraint
  const sens = bc ? [...bc.sensitivities].sort((a, b) => a.rank - b.rank) : []
  const maxEff = Math.max(1e-12, ...sens.map((s) => Math.abs(s.effect)))
  if (!bc) return <div className="muted">No binding constraint reported.</div>
  return (
    <div>
      <div className="mono bc">
        {bc.name}: margin <b className={bc.margin < 0 ? 'neg' : 'pos'}>{bc.margin >= 0 ? '+' : ''}{fmt(bc.margin)} {bc.unit}</b>
      </div>
      <div className="bars">
        {sens.map((s) => (
          <div className="bar-row" key={s.assumption_key}>
            <span className="bar-l" title={s.assumption_key}>{label(s.assumption_key)}</span>
            <span className="bar-track">
              <i className={s.effect >= 0 ? 'pos' : 'neg'} style={{ width: `${(Math.abs(s.effect) / maxEff) * 100}%` }} />
            </span>
            <span className="mono small bar-v">{s.effect >= 0 ? '+' : ''}{fmt(s.effect, 2)}</span>
          </div>
        ))}
      </div>
      {sens.length > 0 && <div className="muted small">sensitivity ({sens[0].method}); signed effect on p_success or margin</div>}
    </div>
  )
}

/** Evidence tab: necessary checks, review items, model labels, reproducibility, cost. */
export function VerdictDetails({ verdict: v }: { verdict: Verdict }) {
  const sb = v.reproducibility.search_budget
  const ce = v.cost_estimate
  const pe = ce?.physical_equivalent_estimate
  return (
    <section className="panel verdict" id="verdict">
      <header className="panel-h">
        <h2>Verdict details <span className="kr">판정 근거</span></h2>
        <span className="pill muted-pill mono">{statusMeta(v).strength}</span>
      </header>

      <h4 className="first">Necessary-condition checks</h4>
      {v.necessary_checks.length === 0 ? (
        <div className="muted small">none</div>
      ) : (
        <div className="tablewrap">
          <table className="tbl compact">
            <thead>
              <tr><th></th><th>Check</th><th>Measured</th><th>Limit</th><th>Note</th></tr>
            </thead>
            <tbody>
              {v.necessary_checks.map((c) => (
                <tr key={c.name} className={c.passed ? '' : 'rv-block'}>
                  <td className={c.passed ? 'pos' : 'neg'}>{c.passed ? '✓' : '✕'}</td>
                  <td className="mono">{c.name}</td>
                  <td className="mono">{fmt(c.measured)} {c.unit}</td>
                  <td className="mono">{fmt(c.limit)} {c.unit}</td>
                  <td className="small muted">{c.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {v.human_review.items.length > 0 && (
        <>
          <h4>Human review items</h4>
          <ul className="rvlist">
            {v.human_review.items.map((i, k) => (
              <li key={k} className={i.severity}>
                <b>{i.severity.toUpperCase()}</b> {i.assumption_key && <code>{i.assumption_key}</code>} {i.reason}
              </li>
            ))}
          </ul>
        </>
      )}

      <h4>Model labels <span className="muted small">what this model does not capture</span></h4>
      <div className="chips">
        {v.model_labels.length === 0 && <span className="muted small">none</span>}
        {v.model_labels.map((l) => (
          <span className="chip label" key={l}>⚠ {l}</span>
        ))}
      </div>

      <div className="grid2">
        <div>
          <h4>Reproducibility</h4>
          <div className="kv mono small">
            <div><span>seed</span><b>{v.reproducibility.seed}</b></div>
            {Object.entries(v.reproducibility.versions).map(([k, x]) => (
              <div key={k}><span>{k}</span><b>{x}</b></div>
            ))}
            {Object.entries(sb).map(([k, x]) => (
              <div key={k}><span>budget.{k}</span><b>{x.toLocaleString('en-US')}</b></div>
            ))}
            {v.reproducibility.spec_hash && <div><span>spec_hash</span><b>{v.reproducibility.spec_hash.slice(0, 12)}</b></div>}
          </div>
        </div>
        <div>
          <h4>Cost</h4>
          {ce ? (
            <div className="cost">
              <div className="cost-row">
                <span className="tagk">SIMULATED</span>
                <b className="mono">{ce.sim_cost.n_evals.toLocaleString('en-US')} evals · {ce.sim_cost.wall_seconds.toFixed(1)} s wall</b>
              </div>
              {pe ? (
                <div className="cost-row">
                  <span className="tagk est">ESTIMATE</span>
                  <div>
                    <b className="mono">${pe.low_usd.toLocaleString('en-US')} – ${pe.high_usd.toLocaleString('en-US')}</b> physical-equivalent trial
                    <div className="muted small">{pe.basis}</div>
                    <div className="small">
                      {pe.sources.map((s, i) => (/^https?:/.test(s) ? <a key={i} href={s} target="_blank" rel="noreferrer">{s.replace(/^https?:\/\//, '').slice(0, 40)}↗ </a> : <span key={i} className="src llm">{s} </span>))}
                    </div>
                  </div>
                </div>
              ) : (
                <div className="muted small">No physical-equivalent estimate attached.</div>
              )}
            </div>
          ) : (
            <div className="muted small">no cost estimate</div>
          )}
        </div>
      </div>
      <div className="muted small mono">trajectory_ref: {v.trajectory_ref ?? '—'} · {trim(v.feasibility.n_samples)} MC samples</div>
    </section>
  )
}
