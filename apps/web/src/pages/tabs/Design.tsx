import { useState } from 'react'
import { fmt } from '../../bundle'
import { LoopChart } from '../../components/LoopChart'
import { StlViewer } from '../../components/StlViewer'
import { Empty, ErrorBox, Loading, Panel } from '../../components/ui'
import { assetUrl, componentState, type ComponentState, type DComponent, type DesignBundle, type DesignBrief } from '../../lib/design'
import { designSnapshot } from '../../lib/summary'
import { isUrl, pct, shortStatus, trim } from '../../util'
import type { VerdictStatus } from '../../types'
import type { ProjectCtx } from '../projectCtx'

const STATE_CHIP: Record<ComponentState, { cls: string; label: string; tip: string }> = {
  ok: { cls: 'ok', label: 'MEETS ALL', tip: 'Catalog part that meets every requirement' },
  fail: { cls: 'bad', label: 'MISSES REQUIREMENT', tip: 'The chosen part fails at least one requirement' },
  custom: { cls: 'recorded', label: 'CUSTOM PART', tip: 'No catalog part fits; a custom part is designed below' },
  sourcing: { cls: 'warn', label: 'NEEDS SOURCING', tip: 'No catalog part and no custom design: has to be sourced or designed' },
}

export function DesignTab({ ctx }: { ctx: ProjectCtx }) {
  const d = ctx.design
  if (d.status === 'loading') return <Loading what="design brief" />
  if (d.status === 'error')
    return (
      <div className="stack">
        <Empty title="No design stage for this project yet">
          The design stage (requirements → components → custom parts → closed loop) is generated into <code>design.json</code> next to the scenario. It is missing here, so this tab has nothing to show; the verdict does not depend on it.
        </Empty>
        <ErrorBox title="Why it is empty" error={d.error} />
      </div>
    )
  return <DesignBody bundle={d.data} ctx={ctx} />
}

function DesignBody({ bundle, ctx }: { bundle: DesignBundle; ctx: ProjectCtx }) {
  const b = bundle.brief
  const snap = designSnapshot(b)
  const notBase = b.base_variant !== null && Math.abs(b.base_variant - ctx.variant.value) > 1e-9
  return (
    <div className="stack">
      {bundle.origin === 'fixture' && (
        <div className="banner warn"><b>DEV FIXTURE</b> · this design is a sample from <code>apps/web/fixtures/design</code>, shown only because <code>design.json</code> is missing from the bundle. Numbers are illustrative, not engine output.</div>
      )}
      <section className="answer info">
        <div className="eyebrow">Design summary</div>
        <p className="answer-line">{b.headline || 'Design brief'}</p>
        <div className="answer-meta">
          <span className="pill muted-pill mono">derived from {ctx.scenario.control.label} = {b.base_variant !== null ? trim(b.base_variant) : '?'} {ctx.scenario.control.unit}</span>
          {snap.massAddedKg !== null && <span className="pill muted-pill mono">+{fmt(snap.massAddedKg, 4)} kg added</span>}
          <span className="pill ok">{snap.ok} ok</span>
          {snap.custom > 0 && <span className="pill recorded">{snap.custom} custom</span>}
          {snap.sourcing > 0 && <span className="pill warn">{snap.sourcing} need sourcing</span>}
          {snap.fail > 0 && <span className="pill bad">{snap.fail} miss a requirement</span>}
        </div>
        {notBase && <p className="small muted">The design is derived from the {trim(b.base_variant!)} {ctx.scenario.control.unit} run, not the {trim(ctx.variant.value)} {ctx.scenario.control.unit} run you are viewing elsewhere.</p>}
      </section>

      <Requirements b={b} />
      <Components b={b} />
      <CustomParts b={b} bundle={bundle} />
      <ClosedLoop b={b} />
      <Alternatives b={b} ctx={ctx} />
      <RisksTests b={b} />
      {b.labels.length > 0 && (
        <div className="chips">{b.labels.map((l) => <span className="chip label" key={l}>⚠ {l}</span>)}</div>
      )}
    </div>
  )
}

