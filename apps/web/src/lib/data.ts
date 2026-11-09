// Data access for the app: one cached load per file, plus an in-memory store for runs made on the local engine.
import { useEffect, useState } from 'react'
import { loadAux, loadIndex, loadScenarioMeta, type DemoIndex, type Scenario, type ScenarioMeta } from '../bundle'
import { loadDesign, type DesignBundle } from './design'
import type { ArData, CalibFile, ExcitationFile, IntegrationFile, LedgerFile } from '../components/Autoresearch'

export type Async<T> = { status: 'loading' } | { status: 'ok'; data: T } | { status: 'error'; error: string }

/** Runs `factory` whenever `key` changes; stale answers are dropped. */
export function useAsync<T>(factory: () => Promise<T>, key: string): Async<T> {
  const [state, setState] = useState<{ key: string; value: Async<T> }>({ key, value: { status: 'loading' } })
  useEffect(() => {
    let live = true
    factory().then(
      (data) => live && setState({ key, value: { status: 'ok', data } }),
      (e: Error) => live && setState({ key, value: { status: 'error', error: e.message } }),
    )
    return () => {
      live = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])
  return state.key === key ? state.value : { status: 'loading' }
}

/* ---------------- index ---------------- */
let indexPromise: Promise<DemoIndex> | null = null
export function getIndex(): Promise<DemoIndex> {
  if (!indexPromise) {
    indexPromise = loadIndex()
    indexPromise.catch(() => (indexPromise = null))
  }
  return indexPromise
}
export const useIndex = () => useAsync(getIndex, 'index')

/* ---------------- scenarios ---------------- */
export interface ScenarioRec {
  scenario: Scenario
  /** HTTP Last-Modified of scenario.json: when this bundle was built (null when the host does not send it). */
  builtAt: string | null
  /** true for runs made on the local engine in this browser session. */
  local: boolean
}

const scenarioCache = new Map<string, Promise<ScenarioRec>>()
const localRuns = new Map<string, ScenarioRec>()
let localCounter = 0

/** Registers a run from the local engine; it lives only in memory (a page reload loses it). */
export function registerLocalRun(s: Scenario): string {
  const id = `local-${++localCounter}`
  localRuns.set(id, { scenario: { ...s, id }, builtAt: new Date().toUTCString(), local: true })
  return id
}
export const localRunIds = () => [...localRuns.keys()]
export const getLocalRun = (id: string) => localRuns.get(id) ?? null

export function getScenario(id: string): Promise<ScenarioRec> {
  if (id.startsWith('local-')) {
    const r = localRuns.get(id)
    return r ? Promise.resolve(r) : Promise.reject(new Error('This was a run on your local engine. It lived only in memory and is gone after a reload. Run the idea again.'))
  }
  let p = scenarioCache.get(id)
  if (!p) {
    p = loadScenarioMeta(id).then((r) => ({ scenario: r.data, builtAt: r.lastModified, local: false }))
    p.catch(() => scenarioCache.delete(id))
    scenarioCache.set(id, p)
  }
  return p
}
export const useScenario = (id: string) => useAsync(() => getScenario(id), `scn:${id}`)

/* ---------------- design ---------------- */
const designCache = new Map<string, Promise<DesignBundle>>()
export function getDesign(id: string): Promise<DesignBundle> {
  if (id.startsWith('local-')) return Promise.reject(new Error('The design stage is generated for recorded scenarios. Local engine runs have no design.json yet.'))
  let p = designCache.get(id)
  if (!p) {
    p = loadDesign(id)
    p.catch(() => designCache.delete(id))
    designCache.set(id, p)
  }
  return p
}
export const useDesign = (id: string) => useAsync(() => getDesign(id), `design:${id}`)

/* ---------------- dashboard ---------------- */
export interface ProjectRec {
  id: string
  meta: ScenarioMeta
  rec: ScenarioRec
  design: DesignBundle | null
}

/** All projects: every recorded scenario in the index plus this session's local runs. A scenario that fails to load is reported, not hidden. */
export async function loadProjects(index: DemoIndex): Promise<{ projects: ProjectRec[]; failed: { id: string; error: string }[] }> {
  const failed: { id: string; error: string }[] = []
  const projects: ProjectRec[] = []
  await Promise.all(
    index.scenarios.map(async (meta) => {
      try {
        const rec = await getScenario(meta.id)
        const design = await getDesign(meta.id).catch(() => null)
        projects.push({ id: meta.id, meta, rec, design })
      } catch (e) {
        failed.push({ id: meta.id, error: (e as Error).message })
      }
    }),
  )
  const order = new Map(index.scenarios.map((s, i) => [s.id, i]))
  projects.sort((a, b) => (order.get(a.id) ?? 0) - (order.get(b.id) ?? 0))
  for (const id of localRunIds()) {
    const rec = localRuns.get(id)!
    projects.push({
      id,
      meta: { id, title: rec.scenario.title ?? id, idea: rec.scenario.idea, template: rec.scenario.template, tagline: rec.scenario.tagline ?? '', tier: rec.scenario.spec.tier },
      rec,
      design: null,
    })
  }
  return { projects, failed }
}
export const useProjects = (index: DemoIndex | null, bump: number) =>
  useAsync(() => (index ? loadProjects(index) : new Promise<never>(() => {})), `projects:${index ? 'ready' : 'wait'}:${bump}`)

/* ---------------- autoresearch ---------------- */
function normalizeLedger(l: LedgerFile | null): LedgerFile | null {
  if (!l) return null
  if (Array.isArray(l)) return { entries: l as LedgerFile['entries'] }
  return l
}
let arPromise: Promise<ArData> | null = null
export function getAutoresearch(index: DemoIndex): Promise<ArData> {
  if (!arPromise) {
    const a = index.autoresearch ?? {}
    arPromise = Promise.all([
      loadAux<LedgerFile>(a.attitude_ledger),
      loadAux<CalibFile>(a.calibration),
      loadAux<IntegrationFile>(a.integration),
      loadAux<ExcitationFile>(a.excitation),
    ]).then(([ledger, calibration, integration, excitation]) => ({ ledger: normalizeLedger(ledger), calibration, integration, excitation }))
  }
  return arPromise
}
