import { useState } from 'react'
import { runEngine } from '../../bundle'
import { Assumptions } from '../../components/Assumptions'
import { Panel } from '../../components/ui'
import type { ProjectCtx } from '../projectCtx'
import { getLocalRun, registerLocalRun } from '../../lib/data'
import { go, projectHref } from '../../lib/router'

export function AssumptionsTab({ ctx }: { ctx: ProjectCtx }) {
  const { scenario, variant, vIdx } = ctx
  const [rerunning, setRerunning] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const rerun = async () => {
    setRerunning(true)
    setErr(null)
    try {
      const s = await runEngine(scenario.idea, ctx.edits)
      const id = registerLocalRun({ ...s, title: `${scenario.title ?? scenario.id} (edited)` })
      go(projectHref(id, 'overview'))
    } catch (e) {
      setErr(`Re-run failed: ${(e as Error).message}`)
    } finally {
      setRerunning(false)
    }
  }
  const isLocal = !!getLocalRun(ctx.id)

  return (
    <div className="stack">
      <p className="lede">Every number the simulation used, with its distribution, source and confidence. Approve what you trust, edit what you know better. Edits change the verdict <b>only</b> when the local engine re-runs them; the recorded verdict is never altered.</p>
      <Assumptions
        assumptions={scenario.spec.assumptions}
        verdict={variant.verdict}
        control={scenario.control}
        variants={scenario.variants}
        variantIdx={vIdx}
        onVariant={(i) => ctx.setVariant(i)}
        approved={ctx.approved}
        onApprove={ctx.setApproved}
        edits={ctx.edits}
        onEdit={ctx.setEdit}
        engineUp={ctx.engineUp && !isLocal}
        onRerun={rerun}
        rerunning={rerunning}
      />
      {err && <div className="callout bad" role="alert">{err}</div>}
      {scenario.spec.success_criteria.length > 0 && (
        <Panel title="Success criteria" kr="성공 조건">
          <div className="tablewrap">
            <table className="tbl compact">
              <thead><tr><th>Criterion</th><th>Metric</th><th>Condition</th><th>Meaning</th></tr></thead>
              <tbody>
                {scenario.spec.success_criteria.map((c) => (
                  <tr key={c.name}>
                    <td><b>{c.name}</b></td>
                    <td className="mono small">{c.metric}</td>
                    <td className="mono">{c.comparator} {c.threshold} {c.unit}</td>
                    <td className="small muted">{c.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}
    </div>
  )
}