function Requirements({ b }: { b: DesignBrief }) {
  return (
    <Panel id="requirements" title="1 · Requirements" kr="요구사항" right={<span className="pill muted-pill">derived from the witness run, with margin</span>}>
      {b.requirements.length === 0 ? (
        <Empty title="No requirements derived" />
      ) : (
        <div className="tablewrap">
          <table className="tbl compact">
            <thead><tr><th>Requirement</th><th>Simulated value</th><th>Margin</th><th>Required</th><th>Source</th></tr></thead>
            <tbody>
              {b.requirements.map((r) => (
                <tr key={r.id}>
                  <td><b>{r.label}</b><div className="small muted">{r.derived_from}</div></td>
                  <td className="mono nowrap">{fmt(r.value, 4)} {r.unit}</td>
                  <td className="mono nowrap">× {fmt(r.margin_factor, 3)}</td>
                  <td className="mono nowrap"><b>{fmt(r.required, 4)} {r.unit}</b></td>
                  <td><span className={`pill ${r.source === 'simulation' ? 'ok' : 'warn'}`}>{r.source || 'unknown'}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  )
}

function Components({ b }: { b: DesignBrief }) {
  return (
    <Panel id="components" title="2 · Components" kr="부품 선정" right={<span className="pill muted-pill">smallest catalog entry meeting every requirement</span>}>
      {b.components.length === 0 ? (
        <Empty title="No components selected" />
      ) : (
        <div className="cards">
          {b.components.map((c) => <ComponentCard key={c.id} c={c} b={b} />)}
        </div>
      )}
    </Panel>
  )
}

function ComponentCard({ c, b }: { c: DComponent; b: DesignBrief }) {
  const st = componentState(c, b)
  const chip = STATE_CHIP[st]
  const ch = c.choice
  const reqLabel = (id: string) => b.requirements.find((r) => r.id === id)?.label ?? id
  return (
    <article className={`ccard ${st}`}>
      <header>
        <div>
          <div className="eyebrow">{c.role.replace(/_/g, ' ')} · ×{c.quantity}</div>
          <h3>{ch ? ch.name : c.custom ? 'No catalog part' : c.id}</h3>
          {ch?.vendor && <div className="small muted">{ch.vendor}</div>}
        </div>
        <span className={`pill ${chip.cls}`} title={chip.tip}>{chip.label}</span>
      </header>
      {c.meets.length > 0 && (
        <table className="tbl compact meets">
          <thead><tr><th>Requirement</th><th>Needs</th><th>Provides</th><th>Margin</th><th /></tr></thead>
          <tbody>
            {c.meets.map((m) => (
              <tr key={m.requirement_id} className={m.ok ? '' : 'rv-block'}>
                <td className="small">{reqLabel(m.requirement_id)}</td>
                <td className="mono nowrap">{fmt(m.required, 4)} {m.unit}</td>
                <td className="mono nowrap">{fmt(m.provided, 4)} {m.unit}</td>
                <td className={`mono ${m.ok ? 'pos' : 'neg'}`}>{m.margin >= 0 ? '+' : ''}{(m.margin * 100).toFixed(0)}%</td>
                <td className={m.ok ? 'pos' : 'neg'} aria-label={m.ok ? 'ok' : 'fails'}>{m.ok ? '✓' : '✕'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="ccard-foot small">
        {ch && (
          <>
            <span className="mono">{ch.mass_kg !== null ? `${ch.mass_kg} kg each` : 'mass n/a'}</span>
            <span className="mono">{ch.unit_cost_usd !== null ? `$${ch.unit_cost_usd.toLocaleString('en-US')} each` : 'unpriced'}</span>
            <span className={`pill ${ch.verified ? 'ok' : 'warn'}`} title={ch.verified ? 'Spec checked against the source' : 'Not checked against the source: verify before ordering'}>{ch.verified ? 'verified' : 'unverified'}</span>
            {isUrl(ch.source) ? <a href={ch.source} target="_blank" rel="noreferrer">source ↗</a> : <span className="src llm">{ch.source || 'no source'}</span>}
          </>
        )}
        {c.cad && <span className="pill recorded">CAD: {c.cad}</span>}
      </div>
      {Object.keys(ch?.specs ?? {}).length > 0 && (
        <div className="kv mono small">{Object.entries(ch!.specs).map(([k, v]) => <div key={k}><span>{k}</span><b>{String(v)}</b></div>)}</div>
      )}
      {c.alternatives.length > 0 && (
        <details>
          <summary className="small muted">{c.alternatives.length} rejected alternative(s)</summary>
          <ul className="plain small">{c.alternatives.map((a, i) => <li key={i}><b>{a.name}</b> <span className="muted">· {a.why_rejected}</span></li>)}</ul>
        </details>
      )}
    </article>
  )
}

function CustomParts({ b, bundle }: { b: DesignBrief; bundle: DesignBundle }) {
  const [sel, setSel] = useState(0)
  const p = b.custom_parts[Math.min(sel, b.custom_parts.length - 1)]
  const flagged = b.components.filter((c) => componentState(c, b) === 'sourcing')
  return (
    <Panel id="custom-parts" title="3 · Custom parts & CAD" kr="맞춤 부품" right={<span className="pill warn">simplified model, needs FEA</span>}>
      {b.custom_parts.length === 0 ? (
        <Empty title="No custom parts were needed or designed">
          {flagged.length > 0 ? `${flagged.length} component(s) still need sourcing: ${flagged.map((c) => c.role.replace(/_/g, ' ')).join(', ')}.` : 'Every component came from the catalog.'}
        </Empty>
      ) : (
        <div className="parts">
          <ul className="partlist" role="tablist" aria-label="Custom parts">
            {b.custom_parts.map((x, i) => (
              <li key={x.id}>
                <button role="tab" aria-selected={i === sel} className={i === sel ? 'on' : ''} onClick={() => setSel(i)}>
                  <b>{x.name}</b>
                  <span className="small muted">{x.material} · {x.mass_kg !== null ? `${x.mass_kg} kg` : 'mass n/a'}</span>
                  {x.check && <span className={`pill ${x.check.ok ? 'ok' : 'bad'}`}>{x.check.ok ? 'check ok' : 'check fails'}</span>}
                </button>
              </li>
            ))}
          </ul>
          <div className="partview">
            {p.cad_stl ? <StlViewer key={p.id} url={assetUrl(bundle, p.cad_stl)} label={p.name} /> : <Empty title="No CAD preview file">This part has parameters but no STL was generated.</Empty>}
            <div className="partinfo">
              <div className="kv mono small">
                {Object.entries(p.params).map(([k, v]) => <div key={k}><span>{k}</span><b>{String(v)}</b></div>)}
              </div>
              {p.load_case && (
                <p className="small">Load case: <b className="mono">{p.load_case.force_N !== null ? fmt(p.load_case.force_N, 4) : '?'} N</b>, safety factor <b className="mono">{p.load_case.safety_factor ?? '?'}</b></p>
              )}
              {p.check ? (
                <div className={`callout ${p.check.ok ? '' : 'bad'}`}>
                  <b>{p.check.method}</b>
                  <div className="mono">{p.check.stress_MPa !== null ? `${fmt(p.check.stress_MPa, 4)} MPa` : '?'} vs allowable {p.check.allow_MPa !== null ? `${fmt(p.check.allow_MPa, 4)} MPa` : '?'} → {p.check.ok ? 'OK' : 'FAILS'}</div>
                  <div className="small warn-t">⚠ {p.check.label}</div>
                </div>
              ) : <p className="small muted">No structural check attached.</p>}
              <div className="row">
                {p.cad_stl && <a className="btn" href={assetUrl(bundle, p.cad_stl)} download>↓ STL</a>}
                {p.cad_step ? <a className="btn" href={assetUrl(bundle, p.cad_step)} download>↓ STEP</a> : <span className="muted small">STEP not generated (no CAD kernel on the build machine)</span>}
              </div>
            </div>
          </div>
        </div>
      )}
    </Panel>
  )
}

function ClosedLoop({ b }: { b: DesignBrief }) {
  return (
    <Panel id="closed-loop" title="4 · Closed loop" kr="폐루프 검증" right={<span className="pill muted-pill">design → mass → re-simulate → verdict</span>}>
      {b.closed_loop.length === 0 ? (
        <Empty title="The closed loop has not been run">The designed hardware's mass has not been fed back into the simulation yet, so reliability of the <i>designed</i> hardware is unknown.</Empty>
      ) : (
        <>
          <p className="small muted">Each point is a real re-run of search + Monte-Carlo with the mass of the chosen hardware put back into the model. A flat tail means the mass has converged.</p>
          <div className="loop">
            <LoopChart steps={b.closed_loop} />
            <div className="tablewrap">
              <table className="tbl compact">
                <thead><tr><th>#</th><th>Mass</th><th>Verdict</th><th>p_success</th><th>Note</th></tr></thead>
                <tbody>
                  {b.closed_loop.map((s) => (
                    <tr key={s.iteration}>
                      <td className="mono">{s.iteration}</td>
                      <td className="mono nowrap">{fmt(s.mass_kg, 5)} kg</td>
                      <td><span className={`pill ${s.status === 'FEASIBLE_FOUND' ? 'ok' : s.status === 'INFEASIBLE_NECESSARY_CONDITION' ? 'bad' : 'weak'}`}>{s.status === 'FEASIBLE_FOUND' ? 'FEASIBLE' : s.status === 'INFEASIBLE_NECESSARY_CONDITION' ? 'IMPOSSIBLE' : 'NOT FOUND'}</span></td>
                      <td className="mono nowrap">{pct(s.p_success)}<div className="small muted">[{pct(s.ci[0])}, {pct(s.ci[1])}] n={s.n}</div></td>
                      <td className="small muted">{s.note}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </Panel>
  )
}

function Alternatives({ b, ctx }: { b: DesignBrief; ctx: ProjectCtx }) {
  return (
    <Panel id="alternatives" title="5 · Alternatives" kr="대안 비교" right={<span className="pill muted-pill">same verdict machinery</span>}>
      {b.alternatives.length === 0 ? (
        <Empty title="No alternatives were compared" />
      ) : (
        <div className="tablewrap">
          <table className="tbl">
            <thead><tr><th>Option</th><th>Change</th><th>Verdict</th><th>p_success</th><th>Mass</th><th>Cost</th><th>Note</th></tr></thead>
            <tbody>
              {b.alternatives.map((a) => {
                const tone = a.status === 'FEASIBLE_FOUND' ? 'ok' : a.status === 'INFEASIBLE_NECESSARY_CONDITION' ? 'bad' : 'weak'
                return (
                  <tr key={a.id} className={a.recommended ? 'is-ctl' : ''}>
                    <td><b>{a.label}</b> {a.recommended && <span className="pill ok tiny">RECOMMENDED</span>}</td>
                    <td className="mono small">{Object.entries(a.changes).map(([k, v]) => `${k} = ${typeof v === 'number' ? trim(v) : v}`).join(', ') || '—'}</td>
                    <td><span className={`pill ${tone}`}>{shortStatus({ status: a.status as VerdictStatus }).label}</span></td>
                    <td className="mono">{a.p_success !== null ? pct(a.p_success) : '—'}</td>
                    <td className="mono nowrap">{a.mass_kg !== null ? `${fmt(a.mass_kg, 5)} kg` : '—'}</td>
                    <td className="mono">{a.cost_usd !== null ? `$${a.cost_usd.toLocaleString('en-US')}` : 'unpriced'}</td>
                    <td className="small muted">{a.note}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="small muted">Want to try other values yourself? <a href={ctx.hrefTo('simulate', { mode: 'live' })}>Run it live in Simulate</a>.</p>
    </Panel>
  )
}

function RisksTests({ b }: { b: DesignBrief }) {
  return (
    <div className="grid2 top">
      <Panel id="risks" title="6 · Risks" kr="위험">
        {b.risks.length === 0 ? <Empty title="No risks listed" /> : (
          <ul className="plain risks">
            {b.risks.map((r, i) => (
              <li key={i}>
                <span className={`pill ${r.severity === 'high' ? 'bad' : r.severity === 'medium' || r.severity === 'med' ? 'warn' : 'muted-pill'}`}>{r.severity.toUpperCase()}</span>
                <div>{r.text}{r.physical_test && <div className="small muted">Physical test: {r.physical_test}</div>}</div>
              </li>
            ))}
          </ul>
        )}
      </Panel>
      <Panel id="next-tests" title="Next physical tests" kr="다음 시험">
        {b.next_tests.length === 0 ? <Empty title="No tests listed" /> : (
          <ol className="plain tests">
            {b.next_tests.map((t, i) => (
              <li key={i}>
                <b>{t.name}</b>
                <div className="small">{t.purpose}</div>
                <div className="small muted">{t.cost !== null ? `~$${t.cost.toLocaleString('en-US')}` : 'cost not sourced'}{t.source && (isUrl(t.source) ? <> · <a href={t.source} target="_blank" rel="noreferrer">source ↗</a></> : ` · ${t.source}`)}</div>
              </li>
            ))}
          </ol>
        )}
      </Panel>
    </div>
  )
}
