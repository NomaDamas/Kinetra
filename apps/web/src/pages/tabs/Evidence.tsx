import { AgentRun } from '../../components/AgentRun'
import { Bom } from '../../components/Bom'
import { Panel } from '../../components/ui'
import { VerdictDetails } from '../../components/VerdictCard'
import { useIndex, useAsync, getAutoresearch } from '../../lib/data'
import { lastRunLabel } from '../../lib/summary'
import type { ProjectCtx } from '../projectCtx'

export function EvidenceTab({ ctx }: { ctx: ProjectCtx }) {
  const { scenario, variant, rec, design } = ctx
  const b = scenario.build
  const brief = design.status === 'ok' ? design.data.brief : null
  const index = useIndex()
  const ar = useAsync(() => (index.status === 'ok' ? getAutoresearch(index.data) : new Promise<never>(() => {})), `ar:${index.status}`)
  const calib = ar.status === 'ok' ? ar.data.calibration : null
  const calibRelevant = calib && scenario.template === 'rocket_car'

  return (
    <div className="stack">
      <p className="lede">Everything behind the answer: the tool-call log that produced it, the necessary-condition screen, how to reproduce it, and the limits of the model. Nothing here is a language-model claim.</p>
      <AgentRun steps={scenario.agent_steps} animate={false} />
      <VerdictDetails verdict={variant.verdict} />

      <Panel title="Reproducibility & provenance" kr="재현성">
        <div className="kv mono small">
          <div><span>bundle seed</span><b>{b?.seed ?? variant.verdict.reproducibility.seed}</b></div>
          {b?.budget && Object.entries(b.budget).map(([k, x]) => <div key={k}><span>budget.{k}</span><b>{String(x)}</b></div>)}
          <div><span>spec_hash</span><b>{variant.verdict.reproducibility.spec_hash?.slice(0, 12) ?? '—'}</b></div>
          <div><span>bundle built</span><b>{lastRunLabel(rec.builtAt, brief?.reproducibility.generated_at ?? null)}</b></div>
          {brief && <div><span>design engine</span><b>{brief.reproducibility.engine || '—'}</b></div>}
          {brief && <div><span>design seed</span><b>{brief.reproducibility.seed ?? '—'}</b></div>}
        </div>
        <h4>Model labels <span className="muted small">what this model does not capture</span></h4>
        <div className="chips">
          {[...new Set([...(b?.labels ?? []), ...variant.verdict.model_labels, ...(brief?.labels ?? [])])].map((l) => <span key={l} className="chip label">⚠ {l}</span>)}
        </div>
      </Panel>

      <Bom verdict={variant.verdict} />

      {calibRelevant && calib && (
        <Panel title="Calibration (autoresearch)" kr="보정" right={<span className="pill warn">SYNTHETIC DATA</span>}>
          <p className="small">{calib.note}</p>
          <p className="small muted">
            Held-out validation residual {calib.residual_rms_noise_units ? calib.residual_rms_noise_units.heldout_validation.toFixed(2) : '—'} (noise units; ≈1 means the fit explains the data to the sensor noise).{' '}
            Whether the mass, thrust gain and damping assumptions of this project can be identified from tests is shown in <a href="#/lab/autoresearch">Lab → Autoresearch</a>.
          </p>
        </Panel>
      )}
    </div>
  )
}
