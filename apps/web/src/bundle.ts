// Demo bundle loading (contract: docs/demo-bundle.md). Static JSON only; nothing here computes physics.
import type { SpecSheet, Trajectory, Verdict } from './types'

export interface ScenarioMeta {
  id: string
  title: string
  idea: string
  template: string
  tagline: string
  tier: 1 | 2
  hero?: boolean
}

export interface AutoresearchPaths {
  attitude_ledger?: string
  calibration?: string
  integration?: string
  excitation?: string
}

export interface DemoIndex {
  scenarios: ScenarioMeta[]
  autoresearch?: AutoresearchPaths
}

export interface AgentStep {
  id: string
  label: string
  tool: string
  status: string
  wall_seconds: number
  summary: string
  detail?: unknown
}

export interface Control {
  key: string
  label: string
  unit: string
  values: number[]
  default_index: number
  hint: string
}

export interface Variant {
  value: number
  verdict: Verdict
  /** file name relative to the scenario folder, or an inline Trajectory (local engine API) */
  trajectory: string | Trajectory
  headline: string
}

export interface Scenario {
  id: string
  idea: string
  template: string
  title?: string
  tagline?: string
  tier?: 1 | 2
  hero?: boolean
  /** Bundle build info (seed, budget, hero_variant, labels, ...). Absent for local engine runs. */
  build?: {
    seed?: number
    budget?: Record<string, number>
    hero_variant?: number
    labels?: string[]
    note?: string
    [k: string]: unknown
  }
  agent_steps: AgentStep[]
  spec: SpecSheet
  control: Control
  variants: Variant[]
}

const useFixtures = typeof location !== 'undefined' && new URLSearchParams(location.search).has('fixtures')
export const IS_FIXTURE = useFixtures
/** Default path is /demo (written by engine bundle scripts). ?fixtures=1 loads dev fixtures (vite dev only). */
export const DEMO_BASE = useFixtures ? '/fixtures/demo' : '/demo'
export const ENGINE_API: string = import.meta.env.VITE_ENGINE_API ?? 'http://localhost:8000'
/** Live simulation WebSocket of the local engine (protocol: src/live/types.ts). */
export const ENGINE_WS = ENGINE_API.replace(/^http/, 'ws') + '/ws/sim'

async function getJsonMeta<T>(url: string): Promise<{ data: T; lastModified: string | null }> {
  const r = await fetch(url, { cache: 'no-cache' })
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`)
  const text = await r.text()
  try {
    return { data: JSON.parse(text) as T, lastModified: r.headers.get('last-modified') }
  } catch {
    throw new Error(`${url}: not JSON (bundle missing?)`)
  }
}
async function getJson<T>(url: string): Promise<T> {
  return (await getJsonMeta<T>(url)).data
}

export const loadIndex = () => getJson<DemoIndex>(`${DEMO_BASE}/index.json`)
export const loadScenario = (id: string) => getJson<Scenario>(`${DEMO_BASE}/${id}/scenario.json`)
/** Scenario plus the HTTP Last-Modified of its file (when the host sends it): "when this bundle was built". */
export const loadScenarioMeta = (id: string) => getJsonMeta<Scenario>(`${DEMO_BASE}/${id}/scenario.json`)

const trajCache = new Map<string, Promise<Trajectory>>()
export function loadTrajectory(scenarioId: string, v: Variant): Promise<Trajectory> {
  if (typeof v.trajectory !== 'string') return Promise.resolve(v.trajectory)
  const url = `${DEMO_BASE}/${scenarioId}/${v.trajectory}`
  let p = trajCache.get(url)
  if (!p) {
    p = getJson<Trajectory>(url)
    p.catch(() => trajCache.delete(url))
    trajCache.set(url, p)
  }
  return p
}

export function loadAux<T>(path: string | undefined): Promise<T | null> {
  if (!path) return Promise.resolve(null)
  return getJson<T>(`${DEMO_BASE}/${path}`).catch(() => null)
}

/** Probe the optional local engine API. Never blocks the demo. */
export async function engineReachable(): Promise<boolean> {
  try {
    const ctl = new AbortController()
    const to = setTimeout(() => ctl.abort(), 1500)
    const r = await fetch(`${ENGINE_API}/health`, { signal: ctl.signal })
    clearTimeout(to)
    return r.ok
  } catch {
    return false
  }
}

/** Shape of the local engine's POST /run answer (PipelineRun.to_dict + headline). */
interface EngineRun {
  idea: string
  template_id: string
  spec: Scenario['spec']
  verdict: Variant['verdict']
  trajectory: Trajectory
  agent_steps: AgentStep[]
  headline?: string
}

/** Runs the whole pipeline on the local engine and wraps the single result as a one-variant Scenario. */
export async function runEngine(idea: string, overrides?: Record<string, number>): Promise<Scenario> {
  const r = await fetch(`${ENGINE_API}/run`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ idea, overrides: overrides ?? {} }),
  })
  if (!r.ok) {
    let detail = ''
    try {
      detail = ((await r.json()) as { detail?: string }).detail ?? ''
    } catch {
      /* body was not JSON */
    }
    throw new Error(`engine /run: HTTP ${r.status}${detail ? ` (${detail})` : ''}`)
  }
  const d = (await r.json()) as EngineRun
  return {
    id: 'local',
    idea: d.idea,
    template: d.template_id,
    title: d.idea.length > 60 ? `${d.idea.slice(0, 57)}…` : d.idea,
    tagline: 'Run on your local engine; not a recorded bundle',
    agent_steps: d.agent_steps,
    spec: d.spec,
    control: { key: 'run', label: 'Local engine run', unit: '', values: [0], default_index: 0, hint: 'A single run on your local engine. There is no sweep for this idea.' },
    variants: [{ value: 0, verdict: d.verdict, trajectory: d.trajectory, headline: d.headline ?? d.verdict.summary }],
  }
}

export function matchScenario(idea: string, list: ScenarioMeta[]): ScenarioMeta | null {
  const q = idea.trim().toLowerCase()
  if (!q) return null
  for (const s of list) {
    if (s.id === q || s.title.toLowerCase() === q || s.idea.trim().toLowerCase() === q) return s
  }
  for (const s of list) {
    const i = s.idea.trim().toLowerCase()
    if (q.length > 12 && (i.includes(q) || q.includes(i))) return s
  }
  return null
}

export function fmt(x: number, digits = 3): string {
  if (!Number.isFinite(x)) return String(x)
  const a = Math.abs(x)
  if (a !== 0 && (a >= 1e5 || a < 1e-3)) return x.toExponential(2)
  return Number(x.toPrecision(digits)).toString()
}
