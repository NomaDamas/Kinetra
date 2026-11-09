import { useCallback, useMemo, useState } from 'react'
import type { DemoIndex } from '../bundle'
import { useDesign, useScenario } from '../lib/data'
import { componentCounts } from '../lib/design'
import { go, PROJECT_TABS, projectHref, type ProjectTab } from '../lib/router'
import { variantIndexFromQuery } from '../lib/summary'
import { ErrorBox, Loading, StatusBadge } from '../components/ui'
import { templateTitle, trim } from '../util'
import type { ProjectCtx } from './projectCtx'
import { OverviewTab } from './tabs/Overview'
import { AssumptionsTab } from './tabs/AssumptionsTab'
import { SimulateTab } from './tabs/Simulate'
import { DesignTab } from './tabs/Design'
import { ReportTab } from './tabs/Report'
import { EvidenceTab } from './tabs/Evidence'

const TAB_META: Record<ProjectTab, { label: string; hint: string }> = {
  overview: { label: 'Overview', hint: 'The answer first' },
  assumptions: { label: 'Assumptions', hint: 'Review gate' },
  simulate: { label: 'Simulate', hint: 'Recorded + live' },
  design: { label: 'Design', hint: 'Parts, CAD, loop' },
  report: { label: 'Report', hint: 'Brief + downloads' },
  evidence: { label: 'Evidence', hint: 'Run log, checks' },
}

interface Props {
  id: string
  tab: ProjectTab
  query: URLSearchParams
  engineUp: boolean
  index: DemoIndex | null
}

export function Project({ id, tab, query, engineUp, index }: Props) {
  const scn = useScenario(id)
  const design = useDesign(id)
  const [approved, setApprovedState] = useState<Record<string, boolean>>({})
  const [edits, setEdits] = useState<Record<string, number>>({})

  const vIdx = useMemo(() => (scn.status === 'ok' ? variantIndexFromQuery(scn.data.scenario, query) : 0), [scn, query])

  const hrefTo = useCallback((t: ProjectTab, extra?: Record<string, string | number | undefined>) => {
    const v = query.get('v') ?? undefined
    return projectHref(id, t, { v, ...extra })
  }, [id, query])

  const setVariant = useCallback<ProjectCtx['setVariant']>(
    (i, opts) => {
      if (scn.status !== 'ok') return
      const value = scn.data.scenario.variants[i].value
      const q: Record<string, string> = { v: String(value), ...(opts?.extra ?? {}) }
      if (!opts?.extra && query.get('mode')) q.mode = query.get('mode')!
      const target = projectHref(id, opts?.tab ?? tab, q)
      go(target, !opts?.tab)
    },
    [scn, id, tab, query],
  )

  if (scn.status === 'loading') return <Loading what={`project “${id}”`} />
  if (scn.status === 'error')
    return (
      <ErrorBox title="This project could not be loaded" error={scn.error}>
        <p className="small muted">Recorded projects live in <code>/demo/&lt;id&gt;/scenario.json</code>. <a href="#/projects">Back to projects</a></p>
      </ErrorBox>
    )

  const { scenario, local } = scn.data
  const variant = scenario.variants[vIdx]
  const ctx: ProjectCtx = {
    id,
    rec: scn.data,
    scenario,
    vIdx,
    variant,
    setVariant,
    design,
    query,
    engineUp,
    approved,
    setApproved: (k, v) => setApprovedState((a) => ({ ...a, [k]: v })),
    edits,
    setEdit: (k, v) =>
      setEdits((e) => {
        const n = { ...e }
        if (v === null) delete n[k]
        else n[k] = v
        return n
      }),
    hrefTo,
  }

  const counts = design.status === 'ok' ? componentCounts(design.data.brief) : null
  const nApproved = scenario.spec.assumptions.filter((a) => approved[a.key]).length

  const badge = (t: ProjectTab): string | null => {
    if (t === 'assumptions') return `${nApproved}/${scenario.spec.assumptions.length}`
    if (t === 'design') return design.status === 'ok' ? `${design.data.brief.components.length}` : design.status === 'error' ? '–' : '…'
    if (t === 'simulate') return String(scenario.variants.length)
    return null
  }

  return (
    <div className="project">
      <div className="project-head">
        <div className="crumbs small"><a href="#/projects">Projects</a> <span className="muted">/</span> <span>{scenario.title ?? id}</span></div>
        <div className="project-title-row">
          <div className="project-title">
            <h1 className="page-title">{scenario.title ?? id}</h1>
            <p className="page-sub">{scenario.idea}</p>
          </div>
          <div className="project-chips">
            <StatusBadge verdict={variant.verdict} big />
            <span className="pill muted-pill">{templateTitle(scenario.template)} · {(scenario.tier ?? scenario.spec.tier) === 1 ? 'tier 1 · verified' : 'tier 2 · experimental'}</span>
            <span className={`pill ${local ? 'warn' : 'recorded'}`} title={local ? 'Made on your local engine in this session; lost on reload.' : 'Seeded run stored in the demo bundle.'}>{local ? 'LOCAL RUN' : 'RECORDED'}</span>
          </div>
        </div>
        {scenario.variants.length > 1 && (
          <div className="small muted mono">
            viewing {scenario.control.label} = <b className="txt">{trim(variant.value)} {scenario.control.unit}</b> · {scenario.variants.length} recorded runs in this sweep
          </div>
        )}
      </div>

      <div className="workspace">
        <nav className="stepnav" aria-label="Project steps">
          {PROJECT_TABS.map((t, i) => (
            <a key={t} href={hrefTo(t)} className={`step-link ${t === tab ? 'on' : ''}`} aria-current={t === tab ? 'page' : undefined}>
              <span className="step-n mono">{i + 1}</span>
              <span className="step-t">
                <b>{TAB_META[t].label}</b>
                <small>{TAB_META[t].hint}</small>
              </span>
              {badge(t) && <span className="step-b mono">{badge(t)}</span>}
            </a>
          ))}
          {counts && counts.fail + counts.sourcing > 0 && (
            <div className="step-note small">{counts.fail + counts.sourcing} component(s) need attention in Design.</div>
          )}
        </nav>
        <div className="tabbody" key={tab}>
          {tab === 'overview' && <OverviewTab ctx={ctx} />}
          {tab === 'assumptions' && <AssumptionsTab ctx={ctx} />}
          {tab === 'simulate' && <SimulateTab ctx={ctx} index={index} />}
          {tab === 'design' && <DesignTab ctx={ctx} />}
          {tab === 'report' && <ReportTab ctx={ctx} />}
          {tab === 'evidence' && <EvidenceTab ctx={ctx} />}
        </div>
      </div>
    </div>
  )
}
