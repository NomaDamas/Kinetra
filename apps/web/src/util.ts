import type { Assumption, Verdict, VerdictStatus } from './types'

export interface StatusMeta {
  tone: 'ok' | 'bad' | 'weak' | 'invalid'
  title: string
  kr: string
  strength: string
  explain: string
}

export function evalsOf(v: Verdict): number | null {
  const sb = v.reproducibility.search_budget
  const fromCost = v.cost_estimate?.sim_cost.n_evals
  if (fromCost) return fromCost
  for (const k of Object.keys(sb)) if (k.includes('eval')) return sb[k]
  return null
}

export function statusMeta(v: Verdict): StatusMeta {
  const n = evalsOf(v)
  const s: VerdictStatus = v.status
  switch (s) {
    case 'FEASIBLE_FOUND':
      return {
        tone: 'ok',
        title: 'FEASIBLE: FOUND',
        kr: '가능: 해를 찾음',
        strength: 'EXISTENCE: STRONG',
        explain: 'A concrete witness (parameter set) was found and re-simulated under Monte-Carlo within the stated assumptions.',
      }
    case 'INFEASIBLE_NECESSARY_CONDITION':
      return {
        tone: 'bad',
        title: 'PROVEN IMPOSSIBLE UNDER ASSUMPTIONS',
        kr: '가정 하에서 불가능 증명',
        strength: 'IMPOSSIBILITY: STRONG',
        explain: 'A necessary condition is violated. No search was needed: the idea fails a physical bound given the assumptions below.',
      }
    case 'NOT_FOUND_IN_BUDGET':
      return {
        tone: 'weak',
        title: `WEAK: NOT FOUND IN ${n !== null ? n.toLocaleString('en-US') : 'N'} EVALS`,
        kr: '예산 내 미발견: 증명 아님',
        strength: 'WEAK EVIDENCE ONLY',
        explain: 'The optimizer did not find a solution within its budget. This is NOT proof of impossibility: a better search, more budget or a different structure may still succeed.',
      }
    default:
      return {
        tone: 'invalid',
        title: 'MODEL INVALID',
        kr: '모델 검증 실패',
        strength: 'NO VERDICT',
        explain: 'The simulation model failed its own sanity checks; no feasibility statement is made.',
      }
  }
}

export function isFeasible(v: Verdict) {
  return v.status === 'FEASIBLE_FOUND'
}

export function describeDist(a: Assumption): string {
  const d = a.distribution
  if (d.kind === 'fixed') return 'fixed'
  if (d.kind === 'uniform') return `U[${trim(d.low)}, ${trim(d.high)}]`
  const clip = d.clip_low !== null || d.clip_high !== null ? ` clip[${d.clip_low ?? '−∞'}, ${d.clip_high ?? '∞'}]` : ''
  return `N(${trim(d.mean)}, σ=${trim(d.std)})${clip}`
}

export function trim(x: number): string {
  if (!Number.isFinite(x)) return String(x)
  const a = Math.abs(x)
  if (a !== 0 && (a >= 1e6 || a < 1e-3)) return x.toExponential(2)
  return Number(x.toPrecision(4)).toString()
}

export function isUrl(s: string) {
  return /^https?:\/\//i.test(s)
}

export function sourceTone(s: string): 'url' | 'llm' | 'user' | 'other' {
  if (isUrl(s)) return 'url'
  if (s.includes('llm_estimate')) return 'llm'
  if (s === 'user') return 'user'
  return 'other'
}
