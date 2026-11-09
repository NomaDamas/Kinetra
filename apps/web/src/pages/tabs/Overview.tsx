import { fmt } from '../../bundle'
import { BindingPanel, FeasibilityGauge, VerdictAnswer } from '../../components/VerdictCard'
import { Empty, Panel, Stat } from '../../components/ui'
import { VariantStrip } from '../../components/VariantStrip'
import { componentState } from '../../lib/design'
import { designSnapshot, nextAction } from '../../lib/summary'
import { evalsOf, pct, shortStatus, trim } from '../../util'
import type { ProjectCtx } from '../projectCtx'

export function OverviewTab({ ctx }: { ctx: ProjectCtx }) {
  const { scenario, variant, vIdx, design } = ctx
  const v = variant.verdict
  const brief = design.status === 'ok' ? design.data.brief : null
  const snap = brief ? designSnapshot(brief) : null
  const s = shortStatus(v)
  const act = nextAction(scenario, vIdx, brief, {
    simulate: (val, extra) => ctx.hrefTo('simulate', { v: val, ...extra }),
    design: ctx.hrefTo('design'),
  })
  const f = v.feasibility
  const sampled = f.n_samples > 0
  const bc = v.binding_constraint
  const needsAttention = brief ? brief.components.filter((c) => ['fail', 'sourcing'].includes(componentState(c, brief))) : []

  return (
    <div className="stack">
      <section className={`answer ${s.tone}`} aria-labelledby="answer-h">
        <div className="eyebrow" id="answer-h">The answer</div>
        <p className="answer-line">{variant.headline}</p>
        <div className="answer-meta">
          <span className={`pill big ${s.tone}`}>{s.label}</span>
          <span className="muted small">{s.strength}</span>
          {scenario.variants.length > 1 && <span className="muted small mono">{scenario.control.label} = {trim(variant.value)} {scenario.control.unit}</span>}
        </div>
      </section>

      <div className="stats">
        <Stat
          label="Success under uncertainty"
          value={sampled ? pct(f.p_success) : '—'}
          tone={!sampled ? undefined : f.p_success >= 0.5 ? 'ok' : 'weak'}
          sub={sampled ? `95% CI ${pct(f.ci_low)} to ${pct(f.ci_high)} · n=${f.n_samples}` : 'not sampled: nothing feasible to draw from'}
          hint="p_success = share of Monte-Carlo assumption draws in which the design still succeeds"
        />
        <Stat
          label="What limits you"
          value={bc ? bc.name.split(' (')[0] : '—'}
          sub={bc ? `${bc.name.includes(' (') ? `${bc.name.slice(bc.name.indexOf(' (') + 2).replace(/\)$/, '')} · ` : ''}margin ${bc.margin >= 0 ? '+' : ''}${fmt(bc.margin)} ${bc.unit}` : 'no binding constraint reported'}
          tone={bc && bc.margin < 0 ? 'bad' : undefined}
        />
        <Stat
          label={`Mass added by the design${design.status === 'ok' && design.data.origin === 'fixture' ? ' · DEV FIXTURE' : ''}`}
          value={snap?.massAddedKg != null ? `${fmt(snap.massAddedKg, 4)} kg` : '—'}
          sub={brief ? (snap?.lastLoop ? `closed loop: p_success ${pct(snap.lastLoop.p_success)} after ${snap.loopIterations} iterations` : 'no closed-loop run') : design.status === 'loading' ? 'loading design…' : 'no design stage yet'}
        />
        <Stat
          label="Components"
          value={snap ? `${snap.ok}/${snap.total} ok` : '—'}
          sub={snap ? `${snap.custom} custom · ${snap.sourcing} need sourcing${snap.fail ? ` · ${snap.fail} fail a requirement` : ''}` : 'design not generated'}
          tone={snap && snap.fail + snap.sourcing > 0 ? 'weak' : undefined}
        />
      </div>

      <section className={`next ${act.tone}`} aria-labelledby="next-h">
        <div className="eyebrow" id="next-h">Recommended next action</div>
        <h2>{act.title}</h2>
        <p>{act.body}</p>
        {act.href && <a className="btn primary" href={act.href}>{act.cta} →</a>}
      </section>

      <Panel title="Verdict in detail" kr="판정">
        <VerdictAnswer verdict={v} />
        <div className="grid2">
          <div>
            <h4 className="first">Feasibility</h4>
            <FeasibilityGauge verdict={v} />
          </div>
          <div>
            <h4 className="first">What limits you {bc && <span className="muted small">· ranked by influence</span>}</h4>
            <BindingPanel verdict={v} assumptions={scenario.spec.assumptions} />
          </div>
        </div>
        <p className="small muted">Checks, review items, model labels and reproducibility are in <a href={ctx.hrefTo('evidence')}>Evidence</a>. {evalsOf(v) !== null && <>Search budget used: {evalsOf(v)!.toLocaleString('en-US')} evaluations.</>}</p>
      </Panel>

      {scenario.variants.length > 1 && (
        <Panel title={`Same idea, different ${scenario.control.label.toLowerCase()}`} kr="변형 비교" right={<a className="small" href={ctx.hrefTo('simulate')}>Open in Simulate →</a>}>
          <VariantStrip control={scenario.control} variants={scenario.variants} active={vIdx} onPick={(i) => ctx.setVariant(i)} />
          <p className="muted small">Each bar is one recorded, seeded run; bar height is p_success, colour is the verdict (green feasible · amber not found in budget · red impossible under assumptions). Click one to switch this whole project to it.</p>
        </Panel>
      )}

      {brief ? (
        needsAttention.length > 0 && (
          <Panel title="Needs attention before you build" kr="주의" right={<a className="small" href={ctx.hrefTo('design')}>Open Design →</a>}>
            <ul className="plain">
              {needsAttention.map((c) => (
                <li key={c.id}><b>{c.role.replace(/_/g, ' ')}</b> <span className="muted">· {c.id}</span>: {componentState(c, brief) === 'fail' ? 'chosen part misses a requirement' : 'no catalog part and no custom design yet: needs sourcing'}</li>
              ))}
            </ul>
          </Panel>
        )
      ) : design.status === 'error' ? (
        <Empty title="No design stage for this project yet">
          <code>design.json</code> was not found, so there are no sized components or CAD to show. The verdict above is unaffected. <span className="mono">{design.error}</span>
        </Empty>
      ) : null}
    </div>
  )
}
