// Design-stage bundle (contract: docs/design-stage.md). Static JSON + CAD files; nothing here computes physics.
import { DEMO_BASE } from '../bundle'

export interface DRequirement {
  id: string
  label: string
  value: number
  unit: string
  derived_from: string
  margin_factor: number
  required: number
  source: string
}
export interface DMeet {
  requirement_id: string
  required: number
  provided: number
  unit: string
  margin: number
  ok: boolean
}
export interface DChoice {
  name: string
  vendor: string
  specs: Record<string, number | string>
  mass_kg: number | null
  unit_cost_usd: number | null
  source: string
  verified: boolean
}
export interface DAlt {
  name: string
  why_rejected: string
}
export interface DComponent {
  id: string
  role: string
  quantity: number
  /** null when no catalog entry meets every requirement (then custom or needs_sourcing is true). */
  choice: DChoice | null
  meets: DMeet[]
  /** choice present and every meets[] row ok. */
  ok: boolean
  alternatives: DAlt[]
  custom: boolean
  needs_sourcing: boolean
  mass_kg_each: number | null
  /** catalog | cad | estimate | simulation | none */
  mass_source: string
  note: string
  cad: { stl: string; step: string | null } | null
}
export interface DCheck {
  method: string
  stress_MPa: number | null
  allow_MPa: number | null
  ok: boolean
  label: string
}
export interface DCustomPart {
  id: string
  name: string
  params: Record<string, number | string>
  material: string
  mass_kg: number | null
  cad_stl: string | null
  cad_step: string | null
  quantity: number
  load_case: { force_N: number | null; safety_factor: number | null } | null
  check: DCheck | null
  extra_checks: DCheck[]
  note: string
}
export interface DLoopStep {
  iteration: number
  mass_kg: number
  status: string
  p_success: number
  ci: [number, number]
  n: number
  note: string
  n_evals: number | null
  wall_seconds: number | null
  assumption_overrides: Record<string, number>
}
export interface DAlternative {
  id: string
  label: string
  changes: Record<string, number | string>
  status: string
  p_success: number | null
  ci: [number, number] | null
  n: number | null
  mass_kg: number | null
  mass_added_kg: number | null
  cost_usd: number | null
  unpriced_lines: number | null
  recommended: boolean
  note: string
}
export interface DRisk {
  text: string
  severity: string
  physical_test: string
  tied_to: string
}
export interface DNextTest {
  name: string
  purpose: string
  cost: number | null
  source: string
}
export interface DesignBrief {
  schema_version: string
  scenario_id: string
  template: string
  base_variant: number | null
  headline: string
  requirements: DRequirement[]
  components: DComponent[]
  custom_parts: DCustomPart[]
  closed_loop: DLoopStep[]
  alternatives: DAlternative[]
  risks: DRisk[]
  next_tests: DNextTest[]
  totals: { mass_added_kg: number | null; mass_estimated_kg: number | null; cost_priced_usd: number | null; unpriced_lines: number }
  labels: string[]
  reproducibility: { seed: number | null; engine: string; mujoco: string; generated_at: string; budget: Record<string, number>; base_spec_hash: string }
}

export interface DesignBundle {
  brief: DesignBrief
  /** Absolute URL prefix (no trailing slash) of the folder holding design.json, cad/ and export/. */
  base: string
}

