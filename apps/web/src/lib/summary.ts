// Everything the dashboard/overview show is computed here from bundle data. No literal result numbers anywhere.
import type { Scenario, Variant } from '../bundle'
import type { Assumption } from '../types'
import { fmt } from '../bundle'
import { evalsOf, pct, trim } from '../util'
import { componentCounts, type DesignBrief } from './design'

export function heroIndex(s: Scenario): number {
  const hv = s.build?.hero_variant
  if (typeof hv === 'number') {
    const i = s.variants.findIndex((v) => Math.abs(v.value - hv) < 1e-9)
    if (i >= 0) return i
  }
  return Math.min(Math.max(s.control.default_index, 0), s.variants.length - 1)
}

export function variantIndexFromQuery(s: Scenario, q: URLSearchParams): number {
  const raw = q.get('v')
  if (raw === null) return heroIndex(s)
  const n = Number(raw)
  if (!Number.isFinite(n)) return heroIndex(s)
  let best = 0
  let bd = Infinity
  s.variants.forEach((v, i) => {
    const d = Math.abs(v.value - n)
    if (d < bd) {
      bd = d
      best = i
    }
  })
  return best
}

/** Index of the feasible variant a suggested fix points at (nearest feasible if the exact value was not replayed). */
export function fixedIndex(s: Scenario, variant: Variant): number | null {
  if (!variant.verdict.suggested_fix) return null
  const ch = variant.verdict.suggested_fix.changes.find((c) => c.param === s.control.key)
  const feas = s.variants.map((v, i) => [v, i] as const).filter(([v]) => v.verdict.status === 'FEASIBLE_FOUND')
  if (feas.length === 0) return null
  if (ch) {
    return feas.reduce((a, b) => (Math.abs(b[0].value - ch.to_value) < Math.abs(a[0].value - ch.to_value) ? b : a))[1]
  }
  return feas.reduce((a, b) => (Math.abs(b[0].value - variant.value) < Math.abs(a[0].value - variant.value) ? b : a))[1]
}

export function topSensitivity(v: Variant['verdict'], assumptions: Assumption[]): { key: string; label: string; effect: number } | null {
  const bc = v.binding_constraint
  if (!bc || bc.sensitivities.length === 0) return null
  const s = [...bc.sensitivities].sort((a, b) => a.rank - b.rank)[0]
  return { key: s.assumption_key, label: assumptions.find((a) => a.key === s.assumption_key)?.label ?? s.assumption_key, effect: s.effect }
}

export interface DesignSnapshot {
  massAddedKg: number | null
  ok: number
  fail: number
  custom: number
  sourcing: number
  total: number
  customParts: number
  unpriced: number
  /** Real re-runs with designed mass (row 0 is the recorded pre-design run). */
  loopReruns: number
  lastLoop: DesignBrief['closed_loop'][number] | null
}
export function designSnapshot(d: DesignBrief): DesignSnapshot {
  const c = componentCounts(d)
  return {
    massAddedKg: d.totals.mass_added_kg,
    ok: c.ok,
    fail: c.fail,
    custom: c.custom,
    sourcing: c.sourcing,
    total: d.components.length,
    customParts: d.custom_parts.length,
    unpriced: d.totals.unpriced_lines,
    loopReruns: d.closed_loop.filter(r => r.iteration > 0).length,
    lastLoop: d.closed_loop.length ? d.closed_loop[d.closed_loop.length - 1] : null,
  }
}

export interface NextAction {
  tone: 'ok' | 'bad' | 'weak' | 'info'
  title: string
  body: string
  /** hash route for the call to action */
  href?: string
  cta?: string
}

/** Recommended next action: rule-based on verdict status, fragility and the design brief. Wording only; every figure comes from data. */
export function nextAction(s: Scenario, variantIdx: number, design: DesignBrief | null, hrefs: { simulate: (v?: number, extra?: Record<string, string>) => string; design: string }): NextAction {
  const variant = s.variants[variantIdx]
  const v = variant.verdict
  const top = topSensitivity(v, s.spec.assumptions)
  const fix = v.suggested_fix
  const fi = fixedIndex(s, variant)
  switch (v.status) {
    case 'INFEASIBLE_NECESSARY_CONDITION': {
      const failed = v.necessary_checks.find((c) => !c.passed)
      return {
        tone: 'bad',
        title: 'Do not build this spec as stated',
        body:
          (failed ? `${failed.name} fails: measured ${fmt(failed.measured)} ${failed.unit} against a limit of ${fmt(failed.limit)} ${failed.unit}. ` : '') +
          (fix ? `Smallest verified change: ${fix.changes.map((c) => `${c.param} ${trim(c.from_value)} → ${trim(c.to_value)} ${c.unit}`).join(', ')}.` : 'No verified fix was produced; relax the failing requirement or change the concept.'),
        href: fi !== null ? hrefs.simulate(s.variants[fi].value, { cmp: '1', play: '1' }) : undefined,
        cta: fi !== null ? 'Replay the fixed configuration' : undefined,
      }
    }
    case 'NOT_FOUND_IN_BUDGET':
      return {
        tone: 'weak',
        title: 'Unproven, not impossible',
        body:
          `The search found nothing in ${evalsOf(v)?.toLocaleString('en-US') ?? 'its'} evaluations. That is weak evidence only. ` +
          (fix ? `The optimizer's verified alternative: ${fix.changes.map((c) => `${c.param} → ${trim(c.to_value)} ${c.unit}`).join(', ')}.` : 'Raise the search budget or change the structure before drawing a conclusion.'),
        href: fi !== null ? hrefs.simulate(s.variants[fi].value, { cmp: '1', play: '1' }) : undefined,
        cta: fi !== null ? 'Replay the fixed configuration' : undefined,
      }
    case 'FEASIBLE_FOUND': {
      const n = v.feasibility.n_samples
      const p = v.feasibility.p_success
      if (n > 0 && p < 0.5) {
        return {
          tone: 'weak',
          title: 'Feasible, but fragile: reduce uncertainty before building',
          body:
            `A working design exists, yet it succeeds in only ${pct(p)} of Monte-Carlo draws (95% CI ${pct(v.feasibility.ci_low)} to ${pct(v.feasibility.ci_high)}). ` +
            (top ? `The assumption that moves the result most is "${top.label}": pin it down first. ` : '') +
            (design?.next_tests[0] ? `First physical test: ${design.next_tests[0].name}.` : ''),
          href: design ? hrefs.design : undefined,
          cta: design ? 'Open the design' : undefined,
        }
      }
      return {
        tone: 'ok',
        title: 'Build the design, then run the first physical test',
        body: design?.next_tests[0] ? `${design.next_tests[0].name}: ${design.next_tests[0].purpose}` : 'The design stage has not produced a test list for this project yet.',
        href: hrefs.design,
        cta: 'Open the design',
      }
    }
    default:
      return { tone: 'info', title: 'No verdict: fix the model first', body: 'The simulation model failed its own sanity checks, so nothing here can be trusted.' }
  }
}

export function lastRunLabel(builtAt: string | null, designAt: string | null): string {
  const raw = designAt && !Number.isNaN(Date.parse(designAt)) ? designAt : builtAt
  if (!raw) return 'unknown'
  const t = Date.parse(raw)
  if (Number.isNaN(t)) return 'unknown'
  return new Date(t).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' })
}
