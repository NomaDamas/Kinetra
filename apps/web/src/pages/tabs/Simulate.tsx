import { useEffect, useRef, useState } from 'react'
import { loadTrajectory, type DemoIndex } from '../../bundle'
import { FixCallout } from '../../components/Fix'
import { Replay } from '../../components/Replay'
import { Panel, ErrorBox } from '../../components/ui'
import { VariantPicker } from '../../components/VariantPicker'
import { VariantStrip } from '../../components/VariantStrip'
import { LivePanel } from '../../live/LivePanel'
import type { LiveTemplate } from '../../live/types'
import { TEMPLATES } from '../../live/config'
import { go, projectHref } from '../../lib/router'
import { fixedIndex } from '../../lib/summary'
import { shortStatus, trim } from '../../util'
import type { Trajectory } from '../../types'
import type { ProjectCtx } from '../projectCtx'

type Mode = 'recorded' | 'live'

export function SimulateTab({ ctx, index }: { ctx: ProjectCtx; index: DemoIndex | null }) {
  const { scenario, variant, query } = ctx
  const mode: Mode = query.get('mode') === 'live' ? 'live' : 'recorded'
  const liveTemplate = TEMPLATES.find((t) => t.scenarioTemplate === scenario.template)?.template as LiveTemplate | undefined
  const [liveOpened, setLiveOpened] = useState(mode === 'live')
  useEffect(() => {
    if (mode === 'live') setLiveOpened(true)
  }, [mode])

  const setMode = (m: Mode) => {
    const q: Record<string, string> = { v: String(variant.value) }
    if (m === 'live') q.mode = 'live'
    go(projectHref(ctx.id, 'simulate', q), true)
  }

  return (
    <div className="stack">
      <div className="modebar" role="tablist" aria-label="Simulation source">
        <button role="tab" aria-selected={mode === 'recorded'} className={`mode ${mode === 'recorded' ? 'on' : ''}`} onClick={() => setMode('recorded')}>
          <span className="pill recorded">RECORDED</span>
          <span>Replay stored MuJoCo runs</span>
        </button>
        <button role="tab" aria-selected={mode === 'live'} className={`mode live ${mode === 'live' ? 'on' : ''}`} onClick={() => setMode('live')} data-testid="tab-live" disabled={!liveTemplate}>
          <span className="live-badge"><i className="live-dot" />LIVE</span>
          <span>{liveTemplate ? 'Real MuJoCo on your local engine' : 'No live template for this project'}</span>
        </button>
      </div>

      <div hidden={mode !== 'recorded'}>
        <RecordedView ctx={ctx} />
      </div>
      {liveOpened && liveTemplate && (
        <div hidden={mode !== 'live'}>
          <LivePanel index={index} lockTemplate={liveTemplate} />
        </div>
      )}
    </div>
  )
}

function RecordedView({ ctx }: { ctx: ProjectCtx }) {
  const { scenario, variant, vIdx, query } = ctx
  const [traj, setTraj] = useState<Trajectory | null>(null)
  const [cmpTraj, setCmpTraj] = useState<Trajectory | null>(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [playToken, setPlayToken] = useState(() => (query.get('play') === '1' ? 1 : 0))
  const compare = query.get('cmp') === '1'
  const fixedIdx = fixedIndex(scenario, variant)
  const first = useRef(true)

  useEffect(() => {
    let live = true
    setLoading(true)
    setErr(null)
    loadTrajectory(scenario.id, variant)
      .then((t) => live && setTraj(t))
      .catch((e: Error) => live && setErr(e.message))
      .finally(() => live && setLoading(false))
    if (first.current) first.current = false
    else setPlayToken((t) => t + 1)
    return () => {
      live = false
    }
  }, [scenario, variant])

  useEffect(() => {
    if (!compare || fixedIdx === null || variant.verdict.status === 'FEASIBLE_FOUND') {
      setCmpTraj(null)
      return
    }
    let live = true
    loadTrajectory(scenario.id, scenario.variants[fixedIdx]).then((t) => live && setCmpTraj(t)).catch(() => live && setCmpTraj(null))
    return () => {
      live = false
    }
  }, [compare, scenario, fixedIdx, variant])

  const setCompare = (on: boolean) => {
    const q: Record<string, string> = { v: String(variant.value) }
    if (on) q.cmp = '1'
    go(projectHref(ctx.id, 'simulate', q), true)
  }
  const applyFix = () => {
    if (fixedIdx === null) return
    ctx.setVariant(fixedIdx, { tab: 'simulate', extra: { play: '1' } })
  }
  const s = shortStatus(variant.verdict)

  return (
    <div className="stack">
      <VariantPicker control={scenario.control} variants={scenario.variants} index={vIdx} onChange={(i) => ctx.setVariant(i)} />
      <div className={`headline-bar ${s.tone}`}>
        <span className={`pill big ${s.tone}`}>{s.label}</span>
        <span className="hl">{variant.headline}</span>
      </div>

      <Panel
        id="replay"
        title="3D replay"
        kr="재생"
        right={
          <>
            <span className="pill recorded">RECORDED · stored MuJoCo trajectory</span>
            <span className="pill muted-pill">Three.js draws it; no physics here</span>
          </>
        }
      >
        {err && <ErrorBox title="Trajectory failed to load" error={err} />}
        <Replay
          traj={traj}
          loading={loading}
          compare={compare ? cmpTraj : null}
          mainLabel={`recorded · ${scenario.control.label} = ${trim(variant.value)} ${scenario.control.unit}`}
          compareLabel={fixedIdx !== null ? `recorded · fixed: ${trim(scenario.variants[fixedIdx].value)} ${scenario.control.unit}` : undefined}
          playToken={playToken}
        />
      </Panel>

      <FixCallout
        variant={variant}
        fixedValue={fixedIdx !== null ? scenario.variants[fixedIdx].value : undefined}
        control={scenario.control}
        fixedIdx={fixedIdx}
        onApply={applyFix}
        compare={compare}
        onCompare={setCompare}
      />

      {scenario.variants.length > 1 && (
        <Panel title="All recorded runs" kr="전체 변형">
          <VariantStrip control={scenario.control} variants={scenario.variants} active={vIdx} onPick={(i) => ctx.setVariant(i)} />
        </Panel>
      )}
    </div>
  )
}