/* eslint-disable @typescript-eslint/no-explicit-any */
function arr<T>(x: unknown): T[] {
  return Array.isArray(x) ? (x as T[]) : []
}
function numOrNull(x: unknown): number | null {
  return typeof x === 'number' && Number.isFinite(x) ? x : null
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function normCheck(c: any): DCheck {
  return {
    method: String(c.method ?? ''),
    stress_MPa: numOrNull(c.stress_MPa),
    allow_MPa: numOrNull(c.allow_MPa),
    ok: !!c.ok,
    label: String(c.label ?? 'simplified model, needs FEA'),
  }
}

/** Tolerant normaliser: missing optional fields become empty values instead of crashing a panel. */
export function normalizeDesign(raw: any): DesignBrief {
  return {
    schema_version: String(raw.schema_version ?? ''),
    scenario_id: String(raw.scenario_id ?? ''),
    template: String(raw.template ?? ''),
    base_variant: numOrNull(raw.base_variant),
    headline: String(raw.headline ?? ''),
    requirements: arr<any>(raw.requirements).map((r) => ({
      id: String(r.id),
      label: String(r.label ?? r.id),
      value: Number(r.value),
      unit: String(r.unit ?? ''),
      derived_from: String(r.derived_from ?? ''),
      margin_factor: Number(r.margin_factor ?? 1),
      required: Number(r.required ?? r.value),
      source: String(r.source ?? ''),
    })),
    components: arr<any>(raw.components).map((c) => ({
      id: String(c.id),
      role: String(c.role ?? ''),
      quantity: Number(c.quantity ?? 1),
      choice: c.choice
        ? {
            name: String(c.choice.name ?? ''),
            vendor: String(c.choice.vendor ?? ''),
            specs: (c.choice.specs ?? {}) as Record<string, number | string>,
            mass_kg: numOrNull(c.choice.mass_kg),
            unit_cost_usd: numOrNull(c.choice.unit_cost_usd),
            source: String(c.choice.source ?? ''),
            verified: !!c.choice.verified,
          }
        : null,
      meets: arr<any>(c.meets).map((m) => ({
        requirement_id: String(m.requirement_id),
        required: Number(m.required),
        provided: Number(m.provided),
        unit: String(m.unit ?? ''),
        margin: Number(m.margin ?? 0),
        ok: !!m.ok,
      })),
      ok: !!c.ok,
      alternatives: arr<any>(c.alternatives).map((a) => ({ name: String(a.name ?? ''), why_rejected: String(a.why_rejected ?? '') })),
      custom: !!c.custom,
      needs_sourcing: !!c.needs_sourcing,
      mass_kg_each: numOrNull(c.mass_kg_each),
      mass_source: String(c.mass_source ?? 'none'),
      note: String(c.note ?? ''),
      cad: c.cad && typeof c.cad === 'object' && c.cad.stl ? { stl: String(c.cad.stl), step: c.cad.step ?? null } : null,
    })),
    custom_parts: arr<any>(raw.custom_parts).map((p) => ({
      id: String(p.id),
      name: String(p.name ?? p.id),
      params: (p.params ?? {}) as Record<string, number | string>,
      material: String(p.material ?? ''),
      mass_kg: numOrNull(p.mass_kg),
      cad_stl: p.cad_stl ?? null,
      cad_step: p.cad_step ?? null,
      quantity: Number(p.quantity ?? 1),
      load_case: p.load_case ? { force_N: numOrNull(p.load_case.force_N), safety_factor: numOrNull(p.load_case.safety_factor) } : null,
      check: p.check ? normCheck(p.check) : null,
      extra_checks: arr<any>(p.extra_checks).map(normCheck),
      note: String(p.note ?? ''),
    })),
    closed_loop: arr<any>(raw.closed_loop).map((s) => ({
      iteration: Number(s.iteration),
      mass_kg: Number(s.mass_kg),
      status: String(s.status ?? ''),
      p_success: Number(s.p_success ?? 0),
      ci: Array.isArray(s.ci) && s.ci.length === 2 ? [Number(s.ci[0]), Number(s.ci[1])] : [Number(s.p_success ?? 0), Number(s.p_success ?? 0)],
      n: Number(s.n ?? 0),
      note: String(s.note ?? ''),
      n_evals: numOrNull(s.n_evals),
      wall_seconds: numOrNull(s.wall_seconds),
      assumption_overrides: (s.assumption_overrides ?? {}) as Record<string, number>,
    })),
    alternatives: arr<any>(raw.alternatives).map((a) => ({
      id: String(a.id),
      label: String(a.label ?? a.id),
      changes: (a.changes ?? {}) as Record<string, number | string>,
      status: String(a.status ?? ''),
      p_success: numOrNull(a.p_success),
      ci: Array.isArray(a.ci) && a.ci.length === 2 ? [Number(a.ci[0]), Number(a.ci[1])] : null,
      n: numOrNull(a.n),
      mass_kg: numOrNull(a.mass_kg),
      mass_added_kg: numOrNull(a.mass_added_kg),
      cost_usd: numOrNull(a.cost_usd),
      unpriced_lines: numOrNull(a.unpriced_lines),
      recommended: !!a.recommended,
      note: String(a.note ?? ''),
    })),
    risks: arr<any>(raw.risks).map((r) => ({ text: String(r.text ?? ''), severity: String(r.severity ?? 'info'), physical_test: String(r.physical_test ?? ''), tied_to: String(r.tied_to ?? '') })),
    next_tests: arr<any>(raw.next_tests).map((t) => ({ name: String(t.name ?? ''), purpose: String(t.purpose ?? ''), cost: numOrNull(t.cost), source: String(t.source ?? '') })),
    totals: {
      mass_added_kg: numOrNull(raw.totals?.mass_added_kg),
      mass_estimated_kg: numOrNull(raw.totals?.mass_estimated_kg),
      cost_priced_usd: numOrNull(raw.totals?.cost_priced_usd),
      unpriced_lines: Number(raw.totals?.unpriced_lines ?? 0),
    },
    labels: arr<string>(raw.labels).map(String),
    reproducibility: {
      seed: numOrNull(raw.reproducibility?.seed),
      engine: String(raw.reproducibility?.engine ?? ''),
      mujoco: String(raw.reproducibility?.mujoco ?? ''),
      generated_at: String(raw.reproducibility?.generated_at ?? ''),
      budget: (raw.reproducibility?.budget ?? {}) as Record<string, number>,
      base_spec_hash: String(raw.reproducibility?.base_spec_hash ?? ''),
    },
  }
}

async function fetchJson(url: string): Promise<unknown> {
  const r = await fetch(url, { cache: 'no-cache' })
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  const text = await r.text()
  try {
    return JSON.parse(text)
  } catch {
    throw new Error('not JSON (file missing)')
  }
}

/** Loads <scenario>/design.json from the demo bundle; rejects with the reason when it is missing or not JSON. */
export async function loadDesign(scenarioId: string): Promise<DesignBundle> {
  const base = `${DEMO_BASE}/${scenarioId}`
  try {
    const raw = await fetchJson(`${base}/design.json`)
    return { brief: normalizeDesign(raw), base }
  } catch (e) {
    throw new Error(`${base}/design.json: ${(e as Error).message}`)
  }
}

export type ComponentState = 'ok' | 'fail' | 'custom' | 'sourcing'

/** ok = catalog part meeting every requirement; custom = a custom part is designed (CAD); sourcing = no catalog part and no design; fail = a chosen part misses a requirement. */
export function componentState(c: DComponent): ComponentState {
  if (c.custom) return 'custom'
  if (c.needs_sourcing || !c.choice) return 'sourcing'
  return c.ok ? 'ok' : 'fail'
}

export function componentCounts(brief: DesignBrief): Record<ComponentState, number> {
  const out: Record<ComponentState, number> = { ok: 0, fail: 0, custom: 0, sourcing: 0 }
  for (const c of brief.components) out[componentState(c)]++
  return out
}

export function assetUrl(d: DesignBundle, rel: string): string {
  return /^https?:|^\//.test(rel) ? rel : `${d.base}/${rel}`
}
